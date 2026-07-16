"""Repair Providers — Issue-driven 修复提供者.

Phase 3: LegacyAutoFixProvider 把现有 auto_fix 链包装进新框架。
Phase 5 试点: OpVersionRepairProvider — 首个细粒度 Provider, 订阅具体
issue code, 只做合同派生级修复 (contract_derived, 指导书 §9.1)。
细粒度 Provider 全量就位后 legacy 链退役。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
    RepairProviderManifest,
)


class OpVersionRepairProvider:
    """op_version 合同派生修复 — 订阅 registry 阶段的具体 issue code.

    只处理 "LLM 把 dialect 版本当 op 版本 / 漏填 / 带 v 前缀" 这一类
    可从 OperationSpec 唯一确定的修复 (§9.1 合同派生), 不触碰其它字段。
    复用 auto_fixer._fix_op_versions 的确定性实现 (单一来源)。
    """

    manifest = RepairProviderManifest(
        provider_id="repair.contract.op_version",
        version="1.0.0",
        # 只订阅本 Provider 真正能修的 code (dialect_version_mismatch 属
        # selected_dialects[].version, 非本 Provider 能力 — 审查 L4)
        handles_issue_codes={"unknown_op"},
        risk="contract_derived",
        deterministic=True,
    )

    def __init__(self, dialect_registry=None) -> None:
        self._dialect_registry = dialect_registry
        self.last_report = None  # 与 Legacy provider 接口对齐 (无整链报告)

    def propose(self, raw_doc: dict, issues: list) -> tuple[dict, list[str]]:
        import copy
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import (
            _fix_op_versions,
        )
        from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash

        before = stable_hash(raw_doc)
        candidate = _fix_op_versions(copy.deepcopy(raw_doc), self._dialect_registry)
        if stable_hash(candidate) == before:
            return raw_doc, []          # 无可修复项
        return candidate, ["fix_op_versions"]


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
        self.last_report = None

    def propose(self, raw_doc: dict, issues: list) -> tuple[dict, list[str]]:
        """返回 (fixed_doc, applied_rule_ids)。fixed_doc 是新对象。

        applied_rule_ids 只含**实际生效**的修复 (过滤链内被 category 策略
        跳过的 '<skipped>' 占位条目); 文档未变时返回空列表 — 否则 engine 的
        "no fixes applicable" 分支不可达且审计失真 (审查 M1)。
        """
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import (
            auto_fix_with_report,
        )
        fixed, af_report = auto_fix_with_report(raw_doc, self._dialect_registry)
        self.last_report = af_report  # main.py 落盘 autofix_report.json 用
        if not af_report.applied:
            return raw_doc, []
        rule_ids = [e.rule_id for e in af_report.entries
                    if e.old_value != "<skipped>"]
        return fixed, rule_ids


def provider_matches(provider, issue_codes: set[str]) -> bool:
    """Provider 订阅匹配: 通配 '*' 或与当前 error issue codes 有交集."""
    handles = provider.manifest.handles_issue_codes
    return "*" in handles or bool(handles & issue_codes)


def default_providers(dialect_registry=None) -> list:
    """默认 Provider 链: 细粒度优先, legacy 兜底."""
    return [
        OpVersionRepairProvider(dialect_registry),
        LegacyAutoFixProvider(dialect_registry),
    ]
