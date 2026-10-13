# pb-merge

- Merge sker bara via `.claude/pb-bin/pb-merge <PR>`, på användarens uttryckliga kommando. Aldrig `gh pr merge`, `--admin` eller `--auto`, och aldrig `git push` till `main`, inte heller av en PR-head: en push av en grön PR-head räknas som merge och går förbi skriptet.
- Skriptet kontrollerar `Closes #N` mot `issue:` i issue-filen, vägrar `explore/*` och röda eller saknade checkar, mergar med squash och städar grenar. Stannar det, rapportera skälet; kringgå det inte.
- Du stänger inga issues; GitHub gör det via `Closes`. Efter merge börjar nästa arbete från ren main.
