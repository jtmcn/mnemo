# Technology Stack: v1.2 RAG Improvements

**Project:** Mnemo
**Milestone:** v1.2 RAG Improvements (semantic chunking, context enrichment, metadata search, quick wins)
**Researched:** 2026-03-08
**Overall Confidence:** HIGH

## Executive Summary

The v1.2 milestone requires **zero new runtime dependencies**. All six features can be built using the existing stack (numpy, chromadb, tiktoken, sqlite3, pydantic). The critical findings are:

1. **Semantic chunking** is a ~100-line algorithm using numpy cosine similarity on embeddings the project already generates via Databricks. No chunking library (chonkie, langchain, etc.) is needed or advisable.
2. **Cosine distance** requires a ChromaDB collection recreation (not a migration) -- the space parameter is immutable after creation. Use `configuration={"hnsw": {"space": "cosine"}}` on ChromaDB 1.5.0 (already installed).
3. **Context enrichment** uses existing SQLite `prev_chunk_id`/`next_chunk_id` links -- the schema already supports chunk expansion with zero changes.
4. **Metadata search** uses existing ChromaDB `$and` where clauses and SQLite indexes on `section_path` and `sequence`.
5. **Search scores and configurable chunks** are pure code changes to existing models and configs.

This is an algorithm and configuration milestone, not a dependency milestone.

---

## Stack Additions Required

### New Dependencies: NONE

Every capability maps to what is already installed:

| Feature | Requires | Provided By | Installed |
|---------|----------|-------------|-----------|
| Semantic chunking (embedding distances) | Cosine similarity, embeddings | `numpy>=1.26` (2.4.2), `httpx` (Databricks API) | Yes |
| Sentence splitting for semantic chunking | Sentence boundary detection | `re` (stdlib) | Yes |
| Context enrichment (chunk expansion) | Adjacent chunk retrieval | `sqlite3` (stdlib), existing `prev_chunk_id`/`next_chunk_id` | Yes |
| Metadata-enriched search (section path) | ChromaDB metadata filtering | `chromadb>=1.0.0` (1.5.0) | Yes |
| Cosine distance metric | ChromaDB collection config | `chromadb>=1.0.0` (1.5.0) | Yes |
| Search scores in results | Model field addition | `pydantic>=2.0` | Yes |
| Configurable chunk sizes | Config parameter | `pydantic>=2.0` or `dataclasses` (stdlib) | Yes |
| Token counting for chunk size validation | Token counting | `tiktoken>=0.5` | Yes |

---

## Feature-by-Feature Stack Analysis

### 1. Semantic Chunking (Embedding-Distance Boundary Detection)

**What it does:** Instead of splitting text at fixed token counts, embed each sentence, compute cosine similarity between consecutive sentences, and split where similarity drops below a threshold.

**Algorithm (implement from scratch, ~100 lines):**
1. Split text block into sentences (regex, already have `re` in tokenizer.py)
2. Batch-embed sentences via existing `DatabricksEmbedder.embed_batch()`
3. Compute cosine similarity between consecutive sentence embeddings (numpy)
4. Detect boundaries where similarity drops below threshold (percentile-based)
5. Group sentences into chunks respecting `max_tokens` constraint

**Why NOT use chonkie or other chunking libraries:**

| Library | Why Not |
|---------|---------|
| chonkie | Adds 505KB+ dependency, requires adapting BaseEmbeddings interface to wrap Databricks client, introduces sentence-transformers transitive dep for its default model. The core algorithm is trivial with numpy. |
| langchain text splitters | Massive dependency for one function. Project explicitly avoids langchain. |
| semantic-chunking (PyPI) | Low-maintenance package, unnecessary abstraction over simple cosine similarity. |
| llama-index | Same issue as langchain -- heavy framework dependency for a focused algorithm. |

**Key integration point:** The semantic chunker slots into `Chunker._create_text_chunks()` as an alternative strategy. Code/diagram/math/table blocks remain atomic (never split). Only TEXT blocks use semantic boundaries.

**numpy cosine similarity (already available):**
```python
import numpy as np

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
```

**Sentence splitting:** Use regex similar to the existing `split_by_tokens` in `tokenizer.py`. The `re` module in stdlib is sufficient -- no need for NLTK or spacy sentence tokenizers for technical book text.

**Embedding cost consideration:** Semantic chunking embeds every sentence during ingestion. For a 500-page book with ~5000 sentences, that is ~100 batches of 50 = 100 API calls. This is a one-time ingestion cost, acceptable at personal scale.

**Confidence:** HIGH -- the algorithm is well-documented (Greg Kamradt's approach), numpy cosine similarity is trivial, and the project already has the embedding infrastructure.

---

### 2. Cosine Distance Metric (ChromaDB)

**Current state:** Collection uses `metadata={"hnsw:space": "l2"}` (line 57 of `vectors/store.py`).

**Target state:** Use `configuration={"hnsw": {"space": "cosine"}}` with ChromaDB 1.5.0.

**Critical constraint: Space is immutable.** ChromaDB does not support changing the distance metric on an existing collection. The collection must be deleted and recreated.

**Migration approach:**
1. Delete existing ChromaDB collection
2. Recreate with `configuration={"hnsw": {"space": "cosine"}}`
3. Re-embed all books (chunks are preserved in SQLite)

**API change in store.py:**
```python
# OLD (legacy metadata format)
self.collection = self.client.get_or_create_collection(
    name=self.config.collection_name,
    metadata={"hnsw:space": "l2"},
)

# NEW (ChromaDB 1.0+ configuration format)
self.collection = self.client.get_or_create_collection(
    name=self.config.collection_name,
    configuration={"hnsw": {"space": "cosine"}},
)
```

**Why cosine over L2:** With L2 on normalized vectors (which is what the project currently does via `_normalize()`), L2 and cosine are mathematically equivalent. However, switching to native cosine means:
- No manual L2 normalization needed before storage (ChromaDB handles it)
- Distance values are interpretable (0 = identical, 2 = opposite)
- Industry standard for text embeddings

**Important:** After switching to cosine, the `_normalize()` method can potentially be kept for safety (cosine distance on pre-normalized vectors is fine) or removed. Keeping it is safer -- it is a no-op on already-normalized vectors.

**Confidence:** HIGH -- verified on ChromaDB 1.5.0 docs, `configuration` parameter format confirmed.

**Sources:**
- [ChromaDB Collection Configuration](https://docs.trychroma.com/docs/collections/configure)
- [ChromaDB Migration Guide](https://docs.trychroma.com/deployment/migration)

---

### 3. Context Enrichment (Chunk Expansion)

**What it does:** When a search returns chunk X, also retrieve chunks X-1 and X+1 (or configurable window) to provide surrounding context.

**Existing infrastructure (zero schema changes):**
- `Chunk.prev_chunk_id` and `Chunk.next_chunk_id` already exist in the model
- `ChunkRepository.get()` retrieves a chunk by ID
- Chunks are already linked during `Chunker._link_chunks()`

**Implementation approach:**
1. After search returns results, for each result chunk, follow `prev_chunk_id`/`next_chunk_id` links
2. Retrieve N adjacent chunks in each direction (configurable window, default 1)
3. Concatenate content in sequence order for the enriched result

**Alternative approach (sequence-based):**
Instead of following linked-list pointers (N+1 queries per result), query by `book_id` and `sequence` range:
```sql
SELECT * FROM chunks
WHERE book_id = ? AND sequence BETWEEN ? AND ?
ORDER BY sequence
```
This is a single query per result and uses the existing index `idx_chunks_sequence ON chunks(book_id, sequence)`.

**Recommendation:** Use the sequence-based approach. It is more efficient (one query instead of following a linked list) and the index already exists.

**No new dependencies required.**

**Confidence:** HIGH -- the schema and indexes already support this pattern.

---

### 4. Metadata-Enriched Search (Section Path Filtering)

**What it does:** Allow search queries to filter by section path (e.g., "only search in Chapter 3") and sequence range.

**ChromaDB metadata filtering (already supported):**
The `section_path` is already stored as a metadata string in ChromaDB (joined with " > "):
```python
metadatas = [{
    "book_id": chunk.book_id,
    "content_type": chunk.content_type.value,
    "section_path": " > ".join(chunk.section_path),
    "sequence": chunk.sequence,
}]
```

ChromaDB supports `$contains` for substring matching on metadata:
```python
where={"section_path": {"$contains": "Chapter 3"}}
```

**SQLite filtering (for keyword search):**
Add a WHERE clause on `section_path` column (JSON array stored as TEXT):
```sql
WHERE json_extract(section_path, '$') LIKE '%Chapter 3%'
```
Or add a new `section_path_text` column with the flattened path for simpler filtering.

**SearchFilter model extension:**
```python
@dataclass
class SearchFilter:
    book_id: str | None = None
    content_type: str | None = None
    section_path: str | None = None        # NEW: filter by section
    sequence_min: int | None = None         # NEW: filter by sequence range
    sequence_max: int | None = None         # NEW: filter by sequence range
```

**No new dependencies required.**

**Confidence:** HIGH -- ChromaDB `$contains` operator is documented, SQLite JSON functions are stdlib.

---

### 5. Search Scores in Results

**What it does:** Expose raw relevance scores from ChromaDB (distance) and FTS5 (rank) alongside the RRF fusion score.

**Current state:** `SearchResult.score` contains the RRF score. ChromaDB distances are computed but discarded after ranking.

**Changes needed:**
1. Add `semantic_distance` and `keyword_rank` fields to `SearchResult`
2. Pass ChromaDB `distance` values through the search pipeline
3. For cosine distance: lower = more similar (0 to 2 range)

**SearchResult model extension:**
```python
@dataclass
class SearchResult:
    # ... existing fields ...
    score: float                              # RRF fusion score
    semantic_distance: float | None = None    # NEW: raw ChromaDB distance
    keyword_rank: int | None = None           # NEW: FTS5 rank position
```

**No new dependencies required.**

**Confidence:** HIGH -- straightforward model and pipeline change.

---

### 6. Configurable Chunk Sizes

**What it does:** Allow per-book chunk size configuration at ingest time, overriding the default 400-800 token range.

**Current state:** `ChunkerConfig` already supports `min_tokens`, `max_tokens`, and `overlap_tokens` as constructor parameters. The `ingest_book()` function already accepts `chunker_config: ChunkerConfig | None`.

**What needs to change:**
1. Expose `ChunkerConfig` parameters through CLI (`mnemo add --min-tokens 200 --max-tokens 600`)
2. Expose through MCP `add_book` tool parameters
3. Optionally store the config used per book in SQLite (for re-embedding reference)

**Schema consideration:** Consider adding `chunk_config` column to `books` table (JSON blob) so re-embedding can use the same settings. This is a minor schema migration.

**No new dependencies required.**

**Confidence:** HIGH -- the config infrastructure already exists, just needs exposure.

---

## Alternatives Considered

| Category | Recommendation | Alternative | Why Not |
|----------|---------------|-------------|---------|
| Semantic chunking | Implement from scratch (~100 LOC) | chonkie library | Adds dependency + transitive deps (sentence-transformers), requires wrapping Databricks API in BaseEmbeddings interface. Algorithm is trivial with numpy. |
| Semantic chunking | Implement from scratch | langchain text splitters | Massive dependency for one function. Project does not use langchain. |
| Sentence splitting | stdlib `re` | NLTK `sent_tokenize` | NLTK requires downloading models at runtime. Regex handles technical text adequately (abbreviations like "e.g." can be handled with a negative lookbehind). |
| Sentence splitting | stdlib `re` | spaCy | Heavy NLP dependency (hundreds of MB) for sentence splitting. Massive overkill. |
| Cosine similarity | numpy (already installed) | scipy | scipy is a transitive dep of chromadb but not explicitly declared. numpy is already a direct dependency and `np.dot` + `np.linalg.norm` is 2 lines. |
| Chunk expansion | Sequence-based SQL query | Follow prev/next linked list | Linked list traversal requires N queries per direction per result. Sequence range query is single query with existing index. |
| Distance metric | ChromaDB native cosine | Keep L2 with manual normalization | Mathematically equivalent for normalized vectors, but native cosine is cleaner and gives interpretable distance values. |

---

## Integration Points

### Files That Change

| File | Change | Feature |
|------|--------|---------|
| `src/mnemo/chunking/chunker.py` | Add semantic chunking strategy alongside fixed-token | Semantic chunking |
| `src/mnemo/chunking/tokenizer.py` | Add sentence splitting function | Semantic chunking |
| `src/mnemo/vectors/store.py` | Change `metadata={"hnsw:space": "l2"}` to `configuration={"hnsw": {"space": "cosine"}}` | Cosine distance |
| `src/mnemo/search/service.py` | Add chunk expansion logic, pass through raw scores | Context enrichment, search scores |
| `src/mnemo/search/models.py` | Add `semantic_distance`, `keyword_rank`, `section_path` filter fields | Search scores, metadata search |
| `src/mnemo/vectors/store.py` | Add `section_path` to `_build_where()` | Metadata search |
| `src/mnemo/ingest.py` | Pass chunk config params through | Configurable chunks |
| `src/mnemo/mcp/tools.py` | Add chunk config params to `add_book`, expose scores | Configurable chunks, scores |
| `src/mnemo/cli.py` | Add `--min-tokens`/`--max-tokens` flags | Configurable chunks |
| `src/mnemo/storage/repository.py` | Add `get_by_sequence_range()` method | Context enrichment |

### Files That Do NOT Change

| File | Why Not |
|------|---------|
| `src/mnemo/models.py` | Chunk model already has `section_path`, `sequence`, `prev_chunk_id`, `next_chunk_id` |
| `src/mnemo/embeddings/client.py` | Embedding client is used as-is for semantic chunking sentence embeddings |
| `src/mnemo/storage/database.py` | Schema changes are minimal (possibly one column for chunk_config), but core schema is sufficient |

---

## What NOT to Add

| Suggestion | Why Not |
|------------|---------|
| `chonkie` | Trivial algorithm does not justify a dependency with its own embedding abstraction layer and transitive deps. 100 lines of numpy is simpler than adapting the BaseEmbeddings interface. |
| `langchain` | Framework dependency for one utility function. Against project philosophy. |
| `nltk` | Requires runtime model downloads for sentence tokenization. Regex is sufficient. |
| `spacy` | Hundreds of MB for sentence splitting. Massive overkill at personal scale. |
| `scipy` | numpy already provides cosine similarity in 2 lines. scipy adds nothing. |
| `sentence-transformers` | Project uses Databricks GTE-large-en, not local models. Adding a local model framework is wrong direction. |
| `pydantic-settings` | No new environment variables in this milestone. |
| `alembic` / migration tool | One optional column addition does not justify a migration framework. `ALTER TABLE ADD COLUMN` is sufficient. |
| `redis` / caching layer | Embedding cache for semantic chunking is unnecessary -- embeddings are computed once at ingest time and discarded. Sentence embeddings are intermediate, not stored. |

---

## pyproject.toml: No Changes Required

```toml
dependencies = [
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "tiktoken>=0.5",
    "pydantic>=2.0",
    "httpx>=0.27",
    "tenacity>=8.3",
    "numpy>=1.26",          # <-- cosine similarity for semantic chunking
    "chromadb>=1.0.0",      # <-- 1.5.0 installed, supports configuration param
    "fastmcp>=2.14,<3",
]
```

No new lines needed.

---

## Installed Version Verification

| Package | Required | Installed | Status |
|---------|----------|-----------|--------|
| chromadb | >=1.0.0 | 1.5.0 | OK -- supports `configuration={"hnsw": {"space": "cosine"}}` |
| numpy | >=1.26 | 2.4.2 | OK -- `np.dot`, `np.linalg.norm` for cosine similarity |
| tiktoken | >=0.5 | (installed) | OK -- `cl100k_base` for token counting |
| pydantic | >=2.0 | (installed) | OK -- model extensions |
| httpx | >=0.27 | (installed) | OK -- Databricks API for sentence embeddings |
| tenacity | >=8.3 | (installed) | OK -- retry logic for embedding API |

---

## Sources

### Official Documentation (HIGH confidence)
- [ChromaDB Collection Configuration](https://docs.trychroma.com/docs/collections/configure) -- `configuration` parameter format, space options
- [ChromaDB Migration Guide](https://docs.trychroma.com/deployment/migration) -- immutability of collection settings
- [ChromaDB Cookbook - Collections](https://cookbook.chromadb.dev/core/collections/) -- `get_or_create_collection` behavior

### Verified by Codebase Inspection (HIGH confidence)
- `src/mnemo/vectors/store.py` -- current L2 distance config, `_normalize()` method
- `src/mnemo/chunking/chunker.py` -- current `ChunkerConfig`, atomic vs text splitting
- `src/mnemo/search/service.py` -- current search pipeline, score handling
- `src/mnemo/models.py` -- `Chunk.prev_chunk_id`, `next_chunk_id`, `section_path`, `sequence`
- `src/mnemo/storage/database.py` -- existing `idx_chunks_sequence` index
- `src/mnemo/storage/repository.py` -- existing `ChunkRepository.get()`, `get_by_book()`

### Community/Research Sources (MEDIUM confidence)
- [Semantic Chunking via Embedding Distance](https://superlinked.com/vectorhub/articles/semantic-chunking) -- Greg Kamradt's boundary detection approach
- [Chonkie Library](https://github.com/chonkie-inc/chonkie) -- evaluated and rejected (unnecessary dependency)
- [ChromaDB Defaults to L2](https://razikus.substack.com/p/chromadb-defaults-to-l2-distance-why-that-might-not-be-the-best-choice-ac3d47461245) -- rationale for cosine over L2
