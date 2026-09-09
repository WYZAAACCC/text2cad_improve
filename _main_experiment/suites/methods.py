"""Model-comparison method registry and RAG client wrapper."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import LlmConfig, RunnerConfig
from ..llm import BenchLlmClient, ToolCallResult, Usage
from ..schemas import MethodSpec


def method_specs(
    *,
    api_key_env: str = "DEEPSEEK_API_KEY",
    base_url: str = "https://api.deepseek.com/beta",
    runner: RunnerConfig | None = None,
) -> list[MethodSpec]:
    def _llm(model: str) -> LlmConfig:
        return LlmConfig(model=model, base_url=base_url, api_key_env=api_key_env,
                         temperature=0.3, top_p=0.9, max_tokens=8192, timeout_s=900.0)

    return [
        MethodSpec(method_id="base_coder", display_name="Base-Coder",
                   llm=_llm("qwen2.5-coder-32b-instruct"), runner=runner or RunnerConfig()),
        MethodSpec(method_id="qwen72b", display_name="Qwen2.5-72B",
                   llm=_llm("qwen2.5-72b-instruct"), runner=runner or RunnerConfig()),
        MethodSpec(method_id="deepseek_r1_distill", display_name="DeepSeek-R1-Distill",
                   llm=_llm("deepseek-r1-distill"), runner=runner or RunnerConfig()),
        MethodSpec(method_id="llama70b", display_name="Llama-3.3-70B",
                   llm=_llm("llama-3.3-70b-instruct"), runner=runner or RunnerConfig()),
        MethodSpec(method_id="cad_rag", display_name="CAD-RAG",
                   llm=_llm("deepseek-v4-pro"), runner=runner or RunnerConfig(),
                   flags={"rag": True}),
        MethodSpec(method_id="aerodisk_llm", display_name="AeroDisk-LLM",
                   llm=_llm("aerodisk-llm"), runner=runner or RunnerConfig()),
    ]


def _retrieve(task: Any, index_root: Path, top_k: int = 3) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if index_root.exists():
        for path in sorted(index_root.rglob("canonical_ir.json"))[:top_k * 4]:
            try:
                docs.append({"path": str(path),
                             "content": path.read_text(encoding="utf-8")[:4000]})
            except Exception:  # noqa: BLE001
                continue
    return docs[:top_k]


class RagClient:
    """Wraps a BenchLlmClient to inject retrieved CAD-spec examples into the prompt."""

    def __init__(self, inner: BenchLlmClient, *, index_root: Path | None = None,
                 top_k: int = 3):
        self.inner = inner
        self.index_root = index_root
        self.top_k = top_k

    def call_strict_tool(self, *, messages, tool_name, tool_description,
                         tool_schema, config) -> ToolCallResult:
        docs = _retrieve(None, self.index_root or Path.cwd(), self.top_k)
        if docs:
            block = "\n\n".join(f"示例 {i+1}:\n{d['content']}" for i, d in enumerate(docs))
            messages = [dict(m) for m in messages]
            messages[0] = {
                "role": "system",
                "content": messages[0].get("content", "") + "\n\n### 检索到的参考 CAD 建模规范 ###\n" + block,
            }
        result = self.inner.call_strict_tool(
            messages=messages, tool_name=tool_name, tool_description=tool_description,
            tool_schema=tool_schema, config=config,
        )
        return ToolCallResult(
            tool_name=result.tool_name, arguments=result.arguments,
            raw_response_id=result.raw_response_id, model=result.model,
            provider=result.provider, usage=result.usage or Usage(),
            latency_s=result.latency_s,
        )
