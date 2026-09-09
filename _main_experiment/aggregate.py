"""Aggregate benchmark RunResults into paper-style summary tables."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .config import ExperimentConfig
from .paths import experiment_output_root
from .schemas import MetricResult, RunResult, TaskSpec
from .utils import atomic_write_json
from .suites.base import iso_now


def load_runs(config: ExperimentConfig) -> list[RunResult]:
    root = experiment_output_root(config) / "runs"
    results: list[RunResult] = []
    if not root.exists():
        return results
    for run_file in root.rglob("run.json"):
        if not any("seed_" in part for part in run_file.parts):
            continue
        try:
            result = RunResult.model_validate(json.loads(run_file.read_text(encoding="utf-8")))
            metrics_file = run_file.parent / "metrics.json"
            if metrics_file.exists():
                result.metrics = [
                    MetricResult.model_validate(item)
                    for item in json.loads(metrics_file.read_text(encoding="utf-8"))
                ]
            results.append(result)
        except Exception:
            continue
    return results


def load_tasks(config: ExperimentConfig) -> list[TaskSpec]:
    tasks_file = experiment_output_root(config) / "tasks.json"
    if not tasks_file.exists():
        return []
    from .tasks.registry import load_tasks_file
    return load_tasks_file(tasks_file)


def _success_flags(result: RunResult) -> dict[str, bool]:
    final_ok = bool(result.ok)
    pass1 = bool(result.ok and result.repair_rounds == 0 and result.attempts_used == 1)
    cad_pass1 = pass1 and "step" in result.outputs and Path(result.outputs["step"]).exists()
    return {"final_ok": final_ok, "pass1": pass1, "cad_pass1": cad_pass1}


def _task_seconds(result: RunResult) -> float | None:
    from datetime import datetime
    if not result.started_at or not result.finished_at:
        return None
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        start = datetime.fromisoformat(result.started_at)
        end = datetime.fromisoformat(result.finished_at)
        return round((end - start).total_seconds(), 2)
    except Exception:  # noqa: BLE001
        return None


def _metric_value(result: RunResult, metric_id: str):
    for metric in result.metrics:
        if metric.metric_id == metric_id:
            return metric.value
    return None


def aggregate_by_method(results: Iterable[RunResult]) -> list[dict[str, Any]]:
    groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        groups[result.method_id].append(result)

    rows = []
    for method_id, runs in sorted(groups.items()):
        flags = [_success_flags(r) for r in runs]
        final_ok = sum(1 for f in flags if f["final_ok"])
        pass1 = sum(1 for f in flags if f["pass1"])
        cad_pass1 = sum(1 for f in flags if f["cad_pass1"])
        total = max(1, len(runs))
        rows.append({
            "method_id": method_id,
            "runs": len(runs),
            "engineering_pass1": round(pass1 / total, 4),
            "cad_pass1": round(cad_pass1 / total, 4),
            "final_success": round(final_ok / total, 4),
            "average_repair_rounds": round(
                sum(r.repair_rounds for r in runs) / total, 4
            ),
            "average_total_tokens": round(
                sum((r.usage or {}).get("total_tokens", 0) for r in runs) / total, 2
            ),
            "average_task_seconds": round(
                sum(s for s in (_task_seconds(r) for r in runs) if s is not None) / total, 2
            ) if any(_task_seconds(r) is not None for r in runs) else None,
            "average_key_dimension_relative_error_pct": round(
                sum(v for v in (_metric_value(r, "key_dimension_relative_error") for r in runs)
                    if isinstance(v, (int, float)))
                / max(1, sum(1 for r in runs
                             if isinstance(_metric_value(r, "key_dimension_relative_error"), (int, float)))), 6
            ) if any(isinstance(_metric_value(r, "key_dimension_relative_error"), (int, float))
                     for r in runs) else None,
            "average_parameter_extraction_accuracy": round(
                sum(v for v in (_metric_value(r, "parameter_extraction_accuracy") for r in runs)
                    if isinstance(v, (int, float)))
                / max(1, sum(1 for r in runs
                             if isinstance(_metric_value(r, "parameter_extraction_accuracy"), (int, float)))), 4
            ) if any(isinstance(_metric_value(r, "parameter_extraction_accuracy"), (int, float))
                     for r in runs) else None,
        })
    return rows


def aggregate_by_level(
    results: Iterable[RunResult],
    tasks: Iterable[TaskSpec],
) -> list[dict[str, Any]]:
    task_map = {t.task_id: t for t in tasks}
    groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        task = task_map.get(result.task_id)
        groups[(task.level.value if task else "unknown")].append(result)
    rows = []
    for level, runs in sorted(groups.items()):
        flags = [_success_flags(r) for r in runs]
        total = max(1, len(runs))
        rows.append({
            "level": level,
            "runs": len(runs),
            "engineering_pass1": round(sum(1 for f in flags if f["pass1"]) / total, 4),
            "final_success": round(sum(1 for f in flags if f["final_ok"]) / total, 4),
            "average_repair_rounds": round(
                sum(r.repair_rounds for r in runs) / total, 4
            ),
            "average_key_dimension_relative_error_pct": round(
                sum(v for v in (_metric_value(r, "key_dimension_relative_error") for r in runs)
                    if isinstance(v, (int, float)))
                / max(1, sum(1 for r in runs
                             if isinstance(_metric_value(r, "key_dimension_relative_error"), (int, float)))), 6
            ) if any(isinstance(_metric_value(r, "key_dimension_relative_error"), (int, float))
                     for r in runs) else None,
        })
    return rows


def aggregate_by_slot(
    results: Iterable[RunResult],
    tasks: Iterable[TaskSpec],
) -> list[dict[str, Any]]:
    task_map = {t.task_id: t for t in tasks}
    groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        task = task_map.get(result.task_id)
        has_slot = bool(task and task.gold.slot_reference is not None)
        groups["slot" if has_slot else "no_slot"].append(result)
    rows = []
    for key, runs in sorted(groups.items()):
        flags = [_success_flags(r) for r in runs]
        total = max(1, len(runs))
        rows.append({
            "group": key,
            "runs": len(runs),
            "engineering_pass1": round(sum(1 for f in flags if f["pass1"]) / total, 4),
            "final_success": round(sum(1 for f in flags if f["final_ok"]) / total, 4),
        })
    return rows


def aggregate_all(
    results: Iterable[RunResult],
    tasks: Iterable[TaskSpec],
    *,
    method_id: str | None = None,
) -> dict[str, Any]:
    results = list(results)
    if method_id:
        results = [r for r in results if r.method_id == method_id]
    tasks = list(tasks)
    return {
        "runs": len(results),
        "methods": aggregate_by_method(results),
        "levels": aggregate_by_level(results, tasks),
        "slots": aggregate_by_slot(results, tasks),
    }


def write_aggregate(path: str | Path, aggregate: dict[str, Any]) -> Path:
    envelope = {
        "schema_version": "aggregate_v1",
        "experiment_id": "main_benchmark",
        "generated_at": iso_now(),
        **aggregate,
    }
    return atomic_write_json(path, envelope)
