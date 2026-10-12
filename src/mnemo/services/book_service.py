"""Book intake: the one place that decides what happens to a book file.

Both front ends — `mnemo add` and the MCP `add_book` tool — call `intake()` and
render its `IntakeOutcome`. Everything that is a *decision* lives here (is this
a duplicate, is the ISBN suspect, does a failed run leave a partial record);
everything that is *presentation* stays in the caller (Rich colour, markdown,
exit codes, the TTY prompt).

`store_book` is the pipeline underneath: it executes the plan intake decides.
"""

from __future__ import annotations

import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mnemo.ingest import Stored, carry_over, store_book
from mnemo.parsing import SUPPORTED_FORMATS, ContentBlock, hash_file, parse_book
from mnemo.storage import BookRepository, get_connection, init_db

if TYPE_CHECKING:
    from mnemo.chunking import ChunkerConfig
    from mnemo.models import Book

DuplicatePolicy = Literal["reject", "skip", "replace"]
IntakeStatus = Literal["added", "replaced", "already_indexed", "rejected"]
RejectReason = Literal[
    "not_found",
    "unsupported_format",
    "duplicate",
    "duplicate_content",
    "parse_failed",
    "pipeline_error",
]
NoteKind = Literal[
    "similar_title", "suspect_isbn", "suspect_metadata", "embeddings_skipped", "nothing_to_embed"
]


def _slug_key(text: str) -> str:
    return " ".join(re.split(r"[\s_-]+", text.lower()))


def _looks_like_filename(title: str, stem: str) -> bool:
    """A spaceless title that reads as a file name, not a hyphenated one like "Catch-22"."""
    if not title or re.search(r"\s", title):
        return False
    if "_" in title or title.count("-") >= 2:
        return True
    # A one-word title ("Dune") in Dune.pdf is just a well-named file.
    return "-" in title and _slug_key(title) == _slug_key(stem)


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

    try:
        digest = hash_file(path)
    except OSError as e:
        return _rejected("parse_failed", f"Failed to read file: {e}")

    plan = _plan(path, digest, on_duplicate, collection, force_metadata, db_path)
    if isinstance(plan, IntakeOutcome):
        return plan

    try:
        stored = store_book(
            plan.book,
            plan.blocks,
            replaces=plan.replaces,
            chunker_config=chunker_config,
            embed=embed,
            db_path=db_path,
            chroma_path=chroma_path,
        )
    except Exception as e:
        return _rejected("pipeline_error", f"Failed to add {path}: {e}")

    return IntakeOutcome(
        status="replaced" if plan.replaces else "added",
        book=stored.book,
        chunks=stored.chunks,
        embedded=stored.embedding == "embedded",
        notes=_notes(stored, plan.similar, path),
        reason=None,
    )


@dataclass(frozen=True)
class _Plan:
    """What intake decided to store, and which existing Book it replaces."""

    book: Book
    blocks: list[ContentBlock]
    replaces: frozenset[str]
    similar: tuple[Book, ...]


def _plan(
    path: Path,
    digest: str,
    on_duplicate: DuplicatePolicy,
    collection: str | None,
    force_metadata: bool,
    db_path: Path | None,
) -> _Plan | IntakeOutcome:
    """Decide what to store and what it replaces, or say why nothing is stored."""
    init_db(db_path)
    with closing(get_connection(db_path)) as conn:
        repo = BookRepository(conn)
        twin = repo.get_by_hash(digest)
        # Checked before parsing, so skipping a known file stays cheap.
        if twin is not None and on_duplicate != "replace":
            return _duplicate(twin, "duplicate", on_duplicate)

        try:
            parsed, blocks = parse_book(path)
        except Exception as e:
            return _rejected("parse_failed", f"Failed to read {path.name}: {e}")

        match = twin
        if match is None and parsed.content_hash:
            match = repo.get_by_content_hash(parsed.content_hash)
            if match is not None and on_duplicate != "replace":
                return _duplicate(match, "duplicate_content", on_duplicate)

        updates: dict[str, str] = {"file_path": str(path.resolve())}
        if collection:
            updates["collection"] = collection
        book = parsed.model_copy(update=updates)
        if match is not None:
            book = carry_over(book, match, force_metadata)

        # A byte match is already this book, so a similar-title note would be noise.
        similar = (
            () if twin else tuple(b for b in repo.find_similar_title(book.title) if b.id != book.id)
        )
    return _Plan(book, blocks, frozenset({match.id}) if match else frozenset(), similar)


def _duplicate(
    existing: Book, reason: RejectReason, on_duplicate: DuplicatePolicy
) -> IntakeOutcome:
    if on_duplicate == "skip":
        return IntakeOutcome(
            status="already_indexed",
            book=existing,
            chunks=0,
            embedded=False,
            notes=(),
            reason=None,
        )
    detail = (
        " with the same content but different file metadata"
        if reason == "duplicate_content"
        else ""
    )
    return _rejected(reason, f"Book already indexed (id: {existing.id}){detail}.", book=existing)


def _notes(stored: Stored, similar: tuple[Book, ...], path: Path) -> tuple[Note, ...]:
    book = stored.book
    notes: list[Note] = []
    if similar:
        first = similar[0]
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
    if _looks_like_filename(book.title, path.stem):
        notes.append(
            Note("suspect_metadata", f'Title "{book.title}" looks like a file name, not a title')
        )
    if stored.embedding == "failed":
        notes.append(Note("embeddings_skipped", stored.embed_error or "embedding failed"))
    elif stored.embedding == "nothing_to_embed":
        notes.append(
            Note(
                "nothing_to_embed",
                "Only front and back matter, so there is nothing to embed; keyword search works.",
            )
        )
    return tuple(notes)
