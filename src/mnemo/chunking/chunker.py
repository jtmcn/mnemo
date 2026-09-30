"""Smart chunking for technical book content.

Transforms ContentBlocks from the EPUB parser into properly-sized Chunks
that preserve code integrity and maintain context for effective retrieval.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from mnemo.chunking.tokenizer import count_tokens, split_by_tokens
from mnemo.models import Chunk, ContentType
from mnemo.parsing.models import ContentBlock

# Below this, or on one line, an atomic block is a fragment (an inline `data`),
# not a listing, and folds into the text around it.
_TINY_ATOMIC_TOKENS = 20


@dataclass
class _Draft:
    """A chunk before its id, sequence and links are assigned."""

    content: str
    content_type: ContentType
    language: str | None
    section_path: list[str]
    sections: list[str]
    token_count: int
    # A large atomic block: never split, and nothing merges into it from behind.
    whole: bool


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
    - TEXT blocks over max_tokens are split with overlap
    - Undersized chunks merge into a neighbour in the same section (or carry
      down into a child section), up to max_tokens
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
        1. Large CODE/DIAGRAM/MATH/TABLE blocks are never split
        2. TEXT over max_tokens is split with overlap
        3. Undersized drafts merge into a neighbour in the same section, or
           carry down into a child section, up to max_tokens
        4. Adjacent chunks are linked (prev_chunk_id, next_chunk_id)
        """
        drafts: list[_Draft] = []
        for block in blocks:
            lead = self._popped_lead(drafts, block)
            if lead is not None:
                # Split small lead + block together so the lead is not left alone.
                joined = replace(block, content=f"{lead.content}\n\n{block.content}")
                parts = self._drafts_for(joined)
                parts[0].sections = lead.sections + [
                    x for x in parts[0].sections if x not in lead.sections
                ]
                drafts.extend(parts)
                continue
            for draft in self._drafts_for(block):
                if drafts and self._should_merge(drafts[-1], draft):
                    drafts[-1] = self._merge(drafts[-1], draft)
                else:
                    drafts.append(draft)

        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                book_id=book_id,
                content=draft.content,
                content_type=draft.content_type,
                token_count=draft.token_count,
                section_path=draft.section_path,
                sections=draft.sections,
                language=draft.language,
                sequence=sequence,
            )
            for sequence, draft in enumerate(drafts)
        ]
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

    def _drafts_for(self, block: ContentBlock) -> list[_Draft]:
        """One draft per block, or several for TEXT over max_tokens."""
        tokens = count_tokens(block.content)
        if self._is_atomic_type(block.content_type):
            tiny = tokens < _TINY_ATOMIC_TOKENS or "\n" not in block.content.strip()
            return [self._draft(block, block.content, tokens, whole=not tiny)]
        if tokens <= self.config.max_tokens:
            return [self._draft(block, block.content, tokens, whole=False)]
        parts = split_by_tokens(
            block.content,
            max_tokens=self.config.max_tokens,
            overlap_tokens=self.config.overlap_tokens,
        )
        return [self._draft(block, part, count_tokens(part), whole=False) for part in parts]

    def _draft(self, block: ContentBlock, content: str, tokens: int, whole: bool) -> _Draft:
        return _Draft(
            content=content,
            content_type=block.content_type,
            language=block.language,
            section_path=list(block.section_path),
            sections=self._sections_from_path(block.section_path),
            token_count=tokens,
            whole=whole,
        )

    def _popped_lead(self, drafts: list[_Draft], block: ContentBlock) -> _Draft | None:
        """Pop and return an undersized last draft that TEXT `block` can't join whole."""
        if not drafts or self._is_atomic_type(block.content_type):
            return None
        prev = drafts[-1]
        same, deeper = self._relation(prev, block.section_path)
        if prev.whole or not (same or deeper) or prev.token_count >= self.config.min_tokens:
            return None
        if count_tokens(f"{prev.content}\n\n{block.content}") <= self.config.max_tokens:
            return None
        return drafts.pop()

    @staticmethod
    def _relation(prev: _Draft, path: list[str]) -> tuple[bool, bool]:
        """Whether `path` is the same section as prev, or a descendant of it."""
        depth = len(prev.section_path)
        return path == prev.section_path, len(path) > depth and path[:depth] == prev.section_path

    def _should_merge(self, prev: _Draft, draft: _Draft) -> bool:
        if prev.whole:
            return False
        same, deeper = self._relation(prev, draft.section_path)
        if not (same or deeper):
            return False
        small = prev.token_count < self.config.min_tokens
        if draft.whole:
            return small
        # Recount: the "\n\n" joiner can cost a token beyond the sum.
        fits = count_tokens(f"{prev.content}\n\n{draft.content}") <= self.config.max_tokens
        if deeper:
            return small and fits
        return (small or draft.token_count < self.config.min_tokens) and fits

    def _merge(self, prev: _Draft, draft: _Draft) -> _Draft:
        content = f"{prev.content}\n\n{draft.content}"
        if draft.whole:
            content_type, language = draft.content_type, draft.language
        elif prev.content_type == draft.content_type:
            content_type, language = prev.content_type, prev.language or draft.language
        else:
            content_type, language = ContentType.TEXT, None
        return _Draft(
            content=content,
            content_type=content_type,
            language=language,
            section_path=list(draft.section_path),
            sections=prev.sections + [s for s in draft.sections if s not in prev.sections],
            token_count=count_tokens(content),
            whole=draft.whole,
        )

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
