# Mnemo

![CI](https://github.com/joel-eq/mnemo/actions/workflows/ci.yml/badge.svg)

Personal technical book library with semantic search via MCP.

## Overview

Mnemo parses technical EPUB books, preserves code blocks and structure, generates embeddings, and exposes semantic search through an MCP server for Claude Desktop and Claude Code.

## Installation

```bash
pip install -e ".[dev]"
```

## Configuration

Semantic search needs an OpenAI-compatible embeddings endpoint — OpenAI, Voyage,
Together, a local Ollama, anything serving `POST {base_url}/embeddings`:

```bash
export MNEMO_EMBED_BASE_URL=https://api.openai.com/v1
export MNEMO_EMBED_API_KEY=sk-...
export MNEMO_EMBED_MODEL=text-embedding-3-small  # optional, this is the default
```

Code, math, and table blocks are never split, so a long listing can exceed a
provider's per-input limit. Inputs are truncated to `MNEMO_EMBED_MAX_TOKENS`
(default 8192, matching text-embedding-3) before embedding — lower it for a
shorter-context model, raise it for a longer one. The full text is always kept
for keyword search and display.

Without these, `add` still stores books and `search` falls back to keyword-only
(SQLite FTS5) — that is a supported mode, so it stays quiet. But a *configured*
endpoint that fails (bad key, wrong model, host down) raises instead of quietly
returning worse results, since a silent downgrade is indistinguishable from a
thin library. `mode="semantic"` also raises when embeddings are unavailable
rather than returning an empty list, which would read as "no matching content". See `.env.example` for the full list. Switching embedding models
changes the vector dimension, which ChromaDB locks on first insert, so re-embed
from scratch after a switch:

```bash
rm -rf ~/.mnemo/chroma && mnemo reindex
```

## Usage

```bash
# Add a book
mnemo add path/to/book.epub

# List books
mnemo list

# List books, flagging any that have no embeddings (keyword search only)
mnemo list --check-embeddings

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
