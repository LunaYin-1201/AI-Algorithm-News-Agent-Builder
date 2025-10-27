from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    app_name: str = "AI Algorithm News Agent"
    environment: str = "development"

    database_url: str = "sqlite:///./news.db"

    # Admin token for privileged endpoints like manual refresh
    admin_token: str = ""

    # LLM config (Ollama-only)
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    enable_llm_filter: bool = False
    llm_model: Optional[str] = None  # e.g., "llama3.1:8b"
    max_age_days_default: int = 7

    # Hacker News (Algolia) fetch settings
    hn_enable: bool = True
    # Comma-separated query terms; if empty, fall back to defaults in hn_fetcher
    hn_query_terms: Optional[str] = None
    hn_min_points: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


