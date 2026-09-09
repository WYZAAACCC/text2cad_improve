"""Benchmark runner: method x task x seed orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from .config import ExperimentConfig
from .llm import BenchLlmClient, OpenAICompatToolClient
from .paths import run_dir
from .pipeline import run_experiment_task
from .schemas import MethodSpec, RunResult, TaskSpec
from .utils import atomic_write_json
from .metrics.compute import compute_all_metrics

ClientFactory = Callable[[MethodSpec, TaskSpec, int], BenchLlmClient]


def _run_complete(run_path: Path) -> bool:
    run_json = run_path / "run.json"
    if not run_json.exists():
        return False
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("status") == "completed"


def run_task(
    task_spec: TaskSpec,
    method_spec: MethodSpec,
    seed: int,
    config: ExperimentConfig,
    client: BenchLlmClient | None = None,
) -> RunResult:
    result = run_experiment_task(task_spec, method_spec, seed, config, client=client)
    if not result.record_id:
        from .suites.base import iso_now, record_id
        result.record_id = record_id(
            "run", method_id=result.method_id,
            task_id=result.task_id, seed=result.seed,
            started_at=result.started_at,
        )
        result.collected_at = result.collected_at or iso_now()
    run_path = run_dir(method_spec.method_id, task_spec.task_id, seed, config=config)
    try:
        metrics = compute_all_metrics(
            run_dir=run_path,
            task_spec=task_spec,
            run_result=result,
            config=config,
        )
        result.metrics = metrics
        atomic_write_json(run_path / "metrics.json", [
            m.model_dump(mode="json") for m in metrics
        ])
        atomic_write_json(run_path / "run.json", result.model_dump(mode="json"))
    except Exception:  # noqa: BLE001
        pass
    return result


def run_benchmark(
    tasks: Iterable[TaskSpec],
    methods: Iterable[MethodSpec],
    seeds: Iterable[int],
    config: ExperimentConfig,
    client_factory: ClientFactory | None = None,
) -> list[RunResult]:
    results: list[RunResult] = []
    task_list = list(tasks)
    method_list = list(methods)
    seed_list = list(seeds)

    for method_spec in method_list:
        for task_spec in task_list:
            for seed in seed_list:
                run_path = run_dir(method_spec.method_id, task_spec.task_id, seed, config=config)
                if config.runner.resume and _run_complete(run_path):
                    continue
                client = None
                if client_factory is not None:
                    client = client_factory(method_spec, task_spec, seed)
                else:
                    client = OpenAICompatToolClient()
                results.append(run_task(task_spec, method_spec, seed, config, client=client))
    return results


def write_results(results: Iterable[RunResult], path: str | Path) -> Path:
    return atomic_write_json(
        path,
        [result.model_dump(mode="json") for result in results],
    )
