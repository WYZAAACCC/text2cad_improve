"""Runtime 失败可修复性分类器 (repair_loop.md §6) — fail-closed.

只有错误能明确关联到 Raw IR 参数时才允许进入 runtime repair (§6.1);
基础设施/实现/合同缺陷返回类别码而**不消耗 repair 预算** (§6.3);
无法证明因果 → unproven_causality, 不进 LLM。纯函数, 表驱动, 无 I/O。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from seekflow_engineering_tools.generative_cad.runtime.diagnostics import RuntimeReport

FailureClassCode = Literal[
    "repairable",
    "infrastructure_failure",
    "implementation_failure",
    "contract_failure",
    "unproven_causality",
]

# §6.3: handler/代码实现缺陷 — 不得让 LLM 改 IR 来"修"代码 bug
_IMPLEMENTATION_EXC = {
    "AttributeError", "NameError", "TypeError", "KeyError", "IndexError",
    "ImportError", "ModuleNotFoundError", "AssertionError", "RecursionError",
}
# §6.3: 环境/资源类
_INFRASTRUCTURE_EXC = {
    "MemoryError", "OSError", "PermissionError", "TimeoutError",
    "FileNotFoundError", "IsADirectoryError",
}
# 无节点归因也不可能由 IR 参数导致的阶段
_NON_REPAIRABLE_STAGES: dict[str, FailureClassCode] = {
    "compiler_middle_end": "implementation_failure",
    "artifact_consistency": "implementation_failure",
    "step_postcheck": "infrastructure_failure",
}
# 无节点归因但可尝试唯一候选规则的阶段 (§6.2)
_UNIQUE_CANDIDATE_STAGES = {"runtime_postconditions", "geometry_postcheck"}

_PARAMS_PATH_TMPL = r"^/nodes/{nid}/params(/.+)?$"


class RuntimeFailureClass(BaseModel):
    repairable: bool
    class_code: FailureClassCode
    reason: str
    target_node_id: str | None = None
    allowed_paths: list[str] = Field(default_factory=list)


def _not_repairable(code: FailureClassCode, reason: str) -> RuntimeFailureClass:
    return RuntimeFailureClass(repairable=False, class_code=code, reason=reason)


def classify_runtime_failure(report: RuntimeReport) -> RuntimeFailureClass:
    """判定一次 runtime 失败是否允许进入 LLM runtime repair."""
    if report.ok:
        return _not_repairable("unproven_causality", "report is ok — nothing to repair")

    primary = next((i for i in report.issues if i.severity in ("error", "fatal")),
                   report.issues[0] if report.issues else None)
    if primary is None:
        return _not_repairable("unproven_causality", "no issues recorded")

    # 1) 异常类型分流 (§6.3)
    if primary.exception_type in _IMPLEMENTATION_EXC:
        return _not_repairable(
            "implementation_failure",
            f"exception_type={primary.exception_type} indicates a code defect, not an IR parameter",
        )
    if primary.exception_type in _INFRASTRUCTURE_EXC:
        return _not_repairable(
            "infrastructure_failure",
            f"exception_type={primary.exception_type} indicates an environment/resource failure",
        )

    # 2) 阶段/合同分流 (§6.3)
    if report.failed_stage in _NON_REPAIRABLE_STAGES:
        return _not_repairable(
            _NON_REPAIRABLE_STAGES[report.failed_stage],
            f"failed_stage={report.failed_stage} cannot be caused by IR parameters",
        )
    if primary.code == "OPERATION_OUTPUT_CONTRACT_MISMATCH":
        return _not_repairable(
            "contract_failure",
            "operation registry and handler implementation disagree",
        )
    if primary.repairability == "non_repairable":
        return _not_repairable(
            "implementation_failure",
            f"issue {primary.code} declared non_repairable at raise site",
        )

    # 3) 明确节点归因 + repairable 声明 (§6.1)
    if primary.repairability == "repairable" and primary.node_id:
        pattern = re.compile(_PARAMS_PATH_TMPL.format(nid=re.escape(primary.node_id)))
        allowed = [p for p in primary.suggested_paths if pattern.match(p)]
        if not allowed:
            allowed = [f"/nodes/{primary.node_id}/params"]
        return RuntimeFailureClass(
            repairable=True, class_code="repairable",
            reason=f"issue {primary.code} attributes to node {primary.node_id} params",
            target_node_id=primary.node_id,
            allowed_paths=allowed,
        )

    # 4) 无节点归因的后置条件失败 → 唯一候选规则 (§6.2)
    if report.failed_stage in _UNIQUE_CANDIDATE_STAGES and not primary.node_id:
        unhealthy = [key for key, h in report.geometry_health.items()
                     if h.get("status") == "error"]
        # geometry_health key 形如 "<node_id>.<output>"
        nodes = sorted({k.split(".", 1)[0] for k in unhealthy})
        if len(nodes) == 1:
            nid = nodes[0]
            return RuntimeFailureClass(
                repairable=True, class_code="repairable",
                reason=(f"unique unhealthy node {nid!r} in geometry_health "
                        f"(single-candidate rule)"),
                target_node_id=nid,
                allowed_paths=[f"/nodes/{nid}/params"],
            )
        return _not_repairable(
            "unproven_causality",
            f"{len(nodes)} candidate nodes in geometry_health — causality not unique",
        )

    # 5) 其余一律 fail-closed
    return _not_repairable(
        "unproven_causality",
        f"cannot prove causality between issue {primary.code} and IR parameters",
    )
