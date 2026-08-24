"""Search result formatters for MCP tools.

Pure string formatting functions — take data and return markdown strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mnemo.search.models import ExpandedResult, SearchResult


def _truncate_at_boundary(content: str, max_chars: int) -> str:
    """Truncate content at sentence or word boundary instead of mid-word.

    Searches backwards from max_chars for sentence-ending punctuation
    ('. ', '! ', '? ', '.\\n'). If found within 60% of max_chars, cuts there.
    Otherwise falls back to last whitespace within 60% of max_chars.
    Ultimate fallback: hard cut at max_chars.

    Args:
        content: Full text content
        max_chars: Maximum character limit

    Returns:
        Truncated content (without trailing indicator — caller adds that)
    """
    if len(content) <= max_chars:
        return content

    min_pos = int(max_chars * 0.6)

    # Try sentence boundary
    for end_marker in [". ", "! ", "? ", ".\n"]:
        pos = content.rfind(end_marker, min_pos, max_chars)
        if pos != -1:
            return content[: pos + len(end_marker)].rstrip()

    # Try word boundary
    pos = content.rfind(" ", min_pos, max_chars)
    if pos != -1:
        return content[:pos]

    # Hard cut
    return content[:max_chars]


def _format_search_results(results: list[SearchResult], max_chars: int = 2000) -> str:
    """Format search results as markdown with attribution.

    Example output per result:
    ---
    **Source:** Python Cookbook > Chapter 3 > Generators
    **Book ID:** a7f3b2 | **Seq:** 42 | **Type:** code | **Match:** semantic | **Score:** 0.85

    ```python
    def fibonacci():
        ...
    ```
    ---
    """
    lines = [f"Found {len(results)} results:\n"]

    for result in results:
        section = " > ".join(result.section_path) if result.section_path else "Unknown section"

        lines.append("---")
        lines.append(f"**Source:** {result.book_title} > {section}")
        lines.append(
            f"**Book ID:** `{result.book_id}` | "
            f"**Seq:** {result.sequence} | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source} | "
            f"**Score:** {result.score:.2f}"
        )
        lines.append("")

        # Format content based on type
        content = result.content
        if len(content) > max_chars:
            content = (
                _truncate_at_boundary(content, max_chars)
                + f"\n\n[truncated at ~{max_chars} chars"
                + f' — use get_book_chunks(book_id="{result.book_id}",'
                + f" start_sequence={result.sequence},"
                + f" end_sequence={result.sequence}) to read full text]"
            )

        if result.content_type == "code":
            lines.append(f"```\n{content}\n```")
        else:
            lines.append(content)

        lines.append("")

    return "\n".join(lines)


def _format_enriched_results(expanded_results: list[ExpandedResult], max_chars: int = 2000) -> str:
    """Format enriched search results with context chunk markers.

    Shows each expanded result with matched chunks clearly delineated
    from surrounding context chunks.
    """
    lines = [f"Found {len(expanded_results)} results (with context):\n"]

    for exp in expanded_results:
        result = exp["result"]
        matched_ids = exp["matched_chunk_ids"]

        section = " > ".join(result.section_path) if result.section_path else "Unknown section"

        lines.append("---")
        lines.append(f"**Source:** {result.book_title} > {section}")
        lines.append(
            f"**Book ID:** `{result.book_id}` | "
            f"**Type:** {result.content_type} | "
            f"**Match:** {result.source} | "
            f"**Score:** {result.score:.2f}"
        )

        for chunk in exp["chunks"]:
            lines.append("")
            lines.append("---")
            if chunk.id in matched_ids:
                lines.append(f"**[MATCH \u2014 seq {chunk.sequence}]**")
            else:
                lines.append(f"*[Context \u2014 seq {chunk.sequence}]*")
            lines.append("")

            content = chunk.content
            if len(content) > max_chars:
                content = (
                    _truncate_at_boundary(content, max_chars)
                    + f"\n\n[truncated at ~{max_chars} chars"
                    + f' — use get_book_chunks(book_id="{result.book_id}",'
                    + f" start_sequence={chunk.sequence},"
                    + f" end_sequence={chunk.sequence}) to read full text]"
                )

            if chunk.content_type.value == "code":
                lines.append(f"```\n{content}\n```")
            else:
                lines.append(content)

        lines.append("")

    return "\n".join(lines)


def _format_mixed_results(
    results: list[SearchResult],
    expanded_map: dict[int, ExpandedResult],
    max_chars: int = 2000,
) -> str:
    """Format results where some have been auto-expanded with context.

    Regular results render normally. Small atomic chunks that were auto-expanded
    render with their surrounding context chunks for readability.
    """
    lines = [f"Found {len(results)} results:\n"]

    for i, result in enumerate(results):
        if i in expanded_map:
            # Render as enriched result with context
            exp = expanded_map[i]
            matched_ids = exp["matched_chunk_ids"]
            section = " > ".join(result.section_path) if result.section_path else "Unknown section"

            lines.append("---")
            lines.append(f"**Source:** {result.book_title} > {section}")
            lines.append(
                f"**Book ID:** `{result.book_id}` | "
                f"**Seq:** {result.sequence} | "
                f"**Type:** {result.content_type} | "
                f"**Match:** {result.source} | "
                f"**Score:** {result.score:.2f}"
            )

            for chunk in exp["chunks"]:
                lines.append("")
                if chunk.id in matched_ids:
                    lines.append(f"**[MATCH \u2014 seq {chunk.sequence}]**")
                else:
                    lines.append(f"*[Context \u2014 seq {chunk.sequence}]*")
                lines.append("")

                content = chunk.content
                if len(content) > max_chars:
                    content = (
                        content[:max_chars]
                        + f"\n\n[truncated at {max_chars} chars"
                        + f' \u2014 use get_book_chunks(book_id="{result.book_id}",'
                        + f" start_sequence={chunk.sequence},"
                        + f" end_sequence={chunk.sequence}) to read full text]"
                    )

                if chunk.content_type.value == "code":
                    lines.append(f"```\n{content}\n```")
                else:
                    lines.append(content)

            lines.append("")
        else:
            # Render as normal result
            section = " > ".join(result.section_path) if result.section_path else "Unknown section"

            lines.append("---")
            lines.append(f"**Source:** {result.book_title} > {section}")
            lines.append(
                f"**Book ID:** `{result.book_id}` | "
                f"**Seq:** {result.sequence} | "
                f"**Type:** {result.content_type} | "
                f"**Match:** {result.source} | "
                f"**Score:** {result.score:.2f}"
            )
            lines.append("")

            content = result.content
            if len(content) > max_chars:
                content = (
                    content[:max_chars]
                    + f"\n\n[truncated at {max_chars} chars"
                    + f' \u2014 use get_book_chunks(book_id="{result.book_id}",'
                    + f" start_sequence={result.sequence},"
                    + f" end_sequence={result.sequence}) to read full text]"
                )

            if result.content_type == "code":
                lines.append(f"```\n{content}\n```")
            else:
                lines.append(content)

            lines.append("")

    return "\n".join(lines)
