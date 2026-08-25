"""Configuration for the embedding client."""

import os
from dataclasses import dataclass


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
            max_input_tokens=int(os.environ.get("MNEMO_EMBED_MAX_TOKENS") or cls.max_input_tokens),
        )
