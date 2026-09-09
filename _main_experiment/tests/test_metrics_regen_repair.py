from _main_experiment.metrics.regen_repair import failure_category_metric, repair_metric
from _main_experiment.schemas import RunResult


def test_repair_metric_records_rounds():
    result = RunResult(
        run_id="r",
        method_id="m",
        task_id="t",
        seed=1,
        ok=True,
        repair_rounds=2,
    )
    metric = repair_metric(result)
    assert metric.value == 2
    assert metric.passed is True


def test_failure_category_maps_stage():
    result = RunResult(
        run_id="r",
        method_id="m",
        task_id="t",
        seed=1,
        ok=False,
        error_stage="mcp_gate",
    )
    metric = failure_category_metric(result)
    assert metric.value == "mcp_gate"
