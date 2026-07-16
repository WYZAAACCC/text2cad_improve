"""Repair Providers — Issue-driven 修复提供者.

Phase 3: LegacyAutoFixProvider 把现有 auto_fix 链包装进新框架 (指导书 §17
Phase 3: "保留 auto_fixer.py 作为兼容入口, 但内部必须调用新 Repair Engine"
的对偶实现 — engine 调用 legacy 链)。
风险如实标注 mixed_legacy (旧链混杂 alias/schema/语义级修复, §1.5);
细粒度 Provider (订阅具体 issue code) 属 Phase 4+ 按扩展逐个抽取。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
    RepairProviderManifest,
)


class LegacyAutoFixProvider:
    """包装 authoring.auto_fixer.auto_fix_with_report 全链.

    合同:
    - 只在验证失败后由 engine 以具体 issues 触发 (不再由调用方盲跑);
    - 修复在文档深拷贝上执行 (auto_fix_with_report 内部保证), 原文档不动;
    - 修复结果必须经 engine 的质量向量验收, 否则丢弃 (原子性)。
    """

    manifest = RepairProviderManifest(
        provider_id="repair.legacy_autofix_chain",
        version="1.0.0",
        handles_issue_codes={"*"},
        risk="mixed_legacy",
        deterministic=True,
    )

    def __init__(self, dialect_registry=None) -> None:
        self._dialect_registry = dialect_registry

    def propose(self, raw_doc: dict, issues: list) -> tuple[dict, list[str]]:
        """返回 (fixed_doc, applied_rule_ids)。fixed_doc 是新对象。"""
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import (
            auto_fix_with_report,
        )
        fixed, af_report = auto_fix_with_report(raw_doc, self._dialect_registry)
        rule_ids = [e.rule_id for e in af_report.entries]
        self.last_report = af_report  # main.py 落盘 autofix_report.json 用
        return fixed, rule_ids
