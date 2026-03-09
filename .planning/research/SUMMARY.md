# Project Research Summary

**Project:** Mnemo v1.2 RAG Improvements
**Domain:** Advanced RAG techniques for technical book search (semantic chunking, context enrichment, metadata search, quick wins)
**Researched:** 2026-03-09
**Confidence:** HIGH

## Executive Summary

Mnemo v1.2 is an algorithm and configuration milestone, not a dependency milestone. All six features (semantic chunking, cosine distance, context enrichment, metadata search, search scores, configurable chunk sizes) can be built with zero new runtime dependencies using the existing stack: numpy, chromadb 1.5.0, tiktoken, sqlite3, and pydantic. The existing schema already contains every field needed for enrichment and filtering (`prev_chunk_id`, `next_chunk_id`, `section_path`, `sequence`), and the existing `ChunkerConfig` already supports the parameters needed for configurable chunk sizes. This is a milestone about writing better algorithms on top of solid infrastructure.

The recommended approach is to ship features in dependency order: quick wins first (cosine distance migration, score exposure, configurable chunk sizes), then metadata search and context enrichment, and semantic chunking last. This ordering is critical because semantic chunking is the highest-risk, highest-complexity feature with mixed benchmark results (54-87% depending on guardrails), and it benefits from all other features being in place first -- cosine distance for correct similarity comparison, configurable chunk sizes for min/max guardrails, and context enrichment as a fallback for when chunking boundaries are imperfect.

The key risks are: (1) ChromaDB silently ignoring distance metric changes on existing collections -- requiring an explicit delete-and-recreate migration, not just a config change; (2) semantic chunking producing tiny fragments that degrade retrieval quality -- mitigated by enforcing a 200+ token minimum floor and keeping it opt-in per book; and (3) no batch re-ingestion path for existing books -- a `reindex_all` command must be built before or alongside the distance metric change. All three are well-understood and preventable with proper implementation ordering.

## Key Findings

### Recommended Stack

Zero new dependencies. Every capability maps to already-installed packages. The semantic chunker is ~100 lines of numpy cosine similarity on embeddings the project already generates via Databricks. No chunking library (chonkie, langchain, etc.) is needed -- they add heavy transitive dependencies for trivial algorithms. Sentence splitting uses stdlib `re`, not NLTK or spaCy. See [STACK.md](STACK.md) for full analysis.

**Core technologies (all existing):**
- **numpy 2.4.2**: Cosine similarity for semantic boundary detection -- 2 lines of `np.dot` + `np.linalg.norm`
- **chromadb 1.5.0**: Native cosine distance via `configuration={"hnsw": {"space": "cosine"}}`, metadata filtering
- **sqlite3 (stdlib)**: Context enrichment via sequence-range queries on existing `idx_chunks_sequence` index, section path filtering via JSON functions
- **tiktoken**: Token counting for chunk size validation and min/max enforcement

### Expected Features

See [FEATURES.md](FEATURES.md) for full landscape.

**Must have (table stakes):**
- **Context enrichment** -- Fetch N adjacent chunks around search results using existing `prev_chunk_id`/`next_chunk_id` links. Highest-value single feature; transforms isolated chunks into readable passages.
- **Search scores** -- Expose RRF score and normalized similarity in MCP output. One-line formatting change that lets Claude judge result confidence.
- **Cosine distance migration** -- Switch ChromaDB from L2 to cosine. Mathematically equivalent for normalized vectors, but gives interpretable 0-1 distance values and removes need for manual normalization.
- **Configurable chunk sizes** -- Expose existing `ChunkerConfig` params through MCP and CLI. Infrastructure prep for semantic chunking.

**Should have (differentiators):**
- **Section path filtering** -- Filter search by chapter/section using existing `section_path` metadata. Enables structural navigation.
- **Sequence range fetching** -- New MCP tool `get_book_chunks` for reading contiguous chunk ranges. Companion to context enrichment.
- **Semantic chunking** -- Embedding-distance boundary detection for text blocks. Highest complexity and potential upside, but benchmarks are mixed. Must be opt-in with strong min/max token guardrails.

**Defer (v2+):**
- Cross-encoder re-ranking, LLM-based chunking, parent-child chunk hierarchy, chunk-level summaries, agentic multi-hop retrieval

### Architecture Approach

Features layer cleanly onto the existing architecture. See [ARCHITECTURE.md](ARCHITECTURE.md) for component maps and data flows. The one new component is `SemanticBoundaryDetector` in `src/mnemo/chunking/semantic.py`. Everything else is modifications to existing components. The critical architectural pattern is function injection: the semantic chunker accepts an `embed_fn: Callable` rather than importing the Databricks client, keeping chunking decoupled from embedding.

**Major components (changes):**
1. **SemanticBoundaryDetector** (new) -- Sentence-level embedding similarity for boundary detection within text ContentBlocks only
2. **SearchService** (modified) -- Post-search context expansion and section path filter passthrough
3. **VectorStore** (modified) -- Cosine distance configuration, section path filter in `_build_where()`
4. **ChunkRepository** (modified) -- `get_neighbors()` for context expansion, `get_by_sequence_range()` for range fetching
5. **MCP tools** (modified) -- New parameters on `search_books` (section, expand_context) and `add_book` (min_tokens, max_tokens)

**Key patterns to follow:**
- Function injection for embedding access in semantic chunker
- Graceful degradation: semantic chunking falls back to fixed-token on failure
- Backward-compatible defaults: all new parameters default to current behavior (expand_context=0, section=None, semantic=False)

### Critical Pitfalls

See [PITFALLS.md](PITFALLS.md) for full analysis including recovery strategies.

1. **ChromaDB silently ignores distance metric changes** -- `get_or_create_collection` with a different space returns the existing collection unchanged. Must delete and recreate the collection explicitly. Verify with `collection.metadata["hnsw:space"]` assertion.
2. **Semantic chunking fragment problem** -- Technical books produce 30-50 token fragments that embed poorly. Enforce min_tokens >= 200, use per-document 90th-95th percentile thresholds, keep semantic chunking opt-in alongside fixed-token.
3. **No batch re-ingestion path** -- Both semantic chunking and distance metric changes require re-ingesting existing books. Build a `reindex_all` CLI command before shipping any breaking changes.
4. **Context enrichment response bloat** -- Expanding 10 results with window=1 triples response size to ~24K tokens, triggering "lost in the middle" effect. Default window=1, reduce top_k when expanding, only expand within same section.
5. **ChromaDB metadata filtering limitations** -- ChromaDB's `where` clause may not support `$contains` for substring matching on string metadata. Section filtering must happen in the SQLite layer to be reliable.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Foundation and Quick Wins

**Rationale:** These features have zero dependencies on each other, deliver immediate value, and set up infrastructure for later phases. Cosine migration must happen before any re-embedding work. Score exposure is a one-line change. Configurable chunks prepares min/max guardrails for semantic chunking.

**Delivers:** Cosine distance collection, visible search scores, chunk size configurability, batch re-ingestion command

**Addresses features:** Cosine distance migration, search score exposure, configurable chunk sizes

**Avoids pitfalls:** #1 (silent metric non-change -- explicit migration script), #7 (raw score confusion -- normalize to 0-1 similarity), #8 (mixed chunk sizes -- store config per book), #9 (normalization inconsistency -- keep `_normalize()` for safety), #4 (no migration path -- build `reindex_all`)

**Files touched:** `vectors/store.py`, `vectors/config.py`, `vectors/migrate.py` (new), `mcp/tools.py`, `search/models.py`, `ingest.py`, `cli.py`

### Phase 2: Metadata Search

**Rationale:** Pure additive filter logic with no new components. Extends existing filter interfaces in both search backends. Can be built and tested bottom-up (repository -> service -> tool).

**Delivers:** Section path filtering on search, sequence range fetching tool

**Addresses features:** Section path filtering, sequence range fetching

**Avoids pitfalls:** #6 (ChromaDB substring matching limitations -- do filtering in SQLite layer instead)

**Files touched:** `storage/repository.py`, `search/service.py`, `vectors/store.py`, `mcp/tools.py`

### Phase 3: Context Enrichment

**Rationale:** Depends on Phase 2 being done (expand_context parameter lives alongside section filter in MCP tool). The chain is repository -> model -> service -> tool. Highest-value feature for end-user experience.

**Delivers:** Surrounding chunk context in search results, delineated match vs. context in MCP output

**Addresses features:** Context enrichment via chunk expansion

**Avoids pitfalls:** #3 (response bloat -- section-aware expansion, configurable window, reduced top_k), and benefits from #4 mitigation (re-ingestion path already exists from Phase 1)

**Files touched:** `storage/repository.py`, `search/models.py`, `search/service.py`, `mcp/tools.py`

### Phase 4: Semantic Chunking

**Rationale:** Most complex feature, highest risk, benefits from all prior work. Cosine distance already in place for similarity computation. Configurable chunk sizes provide min/max guardrails. Context enrichment compensates for imperfect chunk boundaries. Should be opt-in, not default.

**Delivers:** Embedding-distance boundary detection for text blocks, per-book chunking strategy choice

**Addresses features:** Semantic chunking for text blocks

**Avoids pitfalls:** #2 (tiny fragments -- min_tokens floor from Phase 1's configurable chunks), #5 (expensive sentence embedding -- document cost, consider local model)

**Files touched:** `chunking/semantic.py` (new), `chunking/chunker.py`, `ingest.py`, `mcp/tools.py`

### Phase Ordering Rationale

- **Dependency chain:** Cosine distance must ship before any re-embedding. Configurable chunk sizes must exist before semantic chunking (provides guardrails). Context enrichment shares MCP parameter space with metadata search.
- **Risk gradient:** Phases are ordered from lowest risk (config changes, one-line fixes) to highest risk (semantic chunking with mixed benchmark evidence). This lets the team build confidence and test infrastructure early.
- **Independent testability:** Each phase can be shipped, tested in production with real books, and validated before starting the next. If semantic chunking proves worse than fixed-token in practice, the other three phases still deliver significant value.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (Semantic Chunking):** Benchmark evidence is mixed (54% vs 87% depending on guardrails). Needs empirical testing with actual mnemo books before committing. Threshold tuning (percentile vs. absolute) needs experimentation. Decision on local vs. API embedding model for sentence boundary detection impacts cost and latency significantly.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Quick Wins):** ChromaDB migration is well-documented. Score normalization is arithmetic. Configurable chunks is parameter passthrough.
- **Phase 2 (Metadata Search):** Standard SQL filtering patterns. Only nuance is ChromaDB's limited metadata operators (already documented in pitfalls).
- **Phase 3 (Context Enrichment):** Well-documented RAG pattern with reference implementations available.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new dependencies needed. All capabilities verified against installed versions. |
| Features | MEDIUM-HIGH | Feature set is clear and well-scoped. Semantic chunking benchmarks are mixed -- real-world testing needed. |
| Architecture | HIGH | Existing codebase examined in detail. Integration points verified. Schema already supports all features. |
| Pitfalls | HIGH | ChromaDB pitfalls confirmed via issue tracker and docs. Semantic chunking risks backed by multiple benchmarks. |

**Overall confidence:** HIGH

### Gaps to Address

- **Semantic chunking threshold tuning:** No clear best practice for technical book prose. Must be determined empirically per-document using percentile-based approach. Plan for A/B testing against fixed-token chunks on known queries.
- **Local vs. API embedding for boundary detection:** Using Databricks GTE-large-en for sentence embedding is expensive (60-100 extra API calls per book). A lightweight local model (e.g., MiniLM) could reduce this to zero API cost, but adds a new dependency. Decision deferred to Phase 4 planning.
- **ChromaDB `$contains` operator availability:** PITFALLS.md and STACK.md disagree on whether `$contains` works for string metadata. The safe path (filtering in SQLite) is recommended regardless, but this should be verified with a quick integration test early in Phase 2.
- **Original EPUB path not persisted:** Re-ingestion requires knowing where the source file is. Currently not stored in the books table. Consider adding this in Phase 1 alongside the `reindex_all` command.

## Sources

### Primary (HIGH confidence)
- [ChromaDB Collection Configuration](https://docs.trychroma.com/docs/collections/configure) -- distance metric options, immutability
- [ChromaDB Issue #2515](https://github.com/chroma-core/chroma/issues/2515) -- confirms silent ignore of metric change
- [ChromaDB Issue #1168](https://github.com/chroma-core/chroma/issues/1168) -- confirms collection.modify does not change space
- [ChromaDB Cookbook](https://cookbook.chromadb.dev/core/collections/) -- get_or_create behavior, migration patterns
- [Anthropic: Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) -- context enrichment research
- Mnemo codebase: `vectors/store.py`, `chunking/chunker.py`, `search/service.py`, `models.py`, `storage/database.py`, `ingest.py`

### Secondary (MEDIUM confidence)
- [Firecrawl: Best Chunking Strategies for RAG 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) -- recursive 69% vs semantic 54%
- [Clinical Decision Support Chunking Study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12649634/) -- topic-aligned at 87% vs fixed at 13%
- [Superlinked VectorHub: Semantic Chunking](https://superlinked.com/vectorhub/articles/semantic-chunking) -- boundary detection algorithm
- [NirDiamant RAG_Techniques](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/context_enrichment_window_around_chunk.ipynb) -- context enrichment reference implementation
- [Microsoft Azure RAG Enrichment Guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-enrichment-phase) -- enterprise patterns

### Tertiary (LOW confidence)
- [LangCopilot: Document Chunking Practical Guide](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide) -- additional semantic chunking benchmark
- [Weaviate: Chunking Strategies](https://weaviate.io/blog/chunking-strategies-for-rag) -- chunk size impact on embedding quality

---
*Research completed: 2026-03-09*
*Ready for roadmap: yes*
