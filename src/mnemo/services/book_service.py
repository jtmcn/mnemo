"""Book intake: the one place that decides what happens to a book file.

Both front ends call `intake()` (for `add`) and `reindex()`, and render the
`IntakeOutcome` or `ReindexReport` they return. Everything that is a *decision* lives here (is this
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
            "reject" (default) rejects with reason "duplicate" (same bytes) or
            "duplicate_content" (same parsed content), "skip" reports
            "already_indexed" without touching anything, "replace" re-indexes
            over the existing book.
        collection: Optional collection name. On a replace it overrides the
            existing Book's; when omitted, the existing one is kept.
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


ReindexStatus = Literal["success", "partial", "skipped", "failed", "merged"]

# Summary order and wording, shared so the CLI and MCP headlines cannot drift.
_SUMMARY_WORDS: tuple[tuple[ReindexStatus, str], ...] = (
    ("success", "succeeded"),
    ("partial", "without embeddings"),
    ("merged", "merged"),
    ("skipped", "skipped"),
    ("failed", "failed"),
)
_SHOWN_WHEN_ZERO = frozenset({"success", "skipped", "failed"})


@dataclass(frozen=True)
class ReindexRow:
    """What reindex did with one library entry.

    `partial` stored but did not embed; `merged` was folded into a byte-identical
    entry. `message` says why a row is not a plain success; empty when it is.
    """

    book_id: str
    title: str
    status: ReindexStatus
    chunks: int
    message: str = ""


@dataclass(frozen=True)
class ReindexReport:
    """Every entry reindex touched, in library order."""

    rows: tuple[ReindexRow, ...]

    def count(self, status: ReindexStatus) -> int:
        return sum(1 for r in self.rows if r.status == status)

    @property
    def counts(self) -> dict[ReindexStatus, int]:
        return {status: self.count(status) for status, _ in _SUMMARY_WORDS}

    @property
    def ok(self) -> bool:
        """False when a book failed or lost its vectors; merged and skipped are fine."""
        return not (self.count("failed") or self.count("partial"))

    def summary(self) -> tuple[tuple[ReindexStatus, str], ...]:
        """Headline segments like ("partial", "2 without embeddings"), for front ends to style."""
        return tuple(
            (status, f"{n} {words}")
            for status, words in _SUMMARY_WORDS
            if (n := self.count(status)) or status in _SHOWN_WHEN_ZERO
        )


def reindex(
    *,
    chunker_config: ChunkerConfig | None = None,
    embed: bool = True,
    db_path: Path | None = None,
    chroma_path: Path | None = None,
) -> ReindexReport:
    """Re-read every Book from its source file and store it again in place.

    Each Book keeps its id and edited metadata. Entries whose files are now
    byte-identical fold into one (`merged`); entries that only share content
    are kept apart. The first embedding failure stops the run, since storing
    deletes a Book's old vectors first; the rest are reported `skipped`.

    Raises:
        ValueError: embed=True with no embedding endpoint configured.
        httpx.HTTPError: embed=True with an endpoint that rejects a probe.
            Both are raised before any Book is touched.
    """
    # A real round-trip is the only check that catches a bad key or model.
    if embed:
        from mnemo.embeddings import Embedder

        Embedder().embed_one("preflight")

    init_db(db_path)
    with closing(get_connection(db_path)) as conn:
        books = BookRepository(conn).list_all()

    rows: list[ReindexRow] = []
    file_hashes: dict[str, str] = {}
    for index, book in enumerate(books):
        if not book.file_path or not Path(book.file_path).exists():
            reason = "Source file not found" if book.file_path else "No file path stored"
            rows.append(ReindexRow(book.id, book.title, "skipped", 0, reason))
            continue
        try:
            plan = _reindex_plan(book, Path(book.file_path), file_hashes, db_path)
            if isinstance(plan, ReindexRow):
                rows.append(plan)
                continue
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
            rows.append(ReindexRow(book.id, book.title, "failed", 0, str(e)))
            continue

        file_hashes[stored.book.id] = stored.book.file_hash
        if stored.embedding == "failed":
            rows.append(
                ReindexRow(
                    stored.book.id,
                    stored.book.title,
                    "partial",
                    stored.chunks,
                    stored.embed_error or "embedding failed",
                )
            )
            # Every Book embeds the same way, so the rest would fail too, losing their vectors.
            rows.extend(
                ReindexRow(
                    other.id,
                    other.title,
                    "skipped",
                    0,
                    "Stopped after an embedding failure; not re-indexed",
                )
                for other in books[index + 1 :]
            )
            break
        if stored.book.id != book.id:
            rows.append(_merged(book, stored.book.id))
        else:
            rows.append(ReindexRow(stored.book.id, stored.book.title, "success", stored.chunks))

    return ReindexReport(_relabel_folded(rows, file_hashes, db_path))


def _reindex_plan(
    book: Book, source: Path, file_hashes: dict[str, str], db_path: Path | None
) -> _Plan | ReindexRow:
    """Store `book` in place, absorbing any byte-identical entry, or say it already folded."""
    parsed, blocks = parse_book(source)
    parsed = parsed.model_copy(
        update={"file_path": str(source.resolve()), "collection": book.collection}
    )
    with closing(get_connection(db_path)) as conn:
        repo = BookRepository(conn)
        twin = repo.get_by_hash(parsed.file_hash)
        current = repo.get(book.id)
    if current is None and twin is not None and twin.id in file_hashes:
        # Already folded into a byte-twin this run stored; storing again would re-embed it.
        return _merged(book, twin.id)
    previous = current or twin
    return _Plan(
        carry_over(parsed, previous, False) if previous else parsed,
        blocks,
        frozenset({book.id} | ({twin.id} if twin else set())),
        (),
    )


def _merged(book: Book, survivor_id: str) -> ReindexRow:
    return ReindexRow(book.id, book.title, "merged", 0, f"same file as {survivor_id}")


def _relabel_folded(
    rows: list[ReindexRow], file_hashes: dict[str, str], db_path: Path | None
) -> tuple[ReindexRow, ...]:
    """Relabel stored rows whose Book a later byte-identical entry absorbed."""
    with closing(get_connection(db_path)) as conn:
        library = BookRepository(conn).list_all()
    live = {b.id for b in library}
    out: list[ReindexRow] = []
    for row in rows:
        if row.status in ("success", "partial") and row.book_id not in live:
            digest = file_hashes.get(row.book_id)
            survivor = next((b.id for b in library if b.file_hash == digest), None)
            message = f"same file as {survivor}" if survivor else "same file as another entry"
            row = ReindexRow(row.book_id, row.title, "merged", 0, message)
        out.append(row)
    return tuple(out)
