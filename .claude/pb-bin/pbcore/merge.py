"""pb-merge: merge-grinden (D5:20, D4:3-4, D5:30). Läser PR:ens head-SHA en gång, kontrollerar länken
mellan `Closes` och issue-filen, vägrar `explore/*`, kräver att varje förväntad check är grön eller
överhoppad, mergar med squash bunden till SHA:n och städar. Fallerar stängt.

Skilj på skriptets vägran (`REFUSED`, exit 1) och fel från `gh` eller git (`ERROR`, exit 2)."""
import re
import tempfile
from pathlib import Path

from .common import CannotRun, GitRef, git, parse_front_matter, sections
from .ghcli import Gh, GhError
from .pr import ISSUE_RE, PLAN_DIR, links

OK_BUCKETS = ("pass", "skipping")
CHECKS_OK_CODES = (0, 1, 8)  # `gh pr checks` svarar 8 vid väntande checkar även med --json


class Refused(Exception):
    pass


def _git(root, *args):
    try:
        return git(root, *args)
    except CannotRun as e:
        raise GhError(str(e))


def _open_issue(gh, n):
    st = gh.json("issue", "view", n, "--json", "state")
    if not st or st.get("state") != "OPEN":
        raise Refused("issue #%d is not open (the PR must close an open issue)" % n)


def _expected_checks(root, base):
    src = GitRef(root, "origin/" + base)
    names = []
    for f in src.listdir(".claude/pb-expected-checks"):
        if f.endswith(".txt"):
            names += [ln.strip() for ln in src.read(".claude/pb-expected-checks/" + f).splitlines()
                      if ln.strip() and not ln.strip().startswith("#")]
    if not names:
        raise Refused("no list of expected checks on %s (.claude/pb-expected-checks/); refusing to merge without one" % base)
    return names


def merge(root, pr, gh=None, out=print):
    root = Path(root)
    gh = gh or Gh(root)
    info = gh.json("pr", "view", pr, "--json", "number,state,headRefName,headRefOid,baseRefName,title,body,files")
    if info["state"] != "OPEN":
        raise Refused("PR #%s is %s" % (pr, info["state"].lower()))
    sha, branch, base = info["headRefOid"], info["headRefName"], info["baseRefName"]
    if branch.startswith("explore/"):
        raise Refused("explore/* branches are never merged (D2:8); the result of an exploration is knowledge, not code")

    _git(root, "fetch", "--quiet", "origin", "+refs/heads/%s:refs/remotes/origin/%s" % (base, base))
    _git(root, "fetch", "--quiet", "origin", "refs/pull/%s/head" % pr)
    if _git(root, "rev-parse", "FETCH_HEAD").strip() != sha:
        raise Refused("the PR head moved while it was being read; run pb-merge again")

    paths = [f["path"] for f in info["files"]]
    files = [p for p in paths if ISSUE_RE.match(p)]
    if len(files) != 1:
        raise Refused("expected exactly one issue file in the PR (D2:10), found %d" % len(files))
    ipath = files[0]
    fm, ibody, _ = parse_front_matter(_git(root, "show", "%s:%s" % (sha, ipath)))
    n = (fm or {}).get("issue")
    if not isinstance(n, int) or isinstance(n, bool):
        raise Refused("%s has no issue: number in its front matter" % ipath)

    closes, refs = links(info.get("body") or "")
    plan_pr = all(p.startswith(PLAN_DIR) and not p.startswith(PLAN_DIR + "done/") for p in paths)
    if plan_pr:
        if n in closes:
            raise Refused("a plan PR must use 'Refs #%d', not 'Closes #%d': the issue stays open until the code PR" % (n, n))
        if n not in refs:
            raise Refused("the plan PR has no 'Refs #%d' matching issue: %d in %s" % (n, n, ipath))
        body_lines = ["Refs #%d" % n]
        final = ipath
    else:
        if n not in closes:
            raise Refused("the PR has no 'Closes #%d' matching issue: %d in %s" % (n, n, ipath))
        if not ipath.startswith(PLAN_DIR + "done/"):
            raise Refused("the code PR must move %s to %sdone/ (D3:7); the squash message would otherwise name a path that does not exist" % (ipath, PLAN_DIR))
        wanted = {n}
        if fm.get("type") == "hygiene":  # varje ingående sub-issue ska ha ett eget nyckelord
            wanted |= {int(x) for x in re.findall(r"#(\d+)", sections(ibody).get("Acceptance criteria", ""))}
            missing = sorted(wanted - closes)
            if missing:
                raise Refused("hygiene package: no 'Closes #%d' for included issue(s) %s (write 'Closes #1, closes #2')" % (
                    missing[0], ", ".join("#%d" % m for m in missing)))
        for m in sorted(closes | wanted):
            _open_issue(gh, m)
        body_lines = ["Closes #%d" % m for m in sorted(closes | wanted)]
        final = PLAN_DIR + "done/" + ipath.rsplit("/", 1)[1]
    body_lines.append("Issue file: %s" % final)

    rows = gh.json("pr", "checks", pr, "--json", "name,bucket,state", ok_codes=CHECKS_OK_CODES) or []
    for name in _expected_checks(root, base):
        mine = [r for r in rows if r["name"] == name]
        if not mine:
            raise Refused("expected check '%s' is missing on the PR head (a workflow may have been removed)" % name)
        bad = sorted({r["bucket"] for r in mine if r["bucket"] not in OK_BUCKETS})
        if bad:
            raise Refused("check '%s' is %s; it must be pass or skipping" % (name, "/".join(bad)))

    again = gh.json("pr", "view", pr, "--json", "headRefOid")["headRefOid"]
    if again != sha:
        raise Refused("the PR head changed (%s -> %s) after the checks were read; run pb-merge again" % (sha[:8], again[:8]))

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("\n".join(body_lines) + "\n")
        body_file = f.name
    gh.raw("pr", "merge", pr, "--squash", "--match-head-commit", sha,
           "--subject", "%s (#%s)" % (info["title"], pr), "--body-file", body_file)
    Path(body_file).unlink(missing_ok=True)

    after = gh.json("pr", "view", pr, "--json", "state")
    if after.get("state") != "MERGED":
        raise GhError("gh reported success but PR #%s is %s, not MERGED" % (pr, after.get("state")))
    out("OK merged PR #%s (%s) with squash bound to %s" % (pr, branch, sha[:8]))
    _cleanup(root, branch, base, out)


def _cleanup(root, branch, base, out):
    p = git(root, "push", "origin", "--delete", branch, check=False)
    out("OK deleted remote branch %s" % branch if p.returncode == 0 else
        "WARN: the merge succeeded but the remote branch %s could not be deleted: %s" % (branch, p.stderr.strip()[:80]))
    if git(root, "status", "--porcelain").strip():
        out("WARN: the working tree has uncommitted changes; skipped local cleanup")
        return
    steps = [("checkout", base), ("pull", "--ff-only", "origin", base)]
    if git(root, "rev-parse", "--verify", "-q", "refs/heads/" + branch, check=False).returncode == 0:
        steps.append(("branch", "-D", branch))
    for step in steps:
        p = git(root, *step, check=False)
        if p.returncode != 0:
            out("WARN: local cleanup stopped at 'git %s': %s" % (" ".join(step), p.stderr.strip()[:80]))
            return
    out("OK local %s is up to date and %s is removed" % (base, branch))


def run(root, pr, gh=None, out=print):
    try:
        merge(root, pr, gh, out)
        return 0
    except Refused as e:
        out("REFUSED: %s" % e)
        return 1
    except CannotRun as e:  # inklusive GhError
        out("ERROR (not a refusal by pb-merge): %s" % e)
        return 2
