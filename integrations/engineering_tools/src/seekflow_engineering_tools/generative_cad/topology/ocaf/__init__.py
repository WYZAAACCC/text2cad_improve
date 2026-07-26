"""OCAF/TNaming persistent topology naming.

Architecture:
    tracked_ops/       — drop-in replacements for CadQuery shapes.* with history
    models.py          — Live/Audit data models + Selection models
    compat.py          — OCP 7.8.1.1 verified API compatibility layer
    schema.py          — Fixed Tag 100 label tree schema
    label_index.py     — Stable object_id -> TagPath mapping
    repository.py      — OCAF document create/open/save/publish lifecycle
    document.py        — Per-revision OCAF document session
    errors.py          — Structured error types
    capture_session.py — Per-run batch collector (no global staging)
    writer.py          — TopologyNamingWriter (correct TNaming semantics)
    selection_service.py — PersistentSelectionService (native TNaming_Selector)
    heuristic_candidates.py — HeuristicCandidateFinder (diagnostics only)
    selectors.py       — DEPRECATED FaceSelector (use selection_service instead)
"""

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    get_xcaf_application,
    define_binxcaf_format,
    new_xcaf_document,
    list_of_shape_from_iterable,
    ext_utf8,
    retrieve_xcaf_document,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    TopologyEntityKind,
    ProofClass,
    TopologyCaptureScope,
    LiveEvolutionRelation,
    LiveEvolutionBatch,
    EvolutionRelationAudit,
    TrackedShapeResult,
    # Selection models (PR-4)
    SelectionCardinality,
    SelectionPolicy,
    SelectionResolutionStatus,
    SelectionResolution,
    SemanticContract,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
    validate_semantics,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.heuristic_candidates import (
    HeuristicCandidateFinder,
    HeuristicCandidate,
    HeuristicResult,
    HeuristicStatus,
    GeometryFingerprint,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import (
    run_cae_preflight,
)

__all__ = [
    # compat
    "get_xcaf_application",
    "define_binxcaf_format",
    "new_xcaf_document",
    "list_of_shape_from_iterable",
    "ext_utf8",
    "retrieve_xcaf_document",
    # models
    "EvolutionKind",
    "TopologyEntityKind",
    "ProofClass",
    "TopologyCaptureScope",
    "LiveEvolutionRelation",
    "LiveEvolutionBatch",
    "EvolutionRelationAudit",
    "TrackedShapeResult",
    # selection models
    "SelectionCardinality",
    "SelectionPolicy",
    "SelectionResolutionStatus",
    "SelectionResolution",
    "SemanticContract",
    # selection service (PR-4)
    "PersistentSelectionService",
    "validate_semantics",
    # heuristic candidates (PR-4)
    "HeuristicCandidateFinder",
    "HeuristicCandidate",
    "HeuristicResult",
    "HeuristicStatus",
    "GeometryFingerprint",
]
