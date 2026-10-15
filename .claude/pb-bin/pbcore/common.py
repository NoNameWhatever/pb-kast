"""Delade hjälpmedel för kärnans kontroller: utdatakontrakt (D5:32), git-källor,
front matter, rubriker och sökvägskartan (D5:15). Bara standardbiblioteket och PyYAML."""
import os
import re
import subprocess
from pathlib import Path

import yaml

EXIT_OK, EXIT_FAIL, EXIT_UNKNOWN = 0, 1, 2
MAX_SHOWN = 40
LOG_REL = ".pb-logs/gate.log"
LEVELS = {"standard": 0, "strict": 1}


class CannotRun(Exception):
    """Kontrollen kunde inte köras (motsvarar OKÄNT, D6:3). Ger exitkod 2."""


def git(root, *args, check=True):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise CannotRun("git %s: %s" % (" ".join(args), p.stderr.strip() or "exit %d" % p.returncode))
    return p.stdout if check else p


def repo_root(start="."):
    p = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if p.returncode != 0:
        raise CannotRun("not inside a git repository")
    return Path(p.stdout.strip())


class Report:
    """En kontrolls resultat. Grönt: en rad. Rött: bara felen som `fil:rad meddelande`,
    högst MAX_SHOWN rader och sist en sammanfattning med sökväg till hela loggen."""

    def __init__(self, name):
        self.name = name
        self.errors = []

    def error(self, path, message, line=None):
        self.errors.append("%s%s: %s" % (path, ":%d" % line if line else "", message))

    def emit(self, root, out=print):
        log = Path(root) / LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(self.errors) if self.errors else "ok %s" % self.name
        with open(log, "a" if os.environ.get("PB_LOG_APPEND") else "w", encoding="utf-8") as f:
            f.write(text + "\n")
        if not self.errors:
            out("ok %s" % self.name)
            return EXIT_OK
        for line in self.errors[:MAX_SHOWN]:
            out(line)
        out("%s: %d error(s); full log: %s" % (self.name, len(self.errors), LOG_REL))
        return EXIT_FAIL


# --- Källor: arbetsträdet eller en git-ref, med samma gränssnitt ---------------------

class WorkTree:
    def __init__(self, root):
        self.root = Path(root)

    def read(self, path):
        f = self.root / path
        return f.read_text(encoding="utf-8") if f.is_file() else None

    def listdir(self, path):
        d = self.root / path
        return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []

    def ls_files(self):
        return [p for p in git(self.root, "ls-files", "-z").split("\0") if p]


class GitRef:
    def __init__(self, root, ref):
        self.root, self.ref = Path(root), ref

    def read(self, path):
        p = git(self.root, "show", "%s:%s" % (self.ref, path), check=False)
        return p.stdout if p.returncode == 0 else None

    def listdir(self, path):
        p = git(self.root, "ls-tree", "--name-only", self.ref, path.rstrip("/") + "/", check=False)
        if p.returncode != 0:
            return []
        return sorted(os.path.basename(x) for x in p.stdout.splitlines() if x)

    def ls_files(self):
        return [p for p in git(self.root, "ls-tree", "-r", "-z", "--name-only", self.ref).split("\0") if p]


# --- Front matter och rubriker ---------------------------------------------------------

def parse_front_matter(text):
    """Ger (dict eller None, brödtext, radnummer där brödtexten börjar)."""
    m = re.match(r"---\n(.*?)\n---[ \t]*(?:\n|$)", text or "", re.S)
    if not m:
        return None, text or "", 1
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, text, 1
    if not isinstance(data, dict):
        return None, text, 1
    return data, text[m.end():], text[:m.end()].count("\n") + 1


def sections(body):
    """Rubrik (text efter #) -> avsnittets text. Samma rubrik två gånger: den sista gäller."""
    out, name, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"#{1,6}\s+(.+?)\s*$", line)
        if m:
            if name is not None:
                out[name] = "\n".join(buf).strip()
            name, buf = m.group(1), []
        elif name is not None:
            buf.append(line)
    if name is not None:
        out[name] = "\n".join(buf).strip()
    return out


# --- Sökvägskartan (D5:15) ------------------------------------------------------------------

def glob_regex(pattern):
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


class PathMap:
    def __init__(self):
        self.roots = {}
        self.patterns = []  # (regex, level)

    def add(self, data, origin="path map"):
        if not isinstance(data, dict):
            raise CannotRun("%s: expected a mapping" % origin)
        for section, target in (("roots", None), ("patterns", None)):
            v = data.get(section) or {}
            if not isinstance(v, dict):
                raise CannotRun("%s: %s must be a mapping" % (origin, section))
            for key, level in v.items():
                if level not in LEVELS:
                    raise CannotRun("%s: %s: invalid level %r (use strict or standard)" % (origin, key, level))
                if section == "roots":
                    self.roots[key] = max(self.roots.get(key, level), level, key=LEVELS.get)
                else:
                    self.patterns.append((glob_regex(key), level))

    def level(self, path):
        """Högsta matchande nivå över alla kartfiler (max-wins). Okänd sökväg är standard."""
        best = "standard"
        first = path.split("/", 1)[0]
        cands = []
        if "/" in path and first in self.roots:
            cands.append(self.roots[first])
        cands += [lv for rx, lv in self.patterns if rx.match(path)]
        for lv in cands:
            if LEVELS[lv] > LEVELS[best]:
                best = lv
        return best


def load_path_map(src):
    pm = PathMap()
    d = ".claude/pb-path-map"
    files = [d + "/" + n for n in src.listdir(d) if n.endswith(".yml")]
    if not files:
        raise CannotRun("no path map found under %s" % d)
    files.append(".claude/path-map-project.yml")
    for f in files:
        text = src.read(f)
        if text is None:
            continue
        try:
            pm.add(yaml.safe_load(text) or {}, f)
        except yaml.YAMLError as e:
            raise CannotRun("%s: cannot parse: %s" % (f, e))
    return pm


def changed_paths(root, base, head):
    """(status, sökväg, gammal sökväg eller None) mot merge-basen. Rename ger båda sökvägarna."""
    mb = git(root, "merge-base", base, head).strip()
    out = git(root, "diff", "--name-status", "-M", "-z", mb, head).split("\0")
    res, i = [], 0
    while i < len(out) and out[i]:
        st = out[i]
        if st[0] in "RC":
            res.append((st[0], out[i + 2], out[i + 1]))
            i += 3
        else:
            res.append((st[0], out[i + 1], None))
            i += 2
    return res
