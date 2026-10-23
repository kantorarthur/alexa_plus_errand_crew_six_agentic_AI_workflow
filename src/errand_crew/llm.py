"""Thin wrapper over the Claude API that returns schema-validated output.

Every LLM call in this project must end in a tool call whose input validates against a
Pydantic model, so free-form model text never flows between agents.

Sonnet 5.5 rejects a forced tool_choice ("tool" or "any") with a 400, so every call uses
tool_choice "auto" and the system prompt tells the model to answer through the tool.
The guarantee does not come from the API: it comes from the Pydantic validation below,
and a reply that is not a valid tool call is an LLMError.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


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
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                try:
                    return schema.model_validate(block.input)
                except ValidationError as exc:
                    raise LLMError(f"{tool_name}: output failed validation") from exc
        raise LLMError(f"{tool_name}: model did not call the tool")
