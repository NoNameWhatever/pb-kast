"""Kodenheter (D8:2): `.claude/units.yml` med `units: [{path, module}]` och `exclude:`."""
from pathlib import Path

import yaml

from .common import CannotRun


def load(root):
    f = Path(root) / ".claude" / "units.yml"
    if not f.is_file():
        return [], []
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise CannotRun(".claude/units.yml: cannot parse: %s" % e)
    units = data.get("units") or []
    for u in units:
        if not isinstance(u, dict) or not u.get("path") or not u.get("module"):
            raise CannotRun(".claude/units.yml: every unit needs path: and module:")
    exclude = data.get("exclude") or []
    if not isinstance(exclude, list):
        raise CannotRun(".claude/units.yml: exclude: must be a list")
    return units, [str(e) for e in exclude]


def load_units(root):
    return load(root)[0]
