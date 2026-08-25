"""Configuration for the embedding client."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _positive_int(name: str, raw: str | None, default: int) -> int:
    """Parse a positive int, falling back to default on anything else.

    A typo would otherwise surface as an opaque ValueError from inside
    Embedder(), and search swallows that into a keyword-only fallback — so a
    misconfigured var would silently disable semantic search.
    """
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using %d", name, raw, default)
        return default
    if value < 1:
        logger.warning("%s=%d must be >= 1; using %d", name, value, default)
        return default
    return value


@dataclass
class EmbeddingConfig:
    """Configuration for an OpenAI-compatible embeddings endpoint.

    Works with any provider exposing POST {base_url}/embeddings — OpenAI,
    Voyage, Together, a local Ollama, etc. api_key is optional so local
    servers that don't authenticate need no dummy value.
    """

    base_url: str = ""  # e.g., "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "text-embedding-3-small"
    # Chunker keeps text under 2000 tokens but code/math/table blocks are
    # atomic and unbounded, so oversized inputs reach the provider verbatim.
    max_input_tokens: int = 8192
    # Per-request ceiling across all inputs. Deliberately well under any
    # provider's documented cap; ordinary prose never reaches it.
    max_request_tokens: int = 100_000
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        """Load config from environment variables."""
        base_url = os.environ.get("MNEMO_EMBED_BASE_URL", "")
        if base_url and not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        return cls(
            base_url=base_url,
            api_key=os.environ.get("MNEMO_EMBED_API_KEY", ""),
            model=os.environ.get("MNEMO_EMBED_MODEL") or cls.model,
            max_input_tokens=_positive_int(
                "MNEMO_EMBED_MAX_TOKENS",
                os.environ.get("MNEMO_EMBED_MAX_TOKENS"),
                cls.max_input_tokens,
            ),
            max_request_tokens=_positive_int(
                "MNEMO_EMBED_MAX_REQUEST_TOKENS",
                os.environ.get("MNEMO_EMBED_MAX_REQUEST_TOKENS"),
                cls.max_request_tokens,
            ),
        )
