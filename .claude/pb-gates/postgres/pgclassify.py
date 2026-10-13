"""Klassificering av den SQL som en migrering faktiskt körde (D8:28). Satserna kommer från
`pg_stat_statements` (normaliserade, med `$1`), så det som klassas är körd SQL och inte migreringsfiler:
det fångar även `RunPython`, DO-block och dynamisk `EXECUTE`.

Egna regler här: varje `DROP` och `ALTER … DROP` utom en kort lista som inte förstör data, `DELETE`,
`UPDATE`, `TRUNCATE` och läsning från apptabeller (som avslöjar databeroende logik som en tom databas inte
kör). Squawks fem regler för destruktiv DDL läggs till av `pgcheck.py`. Fallerar stängt: det som inte
känns igen som ofarligt är ofarligt bara om det står i listan."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# Migreringsverktygens bokföringstabeller: satser mot dem räknas inte (projektet kan utöka listan, D8:40).
DEFAULT_BOOKKEEPING = frozenset({
    "alembic_version", "django_migrations", "schema_migrations", "flyway_schema_history", "knex_migrations",
    "knex_migrations_lock", "__drizzle_migrations", "_prisma_migrations", "yoyo_migration", "yoyo_lock",
    "_sqlx_migrations", "goose_db_version", "schema_version", "databasechangelog", "databasechangeloglock",
})
SQUAWK_RULES = ("ban-drop-column", "ban-drop-table", "ban-drop-database", "changing-column-type", "ban-truncate-cascade")
DROP_OK = ("INDEX", "TRIGGER", "FUNCTION")  # `DROP <detta>` som statement förstör ingen data
ALTER_DROP_OK = ("CONSTRAINT", "DEFAULT")  # `ALTER … DROP CONSTRAINT` och `ALTER COLUMN … DROP DEFAULT`
READ_START = ("SELECT", "WITH", "INSERT", "COPY")
RELATION_LOOSE = re.compile(r'\b(?:FROM|JOIN)\s+(?:ONLY\s+)?((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\.(?:"[^"]+"|[A-Za-z_][\w$]*))?)(\s*\()?', re.I)
CTE = re.compile(r'\b([A-Za-z_][\w$]*)\s+AS\s*(?:NOT\s+MATERIALIZED\s*|MATERIALIZED\s*)?\(', re.I)


def normalize(sql):
    """Utan kommentarer, med kollapsat blanktecken och utan avslutande semikolon."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()


def _relations(sql):
    """Tabellnamn (utan schema, gemener) som satsen läser via FROM och JOIN, utan funktionsanrop och CTE:er."""
    ctes = {m.group(1).lower() for m in CTE.finditer(sql)}
    out = []
    for m in RELATION_LOOSE.finditer(sql):
        if m.group(2):  # funktionsanrop: FROM generate_series(…)
            continue
        name = m.group(1).split(".")[-1].strip('"').lower()
        schema = m.group(1).split(".")[0].strip('"').lower() if "." in m.group(1) else ""
        if schema in ("pg_catalog", "information_schema") or name.startswith("pg_") or name in ctes:
            continue
        out.append(name)
    return out


def classify(sql, bookkeeping=frozenset()):
    """Ger en lista `(regel, skäl)` för en normaliserad sats; tom lista betyder ofarlig."""
    s = normalize(sql)
    up = s.upper()
    book = DEFAULT_BOOKKEEPING | {b.lower() for b in bookkeeping}
    found = []
    if up.startswith("DROP"):
        words = up.split()
        kind = words[1] if len(words) > 1 else ""
        if kind not in DROP_OK:
            found.append(("drop", "DROP %s destroys an object and its data" % kind))
    elif up.startswith("ALTER"):
        for m in re.finditer(r"\bDROP\b\s+(\w+)", up):
            if m.group(1) not in ALTER_DROP_OK:
                found.append(("alter-drop", "ALTER … DROP %s removes data or a guarantee" % m.group(1)))
                break
    elif up.startswith("DELETE"):
        found.append(("delete", "DELETE removes rows"))
    elif up.startswith("UPDATE"):
        found.append(("update", "UPDATE rewrites rows (a backfill counts, D8:28)"))
    elif up.startswith("TRUNCATE"):
        found.append(("truncate", "TRUNCATE removes all rows"))
    if not found and up.startswith(READ_START):
        tables = [t for t in _relations(s) if t not in book]
        if tables:
            found.append(("reads-app-table", "reads from %s: logic that depends on data an empty database does not run" % ", ".join(sorted(set(tables)))))
    return found


def squawk(statements):
    """Squawks fem regler för destruktiv DDL över satserna; ger `(index, regel)`. Kunde inte köras -> RuntimeError."""
    exe = shutil.which("squawk")
    if not exe:
        raise RuntimeError("squawk not found (it is installed in the ci image by the postgres module)")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "statements.sql"
        # en sats per rad, så att Squawks radnummer är satsens index
        f.write_text("\n".join(normalize(s) + ";" for s in statements) + "\n", encoding="utf-8")
        p = subprocess.run([exe, "--reporter", "json", str(f)], capture_output=True, text=True)
    if p.returncode not in (0, 1):
        raise RuntimeError("squawk failed (exit %d): %s" % (p.returncode, (p.stderr or p.stdout).strip()[:200]))
    try:
        findings = json.loads(p.stdout or "[]")
    except ValueError:
        raise RuntimeError("squawk did not return JSON")
    return [(f["line"], f["rule_name"]) for f in findings if f.get("rule_name") in SQUAWK_RULES]
