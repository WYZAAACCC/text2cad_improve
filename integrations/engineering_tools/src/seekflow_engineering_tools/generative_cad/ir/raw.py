"""RawGcadDocument — the only format LLM may output. extra=forbid everywhere."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LengthUnit = Literal["mm"]
TrustLevel = Literal["concept_geometry", "reference_geometry"]
DegradationPolicy = Literal["fail", "may_skip_with_warning"]


class RawSelectedDialect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dialect: str
    version: str


class RawComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    owner_dialect: str
    kind_hint: str | None = None
    root_node: str | None = None


class RawValueRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: str | None = None
    component: str | None = None
    output: str

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.node) == bool(self.component):
            raise ValueError("ValueRef must specify exactly one of node or component")
        return self


class RawValueDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str


class RawNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    component: str
    dialect: str
    op: str
    op_version: str | None = None
    phase: str
    inputs: list[RawValueRef] = Field(default_factory=list)
    outputs: list[RawValueDecl] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    degradation_policy: DegradationPolicy = "fail"
    autofix_hints: list[dict[str, Any]] | None = Field(default=None)

    @model_validator(mode="after")
    def validate_required_policy(self):
        if self.required and self.degradation_policy != "fail":
            raise ValueError("required nodes must use degradation_policy='fail'")
        return self


class RawConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_step_file: bool
    require_metadata_sidecar: bool
    require_closed_solid: bool
    expected_body_count: int = Field(ge=1)
    expected_bbox_mm: list[float] | None = None
    bbox_tolerance_mm: float = Field(default=1.0, gt=0)
    max_runtime_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def fail_closed_flags(self):
        if self.require_step_file is not True:
            raise ValueError("constraints.require_step_file must be explicitly true")
        if self.require_metadata_sidecar is not True:
            raise ValueError("constraints.require_metadata_sidecar must be explicitly true")
        if self.require_closed_solid is not True:
            raise ValueError("constraints.require_closed_solid must be explicitly true")
        if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
            raise ValueError("constraints.expected_bbox_mm must be [x, y, z]")
        return self


class RawSafety(BaseModel):
    model_config = ConfigDict(extra="forbid")

    non_flight_reference_only: bool
    not_airworthy: bool
    not_certified: bool
    not_for_manufacturing: bool
    not_for_installation: bool
    no_structural_validation: bool
    no_life_prediction: bool

    @model_validator(mode="after")
    def all_true(self):
        for key, value in self.model_dump().items():
            if value is not True:
                raise ValueError(f"safety.{key} must be explicitly true")
        return self


class RawGcadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["g_cad_core_v0.2"]
    document_id: str
    part_name: str
    units: LengthUnit
    trust_level: TrustLevel

    selected_dialects: list[RawSelectedDialect]
    components: list[RawComponent]
    nodes: list[RawNode]

    constraints: RawConstraints
    safety: RawSafety

    llm_validation_hints: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_basic(self):
        if not self.document_id.strip():
            raise ValueError("document_id must be non-empty")
        if not self.part_name.strip():
            raise ValueError("part_name must be non-empty")
        if not self.selected_dialects:
            raise ValueError("selected_dialects must not be empty")
        if not self.components:
            raise ValueError("components must not be empty")
        if not self.nodes:
            raise ValueError("nodes must not be empty")
        return self
