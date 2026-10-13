# demo

Skelettfil: projektets egen efter första genereringen. Mallens regler laddas separat från `.claude/rules/pb-*.md`.

## Stack

- Python: uv, Ruff, basedpyright och pytest. Kodenhet: `backend/`. Läs `.claude/pb-guides/python.md` före kod där.
- Postgres: sidecar `postgres` med `pg_stat_statements`. Läs `.claude/pb-guides/postgres.md` före ändringar i schema eller migreringar.


## Start

Starta sessionen inne i containern via startskriptet, och i projektroten. Projektets egna regler i `.claude/settings.json` läses bara från startkatalogen och ärvs inte uppåt, till skillnad från den här filen. `pb-start` stannar om startkatalogen inte är roten.

## Konventioner

(Projektets egna.)

## Vanliga misstag

Bara misstag med `owner: project` i `project-docs/failures/`, en rad per misstag med hänvisning till posten. Högst ca 10 rader.
