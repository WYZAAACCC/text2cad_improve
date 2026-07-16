"""Runtime 结构化诊断模型 (repair_loop.md §5.2, Stage B).

RuntimeReport 取代 "全部证据压平为 error:str" 的失败出口 —— error 字符串
保留为兼容摘要, 结构化证据 (failing node / geometry health / metrics /
可修复性分级) 供 repair_kernel 分类器与审计使用。

只包含今日可填充字段; §5.2 的 inspection_report/cause_chain/约束范围
无生产者, 暂不建 (有需要时进 evidence)。§5.1 的统一 RepairIssue 延后 —
validation 保留 ValidationIssue, runtime 用本模块 RuntimeIssue。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Repairability = Literal[
    "repairable",                # 错误可明确归因到 Raw IR 参数 (§6.1)
    "conditionally_repairable",  # 需更严格策略/唯一候选证据 (§6.2)
    "non_repairable",            # 基础设施/实现/合同缺陷, 禁进 LLM (§6.3)
    "unknown",                   # 未分类 — 分类器按 fail-closed 处理
]


class RuntimeIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["runtime"] = "runtime"
    stage: str                          # operation_execution / runtime_postconditions / ...
    code: str
    severity: Literal["warning", "error", "fatal"] = "error"
    message: str
    node_id: str | None = None
    component_id: str | None = None
    dialect: str | None = None
    operation: str | None = None
    operation_version: str | None = None
    path: str | None = None
    expected: Any | None = None
    actual: Any | None = None
    exception_type: str | None = None
    repairability: Repairability = "unknown"
    suggested_paths: list[str] = Field(default_factory=list)   # 节点 id 语法: /nodes/<id>/params
    evidence: dict[str, Any] = Field(default_factory=dict)


class RuntimeReport(BaseModel):
    """runtime 一次执行的结构化结果 — 成功也产出 (ok=True, 供进度评分)."""

    ok: bool
    failed_stage: str | None = None
    issues: list[RuntimeIssue] = Field(default_factory=list)
    failing_node_id: str | None = None
    failing_component_id: str | None = None
    failing_operation: str | None = None
    geometry_health: dict[str, dict[str, Any]] = Field(default_factory=dict)
    operation_metrics: list[dict[str, Any]] = Field(default_factory=list)
    degraded_features: list[dict[str, Any]] = Field(default_factory=list)
    runtime_postconditions: dict[str, Any] | None = None
    geometry_postcheck: dict[str, Any] | None = None
    sanitized_traceback: list[str] = Field(default_factory=list)
