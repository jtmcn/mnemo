"""Tests for the CLI module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from mnemo.cli import app

runner = CliRunner()


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

    def test_add_help(self) -> None:
        """Add command help shows EPUB info."""
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0
        assert "EPUB" in result.stdout

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
        assert "1 succeeded" in result.stdout

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
