"""Command-line interface for Mnemo.

Provides commands to manage the book library and MCP server:
- add: Add EPUB files to the library
- remove: Remove a book by ID
- list: List all indexed books
- search: Search books for content
- serve: Start the MCP server for Claude
- migrate-cosine: Migrate ChromaDB from L2 to cosine distance
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from mnemo import __version__


def version_callback(value: bool) -> None:
    if value:
        print(f"mnemo {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="mnemo",
    help="Personal technical book library with semantic search via MCP",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

console = Console()


@app.command()
def add(
    paths: Annotated[
        list[Path],
        typer.Argument(
            help="EPUB file(s) to add",
            exists=False,  # We validate manually for better error messages
        ),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed progress"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-index without prompting if book exists"),
    ] = False,
) -> None:
    """Add EPUB file(s) to the library.

    Parses the EPUB, chunks content, generates embeddings, and stores
    everything for search. Multiple files can be added in one command.
    """
    from mnemo.ingest import ingest_book
    from mnemo.storage import BookRepository, get_connection, init_db

    results = []

    for path in paths:
        # Validate file exists
        if not path.exists():
            if json_output:
                print(json.dumps({"error": f"File not found: {path}"}))
            else:
                console.print(f"[red]File not found: {path}[/red]")
            raise typer.Exit(1)

        if not path.suffix.lower() == ".epub":
            if json_output:
                print(json.dumps({"error": f"Not an EPUB file: {path}"}))
            else:
                console.print(f"[red]Not an EPUB file: {path}[/red]")
            raise typer.Exit(1)

        # Check for duplicate
        init_db()
        conn = get_connection()
        book_repo = BookRepository(conn)

        # Compute file hash to check for duplicate
        import hashlib
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = book_repo.get_by_hash(file_hash)
        conn.close()

        should_force = force
        if existing and not force:
            # Prompt user in TTY mode, error in non-TTY
            if console.is_terminal and not json_output:
                confirm = typer.confirm(
                    f"Book already indexed (id: {existing.id}). Re-index?"
                )
                if confirm:
                    should_force = True
                else:
                    console.print("[yellow]Skipped[/yellow]")
                    continue
            else:
                if json_output:
                    print(json.dumps({
                        "error": "Book exists. Use --force to re-index.",
                        "existing_id": existing.id,
                    }))
                else:
                    console.print(
                        f"[red]Book exists (id: {existing.id}). Use --force to re-index.[/red]"
                    )
                raise typer.Exit(1)

        # Ingest with progress spinner
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                disable=json_output,
            ) as progress:
                progress.add_task(description="Parsing and indexing...", total=None)
                book, chunk_count = ingest_book(path, embed=True, force=should_force)

            result = {
                "id": book.id,
                "title": book.title,
                "authors": book.authors,
                "chunks": chunk_count,
            }
            results.append(result)

            if not json_output:
                authors_str = ", ".join(book.authors) if book.authors else "Unknown"
                console.print(
                    f"[green]Added:[/green] {book.title} by {authors_str} "
                    f"({book.id}) - {chunk_count} chunks"
                )

        except FileNotFoundError as e:
            if json_output:
                print(json.dumps({"error": str(e)}))
            else:
                console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)
        except ValueError as e:
            if json_output:
                print(json.dumps({"error": str(e)}))
            else:
                console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)
        except Exception as e:
            if json_output:
                print(json.dumps({"error": f"Failed to add {path}: {e}"}))
            else:
                console.print(f"[red]Failed to add {path}: {e}[/red]")
            raise typer.Exit(1)

    if json_output:
        print(json.dumps(results))


@app.command(name="list")
def list_books(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """List all indexed books.

    Shows a table of books with their ID, title, and authors.
    """
    from mnemo.storage import BookRepository, get_connection, init_db

    init_db()
    conn = get_connection()
    book_repo = BookRepository(conn)
    books = book_repo.list_all()
    conn.close()

    if json_output:
        result = [
            {
                "id": book.id,
                "title": book.title,
                "authors": book.authors,
            }
            for book in books
        ]
        print(json.dumps(result))
        return

    if not books:
        console.print("No books indexed")
        return

    table = Table(title="Indexed Books")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="green")
    table.add_column("Authors")

    for book in books:
        authors_str = ", ".join(book.authors) if book.authors else "Unknown"
        table.add_row(book.id, book.title, authors_str)

    console.print(table)


@app.command()
def remove(
    book_id: Annotated[
        str,
        typer.Argument(help="6-character book ID to remove"),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Remove a book from the library.

    Deletes the book and all its chunks and vectors.
    """
    from mnemo.ingest import remove_book

    result = remove_book(book_id)

    if json_output:
        print(json.dumps({"removed": result, "book_id": book_id}))
        return

    if result:
        console.print(f"[green]Removed:[/green] {book_id}")
    else:
        console.print(f"[yellow]Book not found (already removed?): {book_id}[/yellow]")


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(help="Search query"),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max results"),
    ] = 5,
    book: Annotated[
        str | None,
        typer.Option("--book", "-b", help="Filter by book ID"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Search books for content.

    Returns results with book attribution and section paths.
    """
    from mnemo.search import SearchService

    service = SearchService()
    results = service.search(query, top_k=limit, book_id=book)

    if json_output:
        output = [
            {
                "book_id": r.book_id,
                "book_title": r.book_title,
                "section_path": r.section_path,
                "content": r.content,
                "score": r.score,
            }
            for r in results
        ]
        print(json.dumps(output))
        return

    if not results:
        console.print("No results found")
        return

    for r in results:
        section = " > ".join(r.section_path) if r.section_path else "No section"
        console.print(f"[bold]{r.book_title}[/bold] > {section}")
        console.print(r.content, highlight=False, markup=False)
        console.print()


@app.command(name="migrate-cosine")
def migrate_cosine(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    chroma_path: Annotated[
        Path | None,
        typer.Option("--chroma-path", help="ChromaDB storage path override"),
    ] = None,
) -> None:
    """Migrate ChromaDB from L2 to cosine distance.

    Copies all vectors to a new collection with cosine distance metric.
    Existing embeddings are preserved (no re-embedding needed).
    Safe to run multiple times (idempotent).
    """
    import chromadb

    from mnemo.vectors.config import VectorConfig
    from mnemo.vectors.migrate import migrate_to_cosine

    try:
        # Resolve ChromaDB path
        config = VectorConfig(persist_path=chroma_path)
        persist_path = config.get_persist_path()
        client = chromadb.PersistentClient(path=str(persist_path))

        result = migrate_to_cosine(client, config.collection_name)

        if json_output:
            print(json.dumps(result))
            return

        if result.get("already_cosine"):
            console.print("[green]Already using cosine distance.[/green]")
        elif result["migrated"] == 0:
            console.print("[green]Empty collection recreated with cosine distance.[/green]")
        else:
            console.print(
                f"[green]Migrated {result['migrated']} vectors to cosine distance.[/green]"
            )

    except RuntimeError as e:
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Migration failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def serve() -> None:
    """Start the MCP server for Claude.

    Runs the MCP server over STDIO. This command blocks until interrupted.
    """
    import mnemo.mcp.tools  # noqa: F401 - ensure tools are registered
    from mnemo.mcp.server import mcp

    mcp.run()


@app.callback()
def app_callback(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Show version and exit", callback=version_callback, is_eager=True),
    ] = False,
) -> None:
    """Personal technical book library with semantic search via MCP."""


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
