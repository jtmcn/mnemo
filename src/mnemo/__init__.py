"""Mnemo: Ask Claude questions, get answers from your book collection.

Main exports:
- intake: Take a book file into the library and report what happened
- IntakeOutcome, Note: What intake returns
- ingest_book: Parse and store an EPUB file (the pipeline under intake)
- embed_book: Generate embeddings for an already-stored book
- remove_book: Remove a book and all associated data
- EmbeddingFailed: Book stored but embedding failed (partial success)
- Book, Chunk, ContentType: Core data models
- BookRepository, ChunkRepository: Storage layer
- EPUBParser: EPUB parsing
- Chunker: Smart chunking
- Embedder: Embedding generation
- VectorStore: Vector storage
"""

from mnemo.ingest import EmbeddingFailed, embed_book, ingest_book, remove_book
from mnemo.models import Book, Chunk, ContentType
from mnemo.services.book_service import IntakeOutcome, Note, intake

__all__ = [
    # Intake — the policy seam both front ends go through
    "intake",
    "IntakeOutcome",
    "Note",
    # Ingestion pipeline
    "ingest_book",
    "embed_book",
    "remove_book",
    "EmbeddingFailed",
    # Models
    "Book",
    "Chunk",
    "ContentType",
]

from importlib.metadata import version as _version

__version__ = _version("mnemo")
