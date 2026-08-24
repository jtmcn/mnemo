"""Embedding generation for Mnemo.

Provides an OpenAI-compatible embeddings client for semantic search.
"""

from mnemo.embeddings.client import Embedder
from mnemo.embeddings.config import EmbeddingConfig

__all__ = ["Embedder", "EmbeddingConfig"]
