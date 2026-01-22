# Phase 3: Search & MCP - Research

**Researched:** 2026-01-21
**Domain:** Hybrid Search (FTS5 + ChromaDB) + MCP Server (FastMCP)
**Confidence:** HIGH

## Summary

This research covers two core domains: implementing hybrid search (combining FTS5 keyword search with ChromaDB semantic search) and exposing search functionality via Model Context Protocol (MCP) for Claude Desktop/Code integration.

**Hybrid Search** combines the strengths of keyword (FTS5) and semantic (ChromaDB) search. FTS5 excels at exact matches (function names, technical terms) while semantic search understands meaning. Reciprocal Rank Fusion (RRF) is the standard algorithm to merge results from both approaches without score normalization. The formula `RRF_score(doc) = sum(1/(k + rank_i))` where k=60 produces stable, well-calibrated rankings.

**FastMCP** is the standard Python framework for MCP servers (78 releases, ~1M downloads/day). Version 2.14.3 is the current stable release. The framework uses decorators (`@mcp.tool`) with automatic schema generation from type hints and docstrings. STDIO transport is the default for Claude Desktop/Code integration.

**Primary recommendation:** Use FastMCP 2.x (`fastmcp<3`) for the MCP server. Implement a `SearchService` class that coordinates FTS5 and ChromaDB queries, merges with RRF, and returns attributed results. The codebase already has both search backends implemented - this phase wires them together and exposes via MCP.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastmcp | >=2.14,<3 | MCP server framework | De facto standard, Pythonic decorators, auto-schema |
| (existing) chromadb | >=1.0.0 | Semantic search | Already in place from Phase 2 |
| (existing) sqlite3 | stdlib | Keyword search (FTS5) | Already in place from Phase 1 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | >=1.26 | RRF score computation | Already in project for vector normalization |
| pydantic | >=2.0 | Search result models | Already in project for data models |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| fastmcp | mcp (official SDK) | Official SDK is lower-level; FastMCP wraps it with better DX |
| RRF | Linear combination | Linear requires score normalization; RRF is rank-based, simpler |
| FTS5 BM25 | External BM25 | FTS5 BM25 is built-in, no extra dependencies |

**Installation:**
```bash
pip install "fastmcp>=2.14,<3"
```

## Architecture Patterns

### Recommended Project Structure
```
src/mnemo/
├── search/
│   ├── __init__.py      # Public exports: SearchService, SearchResult
│   ├── service.py       # SearchService: coordinates FTS5 + ChromaDB
│   ├── hybrid.py        # RRF fusion logic
│   └── models.py        # SearchResult, SearchFilter dataclasses
├── mcp/
│   ├── __init__.py      # Public exports: create_server
│   ├── server.py        # FastMCP server with tool definitions
│   └── tools.py         # Tool implementations (search_books, etc.)
└── ... (existing modules)
```

### Pattern 1: Search Service Facade
**What:** Single service class coordinating keyword + semantic search with unified interface
**When to use:** All search operations
**Example:**
```python
# Source: Project architecture pattern
from dataclasses import dataclass
from typing import Literal

@dataclass
class SearchResult:
    """Unified search result with attribution."""
    chunk_id: str
    book_id: str
    book_title: str
    content: str
    content_type: str
    section_path: list[str]
    score: float  # RRF score (higher = better)
    source: Literal["semantic", "keyword", "both"]

class SearchService:
    """Coordinates FTS5 and ChromaDB search with RRF fusion."""

    def __init__(self, db_path: Path | None = None, chroma_path: Path | None = None):
        self.db_path = db_path
        self.chroma_path = chroma_path

    def search(
        self,
        query: str,
        top_k: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
        mode: Literal["hybrid", "semantic", "keyword"] = "hybrid",
    ) -> list[SearchResult]:
        """Search books with optional filters and mode selection."""
        # Implementation: call both backends, merge with RRF
        pass
```

### Pattern 2: Reciprocal Rank Fusion
**What:** Score-agnostic algorithm for merging ranked lists
**When to use:** Combining FTS5 and ChromaDB results
**Example:**
```python
# Source: Standard RRF implementation
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],  # Lists of chunk_ids
    k: int = 60,
) -> dict[str, float]:
    """Compute RRF scores from multiple ranked lists.

    Args:
        ranked_lists: List of ranked result lists (by chunk_id)
        k: Smoothing constant (default 60, standard in literature)

    Returns:
        Dict mapping chunk_id to RRF score (higher = better)
    """
    scores: dict[str, float] = {}
    for ranked_list in ranked_lists:
        for rank, chunk_id in enumerate(ranked_list, start=1):
            if chunk_id not in scores:
                scores[chunk_id] = 0.0
            scores[chunk_id] += 1.0 / (k + rank)
    return scores
```

### Pattern 3: FastMCP Tool Definition
**What:** Decorator-based tool registration with automatic schema generation
**When to use:** All MCP tool definitions
**Example:**
```python
# Source: FastMCP docs (gofastmcp.com)
from fastmcp import FastMCP

mcp = FastMCP("mnemo")

@mcp.tool
def search_books(
    query: str,
    book_id: str | None = None,
    content_type: str | None = None,
    top_k: int = 10,
) -> str:
    """Search your book library for relevant content.

    Args:
        query: Search query (natural language or keywords)
        book_id: Optional 6-char book ID to filter results
        content_type: Optional filter: text, code, table, diagram, math
        top_k: Maximum results to return (default 10)

    Returns:
        Search results with book/chapter attribution in markdown format
    """
    # Implementation: delegate to SearchService
    pass
```

### Pattern 4: Attribution Formatting
**What:** Format search results with clear source attribution
**When to use:** All search result presentation
**Example:**
```python
# Source: Project requirements (MCP-05)
def format_result(result: SearchResult, book_title: str) -> str:
    """Format a single search result with attribution.

    Example output:
    ---
    **Source:** Python Cookbook > Chapter 3 > Generators
    **Book ID:** a7f3b2 | **Type:** code

    ```python
    def fibonacci():
        a, b = 0, 1
        while True:
            yield a
            a, b = b, a + b
    ```
    ---
    """
    section = " > ".join(result.section_path) if result.section_path else "Unknown section"
    header = f"**Source:** {book_title} > {section}\n"
    header += f"**Book ID:** {result.book_id} | **Type:** {result.content_type}\n\n"

    if result.content_type == "code":
        content = f"```\n{result.content}\n```"
    else:
        content = result.content

    return f"---\n{header}{content}\n---"
```

### Anti-Patterns to Avoid
- **Score-based fusion:** Don't try to normalize FTS5 BM25 scores with ChromaDB distances. Use rank-based RRF instead.
- **Blocking main thread:** FastMCP supports async tools. Use async for database operations if performance matters.
- **print() in STDIO servers:** Never use print() - it corrupts JSON-RPC messages. Use logging to stderr.
- **Hardcoded paths:** Always use configurable paths for SQLite and ChromaDB, defaulting to ~/.mnemo/.
- **Missing type hints:** FastMCP generates schemas from type hints. Missing hints = broken tool definitions.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP protocol handling | Custom JSON-RPC | FastMCP | Handles transport, schema generation, error formatting |
| Rank fusion | Custom weighted average | Standard RRF (k=60) | Proven algorithm, no tuning needed |
| FTS5 query escaping | Regex-based | Quote-wrapping (already implemented) | ChunkRepository._sanitize_fts_query handles this |
| Tool schema generation | Manual JSON Schema | FastMCP type hints | Decorators + docstrings = automatic schema |
| STDIO transport | Custom pipe handling | FastMCP mcp.run() | Handles message framing, JSON-RPC properly |

**Key insight:** The MCP protocol has subtle requirements (message framing, capability negotiation). FastMCP handles these correctly. The search logic is where to focus custom code.

## Common Pitfalls

### Pitfall 1: FTS5 Query Syntax Errors
**What goes wrong:** User query contains FTS5 operators (AND, OR, *, ") and causes syntax errors.
**Why it happens:** FTS5 interprets certain characters as query operators.
**How to avoid:** Already solved in ChunkRepository._sanitize_fts_query() - wraps terms in quotes.
**Warning signs:** SQLite "malformed MATCH expression" errors.

### Pitfall 2: Empty Semantic Results Without Embeddings
**What goes wrong:** Semantic search returns nothing because book was ingested without `embed=True`.
**Why it happens:** ChromaDB collection is empty for that book_id.
**How to avoid:** Check if embeddings exist before semantic search. Fall back to keyword-only.
**Warning signs:** Hybrid search returns only keyword matches.

### Pitfall 3: STDIO Logging Corruption
**What goes wrong:** MCP server fails to communicate with Claude.
**Why it happens:** print() statements corrupt the JSON-RPC stream on stdout.
**How to avoid:** Use Python logging with stderr handler only.
**Warning signs:** "Invalid JSON" errors in Claude Desktop logs.

### Pitfall 4: Missing Book Metadata in Results
**What goes wrong:** Results show chunk content but no book title.
**Why it happens:** ChromaDB metadata has book_id but not book title. Must join with SQLite.
**How to avoid:** SearchService must load Book records to get titles for attribution.
**Warning signs:** Results show "Unknown book" or just book_id.

### Pitfall 5: Tool Parameter Validation
**What goes wrong:** Claude passes invalid parameters (wrong content_type, negative top_k).
**Why it happens:** LLM can hallucinate parameter values.
**How to avoid:** Validate inputs in tool implementation, return helpful error messages.
**Warning signs:** Cryptic errors propagated to Claude.

### Pitfall 6: Large Result Sets
**What goes wrong:** Returning 50+ results overwhelms Claude's context window.
**Why it happens:** top_k too high, or no limit on result text length.
**How to avoid:** Default top_k=10, truncate very long chunks in results.
**Warning signs:** MCP output exceeds token limits (Claude Code warns at 10k tokens).

## Code Examples

Verified patterns from official sources:

### FastMCP Server Setup
```python
# Source: gofastmcp.com/tutorials/create-mcp-server
from fastmcp import FastMCP
import logging

# Configure logging to stderr (CRITICAL for STDIO transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],  # stderr by default
)
logger = logging.getLogger(__name__)

mcp = FastMCP("mnemo")

@mcp.tool
def search_books(query: str, top_k: int = 10) -> str:
    """Search your book library."""
    logger.info(f"Search query: {query}")
    # ... implementation
    return "results"

if __name__ == "__main__":
    mcp.run()  # STDIO transport by default
```

### ChromaDB Metadata Filtering
```python
# Source: docs.trychroma.com/docs/querying-collections/metadata-filtering
# Combined filters using $and
where_clause = None
if book_id and content_type:
    where_clause = {
        "$and": [
            {"book_id": book_id},
            {"content_type": content_type},
        ]
    }
elif book_id:
    where_clause = {"book_id": book_id}
elif content_type:
    where_clause = {"content_type": content_type}

results = collection.query(
    query_embeddings=[query_vector],
    n_results=top_k,
    where=where_clause,
    include=["metadatas", "documents", "distances"],
)
```

### FTS5 BM25 with Custom Weights
```python
# Source: sqlite.org/fts5.html
# FTS5 BM25 returns negative scores (lower = better match)
# Can customize column weights if needed
query = """
    SELECT c.*, bm25(chunks_fts) as score
    FROM chunks c
    JOIN chunks_fts fts ON c.rowid = fts.rowid
    WHERE chunks_fts MATCH ?
    ORDER BY score  -- Lower BM25 score = better match
    LIMIT ?
"""
```

### Claude Desktop Configuration
```json
// Source: gofastmcp.com/integrations/claude-desktop
// Location: ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "mnemo": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/mnemo",
        "python", "-m", "mnemo.mcp.server"
      ],
      "env": {
        "DATABRICKS_HOST": "your-host",
        "DATABRICKS_TOKEN": "your-token"
      }
    }
  }
}
```

### Tool with Structured Output
```python
# Source: modelcontextprotocol.io/specification/draft/server/tools
# For backwards compatibility, return both text and structured content
from fastmcp import FastMCP
from typing import TypedDict

class BookInfo(TypedDict):
    id: str
    title: str
    authors: list[str]
    chunk_count: int

@mcp.tool
def get_book_info(book_id: str) -> BookInfo:
    """Get information about a specific book.

    Args:
        book_id: 6-character book identifier
    """
    # FastMCP handles serialization to JSON
    return {
        "id": "a7f3b2",
        "title": "Python Cookbook",
        "authors": ["David Beazley"],
        "chunk_count": 423,
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| mcp SDK (low-level) | FastMCP decorators | 2024 | Much simpler tool definition |
| Score normalization | Reciprocal Rank Fusion | Standard practice | No tuning required for fusion |
| HTTP transport | STDIO transport | Personal use | Simpler config, no server process |
| Manual JSON schema | Type hint generation | FastMCP 2.0 | Automatic schema from Python types |

**Deprecated/outdated:**
- **FastMCP 1.x:** Incorporated into official MCP SDK. Use FastMCP 2.x standalone.
- **FastMCP 3.x (beta):** In development with breaking changes. Pin to `<3` for stability.

## Open Questions

Things that couldn't be fully resolved:

1. **Similarity score threshold**
   - What we know: ChromaDB returns L2 distances (lower = more similar after normalization)
   - What's unclear: What threshold indicates "relevant" vs "not relevant"
   - Recommendation: Return top_k results regardless. Let Claude judge relevance.

2. **RRF k parameter tuning**
   - What we know: k=60 is standard in literature (Microsoft, OpenSearch)
   - What's unclear: Optimal k for this specific use case
   - Recommendation: Use k=60, can tune later if result quality is poor

3. **Async vs sync tool implementations**
   - What we know: FastMCP supports both async and sync tools
   - What's unclear: Whether SQLite/ChromaDB benefit from async in single-user scenario
   - Recommendation: Start sync (simpler), can convert to async if needed

4. **Result content truncation**
   - What we know: Large code blocks can be thousands of tokens
   - What's unclear: Optimal truncation strategy (by tokens? by lines?)
   - Recommendation: Return full content up to 2000 chars, add "[truncated]" marker

## Sources

### Primary (HIGH confidence)
- [FastMCP GitHub](https://github.com/jlowin/fastmcp) - Version info, installation, features
- [FastMCP Docs](https://gofastmcp.com/) - Tutorial, Claude Desktop integration
- [MCP Specification](https://modelcontextprotocol.io/specification/draft/server/tools) - Tool schema, response format
- [ChromaDB Filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering) - Where clause operators
- [SQLite FTS5](https://sqlite.org/fts5.html) - BM25 scoring, query syntax

### Secondary (MEDIUM confidence)
- [RRF Introduction (OpenSearch)](https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/) - Algorithm explanation
- [Hybrid Search (ParadeDB)](https://www.paradedb.com/learn/search-concepts/reciprocal-rank-fusion) - RRF formula, k parameter
- [Claude Desktop MCP Guide](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop) - Config file location

### Tertiary (LOW confidence)
- Various blog posts on hybrid search benchmarks - Claims of 10-15% precision improvement

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - FastMCP is clearly the standard, well-documented
- Architecture: HIGH - Based on official MCP spec and FastMCP examples
- Hybrid search: HIGH - RRF is well-established, FTS5 + ChromaDB already proven
- Pitfalls: MEDIUM - Some based on general MCP/STDIO experience

**Research date:** 2026-01-21
**Valid until:** 2026-02-21 (FastMCP is stable, pin to <3 for safety)
