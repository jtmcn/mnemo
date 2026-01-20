# Architecture Research

**Project:** Mnemo - Personal Technical Book Library
**Researched:** 2026-01-19
**Confidence:** HIGH (patterns well-documented, components standard)

## Component Overview

Mnemo follows the standard RAG (Retrieval-Augmented Generation) pipeline architecture with two distinct flows:

```
INGESTION FLOW (offline, batch):
┌─────────────────────────────────────────────────────────────────────────────┐
│  EPUB Files                                                                  │
│      │                                                                       │
│      ▼                                                                       │
│  ┌─────────┐     ┌───────────────┐     ┌─────────┐     ┌──────────┐        │
│  │  EPUB   │────▶│   Metadata    │────▶│ Chunker │────▶│ Embedder │        │
│  │ Parser  │     │   Scrubber    │     │         │     │          │        │
│  └─────────┘     └───────────────┘     └─────────┘     └──────────┘        │
│                         │                   │               │               │
│                         ▼                   │               ▼               │
│                   ┌──────────┐              │         ┌──────────┐         │
│                   │  SQLite  │◀─────────────┘         │ ChromaDB │         │
│                   │  Store   │                        │  Store   │         │
│                   └──────────┘                        └──────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘

RETRIEVAL FLOW (online, per-query):
┌─────────────────────────────────────────────────────────────────────────────┐
│  Claude Query (via MCP)                                                     │
│      │                                                                       │
│      ▼                                                                       │
│  ┌────────────┐     ┌──────────┐     ┌──────────┐     ┌───────────┐        │
│  │    MCP     │────▶│ Embedder │────▶│ ChromaDB │────▶│  SQLite   │        │
│  │   Server   │     │ (query)  │     │ (search) │     │(metadata) │        │
│  └────────────┘     └──────────┘     └──────────┘     └───────────┘        │
│      │                                                       │              │
│      ▼                                                       │              │
│  ┌────────────────────────────────────────────────────────┐  │              │
│  │              Formatted Response                        │◀─┘              │
│  │  (chunks + book title + chapter + page context)        │                 │
│  └────────────────────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. EPUB Parser
**Responsibility:** Extract raw text and structural metadata from EPUB files
**Inputs:** EPUB file path
**Outputs:**
- Raw HTML/text content per chapter
- Table of contents structure
- Basic EPUB metadata (title, author, etc.)
**Dependencies:**
- ebooklib (EPUB reading)
- BeautifulSoup (HTML parsing, lxml backend)
**Key decisions:**
- Extract from `<p>` tags to avoid noise (titles, navigation, etc.)
- Preserve chapter boundaries from TOC
- Handle both EPUB2 and EPUB3 formats

### 2. Metadata Scrubber
**Responsibility:** Clean, normalize, and enrich book metadata
**Inputs:** Raw EPUB metadata + extracted content
**Outputs:** Normalized metadata record (title, author, ISBN, publication date, subjects, etc.)
**Dependencies:** EPUB Parser output
**Key decisions:**
- Normalize author names (last, first vs first last)
- Extract/infer missing metadata from content if needed
- Handle multiple ISBNs (ISBN-10, ISBN-13)
- Store language, publisher, subjects for filtering

### 3. Chunker
**Responsibility:** Split text into embedding-ready segments while preserving context
**Inputs:** Extracted text with chapter boundaries
**Outputs:** Text chunks with metadata (chapter, position, neighbors)
**Dependencies:** EPUB Parser output
**Key decisions:**
- **Chunk size:** 400-512 tokens (industry standard for retrieval precision)
- **Overlap:** 10-20% for context continuity
- **Strategy:** Recursive/semantic chunking respects paragraph boundaries
- **Code-aware:** Detect code blocks, keep them intact when possible
- **Metadata preserved:** chapter name, chunk position, neighboring chunk IDs

### 4. Embedder
**Responsibility:** Convert text chunks to vector representations
**Inputs:** Text chunks
**Outputs:** 1024-dimension vectors (BGE-large-en)
**Dependencies:**
- Chunker output
- Databricks Foundation Model API (or local sentence-transformers fallback)
**Key decisions:**
- **Model:** databricks-bge-large-en (1024 dimensions, 512 token window)
- **Batch processing:** Embed in batches to avoid rate limits
- **Normalization:** BGE outputs normalized embeddings (ready for cosine similarity)

### 5. ChromaDB Store
**Responsibility:** Store and search vector embeddings
**Inputs:** Vectors + chunk IDs + basic metadata
**Outputs:** Top-k similar chunks for a query
**Dependencies:**
- Embedder output
- Local filesystem (SQLite + HNSW index files)
**Key decisions:**
- **Persistence:** Local SQLite-backed storage (chroma.sqlite3)
- **Collection per library:** Single collection, metadata filtering for books
- **Metadata stored:** book_id, chapter_id, chunk_position (for filtering)
- **Index:** HNSW (default, good for <1M vectors)

### 6. SQLite Store
**Responsibility:** Store structured metadata for books and chunks
**Inputs:** Metadata from scrubber, chunk metadata from chunker
**Outputs:** Book details, chapter listings, chunk context
**Dependencies:** Metadata Scrubber and Chunker outputs
**Tables:**
- `books` (id, title, author, isbn, path, added_at, etc.)
- `chapters` (id, book_id, title, position)
- `chunks` (id, book_id, chapter_id, position, text, prev_chunk_id, next_chunk_id)
**Key decisions:**
- Unified storage: Keep chunk text here, not in ChromaDB (ChromaDB stores vectors only)
- Foreign keys for relational queries
- Full-text search backup (FTS5) for keyword fallback

### 7. MCP Server
**Responsibility:** Expose search capabilities to Claude via Model Context Protocol
**Inputs:** Search queries from Claude
**Outputs:** Formatted search results with context
**Dependencies:**
- ChromaDB Store (vector search)
- SQLite Store (metadata enrichment)
- FastMCP framework
**Tools exposed:**
- `search_books(query, top_k, filters)` - semantic search across library
- `get_book_info(book_id)` - book metadata
- `get_chapter_context(chunk_id)` - surrounding text for a chunk
- `list_books()` - library inventory
**Key decisions:**
- FastMCP for simple decorator-based tool definition
- Return structured data (let Claude format for user)
- Include source attribution (book title, chapter, page estimate)

### 8. CLI
**Responsibility:** User interface for library management
**Inputs:** User commands
**Outputs:** Formatted terminal output
**Dependencies:** All other components
**Commands:**
- `mnemo add <epub_path>` - ingest a book
- `mnemo remove <book_id>` - remove a book
- `mnemo list` - show library
- `mnemo search <query>` - test search (debugging)
- `mnemo status` - show index health
**Key decisions:**
- Click for command structure
- Rich for formatted output (tables, progress bars)
- Consider rich-click for unified styling

## Data Flow

### Ingestion Flow (Adding a Book)

```
1. CLI: mnemo add /path/to/book.epub
   │
2. EPUB Parser: Read EPUB, extract chapters
   │ Output: chapters[] with raw HTML
   │
3. Metadata Scrubber: Extract and normalize metadata
   │ Output: BookMetadata record
   │
4. SQLite Store: Insert book record
   │ Output: book_id
   │
5. Chunker: Split each chapter into chunks
   │ Output: chunks[] with chapter/position metadata
   │
6. SQLite Store: Insert chunk records with text
   │ Output: chunk_ids[]
   │
7. Embedder: Generate embeddings for all chunks
   │ Output: vectors[]
   │
8. ChromaDB Store: Store vectors with chunk_id references
   │ Output: Success
   │
9. CLI: Display completion status
```

### Retrieval Flow (Searching)

```
1. MCP Server: Receive search_books(query="how does TCP handshake work")
   │
2. Embedder: Convert query to vector
   │ Output: query_vector
   │
3. ChromaDB Store: Find top-k similar vectors
   │ Output: [(chunk_id, score), ...]
   │
4. SQLite Store: Fetch chunk text + book/chapter metadata
   │ Output: enriched results with full context
   │
5. MCP Server: Format and return to Claude
   │ Output: [{text, book_title, chapter, score}, ...]
```

## Build Order

The build order is determined by dependencies. Each component must have its dependencies built first.

### Phase 1: Foundation (No Dependencies)
1. **SQLite Store** - Define schema, basic CRUD
   - Why first: Every other component needs somewhere to store/retrieve metadata
   - Standalone: No code dependencies on other components
   - Testable: Can unit test with mock data

2. **EPUB Parser** - Read EPUB files
   - Why first: Need input data to test anything else
   - Standalone: Only depends on external libraries (ebooklib, BeautifulSoup)
   - Testable: Can test with sample EPUB files

### Phase 2: Data Processing (Depends on Phase 1)
3. **Metadata Scrubber** - Clean and normalize metadata
   - Depends on: EPUB Parser (for raw metadata)
   - Writes to: SQLite Store
   - Why now: Need clean metadata before chunking

4. **Chunker** - Split text into chunks
   - Depends on: EPUB Parser (for text content)
   - Writes to: SQLite Store (chunk records)
   - Why now: Need chunks before embedding

### Phase 3: Vector Pipeline (Depends on Phase 2)
5. **Embedder** - Generate vector embeddings
   - Depends on: Chunker (for text to embed)
   - Why now: Need embeddings before vector storage
   - Note: Can be developed with mock chunker output

6. **ChromaDB Store** - Store and search vectors
   - Depends on: Embedder (for vectors to store)
   - Why now: Completes the ingestion pipeline

### Phase 4: Interface Layer (Depends on Phases 1-3)
7. **CLI** - User commands
   - Depends on: All storage and processing components
   - Why now: Need working backend to exercise
   - Enables: Manual testing of full pipeline

8. **MCP Server** - Claude integration
   - Depends on: ChromaDB Store, SQLite Store, Embedder
   - Why last: Requires complete retrieval pipeline
   - Enables: The actual product use case

### Dependency Graph

```
                    ┌──────────────┐
                    │  MCP Server  │
                    └──────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        ┌──────────┐              ┌──────────┐
        │   CLI    │              │ Embedder │
        └──────────┘              └──────────┘
              │                         │
    ┌─────────┼─────────┐               │
    ▼         ▼         ▼               ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│Metadata│ │Chunker │ │ ChromaDB │ │ ChromaDB │
│Scrubber│ │        │ │  Store   │ │  Store   │
└────────┘ └────────┘ └──────────┘ └──────────┘
    │         │                         │
    └────┬────┘                         │
         ▼                              │
   ┌───────────┐                        │
   │EPUB Parser│                        │
   └───────────┘                        │
         │                              │
         └──────────────┬───────────────┘
                        ▼
                 ┌────────────┐
                 │SQLite Store│
                 └────────────┘
```

## Architecture Patterns

### Pattern 1: Dual Storage
**What:** Store vectors in ChromaDB, metadata/text in SQLite
**Why:**
- ChromaDB optimized for vector similarity search
- SQLite optimized for relational queries and text storage
- Avoids ChromaDB metadata size limits
- Enables hybrid search (vector + keyword)

```python
# ChromaDB stores: chunk_id -> vector
# SQLite stores: chunk_id -> text, book_id, chapter_id, position

# Retrieval joins them:
chunk_ids = chromadb.query(query_vector, top_k=10)
results = sqlite.fetch_chunks(chunk_ids)  # Gets text + metadata
```

### Pattern 2: Chunk Context Linking
**What:** Store prev_chunk_id and next_chunk_id for each chunk
**Why:** Enables context expansion without re-chunking

```python
# When a chunk is highly relevant, fetch neighbors:
chunk = get_chunk(chunk_id)
context = get_chunks([chunk.prev_id, chunk_id, chunk.next_id])
```

### Pattern 3: Lazy Embedding
**What:** Embed on ingest, not on query
**Why:** Query latency matters more than ingest latency

```python
# Ingest: O(n) embeddings, one-time cost
# Query: O(1) embedding (just the query), every time
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Storing Text in ChromaDB
**What:** Using ChromaDB's document storage for chunk text
**Why bad:**
- ChromaDB metadata has size limits
- Harder to do full-text search
- Can't leverage SQL for complex queries
**Instead:** Store only vector + chunk_id in ChromaDB, text in SQLite

### Anti-Pattern 2: Single Monolithic Chunk Size
**What:** Using same chunk size for all content
**Why bad:** Code blocks and dense technical content need different treatment
**Instead:** Code-aware chunking that respects block boundaries

### Anti-Pattern 3: No Overlap Between Chunks
**What:** Chunks that don't share any content with neighbors
**Why bad:** Important context at chunk boundaries gets lost
**Instead:** 10-20% overlap, or store neighbor links for retrieval-time expansion

### Anti-Pattern 4: Embedding at Query Time
**What:** Storing raw text, embedding when searched
**Why bad:** Query latency becomes unacceptable (100ms+ per query)
**Instead:** Embed at ingest time, store vectors

## Scalability Considerations

| Concern | 100 books | 1,000 books | 10,000 books |
|---------|-----------|-------------|--------------|
| Vectors | ~100K | ~1M | ~10M |
| Storage | ~500MB | ~5GB | ~50GB |
| Query time | <50ms | <100ms | Consider sharding |
| Ingestion | Minutes | Hours | Need batching |

**For Mnemo's personal library use case:** 100-1,000 books is realistic. ChromaDB with HNSW handles this easily. No need for distributed architecture.

## Sources

- [NVIDIA RAG 101](https://developer.nvidia.com/blog/rag-101-demystifying-retrieval-augmented-generation-pipelines/)
- [RAG Pipeline Diagram Guide](https://latenode.com/blog/ai-frameworks-technical-infrastructure/rag-retrieval-augmented-generation/rag-diagram-guide-visual-architecture-of-retrieval-augmented-generation)
- [ChromaDB GitHub](https://github.com/chroma-core/chroma)
- [Chroma DB Python Local Persistence](https://johal.in/chroma-db-python-local-persistence-for-llm-memory-stores-2025-2/)
- [Document Chunking for RAG](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide)
- [Chunking Strategies - Weaviate](https://weaviate.io/blog/chunking-strategies-for-rag)
- [Best Chunking Strategies for RAG 2025](https://www.firecrawl.dev/blog/best-chunking-strategies-rag-2025)
- [BGE Hugging Face](https://huggingface.co/BAAI/bge-large-en)
- [Databricks Foundation Models](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models)
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [Anthropic MCP Announcement](https://www.anthropic.com/news/model-context-protocol)
- [SQLite RAG - sqlite.ai](https://blog.sqlite.ai/building-a-rag-on-sqlite)
- [ebooklib on PyPI](https://pypi.org/project/EbookLib/)
- [rich-click](https://ewels.github.io/rich-click/)
- [ZenML Vector Database Comparison](https://www.zenml.io/blog/vector-databases-for-rag)
