"""Operation-specific history adapters — §2.3, §2.4 of the supplementary spec.

Defines:
  - KernelTrackedEntityType / DerivedAggregateType (§2.3):
    Narrow the scope of what OCCT history can authoritatively track.
  - OperationHistoryAdapter Protocol (§2.4):
    Interface each operation-specific adapter must implement.
  - 8 named adapter classes:
    Prism, Revolve, Fillet, Chamfer, ThickSolid, Loft, Sweep, Boolean.

Each adapter documents the operation-specific semantics that a generic
KernelHistoryAdapter cannot capture: FirstShape/LastShape, Degenerated edges,
profile-edge-to-lateral-face mapping, adjacent face modification, etc.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.3, §2.4
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from seekflow_engineering_tools.generative_cad.topology.kernel_identity import (
    KernelHistoryEdge,
)


# ═══════════════════════════════════════════════════════════════════════════════
# §2.3 — Entity tracking scope
# ═══════════════════════════════════════════════════════════════════════════════

KernelTrackedEntityType = Literal["vertex", "edge", "face", "solid"]
"""Entity types that OCCT history can authoritatively track.

Wire and Shell are NOT kernel-authoritative. They are derived aggregates
whose identity is defined by ordered member composition, not by direct
BRepTools_History queries.

Calling Generated(wire) or Modified(shell) and treating an empty list
as 'unchanged' is a bug — these must be handled as derived aggregates.
"""

DerivedAggregateType = Literal["wire", "shell", "compound", "compsolid"]
"""Entity types whose identity is derived from member entities.

Rules (§2.3):
  - Wire: identity = ordered edge-use aggregate
  - Shell: identity = oriented face-use aggregate
  - Compound/Compsolid: identity = child entity set + assembly structure
  - Must NOT call Generated(wire) or Modified(shell) and interpret
    empty results as 'unchanged'
"""


# ═══════════════════════════════════════════════════════════════════════════════
# §2.4 — OperationHistoryAdapter Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class OperationHistoryAdapter(Protocol):
    """Protocol for operation-specific history extraction (§2.4).

    Each CAD operation (Prism, Revolve, Fillet, Boolean, …) has unique
    semantics that a generic KernelHistoryAdapter cannot capture. This
    protocol defines the three methods every adapter must implement:

      1. execute() — perform the operation and return a result shape.
      2. extract_source_history() — query OCCT history for kernel edges.
      3. derive_operation_semantics() — produce operation-specific
         semantic anchors (FirstShape, LastShape, cap faces, etc.).

    The generic normalizer (KernelHistoryAdapter) can only process an
    already-correct source-result graph. It cannot REPAIR a graph that
    is missing operation-specific edges. The adapters here fill that gap.
    """

    adapter_name: str
    """Human-readable adapter name, e.g. 'PrismHistoryAdapter'."""

    def execute(self, **kwargs: Any) -> Any:
        """Perform the operation and return the result shape.

        Args:
            **kwargs: Operation-specific parameters (profile, vec, angle, …).

        Returns:
            The result TopoDS_Shape.
        """
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """Query OCCT history for kernel-level observations.

        Args:
            input_shapes: Dict mapping role names ('profile', 'target', 'tool',
                          'base_face', …) to tracked TopoDS_Shape inputs.

        Returns:
            List of KernelHistoryEdge — one per kernel observation.
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Derive operation-specific semantic anchors.

        Returns:
            List of semantic anchor dicts, each with at least:
              - 'anchor_type': 'first_shape' | 'last_shape' | 'cap_face'
                               | 'degenerated_edge' | 'adjacent_face'
                               | 'offset_face' | 'removed_face'
              - 'description': human-readable explanation
              - 'source_key': reference to input shape key
              - 'result_key': reference to result occurrence key
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Named Adapter Classes (§2.4)
# ═══════════════════════════════════════════════════════════════════════════════


class PrismHistoryAdapter:
    """Adapter for BRepPrimAPI_MakePrism (extrude).

    Operation-specific semantics:
      - Profile edge → lateral face: Generated(edge) produces the side face.
      - Start cap (basis): FirstShape() / FirstShape(subshape).
      - End cap: LastShape() / LastShape(subshape).
      - Copy parameter: records whether Copy=True (deep copy) or False (share).
      - When profile is a wire/face: explicitly interpret cap vs region relationship.

    Ref: §2.4 — Prism
    """

    adapter_name = "PrismHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """profile + vec → extruded solid."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """profile edges → Generated(edge) lateral faces.

        Also captures: FirstShape (start cap), LastShape (end cap).
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: start_cap, end_cap, lateral_faces, copy_mode."""
        ...

    @staticmethod
    def first_shape(result_shape: Any) -> Any:
        """Get the first (start) shape generated by the Prism operation."""
        ...

    @staticmethod
    def last_shape(result_shape: Any) -> Any:
        """Get the last (end) shape generated by the Prism operation."""
        ...


class RevolveHistoryAdapter:
    """Adapter for BRepPrimAPI_MakeRevol (revolve).

    Operation-specific semantics:
      - Profile edge → revolved face: Generated(edge).
      - Partial revolve start/end faces: FirstShape / LastShape.
      - Full 360° revolve: MUST NOT fabricate start/end caps.
      - Degenerated edges (axis-touching profile edges): Degenerated() query.
        Must be recorded — these are identity-significant (a degenerated edge
        means the profile edge collapsed to a point).

    Ref: §2.4 — Revolve
    """

    adapter_name = "RevolveHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """profile + axis + angle → revolved solid."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """profile edges → Generated(edge) revolved faces.

        Partial revolve: FirstShape/LastShape for start/end caps.
        Full 360°: no caps, Degenerated() for axis-touching edges.
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: start_cap, end_cap (partial), degenerated_edges, full_360."""
        ...

    @staticmethod
    def first_shape(result_shape: Any) -> Any:
        """Get the first shape (start cap for partial revolve)."""
        ...

    @staticmethod
    def last_shape(result_shape: Any) -> Any:
        """Get the last shape (end cap for partial revolve)."""
        ...

    @staticmethod
    def degenerated(result_shape: Any) -> list[Any]:
        """Get degenerated edges from the revolve operation."""
        ...


class FilletHistoryAdapter:
    """Adapter for BRepFilletAPI_MakeFillet.

    Operation-specific semantics:
      - Modified adjacent faces: fillet modifies faces adjacent to the
        filleted edge. These must be tracked as modified (same PID).
      - New fillet faces: generated (new PID).
      - Face count: total face count changes (2 adjacent + N new fillet faces).
      - Edge identity: the filleted edge is consumed.

    Ref: §2.4
    """

    adapter_name = "FilletHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """shape + edge + radius → filleted solid."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """filleted_edge → IsDeleted(edge).
        adjacent_faces → Modified(face) → same PID, updated geometry.
        new fillet faces → Generated(new faces) → new PIDs.
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: consumed_edges, modified_adjacent_faces, new_fillet_faces."""
        ...


class ChamferHistoryAdapter:
    """Adapter for BRepFilletAPI_MakeChamfer.

    Operation-specific semantics:
      - Same as Fillet for adjacent face modification.
      - Additional: top edge tracking (chamfer creates a new top edge
        between the two new chamfer faces).

    Ref: §2.4
    """

    adapter_name = "ChamferHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """shape + edge + distances → chamfered solid."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """Same as Fillet, plus top edge tracking on chamfer faces."""
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: consumed_edges, modified_adjacent_faces, new_chamfer_faces, top_edges."""
        ...


class ThickSolidHistoryAdapter:
    """Adapter for BRepOffsetAPI_MakeThickSolid.

    Operation-specific semantics:
      - Offset faces: faces that are offset (modified, same PID OR new PID
        depending on whether face identity survives the offset).
      - Removed faces: faces explicitly removed (deleted).
      - Wall faces: generated (new PIDs) — the thickness walls.

    Ref: §2.4
    """

    adapter_name = "ThickSolidHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """solid + faces_to_remove + thickness → shelled solid."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """removed_faces → IsDeleted.
        offset_faces → Modified (same PID) or Generated (new PID).
        wall faces → Generated (new PIDs).
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: removed_faces, offset_faces, wall_faces."""
        ...


class LoftHistoryAdapter:
    """Adapter for BRepOffsetAPI_ThruSections (loft).

    Operation-specific semantics:
      - Section → generated faces: faces between consecutive sections.
      - Start cap: FirstShape.
      - End cap: LastShape.
      - Section edges are consumed.
      - Ruled/smooth mode affects face topology.

    Ref: §2.4
    """

    adapter_name = "LoftHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """sections → lofted solid/shell."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """section edges → Generated(edge) loft faces.
        FirstShape/LastShape for caps.
        Section profiles themselves are consumed.
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: start_cap, end_cap, section_faces, consumed_sections."""
        ...

    @staticmethod
    def first_shape(result_shape: Any) -> Any:
        """Get the first (start cap) shape."""
        ...

    @staticmethod
    def last_shape(result_shape: Any) -> Any:
        """Get the last (end cap) shape."""
        ...


class SweepHistoryAdapter:
    """Adapter for BRepOffsetAPI_MakePipe (sweep).

    Operation-specific semantics:
      - Profile edges → swept faces: Generated(edge).
      - Spine edge tracking: spine edges used for sweep direction.
      - Start/end caps: FirstShape/LastShape (if solid).

    Ref: §2.4
    """

    adapter_name = "SweepHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """profile + spine → swept solid/shell."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """profile edges → Generated(edge) swept faces.
        spine edges → consumed (guides but not Generated).
        FirstShape/LastShape for caps.
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: profile_generated_faces, spine_consumed_edges, caps."""
        ...


class BooleanHistoryAdapter:
    """Adapter for BRepAlgoAPI_Fuse/Cut/Common.

    Operation-specific semantics:
      - Target faces: Modified or Unchanged (depends on intersection).
      - Tool faces: consumed (deleted) or Generated (create new faces
        on result — these are GENERATED_FROM_TOOL per §2.9).
      - Intersection faces: Generated (new PIDs) — created where
        target and tool intersect.
      - Multi-tool: each tool instance must be tracked independently.
      - Non-destructive mode: Preserves input shapes for history query.

    Ref: §2.4, §2.8
    """

    adapter_name = "BooleanHistoryAdapter"

    def execute(self, **kwargs: Any) -> Any:  # noqa: D401
        """target + tool(s) + operation → result solid."""
        ...

    def extract_source_history(
        self, input_shapes: dict[str, Any],
    ) -> list[KernelHistoryEdge]:
        """Target faces → Modified/Unchanged (same PID or unchanged).
        Tool faces → IsDeleted (consumed) or Generated (create faces on result).
        Intersection → Generated (new PIDs).

        Multi-tool: each tool instance tracked separately.
        query preserves per-instance provenance.
        """
        ...

    def derive_operation_semantics(self) -> list[dict]:
        """Anchors: target_modified_faces, tool_consumed_faces,
        tool_generated_faces, intersection_faces."""
        ...
