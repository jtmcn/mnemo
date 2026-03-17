"""Tests for embedding client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from mnemo.embeddings import DatabricksEmbedder, EmbeddingConfig


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = EmbeddingConfig()
        assert config.model == "databricks-gte-large-en"
        assert config.batch_size == 50
        assert config.max_retries == 5
        assert config.timeout == 30.0

    def test_from_env(self, monkeypatch):
        """Config loads from environment."""
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "test-token")
        config = EmbeddingConfig.from_env()
        assert config.host == "https://test.databricks.com"
        assert config.token == "test-token"

    def test_from_env_missing(self, monkeypatch):
        """Config handles missing env vars."""
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        config = EmbeddingConfig.from_env()
        assert config.host == ""
        assert config.token == ""


class TestDatabricksEmbedder:
    """Tests for DatabricksEmbedder."""

    @pytest.fixture
    def config(self):
        """Valid test configuration."""
        return EmbeddingConfig(
            host="https://test.databricks.com",
            token="test-token",
        )

    @pytest.fixture
    def embedder(self, config):
        """Embedder with test config."""
        return DatabricksEmbedder(config)

    def test_init_requires_credentials(self):
        """Init raises without credentials."""
        with pytest.raises(ValueError, match="DATABRICKS_HOST"):
            DatabricksEmbedder(EmbeddingConfig())

    def test_url_construction(self, embedder):
        """URL is constructed correctly."""
        assert embedder.url == "https://test.databricks.com/serving-endpoints/databricks-gte-large-en/invocations"

    def test_url_strips_trailing_slash(self):
        """URL construction handles trailing slash."""
        config = EmbeddingConfig(
            host="https://test.databricks.com/",
            token="test-token",
        )
        embedder = DatabricksEmbedder(config)
        assert "com/serving" in embedder.url  # Not com//serving

    def test_embed_batch_empty_raises(self, embedder):
        """Empty texts list raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            embedder.embed_batch([])

    def test_embedding_dimension_constant(self):
        """Embedding dimension is documented."""
        assert DatabricksEmbedder.EMBEDDING_DIM == 1024


class TestEmbedderWithMock:
    """Tests using mocked HTTP responses."""

    @pytest.fixture
    def config(self):
        return EmbeddingConfig(
            host="https://test.databricks.com",
            token="test-token",
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

            embedder = DatabricksEmbedder(config)
            result = embedder.embed_batch(["text1", "text2"])

            assert len(result) == 2
            assert len(result[0]) == 1024
            assert result[0][0] == 0.1
            assert result[1][0] == 0.2

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

            embedder = DatabricksEmbedder(config)
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

            embedder = DatabricksEmbedder(config)
            result = embedder.embed_one("single text")

            assert len(result) == 1024
            assert result[0] == 0.5


class TestRetryBehavior:
    """Tests for retry logic."""

    @pytest.fixture
    def config(self):
        return EmbeddingConfig(
            host="https://test.databricks.com",
            token="test-token",
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
