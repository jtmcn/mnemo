# Mnemo Project Instructions

## Versioning

- The version is defined in `pyproject.toml` (single source of truth). `__init__.py` reads it via `importlib.metadata`.
- When making changes, update the version in `pyproject.toml` following semantic versioning:
  - PATCH (x.y.Z): bug fixes, minor changes
  - MINOR (x.Y.0): new features, backward-compatible
  - MAJOR (X.0.0): breaking changes
- Current version: 2.5.1

## Saffron

Saffron runs tasks here from specs in `.saffron/specs/`. Each gate in `.saffron/gates/` wraps one command. Run the same commands before you commit:

- `format`: `ruff format --check src/ tests/`
- `lint`: `ruff check src/ tests/`
- `types`: `mypy src/`
- `tests`: `pytest -m "not integration"`
- `migrations`: every legacy schema, migrated by `init_db`, must match a fresh one. A new column needs its migration.

Commit your work before the gates run. An uncommitted change fails `committed`, because the patch a reviewer reads holds only commits.
A test skip or an ignore comment fails `integrity`. Fix the code the gate names instead.
In a Saffron task, leave the version in `pyproject.toml` alone. The operator bumps it at merge.
