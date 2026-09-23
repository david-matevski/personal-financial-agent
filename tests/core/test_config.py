"""Tests for finagent.core.config: env var sourcing and the extractor factory.

``_env_file=None`` is passed to every ``Settings()`` construction here so
these tests never read the real (git-ignored) ``.env`` file -- only the
environment variables set via ``monkeypatch``.
"""

import pytest

from finagent.core.config import Settings, build_extractor
from finagent.core.errors import ExtractionError


def test_anthropic_api_key_reads_unprefixed_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-key"


def test_anthropic_api_key_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anthropic_api_key is None


def test_extraction_model_and_effort_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINAGENT_EXTRACTION_MODEL", raising=False)
    monkeypatch.delenv("FINAGENT_EXTRACTION_EFFORT", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.extraction_model == "claude-opus-5"
    assert settings.extraction_effort == "high"


def test_build_extractor_raises_clear_error_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(ExtractionError, match="ANTHROPIC_API_KEY"):
        build_extractor(settings)


def test_build_extractor_succeeds_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    extractor = build_extractor(settings)

    assert extractor is not None
