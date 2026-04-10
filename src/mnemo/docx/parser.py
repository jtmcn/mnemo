"""DOCX parser for Mnemo using python-docx."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph

from mnemo.models import Book, ContentType
from mnemo.parsing.models import ContentBlock

# Word styles that indicate code blocks
_CODE_STYLES = {
    "code",
    "html code",
    "preformatted text",
    "source code",
    "macro text",
    "plain text",
    "console",
    "listing",
}

# Heading style pattern
_HEADING_PATTERN = re.compile(r"^Heading (\d+)$", re.IGNORECASE)

# Amendment box pattern: "[OBDRR046: Replace ... upon system implementation of NPRR1188:]"
# Also handles multi-ID: "[OBDRR046 and OBDRR052: ... NPRR1188; or ... NPRR1246, respectively:]"
# Patterns must define named groups: id, instruction, trigger (optional), body
_ERCOT_AMENDMENT_PATTERN = re.compile(
    r"^\[(?P<id>(?:OBD|NPRR)\w+(?:\s+and\s+(?:OBD|NPRR)\w+)*):\s*(?P<instruction>.+?)"
    r"(?:\s+upon\s+.*?implementation\s+of\s+(?P<trigger>(?:NPRR|OBD)\w+(?:;\s*or\s+.*?(?:NPRR|OBD)\w+)*))"
    r"[^]]*:\]\s*(?P<body>.+)$",
    re.DOTALL,
)

DEFAULT_AMENDMENT_PATTERNS: list[re.Pattern[str]] = [_ERCOT_AMENDMENT_PATTERN]


class DocxParser:
    """Parser for DOCX files via python-docx.

    Args:
        amendment_patterns: List of compiled regexes to detect amendment callout
            boxes in single-cell tables. Each pattern must define named groups:
            ``id``, ``instruction``, ``body``, and optionally ``trigger``.
            Defaults to ERCOT-style patterns (OBDRR/NPRR). Pass an empty list
            to disable amendment detection entirely.
    """

    SUPPORTED_EXTENSIONS = {".docx"}

    def __init__(
        self,
        amendment_patterns: list[re.Pattern[str]] | None = None,
    ) -> None:
        if amendment_patterns is None:
            self._amendment_patterns = DEFAULT_AMENDMENT_PATTERNS
        else:
            self._amendment_patterns = amendment_patterns

    def parse(self, file_path: Path | str) -> tuple[Book, list[ContentBlock]]:
        """Parse a DOCX file into Book metadata and ContentBlocks.

        Args:
            file_path: Path to the DOCX file

        Returns:
            Tuple of (Book metadata, list of ContentBlocks)

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"DOCX file not found: {file_path}")

        # Read file bytes for hashing
        file_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Open document
        doc = Document(file_path)

        # Extract metadata
        book = self._extract_metadata(doc, file_path, file_bytes, file_hash)

        # Extract content blocks
        blocks = self._extract_content(doc)

        # Determine structure source
        has_headings = any(_HEADING_PATTERN.match(b.source_file) for b in blocks if b.source_file)
        if has_headings:
            book = book.model_copy(update={"structure_source": "toc"})

        return book, blocks

    def _extract_metadata(
        self,
        doc: Document,
        file_path: Path,
        file_bytes: bytes,
        file_hash: str,
    ) -> Book:
        """Extract Book metadata from DOCX core properties."""
        props = doc.core_properties

        title = props.title or file_path.stem
        authors: list[str] = []
        if props.author:
            # Split on semicolons or commas (common multi-author separators)
            raw = props.author
            if ";" in raw:
                authors = [a.strip() for a in raw.split(";") if a.strip()]
            elif "," in raw:
                authors = [a.strip() for a in raw.split(",") if a.strip()]
            else:
                authors = [raw.strip()]

        first_author = authors[0] if authors else None
        book_id = Book.generate_id(file_bytes, title, first_author)

        return Book(
            id=book_id,
            title=title,
            authors=authors,
            file_hash=file_hash,
            structure_source="inferred",
        )

    def _extract_content(self, doc: Document) -> list[ContentBlock]:
        """Walk DOCX body and emit ContentBlocks."""
        blocks: list[ContentBlock] = []
        section_stack: list[str] = []
        text_accumulator: list[str] = []

        def _flush_text() -> None:
            """Flush accumulated text paragraphs as a single TEXT block."""
            if text_accumulator:
                content = "\n\n".join(text_accumulator)
                if content.strip():
                    blocks.append(
                        ContentBlock(
                            content=content,
                            content_type=ContentType.TEXT,
                            section_path=list(section_stack),
                        )
                    )
                text_accumulator.clear()

        for child in doc.element.body:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "p":
                para = Paragraph(child, doc)
                style_name = para.style.name if para.style else "Normal"
                text = para.text.strip()

                if not text:
                    continue

                # Check for heading
                heading_match = _HEADING_PATTERN.match(style_name)
                if heading_match or style_name == "Title":
                    _flush_text()
                    level = int(heading_match.group(1)) if heading_match else 0

                    # Adjust section stack based on heading level
                    # Level 1 = top-level, level 2 = sub, etc.
                    while len(section_stack) >= max(level, 1):
                        section_stack.pop()
                    section_stack.append(text)

                    # Mark the heading style in source_file for structure detection
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.TEXT,
                            section_path=list(section_stack),
                            source_file=style_name,
                        )
                    )
                    continue

                # Check for code block
                if self._is_code_style(style_name, para):
                    _flush_text()
                    language = self._detect_language(style_name, text)
                    blocks.append(
                        ContentBlock(
                            content=text,
                            content_type=ContentType.CODE,
                            section_path=list(section_stack),
                            language=language,
                        )
                    )
                    continue

                # Regular text paragraph
                text_accumulator.append(text)

            elif tag == "tbl":
                _flush_text()
                table = DocxTable(child, doc)
                amendment = self._try_parse_amendment(table)
                if amendment is not None:
                    blocks.append(
                        ContentBlock(
                            content=amendment,
                            content_type=ContentType.TEXT,
                            section_path=list(section_stack),
                        )
                    )
                else:
                    table_text = self._table_to_text(table)
                    if table_text.strip():
                        blocks.append(
                            ContentBlock(
                                content=table_text,
                                content_type=ContentType.TABLE,
                                section_path=list(section_stack),
                            )
                        )

        # Flush any remaining text
        _flush_text()

        return blocks

    def _is_code_style(self, style_name: str, para: Paragraph) -> bool:
        """Check if a paragraph has a code-like style."""
        if style_name.lower() in _CODE_STYLES:
            return True

        # Check for monospace font as a code indicator
        if para.runs:
            font = para.runs[0].font
            if font.name and any(
                mono in font.name.lower()
                for mono in ("courier", "consolas", "mono", "menlo", "source code")
            ):
                return True

        return False

    def _detect_language(self, style_name: str, text: str) -> str | None:
        """Attempt to detect programming language from style or content."""
        # Some styles encode the language
        style_lower = style_name.lower()
        for lang in ("python", "javascript", "java", "go", "rust", "sql", "shell", "bash"):
            if lang in style_lower:
                return lang

        # Simple heuristics on content
        if text.startswith("#!/"):
            return "shell"
        if text.startswith("def ") or text.startswith("import ") or text.startswith("class "):
            return "python"
        if text.startswith("SELECT ") or text.startswith("INSERT "):
            return "sql"

        return None

    def _try_parse_amendment(self, table: DocxTable) -> str | None:
        """Detect single-cell amendment boxes and format them as annotated text.

        ERCOT-style documents use single-cell tables as bordered callout boxes
        for pending amendments, e.g. "[OBDRR046: Replace paragraph a above
        with the following upon system implementation of NPRR1188:]".

        Returns formatted amendment text, or None if this is a regular table.
        """
        # Only match single-column tables
        if len(table.columns) != 1:
            return None

        # Combine all cell text (some amendment boxes span multiple rows)
        full_text = "\n".join(cell.text.strip() for row in table.rows for cell in row.cells)
        if not full_text:
            return None

        match = None
        for pattern in self._amendment_patterns:
            match = pattern.match(full_text)
            if match:
                break
        if not match:
            return None

        amendment_id = match.group("id")
        instruction = match.group("instruction").strip()
        try:
            trigger = match.group("trigger")
        except IndexError:
            trigger = None
        body = match.group("body").strip()

        header = f"[PENDING AMENDMENT — {amendment_id}"
        if trigger:
            header += f", effective upon {trigger}"
        header += "]"

        return f"{header}\n{instruction.rstrip('.')}:\n{body}"

    def _table_to_text(self, table: DocxTable) -> str:
        """Convert a DOCX table to pipe-delimited text."""
        rows: list[str] = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append("| " + " | ".join(cells) + " |")
            # Add separator after first row (header)
            if len(rows) == 1:
                rows.append("| " + " | ".join("---" for _ in cells) + " |")
        return "\n".join(rows)
