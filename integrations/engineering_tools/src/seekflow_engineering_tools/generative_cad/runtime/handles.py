"""Runtime typed handles — cross-dialect data exchange via typed handles only."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimeHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    component_id: str | None = None
    producer_node: str | None = None


class SolidHandle(RuntimeHandle):
    type: Literal["solid"] = "solid"
    bbox_mm: tuple[float, float, float] | None = None
    volume_mm3: float | None = None


class SolidArrayHandle(RuntimeHandle):
    type: Literal["solid_array"] = "solid_array"
    solid_ids: list[str] = Field(default_factory=list)


class FrameHandle(RuntimeHandle):
    type: Literal["frame"] = "frame"
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    x_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    y_axis: tuple[float, float, float] = (0.0, 1.0, 0.0)
    z_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)


class PlaneHandle(RuntimeHandle):
    type: Literal["plane"] = "plane"
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0)


class PointHandle(RuntimeHandle):
    type: Literal["point"] = "point"
    xyz_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)


class CurveHandle(RuntimeHandle):
    type: Literal["curve"] = "curve"


class ProfileHandle(RuntimeHandle):
    type: Literal["profile"] = "profile"


class EdgeHandle(RuntimeHandle):
    """Handle for a specific edge on a solid body.

    Persistent topology (Phase 1+):
      persistent_topology_id: stable across rebuilds (gcad_topo_v1 scheme)
      semantic_role: human-readable label (e.g. "entry_rim", "top_edge")
      generation: lineage generation counter
      resolution_status: "exact" | "set" | "ambiguous" | "deleted" | "unresolved"

    Deprecated (runtime-only, NOT for persistence):
      edge_index: current B-Rep enumeration index — DO NOT persist
    """
    type: Literal["edge"] = "edge"
    parent_solid_id: str | None = None

    # ── Persistent topology (Phase 1+) ──
    persistent_topology_id: str = ""
    semantic_role: str | None = None
    generation: int = 0
    resolution_status: str = "exact"

    # ── Deprecated: runtime index only, NOT for persistence ──
    edge_index: int = 0  # @deprecated: use persistent_topology_id for stable references


class FaceHandle(RuntimeHandle):
    """Handle for a specific face on a solid body.

    Persistent topology (Phase 1+):
      persistent_topology_id: stable across rebuilds (gcad_topo_v1 scheme)
      semantic_role: human-readable label (e.g. "top", "hole_wall")
      generation: lineage generation counter
      resolution_status: "exact" | "set" | "ambiguous" | "deleted" | "unresolved"

    Deprecated (runtime-only, NOT for persistence):
      face_index: current B-Rep enumeration index — DO NOT persist
    """
    type: Literal["face"] = "face"
    parent_solid_id: str | None = None

    # ── Persistent topology (Phase 1+) ──
    persistent_topology_id: str = ""
    semantic_role: str | None = None
    generation: int = 0
    resolution_status: str = "exact"

    # ── Deprecated: runtime index only, NOT for persistence ──
    face_index: int = 0  # @deprecated: use persistent_topology_id for stable references


RuntimeValue = (
    SolidHandle
    | SolidArrayHandle
    | FrameHandle
    | PlaneHandle
    | PointHandle
    | CurveHandle
    | ProfileHandle
    | EdgeHandle
    | FaceHandle
)
