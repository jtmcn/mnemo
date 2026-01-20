"""Token counting and text splitting utilities.

Uses tiktoken with cl100k_base encoding (GPT-4/Claude compatible) for
accurate token counting and intelligent text splitting.
"""

from __future__ import annotations

import re

import tiktoken

# Use cl100k_base (GPT-4/Claude compatible tokenizer)
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens in text using cl100k_base encoding.

    Args:
        text: Text to count tokens for

    Returns:
        Number of tokens in the text
    """
    if not text:
        return 0
    return len(_encoder.encode(text))


def split_by_tokens(
    text: str,
    max_tokens: int,
    overlap_tokens: int = 50,
) -> list[str]:
    """Split text into chunks of max_tokens with overlap.

    Splits on sentence boundaries when possible, falling back to word
    boundaries. Overlap tokens are added at the start of each chunk
    (except the first) for context continuity.

    Args:
        text: Text to split
        max_tokens: Maximum tokens per chunk
        overlap_tokens: Tokens to overlap between chunks (default 50)

    Returns:
        List of text chunks, each <= max_tokens
    """
    if not text:
        return []

    # If text fits in one chunk, return as-is
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    # Ensure overlap isn't larger than chunk size
    effective_overlap = min(overlap_tokens, max_tokens // 2)

    # Find sentence boundaries for better splitting
    # Pattern matches sentence endings followed by whitespace
    sentence_pattern = re.compile(r"(?<=[.!?])\s+")

    chunks: list[str] = []
    current_pos = 0

    while current_pos < len(tokens):
        # Determine chunk end position
        chunk_end = min(current_pos + max_tokens, len(tokens))

        # Decode the chunk to find sentence boundaries
        chunk_tokens = tokens[current_pos:chunk_end]
        chunk_text = _encoder.decode(chunk_tokens)

        # If this is the last chunk, just use it
        if chunk_end >= len(tokens):
            chunks.append(chunk_text)
            break

        # Try to find a sentence boundary near the end
        best_split = _find_best_split_point(chunk_text, sentence_pattern)

        if best_split > 0:
            # Found a good split point
            split_text = chunk_text[:best_split]
            chunks.append(split_text)

            # Calculate how many tokens we actually used
            used_tokens = len(_encoder.encode(split_text))

            # Move position, accounting for overlap
            current_pos = current_pos + used_tokens - effective_overlap
        else:
            # No good sentence boundary, use the full chunk
            chunks.append(chunk_text)
            current_pos = chunk_end - effective_overlap

        # Ensure we make progress
        if current_pos < 0:
            current_pos = 0

    # Post-process to handle edge cases
    return _clean_chunks(chunks)


def _find_best_split_point(text: str, sentence_pattern: re.Pattern[str]) -> int:
    """Find the best split point in text, preferring sentence boundaries.

    Looks for sentence endings in the last third of the text to find
    a natural break point.

    Args:
        text: Text to find split point in
        sentence_pattern: Compiled regex for sentence boundaries

    Returns:
        Position to split at, or 0 if no good boundary found
    """
    # Look for sentence boundaries in the last half of the text
    search_start = len(text) // 2

    matches = list(sentence_pattern.finditer(text))

    # Find the last sentence boundary before the end
    best_pos = 0
    for match in matches:
        if match.start() >= search_start:
            best_pos = match.end()

    # If no sentence boundary found, try word boundaries
    if best_pos == 0:
        # Find last space in the last third
        last_third = text[search_start:]
        last_space = last_third.rfind(" ")
        if last_space > 0:
            best_pos = search_start + last_space + 1

    return best_pos


def _clean_chunks(chunks: list[str]) -> list[str]:
    """Clean up chunks by trimming whitespace and removing empty chunks.

    Args:
        chunks: List of text chunks

    Returns:
        Cleaned list of chunks
    """
    cleaned = []
    for chunk in chunks:
        trimmed = chunk.strip()
        if trimmed:
            cleaned.append(trimmed)
    return cleaned
