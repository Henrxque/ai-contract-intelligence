from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    enable_openai: bool = False
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pages: int = 40
    max_text_chars: int = 120_000
    pipeline_db_path: Path = Path("data/pipeline.sqlite3")

    @property
    def ai_available(self) -> bool:
        return self.enable_openai and bool(self.openai_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
