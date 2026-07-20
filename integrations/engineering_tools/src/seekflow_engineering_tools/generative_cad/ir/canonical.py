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


class CanonicalPersistentTopoRef(BaseModel):
    """PR 9: Resolved persistent topology reference in canonical IR.

    The canonicalizer resolves RawPersistentTopoRef.semantic_query to
    concrete persistent_ids. If pre-build resolution is impossible,
    uses DeferredPersistentTopoRef (symbolic, resolved during runtime).
    """

    model_config = ConfigDict(extra="forbid")

    persistent_ids: list[str] = Field(
        description="Resolved persistent topology IDs (gct2_<hash>)",
    )
    entity_type: Literal["face", "edge", "vertex"] = Field(
        description="Expected entity type",
    )
    cardinality: Literal[
        "exactly_one", "zero_or_one", "one_or_more", "zero_or_more",
    ] = "exactly_one"
    resolution_policy: Literal[
        "exact_only",
        "allow_deterministic_semantic",
        "allow_set_expansion",
        "allow_fingerprint_unique",
    ] = "exact_only"
    producer_contract_hash: str = Field(
        default="",
        description="Hash of the producer's TopologyContract at build time",
    )


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
    typed_params: dict[str, Any] = Field(default_factory=dict)

    required: bool = True
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"

    operation_effects: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)

    autofix_hints: list[dict[str, Any]] | None = Field(default=None)


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

    # V3 §2.1: design identity carried through from RawGcadDocument
    design_identity: dict | None = None
