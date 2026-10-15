"""Dispatchern bakom `make test|lint|run|check|fmt` (D5:5, D8:1, D11:11).

Modulernas grindar nås via adaptrar: `.claude/pb-gates/<modul>/<mål>`, körbara filer med
villkorligt filnamn (förslag i D12). Dispatchern kör dem per enhet i `.claude/units.yml`:

    <adapter> <enhetens sökväg> [filer...]      # filer bara för `fmt`, relativt repots rot

Adaptern skriver fel som `fil:rad meddelande` och svarar med exitkod 0 (godkänt), 1 (fel)
eller 2 (kunde inte köras), enligt utdatakontraktet (D5:32)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import EXIT_FAIL, EXIT_OK, EXIT_UNKNOWN, LOG_REL, MAX_SHOWN, CannotRun, git
from . import baseline, structure
from .units import load_units

TARGETS = ("test", "lint", "run", "check", "fmt")
OPTIONAL_TARGETS = ("run",)


def changed_files(root):
    """Filer som ändrats mot main (D11:11): committade, ocommittade och nya."""
    base = next((b for b in ("origin/main", "main")
                 if git(root, "rev-parse", "--verify", "-q", b, check=False).returncode == 0), None)
    if base is None:
        raise CannotRun("no main branch to compare against; pass files explicitly")
    mb = git(root, "merge-base", base, "HEAD").strip()
    names = git(root, "diff", "--name-only", "--diff-filter=d", "-z", mb).split("\0")
    names += git(root, "ls-files", "-o", "--exclude-standard", "-z").split("\0")
    return sorted({n for n in names if n and (Path(root) / n).is_file()})


class Result:
    def __init__(self):
        self.green, self.errors, self.unknown = [], [], []

    def code(self):
        return EXIT_FAIL if self.errors else EXIT_UNKNOWN if self.unknown else EXIT_OK


def _run_adapter(root, res, log, target, unit, args):
    module, path = unit["module"], unit["path"]
    label = "%s %s:%s" % (target, module, path)
    adapter = Path(root) / ".claude" / "pb-gates" / module / target
    if not adapter.is_file():
        if target in OPTIONAL_TARGETS:
            res.green.append("ok %s (no %s adapter)" % (label, target))
        else:
            res.unknown.append("cannot run %s: module '%s' has no %s adapter" % (label, module, target))
        return
    with tempfile.TemporaryDirectory() as tmp:
        records = Path(tmp) / "records.jsonl"
        env = dict(os.environ, PB_RECORDS=str(records)) if target == "lint" else None
        p = subprocess.run([str(adapter), path, *args], cwd=str(root), capture_output=True, text=True, env=env)
        out = (p.stdout + p.stderr).strip()
        log.write("== %s (exit %d)\n%s\n" % (label, p.returncode, out))
        lines = [ln for ln in out.splitlines() if ln.strip()]
        filtered = baseline.apply(root, module, path, lines, records, p.returncode) if target == "lint" and p.returncode in (0, 1) else None
    if filtered is not None:
        if lines != filtered:
            log.write("== %s after baseline\n%s\n" % (label, "\n".join(filtered) or "(nothing left)"))
        if filtered:
            res.errors += filtered
        else:
            res.green.append("ok %s (known errors are in the baseline)" % label if p.returncode else "ok %s" % label)
    elif p.returncode == 0:
        res.green.append("ok %s" % label)
    elif p.returncode == 1:
        res.errors += lines or ["%s failed without output" % label]
    else:
        res.unknown.append("cannot run %s: %s" % (label, out.splitlines()[0] if out else "exit %d" % p.returncode))


def _run_core(root, res, log):
    for name, fn in (("roots", structure.check_roots), ("units", structure.check_units),
                     ("gitignore", structure.check_gitignore), ("manifest", structure.check_manifest)):
        try:
            rep = fn(root)
        except CannotRun as e:
            res.unknown.append("cannot run %s: %s" % (name, e))
            continue
        log.write("== %s\n%s\n" % (name, "\n".join(rep.errors) or "ok"))
        if rep.errors:
            res.errors += rep.errors
        else:
            res.green.append("ok %s" % name)


def _run_secret_scan(root, res, log):
    script = Path(__file__).resolve().parent.parent / "pb-secret-scan"
    p = subprocess.run([sys.executable, str(script), "--root", str(root)], capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    log.write("== secret-scan (exit %d)\n%s\n" % (p.returncode, out))
    if p.returncode == 0:
        res.green.append("ok secret-scan")
    elif p.returncode == 1:
        res.errors += [ln for ln in out.splitlines() if ln.strip()]
    else:
        res.unknown.append("cannot run secret-scan: %s" % (out.splitlines()[0] if out else "exit %d" % p.returncode))


def run_gate(root, target, files=None, out=print):
    if target not in TARGETS:
        raise CannotRun("unknown target %r (use %s)" % (target, ", ".join(TARGETS)))
    res = Result()
    logf = Path(root) / LOG_REL
    logf.parent.mkdir(parents=True, exist_ok=True)
    with open(logf, "w", encoding="utf-8") as log:
        try:
            units = load_units(root)
            if target == "fmt" and files is None:
                files = changed_files(root)
        except CannotRun as e:
            res.unknown.append("cannot run %s: %s" % (target, e))
            units = []
        steps = {"check": ("core", "lint", "test", "secret"), "test": ("test",), "lint": ("lint",),
                 "run": ("run",), "fmt": ("fmt",)}[target]
        if not res.unknown:
            for step in steps:
                if step == "core":
                    _run_core(root, res, log)
                elif step == "secret":
                    _run_secret_scan(root, res, log)
                elif step == "fmt":
                    for u in units:
                        prefix = u["path"].rstrip("/") + "/"
                        mine = [f for f in files if u["path"] in (".", "") or f.startswith(prefix)]
                        if not mine:
                            res.green.append("ok fmt %s:%s (no changed files)" % (u["module"], u["path"]))
                        else:
                            _run_adapter(root, res, log, "fmt", u, mine)
                else:
                    for u in units:
                        _run_adapter(root, res, log, step, u, [])
            if not units and target != "check":
                res.green.append("ok %s (no code units)" % target)
        log.write("\n".join(res.errors + res.unknown) + "\n" if res.errors or res.unknown else "")
    code = res.code()
    if code == EXIT_OK:
        for line in res.green:
            out(line)
    else:
        for line in res.errors[:MAX_SHOWN]:
            out(line)
        for line in res.unknown:
            out(line)
        out("%s: %d error(s), %d could not run; full log: %s" % (target, len(res.errors), len(res.unknown), LOG_REL))
    return code
