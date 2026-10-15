"""Lokal secret scan med gitleaks (D6:26): alla commits från merge-basen till head, inline-undantag
ignoreras, undantag bara från `.gitleaks.toml` och `.gitleaksignore`, standardreglerna alltid på,
utdata maskerad och stängt fall vid varje exit-kod skild från noll."""
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from .common import CannotRun, Report, git

LEAK_EXIT = 7  # skild från gitleaks eget fel (1) så att ett fynd och ett krasch inte förväxlas


def find_gitleaks():
    exe = os.environ.get("PB_GITLEAKS") or shutil.which("gitleaks")
    if not exe:
        raise CannotRun("gitleaks not found (it is installed in the dev image, D8:9)")
    return exe


def merge_base(root):
    for base in ("origin/main", "main"):
        if git(root, "rev-parse", "--verify", "-q", base, check=False).returncode == 0:
            return git(root, "merge-base", base, "HEAD").strip()
    raise CannotRun("no main branch to compare against")


def check_config(root, rep):
    cfg = Path(root) / ".gitleaks.toml"
    if not cfg.is_file():
        return None
    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise CannotRun(".gitleaks.toml: cannot parse: %s" % e)
    if (data.get("extend") or {}).get("useDefault") is not True:
        rep.error(".gitleaks.toml", "must contain [extend] useDefault = true so the standard rules stay on (D6:26)")
    return cfg


def scan(root):
    rep = Report("secret-scan")
    exe = find_gitleaks()
    cfg = check_config(root, rep)
    if rep.errors:
        return rep
    mb = merge_base(root)
    if git(root, "rev-parse", "HEAD").strip() == mb:
        return rep  # inga nya commits
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        cmd = [exe, "git", "--log-opts=%s..HEAD" % mb, "--ignore-gitleaks-allow", "--redact", "--no-banner",
               "--exit-code", str(LEAK_EXIT), "--report-format", "json", "--report-path", report,
               "--gitleaks-ignore-path", str(root)]
        if cfg:
            cmd += ["--config", str(cfg)]
        p = subprocess.run(cmd + [str(root)], capture_output=True, text=True)
        if p.returncode == 0:
            return rep
        if p.returncode != LEAK_EXIT:
            raise CannotRun("gitleaks failed (exit %d): %s" % (p.returncode, (p.stderr or p.stdout).strip()[:200]))
        try:
            findings = json.loads(Path(report).read_text(encoding="utf-8") or "[]")
        except (OSError, ValueError):
            raise CannotRun("gitleaks reported leaks but the report could not be read")
    for f in findings:
        # Ingen maskerad eller omaskerad hemlighet skrivs ut, bara plats och regel.
        rep.error(f.get("File", "?"), "possible secret (%s) in commit %s; stop, rotate the key first (D6:26)" % (
            f.get("RuleID", "?"), (f.get("Commit") or "?")[:8]), f.get("StartLine") or None)
    if not rep.errors:
        rep.error("secret-scan", "gitleaks reported leaks")
    return rep
