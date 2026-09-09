import pytest

from _main_experiment.aggregate import aggregate_by_method, aggregate_by_level
from _main_experiment.schemas import RunResult, RunStatus
from _main_experiment.tasks.task_builder import build_task_specs
from _main_experiment.config import ExperimentConfig


def _result(method, task, ok, repair_rounds=0, attempts=1, seed=1):
    return RunResult(
        run_id=f"{method}_{task}_{seed}",
        method_id=method,
        task_id=task,
        seed=seed,
        status=RunStatus.COMPLETED if ok else RunStatus.FAILED,
        ok=ok,
        repair_rounds=repair_rounds,
        attempts_used=attempts,
    )


def test_aggregate_by_method_counts_pass_and_final():
    results = [
        _result("m1", "T01", True, repair_rounds=0),
        _result("m1", "T02", True, repair_rounds=1),
        _result("m1", "T03", False),
    ]
    rows = aggregate_by_method(results)
    assert len(rows) == 1
    assert rows[0]["final_success"] == pytest.approx(2 / 3, abs=1e-3)
    assert rows[0]["engineering_pass1"] == pytest.approx(1 / 3, abs=1e-3)


def test_aggregate_by_level_uses_task_levels():
    tasks = build_task_specs(ExperimentConfig())
    results = [_result("m1", tasks[0].task_id, True)]
    rows = aggregate_by_level(results, tasks)
    assert any(row["level"] == "L1" and row["runs"] == 1 for row in rows)
