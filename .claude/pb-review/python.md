# python-modulens tillägg till kodgranskningen

Läses tillsammans med `core.md` när diffen rör en python-enhet.

- Tester som hoppas över eller begränsas i `conftest.py` (`pytest_collection_modifyitems`, `collect_ignore`,
  autouse-fixtures som gör `pytest.skip`). `conftest.py` är Standard och kontrolleras bara av testcheckens mönster.
- `subprocess` med `shell=True`, `eval`, `exec`, `pickle` och `yaml.load` på data som inte är projektets egen.
- `assert` som enda validering av input i icke-testkod (tas bort med `-O`).
- SQL byggd med f-strängar eller `%`-formatering; sökvägar byggda av input (`pathlib` utan kontroll av `..`).
- Undertryckningar som ändrats: `# noqa` och `# pyright: ignore` med koden intill och en motivering.
- Nya beroenden i `pyproject.toml` som saknar beroendeplan, och ändringar i `uv.lock` som inte följer av manifestet.
