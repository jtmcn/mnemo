"""Tests for embedding client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from mnemo.embeddings import Embedder, EmbeddingConfig


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = EmbeddingConfig()
        assert config.model == "text-embedding-3-small"
        assert config.timeout == 30.0

    def test_from_env(self, monkeypatch):
        """Config loads from environment."""
        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("MNEMO_EMBED_API_KEY", "test-token")
        monkeypatch.setenv("MNEMO_EMBED_MODEL", "custom-embed")
        config = EmbeddingConfig.from_env()
        assert config.base_url == "https://api.example.com/v1"
        assert config.api_key == "test-token"
        assert config.model == "custom-embed"

    def test_from_env_ignores_empty_model(self, monkeypatch):
        """An exported-but-empty model falls back instead of POSTing model=''."""
        monkeypatch.setenv("MNEMO_EMBED_MODEL", "")
        assert EmbeddingConfig.from_env().model == "text-embedding-3-small"

    def test_from_env_token_limits(self, monkeypatch):
        """Token limits parse from env, ignoring junk instead of raising."""
        monkeypatch.setenv("MNEMO_EMBED_MAX_TOKENS", "4096")
        monkeypatch.setenv("MNEMO_EMBED_MAX_REQUEST_TOKENS", "50000")
        config = EmbeddingConfig.from_env()
        assert config.max_input_tokens == 4096
        assert config.max_request_tokens == 50000

    @pytest.mark.parametrize("bad", ["8k", "0", "-5", ""])
    def test_from_env_rejects_bad_token_limits(self, monkeypatch, bad):
        """A typo must not raise from inside Embedder() nor truncate to nothing.

        Search wraps embedding in a broad except, so an opaque ValueError here
        would silently degrade semantic search to keyword-only; 0 would send
        every input as an empty string.
        """
        monkeypatch.setenv("MNEMO_EMBED_MAX_TOKENS", bad)
        assert EmbeddingConfig.from_env().max_input_tokens == 8192

    def test_from_env_adds_scheme(self, monkeypatch):
        """A bare host gets an https:// prefix."""
        monkeypatch.setenv("MNEMO_EMBED_BASE_URL", "api.example.com/v1")
        assert EmbeddingConfig.from_env().base_url == "https://api.example.com/v1"

    def test_from_env_missing(self, monkeypatch):
        """Config handles missing env vars."""
        monkeypatch.delenv("MNEMO_EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("MNEMO_EMBED_API_KEY", raising=False)
        config = EmbeddingConfig.from_env()
        assert config.base_url == ""
        assert config.api_key == ""


class TestEmbedder:
    """Tests for Embedder."""

    @pytest.fixture
    def config(self):
        """Valid test configuration."""
        return EmbeddingConfig(
            base_url="https://api.example.com/v1",
            api_key="test-token",
        )

    @pytest.fixture
    def embedder(self, config):
        """Embedder with test config."""
        return Embedder(config)

    def test_init_requires_base_url(self):
        """Init raises without a configured endpoint."""
        with pytest.raises(ValueError, match="MNEMO_EMBED_BASE_URL"):
            Embedder(EmbeddingConfig())

    def test_init_allows_missing_api_key(self):
        """Local providers (Ollama etc.) need no key."""
        assert Embedder(EmbeddingConfig(base_url="http://localhost:11434/v1")).url

    def test_url_construction(self, embedder):
        """URL is constructed correctly."""
        assert embedder.url == "https://api.example.com/v1/embeddings"

    def test_url_strips_trailing_slash(self):
        """URL construction handles trailing slash."""
        config = EmbeddingConfig(base_url="https://api.example.com/v1/")
        assert Embedder(config).url == "https://api.example.com/v1/embeddings"

    def test_embed_batch_empty_raises(self, embedder):
        """Empty texts list raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            embedder.embed_batch([])


class TestEmbedderWithMock:
    """Tests using mocked HTTP responses."""

    @pytest.fixture
    def config(self):
        return EmbeddingConfig(
            base_url="https://api.example.com/v1",
            api_key="test-token",
        )

    @pytest.fixture
    def mock_response(self):
        """Create a mock successful response."""
        return {
            "data": [
                {"embedding": [0.1] * 1024, "index": 0},
                {"embedding": [0.2] * 1024, "index": 1},
            ]
        }

    def test_embed_batch_success(self, config, mock_response):
        """Successful embedding returns vectors."""
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client

            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp

            embedder = Embedder(config)
            result = embedder.embed_batch(["text1", "text2"])

            assert len(result) == 2
            assert len(result[0]) == 1024
            assert result[0][0] == 0.1
            assert result[1][0] == 0.2

    def test_request_shape(self, config, mock_response):
        """Model goes in the body, key in a Bearer header; no key means no header."""
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_client.post.return_value = mock_resp

            Embedder(config).embed_batch(["text1", "text2"])
            kwargs = mock_client.post.call_args.kwargs
            assert kwargs["json"] == {
                "input": ["text1", "text2"],
                "model": "text-embedding-3-small",
            }
            assert kwargs["headers"]["Authorization"] == "Bearer test-token"

            Embedder(EmbeddingConfig(base_url="http://localhost:11434/v1")).embed_batch(["t"])
            assert "Authorization" not in mock_client.post.call_args.kwargs["headers"]

    def test_oversized_input_is_truncated(self, config, mock_response):
        """A chunk over the model limit is trimmed, not sent whole.

        The chunker keeps code/math/table blocks atomic at any length, and a
        provider 400s the entire batch over one long block.
        """
        from mnemo.chunking.tokenizer import count_tokens

        config.max_input_tokens = 100
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_client.post.return_value = mock_resp

            Embedder(config).embed_batch(["word " * 500, "short one"])
            sent = mock_client.post.call_args.kwargs["json"]["input"]

        assert count_tokens(sent[0]) <= 100
        assert sent[1] == "short one"  # under the limit, untouched

    def test_splits_batches_over_the_request_budget(self, config):
        """Truncation bounds each input, not their sum — split the request too."""
        config.max_request_tokens = 25
        texts = ["word " * 10] * 4  # 11 tokens each, so 2 fit per request

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "data": [{"embedding": [0.1] * 4, "index": 0}, {"embedding": [0.2] * 4, "index": 1}]
            }
            mock_client.post.return_value = mock_resp

            result = Embedder(config).embed_batch(texts)

        assert mock_client.post.call_count == 2
        assert len(result) == 4  # every input still accounted for, in order

    def test_single_oversized_input_still_sent(self, config, mock_response):
        """One input above the whole budget goes alone rather than being dropped."""
        config.max_request_tokens = 5
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"data": [{"embedding": [0.1] * 4, "index": 0}]}
            mock_client.post.return_value = mock_resp

            result = Embedder(config).embed_batch(["word " * 100])

        assert mock_client.post.call_count == 1
        assert len(result) == 1

    def test_embed_batch_maintains_order(self, config):
        """Embeddings are returned in input order even if API returns out of order."""
        response = {
            "data": [
                {"embedding": [0.2] * 1024, "index": 1},  # Out of order
                {"embedding": [0.1] * 1024, "index": 0},
            ]
        }

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client

            mock_resp = MagicMock()
            mock_resp.json.return_value = response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp

            embedder = Embedder(config)
            result = embedder.embed_batch(["first", "second"])

            # Should be sorted by index
            assert result[0][0] == 0.1  # index 0
            assert result[1][0] == 0.2  # index 1

    def test_embed_one_convenience(self, config, mock_response):
        """embed_one is convenience wrapper."""
        mock_response["data"] = [{"embedding": [0.5] * 1024, "index": 0}]

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client

            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp

            embedder = Embedder(config)
            result = embedder.embed_one("single text")

            assert len(result) == 1024
            assert result[0] == 0.5


class TestRetryBehavior:
    """Tests for retry logic."""

    @pytest.fixture
    def config(self):
        return EmbeddingConfig(
            base_url="https://api.example.com/v1",
            api_key="test-token",
        )

    def test_retries_on_429(self, config):
        """Rate limit (429) triggers retry."""
        from mnemo.embeddings.client import is_retryable

        error = httpx.HTTPStatusError(
            "Rate limited",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
        assert is_retryable(error) is True

    def test_retries_on_server_errors(self, config):
        """Server errors trigger retry."""
        from mnemo.embeddings.client import is_retryable

        for status in [500, 502, 503, 504]:
            error = httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=MagicMock(status_code=status),
            )
            assert is_retryable(error) is True

    def test_no_retry_on_400(self, config):
        """Bad request (400) does not retry."""
        from mnemo.embeddings.client import is_retryable

        error = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        assert is_retryable(error) is False

    def test_retries_on_timeout(self, config):
        """Timeout triggers retry."""
        from mnemo.embeddings.client import is_retryable

        error = httpx.TimeoutException("Timeout")
        assert is_retryable(error) is True

    def test_retries_on_connection_error(self, config):
        """Connection error triggers retry."""
        from mnemo.embeddings.client import is_retryable

        error = httpx.ConnectError("Connection refused")
        assert is_retryable(error) is True
