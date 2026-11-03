"""Tests for the open_store seam and its per-call / shared modes."""

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from mnemo.vectors import VectorConfig, VectorStore, backend


@pytest.fixture(autouse=True)
def reset_mode() -> Iterator[None]:
    yield
    backend.configure("per_call")


def _cfg(path: Path) -> VectorConfig:
    return VectorConfig(persist_path=path)


def test_per_call_opens_a_fresh_store_each_time(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "chroma")
    s1 = backend.open_store(cfg)
    s2 = backend.open_store(cfg)
    try:
        assert isinstance(s1, VectorStore)
        assert isinstance(s2, VectorStore)
        assert s1 is not s2
    finally:
        s1.close()
        s2.close()


def test_shared_reuses_one_store_per_path(tmp_path: Path) -> None:
    backend.configure("shared")
    cfg = _cfg(tmp_path / "a")
    first = backend.open_store(cfg)
    second = backend.open_store(cfg)
    first.add(["c1"], [[1.0, 0.0, 0.0]], [{"book_id": "b1"}])
    assert second.count() == 1

    other = backend.open_store(_cfg(tmp_path / "b"))
    assert other.count() == 0


def test_shared_close_does_not_clear_chroma_cache(tmp_path: Path) -> None:
    target = "chromadb.api.shared_system_client.SharedSystemClient.clear_system_cache"
    backend.configure("shared")
    with patch(target) as spy:
        backend.open_store(_cfg(tmp_path / "shared")).close()
        spy.assert_not_called()

    backend.configure("per_call")
    with patch(target) as spy:
        backend.open_store(_cfg(tmp_path / "per_call")).close()
        spy.assert_called_once()


def test_leaving_shared_mode_drops_stores(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "chroma")
    backend.configure("shared")
    first = backend.open_store(cfg)
    backend.configure("per_call")
    backend.configure("shared")
    assert backend.open_store(cfg) is not first


def test_worker_mode_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError):
        backend.configure("worker")
    assert backend.current_mode() == "per_call"


def test_shutdown_is_idempotent() -> None:
    backend.shutdown()
    backend.shutdown()


def test_importing_vectors_does_not_import_chromadb() -> None:
    code = "import mnemo.vectors, mnemo.vectors.backend, sys; print('chromadb' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "False"
