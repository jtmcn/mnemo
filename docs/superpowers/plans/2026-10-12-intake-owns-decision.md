# Intake Owns the Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Intake makes every add/replace/duplicate decision with all hashes in hand, and the pipeline only executes the plan it is given.

**Architecture:** Intake (`services/book_service.py`) hashes the file bytes, looks up a byte match, parses once, looks up a content match, builds the final Book (carry-over included) and decides what it replaces. A new pipeline function `store_book` (`ingest.py`) chunks, swaps rows in one transaction, removes stale vectors, embeds, and *returns* what happened to the embedding instead of raising. `ingest_book`, `DuplicateBook`, `EmbeddingFailed` and `pre_parse_metadata` are deleted; reindex calls `store_book` directly.

**Tech Stack:** Python 3.11–3.13, pydantic models, SQLite, ChromaDB, pytest, ruff, mypy.

**Spec:** The settled design (D1–D10) from the architecture review, recorded in the "Decisions" section below.

## Decisions

- **D1** Intake hashes bytes first (no parse), so a byte-duplicate skip/reject never parses. Then it calls `parse_book` once; content match and similar-title run on the parsed title. `pre_parse_metadata` is deleted. A file that fails to parse is `parse_failed`.
- **D2** `store_book(book, blocks, *, replaces, chunker_config, embed, db_path, chroma_path) -> Stored`. No `force`, no lookups, no policy exceptions.
- **D3** Intake builds the final Book (previous id, `added_at`, edited fields unless `force_metadata`). The similar-title, filename and ISBN notes read that final Book.
- **D4** The read-decide-write race is unchanged from today; a losing writer surfaces as `pipeline_error`.
- **D5** `Stored.embedding` is `"embedded" | "nothing_to_embed" | "failed" | "not_requested"`. `IntakeOutcome.embedded` is true only for `"embedded"`. New Note kind `nothing_to_embed`.
- **D6** `RejectReason` gains `duplicate_content`; `duplicate` means same bytes. Front ends stop sniffing `"same content"` in the message.
- **D7** Nothing before the commit is durable and nothing after it undoes the commit, so `_discard_partial` and the `added_at < started` inference go. A failed stale-vector delete after commit reports `embedding="failed"` (partial success), not an error.
- **D8** Reindex moves onto `store_book` but keeps `ReindexResult`. The MCP timeout cleanup stays, using `hash_file`.
- **D9** Intake tests go through `intake()` on a temp DB; CLI/MCP tests patch `mnemo.services.book_service.intake` and assert rendering.
- **D10** Removing `ingest_book`/`EmbeddingFailed` from `mnemo.__all__` is breaking: version 3.0.0, then `uv lock`.

## Global Constraints

- Code comments: 1–2 lines, only the non-obvious why.
- Gates before every commit: `ruff format --check src/ tests/`, `ruff check src/ tests/`, `mypy src/`, `pytest -m "not integration"`. Coverage stays ≥ 80%.
- No test skips or ignore comments.
- Commits end with the Co-Authored-By line from the session's attribution reminder.
- Branch: `joel/intake-owns-decision`.

## Review Focus

1. A PDF/DOCX whose parsed title differs from its filename gets the similar-title note against the parsed title (the bug this fixes). Test in Task 2.
2. Skipping a byte duplicate must not parse the file (bulk `add --skip-existing` stays fast). Test in Task 2.
3. A replace whose re-parse fails keeps the existing book and its edits, reported as `parse_failed`. Test in Task 2.
4. A stale-vector delete that fails after commit leaves the new book stored, edits carried, no orphan chunks, and reports `embeddings_skipped`. Test in Task 1 (pipeline) and Task 2 (intake).
5. Reindex of an entry whose byte-twin was already folded still reports `merged`. Existing `TestReindexAllBooks` tests in Task 3.

---

### Task 1: The `store_book` pipeline

**Files:**
- Modify: `src/mnemo/ingest.py` (add `Stored`, `EmbedStatus`, `store_book`; rename `_carry_over` → `carry_over`)
- Modify: `src/mnemo/parsing/dispatch.py`, `src/mnemo/parsing/__init__.py` (add `hash_file`)
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `hash_file(path: Path) -> str` (SHA-256 hex of the bytes) in `mnemo.parsing`
  - `EmbedStatus = Literal["embedded", "nothing_to_embed", "failed", "not_requested"]`
  - `@dataclass(frozen=True) class Stored: book: Book; chunks: int; embedding: EmbedStatus; embed_error: str | None = None`
  - `store_book(book: Book, blocks: list[ContentBlock], *, replaces: frozenset[str] = frozenset(), chunker_config: ChunkerConfig | None = None, embed: bool = False, db_path: Path | None = None, chroma_path: Path | None = None) -> Stored`
  - `carry_over(parsed: Book, previous: Book, force_metadata: bool) -> Book` (body unchanged from `_carry_over`)

- [ ] **Step 1: Write failing tests** in `tests/test_pipeline.py`:

```python
"""store_book executes a decided plan: it never looks up duplicates or raises for policy."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mnemo.ingest import NothingToEmbed, Stored, store_book
from mnemo.parsing import hash_file, parse_book
from mnemo.storage import BookRepository, ChunkRepository, get_connection, init_db

SAMPLE = Path("tests/fixtures/sample.epub")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def _books(db: Path) -> list[tuple[str, str]]:
    init_db(db)
    conn = get_connection(db)
    try:
        return [(b.id, b.title) for b in BookRepository(conn).list_all()]
    finally:
        conn.close()


def test_hash_file_matches_the_parsers_file_hash():
    book, _ = parse_book(SAMPLE)
    assert hash_file(SAMPLE) == book.file_hash


def test_stores_the_book_it_is_given(db: Path):
    book, blocks = parse_book(SAMPLE)
    stored = store_book(book, blocks, db_path=db)

    assert isinstance(stored, Stored)
    assert stored.embedding == "not_requested"
    assert stored.chunks > 0
    assert _books(db) == [(book.id, book.title)]


def test_does_not_check_for_duplicates(db: Path):
    """The pipeline stores what it is told; a second store of the same id is the caller's call."""
    book, blocks = parse_book(SAMPLE)
    store_book(book, blocks, db_path=db)
    stored = store_book(book.model_copy(update={"title": "Edited"}), blocks, replaces=frozenset({book.id}), db_path=db)

    assert stored.book.title == "Edited"
    assert _books(db) == [(book.id, "Edited")]


def test_chunker_failure_changes_nothing(db: Path):
    book, blocks = parse_book(SAMPLE)
    store_book(book, blocks, db_path=db)
    with patch("mnemo.ingest.Chunker.chunk", side_effect=RuntimeError("chunker broke")):
        with pytest.raises(RuntimeError, match="chunker broke"):
            store_book(book.model_copy(update={"title": "New"}), blocks, replaces=frozenset({book.id}), db_path=db)

    assert _books(db) == [(book.id, book.title)]


def test_stale_vector_failure_after_commit_is_partial_success(db: Path):
    book, blocks = parse_book(SAMPLE)
    store_book(book, blocks, db_path=db)
    with patch("mnemo.vectors.VectorStore", side_effect=RuntimeError("chroma down")):
        stored = store_book(book.model_copy(update={"title": "New"}), blocks, replaces=frozenset({book.id}), db_path=db)

    assert stored.embedding == "failed"
    assert stored.embed_error is not None and "chroma down" in stored.embed_error
    assert _books(db) == [(book.id, "New")]
    conn = get_connection(db)
    try:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE book_id NOT IN (SELECT id FROM books)"
        ).fetchone()[0]
        assert ChunkRepository(conn).count_by_book(book.id) == stored.chunks
    finally:
        conn.close()
    assert orphans == 0


@pytest.mark.parametrize(
    ("side_effect", "status"),
    [(None, "embedded"), (NothingToEmbed("all boilerplate"), "nothing_to_embed"), (ValueError("no key"), "failed")],
)
def test_embedding_outcome_is_returned_not_raised(db: Path, side_effect, status):
    book, blocks = parse_book(SAMPLE)
    with patch("mnemo.ingest.embed_book", side_effect=side_effect, return_value=3):
        stored = store_book(book, blocks, embed=True, db_path=db)

    assert stored.embedding == status
    assert _books(db) == [(book.id, book.title)]
```

- [ ] **Step 2: Run, expect ImportError** — `pytest tests/test_pipeline.py -v`.

- [ ] **Step 3: Implement.** In `dispatch.py`, add and export from `parsing/__init__.py`:

```python
def hash_file(file_path: Path | str) -> str:
    """SHA-256 of the file bytes: a Book's `file_hash`, without parsing."""
    return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
```

In `ingest.py` (add `from dataclasses import dataclass` and `from mnemo.parsing import ContentBlock`), rename `_carry_over` → `carry_over`, then add after `_delete_vectors`:

```python
EmbedStatus = Literal["embedded", "nothing_to_embed", "failed", "not_requested"]


@dataclass(frozen=True)
class Stored:
    """What the pipeline did with a book it was told to store."""

    book: Book
    chunks: int
    embedding: EmbedStatus
    embed_error: str | None = None


def store_book(
    book: Book,
    blocks: list[ContentBlock],
    *,
    replaces: frozenset[str] = frozenset(),
    chunker_config: ChunkerConfig | None = None,
    embed: bool = False,
    db_path: Path | None = None,
    chroma_path: Path | None = None,
) -> Stored:
    """Chunk, store and optionally embed `book`, removing the books in `replaces`.

    Executes a decision intake already made: no duplicate lookups, no policy.
    Raises only before the commit, when nothing has changed.
    """
    chunks = Chunker(chunker_config).chunk(book.id, blocks)

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        book_repo = BookRepository(conn)
        chunk_repo = ChunkRepository(conn)
        for stale_id in replaces:
            book_repo.delete(stale_id, commit=False)
        book_repo.add(book, commit=False)
        chunk_repo.add_many(chunks, commit=False)
        conn.commit()
    finally:
        conn.close()

    # Past the commit the book is durable, so vector trouble is partial success.
    if replaces:
        try:
            _delete_vectors(set(replaces), chroma_path)
        except Exception as e:
            logger.info("Removing old vectors failed for %s: %s", book.id, e)
            return Stored(book, len(chunks), "failed", f"Old vectors could not be removed: {e}")

    if not embed:
        return Stored(book, len(chunks), "not_requested")
    try:
        embed_book(book.id, db_path=db_path, chroma_path=chroma_path)
    except NothingToEmbed:
        return Stored(book, len(chunks), "nothing_to_embed")
    except Exception as e:
        logger.info("Embedding failed for %s (%s): %s", book.id, book.title, e)
        return Stored(book, len(chunks), "failed", str(e))
    return Stored(book, len(chunks), "embedded")
```

Update `ingest_book`'s call `_carry_over(` → `carry_over(` so it keeps working until Task 4.

- [ ] **Step 4: Run** `pytest tests/test_pipeline.py tests/test_integration.py -q` — expect PASS.
- [ ] **Step 5: Gates, then commit** `feat: store_book pipeline that executes a decided plan and returns its embedding outcome`.

---

### Task 2: Intake decides with every hash in hand

**Files:**
- Modify: `src/mnemo/services/book_service.py` (rewrite `intake`, add `_plan`; delete `_lookup`, `_discard_partial`)
- Modify: `src/mnemo/cli.py:132-137` (treat `duplicate_content` like `duplicate`)
- Modify: `src/mnemo/mcp/tools_books.py:84-95` (switch on reason, not message)
- Test: `tests/test_intake.py`

**Interfaces:**
- Consumes: `hash_file`, `parse_book`, `store_book`, `Stored`, `carry_over` from Task 1.
- Produces: `RejectReason` gains `"duplicate_content"`; `NoteKind` gains `"nothing_to_embed"`. `intake()` signature unchanged.

- [ ] **Step 1: Write/adjust failing tests** in `tests/test_intake.py`:

Add to `TestNotes`:

```python
    def test_similar_title_uses_the_parsed_pdf_title(self, tmp_path: Path, temp_db: Path):
        """A PDF's title comes from its metadata, not its file name."""
        intake(create_test_pdf(tmp_path / "a.pdf", items=[Para("First book body. " * 20)], title="Domain Driven Design"), db_path=temp_db, embed=False)

        outcome = intake(create_test_pdf(tmp_path / "scan-0042.pdf", items=[Para("Different body text. " * 20)], title="Domain-Driven Design"), db_path=temp_db, embed=False)

        assert outcome.status == "added"
        assert "similar_title" in kinds(outcome)
```

Replace `test_skip_does_not_run_the_pipeline` with:

```python
    def test_skip_does_not_parse(self, indexed, sample_epub: Path, temp_db: Path):
        """A byte duplicate is skipped on its hash alone, so bulk --skip-existing stays fast."""
        with patch("mnemo.services.book_service.parse_book") as parse:
            outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="skip")

        assert outcome.status == "already_indexed"
        parse.assert_not_called()
```

In `TestRejections`: `test_pdf_without_text_is_rejected` expects `reason == "parse_failed"`; `test_pipeline_failure_is_reported_not_raised` patches `mnemo.services.book_service.store_book`; delete `test_pipeline_failure_cleans_up_a_stored_book` (D7: nothing past the commit raises).

In `TestEmbedding`, `test_nothing_to_embed_advises_no_retry` becomes:

```python
    def test_nothing_to_embed_is_its_own_note(self, sample_epub: Path, temp_db: Path):
        """All-boilerplate books can never be embedded, so no retry advice fires."""
        from mnemo.ingest import NothingToEmbed

        with patch("mnemo.ingest.embed_book", side_effect=NothingToEmbed("all boilerplate")):
            outcome = intake(sample_epub, db_path=temp_db, embed=True)

        assert outcome.status == "added"
        assert outcome.embedded is False
        assert "nothing_to_embed" in kinds(outcome)
        assert "embeddings_skipped" not in kinds(outcome)
```

In `TestCleanupIsNotDestructive` (rename to `TestFailedReplaceKeepsTheBook`): `test_failed_replace_keeps_the_existing_book` patches `mnemo.services.book_service.parse_book` and expects `reason == "parse_failed"` (drop the pre_parse docstring). `test_committed_content_replace_is_not_discarded` now expects `status == "replaced"`, `embedded is False`, `"embeddings_skipped" in kinds(outcome)`, and the one book is `(first.book.id, "The Ontology Pipeline")`.

In `TestFailureClassification`: `test_validation_error_is_not_a_duplicate` patches `mnemo.services.book_service.parse_book` and expects `parse_failed`; delete `test_duplicate_raised_by_the_pipeline_carries_its_book` (no such raise exists).

In `TestContentDuplicates.test_reject`: expect `reason == "duplicate_content"`.

- [ ] **Step 2: Run** `pytest tests/test_intake.py -q` — expect the new/changed tests to FAIL.

- [ ] **Step 3: Implement** in `book_service.py`. Module imports become:

```python
from contextlib import closing
from mnemo.ingest import Stored, carry_over, store_book
from mnemo.parsing import SUPPORTED_FORMATS, ContentBlock, hash_file, parse_book
from mnemo.storage import BookRepository, get_connection, init_db
```

(Check `mnemo.ingest` does not import `mnemo.services` at module level, so the import is acyclic.)

Add `"duplicate_content"` to `RejectReason` and `"nothing_to_embed"` to `NoteKind`. Replace `intake`'s body after the suffix check, and `_lookup`/`_discard_partial`, with:

```python
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
    """Decide what to store and what it replaces, or why nothing is stored."""
    init_db(db_path)
    with closing(get_connection(db_path)) as conn:
        repo = BookRepository(conn)
        twin = repo.get_by_hash(digest)
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

        # A byte match is already "this book", so a similar-title note would be noise.
        similar = () if twin else tuple(
            b for b in repo.find_similar_title(book.title) if b.id != book.id
        )
    return _Plan(book, blocks, frozenset({match.id}) if match else frozenset(), similar)


def _duplicate(existing: Book, reason: RejectReason, on_duplicate: DuplicatePolicy) -> IntakeOutcome:
    if on_duplicate == "skip":
        return IntakeOutcome(
            status="already_indexed", book=existing, chunks=0, embedded=False, notes=(), reason=None
        )
    detail = " with the same content but different file metadata" if reason == "duplicate_content" else ""
    return _rejected(reason, f"Book already indexed (id: {existing.id}){detail}.", book=existing)


def _notes(stored: Stored, similar: tuple[Book, ...], path: Path) -> tuple[Note, ...]:
    book = stored.book
    notes: list[Note] = []
    if similar:
        first = similar[0]
        authors = ", ".join(first.authors) if first.authors else "Unknown"
        notes.append(Note("similar_title", f'Similar book exists — "{first.title}" by {authors} (id: {first.id})'))
    if book.isbn:
        from mnemo.epub.enrich import validate_isbn

        if not validate_isbn(book.isbn)[0]:
            notes.append(Note("suspect_isbn", f"ISBN {book.isbn} may be invalid (bad checksum)"))
    if _looks_like_filename(book.title, path.stem):
        notes.append(Note("suspect_metadata", f'Title "{book.title}" looks like a file name, not a title'))
    if stored.embedding == "failed":
        notes.append(Note("embeddings_skipped", stored.embed_error or "embedding failed"))
    elif stored.embedding == "nothing_to_embed":
        notes.append(Note("nothing_to_embed", "Only front and back matter, so there is nothing to embed; keyword search works."))
    return tuple(notes)
```

Delete the `datetime`, `logging`/`logger` (if now unused), `pre_parse_metadata` imports, the ponytail comment, and update the module docstring's last paragraph: "`store_book` is the pipeline underneath: it executes the plan intake decides."

In `cli.py:132-137`, replace both `outcome.reason == "duplicate"` checks with `outcome.reason in ("duplicate", "duplicate_content")`.

In `tools_books.py` `_render_intake`:

```python
        if outcome.reason in ("duplicate", "duplicate_content") and book is not None:
            authors = ", ".join(book.authors) if book.authors else "Unknown"
            what = (
                "Book with the same content but different file metadata already exists"
                if outcome.reason == "duplicate_content"
                else "Book already exists"
            )
```

- [ ] **Step 4: Run** `pytest tests/test_intake.py tests/test_pipeline.py -q` — expect PASS. Run `pytest -m "not integration" -q`; `test_cli.py`/`test_mcp.py` failures that patch `pre_parse_metadata`/`ingest_book` are expected and fixed in Task 4 — note them, fix any *other* failure now.
- [ ] **Step 5: Gates (format, lint, types), commit** `refactor: intake decides add, replace or duplicate with every hash in hand`. If the non-integration suite is red only for the Task 4 tests, fold Task 4 in before committing instead, so every commit is green.

---

### Task 3: Reindex on `store_book`

**Files:**
- Modify: `src/mnemo/ingest.py` (`reindex_all_books` body)
- Test: `tests/test_integration.py::TestReindexAllBooks`, `TestEmbeddingFailureIsPartialSuccess::test_reindex_marks_unembedded_books_partial` (unchanged; must stay green)

**Interfaces:**
- Consumes: `store_book`, `Stored`, `carry_over`, `parse_book`.
- Produces: `reindex_all_books` unchanged signature and `ReindexResult` shape.

- [ ] **Step 1: Run** `pytest tests/test_integration.py -k "Reindex or reindex" -q` to record the green baseline.
- [ ] **Step 2: Implement.** Replace the `try:` block in the loop with:

```python
        try:
            parsed, blocks = parse_book(Path(book_file))
            parsed = parsed.model_copy(
                update={"file_path": str(Path(book_file).resolve()), "collection": book.collection}
            )
            conn = get_connection(db_path)
            try:
                repo = BookRepository(conn)
                twin = repo.get_by_hash(parsed.file_hash)
                # An earlier iteration may have folded this entry into its byte-twin.
                previous = repo.get(book.id) or twin
            finally:
                conn.close()
            new_book = carry_over(parsed, previous, False) if previous else parsed
            replaces = frozenset({book.id} | ({twin.id} if twin else set()))
            stored = store_book(
                new_book, blocks, replaces=replaces, chunker_config=chunker_config,
                embed=embed, db_path=db_path, chroma_path=chroma_path,
            )
```

Then branch on `stored`: keep the `new_book.id != book.id` → `merged` row (using `stored.book.id`), record `file_hashes[stored.book.id]`. If `stored.embedding == "failed"`, append the `partial` row (`chunks=stored.chunks`, `error=stored.embed_error`) and run the existing stop-and-skip-the-rest block, then `break`. Otherwise append the `success` row. Delete the `except EmbeddingFailed` branch; keep `except Exception` → `failed`. Update the preflight comment to say `store_book` instead of `ingest_book` and drop "(step 5)".

- [ ] **Step 3: Run** the Step 1 selection — expect PASS, same results.
- [ ] **Step 4: Gates, commit** `refactor: reindex runs on store_book`.

---

### Task 4: Delete the old pipeline and its exceptions; migrate tests

**Files:**
- Modify: `src/mnemo/ingest.py` (delete `ingest_book`, `DuplicateBook`, `EmbeddingFailed`)
- Modify: `src/mnemo/parsing/dispatch.py`, `parsing/__init__.py` (delete `pre_parse_metadata`)
- Modify: `src/mnemo/__init__.py` (exports), `src/mnemo/cli.py:499` comment, `src/mnemo/mcp/tools_books.py:286-291`
- Modify: `tests/test_integration.py`, `tests/test_embedding_integration.py`, `tests/test_cli.py`, `tests/test_mcp.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `mnemo.__all__` = `intake, IntakeOutcome, Note, embed_book, remove_book, Book, Chunk, ContentType`.

- [ ] **Step 1: Delete** the three names from `ingest.py`, `pre_parse_metadata` from parsing, and update `mnemo/__init__.py` docstring and `__all__` (drop `ingest_book`, `EmbeddingFailed`). In `tools_books.add_book`, replace the `pre_parse_metadata` hash with `from mnemo.parsing import hash_file` and `file_hash = hash_file(Path(file_path))` inside the same `try/except Exception`. Fix the `cli.py:499` comment to name `store_book`.

- [ ] **Step 2: Migrate `test_integration.py` and `test_embedding_integration.py`** with this rule:
  - `book, n = ingest_book(p, db, ...)` → `o = intake(p, db_path=db, embed=False, ...)`, then `book, n = o.book, o.chunks`. `force=True` → `on_duplicate="replace"`; `embed=True` → `embed=True`.
  - `pytest.raises(ValueError|DuplicateBook)` on a re-add → `assert o.status == "rejected" and o.reason in {"duplicate", "duplicate_content"}`; `exc.value.book.id` → `o.book.id`.
  - `pytest.raises(EmbeddingFailed)` → `assert o.status == "added" and not o.embedded and "embeddings_skipped" in {n.kind for n in o.notes}`.
  - `TestReplaceIsAtomic` failures raised from the chunker now arrive as `o.reason == "pipeline_error"`; the vector-store-open test expects `o.status == "replaced"`, `not o.embedded`, carried title, no orphans.
  - `TestConnectionLifetime` targets `store_book` (`mnemo_ingest.get_connection` spy, failure via `Chunker.chunk`); drop the DuplicateBook-path test (no longer exists in the pipeline) and add the same closed-connection check for `intake`'s byte-duplicate rejection by spying `mnemo.services.book_service.get_connection`.

- [ ] **Step 3: Migrate `test_cli.py` and `test_mcp.py` add tests** to patch the seam, not its internals. Replace `stub_intake` in `test_cli.py` with:

```python
def outcome(status="added", *, reason=None, notes=(), embedded=True, chunks=5, book=None, message=""):
    """An IntakeOutcome for front-end rendering tests."""
    from mnemo.models import Book
    from mnemo.services.book_service import IntakeOutcome

    book = book or Book(id="abc123", title="Test", authors=["A"], file_hash="a" * 64, structure_source="toc")
    return IntakeOutcome(status=status, book=book, chunks=chunks, embedded=embedded, notes=tuple(notes), reason=reason, message=message)
```

and patch `mnemo.services.book_service.intake` with `return_value=outcome(...)` (or `side_effect=[...]` for the prompt-then-replace flow). Assertions on `ingest_book` kwargs (`collection=...`, `force=...`) become assertions on `intake`'s kwargs (`collection=...`, `on_duplicate=...`). `EmbeddingFailed` side effects become `outcome(embedded=False, notes=[Note("embeddings_skipped", "nope")])`; the raced `DuplicateBook` test becomes `outcome("rejected", reason="duplicate", message="Book already indexed (id: abc123).")`. Add one MCP test that `reason="duplicate_content"` renders "same content but different file metadata". Same rule in `test_mcp.py`; the test at ~1365 that inserts a book into a temp DB via a fake `ingest_book` should call the real `intake` on a fixture file with `db_path` instead.

- [ ] **Step 4: Run** `grep -rn "ingest_book\|DuplicateBook\|EmbeddingFailed\|pre_parse_metadata\|_discard_partial" src tests` — expect no hits except historical comments you then reword. Run `pytest -q` (all, including integration if it runs locally) — expect PASS.
- [ ] **Step 5: Gates, commit** `refactor!: drop ingest_book and its policy exceptions; front-end tests patch intake`.

---

### Task 5: Domain docs and version

**Files:**
- Modify: `CONTEXT.md` (Intake, Intake Outcome, Note sections), `pyproject.toml`, `CLAUDE.md` ("Current version"), `uv.lock`

- [ ] **Step 1: CONTEXT.md.** In **Intake**, replace the pipeline paragraph with: "Intake is deliberately distinct from the **pipeline** (`store_book`) beneath it. Intake hashes the file, parses it once, and decides what to store and which Book it replaces; the pipeline chunks, stores and embeds exactly that, and reports what happened to the embedding instead of raising." In **Intake Outcome**, under `rejected`: "`reason` says why; `duplicate` is the same bytes, `duplicate_content` the same parsed content." In **Note**, add "nothing to embed" to the examples.
- [ ] **Step 2: Version.** `pyproject.toml` → `3.0.0`; `CLAUDE.md` "Current version: 3.0.0"; run `uv lock`.
- [ ] **Step 3: Full gates** (`ruff format --check src/ tests/`, `ruff check src/ tests/`, `mypy src/`, `pytest -m "not integration"`, coverage ≥ 80% via `pytest --cov=mnemo -m "not integration"`).
- [ ] **Step 4: Commit** `docs: intake owns the decision; bump to 3.0.0`.
