# Architecture: v1.2 RAG Improvements

**Project:** Mnemo v1.2 - Semantic Chunking, Context Enrichment, Metadata Search, Quick Wins
**Researched:** 2026-03-08
**Confidence:** HIGH (existing codebase examined, integration points verified)

## Executive Summary

The v1.2 features split into four clean categories with distinct integration points. **Semantic chunking** replaces the text-splitting logic inside `Chunker._create_text_chunks()` with an embedding-distance boundary detector that operates on sentences within a single `ContentBlock`. **Context enrichment** adds a post-search expansion step in `SearchService` that fetches neighboring chunks using the existing `prev_chunk_id`/`next_chunk_id` links. **Metadata-enriched search** extends the existing `VectorStore.query()` and `ChunkRepository.search_fts()` filter interfaces to accept section path and sequence range parameters. **Quick wins** (cosine distance, search scores, configurable chunk sizes) are isolated changes to `VectorConfig`, `SearchResult` formatting, and `ChunkerConfig` passthrough.

The critical architectural insight is that these features layer cleanly onto the existing architecture with **zero schema migrations** required. The chunks table already has `section_path`, `sequence`, `prev_chunk_id`, and `next_chunk_id` -- all the metadata needed for enrichment and filtering. The only component requiring a fundamentally new capability is the semantic chunker, which needs access to the embedding client during ingestion (currently only used in `embed_book()`).

---

## Component Change Map

### New Components

| Component | File | Purpose |
|-----------|------|---------|
| `SemanticBoundaryDetector` | `src/mnemo/chunking/semantic.py` | Detect topic shifts within text blocks using embedding similarity |

### Modified Components

| Component | File | Change |
|-----------|------|--------|
| `Chunker` | `src/mnemo/chunking/chunker.py` | Accept optional `SemanticBoundaryDetector`, use it for text block splitting |
| `ChunkerConfig` | `src/mnemo/chunking/chunker.py` | Add `semantic` bool flag and `similarity_threshold` parameter |
| `SearchService.search()` | `src/mnemo/search/service.py` | Add `section_path` and `sequence_range` filter params; add post-search context expansion |
| `SearchResult` | `src/mnemo/search/models.py` | Add `score` display in MCP output (already exists on model, just not surfaced well) |
| `VectorStore.query()` | `src/mnemo/vectors/store.py` | Add `section_path` filter to `_build_where()` |
| `VectorStore.__init__()` | `src/mnemo/vectors/store.py` | Use `cosine` instead of `l2` for new collections |
| `VectorConfig` | `src/mnemo/vectors/config.py` | Add `distance_metric` field |
| `ChunkRepository.search_fts()` | `src/mnemo/storage/repository.py` | Add `section_path` and `sequence_range` filter params |
| `ChunkRepository` | `src/mnemo/storage/repository.py` | Add `get_neighbors()` method for context expansion |
| `_format_search_results()` | `src/mnemo/mcp/tools.py` | Include score in output |
| `search_books` | `src/mnemo/mcp/tools.py` | Add `section_path` and `expand_context` parameters |
| `ingest_book()` | `src/mnemo/ingest.py` | Accept and pass through `ChunkerConfig` overrides |

### Unchanged Components

| Component | Why Unchanged |
|-----------|---------------|
| `models.py` (Chunk, Book) | Chunk model already has all needed fields |
| `database.py` (schema) | Schema already has section_path, sequence, prev/next links |
| `tokenizer.py` | Still needed for token counting within semantic chunks |
| `hybrid.py` (RRF) | Fusion algorithm unchanged |
| `embeddings/client.py` | Used as-is by semantic chunker |
| `epub/` parser modules | Parsing unchanged |

---

## Feature 1: Semantic Chunking

### Architecture Decision: Sentence-Level Boundary Detection Within Existing Block Pipeline

**Do not** replace the entire chunking pipeline. The existing `Chunker.chunk()` flow -- iterate ContentBlocks, keep atomic types whole, split text blocks -- is sound. Semantic chunking only changes **how text blocks are split**.

The approach: when `ChunkerConfig.semantic=True`, instead of calling `split_by_tokens()` on large text blocks, the chunker calls `SemanticBoundaryDetector.find_boundaries()` which:

1. Splits the text block into sentences
2. Embeds each sentence (using `DatabricksEmbedder`)
3. Computes cosine similarity between consecutive sentence embeddings
4. Identifies boundaries where similarity drops below threshold
5. Groups sentences into chunks respecting min/max token constraints

### Why This Approach Over Alternatives

**Alternative rejected: Embed-first-chunk-second (whole document).** This would require restructuring the entire pipeline from ContentBlock-based to document-based processing. It conflicts with the atomic block preservation (code, tables, diagrams) which is a critical design choice. The existing block-based pipeline correctly segments content types; semantic chunking should only refine text block splitting.

**Alternative rejected: LLM-based chunking.** Too expensive for personal use. A book with 500 text blocks would require 500 LLM calls.

**Alternative rejected: Off-the-shelf semantic chunkers (LangChain, LlamaIndex).** Adding a heavy framework dependency for one function is not justified. The algorithm is straightforward: ~50 lines of core logic.

### Data Flow

```
ContentBlock (TEXT, content="Long text about generators and then decorators...")
    |
    v
SemanticBoundaryDetector.find_boundaries(text, min_tokens, max_tokens)
    |
    |- sentence_split(text) -> ["Generators yield values.", "They pause execution.", ..., "Decorators modify functions.", ...]
    |- embed_batch(sentences) -> [[0.1, 0.2, ...], [0.1, 0.3, ...], ...]
    |- cosine_similarity(emb[i], emb[i+1]) -> [0.92, 0.88, ..., 0.31, ...]
    |- find drops below threshold -> boundary at index N
    |- merge small groups to meet min_tokens
    |- split large groups to meet max_tokens (falls back to token splitter)
    |
    v
["Generators yield values. They pause execution. ...", "Decorators modify functions. ..."]
```

### Integration Point: Embedding Client in Chunker

Currently the embedding client (`DatabricksEmbedder`) is only used in `embed_book()` during the embedding phase. Semantic chunking needs it during the chunking phase. This creates a new dependency path:

```
BEFORE: parse -> chunk -> store -> embed (embedder used here)
AFTER:  parse -> chunk (embedder used here for boundary detection) -> store -> embed (embedder used here for vectors)
```

**Design:** `SemanticBoundaryDetector` takes an embedding function (not a `DatabricksEmbedder` instance) to keep the chunking module decoupled from the embedding module:

```python
# src/mnemo/chunking/semantic.py
from typing import Callable

class SemanticBoundaryDetector:
    def __init__(
        self,
        embed_fn: Callable[[list[str]], list[list[float]]],
        similarity_threshold: float = 0.5,
    ):
        self.embed_fn = embed_fn
        self.similarity_threshold = similarity_threshold

    def find_boundaries(self, text: str, min_tokens: int, max_tokens: int) -> list[str]:
        """Split text into semantically coherent chunks."""
        ...
```

The `ingest_book()` function wires these together:

```python
if chunker_config and chunker_config.semantic:
    from mnemo.embeddings import DatabricksEmbedder
    embedder = DatabricksEmbedder()
    detector = SemanticBoundaryDetector(embed_fn=embedder.embed_batch)
    chunker = Chunker(chunker_config, boundary_detector=detector)
else:
    chunker = Chunker(chunker_config)
```

### Cost Consideration

Semantic chunking embeds every sentence for boundary detection, then `embed_book()` embeds every resulting chunk for vector search. This roughly doubles embedding API calls. For a typical book (~2000 sentences), the boundary detection step adds ~40 API calls (50 sentences/batch). This is acceptable for personal use with ~10 books but should be documented.

**Mitigation:** The boundary detection embeddings are throwaway (used only for similarity). They do NOT need to be stored. Only the final chunk embeddings go to ChromaDB.

---

## Feature 2: Context Enrichment (Chunk Expansion)

### Architecture Decision: Post-Search Expansion in SearchService

Context enrichment happens **after** search, not during indexing. When a search result is returned, the service fetches neighboring chunks using the existing `prev_chunk_id`/`next_chunk_id` links already stored in SQLite.

This is the correct layer because:
1. Expansion is a search-time concern, not a storage concern
2. The chunk links already exist -- no schema changes needed
3. Different searches may want different expansion windows
4. Expansion should not affect RRF scoring (only the matched chunk's position matters)

### Data Flow

```
SearchService.search(query, expand_context=1)
    |
    |- Execute normal search -> [result1, result2, ...]
    |
    |- For each result with expand_context > 0:
    |    |- ChunkRepository.get_neighbors(chunk_id, window=1)
    |    |    |- Follow prev_chunk_id chain (window times)
    |    |    |- Follow next_chunk_id chain (window times)
    |    |    |- Return [prev_chunk, matched_chunk, next_chunk]
    |    |
    |    |- Merge neighbor content into result
    |    |    |- result.context_before = prev_chunk.content
    |    |    |- result.context_after = next_chunk.content
    |
    v
[enriched_result1, enriched_result2, ...]
```

### SearchResult Model Change

```python
@dataclass
class SearchResult:
    chunk_id: str
    book_id: str
    book_title: str
    content: str
    content_type: str
    section_path: list[str]
    score: float
    source: Literal["semantic", "keyword", "both"]
    # NEW: context enrichment
    context_before: str | None = None  # Previous chunk(s) content
    context_after: str | None = None   # Next chunk(s) content
```

### ChunkRepository.get_neighbors()

New method that follows the linked list:

```python
def get_neighbors(self, chunk_id: str, window: int = 1) -> dict:
    """Get neighboring chunks by following prev/next links.

    Returns dict with keys: 'before' (list[Chunk]), 'after' (list[Chunk])
    """
    chunk = self.get(chunk_id)
    if chunk is None:
        return {"before": [], "after": []}

    before = []
    current = chunk
    for _ in range(window):
        if current.prev_chunk_id is None:
            break
        prev = self.get(current.prev_chunk_id)
        if prev is None:
            break
        before.insert(0, prev)
        current = prev

    after = []
    current = chunk
    for _ in range(window):
        if current.next_chunk_id is None:
            break
        nxt = self.get(current.next_chunk_id)
        if nxt is None:
            break
        after.append(nxt)
        current = nxt

    return {"before": before, "after": after}
```

**Performance note:** With `window=1` (default), this is 2 extra SQLite queries per result (get prev, get next). For `top_k=10`, that is 20 queries. SQLite handles this trivially. For larger windows, consider a batch query using `WHERE id IN (...)` but premature optimization for personal use.

### MCP Format

The MCP output should clearly delineate context from the matched chunk:

```
---
**Source:** Python Cookbook > Chapter 3 > Generators
**Book ID:** `a7f3b2` | **Type:** text | **Match:** both | **Score:** 0.032

[context] The previous section discussed list comprehensions and their memory implications...

[match] Generators provide a powerful mechanism for lazy evaluation. Unlike lists, generators
yield values one at a time, allowing you to process large datasets without loading everything
into memory...

[context] The next section covers generator expressions, which provide a more compact syntax...
---
```

---

## Feature 3: Metadata-Enriched Search

### Architecture Decision: Extend Existing Filter Interfaces

Both search backends (FTS5 and ChromaDB) already support filtering. The change is adding more filter dimensions to the existing interfaces.

### ChromaDB: Section Path Filter

ChromaDB metadata already stores `section_path` as a space-joined string (e.g., `"Part I > Chapter 3 > Generators"`). Adding a section path filter uses ChromaDB's `$contains` operator or exact match:

```python
# In VectorStore._build_where()
if section_path:
    # Match chunks whose section_path contains the filter string
    conditions.append({"section_path": {"$contains": section_path}})
```

**Important:** ChromaDB stores `section_path` as `" > ".join(chunk.section_path)` (see `ingest.py` line 82). Filtering by exact section requires knowing the exact string format. A `$contains` filter with just the section name (e.g., `"Generators"`) will match any chunk whose section path includes that word.

### FTS5: Section Path and Sequence Range

SQLite can filter on `section_path` (JSON column) and `sequence` (integer column):

```python
# In ChunkRepository.search_fts()
if section_path is not None:
    # section_path is stored as JSON array, use LIKE for substring match
    sql += " AND c.section_path LIKE ?"
    params.append(f"%{section_path}%")

if sequence_range is not None:
    sql += " AND c.sequence BETWEEN ? AND ?"
    params.extend([sequence_range[0], sequence_range[1]])
```

### SearchService: Unified Filter Passthrough

```python
def search(
    self,
    query: str,
    top_k: int = 10,
    book_id: str | None = None,
    content_type: str | None = None,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
    # NEW metadata filters
    section_path: str | None = None,
    sequence_range: tuple[int, int] | None = None,
    # NEW context enrichment
    expand_context: int = 0,
) -> list[SearchResult]:
```

### MCP Tool: New Parameters

```python
@mcp.tool(...)
def search_books(
    query: str,
    book_id: str | None = None,
    content_type: Literal["text", "code", "table", "diagram", "math"] | None = None,
    top_k: int = 10,
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
    # NEW
    section: str | None = None,       # Filter by section name (substring match)
    expand_context: int = 0,           # Number of neighbor chunks to include (0-3)
) -> str:
```

**Note:** `sequence_range` is deliberately NOT exposed in the MCP tool. It is an internal concept that Claude would not know how to use meaningfully. It exists at the `SearchService` level for programmatic use only.

---

## Feature 4: Quick Wins

### 4a: Cosine Distance Metric

**Problem:** ChromaDB collection `"mnemo"` was created with `{"hnsw:space": "l2"}`. The distance metric cannot be changed on an existing collection.

**Solution:** Migration path:

1. Add `distance_metric: str = "cosine"` to `VectorConfig`
2. Change `VectorStore.__init__()` to use `config.distance_metric`
3. Provide a migration utility that creates a new collection, copies data, swaps names
4. Document that existing users need to re-embed their books (or run migration)

**Migration utility** (new file `src/mnemo/vectors/migrate.py`):

```python
def migrate_to_cosine(chroma_path: Path | None = None) -> int:
    """Migrate the 'mnemo' collection from L2 to cosine distance.

    Creates 'mnemo_cosine' collection, copies all embeddings,
    deletes old collection, renames new one.

    Returns number of vectors migrated.
    """
```

**Why cosine over L2:** With L2-normalized embeddings (which the codebase already does), L2 and cosine are mathematically equivalent. However, switching to cosine means:
- We can remove the manual normalization step (ChromaDB handles it)
- Distance values are more interpretable (0 = identical, 2 = opposite)
- Consistent with how most embedding benchmarks report similarity

**Important nuance:** Since `VectorStore._normalize()` already L2-normalizes all embeddings, the actual search results will be identical with either metric. The benefit is primarily code simplification (removing normalization) and future-proofing.

### 4b: Expose Search Scores in MCP Results

The `SearchResult.score` field already exists and is populated. It is just not prominently displayed in the MCP output. The change is in `_format_search_results()`:

```python
# BEFORE
f"**Match:** {result.source}"

# AFTER
f"**Match:** {result.source} | **Score:** {result.score:.4f}"
```

This is a one-line change.

### 4c: Configurable Chunk Sizes Per Book

`ingest_book()` already accepts `chunker_config: ChunkerConfig | None`. The change is:

1. Pass chunk size parameters through the MCP `add_book` tool
2. Allow CLI to accept `--min-tokens` and `--max-tokens` flags

```python
# MCP tool change
@mcp.tool(...)
async def add_book(
    file_path: str,
    force: bool = False,
    min_tokens: int | None = None,   # NEW
    max_tokens: int | None = None,   # NEW
    ctx: Context = CurrentContext(),
) -> str:
```

The wiring in `_add_book_impl()`:

```python
config = ChunkerConfig(
    min_tokens=min_tokens or 400,
    max_tokens=max_tokens or 800,
)
book, chunk_count = ingest_book(path, chunker_config=config, force=force, embed=True)
```

---

## Data Flow: Complete v1.2 Pipeline

### Ingestion (with semantic chunking)

```
EPUB file
    |
    v
EPUBParser.parse() -> Book, ContentBlocks[]   [UNCHANGED]
    |
    v
Chunker.chunk(book_id, blocks)
    |
    |- For each ContentBlock:
    |    |- CODE/TABLE/DIAGRAM/MATH: _create_atomic_chunk()   [UNCHANGED]
    |    |- TEXT (semantic=False): _create_text_chunks() using split_by_tokens()   [UNCHANGED]
    |    |- TEXT (semantic=True): _create_semantic_chunks()   [NEW]
    |         |- SemanticBoundaryDetector.find_boundaries(text)
    |         |    |- Split into sentences
    |         |    |- Embed sentences (Databricks API)
    |         |    |- Compute consecutive cosine similarities
    |         |    |- Find boundaries at similarity drops
    |         |    |- Merge/split to respect token limits
    |         |- Create Chunk objects from boundary groups
    |
    |- _link_chunks()   [UNCHANGED]
    |
    v
BookRepository.add(book), ChunkRepository.add_many(chunks)   [UNCHANGED]
    |
    v
embed_book() -> DatabricksEmbedder + VectorStore   [UNCHANGED, except cosine metric]
```

### Search (with enrichment and metadata filters)

```
search_books(query, section="Generators", expand_context=1)
    |
    v
SearchService.search(query, section_path="Generators", expand_context=1)
    |
    |- _hybrid_search(query, ..., section_path="Generators")
    |    |- FTS5: search_fts(query, section_path="Generators")   [NEW FILTER]
    |    |- ChromaDB: query(embedding, section_path="Generators")   [NEW FILTER]
    |    |- RRF fusion   [UNCHANGED]
    |
    |- For each result (if expand_context > 0):   [NEW]
    |    |- ChunkRepository.get_neighbors(chunk_id, window=1)
    |    |- Attach context_before, context_after to SearchResult
    |
    v
[SearchResult(content=..., score=0.032, context_before=..., context_after=...)]
    |
    v
_format_search_results() -> Markdown with score and context   [MODIFIED]
```

---

## Suggested Build Order

The build order follows dependency chains and maximizes independent testability.

### Phase 1: Quick Wins (no dependencies between them, all independently testable)

1. **Expose search scores** -- one-line change in `_format_search_results()`, test with existing search tests
2. **Configurable chunk sizes** -- add params to `add_book` MCP tool, pass through to `ingest_book()`, test with different configs
3. **Cosine distance migration** -- new `VectorConfig.distance_metric`, migration utility, update `VectorStore.__init__()`. Requires re-embedding test books.

**Rationale:** Quick wins build confidence, deliver value immediately, and exercise the test infrastructure for later phases.

### Phase 2: Metadata-Enriched Search (depends on nothing new)

1. **Section path filter** -- extend `VectorStore._build_where()` and `ChunkRepository.search_fts()`
2. **SearchService filter passthrough** -- add params to `SearchService.search()`
3. **MCP tool params** -- add `section` parameter to `search_books`
4. **Tests** -- search within specific sections, verify filtering works for both backends

**Rationale:** Pure additive filter logic. No new components, no data model changes. Each layer can be tested independently bottom-up.

### Phase 3: Context Enrichment (depends on ChunkRepository extension)

1. **ChunkRepository.get_neighbors()** -- new method, test with linked chunk fixtures
2. **SearchResult model extension** -- add `context_before`, `context_after` fields
3. **SearchService expansion logic** -- post-search neighbor fetching
4. **MCP tool param** -- add `expand_context` to `search_books`
5. **MCP output formatting** -- `[context]`/`[match]` markers

**Rationale:** Depends on Phase 2 being done (the `expand_context` param lives alongside `section` in the MCP tool). The chain is `repository -> model -> service -> tool`.

### Phase 4: Semantic Chunking (depends on embedding client access pattern)

1. **SemanticBoundaryDetector** -- new module in `src/mnemo/chunking/semantic.py`, fully unit-testable with mock embed function
2. **ChunkerConfig extension** -- add `semantic` flag, `similarity_threshold`
3. **Chunker integration** -- accept optional detector, route text blocks through it
4. **ingest_book() wiring** -- create detector when `semantic=True`, pass to Chunker
5. **Tests** -- verify boundary detection, compare semantic vs. token-based chunks on real content

**Rationale:** This is the most complex feature and benefits from all quick wins being shipped first. Specifically, the cosine distance change should ship before semantic chunking so new books ingested with semantic chunking use cosine from the start.

---

## Patterns to Follow

### Pattern: Function Injection for Embedding Access

The semantic chunker should not import or instantiate `DatabricksEmbedder` directly. Instead, accept an embedding function:

```python
class SemanticBoundaryDetector:
    def __init__(self, embed_fn: Callable[[list[str]], list[list[float]]], ...):
        self.embed_fn = embed_fn
```

**Why:** Testability (mock the embedding function), decoupling (chunking module does not depend on embedding module), and flexibility (could use a different embedder in the future).

### Pattern: Graceful Degradation for Semantic Chunking

If semantic chunking fails (embedding API unavailable, rate limited), fall back to token-based splitting. Do not fail the entire ingestion:

```python
def _create_semantic_chunks(self, book_id, block, start_sequence):
    try:
        boundaries = self.boundary_detector.find_boundaries(
            block.content, self.config.min_tokens, self.config.max_tokens
        )
    except Exception as e:
        logger.warning(f"Semantic chunking failed, falling back to token split: {e}")
        return self._create_text_chunks(book_id, block, start_sequence)
    ...
```

### Pattern: Additive Parameters with Backward-Compatible Defaults

All new parameters default to the current behavior:
- `expand_context=0` -- no expansion (current behavior)
- `section_path=None` -- no filtering (current behavior)
- `semantic=False` -- token-based chunking (current behavior)
- `distance_metric="l2"` -- existing behavior until migration

This ensures zero breaking changes for existing users and tests.

---

## Anti-Patterns to Avoid

### Anti-Pattern: Storing Expanded Context in the Index

**What:** Pre-computing neighbor context and storing it in ChromaDB or SQLite during ingestion
**Why bad:** Doubles storage size, makes chunk boundaries rigid, context window can't be adjusted at search time
**Instead:** Expand at search time using the existing prev/next links

### Anti-Pattern: Re-Embedding Sentences for Every Search

**What:** Using the semantic boundary detection approach at search time (embed the query, then compare to sentence-level embeddings)
**Why bad:** Sentence-level embeddings are only useful for chunking boundaries. Search should use chunk-level embeddings (the full chunk, not individual sentences)
**Instead:** Semantic chunking is an ingestion-time operation only. Search uses chunk embeddings as today.

### Anti-Pattern: Complex Section Path Parsing in ChromaDB

**What:** Storing section_path as a structured object in ChromaDB metadata and building complex `$and` queries
**Why bad:** ChromaDB metadata filtering is limited (no JSON path queries, no array operations). The section_path is stored as a flat string.
**Instead:** Use simple `$contains` string matching. For complex section queries, filter in SQLite where JSON functions are available.

### Anti-Pattern: Making Semantic Chunking the Default

**What:** Changing `ChunkerConfig.semantic` to `True` by default
**Why bad:** Doubles embedding API costs, adds ingestion latency, may not improve retrieval for all book types (e.g., reference manuals with short, independent sections)
**Instead:** Default to `False`. Let users opt in per book via `add_book(semantic=True)`.

---

## Scalability Considerations

| Concern | Current (~10 books) | At 100 books | Mitigation |
|---------|-------------------|--------------|------------|
| Semantic chunking cost | ~40 extra API calls/book | ~4000 total API calls to re-ingest | Opt-in per book, not retroactive |
| Context expansion queries | 20 SQLite queries/search | Same (per-search, not per-book) | Batch `get_neighbors()` if needed |
| Section filter performance | Negligible | SQLite index on section_path | Add `CREATE INDEX idx_chunks_section ON chunks(section_path)` if slow |
| Cosine migration | Re-embed ~5000 chunks | Re-embed ~50000 chunks | Batch migration utility, run once |

---

## Sources

- Existing codebase: all source files examined as listed in the component maps above
- [Semantic Chunking with Embedding Distance](https://superlinked.com/vectorhub/articles/semantic-chunking) -- boundary detection algorithm (HIGH confidence)
- [Best Chunking Strategies for RAG 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) -- trade-off analysis (MEDIUM confidence)
- [Max-Min Semantic Chunking](https://milvus.io/blog/embedding-first-chunking-second-smarter-rag-retrieval-with-max-min-semantic-chunking.md) -- alternative approach considered (MEDIUM confidence)
- [ChromaDB Collections - Distance Metrics](https://docs.trychroma.com/docs/collections/configure) -- cosine metric configuration (HIGH confidence)
- [ChromaDB FAQ - Changing Distance Metric](https://cookbook.chromadb.dev/faq/) -- migration requirement confirmed (HIGH confidence)
- [ChromaDB L2 vs Cosine Analysis](https://razikus.substack.com/p/chromadb-defaults-to-l2-distance-why-that-might-not-be-the-best-choice-ac3d47461245) -- rationale for cosine switch (MEDIUM confidence)
