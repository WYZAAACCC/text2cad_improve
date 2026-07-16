"""Extension Activation Resolver (§6.2).

从文档自身的**明确元数据**构建激活快照 — 确定性来源:
canonical/raw graph 实际使用的 dialect 与 operation。
禁止名称字符串猜测 ("cutter" in name 之类, §5.2/§12)。

part_family / domain_skills 激活 (来自 L1 part_intent / selected_domain_skills)
由调用方显式传入 — 文档内部无此信息, 不猜。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.validation_kernel.models import (
    ActivationSnapshot,
)


def resolve_activation_from_document(doc) -> ActivationSnapshot:
    """RawGcadDocument (已解析) → ActivationSnapshot."""
    dialects: set[str] = set()
    operations: set[str] = set()
    try:
        for sd in getattr(doc, "selected_dialects", []) or []:
            d = getattr(sd, "dialect", None)
            if d:
                dialects.add(d)
        for node in getattr(doc, "nodes", []) or []:
            d = getattr(node, "dialect", None)
            op = getattr(node, "op", None)
            if d:
                dialects.add(d)
            if op:
                operations.add(op)
    except Exception:
        # 激活解析失败时回退为空快照: Core 规则仍全部运行 (fail-safe 方向正确 —
        # 只可能少跑扩展规则, 不可能屏蔽 Core)
        return ActivationSnapshot()
    return ActivationSnapshot(dialects=dialects, operations=operations)
