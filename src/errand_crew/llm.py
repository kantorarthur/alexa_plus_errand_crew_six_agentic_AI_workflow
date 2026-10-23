"""Thin wrapper over the Claude API that returns schema-validated output.

Every LLM call in this project must end in a tool call whose input validates against a
Pydantic model, so free-form model text never flows between agents.

Sonnet 5.5 rejects a forced tool_choice ("tool" or "any") with a 400, so every call uses
tool_choice "auto" and the system prompt tells the model to answer through the tool.
The guarantee does not come from the API: it comes from the Pydantic validation below,
and a reply that is not a valid tool call is an LLMError.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Protocol, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from .schemas import Usage

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# USD per million tokens (input, output), taken from Anthropic's published pricing on
# 2026-10-23 for prompts up to 100k tokens. An estimate: prices change, so check them.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}


class UsageMeter:
    """Adds up the tokens of every Claude call made while one errand runs."""

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._cost = 0.0
        self._cost_known = True

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        price = PRICES_PER_MTOK.get(model)
        if price is None:
            self._cost_known = False
        else:
            self._cost += (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000

    def snapshot(self) -> Usage | None:
        if not self.calls:
            return None
        return Usage(
            calls=self.calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            estimated_cost_usd=round(self._cost, 6) if self._cost_known else None,
        )


# The meter of the errand being run. Tasks started by that errand inherit it.
_current_meter: ContextVar[UsageMeter | None] = ContextVar("errand_usage_meter", default=None)


def start_meter() -> UsageMeter:
    meter = UsageMeter()
    _current_meter.set(meter)
    return meter


class LLMError(Exception):
    pass


class StructuredLLM(Protocol):
    async def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        tool_name: str,
        max_tokens: int = 1024,
    ) -> T: ...


class ClaudeLLM:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key or None)

    async def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        tool_name: str,
        max_tokens: int = 1024,
    ) -> T:
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=(
                f"{system}\n\nAnswer only by calling the `{tool_name}` tool exactly once. "
                "Do not reply in plain text."
            ),
            tools=[
                {
                    "name": tool_name,
                    "description": "Return your answer by calling this tool.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": user}],
        )
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        log.info("claude call: tool=%s model=%s in=%d out=%d", tool_name, model, input_tokens, output_tokens)
        meter = _current_meter.get()
        if meter is not None:
            meter.add(model, input_tokens, output_tokens)
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                try:
                    return schema.model_validate(block.input)
                except ValidationError as exc:
                    raise LLMError(f"{tool_name}: output failed validation") from exc
        raise LLMError(f"{tool_name}: model did not call the tool")
