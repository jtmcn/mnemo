"""Book intake: the one place that decides what happens to a book file.

Both front ends — `mnemo add` and the MCP `add_book` tool — call `intake()` and
render its `IntakeOutcome`. Everything that is a *decision* lives here (is this
a duplicate, is the ISBN suspect, does a failed run leave a partial record);
everything that is *presentation* stays in the caller (Rich colour, markdown,
exit codes, the TTY prompt).

`ingest_book` remains the pipeline underneath — parse, chunk, store, embed —
and stays public for callers who want it without the policy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mnemo.parsing import SUPPORTED_FORMATS, pre_parse_metadata
from mnemo.storage import BookRepository, get_connection, init_db

if TYPE_CHECKING:
    from mnemo.chunking import ChunkerConfig
    from mnemo.models import Book

logger = logging.getLogger(__name__)

DuplicatePolicy = Literal["reject", "skip", "replace"]
IntakeStatus = Literal["added", "replaced", "already_indexed", "rejected"]
RejectReason = Literal[
    "not_found",
    "unsupported_format",
    "duplicate",
    "parse_failed",
    "pipeline_error",
]
NoteKind = Literal["similar_title", "suspect_isbn", "suspect_metadata", "embeddings_skipped"]


def _slug_key(text: str) -> str:
    return " ".join(re.split(r"[\s_-]+", text.lower()))


def _looks_like_filename(title: str, stem: str) -> bool:
    """A spaceless title that reads as a file name, not a hyphenated one like "Catch-22"."""
    if not title or re.search(r"\s", title):
        return False
    return "_" in title or title.count("-") >= 2 or _slug_key(title) == _slug_key(stem)


@dataclass(frozen=True)
class Note:
    """An advisory finding that does not change the outcome.

    `kind` is what renderers switch on; `message` is the composed human text,
    so the CLI and MCP cannot drift into wording the same finding differently.
    """

    kind: NoteKind
    message: str


@dataclass(frozen=True)
class IntakeOutcome:
    """What happened to one book file.

    `embedded` is deliberately separate from `status`: a replace can succeed
    and still lose its vectors, which a single tag cannot express.
    """

    status: IntakeStatus
    book: Book | None
    chunks: int
    embedded: bool
    notes: tuple[Note, ...]
    reason: RejectReason | None
    # Composed once here so the CLI and MCP cannot word the same rejection
    # differently, as they did before intake existed. Empty on success.
    message: str = ""

    @property
    def skipped(self) -> bool:
        """Whether the file was left alone because it was already indexed."""
        return self.status == "already_indexed"


def _rejected(reason: RejectReason, message: str, book: Book | None = None) -> IntakeOutcome:
    """Build a rejection carrying its reason code and the prose to show.

    `message` is what the front ends print; `reason` is what they branch on.
    """
    return IntakeOutcome(
        status="rejected",
        book=book,
        chunks=0,
        embedded=False,
        notes=(),
        reason=reason,
        message=message,
    )


def intake(
    path: Path,
    *,
    on_duplicate: DuplicatePolicy = "reject",
    collection: str | None = None,
    chunker_config: ChunkerConfig | None = None,
    embed: bool = True,
    db_path: Path | None = None,
    chroma_path: Path | None = None,
    force_metadata: bool = False,
) -> IntakeOutcome:
    """Take one book file into the library and report what happened.

    Args:
        path: Book file to take in (.epub, .docx, .pdf)
        on_duplicate: What to do when the file hash or content is already indexed —
            "reject" (default) rejects with reason "duplicate", "skip" reports
            "already_indexed" without touching anything, "replace" re-indexes
            over the existing book.
        collection: Optional collection name, applied only to fresh ingests.
        chunker_config: Chunking configuration override.
        embed: Generate embeddings after storing (default True).
        db_path: SQLite path (default ~/.mnemo/mnemo.db)
        chroma_path: ChromaDB path (default ~/.mnemo/chroma)
        force_metadata: On a replace, take metadata from the file instead of
            keeping the existing book's.

    Returns:
        An IntakeOutcome. Predictable failures are reported as
        status="rejected" with a reason code, never raised.
    """
    path = Path(path)

    if not path.exists():
        return _rejected("not_found", f"File not found: {path}")

    if path.suffix.lower() not in SUPPORTED_FORMATS:
        return _rejected(
            "unsupported_format",
            f"Unsupported format: {path.suffix} "
            f"(supported: {', '.join(sorted(SUPPORTED_FORMATS))})",
        )

    # Hash and (for EPUB) metadata come from here, so a file we cannot read is
    # rejected before anything touches the database.
    try:
        pre_parsed = pre_parse_metadata(path)
    except Exception as e:
        return _rejected("parse_failed", f"Failed to read file: {e}")

    existing, similar = _lookup(pre_parsed, db_path)

    if existing is not None:
        if on_duplicate == "reject":
            return _rejected(
                "duplicate",
                f"Book already indexed (id: {existing.id}).",
                book=existing,
            )
        if on_duplicate == "skip":
            return IntakeOutcome(
                status="already_indexed",
                book=existing,
                chunks=0,
                embedded=False,
                notes=(),
                reason=None,
            )

    notes: list[Note] = []

    from mnemo.ingest import DuplicateBook, EmbeddingFailed, ingest_book

    embed_note: Note | None = None
    # ponytail: ingest_book swallows NothingToEmbed and returns normally, so an
    # all-boilerplate book reads as embedded here. Correcting that needs a
    # return-value change to ingest_book; matches what --json already reports.
    embedded = embed
    started = datetime.now(UTC)
    try:
        book, chunks = ingest_book(
            path,
            db_path=db_path,
            chunker_config=chunker_config,
            force=on_duplicate == "replace",
            embed=embed,
            chroma_path=chroma_path,
            collection=collection,
            force_metadata=force_metadata,
        )
    except EmbeddingFailed as e:
        # Committed and keyword-searchable; only the vectors are missing.
        book, chunks, embedded = e.book, e.chunk_count, False
        embed_note = Note("embeddings_skipped", str(e))
    except DuplicateBook as e:
        # Same content under different file metadata is only found once parsed.
        if on_duplicate == "skip":
            return IntakeOutcome(
                status="already_indexed",
                book=e.book,
                chunks=0,
                embedded=False,
                notes=(),
                reason=None,
            )
        if e.book.file_hash != pre_parsed.file_hash:
            return _rejected(
                "duplicate",
                f"Book already indexed (id: {e.book.id}) with the same content "
                f"but different file metadata.",
                book=e.book,
            )
        return _rejected("duplicate", f"Book already indexed (id: {e.book.id}).", book=e.book)
    except FileNotFoundError as e:
        return _rejected("not_found", str(e))
    except Exception as e:
        # A replacement keeps the old book's added_at, so only a book newer than
        # this run is ours to remove; anything older holds the user's id and edits.
        _discard_partial(pre_parsed.file_hash, started, db_path, chroma_path)
        return _rejected("pipeline_error", f"Failed to add {path}: {e}")

    # A content match replaces a book under its own id, so it is not "similar" to itself.
    others = [b for b in similar if b.id != book.id]
    if others:
        first = others[0]
        authors = ", ".join(first.authors) if first.authors else "Unknown"
        notes.append(
            Note(
                "similar_title",
                f'Similar book exists — "{first.title}" by {authors} (id: {first.id})',
            )
        )

    if book.isbn:
        from mnemo.epub.enrich import validate_isbn

        is_valid, _ = validate_isbn(book.isbn)
        if not is_valid:
            notes.append(Note("suspect_isbn", f"ISBN {book.isbn} may be invalid (bad checksum)"))

    # A content match is only found inside the pipeline; a replaced book keeps its added_at.
    replaced = existing is not None or book.added_at < started
    if _looks_like_filename(book.title, path.stem):
        notes.append(
            Note("suspect_metadata", f'Title "{book.title}" looks like a file name, not a title')
        )

    if embed_note is not None:
        notes.append(embed_note)

    return IntakeOutcome(
        status="replaced" if replaced else "added",
        book=book,
        chunks=chunks,
        embedded=embedded,
        notes=tuple(notes),
        reason=None,
    )


def _lookup(pre_parsed: Book, db_path: Path | None) -> tuple[Book | None, list[Book]]:
    """Find a hard duplicate by hash, and similar titles when there isn't one.

    Soft-duplicate detection is skipped on a hash match: the caller is already
    being told the book is indexed, so "a similar book exists" would be noise.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        repo = BookRepository(conn)
        existing = repo.get_by_hash(pre_parsed.file_hash)
        similar = [] if existing else repo.find_similar_title(pre_parsed.title)
        return existing, similar
    finally:
        conn.close()


def _discard_partial(
    file_hash: str, started: datetime, db_path: Path | None, chroma_path: Path | None
) -> None:
    """Remove a book the failed pipeline had already added since `started`.

    Best effort: the run has already failed, and a cleanup error would mask
    the real cause.
    """
    from mnemo.ingest import remove_book

    try:
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            partial = BookRepository(conn).get_by_hash(file_hash)
        finally:
            conn.close()
        if partial and partial.added_at >= started:
            remove_book(partial.id, db_path=db_path, chroma_path=chroma_path)
    except Exception:
        logger.exception("Cleanup after a failed intake did not complete")
