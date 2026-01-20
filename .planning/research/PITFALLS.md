# Pitfalls Research: Mnemo Document Embedding System

**Domain:** Technical book embedding/retrieval with MCP integration
**Researched:** 2026-01-19
**Confidence:** MEDIUM-HIGH (multiple sources verified)

## Critical Pitfalls

Mistakes that can sink the project or require major rewrites.

### 1. Code Block Destruction During Chunking

**What goes wrong:** Standard text chunkers split code at arbitrary points, breaking function definitions, class declarations, or even mid-line. Retrieved chunks contain syntactically invalid code that confuses the LLM and makes answers useless.

**Warning signs:**
- Code snippets in retrieved results are incomplete
- Missing function signatures, decorators, or closing braces
- LLM produces broken code examples citing your books

**Prevention:**
- Use semantic or AST-aware chunking for code blocks
- Detect code blocks (via HTML `<pre>`, `<code>` tags) during EPUB parsing
- Treat code blocks as atomic units - never split them
- If code exceeds chunk size, store as separate linked chunk with context metadata

**Phase:** Must address in Phase 1 (EPUB parsing/chunking). Cannot retrofit easily.

**Sources:**
- [Stack Overflow - Breaking up is hard to do: Chunking in RAG](https://stackoverflow.blog/2024/12/27/breaking-up-is-hard-to-do-chunking-in-rag-applications/)
- [Mastering Code Chunking for RAG](https://medium.com/@joe_30979/mastering-code-chunking-for-retrieval-augmented-generation-66660397d0e0)

---

### 2. EPUB Code Block Formatting Loss

**What goes wrong:** EPUB files store code in HTML (`<pre>`, `<code>` tags) but extraction libraries often strip formatting or merge code with surrounding prose. Technical books become useless when code loses indentation or gets concatenated with explanatory text.

**Warning signs:**
- Extracted text has code without line breaks
- Indentation is lost (critical for Python)
- Inline code spans merge with surrounding sentences
- Code examples are missing entirely

**Prevention:**
- Use EbookLib + BeautifulSoup pipeline (not raw text extraction)
- Explicitly detect and preserve `<pre>` and `<code>` tags
- Store code blocks with language metadata if available
- Test extraction with Python and YAML content (indentation-sensitive)
- Verify against original EPUB rendering

**Phase:** Phase 1 (EPUB parsing). Foundation for everything.

**Sources:**
- [Extracting text from EPUB files in Python](https://bitsgalore.org/2023/03/09/extracting-text-from-epub-files-in-python.html)
- [Fixing Manning EPUB Code Spans](https://www.garretwilson.com/blog/2023/01/04/fix-manning-epub)

---

### 3. Embedding Model/Query Mismatch

**What goes wrong:** Using different embedding models for indexing vs. querying, or changing models without reindexing. Vectors become incomparable - queries return random results.

**Warning signs:**
- Search results seem random or unrelated
- High similarity scores for obviously wrong matches
- Sudden quality degradation after "minor" changes

**Prevention:**
- Store embedding model identifier with every vector
- Validate model consistency on startup
- Build reindexing into the workflow from day one
- Never mix embeddings from different models in same collection

**Phase:** Phase 1 (embedding pipeline design). Must be architectural decision.

**Sources:**
- [23 RAG Pitfalls](https://www.nb-data.com/p/23-rag-pitfalls-and-how-to-fix-them)
- [Chroma FAQ](https://cookbook.chromadb.dev/faq/)

---

### 4. ChromaDB Multi-Worker Stale Data

**What goes wrong:** Running ChromaDB in library mode (embedded) with multiple workers (Gunicorn, uvicorn workers). Each worker has its own in-memory view. One worker adds documents, others never see them.

**Warning signs:**
- Newly added books don't appear in searches
- Inconsistent results depending on which request you make
- Works in development (single process), fails in production

**Prevention:**
- Use ChromaDB client-server mode, not library mode
- Or ensure single-worker deployment for MCP server
- For Claude Desktop MCP, single process is likely fine
- Test explicitly with concurrent add/query operations

**Phase:** Phase 2 (storage layer). Architectural decision about deployment model.

**Sources:**
- [ChromaDB Library Mode = Stale RAG Data](https://medium.com/@okekechimaobi/chromadb-library-mode-stale-rag-data-never-use-it-in-production-heres-why-b6881bd63067)
- [Chroma Road to Production](https://cookbook.chromadb.dev/running/road-to-prod/)

---

### 5. BGE Similarity Score Misinterpretation

**What goes wrong:** BGE models (including bge-large-en) produce similarity scores in range [0.6, 1.0] due to contrastive learning temperature. Developers set threshold at 0.5 thinking "50% similar" - everything passes.

**Warning signs:**
- Too many results returned for every query
- Irrelevant results have "high" similarity (0.6-0.7)
- Filtering by similarity doesn't help quality

**Prevention:**
- Use bge-large-en-v1.5 (improved similarity distribution)
- Calibrate thresholds empirically on your data (typically 0.8-0.9)
- Focus on relative ranking, not absolute scores
- Consider reranking for top results

**Phase:** Phase 1 (embedding selection) and Phase 3 (retrieval tuning).

**Sources:**
- [BAAI/bge-large-en HuggingFace](https://huggingface.co/BAAI/bge-large-en)
- [BGE Series Documentation](https://bge-model.com/tutorial/1_Embedding/1.2.1.html)

---

## Common Mistakes

Frequent errors that hurt quality but don't kill the project.

### 6. Over-Chunking Technical Content

**What goes wrong:** Using small chunk sizes (128-256 tokens) destroys context. A chunk mentions "the algorithm" but the algorithm definition is in a different chunk. Retrieved content is incomprehensible without surrounding context.

**Prevention:**
- Start with larger chunks (512-1024 tokens) for technical content
- Include chapter/section context in chunk metadata
- Consider parent-child chunking (retrieve small, provide large context)
- Test with questions that require multi-paragraph answers

**Phase:** Phase 1 (chunking strategy).

---

### 7. Ignoring EPUB Structure

**What goes wrong:** Treating EPUB as flat text. Missing valuable structural information: chapter titles, section headers, book metadata. Retrieval can't filter by book, can't cite source location.

**Prevention:**
- Extract and preserve document hierarchy (book -> chapter -> section)
- Store metadata: book title, author, chapter, page/location
- Use metadata for filtering and citation
- Include structural context in chunks ("Chapter 5: Advanced Patterns")

**Phase:** Phase 1 (EPUB parsing).

---

### 8. No Hybrid Search

**What goes wrong:** Pure vector search fails on exact terms: function names, error codes, specific API calls. User searches "useEffect" and gets results about "side effects" instead.

**Prevention:**
- Implement hybrid search (vector + keyword/BM25)
- ChromaDB supports metadata filtering but not full-text
- Consider SQLite FTS5 for keyword search alongside vectors
- Weight keyword matches higher for code-related queries

**Phase:** Phase 2 or 3 (retrieval optimization).

**Sources:**
- [23 RAG Pitfalls](https://www.nb-data.com/p/23-rag-pitfalls-and-how-to-fix-them)

---

### 9. HNSW Index Memory Growth

**What goes wrong:** ChromaDB's HNSW index grows but never shrinks. Adding 5000 documents then deleting 4000 still uses memory for 5000. Over time, index bloats.

**Prevention:**
- Plan for periodic collection recreation
- Track document count vs index size
- For significant deletions, recreate collection and re-add documents
- Budget memory for peak document count, not current

**Phase:** Phase 2 (storage design) - plan for it, implement later.

**Sources:**
- [Chroma FAQ](https://cookbook.chromadb.dev/faq/)

---

### 10. Databricks Rate Limit Blindness

**What goes wrong:** Hitting Databricks embedding API rate limits during bulk indexing. 429 errors cause partial indexing, or entire batch fails without clear status.

**Prevention:**
- Implement exponential backoff with jitter
- Batch documents appropriately (respect token limits)
- Track progress - resume from last successful batch
- Consider local embedding for initial bulk load
- Monitor ITPM (input tokens per minute) limits

**Phase:** Phase 1 (embedding pipeline).

**Sources:**
- [Databricks Foundation Model APIs limits](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/limits)

---

### 11. MCP Server Configuration Fragility

**What goes wrong:** MCP server works in development, fails silently in Claude Desktop. Config file errors aren't reported clearly. Server appears connected but tools don't work.

**Prevention:**
- Test with Claude Desktop from early development
- Validate JSON config programmatically before deployment
- Log startup and connection events
- Handle errors gracefully with informative messages
- Test tool invocations, not just connection

**Phase:** Phase 3 (MCP integration). Test early, don't leave to end.

**Sources:**
- [MCP Server Issues](https://github.com/modelcontextprotocol/servers/issues/2729)
- [Claude MCP Setup Guide](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)

---

## Domain-Specific Gotchas

Issues unique to technical book embedding systems.

### 12. Code vs. Prose Embedding Mismatch

**Context:** User queries are natural language ("how do I handle errors in async functions?") but the most relevant content is a code block with minimal prose. Embedding models trained on prose struggle with code semantics.

**Solution:**
- Ensure code blocks include surrounding explanatory prose in the same chunk
- Consider code-specialized embedding models (or hybrid approach)
- Store code language metadata for filtering
- Weight prose-heavy chunks higher for conceptual questions

---

### 13. Publisher-Specific EPUB Quirks

**Context:** Different publishers use different EPUB structures. O'Reilly, Manning, Pragmatic Programmers all have their quirks. Code spans may use different HTML patterns.

**Solution:**
- Test parsing with EPUBs from each publisher you'll support
- Build publisher-detection and custom parsing rules if needed
- Document known issues per publisher
- Maintain test corpus with examples from each source

---

### 14. Token Limit Chunking vs. Character Limit Chunking

**Context:** Embedding models have token limits (512 for BGE), but chunking often happens by character count. A 512-character chunk might be 200 tokens or 150 depending on content (code is token-dense).

**Solution:**
- Chunk by tokens, not characters
- Use the embedding model's tokenizer for accurate counting
- Leave buffer (aim for 450 tokens for 512-limit model)
- Code-heavy chunks need smaller character limits

---

### 15. Missing "As Of" Context

**Context:** Technical books become outdated. A 2019 React book describes class components; a 2024 book uses hooks. Without publication date in retrieval, you get conflicting advice.

**Solution:**
- Extract and store publication date from EPUB metadata
- Include date in chunk metadata and potentially in prompt
- Allow date-based filtering in search
- Surface publication date in results

---

### 16. Semantic Search Doesn't Find Function Names

**Context:** User searches for `useReducer` (exact function name). Semantic search returns results about "state management" and "reducer patterns" but not the specific API documentation.

**Solution:**
- Implement keyword/exact match alongside semantic search
- Extract and index code identifiers separately
- Consider dedicated "code term" metadata field
- Boost exact matches in ranking

---

### 17. Table and Diagram Information Loss

**Context:** Technical books have tables (comparison charts, API references) and diagrams. These are often lost or garbled in extraction. Tables become run-on text.

**Solution:**
- Detect HTML tables and preserve structure
- Convert tables to markdown or structured format
- For images/diagrams, store alt-text if available
- Consider marking chunks as "contains table" for special handling

---

### 18. ChromaDB Schema Migration on Upgrade

**Context:** Upgrading ChromaDB from 0.4.x to 0.5.x triggers automatic schema migration. This is one-way - you can't downgrade. All clients must be updated simultaneously.

**Solution:**
- Pin ChromaDB version explicitly
- Test upgrades in isolation first
- Backup data before version changes
- Plan upgrade windows with downtime

**Sources:**
- [Chroma FAQ](https://cookbook.chromadb.dev/faq/)

---

## Phase Mapping Summary

| Phase | Critical Pitfalls | Common Mistakes | Gotchas |
|-------|------------------|-----------------|---------|
| Phase 1: EPUB & Chunking | Code destruction, Formatting loss, Embedding selection | Over-chunking, Ignoring structure, Rate limits | Token vs char, Publisher quirks, Tables |
| Phase 2: Storage | Multi-worker stale data | HNSW bloat, Schema migration | - |
| Phase 3: Retrieval & MCP | Similarity misinterpretation | No hybrid search, MCP config | Code vs prose, Function names, Missing dates |

---

## Pre-Flight Checklist

Before each phase, verify:

**Before EPUB Parsing:**
- [ ] Test with code-heavy EPUB (Python book)
- [ ] Verify code indentation preservation
- [ ] Check table extraction
- [ ] Test multiple publishers

**Before Embedding:**
- [ ] Confirm BGE v1.5 (not v1.0)
- [ ] Implement rate limiting/backoff
- [ ] Set up batch progress tracking
- [ ] Test chunk token counts

**Before Storage:**
- [ ] Decide library vs. client-server mode
- [ ] Plan embedding model version tracking
- [ ] Design metadata schema

**Before MCP Integration:**
- [ ] Test with Claude Desktop early
- [ ] Verify JSON config programmatically
- [ ] Plan error handling and logging
