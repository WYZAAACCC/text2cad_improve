"""Validation Kernel — Rule Registry (§5, §7.1 启动期冲突治理).

Kernel 不 import 任何具体 dialect/feature/part 模块 (不可妥协原则 3):
legacy 规则的 validator callable 由 legacy_adapter 注入, registry 只见合同。
"""
from __future__ import annotations
from functools import lru_cache
from typing import Callable

from seekflow_engineering_tools.generative_cad.validation_kernel.models import (
    ActivationSnapshot,
    ExtensionManifest,
    RuleLayer,
    RuleManifest,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.stages import (
    ValidationStage,
    FULL_STAGE_ORDER,
)


class RuleRegistryError(RuntimeError):
    pass


class RegisteredRule:
    """manifest + evaluate callable (validator(subject) -> ValidationReport)."""

    def __init__(self, manifest: RuleManifest, evaluate: Callable) -> None:
        self.manifest = manifest
        self.evaluate = evaluate


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, RegisteredRule] = {}
        self._extensions: dict[str, ExtensionManifest] = {}
        self._frozen = False

    # ---- 注册 ----
    def register_rule(self, manifest: RuleManifest, evaluate: Callable) -> None:
        if self._frozen:
            raise RuleRegistryError("registry is frozen")
        if manifest.rule_id in self._rules:
            raise RuleRegistryError(f"duplicate rule_id: {manifest.rule_id}")
        self._rules[manifest.rule_id] = RegisteredRule(manifest, evaluate)

    def register_extension(self, manifest: ExtensionManifest) -> None:
        if self._frozen:
            raise RuleRegistryError("registry is frozen")
        if manifest.extension_id in self._extensions:
            raise RuleRegistryError(f"duplicate extension_id: {manifest.extension_id}")
        self._extensions[manifest.extension_id] = manifest

    def freeze(self) -> None:
        self._governance_check()
        self._frozen = True

    # ---- 启动期治理 (§7.1, fail-closed) ----
    def _governance_check(self) -> None:
        # extension 依赖缺失 / 显式冲突
        for ext in self._extensions.values():
            for req in ext.requires_extensions:
                if req not in self._extensions:
                    raise RuleRegistryError(
                        f"extension {ext.extension_id!r} requires missing {req!r}")
            for bad in ext.conflicts_with:
                if bad in self._extensions:
                    raise RuleRegistryError(
                        f"extension conflict: {ext.extension_id!r} vs {bad!r}")
        # before/after DAG 环检测
        ids = set(self._rules)
        edges: dict[str, set[str]] = {rid: set() for rid in ids}
        for rid, rr in self._rules.items():
            for b in rr.manifest.before:
                if b in ids:
                    edges[rid].add(b)          # rid 先于 b
            for a in rr.manifest.after:
                if a in ids:
                    edges[a].add(rid)          # a 先于 rid
        state: dict[str, int] = {}

        def dfs(u: str) -> None:
            state[u] = 1
            for v in edges[u]:
                if state.get(v) == 1:
                    raise RuleRegistryError(f"rule ordering cycle involving {u!r} -> {v!r}")
                if state.get(v, 0) == 0:
                    dfs(v)
            state[u] = 2

        for rid in ids:
            if state.get(rid, 0) == 0:
                dfs(rid)

    # ---- 查询/选择 ----
    def get(self, rule_id: str) -> RegisteredRule | None:
        return self._rules.get(rule_id)

    def list_rule_ids(self) -> list[str]:
        return sorted(self._rules)

    def select(self, stage: ValidationStage,
               activation: ActivationSnapshot | None = None) -> list[RegisteredRule]:
        """按 stage 选择激活的规则, 输出顺序确定 (注册序).

        Extension 只能新增规则, 不能屏蔽 Core (不可妥协原则 4):
        Core 规则永远入选, Extension 规则按 selector 匹配。
        """
        activation = activation or ActivationSnapshot()
        picked: list[RegisteredRule] = []
        for rr in self._rules.values():
            m = rr.manifest
            if m.stage != stage:
                continue
            if m.layer == RuleLayer.CORE:
                picked.append(rr)
            elif m.selector.matches(activation):
                picked.append(rr)
        return picked


@lru_cache(maxsize=1)
def default_rule_registry() -> RuleRegistry:
    """默认注册表: Core legacy 规则 + 内置扩展 (统一注册接口, 无 Kernel 特判)."""
    from seekflow_engineering_tools.generative_cad.validation_kernel.legacy_adapter import (
        register_legacy_core_rules,
    )
    from seekflow_engineering_tools.generative_cad.extensions.features.hole import (
        build_extension as build_hole_extension,
    )
    reg = RuleRegistry()
    register_legacy_core_rules(reg)
    build_hole_extension(reg)
    reg.freeze()
    return reg
