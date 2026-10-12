"""Mnemo: Ask Claude questions, get answers from your book collection.

Main exports:
- intake: Take a book file into the library and report what happened
- IntakeOutcome, Note: What intake returns
- embed_book: Generate embeddings for an already-stored book
- remove_book: Remove a book and all associated data
- Book, Chunk, ContentType: Core data models
- BookRepository, ChunkRepository: Storage layer
- EPUBParser: EPUB parsing
- Chunker: Smart chunking
- Embedder: Embedding generation
- VectorStore: Vector storage
"""

from mnemo.ingest import embed_book, remove_book
from mnemo.models import Book, Chunk, ContentType
from mnemo.services.book_service import IntakeOutcome, Note, intake

__all__ = [
    # Intake — the policy seam both front ends go through
    "intake",
    "IntakeOutcome",
    "Note",
    # Library maintenance
    "embed_book",
    "remove_book",
    # Models
    "Book",
    "Chunk",
    "ContentType",
]

from importlib.metadata import version as _version

__version__ = _version("mnemo")
