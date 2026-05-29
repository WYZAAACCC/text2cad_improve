"""Legacy v0.1 IR models — kept for backward compatibility with existing tests.

These models are re-exported from ir/__init__.py so that old imports like
`from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec` still work.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LengthUnit = Literal["mm"]
TrustLevel = Literal["concept_geometry", "reference_geometry"]
GenerationRoute = Literal["llm_skill_base"]


class SelectedBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_id: str
    base_version: str


class SelectedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str
    skill_version: str


class FeatureGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    base_id: str
    op: str
    phase: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    required: bool = True
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"

    @model_validator(mode="after")
    def validate_id(self):
        if not self.id.strip():
            raise ValueError("node id must be non-empty")
        if not self.base_id.strip():
            raise ValueError("base_id must be non-empty")
        if not self.op.strip():
            raise ValueError("op must be non-empty")
        if not self.phase.strip():
            raise ValueError("phase must be non-empty")
        if self.required and self.degradation_policy != "fail":
            raise ValueError("required nodes must use degradation_policy='fail'")
        return self


class FeatureGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[FeatureGraphNode]

    @model_validator(mode="after")
    def validate_unique_ids(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("feature graph node ids must be unique")
        return self


class SystemValidationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_step_file: bool = True
    require_metadata_sidecar: bool = True
    require_closed_solid: bool = True
    expected_body_count: int = Field(default=1, ge=1)
    expected_bbox_mm: list[float] | None = None
    bbox_tolerance_mm: float = Field(default=1.0, gt=0)
    max_runtime_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def validate_bbox(self):
        if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
            raise ValueError("expected_bbox_mm must be [x, y, z]")
        if not self.require_step_file:
            raise ValueError("require_step_file cannot be false")
        if not self.require_metadata_sidecar:
            raise ValueError("require_metadata_sidecar cannot be false")
        if not self.require_closed_solid:
            raise ValueError("require_closed_solid cannot be false")
        return self


class LLMValidationHints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_outer_dia_mm: float | None = Field(default=None, gt=0)
    expected_length_mm: float | None = Field(default=None, gt=0)
    expected_axial_width_mm: float | None = Field(default=None, gt=0)
    expected_feature_notes: list[str] = Field(default_factory=list)


class SafetyFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")
    non_flight_reference_only: bool = True
    not_airworthy: bool = True
    not_certified: bool = True
    not_for_manufacturing: bool = True
    not_for_installation: bool = True
    no_structural_validation: bool = True
    no_life_prediction: bool = True

    @model_validator(mode="after")
    def enforce_true(self):
        for name, value in self.model_dump().items():
            if value is not True:
                raise ValueError(f"safety flag {name} must be true")
        return self


class GenerativeCADSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ir_version: Literal["g_cad_ir_v0.1"] = "g_cad_ir_v0.1"
    generation_route: GenerationRoute = "llm_skill_base"
    part_name: str
    units: LengthUnit = "mm"
    trust_level: TrustLevel = "reference_geometry"
    selected_bases: list[SelectedBase]
    selected_skills: list[SelectedSkill] = Field(default_factory=list)
    feature_graph: FeatureGraph
    system_validation_contract: SystemValidationContract = Field(default_factory=SystemValidationContract)
    llm_validation_hints: LLMValidationHints = Field(default_factory=LLMValidationHints)
    safety: SafetyFlags = Field(default_factory=SafetyFlags)

    @model_validator(mode="after")
    def validate_basic(self):
        if not self.part_name.strip():
            raise ValueError("part_name must be non-empty")
        if not self.selected_bases:
            raise ValueError("selected_bases must not be empty")
        selected_ids = {b.base_id for b in self.selected_bases}
        for node in self.feature_graph.nodes:
            if node.base_id not in selected_ids:
                raise ValueError(
                    f"node {node.id!r} uses base {node.base_id!r}, "
                    "not present in selected_bases"
                )
        if self.trust_level not in {"concept_geometry", "reference_geometry"}:
            raise ValueError("generative CAD trust_level cannot exceed reference_geometry")
        return self
