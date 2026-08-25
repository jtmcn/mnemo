"""Outcome matrix for the book intake module.

intake() is the single seam both front ends go through, so its status x reason
x notes matrix is tested here directly rather than through Rich prose in
test_cli.py or markdown strings in test_mcp.py.
"""

from __future__ import annotations

import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from mnemo.services.book_service import IntakeOutcome, intake
from mnemo.storage import BookRepository, get_connection, init_db
from tests.fixtures.epub_factory import create_test_epub


@pytest.fixture
def temp_db():
    """Provide a temporary database path."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "test.db"


@pytest.fixture
def sample_epub() -> Path:
    """Path to the sample EPUB fixture."""
    return Path("tests/fixtures/sample.epub")


def kinds(outcome: IntakeOutcome) -> set[str]:
    """Note kinds present on an outcome, as a set."""
    return {note.kind for note in outcome.notes}


class TestRejections:
    """Predictable failures come back as values, not exceptions."""

    def test_missing_file(self, temp_db: Path):
        outcome = intake(Path("/nope/missing.epub"), db_path=temp_db)

        assert outcome.status == "rejected"
        assert outcome.reason == "not_found"
        assert outcome.book is None
        assert outcome.chunks == 0

    def test_unsupported_format(self, tmp_path: Path, temp_db: Path):
        junk = tmp_path / "notes.txt"
        junk.write_text("plain text")

        outcome = intake(junk, db_path=temp_db)

        assert outcome.status == "rejected"
        assert outcome.reason == "unsupported_format"
        assert outcome.book is None

    def test_unreadable_book(self, tmp_path: Path, temp_db: Path):
        corrupt = tmp_path / "corrupt.epub"
        corrupt.write_bytes(b"not actually an epub")

        outcome = intake(corrupt, db_path=temp_db)

        assert outcome.status == "rejected"
        assert outcome.reason == "parse_failed"
        assert outcome.book is None

    def test_pipeline_failure_is_reported_not_raised(self, sample_epub: Path, temp_db: Path):
        with patch("mnemo.ingest.ingest_book", side_effect=RuntimeError("disk gone")):
            outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "pipeline_error"

    def test_pipeline_failure_cleans_up_a_stored_book(self, sample_epub: Path, temp_db: Path):
        """A book committed before the failure must not survive as a partial record."""
        from mnemo.ingest import ingest_book as real_ingest

        def store_then_fail(*args, **kwargs):
            real_ingest(*args, **kwargs)
            raise RuntimeError("failed after commit")

        with patch("mnemo.ingest.ingest_book", side_effect=store_then_fail):
            outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "pipeline_error"

        init_db(temp_db)
        conn = get_connection(temp_db)
        try:
            assert BookRepository(conn).list_all() == []
        finally:
            conn.close()


class TestFreshIntake:
    """A book the library has not seen before."""

    def test_added(self, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "added"
        assert outcome.reason is None
        assert outcome.book is not None
        assert outcome.book.title == "Python Testing Guide"
        assert outcome.chunks > 0

    def test_collection_is_applied(self, sample_epub: Path, temp_db: Path):
        outcome = intake(
            sample_epub, db_path=temp_db, embed=False, collection="ERCOT Nodal Protocols"
        )

        assert outcome.book is not None
        assert outcome.book.collection == "ERCOT Nodal Protocols"

    def test_outcome_is_frozen(self, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        with pytest.raises(FrozenInstanceError):
            outcome.status = "rejected"  # type: ignore[misc]


class TestDuplicatePolicy:
    """on_duplicate maps one-to-one onto outcomes."""

    @pytest.fixture
    def indexed(self, sample_epub: Path, temp_db: Path):
        first = intake(sample_epub, db_path=temp_db, embed=False)
        assert first.status == "added"
        return first

    def test_reject_is_the_default(self, indexed, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "duplicate"

    def test_reject_carries_the_existing_book(self, indexed, sample_epub: Path, temp_db: Path):
        """The front ends quote the existing id and title back at the user."""
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.book is not None
        assert outcome.book.id == indexed.book.id

    def test_skip(self, indexed, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="skip")

        assert outcome.status == "already_indexed"
        assert outcome.reason is None
        assert outcome.book is not None
        assert outcome.book.id == indexed.book.id
        assert outcome.chunks == 0

    def test_replace(self, indexed, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "replaced"
        assert outcome.reason is None
        assert outcome.chunks > 0

    def test_replace_leaves_one_book(self, indexed, sample_epub: Path, temp_db: Path):
        intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        init_db(temp_db)
        conn = get_connection(temp_db)
        try:
            assert len(BookRepository(conn).list_all()) == 1
        finally:
            conn.close()

    def test_skip_does_not_run_the_pipeline(self, indexed, sample_epub: Path, temp_db: Path):
        """Skipping a duplicate must not re-chunk or re-store anything."""
        with patch("mnemo.ingest.ingest_book") as pipeline:
            intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="skip")

        pipeline.assert_not_called()


class TestNotes:
    """Advisory findings ride alongside the status rather than changing it."""

    def test_suspect_isbn(self, tmp_path: Path, temp_db: Path):
        book = create_test_epub(
            title="Bad Checksum Book",
            isbn="9781234567890",  # fails the ISBN-13 checksum
            output_path=tmp_path / "bad-isbn.epub",
        )

        outcome = intake(book, db_path=temp_db, embed=False)

        assert outcome.status == "added"
        assert "suspect_isbn" in kinds(outcome)

    def test_valid_isbn_is_quiet(self, tmp_path: Path, temp_db: Path):
        book = create_test_epub(
            title="Good Checksum Book",
            isbn="9780134685991",
            output_path=tmp_path / "good-isbn.epub",
        )

        outcome = intake(book, db_path=temp_db, embed=False)

        assert "suspect_isbn" not in kinds(outcome)

    def test_similar_title(self, tmp_path: Path, temp_db: Path):
        first = create_test_epub(
            title="Effective Python Testing",
            chapters=[{"title": "One", "content": "<p>First edition body text.</p>"}],
            output_path=tmp_path / "first.epub",
        )
        second = create_test_epub(
            title="Effective Python Testing!",
            chapters=[{"title": "One", "content": "<p>Second edition body text.</p>"}],
            output_path=tmp_path / "second.epub",
        )
        intake(first, db_path=temp_db, embed=False)

        outcome = intake(second, db_path=temp_db, embed=False)

        assert outcome.status == "added"
        assert "similar_title" in kinds(outcome)

    def test_no_similar_title_on_a_hash_duplicate(self, sample_epub: Path, temp_db: Path):
        """A hard duplicate is already reported as one; a soft warning would be noise."""
        intake(sample_epub, db_path=temp_db, embed=False)

        outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert "similar_title" not in kinds(outcome)

    def test_unique_title_is_quiet(self, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert "similar_title" not in kinds(outcome)


class TestEmbedding:
    """embedded is orthogonal to status: a replace can also lose its vectors."""

    def test_not_embedded_when_embedding_is_off(self, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.embedded is False
        assert "embeddings_skipped" not in kinds(outcome)

    def test_unconfigured_endpoint_is_partial_success(self, sample_epub: Path, temp_db: Path):
        """No credentials (conftest clears them): the book is stored, vectors are not."""
        outcome = intake(sample_epub, db_path=temp_db, embed=True)

        assert outcome.status == "added"
        assert outcome.embedded is False
        assert "embeddings_skipped" in kinds(outcome)
        assert outcome.chunks > 0

    def test_embedded_on_success(self, sample_epub: Path, temp_db: Path):
        with patch("mnemo.ingest.embed_book", return_value=7):
            outcome = intake(sample_epub, db_path=temp_db, embed=True)

        assert outcome.status == "added"
        assert outcome.embedded is True
        assert "embeddings_skipped" not in kinds(outcome)

    def test_replace_can_lose_its_vectors(self, sample_epub: Path, temp_db: Path):
        intake(sample_epub, db_path=temp_db, embed=False)

        outcome = intake(sample_epub, db_path=temp_db, embed=True, on_duplicate="replace")

        assert outcome.status == "replaced"
        assert outcome.embedded is False
        assert "embeddings_skipped" in kinds(outcome)

    def test_nothing_to_embed_advises_no_retry(self, sample_epub: Path, temp_db: Path):
        """All-boilerplate books can never be embedded, so the retry note must not fire.

        embedded stays True here, matching what `mnemo add --json` has always
        reported: ingest_book swallows NothingToEmbed and returns normally, so
        intake cannot tell it apart from a successful embed without changing
        ingest_book's signature. See the ponytail note in book_service.
        """
        from mnemo.ingest import NothingToEmbed

        with patch("mnemo.ingest.embed_book", side_effect=NothingToEmbed("all boilerplate")):
            outcome = intake(sample_epub, db_path=temp_db, embed=True)

        assert outcome.status == "added"
        assert "embeddings_skipped" not in kinds(outcome)


class TestCleanupIsNotDestructive:
    """Cleanup must only ever remove a book this run could have created."""

    def test_failed_replace_keeps_the_existing_book(self, sample_epub: Path, temp_db: Path):
        """A re-parse that fails must not delete the healthy book it was replacing.

        pre_parse_metadata only reads the OPF while parse_book walks the whole
        spine, so a since-corrupted file passes the first and fails the second.
        ingest_book deletes the old record at step 5, after the parse at step
        3 — so on the failure path the hash still resolves to the good book.
        """
        first = intake(sample_epub, db_path=temp_db, embed=False)
        assert first.status == "added"

        with patch("mnemo.ingest.parse_book", side_effect=RuntimeError("corrupt spine")):
            outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "rejected"
        assert outcome.reason == "pipeline_error"

        init_db(temp_db)
        conn = get_connection(temp_db)
        try:
            assert [b.id for b in BookRepository(conn).list_all()] == [first.book.id]
        finally:
            conn.close()


class TestFailureClassification:
    """A broken book is a pipeline error, not a duplicate."""

    def test_validation_error_is_not_a_duplicate(self, sample_epub: Path, temp_db: Path):
        """pydantic.ValidationError subclasses ValueError, as does the duplicate guard."""
        import pydantic

        broken = pydantic.ValidationError.from_exception_data("Book", [])
        with patch("mnemo.ingest.parse_book", side_effect=broken):
            outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "pipeline_error"

    def test_duplicate_raised_by_the_pipeline_carries_its_book(
        self, sample_epub: Path, temp_db: Path
    ):
        """A book indexed between the lookup and the pipeline is still a duplicate.

        The front ends quote the existing id, so the outcome has to carry it
        however the duplicate was detected.
        """
        from mnemo.ingest import DuplicateBook
        from mnemo.models import Book

        other = Book(
            id="abcdef",
            title="Raced In",
            authors=["A"],
            file_hash="f" * 64,
            structure_source="toc",
        )
        with patch(
            "mnemo.ingest.ingest_book",
            side_effect=DuplicateBook(other, "Book already indexed (id: abcdef)."),
        ):
            outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "duplicate"
        assert outcome.book is not None
        assert outcome.book.id == "abcdef"
        # Advice is the front end's to add, so the message must not pre-empt it.
        assert "force" not in outcome.message.lower()
