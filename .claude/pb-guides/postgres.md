# postgres-modulen: läs före ändringar i schema eller migreringar

Bara det som inte kan bli en grind. Checken `postgres-migrations` körs i CI för PR:er som inte är utkast.

- Migreringar rullas bara framåt och ska fungera med koden som senast deployades (rollback-målet, D6:37). En
  `down`-migrering räknas aldrig som rollback-plan. Nya kolumner är nullable eller har default. Namnbyten görs som
  expand/contract: lägg till, migrera data, ta bort i ett eget, sent steg när ingen kan behöva det gamla.
- Checken läser den SQL som faktiskt körs. Den flaggar varje `DROP` (utom index, constraint, default, trigger,
  funktion), `DELETE`, `UPDATE`, `TRUNCATE`, typändring och läsning från apptabeller. Varje `UPDATE` flaggas,
  även en backfill till en ny kolumn. En flaggad sats kräver en strict-issue med `destructive: true` och rubriken
  `Backup and restore`; annars är checken röd.
- Migreringskommandot står i `.claude/pb-postgres.yml`. `migrate: none` är bara tillåtet utan migreringsfiler.
  Lägg migreringsverktygets egna tabeller i `bookkeeping_tables:` om de inte redan är kända.
- Integrationstester går mot sidecaren (`postgres`) med isolering per test: en egen databas eller ett eget schema
  per test. Tester startar aldrig containrar (D6:14).
- Databasen körs med `pg_stat_statements` förladdad, och sidecarns lösenord är ingen secret. Riktiga dev-nycklar
  ligger bara i `.env`.
- Ett datavolymsteg som inte går att ångra körs aldrig vid deploy, utan som ett separat steg efter backup (D6:38).
