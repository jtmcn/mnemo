"""Run Chroma in a child process that stops when idle.

Chroma's Rust core never returns HNSW index memory inside a process; only exit
does. The parent side of this module must never import chromadb.
"""

from __future__ import annotations

import os
import pickle
import signal
import struct
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, cast, get_args

from mnemo.vectors.config import VectorConfig

if TYPE_CHECKING:
    from mnemo.vectors.store import QueryResult, VectorStore

VectorMethod = Literal["add", "query", "delete_by_book", "count"]

_METHODS: frozenset[str] = frozenset(get_args(VectorMethod))
_HEADER = struct.Struct("!I")
_STOP_TIMEOUT = 10.0


def write_frame(stream: BinaryIO, obj: object) -> None:
    payload = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(payload)) + payload)
    stream.flush()


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = stream.read(size - len(buf))
        if not chunk:
            raise EOFError("vector worker stream closed")
        buf += chunk
    return bytes(buf)


def read_frame(stream: BinaryIO) -> object:
    (size,) = _HEADER.unpack(_read_exact(stream, _HEADER.size))
    return pickle.loads(_read_exact(stream, size))


class VectorWorkerError(RuntimeError):
    """The worker process died or could not be reached."""


class VectorWorker:
    """Owns one child process running Chroma; spawns it lazily and stops it when idle."""

    def __init__(self, idle_seconds: float) -> None:
        self.idle_seconds = idle_seconds
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._stdin: BinaryIO | None = None
        self._stdout: BinaryIO | None = None
        self._timer: threading.Timer | None = None
        self._last_used = 0.0
        self._closed = False

    @property
    def pid(self) -> int | None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return None
        return proc.pid

    def call(self, config: VectorConfig, method: VectorMethod, *args: Any, **kwargs: Any) -> Any:
        request = (config, method, args, kwargs)
        with self._lock:
            if self._closed:
                raise VectorWorkerError("vector worker is shut down")
            try:
                stdout = self._send_locked(request, method)
                reply = read_frame(stdout)
            except (EOFError, OSError, pickle.UnpicklingError) as exc:
                # No retry: the child may have committed an add before dying.
                self._stop_locked()
                raise VectorWorkerError(f"vector worker exited during {method}") from exc
            except BaseException:
                # An interrupted exchange leaves the stream out of step; start fresh next call.
                self._stop_locked()
                raise
            finally:
                self._last_used = time.monotonic()
                self._arm_timer_locked(self.idle_seconds)
        status, value = cast("tuple[str, Any]", reply)
        if status == "err":
            raise cast(BaseException, value)
        return value

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._stop_locked()

    def _send_locked(self, request: object, method: str) -> BinaryIO:
        for _ in range(2):
            stdin, stdout = self._ensure_running_locked()
            try:
                write_frame(stdin, request)
                return stdout
            except BrokenPipeError:
                # The child died before reading the request, so a retry can't double-apply.
                self._stop_locked()
        raise VectorWorkerError(f"vector worker exited before {method}")

    def _ensure_running_locked(self) -> tuple[BinaryIO, BinaryIO]:
        if self._proc is not None and self._proc.poll() is not None:
            self._stop_locked()
        if self._proc is None:
            # -P keeps the host's cwd off sys.path so project files can't shadow imports.
            proc = subprocess.Popen(
                [sys.executable, "-P", "-m", "mnemo.vectors.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
            )
            self._proc = proc
            self._stdin = cast(BinaryIO, proc.stdin)
            self._stdout = cast(BinaryIO, proc.stdout)
        assert self._stdin is not None and self._stdout is not None
        return self._stdin, self._stdout

    def _stop_locked(self) -> None:
        proc, stdin, stdout = self._proc, self._stdin, self._stdout
        if proc is None:
            return
        try:
            try:
                if stdin is not None:
                    stdin.close()
            except OSError:
                pass  # unflushed bytes to a dead child; the fd is closed regardless
            if stdout is not None:
                # A child blocked writing an unread reply gets EPIPE instead of hanging the wait.
                stdout.close()
            try:
                proc.wait(timeout=_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        finally:
            # Cleared only once reaped, so pid stays set until the process is gone.
            self._proc = self._stdin = self._stdout = None

    def _arm_timer_locked(self, delay: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        timer = threading.Timer(delay, self._on_idle)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _on_idle(self) -> None:
        with self._lock:
            # A newer call re-armed the timer, or the worker is already gone.
            if threading.current_thread() is not self._timer or self._proc is None:
                return
            remaining = self.idle_seconds - (time.monotonic() - self._last_used)
            if remaining > 0:
                self._arm_timer_locked(remaining)
                return
            self._timer = None
            self._stop_locked()


class RemoteVectorStore:
    """A VectorBackend whose calls run in the worker process."""

    def __init__(self, worker: VectorWorker, config: VectorConfig) -> None:
        self._worker = worker
        self._config = config

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        self._worker.call(self._config, "add", ids, embeddings, metadatas, documents)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        book_id: str | None = None,
        content_type: str | None = None,
    ) -> list[QueryResult]:
        result = self._worker.call(
            self._config, "query", query_embedding, n_results, book_id, content_type
        )
        return cast("list[QueryResult]", result)

    def delete_by_book(self, book_id: str) -> int:
        return int(self._worker.call(self._config, "delete_by_book", book_id))

    def count(self, book_id: str | None = None) -> int:
        return int(self._worker.call(self._config, "count", book_id))

    def close(self) -> None:
        # The worker outlives handles; idle shutdown or backend.shutdown() stops it.
        return None


def _portable(exc: Exception) -> BaseException:
    # Unpickling a chromadb exception would import chromadb in the parent.
    if type(exc).__module__ == "builtins":
        try:
            return cast(BaseException, pickle.loads(pickle.dumps(exc)))
        except Exception:
            pass
    return RuntimeError(f"{type(exc).__name__}: {exc}")


def main() -> None:
    # Keep the real stdout for frames and send stray prints to stderr, before chromadb loads.
    ipc_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    # The parent ends this process by closing stdin; a terminal Ctrl-C shouldn't.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    test_delay = float(os.environ.get("MNEMO_VECTOR_WORKER_TEST_DELAY") or 0)
    test_print = os.environ.get("MNEMO_VECTOR_WORKER_TEST_PRINT") == "1"

    from mnemo.vectors.store import VectorStore

    stores: dict[tuple[str, str], VectorStore] = {}
    ipc_in = sys.stdin.buffer
    while True:
        try:
            frame = read_frame(ipc_in)
        except EOFError:
            return
        config, method, args, kwargs = cast(
            "tuple[VectorConfig, str, tuple[Any, ...], dict[str, Any]]", frame
        )
        reply: tuple[str, object]
        try:
            if method not in _METHODS:
                raise ValueError(f"unknown vector method: {method!r}")
            key = (str(config.get_persist_path()), config.collection_name)
            store = stores.get(key)
            if store is None:
                # Never closed: Chroma's clear_system_cache() leaks rather than frees.
                store = stores[key] = VectorStore(config)
            reply = ("ok", getattr(store, method)(*args, **kwargs))
        except Exception as exc:
            reply = ("err", _portable(exc))
        if test_delay:
            time.sleep(test_delay)
        if test_print:
            print("vector worker test noise (sys.stdout)")
            os.write(1, b"vector worker test noise (fd 1)\n")
        try:
            write_frame(ipc_out, reply)
        except BrokenPipeError:
            return


if __name__ == "__main__":
    main()
    # Skip chromadb's posthog atexit join (~0.7 s per stop); its writes already survive SIGKILL.
    sys.stderr.flush()
    os._exit(0)
