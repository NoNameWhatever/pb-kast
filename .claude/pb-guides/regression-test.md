# Regressionstest vid buggrättning (`type: bug`)

1. Skriv testet först och kör det mot oförändrad kod.
2. Det ska falla på en assertion, inte på import eller insamling. Annars är testet fel.
3. Gör rättelsen. Testet ska nu vara grönt.
4. Låt testet ligga kvar i sviten. Markera det inte som överhoppat och ta inte bort det för att få grönt; en skip-markör eller raderad testfil måste stå under `Tester:` (minimal testcheck).

PR-raden `Regression test:` är antingen `<testfil>::<testnamn> – fell on base: <en rad felutdata>` eller `none – <reason>`. En namngiven testfil måste vara ändrad i PR:en.

PR:en lägger också till en post i `project-docs/failures/`. Fältet `introduced-by:` (`"#123"` inom citattecken, annars är `#` en YAML-kommentar, eller `unknown`) är valfritt.
