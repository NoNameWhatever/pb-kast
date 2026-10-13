# Beroendeplan

Ändrade eller nya beroenden är strict. Planen (under `Plan` i issue-filen) anger:

- Paket och officiell källa.
- Varför, och om det går utan nytt beroende.
- Om installationsskript krävs. Skript är avstängda som standard och tillåts ett i taget i allowlisten.
- Underhållsläge: senaste release och antal maintainers.
- Kända sårbarheter i vald version, med OSV som källa.

Versionsnummer skrivs aldrig ur minnet; resolvern väljer. Cooldownen (minst 7 dagar gammal version) gäller. Ett undantag för en brådskande säkerhetspatch kräver en strict-issue med motivering.
