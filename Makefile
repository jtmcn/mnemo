.PHONY: lint format check test test-cov typecheck ci all

# Everything worth running before you push: lint, format, types, full tests.
all: check typecheck test

# Exactly what .github/workflows/ci.yml gates on, in the same order.
# Use this to reproduce a CI failure; `all` is the fuller local run because
# it also exercises the integration tests.
ci:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	uv run mypy src/
	uv run pytest -m 'not integration' --cov=mnemo --cov-report=term-missing --cov-fail-under=80

# Run ruff linter
lint:
	uv run ruff check src/ tests/

# Auto-fix lint and format issues
format:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

# Check lint + formatting without modifying files
check:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

# Run tests
test:
	uv run pytest

# Run tests with coverage
test-cov:
	uv run pytest --cov=mnemo --cov-report=term-missing

# Run mypy type checking
typecheck:
	uv run mypy src/
