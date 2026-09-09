"""Regeneration and repair-loop metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters import call_mcp_tool
from ..config import ExperimentConfig
from ..schemas import MetricResult, RunResult, TaskSpec


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def regeneration_metric(run_dir: Path) -> MetricResult:
    try:
        listed = call_mcp_tool("list_regeneratable_params", {"base_dir": str(run_dir)})
        params = listed.get("parameters") or []
        if not params:
            return MetricResult(
                metric_id="regeneration_skipped",
                name="参数再生",
                value=None,
                passed=None,
                notes="没有可再生成参数",
            )
        param = params[0]
        current = param.get("current")
        if current is None:
            return MetricResult(
                metric_id="regeneration_skipped",
                name="参数再生",
                value=None,
                passed=None,
                notes="首个参数缺少当前值",
            )
        low, high = param.get("range") or (0.0, current * 2)
        new_value = max(low, min(high, current * 1.05))
        result = call_mcp_tool("regenerate_model", {
            "base_dir": str(run_dir),
            "param_updates": [{"param_key": param["param_key"], "new_value": new_value}],
        })
        return MetricResult(
            metric_id="regeneration_ok",
            name="参数再生成功率",
            value=1.0 if result.get("ok") else 0.0,
            unit="ratio",
            level="task",
            passed=bool(result.get("ok")),
            notes=str(result.get("reason") or result.get("error") or "")[:200],
        )
    except Exception as exc:  # noqa: BLE001
        return MetricResult(
            metric_id="regeneration_error",
            name="参数再生",
            value=False,
            passed=False,
            notes=str(exc)[:200],
        )


def repair_metric(run_result: RunResult) -> MetricResult:
    return MetricResult(
        metric_id="repair_rounds",
        name="修复轮数",
        value=run_result.repair_rounds,
        unit="round",
        level="task",
        passed=run_result.ok,
    )


def failure_category_metric(run_result: RunResult) -> MetricResult:
    stage = run_result.error_stage or "none"
    if run_result.ok:
        category = "success"
    elif stage in ("mcp_gate", "runtime", "validation"):
        category = stage
    elif stage == "llm":
        category = "llm_failure"
    else:
        category = "other"
    return MetricResult(
        metric_id="failure_category",
        name="失败模式分类",
        value=category,
        level="task",
        passed=run_result.ok,
    )


class RegenerationRepairMetricsComputer:
    def compute(
        self,
        *,
        run_dir: Path,
        task_spec: TaskSpec,
        run_result: RunResult,
        config: ExperimentConfig,
    ) -> list[MetricResult]:
        metrics = [repair_metric(run_result), failure_category_metric(run_result)]
        if run_result.ok:
            metrics.append(regeneration_metric(run_dir))
        return metrics
