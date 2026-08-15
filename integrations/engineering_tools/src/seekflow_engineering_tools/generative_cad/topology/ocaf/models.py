"""Core data models for OCAF topology capture — Live/Audit separation.

Implements §5 of the v3.0 implementation guide:

  Live Model (in-process only):
    - LiveEvolutionRelation: stores REAL TopoDS_Shape handles (old_shape + new_shapes)
    - LiveEvolutionBatch: groups relations from one builder execution
    - TrackedShapeResult: returned by tracked_* functions, holds batch directly

  Audit Model (JSON-safe, cross-process):
    - EvolutionRelationAudit: lightweight evidence projection, NO Shape handles

Constraints:
  - Live Shapes do NOT cross process boundaries and do NOT enter JSON.
  - Audit projection must not contain TopoDS_Shape handles.
  - Writer accepts ONLY LiveEvolutionBatch (never Audit).
  - Illegal relation (kind+shapes mismatch) → fail immediately (validate()).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EvolutionKind(str, Enum):
    """What kind of kernel-observed evolution occurred."""
    PRIMITIVE = "primitive"       # Shape created from nothing (box, cylinder, ...)
    GENERATED = "generated"       # New sub-shapes generated from old (profile → faces)
    MODIFIED = "modified"         # Existing sub-shapes modified (target face → result face)
    DELETED = "deleted"           # Old sub-shapes deleted (tool face consumed by cut)


class TopologyEntityKind(str, Enum):
    """Granularity of a topology entity."""
    SOLID = "solid"
    SHELL = "shell"
    FACE = "face"
    WIRE = "wire"
    EDGE = "edge"
    VERTEX = "vertex"


class ProofClass(str, Enum):
    """Provenance strength of a kernel history observation."""
    EXACT_KERNEL_HISTORY = "exact_kernel_history"   # Full BRepTools_History or Builder direct
    EXACT_CONSTRUCTION = "exact_construction"       # Determined by construction semantics
    PARTIAL_POSTPROCESS = "partial_postprocess"     # Missing post-processing phases (e.g. clean)
    EXTERNAL_IMPORT = "external_import"             # Imported geometry, no history available
    HEURISTIC_CANDIDATE = "heuristic_candidate"     # Fingerprint-based, NOT authoritative
    FAILED = "failed"                               # Extraction raised an exception


# ---------------------------------------------------------------------------
# Capture scope (unchanged from PR-1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopologyCaptureScope:
    """Identifies exactly which node/phase/suboperation produced a batch.

    Forms the namespace for relation_id uniqueness and audit traceability.
    """
    schema_version: str = "gcad_topo_v3@ocaf_v1"
    document_id: str = ""
    component_id: str = ""
    node_id: str = ""
    dialect: str = ""
    operation: str = ""
    operation_version: str = ""
    phase: str = ""
    suboperation_index: int = 0


# ---------------------------------------------------------------------------
# Live models — hold real TopoDS_Shape handles (in-process only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LiveEvolutionRelation:
    """A single kernel-observed evolution with REAL TopoDS_Shape handles.

    Live shapes MUST NOT be serialized or passed across process boundaries.
    They exist only for the duration of OCAF write within the same geometry worker.

    The validate() method enforces the shape contract:
      PRIMITIVE:  old_shape=None,  len(new_shapes) >= 1
      GENERATED:  old_shape!=None, len(new_shapes) >= 1
      MODIFIED:   old_shape!=None, len(new_shapes) >= 1
      DELETED:    old_shape!=None, len(new_shapes) == 0
    """

    relation_id: str
    operation_id: str
    kind: EvolutionKind
    entity_kind: TopologyEntityKind
    source_key: str
    old_shape: Any | None                # TopoDS_Shape | None (live!)
    new_shapes: tuple[Any, ...] = ()     # tuple of TopoDS_Shape (live!)
    proof: ProofClass = ProofClass.EXACT_KERNEL_HISTORY
    diagnostics: tuple[str, ...] = ()

    def validate(self) -> None:
        """Enforce the shape contract. Raises InvalidEvolutionRelationError.

        Uses explicit raise — NOT bare assert — so that validation survives
        ``python -O`` (which strips assert statements).  v5.0 §8.5.
        """
        from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
            InvalidEvolutionRelationError,
        )
        if self.kind is EvolutionKind.PRIMITIVE:
            if self.old_shape is not None:
                raise InvalidEvolutionRelationError(
                    f"PRIMITIVE relation {self.relation_id} must have old_shape=None",
                    relation_id=self.relation_id,
                    kind=self.kind.value,
                )
            if len(self.new_shapes) < 1:
                raise InvalidEvolutionRelationError(
                    f"PRIMITIVE relation {self.relation_id} must have >=1 new_shapes",
                    relation_id=self.relation_id,
                    kind=self.kind.value,
                )
        elif self.kind in (EvolutionKind.GENERATED, EvolutionKind.MODIFIED):
            if self.old_shape is None:
                raise InvalidEvolutionRelationError(
                    f"{self.kind.value} relation {self.relation_id} must have old_shape",
                    relation_id=self.relation_id,
                    kind=self.kind.value,
                )
            if len(self.new_shapes) < 1:
                raise InvalidEvolutionRelationError(
                    f"{self.kind.value} relation {self.relation_id} must have >=1 new_shapes",
                    relation_id=self.relation_id,
                    kind=self.kind.value,
                )
        elif self.kind is EvolutionKind.DELETED:
            if self.old_shape is None:
                raise InvalidEvolutionRelationError(
                    f"DELETED relation {self.relation_id} must have old_shape",
                    relation_id=self.relation_id,
                    kind=self.kind.value,
                )
            if len(self.new_shapes) != 0:
                raise InvalidEvolutionRelationError(
                    f"DELETED relation {self.relation_id} must have 0 new_shapes",
                    relation_id=self.relation_id,
                    kind=self.kind.value,
                )


@dataclass
class LiveEvolutionBatch:
    """All kernel-observed evolutions from a single builder execution.

    Live shapes (result_shape, context_shape, and shapes within relations)
    are in-process TopoDS_Shape handles. They MUST NOT be serialized.

    Each batch corresponds to one TrackedOperation execution.
    """

    scope: TopologyCaptureScope = field(default_factory=TopologyCaptureScope)
    builder_kind: str = ""                 # "BOPAlgo_BOP" | "BRepPrimAPI_MakePrism" | ...
    builder_options: dict[str, Any] = field(default_factory=dict)
    result_shape: Any = None               # TopoDS_Shape — the full result
    context_shape: Any = None              # TopoDS_Shape — context for Selector
    relations: list[LiveEvolutionRelation] = field(default_factory=list)
    construction_roles: dict[str, Any] = field(default_factory=dict)
    edge_roles: dict[str, Any] = field(default_factory=dict)
    face_roles: dict[str, Any] = field(default_factory=dict)
    history_complete: bool = True
    missing_phases: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def validate_all(self) -> None:
        """Run validate() on every relation in this batch."""
        for rel in self.relations:
            rel.validate()

    def to_audit(self) -> list[EvolutionRelationAudit]:
        """Project all relations to JSON-safe audit records."""
        return [rel_to_audit(r) for r in self.relations]


# ---------------------------------------------------------------------------
# Audit model — JSON safe, NO Shape handles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvolutionRelationAudit:
    """Lightweight, JSON-serializable projection of one evolution.

    Contains scalar evidence (area, centroid) but NO TopoDS_Shape handles.
    Used for metadata export, diagnostic logging, and audit trails.
    Must NEVER be used as input to TNaming_Builder.
    """

    relation_id: str
    operation_id: str
    kind: str
    entity_kind: str
    source_key: str
    proof: str
    old_evidence: dict | None = None
    new_evidence: tuple[dict, ...] = ()
    diagnostics: tuple[str, ...] = ()


def rel_to_audit(rel: LiveEvolutionRelation) -> EvolutionRelationAudit:
    """Convert a live relation to its audit projection."""
    return EvolutionRelationAudit(
        relation_id=rel.relation_id,
        operation_id=rel.operation_id,
        kind=rel.kind.value,
        entity_kind=rel.entity_kind.value,
        source_key=rel.source_key,
        proof=rel.proof.value,
        old_evidence=_shape_evidence(rel.old_shape) if rel.old_shape is not None else None,
        new_evidence=tuple(_shape_evidence(s) for s in rel.new_shapes),
        diagnostics=rel.diagnostics,
    )


def _shape_evidence(shape: Any) -> dict:
    """Extract lightweight evidence from a TopoDS_Shape for audit.

    Only stores scalar geometric properties — safe for JSON.
    Returns empty dict if shape is None or evidence extraction fails.
    """
    if shape is None:
        return {}
    try:
        # Try to treat as a TopoDS_Face
        from OCP.TopoDS import TopoDS_Face
        face = TopoDS_Face()
        face = TopoDS_Face.DownCast_s(shape) if hasattr(TopoDS_Face, 'DownCast_s') else None
        # Fallback: use BRepGProp for area/centroid
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, props)
        center = props.CentreOfMass()
        return {
            "area_mm2": round(props.Mass(), 4),
            "center": (round(center.X(), 4), round(center.Y(), 4), round(center.Z(), 4)),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# TrackedShapeResult — returned by all tracked_* functions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrackedShapeResult:
    """Result of a single tracked geometry operation.

    Contains the identical geometry as the corresponding CadQuery free function
    (verified by A/B volume/face/validity comparison), plus the LiveEvolutionBatch
    with all captured history relations.

    No capture_token — the batch is held directly. No global staging.
    """

    result: Any = None                     # cadquery.Shape — identical geometry
    batch: LiveEvolutionBatch = field(default_factory=LiveEvolutionBatch)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class FaceRoleSpec:
    """Stable per-face naming entry under a feature's ResultRoot.

    Unlike the semantic construction_roles (start_cap, rim, ...), this models
    *any* result face, including faces that are only modified/carried through
    by an operation such as fillet or boolean.

    ``source_shape`` records the first occurrence's cross-feature source:
      - first_evolution=MODIFIED  -> TNaming_Builder.Modify(source, face)
      - first_evolution=GENERATED -> TNaming_Builder.Generated(source, face)

    When a previous revision already named this role, the writer instead calls
    Modify(previous_face, face).
    """

    role_key: str
    shape: Any
    source_shape: Any | None = None
    first_evolution: EvolutionKind = EvolutionKind.GENERATED


# ---------------------------------------------------------------------------
# Selection models — §5.3 of v3.0 implementation guide
# ---------------------------------------------------------------------------

class SelectionCardinality(str, Enum):
    """How many topology entities can satisfy this selection."""
    EXACT_ONE = "exact_one"
    SET_ALLOWED = "set_allowed"


class SelectionResolutionStatus(str, Enum):
    """Outcome of solving a persistent selection against current geometry."""
    UNIQUE = "unique"               # Exactly one matching entity, semantics valid
    SET = "set"                     # Multiple entities allowed by policy
    DELETED = "deleted"             # Target deleted, policy allows
    AMBIGUOUS = "ambiguous"         # Multiple candidates but policy requires EXACT_ONE
    UNRESOLVED = "unresolved"       # Cannot resolve at all
    INVALID_SEMANTICS = "invalid_semantics"  # Resolved but fails semantic contract
    INVALID_POLICY = "invalid_policy"        # Policy cannot be read from OCAF (v5.0 §9.2)
    INVALID_CONTRACT = "invalid_contract"    # Contract cannot be read from OCAF (v5.0 §9.2)
    INVALID_SELECTION_ID = "invalid_selection_id"  # Selection ID not in index (v6.0 §9.1)
    VALIDATION_UNAVAILABLE = "validation_unavailable"  # Contract check cannot be executed (v6.0 §9.5)


@dataclass(frozen=True)
class SelectionPolicy:
    """Constraints on what kind of topology entity and how many.

    entity_kind: expected type (FACE, EDGE, etc.)
    cardinality: EXACT_ONE or SET_ALLOWED
    allow_deleted: if True, DELETED is a valid resolution
    required_for_cae: if True, heuristic fallback is forbidden
    split_strategy: optional split resolution ("largest_area") — when the
        selected face splits into multiple, return the largest-area sub-face
        as UNIQUE instead of AMBIGUOUS.
    """
    entity_kind: TopologyEntityKind
    cardinality: SelectionCardinality = SelectionCardinality.EXACT_ONE
    allow_deleted: bool = False
    required_for_cae: bool = False
    split_strategy: str | None = None


@dataclass(frozen=True)
class SemanticContract:
    """Post-hoc validation constraints on resolved topology.

    These are ONLY used for validation after TNaming Solve — never for
    identity resolution. A shape that matches all contract constraints
    is not necessarily the "correct" shape (only TNaming can tell that).
    """
    surface_type: str | None = None           # "Plane" | "Cylinder" | "Cone" | ...
    curve_type: str | None = None
    expected_axis: tuple[float, float, float] | None = None
    expected_normal: tuple[float, float, float] | None = None
    radius_range: tuple[float, float] | None = None
    area_range: tuple[float, float] | None = None     # (min_area, max_area) — v5.0 §9.5
    zone_id: str | None = None
    orientation: str | None = None
    connectivity_role: str | None = None


@dataclass(frozen=True)
class SelectionResolution:
    """Result of PersistentSelectionService.solve()."""
    status: SelectionResolutionStatus
    selection_id: str
    resolved_shapes: tuple[Any, ...] = ()     # TopoDS_Shape handles (live)
    candidates: list[dict] = field(default_factory=list)
    detail: str = ""
    proof: ProofClass | None = None


# ---------------------------------------------------------------------------
# Stable Identity models — v4.0 P0-02 + P1-01/02
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceEntityRef:
    """Stable reference to a topology entity without using face/edge index.

    P1-02: Replaces raw string source_keys like "target_face_0".
    Tracked operations should populate this from known component/feature/selection IDs.
    """
    component_id: str = ""
    feature_id: str = ""
    selection_id: str | None = None
    construction_role: str | None = None   # "start_cap" | "end_cap" | "profile_edge" | ...
    entity_kind: TopologyEntityKind = TopologyEntityKind.FACE


@dataclass(frozen=True)
class RelationKey:
    """Stable business identity for an evolution relation.

    P1-01: Replaces relation list index as persistent Tag.
    Same feature + source entity + kind + role → same OCAF label across revisions.
    """
    feature_id: str
    source_entity_ref: SourceEntityRef
    evolution_kind: EvolutionKind
    relation_role: str = ""   # "target" | "tool" | "profile"


@dataclass(frozen=True)
class StableObjectKey:
    """Composite key for stable label identity across revisions.

    object_kind: "component" | "feature" | "selection" | "relation" | "revision" | "cae_binding"
    namespace:   scoping context (e.g. "lineage", "component:disk", "feature:cut_1")
    object_id:   business identifier within the namespace
    """
    object_kind: str
    namespace: str
    object_id: str

    # v5.0 §5.3: expanded kind set for full index coverage
    _VALID_KINDS = frozenset({
        "component", "feature", "selection",
        "relation", "revision", "cae_binding", "face_role",
    })

    def __post_init__(self):
        if self.object_kind not in self._VALID_KINDS:
            raise ValueError(
                f"Invalid object_kind: {self.object_kind!r}. "
                f"Must be one of: {', '.join(sorted(self._VALID_KINDS))}"
            )

    def __str__(self) -> str:
        return f"{self.object_kind}:{self.namespace}:{self.object_id}"


# ---------------------------------------------------------------------------
# CAE Binding models — §12 of v3.0 implementation guide
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaeBinding:
    """A binding from a topology selection to a CAE analysis role.

    CAE solvers (ANSYS, etc.) receive only selection_id — never face index,
    edge index, coordinate, or nearest-neighbor heuristic.
    """
    binding_id: str
    selection_id: str
    analysis_role: str                    # "load_face" | "constraint_surface" | "bore_contact" | ...
    required: bool = True
    allowed_entity_kinds: tuple[TopologyEntityKind, ...] = (TopologyEntityKind.FACE,)
    cardinality: SelectionCardinality = SelectionCardinality.EXACT_ONE
    require_native_proof: bool = True      # reject HEURISTIC_CANDIDATE (v5.0 §10.3)
    require_complete_history: bool = True  # require history_complete=True (v5.0 §10.3)


@dataclass(frozen=True)
class CaePreflightResult:
    """Result of CAE binding preflight check.

    ok=True only if every required binding has a valid resolution.
    """
    ok: bool
    bindings: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SelectionSpec:
    """A pipeline-level spec for creating a persistent topology selection.

    selection_id: stable business identifier for the selection.
    component_id: owning component whose "body" output contains the target face.
    face_selector: CadQuery face selector string (e.g. ">Z" for the top face).
    role_key: optional named role (e.g. "+X", "start_cap") resolved from the
        captured feature's construction_roles; takes precedence over face_selector.
    edge_selector: CadQuery edge selector string (e.g. ">Z"), used when the
        policy entity_kind is EDGE.
    policy: optional SelectionPolicy (defaults to FACE / EXACT_ONE).
    contract: optional SemanticContract for post-solve validation.
    """
    selection_id: str
    component_id: str
    face_selector: str = ""
    role_key: str | None = None
    edge_selector: str = ""
    policy: SelectionPolicy | None = None
    contract: SemanticContract | None = None


# ---------------------------------------------------------------------------
# Pipeline configuration — v5.0 §6.2
# ---------------------------------------------------------------------------

TopologyMode = Literal["off", "audit", "enforce"]


@dataclass(frozen=True, slots=True)
class TopologyRunConfig:
    """Formal topology capture configuration for the G-CAD pipeline.

    v5.0 §6.2: replaces the ad-hoc ``ocaf_path`` + ``ctx.topology_mode`` pattern.

    Usage:
        config = TopologyRunConfig(mode="enforce", lineage_id="dl-1", revision_id="rev-1")
        result = run_canonical_gcad(canonical, ..., topology=config)
    """
    mode: TopologyMode = "off"
    lineage_id: str = ""
    revision_id: str = ""
    parent_revision_id: str | None = None
    output_root: Path | None = None
    required_selection_ids: tuple[str, ...] = ()
    required_cae_binding_ids: tuple[str, ...] = ()
    cae_bindings: tuple[Any, ...] = ()  # tuple[CaeBinding, ...] — v6.0 §8.3
    selection_specs: tuple[Any, ...] = ()  # tuple[SelectionSpec, ...] — v7 T12-a
    verify_in_subprocess: bool = True

    @property
    def ocaf_path(self) -> Path | None:
        """Derive the OCAF XBF path from output_root + lineage_id."""
        if self.output_root is None or not self.lineage_id:
            return None
        return self.output_root / "lineage" / self.lineage_id / "design.xbf"


# ---------------------------------------------------------------------------
# Revision model — v5.0 §7.2
# ---------------------------------------------------------------------------

RevisionState = Literal["staging", "validated", "published", "aborted"]


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """Immutable record of one revision in a design lineage.

    v5.0 §7.2: stored at Tag 100:6 in the OCAF document.
    Each Revision links to its parent for conflict-free lineage tracking.
    """
    lineage_id: str
    revision_id: str
    revision_number: int
    parent_revision_id: str | None = None
    canonical_ir_hash: str = ""
    operation_graph_hash: str = ""
    geometry_hash: str = ""
    xbf_hash: str | None = None
    state: RevisionState = "staging"

    def to_dict(self) -> dict:
        return {
            "lineage_id": self.lineage_id,
            "revision_id": self.revision_id,
            "revision_number": self.revision_number,
            "parent_revision_id": self.parent_revision_id,
            "canonical_ir_hash": self.canonical_ir_hash,
            "operation_graph_hash": self.operation_graph_hash,
            "geometry_hash": self.geometry_hash,
            "xbf_hash": self.xbf_hash,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RevisionRecord:
        return cls(
            lineage_id=data["lineage_id"],
            revision_id=data["revision_id"],
            revision_number=data["revision_number"],
            parent_revision_id=data.get("parent_revision_id"),
            canonical_ir_hash=data.get("canonical_ir_hash", ""),
            operation_graph_hash=data.get("operation_graph_hash", ""),
            geometry_hash=data.get("geometry_hash", ""),
            xbf_hash=data.get("xbf_hash"),
            state=data.get("state", "staging"),
        )
