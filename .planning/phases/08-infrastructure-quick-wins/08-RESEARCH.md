# Phase 8: Infrastructure & Quick Wins - Research

**Researched:** 2026-03-10
**Domain:** ChromaDB migration, search scoring, configurable chunking, SQLite schema evolution
**Confidence:** HIGH

## Summary

Phase 8 covers five independent workstreams that share no inter-dependencies: (1) migrating the ChromaDB collection from L2 to cosine distance, (2) exposing cosine similarity scores in search results, (3) making chunk sizes configurable per book at ingest time, (4) persisting EPUB file paths in the books table, and (5) a CLI command to run the migration.

All changes are achievable with the existing stack (ChromaDB 1.4.1, SQLite, Python 3.11+). No new dependencies are needed. The hardest part is the ChromaDB migration: `get_or_create_collection` silently ignores distance metric changes on existing collections, so migration must create a new collection, copy all data (embeddings + metadata + documents), verify counts match, then delete the old collection.

**Primary recommendation:** Implement as five independent tasks that can be built and tested in isolation. The migration script is the highest-risk item and should be built with explicit count verification and a dry-run option.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | ChromaDB collection uses cosine distance metric instead of L2 | VectorStore `__init__` changes `hnsw:space` from `l2` to `cosine`. Migration handles existing data. |
| INFRA-02 | Migration script copies existing vectors from L2 collection to new cosine collection without re-embedding | ChromaDB `collection.get(include=['embeddings','metadatas','documents'])` with limit/offset provides batch extraction. New collection created with `hnsw:space: cosine`. |
| INFRA-03 | Migration verifies vector counts match before deleting old collection | Compare `old_collection.count()` with `new_collection.count()` before calling `client.delete_collection(old_name)`. |
| INFRA-04 | EPUB file path stored in books table for future re-indexing | SQLite ALTER TABLE adds `epub_path TEXT` column. Stored as absolute resolved path during ingest. |
| INFRA-05 | CLI `migrate-cosine` command runs the collection migration | New typer command in `cli.py` delegating to migration function. |
| SRCH-01 | Search results include numeric relevance scores (cosine similarity 0-1) | Cosine distance in ChromaDB ranges 0-2 for normalized vectors. Similarity = `1 - distance`. Score replaces current RRF-based placeholder. |
| CHUNK-01 | `add_book` MCP tool accepts optional `chunk_min_tokens` and `chunk_max_tokens` parameters | Add parameters to `add_book` tool signature, pass through to `ChunkerConfig`. |
| CHUNK-02 | Chunk size parameters validate: min >= 100, max <= 2000, min < max | Validation in `add_book` before passing to ingest pipeline. |
| CHUNK-03 | Default chunk sizes remain 400/800 when not specified (backward compatible) | `ChunkerConfig` already defaults to 400/800. Only override when parameters explicitly provided. |
</phase_requirements>

## Standard Stack

### Core (already installed, no changes)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| chromadb | 1.4.1 | Vector storage with cosine distance | Already in use, supports `hnsw:space: cosine` |
| sqlite3 | stdlib | Books table schema evolution | ALTER TABLE for epub_path column |
| typer | transitive | CLI migrate-cosine command | Already in use for CLI commands |
| numpy | >= 1.26 | L2 normalization (still needed for cosine) | Already in use |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual batch migration | ChromaDB clone/copy | No built-in clone API exists in ChromaDB 1.4.x |

**Installation:**
```bash
# No new dependencies needed
```

## Architecture Patterns

### Migration Script Structure
```
src/mnemo/
  vectors/
    store.py          # Change hnsw:space to cosine
    migrate.py         # NEW: migration logic (separate from store)
  storage/
    database.py        # Add epub_path column to schema
  ingest.py           # Pass epub_path to book, pass chunk params through
  mcp/tools.py        # Add chunk_min/max params to add_book
  cli.py              # Add migrate-cosine command
```

### Pattern 1: ChromaDB Collection Migration
**What:** Create new cosine collection, batch-copy all data, verify counts, delete old.
**When to use:** Any distance metric change (one-time migration).
**Example:**
```python
# Source: Verified against ChromaDB 1.4.1 API (tested locally)
def migrate_to_cosine(client: chromadb.ClientAPI, collection_name: str = "mnemo") -> dict:
    old = client.get_collection(collection_name)
    old_count = old.count()

    if old_count == 0:
        # Empty collection - just recreate
        client.delete_collection(collection_name)
        client.create_collection(collection_name, metadata={"hnsw:space": "cosine"})
        return {"migrated": 0, "verified": True}

    # Create temp collection with cosine
    temp_name = f"{collection_name}_cosine_migration"
    new = client.create_collection(temp_name, metadata={"hnsw:space": "cosine"})

    # Batch copy (ChromaDB get supports limit/offset)
    batch_size = 1000
    offset = 0
    while offset < old_count:
        batch = old.get(
            include=["embeddings", "metadatas", "documents"],
            limit=batch_size, offset=offset,
        )
        if not batch["ids"]:
            break
        new.add(
            ids=batch["ids"],
            embeddings=batch["embeddings"],
            metadatas=batch["metadatas"],
            documents=batch["documents"],
        )
        offset += len(batch["ids"])

    # Verify counts match
    new_count = new.count()
    if new_count != old_count:
        client.delete_collection(temp_name)
        raise RuntimeError(f"Count mismatch: old={old_count}, new={new_count}")

    # Swap: delete old, rename new (ChromaDB has no rename, so delete+recreate)
    client.delete_collection(collection_name)
    # ChromaDB has no rename API - must copy again to final name
    final = client.create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    # Copy from temp to final...
    # OR: use temp_name as the permanent name and update VectorConfig

    return {"migrated": new_count, "verified": True}
```

**Important:** ChromaDB has no collection rename API. Two approaches:
1. Copy old -> temp_cosine, verify, delete old, copy temp -> final name, delete temp (3 copies total but same name preserved)
2. Copy old -> new name, verify, delete old, update config to use new name (1 copy, name changes)

**Recommendation:** Use approach 1 (preserve name) since the collection name "mnemo" is used in VectorConfig default and throughout the codebase. Alternatively, since the data is already in the temp collection and verified, we can copy from temp to final in one more batch pass. For collections with many vectors, approach 2 is faster but changes config.

**Simpler approach:** Since we need the same name, the cleanest pattern is:
1. Create `mnemo_cosine` with cosine metric
2. Batch copy all data from `mnemo` to `mnemo_cosine`
3. Verify counts match
4. Delete `mnemo`
5. Create new `mnemo` with cosine metric
6. Batch copy from `mnemo_cosine` to `mnemo`
7. Verify counts match
8. Delete `mnemo_cosine`

This is two full copies but guarantees the original name is preserved and rollback is safe (old collection exists until step 4).

### Pattern 2: Cosine Similarity Score Conversion
**What:** Convert ChromaDB cosine distance to 0-1 similarity score.
**When to use:** Whenever returning search results after migration.
**Example:**
```python
# ChromaDB cosine distance for normalized vectors: 0 (identical) to 2 (opposite)
# Similarity = 1 - distance gives range: 1 (identical) to -1 (opposite)
# For practical purposes, clamp to 0-1:
similarity = max(0.0, 1.0 - distance)
```

### Pattern 3: SQLite Schema Migration
**What:** Add `epub_path` column to existing books table.
**When to use:** Schema evolution without losing data.
**Example:**
```python
# Safe ALTER TABLE - column may already exist
try:
    conn.execute("ALTER TABLE books ADD COLUMN epub_path TEXT")
    conn.commit()
except sqlite3.OperationalError as e:
    if "duplicate column name" not in str(e):
        raise
```

### Anti-Patterns to Avoid
- **Calling `get_or_create_collection` with new metadata to change distance:** Silently ignored. MUST delete and recreate.
- **Migrating without count verification:** Data loss would be undetectable.
- **Storing relative EPUB paths:** Use `Path.resolve()` for absolute paths since working directory may change.
- **Making chunk size validation only in MCP layer:** Validate in both MCP tool AND `ChunkerConfig` for defense in depth.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cosine similarity computation | Manual dot product calculation | ChromaDB's `hnsw:space: cosine` | Built into HNSW index, faster and correct |
| Token counting for validation | Character-based estimation | `tiktoken` (already used in `chunker.py`) | Accurate token counts match embedding model |

## Common Pitfalls

### Pitfall 1: ChromaDB Silently Ignores Metric Changes
**What goes wrong:** `get_or_create_collection("mnemo", metadata={"hnsw:space": "cosine"})` returns the existing L2 collection unchanged.
**Why it happens:** ChromaDB treats `get_or_create` as "get if exists" and only uses metadata on create.
**How to avoid:** Explicit delete + create workflow with data copy in between.
**Warning signs:** Distances still range 0-2+ instead of 0-2 for cosine.

### Pitfall 2: Cosine Distance Range Confusion
**What goes wrong:** Assuming cosine distance is 0-1 (it is 0-2 for chromadb).
**Why it happens:** Cosine similarity is -1 to 1, but ChromaDB returns cosine distance = 1 - cosine_similarity, ranging 0 to 2.
**How to avoid:** Use `similarity = max(0.0, 1.0 - distance)` to get a clean 0-1 score.
**Warning signs:** Scores > 1.0 or negative scores in output.

### Pitfall 3: L2 Normalization Still Required
**What goes wrong:** Removing L2 normalization after switching to cosine distance.
**Why it happens:** Assumption that cosine distance handles unnormalized vectors.
**How to avoid:** Keep `_normalize()` in VectorStore. ChromaDB's cosine distance still benefits from pre-normalized vectors for consistent results. GTE-large-en returns unnormalized embeddings.
**Warning signs:** Inconsistent similarity scores between queries.

### Pitfall 4: Migration on Empty Collection
**What goes wrong:** Migration script crashes on `get()` with no data, or count verification fails on 0 == 0.
**Why it happens:** Edge case not considered.
**How to avoid:** Check `old.count() == 0` upfront and just recreate the collection directly.

### Pitfall 5: SQLite ALTER TABLE Idempotency
**What goes wrong:** Running `ALTER TABLE books ADD COLUMN epub_path TEXT` twice crashes.
**Why it happens:** SQLite raises `OperationalError: duplicate column name`.
**How to avoid:** Catch the specific error, or check `PRAGMA table_info(books)` first.

### Pitfall 6: Loss of RRF Scores in Hybrid Search
**What goes wrong:** Replacing RRF scores with raw cosine similarity breaks hybrid search ranking.
**Why it happens:** RRF fusion scores and cosine similarity scores are different scales.
**How to avoid:** SRCH-01 says "include numeric relevance scores." For semantic-only mode, use cosine similarity directly. For hybrid mode, keep RRF scores but also pass through the cosine similarity as an additional field. Or: since the `score` field on `SearchResult` already exists, populate it with cosine similarity for semantic results and keep RRF for hybrid.
**Recommendation:** Populate `SearchResult.score` with cosine similarity (0-1) for semantic results, RRF score for hybrid. The score is already displayed in MCP output.

## Code Examples

### ChromaDB Batch Get (verified locally)
```python
# Source: Tested against ChromaDB 1.4.1
batch = collection.get(
    include=["embeddings", "metadatas", "documents"],
    limit=1000,
    offset=0,
)
# Returns dict with keys: ids, embeddings, metadatas, documents, uris, included, data
```

### SQLite Safe Column Addition
```python
# Source: SQLite documentation - ALTER TABLE
def add_epub_path_column(conn: sqlite3.Connection) -> None:
    """Add epub_path column if it doesn't exist."""
    try:
        conn.execute("ALTER TABLE books ADD COLUMN epub_path TEXT")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise
```

### Cosine Similarity from ChromaDB Distance
```python
# Source: Verified against ChromaDB 1.4.1 with normalized vectors
# For query [1,0,...0] against [0.707,0.707,...0]:
#   cosine_distance = 0.292893
#   similarity = 1 - 0.292893 = 0.707107 (correct cosine similarity)
def cosine_similarity(distance: float) -> float:
    """Convert ChromaDB cosine distance to 0-1 similarity score."""
    return max(0.0, min(1.0, 1.0 - distance))
```

### ChunkerConfig Validation
```python
# Validation for CHUNK-02
def validate_chunk_params(min_tokens: int | None, max_tokens: int | None) -> str | None:
    """Validate chunk size parameters. Returns error message or None."""
    if min_tokens is not None and min_tokens < 100:
        return "chunk_min_tokens must be >= 100"
    if max_tokens is not None and max_tokens > 2000:
        return "chunk_max_tokens must be <= 2000"
    if min_tokens is not None and max_tokens is not None and min_tokens >= max_tokens:
        return "chunk_min_tokens must be less than chunk_max_tokens"
    return None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| L2 distance in ChromaDB | Cosine distance for similarity search | This phase | Better semantic similarity ranking; 0-1 interpretable scores |
| RRF placeholder scores | Real cosine similarity scores | This phase | Users can judge result confidence |
| Fixed 400/800 chunk sizes | Configurable per-book chunk sizes | This phase | Tunable for different book types |

## Open Questions

1. **Double-copy migration vs config change**
   - What we know: ChromaDB has no rename API. Preserving collection name "mnemo" requires copying data twice (old->temp->new).
   - What's unclear: Whether the double-copy is worth it vs. just changing `VectorConfig.collection_name` default.
   - Recommendation: Preserve the name "mnemo" via double-copy. The collection is small (personal library, ~10 books, ~10K vectors max). The extra copy takes seconds. Changing config introduces migration state complexity.

2. **Score field semantics in hybrid mode**
   - What we know: Hybrid search uses RRF scores (small fractions like 0.032). Semantic search can now return real cosine similarity (0-1).
   - What's unclear: Should hybrid mode return RRF scores or try to normalize to 0-1?
   - Recommendation: Keep RRF scores for hybrid (they work for ranking), use cosine similarity for semantic-only mode. The `source` field on SearchResult already indicates which mode produced the result. SRCH-01 says "relevance scores (cosine similarity 0-1)" which applies to the cosine similarity conversion, not necessarily replacing RRF.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | Collection uses cosine metric | unit | `python -m pytest tests/test_vectors.py -x -k cosine` | Needs new tests |
| INFRA-02 | Migration copies vectors without re-embedding | unit | `python -m pytest tests/test_migration.py -x -k copy` | Wave 0 |
| INFRA-03 | Migration verifies counts before delete | unit | `python -m pytest tests/test_migration.py -x -k verify` | Wave 0 |
| INFRA-04 | EPUB path stored in books table | unit | `python -m pytest tests/test_storage.py -x -k epub_path` | Needs new tests |
| INFRA-05 | CLI migrate-cosine command | unit | `python -m pytest tests/test_cli.py -x -k migrate` | Needs new tests |
| SRCH-01 | Search results include cosine similarity 0-1 | unit | `python -m pytest tests/test_search.py -x -k score` | Needs new tests |
| CHUNK-01 | add_book accepts chunk size params | unit | `python -m pytest tests/test_mcp.py -x -k chunk_size` | Needs new tests |
| CHUNK-02 | Invalid chunk params rejected | unit | `python -m pytest tests/test_mcp.py -x -k chunk_valid` | Needs new tests |
| CHUNK-03 | Default chunk sizes backward compatible | unit | `python -m pytest tests/test_chunker.py -x -k default` | Partially exists |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_migration.py` -- covers INFRA-02, INFRA-03 (new file for migration logic)
- [ ] New tests in `tests/test_vectors.py` -- covers INFRA-01 (cosine collection creation)
- [ ] New tests in `tests/test_storage.py` -- covers INFRA-04 (epub_path column)
- [ ] New tests in `tests/test_search.py` -- covers SRCH-01 (cosine similarity scores)
- [ ] New tests in `tests/test_mcp.py` -- covers CHUNK-01, CHUNK-02 (chunk size params)

## Sources

### Primary (HIGH confidence)
- ChromaDB 1.4.1 API -- tested locally: collection creation with cosine metric, batch get with limit/offset, metric immutability on get_or_create
- SQLite ALTER TABLE -- stdlib documentation, well-known behavior
- Existing codebase -- `src/mnemo/vectors/store.py`, `src/mnemo/storage/database.py`, `src/mnemo/chunking/chunker.py`, `src/mnemo/mcp/tools.py`, `src/mnemo/ingest.py`, `src/mnemo/cli.py`

### Secondary (MEDIUM confidence)
- ChromaDB cosine distance range (0-2 for distance, not 0-1) -- verified locally with test vectors

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all existing libraries
- Architecture: HIGH -- verified ChromaDB APIs locally, straightforward SQLite changes
- Pitfalls: HIGH -- key gotchas verified (metric immutability, distance range, ALTER TABLE idempotency)

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable stack, no fast-moving dependencies)
