"""Tests for the out-of-process Chroma worker and its idle shutdown."""

import os
import random
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from mnemo.vectors import VectorConfig, backend
from mnemo.vectors.worker import RemoteVectorStore, VectorWorker, VectorWorkerError

DIM = 8


def _unit(i: int) -> list[float]:
    vec = [0.0] * DIM
    vec[i] = 1.0
    return vec


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.fixture
def cfg(tmp_path: Path) -> VectorConfig:
    return VectorConfig(persist_path=tmp_path / "chroma")


@pytest.fixture
def make_worker() -> Iterator[Callable[[float], VectorWorker]]:
    workers: list[VectorWorker] = []

    def make(idle_seconds: float = 300.0) -> VectorWorker:
        worker = VectorWorker(idle_seconds=idle_seconds)
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.shutdown()


@pytest.fixture(autouse=True)
def reset_mode() -> Iterator[None]:
    yield
    backend.configure("per_call")


def _add_three(store: RemoteVectorStore) -> None:
    store.add(
        ["c0", "c1", "c2"],
        [_unit(0), _unit(1), _unit(2)],
        [{"book_id": "b1"}] * 3,
        ["zero", "one", "two"],
    )


def _kill_and_wait(worker: VectorWorker) -> int:
    pid = worker.pid
    assert pid is not None
    os.kill(pid, signal.SIGKILL)
    # Let poll() see the death so the next call respawns instead of racing the kernel.
    assert _wait_until(lambda: worker.pid is None)
    return pid


def test_round_trip_add_query_count_delete(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    store = RemoteVectorStore(make_worker(300.0), cfg)
    _add_three(store)
    assert store.count() == 3
    assert store.count(book_id="b1") == 3

    results = store.query(_unit(1), n_results=2)
    assert results[0]["id"] == "c1"
    assert results[0]["document"] == "one"
    assert results[0]["metadata"] == {"book_id": "b1"}

    assert store.delete_by_book("b1") == 3
    assert store.count() == 0
    store.close()


def test_worker_starts_lazily_and_stops_when_idle(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(0.3)
    store = RemoteVectorStore(worker, cfg)
    assert worker.pid is None

    assert store.count() == 0
    old_pid = worker.pid
    assert old_pid is not None

    assert _wait_until(lambda: worker.pid is None, timeout=2.0)
    with pytest.raises(ProcessLookupError):
        os.kill(old_pid, 0)


def test_next_call_after_idle_respawns(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(0.3)
    store = RemoteVectorStore(worker, cfg)
    store.count()
    old_pid = worker.pid
    assert _wait_until(lambda: worker.pid is None, timeout=2.0)

    assert store.count() == 0
    assert worker.pid is not None
    assert worker.pid != old_pid


def test_vectors_survive_idle_shutdown(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(0.3)
    store = RemoteVectorStore(worker, cfg)
    _add_three(store)
    assert _wait_until(lambda: worker.pid is None, timeout=2.0)
    assert store.count() == 3


def test_vectors_survive_worker_kill(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(300.0)
    store = RemoteVectorStore(worker, cfg)
    _add_three(store)
    _kill_and_wait(worker)
    assert store.count() == 3


def test_respawns_after_kill_between_calls(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(300.0)
    store = RemoteVectorStore(worker, cfg)
    store.count()
    old_pid = _kill_and_wait(worker)
    assert store.count() == 0
    assert worker.pid not in (None, old_pid)


def test_broken_pipe_on_write_respawns_and_retries(
    make_worker: Callable[[float], VectorWorker],
    cfg: VectorConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker(300.0)
    store = RemoteVectorStore(worker, cfg)
    store.count()
    proc = worker._proc
    assert proc is not None
    _kill_and_wait(worker)
    # Hide the death from poll() so the request write itself hits the closed pipe.
    monkeypatch.setattr(proc, "poll", lambda: None)
    assert store.count() == 0
    assert worker._proc is not proc


def test_kill_mid_call_raises_then_recovers(
    make_worker: Callable[[float], VectorWorker],
    cfg: VectorConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MNEMO_VECTOR_WORKER_TEST_DELAY", "0.5")
    worker = make_worker(300.0)
    store = RemoteVectorStore(worker, cfg)
    store.count()
    pid = worker.pid
    assert pid is not None

    errors: list[BaseException] = []

    def call() -> None:
        try:
            store.count()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=call)
    thread.start()
    time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VectorWorkerError)
    assert "count" in str(errors[0])
    assert worker.pid is None
    assert store.count() == 0


def test_child_exception_is_reraised(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    store = RemoteVectorStore(make_worker(300.0), cfg)
    _add_three(store)
    with pytest.raises(Exception, match="dimension") as excinfo:
        store.query([1.0, 0.0, 0.0, 0.0])
    assert not isinstance(excinfo.value, VectorWorkerError)
    # The worker survives a failed request.
    assert store.count() == 3


def test_unknown_method_is_rejected(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(300.0)
    method: Any = "close"
    with pytest.raises(Exception, match="close"):
        worker.call(cfg, method)


def test_worker_stdout_noise_is_harmless(
    make_worker: Callable[[float], VectorWorker],
    cfg: VectorConfig,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MNEMO_VECTOR_WORKER_TEST_PRINT", "1")
    worker = make_worker(300.0)
    store = RemoteVectorStore(worker, cfg)
    _add_three(store)
    assert store.count() == 3
    assert store.query(_unit(2), n_results=1)[0]["id"] == "c2"
    worker.shutdown()
    assert capfd.readouterr().out == ""


def test_idle_shutdown_races_concurrent_callers(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    store = RemoteVectorStore(make_worker(0.05), cfg)
    errors: list[BaseException] = []

    def hammer(seed: int) -> None:
        rng = random.Random(seed)
        try:
            for _ in range(25):
                store.count()
                time.sleep(rng.uniform(0.0, 0.1))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []


def test_calls_after_shutdown_raise(
    make_worker: Callable[[float], VectorWorker], cfg: VectorConfig
) -> None:
    worker = make_worker(300.0)
    store = RemoteVectorStore(worker, cfg)
    store.count()
    pid = worker.pid
    assert pid is not None
    worker.shutdown()
    worker.shutdown()
    assert worker.pid is None
    assert _gone(pid)
    with pytest.raises(VectorWorkerError):
        store.count()
    assert worker.pid is None


def test_worker_mode_open_store_returns_remote(cfg: VectorConfig) -> None:
    backend.configure("worker", 300)
    store = backend.open_store(cfg)
    assert isinstance(store, RemoteVectorStore)
    worker = backend.current_worker()
    assert worker is not None
    assert store.count() == 0
    pid = worker.pid
    assert pid is not None

    backend.configure("per_call")
    assert worker.pid is None
    assert _gone(pid)
    assert backend.current_worker() is None


def test_backend_shutdown_stops_worker_and_next_open_respawns(cfg: VectorConfig) -> None:
    backend.configure("worker", 300)
    backend.open_store(cfg).count()
    first = backend.current_worker()
    assert first is not None
    backend.shutdown()
    assert first.pid is None
    assert backend.current_mode() == "worker"

    assert backend.open_store(cfg).count() == 0
    second = backend.current_worker()
    assert second is not None
    assert second is not first


_PARENT_SCRIPT = """
import sys
from pathlib import Path
from mnemo.vectors import VectorConfig, backend
backend.configure("worker", 300)
store = backend.open_store(VectorConfig(persist_path=Path(sys.argv[1])))
store.add(["a"], [[1.0] * 8], [{"book_id": "b"}])
assert store.count() == 1
try:
    store.query([1.0] * 4)
except Exception as exc:
    assert "dimension" in str(exc)
backend.shutdown()
print("chromadb" in sys.modules)
"""


def test_worker_mode_keeps_chromadb_out_of_the_parent(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PARENT_SCRIPT, str(tmp_path / "chroma")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
