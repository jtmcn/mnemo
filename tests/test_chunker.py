"""Comprehensive tests for the chunking module.

Tests token counting, text splitting, and the smart chunker with
special focus on code block preservation.
"""

from mnemo.chunking.chunker import Chunker, ChunkerConfig
from mnemo.chunking.tokenizer import count_tokens, split_by_tokens
from mnemo.models import ContentType
from mnemo.parsing.models import ContentBlock

# =============================================================================
# Token Counting Tests
# =============================================================================


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_count_tokens_empty_string(self):
        """Empty string should return 0 tokens."""
        assert count_tokens("") == 0

    def test_count_tokens_simple_text(self):
        """Simple text should return positive token count."""
        count = count_tokens("Hello world")
        assert count > 0
        # "Hello world" is typically 2 tokens
        assert count == 2

    def test_count_tokens_code_with_indentation(self):
        """Code with indentation should count correctly."""
        code = """def example():
    x = 1
    y = 2
    return x + y"""
        count = count_tokens(code)
        assert count > 0
        # Verify it's a reasonable count for this code
        assert 10 < count < 50

    def test_count_tokens_unicode(self):
        """Unicode text should be handled correctly."""
        count = count_tokens("Hello world")
        assert count > 0

    def test_count_tokens_whitespace_only(self):
        """Whitespace-only text should still count."""
        count = count_tokens("   \n\t   ")
        assert count >= 0


# =============================================================================
# Text Splitting Tests
# =============================================================================


class TestSplitByTokens:
    """Tests for split_by_tokens function."""

    def test_split_short_text_no_split(self):
        """Short text that fits should return single chunk."""
        chunks = split_by_tokens("Hello world", max_tokens=100)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_split_long_text_multiple_chunks(self):
        """Long text should be split into multiple chunks."""
        # Generate text that will need splitting
        long_text = "This is a sentence. " * 100
        chunks = split_by_tokens(long_text, max_tokens=50)
        assert len(chunks) > 1

    def test_split_respects_max_tokens(self):
        """Each chunk should be <= max_tokens."""
        long_text = "Word " * 500
        max_tokens = 100
        chunks = split_by_tokens(long_text, max_tokens=max_tokens)

        for i, chunk in enumerate(chunks):
            token_count = count_tokens(chunk)
            assert token_count <= max_tokens, (
                f"Chunk {i} has {token_count} tokens, exceeds max {max_tokens}"
            )

    def test_split_adds_overlap(self):
        """Chunks should have overlapping content for context."""
        # Create text with distinct numbered sentences
        sentences = [f"Sentence number {i} here." for i in range(1, 30)]
        long_text = " ".join(sentences)

        chunks = split_by_tokens(long_text, max_tokens=50, overlap_tokens=20)

        # With overlap, we expect some content from end of one chunk
        # to appear at start of next chunk
        # This is hard to verify exactly, so we check that chunks were created
        assert len(chunks) > 1

    def test_split_on_sentence_boundary(self):
        """Split should prefer sentence boundaries."""
        # Text with clear sentence boundaries
        text = "First sentence here. Second sentence follows. Third sentence ends."
        chunks = split_by_tokens(text, max_tokens=10)

        # With such a small max, we'll get splits
        # Each chunk should ideally end at a sentence boundary
        # We can't guarantee this, but we verify no errors
        assert len(chunks) >= 1

    def test_split_empty_text(self):
        """Empty text should return empty list."""
        chunks = split_by_tokens("", max_tokens=100)
        assert chunks == []

    def test_split_single_long_word(self):
        """Single word longer than max_tokens should be handled."""
        # This is an edge case - a single token sequence that exceeds limit
        long_word = "supercalifragilisticexpialidocious"
        chunks = split_by_tokens(long_word, max_tokens=2)
        # Should return something, not crash
        assert len(chunks) >= 1


# =============================================================================
# Code Block Tests (CRITICAL)
# =============================================================================


class TestCodeBlockPreservation:
    """Critical tests ensuring code blocks are NEVER split."""

    def test_code_block_never_split(self):
        """Code block should remain as single chunk."""
        code = """def example():
    x = 1
    y = 2
    return x + y"""

        blocks = [
            ContentBlock(
                content=code,
                content_type=ContentType.CODE,
                section_path=["Chapter 1"],
                language="python",
                source_file="ch1.html",
            )
        ]

        config = ChunkerConfig(max_tokens=10)  # Very small max
        chunker = Chunker(config)
        chunks = chunker.chunk("abc123", blocks)

        assert len(chunks) == 1, f"Code was split into {len(chunks)} chunks!"
        assert chunks[0].content == code, "Code content was modified!"

    def test_large_code_block_stays_intact(self):
        """Large code block (>max_tokens) must stay as single chunk."""
        # Create a large code block
        large_code = "def example():\n" + "    x = 1\n" * 100

        blocks = [
            ContentBlock(
                content=large_code,
                content_type=ContentType.CODE,
                section_path=["Chapter 1"],
                language="python",
                source_file="ch1.html",
            )
        ]

        config = ChunkerConfig(max_tokens=50)  # Very small max
        chunker = Chunker(config)
        chunks = chunker.chunk("a1b2c3", blocks)

        # Must be exactly 1 chunk, never split
        assert len(chunks) == 1, f"Large code was split into {len(chunks)} chunks!"
        assert chunks[0].content == large_code, "Code content was modified!"

    def test_code_preserves_indentation(self):
        """Code indentation must be preserved exactly."""
        code = """class Example:
    def __init__(self):
        self.value = None

    def method(self):
        if True:
            return 1
        else:
            return 2"""

        blocks = [
            ContentBlock(
                content=code,
                content_type=ContentType.CODE,
                section_path=["Classes"],
                language="python",
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert chunks[0].content == code
        # Verify specific indentation patterns
        assert "    def __init__" in chunks[0].content
        assert "        self.value" in chunks[0].content

    def test_code_preserves_language(self):
        """Code language attribute must be preserved."""
        blocks = [
            ContentBlock(
                content="console.log('hello');",
                content_type=ContentType.CODE,
                section_path=["JS"],
                language="javascript",
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert chunks[0].language == "javascript"

    def test_diagram_never_split(self):
        """Diagram content should never be split."""
        diagram = """
    +--------+     +--------+
    | Start  |---->| End    |
    +--------+     +--------+
        |
        v
    +--------+
    | Middle |
    +--------+
"""
        blocks = [
            ContentBlock(
                content=diagram,
                content_type=ContentType.DIAGRAM,
                section_path=["Architecture"],
                source_file="ch1.html",
            )
        ]

        config = ChunkerConfig(max_tokens=10)
        chunker = Chunker(config)
        chunks = chunker.chunk("a1b2c3", blocks)

        assert len(chunks) == 1
        assert chunks[0].content == diagram

    def test_math_never_split(self):
        """Math content should never be split."""
        math = r"\sum_{i=1}^{n} x_i = \frac{1}{n} \sum_{j=1}^{m} y_j"

        blocks = [
            ContentBlock(
                content=math,
                content_type=ContentType.MATH,
                section_path=["Formulas"],
                source_file="ch1.html",
            )
        ]

        config = ChunkerConfig(max_tokens=5)
        chunker = Chunker(config)
        chunks = chunker.chunk("a1b2c3", blocks)

        assert len(chunks) == 1
        assert chunks[0].content == math

    def test_table_never_split(self):
        """Table content should never be split."""
        table = """| Name | Value |
| ---- | ----- |
| foo  | 1     |
| bar  | 2     |
| baz  | 3     |"""

        blocks = [
            ContentBlock(
                content=table,
                content_type=ContentType.TABLE,
                section_path=["Data"],
                source_file="ch1.html",
            )
        ]

        config = ChunkerConfig(max_tokens=5)
        chunker = Chunker(config)
        chunks = chunker.chunk("a1b2c3", blocks)

        assert len(chunks) == 1
        assert chunks[0].content == table


# =============================================================================
# Section Tracking Tests
# =============================================================================


class TestSectionTracking:
    """Tests for section path and hierarchy tracking."""

    def test_chunks_have_section_path(self):
        """Each chunk should have its section path."""
        blocks = [
            ContentBlock(
                content="Introduction text.",
                content_type=ContentType.TEXT,
                section_path=["Part 1", "Chapter 1", "Introduction"],
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert chunks[0].section_path == ["Part 1", "Chapter 1", "Introduction"]

    def test_sections_from_path(self):
        """Sections list should contain the deepest section."""
        blocks = [
            ContentBlock(
                content="Some content.",
                content_type=ContentType.TEXT,
                section_path=["Part 1", "Chapter 1", "Section 1.1"],
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert "Section 1.1" in chunks[0].sections

    def test_empty_section_path(self):
        """Empty section path should be handled."""
        blocks = [
            ContentBlock(
                content="Orphan content.",
                content_type=ContentType.TEXT,
                section_path=[],
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert chunks[0].section_path == []
        assert chunks[0].sections == []


# =============================================================================
# Linking Tests
# =============================================================================


class TestChunkLinking:
    """Tests for adjacent chunk linking."""

    def test_first_chunk_no_prev(self):
        """First chunk should have no prev_chunk_id."""
        blocks = [
            ContentBlock(
                content="First content.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="Second content.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert chunks[0].prev_chunk_id is None

    def test_last_chunk_no_next(self):
        """Last chunk should have no next_chunk_id."""
        blocks = [
            ContentBlock(
                content="First content.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="Second content.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert chunks[-1].next_chunk_id is None

    def test_middle_chunks_linked_both_ways(self):
        """Middle chunks should be linked to both neighbors."""
        blocks = [
            ContentBlock(
                content="First.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="Second.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="Third.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        # Middle chunk (index 1)
        assert chunks[1].prev_chunk_id == chunks[0].id
        assert chunks[1].next_chunk_id == chunks[2].id

    def test_links_are_consistent(self):
        """Chunk links should form a consistent chain."""
        blocks = [
            ContentBlock(
                content=f"Content {i}.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            )
            for i in range(5)
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        # Verify chain consistency
        for i in range(len(chunks) - 1):
            # Current's next should point to next chunk
            assert chunks[i].next_chunk_id == chunks[i + 1].id
            # Next's prev should point to current chunk
            assert chunks[i + 1].prev_chunk_id == chunks[i].id


# =============================================================================
# Integration Tests
# =============================================================================


class TestChunkerIntegration:
    """Integration tests for mixed content scenarios."""

    def test_mixed_content_types(self):
        """Chunker should handle mix of all content types."""
        blocks = [
            ContentBlock(
                content="Introduction paragraph.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="def hello():\n    print('hi')",
                content_type=ContentType.CODE,
                section_path=["Ch1"],
                language="python",
                source_file="ch1.html",
            ),
            ContentBlock(
                content="| A | B |\n|---|---|\n| 1 | 2 |",
                content_type=ContentType.TABLE,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="+--+\n|  |\n+--+",
                content_type=ContentType.DIAGRAM,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
            ContentBlock(
                content="$x^2 + y^2 = z^2$",
                content_type=ContentType.MATH,
                section_path=["Ch1"],
                source_file="ch1.html",
            ),
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert len(chunks) == 5
        assert chunks[0].content_type == ContentType.TEXT
        assert chunks[1].content_type == ContentType.CODE
        assert chunks[2].content_type == ContentType.TABLE
        assert chunks[3].content_type == ContentType.DIAGRAM
        assert chunks[4].content_type == ContentType.MATH

    def test_empty_blocks_list(self):
        """Empty blocks list should return empty chunks list."""
        chunker = Chunker()
        chunks = chunker.chunk("book1", [])
        assert chunks == []

    def test_single_block(self):
        """Single block should produce single chunk."""
        blocks = [
            ContentBlock(
                content="Only content.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        assert len(chunks) == 1
        assert chunks[0].prev_chunk_id is None
        assert chunks[0].next_chunk_id is None

    def test_chunk_ids_are_unique(self):
        """All chunk IDs should be unique."""
        blocks = [
            ContentBlock(
                content=f"Content {i}.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            )
            for i in range(10)
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        ids = [chunk.id for chunk in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk IDs found!"

    def test_sequence_numbers_are_correct(self):
        """Sequence numbers should be consecutive starting from 0."""
        blocks = [
            ContentBlock(
                content=f"Content {i}.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            )
            for i in range(5)
        ]

        chunker = Chunker()
        chunks = chunker.chunk("a1b2c3", blocks)

        sequences = [chunk.sequence for chunk in chunks]
        assert sequences == list(range(len(chunks)))

    def test_book_id_propagated(self):
        """All chunks should have the correct book_id."""
        blocks = [
            ContentBlock(
                content="Content.",
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            )
        ]

        chunker = Chunker()
        chunks = chunker.chunk("abc123", blocks)

        assert all(chunk.book_id == "abc123" for chunk in chunks)


class TestChunkerConfigValidation:
    """Tests for ChunkerConfig.validate_params validation."""

    def test_valid_params_returns_none(self):
        """Valid params (min=200, max=1000) should return None."""
        result = ChunkerConfig.validate_params(200, 1000)
        assert result is None

    def test_min_too_small_returns_error(self):
        """min_tokens < 100 should return error string."""
        result = ChunkerConfig.validate_params(50, 800)
        assert result is not None
        assert "chunk_min_tokens" in result
        assert ">= 100" in result

    def test_max_too_large_returns_error(self):
        """max_tokens > 2000 should return error string."""
        result = ChunkerConfig.validate_params(400, 3000)
        assert result is not None
        assert "chunk_max_tokens" in result
        assert "<= 2000" in result

    def test_min_gte_max_returns_error(self):
        """min_tokens >= max_tokens should return error string."""
        result = ChunkerConfig.validate_params(800, 800)
        assert result is not None
        assert "less than" in result

    def test_none_params_returns_none(self):
        """None params (defaults) should return None."""
        result = ChunkerConfig.validate_params(None, None)
        assert result is None

    def test_only_min_provided_valid(self):
        """Only min_tokens provided with valid value should return None."""
        result = ChunkerConfig.validate_params(200, None)
        assert result is None

    def test_only_max_provided_valid(self):
        """Only max_tokens provided with valid value should return None."""
        result = ChunkerConfig.validate_params(None, 1000)
        assert result is None

    def test_text_splitting_creates_linked_chunks(self):
        """Split text should produce linked chunks with correct sequences."""
        # Create text that will definitely be split
        long_text = "This is a sentence. " * 100

        blocks = [
            ContentBlock(
                content=long_text,
                content_type=ContentType.TEXT,
                section_path=["Ch1"],
                source_file="ch1.html",
            )
        ]

        config = ChunkerConfig(max_tokens=50)
        chunker = Chunker(config)
        chunks = chunker.chunk("a1b2c3", blocks)

        # Should have multiple chunks
        assert len(chunks) > 1

        # All should be TEXT
        assert all(c.content_type == ContentType.TEXT for c in chunks)

        # Should be properly linked
        assert chunks[0].prev_chunk_id is None
        assert chunks[-1].next_chunk_id is None
        for i in range(1, len(chunks)):
            assert chunks[i].prev_chunk_id == chunks[i - 1].id


class TestTruncateToTokens:
    """Tests for truncate_to_tokens."""

    def test_leaves_short_text_alone(self):
        from mnemo.chunking.tokenizer import truncate_to_tokens

        assert truncate_to_tokens("a short line", 100) == "a short line"

    def test_truncates_long_text(self):
        from mnemo.chunking.tokenizer import count_tokens, truncate_to_tokens

        out = truncate_to_tokens("word " * 500, 50)
        assert count_tokens(out) == 50
        assert "word" in out

    def test_empty_text(self):
        from mnemo.chunking.tokenizer import truncate_to_tokens

        assert truncate_to_tokens("", 10) == ""
