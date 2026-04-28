# Mnemo Project Instructions

## Versioning

- The version is defined in `pyproject.toml` (single source of truth). `__init__.py` reads it via `importlib.metadata`.
- When making changes, update the version in `pyproject.toml` following semantic versioning:
  - PATCH (x.y.Z): bug fixes, minor changes
  - MINOR (x.Y.0): new features, backward-compatible
  - MAJOR (X.0.0): breaking changes
- Current version: 1.11.0
