---
phase: 01-foundation
plan: 04
type: execute
wave: 3
depends_on: ["01-02"]
files_modified:
  - src/mnemo/chunking/__init__.py
  - src/mnemo/chunking/chunker.py
  - src/mnemo/chunking/tokenizer.py
  - tests/test_chunker.py
autonomous: true

must_haves:
  truths:
    - "Text is split into 400-800 token chunks with overlap"
    - "Code blocks are never split"
    - "Each chunk knows its section context"
    - "Chunks are labeled by content type"
    - "Adjacent chunks are linked (prev/next)"
  artifacts:
    - path: "src/mnemo/chunking/chunker.py"
      provides: "Smart chunking logic"
      exports: ["Chunker"]
    - path: "src/mnemo/chunking/tokenizer.py"
      provides: "Token counting with tiktoken"
      exports: ["count_tokens"]
  key_links:
    - from: "src/mnemo/chunking/chunker.py"
      to: "src/mnemo/epub/content.py"
      via: "ContentBlock input"
      pattern: "ContentBlock"
    - from: "src/mnemo/chunking/chunker.py"
      to: "src/mnemo/models.py"
      via: "Chunk output"
      pattern: "from mnemo.models import Chunk"
---

<objective>
Build smart chunker that respects code blocks, tracks context, and links adjacent chunks.

Purpose: Transform ContentBlocks from the parser into properly-sized Chunks that preserve code integrity and maintain context for effective retrieval.

Output: Chunker class that produces linked Chunk objects from ContentBlocks.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-foundation/01-CONTEXT.md
@.planning/phases/01-foundation/01-01-SUMMARY.md
@.planning/phases/01-foundation/01-02-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Implement token counting</name>
  <files>src/mnemo/chunking/__init__.py, src/mnemo/chunking/tokenizer.py</files>
  <action>
Create src/mnemo/chunking/__init__.py exporting chunker components.

Create tokenizer.py with tiktoken-based token counting:

```python
import tiktoken

# Use cl100k_base (GPT-4/Claude compatible tokenizer)
_encoder = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    """Count tokens in text using cl100k_base encoding."""
    return len(_encoder.encode(text))

def split_by_tokens(text: str, max_tokens: int, overlap_tokens: int = 50) -> list[str]:
    """
    Split text into chunks of max_tokens with overlap.

    Returns list of text chunks, each <= max_tokens.
    Overlap added at start of each chunk (except first).
    Splits on sentence boundaries when possible.
    """
```

Implementation notes for split_by_tokens:
1. Encode entire text to tokens
2. Find split points at sentence boundaries (. ! ?)
3. If no sentence boundary in range, split on word boundary
4. Add overlap_tokens from previous chunk to start of next
5. Decode tokens back to text

Edge cases:
- Single word longer than max_tokens -> keep as-is (rare, but handle)
- Text shorter than max_tokens -> return as single chunk
- Overlap larger than chunk -> reduce overlap
  </action>
  <verify>
```python
from mnemo.chunking.tokenizer import count_tokens, split_by_tokens
assert count_tokens("Hello world") > 0
chunks = split_by_tokens("A" * 1000, max_tokens=100)
assert all(count_tokens(c) <= 100 for c in chunks)
```
  </verify>
  <done>count_tokens returns accurate counts, split_by_tokens produces valid chunks with overlap</done>
</task>

<task type="auto">
  <name>Task 2: Implement smart chunker</name>
  <files>src/mnemo/chunking/chunker.py</files>
  <action>
Create chunker.py with Chunker class:

```python
from dataclasses import dataclass
from mnemo.models import Chunk, ContentType
from mnemo.epub.content import ContentBlock
from mnemo.chunking.tokenizer import count_tokens, split_by_tokens
import uuid

@dataclass
class ChunkerConfig:
    min_tokens: int = 400
    max_tokens: int = 800
    overlap_tokens: int = 50

class Chunker:
    def __init__(self, config: ChunkerConfig | None = None):
        self.config = config or ChunkerConfig()

    def chunk(self, book_id: str, blocks: list[ContentBlock]) -> list[Chunk]:
        """
        Convert ContentBlocks to Chunks with proper sizing and linking.

        Rules:
        1. CODE/DIAGRAM/MATH/TABLE blocks: Never split, keep as single chunk
           (even if > max_tokens)
        2. TEXT blocks: Split to min-max token range with overlap
        3. Track section boundaries for spanning chunks
        4. Link adjacent chunks (prev_chunk_id, next_chunk_id)
        """
```

Chunking algorithm:
1. Process blocks in order, maintaining:
   - current_sequence: int (global chunk order)
   - previous_chunk: Chunk | None (for linking)

2. For each ContentBlock:
   - If CODE/DIAGRAM/MATH/TABLE:
     - Create single Chunk with full content
     - No size limit enforcement
   - If TEXT:
     - If tokens <= max_tokens: create single chunk
     - If tokens > max_tokens: use split_by_tokens()
     - Track if split spans section boundary -> populate sections list

3. Linking logic:
   - After creating chunk, set prev_chunk_id to previous_chunk.id
   - Update previous_chunk.next_chunk_id to current chunk.id
   - This requires two passes or mutable update

4. Section spanning:
   - Track current_section_path
   - If block has different section_path, note transition
   - For TEXT chunks that span: sections = [old_section, new_section]

Generate UUIDs for chunk IDs using uuid.uuid4().
  </action>
  <verify>
```python
from mnemo.chunking.chunker import Chunker, ChunkerConfig
from mnemo.epub.content import ContentBlock
from mnemo.models import ContentType

config = ChunkerConfig(min_tokens=10, max_tokens=50)
chunker = Chunker(config)

blocks = [
    ContentBlock(content="Short text.", content_type=ContentType.TEXT,
                 section_path=["Ch1"], language=None, source_file="ch1.html"),
    ContentBlock(content="def foo():\n    return 42", content_type=ContentType.CODE,
                 section_path=["Ch1"], language="python", source_file="ch1.html"),
]
chunks = chunker.chunk("book123", blocks)
assert len(chunks) >= 2
assert chunks[1].content_type == ContentType.CODE
```
  </verify>
  <done>Chunker produces properly-sized, linked chunks that never split code blocks</done>
</task>

<task type="auto">
  <name>Task 3: Add comprehensive tests</name>
  <files>tests/test_chunker.py</files>
  <action>
Create tests/test_chunker.py with comprehensive test coverage:

1. Token counting tests:
   - test_count_tokens_empty_string
   - test_count_tokens_simple_text
   - test_count_tokens_code_with_indentation

2. Text splitting tests:
   - test_split_short_text_no_split
   - test_split_long_text_multiple_chunks
   - test_split_respects_max_tokens
   - test_split_adds_overlap
   - test_split_on_sentence_boundary

3. Code block tests (CRITICAL):
   - test_code_block_never_split
   - test_large_code_block_stays_intact (>max_tokens)
   - test_code_preserves_indentation
   - test_code_preserves_language

4. Section tracking tests:
   - test_chunks_have_section_path
   - test_boundary_spanning_chunk_lists_both_sections

5. Linking tests:
   - test_first_chunk_no_prev
   - test_last_chunk_no_next
   - test_middle_chunks_linked_both_ways

6. Integration tests:
   - test_mixed_content_types
   - test_empty_blocks_list
   - test_single_block
  </action>
  <verify>pytest tests/test_chunker.py -v --tb=short</verify>
  <done>All chunker tests pass, especially code block preservation tests</done>
</task>

</tasks>

<verification>
```bash
# All tests
pytest tests/test_chunker.py -v

# Import check
python -c "from mnemo.chunking import Chunker, count_tokens; print('Chunker OK')"

# Code block integrity verification
python -c "
from mnemo.chunking.chunker import Chunker, ChunkerConfig
from mnemo.epub.content import ContentBlock
from mnemo.models import ContentType

# Create a large code block (> max_tokens)
large_code = 'def example():\n' + '    x = 1\n' * 100
config = ChunkerConfig(max_tokens=50)  # Very small max
chunker = Chunker(config)

blocks = [ContentBlock(
    content=large_code,
    content_type=ContentType.CODE,
    section_path=['Ch1'],
    language='python',
    source_file='test.html'
)]
chunks = chunker.chunk('book1', blocks)

# Must be exactly 1 chunk, never split
assert len(chunks) == 1, f'Code was split into {len(chunks)} chunks!'
assert chunks[0].content == large_code, 'Code content was modified!'
print('Code block integrity verified!')
"
```
</verification>

<success_criteria>
1. Text chunks are 400-800 tokens (configurable)
2. Code blocks NEVER split, regardless of size
3. Overlap tokens added between text chunks
4. Each chunk has correct section_path
5. Boundary-spanning chunks list both sections
6. Chunks linked via prev_chunk_id/next_chunk_id
7. All content types preserved (CODE, TABLE, DIAGRAM, MATH, TEXT)
8. All tests pass
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-04-SUMMARY.md`
</output>
