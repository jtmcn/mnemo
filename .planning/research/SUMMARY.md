# Research Summary

**Project:** Mnemo - Personal Technical Book Library with MCP Semantic Search
**Synthesized:** 2026-01-19
**Overall Confidence:** HIGH

---

## Executive Summary

Mnemo is a personal technical book embedding and retrieval system that exposes semantic search via MCP for Claude integration. The 2026 Python ecosystem is mature for this use case: FastMCP 2.x provides production-ready MCP servers, ChromaDB handles vector storage at personal library scale, and Databricks GTE-large-en offers 8192-token embeddings (critical for code-heavy content). The architecture follows standard RAG patterns with a dual-storage approach: ChromaDB for vectors, SQLite for metadata and text.

The key differentiator is code-aware chunking for technical books. Standard chunkers destroy code by splitting mid-function or mid-statement. This must be addressed from Phase 1 - it cannot be retrofitted. The EPUB parsing pipeline (EbookLib + BeautifulSoup) must explicitly preserve `<pre>` and `<code>` tags with indentation intact. For a personal library of ~10 books, this is a well-scoped problem with no need for enterprise infrastructure.

The primary risks are: (1) code block destruction during chunking, (2) EPUB formatting loss during extraction, and (3) embedding model mismatch between indexing and querying. All three must be addressed in Phase 1. Secondary risks include ChromaDB stale data in multi-worker deployments and Databricks rate limits during bulk indexing. The MCP server integration should be tested early against Claude Desktop, not left to the end.

---

## Stack

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| **MCP Server** | FastMCP | `<3` (pin to v2) | De facto standard, decorator-based API, v3 breaking changes expected |
| **Vector DB** | ChromaDB | 1.4.x | Embedded, no infrastructure, HNSW indexing, ideal for <1M vectors |
| **Embeddings** | Databricks GTE-large-en | current | 8192 token context (vs BGE's 512), 1024 dimensions. BGE deprecated Feb 2026 |
| **EPUB Parsing** | EbookLib + BeautifulSoup + lxml | 0.20 / 4.14.3 / 6.0.2 | Battle-tested combination, handles EPUB2/3 |
| **Chunking** | Custom + semchunk | 3.2.5 | Code-aware chunking required; semchunk for prose (85% faster than alternatives) |
| **Metadata Store** | SQLite via aiosqlite | 0.22.1 | Async interface, relational queries, FTS5 for keyword search |
| **Config** | Pydantic + pydantic-settings | 2.12.5 | Type-safe config, env var handling |
| **HTTP** | httpx | 0.28.1 | Async HTTP for Databricks API |
| **Dev Tools** | uv, Ruff, mypy, pytest | latest | Modern Python toolchain |

**Critical Version Notes:**
- Pin FastMCP to `<3` to avoid breaking changes
- Use GTE-large-en, NOT BGE-large-en (deprecated February 2026)
- Require Python 3.11+ (pytest-asyncio 1.3 needs 3.10+, 3.11 has performance gains)

---

## Features

### Table Stakes (MVP Required)
1. **Semantic search** - Search by meaning, not keywords; users expect Google-level relevance
2. **Source citation** - Book, chapter, page/section for every result; RAG without citations is useless
3. **MCP integration** - The product's core value; Claude calls search tools
4. **Basic CLI** - `add`, `remove`, `list` commands for library management
5. **EPUB text extraction** - Foundation for everything else
6. **Reasonable speed** - <2-3 seconds for ~10 books

### Differentiators (MVP Stretch)
1. **Code-aware chunking** - Keep code blocks intact, associate with explanatory prose. This is THE differentiator for technical books.
2. **Chapter/section navigation** - Results include structural context ("Chapter 5 > Section 5.2")

### Anti-Features (Do NOT Build)
- Full ebook reader (use existing readers)
- Format conversion (use Calibre)
- Cloud sync / multi-device
- Social features / sharing
- Store integration / book discovery
- Natural language chat UI (Claude IS the UI)
- DRM handling
- Automatic file watching / re-indexing

---

## Architecture

### Component Structure

```
INGESTION (offline):
  EPUB -> Parser -> Metadata Scrubber -> Chunker -> Embedder -> ChromaDB
                          |                |
                          v                v
                        SQLite (metadata + text)

RETRIEVAL (per-query):
  Claude -> MCP Server -> Embedder -> ChromaDB -> SQLite -> Response
```

### Key Patterns
1. **Dual storage**: Vectors in ChromaDB, text/metadata in SQLite (avoids ChromaDB metadata limits)
2. **Chunk context linking**: Store prev/next chunk IDs for context expansion
3. **Lazy embedding**: Embed on ingest, not query (query latency matters more)

### Build Order
| Phase | Components | Rationale |
|-------|------------|-----------|
| 1 | SQLite Store, EPUB Parser | Foundation with no dependencies |
| 2 | Metadata Scrubber, Chunker | Depends on parser, writes to SQLite |
| 3 | Embedder, ChromaDB Store | Depends on chunker, completes vector pipeline |
| 4 | CLI, MCP Server | Requires complete backend |

---

## Critical Pitfalls

### 1. Code Block Destruction During Chunking [CRITICAL - Phase 1]
Standard chunkers split code mid-function. Technical books become useless.
**Prevention:** Detect `<pre>`/`<code>` tags, treat code blocks as atomic units, never split them.

### 2. EPUB Code Formatting Loss [CRITICAL - Phase 1]
Extraction strips indentation, merges code with prose. Python code breaks.
**Prevention:** Use EbookLib + BeautifulSoup, explicitly preserve formatting tags, test with Python books.

### 3. Embedding Model/Query Mismatch [CRITICAL - Phase 1]
Different models for indexing vs. querying produces random results.
**Prevention:** Store model identifier with vectors, validate on startup, build reindexing into workflow.

### 4. ChromaDB Stale Data in Multi-Worker [Phase 2]
Library mode + multiple workers = inconsistent reads.
**Prevention:** Single-worker deployment for MCP server (fine for personal use).

### 5. Databricks Rate Limits [Phase 1]
429 errors during bulk indexing cause partial/failed indexes.
**Prevention:** Exponential backoff, batch tracking, resume capability.

---

## Recommendations

### Phase Structure

**Phase 1: Foundation (EPUB + Storage)**
- Build EPUB parser with code-aware extraction
- Design SQLite schema for books/chapters/chunks
- Implement code-preserving chunker
- Test with real technical EPUBs from O'Reilly, Manning, Pragmatic

**Phase 2: Vector Pipeline**
- Integrate Databricks GTE-large-en embeddings
- Set up ChromaDB with persistence
- Implement batch indexing with rate limiting
- Add embedding model version tracking

**Phase 3: Retrieval + MCP**
- Build search pipeline (query -> embed -> search -> enrich)
- Implement MCP server with FastMCP
- Expose tools: `search_books`, `get_book_info`, `list_books`
- Test against Claude Desktop EARLY

**Phase 4: CLI + Polish**
- Build CLI with Click/Rich
- Add library management commands
- Integration testing
- Documentation

### Research Flags

| Phase | Needs Research? | Notes |
|-------|-----------------|-------|
| Phase 1 | NO | Patterns well-documented, test with real EPUBs |
| Phase 2 | NO | Standard ChromaDB + Databricks integration |
| Phase 3 | MAYBE | MCP best practices still evolving; test early |
| Phase 4 | NO | Standard CLI patterns |

### Gaps to Address During Planning

1. **Publisher-specific EPUB quirks** - Test parsing with actual books from target publishers
2. **Code chunking heuristics** - Need real data to tune "large code block" thresholds
3. **Similarity score calibration** - Thresholds need empirical tuning on technical content
4. **Hybrid search** - Deferred to post-MVP but architecture should not preclude it

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All libraries verified on PyPI, versions current |
| Features | MEDIUM-HIGH | Clear scope, anti-features well-defined |
| Architecture | HIGH | Standard RAG patterns, well-documented |
| Pitfalls | MEDIUM-HIGH | Multiple sources confirm key risks |

**Overall: HIGH** - This is a well-understood problem space with mature tooling. The main execution risk is code-aware chunking, which requires careful implementation but has clear patterns.

---

## Sources

### Official Documentation
- [FastMCP GitHub](https://github.com/jlowin/fastmcp)
- [ChromaDB Docs](https://docs.trychroma.com/getting-started)
- [Databricks Foundation Models](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models)
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [uv Documentation](https://docs.astral.sh/uv/)

### RAG Patterns
- [NVIDIA RAG 101](https://developer.nvidia.com/blog/rag-101-demystifying-retrieval-augmented-generation-pipelines/)
- [23 RAG Pitfalls](https://www.nb-data.com/p/23-rag-pitfalls-and-how-to-fix-them)
- [Chunking Strategies - Weaviate](https://weaviate.io/blog/chunking-strategies-for-rag)

### Code-Specific
- [Stack Overflow - Breaking up is hard to do: Chunking in RAG](https://stackoverflow.blog/2024/12/27/breaking-up-is-hard-to-do-chunking-in-rag-applications/)
- [CodeSearchNet Challenge](https://arxiv.org/pdf/1909.09436)
- [Mastering Code Chunking for RAG](https://medium.com/@joe_30979/mastering-code-chunking-for-retrieval-augmented-generation-66660397d0e0)

### EPUB Processing
- [Extracting text from EPUB files in Python](https://bitsgalore.org/2023/03/09/extracting-text-from-epub-files-in-python.html)
- [Vectorizing EPUB with Unstructured and Milvus](https://zilliz.com/learn/vectorize-and-query-epub-content-with-unstructured-and-milvus)
