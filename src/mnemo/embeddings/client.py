"""Databricks embedding client with retry logic."""

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from mnemo.embeddings.config import EmbeddingConfig


def is_retryable(exc: BaseException) -> bool:
    """Check if exception is retryable (rate limit or transient)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


class DatabricksEmbedder:
    """Client for generating embeddings via Databricks GTE-large-en.

    GTE-large-en produces 1024-dimension embeddings and has an 8192 token
    context window. Unlike BGE models, it does NOT require instruction
    prefixes for queries.

    Note: Embeddings are NOT normalized by the API. Caller must L2-normalize
    before storage if using cosine/dot-product similarity.
    """

    EMBEDDING_DIM = 1024

    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig.from_env()
        if not self.config.host or not self.config.token:
            raise ValueError(
                "DATABRICKS_HOST and DATABRICKS_TOKEN must be set. "
                "Get token from Databricks -> User Settings -> Developer -> Access tokens"
            )
        self.url = (
            f"{self.config.host.rstrip('/')}/serving-endpoints/{self.config.model}/invocations"
        )

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: List of texts to embed (max 50 recommended)

        Returns:
            List of 1024-dimension embedding vectors (unnormalized)

        Raises:
            httpx.HTTPStatusError: On non-retryable API errors
            ValueError: If texts is empty
        """
        if not texts:
            raise ValueError("texts cannot be empty")

        return self._embed_with_retry(texts)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
        retry=retry_if_exception(is_retryable),
        reraise=True,
    )
    def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Internal method with retry decorator."""
        with httpx.Client(timeout=self.config.timeout) as client:
            response = client.post(
                self.url,
                json={"input": texts},
                headers={"Content-Type": "application/json"},
                auth=("token", self.config.token),
            )
            response.raise_for_status()
            data = response.json()
            # Sort by index to maintain order
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text. Convenience wrapper around embed_batch."""
        return self.embed_batch([text])[0]
