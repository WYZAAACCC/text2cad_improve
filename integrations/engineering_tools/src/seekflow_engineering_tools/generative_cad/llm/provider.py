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

    # A caller that makes one call and stops needs neither of these. A caller
    # that loops - append the turn, run the tool, append the reply, ask again -
    # needs both, because the protocol requires the assistant message carrying
    # the call to precede the tool message answering it, and the two are
    # linked by the call id. Without them the caller has to fabricate an id
    # and re-serialise the arguments, which is a place for the transcript to
    # drift from what the model actually said.
    tool_call_id: str | None = None
    assistant_content: str = ""
    # How many further calls the model proposed in the same turn. Carried
    # rather than discarded so a transcript can show the turn was wider
    # than the single action that was taken.
    extra_tool_calls: int = 0


class LlmToolCaller(Protocol):
    """Protocol for LLM providers that support strict tool calling.

    Implementations must enforce:
    - At least one tool call in the response, of the requested name; when the
      model proposes several, the first is returned and the count of the rest
      is reported on the result.
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
