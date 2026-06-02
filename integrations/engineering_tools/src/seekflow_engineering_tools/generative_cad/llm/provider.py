"""LLM provider protocol and ToolCallResult."""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class ToolCallResult(BaseModel):
    """Result of a single strict tool call to an LLM provider."""

    model_config = {"extra": "forbid"}

    tool_name: str
    arguments: dict[str, Any]
    raw_response_id: str | None = None
    model: str
    provider: str


class LlmToolCaller(Protocol):
    """Protocol for LLM providers that support strict tool calling.

    Implementations must enforce:
    - Exactly one tool call in the response.
    - Valid JSON in tool call arguments.
    - Provider schema enforcement is NOT trusted as final validation.
    """

    def call_strict_tool(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        model_config: Any,  # LlmModelConfig
    ) -> ToolCallResult:
        ...
