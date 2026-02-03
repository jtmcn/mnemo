# Phase 4: CLI & Integration - Research

**Researched:** 2026-02-03
**Domain:** Python CLI development with Typer and Rich
**Confidence:** HIGH

## Summary

Phase 4 wraps existing mnemo functionality (parsing, indexing, search, MCP server) into a command-line interface. The CLI needs to provide five commands (`add`, `remove`, `list`, `search`, `serve`) with Rich formatted output, progress feedback, error handling, and JSON output for scripting.

The existing codebase already has:
- `ingest_book()` and `remove_book()` in `mnemo/ingest.py`
- `SearchService` in `mnemo/search/service.py`
- `BookRepository.list_all()` in `mnemo/storage/repository.py`
- FastMCP server via `python -m mnemo.mcp`

**Primary recommendation:** Use Typer with Rich integration for a modern, type-hint driven CLI with minimal boilerplate. Typer is built on Click and includes Rich by default, providing beautiful tables, progress bars, and error formatting.

## Standard Stack

The established libraries for Python CLI development:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | >=0.12 | CLI framework | Type-hint driven, Click-based, includes Rich, minimal boilerplate |
| rich | >=14.0 | Terminal formatting | Tables, progress bars, colors, auto-detects TTY |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (none needed) | - | - | Typer includes rich and click as dependencies |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Typer | Click | More explicit but more verbose; Typer is built on Click anyway |
| Typer | argparse | No dependencies but much more boilerplate, no rich integration |
| Rich progress | typer.progressbar | Less control; docs recommend Rich "if you can" |

**Installation:**
```bash
pip install typer[all]
```

Note: `typer[all]` includes rich, shellingham (shell detection), and click. Since the project already has dependencies, just add `typer>=0.12` to pyproject.toml - rich is already pulled in.

## Architecture Patterns

### Recommended Project Structure
```
src/mnemo/
├── cli.py              # All CLI commands in one file (small scope)
├── __init__.py         # Exports main() for entry point
└── ... (existing modules)
```

For this phase, a single `cli.py` file is appropriate given the five commands are tightly related. No need for a `commands/` subdirectory.

### Pattern 1: Typer App with Subcommands
**What:** Single Typer instance with decorated command functions
**When to use:** CLI apps with multiple commands sharing common patterns
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/commands/
import typer
from typing import Annotated

app = typer.Typer(
    help="Mnemo: Personal book library with semantic search",
    no_args_is_help=True,  # Show help when no command given
    pretty_exceptions_show_locals=False,  # Security: hide local vars in errors
)

@app.command()
def add(
    paths: Annotated[list[Path], typer.Argument(help="EPUB file(s) to add")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show details")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON")] = False,
):
    """Add EPUB book(s) to the library."""
    ...
```

### Pattern 2: Global Options via Callback
**What:** Define options that apply to all commands
**When to use:** `--json`, `--verbose`, `--quiet` flags shared across commands
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/commands/callback/
from dataclasses import dataclass

@dataclass
class State:
    json_output: bool = False
    verbose: bool = False

state = State()

@app.callback()
def main(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Mnemo: Personal book library with semantic search."""
    state.json_output = json_output
    state.verbose = verbose
```

### Pattern 3: Rich Console with TTY Detection
**What:** Use Rich Console that auto-detects terminal capabilities
**When to use:** All formatted output (tables, progress, colors)
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/console.html
from rich.console import Console

console = Console()  # Auto-detects TTY, respects NO_COLOR

# For JSON output mode, bypass Rich
if state.json_output:
    import json
    print(json.dumps(data))  # Plain stdout, no Rich
else:
    console.print(table)  # Rich formatted
```

### Pattern 4: Progress for Multi-Stage Operations
**What:** Rich Progress with custom stages for add command
**When to use:** Long-running operations with distinct phases
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/progress.html
from rich.progress import Progress, SpinnerColumn, TextColumn

with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    console=console,
    transient=True,  # Clear when done
) as progress:
    task = progress.add_task("Parsing...", total=None)  # Indeterminate
    book, content_blocks = parser.parse(epub_path)

    progress.update(task, description="Chunking...")
    chunks = chunker.chunk(book.id, content_blocks)

    progress.update(task, description="Storing...")
    # ... store to SQLite

    progress.update(task, description="Embedding...")
    # ... generate embeddings
```

### Pattern 5: Confirmation Prompts
**What:** typer.confirm() for destructive or duplicate operations
**When to use:** Duplicate book detection, destructive operations
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/prompt/
# Duplicate detection: prompt user "Book exists. Re-index? [y/N]"
existing = book_repo.get_by_hash(book.file_hash)
if existing:
    reindex = typer.confirm(
        f"Book already indexed ({existing.title}). Re-index?",
        default=False,
    )
    if not reindex:
        raise typer.Exit(0)
    # Continue with force=True
```

### Anti-Patterns to Avoid
- **print() statements:** Use `console.print()` or `typer.echo()` - never raw `print()` except for `--json` output
- **Global Rich Console creation at import time:** Create Console inside functions or at module level with lazy init
- **Hardcoded colors:** Let Rich auto-detect; use semantic styles like `[bold]`, `[green]`
- **Blocking on serve:** The `mcp.run()` blocks; that's correct, but document it

## Don't Hand-Roll

Problems that have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Argument parsing | Custom sys.argv parsing | Typer decorators | Type hints drive everything |
| Progress indicators | Print statements | Rich Progress | Smooth animations, TTY-aware |
| Tables | String formatting | Rich Table | Auto-sizing, borders, alignment |
| Color support detection | isatty() checks | Rich Console | Handles NO_COLOR, TERM, pipe detection |
| Confirmation prompts | input() with parsing | typer.confirm() | Standardized [y/N] format |
| Exit codes | sys.exit() | typer.Exit() | Clean shutdown, caught by Typer |
| Error display | Exception printing | Typer pretty exceptions | Filtered traceback, colors |

**Key insight:** Typer + Rich handle all the edge cases that CLI developers typically forget (TTY detection, pipe handling, NO_COLOR, terminal width, Unicode support).

## Common Pitfalls

### Pitfall 1: Print in MCP Server Context
**What goes wrong:** Using print() or Rich console in serve command corrupts STDIO transport
**Why it happens:** MCP uses stdin/stdout for JSON-RPC, any other output breaks protocol
**How to avoid:** `serve` command just calls `mcp.run()` which handles STDIO correctly
**Warning signs:** MCP client receives malformed JSON, connection fails

### Pitfall 2: Non-Zero Exit on "Not Found" Remove
**What goes wrong:** `mnemo remove nonexistent` exits 1, breaks scripts
**Why it happens:** Treating "already gone" as an error
**How to avoid:** Per CONTEXT.md: warn but exit 0 ("Book not found (already removed?)")
**Warning signs:** Scripts fail when removing potentially-deleted books

### Pitfall 3: Interactive Prompts in Non-TTY
**What goes wrong:** `mnemo add book.epub < /dev/null` hangs or errors on duplicate prompt
**Why it happens:** typer.confirm() blocks waiting for input that never comes
**How to avoid:** Check `console.is_terminal` before prompting; in non-TTY, fail with message
**Warning signs:** CI/scripts hang indefinitely

### Pitfall 4: Rich Output When Piped
**What goes wrong:** `mnemo list | grep foo` includes ANSI escape codes
**Why it happens:** Console created with force_terminal=True or TTY misdetected
**How to avoid:** Let Rich auto-detect (default behavior); test with `| cat`
**Warning signs:** Garbled output, escape sequences visible

### Pitfall 5: Embedding Failures Mid-Add
**What goes wrong:** API error after SQLite commit leaves inconsistent state
**Why it happens:** Embedding happens after chunk storage
**How to avoid:** Per CONTEXT.md: fail completely, delete partial work on error
**Warning signs:** Books in SQLite without embeddings in ChromaDB

### Pitfall 6: Missing Error Context
**What goes wrong:** "Error: File not found" without showing which file
**Why it happens:** Catching exception, printing generic message
**How to avoid:** Include the path in error message: `f"File not found: {path}"`
**Warning signs:** Users can't diagnose issues

### Pitfall 7: Version Flag with Required Args
**What goes wrong:** `mnemo --version` fails asking for required arguments
**Why it happens:** Version callback not marked is_eager=True
**How to avoid:** Use `is_eager=True` on version option callback
**Warning signs:** Version requires dummy arguments

## Code Examples

Verified patterns from official sources:

### Entry Point Setup (pyproject.toml)
```toml
# Already in pyproject.toml, just verify:
[project.scripts]
mnemo = "mnemo.cli:main"
```

### Basic CLI Structure
```python
# Source: https://typer.tiangolo.com/
import typer
from typing import Annotated
from pathlib import Path
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="Mnemo: Personal book library with semantic search",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

console = Console()

@app.command()
def list(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
):
    """List all indexed books."""
    from mnemo.storage import BookRepository, get_connection, init_db

    init_db()
    conn = get_connection()
    repo = BookRepository(conn)
    books = repo.list_all()
    conn.close()

    if json_output:
        import json
        data = [{"id": b.id, "title": b.title, "authors": b.authors} for b in books]
        print(json.dumps(data, indent=2))
    else:
        table = Table(title="Indexed Books")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Authors")
        for book in books:
            table.add_row(book.id, book.title, ", ".join(book.authors))
        console.print(table)

def main():
    app()

if __name__ == "__main__":
    main()
```

### Add Command with Progress
```python
# Source: https://rich.readthedocs.io/en/stable/progress.html
from rich.progress import Progress, SpinnerColumn, TextColumn

@app.command()
def add(
    paths: Annotated[list[Path], typer.Argument(help="EPUB file(s) to add")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """Add EPUB book(s) to the library."""
    from mnemo.ingest import ingest_book
    from mnemo.storage import BookRepository, get_connection, init_db

    results = []

    for path in paths:
        if not path.exists():
            console.print(f"[red]File not found: {path}[/red]")
            raise typer.Exit(1)

        # Check for duplicate
        # ... (duplicate detection with confirm prompt)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
            disable=json_output,  # No progress for JSON mode
        ) as progress:
            task = progress.add_task("Parsing...", total=None)

            try:
                # ingest_book handles all stages internally
                # For stage feedback, we'd need to refactor or add callbacks
                progress.update(task, description="Indexing...")
                book, chunk_count = ingest_book(path, embed=True)

                results.append({
                    "id": book.id,
                    "title": book.title,
                    "authors": book.authors,
                    "chunks": chunk_count,
                })

                if not json_output:
                    console.print(
                        f"[green]Added:[/green] {book.title} by {', '.join(book.authors)} "
                        f"({book.id}) - {chunk_count} chunks"
                    )
            except Exception as e:
                console.print(f"[red]Error adding {path}: {e}[/red]")
                raise typer.Exit(1)

    if json_output:
        import json
        print(json.dumps(results, indent=2))
```

### Serve Command (Simple)
```python
@app.command()
def serve():
    """Start the MCP server for Claude Desktop integration."""
    from mnemo.mcp.server import mcp
    import mnemo.mcp.tools  # Ensure tools are registered

    # mcp.run() blocks and handles STDIO
    mcp.run()
```

### Search Command
```python
@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 5,
    book: Annotated[str | None, typer.Option("--book", "-b", help="Filter by book ID")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """Search books for relevant content."""
    from mnemo.search import SearchService

    service = SearchService()
    results = service.search(query, top_k=limit, book_id=book)

    if json_output:
        import json
        data = [
            {
                "book_id": r.book_id,
                "book_title": r.book_title,
                "section_path": r.section_path,
                "content": r.content,
                "score": r.score,
            }
            for r in results
        ]
        print(json.dumps(data, indent=2))
    else:
        for r in results:
            path = " > ".join(r.section_path) if r.section_path else "No section"
            console.print(f"[bold]{r.book_title}[/bold] > {path}")
            console.print(r.content)
            console.print()
```

### Testing with CliRunner
```python
# Source: https://typer.tiangolo.com/tutorial/testing/
from typer.testing import CliRunner
from mnemo.cli import app

runner = CliRunner()

def test_list_empty():
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0

def test_add_missing_file():
    result = runner.invoke(app, ["add", "nonexistent.epub"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()

def test_list_json():
    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output)
    assert isinstance(data, list)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| argparse | typer with type hints | 2020+ | 80% less boilerplate |
| click decorators | Annotated type hints | Typer 0.9+ | Better IDE support |
| manual colors | Rich auto-detection | Rich 10+ | NO_COLOR, TTY handled |
| tqdm progress | Rich Progress | 2021+ | Unified styling, multi-bar |

**Deprecated/outdated:**
- `click.echo()`: Still works but `console.print()` preferred for Rich integration
- `typer.progressbar()`: Docs recommend Rich Progress "if you can"

## Open Questions

Things that couldn't be fully resolved:

1. **Stage-granular progress feedback**
   - What we know: ingest_book() is atomic, doesn't expose parsing/chunking/embedding stages
   - What's unclear: How to show "Parsing... Chunking... Embedding..." without refactoring
   - Recommendation: Either refactor ingest.py with callbacks, or use single "Indexing..." stage

2. **Chapter count in summary**
   - What we know: CONTEXT.md specifies "342 chunks, 12 chapters" in completion message
   - What's unclear: Chunks are counted, but chapters aren't directly tracked
   - Recommendation: Count unique top-level section_path entries, or infer from chunk sections

## Sources

### Primary (HIGH confidence)
- [Typer Official Documentation](https://typer.tiangolo.com/) - CLI framework usage, testing, callbacks
- [Rich Documentation](https://rich.readthedocs.io/en/stable/) - Tables, Progress, Console API
- [FastMCP Documentation](https://gofastmcp.com/deployment/running-server) - Server running, STDIO transport

### Secondary (MEDIUM confidence)
- WebSearch results on CLI frameworks comparison (multiple sources agree on Typer recommendation)
- WebSearch results on Rich TTY detection patterns

### Tertiary (LOW confidence)
- None - all findings verified with official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Typer/Rich are clearly the modern standard, verified with official docs
- Architecture: HIGH - Patterns directly from official documentation
- Pitfalls: HIGH - Based on project CONTEXT.md decisions and standard CLI issues

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (stable, mature libraries)
