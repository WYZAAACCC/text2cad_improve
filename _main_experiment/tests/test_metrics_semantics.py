import json
import math

from _main_experiment.config import ExperimentConfig
from _main_experiment.metrics.semantics import (
    SemanticMetricsComputer,
    fdg_f1,
    parameter_accuracy,
)
from _main_experiment.metrics.geometry import hausdorff_distance
from _main_experiment.schemas import RunResult, TaskSpec


def _ir(nodes):
    return {
        "schema_version": "g_cad_core_v0.2",
        "components": [],
        "nodes": nodes,
        "constraints": {},
        "safety": {},
    }


def test_parameter_accuracy():
    metric = parameter_accuracy({"od_mm": 500}, {"od_mm": 500.01}, tolerance=0.05)
    assert metric.value == 1.0
    assert metric.passed is True


def test_fdg_f1():
    ref = [{"id": "a", "component": "c", "dialect": "d", "op": "o", "phase": "p"}]
    act = [{"id": "a", "component": "c", "dialect": "d", "op": "o", "phase": "p"}]
    metric = fdg_f1(ref, act, kind="node")
    assert metric.value == 1.0


def test_hausdorff_distance():
    a = [(0.0, 0.0), (1.0, 0.0)]
    b = [(0.0, 0.0), (1.1, 0.0)]
    assert math.isclose(hausdorff_distance(a, b), 0.1, abs_tol=1e-9)


def test_semantic_computer_returns_metrics(tmp_path, monkeypatch):
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    gold_ir = _ir([{
        "id": "a", "component": "c", "dialect": "d", "op": "o", "phase": "p",
        "inputs": [], "outputs": [], "params": {"od_mm": 500},
    }])
    (gold_dir / "canonical_ir.json").write_text(json.dumps(gold_ir), encoding="utf-8")
    run_path = tmp_path / "run"
    run_path.mkdir()
    (run_path / "raw_fixed.json").write_text(json.dumps(gold_ir), encoding="utf-8")
    (run_path / "validation_initial.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    task = TaskSpec(
        task_id="T01",
        level="L1",
        task_type="generation",
        prompt="test",
        normalized_params={"od_mm": 500},
        gold={
            "fdg_path": gold_dir / "fdg.json",
            "canonical_ir_path": gold_dir / "canonical_ir.json",
            "step_path": gold_dir / "output.step",
        },
    )
    metrics = SemanticMetricsComputer().compute(
        run_dir=run_path,
        task_spec=task,
        run_result=RunResult(run_id="r", method_id="m", task_id="T01", seed=1),
        config=ExperimentConfig(),
    )
    assert len(metrics) == 4
    assert metrics[0].metric_id == "parameter_accuracy"
