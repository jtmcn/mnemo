"""OpenAI-compatible embedding client with retry logic."""

from collections.abc import Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from mnemo.chunking.tokenizer import count_tokens, truncate_to_tokens
from mnemo.embeddings.config import EmbeddingConfig, EmbeddingsNotConfigured


def is_retryable(exc: BaseException) -> bool:
    """Check if exception is retryable (rate limit or transient)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


class Embedder:
    """Client for any OpenAI-compatible /embeddings endpoint.

    Dimension is whatever the configured model returns; ChromaDB locks it in
    on the collection and rejects mismatches afterwards. Deleting the records
    does not release the lock, so switching models means deleting the
    collection: `rm -rf ~/.mnemo/chroma && mnemo reindex`.

    Note: embeddings are NOT assumed to be normalized. VectorStore
    L2-normalizes before storage for cosine similarity.
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig.from_env()
        if not self.config.base_url:
            raise EmbeddingsNotConfigured(
                "MNEMO_EMBED_BASE_URL must be set to an OpenAI-compatible endpoint "
                "(e.g. https://api.openai.com/v1), along with MNEMO_EMBED_API_KEY "
                "unless the provider needs no auth."
            )
        self.url = f"{self.config.base_url.rstrip('/')}/embeddings"

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: List of texts to embed (max 50 recommended)

        Oversized inputs are truncated rather than rejected: the chunker keeps
        code/math/table blocks whole no matter how long, and a provider 400s on
        the whole batch for one long block. The full text stays in SQLite for
        keyword search and display — only the vector sees the head of it.

        Returns:
            List of embedding vectors, one per input, in input order

        Raises:
            httpx.HTTPStatusError: On non-retryable API errors
            ValueError: If texts is empty
        """
        if not texts:
            raise ValueError("texts cannot be empty")

        # ponytail: cl100k_base is OpenAI's tokenizer, so the count only matches
        # OpenAI exactly. Providers with a smaller window (a 512-token local
        # model) need MNEMO_EMBED_MAX_TOKENS lowered to match, or oversized
        # inputs still reach them.
        texts = [truncate_to_tokens(t, self.config.max_input_tokens) for t in texts]

        embeddings: list[list[float]] = []
        for group in self._token_budgeted(texts):
            embeddings.extend(self._embed_with_retry(group))
        return embeddings

    def _token_budgeted(self, texts: list[str]) -> Iterator[list[str]]:
        """Split texts so no single request exceeds the per-request budget.

        Truncation bounds each input, not their sum: 50 chunks of 8192 tokens
        is ~410k in one request, past what providers accept, and it fails as a
        non-retryable 400 on the whole batch. Books of ordinary prose never
        reach the budget, so this only splits the pathological case.
        """
        group: list[str] = []
        used = 0
        for text in texts:
            tokens = count_tokens(text)
            if group and used + tokens > self.config.max_request_tokens:
                yield group
                group, used = [], 0
            group.append(text)
            used += tokens
        if group:
            yield group

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
