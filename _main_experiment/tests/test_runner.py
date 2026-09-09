from _main_experiment.config import ExperimentConfig, LlmConfig
from _main_experiment.paths import run_dir
from _main_experiment.runner import run_benchmark
from _main_experiment.schemas import MethodSpec, RunResult, RunStatus, TaskSpec
from _main_experiment.tasks.task_builder import build_task_specs
from _main_experiment.utils import atomic_write_json


def _method():
    return MethodSpec(
        method_id="m1",
        display_name="M1",
        llm=LlmConfig(model="mock"),
    )


def _task(task_id="T01"):
    task = build_task_specs(ExperimentConfig())[0]
    return task.model_copy(update={"task_id": task_id})


def test_run_benchmark_loops_over_tasks_and_seeds(tmp_path, monkeypatch):
    config = ExperimentConfig(output_root=tmp_path / "output")
    calls = []

    def fake_run(task_spec, method_spec, seed, config, client=None):
        calls.append((method_spec.method_id, task_spec.task_id, seed))
        return RunResult(
            run_id=f"{method_spec.method_id}__{task_spec.task_id}__{seed}",
            method_id=method_spec.method_id,
            task_id=task_spec.task_id,
            seed=seed,
            status=RunStatus.COMPLETED,
            ok=True,
        )

    monkeypatch.setattr("_main_experiment.runner.run_experiment_task", fake_run)
    results = run_benchmark(
        [_task("T01"), _task("T02")],
        [_method()],
        [1, 2],
        config,
    )
    assert len(results) == 4
    assert ("m1", "T01", 1) in calls
    assert ("m1", "T02", 2) in calls


def test_run_benchmark_resumes_completed_runs(tmp_path, monkeypatch):
    config = ExperimentConfig(output_root=tmp_path / "output")
    completed_path = run_dir("m1", "T01", 1, config=config)
    completed_path.mkdir(parents=True, exist_ok=True)
    atomic_write_json(completed_path / "run.json", {
        "run_id": "x",
        "status": "completed",
        "ok": True,
    })
    calls = []

    def fake_run(task_spec, method_spec, seed, config, client=None):
        calls.append(seed)
        return RunResult(
            run_id=f"r_{seed}",
            method_id="m1",
            task_id=task_spec.task_id,
            seed=seed,
            status=RunStatus.COMPLETED,
            ok=True,
        )

    monkeypatch.setattr("_main_experiment.runner.run_experiment_task", fake_run)
    results = run_benchmark([_task()], [_method()], [1, 2], config)
    assert len(results) == 1
    assert calls == [2]
