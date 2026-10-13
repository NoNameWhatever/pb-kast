# Plangranskning (strict)

Gäller en PR som bara rör `project-docs/issues/`.

- Kriterierna går att testa, och `source` säger det kriteriet påstår. Läs källan.
- Antaganden om befintlig kod stämmer. Kontrollera med Grep och Read.
- Planen täcker kriterierna och inget mer, och ryms i en PR (högst ca 400 rader). Annars ska ändringen delas.
- Frågor under `Security` som borde vara besvarade är besvarade.
- `Risk` anger vad som händer om ändringen är fel, inklusive det en revert inte återställer, och `destructive:` stämmer.
- `Test plan` visar vilket test som prövar varje kriterium och vilka felvägar som testas.
- Inga konflikter med `architecture.md`, ADR:er eller hotmodellen.
