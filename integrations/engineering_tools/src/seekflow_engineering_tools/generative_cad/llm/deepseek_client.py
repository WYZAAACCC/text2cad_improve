"""DeepSeek strict tool caller — uses beta endpoint with strict=True."""
from __future__ import annotations

import json
import os
from typing import Any

from seekflow_engineering_tools.generative_cad.llm.errors import LlmToolCallError
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.llm.provider import ToolCallResult


class DeepSeekToolCaller:
    """Strict tool caller for DeepSeek API (beta endpoint).

    Enforces:
    - Exactly one tool call in the response.
    - Valid JSON in tool call arguments.
    - Tool name matches requested name.
    - Provider schema is NOT trusted as final validation.
    """

    def call_strict_tool(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        model_config: LlmModelConfig,
    ) -> ToolCallResult:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise LlmToolCallError(
                "DEEPSEEK_API_KEY environment variable is not set",
                code="provider_no_auth",
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LlmToolCallError(
                "openai package is required for DeepSeekToolCaller. Install with: pip install openai",
                code="provider_missing_dependency",
            ) from exc

        client = OpenAI(
            api_key=api_key,
            base_url=model_config.base_url,
        )

        # v6.3: Transform Pydantic JSON Schema to DeepSeek strict-mode subset.
        # DeepSeek requires additionalProperties as boolean, all properties in
        # required, and no unsupported keywords (minLength, maxLength, etc.).
        from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
            to_deepseek_strict_schema,
        )
        strict_params = to_deepseek_strict_schema(tool_schema)

        # v6.3: Use strict=False to avoid DeepSeek known bug (issue #1069).
        # Use tool_choice="required" to force the model to always call the tool.
        # With thinking disabled (extra_body), tool_choice="required" is supported
        # on deepseek-v4-pro (the issue #1376 only affects thinking mode).
        # References:
        # - https://github.com/deepseek-ai/DeepSeek-V3/issues/1069 (strict JSON bug)
        # - https://github.com/deepseek-ai/DeepSeek-V3/issues/1376 (thinking+tools)
        tools = [{
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "strict": False,
                "parameters": strict_params,
            },
        }]

        try:
            response = client.chat.completions.create(
                model=model_config.model,
                messages=messages,
                tools=tools,
                tool_choice="required",
                timeout=model_config.timeout_s,
                extra_body={"thinking": {"type": "disabled"}},
                **({"temperature": model_config.temperature} if model_config.temperature is not None else {}),
            )
        except Exception as exc:
            raise LlmToolCallError(
                f"DeepSeek API call failed: {exc}",
                code="provider_api_error",
            ) from exc

        message = response.choices[0].message

        if not message.tool_calls:
            raise LlmToolCallError(
                "Model returned no tool call. Ensure strict tool calling is enabled and the schema is valid.",
                code="provider_no_tool_call",
            )

        if len(message.tool_calls) != 1:
            raise LlmToolCallError(
                f"Expected exactly one tool call, got {len(message.tool_calls)}",
                code="provider_multiple_tool_calls",
            )

        call = message.tool_calls[0]
        if call.function.name != tool_name:
            raise LlmToolCallError(
                f"Unexpected tool call name: {call.function.name!r} (expected {tool_name!r})",
                code="provider_wrong_tool_name",
            )

        try:
            args = json.loads(call.function.arguments)
        except json.JSONDecodeError as exc:
            raise LlmToolCallError(
                f"Tool call arguments were not valid JSON: {exc}",
                code="provider_invalid_json",
            ) from exc

        if not isinstance(args, dict):
            raise LlmToolCallError(
                f"Tool call arguments must be a JSON object, got {type(args).__name__}",
                code="provider_arguments_not_object",
            )

        return ToolCallResult(
            tool_name=call.function.name,
            arguments=args,
            raw_response_id=getattr(response, "id", None),
            model=model_config.model,
            provider="deepseek",
        )
