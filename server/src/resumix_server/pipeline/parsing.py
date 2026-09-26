"""Getting a model's reply into a validated object, and saying why it would not.

Every generator needed the same three steps — drop the Markdown code fence a
model sometimes wraps its reply in, parse the JSON, validate it against a
pydantic model — and each one had its own copy. This is the one copy. The two
diagnostic helpers live here for the same reason: whoever parses a reply is
the one who has to log what was wrong with it.
"""

from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

# How much of a rejected payload to log: enough head to see the shape the
# model chose and enough tail to see where a truncated reply stopped. Both
# together stay under the per-line cap the run log store applies.
RAW_HEAD_CHARS = 1200
RAW_TAIL_CHARS = 400


def raw_excerpt(content: Optional[str]) -> str:
    """Head and tail of a payload, with the middle elided."""
    if not content:
        return repr(content)
    elided = len(content) - RAW_HEAD_CHARS - RAW_TAIL_CHARS
    if elided <= 0:
        return content
    return (
        f"{content[:RAW_HEAD_CHARS]}"
        f"\n    ... [{elided} chars elided] ...\n"
        f"{content[-RAW_TAIL_CHARS:]}"
    )


def reply_diagnostics(response) -> str:
    """Why a reply could not be used, beyond the validation error itself.

    ``finish_reason="length"`` means the model was cut off rather than wrong,
    and reasoning counts tell a thinking budget that ate the output budget
    apart from one that was never applied — neither is visible in a Pydantic
    error.
    """
    choice = response.choices[0]
    content = choice.message.content
    bits = [
        f"finish_reason={choice.finish_reason}",
        f"content_chars={len(content or '')}",
    ]
    reasoning = getattr(choice.message, "reasoning_content", None)
    if reasoning:
        bits.append(f"reasoning_chars={len(reasoning)}")
    usage = getattr(response, "usage", None)
    if usage is not None:
        details = getattr(usage, "completion_tokens_details", None)
        bits.append(f"completion_tokens={getattr(usage, 'completion_tokens', None)}")
        bits.append(
            f"reasoning_tokens={getattr(details, 'reasoning_tokens', None) if details else None}"
        )
    return ", ".join(bits)


def strip_fences(text: str) -> str:
    """Drop a Markdown code fence around a reply, if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_model_json(
    content: Optional[str],
    model: Type[M],
    *,
    empty: str = "LLM returned empty content",
    unwrap_nested: bool = False,
) -> M:
    """Parse one reply into ``model``.

    Raises ``ValueError`` (including ``json.JSONDecodeError``) when the content
    is missing or is not JSON, and ``ValidationError`` when it does not
    conform. Both are what the callers feed back to the model as the next turn,
    so a weak ``response_format`` costs a retry rather than correctness.

    ``unwrap_nested`` is for the providers that wrap the real payload inside a
    single string field, e.g. ``{"description": "{\\"match_percentage\\": …}"}``.
    """
    if not content:
        raise ValueError(empty)

    data = json.loads(strip_fences(content))
    try:
        return model.model_validate(data)
    except ValidationError:
        if unwrap_nested and isinstance(data, dict) and len(data) == 1:
            wrapped = next(iter(data.values()))
            if isinstance(wrapped, str):
                return model.model_validate(json.loads(wrapped))
        raise


__all__ = ["strip_fences", "parse_model_json", "raw_excerpt", "reply_diagnostics"]
