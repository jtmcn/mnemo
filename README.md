# Mnemo

[![CI](https://github.com/jtmcn/mnemo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jtmcn/mnemo/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/github/license/jtmcn/mnemo)](LICENSE)

Personal technical book library with semantic search via MCP.

Mnemo indexes EPUB, DOCX and PDF books you already own — keeping code, math and
table blocks intact — and exposes them to Claude Code and Claude Desktop as MCP tools,
so an answer arrives with the book and section it came from. The same library is
searchable from the terminal with `mnemo search`.

## Demo

Real output, reproducible from this repo's test fixture with no embedding
endpoint configured (keyword-only mode):

```console
$ mnemo add tests/fixtures/sample.epub
Added: Python Testing Guide by Test Author (10b05d) - 8 chunks
Note: ISBN 9781234567890 may be invalid (bad checksum)
Embeddings skipped: MNEMO_EMBED_BASE_URL must be set to an OpenAI-compatible endpoint
(e.g. https://api.openai.com/v1), along with MNEMO_EMBED_API_KEY unless the provider
needs no auth.
Keyword search works now. Re-run `mnemo add --force tests/fixtures/sample.epub` to add
semantic search.

$ mnemo search test_addition -n 2
Python Testing Guide > Chapter 2: Code Examples
def test_addition():
    assert 1 + 1 == 2
    assert 2 + 2 == 4

def test_subtraction():
    assert 5 - 3 == 2
    assert 10 - 7 == 3
```

## Features

- **Structure-preserving parsing** — EPUB and DOCX, with code, math and table
  blocks never split across chunks, so a listing arrives whole.
- **PDF** — born-digital PDFs, sectioned by their bookmark outline, with
  monospace blocks kept whole as code. No OCR: a scan without a text layer is
  rejected, and tables and math inside a PDF are indexed as plain text.
- **Hybrid retrieval** — SQLite FTS5 keyword search and ChromaDB vectors merged
  with reciprocal rank fusion; force one side with `mode="keyword"` or
  `mode="semantic"`.
- **Degrades honestly** — with no embedding endpoint configured, books still
  index and search falls back to keyword-only. A *configured* endpoint that
  fails raises instead of silently returning worse results.
- **10 MCP tools** — search, section outlines, contiguous chunk reads, add /
  remove / reindex, metadata edits, and enrichment from Google Books and Open
  Library.
- **Collections** — group related books (`--collection "ERCOT Nodal Protocols"`)
  and scope searches to one group.
- **Intake checks** — duplicate detection by file hash, ISBN checksum
  validation, similar-title warnings before you index the same book twice.
- **Portable library** — `mnemo backup` writes one `.tar.gz` of database plus
  vectors; `mnemo restore` recreates it.

## Requirements

- **Python 3.11, 3.12 or 3.13** — all three are covered by CI. Python 3.14 is
  excluded in `requires-python`, because ChromaDB's Pydantic v1 shim fails there.
- **For semantic search (optional):** any OpenAI-compatible embeddings endpoint —
  anything serving `POST {base_url}/embeddings` (OpenAI, Voyage, Together, a
  local Ollama).

## Install

```sh
uv tool install git+https://github.com/jtmcn/mnemo
```

Or with pip:

```sh
pip install "git+https://github.com/jtmcn/mnemo"
```

> [!WARNING]
> Don't `pip install mnemo` — the PyPI name belongs to an unrelated project.
> This tool is installed from git.

From source, for development:

```sh
git clone git@github.com:jtmcn/mnemo.git
cd mnemo
uv sync --all-extras
uv run mnemo --help
```

## Configure embeddings

```sh
export MNEMO_EMBED_BASE_URL=https://api.openai.com/v1
export MNEMO_EMBED_API_KEY=sk-...
export MNEMO_EMBED_MODEL=text-embedding-3-small   # optional, this is the default
```

Mnemo does not read `.env` itself — use direnv, dotenv, or `source` it. See
[.env.example](.env.example) for every variable, including
`MNEMO_EMBED_MAX_TOKENS` (default 8192, the truncation ceiling per input) and
`MNEMO_LOG_LEVEL` (MCP server only).

Switching embedding models changes the vector dimension, which ChromaDB locks on
first insert. Re-embed from scratch after a switch:

```sh
rm -rf ~/.mnemo/chroma && mnemo reindex
```

## CLI

```sh
mnemo add book.epub other.docx paper.pdf   # index one or more books
mnemo add *.epub --collection "SRE"   # tag a batch; --skip-existing for unattended runs
mnemo list --check-embeddings         # which books have vectors (none = keyword-only)
mnemo search "consistent hashing" -n 10 --book 10b05d
mnemo remove 10b05d
mnemo reindex                         # re-parse and re-embed everything
mnemo export book-paths.txt           # one source path per line, for re-import
mnemo backup ~/mnemo-backup.tar.gz
mnemo restore ~/mnemo-backup.tar.gz --force
mnemo serve                           # MCP server over STDIO (blocks)
```

Every command except `export` and `serve` takes `--json`; `mnemo <command> --help`
has the full flag list. `mnemo migrate-cosine` moves an older vector collection from
L2 to cosine distance without re-embedding, and is idempotent.

## Use from Claude

Register the STDIO server with Claude Code:

```sh
claude mcp add mnemo \
  -e MNEMO_EMBED_BASE_URL=https://api.openai.com/v1 \
  -e MNEMO_EMBED_API_KEY=sk-... \
  -- mnemo serve
```

For Claude Desktop, add it to `claude_desktop_config.json` (on macOS,
`~/Library/Application Support/Claude/`). Use the absolute path from
`which mnemo` — Claude Desktop does not inherit your shell's `PATH`:

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "/Users/you/.local/bin/mnemo",
      "args": ["serve"],
      "env": {
        "MNEMO_EMBED_BASE_URL": "https://api.openai.com/v1",
        "MNEMO_EMBED_API_KEY": "sk-..."
      }
    }
  }
}
```

The server exposes ten tools: `search_books`, `get_book_structure`,
`get_book_chunks`, `list_available_books`, `get_book_info`, `add_book`,
`remove_book`, `reindex_all_books`, `update_book_metadata`, `enrich_book`.

## Data

Created on first run, not currently configurable:

| Path | Contents |
| --- | --- |
| `~/.mnemo/mnemo.db` | SQLite: books, chunks, FTS5 index |
| `~/.mnemo/chroma` | ChromaDB vectors |

Source book files are read in place and never copied or modified; `mnemo remove`
leaves them alone. Because the library stores absolute paths, `mnemo reindex`
skips books whose files have moved.

## Development

```sh
make ci         # exactly what CI gates on: lint, format check, mypy, tests with 80% coverage floor
make all        # the fuller local run (adds integration tests)
make format     # ruff fix + format
```

Every target runs `uv sync --locked --all-extras --dev` first, so a fresh clone
needs no setup step. `.python-version` pins local work to 3.12.

Integration tests need embedding credentials; deselect them with
`pytest -m 'not integration'`.

## Contributing

Issues and pull requests: <https://github.com/jtmcn/mnemo/issues>. Run `make ci`
before pushing.

## License

[MIT](LICENSE) © 2026 Joel McNierney

---

Working on mnemo with an agent? [CLAUDE.md](CLAUDE.md) holds the project
instructions and [CONTEXT.md](CONTEXT.md) defines the domain vocabulary
(Book, Chunk, Intake, Intake Outcome).
