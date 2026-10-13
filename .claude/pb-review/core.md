# Kodgranskning (strict)

Läs den här filen och de modulfiler i katalogen som hör till modulerna diffen rör.

## Alltid
- Diffen mot den godkända planen på main: scope och oplanerade sökvägar.
- Testernas täckning av kriterier och felvägar.
- `Security` mot implementationen.
- Revert-bedömningen under `Risk`, inklusive kompatibilitet med föregående deployade kod och `destructive:`.
- Att hotmodellen följer med när en förtroendegräns eller angreppsyta ändras.
- Vid `type: bug`: att regressionstestet prövar felvägen och inte bara den nya koden.

## Bara de områden diffen rör
- Identitet och behörighet: authn, authz, sessioner.
- Input: injection, XSS, SSRF, validering.
- Filer och processer: path traversal, kommandoexekvering.
- Beständig data: kompatibilitet, destruktiva steg, backup.
- Beroenden: skript, källor, underhållsläge.
- Loggning och fel: känslig data.
- Host-körda filer: `.devcontainer/`, compose, Dockerfile.
