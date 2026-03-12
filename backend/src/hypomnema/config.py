from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "HYPOMNEMA_"}

    # Deployment mode
    mode: Literal["local", "server"] = "local"

    # Database
    db_path: Path = Path("data/hypomnema.db")

    # Embedding
    embedding_dim: int = 384
    embedding_model: str = "all-MiniLM-L6-v2"

    # LLM
    llm_provider: Literal["claude", "google", "mock"] = "mock"
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    frontend_port: int = 3000

    # Triage
    triage_threshold: float = 0.3

    # Feeds
    feed_fetch_timeout: float = 30.0

    # sqlite-vec extension path (empty = auto-detect via sqlite_vec.loadable_path())
    sqlite_vec_path: str = ""

    @field_validator("embedding_dim")
    @classmethod
    def embedding_dim_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("embedding_dim must be a positive integer")
        return v

    @field_validator("triage_threshold")
    @classmethod
    def triage_threshold_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("triage_threshold must be between 0.0 and 1.0")
        return v

    @property
    def cors_origins(self) -> list[str]:
        origins = [
            f"http://localhost:{self.frontend_port}",
            f"http://127.0.0.1:{self.frontend_port}",
        ]
        if self.host not in ("127.0.0.1", "localhost"):
            origins.append(f"http://{self.host}:{self.frontend_port}")
        return origins

    @model_validator(mode="after")
    def set_host_for_mode(self) -> "Settings":
        if self.mode == "local":
            self.host = "127.0.0.1"
        return self
