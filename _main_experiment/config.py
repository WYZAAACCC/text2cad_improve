"""Experiment configuration models.

The experiment module owns its own configuration objects so the main
application and the existing engineering-tools package do not need to change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmConfig(StrictModel):
    provider: str = "openai_compat"
    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com/beta"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float | None = 0.3
    top_p: float | None = 0.9
    seed: int | None = None
    max_tokens: int | None = 8192
    tool_choice: str = "required"
    thinking: dict | None = None
    timeout_s: float = 900.0
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float | None) -> float | None:
        if value is not None and not (0 <= value <= 2):
            raise ValueError("temperature must be between 0 and 2")
        return value

    @field_validator("top_p")
    @classmethod
    def validate_top_p(cls, value: float | None) -> float | None:
        if value is not None and not (0 < value <= 1):
            raise ValueError("top_p must be between 0 and 1")
        return value

    @field_validator("seed", "max_tokens", "timeout_s")
    @classmethod
    def validate_positive_or_none(
        cls, value: int | float | None
    ) -> int | float | None:
        if value is not None and value <= 0:
            raise ValueError("value must be greater than 0")
        return value


class RunnerConfig(StrictModel):
    max_repair_attempts: int = 3
    single_cad_timeout_s: float = 900.0
    task_timeout_s: float = 3600.0
    workers: int = 1
    resume: bool = True

    @field_validator("max_repair_attempts", "workers")
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be non-negative")
        return value

    @field_validator("single_cad_timeout_s", "task_timeout_s")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout must be greater than 0")
        return value


class EvalConfig(StrictModel):
    length_tolerance_mm: float = 0.05
    angle_tolerance_deg: float = 0.1
    hausdorff_sample_count: int = 2000
    step_volume_relative_tolerance: float = 0.001
    step_dimension_tolerance_mm: float = 0.05

    @field_validator(
        "length_tolerance_mm",
        "angle_tolerance_deg",
        "hausdorff_sample_count",
        "step_volume_relative_tolerance",
        "step_dimension_tolerance_mm",
    )
    @classmethod
    def validate_positive(cls, value: float | int) -> float | int:
        if value <= 0:
            raise ValueError("value must be greater than 0")
        return value


class ExperimentConfig(StrictModel):
    root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent)
    output_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "output")
    llm: LlmConfig = Field(default_factory=LlmConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)

    def resolved_output_root(self) -> Path:
        root = self.output_root
        if not root.is_absolute():
            root = self.root / root
        return root.resolve()


def default_experiment_config() -> ExperimentConfig:
    """Return the production experiment configuration."""
    return ExperimentConfig()
