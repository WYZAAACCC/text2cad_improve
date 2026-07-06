"""Spatial Intent Resolution — Pydantic v2 Data Models.

All models use extra="forbid". Designed for DeepSeek strict tool calling.

Key type aliases are defined as standalone Literal types (not via model_fields)
to avoid implicit Pydantic v2 API dependencies.

Architecture:
  MechanicalObjectGraphDraft (LLM output)
    → SpatialConstraintGraph (symbolic constraints, system-built)
      → PlacementConstraint (per-constraint symbolic equation)
        → SymbolicDimensionRef (references component.axis.edge)
  Phase C:
    → ConstraintResolver uses actual bbox measurements
    → NumericPlacement (concrete coordinates for composition handler)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone type aliases (avoid Pydantic model_fields implicit references)
# ═══════════════════════════════════════════════════════════════════════════════

SpatialModeType = Literal[
    "guided", "auto_conservative", "auto_mechanical",
    "auto_complex_verified", "precision",
]

AxisNameType = Literal["X", "Y", "Z"]

SourceKindType = Literal[
    "user_explicit", "user_selected_option", "llm_inferred",
    "archetype_default", "system_default", "solver_derived",
]

SpatialRelationType = Literal[
    "above", "below", "left_of", "right_of", "front_of", "behind",
    "between", "coaxial", "concentric", "parallel", "perpendicular",
    "symmetric_pair", "face_contact", "flush", "offset", "clearance",
    "centered_on", "inside", "surrounds", "supports", "attached_to",
]

UnknownKindType = Literal[
    "component_count", "relative_placement", "axis_direction",
    "face_selection", "contact_relation", "spacing", "symmetry",
    "assembly_vs_fused", "feature_location", "port_direction",
    "numeric_value",  # e.g. bolt hole diameter, wall thickness, fillet radius
    "material_specification",  # e.g. carbon steel vs stainless, PN16 vs PN40
]

OriginSemanticsType = Literal[
    "center", "center_bottom", "center_top", "axis_front",
    "axis_midpoint", "mounting_face_center", "unknown",
]

ClarificationMode = Literal["option", "custom", "auto"]

AutoLevelType = Literal[
    "auto_conservative", "auto_mechanical", "auto_complex_verified",
]

ValidationStatusType = Literal["not_checked", "pass", "fail", "warning"]

SpatialFinalStatus = Literal["VERIFIED", "ASSUMPTION_BASED", "NEEDS_CLARIFICATION"]


# ═══════════════════════════════════════════════════════════════════════════════
# Confidence
# ═══════════════════════════════════════════════════════════════════════════════

class Confidence(BaseModel):
    """Confidence annotation for any spatial fact.

    0.0 = pure guess, 1.0 = user-explicit or solver-verified.
    """
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0.0, le=1.0)
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# KnownDimension — structured replacement for free-form dict
# ═══════════════════════════════════════════════════════════════════════════════

class KnownDimension(BaseModel):
    """A single user-stated dimension with axis binding.

    Structured replacement for the original document's dict[str, float].
    The axis field tells the solver which bbox axis this dimension corresponds to.
    """
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="e.g. 'outer_diameter', 'height', 'length', 'width', 'thickness'")
    value_mm: float = Field(gt=0)
    axis: AxisNameType | None = Field(
        default=None,
        description="Primary axis: Z=axial height, X/Y=lateral dimensions"
    )
    is_exact: bool = Field(
        default=True,
        description="True=user explicitly stated, False=approximate ('about 100mm')"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ComponentRole — LLM-extracted component semantics
# ═══════════════════════════════════════════════════════════════════════════════

class ComponentRole(BaseModel):
    """Semantic description of a mechanical component.

    component_id MUST match what will appear in FeatureSequenceDraft.
    """
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(description="Must match FeatureSequence component_id")
    display_name: str = ""
    role: str = Field(description="Mechanical role: 'top_plate', 'pillar', 'hub', 'spider', 'base'")
    kind_hint: str = Field(default="", description="Geometry type hint: 'plate', 'cylinder', 'ring', 'spring'")
    primary_dialect_hint: str | None = Field(
        default=None,
        description="Expected dialect: 'axisymmetric', 'sketch_extrude', 'loft_sweep'"
    )
    known_dimensions: list[KnownDimension] = Field(default_factory=list)
    source_text: str = Field(default="", description="Original user prompt text describing this component")
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))


# ═══════════════════════════════════════════════════════════════════════════════
# LocalFrameDraft — per-component coordinate frame assumption
# ═══════════════════════════════════════════════════════════════════════════════

class LocalFrameDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    origin_semantics: OriginSemanticsType = "unknown"
    x_axis_semantics: str = Field(default="global_X")
    y_axis_semantics: str = Field(default="global_Y")
    z_axis_semantics: str = Field(default="global_Z")
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialRelationDraft — LLM-inferred relation (imprecise, to be solved)
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialRelationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_id: str
    type: SpatialRelationType
    entities: list[str] = Field(description="component_ids involved in this relation")
    value_mm: float | None = Field(default=None, description="offset/clearance value if known")
    direction: str | None = Field(default=None, description="'+Z', '-X' etc.")
    source: SourceKindType = "llm_inferred"
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))
    rationale: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialUnknown — LLM-identified uncertainty
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialUnknown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unknown_id: str
    kind: UnknownKindType
    entities: list[str]
    question_hint: str = Field(description="Draft question for the user (LLM must always provide this)")
    impact: float = Field(ge=0.0, le=1.0, description="How badly the CAD model changes if wrong")
    uncertainty: float = Field(ge=0.0, le=1.0, description="How unclear the prompt is")
    answer_cost: float = Field(ge=0.0, le=1.0, description="How hard for user to answer")
    reason: str = ""
    # LLM-generated concrete options (2-4 items each)
    suggested_option_labels: list[str] = Field(
        default_factory=list,
        description="Concrete option labels with specific values, e.g. ['DN100 φ114mm（推荐）', 'DN150 φ168mm']"
    )
    suggested_option_descriptions: list[str] = Field(
        default_factory=list,
        description="Descriptions matching each option, e.g. ['按GB/T 9119，DN250法兰配DN100通孔']"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MechanicalObjectGraphDraft — Level-1 spatial IR (LLM output)
# ═══════════════════════════════════════════════════════════════════════════════

class MechanicalObjectGraphDraft(BaseModel):
    """LLM-extracted spatial intent.

    This is the ONLY spatial output the LLM produces.
    All coordinate computation happens in the solver, not the LLM.
    """
    model_config = ConfigDict(extra="forbid")
    mode: SpatialModeType = "guided"
    global_frame_assumption: str = "X=left-right, Y=front-back, Z=bottom-top, units=mm"
    components: list[ComponentRole] = Field(default_factory=list, min_length=1)
    local_frames: list[LocalFrameDraft] = Field(default_factory=list)
    candidate_relations: list[SpatialRelationDraft] = Field(default_factory=list)
    unknowns: list[SpatialUnknown] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_invariants(self):
        # component_id uniqueness
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component_id values must be unique")
        # local_frames must reference existing component_ids
        frame_ids = {f.component_id for f in self.local_frames}
        unknown_frames = frame_ids - set(ids)
        if unknown_frames:
            raise ValueError(f"local_frames reference unknown component_ids: {unknown_frames}")
        # relations entities must reference existing component_ids
        for rel in self.candidate_relations:
            unknown_entities = set(rel.entities) - set(ids)
            if unknown_entities:
                raise ValueError(
                    f"relation {rel.relation_id} references unknown entities: {unknown_entities}"
                )
        # unknowns entities same check
        for unk in self.unknowns:
            unknown_entities = set(unk.entities) - set(ids)
            if unknown_entities:
                raise ValueError(
                    f"unknown {unk.unknown_id} references unknown entities: {unknown_entities}"
                )
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# SymbolicDimensionRef — core abstraction for constraint-deferred solving
# ═══════════════════════════════════════════════════════════════════════════════

class SymbolicDimensionRef(BaseModel):
    """Symbolic reference to a component's extent on a given axis.

    This is THE key innovation over the original document.
    Instead of outputting numeric PlacementTransform (which needs dimensions
    that don't exist yet), the solver outputs SymbolicDimensionRef bindings.
    Phase C ConstraintResolver substitutes actual bbox measurements.

    Examples:
      SymbolicDimensionRef(component_id="top_plate", axis="Z", edge="extent")
        → top_plate's Z height (bbox.zlen)
      SymbolicDimensionRef(component_id="bottom_plate", axis="Z", edge="max")
        → bottom_plate's Z top face (bbox.zmax after placement)
    """
    model_config = ConfigDict(extra="forbid")
    component_id: str
    axis: AxisNameType
    edge: Literal["min", "max", "extent"] = "extent"


# ═══════════════════════════════════════════════════════════════════════════════
# PlacementConstraint — symbolic constraint (replaces absolute PlacementTransform)
# ═══════════════════════════════════════════════════════════════════════════════

class PlacementConstraint(BaseModel):
    """A single symbolic placement constraint.

    Constraint types:
    - "stack": lower.zmax + offset = upper.zmin (Z-axis stacking)
    - "align_axis": A.{axis} = B.{axis} (coaxial alignment)
    - "symmetric": A.x = -d/2, B.x = +d/2 (symmetric pair)
    - "contact": distance(A.face, B.face) <= tolerance
    - "identity": explicit (0,0,0) placement
    """
    model_config = ConfigDict(extra="forbid")
    constraint_id: str
    type: Literal["stack", "align_axis", "symmetric", "contact", "identity"]
    entities: list[str] = Field(min_length=1)
    bindings: dict[str, SymbolicDimensionRef] = Field(
        default_factory=dict,
        description="key=placeholder name, value=symbolic dimension reference"
    )
    offset_mm: float = 0.0
    spacing_mm: float | None = None  # for symmetric_pair
    axis: AxisNameType | None = None
    tolerance_mm: float = 0.5
    source: SourceKindType = "solver_derived"
    required: bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialConstraintGraph — Phase A output (symbolic constraints only)
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialConstraintGraph(BaseModel):
    """Symbolic constraint graph produced by Phase A.

    Carries NO numeric placements. All constraints use SymbolicDimensionRef.
    Numeric resolution happens in Phase C (ConstraintResolver).
    """
    model_config = ConfigDict(extra="forbid")
    components: list[ComponentRole]
    local_frames: list[LocalFrameDraft]
    constraints: list[PlacementConstraint] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    solved_assembly_bbox_mm: tuple[float, float, float] | None = Field(
        default=None,
        description="Solver-derived assembly bbox estimate (reference only, NOT RawConstraints.expected_bbox_mm)"
    )
    expected_body_count: int | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# NumericPlacement — Phase C output (concrete coordinates)
# ═══════════════════════════════════════════════════════════════════════════════

class NumericPlacement(BaseModel):
    """Concrete placement computed by ConstraintResolver (Phase C).

    Consumed by composition handler (handle_place_component) at runtime.
    """
    model_config = ConfigDict(extra="forbid")
    component_id: str
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    source: SourceKindType = "solver_derived"
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=1.0))
    assumptions: list[str] = Field(default_factory=list)
    is_pending: bool = False
    pending_reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Q&A System
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str
    label: str
    description: str = ""
    recommended: bool = False
    geometric_consequence: str = Field(
        default="",
        description="Spatial layout consequence of choosing this option (shown to user)"
    )
    auto_policy: str | None = None
    constraints_to_add: list[SpatialRelationDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpatialQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    unknown_id: str
    type: str
    entities: list[str]
    question_text: str
    why_it_matters: str
    impact: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    answer_cost: float = Field(ge=0.0, le=1.0)
    priority: float = Field(ge=0.0, le=1.0)
    options: list[SpatialQuestionOption] = Field(default_factory=list)
    allow_custom: bool = True
    allow_auto: bool = True


class UserSpatialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    mode: ClarificationMode
    selected_option_id: str | None = None
    custom_text: str | None = None
    auto_level: AutoLevelType | None = None


class NormalizedSpatialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    source_answer: UserSpatialAnswer
    relations_added: list[SpatialRelationDraft] = Field(default_factory=list)
    assumptions_added: list[str] = Field(default_factory=list)
    requires_replanning: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# AssumptionLedger
# ═══════════════════════════════════════════════════════════════════════════════

class AssumptionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumption_id: str
    statement: str
    source: SourceKindType
    confidence: float = Field(ge=0.0, le=1.0)
    user_delegated: bool = False
    user_confirmed: bool = False
    validation_status: ValidationStatusType = "not_checked"
    evidence: list[str] = Field(default_factory=list)


class AssumptionLedger(BaseModel):
    """Audit trail for every spatial assumption made during authoring.

    Every auto-inferred relation must be recorded here.
    High-risk unconfirmed assumptions block silent CAD generation.
    """
    model_config = ConfigDict(extra="forbid")
    entries: list[AssumptionEntry] = Field(default_factory=list)

    def add(self, entry: AssumptionEntry) -> None:
        self.entries.append(entry)

    def high_risk_unconfirmed(self) -> list[AssumptionEntry]:
        return [
            e for e in self.entries
            if e.confidence < 0.65
            and not e.user_confirmed
            and e.validation_status != "pass"
        ]

    def all_by_source(self, source: SourceKindType) -> list[AssumptionEntry]:
        return [e for e in self.entries if e.source == source]


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-round state management
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialSessionState(BaseModel):
    """Serializable state for multi-round clarification.

    When needs_clarification=True, this state is returned with the result.
    The caller persists it and passes it back on the next round.
    """
    model_config = ConfigDict(extra="forbid")
    session_id: str
    object_graph_json: str = Field(description="MechanicalObjectGraphDraft.model_dump_json()")
    constraint_graph_json: str | None = None
    ledger_json: str = Field(description="AssumptionLedger.model_dump_json()")
    answered_question_ids: list[str] = Field(default_factory=list)
    round_number: int = 1
    max_rounds: int = 3


# ═══════════════════════════════════════════════════════════════════════════════
# Solver / Validator Reports
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialSolverIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["warning", "error"]
    code: str
    message: str
    entities: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)


class SpatialSolverReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    constraints_total: int = 0
    constraints_solved: int = 0
    constraints_unsolved: int = 0
    pending_placements: list[str] = Field(default_factory=list)
    issues: list[SpatialSolverIssue] = Field(default_factory=list)


class SpatialValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["warning", "error"]
    code: str
    message: str
    entities: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)


class SpatialValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    issues: list[SpatialValidationIssue] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialFrontendResult — Phase A final output
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialFrontendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    needs_clarification: bool = False
    final_status: SpatialFinalStatus = "ASSUMPTION_BASED"
    questions: list[SpatialQuestion] = Field(default_factory=list)
    object_graph: MechanicalObjectGraphDraft | None = None
    constraint_graph: SpatialConstraintGraph | None = None
    solver_report: SpatialSolverReport | None = None
    validation_report: SpatialValidationReport | None = None
    assumption_ledger: AssumptionLedger = Field(default_factory=AssumptionLedger)
    session_state: SpatialSessionState | None = Field(
        default=None,
        description="Non-None when caller must persist state for next round"
    )
    failures: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# GeometrySpatialAudit models (Phase C)
# ═══════════════════════════════════════════════════════════════════════════════

class ComponentBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    xmin: float; xmax: float
    ymin: float; ymax: float
    zmin: float; zmax: float

    @property
    def xlen(self) -> float: return self.xmax - self.xmin
    @property
    def ylen(self) -> float: return self.ymax - self.ymin
    @property
    def zlen(self) -> float: return self.zmax - self.zmin
    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.xmin + self.xmax) / 2,
            (self.ymin + self.ymax) / 2,
            (self.zmin + self.zmax) / 2,
        )


class PairwiseSpatialMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str; b: str
    overlap_volume_mm3: float = 0.0
    overlap_ratio_min: float = Field(
        ge=0.0, le=1.0,
        description="min(overlap_vol/A_vol, overlap_vol/B_vol)"
    )
    bbox_distance_mm: float = 0.0
    contacts: bool = False


class GeometrySpatialAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    component_bboxes: list[ComponentBBox] = Field(default_factory=list)
    pairwise_metrics: list[PairwiseSpatialMetric] = Field(default_factory=list)
    issues: list[SpatialValidationIssue] = Field(default_factory=list)
    assembly_bbox_mm: tuple[float, float, float] | None = None
    solid_count: int | None = None
    connectivity_graph_connected: bool | None = None
