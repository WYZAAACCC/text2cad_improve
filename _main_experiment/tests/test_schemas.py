from pathlib import Path

import pytest
from pydantic import ValidationError

from _main_experiment.config import ExperimentConfig, LlmConfig, RunnerConfig
from _main_experiment.schemas import (
    AcceptanceCriteria,
    DifficultyLevel,
    GoldReference,
    KeyDimension,
    RunSpec,
    TaskSpec,
    TaskType,
)


def test_default_experiment_config_is_strict():
    config = ExperimentConfig()
    assert config.llm.model == "deepseek-v4-pro"
    assert config.runner.max_repair_attempts == 3
    assert config.eval.length_tolerance_mm == 0.05
    assert config.resolved_output_root().name == "output"


def test_llm_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        LlmConfig(model="m", unknown=True)


def test_task_spec_accepts_minimal_gold_reference(tmp_path):
    gold = GoldReference(
        fdg_path=tmp_path / "fdg.json",
        canonical_ir_path=tmp_path / "canonical_ir.json",
        step_path=tmp_path / "output.step",
        key_dimensions=[KeyDimension(name="outer_diameter_mm", expected_mm=500.0)],
        acceptance=AcceptanceCriteria(),
    )
    task = TaskSpec(
        task_id="T01",
        level=DifficultyLevel.L1,
        task_type=TaskType.GENERATION,
        prompt="生成一个涡轮盘参考模型",
        normalized_params={"od_mm": 500},
        gold=gold,
    )
    assert task.task_id == "T01"
    assert task.gold.step_path.name == "output.step"


def test_run_spec_rejects_negative_seed():
    with pytest.raises(ValidationError):
        RunSpec(run_id="r1", method_id="m1", task_id="t1", seed=-1)


def test_runner_config_validates_repair_attempts():
    with pytest.raises(ValidationError):
        RunnerConfig(max_repair_attempts=-1)
