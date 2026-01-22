"""Hybrid search fusion algorithm.

Implements Reciprocal Rank Fusion (RRF) for combining ranked result lists
from different search backends (FTS5 keyword search, ChromaDB semantic search).
"""

from __future__ import annotations


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
) -> dict[str, float]:
    """Compute RRF scores from multiple ranked result lists.

    Reciprocal Rank Fusion is a score-agnostic algorithm for merging ranked
    lists. It doesn't require score normalization - only rank positions matter.

    Formula: RRF_score(doc) = sum(1 / (k + rank)) across all lists

    The k parameter (default 60) is a smoothing constant that:
    - Prevents division by zero (rank starts at 1)
    - Balances influence of top vs lower-ranked results
    - k=60 is standard in literature (Microsoft, OpenSearch)

    Args:
        ranked_lists: List of ranked result lists, where each inner list
            contains chunk_ids ordered by relevance (best first).
            Example: [["id1", "id2"], ["id2", "id3"]]
        k: Smoothing constant (default 60, per literature standard)

    Returns:
        Dict mapping chunk_id to RRF score (higher = more relevant).
        Items appearing in multiple lists score higher.

    Examples:
        >>> # Item in both lists scores higher
        >>> scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
        >>> scores["b"] > scores["a"]  # "b" in both lists
        True
        >>> scores["b"] > scores["c"]  # "b" in both lists
        True

        >>> # Items only in one list get single score
        >>> scores = reciprocal_rank_fusion([["a"], ["b"]])
        >>> scores["a"] == scores["b"]  # Same rank in their lists
        True
    """
    if k < 0:
        raise ValueError("k must be non-negative")

    scores: dict[str, float] = {}

    for ranked_list in ranked_lists:
        for rank, chunk_id in enumerate(ranked_list, start=1):
            if chunk_id not in scores:
                scores[chunk_id] = 0.0
            scores[chunk_id] += 1.0 / (k + rank)

    return scores
