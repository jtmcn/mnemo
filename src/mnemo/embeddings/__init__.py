"""Embedding generation for Mnemo.

Provides client for generating embeddings via Databricks GTE-large-en.
"""

from mnemo.embeddings.client import DatabricksEmbedder
from mnemo.embeddings.config import EmbeddingConfig

__all__ = ["DatabricksEmbedder", "EmbeddingConfig"]
