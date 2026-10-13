"""pb-stats (D11:8, D11:9): mätetal härledda ur git, issue-filer, felregistret och `gh`. Läsande och utan lagring;
allt kan räknas om, även bakåt med `--ref`. Varje mätetal anger vilket beslut eller vilken trigger det matar
(`feeds`), och ett mätetal utan mottagare får inte finnas (testat). `--json` ger ett versionerat schema.

Mätetalen från git och filer (squash-commitens kropp är PR-kroppen, `pb-merge`) kräver ingen `gh`. Mätetalen från
GitHub (ledtid, commits efter öppnad PR, röda körningar, grönt första försöket) står som `unavailable` när `gh`
saknas eller misslyckas; de övriga påverkas inte."""
import json
import re
import statistics
from collections import Counter
from datetime import datetime, timezone

from .common import CannotRun, GitRef, git, parse_front_matter, sections
from .ghcli import Gh, GhError
from .pr import row_value
from .start import MAIN_CANDIDATES

SCHEMA_VERSION = 1
PR_SUBJECT = re.compile(r"\(#(\d+)\)\s*$")
CLOSES = re.compile(r"\b(?:closes|refs)\s+#(\d+)", re.I)
NONE_TEXT = re.compile(r"^\s*(?:none|inga?|ingen|n/?a|[-–—])\b", re.I)
SEVERITIES = ("critical", "high", "medium", "low", "info")
ISSUE_FILE = re.compile(r"^(?:done/)?(\d+)-[^/]+\.md$")

# Mätetalens mottagare: beslutet eller triggern som fakta ska mata (D11:8). Nyckeln är mätetalets namn.
FEEDS = {
    "failures": "D11:4–5 (felregistret: nya regler, kontroller och vanliga misstag), D4:2",
    "bugs_by_introducing_level": "D2:4 och D6:36 (nivåindelningen)",
    "regression_test_none": "D11:14 (trigger för körning av regressionstest i CI)",
    "reverts": "D6:36 (revert av Skärpt), D2:16",
    "criteria_changes": "D10 (piloten: hur ofta kriterier ändras efter start)",
    "deviations": "D2:14 (avvikelser från agentens villkor)",
    "security_reviews": "D11:18 och D2 (sökvägsgolvet)",
    "lead_time": "D2, D10 och B13 (ledtid per steg; trigger för parallella sessioner)",
    "commits_after_open": "D11:1 och D11:17 (rättelser efter öppnad PR; lätt granskning)",
    "ci_red_runs": "D5 och D11:2 (var grindarna fäller)",
    "first_attempt_green": "D11:2 och D10 (grönt första försöket)",
}


def main_ref(root):
    for b in MAIN_CANDIDATES:
        if git(root, "rev-parse", "--verify", "-q", b, check=False).returncode == 0:
            return b
    raise CannotRun("no main branch to read (origin/main or main)")


def _front(src, rel):
    text = src.read(rel)
    if text is None:
        return None, ""
    fm, body, _ = parse_front_matter(text)
    return fm or {}, body


def load_issues(src):
    """issue-nummer -> (front matter, brödtext) för `project-docs/issues/` och `done/`."""
    out = {}
    for d in ("project-docs/issues", "project-docs/issues/done"):
        for name in src.listdir(d):
            m = ISSUE_FILE.match(name)
            if not name.endswith(".md") or not m:
                continue
            fm, body = _front(src, "%s/%s" % (d, name))
            if fm is not None:
                num = fm.get("issue") if isinstance(fm.get("issue"), int) else int(m.group(1))
                out[num] = (fm, body)
    return out


def load_failures(src):
    out = []
    for name in src.listdir("project-docs/failures"):
        if name.endswith(".md"):
            fm, _ = _front(src, "project-docs/failures/" + name)
            if fm:
                out.append((name, fm))
    return out


def merged_prs(root, ref):
    """PR:er på main i ordning nyast först: (nummer, sha, tid, ämne, kropp). Squash ger en commit per PR (D5)."""
    raw = git(root, "log", "--first-parent", "--format=%H%x1f%ct%x1f%s%x1f%b%x1e", ref)
    prs = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, ts, subject, body = (rec.split("\x1f") + ["", "", "", ""])[:4]
        m = PR_SUBJECT.search(subject)
        prs.append({"number": int(m.group(1)) if m else None, "sha": sha, "time": int(ts), "subject": subject, "body": body})
    return prs


def _pr_level(pr, issues):
    for n in CLOSES.findall(pr["body"]):
        entry = issues.get(int(n))
        if entry and entry[0].get("level") in ("standard", "strict"):
            return entry[0]["level"]
    return "unknown"


def counted(items):
    return dict(sorted(Counter(items).items()))


# --- Mätetal ur git och filer ------------------------------------------------------------------------------------------

def m_failures(ctx):
    recs = load_failures(ctx["src"])
    return {"n": len(recs), "by_cause": counted(f.get("cause", "unknown") for _, f in recs),
            "by_owner": counted(f.get("owner", "unknown") for _, f in recs),
            "by_action": counted(f.get("action", "unknown") for _, f in recs),
            "by_detected": counted(f.get("detected", "unknown") for _, f in recs)}


def m_bugs_by_introducing_level(ctx):
    by_number = {p["number"]: p for p in ctx["prs"] if p["number"] is not None}
    levels = []
    for _, f in load_failures(ctx["src"]):
        if "introduced-by" not in f:
            continue
        m = re.match(r"^#?(\d+)$", str(f["introduced-by"]).strip())
        pr = by_number.get(int(m.group(1))) if m else None
        levels.append(_pr_level(pr, ctx["issues"]) if pr else "unknown")
    return {"n": len(levels), "by_level": counted(levels)}


def m_regression_test_none(ctx):
    rows = [row_value(p["body"], "Regression test:") for p in ctx["prs"]]
    rows = [r for r in rows if r]
    none = [r for r in rows if re.match(r"^none\b", r.strip(), re.I)]
    return {"bug_prs": len(rows), "none": len(none), "share": round(len(none) / len(rows), 3) if rows else None}


def m_reverts(ctx):
    rev = [p for p in ctx["prs"] if p["subject"].startswith("Revert ")]
    return {"n": len(rev), "of_merges": len([p for p in ctx["prs"] if p["number"]]), "prs": [p["number"] for p in rev if p["number"]]}


def m_criteria_changes(ctx):
    changed = 0
    for _, (fm, body) in ctx["issues"].items():
        text = sections(body).get("Criteria changes", "").strip()
        if text and not NONE_TEXT.match(text):
            changed += 1
    return {"issues": len(ctx["issues"]), "with_changes": changed}


def m_deviations(ctx):
    rows = [row_value(p["body"], "Deviations:") for p in ctx["prs"]]
    rows = [r for r in rows if r]
    deviating = [r for r in rows if not NONE_TEXT.match(r)]
    return {"prs_with_row": len(rows), "with_deviations": len(deviating),
            "share": round(len(deviating) / len(rows), 3) if rows else None}


def m_security_reviews(ctx):
    reviews = []
    for num, (fm, body) in sorted(ctx["issues"].items()):
        if fm.get("type") != "security" or "reviewed-sha" not in fm:
            continue
        findings = sections(body).get("Findings", "")
        sev = Counter()
        for line in findings.splitlines():
            if re.match(r"^\s*[-*]\s+\S", line):
                word = next((s for s in SEVERITIES if re.search(r"\b%s\b" % s, line, re.I)), "unspecified")
                sev[word] += 1
        reviews.append({"issue": num, "reviewed_sha": str(fm["reviewed-sha"])[:12], "findings": sum(sev.values()),
                        "by_severity": dict(sorted(sev.items()))})
    return {"n": len(reviews), "reviews": reviews}


# --- Mätetal ur GitHub -------------------------------------------------------------------------------------------------

def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _dist(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "median": None, "p90": None}
    p90 = values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]
    return {"n": len(values), "median": round(statistics.median(values), 2), "p90": round(p90, 2)}


def gh_data(gh, merged_numbers):
    prs = gh.json("pr", "list", "--state", "merged", "--limit", "500", "--json", "number,body,createdAt,mergedAt,headRefName") or []
    issues = gh.json("issue", "list", "--state", "all", "--limit", "500", "--json", "number,createdAt") or []
    runs = gh.json("run", "list", "--limit", "500", "--json", "name,conclusion,headBranch,createdAt") or []
    # bara PR:er vars squash-commit (`titel (#N)`) ligger på ref: en tidsgräns mot ref-commitens tid är för skör (GitHubs commit- och mergetid kan skilja sig)
    prs = [p for p in prs if p.get("mergedAt") and p["number"] in merged_numbers]
    # `commits` ingår inte i listfrågan: med författare per commit överskrider den GraphQL-gränsen på 500 000 noder vid --limit 500
    for p in prs:
        p["commits"] = (gh.json("pr", "view", str(p["number"]), "--json", "commits") or {}).get("commits") or []
    return prs, issues, runs


def m_lead_time(ctx):
    prs, issues, _ = ctx["gh"]
    created = {i["number"]: _ts(i["createdAt"]) for i in issues}
    open_to_merge, issue_to_merge = [], []
    for p in prs:
        merged, opened = _ts(p["mergedAt"]), _ts(p["createdAt"])
        open_to_merge.append((merged - opened).total_seconds() / 3600)
        for n in CLOSES.findall(p.get("body") or ""):
            if int(n) in created:
                issue_to_merge.append((merged - created[int(n)]).total_seconds() / 3600)
                break
    return {"unit": "hours", "pr_open_to_merge": _dist(open_to_merge), "issue_to_merge": _dist(issue_to_merge)}


def m_commits_after_open(ctx):
    prs, _, _ = ctx["gh"]
    counts = []
    for p in prs:
        opened = _ts(p["createdAt"])
        counts.append(sum(1 for c in p.get("commits") or [] if _ts(c.get("committedDate")) and _ts(c["committedDate"]) > opened))
    d = _dist(counts)
    d["with_any"] = sum(1 for c in counts if c > 0)
    return d


def m_ci_red_runs(ctx):
    _, _, runs = ctx["gh"]
    per = {}
    for r in runs:
        if r.get("headBranch") == "main":
            continue
        row = per.setdefault(r["name"], {"runs": 0, "failed": 0})
        row["runs"] += 1
        if r.get("conclusion") == "failure":
            row["failed"] += 1
    return {"per_workflow": dict(sorted(per.items()))}


def m_first_attempt_green(ctx):
    prs, _, runs = ctx["gh"]
    failed_branches = {r["headBranch"] for r in runs if r.get("conclusion") == "failure"}
    seen = {r["headBranch"] for r in runs}
    counted_prs = [p for p in prs if p.get("headRefName") in seen]
    green = [p for p in counted_prs if p["headRefName"] not in failed_branches]
    return {"prs": len(counted_prs), "green_first_time": len(green),
            "share": round(len(green) / len(counted_prs), 3) if counted_prs else None}


FILE_METRICS = (("failures", m_failures), ("bugs_by_introducing_level", m_bugs_by_introducing_level),
                ("regression_test_none", m_regression_test_none), ("reverts", m_reverts),
                ("criteria_changes", m_criteria_changes), ("deviations", m_deviations),
                ("security_reviews", m_security_reviews))
GH_METRICS = (("lead_time", m_lead_time), ("commits_after_open", m_commits_after_open),
              ("ci_red_runs", m_ci_red_runs), ("first_attempt_green", m_first_attempt_green))


def compute(root, ref=None, gh=None, use_gh=True, now=None):
    ref = ref or main_ref(root)
    sha = git(root, "rev-parse", "--verify", ref).strip()
    src = GitRef(root, ref)
    ctx = {"src": src, "prs": merged_prs(root, ref), "issues": load_issues(src)}
    metrics, unavailable = {}, {}
    for name, fn in FILE_METRICS:
        metrics[name] = fn(ctx)
    if use_gh:
        try:
            ctx["gh"] = gh_data(gh or Gh(root), {p["number"] for p in ctx["prs"] if p["number"] is not None})
        except GhError as e:
            for name, _ in GH_METRICS:
                unavailable[name] = str(e)
        else:
            for name, fn in GH_METRICS:
                metrics[name] = fn(ctx)
    else:
        for name, _ in GH_METRICS:
            unavailable[name] = "skipped (--no-gh)"
    return {"schema": SCHEMA_VERSION, "ref": ref, "sha": sha,
            "generated": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metrics": {k: {"feeds": FEEDS[k], "value": v} for k, v in metrics.items()},
            "unavailable": {k: {"feeds": FEEDS[k], "reason": v} for k, v in unavailable.items()}}


# --- Text ---------------------------------------------------------------------------------------------------------------

def _flat(v):
    if isinstance(v, dict):
        return ", ".join("%s %s" % (k, _flat(x)) if not isinstance(x, dict) else "%s (%s)" % (k, _flat(x)) for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_flat(x) for x in v) or "none"
    return "n/a" if v is None else str(v)


def render(result):
    lines = ["pb-stats %s @ %s (schema %d)" % (result["ref"], result["sha"][:8], result["schema"])]
    for name, m in result["metrics"].items():
        lines.append("%s: %s" % (name, _flat(m["value"])))
        lines.append("  feeds: %s" % m["feeds"])
    for name, m in result["unavailable"].items():
        lines.append("%s: unavailable (%s)" % (name, m["reason"]))
        lines.append("  feeds: %s" % m["feeds"])
    return "\n".join(lines)


def emit(result, as_json=False, out=print):
    out(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False) if as_json else render(result))
