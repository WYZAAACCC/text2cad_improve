"""Core experiment data models shared by all later work packages."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import LlmConfig, RunnerConfig


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskType(str, Enum):
    GENERATION = "generation"
    EDIT = "edit"


class DifficultyLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class KeyDimension(StrictModel):
    name: str
    expected_mm: float
    tolerance_mm: float = 0.05
    unit: str = "mm"


class SlotReference(StrictModel):
    teeth_count: int
    slot_depth_mm: float
    throat_half_width_mm: float
    reference_profile_path: Path | None = None


class AcceptanceCriteria(StrictModel):
    require_step_file: bool = True
    require_metadata_sidecar: bool = True
    require_closed_solid: bool = True
    required_feature_counts: dict[str, int] = Field(default_factory=dict)


class GoldReference(StrictModel):
    fdg_path: Path
    canonical_ir_path: Path
    step_path: Path
    brep_path: Path | None = None
    key_dimensions: list[KeyDimension] = Field(default_factory=list)
    slot_reference: SlotReference | None = None
    acceptance: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)


class TaskSpec(StrictModel):
    task_id: str
    level: DifficultyLevel
    task_type: TaskType
    family_id: str | None = None
    prompt: str
    normalized_params: dict[str, Any] = Field(default_factory=dict)
    gold: GoldReference
    description: str = ""


class MethodSpec(StrictModel):
    method_id: str
    display_name: str
    llm: LlmConfig
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    flags: dict[str, bool] = Field(default_factory=dict)


class RunSpec(StrictModel):
    run_id: str
    method_id: str
    task_id: str
    seed: int
    attempt: int = 0

    @field_validator("seed", "attempt")
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be non-negative")
        return value


class MetricResult(StrictModel):
    metric_id: str
    name: str
    value: Any
    unit: str | None = None
    level: str | None = None
    passed: bool | None = None
    notes: str | None = None


class RunResult(StrictModel):
    run_id: str
    record_id: str = ""
    collected_at: str | None = None
    schema_version: str = "run_v1"
    method_id: str
    task_id: str
    seed: int
    status: RunStatus = RunStatus.PENDING
    ok: bool = False
    attempts_used: int = 0
    repair_rounds: int = 0
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    usage: dict[str, int] | None = None
    metrics: list[MetricResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
