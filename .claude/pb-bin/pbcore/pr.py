"""Kontroller som läser en PR: nivåjämförelse (D5:23), formatcheck (D5:17, 26, D11:14, 16, 18)
och testcheck (D11:12). En PR är diffen mellan `base` och `head` plus PR-kroppen."""
import re
from datetime import date
from pathlib import Path

import yaml

from . import baseline as bl
from .common import (LEVELS, CannotRun, GitRef, Report, changed_paths, git, glob_regex,
                     load_path_map, parse_front_matter, sections)

ISSUE_RE = re.compile(r"^project-docs/issues/(?:done/)?(\d+)-[^/]+\.md$")
PLAN_DIR = "project-docs/issues/"
TYPES = ("hygiene", "bug", "security")
ROWS = ("Docs:", "Deviations:", "Tests:", "Review:")
FAIL_DETECTED = ("user", "reviewer", "ci", "production")
FAIL_CAUSE = ("broken-instruction", "missing-instruction", "missing-check", "other")
FAIL_OWNER = ("template", "project")
FAIL_ACTION = ("none", "common-mistakes", "rule", "hook", "check", "test", "template-issue")
BASE_HEADINGS = ("Goal", "Acceptance criteria", "Out of scope", "Criteria changes")
MAX_COMMON_MISTAKES = 10


def read_body(body_file):
    if not body_file:
        raise CannotRun("no PR body given (--pr-body-file)")
    p = Path(body_file)
    if not p.is_file():
        raise CannotRun("PR body file not found: %s" % body_file)
    return p.read_text(encoding="utf-8")


def links(body):
    closes = {int(n) for n in re.findall(r"(?i)\bcloses\s+#(\d+)", body)}
    refs = {int(n) for n in re.findall(r"(?i)\brefs\s+#(\d+)", body)}
    return closes, refs


def issue_files(changes):
    return [p for st, p, _ in changes if st != "D" and ISSUE_RE.match(p)]


def is_plan_pr(changes):
    """Diffen rör bara issue-filer som ännu inte är klara (D3:6)."""
    return bool(changes) and all(
        (p.startswith(PLAN_DIR) and not p.startswith(PLAN_DIR + "done/")) and (o is None or o.startswith(PLAN_DIR))
        for _, p, o in changes)


def row_value(body, label, labels=ROWS + ("Regression test:",)):
    """Texten efter en rad som börjar med `label`, eller på raderna under tills nästa rad eller rubrik."""
    lines = body.splitlines()
    rx = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?%s(?:\*\*)?\s*(.*)$" % re.escape(label))
    for i, line in enumerate(lines):
        m = rx.match(line)
        if not m:
            continue
        parts = [m.group(1).strip()]
        for nxt in lines[i + 1:]:
            if not nxt.strip() and any(parts):
                break
            if re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:%s|Closes\b|Refs\b)" % "|".join(re.escape(x) for x in labels), nxt) \
                    or nxt.startswith("#"):
                break
            parts.append(nxt.strip())
        return " ".join(x for x in parts if x).strip()
    return None


def _head_issue(root, head, path):
    text = GitRef(root, head).read(path)
    return parse_front_matter(text) if text is not None else (None, "", 1)


# --- Nivåjämförelse -----------------------------------------------------------------------------

def check_level(root, base, head, body_file=None):
    rep = Report("level")
    # Issue-filen hittas via diffen (en per PR, D2:10); länken i PR-kroppen kontrolleras av formatchecken.
    changes = changed_paths(root, base, head)
    pm_base, pm_head = load_path_map(GitRef(root, base)), load_path_map(GitRef(root, head))

    def level(path):
        a, b = pm_base.level(path), pm_head.level(path)
        return a if LEVELS[a] >= LEVELS[b] else b

    strict_paths = []
    for _, p, o in changes:
        if any(level(x) == "strict" for x in (p, o) if x):
            strict_paths.append(p)
    computed = "strict" if strict_paths else "standard"

    files = issue_files(changes)
    if len(files) != 1:
        rep.error("project-docs/issues/", "expected exactly one issue file changed in the PR, found %d" % len(files))
        return rep
    fm, _, _ = _head_issue(root, head, files[0])
    if not fm or fm.get("level") not in LEVELS:
        rep.error(files[0], "front matter has no valid level: (standard or strict)")
        return rep
    planned = fm["level"]
    if computed == "strict" and planned != "strict":
        shown = ", ".join(strict_paths[:3]) + (" ..." if len(strict_paths) > 3 else "")
        rep.error(files[0], "computed level is strict (%s) but the issue file plans level: %s" % (shown, planned))
    if fm.get("type") == "hygiene" and computed == "strict":
        rep.error(files[0], "a hygiene package must stay standard (D3:10) but touches strict paths: %s" % ", ".join(strict_paths[:3]))
    if planned == "strict" and not is_plan_pr(changes):
        old = next((o for _, p, o in changes if p == files[0] and o), None)
        main_path = old or (PLAN_DIR + files[0].rsplit("/", 1)[1])
        main_fm, _, _ = parse_front_matter(GitRef(root, base).read(main_path))
        if not main_fm or main_fm.get("level") != "strict":
            rep.error(files[0], "planned level is strict but the approved plan (level: strict) is not in %s on %s" % (main_path, base))
    return rep


# --- Formatcheck ---------------------------------------------------------------------------------

def _nonempty_section(rep, path, secs, name, why=""):
    if name not in secs:
        rep.error(path, "missing heading '%s'%s" % (name, why))
    elif not secs[name].strip():
        rep.error(path, "heading '%s' is empty" % name)


def _check_failure_post(rep, root, head, path):
    fm, _, _ = _head_issue(root, head, path)
    if fm is None:
        rep.error(path, "failure post has no front matter")
        return
    d = fm.get("date")
    if not isinstance(d, date) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)):
        rep.error(path, "date must be YYYY-MM-DD")
    for key, allowed in (("detected", FAIL_DETECTED), ("cause", FAIL_CAUSE), ("owner", FAIL_OWNER), ("action", FAIL_ACTION)):
        if fm.get(key) not in allowed:
            rep.error(path, "%s must be one of: %s" % (key, ", ".join(allowed)))
    if fm.get("cause") == "broken-instruction" and not fm.get("breaks"):
        rep.error(path, "breaks: (path of the rule file) is required when cause is broken-instruction")
    if not fm.get("pr") and not fm.get("issue"):
        rep.error(path, "pr: or issue: is required")


def _test_file_globs(root, head):
    src = GitRef(root, head)
    globs = []
    for name in src.listdir(".claude/pb-test-guard"):
        if name.endswith(".yml"):
            data = yaml.safe_load(src.read(".claude/pb-test-guard/" + name)) or {}
            globs += [glob_regex(g) for g in data.get("test_files", [])]
    return globs


def check_format(root, base, head, body_file):
    rep = Report("format")
    body = read_body(body_file)
    changes = changed_paths(root, base, head)
    closes, refs = links(body)
    plan_pr = is_plan_pr(changes)

    files = issue_files(changes)
    if len(files) != 1:
        rep.error("project-docs/issues/", "expected exactly one issue file changed in the PR (D2:10), found %d" % len(files))
        return rep
    path = files[0]
    fm, ibody, _ = _head_issue(root, head, path)
    if fm is None:
        rep.error(path, "issue file has no valid front matter")
        return rep
    secs = sections(ibody)

    n = fm.get("issue")
    if not isinstance(n, int) or isinstance(n, bool):
        rep.error(path, "front matter issue: must be the GitHub issue number")
    else:
        m = int(ISSUE_RE.match(path).group(1))
        if n != m:
            rep.error(path, "issue: %s does not match the file name number %d" % (n, m))
        if n in closes:
            pass
        elif plan_pr and n in refs:
            pass  # plan-PR: issuen ska stanna öppen tills kod-PR:en (förslag, D12 Öppet)
        else:
            rep.error(path, "PR body has no 'Closes #%d' matching issue: %d%s" % (n, n, " ('Refs #%d' is allowed only in a plan PR)" % n if plan_pr else ""))

    level, typ = fm.get("level"), fm.get("type")
    if level not in LEVELS:
        rep.error(path, "level: must be standard or strict")
    if typ is not None and typ not in TYPES:
        rep.error(path, "type: must be one of %s when present" % ", ".join(TYPES))
    for h in BASE_HEADINGS:
        if h not in secs:
            rep.error(path, "missing heading '%s'" % h)
    if typ not in ("hygiene", "security"):
        _nonempty_section(rep, path, secs, "Test plan")
    if level == "strict":
        for h in ("Plan", "Risk"):
            if h not in secs:
                rep.error(path, "missing heading '%s' (strict)" % h)
        _nonempty_section(rep, path, secs, "Security", " (strict)")
        if not isinstance(fm.get("destructive"), bool):
            rep.error(path, "destructive: true|false is required at level: strict (D9:7)")
    if fm.get("destructive") is True:
        _nonempty_section(rep, path, secs, "Backup and restore", " (destructive: true, D6:39)")
    if typ == "security":
        sha = str(fm.get("reviewed-sha") or "")
        ok = bool(re.fullmatch(r"[0-9a-f]{7,40}", sha)) and git(
            root, "merge-base", "--is-ancestor", sha, base, check=False).returncode == 0
        if not ok:
            rep.error(path, "reviewed-sha must be a commit on %s" % base)
        for h in ("Findings", "Coverage"):
            _nonempty_section(rep, path, secs, h, " (type: security)")

    for label in ROWS:
        v = row_value(body, label)
        if v is None:
            rep.error("PR body", "missing row '%s'" % label)
        elif not v:
            rep.error("PR body", "row '%s' is empty" % label)

    if typ == "bug":
        v = row_value(body, "Regression test:")
        if v is None:
            rep.error("PR body", "missing row 'Regression test:' (type: bug)")
        elif not re.match(r"^none\s+[–-]\s+\S", v):
            m = re.match(r"^(\S+?)::\S+\s+[–-]\s+fell on base:\s*\S", v)
            if not m:
                rep.error("PR body", "'Regression test:' must be '<file>::<test> – fell on base: <output>' or 'none – <reason>'")
            else:
                f = m.group(1)
                if not any(p == f and st != "D" for st, p, _ in changes):
                    rep.error("PR body", "regression test file '%s' is not changed in the PR" % f)
                globs = _test_file_globs(root, head)
                if globs and not any(g.match(f) for g in globs):
                    rep.error("PR body", "'%s' does not match a test file pattern in .claude/pb-test-guard/" % f)
        if not any(st == "A" and p.startswith("project-docs/failures/") and p.endswith(".md") for st, p, _ in changes):
            rep.error("project-docs/failures/", "type: bug requires a new failure post in the PR (D11:14)")

    for st, p, _ in changes:
        if st != "D" and p.startswith("project-docs/failures/") and p.endswith(".md"):
            _check_failure_post(rep, root, head, p)

    claude = GitRef(root, head).read("CLAUDE.md")
    if claude is not None:
        common = sections(claude).get("Vanliga misstag", "")
        items = [ln for ln in common.splitlines() if ln.lstrip().startswith("- ")]
        if len(items) > MAX_COMMON_MISTAKES:
            rep.error("CLAUDE.md", "'Vanliga misstag' has %d lines; the limit is %d (D11:7)" % (len(items), MAX_COMMON_MISTAKES))
        tree = set(GitRef(root, head).ls_files())
        for ln in items:
            refs_ = re.findall(r"project-docs/failures/[\w./-]+\.md", ln)
            if not refs_ or any(r not in tree for r in refs_):
                rep.error("CLAUDE.md", "each 'Vanliga misstag' line must reference an existing failure post: %s" % ln.strip()[:60])
    return rep


# --- Testcheck ----------------------------------------------------------------------------------------

def check_test_guard(root, base, head, body_file):
    rep = Report("test-guard")
    body = read_body(body_file)
    src = GitRef(root, head)
    rules = []
    for name in src.listdir(".claude/pb-test-guard"):
        if name.endswith(".yml"):
            data = yaml.safe_load(src.read(".claude/pb-test-guard/" + name)) or {}
            rules.append(([glob_regex(g) for g in data.get("test_files", [])],
                          [re.compile(m) for m in data.get("skip_markers", [])]))
    if not rules:
        return rep  # ingen modul med testmönster än: inget att kontrollera
    tests_text = row_value(body, "Tests:") or ""
    changes = changed_paths(root, base, head)
    mb = git(root, "merge-base", base, head).strip()

    def is_test(path):
        return any(g.match(path) for globs, _ in rules for g in globs)

    def declared(path):
        return path in tests_text

    for st, p, old in changes:
        if st == "D" and is_test(p) and not declared(p):
            rep.error(p, "test file deleted; list its path under Tests: in the PR body")
        elif st == "R" and old and is_test(old) and not is_test(p) and not declared(old):
            rep.error(old, "test file moved out of the test patterns; list its path under Tests:")
    diff = git(root, "diff", "-U0", "--no-color", mb, head)
    cur, line_no = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            line_no = int(m.group(1)) if m else 0
        elif line.startswith("+") and cur:
            if is_test(cur) and not declared(cur):
                for globs, markers in rules:
                    if any(g.match(cur) for g in globs) and any(mk.search(line[1:]) for mk in markers):
                        rep.error(cur, "added line skips or limits tests; list this path under Tests: (%s)" % line[1:].strip()[:50], line_no)
                        break
            line_no += 1
    return rep


# --- Baslinjekontroll (D8:5 krav 2) --------------------------------------------------------------

def check_baseline(root, base, head):
    """En PR får inte lägga till poster i en baslinje, inte heller skapa en: den enda vägen in är adoptionens commit
    (D7:21), som går till main utan PR. Har merge-basen inte mallen än (ingen `.copier-answers.yml`) är PR:en
    adoptionen och kontrollen gäller inte."""
    rep = Report("baseline")
    mb = git(root, "merge-base", base, head).strip()
    if git(root, "cat-file", "-e", "%s:.copier-answers.yml" % mb, check=False).returncode != 0:
        return rep
    src, old = GitRef(root, head), GitRef(root, mb)
    for name in src.listdir(bl.BASELINE_DIR):
        if not name.endswith(".jsonl"):
            continue
        path = "%s/%s" % (bl.BASELINE_DIR, name)
        new_keys, bad = bl.parse_baseline(src.read(path), path)
        for b in bad:
            rep.errors.append(b)
        old_keys, _ = bl.parse_baseline(old.read(path), path)
        for (file, rule, content), n in sorted(new_keys.items()):
            extra = n - old_keys[(file, rule, content)]
            if extra > 0:
                rep.error(path, "adds %d entr%s for %s (%s); a baseline can only shrink, fix the error instead (D8:5)"
                          % (extra, "y" if extra == 1 else "ies", file, rule))
    return rep
