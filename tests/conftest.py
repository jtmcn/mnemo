"""Shared test fixtures."""

import pytest

# Every var that steers the embedding client. Anything reading real values
# here would make results depend on the machine running the suite.
_EMBED_ENV = (
    "MNEMO_EMBED_BASE_URL",
    "MNEMO_EMBED_API_KEY",
    "MNEMO_EMBED_MODEL",
    "MNEMO_EMBED_MAX_TOKENS",
    "MNEMO_EMBED_MAX_REQUEST_TOKENS",
)


@pytest.fixture(autouse=True)
def _isolate_embedding_env(monkeypatch):
    """Clear embedding config so tests never reach a real endpoint.

    tests/test_search.py builds ~20 real SearchService instances; with
    credentials exported (as any developer working on mnemo will have) their
    hybrid and semantic paths would hit the configured provider and behave
    differently than in CI. Tests that want these set do so themselves, which
    still wins — monkeypatch.setenv in the test body runs after this fixture.
    """
    for name in _EMBED_ENV:
        monkeypatch.delenv(name, raising=False)
