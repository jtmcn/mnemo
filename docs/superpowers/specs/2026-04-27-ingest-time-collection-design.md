# Ingest-Time Collection Support — Design

**Status:** Approved 2026-04-27
**Follows:** `docs/superpowers/plans/2026-04-15-book-collections.md` (book collections feature, shipped in v1.11.0)

## Motivation

The book collections feature (v1.11.0) added a `collection` field on `Book` and exposed it through `update_book_metadata` and `search_books`. However, ingestion paths (`mnemo add`, MCP `add_book`, and the underlying `ingest_book`) don't accept a `collection` argument. The user's stated workflow — tagging 67 ERCOT nodal protocol files as part of the same group — currently requires:

1. 67 ingest calls (`mnemo add file_i.docx`)
2. 67 follow-up `update_book_metadata(book_id_i, collection="ERCOT Nodal Protocols")` calls

This phase closes the gap. After this change, the workflow collapses to a single CLI command:

```
mnemo add ercot/*.docx --collection "ERCOT Nodal Protocols"
```

…and the equivalent MCP call exists for AI-assistant-driven ingestion.

## Architecture

Thread a `collection: str | None = None` parameter through the existing ingestion chain:

```
CLI add command  ──┐
                   ├──▶ _add_book_impl ──▶ ingest_book ──▶ Book.collection
MCP add_book   ────┘
```

`ingest_book` is the central choke point. It already uses a `model_copy` to set `file_path` on the parsed `Book` post-parse; the same pattern handles `collection`. The MCP and CLI layers are thin pass-throughs.

**Duplicate handling (Approach A — strict):** if the book already exists in the library and `force=False`, ingestion returns the existing-book error as it does today. The `collection` parameter is *not* applied to the existing book. Re-tagging an already-indexed book is an explicit operation through `update_book_metadata`. With `force=True`, the existing book is removed and a fresh ingest applies the collection to the new row.

This preserves the principle that `add` is for new content and `update_book_metadata` is for editing existing content. It also avoids surprising silent mutations on duplicate-detect paths.

## Components and Changes

### `src/mnemo/ingest.py`

Add `collection: str | None = None` parameter to `ingest_book()`. After parsing the book at line 153 and before the duplicate check at line 159, fold `collection` into the existing `model_copy` call that sets `file_path`:

```python
updates = {"file_path": str(book_path.resolve())}
if collection:
    updates["collection"] = collection
book = book.model_copy(update=updates)
```

Empty string and `None` are both treated as "no collection" (skip the field). No normalization, no validation — collection is an opaque user-defined string consistent with the rest of the feature.

### `src/mnemo/mcp/tools_books.py`

`_add_book_impl`: add `collection: str | None = None` parameter. Forward to `pipeline_ingest(...)`.

`add_book` MCP tool: add `collection: str | None = None` to the registered signature. Update docstring to describe the parameter and explicitly note that it only applies to fresh ingests (duplicates without `force=True` will not be retagged).

### `src/mnemo/cli.py`

Add `--collection` Typer option (no short form) to the `add` command:

```python
collection: Annotated[
    str | None,
    typer.Option("--collection", help="Group these books under a collection name"),
] = None,
```

When the user passes multiple paths, the same `collection` applies to all of them (single value per invocation). Forward through the existing per-path ingestion loop.

### Version

Bump `pyproject.toml` and `CLAUDE.md` from `1.11.0` to `1.12.0` (new feature, backward-compatible).

## Data Flow

User runs `mnemo add ercot/*.docx --collection "ERCOT Nodal Protocols"`:

1. CLI iterates paths, calls `ingest_book(path, collection="ERCOT Nodal Protocols")` for each
2. `ingest_book` parses each file → constructs a `Book` from metadata
3. `Book` gets `file_path` and `collection` set via `model_copy`
4. Duplicate check runs against `file_hash`
5. New books: persisted with `collection` populated; chunks stored; embeddings (optional)
6. Duplicate books without `force`: `ValueError` raised; existing book unchanged
7. CLI surfaces success/error per file as it does today

## Testing

**`tests/test_integration.py`** (real-DB end-to-end):

- `test_ingest_book_persists_collection`: ingest a book with `collection="X"`, verify `BookRepository.get(...).collection == "X"`
- `test_ingest_book_without_collection`: ingest without the param, verify `collection is None`
- `test_ingest_duplicate_with_collection_does_not_retag`: ingest twice with different collection values; second call raises `ValueError`; existing book's collection from the first ingest is preserved (not overwritten by the second). Locks in Approach A.
- `test_ingest_force_with_collection_replaces`: ingest, then re-ingest with `force=True, collection="Y"`; verify the new book has `collection == "Y"`

**`tests/test_mcp.py`:**

- `test_add_book_forwards_collection`: `_add_book_impl(path, collection="X")` calls `ingest_book` with `collection="X"`
- `test_add_book_default_collection_is_none`: omitting the param results in `collection=None` reaching `ingest_book`

**`tests/test_cli.py`:**

- `test_cli_add_with_collection`: `mnemo add file.docx --collection "X"` invokes the ingest path with `collection="X"`
- `test_cli_add_multi_path_with_collection`: passing multiple paths and one `--collection` applies the same value to each ingest call

## Out of Scope

- **Bulk-add to MCP `add_book`**: still one file per call. AI-assistant workflow can loop calls if needed.
- **Per-file collection overrides (manifest)**: one collection per invocation; no per-file mapping.
- **Auto-retag on duplicate**: rejected during brainstorming. Use `update_book_metadata` for re-tagging.
- **`Book.from_metadata` classmethod extension**: bypassed via the existing `model_copy` pattern in `ingest_book`. Not needed.
- **Collection name normalization** (trim/lowercase): collection stays an opaque user-defined string.

## Acceptance Criteria

1. `mnemo add file.docx --collection "X"` results in a book with `collection == "X"`
2. `mnemo add file1.docx file2.docx --collection "X"` tags both files
3. MCP `add_book(file_path="...", collection="X")` works equivalently
4. Re-ingesting a duplicate without `--force` does not change the existing book's collection
5. Re-ingesting with `--force --collection "Y"` results in the new book having `collection == "Y"`
6. All existing tests still pass; new tests above pass
7. Version bumped to 1.12.0
