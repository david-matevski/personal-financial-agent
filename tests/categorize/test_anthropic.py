"""Tests for AnthropicCategorizer, against a stubbed client (no network)."""

from datetime import date
from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import pytest

from finagent.categorize.anthropic import AnthropicCategorizer
from finagent.categorize.base import CategorizeItem, CategoryExample, CategoryOption
from finagent.categorize.prompt import SYSTEM_PROMPT
from finagent.categorize.schema import CategorizationOutput, CategorizedItem
from finagent.core.errors import CategorizationError

_ITEMS = [
    CategorizeItem(
        id=1,
        description="Fictional Coffee Co",
        amount=Decimal("5.00"),
        direction="OUT",
        posted_date=date(2026, 1, 5),
    )
]
_CATEGORIES = [CategoryOption(id=1, name="Dining", description="restaurants, cafes")]
_EXAMPLES = [CategoryExample(description="Fictional Coffee Co", category_name="Dining")]


class _FakeMessages:
    def __init__(self, response: object, captured: dict[str, Any]) -> None:
        self._response = response
        self._captured = captured

    def parse(self, **kwargs: object) -> object:
        self._captured.update(kwargs)
        return self._response


class _RaisingMessages:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def parse(self, **kwargs: object) -> object:
        raise self._exc


class _FakeClient:
    def __init__(self, messages: object) -> None:
        self.messages = messages


def _response(stop_reason: str, parsed_output: object) -> Any:
    class _Response:
        def __init__(self) -> None:
            self.stop_reason = stop_reason
            self.parsed_output = parsed_output

    return _Response()


def _output() -> CategorizationOutput:
    return CategorizationOutput(
        items=[CategorizedItem(id=1, category_name="Dining", confidence=0.9)]
    )


def test_request_uses_configured_model() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_response("end_turn", _output()), captured))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)

    assert captured["model"] == "claude-haiku-4-5"


def test_request_sends_no_thinking_or_effort_params() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_response("end_turn", _output()), captured))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)

    assert "thinking" not in captured
    assert "output_config" not in captured
    assert "effort" not in captured


def test_system_prompt_is_cached_and_stable() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_response("end_turn", _output()), captured))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)

    system = captured["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["text"] == SYSTEM_PROMPT
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_categories_and_examples_are_in_the_user_message_not_system() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_response("end_turn", _output()), captured))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)

    user_content = captured["messages"][0]["content"]
    assert "Dining" in user_content
    assert "restaurants, cafes" in user_content
    assert "Fictional Coffee Co" in user_content
    system_text = captured["system"][0]["text"]
    assert "Dining" not in system_text
    assert "Fictional Coffee Co" not in system_text


def test_output_format_is_the_categorization_schema() -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient(_FakeMessages(_response("end_turn", _output()), captured))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)

    assert captured["output_format"] is CategorizationOutput


def test_max_tokens_stop_raises_categorization_error() -> None:
    client = _FakeClient(_FakeMessages(_response("max_tokens", None), {}))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    with pytest.raises(CategorizationError):
        categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)


def test_refusal_stop_raises_categorization_error() -> None:
    client = _FakeClient(_FakeMessages(_response("refusal", None), {}))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    with pytest.raises(CategorizationError):
        categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)


def test_sdk_api_error_is_wrapped_in_categorization_error() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk_error = anthropic.APIConnectionError(message="connection reset", request=request)
    client = _FakeClient(_RaisingMessages(sdk_error))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    with pytest.raises(CategorizationError):
        categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)


def test_unknown_category_name_in_response_is_dropped() -> None:
    output = CategorizationOutput(
        items=[CategorizedItem(id=1, category_name="Not A Real Category", confidence=0.9)]
    )
    client = _FakeClient(_FakeMessages(_response("end_turn", output), {}))
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    decisions = categorizer.categorize(_ITEMS, _CATEGORIES, _EXAMPLES)

    assert decisions == []


def test_empty_items_returns_empty_without_calling_the_client() -> None:
    def _fail(**kwargs: object) -> object:
        raise AssertionError("should not call the client for an empty batch")

    client = _FakeClient(type("M", (), {"parse": staticmethod(_fail)})())
    categorizer = AnthropicCategorizer(client=client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    assert categorizer.categorize([], _CATEGORIES, _EXAMPLES) == []
