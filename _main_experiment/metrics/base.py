"""Metric computer protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config import ExperimentConfig
from ..schemas import MetricResult, RunResult, TaskSpec


class MetricComputer(Protocol):
    def compute(
        self,
        *,
        run_dir: Path,
        task_spec: TaskSpec,
        run_result: RunResult,
        config: ExperimentConfig,
    ) -> list[MetricResult]:
        ...
