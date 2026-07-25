"""Pure data models for OCAF topology capture. No OCP/OCCT dependency.

These models separate live (in-process) TopoDS_Shape data from serializable
audit metadata. Live shapes exist only in TopologyEvolutionBatch during capture;
EvolutionRelation stores lightweight evidence for audit trails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvolutionKind(str, Enum):
    """What kind of kernel-observed evolution occurred."""
    PRIMITIVE = "primitive"       # Shape created from nothing (box, cylinder, ...)
    GENERATED = "generated"       # New sub-shapes generated from old (profile → faces)
    MODIFIED = "modified"         # Existing sub-shapes modified (target face → result face)
    DELETED = "deleted"           # Old sub-shapes deleted (tool face consumed by cut)


class HistoryQuality(str, Enum):
    """Provenance strength of a kernel history observation."""
    EXACT_KERNEL = "exact_kernel"             # Complete BRepTools_History or Builder direct
    PARTIAL_KERNEL = "partial_kernel"         # Missing post-processing phases (e.g. clean)
    DETERMINISTIC = "deterministic"           # Based on construction semantics (primitive)
    UNAVAILABLE = "unavailable"               # Interface not available in current OCCT version
    FAILED = "failed"                         # Extraction raised an exception


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


@dataclass(frozen=True)
class EvolutionRelation:
    """A single kernel-observed evolution: old shape → new shapes.

    Live TopoDS_Shape handles are NOT stored here — they exist only in the
    enclosing TopologyEvolutionBatch during in-process capture. This record
    holds lightweight audit evidence for serialization.

    relation_id is globally unique within a document and scoped by node_id.
    """
    relation_id: str
    kind: EvolutionKind
    entity_type: str = "face"          # "face" | "edge" | "vertex"
    source_role: str = ""              # e.g. "target", "tool", "profile_face"
    quality: HistoryQuality = HistoryQuality.EXACT_KERNEL
    old_shape_evidence: dict[str, Any] = field(default_factory=dict)
    new_shape_count: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyEvolutionBatch:
    """All kernel-observed evolutions from a single builder execution.

    Live shapes (result_shape, context_shape, first_shape, last_shape) are
    in-process TopoDS_Shape handles. They MUST NOT be serialized to JSON or
    passed across process boundaries. They exist only for the duration of
    OCAF write and Selector creation within the same geometry worker.
    """
    scope: TopologyCaptureScope = field(default_factory=TopologyCaptureScope)
    builder_kind: str = ""                 # "BOPAlgo_BOP" | "BRepPrimAPI_MakePrism" | ...
    builder_options: dict[str, Any] = field(default_factory=dict)

    # Live shapes (in-process only, DO NOT serialize)
    result_shape: Any = None               # TopoDS_Shape
    context_shape: Any = None              # TopoDS_Shape
    first_shape: Any = None                # TopoDS_Shape | None (MakePrism FirstShape)
    last_shape: Any = None                 # TopoDS_Shape | None (MakePrism LastShape)

    relations: list[EvolutionRelation] = field(default_factory=list)
    history_complete: bool = True
    missing_phases: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrackedShapeResult:
    """Returned by every tracked_* function.

    Contains the exact same geometry as the corresponding CadQuery free function
    (verified by A/B volume/face/validity comparison), plus a capture_token
    referencing the staged TopologyEvolutionBatch.
    """
    result: Any = None                     # cadquery.Shape — identical geometry
    capture_token: str = ""                # unique ID referencing the staged batch
    diagnostics: tuple[str, ...] = ()
