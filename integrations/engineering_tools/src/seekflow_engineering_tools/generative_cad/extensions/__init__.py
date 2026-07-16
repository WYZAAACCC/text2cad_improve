"""内置扩展装配入口 — Kernel 经由本统一接口加载扩展, 不认识任何具体扩展.

新增内置扩展: 只修改本文件的注册清单与扩展包本身,
不得修改 validation_kernel/ 任何文件 (指导书验收标准 1/3)。
"""
from __future__ import annotations


def register_builtin_extensions(reg) -> None:
    """把仓库内置扩展注册进 RuleRegistry (统一注册接口, 无 Kernel 特判)."""
    from seekflow_engineering_tools.generative_cad.extensions.features.hole import (
        build_extension as build_hole_extension,
    )
    for build in (build_hole_extension,):
        build(reg)
