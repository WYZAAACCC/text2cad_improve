"""DeepSeek strict tool caller — uses beta endpoint with strict=True."""
from __future__ import annotations

import json
import os
from typing import Any, Callable

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
        stream: bool = False,
        on_reasoning_token: Callable[[str], None] | None = None,
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

        if stream:
            stream_extra = {"thinking": {"type": "enabled"}}
            stream_extra["reasoning_effort"] = model_config.reasoning_effort or "low"
            try:
                stream_resp = client.chat.completions.create(
                    model=model_config.model,
                    messages=messages,
                    tools=tools,
                    stream=True,
                    timeout=model_config.timeout_s,
                    extra_body=stream_extra,
                    **({"temperature": model_config.temperature} if model_config.temperature is not None else {}),
                )
            except Exception as exc:
                raise LlmToolCallError(
                    f"DeepSeek API call failed: {exc}",
                    code="provider_api_error",
                ) from exc

            tool_call_name: str | None = None
            arg_parts: list[str] = []
            response_id: str | None = None
            tool_call_id: str | None = None
            content_parts: list[str] = []
            try:
                for chunk in stream_resp:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    rc = getattr(delta, "reasoning_content", None)
                    if rc and on_reasoning_token:
                        on_reasoning_token(rc)
                    if getattr(delta, "content", None):
                        content_parts.append(delta.content)
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            if getattr(tc, "id", None):
                                tool_call_id = tc.id
                            if tc.function and tc.function.name:
                                tool_call_name = tc.function.name
                            if tc.function and tc.function.arguments:
                                arg_parts.append(tc.function.arguments)
                    response_id = response_id or getattr(chunk, "id", None)
            except Exception as exc:
                raise LlmToolCallError(
                    f"DeepSeek stream interrupted: {exc}",
                    code="provider_stream_error",
                ) from exc

            if not tool_call_name or not arg_parts:
                # thinking 模式不强制 tool_choice；无工具调用时回退到非流式 required 模式
                return self.call_strict_tool(
                    messages=messages,
                    tool_name=tool_name,
                    tool_description=tool_description,
                    tool_schema=tool_schema,
                    model_config=model_config,
                )

            try:
                args = json.loads("".join(arg_parts))
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
            if tool_call_name != tool_name:
                raise LlmToolCallError(
                    f"Unexpected tool call name: {tool_call_name!r} (expected {tool_name!r})",
                    code="provider_wrong_tool_name",
                )
            return ToolCallResult(
                tool_name=tool_call_name,
                arguments=args,
                raw_response_id=response_id,
                model=model_config.model,
                provider="deepseek",
                tool_call_id=tool_call_id,
                assistant_content="".join(content_parts),
            )

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

        # A schema with a discriminated-union action invites the model to
        # propose several actions in one turn. Refusing the whole turn over
        # that throws away a response that is otherwise perfectly usable, so
        # only the first is acted on - a caller that loops takes one action
        # per turn by design - and the number dropped is carried on the
        # result rather than discarded silently.
        extra_tool_calls = max(0, len(message.tool_calls) - 1)
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
            tool_call_id=getattr(call, "id", None),
            assistant_content=getattr(message, "content", None) or "",
            extra_tool_calls=extra_tool_calls,
        )
