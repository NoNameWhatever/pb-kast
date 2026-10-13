"""Gemensam kod för python-modulens adaptrar (D8:26, 29, 32, 33). Adaptrarna körs av kärnans
dispatcher som `<adapter> <enhetens sökväg> [filer]` och svarar med exitkod 0 (godkänt), 1 (fel) eller
2 (kunde inte köras), med fel som `fil:rad meddelande` (D5:32).

Golvet läggs sist (D8:32): grinden kör verktygen med en genererad konfig som `extend`ar/`extends`
projektets och sätter mallens golv ovanpå, så att en försvagning i projektets konfig inte har effekt."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

RUFF_SELECT = ["E", "F", "W", "I", "B", "UP", "S", "PGH", "RUF100"]
FORBIDDEN_CONFIG_FILES = ("ruff.toml", ".ruff.toml", "pyrightconfig.json", "pytest.ini", "tox.ini")
FORBIDDEN_UV_KEYS = ("exclude-newer", "no-build", "python-preference", "python-downloads-json-url")
PYTEST_NEUTRAL = ["-o", "addopts=", "-o", "norecursedirs=*.egg .* _darcs build CVS dist node_modules venv {arch}",
                  "-o", "python_files=test_*.py *_test.py", "-o", "python_classes=Test", "-o", "python_functions=test",
                  "-p", "no:cacheprovider"]
UV_LOCK_STALE = ("needs to be updated", "lockfile", "is out of date")


class CannotRun(Exception):
    pass


def record(text, file, line, rule):
    """Baslinjewrappern (D8:25) sätter PB_RECORDS: varje fynd som får ligga i en baslinje skrivs då också som en post
    med fil, rad och regel. Konfigfel och golvbrott skrivs aldrig hit, så de kan inte baslinjas."""
    path = os.environ.get("PB_RECORDS")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": text, "file": file, "line": line, "rule": rule}) + "\n")


def complete():
    """Markerar att alla verktyg körts klart, så att wrappern får kalla en post i baslinjen för inaktuell."""
    path = os.environ.get("PB_RECORDS")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"complete": True}) + "\n")


def need(tool):
    exe = shutil.which(tool)
    if not exe:
        raise CannotRun("%s not found (it is installed in the ci image by the python module)" % tool)
    return exe


def run(cmd, cwd, timeout=None, env=None):
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise CannotRun("%s timed out" % cmd[0])
    except OSError as e:
        raise CannotRun("%s could not start: %s" % (cmd[0], e))


def tracked_python_files(root, unit):
    """Spårade och nya, icke-ignorerade filer: grinden körs före commit, och en ny fil får inte slippa kontrollen."""
    p = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", unit], root)
    if p.returncode != 0:
        raise CannotRun("git ls-files failed: %s" % p.stderr.strip())
    return [f for f in p.stdout.split("\0") if f.endswith((".py", ".pyi"))]


# --- Konfig som mallen äger -------------------------------------------------------------------------------

# Projektets Ruff-inställningar som får följa med till golvet (vitlista). Allt annat, framför allt
# `select`, `ignore`, `per-file-ignores` och `extend-per-file-ignores`, tas inte med: ett golv som bara
# `extend`ar projektets fil släpper igenom `per-file-ignores`, så golvet är en fristående fil (D12:8).
RUFF_TOP_KEYS = ("line-length", "indent-width", "target-version", "src", "exclude", "extend-exclude",
                 "respect-gitignore", "namespace-packages", "force-exclude")
RUFF_LINT_KEYS = ("isort", "exclude")


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k)


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join("%s = %s" % (_toml_key(k), _toml_value(x)) for k, x in v.items()) + " }"
    raise CannotRun("cannot write %r to TOML" % (v,))


def dump_toml(data, prefix=()):
    """Minimal TOML-skrivare för skalärer, listor och tabeller (räcker för Rufffs inställningar)."""
    lines = [("%s = %s" % (_toml_key(k), _toml_value(v))) for k, v in data.items() if not isinstance(v, dict)]
    out = []
    if lines:
        if prefix:
            out.append("[%s]" % ".".join(_toml_key(k) for k in prefix))
        out += lines + [""]
    for k, v in data.items():
        if isinstance(v, dict):
            out.append(dump_toml(v, prefix + (k,)))
    return "\n".join(out)


def project_ruff_settings(unit_abs):
    f = Path(unit_abs) / "pyproject.toml"
    try:
        ruff = tomllib.loads(f.read_text(encoding="utf-8")).get("tool", {}).get("ruff", {})
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise CannotRun("%s: cannot read: %s" % (f, e))
    out = {k: ruff[k] for k in RUFF_TOP_KEYS if k in ruff}
    if isinstance(ruff.get("format"), dict):
        out["format"] = ruff["format"]
    lint = {k: ruff["lint"][k] for k in RUFF_LINT_KEYS if isinstance(ruff.get("lint"), dict) and k in ruff["lint"]}
    return out, lint, "extend" in ruff


def ruff_floor(unit_abs):
    """Ger (TOML-text, fel om projektet försökt `extend`a en annan fil). Golvet är fristående: projektets
    vitlistade inställningar med mallens `select`, tomma `ignore` och per-file-ignores ovanpå."""
    top, lint, extends = project_ruff_settings(unit_abs)
    lint = {**lint, "select": RUFF_SELECT, "ignore": [], "per-file-ignores": {
        "**/tests/**": ["S101"], "**/test_*.py": ["S101"], "**/conftest.py": ["S101"]}}
    return dump_toml({**top, "lint": lint}) + "\n", extends


class ruff_config:
    """Skriver golvet i enhetens katalog, så att sökvägar i `exclude` och `src` räknas som i projektets
    egen fil, och tar bort det efteråt."""

    def __init__(self, unit_abs):
        self.unit_abs = Path(unit_abs)
        self.path = None

    def __enter__(self):
        text, _ = ruff_floor(self.unit_abs)
        fd, name = tempfile.mkstemp(prefix=".pb-ruff-", suffix=".toml", dir=str(self.unit_abs))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.path = name
        return name

    def __exit__(self, *exc):
        if self.path:
            Path(self.path).unlink(missing_ok=True)


def pyright_config(unit_abs, tmp):
    cfg = {"extends": str(Path(unit_abs) / "pyproject.toml"), "include": [str(unit_abs)],
           "typeCheckingMode": "strict", "enableTypeIgnoreComments": False,
           "reportIgnoreCommentWithoutRule": "error"}
    path = Path(tmp) / "pyrightconfig.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


# --- Kontroller som inte kör något verktyg --------------------------------------------------------------------

def check_config_files(root, unit):
    errors = []
    for name in FORBIDDEN_CONFIG_FILES:
        if (Path(root) / unit / name).is_file():
            errors.append("%s/%s: this configuration file is not read by the gate; put the settings in pyproject.toml (D8:32)" % (unit, name))
    return errors


def check_uv_config(root, unit):
    """Golvet för uv ligger i /etc/uv/uv.toml i imagen; projektets konfig får inte sätta samma nycklar (D8:29)."""
    errors = []
    for rel, extract in (("pyproject.toml", lambda d: d.get("tool", {}).get("uv", {})), ("uv.toml", lambda d: d)):
        f = Path(root) / unit / rel
        if not f.is_file():
            continue
        try:
            data = extract(tomllib.loads(f.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as e:
            errors.append("%s/%s: cannot parse: %s" % (unit, rel, e))
            continue
        for key in FORBIDDEN_UV_KEYS:
            if key in data:
                errors.append("%s/%s: %s must not be set by the project; the template's floor is in /etc/uv/uv.toml (D8:29)" % (unit, rel, key))
    return errors


DIRECTIVE_RUFF = re.compile(r"^\s*#\s*ruff\s*:\s*noqa\b", re.I)
DIRECTIVE_PYRIGHT = re.compile(r"#\s*pyright\s*:\s*(?P<what>.*)$")
PYRIGHT_OK = re.compile(r"^(strict\b|ignore\[[A-Za-z0-9_,\s]+\])")


def check_directives(root, unit):
    """Direktiv i koden som ändrar konfig är röda (D8:33): filomfattande `# ruff: noqa` och `# pyright:` utom
    `strict` och `ignore[regel]`."""
    errors = []
    for rel in tracked_python_files(root, unit):
        try:
            lines = (Path(root) / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            if DIRECTIVE_RUFF.match(line):
                errors.append("%s:%d: a file-wide '# ruff: noqa' is not allowed; suppress single lines with a code (D8:33)" % (rel, n))
            m = DIRECTIVE_PYRIGHT.search(line)
            if m and not PYRIGHT_OK.match(m.group("what").strip()):
                errors.append("%s:%d: '# pyright: %s' changes the configuration; only 'strict' and 'ignore[rule]' are allowed (D8:33)" % (rel, n, m.group("what").strip()[:30]))
    return errors


# --- Verktyg ----------------------------------------------------------------------------------------------------------

def ruff_check(root, unit, targets):
    ruff = need("ruff")
    errors = []
    with ruff_config(Path(root) / unit) as cfg:
        p = run([ruff, "check", "--config", cfg, "--no-cache", "--output-format", "concise", *targets], root)
        if p.returncode == 1:
            for ln in p.stdout.splitlines():
                m = re.match(r"^(\S+?):(\d+):\d+: (\S+)", ln)
                if m:
                    errors.append(ln)
                    record(ln, m.group(1), int(m.group(2)), m.group(3))
        elif p.returncode != 0:
            raise CannotRun("ruff check failed: %s" % (p.stderr or p.stdout).strip()[:200])
        p = run([ruff, "format", "--check", "--output-format", "json", "--config", cfg, "--no-cache", *targets], root)
        if p.returncode == 1:
            try:
                found = json.loads(p.stdout)
            except ValueError:
                raise CannotRun("ruff format did not return JSON")
            for d in found:
                if d.get("code") == "unformatted":
                    name = os.path.relpath(d["filename"], root)
                    errors.append("%s: would be reformatted; run: make fmt" % name)
                    record(errors[-1], name, 0, "format")
        elif p.returncode != 0:
            raise CannotRun("ruff format failed: %s" % (p.stderr or p.stdout).strip()[:200])
    return errors


def uv_sync(root, unit):
    """Installerar enhetens miljö i låst läge (D6:27). En föråldrad lås är ett fel i repot, inte i verktyget."""
    uv = need("uv")
    p = run([uv, "sync", "--locked", "--project", unit], root)
    if p.returncode == 0:
        return None
    msg = (p.stderr or p.stdout).strip()
    if any(s in msg for s in UV_LOCK_STALE):
        return ["%s/uv.lock: the lockfile is missing or out of date; run 'uv lock' and review the diff (%s)" % (unit, msg.splitlines()[-1][:80])]
    raise CannotRun("uv sync failed: %s" % msg[:200])


def pyright(root, unit, tmp):
    bp = need("basedpyright")
    py = Path(root) / unit / ".venv" / "bin" / "python"
    if not py.is_file():
        raise CannotRun("%s/.venv is missing; uv sync did not create the environment" % unit)
    cfg = pyright_config(Path(root) / unit, tmp)
    p = run([bp, "-p", cfg, "--outputjson", "--pythonpath", str(py)], root)
    if p.returncode not in (0, 1):
        raise CannotRun("basedpyright failed (exit %d): %s" % (p.returncode, (p.stderr or p.stdout).strip()[:200]))
    try:
        data = json.loads(p.stdout)
    except ValueError:
        raise CannotRun("basedpyright did not return JSON")
    errors = []
    for d in data.get("generalDiagnostics", []):
        if d.get("severity") != "error":
            continue
        rel = os.path.relpath(d["file"], root)
        line = d.get("range", {}).get("start", {}).get("line", 0) + 1
        errors.append("%s:%d: %s%s" % (rel, line, d.get("message", "").splitlines()[0], " (%s)" % d["rule"] if d.get("rule") else ""))
        record(errors[-1], rel, line, d.get("rule") or "error")
    return errors


def pytest(root, unit):
    err = uv_sync(root, unit)
    if err:
        return err
    uv = need("uv")
    p = run([uv, "run", "--locked", "--project", unit, "pytest", *PYTEST_NEUTRAL, "--tb=line", "-q", "--no-header", unit], root)
    out = (p.stdout + p.stderr).strip()
    if p.returncode == 0:
        return []
    if p.returncode == 5:
        return ["%s: no tests were collected; a unit needs at least one test (D5:8)" % unit]
    if p.returncode in (1, 2):
        lines = [ln for ln in out.splitlines() if re.match(r"^(/|[\w.-]+/)?[\w./-]+:\d+: ", ln) or ln.startswith(("FAILED", "ERROR"))]
        return lines or [ln for ln in out.splitlines()[-15:] if ln.strip()]
    raise CannotRun("pytest failed to run (exit %d): %s" % (p.returncode, out[-200:]))


# --- Ingångar ---------------------------------------------------------------------------------------------------------

def finish(errors):
    for e in errors:
        print(e)
    return 1 if errors else 0


def entry(fn):
    """Kör `fn(root, unit, files)` och översätter till exitkod. Fel som inte är kodfel ger 2."""
    if len(sys.argv) < 2:
        print("usage: <adapter> <unit path> [files...]")
        return 2
    root = Path(os.getcwd())
    try:
        return finish(fn(root, sys.argv[1].rstrip("/") or ".", sys.argv[2:]))
    except CannotRun as e:
        print(str(e))
        return 2


def do_lint(root, unit, files):
    errors = check_config_files(root, unit) + check_uv_config(root, unit) + check_directives(root, unit)
    if ruff_floor(Path(root) / unit)[1]:
        errors.append("%s/pyproject.toml: [tool.ruff] extend is not supported; put the settings in this file (D12:8)" % unit)
    errors += ruff_check(root, unit, [unit])
    with tempfile.TemporaryDirectory() as tmp:
        stale = uv_sync(root, unit)
        if stale:
            return errors + stale
        errors += pyright(root, unit, tmp)
    complete()
    return errors


def do_test(root, unit, files):
    return pytest(root, unit)


def do_fmt(root, unit, files):
    ruff = need("ruff")
    py = [f for f in files if f.endswith((".py", ".pyi")) and (root / f).is_file()]
    if not py:
        return []
    with ruff_config(Path(root) / unit) as cfg:
        for cmd in (["check", "--select", "I", "--fix", "--quiet"], ["format", "--quiet"]):
            p = run([ruff, *cmd, "--config", cfg, "--no-cache", *py], root)
            if p.returncode not in (0, 1):
                raise CannotRun("ruff %s failed: %s" % (cmd[0], (p.stderr or p.stdout).strip()[:200]))
    return []


def do_check_file(root, unit, files):
    py = [f for f in files if f.endswith((".py", ".pyi")) and (root / f).is_file()]
    if not py:
        return []
    return ruff_check(root, unit, py)
