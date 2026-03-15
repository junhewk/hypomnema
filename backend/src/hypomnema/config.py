from pathlib import Path
import re
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

from hypomnema.tidy import DEFAULT_TIDY_LEVEL, TidyLevel


_DB_OVERRIDABLE = {
    "llm_provider", "llm_model", "anthropic_api_key", "google_api_key",
    "openai_api_key", "ollama_base_url", "openai_base_url",
    "embedding_provider", "embedding_model", "embedding_dim",
    "tidy_level",
}


class Settings(BaseSettings):
    model_config = {"env_prefix": "HYPOMNEMA_"}

    # Deployment mode
    mode: Literal["local", "server", "desktop"] = "local"

    # Database
    db_path: Path = Path("data/hypomnema.db")

    # Embedding
    embedding_dim: int = 384
    embedding_model: str = "all-MiniLM-L6-v2"

    # LLM
    llm_provider: Literal["claude", "google", "openai", "ollama", "mock"] = "mock"
    llm_model: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = ""
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL

    # Embedding provider (fixed at install time — not changeable at runtime)
    embedding_provider: Literal["local", "openai", "google"] = "local"

    # Auth (server mode only)
    passphrase: str = ""

    # Server
    host: str = "127.0.0.1"
    port: int = 8073
    frontend_port: int = 3073

    # Triage
    triage_threshold: float = 0.3

    # Feeds
    feed_fetch_timeout: float = 30.0

    # sqlite-vec extension path (empty = auto-detect via sqlite_vec.loadable_path())
    sqlite_vec_path: str = ""

    # Static file serving (desktop mode)
    static_dir: Path | None = None

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
    def is_remote(self) -> bool:
        return self.host not in ("127.0.0.1", "localhost")

    @property
    def cors_origins(self) -> list[str]:
        origins = [
            f"http://localhost:{self.frontend_port}",
            f"http://127.0.0.1:{self.frontend_port}",
        ]
        if self.is_remote:
            if self.host == "0.0.0.0":  # noqa: S104
                # 0.0.0.0 binds all interfaces — allow any origin on the frontend port
                import socket

                hostname = socket.gethostname()
                try:
                    ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
                    origins.append(f"http://{ip}:{self.frontend_port}")
                except OSError:
                    pass
                origins.append(f"http://{hostname}:{self.frontend_port}")
            else:
                origins.append(f"http://{self.host}:{self.frontend_port}")
        return origins

    @property
    def cors_origin_regex(self) -> str | None:
        if self.host == "0.0.0.0":  # noqa: S104
            return rf"^https?://[^/]+:{re.escape(str(self.frontend_port))}$"
        return None

    @classmethod
    def with_db_overrides(cls, base: "Settings", db_settings: dict[str, str]) -> "Settings":
        """Create a new Settings with DB-overridable fields merged from stored values."""
        overrides: dict[str, str | int] = {
            k: v for k, v in db_settings.items() if k in _DB_OVERRIDABLE and v
        }
        if not overrides:
            return base
        # DB stores everything as strings — convert numeric fields
        if "embedding_dim" in overrides:
            overrides["embedding_dim"] = int(overrides["embedding_dim"])
        data = {k: getattr(base, k) for k in cls.model_fields}
        data.update(overrides)
        return cls.model_construct(**data)

    @model_validator(mode="after")
    def set_host_for_mode(self) -> "Settings":
        if self.mode in ("local", "desktop"):
            self.host = "127.0.0.1"
        elif self.mode == "server" and self.host == "127.0.0.1":
            self.host = "0.0.0.0"  # noqa: S104
        return self
