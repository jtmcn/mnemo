# Phase 2: Vector Pipeline - Research

**Researched:** 2026-01-20
**Domain:** Embeddings (Databricks GTE-large-en) + Vector Storage (ChromaDB)
**Confidence:** HIGH

## Summary

This research covers two core domains: generating embeddings via Databricks Model Serving and storing vectors in ChromaDB for semantic search.

**Databricks GTE-large-en** is a 1024-dimension text embedding model with 8192 token context window, available via pay-per-token endpoints. The model does NOT require instruction prefixes for queries (unlike BGE models). Rate limiting is query-based (540,000 QPH) rather than token-based for embedding models. The REST API follows OpenAI-compatible format with `{"input": [...]}` request bodies.

**ChromaDB** is a mature vector database (v1.4.1 as of Jan 2026) that supports both ephemeral and persistent storage. For this project, we use the `PersistentClient` with pre-computed embeddings (bypassing ChromaDB's default embedding function). Collections lock to embedding dimensionality on first insert, so consistent 1024-dimension vectors are critical.

**Primary recommendation:** Use `httpx` for async HTTP calls to Databricks, `tenacity` for exponential backoff retry logic, and ChromaDB's `PersistentClient` with explicit embeddings parameter. Normalize embeddings (L2) before storage since GTE-large-en does not return normalized vectors.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| chromadb | >=1.4 | Vector storage | Best-in-class embedded vector DB, SQLite-based persistence |
| httpx | >=0.27 | Async HTTP client | Modern async/await, cleaner API than requests |
| tenacity | >=8.3 | Retry logic | Production-grade exponential backoff with decorators |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | >=1.26 | Vector normalization | L2 normalize embeddings before storage |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | requests | requests is sync-only; httpx supports both sync/async |
| tenacity | backoff | tenacity has better async support and more features |
| chromadb | qdrant-client | Qdrant requires separate server; ChromaDB embeds directly |

**Installation:**
```bash
pip install chromadb>=1.4 httpx>=0.27 tenacity>=8.3 numpy>=1.26
```

## Architecture Patterns

### Recommended Project Structure
```
src/mnemo/
├── embeddings/
│   ├── __init__.py      # Public exports
│   ├── client.py        # DatabricksEmbedder class
│   └── config.py        # EmbeddingConfig dataclass
├── vectors/
│   ├── __init__.py      # Public exports
│   ├── store.py         # VectorStore (ChromaDB wrapper)
│   └── config.py        # VectorConfig dataclass
└── ... (existing modules)
```

### Pattern 1: Embedding Client with Retry
**What:** Thin client wrapper around Databricks REST API with built-in retry logic
**When to use:** All embedding generation
**Example:**
```python
# Source: Databricks docs + tenacity docs
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

class DatabricksEmbedder:
    def __init__(self, host: str, token: str):
        self.url = f"{host}/serving-endpoints/databricks-gte-large-en/invocations"
        self.headers = {"Content-Type": "application/json"}
        self.auth = ("token", token)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    )
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts with automatic retry on rate limits."""
        with httpx.Client(timeout=30) as client:
            response = client.post(
                self.url,
                json={"input": texts},
                headers=self.headers,
                auth=self.auth,
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
```

### Pattern 2: Vector Store with Explicit Embeddings
**What:** ChromaDB wrapper that accepts pre-computed embeddings
**When to use:** All vector storage/retrieval
**Example:**
```python
# Source: ChromaDB docs
import chromadb
import numpy as np

class VectorStore:
    def __init__(self, persist_path: str, collection_name: str = "mnemo"):
        self.client = chromadb.PersistentClient(path=persist_path)
        # No embedding_function - we provide embeddings explicitly
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "l2"}  # L2 distance (default)
        )

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str] | None = None,
    ) -> None:
        """Add vectors with metadata. Embeddings must be normalized."""
        # Normalize embeddings (GTE doesn't return normalized vectors)
        normalized = self._normalize(embeddings)
        self.collection.add(
            ids=ids,
            embeddings=normalized,
            metadatas=metadatas,
            documents=documents,
        )

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: dict | None = None,
    ):
        """Query by embedding vector with optional metadata filter."""
        normalized = self._normalize([query_embedding])
        return self.collection.query(
            query_embeddings=normalized,
            n_results=n_results,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

    def _normalize(self, embeddings: list[list[float]]) -> list[list[float]]:
        """L2 normalize embeddings."""
        arr = np.array(embeddings)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return (arr / norms).tolist()
```

### Pattern 3: Batch Processing with Progress
**What:** Process chunks in batches with progress tracking
**When to use:** Bulk embedding of books
**Example:**
```python
# Source: General pattern for batch processing
from typing import Iterator

def batch_chunks(items: list, batch_size: int = 50) -> Iterator[list]:
    """Yield successive batches of items."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]

def embed_book_chunks(
    chunks: list[Chunk],
    embedder: DatabricksEmbedder,
    batch_size: int = 50,
) -> list[tuple[str, list[float]]]:
    """Embed all chunks for a book, returning (chunk_id, embedding) pairs."""
    results = []
    for batch in batch_chunks(chunks, batch_size):
        texts = [chunk.content for chunk in batch]
        embeddings = embedder.embed_batch(texts)
        for chunk, embedding in zip(batch, embeddings):
            results.append((chunk.id, embedding))
    return results
```

### Anti-Patterns to Avoid
- **Mixed embedding functions:** Never use ChromaDB's default embedding function alongside explicit embeddings. Pick one approach.
- **Unnormalized storage:** GTE-large-en does NOT return normalized embeddings. Always L2-normalize before storage.
- **Unbatched requests:** Never embed one text at a time. Always batch (50 texts per request is a good starting point).
- **Missing retry logic:** Rate limits are guaranteed at scale. Build retry from the start.
- **Storing embeddings without chunk IDs:** Use chunk UUIDs as ChromaDB document IDs for easy lookup.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retries | Custom while loop | tenacity | Handles jitter, backoff curves, exception filtering |
| Embedding batching | Manual splitting | Simple generator | But DO handle partial failures within batch |
| Vector normalization | Loop over vectors | numpy | Vectorized operations are 100x faster |
| Persistent vectors | Custom file format | ChromaDB | Handles HNSW index, persistence, concurrent access |
| Rate limit detection | String parsing | HTTP status codes | 429 is standard, response includes retry_after |

**Key insight:** The complexity in this phase is orchestration (batching, retries, error recovery), not the individual operations. Use proven libraries for the building blocks.

## Common Pitfalls

### Pitfall 1: Dimensionality Mismatch
**What goes wrong:** First insert sets collection dimension. Later inserts with different model fail silently or raise cryptic errors.
**Why it happens:** Switching embedding models or using wrong endpoint.
**How to avoid:** Always use `databricks-gte-large-en` (1024 dims). Add assertion on embedding length.
**Warning signs:** Empty query results, "dimension mismatch" errors.

### Pitfall 2: Stale Data in Multi-Process (Library Mode)
**What goes wrong:** Different processes see different data when using ChromaDB in library mode (PersistentClient).
**Why it happens:** Gunicorn/multi-worker deployments with embedded SQLite.
**How to avoid:** For this project (CLI + MCP), single-process is fine. For production web apps, use ChromaDB server mode.
**Warning signs:** Query returns outdated results, data appears to "disappear."

### Pitfall 3: Rate Limit Avalanche
**What goes wrong:** Bulk indexing of large book triggers cascading failures.
**Why it happens:** No backoff, or backoff too aggressive after first retry.
**How to avoid:** Use exponential backoff with jitter. Start conservative (50 texts/batch). Monitor 429s.
**Warning signs:** Many consecutive 429 errors, increasing retry times.

### Pitfall 4: Partial Batch Failure
**What goes wrong:** 45 of 50 texts in batch succeed, but entire batch marked failed.
**Why it happens:** API returns single error for any failure.
**How to avoid:** On batch failure, retry smaller sub-batches. Log which texts failed.
**Warning signs:** Some chunks missing embeddings after "successful" indexing.

### Pitfall 5: Token Limit Exceeded
**What goes wrong:** Chunk exceeds 8192 token limit for GTE-large-en.
**Why it happens:** Phase 1 chunker uses token counting but atomic code blocks can be huge.
**How to avoid:** Phase 1 already handles this with atomic code blocks. But add a safety check: truncate text if token_count > 8000.
**Warning signs:** HTTP 400 errors from embedding API.

### Pitfall 6: Missing Normalization
**What goes wrong:** Query results have inconsistent ordering, similarity scores look wrong.
**Why it happens:** GTE-large-en explicitly does NOT return normalized embeddings.
**How to avoid:** Always L2-normalize before storing AND before querying.
**Warning signs:** Similarity scores > 1.0, inconsistent rankings.

## Code Examples

Verified patterns from official sources:

### Databricks REST API Call
```python
# Source: https://docs.databricks.com/aws/en/machine-learning/model-serving/query-embedding-models
import httpx

def embed_texts(texts: list[str], host: str, token: str) -> list[list[float]]:
    """Generate embeddings via Databricks GTE-large-en."""
    url = f"{host}/serving-endpoints/databricks-gte-large-en/invocations"
    response = httpx.post(
        url,
        json={"input": texts},
        headers={"Content-Type": "application/json"},
        auth=("token", token),
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    # Response format: {"data": [{"embedding": [...], "index": 0}, ...]}
    # Sort by index to maintain order
    sorted_data = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in sorted_data]
```

### ChromaDB with Pre-computed Embeddings
```python
# Source: https://docs.trychroma.com/reference/python/collection
import chromadb

# Create persistent client (data saved to disk)
client = chromadb.PersistentClient(path="/path/to/data")

# Get or create collection (no embedding function = we provide embeddings)
collection = client.get_or_create_collection(name="mnemo")

# Add with explicit embeddings
collection.add(
    ids=["chunk-uuid-1", "chunk-uuid-2"],
    embeddings=[[0.1, 0.2, ...], [0.3, 0.4, ...]],  # 1024-dim each
    metadatas=[
        {"book_id": "a7f3b2", "chapter": "Introduction"},
        {"book_id": "a7f3b2", "chapter": "Chapter 1"},
    ],
    documents=["Optional: original text", "for debugging"],
)

# Query with explicit embedding
results = collection.query(
    query_embeddings=[[0.1, 0.2, ...]],  # 1024-dim query vector
    n_results=10,
    where={"book_id": "a7f3b2"},  # Optional filter
    include=["metadatas", "documents", "distances"],
)
```

### Tenacity Retry with 429 Handling
```python
# Source: https://tenacity.readthedocs.io/
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception,
)
import httpx

def is_retryable(exc: BaseException) -> bool:
    """Check if exception is retryable (rate limit or transient)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
    retry=retry_if_exception(is_retryable),
)
def embed_with_retry(texts: list[str], client: httpx.Client, url: str) -> list:
    """Embed texts with automatic retry on transient failures."""
    response = client.post(url, json={"input": texts})
    response.raise_for_status()
    return response.json()["data"]
```

### L2 Normalization
```python
# Source: HuggingFace GTE-large-en-v1.5 model card
import numpy as np

def normalize_l2(embeddings: list[list[float]]) -> list[list[float]]:
    """L2 normalize embeddings (required for GTE-large-en)."""
    arr = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    # Avoid division by zero
    norms = np.maximum(norms, 1e-12)
    normalized = arr / norms
    return normalized.tolist()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| BGE models | GTE-large-en | Feb 2026 | BGE deprecated on Databricks, GTE is replacement |
| 512 token window | 8192 token window | GTE v1.5 | Can embed much longer chunks natively |
| requests (sync) | httpx (async capable) | ~2024 | Better for concurrent batch processing |
| Custom retry loops | tenacity decorators | ~2023 | Cleaner code, proven reliability |

**Deprecated/outdated:**
- **BGE models on Databricks:** Deprecated Feb 2026. Use GTE-large-en instead.
- **ChromaDB Settings object:** Older ChromaDB versions used Settings for configuration. Current version uses constructor parameters.

## Open Questions

Things that couldn't be fully resolved:

1. **Exact batch size optimization**
   - What we know: 50 texts/batch is a reasonable starting point (from requirements)
   - What's unclear: Optimal batch size for throughput vs. latency tradeoff
   - Recommendation: Start with 50, add instrumentation to tune later

2. **Workspace tier rate limits**
   - What we know: GTE has 540,000 QPH limit, no token limits
   - What's unclear: User's specific Databricks workspace tier limits
   - Recommendation: Build with backoff, log actual limits encountered

3. **ChromaDB document storage**
   - What we know: ChromaDB can store original text in `documents` field
   - What's unclear: Whether to store chunk text (duplicates SQLite) or omit
   - Recommendation: Store it - useful for debugging, ChromaDB handles compression

## Sources

### Primary (HIGH confidence)
- [Databricks GTE-large-en docs](https://docs.databricks.com/aws/en/machine-learning/model-serving/query-embedding-models) - API format, response structure
- [Databricks rate limits](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/limits) - QPH limits, 429 handling
- [ChromaDB getting started](https://docs.trychroma.com/getting-started) - Client types, persistence
- [ChromaDB collection reference](https://docs.trychroma.com/reference/python/collection) - Method signatures
- [HuggingFace GTE-large-en-v1.5](https://huggingface.co/Alibaba-NLP/gte-large-en-v1.5) - Model specs, no instruction prefix needed
- [tenacity docs](https://tenacity.readthedocs.io/) - Retry patterns, exponential backoff

### Secondary (MEDIUM confidence)
- [ChromaDB cookbook](https://cookbook.chromadb.dev/core/collections/) - Best practices, batching
- [Databricks backoff example](https://docs.databricks.com/aws/en/machine-learning/model-serving/model-serving-timeouts) - Retry pattern

### Tertiary (LOW confidence)
- Various blog posts on ChromaDB multi-process issues - Validated against official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official docs for all libraries
- Architecture: HIGH - Based on official examples and patterns
- Pitfalls: HIGH - Documented issues in official troubleshooting

**Research date:** 2026-01-20
**Valid until:** 2026-02-20 (stable domain, 30 days)
