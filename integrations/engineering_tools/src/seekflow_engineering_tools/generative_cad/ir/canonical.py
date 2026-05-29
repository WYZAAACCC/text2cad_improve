"""CanonicalGcadDocument — validated, resolved, hash-carrying IR."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.ir.raw import RawConstraints, RawSafety
from seekflow_engineering_tools.generative_cad.ir.values import ValueType


class CanonicalSelectedDialect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dialect: str
    version: str
    contract_hash: str


class CanonicalComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    owner_dialect: str
    kind_hint: str | None = None
    root_node: str
    output_aliases: dict[str, str] = Field(default_factory=dict)


class CanonicalValueRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producer_node: str | None = None
    producer_component: str | None = None
    output: str
    resolved_type: ValueType


class CanonicalValueDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: ValueType
    value_id: str


class CanonicalNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    component: str
    dialect: str
    op: str
    op_version: str
    phase: str

    inputs: list[CanonicalValueRef] = Field(default_factory=list)
    outputs: list[CanonicalValueDecl] = Field(default_factory=list)

    params: dict[str, Any] = Field(default_factory=dict)
    typed_params: Any = None

    required: bool = True
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"

    operation_effects: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)


class CanonicalGcadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["g_cad_core_v0.2"] = "g_cad_core_v0.2"
    canonical_version: Literal["canonical_gcad_v0.2"] = "canonical_gcad_v0.2"

    document_id: str
    part_name: str
    units: Literal["mm"] = "mm"
    trust_level: Literal["concept_geometry", "reference_geometry"] = "reference_geometry"

    selected_dialects: list[CanonicalSelectedDialect]
    components: list[CanonicalComponent]
    nodes: list[CanonicalNode]

    constraints: RawConstraints
    safety: RawSafety

    canonical_graph_hash: str
    raw_graph_hash: str | None = None
