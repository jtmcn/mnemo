# Vector Worker Idle Unload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A long-lived `mnemo serve` process gives back the ~200 MB and ~24 threads that vector search loads once it has been idle, and stops growing ~125 MB on every add/remove/reindex.

**Architecture:** All Chroma access goes through one seam, `mnemo.vectors.backend.open_store()`. Short-lived processes (CLI, tests) keep today's per-call `VectorStore`. The MCP server instead routes every vector call to a child process (`python -m mnemo.vectors.worker`) that speaks length-prefixed pickle frames over its stdin/stdout, and stops it after `MNEMO_VECTOR_IDLE_SECONDS` without calls. The OS reclaims everything when the child exits. Task 1 ships the leak fix alone.

**Tech Stack:** Python 3.11–3.13, chromadb 1.5 (Rust core), fastmcp 4.1, stdlib `subprocess`/`threading`/`pickle`/`struct`.

**Spec:** the Findings section below; there is no separate spec. The measurements were taken 2026-11-02 against the live library (5,682 vectors × 4096 dims, `~/.mnemo/chroma` = 204 MB).

## Findings (why not unload in-process)

| Experiment | Result |
|---|---|
| Search loads Chroma; then `VectorStore.close()` + drop refs + `gc` + `malloc_zone_pressure_relief` | RSS 346.8 → **346.8 MB**: nothing is freed |
| Reload after that release | +127 MB (473.6 MB) |
| `open → count → close` ×4 in one process | 114 → 287 → 416 → 543 → **666 MB** |
| Same loop without `close()` (no `clear_system_cache()`) | 114 → 290 → 292 → 292 → **292 MB**: flat |
| Chroma `chroma_segment_cache_policy="LRU"`, `chroma_memory_limit_bytes=16 MB` | still ~250 MB: not honoured for the HNSW index |
| Child process does open + query and exits; parent never imports chromadb | parent 15.9 MB before and after; child peak 253 MB; cold start **1.13 s** |

So in-process unloading cannot work. `close()` is what causes the per-mutation leak, and only process exit returns the memory. Hybrid search already spends ~2.8 s on the embeddings API, so a ~1.1 s cold start after idle is acceptable.

## Global Constraints

- No new runtime dependencies. Python `>=3.11,<3.14`. `mypy src/` strict stays clean.
- No new `# type: ignore`, `# noqa`, or test skips (the `integrity` gate).
- Code comments: 1–2 lines, why-only (user CLAUDE.md).
- The MCP server's fd 1 is the JSON-RPC stream. Nothing may write to it except fastmcp.
- `MNEMO_VECTOR_IDLE_SECONDS`: default `300`. `0` = keep Chroma in-process, shared, never unloaded. A negative or non-numeric value logs a warning and uses `300`.
- Worker mode is switched on only in the serve entry path (`mnemo.mcp.server.run()`), never at `server.py` import: `tests/test_mcp.py` imports the server, and enabling it there would flip the global for the whole pytest process.
- Version → `3.4.0` in `pyproject.toml`, `CLAUDE.md`, `uv.lock` (Task 3).

## Review Focus

1. Chroma or anything in the worker prints to stdout → neither the MCP stream nor the IPC channel is corrupted (Task 2: `test_worker_stdout_noise_is_harmless`).
2. Idle shutdown fires while another thread is mid-call or about to call. `add_book` runs in `asyncio.to_thread` while search runs on the loop thread → no call fails (Task 2: `test_idle_shutdown_races_concurrent_callers`).
3. Worker killed between calls → next call respawns and succeeds. Killed mid-call → that call raises `VectorWorkerError`, the next succeeds (Task 2: `test_respawns_after_kill_between_calls`, `test_kill_mid_call_raises_then_recovers`).
4. Vectors added just before an idle shutdown or a SIGKILL are still there after respawn (Task 2: `test_vectors_survive_idle_shutdown`, `test_vectors_survive_worker_kill`).
5. Parent exits normally or is SIGKILLed → the worker is gone within 5 s and doesn't hold `~/.mnemo/chroma` (Task 3: `test_worker_exits_with_parent`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/mnemo/vectors/__init__.py` | Lazy re-exports (`__getattr__`), so importing the package never imports chromadb |
| `src/mnemo/vectors/backend.py` (new) | `VectorBackend` protocol, mode switch, `open_store()`, `shutdown()` |
| `src/mnemo/vectors/worker.py` (new) | Frame helpers, child `main()`, parent `VectorWorker` + `RemoteVectorStore` |
| `src/mnemo/ingest.py:99-101, 155, 432-436` | Open stores via `open_store()` |
| `src/mnemo/search/service.py:127, 796-801` | Open its store via `open_store()` |
| `src/mnemo/mcp/server.py`, `mcp/__main__.py`, `cli.py:772-779` | `run()` entry that configures vectors, then serves |
| `tests/test_vector_backend.py`, `tests/test_vector_worker.py` (new), `tests/test_mcp.py` | Tests |
| `README.md:109-110`, `.env.example` | Document `MNEMO_VECTOR_IDLE_SECONDS` |

---

### Task 1: One seam for opening stores; the server shares one store per path (fixes the leak)

**Files:**
- Create: `src/mnemo/vectors/backend.py`
- Modify: `src/mnemo/vectors/__init__.py`, `src/mnemo/ingest.py` (3 sites), `src/mnemo/search/service.py:127,796-801`, `src/mnemo/mcp/server.py`, `src/mnemo/mcp/__main__.py`, `src/mnemo/cli.py:772-779`
- Test: `tests/test_vector_backend.py`, `tests/test_mcp.py`

**Interfaces:**
- Produces, in `mnemo.vectors.backend`:
  - `VectorMode = Literal["per_call", "shared", "worker"]`
  - `class VectorBackend(Protocol)` with exactly `VectorStore`'s public signatures: `add(ids: list[str], embeddings: list[list[float]], metadatas: list[dict[str, Any]], documents: list[str] | None = None) -> None`, `query(query_embedding: list[float], n_results: int = 10, book_id: str | None = None, content_type: str | None = None) -> list[QueryResult]`, `delete_by_book(book_id: str) -> int`, `count(book_id: str | None = None) -> int`, `close() -> None`
  - `configure(mode: VectorMode, idle_seconds: float = 300.0) -> None`. Leaving a mode releases its resources (drops shared stores; shuts down a worker once Task 2 exists).
  - `current_mode() -> VectorMode` (default `"per_call"`)
  - `open_store(config: VectorConfig | None = None) -> VectorBackend`
  - `shutdown() -> None` (idempotent)
- Produces, in `mnemo.mcp.server`: `run() -> None`

- [ ] **Step 1: Write the failing tests** in `tests/test_vector_backend.py`, each using a `tmp_path` Chroma dir and restoring `configure("per_call")` in a fixture finalizer:
  - `test_per_call_opens_a_fresh_store_each_time`: two `open_store(cfg)` → `isinstance(s, VectorStore)` and `s1 is not s2`.
  - `test_shared_reuses_one_store_per_path`: after `configure("shared")`, an `add` through one handle is visible to `count()` through a second handle for the same path. A different `persist_path` gives an independent count.
  - `test_shared_close_does_not_clear_chroma_cache`: patch `chromadb.api.shared_system_client.SharedSystemClient.clear_system_cache` with a spy; `configure("shared")`; `open_store(cfg).close()` → spy not called. In `per_call` mode → called once.
  - `test_importing_vectors_does_not_import_chromadb`: `subprocess.run([sys.executable, "-c", "import mnemo.vectors, mnemo.vectors.backend, sys; print('chromadb' in sys.modules)"])` → stdout `"False"`.
  - In `tests/test_mcp.py`, `test_run_configures_shared_vectors`: patch `mnemo.mcp.server.mcp.run`; call `run()` → `current_mode() == "shared"`; restore `per_call`.

- [ ] **Step 2: Run them to verify they fail.** Run: `pytest tests/test_vector_backend.py tests/test_mcp.py -k "per_call or shared or importing_vectors or run_configures" -v`. Expected: FAIL (`ModuleNotFoundError: mnemo.vectors.backend`).

- [ ] **Step 3: Implement.**
  - `backend.py`: module-level state guarded by a `threading.Lock`. In `shared` mode, keep `dict[tuple[str, str], VectorStore]` keyed by `(str(config.get_persist_path()), config.collection_name)` and return a small handle that delegates the four data methods and makes `close()` a no-op. Import `VectorStore` inside `open_store`, not at module top.
  - `vectors/__init__.py`: `__getattr__` lazy exports, the same pattern as `mnemo/mcp/__init__.py`. `VectorConfig` can stay an eager import (`config.py` has no chromadb import).
  - Replace `VectorStore(...)` with `open_store(...)` at `ingest.py:101`, `:155`, `:434`, and in `SearchService._ensure_initialized`. Type `SearchService._vector_store` as `VectorBackend | None`. Callers keep calling `close()`.
  - `server.py`: `run()` calls `configure("shared")`, `atexit.register(backend.shutdown)`, then `mcp.run()`. `cli.serve`, `mcp/__main__.py` and `server.py`'s `__main__` block call `run()`.

- [ ] **Step 4: Run the tests to verify they pass**, then the full gates: `ruff format --check src/ tests/ && ruff check src/ tests/ && mypy src/ && pytest -m "not integration" -q`. Expected: all pass.

- [ ] **Step 5: Commit.** `git commit -m "fix: share one Chroma store per path in the server instead of leaking one per mutation"`

---

### Task 2: Out-of-process vector worker with idle shutdown

**Files:**
- Create: `src/mnemo/vectors/worker.py`
- Modify: `src/mnemo/vectors/backend.py` (add the `"worker"` branch)
- Test: `tests/test_vector_worker.py`

**Interfaces:**
- Consumes: `VectorBackend`, `configure`, `open_store`, `shutdown` from Task 1.
- Produces, in `mnemo.vectors.worker`:
  - `VectorMethod = Literal["add", "query", "delete_by_book", "count"]`
  - `write_frame(stream: BinaryIO, obj: object) -> None` / `read_frame(stream: BinaryIO) -> object`: 4-byte big-endian length (`struct "!I"`) + pickle. `read_frame` raises `EOFError` on a clean EOF.
  - `class VectorWorkerError(RuntimeError)`
  - `class VectorWorker`: `__init__(self, idle_seconds: float)`, `call(self, config: VectorConfig, method: VectorMethod, *args: Any, **kwargs: Any) -> Any`, `pid: int | None` (property; `None` when not running), `shutdown(self) -> None`
  - `class RemoteVectorStore` (satisfies `VectorBackend`): `__init__(self, worker: VectorWorker, config: VectorConfig)`. The four data methods forward to `worker.call`; `close()` is a no-op.
  - `main() -> None`, run as `python -m mnemo.vectors.worker`
- `configure("worker", idle_seconds)` makes `open_store` return `RemoteVectorStore` over one process-wide `VectorWorker`.

- [ ] **Step 1: Write the failing tests** in `tests/test_vector_worker.py`. Use a `tmp_path` Chroma dir, a fixture that yields `VectorWorker(idle_seconds=...)` and calls `shutdown()` after, and 8-dim unit vectors:
  - `test_round_trip_add_query_count_delete`: `add` 3 ids → `count() == 3`; `query` returns the nearest id first; `delete_by_book("b1") == 3`; `count() == 0`.
  - `test_worker_starts_lazily_and_stops_when_idle`: `idle_seconds=0.3`; `pid is None` before the first call; set after; `None` within 2 s of the last call, and `os.kill(old_pid, 0)` raises `ProcessLookupError`.
  - `test_next_call_after_idle_respawns`: the call after an idle stop succeeds with a new `pid`.
  - `test_vectors_survive_idle_shutdown`: `add` → wait for the idle stop → `count() == 3` in the new worker.
  - `test_vectors_survive_worker_kill`: `add` → `os.kill(pid, SIGKILL)` → `count() == 3`.
  - `test_respawns_after_kill_between_calls`: SIGKILL between calls → the next `count()` succeeds.
  - `test_kill_mid_call_raises_then_recovers`: patch the child to sleep inside `count` (use an env hook read in `main()`, e.g. `MNEMO_VECTOR_WORKER_TEST_DELAY`), SIGKILL during the call → `VectorWorkerError`; the next call succeeds.
  - `test_child_exception_is_reraised`: a `query` with a wrong-dimension embedding raises in the parent, with the child's message in `str(exc)`.
  - `test_worker_stdout_noise_is_harmless`: run with `MNEMO_VECTOR_WORKER_TEST_PRINT=1`, so `main()` prints to `sys.stdout` and `os.write(1, ...)` before every reply. Calls still succeed, and `capfd.readouterr().out == ""`.
  - `test_idle_shutdown_races_concurrent_callers`: `idle_seconds=0.05`; 4 threads × 25 `count()` calls with random 0–0.1 s sleeps → no exceptions.
  - `test_worker_mode_open_store_returns_remote`: `configure("worker", 300)` → `isinstance(open_store(cfg), RemoteVectorStore)`; `configure("per_call")` stops the worker (`pid is None`).

- [ ] **Step 2: Run to verify they fail.** Run: `pytest tests/test_vector_worker.py -v`. Expected: FAIL (`ModuleNotFoundError: mnemo.vectors.worker`).

- [ ] **Step 3: Implement `worker.py`.**
  - **Child `main()`:** keep the real stdout pipe for IPC and point fd 1 at stderr before importing chromadb, so stray prints can't corrupt frames:

    ```python
    ipc_out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    ```

    Then loop `read_frame(sys.stdin.buffer)` → `(config, method, args, kwargs)`. Reject methods outside `VectorMethod`. Cache one `VectorStore` per `(path, collection)`, never closed. Reply `("ok", value)` or `("err", exc)`, falling back to `RuntimeError(f"{type(e).__name__}: {e}")` if the exception doesn't pickle. Return on `EOFError`.
  - **Parent `VectorWorker`:**
    - Spawn: `subprocess.Popen([sys.executable, "-m", "mnemo.vectors.worker"], stdin=PIPE, stdout=PIPE, stderr=None)`, so the child's stderr goes to the host log.
    - Calls: one `threading.Lock` held for each request/response round trip. Spawn if `proc is None or proc.poll() is not None`. Record `time.monotonic()` as last-used.
    - Idle timer: after each call, re-arm a daemon `threading.Timer(idle_seconds, ...)`. It takes the lock and stops the worker only if `now - last_used >= idle_seconds`.
    - Stop: close stdin, `wait(timeout=10)`, then `kill()`.
    - Failures: `BrokenPipeError` while writing the request means the child never received it, so respawn and retry once. `EOFError`/`OSError` while reading the reply means stop the worker and raise `VectorWorkerError(f"vector worker exited during {method}")`; don't retry, because `add` may have committed.
  - In `backend.py`, implement the `"worker"` branch; leaving worker mode calls `worker.shutdown()`.

- [ ] **Step 4: Run to verify they pass.** Run `pytest tests/test_vector_worker.py -v`, then the full gates as in Task 1. Expected: all pass; the new file adds well under 30 s.

- [ ] **Step 5: Commit.** `git commit -m "feat: run Chroma in a worker process that stops when idle"`

---

### Task 3: Server uses the worker; config, docs, version

**Files:**
- Modify: `src/mnemo/mcp/server.py`, `README.md:109-110`, `.env.example`, `pyproject.toml`, `CLAUDE.md`, `uv.lock`
- Test: `tests/test_mcp.py`, `tests/test_vector_worker.py`

**Interfaces:**
- Consumes: `configure`, `shutdown` (Task 1); worker mode, `VectorWorker.pid` (Task 2).
- Produces, in `mnemo.mcp.server`: `vector_idle_seconds() -> float`. `run()` now calls `configure("worker", s)` when `s > 0`, and `configure("shared")` when `s == 0`.

- [ ] **Step 1: Write the failing tests.**
  - `test_vector_idle_seconds_parsing` (parametrized, `monkeypatch`): unset → `300.0`; `"0"` → `0.0`; `"45"` → `45.0`; `"abc"` and `"-1"` → `300.0` plus a warning in `caplog`.
  - `test_run_uses_worker_by_default` / `test_run_zero_keeps_shared`: patch `mcp.run`; check `current_mode()`; restore `per_call`.
  - `test_server_process_never_imports_chromadb`: a subprocess script with `HOME=tmp_path`:
    - Sets `configure("worker", 0.5)`.
    - Runs `SearchService(db_path, chroma_path)` in semantic mode with `svc._embedder` replaced by a fake returning a fixed 8-dim vector, after adding vectors via `open_store`.
    - Runs `ingest.remove_book` on a book inserted into the temp DB.
    - Prints `"chromadb" in sys.modules` → `False`.
    - After 2 s, the worker pid is gone.
  - `test_worker_exits_with_parent` (Review Focus 5): a subprocess parent starts the worker, prints its pid, then blocks. The test SIGKILLs the parent → `os.kill(worker_pid, 0)` raises `ProcessLookupError` within 5 s, because the child exits on stdin EOF. Repeat for a parent that exits normally (`atexit` path).

- [ ] **Step 2: Run to verify they fail.** Run: `pytest tests/test_mcp.py tests/test_vector_worker.py -k "idle_seconds or run_ or never_imports or exits_with_parent" -v`. Expected: FAIL.

- [ ] **Step 3: Implement** `vector_idle_seconds()` and the `run()` branch. Document `MNEMO_VECTOR_IDLE_SECONDS` (default 300, `0` disables unloading; the first search after an unload takes about 1 s longer) beside `MNEMO_LOG_LEVEL` in `README.md` and as a commented entry in `.env.example`. Bump the version to `3.4.0` (`pyproject.toml`, `CLAUDE.md`), then `uv lock`.

- [ ] **Step 4: Verify.**
  - Run the full gates as in Task 1. Expected: all pass, coverage ≥ 80%.
  - Acceptance on the real library (manual, read-only):
    - Start `mnemo serve` from this branch with `MNEMO_VECTOR_IDLE_SECONDS=30`. Drive it over raw stdio: initialize, `search_books`, then idle 45 s, sampling `ps -o rss=` and `ps -M`. Expected: about 340 MB and 27 threads (server + worker) right after the search, back to the connected baseline (about 140 MB, 3 threads) after the window. The next search succeeds.
    - Run 4 `add_book` + `remove_book` cycles on a fixture EPUB. Expected: server RSS doesn't grow across cycles.
    - A ready-made driver from the investigation is at `/private/tmp/claude-502/-Users-joel-Code-mnemo--claude-worktrees-jiggly-marinating-papert/f8320c77-ff14-4dae-aeea-d68c167efbad/scratchpad/idle_bench.py` (session-local; recreate it if it's gone).

- [ ] **Step 5: Commit.** `git commit -m "feat: unload vector search after MNEMO_VECTOR_IDLE_SECONDS in the MCP server"`
