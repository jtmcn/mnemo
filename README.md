# Mnemo

![CI](https://github.com/joel-eq/mnemo/actions/workflows/ci.yml/badge.svg)

Personal technical book library with semantic search via MCP.

## Overview

Mnemo parses technical EPUB books, preserves code blocks and structure, generates embeddings, and exposes semantic search through an MCP server for Claude Desktop and Claude Code.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Add a book
mnemo add path/to/book.epub

# List books
mnemo list

# Remove a book
mnemo remove <book-id>
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/mnemo

# Linting
ruff check src/mnemo
```

## License

MIT
