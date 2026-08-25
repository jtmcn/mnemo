"""Command-line interface for Mnemo.

Provides commands to manage the book library and MCP server:
- add: Add book files (.epub, .docx) to the library
- remove: Remove a book by ID
- list: List all indexed books
- search: Search books for content
- serve: Start the MCP server for Claude
- migrate-cosine: Migrate ChromaDB from L2 to cosine distance
- backup: Archive the library (SQLite + ChromaDB) to a .tar.gz file
- restore: Restore a library from a .tar.gz backup archive
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.markup import escape
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
            help="Book file(s) to add (.epub, .docx)",
            exists=False,  # We validate manually for better error messages
            readable=False,  # Avoid os.access() which fails on macOS TCC-protected dirs
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
    collection: Annotated[
        str | None,
        typer.Option(
            "--collection",
            help=(
                "Tag these books with a collection name for grouping (e.g. 'ERCOT Nodal Protocols')"
            ),
        ),
    ] = None,
) -> None:
    """Add book file(s) to the library.

    Parses the book, chunks content, generates embeddings, and stores
    everything for search. Supports .epub and .docx files.
    """
    from mnemo.ingest import EmbeddingFailed, ingest_book
    from mnemo.services.book_service import validate_book_path
    from mnemo.storage import BookRepository, get_connection, init_db

    results = []

    for path in paths:
        # Validate path using service layer
        error = validate_book_path(path)
        if error:
            if json_output:
                print(json.dumps({"error": error}))
            else:
                console.print(f"[red]{escape(error)}[/red]")
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
                confirm = typer.confirm(f"Book already indexed (id: {existing.id}). Re-index?")
                if confirm:
                    should_force = True
                else:
                    console.print("[yellow]Skipped[/yellow]")
                    continue
            else:
                if json_output:
                    print(
                        json.dumps(
                            {
                                "error": "Book exists. Use --force to re-index.",
                                "existing_id": existing.id,
                            }
                        )
                    )
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
                embed_error: str | None = None
                try:
                    book, chunk_count = ingest_book(
                        path,
                        embed=True,
                        force=should_force,
                        collection=collection,
                    )
                except EmbeddingFailed as e:
                    # Book is committed and keyword-searchable — partial success,
                    # not a failure. Report it and keep going.
                    book, chunk_count, embed_error = e.book, e.chunk_count, str(e)

            result = {
                "id": book.id,
                "title": book.title,
                "authors": book.authors,
                "chunks": chunk_count,
                "embedded": embed_error is None,
            }
            if embed_error:
                result["embed_error"] = embed_error
            results.append(result)

            if not json_output:
                authors_str = ", ".join(book.authors) if book.authors else "Unknown"
                console.print(
                    f"[green]Added:[/green] {escape(book.title)} by {escape(authors_str)} "
                    f"({book.id}) - {chunk_count} chunks"
                )
                if embed_error:
                    console.print(
                        f"[yellow]Embeddings skipped:[/yellow] {escape(embed_error)}\n"
                        f"[yellow]Keyword search works now. Re-run "
                        f"`mnemo add --force {escape(shlex.quote(str(path)))}` "
                        f"to add semantic search.[/yellow]"
                    )

        except FileNotFoundError as e:
            if json_output:
                print(json.dumps({"error": str(e)}))
            else:
                console.print(f"[red]Error: {escape(str(e))}[/red]")
            raise typer.Exit(1) from e
        except ValueError as e:
            if json_output:
                print(json.dumps({"error": str(e)}))
            else:
                console.print(f"[red]Error: {escape(str(e))}[/red]")
            raise typer.Exit(1) from e
        except Exception as e:
            if json_output:
                print(json.dumps({"error": f"Failed to add {path}: {e}"}))
            else:
                console.print(f"[red]Failed to add {escape(str(path))}: {escape(str(e))}[/red]")
            raise typer.Exit(1) from e

    if json_output:
        print(json.dumps(results))


def _vector_counts(book_ids: list[str]) -> dict[str, int]:
    """How many vectors each book has in ChromaDB.

    A count rather than a yes/no: embed_book writes in batches, so a run that
    dies partway leaves a book with some vectors but not all. Reporting the
    number keeps that visible instead of claiming the book is embedded.

    Opening the store creates an empty ChromaDB if none exists, so only call
    this when the caller has asked for embedding status.
    """
    from mnemo.vectors import VectorConfig, VectorStore

    store = VectorStore(VectorConfig())
    try:
        return {book_id: store.count(book_id) for book_id in book_ids}
    finally:
        store.close()


@app.command(name="list")
def list_books(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    check_embeddings: Annotated[
        bool,
        typer.Option(
            "--check-embeddings",
            help="Also report each book's vector count (loads ChromaDB, slower)",
        ),
    ] = False,
) -> None:
    """List all indexed books.

    Shows a table of books with their ID, title, and authors. With
    --check-embeddings, also shows how many vectors each book has; a book
    with none is keyword-searchable only.
    """
    from mnemo.storage import BookRepository, get_connection, init_db

    init_db()
    conn = get_connection()
    book_repo = BookRepository(conn)
    books = book_repo.list_all()
    conn.close()

    vectors: dict[str, int] = {}
    if check_embeddings and books:
        vectors = _vector_counts([book.id for book in books])

    if json_output:
        result = []
        for book in books:
            entry: dict[str, Any] = {
                "id": book.id,
                "title": book.title,
                "authors": book.authors,
            }
            if check_embeddings:
                entry["vectors"] = vectors.get(book.id, 0)
                entry["embedded"] = vectors.get(book.id, 0) > 0
            result.append(entry)
        print(json.dumps(result))
        return

    if not books:
        console.print("No books indexed")
        return

    table = Table(title="Indexed Books")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="green")
    table.add_column("Authors")
    if check_embeddings:
        table.add_column("Vectors", justify="right")

    for book in books:
        authors_str = ", ".join(book.authors) if book.authors else "Unknown"
        row = [book.id, escape(book.title), escape(authors_str)]
        if check_embeddings:
            count = vectors.get(book.id, 0)
            row.append(str(count) if count else "[yellow]none[/yellow]")
        table.add_row(*row)

    console.print(table)

    if check_embeddings:
        missing = sum(1 for book in books if not vectors.get(book.id, 0))
        if missing:
            console.print(
                f"[yellow]{missing} book(s) have no embeddings (keyword search only). "
                f"Set MNEMO_EMBED_BASE_URL/MNEMO_EMBED_API_KEY, then run `mnemo reindex`.[/yellow]"
            )


@app.command()
def export(
    output: Annotated[
        Path,
        typer.Argument(help="Output file path (one EPUB path per line)"),
    ] = Path("book-paths.txt"),
) -> None:
    """Export EPUB paths for all indexed books.

    Writes one path per line, suitable for re-importing with:
        mnemo add (cat book-paths.txt)
    """
    from mnemo.storage import BookRepository, get_connection, init_db

    init_db()
    conn = get_connection()
    book_repo = BookRepository(conn)
    books = book_repo.list_all()
    conn.close()

    paths = [book.file_path for book in books if book.file_path]

    if not paths:
        console.print("[yellow]No books with file paths to export.[/yellow]")
        raise typer.Exit(1)

    output.write_text("\n".join(paths) + "\n")
    console.print(f"[green]Exported {len(paths)} paths to {escape(str(output))}[/green]")


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
        console.print(f"[green]Removed:[/green] {escape(book_id)}")
    else:
        console.print(f"[yellow]Book not found (already removed?): {escape(book_id)}[/yellow]")


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
    try:
        results = service.search(query, top_k=limit, book_id=book)
    except (ValueError, httpx.HTTPError) as e:
        # A configured endpoint that fails is a misconfiguration, not a reason
        # to quietly return worse results. Say so instead of a traceback.
        message = f"Semantic search failed: {e}"
        if json_output:
            print(json.dumps({"error": message}))
        else:
            console.print(f"[red]Error: {escape(message)}[/red]")
            console.print(
                "[yellow]Check MNEMO_EMBED_BASE_URL / MNEMO_EMBED_API_KEY, "
                "or unset them for keyword-only search.[/yellow]"
            )
        raise typer.Exit(1) from e

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
        console.print(f"[bold]{escape(r.book_title)}[/bold] > {escape(section)}")
        console.print(r.content, highlight=False, markup=False)
        console.print()


@app.command()
def reindex(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show per-book details"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Re-index all books in the library.

    Re-parses books, re-chunks content, and regenerates embeddings for every
    book. Useful after upgrading mnemo's chunking or embedding pipeline.
    Books whose source files are missing are skipped.
    """
    from mnemo.ingest import reindex_all_books
    from mnemo.storage import BookRepository, get_connection, init_db

    # Check if there are any books first
    init_db()
    conn = get_connection()
    book_repo = BookRepository(conn)
    books = book_repo.list_all()
    conn.close()

    if not books:
        if json_output:
            print(json.dumps({"results": [], "success": 0, "skipped": 0, "failed": 0}))
        else:
            console.print("No books to reindex")
        return

    if not json_output:
        console.print(f"Reindexing {len(books)} book(s)...")

    preflight_error: str | None = None
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        disable=json_output,
    ) as progress:
        progress.add_task(description="Reindexing all books...", total=None)
        try:
            results = reindex_all_books(embed=True)
        except (ValueError, httpx.HTTPError) as e:
            # Only the embedding preflight escapes here (per-book
            # EmbeddingFailed is handled inside reindex_all_books), so nothing
            # has been touched. Report after the spinner stops.
            preflight_error = str(e)

    if preflight_error is not None:
        if json_output:
            print(json.dumps({"error": preflight_error}))
        else:
            console.print(f"[red]Error: {escape(preflight_error)}[/red]")
            console.print("[yellow]No books were changed.[/yellow]")
        raise typer.Exit(1)

    success = sum(1 for r in results if r["status"] == "success")
    partial = sum(1 for r in results if r["status"] == "partial")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")

    if json_output:
        print(
            json.dumps(
                {
                    "results": results,
                    "success": success,
                    "partial": partial,
                    "skipped": skipped,
                    "failed": failed,
                }
            )
        )
        return

    if verbose:
        for r in results:
            if r["status"] == "success":
                console.print(
                    f"  [green]OK[/green] {escape(str(r['title']))} ({r['book_id']}) - "
                    f"{r['chunks']} chunks"
                )
            elif r["status"] == "partial":
                console.print(
                    f"  [yellow]PARTIAL[/yellow] {escape(str(r['title']))} ({r['book_id']}) - "
                    f"{r['chunks']} chunks, no embeddings: {escape(str(r['error']))}"
                )
            elif r["status"] == "skipped":
                console.print(
                    f"  [yellow]SKIP[/yellow] {escape(str(r['title']))} ({r['book_id']}) - "
                    f"{escape(str(r['error']))}"
                )
            else:
                console.print(
                    f"  [red]FAIL[/red] {escape(str(r['title']))} ({r['book_id']}) - "
                    f"{escape(str(r['error']))}"
                )

    summary = f"[green]{success} succeeded[/green], "
    if partial:
        summary += f"[yellow]{partial} without embeddings[/yellow], "
    summary += f"[yellow]{skipped} skipped[/yellow], [red]{failed} failed[/red]"
    console.print(summary)

    # partial means the book was re-indexed but its vectors were not rewritten
    # — before this existed the same outcome was reported as failed, and a
    # wrapper script must not read it as success.
    if failed > 0 or partial > 0:
        raise typer.Exit(1)


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
            console.print(f"[red]Migration failed: {escape(str(e))}[/red]")
        raise typer.Exit(1) from e
    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise typer.Exit(1) from e


@app.command()
def backup(
    output: Annotated[
        Path | None,
        typer.Argument(help="Output archive path (default: mnemo-backup-TIMESTAMP.tar.gz)"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Back up the library to a .tar.gz archive.

    Creates a portable archive containing the SQLite database and all
    ChromaDB vectors. Use 'mnemo restore' to recreate the library from
    the archive.
    """
    import chromadb

    from mnemo.backup import create_backup
    from mnemo.storage import get_db_path, init_db
    from mnemo.vectors.config import VectorConfig

    # Resolve output path
    if output is None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = Path(f"mnemo-backup-{timestamp}.tar.gz")

    init_db()
    db_path = get_db_path()
    config = VectorConfig()
    chroma_client = chromadb.PersistentClient(path=str(config.get_persist_path()))

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            disable=json_output,
        ) as progress:
            progress.add_task(description="Creating backup...", total=None)
            manifest = create_backup(
                db_path, chroma_client, output, collection_name=config.collection_name
            )

        if json_output:
            print(json.dumps({**manifest, "archive_path": str(output)}))
        else:
            console.print(
                f"[green]Backup created:[/green] {escape(str(output))}\n"
                f"  Books: {manifest['book_count']}, "
                f"Vectors: {manifest['vector_count']}, "
                f"Schema: v{manifest['schema_version']}"
            )

    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Backup failed: {escape(str(e))}[/red]")
        raise typer.Exit(1) from e


@app.command()
def restore(
    archive: Annotated[
        Path,
        typer.Argument(help="Path to the .tar.gz backup archive"),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing data"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Restore a library from a .tar.gz backup archive.

    Recreates the SQLite database and ChromaDB vector collection from
    a backup created with 'mnemo backup'. Use --force to overwrite an
    existing library.
    """
    import chromadb

    from mnemo.backup import restore_backup
    from mnemo.storage import get_db_path
    from mnemo.vectors.config import VectorConfig

    db_path = get_db_path()
    config = VectorConfig()
    chroma_client = chromadb.PersistentClient(path=str(config.get_persist_path()))

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            disable=json_output,
        ) as progress:
            progress.add_task(description="Restoring backup...", total=None)
            manifest = restore_backup(
                archive,
                db_path,
                chroma_client,
                force=force,
                collection_name=config.collection_name,
            )

        if json_output:
            print(json.dumps({**manifest, "archive_path": str(archive)}))
        else:
            console.print(
                f"[green]Restore complete:[/green] {escape(str(archive))}\n"
                f"  Books: {manifest['book_count']}, "
                f"Vectors: {manifest['vector_count']}, "
                f"Schema: v{manifest['schema_version']}"
            )

    except FileExistsError as e:
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error: {escape(str(e))}[/red]")
            console.print("[yellow]Use --force to overwrite existing data.[/yellow]")
        raise typer.Exit(1) from e
    except (ValueError, Exception) as e:
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Restore failed: {escape(str(e))}[/red]")
        raise typer.Exit(1) from e


@app.command()
def serve() -> None:
    """Start the MCP server for Claude.

    Runs the MCP server over STDIO. This command blocks until interrupted.
    """
    from mnemo.mcp.server import mcp  # domain modules registered via server.py imports

    mcp.run()


@app.callback()
def app_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Personal technical book library with semantic search via MCP."""


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
