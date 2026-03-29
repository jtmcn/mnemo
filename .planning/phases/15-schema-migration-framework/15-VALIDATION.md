---
phase: 15
slug: schema-migration-framework
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-29
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_storage.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_storage.py -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 1 | DATA-04 | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_fresh_db_has_schema_version -x` | ❌ W0 | ⬜ pending |
| 15-01-02 | 01 | 1 | DATA-04 | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_fresh_db_at_latest_version -x` | ❌ W0 | ⬜ pending |
| 15-01-03 | 01 | 1 | DATA-04 | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_versioned_db_idempotent -x` | ❌ W0 | ⬜ pending |
| 15-01-04 | 01 | 1 | DATA-05 | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_legacy_db_gets_stamped -x` | ❌ W0 | ⬜ pending |
| 15-01-05 | 01 | 1 | DATA-05 | unit | `pytest tests/test_storage.py::TestSchemaVersion::test_partial_legacy_db_migrated -x` | ❌ W0 | ⬜ pending |
| 15-01-06 | 01 | 1 | DATA-05 | regression | `pytest tests/test_storage.py::TestEpubPath::test_existing_db_without_epub_path_gets_migrated -x` | ✅ | ⬜ pending |
| 15-01-07 | 01 | 1 | DATA-05 | regression | `python -m pytest -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_storage.py` — add `TestSchemaVersion` class with 5 new test cases (fresh DB has schema_version, fresh DB at latest version, versioned DB idempotent, legacy DB gets stamped, partial legacy DB migrated)

*Existing infrastructure covers test framework requirements.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
