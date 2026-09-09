"""Path helpers for the isolated experiment output tree."""

from __future__ import annotations

from pathlib import Path

from .config import ExperimentConfig

MAIN_EXPERIMENT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = MAIN_EXPERIMENT_ROOT / "output"


def ensure_inside_experiment_output(
    path: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Resolve a path and require it to stay inside the experiment output root."""
    root = Path(output_root).resolve()
    resolved = Path(path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes experiment output root: {resolved}")
    return resolved


def experiment_output_root(config: ExperimentConfig | None = None) -> Path:
    if config is None:
        return DEFAULT_OUTPUT_ROOT.resolve()
    return config.resolved_output_root()


def method_dir(
    method_id: str,
    config: ExperimentConfig | None = None,
) -> Path:
    root = experiment_output_root(config)
    return root / "runs" / method_id


def run_dir(
    method_id: str,
    task_id: str,
    seed: int,
    attempt: int | None = None,
    config: ExperimentConfig | None = None,
) -> Path:
    root = experiment_output_root(config)
    attempt_part = f"attempt_{attempt}" if attempt is not None else "latest"
    return root / "runs" / method_id / task_id / f"seed_{seed}" / attempt_part


def task_gold_dir(
    task_id: str,
    config: ExperimentConfig | None = None,
) -> Path:
    root = experiment_output_root(config)
    return root / "golden" / task_id


def report_path(
    report_name: str,
    config: ExperimentConfig | None = None,
) -> Path:
    root = experiment_output_root(config)
    return root / "reports" / report_name


def ensure_parent(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
