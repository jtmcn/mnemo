"""Tests for the CLI module."""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from mnemo.cli import app

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Rich output with style escapes removed and wrapping collapsed.

    Rich splits styled runs mid-sentence and wraps at terminal width, so a
    substring assertion against raw stdout passes under NO_COLOR and fails in
    a real terminal.
    """
    return " ".join(_ANSI.sub("", text).split())


class TestHelp:
    """Tests for help output."""

    def test_main_help(self) -> None:
        """Main help shows all commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "add" in result.stdout
        assert "list" in result.stdout
        assert "remove" in result.stdout
        assert "search" in result.stdout
        assert "serve" in result.stdout
        assert "export" in result.stdout

    def test_add_help(self) -> None:
        """Add command help shows format info."""
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0
        assert ".epub" in result.stdout or ".docx" in result.stdout

    def test_list_help(self) -> None:
        """List command help shows description."""
        result = runner.invoke(app, ["list", "--help"])
        assert result.exit_code == 0
        assert "List" in result.stdout

    def test_remove_help(self) -> None:
        """Remove command help shows book ID info."""
        result = runner.invoke(app, ["remove", "--help"])
        assert result.exit_code == 0
        assert "book" in result.stdout.lower()

    def test_search_help(self) -> None:
        """Search command help shows query info."""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "query" in result.stdout.lower()

    def test_serve_help(self) -> None:
        """Serve command help shows MCP info."""
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "MCP" in result.stdout

    def test_export_help(self) -> None:
        """Export command help shows path info."""
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0
        assert "EPUB" in result.stdout


class TestList:
    """Tests for the list command."""

    def test_list_works(self) -> None:
        """List command runs successfully (may have books or not)."""
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_json_valid(self) -> None:
        """List with --json returns valid JSON array."""
        result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)


class TestAdd:
    """Tests for the add command."""

    def test_add_missing_file(self) -> None:
        """Add command fails with missing file."""
        result = runner.invoke(app, ["add", "nonexistent.epub"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_add_non_epub(self) -> None:
        """Add command fails with non-EPUB file."""
        result = runner.invoke(app, ["add", "somefile.txt"])
        assert result.exit_code == 1
        assert "not an epub" in result.stdout.lower() or "not found" in result.stdout.lower()


class TestAddCollection:
    """Tests for --collection flag on the add command."""

    @patch("mnemo.ingest.ingest_book")
    @patch("mnemo.storage.repository.BookRepository.get_by_hash", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_add_with_collection_flag_forwards_to_ingest(
        self,
        mock_init,
        mock_conn,
        mock_validate,
        mock_get_by_hash,
        mock_ingest,
        tmp_path,
    ) -> None:
        """`mnemo add file.docx --collection X` calls ingest_book with collection=X."""
        from mnemo.models import Book

        epub = tmp_path / "book.epub"
        epub.write_bytes(b"fake content")

        mock_book = Book(
            id="abc123",
            title="Test",
            authors=[],
            file_hash="a" * 64,
            structure_source="toc",
        )
        mock_ingest.return_value = (mock_book, 5)

        result = runner.invoke(
            app,
            ["add", str(epub), "--collection", "ERCOT Nodal Protocols", "--json"],
        )

        assert result.exit_code == 0
        mock_ingest.assert_called_once()
        assert mock_ingest.call_args.kwargs["collection"] == "ERCOT Nodal Protocols"

    @patch("mnemo.ingest.ingest_book")
    @patch("mnemo.storage.repository.BookRepository.get_by_hash", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_add_multi_path_with_collection_applies_to_all(
        self,
        mock_init,
        mock_conn,
        mock_validate,
        mock_get_by_hash,
        mock_ingest,
        tmp_path,
    ) -> None:
        """Same --collection value is forwarded for every path in a multi-path invocation."""
        from mnemo.models import Book

        epub1 = tmp_path / "a.epub"
        epub2 = tmp_path / "b.epub"
        epub1.write_bytes(b"content a")
        epub2.write_bytes(b"content b")

        mock_book = Book(
            id="abc123",
            title="Test",
            authors=[],
            file_hash="a" * 64,
            structure_source="toc",
        )
        mock_ingest.return_value = (mock_book, 5)

        result = runner.invoke(
            app,
            ["add", str(epub1), str(epub2), "--collection", "Group A", "--json"],
        )

        assert result.exit_code == 0
        assert mock_ingest.call_count == 2
        for call in mock_ingest.call_args_list:
            assert call.kwargs["collection"] == "Group A"

    @patch("mnemo.ingest.ingest_book")
    @patch("mnemo.storage.repository.BookRepository.get_by_hash", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_add_without_collection_passes_none(
        self,
        mock_init,
        mock_conn,
        mock_validate,
        mock_get_by_hash,
        mock_ingest,
        tmp_path,
    ) -> None:
        """Omitting --collection results in collection=None reaching ingest_book."""
        from mnemo.models import Book

        epub = tmp_path / "book.epub"
        epub.write_bytes(b"fake content")

        mock_book = Book(
            id="abc123",
            title="Test",
            authors=[],
            file_hash="a" * 64,
            structure_source="toc",
        )
        mock_ingest.return_value = (mock_book, 5)

        result = runner.invoke(app, ["add", str(epub), "--json"])

        assert result.exit_code == 0
        assert mock_ingest.call_args.kwargs.get("collection") is None


class TestRemove:
    """Tests for the remove command."""

    def test_remove_nonexistent(self) -> None:
        """Remove command warns but succeeds for nonexistent book."""
        result = runner.invoke(app, ["remove", "abc123"])
        assert result.exit_code == 0
        assert "not found" in result.stdout.lower()

    def test_remove_json_nonexistent(self) -> None:
        """Remove with --json returns valid JSON with removed=false."""
        result = runner.invoke(app, ["remove", "abc123", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["removed"] is False
        assert data["book_id"] == "abc123"


class TestExport:
    """Tests for the export command."""

    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    @patch("mnemo.storage.BookRepository")
    def test_export_writes_paths(self, mock_repo_cls, mock_init, mock_conn, tmp_path) -> None:
        """Export writes one EPUB path per line."""
        mock_book_1 = MagicMock()
        mock_book_1.file_path = "/books/one.epub"
        mock_book_2 = MagicMock()
        mock_book_2.file_path = "/books/two.epub"
        mock_repo_cls.return_value.list_all.return_value = [mock_book_1, mock_book_2]

        out = tmp_path / "export.txt"
        result = runner.invoke(app, ["export", str(out)])

        assert result.exit_code == 0
        assert "2 paths" in _plain(result.stdout)
        lines = out.read_text().strip().splitlines()
        assert lines == ["/books/one.epub", "/books/two.epub"]

    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    @patch("mnemo.storage.BookRepository")
    def test_export_skips_books_without_path(
        self, mock_repo_cls, mock_init, mock_conn, tmp_path
    ) -> None:
        """Export skips books that have no file_path."""
        mock_book = MagicMock()
        mock_book.file_path = "/books/one.epub"
        mock_no_path = MagicMock()
        mock_no_path.file_path = None
        mock_repo_cls.return_value.list_all.return_value = [mock_book, mock_no_path]

        out = tmp_path / "export.txt"
        result = runner.invoke(app, ["export", str(out)])

        assert result.exit_code == 0
        assert "1 paths" in _plain(result.stdout)
        lines = out.read_text().strip().splitlines()
        assert lines == ["/books/one.epub"]

    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    @patch("mnemo.storage.BookRepository")
    def test_export_empty_library(self, mock_repo_cls, mock_init, mock_conn, tmp_path) -> None:
        """Export with no books exits with error."""
        mock_repo_cls.return_value.list_all.return_value = []

        out = tmp_path / "export.txt"
        result = runner.invoke(app, ["export", str(out)])

        assert result.exit_code == 1
        assert "no books" in result.stdout.lower()

    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    @patch("mnemo.storage.BookRepository")
    def test_export_default_filename(
        self, mock_repo_cls, mock_init, mock_conn, tmp_path, monkeypatch
    ) -> None:
        """Export defaults to book-paths.txt."""
        # export writes to CWD; chdir so it lands in tmp, not the repo root
        monkeypatch.chdir(tmp_path)
        mock_book = MagicMock()
        mock_book.file_path = "/books/one.epub"
        mock_repo_cls.return_value.list_all.return_value = [mock_book]

        result = runner.invoke(app, ["export"])

        assert result.exit_code == 0
        assert "book-paths.txt" in result.stdout


class TestMigrateCosine:
    """Tests for the migrate-cosine command."""

    def test_migrate_cosine_help(self) -> None:
        """migrate-cosine command help exists."""
        result = runner.invoke(app, ["migrate-cosine", "--help"])
        assert result.exit_code == 0
        assert "cosine" in result.stdout.lower()

    @patch("mnemo.vectors.migrate.migrate_to_cosine")
    @patch("chromadb.PersistentClient")
    def test_migrate_cosine_delegates(self, mock_client_cls, mock_migrate) -> None:
        """migrate-cosine delegates to migrate_to_cosine function."""
        mock_migrate.return_value = {"migrated": 10, "verified": True}
        mock_client_cls.return_value = MagicMock()

        result = runner.invoke(app, ["migrate-cosine"])

        assert result.exit_code == 0
        mock_migrate.assert_called_once()
        assert "10" in result.stdout

    @patch("mnemo.vectors.migrate.migrate_to_cosine")
    @patch("chromadb.PersistentClient")
    def test_migrate_cosine_json_output(self, mock_client_cls, mock_migrate) -> None:
        """migrate-cosine --json outputs JSON result."""
        mock_migrate.return_value = {"migrated": 5, "verified": True}
        mock_client_cls.return_value = MagicMock()

        result = runner.invoke(app, ["migrate-cosine", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["migrated"] == 5

    @patch("mnemo.vectors.migrate.migrate_to_cosine")
    @patch("chromadb.PersistentClient")
    def test_migrate_cosine_already_cosine(self, mock_client_cls, mock_migrate) -> None:
        """migrate-cosine reports when already using cosine."""
        mock_migrate.return_value = {"migrated": 0, "already_cosine": True}
        mock_client_cls.return_value = MagicMock()

        result = runner.invoke(app, ["migrate-cosine"])

        assert result.exit_code == 0
        assert "already" in result.stdout.lower()

    def test_main_help_includes_migrate_cosine(self) -> None:
        """Main help shows migrate-cosine command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "migrate-cosine" in result.stdout


class TestReindex:
    """Tests for the reindex command."""

    def test_reindex_help(self) -> None:
        """Reindex command help shows description."""
        result = runner.invoke(app, ["reindex", "--help"])
        assert result.exit_code == 0
        assert "re-index" in result.stdout.lower() or "reindex" in result.stdout.lower()

    def test_main_help_includes_reindex(self) -> None:
        """Main help shows reindex command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "reindex" in result.stdout

    @patch("mnemo.ingest.reindex_all_books")
    @patch("mnemo.storage.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_no_books(self, mock_init, mock_conn, mock_list, mock_reindex) -> None:
        """Reindex with no books reports empty library."""
        mock_list.return_value = []
        result = runner.invoke(app, ["reindex"])
        assert result.exit_code == 0
        assert "no books" in result.stdout.lower()
        mock_reindex.assert_not_called()

    @patch("mnemo.ingest.reindex_all_books")
    @patch("mnemo.storage.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_no_books_json(self, mock_init, mock_conn, mock_list, mock_reindex) -> None:
        """Reindex --json with no books returns empty results."""
        mock_list.return_value = []
        result = runner.invoke(app, ["reindex", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["results"] == []
        assert data["success"] == 0

    @patch("mnemo.ingest.reindex_all_books")
    @patch("mnemo.storage.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_success(self, mock_init, mock_conn, mock_list, mock_reindex) -> None:
        """Reindex reports success count."""
        mock_book = MagicMock()
        mock_list.return_value = [mock_book]
        mock_reindex.return_value = [
            {
                "book_id": "abc123",
                "title": "Test Book",
                "status": "success",
                "chunks": 50,
                "error": None,
            },
        ]
        result = runner.invoke(app, ["reindex"])
        assert result.exit_code == 0
        assert "1 succeeded" in _plain(result.stdout)

    @patch("mnemo.ingest.reindex_all_books")
    @patch("mnemo.storage.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_json_output(self, mock_init, mock_conn, mock_list, mock_reindex) -> None:
        """Reindex --json returns structured results."""
        mock_book = MagicMock()
        mock_list.return_value = [mock_book]
        mock_reindex.return_value = [
            {
                "book_id": "abc123",
                "title": "Test",
                "status": "success",
                "chunks": 50,
                "error": None,
            },
            {
                "book_id": "def456",
                "title": "Missing",
                "status": "skipped",
                "chunks": 0,
                "error": "EPUB file not found",
            },
        ]
        result = runner.invoke(app, ["reindex", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["success"] == 1
        assert data["skipped"] == 1
        assert data["failed"] == 0
        assert len(data["results"]) == 2

    @patch("mnemo.ingest.reindex_all_books")
    @patch("mnemo.storage.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_verbose(self, mock_init, mock_conn, mock_list, mock_reindex) -> None:
        """Reindex --verbose shows per-book details."""
        mock_book = MagicMock()
        mock_list.return_value = [mock_book]
        mock_reindex.return_value = [
            {
                "book_id": "abc123",
                "title": "Good Book",
                "status": "success",
                "chunks": 50,
                "error": None,
            },
            {
                "book_id": "def456",
                "title": "Gone Book",
                "status": "skipped",
                "chunks": 0,
                "error": "EPUB file not found",
            },
        ]
        result = runner.invoke(app, ["reindex", "--verbose"])
        assert result.exit_code == 0
        assert "Good Book" in result.stdout
        assert "Gone Book" in result.stdout

    @patch("mnemo.ingest.reindex_all_books")
    @patch("mnemo.storage.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_failure_exits_nonzero(
        self, mock_init, mock_conn, mock_list, mock_reindex
    ) -> None:
        """Reindex exits with code 1 when any book fails."""
        mock_book = MagicMock()
        mock_list.return_value = [mock_book]
        mock_reindex.return_value = [
            {
                "book_id": "abc123",
                "title": "Bad Book",
                "status": "failed",
                "chunks": 0,
                "error": "parse error",
            },
        ]
        result = runner.invoke(app, ["reindex"])
        assert result.exit_code == 1


class TestSearch:
    """Tests for the search command."""

    def test_search_runs(self) -> None:
        """Search command runs successfully (may return no results)."""
        result = runner.invoke(app, ["search", "test query"])
        assert result.exit_code == 0

    def test_search_json_valid(self) -> None:
        """Search with --json returns valid JSON array."""
        result = runner.invoke(app, ["search", "test query", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_search_with_limit(self) -> None:
        """Search with --limit option works."""
        result = runner.invoke(app, ["search", "test", "--limit", "3"])
        assert result.exit_code == 0

    def test_search_with_book_filter(self) -> None:
        """Search with --book filter option works."""
        result = runner.invoke(app, ["search", "test", "--book", "abc123"])
        assert result.exit_code == 0


class TestBackupCLI:
    """Tests for the backup CLI command."""

    def test_backup_help(self) -> None:
        """backup --help shows help text."""
        result = runner.invoke(app, ["backup", "--help"])
        assert result.exit_code == 0
        assert "backup" in result.stdout.lower()


class TestRestoreCLI:
    """Tests for the restore CLI command."""

    def test_restore_help(self) -> None:
        """restore --help shows help text."""
        result = runner.invoke(app, ["restore", "--help"])
        assert result.exit_code == 0
        assert "restore" in result.stdout.lower()


class TestBookServiceSurface:
    """book_service keeps only the function that does real work."""

    def test_only_validate_book_path_is_exported(self):
        from mnemo.services import book_service

        public = [n for n in dir(book_service) if not n.startswith("_")]
        assert "validate_book_path" in public
        assert "find_duplicate" not in public
        assert "list_all_books" not in public

    def test_validate_book_path_rejects_missing_file(self, tmp_path):
        from mnemo.services.book_service import validate_book_path

        result = validate_book_path(tmp_path / "nope.epub")
        assert result is not None
        assert "File not found" in result

    def test_validate_book_path_rejects_bad_extension(self, tmp_path):
        from mnemo.services.book_service import validate_book_path

        bad = tmp_path / "book.pdf"
        bad.write_text("x")
        result = validate_book_path(bad)
        assert result is not None
        assert "Unsupported format" in result

    def test_validate_book_path_accepts_epub(self, tmp_path):
        from mnemo.services.book_service import validate_book_path

        good = tmp_path / "book.epub"
        good.write_text("x")
        assert validate_book_path(good) is None


class TestAddPartialEmbedding:
    """`mnemo add` reports a stored-but-unembedded book as partial success.

    Regression test for #6: ingest_book commits the book before embedding, so
    an embedding failure used to print an error and exit 1 while leaving a
    durable book behind — and the retry then reported it as a duplicate.
    """

    @patch("mnemo.ingest.ingest_book")
    @patch("mnemo.storage.repository.BookRepository.get_by_hash", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_add_exits_zero_and_warns_when_embedding_fails(
        self, mock_init, mock_conn, mock_validate, mock_get_by_hash, mock_ingest, tmp_path
    ) -> None:
        from mnemo.ingest import EmbeddingFailed
        from mnemo.models import Book

        epub = tmp_path / "book.epub"
        epub.write_bytes(b"fake content")

        book = Book(
            id="abc123",
            title="Test",
            authors=["A"],
            file_hash="a" * 64,
            structure_source="toc",
        )
        mock_ingest.side_effect = EmbeddingFailed(
            book, 8, ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN must be set")
        )

        result = runner.invoke(app, ["add", str(epub)])

        assert result.exit_code == 0
        # Rich wraps at terminal width and injects style escapes, so compare
        # against the flattened text (see _plain).
        out = _plain(result.stdout)
        assert "Added" in out
        assert "Embeddings skipped" in out
        # The advice must point at the single-book path, not the whole-library
        # rebuild: mnemo reindex deletes every book's vectors before re-embedding.
        assert "mnemo add --force" in out
        assert "mnemo reindex" not in out

    @patch("mnemo.ingest.ingest_book")
    @patch("mnemo.storage.repository.BookRepository.get_by_hash", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_add_json_marks_book_unembedded(
        self, mock_init, mock_conn, mock_validate, mock_get_by_hash, mock_ingest, tmp_path
    ) -> None:
        from mnemo.ingest import EmbeddingFailed
        from mnemo.models import Book

        epub = tmp_path / "book.epub"
        epub.write_bytes(b"fake content")

        book = Book(
            id="abc123", title="Test", authors=[], file_hash="a" * 64, structure_source="toc"
        )
        mock_ingest.side_effect = EmbeddingFailed(book, 8, ValueError("no credentials"))

        result = runner.invoke(app, ["add", str(epub), "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload[0]["embedded"] is False
        assert payload[0]["chunks"] == 8
        assert "no credentials" in payload[0]["embed_error"]

    @patch("mnemo.ingest.ingest_book")
    @patch("mnemo.storage.repository.BookRepository.get_by_hash", return_value=None)
    @patch("mnemo.services.book_service.validate_book_path", return_value=None)
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_add_json_marks_book_embedded_on_success(
        self, mock_init, mock_conn, mock_validate, mock_get_by_hash, mock_ingest, tmp_path
    ) -> None:
        from mnemo.models import Book

        epub = tmp_path / "book.epub"
        epub.write_bytes(b"fake content")

        book = Book(
            id="abc123", title="Test", authors=[], file_hash="a" * 64, structure_source="toc"
        )
        mock_ingest.return_value = (book, 8)

        result = runner.invoke(app, ["add", str(epub), "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout)[0]["embedded"] is True


class TestListCheckEmbeddings:
    """`mnemo list --check-embeddings` reports each book's vector count."""

    @staticmethod
    def _books():
        from mnemo.models import Book

        return [
            Book(id="abc123", title="Has", authors=[], file_hash="a" * 64, structure_source="toc"),
            Book(
                id="def456", title="Lacks", authors=[], file_hash="b" * 64, structure_source="toc"
            ),
        ]

    @patch("mnemo.cli._vector_counts")
    @patch("mnemo.storage.repository.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_list_flags_books_without_embeddings(
        self, mock_init, mock_conn, mock_list_all, mock_counts
    ) -> None:
        mock_list_all.return_value = self._books()
        mock_counts.return_value = {"abc123": 12, "def456": 0}

        result = runner.invoke(app, ["list", "--check-embeddings", "--json"])

        assert result.exit_code == 0
        payload = {b["id"]: (b["vectors"], b["embedded"]) for b in json.loads(result.stdout)}
        assert payload == {"abc123": (12, True), "def456": (0, False)}

    @patch("mnemo.cli._vector_counts")
    @patch("mnemo.storage.repository.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_list_reports_the_count_not_a_yes(
        self, mock_init, mock_conn, mock_list_all, mock_counts
    ) -> None:
        """A partly-embedded book must not be reported as simply embedded.

        embed_book writes in batches, so a run that dies partway leaves some
        vectors behind; a bare "yes" would hide exactly the book the flag
        exists to surface.
        """
        mock_list_all.return_value = self._books()
        mock_counts.return_value = {"abc123": 3, "def456": 0}

        result = runner.invoke(app, ["list", "--check-embeddings"])

        assert result.exit_code == 0
        assert "3" in result.stdout
        assert "none" in result.stdout
        # Rich injects style escapes between the count and the words and wraps
        # at terminal width, so assert on the wording only.
        assert "have no embeddings" in _plain(result.stdout)

    @patch("mnemo.cli._vector_counts")
    @patch("mnemo.storage.repository.BookRepository.list_all", return_value=[])
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_list_without_flag_never_touches_chromadb(
        self, mock_init, mock_conn, mock_list_all, mock_counts
    ) -> None:
        result = runner.invoke(app, ["list", "--json"])

        assert result.exit_code == 0
        mock_counts.assert_not_called()


class TestReindexCredentialPreflight:
    """`mnemo reindex` refuses to run without credentials rather than wiping vectors.

    ingest_book deletes a book's existing vectors before re-embedding, so
    reindexing with no credentials would strip the library one book at a time.
    """

    @patch("mnemo.storage.repository.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_aborts_without_credentials(
        self, mock_init, mock_conn, mock_list_all, monkeypatch
    ) -> None:
        from mnemo.models import Book

        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        mock_list_all.return_value = [
            Book(id="abc123", title="A", authors=[], file_hash="a" * 64, structure_source="toc")
        ]

        with patch("mnemo.ingest.ingest_book") as mock_ingest:
            result = runner.invoke(app, ["reindex"])

        assert result.exit_code == 1
        assert "DATABRICKS_HOST" in result.stdout
        assert "No books were changed" in _plain(result.stdout)
        # Nothing was re-ingested, so no vectors were deleted.
        mock_ingest.assert_not_called()


class TestReindexPartial:
    """A book re-indexed but not re-embedded is reported as partial, not failed."""

    @patch("mnemo.storage.repository.BookRepository.list_all")
    @patch("mnemo.storage.get_connection")
    @patch("mnemo.storage.init_db")
    def test_reindex_reports_partial_books(self, mock_init, mock_conn, mock_list_all) -> None:
        from mnemo.models import Book

        mock_list_all.return_value = [
            Book(id="abc123", title="A", authors=[], file_hash="a" * 64, structure_source="toc")
        ]
        results = [
            {
                "book_id": "abc123",
                "title": "A",
                "status": "partial",
                "chunks": 8,
                "error": "no credentials",
            }
        ]

        with patch("mnemo.ingest.reindex_all_books", return_value=results):
            result = runner.invoke(app, ["reindex", "--verbose"])

        assert result.exit_code == 1, "a run that embedded nothing must not exit 0"
        assert "PARTIAL" in result.stdout
        assert "without embeddings" in _plain(result.stdout)
