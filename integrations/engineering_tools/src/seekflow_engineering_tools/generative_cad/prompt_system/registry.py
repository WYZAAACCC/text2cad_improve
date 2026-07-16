"""PromptRegistry — 提示词注册表.

所有生产 prompt 以引用方式注册 (见 fragments_legacy.py)。新增专业知识 pack
按 layer/tags 注册后, 由 PromptCompiler.select 按命中标签选择。
"""
from __future__ import annotations
from functools import lru_cache

from seekflow_engineering_tools.generative_cad.prompt_system.models import PromptFragment


class PromptRegistryError(RuntimeError):
    pass


class PromptRegistry:
    def __init__(self) -> None:
        self._fragments: dict[str, PromptFragment] = {}
        self._frozen = False

    # ---- 注册 ----
    def register(self, fragment: PromptFragment) -> None:
        if self._frozen:
            raise PromptRegistryError("registry is frozen")
        if fragment.id in self._fragments:
            raise PromptRegistryError(f"duplicate fragment id: {fragment.id}")
        self._fragments[fragment.id] = fragment

    def freeze(self) -> None:
        self._frozen = True

    # ---- 查询 ----
    def get(self, fragment_id: str) -> PromptFragment | None:
        return self._fragments.get(fragment_id)

    def list_ids(self) -> list[str]:
        return sorted(self._fragments)

    def select(self, *, stage: str | None = None, tags: set[str] | None = None) -> list[PromptFragment]:
        """按阶段与标签选择 fragment (always_on 恒选中).

        返回按 priority 降序排列的列表; requires 缺失或 excludes 冲突时抛错
        (fail-closed: 冲突时停止编译, 不静默覆盖)。
        """
        tags = tags or set()
        picked: list[PromptFragment] = []
        for f in self._fragments.values():
            if f.always_on:
                picked.append(f)
                continue
            if stage is not None and f.stages and stage not in f.stages:
                continue
            if f.tags and not (set(f.tags) & tags):
                continue
            if not f.tags:
                # 无标签的非 always_on fragment 只按 stage 命中
                if stage is None or not f.stages:
                    continue
            picked.append(f)

        ids = {f.id for f in picked}
        for f in picked:
            for req in f.requires:
                if req not in ids:
                    raise PromptRegistryError(
                        f"fragment {f.id!r} requires {req!r} which was not selected")
            for exc in f.excludes:
                if exc in ids:
                    raise PromptRegistryError(
                        f"fragment conflict: {f.id!r} excludes {exc!r} — refuse to compile")
        picked.sort(key=lambda f: (-f.priority, f.id))
        return picked


@lru_cache(maxsize=1)
def default_prompt_registry() -> PromptRegistry:
    """构建默认注册表: 登记全部 legacy 生产 fragment + 领域技能引用."""
    from seekflow_engineering_tools.generative_cad.prompt_system.fragments_legacy import (
        register_legacy_fragments,
    )
    reg = PromptRegistry()
    register_legacy_fragments(reg)
    reg.freeze()
    return reg
