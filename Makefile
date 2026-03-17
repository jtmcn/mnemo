.PHONY: lint format check test test-cov typecheck all

# Run all checks (lint + typecheck + test)
all: check test

# Run ruff linter
lint:
	ruff check src/ tests/

# Auto-fix lint and format issues
format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

# Check lint + formatting without modifying files
check:
	ruff check src/ tests/
	ruff format --check src/ tests/

# Run tests
test:
	pytest

# Run tests with coverage
test-cov:
	pytest --cov=mnemo --cov-report=term-missing

# Run mypy type checking
typecheck:
	mypy src/
