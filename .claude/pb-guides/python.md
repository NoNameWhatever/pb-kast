# python-modulen: läs före kod i en python-enhet

Bara det som inte kan bli en grind. Allt annat kontrolleras av `make lint` och `make test`.

- Kör verktygen via `make` (`make lint`, `make test`, `make fmt`), inte direkt. Grinden lägger mallens golv
  över projektets konfig; en fristående `ruff` eller `basedpyright` kan ge annat svar.
- Konfigen ligger i enhetens `pyproject.toml` (`[tool.ruff]`, `[tool.basedpyright]`, `[tool.pytest.ini_options]`).
  Filer som `ruff.toml`, `pyrightconfig.json`, `pytest.ini` och `tox.ini` läses inte och gör grinden röd.
- Grinden läser bara vissa Ruff-inställningar från projektet (`line-length`, `target-version`, `src`,
  `exclude`, `format`, `lint.isort`). Regelval och undantag (`select`, `ignore`, `per-file-ignores`) sätts av mallen.
- Undertryck en rad med kod: `# noqa: S603` eller `# pyright: ignore[reportUnknownMemberType]`. Filomfattande
  `# ruff: noqa` och `# pyright: basic` är röda. Behövs ett undantag: förklara varför i koden intill.
- Nya beroenden går via beroendeplanen (`pb-guides/dependency-plan.md`). `uv.lock` ändras bara med `uv lock`, och
  diffen granskas. Cooldownen (7 dagar) och `no-build` sätts av mallen; sätt dem inte i projektet.
- Python-versionen står i `.python-version`; uv hämtar den vid körning. Ett versionsbyte är en vanlig PR.
- Tester: en enhet behöver minst ett test. Hoppa inte över tester med `skip` eller `xfail` utan att ange
  filen under `Tests:` i PR-kroppen.
