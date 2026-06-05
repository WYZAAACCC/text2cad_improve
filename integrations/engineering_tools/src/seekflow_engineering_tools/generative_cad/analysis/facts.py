"""ShapeFacts — typed geometric facts propagated through the operation graph.

ShapeFacts are conservative estimates of a solid body's geometric properties,
derived from operation parameters (static) or runtime measurements (dynamic).
They enable:
- Pre-execution feasibility checks (e.g. bore > outer radius → impossible)
- Planner decisions (e.g. hole pattern should batch)
- Cross-dialect analysis (e.g. composition boolean cut might be no-op)

Phase 1: facts derived from operation typed_params (static, no OCP needed).
Phase 2+: runtime measurement facts from GeometryRuntime.inspect_solid().

Design: facts are always conservative — unknown != error.
A fact with confidence="unknown" means "we couldn't determine this statically".
Only explicitly violated safety bounds are errors.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════════════════
# NumericFact — a single numeric property with confidence
# ═══════════════════════════════════════════════════════════════════════════════


class NumericFact(BaseModel):
    """A single numeric geometric property.

    Confidence levels:
    - exact: derived from operation parameters (e.g. revolve r_mm=50 → radius_max=50)
    - conservative: bounded estimate (e.g. boolean_cut → bbox <= original bbox)
    - measured: from runtime GeometryRuntime (Phase 2+)
    - unknown: could not determine (default)
    """

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(default=None, description="The numeric value, if known.")

    expr: dict[str, Any] | None = Field(
        default=None,
        description="DimExpr that produced this value (Phase 2+).",
    )
    confidence: Literal["exact", "conservative", "measured", "unknown"] = Field(
        default="unknown",
        description="How confident we are in this value.",
    )
    source_node: str | None = Field(
        default=None,
        description="Node ID that produced this fact.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# BBoxFacts — axis-aligned bounding box
# ═══════════════════════════════════════════════════════════════════════════════


class BBoxFacts(BaseModel):
    """Axis-aligned bounding box of a solid body.

    For axisymmetric parts, xlen == ylen == 2 * radius_max (conservative).
    """

    model_config = ConfigDict(extra="forbid")

    xlen_mm: NumericFact = Field(default_factory=NumericFact)
    ylen_mm: NumericFact = Field(default_factory=NumericFact)
    zlen_mm: NumericFact = Field(default_factory=NumericFact)
    xmin_mm: NumericFact = Field(default_factory=NumericFact)
    xmax_mm: NumericFact = Field(default_factory=NumericFact)
    ymin_mm: NumericFact = Field(default_factory=NumericFact)
    ymax_mm: NumericFact = Field(default_factory=NumericFact)
    zmin_mm: NumericFact = Field(default_factory=NumericFact)
    zmax_mm: NumericFact = Field(default_factory=NumericFact)


# ═══════════════════════════════════════════════════════════════════════════════
# FaceFact — a single named face
# ═══════════════════════════════════════════════════════════════════════════════


class FaceFact(BaseModel):
    """A named face on a solid body, identified by geometric role.

    Phase 1: faces are identified by role (top/bottom/outer_cylindrical etc.)
    from operation parameters. No OCP face iteration needed.
    """

    model_config = ConfigDict(extra="forbid")

    role: str = Field(description="Semantic role: 'top', 'bottom', 'front', 'outer_cylindrical', etc.")
    surface_type: Literal["plane", "cylinder", "cone", "sphere", "unknown"] = Field(
        default="unknown",
        description="Surface type of this face.",
    )
    normal: tuple[float, float, float] | None = Field(
        default=None,
        description="Approximate face normal (for planar faces).",
    )
    axis: tuple[float, float, float] | None = Field(
        default=None,
        description="Axis direction (for cylindrical faces).",
    )
    area_mm2: NumericFact = Field(default_factory=NumericFact)
    selector: dict[str, Any] = Field(
        default_factory=dict,
        description="FaceSelector that would re-select this face at runtime.",
    )
    source_node: str | None = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════════════
# ShapeFacts — geometric facts about a single solid body output
# ═══════════════════════════════════════════════════════════════════════════════


class ShapeFacts(BaseModel):
    """Geometric facts about a single solid body (node output or component output).

    Key invariant: facts are identified by value_id, matching the format
    used in CanonicalValueDecl.value_id:
      f"{type}:{component}:{node_id}:{output_name}"

    Example:
        ShapeFacts(
            value_id="solid:c1:n1:body",
            value_type="solid",
            component_id="c1",
            producer_node="n1",
            radius_max_mm=NumericFact(value=50.0, confidence="exact", source_node="n1"),
            bbox=BBoxFacts(xlen_mm=NumericFact(value=100.0, confidence="exact"), ...),
            traits=["closed_candidate", "axisymmetric", "z_axis"],
            faces={
                "outer_cylindrical": FaceFact(role="outer_cylindrical", surface_type="cylinder", axis=(0,0,1)),
                "top": FaceFact(role="top", surface_type="plane", normal=(0,0,1)),
            },
        )
    """

    model_config = ConfigDict(extra="forbid")

    value_id: str = Field(description="Unique ID matching CanonicalValueDecl.value_id format.")
    value_type: str = Field(default="solid", description="Nominal ValueType (from ir/values.py).")
    component_id: str = Field(description="Owning component ID.")
    producer_node: str | None = Field(default=None, description="Node that produced this solid.")

    # ── Bounding box ──
    bbox: BBoxFacts = Field(default_factory=BBoxFacts)

    # ── Radial extent (axisymmetric) ──
    radius_min_mm: NumericFact = Field(default_factory=NumericFact)
    radius_max_mm: NumericFact = Field(default_factory=NumericFact)

    # ── Axial extent ──
    length_z_mm: NumericFact = Field(default_factory=NumericFact)

    # ── Volume ──
    volume_mm3: NumericFact = Field(default_factory=NumericFact)

    # ── Qualitative traits ──
    traits: list[str] = Field(
        default_factory=list,
        description="E.g. 'closed_candidate', 'axisymmetric', 'z_axis', 'modified_by_boolean_cut'.",
    )

    # ── Named faces ──
    faces: dict[str, FaceFact] = Field(
        default_factory=dict,
        description="Faces keyed by role: 'top', 'bottom', 'outer_cylindrical', etc.",
    )

    # ── Provenance ──
    derived_from: list[str] = Field(
        default_factory=list,
        description="value_ids of upstream ShapeFacts this was derived from.",
    )
    notes: list[str] = Field(default_factory=list)

    # ── Extension: operation-specific extras ──
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Operation-specific facts (e.g. center_bore_radius_mm, hole_patterns).",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FactStore — stores and indexes ShapeFacts by value_id and node_output key
# ═══════════════════════════════════════════════════════════════════════════════


class FactStore(BaseModel):
    """Container for all ShapeFacts in a compilation unit.

    Provides two lookup paths:
    1. by_value_id: value_id → ShapeFacts (universal key)
    2. by_node_output: "{node_id}.{output_name}" → value_id (shortcut for node context)
    """

    model_config = ConfigDict(extra="forbid")

    by_value_id: dict[str, ShapeFacts] = Field(default_factory=dict)
    by_node_output: dict[str, str] = Field(
        default_factory=dict,
        description="'{node_id}.{output_name}' → value_id mapping.",
    )

    def bind(self, node_id: str, output_name: str, facts: ShapeFacts) -> None:
        """Register a ShapeFacts entry.

        Args:
            node_id: The producer node ID.
            output_name: The output name (e.g. 'body').
            facts: The ShapeFacts to register (must have value_id set).
        """
        key = f"{node_id}.{output_name}"
        self.by_node_output[key] = facts.value_id
        self.by_value_id[facts.value_id] = facts

    def get_node_output(self, node_id: str, output_name: str) -> ShapeFacts | None:
        """Look up ShapeFacts by node ID and output name.

        Returns None if no facts are registered for this output.
        """
        fid = self.by_node_output.get(f"{node_id}.{output_name}")
        if not fid:
            return None
        return self.by_value_id.get(fid)

    def get_component_output(self, component_id: str, output_name: str = "body") -> ShapeFacts | None:
        """Look up ShapeFacts by component ID and output name.

        Searches through all facts to find one matching the component_id
        and output name. Uses node_output binding for fast lookup when
        the component root_node is known; falls back to linear scan.
        """
        # Fast path: check if any node_output binding matches
        for node_key, vid in self.by_node_output.items():
            # node_key format: "{node_id}.{output_name}"
            if node_key.endswith(f".{output_name}"):
                facts = self.by_value_id.get(vid)
                if facts and facts.component_id == component_id:
                    return facts
        # Slow path: linear scan
        for facts in self.by_value_id.values():
            if facts.component_id == component_id:
                if f":{component_id}:" in facts.value_id:
                    return facts
        return None
