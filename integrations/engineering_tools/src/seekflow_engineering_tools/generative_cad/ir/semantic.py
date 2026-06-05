"""Semantic type sidecar — enriches nominal ValueType with geometric traits.

Phase 1: schema definition only. Not wired into validation pipeline.
Phase 2+: semantic_typecheck pass can use these to catch mismatches
(e.g. chamfer requires closed_solid, shell requires manifold_solid).

Design: Does NOT replace ir/values.py ValueType. Old ValueType continues
to be used for typecheck and runtime handle ABI. SemanticType is a parallel
sidecar used by new analysis passes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════════════════
# SemanticType
# ═══════════════════════════════════════════════════════════════════════════════


class SemanticType(BaseModel):
    """Semantic type annotation — enriches nominal ValueType with geometric traits.

    Traits are conservative: absent trait means "unknown", not "false".
    This is important — we don't want to reject valid geometry because
    we couldn't determine a trait.

    Example:
        SemanticType(kind="solid", traits=["closed", "manifold", "axisymmetric"])
        SemanticType(kind="profile", traits=["closed", "planar"])
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "solid",
        "solid_array",
        "frame",
        "plane",
        "point",
        "curve",
        "profile",
        "sketch",
        "face",
        "edge",
        "datum",
        "dimension",
    ] = Field(description="Broad value kind (more granular than ValueType).")

    traits: list[str] = Field(
        default_factory=list,
        description=(
            "Geometric traits: 'closed', 'manifold', 'planar', 'cylindrical', "
            "'axisymmetric', 'prismatic', 'thin_walled', 'single_body', 'multi_body'."
        ),
    )
    facts: dict[str, Any] = Field(
        default_factory=dict,
        description="Supplementary facts (e.g. radius range, bbox extent).",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FaceSelector — named face selection (topology-relative, not index-based)
# ═══════════════════════════════════════════════════════════════════════════════


class FaceSelector(BaseModel):
    """Describe which face(s) of a solid body to operate on.

    Used by PlacementExpr and future face-relative operations.
    Selection is semantic (topology-relative), not index-based.
    This avoids the persistent topology naming problem — we select
    by geometric role, not by face index.

    Example (outer cylindrical face):
        FaceSelector(source={"component": "c1"}, role="outer_cylindrical")

    Example (largest planar face in +Z direction):
        FaceSelector(source={"component": "c1"}, role="largest_planar", normal_hint=(0, 0, 1))
    """

    model_config = ConfigDict(extra="forbid")

    source: dict[str, str] = Field(
        default_factory=dict,
        description="Source specifier: {'component': 'c1'} or {'node': 'n1', 'output': 'body'}.",
    )
    role: (
        Literal[
            "top",
            "bottom",
            "front",
            "back",
            "left",
            "right",
            "outer_cylindrical",
            "inner_cylindrical",
            "largest_planar",
            "all",
        ]
        | None
    ) = Field(
        default=None,
        description="Semantic role of the target face.",
    )
    normal_hint: tuple[float, float, float] | None = Field(
        default=None,
        description="Approximate face normal for disambiguation.",
    )
    area_rank: int | None = Field(
        default=None,
        description="Select by area rank (0=largest, 1=second largest, -1=smallest).",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PlacementExpr — face-relative placement (unified hole/slot/boss/rib placement)
# ═══════════════════════════════════════════════════════════════════════════════


class PlacementExpr(BaseModel):
    """Unified placement expression for face-relative feature positioning.

    Replaces the proliferation of placement models:
    - HolePlacementV2 (from ir/geometry_semantics.py)
    - CircularPatternPlacementV2
    - Legacy axis + position_mm

    All of these can be expressed as a FaceSelector + origin + UV offset.

    Example (center of top face, blind 30mm):
        PlacementExpr(
            face=FaceSelector(role="top"),
            origin="center",
            u=0.0, v=0.0,
            direction="face_normal",
        )
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["placement_expr"] = "placement_expr"

    face: FaceSelector = Field(
        description="Target face for the placement.",
    )
    origin: Literal["center", "centroid", "datum", "uv"] = Field(
        default="center",
        description="Origin mode for UV coordinate interpretation.",
    )
    u: float | dict[str, Any] = Field(
        default=0.0,
        description="U coordinate on the face (mm or DimExpr).",
    )
    v: float | dict[str, Any] = Field(
        default=0.0,
        description="V coordinate on the face (mm or DimExpr).",
    )
    direction: Literal["face_normal", "reverse_face_normal"] = Field(
        default="face_normal",
        description="Direction from entry face INTO the part.",
    )
