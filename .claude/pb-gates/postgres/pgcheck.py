"""Checken för destruktiva migrationer (D8:28, D6:39). Körs som steg i modulens integrationsjobb för varje
merge-kandidat, oavsett vilka sökvägar som ändrats:

  1. merge-basens migrationer körs mot en tom databas,
  2. statistiken i `pg_stat_statements` nollställs,
  3. PR:ens migrationer körs med projektets migreringskommando (`.claude/pb-postgres.yml`),
  4. de fångade satserna klassas (pgclassify.py, plus Squawks fem regler),
  5. ett fynd är rött om inte issue-filen har `level: strict` och `destructive: true` (D6:39).

Kunde inte köras (exit 2): databasen nås inte, sidecaren är fel konfigurerad, poster har kastats ur
statistiken (`dealloc`), migreringskommandot saknas eller misslyckas, eller Squawk saknas."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "pb-bin"))

import pgclassify  # noqa: E402
from pbcore.common import GitRef, changed_paths, git, glob_regex, parse_front_matter  # noqa: E402
from pbcore.pr import issue_files  # noqa: E402

CONFIG = ".claude/pb-postgres.yml"
MIGRATION_PATTERNS = ("**/migrations/**", "**/alembic/**", "**/*.sql")
MIGRATE_TIMEOUT = 900


class CannotRun(Exception):
    pass


def load_config(text, where):
    if text is None:
        raise CannotRun("%s is missing at %s (the postgres module ships it as a skeleton, D8:40)" % (CONFIG, where))
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise CannotRun("%s cannot be parsed: %s" % (CONFIG, e))
    migrate = data.get("migrate")
    book = data.get("bookkeeping_tables") or []
    if not isinstance(migrate, str) or not migrate.strip():
        raise CannotRun("%s: migrate: must be a command or 'none'" % CONFIG)
    if not isinstance(book, list):
        raise CannotRun("%s: bookkeeping_tables: must be a list" % CONFIG)
    return migrate.strip(), [str(b) for b in book]


class Db:
    def __init__(self, url):
        self.url = url
        u = urlparse(url)
        self.env = {"DATABASE_URL": url, "PGHOST": u.hostname or "localhost", "PGPORT": str(u.port or 5432),
                    "PGUSER": unquote(u.username or ""), "PGPASSWORD": unquote(u.password or ""),
                    "PGDATABASE": (u.path or "/").lstrip("/")}

    def query(self, sql):
        if not shutil.which("psql"):
            raise CannotRun("psql not found (it is installed in the ci image by the postgres module)")
        p = subprocess.run(["psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", self.url, "-c", sql], capture_output=True, text=True,
                           env={**os.environ, **self.env})
        if p.returncode != 0:
            raise CannotRun("the database could not be queried: %s" % (p.stderr.strip().splitlines() or ["psql failed"])[-1][:160])
        return p.stdout.strip()


def verify_statistics(db):
    """Sidecaren och CI:s service-container ska ha samma preload (D8:22); annars ger checken falskt grönt."""
    db.query("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    for setting, want in (("pg_stat_statements.track", "all"), ("pg_stat_statements.track_utility", "on")):
        got = db.query("SHOW %s" % setting)
        if got != want:
            raise CannotRun("%s is '%s' but must be '%s'; the database was not started with the module's command (D8:22)" % (setting, got, want))
    try:
        db.query("SELECT count(*) FROM pg_stat_statements")
    except CannotRun:
        raise CannotRun("pg_stat_statements is not loaded; start the database with shared_preload_libraries=pg_stat_statements (D8:22)")


def run_migrate(command, cwd, db, label):
    p = subprocess.run(["sh", "-c", command], cwd=str(cwd), capture_output=True, text=True, timeout=MIGRATE_TIMEOUT,
                       env={**os.environ, **db.env})
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        raise CannotRun("the migration command failed on %s (exit %d): %s" % (label, p.returncode, " | ".join(tail)[:240]))


def captured_statements(db):
    raw = db.query("SELECT coalesce(json_agg(query ORDER BY query), '[]') FROM pg_stat_statements "
                   "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                   "AND query NOT ILIKE '%pg_stat_statements%'")
    dealloc = db.query("SELECT dealloc FROM pg_stat_statements_info")
    if dealloc != "0":
        raise CannotRun("%s statements were evicted from pg_stat_statements (dealloc); raise pg_stat_statements.max in the module's command (D8:28)" % dealloc)
    return json.loads(raw)


def check_none(root, head_ref):
    """`migrate: none` är tillåtet så länge ingen spårad fil matchar migrationsmönstren (D8:40)."""
    rxs = [glob_regex(p) for p in MIGRATION_PATTERNS]
    hits = [f for f in GitRef(root, head_ref).ls_files() if any(rx.match(f) for rx in rxs)]
    return ["%s: a migration file exists but %s says migrate: none; set the migration command (D8:40)" % (f, CONFIG) for f in hits[:20]]


def plan_of_pr(root, base_ref, head_ref):
    files = issue_files(changed_paths(root, base_ref, head_ref))
    if len(files) != 1:
        return None, None
    fm = parse_front_matter(GitRef(root, head_ref).read(files[0]))[0] or {}
    return fm.get("level"), fm.get("destructive")


def run_check(root, base_ref, head_ref, database_url):
    """Ger (fel, anteckning). Kastar CannotRun när kontrollen inte kan avgöra något."""
    root = Path(root)
    head_cfg = load_config(GitRef(root, head_ref).read(CONFIG), head_ref)
    if head_cfg[0].lower() == "none":
        return check_none(root, head_ref), "no migration command (migrate: none) and no migration files"
    if not database_url:
        raise CannotRun("no database: set DATABASE_URL (the integration job's service container)")
    db = Db(database_url)
    verify_statistics(db)

    mb = git(root, "merge-base", base_ref, head_ref).strip()
    base_cfg = load_config(GitRef(root, mb).read(CONFIG), "the merge base") if GitRef(root, mb).read(CONFIG) is not None else ("none", [])
    if base_cfg[0].lower() != "none":
        wt = tempfile.mkdtemp(prefix="pb-base-")
        try:
            git(root, "worktree", "add", "--detach", wt, mb)
            run_migrate(base_cfg[0], wt, db, "the merge base")
        finally:
            git(root, "worktree", "remove", "--force", wt, check=False)
    db.query("SELECT pg_stat_statements_reset()")
    run_migrate(head_cfg[0], root, db, "the PR")
    statements = captured_statements(db)

    flagged = []
    for stmt in statements:
        for rule, why in pgclassify.classify(stmt, head_cfg[1]):
            flagged.append((rule, why, stmt))
    try:
        for idx, rule in pgclassify.squawk(statements):
            if not any(s == statements[idx] and r == rule for r, _, s in flagged):
                flagged.append((rule, "Squawk: %s" % rule, statements[idx]))
    except RuntimeError as e:
        raise CannotRun(str(e))

    level, destructive = plan_of_pr(root, base_ref, head_ref)
    if not flagged:
        return [], "%d statements from the PR's migrations, none destructive" % len(statements)
    if level == "strict" and destructive is True:
        return [], "%d destructive statement(s) covered by destructive: true" % len(flagged)
    errors = []
    for rule, why, stmt in flagged[:30]:
        errors.append("migrations: %s: %s [%s]" % (rule, pgclassify.normalize(stmt)[:110], why))
    errors.append("migrations: %d flagged statement(s) but the issue file is not level: strict with destructive: true (D6:39)" % len(flagged))
    return errors, ""
