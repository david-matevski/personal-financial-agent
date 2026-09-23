"""Application configuration, sourced from environment variables (§3 of AGENTS.md)."""

from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from finagent.core.errors import ExtractionError

if TYPE_CHECKING:
    from finagent.ingest.extract.anthropic import AnthropicStatementExtractor


class Settings(BaseSettings):
    """Runtime configuration. Populated from environment variables and `.env`.

    Most variables are prefixed with ``FINAGENT_`` (e.g.
    ``FINAGENT_DATABASE_URL``). ``anthropic_api_key`` is the exception: it
    reads the unprefixed ``ANTHROPIC_API_KEY``, matching the Anthropic SDK's
    own convention.
    """

    model_config = SettingsConfigDict(
        env_prefix="FINAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://finagent:finagent@localhost:5432/finagent"
    log_level: str = "INFO"

    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    extraction_model: str = "claude-opus-5-5"
    extraction_effort: str = "high"  # Set explicitly; Opus 5.5's API default is medium


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance."""
    return Settings()


def build_extractor(settings: Settings) -> "AnthropicStatementExtractor":
    """Construct the Anthropic-backed ``StatementExtractor`` from settings.

    Raises ``ExtractionError`` with a clear message if no API key is
    configured, rather than letting the SDK fail on the first request.
    """
    # Imported here, not at module level, so importing finagent.core.config
    # never requires the anthropic SDK to be installed unless extraction is
    # actually used.
    import anthropic

    from finagent.ingest.extract.anthropic import AnthropicStatementExtractor

    if settings.anthropic_api_key is None:
        raise ExtractionError(
            "ANTHROPIC_API_KEY is not set; statement extraction requires an Anthropic API key"
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    return AnthropicStatementExtractor(
        client=client,
        model=settings.extraction_model,
        effort=settings.extraction_effort,
    )
