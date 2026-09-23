"""Tests for AnthropicStatementExtractor, against a stubbed client (no network)."""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from finagent.core.errors import ExtractionError
from finagent.ingest.document import DocumentKind, SourceDocument
from finagent.ingest.extract.anthropic import AnthropicStatementExtractor
from finagent.ingest.extract.prompt import SYSTEM_PROMPT
from finagent.ingest.extract.schema import StatementExtraction

_PARSED = StatementExtraction(
    issuer="TD",
    account_name="TD Rewards Visa",
    account_last4="1234",
    account_type="CREDIT",
    currency="CAD",
    transactions=[],
)


class _FakeStream:
    def __init__(self, message: object) -> None:
        self._message = message

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def get_final_message(self) -> object:
        return self._message


class _RaisingMessages:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def stream(self, **kwargs: object) -> _FakeStream:
        raise self._exc


class _FakeMessages:
    def __init__(self, message: object, captured: dict[str, Any]) -> None:
        self._message = message
        self._captured = captured

    def stream(self, **kwargs: object) -> _FakeStream:
        self._captured.update(kwargs)
        return _FakeStream(self._message)


class _FakeBeta:
    def __init__(self, messages: object) -> None:
        self.messages = messages


class _FakeClient:
    def __init__(self, messages: object) -> None:
        self.beta = _FakeBeta(messages)


def _message(stop_reason: str, parsed_output: object) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed_output)


def _pdf_doc() -> SourceDocument:
    return SourceDocument(
        filename="statement.pdf",
        kind=DocumentKind.PDF,
        data=b"%PDF-1.7 fake synthetic body",
        media_type="application/pdf",
    )


def test_request_puts_document_block_before_text_block() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_message("end_turn", _PARSED), captured))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="high")  # type: ignore[arg-type]

    extractor.extract(_pdf_doc())

    content = captured["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[1]["type"] == "text"


def test_request_uses_model_and_effort_from_config() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_message("end_turn", _PARSED), captured))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="xhigh")  # type: ignore[arg-type]

    extractor.extract(_pdf_doc())

    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"] == {"effort": "xhigh"}
    assert captured["output_format"] is StatementExtraction


def test_system_prompt_is_cached() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_message("end_turn", _PARSED), captured))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="high")  # type: ignore[arg-type]

    extractor.extract(_pdf_doc())

    system = captured["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    block = system[0]
    assert block["type"] == "text"
    assert block["text"] == SYSTEM_PROMPT
    assert block["cache_control"] == {"type": "ephemeral"}


def test_feedback_is_included_in_the_request() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_message("end_turn", _PARSED), captured))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="high")  # type: ignore[arg-type]

    extractor.extract(_pdf_doc(), feedback="transactions summed to 5.00, expected 10.00")

    text_block = captured["messages"][0]["content"][1]["text"]
    assert "transactions summed to 5.00" in text_block


def test_max_tokens_stop_raises_extraction_error() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_message("max_tokens", None), captured))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="high")  # type: ignore[arg-type]

    with pytest.raises(ExtractionError):
        extractor.extract(_pdf_doc())


def test_refusal_stop_raises_extraction_error() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_message("refusal", None), captured))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="high")  # type: ignore[arg-type]

    with pytest.raises(ExtractionError):
        extractor.extract(_pdf_doc())


def test_sdk_api_error_is_wrapped_in_extraction_error() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk_error = anthropic.APIConnectionError(message="connection reset", request=request)
    client = _FakeClient(_RaisingMessages(sdk_error))
    extractor = AnthropicStatementExtractor(client=client, model="claude-opus-5-5", effort="high")  # type: ignore[arg-type]

    with pytest.raises(ExtractionError):
        extractor.extract(_pdf_doc())
