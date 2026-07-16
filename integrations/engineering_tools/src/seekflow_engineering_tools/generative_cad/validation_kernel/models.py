"""Validation Kernel — 统一 Rule / Extension 数据模型.

对应指导书 §5 (RuleManifest/RuleSelector) 与 §6 (ExtensionManifest/Activation)。
Phase 1: 模型就位 + legacy 包装; ValidationIssue v2 (§5.5) 属 Phase 2
(扩展现有 Issue 模型会波及全部 validator 输出, 违反行为冻结)。
"""
from __future__ import annotations
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from seekflow_engineering_tools.generative_cad.validation_kernel.stages import ValidationStage


class RuleLayer(str, Enum):
    CORE = "core"
    EXTENSION = "extension"


class RuleSelector(BaseModel):
    """规则激活选择器 — 只允许明确元数据, 禁止名称字符串猜测 (§5.2)."""
    always: bool = False
    dialects: set[str] = Field(default_factory=set)
    operations: set[str] = Field(default_factory=set)
    feature_tags: set[str] = Field(default_factory=set)
    part_families: set[str] = Field(default_factory=set)
    domain_skills: set[str] = Field(default_factory=set)

    def matches(self, activation: "ActivationSnapshot") -> bool:
        if self.always:
            return True
        return bool(
            (self.dialects & activation.dialects)
            or (self.operations & activation.operations)
            or (self.feature_tags & activation.feature_tags)
            or (self.part_families & activation.part_families)
            or (self.domain_skills & activation.domain_skills)
        )


class RuleManifest(BaseModel):
    """每条验证规则的合同 (§5.1)."""
    rule_id: str                       # 全局唯一, 带 namespace, 如 core.legacy.structure
    version: str = "1.0.0"
    provider_id: str = "core"
    layer: RuleLayer = RuleLayer.CORE
    stage: ValidationStage

    selector: RuleSelector = Field(default_factory=lambda: RuleSelector(always=True))
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)

    requires_facts: list[str] = Field(default_factory=list)
    produces_facts: list[str] = Field(default_factory=list)
    emitted_issue_codes: list[str] = Field(default_factory=list)

    deterministic: bool = True
    side_effect_free: bool = True
    estimated_cost: Literal["cheap", "normal", "expensive"] = "cheap"
    failure_policy: Literal["fail_closed", "report_provider_error"] = "report_provider_error"


class RuleExecutionRecord(BaseModel):
    """单条规则执行记录 (§15.2) — 跳过/异常不得静默消失."""
    rule_id: str
    rule_version: str = "1.0.0"
    provider_id: str = "core"
    stage: str = ""
    status: Literal["passed", "failed", "skipped", "provider_error"] = "passed"
    duration_ms: float = 0.0
    issue_count: int = 0
    skip_reason: Optional[str] = None


class ActivationSnapshot(BaseModel):
    """一次验证任务的不可变激活快照 (§6.3).

    Phase 1: 生产路径全部 Core (always) 规则, 快照为空集即可。
    Phase 4 起由 ActivationResolver 从 part_intent/selected_domain_skills/
    canonical graph 构建。
    """
    dialects: set[str] = Field(default_factory=set)
    operations: set[str] = Field(default_factory=set)
    feature_tags: set[str] = Field(default_factory=set)
    part_families: set[str] = Field(default_factory=set)
    domain_skills: set[str] = Field(default_factory=set)
    mode: Literal["enforce", "advisory"] = "enforce"


class ExtensionManifest(BaseModel):
    """扩展包合同 (§6.1). Phase 1 仅登记模型; 首个真实扩展在 Phase 4."""
    extension_id: str
    version: str = "1.0.0"
    kind: Literal["feature", "dialect", "part_family", "domain"]
    selectors: list[RuleSelector] = Field(default_factory=list)
    requires_extensions: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    enabled_by_default: bool = True
