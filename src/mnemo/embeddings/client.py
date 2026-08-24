"""OpenAI-compatible embedding client with retry logic."""

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


class Embedder:
    """Client for any OpenAI-compatible /embeddings endpoint.

    Dimension is whatever the configured model returns; ChromaDB locks it in
    on first insert and rejects mismatches afterwards. Switching models means
    `mnemo reindex --force` (or a fresh collection).

    Note: embeddings are NOT assumed to be normalized. VectorStore
    L2-normalizes before storage for cosine similarity.
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig.from_env()
        if not self.config.base_url:
            raise ValueError(
                "MNEMO_EMBED_BASE_URL must be set to an OpenAI-compatible endpoint "
                "(e.g. https://api.openai.com/v1), along with MNEMO_EMBED_API_KEY "
                "unless the provider needs no auth."
            )
        self.url = f"{self.config.base_url.rstrip('/')}/embeddings"

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: List of texts to embed (max 50 recommended)

        Returns:
            List of embedding vectors, one per input, in input order

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
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        with httpx.Client(timeout=self.config.timeout) as client:
            response = client.post(
                self.url,
                json={"input": texts, "model": self.config.model},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            # Sort by index to maintain order
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text. Convenience wrapper around embed_batch."""
        return self.embed_batch([text])[0]
