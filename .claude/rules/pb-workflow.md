# pb-workflow

Prefixet `pb-` betyder "project base": filer med det ägs av mallen och handredigeras aldrig. Behöver en mallfil ändras, stanna och säg det. Sökvägar och fältnamn som checkar läser är engelska.

## Start och orientering
- Kör `.claude/pb-bin/pb-start` först i varje session och efter `/clear`, och läs bara dess utdata. STOPP: rapportera och vänta. INFO: nämn kort. OKÄNT: redovisa med orsak. Saknas eller kraschar skriptet: säg det och vänta. Starta i projektroten: projektets `.claude/settings.json` läses inte från en undermapp.
- Läs per uppgift: issue-filen, kärnan i `project-docs/architecture.md`, de områdesfiler den pekar ut och de delar av `product.md` som `source` pekar på. Läs inte `issues/done/`. Vid återupptagning: `git log main..HEAD --oneline`, kroppen i senaste commiten (`Läge:`) och PR-kommentarerna.
- Delegera bred sökning (okänd kod, flera tänkbara ställen) till `pb-explorer`, aldrig en uppslagning som en Grep klarar. Läs själv de utpekade intervallen innan något ändras.
- Läs intervall efter en Grep, inte hela stora filer. Orienteringen är klar när du kan namnge filerna som ska ändras och testet som visar kriteriet; då börjar TDD. Läs inte om en fil som är oförändrad i kontexten.
- Innan kod i en enhet i `.claude/units.yml` ändras: läs modulens fil i `.claude/pb-guides/`.

## Issue, nivå och plan
- Varje ändring har `project-docs/issues/N-slug.md` (N = GitHub-issuens nummer) och grenen `N-slug`. Front matter: `issue: N`, `level: standard|strict`, valfritt `type: hygiene|bug|security` och `parent:`, `destructive: true|false` (krävs vid strict). Rubriker: `Goal`, `Acceptance criteria` (varje kriterium med `source`: användarens ord eller en sökväg i projektdokumenten), `Out of scope`, `Test plan` (utom hygiene och security), `Criteria changes` (datum och skäl). Strict har dessutom `Plan`, `Risk` (vad händer om ändringen är fel, inklusive det en revert inte återställer) och `Security`.
- Nivån är den högsta av de ändrade filernas nivåer i sökvägskartan och kan bara höjas. Strict: behörigheter och identitet, secrets och krypto, beständig data, extern exponering, beroenden, säkerhetsnätet självt (CI, grindar, hooks, behörigheter, kartan). Planera nivån och stanna om ändringen berör en högre.
- Standard: issue-filen är första commit. Visa mål, kriterier och testplan i chatten (högst ca 10 rader) och vänta på användarens OK före kod. Strict: plan-PR med bara issue-filen och `Refs #N` (inte `Closes`, issuen ska stå öppen), granskad av `pb-reviewer`, som användaren mergar via `pb-merge` före koden. `Security`: svara bara på frågorna som berör ändringen, med sökväg eller beteende per svar (frågorna: `pb-guides/strict-plan.md`).
- Kan du inte skriva kriterier: stanna och föreslå utforskning på `explore/<slug>` (mockdata, mergas aldrig).

## Stoppvillkor
Stanna och rapportera när (1) ändringen berör högre nivå än planerad, (2) det som räknas som klart måste ändras (föreslå, användaren beslutar), (3) grönt kräver att ett test, en grind eller en tröskel försvagas eller stängs av (även lint- och typkonfig), (4) du fastnat efter 3 försök på samma fel, (5) ett beslut är användarens: produkt, arkitektur, säkerhet, data, kostnad, behörigheter, eller en konflikt i en mallägd fil. Reversibla lågriskbeslut fattar du själv och noterar under `Deviations:`.

## Arbetssätt
- TDD är standard och testtäckningen löpande; nya testfall vid luckor är ingen avvikelse. En PR har ett syfte och högst ca 400 ändrade rader (lock- och genererade filer och tester undantagna); dela annars. Stora ändringar går per issue mot main: inkopplingen sist, delad infrastruktur först, destruktiva steg som expand, migrate, contract.
- Grindarna körs via `make test|lint|run|check|fmt` eller `.claude/pb-bin/`, aldrig via råa verktyg. Läs `.pb-logs/gate.log` med Grep eller intervall. Kör `make check` (rymmer secret scan) före varje push och stanna vid fynd.
- Pausar du mitt i en issue: committa med ett block `Läge:` i kroppen (högst 5 rader: klart, nästa steg, prövat och förkastat). Föreslå `/clear` när planen är mergad, PR:en öppnad, issuen mergad eller ett kriterium är klart och committat.
- PR-kroppen har raderna `Closes #N` (ett nyckelord per issue: `Closes #1, closes #2`), `Docs:`, `Deviations:` (eller `none`), `Tests:` (ändrade, raderade eller överhoppade tester med sökväg och motivering, eller `none`), `Review:` (reviewerns sammanfattning oförändrad och ditt svar per fynd) och vid `type: bug` `Regression test:` (rutin: `pb-guides/regression-test.md`).
- Granskning: `pb-reviewer` vid strict, både plan-PR och kod-PR, `pb-reviewer-standard` vid standard, efter gröna grindar och före användarens merge. Delegera med bara PR-numret.

## Beroenden, data, workflows
- Skriv aldrig versionsnummer ur minnet. Verifiera paketnamn mot officiell källa. Inga prereleases, forkar eller alternativa register utan motivering i planen. Installera aldrig på hosten. Ändrade beroenden är strict (plan: `pb-guides/dependency-plan.md`).
- Migrationer ska fungera med den kod som senast deployades; namnbyten som expand/contract; ett destruktivt steg körs aldrig vid deploy. Revert av strict: `pb-guides/revert-plan.md`.
- Ändringar i `.github/workflows/` kan du inte pusha. Pusha först allt annat på grenen, lägg workflowändringen i egna commits och lämna den som patch: `rm -rf .git/pb-patch && git format-patch --base=origin/<gren> -o .git/pb-patch origin/<gren>..HEAD`, och stanna med grenens namn. När användaren pushat: på rent träd `git fetch origin && git reset --hard origin/<gren>` och `rm -rf .git/pb-patch`. Begär containeråtgärder med exakt kommando och ändrade host-körda filer; du startar eller bygger aldrig containrar. Mallupdate: strict, plan i `pb-guides/template-update-plan.md`.
