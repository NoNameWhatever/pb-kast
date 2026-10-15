"""Baslinjewrappern (D8:25, D8:5, D5:25): gör att ett adopterat projekt kan börja med sina befintliga lint- och typfel
utan att nya fel kan gömma sig.

Modulens lint-adapter skriver, när miljövariabeln PB_RECORDS är satt, en post per fynd som får baslinjas
(`{"text", "file", "line", "rule"}`) och sist `{"complete": true}`. Wrappern läser `project-docs/baseline/<modul>.jsonl`:
en JSON-rad per befintligt fel med fil, regel och innehållet på felraden (blanktecken hopdragna, inget radnummer).
Fynd som finns i baslinjen släpps igenom (krav 1, 4). En post som inte längre har något fynd är rött tills den tas bort
(krav 3). Att en PR inte lägger till poster kontrolleras av `pb-check baseline` (krav 2, `pr.check_baseline`)."""
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .common import CannotRun

BASELINE_DIR = "project-docs/baseline"


def baseline_rel(module):
    return "%s/%s.jsonl" % (BASELINE_DIR, module)


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def entry_key(root, rec):
    """(fil, regel, innehåll). Innehållet är felradens text i arbetsträdet; en post utan rad (format) har tomt innehåll."""
    content = ""
    line = rec.get("line") or 0
    f = Path(root) / rec["file"]
    if line > 0 and f.is_file():
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        if line <= len(lines):
            content = normalize(lines[line - 1])
    return (rec["file"], rec["rule"], content)


def parse_baseline(text, where=BASELINE_DIR):
    """Ger (Counter av nycklar, felmeddelanden för trasiga rader)."""
    keys, bad = Counter(), []
    for n, raw in enumerate((text or "").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
            keys[(d["file"], d["rule"], d["content"])] += 1
        except (ValueError, KeyError, TypeError):
            bad.append("%s:%d: not a baseline entry (expected {\"file\", \"rule\", \"content\"})" % (where, n))
    return keys, bad


def read_records(path):
    """Ger (poster, klar) ur adapterns PB_RECORDS-fil."""
    recs, complete = [], False
    p = Path(path)
    if p.is_file():
        for raw in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if d.get("complete"):
                complete = True
            elif "file" in d and "rule" in d and "text" in d:
                recs.append(d)
    return recs, complete


def in_unit(file, unit):
    return unit in (".", "") or file == unit or file.startswith(unit.rstrip("/") + "/")


def apply(root, module, unit, out_lines, records_path, exit_code):
    """Filtrerar adapterns fel mot modulens baslinje. Ger (kvarvarande fellinjer, färskt exitläge) eller None när
    modulen saknar baslinje. Utan baslinjefil ändras ingenting: alla fynd är röda (krav 1)."""
    f = Path(root) / baseline_rel(module)
    if not f.is_file():
        return None
    keys, bad = parse_baseline(f.read_text(encoding="utf-8"), baseline_rel(module))
    recs, complete = read_records(records_path)
    remaining_keys = Counter(keys)
    skip = Counter()
    for rec in recs:
        k = entry_key(root, rec)
        if remaining_keys[k] > 0:
            remaining_keys[k] -= 1
            skip[rec["text"]] += 1
    lines = []
    for ln in out_lines:
        if skip[ln] > 0:
            skip[ln] -= 1
        else:
            lines.append(ln)
    errors = list(bad)
    if complete and exit_code in (0, 1):
        for (file, rule, content), n in sorted(remaining_keys.items()):
            if n > 0 and in_unit(file, unit):
                errors.append("%s: stale entry for %s (%s%s) x%d; the error is gone, remove the line (D8:5)"
                              % (baseline_rel(module), file, rule, ", " + content[:40] if content else "", n))
    return lines + errors


def collect(root, module, unit):
    """Kör modulens lint-adapter för enheten och ger dess baslinjebara fynd som poster med nyckel."""
    adapter = Path(root) / ".claude" / "pb-gates" / module / "lint"
    if not adapter.is_file():
        raise CannotRun("module '%s' has no lint adapter" % module)
    with tempfile.TemporaryDirectory() as tmp:
        rec = Path(tmp) / "records.jsonl"
        env = dict(os.environ, PB_RECORDS=str(rec))
        p = subprocess.run([str(adapter), unit], cwd=str(root), capture_output=True, text=True, env=env)
        if p.returncode == 2:
            raise CannotRun("lint could not run for %s:%s: %s" % (module, unit, (p.stdout + p.stderr).strip().splitlines()[0] if (p.stdout + p.stderr).strip() else "exit 2"))
        recs, complete = read_records(rec)
    if not complete:
        others = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
        raise CannotRun("lint stopped before all tools ran for %s:%s; fix these first (they cannot be baselined): %s"
                        % (module, unit, "; ".join(others[:3])))
    keys = Counter(entry_key(root, r) for r in recs)
    unbaselinable = len([ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]) - len(recs)
    return keys, unbaselinable


def dump(keys):
    return "".join(json.dumps({"file": f, "rule": r, "content": c}, ensure_ascii=False) + "\n"
                   for (f, r, c), n in sorted(keys.items()) for _ in range(n))


def create(root, modules_units, force=False):
    """`pb-baseline create`: skriver `project-docs/baseline/<modul>.jsonl` ur nuvarande fynd (bara vid adoption, D7:19)."""
    per_module = {}
    for module, unit in modules_units:
        keys, unbaselinable = collect(root, module, unit)
        if unbaselinable > 0:
            raise CannotRun("%s:%s has %d error(s) that cannot be baselined (configuration or floor violations); fix them first"
                            % (module, unit, unbaselinable))
        per_module.setdefault(module, Counter()).update(keys)
    written = []
    for module, keys in per_module.items():
        f = Path(root) / baseline_rel(module)
        if f.exists() and not force:
            raise CannotRun("%s exists; a baseline is only created at adoption (use --force to rewrite it)" % baseline_rel(module))
        if keys:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(dump(keys), encoding="utf-8")
            written.append((baseline_rel(module), sum(keys.values())))
    return written


def prune(root, modules_units):
    """`pb-baseline prune`: tar bort poster utan fynd. En baslinje får bara krympa."""
    result = []
    for module in sorted({m for m, _ in modules_units}):
        f = Path(root) / baseline_rel(module)
        if not f.is_file():
            continue
        current = Counter()
        for m, unit in modules_units:
            if m == module:
                current.update(collect(root, m, unit)[0])
        old, bad = parse_baseline(f.read_text(encoding="utf-8"))
        if bad:
            raise CannotRun("; ".join(bad[:2]))
        kept = Counter({k: min(n, current[k]) for k, n in old.items() if min(n, current[k]) > 0})
        removed = sum(old.values()) - sum(kept.values())
        if removed:
            if kept:
                f.write_text(dump(kept), encoding="utf-8")
            else:
                f.unlink()
        result.append((baseline_rel(module), removed))
    return result
