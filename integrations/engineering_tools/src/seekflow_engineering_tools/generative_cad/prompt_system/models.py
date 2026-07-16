"""Prompt Fragment / Trace 数据模型.

PromptFragment 是版本化的提示词单元（docs/提示词系统升级.md 第五节）。
legacy fragment 的 body 用 lazy callable 引用原始字符串常量 —— 不复制内容，
保证与 skills/prompts.py 等原定义处永远一致（铁律: 不改已有 prompt 内容）。
"""
from __future__ import annotations
import hashlib
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

FragmentLayer = Literal[
    "core", "stage", "contract", "domain", "part",
    "feature", "region", "task", "backend", "legacy",
]

FragmentStrength = Literal["must", "must_not", "should", "info"]


class RuleClaim(BaseModel):
    """机器可读的规则声明, 供编译器做冲突检测."""
    rule_id: str
    strength: FragmentStrength = "info"
    key: str = ""
    value: object = None


class PromptFragment(BaseModel):
    """版本化提示词单元.

    body 二选一:
      - body: 字面字符串 (新增 fragment 用)
      - body_ref: 无参 callable, 返回字符串 (legacy fragment 用 — 引用原常量,
        单一来源, 内容变更只发生在原定义处)
    """
    model_config = {"arbitrary_types_allowed": True}

    id: str
    version: str = "1.0.0"
    layer: FragmentLayer = "legacy"
    stages: tuple[str, ...] = ()          # 适用阶段; 空=全部
    tags: tuple[str, ...] = ()            # domain/part/feature/region 命中标签
    requires: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    priority: int = 0
    always_on: bool = False               # legacy 生产 prompt: 恒注入, 不参与裁剪
    source: str = ""                      # 原定义处 (module:CONSTANT), 供审计
    rules: tuple[RuleClaim, ...] = ()
    body: Optional[str] = None
    body_ref: Optional[Callable[[], str]] = Field(default=None, exclude=True)

    def resolve_body(self) -> str:
        if self.body_ref is not None:
            return self.body_ref()
        return self.body or ""

    def body_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.resolve_body().encode("utf-8")).hexdigest()


class FragmentUse(BaseModel):
    """trace 中的单条 fragment 使用记录."""
    id: str
    version: str
    source: str = ""
    reason: str = ""
    hash: str = ""


class PromptTrace(BaseModel):
    """一次模型调用的提示词追踪记录 (prompt_trace.json)."""
    request_id: str = ""
    stage: str = ""
    compiler_version: str = ""
    selected_fragments: list[FragmentUse] = Field(default_factory=list)
    rejected_fragments: list[dict] = Field(default_factory=list)
    system_prompt_hash: str = ""
    user_prompt_hash: str = ""
    system_prompt_chars: int = 0
    user_prompt_chars: int = 0


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
