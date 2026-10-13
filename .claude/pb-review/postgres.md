# postgres-modulens tillägg till kodgranskningen

Läses tillsammans med `core.md` när diffen rör migreringar, schema eller SQL.

- Fungerar migreringen med koden som senast deployades? Nya `NOT NULL`-kolumner utan default, borttagna eller
  omdöpta kolumner och ändrade typer bryter rollback-målet (D6:37).
- Stämmer `destructive:` i issue-filen med de flaggade satserna i checkens utdata, och finns backup och
  återställning med provdatum under `Backup and restore`?
- Lås: `CREATE INDEX` utan `CONCURRENTLY` på stora tabeller, `ALTER TABLE` som skriver om tabellen, långa
  transaktioner.
- Backfills: körs de i batchar, och är de idempotenta om de avbryts?
- SQL byggd med strängsammanfogning i migreringar och kod (injection), `GRANT` som ger bredare rätt än behövs.
- Tester: isolering per test, och att testerna inte delar tillstånd mellan databaser.
