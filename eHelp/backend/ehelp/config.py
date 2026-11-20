import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    dev_admin: bool
    max_upload_bytes: int
    libreoffice_path: str
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "opsintel-dev"
    ai_num_ctx: int = 4096
    ai_max_tokens: int = 512
    ai_timeout_s: int = 180
    ai_top_k: int = 4
    ai_context_chars: int = 2500
    ai_max_queue: int = 4

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ehelp.db"


def _load_env_file() -> None:
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def load_config() -> Config:
    _load_env_file()
    env = os.environ.get
    return Config(
        data_dir=Path(env("EHELP_DATA_DIR", "./data")).resolve(),
        dev_admin=env("EHELP_DEV_ADMIN", "0").lower() in ("1", "true", "yes"),
        max_upload_bytes=int(env("EHELP_MAX_UPLOAD_MB", "500")) * 1024 * 1024,
        libreoffice_path=env("EHELP_LIBREOFFICE_PATH", ""),
        ollama_url=env("EHELP_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=env("EHELP_OLLAMA_MODEL", "opsintel-dev"),
        ai_num_ctx=int(env("EHELP_AI_NUM_CTX", "4096")),
        ai_max_tokens=int(env("EHELP_AI_MAX_TOKENS", "512")),
        ai_timeout_s=int(env("EHELP_AI_TIMEOUT_S", "180")),
        ai_top_k=int(env("EHELP_AI_TOP_K", "4")),
        ai_context_chars=int(env("EHELP_AI_CONTEXT_CHARS", "2500")),
        ai_max_queue=int(env("EHELP_AI_MAX_QUEUE", "4")),
    )
