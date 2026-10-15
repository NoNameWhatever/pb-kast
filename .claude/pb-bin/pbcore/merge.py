"""pb-merge: merge-grinden (D5:20, D4:3-4, D5:30). Läser PR:ens head-SHA en gång, kontrollerar länken
mellan `Closes` och issue-filen, vägrar `explore/*`, kräver att varje förväntad check är grön eller
överhoppad, mergar med squash bunden till SHA:n och städar. Fallerar stängt.

Väntande checkar väntas in (högst `WAIT_SECONDS`, under taket på ett foreground-anrop i Claude Code): en röd,
avbruten eller okänd check vägrar direkt, en väntande pollas, och en förväntad check som inte syns än får
`MISSING_GRACE` sekunder (en omkörning efter en redigerad PR-kropp registreras med fördröjning). Taket nått ger
`REFUSED` utan att något mergats; kör pb-merge igen.

Skilj på skriptets vägran (`REFUSED`, exit 1) och fel från `gh` eller git (`ERROR`, exit 2)."""
import re
import tempfile
import time
from pathlib import Path

from .common import CannotRun, GitRef, git, parse_front_matter, sections
from .ghcli import Gh, GhError
from .pr import ISSUE_RE, PLAN_DIR, links

OK_BUCKETS = ("pass", "skipping")
CHECKS_OK_CODES = (0, 1, 8)  # `gh pr checks` svarar 8 vid väntande checkar även med --json
WAIT_SECONDS = 540  # ett foreground-Bash i Claude Code dör vid 600 s
POLL_SECONDS = 15
MISSING_GRACE = 60


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


def _await_checks(gh, pr, names, wait, poll, sleep, clock, out):
    """Returnerar när varje förväntad check är pass eller skipping. Vägrar direkt vid en röd, avbruten eller okänd
    check, och när `wait` sekunder gått med en väntande eller saknad check."""
    start = clock()
    announced = None
    while True:
        rows = gh.json("pr", "checks", pr, "--json", "name,bucket,state", ok_codes=CHECKS_OK_CODES) or []
        pending, missing = [], []
        for name in names:
            mine = [r for r in rows if r["name"] == name]
            if not mine:
                missing.append(name)
                continue
            bad = sorted({r["bucket"] for r in mine if r["bucket"] not in OK_BUCKETS + ("pending",)})
            if bad:
                raise Refused("check '%s' is %s; it must be pass or skipping" % (name, "/".join(bad)))
            if any(r["bucket"] == "pending" for r in mine):
                pending.append(name)
        if not pending and not missing:
            return
        elapsed = clock() - start
        if missing and elapsed >= min(MISSING_GRACE, wait):
            raise Refused("expected check '%s' is missing on the PR head (a workflow may have been removed)" % missing[0])
        if elapsed >= wait:
            raise Refused("check '%s' is still pending after %d s; it must be pass or skipping; run pb-merge again"
                          % (pending[0], int(elapsed)))
        waiting = ", ".join(pending + missing)
        if waiting != announced:
            out("WAIT: waiting for %s (up to %d s)" % (waiting, max(0, int(wait - elapsed))))
            announced = waiting
        sleep(poll)


def merge(root, pr, gh=None, out=print, wait=WAIT_SECONDS, poll=POLL_SECONDS, sleep=time.sleep, clock=time.monotonic):
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

    started = clock()
    _await_checks(gh, pr, _expected_checks(root, base), wait, poll, sleep, clock, out)

    again = gh.json("pr", "view", pr, "--json", "headRefOid")["headRefOid"]
    if again != sha:
        raise Refused("the PR head changed (%s -> %s) after the checks were read; run pb-merge again" % (sha[:8], again[:8]))

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("\n".join(body_lines) + "\n")
        body_file = f.name
    while True:
        try:
            gh.raw("pr", "merge", pr, "--squash", "--match-head-commit", sha,
                   "--subject", "%s (#%s)" % (info["title"], pr), "--body-file", body_file)
            break
        except GhError as e:
            # en omkörning som startade efter att den gamla gröna raden lästes: vänta in den, inom samma tak
            if "is expected" not in str(e) or clock() - started >= wait:
                Path(body_file).unlink(missing_ok=True)
                raise
            out("WAIT: GitHub is still waiting for a required check to report; trying again")
            sleep(poll)
    Path(body_file).unlink(missing_ok=True)

    after = gh.json("pr", "view", pr, "--json", "state")
    if after.get("state") != "MERGED":
        raise GhError("gh reported success but PR #%s is %s, not MERGED" % (pr, after.get("state")))
    out("OK merged PR #%s (%s) with squash bound to %s" % (pr, branch, sha[:8]))
    _cleanup(root, branch, base, out, sha)


def _cleanup(root, branch, base, out, sha=None):
    p = git(root, "push", "origin", "--delete", branch, check=False)
    out("OK deleted remote branch %s" % branch if p.returncode == 0 else
        "WARN: the merge succeeded but the remote branch %s could not be deleted: %s" % (branch, p.stderr.strip()[:80]))
    if git(root, "status", "--porcelain").strip():
        out("WARN: the working tree has uncommitted changes; skipped local cleanup")
        return
    steps = [("checkout", base), ("pull", "--ff-only", "origin", base)]
    if git(root, "rev-parse", "--verify", "-q", "refs/heads/" + branch, check=False).returncode == 0:
        steps.append(("worktree-of", branch))
        steps.append(("branch", "-D", branch))
    for step in steps:
        if step[0] == "worktree-of":
            if not _remove_worktree(root, branch, sha, out):
                return
            continue
        p = git(root, *step, check=False)
        if p.returncode != 0:
            out("WARN: local cleanup stopped at 'git %s': %s" % (" ".join(step), p.stderr.strip()[:80]))
            return
    out("OK local %s is up to date and %s is removed" % (base, branch))


def _worktree_of(root, branch):
    """Sökvägen till en annan worktree där grenen är utcheckad, annars None."""
    path = None
    for line in git(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == "branch refs/heads/" + branch and path and Path(path).resolve() != Path(root).resolve():
            return path
    return None


def _remove_worktree(root, branch, sha, out):
    """En worktree som en session lämnat på den mergade grenen (F39) blockerar `branch -D` och nästa gren med samma namn.
    Tas bara bort när den är ren och står på den mergade head-SHA:n, så att inget går förlorat; annars varnar skriptet med
    kommandona. Ger False när städningen ska stanna."""
    path = _worktree_of(root, branch)
    if path is None:
        return True
    if not Path(path).is_dir():
        git(root, "worktree", "prune", check=False)
        return True
    manual = "remove it yourself with `git worktree unlock %s; git worktree remove %s` and then `git branch -D %s`" % (path, path, branch)
    if git(path, "status", "--porcelain").strip():
        out("WARN: branch %s is checked out in the worktree %s, which has uncommitted or untracked files; %s" % (branch, path, manual))
        return False
    head = git(path, "rev-parse", "HEAD").strip()
    if sha and head != sha:
        out("WARN: branch %s is checked out in the worktree %s at %s, not the merged head %s; %s" % (branch, path, head[:8], sha[:8], manual))
        return False
    git(root, "worktree", "unlock", path, check=False)
    p = git(root, "worktree", "remove", path, check=False)
    if p.returncode != 0:
        out("WARN: the worktree %s could not be removed: %s; %s" % (path, p.stderr.strip()[:80], manual))
        return False
    out("OK removed the worktree %s of %s" % (path, branch))
    return True


def run(root, pr, gh=None, out=print, **timing):
    try:
        merge(root, pr, gh, out, **timing)
        return 0
    except Refused as e:
        out("REFUSED: %s" % e)
        return 1
    except CannotRun as e:  # inklusive GhError
        out("ERROR (not a refusal by pb-merge): %s" % e)
        return 2
