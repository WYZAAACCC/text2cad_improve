"""Semantic sketch topology graph — stable vertex/edge/wire identity.

Replaces anonymous OCC vertex-index addressing with engineering-semantic IDs.
Applicable to fir-tree grooves, dovetails, gear profiles, blade sections, etc.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field


class ProfileVertex(BaseModel):
    """A named point in the 2D sketch with an optional engineering role."""

    vertex_id: str = Field(description="Unique vertex identifier within this profile")
    x_mm: float
    y_mm: float
    engineering_role: str | None = Field(
        default=None,
        description="e.g. right_upper_tooth_tip, bore_clamp_root",
    )
    tags: set[str] = Field(default_factory=set)


class ProfileEdge(BaseModel):
    """A named edge segment (line or arc) between two vertices."""

    edge_id: str = Field(description="Unique edge identifier within this profile")
    kind: Literal["line", "arc"] = "line"
    start_vertex_id: str
    end_vertex_id: str
    engineering_role: str | None = Field(
        default=None,
        description="e.g. right_upper_working_flank, hub_to_web_transition",
    )
    tags: set[str] = Field(default_factory=set)

    # ── arc-specific fields ──
    center_x_mm: float | None = None
    center_y_mm: float | None = None
    radius_mm: float | None = None
    direction: Literal["cw", "ccw"] | None = None


class ProfileWire(BaseModel):
    """An ordered collection of edges forming a possibly-closed contour."""

    wire_id: str = Field(description="Unique wire identifier")
    ordered_edge_ids: list[str] = Field(min_length=1)
    closed: bool = False


class ProfileGraph(BaseModel):
    """Complete semantic topology for one 2D sketch profile.

    Build from polyline points + explicit arcs, then use for stable
    corner identification during fillet_sketch and postcondition checks.
    """

    vertices: dict[str, ProfileVertex] = Field(default_factory=dict)
    edges: dict[str, ProfileEdge] = Field(default_factory=dict)
    wires: dict[str, ProfileWire] = Field(default_factory=dict)
    default_wire_id: str | None = Field(default=None)

    # ── builders ──────────────────────────────────────────────────────

    @classmethod
    def from_polyline(
        cls,
        points: list[tuple[float, float]],
        *,
        wire_id: str = "profile",
        vertex_prefix: str = "v",
        edge_prefix: str = "e",
    ) -> "ProfileGraph":
        """Build a graph from a closed polyline (x,y) point list.

        Each point → ProfileVertex. Each consecutive pair → ProfileEdge.
        The last-to-first segment closes the loop.
        """
        n = len(points)
        if n < 3:
            raise ValueError(f"polyline must have ≥3 points, got {n}")

        vertices: dict[str, ProfileVertex] = {}
        edges: dict[str, ProfileEdge] = {}
        ordered: list[str] = []

        for i in range(n):
            vid = f"{vertex_prefix}{i}"
            vertices[vid] = ProfileVertex(
                vertex_id=vid, x_mm=points[i][0], y_mm=points[i][1],
            )
        for i in range(n):
            j = (i + 1) % n
            eid = f"{edge_prefix}{i}"
            edges[eid] = ProfileEdge(
                edge_id=eid,
                start_vertex_id=f"{vertex_prefix}{i}",
                end_vertex_id=f"{vertex_prefix}{j}",
            )
            ordered.append(eid)

        return cls(
            vertices=vertices,
            edges=edges,
            wires={wire_id: ProfileWire(wire_id=wire_id, ordered_edge_ids=ordered, closed=True)},
            default_wire_id=wire_id,
        )

    # ── queries ───────────────────────────────────────────────────────

    def resolve_wire(self, wire_id: str | None = None) -> ProfileWire:
        if wire_id is None:
            wire_id = self.default_wire_id
        if wire_id is None or wire_id not in self.wires:
            available = sorted(self.wires.keys())
            raise KeyError(
                f"wire '{wire_id}' not found. "
                f"Available: {available}. Must specify wire_id explicitly."
            )
        return self.wires[wire_id]

    def find_corner_vertex(
        self, edge_a_id: str, edge_b_id: str, wire_id: str | None = None
    ) -> str:
        """Return the vertex_id shared by two adjacent edges.

        Raises ValueError if the edges are not adjacent.
        """
        wire = self.resolve_wire(wire_id)
        e_ids = wire.ordered_edge_ids
        if edge_a_id not in self.edges or edge_b_id not in self.edges:
            raise ValueError("edge_id not found in graph")

        # Check adjacency in the ordered sequence (cyclic)
        pos_a = e_ids.index(edge_a_id)
        pos_b = e_ids.index(edge_b_id)
        diff = (pos_b - pos_a) % len(e_ids)
        if diff not in (1, len(e_ids) - 1):
            raise ValueError(
                f"edges '{edge_a_id}' and '{edge_b_id}' are not adjacent "
                f"in wire '{wire.wire_id}'"
            )

        edge_a = self.edges[edge_a_id]
        edge_b = self.edges[edge_b_id]
        shared = {edge_a.start_vertex_id, edge_a.end_vertex_id} & {
            edge_b.start_vertex_id, edge_b.end_vertex_id,
        }
        if len(shared) != 1:
            raise ValueError(
                f"edges '{edge_a_id}' and '{edge_b_id}' share "
                f"{len(shared)} vertices (expected 1)"
            )
        return shared.pop()

    def edge_length(self, edge_id: str) -> float:
        e = self.edges[edge_id]
        if e.kind == "arc":
            return float("nan")  # callers should use arc-specific length
        v1 = self.vertices[e.start_vertex_id]
        v2 = self.vertices[e.end_vertex_id]
        return math.hypot(v2.x_mm - v1.x_mm, v2.y_mm - v1.y_mm)

    def interior_angle_rad(self, edge_a_id: str, edge_b_id: str, wire_id: str | None = None) -> float:
        """Compute the interior angle (radians) at the shared corner vertex."""
        corner_vid = self.find_corner_vertex(edge_a_id, edge_b_id, wire_id)
        edge_a = self.edges[edge_a_id]
        edge_b = self.edges[edge_b_id]

        # Get the other endpoint of each edge (not the corner)
        if edge_a.start_vertex_id == corner_vid:
            va = self.vertices[edge_a.end_vertex_id]
        else:
            va = self.vertices[edge_a.start_vertex_id]
        if edge_b.start_vertex_id == corner_vid:
            vb = self.vertices[edge_b.end_vertex_id]
        else:
            vb = self.vertices[edge_b.start_vertex_id]

        corner = self.vertices[corner_vid]
        dx1 = va.x_mm - corner.x_mm; dy1 = va.y_mm - corner.y_mm
        dx2 = vb.x_mm - corner.x_mm; dy2 = vb.y_mm - corner.y_mm
        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 < 1e-12 or len2 < 1e-12:
            raise ValueError("zero-length edge at corner")
        cos_a = max(-1.0, min(1.0, (dx1*dx2 + dy1*dy2) / (len1*len2)))
        return math.acos(cos_a)
