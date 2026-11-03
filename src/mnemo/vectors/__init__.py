"""Vector storage for Mnemo.

Provides ChromaDB-based vector storage for semantic search.
"""

from typing import TYPE_CHECKING, Any

from mnemo.vectors.config import VectorConfig

if TYPE_CHECKING:
    from mnemo.vectors.store import QueryResult, VectorStore


def __getattr__(name: str) -> Any:
    """Lazy import so importing this package never loads chromadb."""
    if name in ("VectorStore", "QueryResult"):
        from mnemo.vectors import store

        return getattr(store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["VectorStore", "VectorConfig", "QueryResult"]
