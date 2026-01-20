# Features Research

**Project:** Mnemo - Personal Technical Book Library with MCP Semantic Search
**Domain:** Personal knowledge base / document retrieval for technical books
**Researched:** 2026-01-19
**Confidence:** MEDIUM-HIGH (verified against multiple 2025-2026 sources)

---

## Table Stakes

Features users expect. Without these, the system isn't viable.

### Semantic Search (Not Just Keyword)

**Description:** Search by meaning, not exact keywords. "How do I handle errors in async code?" should find content about try/catch, error boundaries, rejection handling - even if those exact words weren't in the query.

**Complexity:** Medium
- Requires embedding model selection
- Vector database setup
- Query embedding pipeline

**Dependencies:**
- Text extraction from EPUB
- Chunking strategy
- Embedding model
- Vector store

**Why table stakes:** Users have been trained by Google's 95% first-page accuracy. Enterprise search has only 10% first-attempt success rate - that gap is what makes people abandon tools. If your search requires knowing exact keywords, users will just use Google or ask Claude directly.

**Sources:** [Shelf Knowledge Management Trends](https://shelf.io/blog/the-9-knowledge-management-trends-you-can-expect-in-2025/), [AI Knowledge Base Guide](https://www.robylon.ai/blog/ai-knowledge-base-guide-2026)

---

### Source Citation / Attribution

**Description:** Every search result must clearly show: which book, which chapter, what page/section. Users need to verify claims and read surrounding context.

**Complexity:** Medium
- Must preserve source metadata through embedding pipeline
- Results must link back to original location

**Dependencies:**
- EPUB parsing that preserves structure (chapter, section)
- Metadata storage alongside embeddings
- Result formatting that includes attribution

**Why table stakes:** RAG without citations is just "trust me bro." Research shows users need to verify AI-retrieved information. Without attribution, there's no way to: (1) confirm the information is correct, (2) read more context, (3) cite the source in their own work. Legal RAG systems without proper citation still hallucinate 17-33% of the time.

**Sources:** [Source Attribution in RAG](https://arxiv.org/abs/2507.04480), [Legal RAG Hallucinations](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)

---

### Reasonable Search Speed

**Description:** Search results in under 2-3 seconds for a personal library (~10 books). Not instant, but not painful.

**Complexity:** Low
- Vector similarity search is fast
- Small corpus makes this easy

**Dependencies:**
- Efficient vector store (even simple ones work at this scale)
- Pre-computed embeddings (don't embed at query time)

**Why table stakes:** Knowledge workers waste 9.3 hours/week searching. Slow search compounds frustration. At 10 books, this should be trivially fast - if it's slow, something is wrong.

**Sources:** [LivePro Knowledge Management Statistics](https://www.livepro.com/knowledge-management-trends-statistics/)

---

### MCP Integration (For This Specific Product)

**Description:** Expose search as MCP tools that Claude Desktop/Code can call. This IS the product's core value proposition.

**Complexity:** Medium
- MCP server implementation
- Tool definitions
- Result formatting for LLM consumption

**Dependencies:**
- Working search functionality
- MCP SDK (TypeScript or Python)

**Why table stakes:** Without MCP, this is just another search tool. The entire value proposition is "ask Claude, get answers from your books." MCP is the bridge that makes that possible.

**Sources:** [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25), [MCP Anniversary Post](https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/)

---

### Basic Book Management (Add/Remove)

**Description:** CLI commands to add EPUBs to the library and remove them. See what books are indexed.

**Complexity:** Low
- File operations
- Database/index updates

**Dependencies:**
- EPUB parsing
- Index storage

**Why table stakes:** Users need to manage their library. Without add/remove, the system is static and useless after initial setup.

---

### EPUB Text Extraction

**Description:** Extract readable text from EPUB files, handling the HTML-based format, preserving structure where possible.

**Complexity:** Low-Medium
- EPUB is HTML-based (more accessible than PDF)
- Need to handle various EPUB structures
- Preserve chapter/section boundaries

**Dependencies:**
- EPUB parsing library

**Why table stakes:** No text extraction = no search. EPUB is the input format, text is what gets embedded.

**Sources:** [Zilliz EPUB Vectorization Guide](https://zilliz.com/learn/vectorize-and-query-epub-content-with-unstructured-and-milvus)

---

## Differentiators

Features that set this apart from generic RAG tools.

### Code-Aware Chunking

**Description:** Technical books contain code blocks interspersed with prose. Standard sentence-based chunking breaks code in the middle or separates explanation from example. Code-aware chunking keeps code blocks intact and associates them with surrounding explanatory text.

**Value:** Technical book search that actually understands code. Standard RAG tools treat code as text, leading to broken snippets and lost context. Proper handling of code blocks means: (1) complete code examples in results, (2) explanatory prose stays with its code, (3) code search returns the "why" not just the "what."

**Complexity:** Medium
- Detect code blocks in HTML/EPUB
- Modified chunking strategy
- May need different embedding approach for code vs prose

**Sources:** [Roo Code Codebase Indexing](https://docs.roocode.com/features/codebase-indexing), [CodeSearchNet Challenge](https://arxiv.org/pdf/1909.09436)

---

### Chapter/Section Navigation Context

**Description:** Results include not just the matching chunk, but its location in the book's structure: "Chapter 5: Error Handling > Section 5.2: Async Errors > Understanding Promise Rejection"

**Value:** Helps users understand where in the book this information appears. A result from "Chapter 1: Introduction" has different weight than one from "Chapter 12: Advanced Patterns." Also enables browsing - "show me everything in Chapter 5."

**Complexity:** Low-Medium
- Parse EPUB table of contents
- Maintain hierarchy in metadata
- Include in search results

---

### Relevance Explanation

**Description:** Don't just return results - explain why they matched. "This section discusses async error handling, which relates to your question about Promise rejection."

**Value:** Helps users quickly assess if a result is relevant. Reduces time spent reading irrelevant sections. Builds trust in the system. Particularly valuable for technical queries where the connection might not be obvious.

**Complexity:** Medium-High
- Requires LLM call to explain relevance
- May slow down results
- Consider making this optional/on-demand

---

### Cross-Book Synthesis

**Description:** When multiple books discuss the same topic, surface that: "3 books in your library discuss this topic. Here's how their perspectives differ..."

**Value:** Unique to personal libraries - you own these books because you wanted multiple perspectives. Surfacing agreement/disagreement across books is powerful for learning.

**Complexity:** High
- Requires comparing/clustering results across books
- May need LLM to synthesize differences
- Consider for post-MVP

---

### Hybrid Search (Semantic + Keyword)

**Description:** Combine vector similarity with keyword matching. Semantic handles conceptual queries; keywords handle specific terms, error messages, function names.

**Value:** Technical content often requires exact matches: "ModuleNotFoundError", "useEffect", "O(n log n)". Pure semantic search may miss these. Hybrid catches both conceptual and literal queries.

**Complexity:** Medium
- Requires keyword index in addition to vector store
- Result fusion/ranking from two sources
- Some vector DBs support this natively

**Sources:** [Amazon Bedrock Hybrid Search](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-knowledge-bases-now-supports-hybrid-search/)

---

### Reading Progress / Annotations Sync

**Description:** Track what you've read, sync highlights/annotations from reading apps, include annotated sections in search.

**Value:** Your highlights represent what YOU found important. Including them in search surfaces personally-curated content.

**Complexity:** High
- Format-dependent (Kindle, Apple Books, etc. have different export formats)
- Sync complexity
- Consider for post-MVP

---

## Anti-Features

Things to deliberately NOT build for Mnemo.

### Full Ebook Reader

**Why not:** The goal is search and retrieval for Claude integration, not replacing Calibre or Apple Books. Building a reader is a massive scope expansion: pagination, bookmarks, highlighting, annotations, font handling, responsive layout. Users already have readers they like.

**Alternative:** Return results with enough context to be useful, plus clear attribution so users can open the book in their preferred reader at the right location.

---

### Format Conversion

**Why not:** Calibre already does this extremely well. Converting MOBI to EPUB, PDF to EPUB, etc. is a solved problem with edge cases that will consume unlimited time.

**Alternative:** Require EPUB input. Users can convert with Calibre first. Document this clearly.

---

### Cloud Sync / Multi-Device

**Why not:** Adds massive complexity: authentication, storage, conflict resolution, privacy concerns. Personal use on one machine is the explicit scope.

**Alternative:** Local-first, single-device. If users want sync, they can put the data directory in Dropbox/iCloud themselves.

---

### Social Features (Sharing, Collaboration)

**Why not:** "Personal" library means personal. Sharing introduces: permissions, privacy, copyright concerns, multi-user complexity.

**Alternative:** Single user. If someone wants to share findings, they can copy/paste or screenshot.

---

### Automatic Book Discovery / Store Integration

**Why not:** Don't try to be Goodreads or an ebook store. Scope creep toward "find books" rather than "search books you own."

**Alternative:** Users explicitly add books they own. That's the workflow.

---

### Complex Metadata Editing

**Why not:** Calibre is amazing at metadata management: cover art, series info, author disambiguation, custom columns. Don't compete.

**Alternative:** Extract and use what's in the EPUB. If users want to fix metadata, they do it in Calibre before adding to Mnemo.

---

### Natural Language Chat Interface

**Why not:** Claude IS the chat interface. Mnemo provides the search tool; Claude provides the conversation. Building a chat UI duplicates Claude's job and adds complexity.

**Alternative:** MCP tools that Claude calls. The "chat" happens in Claude Desktop/Code. Mnemo just answers queries.

---

### Automatic Re-Indexing on File Changes

**Why not:** Complexity with file watching, partial updates, determining what changed. For ~10 books, manual re-index is fine.

**Alternative:** CLI command to re-index a specific book or all books. User triggers when they add/update books.

---

### DRM Handling

**Why not:** Legal minefield. Technical complexity. Most technical books from legitimate sources (O'Reilly, Pragmatic Programmers, direct purchase) are DRM-free.

**Alternative:** Require DRM-free EPUBs. Document this requirement clearly. If users have DRM books, they handle removal themselves with appropriate tools (and legal considerations).

---

### Real-Time Embedding Updates

**Why not:** At 10 books, batch indexing is fast enough. Real-time complicates architecture significantly.

**Alternative:** Batch index command. Run when library changes.

---

## Feature Dependencies

```
EPUB Parsing
    |
    v
Text Extraction -----> Code Block Detection
    |                        |
    v                        v
Chunking Strategy <---- Code-Aware Chunking
    |
    v
Embedding Generation
    |
    v
Vector Storage -------> Keyword Index (for hybrid)
    |                        |
    v                        v
Semantic Search <------ Hybrid Search
    |
    v
Source Attribution
    |
    v
MCP Tool Exposure
    |
    v
Claude Integration (external)
```

---

## MVP Recommendation

For MVP, prioritize these table stakes + one differentiator:

### Must Have (MVP):
1. **EPUB text extraction** - Foundation for everything
2. **Basic chunking** - Can refine later
3. **Semantic search** - Core value
4. **Source citation** - Without this, results are untrustworthy
5. **MCP integration** - The product's reason for existing
6. **Basic CLI (add/remove/list)** - Minimal book management

### Should Have (MVP stretch):
7. **Code-aware chunking** - Key differentiator for technical books, not much harder than basic chunking if done from the start

### Defer to Post-MVP:
- Hybrid search (semantic alone works for initial scope)
- Cross-book synthesis (requires working search first)
- Relevance explanation (nice-to-have, not essential)
- Reading progress/annotations (high complexity, low initial value)
- Chapter/section navigation (can be added to existing search)

### Explicitly Out of Scope:
- All anti-features listed above
- Mobile/web interface
- Multiple users
- Cloud anything

---

## Sources

### Research and Analysis
- [AI Knowledge Base Guide - Robylon](https://www.robylon.ai/blog/ai-knowledge-base-guide-2026)
- [Slack AI Knowledge Base](https://slack.com/blog/productivity/what-is-an-ai-knowledge-base-tools-features-and-best-practices)
- [Knowledge Management Trends - Shelf](https://shelf.io/blog/the-9-knowledge-management-trends-you-can-expect-in-2025/)
- [Knowledge Management Statistics - LivePro](https://www.livepro.com/knowledge-management-trends-statistics/)

### RAG and Semantic Search
- [RAG Tools and Frameworks 2026](https://research.aimultiple.com/retrieval-augmented-generation/)
- [Azure AI Search RAG](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)
- [Complete Guide to RAG and Vector Databases 2026](https://solvedbycode.ai/blog/complete-guide-rag-vector-databases-2026)
- [Amazon Bedrock Hybrid Search](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-knowledge-bases-now-supports-hybrid-search/)

### RAG Pitfalls
- [23 RAG Pitfalls](https://www.nb-data.com/p/23-rag-pitfalls-and-how-to-fix-them)
- [RAG Gone Wrong - 7 Mistakes](https://www.kapa.ai/blog/rag-gone-wrong-the-7-most-common-mistakes-and-how-to-avoid-them)
- [Chunking Strategy and RAG Errors](https://ragaboutit.com/the-chunking-strategy-shift-why-semantic-boundaries-cut-your-rag-errors-by-60/)

### Code Search
- [CodeSearchNet Challenge](https://arxiv.org/pdf/1909.09436)
- [LLM Agents Improve Semantic Code Search](https://arxiv.org/html/2408.11058)
- [Roo Code Codebase Indexing](https://docs.roocode.com/features/codebase-indexing)

### EPUB and Technical Books
- [Vectorizing EPUB with Unstructured and Milvus](https://zilliz.com/learn/vectorize-and-query-epub-content-with-unstructured-and-milvus)
- [Ebook Search GitHub Project](https://github.com/derwiki/ebook-search)
- [Calibre Alternatives 2026](https://technicalwall.com/alternatives/best-calibre-alternatives/)

### Citation and Grounding
- [Source Attribution in RAG](https://arxiv.org/abs/2507.04480)
- [Hallucination Mitigation Review](https://www.mdpi.com/2227-7390/13/5/856)
- [Legal RAG Hallucinations Study](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)

### MCP Protocol
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [One Year of MCP Anniversary](https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/)

### Personal Knowledge Management
- [Second Brain Apps 2026](https://radiantapp.com/blog/best-second-brain-apps)
- [Building AI Second Brain - AFFiNE](https://affine.pro/blog/build-ai-second-brain)
- [Personal Knowledge Management Guide](https://www.glukhov.org/post/2025/07/personal-knowledge-management/)
