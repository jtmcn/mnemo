"""Mnemo: Ask Claude questions, get answers from your book collection.

Main exports:
- ingest_book: Parse and store an EPUB file
- embed_book: Generate embeddings for an already-stored book
- remove_book: Remove a book and all associated data
- Book, Chunk, ContentType: Core data models
- BookRepository, ChunkRepository: Storage layer
- EPUBParser: EPUB parsing
- Chunker: Smart chunking
- DatabricksEmbedder: Embedding generation
- VectorStore: Vector storage
"""

from mnemo.ingest import embed_book, ingest_book, remove_book
from mnemo.models import Book, Chunk, ContentType

__all__ = [
    # Ingestion
    "ingest_book",
    "embed_book",
    "remove_book",
    # Models
    "Book",
    "Chunk",
    "ContentType",
]

__version__ = "0.1.0"
