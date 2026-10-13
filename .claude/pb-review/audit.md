# Säkerhetsgenomgång av hela kodbasen

Uppdraget är `genomgång <enhet|tvärgående> <sha>`. Granska kodbasen som den är vid `<sha>`, inte en diff. Läs modulfilerna i katalogen som hör till enheten.

Det som inte syns i en diff:
- Ingångar (routes, handlers, jobb, CLI) och hur var och en kontrollerar identitet och behörighet.
- Platser där data används riskabelt (SQL, shell, filsökväg, mallar, deserialisering, utgående anrop) och varifrån datan kommer.
- Secrets och känslig data i kod, fixtures och loggning.
- Hotmodellen mot koden.
- Om undertryckningar och baslinjeposter för säkerhetsregler fortfarande är motiverade.
- Projektets egna workflows.
- Öppna Dependabot alerts och oanvända beroenden.

Vid `tvärgående`: workflows, compose, `.devcontainer/` och hotmodellen.

Stil och det lint redan hittar ingår inte. Redovisa under `Coverage` vad som granskats och inte, särskilt om enheten var för stor för en kontext.
