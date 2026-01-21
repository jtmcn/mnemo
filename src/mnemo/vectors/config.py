"""Configuration for ChromaDB vector store."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class VectorConfig:
    """Configuration for ChromaDB vector store."""

    persist_path: Path | None = None  # None = use default ~/.mnemo/chroma
    collection_name: str = "mnemo"

    def get_persist_path(self) -> Path:
        """Get the persistence path, creating default if needed."""
        if self.persist_path:
            return self.persist_path
        default = Path.home() / ".mnemo" / "chroma"
        default.mkdir(parents=True, exist_ok=True)
        return default
