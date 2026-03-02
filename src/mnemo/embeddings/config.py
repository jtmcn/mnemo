"""Configuration for Databricks embedding client."""

from dataclasses import dataclass
import os


@dataclass
class EmbeddingConfig:
    """Configuration for Databricks embedding client."""

    host: str = ""  # e.g., "https://xxx.cloud.databricks.com"
    token: str = ""
    model: str = "databricks-gte-large-en"
    batch_size: int = 50
    max_retries: int = 5
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        """Load config from environment variables."""
        host = os.environ.get("DATABRICKS_HOST", "")
        if host and not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return cls(
            host=host,
            token=os.environ.get("DATABRICKS_TOKEN", ""),
        )
