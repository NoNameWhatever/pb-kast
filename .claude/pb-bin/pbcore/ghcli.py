"""Tunt gränssnitt mot `gh`. Fel från `gh` skiljs från skriptens egna vägran (D5:20)."""
import json
import subprocess

from .common import CannotRun


class GhError(CannotRun):
    """`gh` (eller nätet) misslyckades. Är inte en vägran från skriptet."""


class Gh:
    def __init__(self, root, exe="gh"):
        self.root, self.exe = root, exe

    def raw(self, *args, ok_codes=(0,)):
        try:
            p = subprocess.run([self.exe, *map(str, args)], cwd=str(self.root), capture_output=True, text=True)
        except FileNotFoundError:
            raise GhError("gh is not installed")
        # En nollskild exitkod som är tillåten (till exempel 1 eller 8 för `gh pr checks` med röda eller
        # väntande checkar) räknas bara om `gh` också gav utdata; annars är det ett fel.
        if p.returncode not in ok_codes or (p.returncode != 0 and not p.stdout.strip()):
            raise GhError("gh %s failed: %s" % (" ".join(map(str, args[:3])), (p.stderr or p.stdout).strip()[:300]))
        return p.stdout

    def json(self, *args, ok_codes=(0,)):
        out = self.raw(*args, ok_codes=ok_codes)
        try:
            return json.loads(out or "null")
        except ValueError:
            raise GhError("gh %s returned invalid JSON" % " ".join(map(str, args[:3])))
