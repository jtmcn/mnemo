# Feature Landscape: v1.2 RAG Improvements

**Domain:** Advanced RAG techniques for technical book search
**Milestone:** v1.2 RAG Improvements (subsequent milestone; chunking, search, and MCP tools already exist)
**Researched:** 2026-03-08
**Confidence:** MEDIUM-HIGH

---

## Context

Mnemo has a working hybrid search pipeline: fixed-token chunking (400-800 tokens), FTS5 keyword search, ChromaDB semantic search with L2 distance on L2-normalized GTE-large-en embeddings, and RRF fusion. This milestone improves search quality through better chunking, richer search results, and structural navigation.

Existing infrastructure that these features build on:
- `Chunker` with `ChunkerConfig(min_tokens, max_tokens, overlap_tokens)` and atomic CODE/TABLE/DIAGRAM/MATH handling
- `prev_chunk_id`/`next_chunk_id` linking between adjacent chunks
- `section_path` stored in both SQLite (JSON array) and ChromaDB metadata (joined string)
- `sequence` field indexed per book (`idx_chunks_sequence`)
- `VectorStore._normalize()` that L2-normalizes all embeddings before storage
- `SearchResult` with `score` field (RRF score, already computed but not prominently displayed)

---

## Table Stakes

Features that move search quality from "functional" to "good." Without these, users hit basic limitations quickly.

### 1. Context Enrichment via Chunk Expansion

**Description:** When a search returns a matched chunk, also fetch the N surrounding chunks (before and after) to provide reading context. A code block without the explanation before it, or a concept without the example after it, gives incomplete answers.

**How it works:**
1. User searches, gets back N result chunks as today
2. For each result chunk, follow `prev_chunk_id` links backward `window` times and `next_chunk_id` links forward `window` times
3. Collect all chunks in the window, ordered by sequence
4. Return the matched chunk with surrounding chunks clearly delimited (e.g., `[context before]` / `[matched]` / `[context after]`)
5. Deduplicate: if two matched chunks have overlapping windows, merge into one context block

**Complexity:** Low
- Uses existing `prev_chunk_id`/`next_chunk_id` links -- no schema changes
- Requires `ChunkRepository.get()` calls to fetch neighbors (already exists)
- Add `context_window` parameter to `search_books` MCP tool (default 1)

**Dependencies on existing:** `prev_chunk_id`/`next_chunk_id` fields on Chunk model, `ChunkRepository.get()`.

**Implementation notes:**
- Default window of 1 (one chunk before, one chunk after) triples the context per result
- Window of 0 preserves current behavior (backward compatible)
- Alternative to linked-list traversal: query by `book_id` + `sequence BETWEEN (seq-window) AND (seq+window)` which is faster (indexed) and avoids N+1 queries
- Cap total expanded token count to prevent massive responses (e.g., max 3000 tokens per expanded result)

**Confidence:** HIGH -- standard RAG pattern, well-documented in [NirDiamant RAG_Techniques](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/context_enrichment_window_around_chunk.ipynb) and [Microsoft Azure RAG guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-enrichment-phase)

---

### 2. Expose Search Relevance Scores

**Description:** The RRF score is already computed and stored in `SearchResult.score`, but the formatted output only shows `Match: semantic/keyword/both`. Exposing the numeric score lets Claude judge confidence and decide whether to search again with different terms.

**How it works:**
- In `_format_search_results`, add the score to the output line: `**Score:** 0.032 | **Match:** both`
- For semantic-only mode, also show the raw ChromaDB distance (currently discarded)
- Normalize scores to be interpretable: RRF scores are tiny (0.016-0.033 range), so either show as-is with explanation or normalize to 0-100 scale

**Complexity:** Low
- One-line change to `_format_search_results` formatting string
- Optionally add raw distance to `SearchResult` model (new field `distance: float | None`)

**Dependencies on existing:** `SearchResult.score` (already populated), `_format_search_results` in `tools.py`.

**Confidence:** HIGH

---

### 3. Switch ChromaDB to Cosine Distance

**Description:** Current collection uses `l2` (L2/Euclidean) distance. Since all embeddings are already L2-normalized before storage, L2 distance and cosine distance produce identical ranking. The difference is score readability: cosine distance ranges 0-1 (0 = identical, 1 = orthogonal), while L2 on normalized vectors ranges 0-2 and is harder to interpret.

**How it works:**
- ChromaDB does not allow changing the distance metric on an existing collection
- Migration required: create new collection with `{"hnsw": {"space": "cosine"}}`, copy all data from old collection, delete old collection
- Write a one-time migration script (CLI command or standalone script)
- Update `VectorStore.__init__` to use `cosine` for new collections

**Complexity:** Low
- Migration script is ~30 lines: batch-read from old collection, batch-write to new
- No re-embedding needed (same vectors, different distance function)
- Risk: data loss if migration is interrupted mid-transfer

**Dependencies on existing:** `VectorStore`, `VectorConfig`.

**Implementation notes:**
- Safe migration approach: create `mnemo_cosine` collection, migrate data, verify counts match, update `VectorConfig.collection_name` to `mnemo_cosine`, then delete old `mnemo` collection
- ChromaDB does not support collection renaming, so either keep new name or delete-then-recreate
- Since retrieval ranking is unchanged (math is equivalent for normalized vectors), this is zero-risk to search quality

**Confidence:** HIGH -- verified in [ChromaDB docs](https://docs.trychroma.com/docs/collections/configure) and [ChromaDB FAQ](https://cookbook.chromadb.dev/faq/)

---

## Differentiators

Features that meaningfully improve search quality beyond baseline. Not strictly required but provide significant value.

### 4. Semantic Chunking for Text Blocks

**Description:** Replace fixed-token splitting for TEXT blocks with embedding-distance-based boundary detection. Instead of splitting every 400-800 tokens at sentence boundaries, embed each sentence and split where topics shift (detected by high cosine distance between consecutive sentence embeddings).

**How it works:**
1. Split text block into sentences (regex or `nltk.sent_tokenize`)
2. Embed each sentence via `DatabricksEmbedder.embed_batch()`
3. Compute cosine distance between consecutive sentence pairs: `dist[i] = 1 - cosine_sim(emb[i], emb[i+1])`
4. Identify boundary points where distance exceeds threshold (95th percentile of all distances in the document, or tunable absolute threshold)
5. Group sentences between boundaries into chunks
6. Merge chunks below `min_tokens` with nearest neighbor
7. Split chunks exceeding `max_tokens` using existing sentence-boundary splitting as fallback

**Complexity:** Medium-High
- Requires embedding every sentence during ingest (extra API calls and latency)
- For a 500-chunk book with ~10 sentences per chunk: ~5,000 sentence embeddings
- At Databricks batch API pricing: adds ~20-30 seconds to ingest
- Must handle edge cases: very short sentences, single-sentence paragraphs, sentences that are actually code inline
- Existing books need re-ingestion + re-embedding to benefit

**Dependencies on existing:** `Chunker._create_text_chunks()` (replacement target), `ChunkerConfig` (min/max bounds still apply), `DatabricksEmbedder.embed_batch()`.

**Implementation notes:**
- Atomic types (CODE, TABLE, DIAGRAM, MATH) remain unchanged -- semantic chunking only applies to TEXT blocks
- The threshold is the critical tuning parameter. Too low = too many small chunks (benchmarks show semantic chunking averaged 43 tokens per chunk and scored 54% accuracy vs recursive at 69%). The min_tokens guard is essential.
- Consider a configurable flag: `semantic_chunking: bool = False` on `ChunkerConfig`, defaulting off so existing behavior is preserved
- Store chunking method in book metadata for traceability

**Confidence:** MEDIUM -- benchmarks show mixed results. [Firecrawl 2026 benchmark](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) placed recursive splitting first at 69%, semantic chunking at 54%. However, a [clinical study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12649634/) found topic-aligned chunking hit 87% vs 13% for fixed-size. The difference is likely the min/max token guardrails preventing fragment generation. With proper bounds, semantic chunking should outperform fixed, but empirical tuning is needed.

---

### 5. Metadata-Enriched Search: Section Path Filtering

**Description:** Add section path filtering to `search_books` so users can say "search chapter 3" or "search the generators section." Currently, the only filters are `book_id` and `content_type`.

**How it works:**
- Add `section` parameter to `search_books` MCP tool
- For SQLite/FTS5 search: add `WHERE section_path LIKE '%Chapter 3%'` or use `json_each()` for exact matching
- For ChromaDB search: use `where` clause with `$contains` on the `section_path` metadata field (stored as `"Part I > Chapter 3 > Generators"`)
- Support partial matching: "Chapter 3" matches any chunk whose section_path contains "Chapter 3"

**Complexity:** Medium
- SQLite side: straightforward LIKE or json_each query on existing indexed data
- ChromaDB side: `$contains` operator on string metadata works for substring matching
- The tricky part is UI/UX: what does the user type? Full path? Partial? Regex? Keep it simple -- substring match.

**Dependencies on existing:** `section_path` stored in both SQLite (JSON array) and ChromaDB metadata (joined string). `SearchFilter` model, `SearchService.search()`, `VectorStore.query()`.

**Implementation notes:**
- Extend `SearchFilter` with `section: str | None`
- Add `section` parameter to `search_books` MCP tool
- For ChromaDB: `where={"section_path": {"$contains": section_value}}`
- For FTS5: add `AND c.section_path LIKE ?` with `%{section_value}%`

**Confidence:** HIGH -- uses existing stored data, standard query patterns

---

### 6. Metadata-Enriched Search: Sequence Range Fetching

**Description:** After finding a relevant chunk, allow fetching a contiguous range of chunks by sequence number. "Give me chunks 15-25 from this book" enables reading flow beyond the context window.

**How it works:**
- New MCP tool `get_book_chunks(book_id, start_sequence, end_sequence)` or add parameters to `search_books`
- SQL: `SELECT * FROM chunks WHERE book_id = ? AND sequence BETWEEN ? AND ? ORDER BY sequence`
- Return chunks in sequence order with content and metadata

**Complexity:** Low-Medium
- SQL query is trivial (index exists: `idx_chunks_sequence`)
- Decision: new tool vs parameter on existing tool
- New tool is cleaner: `search_books` finds, `get_book_chunks` reads

**Dependencies on existing:** `chunks.sequence` field, `idx_chunks_sequence` index, `ChunkRepository`.

**Implementation notes:**
- Recommend a new MCP tool rather than overloading `search_books`
- Cap range to prevent massive responses (e.g., max 20 chunks per request)
- Include section_path in output so Claude knows what section the chunks belong to
- Mark as `readOnlyHint=True`

**Confidence:** HIGH

---

### 7. Configurable Chunk Sizes per Book

**Description:** Allow specifying min/max token sizes when adding a book via MCP. Dense mathematical books benefit from smaller chunks (200-400 tokens); narrative books work better with larger chunks (600-1000 tokens).

**How it works:**
- Add optional `chunk_min_tokens` and `chunk_max_tokens` parameters to `add_book` MCP tool
- Pass through to `ChunkerConfig` during `ingest_book()`
- Defaults remain 400/800 if not specified

**Complexity:** Low
- `ChunkerConfig` already supports these parameters
- `ingest_book()` already accepts `chunker_config`
- Only need to wire MCP tool parameters through to the pipeline

**Dependencies on existing:** `ChunkerConfig`, `ingest_book(chunker_config=...)`, `add_book` MCP tool.

**Implementation notes:**
- Validate: `min_tokens >= 100`, `max_tokens <= 2000`, `min_tokens < max_tokens`
- Book must be re-ingested (with `force=true`) to change chunk sizes
- Consider storing the chunk config used in book metadata for reproducibility (optional, not required)

**Confidence:** HIGH

---

## Anti-Features

Features to explicitly NOT build in v1.2.

### LLM-Based Chunking

**Why avoid:** Using GPT/Claude to decide chunk boundaries is expensive per chunk (~$0.01-0.05 per chunk at scale), slow (adds seconds per chunk), non-deterministic, and overkill for ~10 books. Semantic chunking via embeddings achieves 80% of the benefit at 10% of the cost.

**What to do instead:** Embedding-distance semantic chunking with min/max token guardrails.

---

### Agentic/Multi-Hop Retrieval

**Why avoid:** Adds tool-chaining complexity (planning loops, state management) for marginal gain. Claude itself already performs multi-turn search naturally -- it calls `search_books` multiple times with refined queries.

**What to do instead:** Keep `search_books` as a single-shot tool. Let Claude handle multi-step reasoning.

---

### Parent-Child Chunk Hierarchy / Auto-Merging

**Why avoid:** Requires tree structure in storage, complex merge logic, and careful handling of cross-level navigation. Context enrichment via neighbor expansion achieves the same goal (providing surrounding context) with far less complexity.

**What to do instead:** Context enrichment with configurable window size.

---

### Chunk-Level Summaries/Keywords in Metadata

**Why avoid:** Requires LLM call per chunk during ingest, dramatically increasing ingest cost and time. The embedding itself captures semantic meaning; adding a summary is redundant for retrieval.

**What to do instead:** Rely on embeddings for semantic matching and `section_path` for structural context.

---

### Cross-Encoder Re-Ranking

**Why avoid:** Adds a heavy model dependency and inference cost per query. RRF fusion of keyword + semantic search is already a strong ranking baseline. At ~10 books, the improvement is marginal.

**What to do instead:** Keep RRF fusion. Revisit only if search quality is measurably poor after v1.2.

---

### Automatic Re-Chunking on Strategy Change

**Why avoid:** Silently re-ingesting books when chunking config changes is destructive, slow (requires re-embedding), and confusing. Users should make this decision explicitly.

**What to do instead:** Document: "Re-add with `force=true` to apply new chunking strategy."

---

## Feature Dependencies

```
Independent quick wins (do first):
  Cosine distance migration ──> Score exposure (benefits from 0-1 cosine distances)

Independent medium features (do in parallel):
  Context enrichment (uses existing prev/next links)
  Section path filtering (extends search params)
  Configurable chunk sizes (extends add_book params)
  Sequence range fetching (new tool or param)

Depends on quick wins + medium features:
  Semantic chunking (most complex; benefits from configurable chunk sizes
                     existing first as min/max guardrails; requires re-ingest)
```

**Critical ordering insight:** Semantic chunking should be implemented last because:
1. It is the most complex feature with the most risk
2. Existing books must be re-ingested + re-embedded to benefit
3. Configurable chunk sizes should exist first so min/max bounds are tunable
4. Cosine distance should be migrated first so the embedding comparison during chunking uses the right metric
5. All other features work with both old (fixed) and new (semantic) chunks

---

## MVP Recommendation

### Must Have (ordered by implementation sequence):

1. **Cosine distance migration** -- One-time script, improves score interpretability, no behavioral change. Unblocks meaningful score display.
2. **Search scores exposure** -- Tiny change to formatting, lets Claude judge result confidence.
3. **Context enrichment** -- Highest-value single feature. Transforms isolated chunks into readable passages.
4. **Configurable chunk sizes** -- Small API change, prepares infrastructure for semantic chunking.

### Should Have:

5. **Section path filtering** -- Enables structural navigation, medium effort.
6. **Sequence range fetching** -- Companion to context enrichment for deeper reading.
7. **Semantic chunking** -- Highest complexity, highest potential upside, but existing fixed chunking is functional. Needs empirical tuning.

### Explicitly Defer:

- Cross-encoder re-ranking
- LLM-based chunking
- Chunk metadata enrichment (summaries, keywords)
- Parent-child hierarchy

---

## Sources

### Semantic Chunking
- [Firecrawl: Best Chunking Strategies for RAG 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) -- Benchmarks: recursive 69% vs semantic 54%
- [Milvus: Max-Min Semantic Chunking](https://milvus.io/blog/embedding-first-chunking-second-smarter-rag-retrieval-with-max-min-semantic-chunking.md) -- Advanced boundary detection algorithm
- [Superlinked VectorHub: Semantic Chunking](https://superlinked.com/vectorhub/articles/semantic-chunking) -- Algorithm walkthrough and tradeoffs
- [Clinical Decision Support Chunking Study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12649634/) -- Topic-aligned at 87% vs fixed at 13%

### Context Enrichment
- [NirDiamant RAG_Techniques: Context Enrichment Window](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/context_enrichment_window_around_chunk.ipynb) -- Reference implementation
- [Microsoft Azure RAG Enrichment Phase](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-enrichment-phase) -- Enterprise patterns
- [PIXION: RAG Context Enrichment Strategies](https://pixion.co/blog/rag-strategies-context-enrichment) -- Sentence window vs auto-merging comparison

### ChromaDB Distance Metrics
- [ChromaDB Collection Configuration Docs](https://docs.trychroma.com/docs/collections/configure) -- Distance metric options, cosine setup
- [ChromaDB FAQ/Cookbook](https://cookbook.chromadb.dev/faq/) -- Migration approach for changing metrics
- [LangChain Discussion: Changing ChromaDB Distance](https://github.com/langchain-ai/langchain/discussions/22422) -- Confirms migration-only approach
