"""The seam for opening vector stores.

per_call: a fresh VectorStore per open (CLI, tests).
shared: one VectorStore per path for the process lifetime (MCP server).
worker: Chroma runs in a child process that stops when idle.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Literal, Protocol

from mnemo.vectors.config import VectorConfig
from mnemo.vectors.worker import RemoteVectorStore, VectorWorker

if TYPE_CHECKING:
    from mnemo.vectors.store import QueryResult, VectorStore

VectorMode = Literal["per_call", "shared", "worker"]


class VectorBackend(Protocol):
    """What callers need from a vector store, wherever it lives."""

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None: ...

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
    ) -> list[QueryResult]: ...

    def delete_by_book(self, book_id: str) -> int: ...

    def count(self, book_id: str | None = None) -> int: ...

    def close(self) -> None: ...


class _SharedHandle:
    """Delegates to a process-wide store; close() is a no-op so the client stays cached."""

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        self._store.add(ids, embeddings, metadatas, documents)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
    ) -> list[QueryResult]:
        return self._store.query(query_embedding, n_results, book_id, content_type)

    def delete_by_book(self, book_id: str) -> int:
        return self._store.delete_by_book(book_id)

    def count(self, book_id: str | None = None) -> int:
        return self._store.count(book_id)

    def close(self) -> None:
        # Chroma's clear_system_cache() leaks ~125 MB per open/close cycle.
        return None


_lock = threading.Lock()
_mode: VectorMode = "per_call"
_shared: dict[tuple[str, str], VectorStore] = {}
_worker: VectorWorker | None = None
_idle_seconds = 300.0


def configure(mode: VectorMode, idle_seconds: float = 300.0) -> None:
    """Select how open_store() opens stores; leaving a mode releases its resources."""
    global _mode, _idle_seconds
    with _lock:
        if mode != _mode:
            _release_locked()
        _mode = mode
        _idle_seconds = idle_seconds
        if _worker is not None:
            # Keep the worker: open handles hold it, and the new delay applies from the next call.
            _worker.idle_seconds = idle_seconds


def current_mode() -> VectorMode:
    return _mode


def current_worker() -> VectorWorker | None:
    """The process-wide worker in worker mode, else None."""
    return _worker if _mode == "worker" else None


def open_store(config: VectorConfig | None = None) -> VectorBackend:
    global _worker
    config = config or VectorConfig()
    with _lock:
        if _mode == "worker":
            if _worker is None:
                _worker = VectorWorker(_idle_seconds)
            return RemoteVectorStore(_worker, config)

        # Only the in-process modes load chromadb.
        from mnemo.vectors.store import VectorStore

        if _mode != "shared":
            return VectorStore(config)
        key = (str(config.get_persist_path()), config.collection_name)
        store = _shared.get(key)
        if store is None:
            store = _shared[key] = VectorStore(config)
        return _SharedHandle(store)


def shutdown() -> None:
    """Release everything the current mode holds. Safe to call repeatedly."""
    with _lock:
        _release_locked()


def _release_locked() -> None:
    global _worker
    # Dropping references lets Chroma's cached clients be collected.
    _shared.clear()
    if _worker is not None:
        _worker.shutdown()
        _worker = None
