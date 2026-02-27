# PRD: Mnemo Ebook Library Management

**Author:** Joel  
**Date:** February 2026  
**Status:** Draft  
**Branch:** `manage-books-mcp`

---

## 1. Summary

Extend mnemo's MCP server with book management tools so Claude can add, remove, and edit ebook metadata directly from the chat interface. Today, book lifecycle operations require the CLI (`mnemo add`, `mnemo remove`). This PRD adds MCP tools that let Claude orchestrate ingestion and metadata cleanup without the user leaving the conversation.

**Scope:** EPUB only (PDF deferred). Metadata changes apply to mnemo's SQLite/ChromaDB records only — source `.epub` files are never modified.

---

## 2. Problem

Managing the mnemo library currently requires context-switching to a terminal. A typical workflow — "add this book, fix the author name, check it indexed correctly" — spans three CLI invocations. Claude already has Filesystem access to the user's ebook directory, so it can locate files; it just can't tell mnemo to ingest or update them.

---

## 3. Goals & Non-Goals

### Goals

- Add MCP tools for book ingestion, removal, and metadata editing
- Read epub files via the existing Filesystem MCP extension (configurable path)
- Store book metadata in the existing SQLite database (no new stores)
- Keep source `.epub` files unmodified at all times
- Support title, author, and ISBN correction in application data
- Maintain backward compatibility with the existing CLI and search tools

### Non-Goals

- PDF support (future phase)
- Modifying source `.epub` files
- Adding a new database (SQLite + ChromaDB are sufficient)
- Tag/genre/comment fields (future phase)
- Metadata lookup from external APIs like Open Library (future phase)
- Web UI or additional transport protocols

---

## 4. Architecture

### 4.1 How It Fits

The existing architecture already separates concerns cleanly:

```
Filesystem MCP          mnemo MCP
(user's computer)       (Claude's environment)
      │                       │
      │  path to .epub        │
      └──────────────────────►│
                              │
                    ┌─────────┴─────────┐
                    │  New MCP Tools     │
                    │  add_book          │
                    │  remove_book       │
                    │  update_book_meta  │
                    └─────────┬─────────┘
                              │
                    ┌─────────┴─────────┐
                    │  Existing Layer    │
                    │  ingest.py         │
                    │  SQLite + ChromaDB │
                    └───────────────────┘
```

Claude reads the epub from the user's filesystem via the Filesystem MCP, then calls mnemo's `add_book` tool with the file path. Mnemo handles parsing, chunking, embedding, and storage. No new storage systems are needed.

### 4.2 File Access Pattern

The ebook directory path is configured via the `MNEMO_BOOKS_DIR` environment variable in the MCP server config. The mnemo server reads `.epub` files directly from this path. The Filesystem MCP extension provides Claude with the ability to list and browse the directory, but the actual file reading for ingestion is done by mnemo's existing `EPUBParser`.

**Claude Desktop config example:**
```json
{
  "mcpServers": {
    "mnemo": {
      "command": "python",
      "args": ["-m", "mnemo.mcp.server"],
      "env": {
        "MNEMO_BOOKS_DIR": "/Users/joel/Documents/Books",
        "DATABRICKS_TOKEN": "...",
        "DATABRICKS_HOST": "..."
      }
    }
  }
}
```

### 4.3 Why Not a New Database?

The existing SQLite `books` table already tracks title, authors, ISBN, file_hash, and added_at. ChromaDB stores chunk-level metadata for vector search. Both support update operations. Adding a third store would create sync complexity for no gain. The SQLite `books` table is the single source of truth for editable metadata; ChromaDB metadata is derived from it during ingestion.

---

## 5. New MCP Tools

### 5.1 `add_book`

Ingest an EPUB file into the library.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | `str` | yes | Absolute path to the `.epub` file |
| `force` | `bool` | no | Re-index if already exists (default: false) |
| `embed` | `bool` | no | Generate embeddings after chunking (default: true) |

**Returns:** Markdown summary with book ID, title, authors, chunk count, or error message.

**Behavior:**
- Validates file exists and is `.epub`
- Checks for duplicate via `file_hash`
- If duplicate found and `force=false`, returns error with existing book ID
- Delegates to existing `ingest_book()` pipeline
- Returns structured result for Claude to report to the user

**Error cases:** file not found, not an epub, duplicate exists, embedding credentials missing.

### 5.2 `remove_book`

Remove a book and all its chunks and vectors.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `book_id` | `str` | yes | 6-char hex book identifier |

**Returns:** Confirmation message or "not found" error.

**Behavior:** Delegates to existing `remove_book()` in `ingest.py`. Cascade delete handles chunks in SQLite; vectors cleaned from ChromaDB.

### 5.3 `update_book_metadata`

Edit a book's metadata in SQLite only.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `book_id` | `str` | yes | 6-char hex book identifier |
| `title` | `str` | no | New title |
| `authors` | `list[str]` | no | New author list |
| `isbn` | `str` | no | New ISBN |

**Returns:** Updated book info (same format as `get_book_info`).

**Behavior:**
- At least one of `title`, `authors`, or `isbn` must be provided
- Updates only the specified fields in the SQLite `books` table
- Does NOT re-chunk, re-embed, or modify ChromaDB chunk metadata
- Does NOT touch the source `.epub` file

**Rationale for not updating ChromaDB metadata:** Chunk metadata in ChromaDB includes `book_id` and `section_path` but not title/author. The `SearchService` already resolves book titles from SQLite via `_get_book_title()`, so updating SQLite is sufficient for search results to reflect the new metadata.

---

## 6. Data Model Changes

### 6.1 SQLite: `books` Table

No schema changes required. The existing table already has `title`, `authors` (JSON array), and `isbn` columns. The new `update_book_metadata` tool writes to these columns directly.

### 6.2 New: `BookRepository.update()` Method

```python
def update(
    self,
    book_id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> Book | None:
    """Update book metadata fields. Returns updated Book or None if not found."""
```

This is the only repository change needed. The method builds a dynamic UPDATE statement for the provided fields.

### 6.3 ChromaDB

No changes. Chunk vectors and metadata remain untouched by metadata edits.

---

## 7. Implementation Plan

### Phase 1: Repository Layer (small)

- Add `BookRepository.update()` method
- Unit tests for update with each field combination
- Test that update with no fields raises `ValueError`
- Test that update on nonexistent book returns `None`

### Phase 2: MCP Tool Implementations (medium)

- Add `_add_book_impl()`, `_remove_book_impl()`, `_update_book_metadata_impl()` in `mcp/tools.py`
- Register tools with `@mcp.tool` decorators
- Wire `add_book` to existing `ingest_book()` from `ingest.py`
- Wire `remove_book` to existing `remove_book()` from `ingest.py`
- Wire `update_book_metadata` to new `BookRepository.update()`

### Phase 3: Environment Config (small)

- Add `MNEMO_BOOKS_DIR` support to server startup
- Validate the directory exists on server init (warn, don't crash)
- Use in `add_book` for path validation (optional: restrict paths to this dir)

### Phase 4: Testing (medium)

- Unit tests for each tool implementation function
- Integration test: add → search → update metadata → search (title updated in results)
- Integration test: add → remove → search (no results)
- Integration test: add duplicate without force → error; with force → success
- MCP protocol test: verify tool schemas are correct

---

## 8. Tool Interaction Examples

### Adding a book

```
User: "Add the Python Cookbook from my Books folder"
Claude: [uses Filesystem to list /Users/joel/Documents/Books]
Claude: [finds python-cookbook.epub]
Claude: [calls add_book(file_path="/Users/joel/Documents/Books/python-cookbook.epub")]
Claude: "Added Python Cookbook by David Beazley (id: a3f7c2) — 892 chunks indexed."
```

### Fixing metadata

```
User: "The author on that book is wrong, it should be David Beazley and Brian K. Jones"
Claude: [calls update_book_metadata(book_id="a3f7c2", authors=["David Beazley", "Brian K. Jones"])]
Claude: "Updated authors for Python Cookbook."
```

### Removing a book

```
User: "Remove the old edition"
Claude: [calls list_available_books to identify it]
Claude: [calls remove_book(book_id="b2e9f1")]
Claude: "Removed b2e9f1 from the library."
```

---

## 9. Security & Safety

- **Read-only source files:** mnemo never writes to the epub directory. The `EPUBParser` opens files in read mode only.
- **Path validation:** `add_book` validates the file path exists and ends in `.epub`. Optionally restrict to `MNEMO_BOOKS_DIR` to prevent ingestion of arbitrary filesystem paths.
- **No destructive defaults:** `remove_book` requires explicit `book_id`. `add_book` with `force=false` refuses duplicates. Claude must confirm actions with the user.
- **MCP tool annotations:** Mark `remove_book` with `destructiveHint=True` so clients can surface confirmation prompts.

---

## 10. Future Extensions (Out of Scope)

These are explicitly deferred but inform the design:

| Feature | Why deferred | Design consideration |
|---------|-------------|---------------------|
| PDF support | Different parser needed | `add_book` accepts `file_path`; parser selection can be based on extension |
| Tags & comments | Needs schema migration | Add columns to `books` table; new `update_book_metadata` params |
| Metadata lookup (Open Library, Google Books) | API dependency | New tool `lookup_book_metadata(isbn)` that returns suggestions; user confirms before `update_book_metadata` |
| Bulk import | Depends on `add_book` working well | New tool `scan_books_dir()` that lists unindexed epubs |
| Re-embed after metadata change | Expensive, rarely needed | Flag on `update_book_metadata` to trigger re-embedding |

---

## 11. Success Criteria

- Claude can add an epub by path, receiving confirmation with book ID and chunk count
- Claude can remove a book by ID with confirmation
- Claude can update title, authors, or ISBN and see changes reflected in `get_book_info` and search results
- All existing CLI commands and search tools continue working unchanged
- Source `.epub` files are never modified (verified by file hash comparison in tests)
