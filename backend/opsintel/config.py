from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EXCLUDED_DIRS = [
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode", ".gradle",
    "dist", "build", "target", "obj", ".next", ".nuxt", "coverage",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    opsintel_data_dir: Path = Path("./data")
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    sqlite_cache_mb: int = 128
    sqlite_busy_timeout_ms: int = 5000

    max_file_size_mb: float = 20.0
    excluded_dirs: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDED_DIRS))
    chunk_lines: int = 50
    chunk_max_chars: int = 8000
    parse_timeout_s: int = 120
    parse_cache_max_mb: int = 512
    libreoffice_path: str = ""

    search_page_size_max: int = 100
    viewer_max_lines: int = 2000

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "opsintel-dev"
    ollama_min_version: str = "0.9.0"
    ai_enabled: bool = True
    ai_max_queue: int = 4
    ai_max_concurrency: int = 1
    ai_num_ctx: int = 4096
    ai_max_tokens: int = 512
    ai_timeout_s: int = 180
    ollama_keep_alive: str = "10m"
    ai_retrieval_top_k: int = 8
    ai_context_chars: int = 6000
    ai_cache_ttl_s: int = 900
    ai_cache_max_entries: int = 500

    worker_min_free_ram_mb: int = 1500
    worker_lease_s: int = 120
    worker_idle_sleep_s: float = 2.0
    worker_resource_wait_s: float = 5.0

    gitea_url: str = ""
    gitea_token: SecretStr = SecretStr("")
    gitea_webhook_secret: SecretStr = SecretStr("")
    gitea_poll_interval_s: int = 300
    git_timeout_s: int = 900

    job_max_attempts: int = 5
    job_backoff_base_s: float = 30.0
    job_backoff_max_s: float = 3600.0
    queue_max_queued: int = 1000
    file_max_attempts: int = 3

    @property
    def mirrors_dir(self) -> Path:
        return self.opsintel_data_dir / "mirrors"

    @property
    def db_path(self) -> Path:
        return self.opsintel_data_dir / "opsintel.db"

    @property
    def max_file_size_bytes(self) -> int:
        return int(self.max_file_size_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
