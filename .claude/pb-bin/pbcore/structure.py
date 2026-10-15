"""Kontroller som bara läser repots tillstånd: rotkataloger (D5:22), grennamn (D5:18),
`.gitignore`-effekt (D5:16, D6:22) och hash-manifest (D5:24)."""
import subprocess
from pathlib import Path

import yaml

from .common import CannotRun, Report, WorkTree, git, glob_regex, load_path_map
from .units import load as load_units_file

# Modulbooleans i .copier-answers.yml som saknar mallägda filer och därmed manifest.
MODULES_WITHOUT_OWNED_FILES = ("external_exposure",)


def check_roots(root):
    rep = Report("roots")
    src = WorkTree(root)
    pm = load_path_map(src)
    dirs = sorted({p.split("/", 1)[0] for p in src.ls_files() if "/" in p})
    for d in dirs:
        if d not in pm.roots:
            rep.error(d + "/", "root directory is not classified; add it under roots: in .claude/path-map-project.yml (strict or standard)")
    return rep


TEMPLATE_OWNED_DIRS = (".claude/", ".devcontainer/pb-")


def module_manifests(root):
    """Modul -> manifestmönster, ur `.claude/pb-gates/<modul>/manifests` (ett mönster per rad, D8:2)."""
    gates = Path(root) / ".claude" / "pb-gates"
    out = {}
    for d in sorted(gates.iterdir()) if gates.is_dir() else []:
        f = d / "manifests"
        if f.is_file():
            out[d.name] = [glob_regex("**/" + ln.strip()) for ln in f.read_text(encoding="utf-8").splitlines()
                           if ln.strip() and not ln.strip().startswith("#")]
    return out


def check_units(root):
    """Ett manifest som varken ligger i en deklarerad enhet eller under `exclude:` är rött (D8:2, D8:35)."""
    rep = Report("units")
    manifests = module_manifests(root)
    if not manifests:
        return rep
    units, exclude = load_units_file(root)
    declared = {(u["module"], u["path"].rstrip("/") or ".") for u in units}
    ex = [(e.rstrip("/"), glob_regex(e)) for e in exclude]
    for f in WorkTree(root).ls_files():
        if f.startswith(TEMPLATE_OWNED_DIRS):
            continue  # mallens egna manifest (till exempel sidecarns package.json) är aldrig projektets kodenheter
        for module, patterns in manifests.items():
            if not any(rx.match(f) for rx in patterns):
                continue
            unit_dir = f.rsplit("/", 1)[0] if "/" in f else "."
            if (module, unit_dir) in declared:
                continue
            if any(f == e or f.startswith(e + "/") or rx.match(f) for e, rx in ex):
                continue
            rep.error(f, "manifest of module '%s' is outside every declared unit; declare '%s' in .claude/units.yml or list it under exclude:" % (module, unit_dir))
    return rep


def check_branch(root, branch):
    rep = Report("branch")
    if not branch:
        raise CannotRun("no branch name given (--branch)")
    if branch.startswith("explore/"):
        rep.error(branch, "explore/* branches are never merged (D2:8); open a normal branch N-slug for the build")
    return rep


def check_gitignore(root):
    rep = Report("gitignore")
    d = Path(root) / ".claude" / "pb-baseline" / "gitignore"
    files = sorted(d.glob("*.txt")) if d.is_dir() else []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            path = line.strip()
            if not path or path.startswith("#"):
                continue
            # Utan användarens globala excludes-fil (Claude Code skriver dit, F28): bara repots egen .gitignore räknas.
            p = git(root, "-c", "core.excludesFile=/dev/null", "check-ignore", "-q", "--no-index", path, check=False)
            if p.returncode == 1:
                rep.error("%s" % f.relative_to(root), "'%s' is not ignored by .gitignore (a negation or a missing line)" % path, n)
            elif p.returncode != 0:
                raise CannotRun("git check-ignore failed for %s: %s" % (path, p.stderr.strip()))
    if files:
        for tracked in git(root, "ls-files", "-ci", "--exclude-standard", "-z").split("\0"):
            if tracked:
                rep.error(tracked, "tracked file matches an ignored pattern; remove it from the index (secrets must never be tracked)")
    return rep


def check_manifest(root):
    rep = Report("manifest")
    mdir = Path(root) / ".claude" / "pb-manifest"
    core = mdir / "core.sha256"
    if not core.is_file():
        rep.error(".claude/pb-manifest/core.sha256", "missing; every tag ships it (D5:24)")
    expected = [core] if core.is_file() else []
    answers_file = Path(root) / ".copier-answers.yml"
    answers = {}
    if answers_file.is_file():
        answers = yaml.safe_load(answers_file.read_text(encoding="utf-8")) or {}
    for key, value in sorted(answers.items()):
        if value is True and key not in MODULES_WITHOUT_OWNED_FILES:
            m = mdir / ("%s.sha256" % key)
            if m.is_file():
                expected.append(m)
            else:
                rep.error(".claude/pb-manifest/%s.sha256" % key, "missing manifest for enabled module '%s'" % key)
    for extra in sorted(mdir.glob("*.sha256")) if mdir.is_dir() else []:
        if extra not in expected and extra.name != "core.sha256":
            expected.append(extra)
    for m in expected:
        try:
            p = subprocess.run(["sha256sum", "-c", "--quiet", str(m.relative_to(root))], cwd=str(root),
                               capture_output=True, text=True)
        except FileNotFoundError:
            raise CannotRun("sha256sum not found")
        if p.returncode != 0:
            for line in (p.stdout + p.stderr).splitlines():
                line = line.strip()
                if line.endswith(": FAILED"):
                    rep.error(line[:-len(": FAILED")], "differs from the tag manifest %s (template-owned file was edited)" % m.name)
                elif line.endswith("FAILED open or read"):
                    rep.error(line.split(":")[0], "listed in %s but missing (template-owned file was deleted)" % m.name)
                elif line.startswith("sha256sum:") or "FAILED" in line:
                    continue
                elif line:
                    rep.error(str(m.relative_to(root)), line)
    return rep
