"""OCAF/TNaming persistent topology naming — PR-1: Tracked Operations.

This package provides OCCT Builder-level wrappers that perform geometry operations
once while simultaneously capturing kernel History (BRepTools_History or equivalent).

Architecture:
    tracked_ops/  — drop-in replacements for CadQuery shapes.cut/extrude/revolve
                    that produce identical geometry + history capture.
    compat.py     — OCP 7.8.1.1 verified API compatibility layer.
    models.py     — pure data models (no OCP dependency).

PR-1 scope: tracked_ops only. No OCAF Writer, no Selector, no Registry integration.
"""

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    get_xcaf_application,
    define_binxcaf_format,
    new_xcaf_document,
    list_of_shape_from_iterable,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    EvolutionRelation,
    HistoryQuality,
    TopologyCaptureScope,
    TopologyEvolutionBatch,
    TrackedShapeResult,
)

__all__ = [
    # compat
    "get_xcaf_application",
    "define_binxcaf_format",
    "new_xcaf_document",
    "list_of_shape_from_iterable",
    # models
    "EvolutionKind",
    "EvolutionRelation",
    "HistoryQuality",
    "TopologyCaptureScope",
    "TopologyEvolutionBatch",
    "TrackedShapeResult",
]
