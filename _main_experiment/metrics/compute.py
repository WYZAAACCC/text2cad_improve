"""Convenience runner that invokes all metric computers for one experiment run."""

from __future__ import annotations

from pathlib import Path

from ..config import ExperimentConfig
from ..schemas import MetricResult, RunResult, TaskSpec
from .geometry import GeometryMetricsComputer
from .regen_repair import RegenerationRepairMetricsComputer
from .semantics import SemanticMetricsComputer


def compute_all_metrics(
    *,
    run_dir: Path,
    task_spec: TaskSpec,
    run_result: RunResult,
    config: ExperimentConfig,
) -> list[MetricResult]:
    computers = [
        SemanticMetricsComputer(),
        GeometryMetricsComputer(),
        RegenerationRepairMetricsComputer(),
    ]
    metrics: list[MetricResult] = []
    for computer in computers:
        try:
            metrics.extend(computer.compute(
                run_dir=run_dir,
                task_spec=task_spec,
                run_result=run_result,
                config=config,
            ))
        except Exception as exc:  # noqa: BLE001
            metrics.append(MetricResult(
                metric_id="metric_computer_error",
                name=type(computer).__name__,
                value=False,
                passed=False,
                notes=str(exc)[:300],
            ))
    return metrics
