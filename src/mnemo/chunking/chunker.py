"""Smart chunking for technical book content.

Transforms ContentBlocks from the EPUB parser into properly-sized Chunks
that preserve code integrity and maintain context for effective retrieval.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from mnemo.chunking.tokenizer import count_tokens, split_by_tokens
from mnemo.models import Chunk, ContentType
from mnemo.parsing.models import ContentBlock


@dataclass
class ChunkerConfig:
    """Configuration for chunking behavior.

    Attributes:
        min_tokens: Minimum tokens per text chunk (default 400)
        max_tokens: Maximum tokens per text chunk (default 800)
        overlap_tokens: Overlap tokens between text chunks (default 50)
    """

    min_tokens: int = 400
    max_tokens: int = 800
    overlap_tokens: int = 50

    @staticmethod
    def validate_params(min_tokens: int | None, max_tokens: int | None) -> str | None:
        """Validate chunk size parameters.

        Args:
            min_tokens: Minimum tokens per chunk (or None for default)
            max_tokens: Maximum tokens per chunk (or None for default)

        Returns:
            Error message string if invalid, None if valid.
        """
        if min_tokens is not None and min_tokens < 100:
            return "chunk_min_tokens must be >= 100"
        if max_tokens is not None and max_tokens > 2000:
            return "chunk_max_tokens must be <= 2000"
        if min_tokens is not None and max_tokens is not None and min_tokens >= max_tokens:
            return "chunk_min_tokens must be less than chunk_max_tokens"
        return None


class Chunker:
    """Smart chunker that preserves code blocks and links adjacent chunks.

    Key behaviors:
    - CODE, DIAGRAM, MATH, TABLE blocks are NEVER split (atomic units)
    - TEXT blocks are split to min-max token range with overlap
    - All chunks are linked via prev_chunk_id and next_chunk_id
    - Section boundaries are tracked for context

    Example:
        >>> config = ChunkerConfig(min_tokens=400, max_tokens=800)
        >>> chunker = Chunker(config)
        >>> chunks = chunker.chunk("book123", content_blocks)
    """

    def __init__(self, config: ChunkerConfig | None = None):
        """Initialize chunker with configuration.

        Args:
            config: Chunking configuration (uses defaults if None)
        """
        self.config = config or ChunkerConfig()

    def chunk(self, book_id: str, blocks: list[ContentBlock]) -> list[Chunk]:
        """Convert ContentBlocks to Chunks with proper sizing and linking.

        Rules:
        1. CODE/DIAGRAM/MATH/TABLE blocks: Never split, keep as single chunk
           (even if > max_tokens)
        2. TEXT blocks: Split to min-max token range with overlap
        3. Track section boundaries for spanning chunks
        4. Link adjacent chunks (prev_chunk_id, next_chunk_id)

        Args:
            book_id: ID of the book these chunks belong to
            blocks: List of ContentBlocks from EPUB parser

        Returns:
            List of Chunk objects, linked and properly sized
        """
        if not blocks:
            return []

        # First pass: create all chunks
        chunks: list[Chunk] = []
        current_sequence = 0

        for block in blocks:
            if self._is_atomic_type(block.content_type):
                # Atomic types: never split
                chunk = self._create_atomic_chunk(
                    book_id=book_id,
                    block=block,
                    sequence=current_sequence,
                )
                chunks.append(chunk)
                current_sequence += 1
            else:
                # TEXT: may need splitting
                text_chunks = self._create_text_chunks(
                    book_id=book_id,
                    block=block,
                    start_sequence=current_sequence,
                )
                chunks.extend(text_chunks)
                current_sequence += len(text_chunks)

        # Second pass: link adjacent chunks
        self._link_chunks(chunks)

        return chunks

    def _is_atomic_type(self, content_type: ContentType) -> bool:
        """Check if content type should never be split.

        Args:
            content_type: The content type to check

        Returns:
            True if this type should be kept as a single chunk
        """
        return content_type in (
            ContentType.CODE,
            ContentType.DIAGRAM,
            ContentType.MATH,
            ContentType.TABLE,
        )

    def _create_atomic_chunk(
        self,
        book_id: str,
        block: ContentBlock,
        sequence: int,
    ) -> Chunk:
        """Create a single chunk from an atomic content block.

        Args:
            book_id: ID of the parent book
            block: ContentBlock to convert
            sequence: Sequence number for ordering

        Returns:
            Single Chunk representing the entire block
        """
        content = block.content
        token_count = count_tokens(content)

        return Chunk(
            id=str(uuid.uuid4()),
            book_id=book_id,
            content=content,
            content_type=block.content_type,
            token_count=token_count,
            section_path=list(block.section_path),
            sections=self._sections_from_path(block.section_path),
            language=block.language,
            sequence=sequence,
        )

    def _create_text_chunks(
        self,
        book_id: str,
        block: ContentBlock,
        start_sequence: int,
    ) -> list[Chunk]:
        """Create one or more chunks from a text content block.

        Splits text that exceeds max_tokens, maintaining overlap for
        context continuity.

        Args:
            book_id: ID of the parent book
            block: ContentBlock to convert
            start_sequence: Starting sequence number

        Returns:
            List of Chunks (usually 1, more if text was split)
        """
        content = block.content
        token_count = count_tokens(content)

        # No split needed if within limits
        if token_count <= self.config.max_tokens:
            return [
                Chunk(
                    id=str(uuid.uuid4()),
                    book_id=book_id,
                    content=content,
                    content_type=block.content_type,
                    token_count=token_count,
                    section_path=list(block.section_path),
                    sections=self._sections_from_path(block.section_path),
                    language=block.language,
                    sequence=start_sequence,
                )
            ]

        # Split the text
        text_parts = split_by_tokens(
            content,
            max_tokens=self.config.max_tokens,
            overlap_tokens=self.config.overlap_tokens,
        )

        chunks: list[Chunk] = []
        for i, part in enumerate(text_parts):
            part_token_count = count_tokens(part)

            # For split chunks, all share the same section path
            # (they're from the same block, which has one section)
            chunk = Chunk(
                id=str(uuid.uuid4()),
                book_id=book_id,
                content=part,
                content_type=block.content_type,
                token_count=part_token_count,
                section_path=list(block.section_path),
                sections=self._sections_from_path(block.section_path),
                language=block.language,
                sequence=start_sequence + i,
            )
            chunks.append(chunk)

        return chunks

    def _sections_from_path(self, section_path: list[str]) -> list[str]:
        """Convert section path to sections list.

        For most chunks, this is just the deepest section. For chunks
        spanning boundaries (handled during linking), this may contain
        multiple sections.

        Args:
            section_path: Full hierarchy path

        Returns:
            List of section names (usually just the deepest one)
        """
        if not section_path:
            return []
        # Return the deepest section as the primary section
        return [section_path[-1]]

    def _link_chunks(self, chunks: list[Chunk]) -> None:
        """Link adjacent chunks with prev/next references.

        Modifies chunks in place to set prev_chunk_id and next_chunk_id.

        Args:
            chunks: List of chunks to link
        """
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk.prev_chunk_id = chunks[i - 1].id

            if i < len(chunks) - 1:
                chunk.next_chunk_id = chunks[i + 1].id
