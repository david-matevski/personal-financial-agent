"""Anthropic-backed ``StatementExtractor``.

Structured output is requested via ``client.beta.messages.stream(...,
output_format=StatementExtraction)``. Streaming (rather than a plain
``messages.parse()`` call) is used because a statement with many
transactions can need a large ``max_tokens``, and the SDK refuses a
non-streaming request it estimates will run past its connection-idle
timeout (see the claude-api skill's streaming.md: "Large max_tokens without
streaming raises ValueError"). ``beta.messages.stream`` accepts
``output_format`` directly and its ``get_final_message()`` returns a
``ParsedBetaMessage`` with ``.parsed_output`` already validated against the
schema, so no separate non-streaming structured-output path is needed.

Server-side refusal fallbacks (`fallbacks="default"`, beta
`server-side-fallback-2026-07-01`) are enabled so a declined request is
retried on Anthropic's recommended substitute model instead of surfacing a
refusal to the caller. This is compatible with structured output on the
installed SDK (1.8.0): ``beta.messages.stream`` takes both ``output_format``
and ``fallbacks`` as ordinary parameters.
"""

import base64
import logging
from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

from finagent.core.errors import ExtractionError
from finagent.ingest.document import DocumentKind, SourceDocument
from finagent.ingest.extract.prompt import SYSTEM_PROMPT
from finagent.ingest.extract.schema import StatementExtraction

logger = logging.getLogger(__name__)

# Adaptive thinking tokens count against this cap too, so it must cover
# reasoning plus a long statement's full transaction list; streaming means
# there's no connection-timeout risk from setting it high.
_MAX_TOKENS = 64000
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_EXTRACT_INSTRUCTION = (
    "Extract this statement ({filename}) into the structured schema "
    "described in the system prompt. Transcribe every transaction line."
)


class AnthropicStatementExtractor:
    """Extracts statements with Claude structured output."""

    def __init__(self, client: anthropic.Anthropic, model: str, effort: str) -> None:
        self._client = client
        self._model = model
        self._effort = effort

    def extract(self, doc: SourceDocument, feedback: str | None = None) -> StatementExtraction:
        """Extract ``doc`` into a ``StatementExtraction``.

        On a retry, ``feedback`` (a description of the validation
        discrepancy from the previous attempt) is appended to the request
        as an extra instruction, asking for a corrected, complete
        extraction in one fresh call -- there is no need to replay the
        prior (invalid) answer.
        """
        instruction = _EXTRACT_INSTRUCTION.format(filename=doc.filename)
        if feedback:
            instruction += (
                f"\n\nYour previous extraction of this statement did not reconcile: {feedback}"
            )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": _document_content(doc, instruction)}
        ]

        # The request bodies here are plain dicts, not the SDK's precise
        # nested TypedDict unions (BetaContentBlockParam etc.) -- casting is
        # simpler than reconstructing that hierarchy, and the request shape
        # is covered by tests against a stubbed client instead.
        try:
            with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=cast(list[BetaMessageParam], messages),
                output_config=cast(BetaOutputConfigParam, {"effort": self._effort}),
                output_format=StatementExtraction,
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIError as exc:
            raise ExtractionError(f"Anthropic API error extracting {doc.filename}") from exc
        except anthropic.AnthropicError as exc:
            raise ExtractionError(f"Anthropic SDK error extracting {doc.filename}") from exc

        if message.stop_reason == "max_tokens":
            raise ExtractionError(f"Extraction of {doc.filename} was truncated (max_tokens)")
        if message.stop_reason == "refusal":
            raise ExtractionError(f"Extraction of {doc.filename} was refused by the model")

        if message.parsed_output is None:
            raise ExtractionError(f"Extraction of {doc.filename} returned no structured output")

        return message.parsed_output


def _document_content(doc: SourceDocument, instruction: str) -> list[dict[str, Any]]:
    """Build the user-turn content blocks for one document.

    A document/image block always precedes the instruction text block, per
    the Claude API's document-handling guidance. Table documents have no
    bytes to send, so the rows are rendered as tab-separated lines of text
    instead.
    """
    if doc.kind is DocumentKind.PDF:
        encoded = base64.standard_b64encode(doc.data).decode("ascii")
        return [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": doc.media_type, "data": encoded},
            },
            {"type": "text", "text": instruction},
        ]
    if doc.kind is DocumentKind.IMAGE:
        encoded = base64.standard_b64encode(doc.data).decode("ascii")
        return [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": doc.media_type, "data": encoded},
            },
            {"type": "text", "text": instruction},
        ]

    table_text = "\n".join("\t".join(row) for row in doc.rows)
    return [{"type": "text", "text": f"{table_text}\n\n{instruction}"}]
