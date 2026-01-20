"""Smart chunking for technical book content.

Provides token-aware chunking that preserves code blocks as atomic units
and maintains context through adjacent chunk linking.

Exports:
    Chunker: Main chunking class
    ChunkerConfig: Configuration for chunk sizes
    count_tokens: Token counting utility
    split_by_tokens: Token-aware text splitting
"""

from mnemo.chunking.chunker import Chunker, ChunkerConfig
from mnemo.chunking.tokenizer import count_tokens, split_by_tokens

__all__ = ["Chunker", "ChunkerConfig", "count_tokens", "split_by_tokens"]
