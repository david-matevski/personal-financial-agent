"""Application configuration, sourced from environment variables (§3 of AGENTS.md)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Populated from environment variables and `.env`.

    All variables are prefixed with ``FINAGENT_`` (e.g. ``FINAGENT_DATABASE_URL``).
    """

    model_config = SettingsConfigDict(
        env_prefix="FINAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://finagent:finagent@localhost:5432/finagent"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance."""
    return Settings()
