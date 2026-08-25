# Domain language

Terms mnemo's code and conversations use. Add an entry when a name becomes
load-bearing — when getting it wrong would produce the wrong code — not for
every noun in the codebase.

## Book

One source file taken into the library, plus its metadata: title, authors,
ISBN, language, collection, and the absolute path it was read from. Identified
two ways, and the difference matters:

- **`id`** — a 6-character hex handle, what users and MCP tools pass around.
- **`file_hash`** — SHA-256 of the file bytes, what duplicate detection uses.

Two files with identical bytes are the same Book. Two editions of the same
work are different Books that a *similar title* note may connect.

## Chunk

A passage of a Book sized for retrieval, carrying its `section_path` (the
heading hierarchy it sits under) and its `sequence` within the Book. Chunks
are what search returns and what gets embedded. Code, math and table blocks
are never split across Chunks, which is why a single Chunk can exceed the
embedding provider's per-input limit.

## Collection

A free-text label grouping related Books ("ERCOT Nodal Protocols"). Applied at
intake for fresh Books only; retagging an existing Book is
`update_book_metadata`. An empty string means no collection.

## Intake

Taking one book file into the library, and every decision that goes with it:
is the file readable, is it already indexed, does a similar title already
exist, is the ISBN plausible, and what to do with a Book that stored but did
not embed.

Intake is deliberately distinct from the **pipeline** (`ingest_book`) beneath
it, which only parses, chunks, stores and embeds. Intake decides; the pipeline
executes. Both front ends — `mnemo add` and the MCP `add_book` tool — go
through intake and render what it returns, so a rule lives in one place
instead of being decided twice.

## Intake Outcome

What intake returns instead of raising. A status, and everything a front end
needs to render it:

- **`added`** / **`replaced`** — the Book is in the library.
- **`already_indexed`** — the file was left alone (`on_duplicate="skip"`).
- **`rejected`** — nothing changed; `reason` says why.

**`embedded`** is separate from the status on purpose: a `replaced` Book can
still lose its vectors, which one tag cannot express.

## Note

An advisory finding attached to an Intake Outcome that does not change what
happened — a similar title, a suspect ISBN, embeddings that were skipped. Each
carries a `kind` for front ends to switch on and a pre-composed `message`, so
the CLI and MCP cannot word the same finding differently.

## Partial success

A Book that stored and is keyword-searchable but has no vectors. Not a
failure: the Book is durable and usable, only semantic search is missing.
Reported as a `Note`, and as `embedded: false`.
