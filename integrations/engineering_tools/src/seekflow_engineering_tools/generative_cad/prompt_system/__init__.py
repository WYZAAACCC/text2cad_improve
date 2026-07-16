"""Prompt System — Prompt Registry + Prompt Compiler + Prompt Trace.

设计原则（对应 docs/提示词系统升级.md，按"架构就位、行为冻结"铁律实施）:

1. 现有生产 prompt（L1/L2 系统提示词、服务器约束块等）以**引用**方式注册为
   legacy fragment —— 零复制、单一来源，字符串内容永远与原定义处一致。
2. PromptCompiler 复现与现有生产路径**逐字节一致**的消息组合（由回归测试锁定），
   同时产出 prompt_trace（fragment 清单 + system/user prompt hash）。
3. 新增专业知识（domain/part/feature/region pack）走分层选择；legacy fragment
   标记 always_on，不参与裁剪 —— 已稳定生成模型的提示词内容不改变。
"""
from seekflow_engineering_tools.generative_cad.prompt_system.models import (
    PromptFragment,
    PromptTrace,
    FragmentUse,
)
from seekflow_engineering_tools.generative_cad.prompt_system.registry import (
    PromptRegistry,
    default_prompt_registry,
)
from seekflow_engineering_tools.generative_cad.prompt_system.compiler import (
    PromptCompiler,
    CompiledPrompt,
)

__all__ = [
    "PromptFragment",
    "PromptTrace",
    "FragmentUse",
    "PromptRegistry",
    "default_prompt_registry",
    "PromptCompiler",
    "CompiledPrompt",
]
