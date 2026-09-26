"""Anthropic-backed ``TransactionCategorizer`` using Claude Haiku 4.5.

Structured output is requested via the SDK's non-streaming
``client.messages.parse(..., output_format=CategorizationOutput)``. Unlike
statement extraction (``finagent.ingest.extract.anthropic``), a
categorization batch's response is small -- at most 100 short per-item
decisions -- so there's no risk of the SDK's non-streaming-timeout guard
rejecting the request, and the simpler non-streaming call is used instead
of ``beta.messages.stream``.

Haiku 4.5 does not support adaptive thinking or ``effort``: neither is sent
in the request. The system prompt is cached, but Haiku 4.5's minimum
cacheable prefix is 4096 tokens (higher than most models -- see the
claude-api skill's shared/prompt-caching.md), and this prompt is shorter
than that, so the ``cache_control`` marker here won't actually create a
cache entry yet (silently: no error, just `cache_creation_input_tokens: 0`
in the response). It's left in place anyway since it's harmless and starts
working for free if the prompt grows past that threshold.
"""

from collections.abc import Sequence
from typing import cast

import anthropic
from anthropic.types import MessageParam, TextBlockParam

from finagent.categorize.base import (
    CategorizeItem,
    CategoryDecision,
    CategoryExample,
    CategoryOption,
)
from finagent.categorize.prompt import SYSTEM_PROMPT
from finagent.categorize.schema import CategorizationOutput, decode_decisions
from finagent.core.errors import CategorizationError

_MAX_TOKENS = 8000


class AnthropicCategorizer:
    """Categorizes transactions with Claude Haiku 4.5 structured output."""

    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        self._client = client
        self._model = model

    def categorize(
        self,
        items: Sequence[CategorizeItem],
        categories: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        """Categorize one batch of items. Returns fewer decisions than items on a partial answer."""
        if not items:
            return []

        user_text = _build_user_message(items, categories, examples)
        messages: list[dict[str, object]] = [{"role": "user", "content": user_text}]

        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=cast(
                    list[TextBlockParam],
                    [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                ),
                messages=cast(list[MessageParam], messages),
                output_format=CategorizationOutput,
            )
        except anthropic.APIError as exc:
            raise CategorizationError("Anthropic API error categorizing transactions") from exc
        except anthropic.AnthropicError as exc:
            raise CategorizationError("Anthropic SDK error categorizing transactions") from exc

        if response.stop_reason == "max_tokens":
            raise CategorizationError("Categorization was truncated (max_tokens)")
        if response.stop_reason == "refusal":
            raise CategorizationError("Categorization was refused by the model")
        if response.parsed_output is None:
            raise CategorizationError("Categorization returned no structured output")

        valid_ids = {item.id for item in items}
        return decode_decisions(response.parsed_output, valid_ids=valid_ids, categories=categories)


def _build_user_message(
    items: Sequence[CategorizeItem],
    categories: Sequence[CategoryOption],
    examples: Sequence[CategoryExample],
) -> str:
    """Render the categories, examples, and transactions for one request.

    Categories and examples vary every call (the owner's corrections accrue
    over time), so they belong in the user message, not the system prompt
    -- that's what keeps the system prompt itself a stable, cacheable
    prefix (AGENTS.md's prompt-caching note; see also the module docstring).
    Never logged: this text can contain merchant descriptions.
    """
    lines = ["## Categories", ""]
    for category in categories:
        if category.description:
            lines.append(f"- {category.name}: {category.description}")
        else:
            lines.append(f"- {category.name}")

    if examples:
        lines.append("")
        lines.append("## Examples of the owner's past categorizations")
        lines.append("")
        for example in examples:
            lines.append(f"- {example.description!r} -> {example.category_name}")

    lines.append("")
    lines.append("## Transactions to categorize")
    lines.append("")
    for item in items:
        lines.append(
            f"- id={item.id} date={item.posted_date.isoformat()} "
            f"direction={item.direction} amount={item.amount} "
            f"description={item.description!r}"
        )

    return "\n".join(lines)
