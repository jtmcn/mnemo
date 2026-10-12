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


def test_replaces_the_ids_it_is_told_to(db: Path):
    """The pipeline stores what it is told; deciding what to replace is the caller's job."""
    book, blocks = parse_book(SAMPLE)
    store_book(book, blocks, db_path=db)
    edited = book.model_copy(update={"title": "Edited"})

    stored = store_book(edited, blocks, replaces=frozenset({book.id}), db_path=db)

    assert stored.book.title == "Edited"
    assert _books(db) == [(book.id, "Edited")]


def test_chunker_failure_changes_nothing(db: Path):
    book, blocks = parse_book(SAMPLE)
    store_book(book, blocks, db_path=db)
    renamed = book.model_copy(update={"title": "New"})

    with (
        patch("mnemo.ingest.Chunker.chunk", side_effect=RuntimeError("chunker broke")),
        pytest.raises(RuntimeError, match="chunker broke"),
    ):
        store_book(renamed, blocks, replaces=frozenset({book.id}), db_path=db)

    assert _books(db) == [(book.id, book.title)]


def test_stale_vector_failure_after_commit_is_partial_success(db: Path):
    book, blocks = parse_book(SAMPLE)
    store_book(book, blocks, db_path=db)
    renamed = book.model_copy(update={"title": "New"})

    with patch("mnemo.vectors.VectorStore", side_effect=RuntimeError("chroma down")):
        stored = store_book(renamed, blocks, replaces=frozenset({book.id}), db_path=db)

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
    [
        (None, "embedded"),
        (NothingToEmbed("all boilerplate"), "nothing_to_embed"),
        (ValueError("no key"), "failed"),
    ],
)
def test_embedding_outcome_is_returned_not_raised(db: Path, side_effect, status):
    book, blocks = parse_book(SAMPLE)

    with patch("mnemo.ingest.embed_book", side_effect=side_effect, return_value=3):
        stored = store_book(book, blocks, embed=True, db_path=db)

    assert stored.embedding == status
    assert _books(db) == [(book.id, book.title)]
