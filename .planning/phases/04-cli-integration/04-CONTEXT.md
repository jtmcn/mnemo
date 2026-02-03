# Phase 4: CLI & Integration - Context

**Gathered:** 2026-02-01
**Status:** Ready for planning

<domain>
## Phase Boundary

User-facing command line interface to manage the book library and start the MCP server. Wraps existing functionality (parsing, indexing, search) into five commands:
- `mnemo add <path>` — add EPUB(s) to library
- `mnemo remove <book_id>` — remove book
- `mnemo list` — list indexed books
- `mnemo search <query>` — test search from terminal
- `mnemo serve` — start MCP server for Claude

</domain>

<decisions>
## Implementation Decisions

### Output Formatting
- Rich tables with box-drawn borders for `list` command
- Colors with auto-detect: use colors when TTY detected, plain when piped or redirected
- Verbosity: quiet by default, `-v` flag adds detail
- `--json` flag on all commands for machine-readable output (scripting/piping)

### Error Handling
- Missing file: clear error message, exit 1 ("File not found: path/to/book.epub")
- API failure mid-indexing: fail completely, delete partial work, user must re-run
- Duplicate book (same file hash): prompt user "Book exists. Re-index? [y/N]"
- Remove non-existent book: warning but exit 0 ("Book not found (already removed?)")

### Add Workflow
- Progress: stage updates ("Parsing... Chunking... Embedding... Done.")
- Completion: summary stats ("Added: Title by Author (abc123) — 342 chunks, 12 chapters")
- Multiple paths supported: `mnemo add *.epub` processes each sequentially
- Batch failure: stop on first error, fail fast

### Search Output
- Default: 5 results
- Snippets: show full chunk content
- Attribution: hierarchical path ("Book Title > Chapter 3 > Section: Handling Errors")
- Filters: `--book <id>` to limit to specific book (no type filter)

### Claude's Discretion
- CLI framework choice (click, typer, argparse)
- Exact progress stage granularity
- Color palette for rich output
- Table column widths and alignment

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches for CLI tooling.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-cli-integration*
*Context gathered: 2026-02-01*
