"""Authoring schemas — staged generation for reduced LLM hallucination.

Instead of one giant RawGcadDocument, the LLM outputs three smaller objects:
  1. RoutePlan — choose route and dialects (no nodes, no params).
  2. FeatureSequenceDraft — list operations in order (no params).
  3. NodeParamsDraft — fill params for ONE operation at a time.

The system assembles these into RawGcadDocument.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── RoutePlan ────────────────────────────────────────────────────────────────


class RouteDecision(str, Enum):
    PRIMITIVE = "primitive"
    GENERATIVE_CAD_IR = "generative_cad_ir"
    UNSUPPORTED = "unsupported"
    NEEDS_CLARIFICATION = "needs_clarification"


class SelectedDialectDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialect: str
    version: str
    reason: str


class RoutePlan(BaseModel):
    """Level-1 output: route decision + dialect selection. No nodes or params."""

    model_config = ConfigDict(extra="forbid")

    route_decision: RouteDecision
    part_intent: dict[str, str] = Field(default_factory=dict)
    selected_dialects: list[SelectedDialectDraft] = Field(default_factory=list)
    selected_domain_skills: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_route_invariants(self) -> "RoutePlan":
        if self.route_decision == RouteDecision.GENERATIVE_CAD_IR:
            if not self.selected_dialects:
                raise ValueError(
                    "route_decision=generative_cad_ir requires selected_dialects non-empty"
                )
        if self.route_decision == RouteDecision.UNSUPPORTED:
            if not self.unsupported_capabilities:
                raise ValueError(
                    "route_decision=unsupported requires unsupported_capabilities non-empty"
                )
        if self.route_decision == RouteDecision.NEEDS_CLARIFICATION:
            if not self.clarification_questions:
                raise ValueError(
                    "route_decision=needs_clarification requires clarification_questions non-empty"
                )
        return self


# ── FeatureSequenceDraft ─────────────────────────────────────────────────────


class ComponentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    owner_dialect: str
    kind_hint: str = ""
    description: str = ""


class NodePlanDraft(BaseModel):
    """One node in the feature sequence — op + wiring, NO params."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    component_id: str
    dialect: str
    op: str
    op_version: str
    phase: str
    purpose: str = ""
    expected_input_source: str | None = None
    expected_output_name: str = "body"
    required: bool = True
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"


class FeatureSequenceDraft(BaseModel):
    """Level-2 output: ordered operation sequence. NO params, safety, or constraints."""

    model_config = ConfigDict(extra="forbid")

    components: list[ComponentDraft] = Field(default_factory=list)
    node_sequence: list[NodePlanDraft] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unsupported_details: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_has_nodes(self) -> "FeatureSequenceDraft":
        if not self.node_sequence:
            raise ValueError("node_sequence must be non-empty")
        # Verify every node references an existing component
        comp_ids = {c.component_id for c in self.components}
        for node in self.node_sequence:
            if node.component_id not in comp_ids:
                raise ValueError(
                    f"Node {node.node_id!r} references unknown component "
                    f"{node.component_id!r}"
                )
        return self


# ── NodeParamsDraft ──────────────────────────────────────────────────────────


class NodeParamsDraft(BaseModel):
    """Params for ONE operation. Validated against OperationSpec.params_model."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    dialect: str
    op: str
    op_version: str
    params: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


# ── RawAssemblyResult ────────────────────────────────────────────────────────


class RawAssemblyResult(BaseModel):
    """Result of system-side RawGcadDocument assembly."""

    model_config = ConfigDict(extra="forbid")

    raw_document: dict[str, Any]
    source_route_plan_hash: str
    source_feature_sequence_hash: str
    source_node_params_hashes: dict[str, str]
    system_filled_fields: list[str]
