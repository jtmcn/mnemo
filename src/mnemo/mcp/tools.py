"""Re-export shim for backward compatibility.

Original tools.py was split into domain modules in Phase 18.
Tests and external code that import from mnemo.mcp.tools continue to work.
"""

# Re-export all _impl functions and public tools for backward compat
# Re-export asyncio for tests that patch mnemo.mcp.tools.asyncio
import asyncio  # noqa: F401

from mnemo.mcp.formatters import (  # noqa: F401
    _format_enriched_results,
    _format_mixed_results,
    _format_search_results,
    _truncate_at_boundary,
)
from mnemo.mcp.tools_books import (  # noqa: F401
    _add_book_impl,
    _reindex_all_books_impl,
    _remove_book_impl,
    add_book,
    reindex_all_books,
)
from mnemo.mcp.tools_metadata import (  # noqa: F401
    _enrich_book_impl,
    _get_book_info_impl,
    _list_available_books_impl,
    _update_book_metadata_impl,
)
from mnemo.mcp.tools_search import (  # noqa: F401
    _get_book_chunks_impl,
    _get_book_structure_impl,
    _search_books_impl,
)
from mnemo.mcp.tools_search import _make_book_repo as _get_book_repo  # noqa: F401
from mnemo.mcp.tools_search import _make_chunk_repo as _get_chunk_repo  # noqa: F401

# Re-export domain module factory functions (tests that patch these)
from mnemo.mcp.tools_search import _make_search_service as _get_search_service  # noqa: F401

# Re-export storage helpers used in add_book tests (tests patch these on this module)
from mnemo.storage import BookRepository, get_connection, init_db  # noqa: F401

# Module-level globals for test patching compatibility.
# Tests that set tools._search_service or tools._db_connection need these.
# Note: setting these on the shim module does NOT affect domain module globals.
# Tests calling _impl functions should instead pass deps as parameters.
# These are kept here only for tests that call @mcp.tool wrappers (which use
# domain module globals) — such tests should patch on the domain module directly.
_search_service = None
_db_connection = None
