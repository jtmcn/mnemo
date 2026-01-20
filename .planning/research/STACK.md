# Stack Research: Mnemo

**Project:** Technical book embedding and retrieval system with MCP integration
**Researched:** 2026-01-19
**Overall Confidence:** HIGH

## Executive Summary

The 2026 Python ecosystem for document embedding/retrieval is mature and well-defined. For a personal technical book library with ~10 EPUBs, the recommended stack prioritizes simplicity and modern tooling over enterprise-scale solutions. Key decisions:

1. **FastMCP 2.x** for MCP server (pin to `<3` to avoid breaking changes)
2. **ChromaDB 1.4.x** for vector storage (excellent Python-native experience)
3. **Databricks GTE-large-en** for embeddings (8192 token context, replacing deprecated BGE)
4. **EbookLib + BeautifulSoup** for EPUB parsing (proven combination)
5. **Custom chunking** for code-heavy technical content (LangChain splitters as fallback)
6. **uv** for project management (fast, modern, replaces poetry/pip)

---

## Recommended Stack

### MCP Server Framework

**Choice:** FastMCP 2.14.3 (pin to `fastmcp<3`)
**Rationale:** FastMCP is the de facto standard for Python MCP servers. Version 2.x provides production-ready features including enterprise auth, deployment tools, and testing utilities. The simple decorator-based API (`@mcp.tool`) minimizes boilerplate. Version 3.0 is in development with breaking changes expected, so pinning to v2 is essential for stability.
**Alternatives Considered:**
- `mcp` (official SDK) - Lower-level, more boilerplate. FastMCP 1.0 was incorporated into the official SDK, but FastMCP 2.x extends far beyond it.
- Custom implementation - Unnecessary complexity for this use case.

**Confidence:** HIGH (verified via [GitHub](https://github.com/jlowin/fastmcp), [PyPI](https://pypi.org/project/fastmcp/))

**Installation:**
```bash
uv add "fastmcp<3"
```

---

### Vector Database

**Choice:** ChromaDB 1.4.1
**Rationale:** ChromaDB is the standard embedded vector database for Python RAG applications. It runs locally (no server required), has excellent Python ergonomics, and supports persistence to disk. For ~10 books, the embedded mode is ideal - no infrastructure overhead. The Rust-core rewrite provides excellent performance with HNSW indexing.
**Alternatives Considered:**
- Pinecone/Weaviate/Qdrant - Overkill for personal library scale; require cloud/server setup
- FAISS - Lower-level, requires more manual management
- LanceDB - Newer, less ecosystem support
- SQLite with pgvector - More manual work, no native HNSW

**Confidence:** HIGH (verified via [PyPI](https://pypi.org/project/chromadb/), [GitHub](https://github.com/chroma-core/chroma))

**Installation:**
```bash
uv add chromadb
```

---

### Embedding Model/API

**Choice:** Databricks GTE-large-en (`databricks-gte-large-en`)
**Rationale:** Given the project requirement for Databricks, GTE-large-en is the recommended model. It offers 8192-token context window (vs BGE's 512), 1024-dimension embeddings, and Apache 2.0 license. The longer context window is particularly valuable for technical content with code blocks.

**IMPORTANT DEPRECATION NOTICE:** BGE-large-en is being deprecated starting February 15, 2026 (pay-per-token) and May 15, 2026 (provisioned throughput). Use GTE-large-en instead.

**Alternatives Considered:**
- BGE-large-en - Deprecated, shorter context window (512 tokens)
- OpenAI ada-002/text-embedding-3 - External dependency, not Databricks-native
- Local models (all-MiniLM, etc.) - Requires GPU/compute, more operational overhead

**Confidence:** HIGH (verified via [Databricks docs](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models))

**Client Options (in order of preference):**

1. **Databricks SDK (recommended):**
```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
response = w.serving_endpoints.query(
    name="databricks-gte-large-en",
    input="Text to embed"
)
```

2. **OpenAI-compatible client:**
```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
client = w.serving_endpoints.get_open_ai_client()
response = client.embeddings.create(
    model="databricks-gte-large-en",
    input="Text to embed"
)
```

**Installation:**
```bash
uv add databricks-sdk
```

---

### EPUB Parsing

**Choice:** EbookLib 0.20 + BeautifulSoup4 4.14.3 + lxml 6.0.2
**Rationale:** EbookLib is the standard Python library for EPUB manipulation, supporting both EPUB2 and EPUB3. However, it returns HTML content that requires parsing. BeautifulSoup with lxml parser provides robust HTML-to-text extraction. This combination is battle-tested and used in production by tools like Booktype, Audiblez, and Marker.

**Alternatives Considered:**
- epub-meta - Metadata only, no content extraction
- textract - Heavier dependency, uses EbookLib internally anyway
- PyMuPDF - Primarily for PDF, EPUB support is secondary
- Custom ZIP extraction - Reinventing the wheel

**Confidence:** HIGH (verified via [PyPI EbookLib](https://pypi.org/project/EbookLib/), [PyPI BeautifulSoup4](https://pypi.org/project/beautifulsoup4/))

**Installation:**
```bash
uv add ebooklib beautifulsoup4 lxml
```

**Usage Pattern:**
```python
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

book = epub.read_epub('technical_book.epub')
for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
    soup = BeautifulSoup(item.get_content(), 'lxml')
    text = soup.get_text()
    # Also extract code blocks separately
    code_blocks = soup.find_all(['pre', 'code'])
```

---

### Text Chunking

**Choice:** Custom chunking with semchunk 3.2.5 as foundation
**Rationale:** Technical books with code require special handling. Standard chunkers (like LangChain's RecursiveCharacterTextSplitter) can break code blocks mid-statement. For technical content:

1. **Primary:** Custom chunker that preserves code blocks as atomic units
2. **Fallback:** semchunk for prose sections (85% faster than alternatives, semantically meaningful splits)
3. **Token counting:** tiktoken 0.12.0 for accurate token measurement

**Key Requirements for Technical Content:**
- Code blocks must remain intact (never split mid-block)
- Preserve language annotations for syntax highlighting context
- Overlap chunks at semantic boundaries, not arbitrary positions
- Target ~500-1000 tokens per chunk (well under GTE's 8192 limit)

**Alternatives Considered:**
- LangChain RecursiveCharacterTextSplitter - Good general purpose, but can distort code blocks
- LlamaIndex SemanticSplitter - Heavier dependency, embedding-based (slower)
- ai-chunking - Newer, less proven
- semantic-text-splitter - 85% slower than semchunk

**Confidence:** MEDIUM (custom chunking strategy needs validation with actual technical EPUBs)

**Installation:**
```bash
uv add semchunk tiktoken
```

**Strategy:**
```python
# 1. Extract content, identifying code blocks
# 2. For code blocks: keep intact, embed with language context
# 3. For prose: use semchunk with ~800 token target
# 4. Add metadata: chapter, section, is_code, language

import semchunk
import tiktoken

tokenizer = tiktoken.encoding_for_model("gpt-4o")  # or use Databricks tokenizer
chunker = semchunk.chunk

prose_chunks = chunker(
    text=prose_content,
    chunk_size=800,
    token_counter=lambda x: len(tokenizer.encode(x)),
    overlap=0.1  # 10% overlap
)
```

---

### Metadata Storage

**Choice:** SQLite via aiosqlite 0.22.1
**Rationale:** SQLite is ideal for single-user, local-first applications. Book metadata (title, author, chapters, chunk locations) fits naturally in relational schema. aiosqlite provides async interface compatible with FastMCP's async patterns. The database file co-locates with ChromaDB for simple backup/portability.

**Alternatives Considered:**
- PostgreSQL - Overkill for personal library
- JSON files - No querying capability, harder to manage
- ChromaDB metadata only - Limited query patterns
- SQLAlchemy - Added complexity for simple schema

**Confidence:** HIGH (verified via [PyPI](https://pypi.org/project/aiosqlite/), [GitHub](https://github.com/omnilib/aiosqlite))

**Installation:**
```bash
uv add aiosqlite
```

---

### HTTP Client (for Databricks API)

**Choice:** httpx 0.28.1
**Rationale:** httpx provides both sync and async HTTP with a requests-compatible API. Essential for Databricks API calls. Supports HTTP/2 and has excellent async patterns. The Databricks SDK uses httpx internally.

**Alternatives Considered:**
- requests - No async support
- aiohttp - Async-only, different API from requests

**Confidence:** HIGH (verified via [PyPI](https://pypi.org/project/httpx/))

**Installation:**
```bash
uv add httpx
```

---

### Configuration & Validation

**Choice:** Pydantic 2.12.5 + pydantic-settings
**Rationale:** Pydantic is the standard for Python data validation, used by FastAPI, LangChain, and many others. pydantic-settings handles environment variables and configuration files elegantly. Type hints provide IDE support and catch errors early.

**Alternatives Considered:**
- dataclasses - No validation
- attrs - Less ecosystem support
- Manual validation - Error-prone

**Confidence:** HIGH (verified via [PyPI](https://pypi.org/project/pydantic/))

**Installation:**
```bash
uv add pydantic pydantic-settings
```

---

### Development Tools

#### Package Manager
**Choice:** uv 0.9.26
**Rationale:** uv is the modern standard for Python project management, replacing pip, poetry, virtualenv, and more. 10-100x faster than alternatives. Created by Astral (same team as Ruff). Excellent pyproject.toml support and lockfile management.

**Installation:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Linting & Formatting
**Choice:** Ruff 0.14.13
**Rationale:** Ruff replaces Black, Flake8, isort, and dozens of plugins in a single, Rust-powered tool. 10-100x faster than alternatives. Used by FastAPI, Pandas, SciPy. >99.9% Black-compatible formatting.

**Alternatives Considered:**
- Black + Flake8 + isort - Multiple tools, slower, more config
- pylint - Slower, more opinionated

**Installation:**
```bash
uv add --dev ruff
```

#### Type Checking
**Choice:** mypy 1.19.1
**Rationale:** mypy remains the standard Python type checker with best ecosystem support. 40% speedup in recent versions. Strict mode catches real bugs.

**Alternatives Considered:**
- Pyright - Excellent, but mypy has broader ecosystem support
- ty (Astral) - Too new for production (released January 2026)

**Installation:**
```bash
uv add --dev mypy
```

#### Testing
**Choice:** pytest 9.0.2 + pytest-asyncio 1.3.0
**Rationale:** pytest is the Python testing standard. pytest-asyncio required for testing async MCP tools and database operations. Auto mode simplifies async test configuration.

**Installation:**
```bash
uv add --dev pytest pytest-asyncio
```

---

## Anti-Recommendations

### Do NOT Use

| Library | Why Not |
|---------|---------|
| **databricks-bge-large-en** | Deprecated February 2026. Use GTE instead. |
| **LangChain (full framework)** | Massive dependency for simple RAG. Use individual tools if needed. |
| **poetry** | Slower than uv, more complex. uv is the 2026 standard. |
| **Black + Flake8** | Ruff is faster and combines both. |
| **requests** | No async support. Use httpx. |
| **transformers (full)** | Heavy dependency if you only need tokenization. Use tiktoken. |
| **FastMCP 3.x** | Breaking changes expected. Pin to `<3`. |
| **Python < 3.10** | pytest-asyncio 1.3 requires 3.10+. Modern typing features need 3.10+. |

---

## Version Constraints

```toml
# pyproject.toml
[project]
requires-python = ">=3.11"

[project.dependencies]
fastmcp = "<3"  # Pin to v2 to avoid breaking changes
chromadb = ">=1.4.0"
ebooklib = ">=0.20"
beautifulsoup4 = ">=4.14.0"
lxml = ">=6.0.0"
databricks-sdk = ">=0.78.0"
httpx = ">=0.28.0"
pydantic = ">=2.12.0"
pydantic-settings = ">=2.0.0"
aiosqlite = ">=0.22.0"
semchunk = ">=3.2.0"
tiktoken = ">=0.12.0"

[dependency-groups]
dev = [
    "ruff>=0.14.0",
    "mypy>=1.19.0",
    "pytest>=9.0.0",
    "pytest-asyncio>=1.3.0",
]
```

---

## Version Notes

### Python Version
**Recommend: Python 3.11+**

- pytest-asyncio 1.3.0 requires Python >= 3.10
- Python 3.11 has significant performance improvements (10-60% faster)
- Python 3.12/3.13 supported by all recommended libraries
- Avoid Python 3.14 (alpha) for production

### Deprecation Warnings

1. **Databricks BGE-large-en**: Deprecated starting February 15, 2026. Migrate to GTE-large-en before then.

2. **FastMCP 3.0**: Expected in 2026 with breaking changes. Pin to `fastmcp<3` for stability.

3. **EbookLib Python 2.7**: 0.20 is the final version supporting Python 2.7. Future versions will be Python 3 only (not a concern for this project).

---

## Sources

### Official Documentation (HIGH confidence)
- [FastMCP GitHub](https://github.com/jlowin/fastmcp)
- [ChromaDB Docs](https://docs.trychroma.com/getting-started)
- [Databricks Foundation Model APIs](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models)
- [Databricks Embedding Query](https://docs.databricks.com/aws/en/machine-learning/model-serving/query-embedding-models)
- [uv Documentation](https://docs.astral.sh/uv/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)

### PyPI Verified Versions (HIGH confidence)
- [chromadb 1.4.1](https://pypi.org/project/chromadb/)
- [EbookLib 0.20](https://pypi.org/project/EbookLib/)
- [beautifulsoup4 4.14.3](https://pypi.org/project/beautifulsoup4/)
- [lxml 6.0.2](https://pypi.org/project/lxml/)
- [databricks-sdk 0.78.0](https://pypi.org/project/databricks-sdk/)
- [httpx 0.28.1](https://pypi.org/project/httpx/)
- [pydantic 2.12.5](https://pypi.org/project/pydantic/)
- [aiosqlite 0.22.1](https://pypi.org/project/aiosqlite/)
- [semchunk 3.2.5](https://pypi.org/project/semchunk/)
- [tiktoken 0.12.0](https://pypi.org/project/tiktoken/)
- [ruff 0.14.13](https://pypi.org/project/ruff/)
- [mypy 1.19.1](https://pypi.org/project/mypy/)
- [pytest 9.0.2](https://pypi.org/project/pytest/)
- [pytest-asyncio 1.3.0](https://pypi.org/project/pytest-asyncio/)

### Community/Blog Sources (MEDIUM confidence)
- [semchunk GitHub](https://github.com/isaacus-dev/semchunk) - Performance benchmarks
- [LangChain Text Splitters](https://python.langchain.com/docs/how_to/recursive_text_splitter/) - Chunking patterns
- [Real Python uv Guide](https://realpython.com/python-uv/) - Best practices
