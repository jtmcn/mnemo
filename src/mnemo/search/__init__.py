"""Search module for Mnemo.

Provides hybrid search combining FTS5 keyword search with ChromaDB semantic
search using Reciprocal Rank Fusion (RRF).

Public API:
    SearchService: Main search coordinator
    SearchResult: Unified search result with attribution
    SearchFilter: Optional filters for search queries
    ExpandedResult: A result plus its neighbouring context chunks
    SearchResponse: Results, plus why nothing matched when nothing did
    EmptyReason: The kind and wording of an empty search
    reciprocal_rank_fusion: RRF algorithm (exported for testing)
"""

from typing import TYPE_CHECKING, Any

from mnemo.search.hybrid import reciprocal_rank_fusion
from mnemo.search.models import (
    EmptyReason,
    ExpandedResult,
    SearchFilter,
    SearchResponse,
    SearchResult,
)

if TYPE_CHECKING:
    # Runtime import stays lazy (see __getattr__); type checkers need the real class.
    from mnemo.search.service import SearchService

# SearchService imported lazily to avoid import-time side effects
__all__ = [
    "SearchService",
    "SearchResult",
    "SearchFilter",
    "ExpandedResult",
    "SearchResponse",
    "EmptyReason",
    "reciprocal_rank_fusion",
]


def __getattr__(name: str) -> Any:
    """Lazy import for SearchService to avoid import-time side effects."""
    if name == "SearchService":
        from mnemo.search.service import SearchService

        return SearchService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
