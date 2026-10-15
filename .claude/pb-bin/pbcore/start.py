"""pb-start: orientering vid sessionsstart (D4:17). Läsande: ändrar aldrig arbetsträdet, bara
`git fetch`. Tre klasser: STOPP (agenten rapporterar och väntar), INFO (en rad var) och OKÄNT
(en kontroll som inte kunde köras, alltid med orsak, D6:3). Högst ca 10 rader."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .common import CannotRun, git, parse_front_matter
from .ghcli import Gh, GhError

DEFAULT_CADENCE = {"small_items": 10, "small_items_age_weeks": 4, "docs_review_merges": 15,
                   "security_review_commits": 30}
MAX_LINES = 10
MAIN_CANDIDATES = ("origin/main", "main")


def _main_ref(root):
    for b in MAIN_CANDIDATES:
        if git(root, "rev-parse", "--verify", "-q", b, check=False).returncode == 0:
            return b
    return None


def _front(root, rel):
    f = Path(root) / rel
    try:
        return parse_front_matter(f.read_text(encoding="utf-8"))[0] or {}
    except OSError:
        return {}


def _issue_files(root, done):
    d = Path(root) / "project-docs" / "issues" / ("done" if done else "")
    return sorted(p for p in d.glob("*.md")) if d.is_dir() else []


def _commit_count(root, main, since):
    p = git(root, "rev-list", "--count", "--first-parent", "%s..%s" % (since, main) if since else main, check=False)
    return int(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip().isdigit() else None


def _adoption_commit(root, main):
    """Första commit på main som lägger till `.copier-answers.yml`: init eller adoption, där mallens flöde börjar.
    Räknarna räknar efter den när ingen tidigare körning finns (F22). None om filen aldrig lagts till."""
    p = git(root, "log", "--diff-filter=A", "--first-parent", "--reverse", "--format=%H", main, "--", ".copier-answers.yml", check=False)
    shas = p.stdout.split() if p.returncode == 0 else []
    return shas[0] if shas else None


def _last_added(root, main, paths):
    """Senast tillagda filen bland `paths` (commit och sökväg), eller None."""
    best = None
    for rel in paths:
        p = git(root, "log", "--diff-filter=A", "--format=%ct %H", "-1", main, "--", rel, check=False)
        if p.returncode == 0 and p.stdout.strip():
            ts, sha = p.stdout.split()
            if best is None or int(ts) > best[0]:
                best = (int(ts), sha, rel)
    return best


def orient(root, cwd=None, gh=None, fetch=True):
    root = Path(root)
    gh = gh or Gh(root)
    stop, info, unknown = [], [], []

    if Path(cwd or root).resolve() != root.resolve():
        stop.append("STOPP: start in the project root (%s), not in %s; the project's own settings are only read from the start directory" % (root, cwd))

    if fetch:
        p = git(root, "fetch", "--quiet", "origin", check=False)
        if p.returncode != 0:
            unknown.append("OKÄNT: git fetch failed (%s); main may be out of date" % (p.stderr.strip().splitlines() or ["no remote"])[0][:80])

    dirty = [ln for ln in git(root, "status", "--porcelain").splitlines() if ln.strip()]
    if dirty:
        stop.append("STOPP: %d uncommitted change(s), commit or discard them first (e.g. %s)" % (len(dirty), dirty[0][3:]))

    main = _main_ref(root)
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch not in ("main", "HEAD"):
        m = re.match(r"^(\d+)-", branch)
        info.append("INFO: on branch %s%s" % (branch, " (issue #%s)" % m.group(1) if m else ""))
        try:
            prs = gh.json("pr", "list", "--head", branch, "--state", "all", "--json", "number,state", "--limit", "1")
            if prs and prs[0]["state"] in ("MERGED", "CLOSED"):
                stop.append("STOPP: the PR for this branch (#%s) is %s; start from a clean main" % (prs[0]["number"], prs[0]["state"].lower()))
        except GhError as e:
            unknown.append("OKÄNT: could not check the PR of this branch: %s" % e)

    try:
        open_prs = gh.json("pr", "list", "--state", "open", "--json", "number,title,headRefName")
        for pr in (open_prs or [])[:3]:
            info.append("INFO: PR #%s waits for your merge: %s" % (pr["number"], pr["title"][:60]))
    except GhError as e:
        unknown.append("OKÄNT: could not list open PRs: %s" % e)

    _failure_register(root, info)
    _stale_issue_files(root, gh, info, unknown)
    _cadence(root, gh, main, info, unknown)

    lines = stop + info + unknown
    if len(lines) > MAX_LINES:
        keep = lines[:MAX_LINES - 1]
        lines = keep + ["INFO: (+%d more lines omitted)" % (len(lines) - len(keep))]
    return lines, bool(stop), bool(unknown)


def _failure_register(root, info):
    groups = {}
    for f in sorted((Path(root) / "project-docs" / "failures").glob("*.md")):
        fm = _front(root, f.relative_to(root))
        if fm.get("breaks"):
            groups.setdefault(fm["breaks"], []).append(fm.get("action"))
    for rule, actions in sorted(groups.items()):
        if len(actions) >= 2 and not any(a in ("hook", "check") for a in actions):
            info.append("INFO: %s has %d failure posts and no hook or check yet (D4:2)" % (rule, len(actions)))


def _stale_issue_files(root, gh, info, unknown):
    for f in _issue_files(root, done=False):
        n = _front(root, f.relative_to(root)).get("issue")
        if not isinstance(n, int):
            continue
        try:
            st = gh.json("issue", "view", n, "--json", "state")
        except GhError as e:
            unknown.append("OKÄNT: could not check issue #%d: %s" % (n, e))
            return
        if st and st.get("state") == "CLOSED":
            info.append("INFO: %s is still in issues/ but issue #%d is closed; propose moving it to issues/done/ with outcome: cancelled" % (f.name, n))


def _cadence(root, gh, main, info, unknown):
    cad = dict(DEFAULT_CADENCE)
    cf = Path(root) / "project-docs" / "cadence.yml"
    if cf.is_file():
        try:
            cad.update(yaml.safe_load(cf.read_text(encoding="utf-8")) or {})
        except yaml.YAMLError:
            unknown.append("OKÄNT: project-docs/cadence.yml cannot be parsed; using the template's defaults")
    else:
        info.append("INFO: project-docs/cadence.yml is missing; using the template's defaults")
    if main is None:
        unknown.append("OKÄNT: no main branch found; hygiene and security review triggers not checked")
        return

    done = [f.relative_to(root) for f in _issue_files(root, done=True)]
    hyg = _last_added(root, main, [str(r) for r in done if _front(root, r).get("type") == "hygiene"])
    start = _adoption_commit(root, main)
    n = _commit_count(root, main, hyg[1] if hyg else start)
    if n is not None and n >= cad["docs_review_merges"]:
        info.append("INFO: %d commits on main since the last hygiene run (limit %s); propose a hygiene run with a docs review" % (n, cad["docs_review_merges"]))

    _small_items(root, gh, cad, info, unknown)

    sec = _last_added(root, main, [str(r) for r in done if _front(root, r).get("type") == "security"])
    base = _front(root, sec[2]).get("reviewed-sha") if sec else None
    n = _commit_count(root, main, base if base and git(root, "cat-file", "-e", str(base), check=False).returncode == 0 else start)
    tm = _last_added(root, main, ["project-docs/threat-model.md"]) if (Path(root) / "project-docs/threat-model.md").is_file() else None
    if n is not None and n >= cad["security_review_commits"]:
        info.append("INFO: security review is due (%s commits on main since the last review, limit %s)" % (n, cad["security_review_commits"]))
    elif tm and not base:
        info.append("INFO: security review is due (the threat model has no review yet)")
    elif tm and git(root, "merge-base", "--is-ancestor", str(base), tm[1], check=False).returncode == 0 and str(base) != tm[1]:
        info.append("INFO: security review is due (the threat model changed after the last review)")


def _small_items(root, gh, cad, info, unknown):
    try:
        inbox = gh.json("issue", "list", "--state", "open", "--search", "chore-inkorg in:title", "--json", "number", "--limit", "1")
        if not inbox:
            return
        subs = gh.json("api", "repos/{owner}/{repo}/issues/%d/sub_issues" % inbox[0]["number"])
    except GhError as e:
        unknown.append("OKÄNT: could not check the small-item inbox: %s" % e)
        return
    opened = [s for s in (subs or []) if s.get("state") == "open"]
    if not opened:
        return
    oldest = min(datetime.fromisoformat(s["created_at"].replace("Z", "+00:00")) for s in opened)
    old = datetime.now(timezone.utc) - oldest > timedelta(weeks=cad["small_items_age_weeks"])
    if len(opened) >= cad["small_items"] or old:
        info.append("INFO: %d open small items (limits: %s items, %s weeks); propose a hygiene package" % (
            len(opened), cad["small_items"], cad["small_items_age_weeks"]))
