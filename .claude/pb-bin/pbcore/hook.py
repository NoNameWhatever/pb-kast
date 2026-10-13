"""Återkopplingshooken (D11:10): lint och format av en nyss ändrad fil, med modulens adapter i
enfilsläge (`.claude/pb-gates/<modul>/check-file <enhet> <fil>`). Hooken ändrar aldrig något och
fallerar öppet: fel som inte är ett lint- eller formatfel ger ingen återkoppling, grinden bär kravet."""
import json
import os
import subprocess
from pathlib import Path

from .common import CannotRun, repo_root
from .gate import load_units

TIMEOUT_SECONDS = 15
MAX_LINES = 10


def feedback(payload, timeout=TIMEOUT_SECONDS):
    """Ger den text som ska återkopplas till agenten, eller None."""
    fp = (payload.get("tool_input") or {}).get("file_path")
    if not fp:
        return None
    try:
        root = repo_root(payload.get("cwd") or os.getcwd())
        rel = os.path.relpath(os.path.realpath(fp), os.path.realpath(root))
        if rel.startswith(".."):
            return None
        units = load_units(root)
    except (CannotRun, OSError):
        return None
    mine = [u for u in units if u["path"] in (".", "") or rel == u["path"] or rel.startswith(u["path"].rstrip("/") + "/")]
    if not mine:
        return None
    unit = max(mine, key=lambda u: len(u["path"]))
    adapter = Path(root) / ".claude" / "pb-gates" / unit["module"] / "check-file"
    if not adapter.is_file():
        return None
    try:
        p = subprocess.run([str(adapter), unit["path"], rel], cwd=str(root), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p.returncode != 1:
        return None
    lines = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()][:MAX_LINES]
    return "\n".join(lines + ["Formatfel rättas med: make fmt FILES=%s" % rel])


def run(stdin_text, out=print):
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        return 0
    msg = feedback(payload)
    if msg:
        out(json.dumps({"decision": "block", "reason": msg}))
    return 0
