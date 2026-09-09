from collections import Counter

from _main_experiment.config import ExperimentConfig
from _main_experiment.schemas import DifficultyLevel, TaskType
from _main_experiment.tasks.task_builder import build_task_specs


def test_build_task_specs_has_40_tasks(tmp_path):
    config = ExperimentConfig(output_root=tmp_path / "output")
    tasks = build_task_specs(config)
    assert len(tasks) == 40
    assert len({t.task_id for t in tasks}) == 40


def test_build_task_specs_distribution(tmp_path):
    config = ExperimentConfig(output_root=tmp_path / "output")
    tasks = build_task_specs(config)
    levels = Counter(t.level for t in tasks)
    assert levels == {
        DifficultyLevel.L1: 8,
        DifficultyLevel.L2: 10,
        DifficultyLevel.L3: 12,
        DifficultyLevel.L4: 10,
    }
    types = Counter(t.task_type for t in tasks)
    assert types[TaskType.GENERATION] == 32
    assert types[TaskType.EDIT] == 8


def test_build_task_specs_gold_paths(tmp_path):
    config = ExperimentConfig(output_root=tmp_path / "output")
    tasks = build_task_specs(config)
    assert tasks[0].gold.step_path.parts[-2:] == ("T01", "output.step")
