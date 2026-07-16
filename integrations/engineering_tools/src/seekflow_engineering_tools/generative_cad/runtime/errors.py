"""Typed runtime exception (repair_loop.md §5.3, Stage B).

GcadRuntimeError 携带结构化 RuntimeIssue 穿越 runtime 调用栈, 由
pipeline/run.py 的 catch-all 归一化进 RuntimeReport。继承 RuntimeError
且 str(exc)==issue.message —— 所有既有 `except RuntimeError` 与
错误字符串匹配保持不变。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.runtime.diagnostics import RuntimeIssue


class GcadRuntimeError(RuntimeError):
    def __init__(
        self,
        issue: RuntimeIssue,
        *,
        node_snapshot: dict | None = None,
        geometry_health: dict | None = None,
    ) -> None:
        super().__init__(issue.message)
        self.issue = issue
        self.node_snapshot = node_snapshot
        self.geometry_health = geometry_health
