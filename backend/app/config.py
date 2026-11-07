from functools import lru_cache
import os
from pathlib import Path

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _HAS_PYDANTIC_SETTINGS = True
except ImportError:
    from pydantic import BaseModel as BaseSettings
    SettingsConfigDict = dict
    _HAS_PYDANTIC_SETTINGS = False


def _load_dotenv_fallback(env_path: str = ".env") -> None:
    p = Path(env_path)
    if not p.is_file():
        return
    for raw_line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


if not _HAS_PYDANTIC_SETTINGS:
    _load_dotenv_fallback()


class Settings(BaseSettings):
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./testforge.db")
    frontend_origins: str = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    )
    artifact_dir: str = os.getenv("ARTIFACT_DIR", "./artifacts")
    vultr_inference_api_key: str = os.getenv("VULTR_INFERENCE_API_KEY", "")
    vultr_inference_base_url: str = os.getenv(
        "VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1"
    )
    vultr_inference_model: str = os.getenv(
        "VULTR_INFERENCE_MODEL", "deepseek-v4.1-flash-1017"
    )
    runner_mode: str = os.getenv("RUNNER_MODE", "local")
    sandbox_worker_url: str = os.getenv("SANDBOX_WORKER_URL", "")
    sandbox_worker_token: str = os.getenv("SANDBOX_WORKER_TOKEN", "")
    max_run_seconds: int = int(os.getenv("MAX_RUN_SECONDS", "90"))
    code_sandbox_timeout_seconds: int = int(os.getenv("CODE_SANDBOX_TIMEOUT_SECONDS", "6"))

    if _HAS_PYDANTIC_SETTINGS:
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [x.strip() for x in self.frontend_origins.split(",") if x.strip()]

    @property
    def artifacts(self) -> Path:
        p = Path(self.artifact_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def settings() -> Settings:
    return Settings()
