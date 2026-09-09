"""Unified LLM client used by the experiment runner.

This module intentionally avoids importing the main application client so the
benchmark can point at any OpenAI-compatible endpoint by changing configuration.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .config import LlmConfig


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ToolCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    arguments: dict[str, Any]
    raw_response_id: str
    model: str
    provider: str
    usage: Usage = Usage()
    latency_s: float = 0.0


class LlmCallError(RuntimeError):
    def __init__(self, message: str, *, code: str = "llm_call_error"):
        super().__init__(message)
        self.code = code


@runtime_checkable
class BenchLlmClient(Protocol):
    def call_strict_tool(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        config: LlmConfig,
    ) -> ToolCallResult:
        """Call exactly one strict tool and return parsed arguments."""


class OpenAICompatToolClient:
    """OpenAI-compatible client with reproducible sampling controls."""

    def call_strict_tool(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        config: LlmConfig,
    ) -> ToolCallResult:
        api_key = os.environ.get(config.api_key_env, "")
        if not api_key:
            raise LlmCallError(
                f"environment variable {config.api_key_env!r} is not set",
                code="provider_no_auth",
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LlmCallError(
                "openai package is required for OpenAICompatToolClient",
                code="provider_missing_dependency",
            ) from exc

        client = OpenAI(api_key=api_key, base_url=config.base_url, timeout=config.timeout_s)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "strict": False,
                    "parameters": tool_schema,
                },
            }
        ]

        request: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": config.tool_choice,
        }
        if config.temperature is not None:
            request["temperature"] = config.temperature
        if config.top_p is not None:
            request["top_p"] = config.top_p
        if config.seed is not None:
            request["seed"] = config.seed
        if config.max_tokens is not None:
            request["max_tokens"] = config.max_tokens
        extra_body = dict(config.extra_body or {})
        if config.thinking is not None:
            extra_body["thinking"] = config.thinking
        if extra_body:
            request["extra_body"] = extra_body

        started = time.monotonic()
        try:
            response = client.chat.completions.create(**request)
        except LlmCallError:
            raise
        except Exception as exc:
            raise LlmCallError(
                f"LLM API call failed: {exc}",
                code="provider_api_error",
            ) from exc

        latency_s = time.monotonic() - started
        message = response.choices[0].message
        if not message.tool_calls:
            retry_messages = messages + [
                {"role": "assistant", "content": message.content or ""},
                {"role": "user", "content": f"You must call the {tool_name!r} tool now. Return only the tool call arguments."},
            ]
            retry_req = dict(request)
            retry_req["messages"] = retry_messages
            retry_req.pop("seed", None)
            retry_req.pop("top_p", None)
            if retry_req.get("max_tokens") is None or retry_req["max_tokens"] > 2048:
                retry_req["max_tokens"] = 2048
            response = client.chat.completions.create(**retry_req)
            message = response.choices[0].message
        if not message.tool_calls:
            raise LlmCallError(
                "model returned no tool call",
                code="provider_no_tool_call",
            )
        calls = message.tool_calls or []
        matching = [c for c in calls
                    if getattr(getattr(c, "function", None), "name", None) == tool_name]
        if not matching:
            names = [getattr(getattr(c, "function", None), "name", None) for c in calls]
            raise LlmCallError(
                f"no tool call matching {tool_name!r}, got {names}",
                code="provider_wrong_tool_name",
            )
        call = matching[0]
        if call.function.name != tool_name:
            raise LlmCallError(
                f"unexpected tool name {call.function.name!r}, expected {tool_name!r}",
                code="provider_wrong_tool_name",
            )

        try:
            arguments = json.loads(call.function.arguments)
        except json.JSONDecodeError as exc:
            raise LlmCallError(
                "tool call arguments were not valid JSON",
                code="provider_invalid_json",
            ) from exc

        usage = Usage()
        if response.usage is not None:
            usage = Usage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return ToolCallResult(
            tool_name=tool_name,
            arguments=arguments,
            raw_response_id=response.id,
            model=config.model,
            provider=config.provider,
            usage=usage,
            latency_s=latency_s,
        )


class MockBenchLlmClient:
    """Deterministic client for tests and runner dry-runs."""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        repeat_last: bool = True,
        usage: Usage | None = None,
    ) -> None:
        self.responses = responses or [{}]
        self.repeat_last = repeat_last
        self.usage = usage or Usage()
        self.calls = 0

    def call_strict_tool(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        config: LlmConfig,
    ) -> ToolCallResult:
        index = min(self.calls, len(self.responses) - 1) if self.repeat_last else self.calls
        if index >= len(self.responses):
            raise LlmCallError("mock response sequence exhausted", code="mock_exhausted")
        arguments = self.responses[index]
        self.calls += 1
        return ToolCallResult(
            tool_name=tool_name,
            arguments=arguments,
            raw_response_id=f"mock_{self.calls}",
            model=config.model,
            provider=config.provider,
            usage=self.usage,
            latency_s=0.001,
        )
