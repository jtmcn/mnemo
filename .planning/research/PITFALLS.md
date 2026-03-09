# Pitfalls: RAG Improvements for Mnemo v1.2

**Domain:** Adding semantic chunking, context enrichment, metadata search, and distance metric changes to an existing RAG system
**Researched:** 2026-03-09
**Confidence:** HIGH (based on codebase analysis, ChromaDB documentation, and RAG literature)

---

## Critical Pitfalls

Mistakes that cause data loss, require full re-ingestion, or silently degrade search quality.

---

### 1. ChromaDB Silently Ignores Distance Metric Changes on Existing Collections

**What goes wrong:**
The current `VectorStore.__init__` calls `get_or_create_collection(name="mnemo", metadata={"hnsw:space": "l2"})`. If you change this to `{"hnsw:space": "cosine"}` and deploy, ChromaDB silently returns the existing L2 collection unchanged. The code runs without error, but all queries still use L2 distance. You think you switched to cosine, but nothing changed.

**Why it happens:**
ChromaDB's HNSW space parameter is immutable after collection creation. `get_or_create_collection` with a different space parameter does not error -- it just returns the existing collection with its original configuration. This is [documented behavior](https://cookbook.chromadb.dev/core/collections/) but easy to miss.

**How to avoid:**
You must delete and recreate the collection, or clone to a new collection name. For mnemo with ~9500 chunks across 7 books, the safest approach is:

1. Delete the old collection: `client.delete_collection("mnemo")`
2. Create new collection with cosine: `client.create_collection("mnemo", metadata={"hnsw:space": "cosine"})`
3. Re-embed all books (vectors must be re-added; you cannot copy L2-normalized vectors to cosine without consideration)

The key subtlety: mnemo currently L2-normalizes vectors before storage (see `VectorStore._normalize()`). With L2-normalized vectors, L2 distance and cosine distance produce the same ranking order. So switching to cosine distance is mathematically equivalent IF you keep the normalization. But if you also remove the manual normalization (since cosine distance normalizes internally), you must re-embed from scratch because the stored vectors are already normalized.

**Warning signs:**
- Distance values from queries don't change after "switching" to cosine
- `collection.metadata` still shows `{"hnsw:space": "l2"}` after the change
- Tests pass because they create fresh collections each time

**Phase to address:**
Quick wins phase. Must be an explicit migration step, not just a config change. Provide a CLI command or script that handles the recreation.

---

### 2. Semantic Chunking Produces Tiny Fragments That Destroy Retrieval Quality

**What goes wrong:**
Semantic chunking using embedding-distance boundary detection splits text whenever consecutive sentence embeddings diverge beyond a threshold. For technical books with frequent topic shifts (definition, example, explanation, caveat), this produces fragments averaging 30-50 tokens. These tiny chunks embed poorly -- they lack enough context for the embedding model to capture meaning -- and flood search results with near-meaningless snippets.

A [2025 benchmark](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide) found semantic chunking at 54% accuracy vs. recursive 512-token splitting at 69%, specifically because of fragment size issues. A [NAACL 2025 paper](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) found that fixed 200-word chunks matched or beat semantic chunking across retrieval and answer generation tasks.

**Why it happens:**
Technical prose has high local variation -- a sentence about a concept, then a code reference, then a caveat, then back to explanation. Embedding distance between these adjacent sentences is high even though they belong to the same topic. The threshold treats every stylistic shift as a semantic boundary.

**How to avoid:**
- Set minimum chunk size to 200 tokens (mnemo's current `min_tokens=400` is a good floor). After semantic boundary detection, merge consecutive below-minimum chunks
- Use the 90th-95th percentile of inter-sentence distances as the threshold, not a fixed value. Compute this per-document, not globally
- Keep semantic chunking as an OPTION alongside the existing fixed-token chunker, not a replacement. Some books may chunk better with fixed-token
- Test with actual mnemo books before committing: compare retrieval quality of semantic vs. fixed-token on known queries

**Warning signs:**
- Average chunk token count drops below 100 after switching to semantic chunking
- Search results return many small fragments instead of coherent passages
- Users get worse answers from Claude after the change (the most important signal)

**Phase to address:**
Semantic chunking phase. Must include a minimum chunk size floor and a fallback to fixed-token chunking. Do not make semantic chunking the only option.

---

### 3. Context Enrichment Blows Up MCP Response Size and Degrades LLM Answers

**What goes wrong:**
Context enrichment expands each search result with adjacent chunks (prev/next via `prev_chunk_id`/`next_chunk_id`). With a window of 1 (default), each result triples in size. With `top_k=10` results, you go from ~8,000 tokens to ~24,000 tokens in the MCP response. Claude's context window can handle it, but the "lost in the middle" effect means relevant information buried in expanded context gets ignored. Worse, the expanded chunks may contain irrelevant content from neighboring topics, actively confusing the LLM.

**Why it happens:**
The intuition "more context = better answers" is wrong past a threshold. [Research shows](https://www.anthropic.com/news/contextual-retrieval) that retrieval performance degrades as context length increases, even for straightforward tasks. The model's attention gets diluted across the expanded text.

**How to avoid:**
- Default window to 1 (one chunk before + one chunk after), not higher
- Only expand in the SAME section -- do not cross `section_path` boundaries. If the prev chunk has a different `section_path[-1]`, do not include it
- Mark the original match vs. context chunks in the response so Claude knows which part actually matched the query
- Reduce `top_k` when context enrichment is enabled (e.g., `top_k=5` with expansion instead of `top_k=10` without)
- Make enrichment opt-in per search call, not always-on

**Warning signs:**
- MCP response payloads grow beyond 30KB
- Claude's answers reference information from adjacent chunks that is irrelevant to the question
- Search latency increases noticeably (each result requires 2 additional SQLite lookups)

**Phase to address:**
Context enrichment phase. Design the expansion to be configurable and section-aware from day one.

---

### 4. Re-ingestion Required But No Migration Path Provided

**What goes wrong:**
Both semantic chunking and distance metric changes require re-ingesting existing books. Without a clear migration path, users must manually `remove_book` and `add_book` for all 7 books, losing any customization. If the ingest pipeline changes (new chunk IDs, different chunking), the ChromaDB vectors become orphaned from SQLite chunks. The system enters an inconsistent state where vector IDs point to non-existent chunks.

**Why it happens:**
The current `ingest_book(force=True)` handles re-ingestion for a single book, but there is no batch re-ingestion command. The current `embed_book()` deletes existing vectors before re-embedding (line 69 of `ingest.py`), but only for one book at a time. There is no "re-chunk and re-embed everything" command.

**How to avoid:**
- Add a `reindex_all` CLI command that iterates all books and re-ingests with `force=True`
- The command must handle the ChromaDB collection recreation (delete old, create with new distance metric)
- Include a `--dry-run` flag that reports what would change without modifying data
- Consider storing the original EPUB path in the books table so re-ingestion can find the source file. Currently, the EPUB path is not persisted anywhere after initial ingest

**Warning signs:**
- Users upgrade mnemo but their existing books return poor search results
- ChromaDB has vectors for chunk IDs that no longer exist in SQLite
- `search_books` returns "chunk not found in SQLite" warnings (see `service.py` line 189)

**Phase to address:**
Must be addressed BEFORE shipping any chunking or distance metric changes. Either as a prerequisite or as part of the quick wins phase. Without a migration path, all other improvements are inaccessible to existing users.

---

## Moderate Pitfalls

---

### 5. Semantic Chunking Requires Extra Embedding API Calls at Ingest Time

**What goes wrong:**
Semantic chunking needs to embed every sentence to compute inter-sentence distances for boundary detection. A 500-chunk book might have 3,000-5,000 sentences. At Databricks API rates, this means 60-100 extra batch calls just for chunking, before the actual chunk embedding. Ingest time could go from 2 minutes to 10+ minutes, and API costs increase proportionally.

**Why it happens:**
The boundary detection algorithm requires pairwise sentence embedding comparisons. This is fundamentally more expensive than fixed-token chunking, which needs zero API calls.

**How to avoid:**
- Use a small, fast local model for boundary detection (e.g., sentence-transformers `all-MiniLM-L6-v2` via `sentence-transformers` library). The boundary detection embeddings do not need to match the storage embeddings -- they just need to capture relative similarity
- Alternatively, batch sentence embeddings aggressively (Databricks supports up to batch size of several hundred)
- Cache sentence embeddings so re-chunking with different thresholds does not require re-embedding
- Document the ingest time increase so users are not surprised

**Warning signs:**
- `add_book` timeout increases from ~2 minutes to 10+ minutes
- Databricks API costs increase significantly after deploying semantic chunking
- MCP `add_book` hits the 300-second timeout (`asyncio.wait_for` in the MCP tool layer)

**Phase to address:**
Semantic chunking phase. Decide on local vs. API embedding for boundary detection before implementation.

---

### 6. Section Path Filtering Does Not Work With ChromaDB Substring Matching

**What goes wrong:**
The current `section_path` is stored as a joined string in ChromaDB metadata: `"Part I > Chapter 3 > Async Generators"`. Filtering by section path requires substring or prefix matching, but ChromaDB's `where` clause only supports exact equality, `$in`, `$ne`, and comparison operators. There is no `$contains` or `$like` operator for string metadata. A filter like `{"section_path": {"$contains": "Chapter 3"}}` will silently fail or error.

**Why it happens:**
Developers assume ChromaDB metadata filtering works like SQL `LIKE` clauses. It does not. ChromaDB metadata is designed for exact match and numeric range queries.

**How to avoid:**
- Store section_path components as separate metadata fields: `section_level_0: "Part I"`, `section_level_1: "Chapter 3"`, etc. This enables exact match at each level
- Alternatively, do section filtering in SQLite (which has full SQL capabilities) and use the resulting chunk IDs to filter ChromaDB results. This leverages the existing dual-storage architecture
- The hybrid search pipeline already loads chunks from SQLite -- add section filtering there, not in ChromaDB
- Do NOT try to filter by section_path directly in ChromaDB metadata

**Warning signs:**
- Section path filter returns zero results even when matching chunks exist
- ChromaDB raises an error about unsupported `where` operators
- Filter works in tests with exact section paths but fails with partial paths

**Phase to address:**
Metadata search phase. Design the filtering to happen in the SQLite layer, using the existing `idx_chunks_sequence` index and `section_path` JSON column.

---

### 7. Exposing Raw Distance Scores Confuses Claude and Users

**What goes wrong:**
The current system uses RRF scores (higher = more relevant). If you expose raw ChromaDB distances alongside RRF scores, the semantics are inverted: lower distance = more similar. Mixing these in MCP results confuses Claude. It might say "this result has a high score of 0.85" when 0.85 is actually a poor distance score (far from the query).

Additionally, L2 distances and cosine distances have completely different scales. L2 distances for normalized vectors range from 0 to 4. Cosine distances range from 0 to 2. If you switch distance metrics, any thresholds or interpretations based on the old scale become meaningless.

**Why it happens:**
Developers want to expose "relevance scores" for transparency, but raw distance values are not user-interpretable without normalization and context.

**How to avoid:**
- Convert distances to a 0-1 similarity score before exposing. For cosine distance: `similarity = 1 - (distance / 2)`. For L2 with normalized vectors: `similarity = 1 - (distance / 4)`
- Label the field as `relevance_score` not `distance` or `raw_score`
- Include a text interpretation: "highly relevant" (>0.8), "relevant" (0.5-0.8), "somewhat relevant" (<0.5)
- Keep the existing RRF score for result ordering; add the similarity score as supplementary information

**Warning signs:**
- Claude misinterprets distance values as relevance scores
- Users see different score scales before and after the cosine migration
- Thresholds that worked with L2 fail with cosine

**Phase to address:**
Quick wins phase (expose search scores). Must normalize before exposing, not after.

---

### 8. Configurable Chunk Sizes Without Re-indexing Leads to Mixed Collections

**What goes wrong:**
Adding configurable chunk sizes per book at ingest time means different books have different chunk sizes. The embedding model may behave differently with 200-token chunks vs. 800-token chunks -- shorter chunks have less context and embed differently. When searching across books, results from differently-sized chunks are not directly comparable. A short chunk from one book might score higher than a longer, more relevant chunk from another book simply because short text has sharper (less diluted) embeddings.

**Why it happens:**
The intuition "let users pick the right size for each book" ignores the interaction between chunk size and embedding quality. Embedding models have a sweet spot -- too short and the embedding lacks context, too long and the meaning is diluted.

**How to avoid:**
- Provide sensible defaults (keep current 400-800 token range) and only allow deviation within a reasonable band (200-1200 tokens)
- Document that changing chunk size for one book requires re-embedding that book
- Store the chunk configuration used for each book (in the books table or metadata) so it is clear what settings were used
- Do NOT allow mix-and-match without warning users about comparability

**Warning signs:**
- Some books consistently rank lower in search results after being ingested with different chunk sizes
- Users report that a specific book "never shows up" in relevant searches
- Average token counts vary wildly across books

**Phase to address:**
Quick wins / configurable chunk sizes phase. Add config storage before allowing customization.

---

### 9. L2 Normalization Removal Breaks Compatibility With Existing Vectors

**What goes wrong:**
The current system manually L2-normalizes all embeddings before storing them (see `VectorStore._normalize()`). This was necessary because GTE-large-en returns unnormalized vectors, and L2 distance on unnormalized vectors does not give meaningful similarity. If you switch to cosine distance (which internally normalizes), you might be tempted to remove the manual normalization. But if ANY existing vectors in the collection were stored with normalization, and new vectors are stored without, the collection has inconsistent vectors. Distance calculations between old (normalized) and new (unnormalized) vectors are meaningless.

**Why it happens:**
"Cosine distance handles normalization for us" is true for new collections, but ignores backward compatibility with existing data.

**How to avoid:**
- If switching to cosine, either:
  - (a) Keep the manual normalization (it is harmless with cosine distance -- normalizing already-normalized vectors is a no-op), OR
  - (b) Remove normalization AND re-embed all existing books from scratch
- Option (a) is safer and requires no re-embedding. The vectors are already normalized; cosine distance on normalized vectors equals L2 distance on normalized vectors. The switch is purely for code clarity and consistency
- Document which approach was taken so future developers understand why normalization is (or is not) present

**Warning signs:**
- Search quality suddenly degrades for books ingested before the change
- New books rank higher than old books regardless of relevance
- `VectorStore._normalize()` is deleted but old vectors remain in the collection

**Phase to address:**
Quick wins phase (cosine distance switch). Decide normalization strategy before implementing. Option (a) is recommended -- keep normalization, it costs nothing.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip re-embedding after distance metric change | Faster deployment, no API cost | Silently uses old metric, no actual improvement | Never -- the whole point is changing the metric |
| Use the storage embedding model for semantic boundary detection | No new dependency | 5-10x slower ingest, higher API costs | Only if ingest speed is not a concern and API costs are trivial |
| Hard-code semantic chunk threshold | Simple implementation | Threshold that works for one book fails on another | Only for initial prototype; must be made adaptive |
| Expand ALL search results with context | Simple implementation | Response size bloat, lost-in-the-middle effect | Only if top_k is reduced to 3-5 |
| Store expanded context in ChromaDB documents | Avoid runtime expansion lookups | Massively increased storage, cannot change window later | Never -- use runtime expansion from SQLite |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| ChromaDB collection recreation | Changing `metadata` in `get_or_create_collection` and assuming it takes effect | Delete collection first, then `create_collection` with new settings |
| ChromaDB `get()` for migration | Using `offset` parameter (not supported in all versions) | Use `get()` with `limit` and paginate via `ids` |
| Databricks embedding for chunking | Using GTE-large-en for sentence-level boundary detection | Use a small local model; GTE-large-en is overkill for relative similarity |
| SQLite FTS5 with section filtering | Adding section_path to FTS query syntax | Filter section_path via SQL WHERE on the chunks table, not via FTS5 |
| `prev_chunk_id`/`next_chunk_id` for expansion | Following links without checking section boundaries | Verify `section_path` matches before including adjacent chunks |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Embedding every sentence for semantic chunking via API | Ingest takes 10+ minutes per book | Use local embedding model for boundary detection | Any book with 500+ sentences (~most technical books) |
| Loading full chunks for context expansion at search time | Search latency doubles from ~200ms to ~500ms | Preload adjacent chunk IDs in the initial SQLite query with a JOIN | With context window > 1 or top_k > 10 |
| Section path filtering as post-retrieval filter | Retrieve 100 results, filter to 3 | Push section filter into ChromaDB WHERE clause (exact match on section fields) or SQLite query | When most chunks do not match the section filter |
| Re-embedding all books sequentially | Migration takes hours | Batch re-embedding with parallel book processing | With more than ~10 books |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Returning expanded context without marking the match | Claude cannot tell which part of the expanded text answered the query | Wrap the matched chunk in markers: `[MATCH START]...[MATCH END]` with context before/after |
| Showing raw distance scores | Users see meaningless numbers like 0.342 | Convert to 0-1 similarity with text label: "92% relevant" |
| Changing default chunking without re-indexing existing books | Old books searched with old chunk boundaries, new books with new | Provide a `reindex` command and document the need to re-index |
| Section path filter with no results returns empty without explanation | User thinks no relevant content exists | Return "No results in section X. Try without section filter?" |

## "Looks Done But Isn't" Checklist

- [ ] **Cosine distance switch:** Verify `collection.metadata` shows `cosine` after migration -- `get_or_create_collection` silently keeps old metric
- [ ] **Semantic chunking:** Verify average chunk size is above 150 tokens -- boundary detection may produce tiny fragments
- [ ] **Context enrichment:** Verify expanded chunks share the same `section_path` as the matched chunk -- cross-section expansion adds noise
- [ ] **Search scores:** Verify scores are normalized to 0-1 range and higher = more relevant -- raw distances are inverted
- [ ] **Section path filter:** Verify filtering works with partial paths (e.g., "Chapter 3" matches "Part I > Chapter 3 > Section 1") -- ChromaDB does not support substring matching
- [ ] **Configurable chunk sizes:** Verify chunk config is persisted per book -- otherwise re-ingest uses defaults and original config is lost
- [ ] **Re-indexing:** Verify all 7 existing books work correctly after the migration -- test with real data, not just new ingests
- [ ] **prev/next links:** Verify chunk links are correct after re-chunking -- new chunk IDs break old links

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| ChromaDB still on L2 after "migration" | LOW | Delete collection, recreate with cosine, re-embed all books |
| Tiny semantic chunks degrading search | MEDIUM | Re-ingest affected books with higher min_tokens or fixed-token chunker |
| Context expansion returning cross-section noise | LOW | Add section boundary check, no re-indexing needed |
| Mixed normalized/unnormalized vectors | HIGH | Must re-embed all books from scratch -- cannot fix in place |
| Orphaned ChromaDB vectors after re-chunking | LOW | Delete all vectors for the book, re-embed |
| Section filter returning zero results | LOW | Move filtering to SQLite layer, no data changes needed |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| #1 Silent distance metric non-change | Quick wins (cosine switch) | Assert `collection.metadata["hnsw:space"] == "cosine"` in test |
| #2 Tiny semantic chunk fragments | Semantic chunking | Assert `mean(chunk.token_count) > 150` after chunking |
| #3 Context expansion bloat | Context enrichment | Measure response size with expansion vs. without |
| #4 No migration path | Pre-requisite / quick wins | `reindex_all` command exists and works on all 7 books |
| #5 Expensive sentence embedding | Semantic chunking | Benchmark ingest time before and after |
| #6 Section filter fails in ChromaDB | Metadata search | Integration test with partial section path match |
| #7 Raw distance score confusion | Quick wins (expose scores) | Verify scores are 0-1 with higher = better |
| #8 Mixed chunk sizes incomparable | Configurable chunks | Store and display chunk config per book |
| #9 Normalization inconsistency | Quick wins (cosine switch) | Keep `_normalize()` or re-embed everything |

---

## Sources

- [ChromaDB Cookbook: Collections](https://cookbook.chromadb.dev/core/collections/) -- distance metric immutability, cloning pattern (HIGH confidence)
- [ChromaDB Docs: Configure Collections](https://docs.trychroma.com/docs/collections/configure) -- HNSW space configuration (HIGH confidence)
- [ChromaDB Issue #2515: Unable to modify hnsw:space](https://github.com/chroma-core/chroma/issues/2515) -- confirms silent ignore behavior (HIGH confidence)
- [ChromaDB Issue #1168: collection.modify metadata doesn't change space](https://github.com/chroma-core/chroma/issues/1168) -- confirms immutability (HIGH confidence)
- [Firecrawl: Best Chunking Strategies for RAG 2025](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) -- NAACL 2025 findings on semantic chunking costs (MEDIUM confidence)
- [LangCopilot: Document Chunking for RAG 2025](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide) -- benchmark showing semantic chunking at 54% vs. recursive at 69% (MEDIUM confidence)
- [Anthropic: Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) -- context enrichment strategies (HIGH confidence)
- [Weaviate: Chunking Strategies for RAG](https://weaviate.io/blog/chunking-strategies-for-rag) -- chunk size impact on embedding quality (MEDIUM confidence)
- [Advanced RAG: Sentence Window Retrieval](https://glaforge.dev/posts/2025/02/25/advanced-rag-sentence-window-retrieval/) -- sentence window pattern and caveats (MEDIUM confidence)
- [Superlinked VectorHub: Semantic Chunking](https://superlinked.com/vectorhub/articles/semantic-chunking) -- threshold selection strategies (MEDIUM confidence)
- Mnemo codebase analysis: `vectors/store.py`, `chunking/chunker.py`, `search/service.py`, `ingest.py` (HIGH confidence)

---
*Pitfalls research for: Mnemo v1.2 RAG Improvements*
*Researched: 2026-03-09*
