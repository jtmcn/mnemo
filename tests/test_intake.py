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
from tests.fixtures.pdf_factory import Para, create_blank_pdf, create_test_pdf


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

    def test_pdf_without_text_is_rejected(self, tmp_path: Path, temp_db: Path):
        outcome = intake(create_blank_pdf(tmp_path / "scan.pdf"), db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "parse_failed"
        assert "no extractable text" in outcome.message

    def test_pipeline_failure_is_reported_not_raised(self, sample_epub: Path, temp_db: Path):
        with patch("mnemo.services.book_service.store_book", side_effect=RuntimeError("disk gone")):
            outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "pipeline_error"


class TestFreshIntake:
    """A book the library has not seen before."""

    def test_added(self, sample_epub: Path, temp_db: Path):
        outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "added"
        assert outcome.reason is None
        assert outcome.book is not None
        assert outcome.book.title == "Python Testing Guide"
        assert outcome.chunks > 0

    def test_added_pdf(self, tmp_path: Path, temp_db: Path):
        outcome = intake(create_test_pdf(tmp_path / "book.pdf"), db_path=temp_db, embed=False)

        assert outcome.status == "added"
        assert outcome.book is not None
        assert outcome.book.title == "Test PDF Book"
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

    def test_skip_does_not_parse(self, indexed, sample_epub: Path, temp_db: Path):
        """A byte duplicate is skipped on its hash alone, so bulk --skip-existing stays fast."""
        with patch("mnemo.services.book_service.parse_book") as parse:
            outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="skip")

        assert outcome.status == "already_indexed"
        parse.assert_not_called()


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

    def test_similar_title_uses_the_parsed_pdf_title(self, tmp_path: Path, temp_db: Path):
        """A PDF's title comes from its metadata, not its file name."""
        first = create_test_pdf(
            tmp_path / "a.pdf",
            items=[Para(["First book body. " * 20])],
            title="Domain Driven Design",
        )
        second = create_test_pdf(
            tmp_path / "scan-0042.pdf",
            items=[Para(["Different body text. " * 20])],
            title="Domain-Driven Design",
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

    def test_nothing_to_embed_is_its_own_note(self, sample_epub: Path, temp_db: Path):
        """All-boilerplate books can never be embedded, so no retry advice fires."""
        from mnemo.ingest import NothingToEmbed

        with patch("mnemo.ingest.embed_book", side_effect=NothingToEmbed("all boilerplate")):
            outcome = intake(sample_epub, db_path=temp_db, embed=True)

        assert outcome.status == "added"
        assert outcome.embedded is False
        assert "nothing_to_embed" in kinds(outcome)
        assert "embeddings_skipped" not in kinds(outcome)


class TestFailedReplaceKeepsTheBook:
    """A replace that fails before its commit leaves the existing book, edits and all."""

    def test_failed_replace_keeps_the_existing_book(self, sample_epub: Path, temp_db: Path):
        """A re-parse that fails must not delete the healthy book it was replacing."""
        first = intake(sample_epub, db_path=temp_db, embed=False)
        assert first.status == "added"

        with patch(
            "mnemo.services.book_service.parse_book", side_effect=RuntimeError("corrupt spine")
        ):
            outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "rejected"
        assert outcome.reason == "parse_failed"

        init_db(temp_db)
        conn = get_connection(temp_db)
        try:
            assert [b.id for b in BookRepository(conn).list_all()] == [first.book.id]
        finally:
            conn.close()

    def test_failed_replace_keeps_the_edited_title(self, sample_epub: Path, temp_db: Path):
        first = intake(sample_epub, db_path=temp_db, embed=False)
        assert first.book is not None
        conn = get_connection(temp_db)
        BookRepository(conn).update(first.book.id, title="Hand-Fixed Title")
        conn.commit()
        conn.close()

        with patch("mnemo.ingest.Chunker.chunk", side_effect=RuntimeError("chunker broke")):
            outcome = intake(sample_epub, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.reason == "pipeline_error"
        conn = get_connection(temp_db)
        try:
            books = BookRepository(conn).list_all()
        finally:
            conn.close()
        assert [(b.id, b.title) for b in books] == [(first.book.id, "Hand-Fixed Title")]

    def test_committed_content_replace_is_not_discarded(self, tmp_path: Path, temp_db: Path):
        """A vector cleanup failure after the commit is partial success, not a rollback."""
        original = create_test_pdf(tmp_path / "a.pdf", title="The Ontology Pipeline")
        edited = create_test_pdf(tmp_path / "b.pdf", title="Ontology-Pipeline")
        first = intake(original, db_path=temp_db, embed=False)
        assert first.book is not None

        with patch("mnemo.vectors.VectorStore", side_effect=RuntimeError("chroma down")):
            outcome = intake(edited, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "replaced"
        assert outcome.embedded is False
        assert "embeddings_skipped" in kinds(outcome)
        conn = get_connection(temp_db)
        try:
            books = BookRepository(conn).list_all()
        finally:
            conn.close()
        assert [(b.id, b.title) for b in books] == [(first.book.id, "The Ontology Pipeline")]


class TestFailureClassification:
    """A broken book is a parse failure, not a duplicate."""

    def test_validation_error_is_not_a_duplicate(self, sample_epub: Path, temp_db: Path):
        """pydantic.ValidationError subclasses ValueError, as does the duplicate guard."""
        import pydantic

        broken = pydantic.ValidationError.from_exception_data("Book", [])
        with patch("mnemo.services.book_service.parse_book", side_effect=broken):
            outcome = intake(sample_epub, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "parse_failed"


class TestContentDuplicates:
    """Same content under edited metadata is handled like a hash duplicate."""

    @pytest.fixture
    def indexed(self, tmp_path: Path, temp_db: Path):
        original = create_test_pdf(tmp_path / "orig.pdf", title="The Ontology Pipeline")
        edited = create_test_pdf(tmp_path / "Ontology-Pipeline.pdf", title="Ontology-Pipeline")
        first = intake(original, db_path=temp_db, embed=False)
        assert first.status == "added"
        return first, edited

    def test_reject(self, indexed, temp_db: Path):
        first, edited = indexed
        outcome = intake(edited, db_path=temp_db, embed=False)

        assert outcome.status == "rejected"
        assert outcome.reason == "duplicate_content"
        assert outcome.book is not None and outcome.book.id == first.book.id
        assert "same content" in outcome.message

    def test_skip(self, indexed, temp_db: Path):
        first, edited = indexed
        outcome = intake(edited, db_path=temp_db, embed=False, on_duplicate="skip")

        assert outcome.status == "already_indexed"
        assert outcome.book is not None and outcome.book.id == first.book.id

    def test_replace_reports_replaced_and_keeps_title(self, indexed, temp_db: Path):
        first, edited = indexed
        outcome = intake(edited, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "replaced"
        assert outcome.book is not None
        assert outcome.book.id == first.book.id
        assert outcome.book.title == "The Ontology Pipeline"
        assert "suspect_metadata" not in kinds(outcome)

    def test_force_metadata_passes_through(self, indexed, temp_db: Path):
        first, edited = indexed
        outcome = intake(
            edited, db_path=temp_db, embed=False, on_duplicate="replace", force_metadata=True
        )

        assert outcome.book is not None and outcome.book.title == "Ontology-Pipeline"
        assert "suspect_metadata" in kinds(outcome)

    def test_replace_does_not_point_a_similar_note_at_itself(self, tmp_path: Path, temp_db: Path):
        # Similar-title matching reads the parsed title, so it sees the new one.
        chapters = [{"title": "One", "content": "<p>" + "Ontologies, step by step. " * 10 + "</p>"}]
        original = create_test_epub(
            title="The Ontology Pipeline", chapters=chapters, output_path=tmp_path / "a.epub"
        )
        edited = create_test_epub(
            title="Ontology-Pipeline", chapters=chapters, output_path=tmp_path / "b.epub"
        )
        first = intake(original, db_path=temp_db, embed=False)

        outcome = intake(edited, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.status == "replaced"
        assert outcome.book is not None and outcome.book.id == first.book.id
        assert "similar_title" not in kinds(outcome)

    def test_kept_slug_title_is_still_flagged(self, tmp_path: Path, temp_db: Path):
        slug = create_test_pdf(tmp_path / "slug.pdf", title="ontology_pipeline")
        proper = create_test_pdf(tmp_path / "proper.pdf", title="The Ontology Pipeline")
        intake(slug, db_path=temp_db, embed=False)

        outcome = intake(proper, db_path=temp_db, embed=False, on_duplicate="replace")

        assert outcome.book is not None and outcome.book.title == "ontology_pipeline"
        assert "suspect_metadata" in kinds(outcome)


class TestSuspectMetadata:
    @pytest.mark.parametrize(
        ("title", "filename"),
        [
            ("Ontology-Pipeline", "Ontology-Pipeline.pdf"),
            ("Ontology-Pipeline", "ontology_pipeline.pdf"),
            ("designing_data_apps", "x.pdf"),
            ("my-book-v2", "x.pdf"),
        ],
    )
    def test_slug_title_is_flagged(self, title: str, filename: str, tmp_path: Path, temp_db: Path):
        outcome = intake(
            create_test_pdf(tmp_path / filename, title=title), db_path=temp_db, embed=False
        )

        assert "suspect_metadata" in kinds(outcome)

    @pytest.mark.parametrize(
        "title",
        [
            "The Ontology Pipeline",
            "Designing Data-Intensive Applications",
            "Python",
            "Catch-22",
            "Self-Reliance",
            "Spider-Man",
            "X-Men",
            "Ontology-Pipeline",
        ],
    )
    def test_real_title_is_quiet(self, title: str, tmp_path: Path, temp_db: Path):
        outcome = intake(
            create_test_pdf(tmp_path / "x.pdf", title=title), db_path=temp_db, embed=False
        )

        assert "suspect_metadata" not in kinds(outcome)

    @pytest.mark.parametrize("title", ["Dune", "Neuromancer"])
    def test_one_word_title_named_after_its_file_is_quiet(
        self, title: str, tmp_path: Path, temp_db: Path
    ):
        outcome = intake(
            create_test_pdf(tmp_path / f"{title}.pdf", title=title), db_path=temp_db, embed=False
        )

        assert "suspect_metadata" not in kinds(outcome)


class TestEmptyContent:
    def test_textless_books_are_not_duplicates(self, tmp_path: Path, temp_db: Path):
        def plates(title: str) -> Path:
            return create_test_epub(
                title=title,
                chapters=[{"title": title, "content": '<img src="plate.png"/>'}],
                output_path=tmp_path / f"{title}.epub",
            )

        first = intake(plates("Alpha"), db_path=temp_db, embed=False)
        second = intake(plates("Beta"), db_path=temp_db, embed=False)

        assert first.status == "added"
        assert second.status == "added"
        assert first.book is not None and second.book is not None
        assert first.book.id != second.book.id

    def test_watermark_only_scans_are_not_duplicates(self, tmp_path: Path, temp_db: Path):
        first, second = (
            create_test_pdf(
                tmp_path / f"{name}.pdf", title=name, items=[Para(["Scanned with CamScanner"])]
            )
            for name in ("Receipts 2024", "Tax Letter")
        )

        outcomes = [intake(p, db_path=temp_db, embed=False) for p in (first, second)]

        assert [o.status for o in outcomes] == ["added", "added"]
        assert outcomes[0].book is not None and outcomes[1].book is not None
        assert outcomes[0].book.id != outcomes[1].book.id
