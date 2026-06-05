"""Fact derivation rules — per-operation ShapeFacts computation.

Each rule function reads a CanonicalNode's typed_params (and optionally
upstream facts from FactStore) and produces a ShapeFacts for the node's
solid body output.

Phase 1 coverage:
  - axisymmetric.revolve_profile
  - axisymmetric.cut_center_bore
  - axisymmetric.cut_circular_hole_pattern
  - axisymmetric.cut_annular_groove
  - composition.translate_solid
  - composition.boolean_union
  - composition.boolean_cut

Phase 2+: extends to sketch_extrude, loft_sweep, shell_housing ops.

Design: each rule is a pure function with signature:
  (node: CanonicalNode, component_id: str, store: FactStore | None) -> ShapeFacts
"""

from __future__ import annotations

from typing import Any, Callable

from seekflow_engineering_tools.generative_cad.analysis.facts import (
    BBoxFacts,
    FaceFact,
    NumericFact,
    ShapeFacts,
)
from seekflow_engineering_tools.generative_cad.compiler.config import MIN_WALL_MARGIN_MM


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _is_finite(x: Any) -> bool:
    """Return True if x is a finite number."""
    return isinstance(x, (int, float)) and x == x and x != float("inf") and x != float("-inf")


def _n(value: float | None, confidence: str = "exact", source_node: str | None = None) -> NumericFact:
    """Create a NumericFact with the given value and confidence."""
    return NumericFact(value=value, confidence=confidence, source_node=source_node)


def _make_value_id(node, output_name: str = "body") -> str:
    """Build a value_id matching CanonicalValueDecl.value_id format."""
    return f"solid:{node.component}:{node.id}:{output_name}"


def _typed(node, key: str, default: Any = None) -> Any:
    """Get a value from typed_params, falling back to params."""
    if node.typed_params:
        return node.typed_params.get(key, node.params.get(key, default))
    return node.params.get(key, default)


# ═══════════════════════════════════════════════════════════════════════════════
# axisymmetric.revolve_profile
# ═══════════════════════════════════════════════════════════════════════════════


def rule_revolve_profile(node, component_id: str, _store=None) -> ShapeFacts:
    """Derive ShapeFacts from revolve_profile parameters.

    Input: profile_stations: list[{r_mm, z_front_mm, z_rear_mm}]
    Output: radius_max_mm, radius_min_mm, bbox, zlen, faces (top/bottom/outer_cylindrical)
    """
    stations = _typed(node, "profile_stations", [])
    if not stations:
        return ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["no profile stations — cannot derive facts"],
        )

    max_r = 0.0
    min_r = float("inf")
    z_min = float("inf")
    z_max = float("-inf")

    for s in stations:
        r = float(s.get("r_mm", 0))
        zf = float(s.get("z_front_mm", 0))
        zr = float(s.get("z_rear_mm", 0))
        if _is_finite(r) and r > 0:
            max_r = max(max_r, r)
            min_r = min(min_r, r)
        if _is_finite(zf):
            z_min = min(z_min, zf)
        if _is_finite(zr):
            z_max = max(z_max, zr)

    if max_r <= 0 or min_r <= 0 or min_r == float("inf"):
        return ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["profile_stations have no valid radii"],
        )

    zlen = z_max - z_min if z_min < float("inf") and z_max > float("-inf") else 0.0

    return ShapeFacts(
        value_id=_make_value_id(node),
        value_type="solid",
        component_id=component_id,
        producer_node=node.id,
        bbox=BBoxFacts(
            xlen_mm=_n(2.0 * max_r, "exact", node.id),
            ylen_mm=_n(2.0 * max_r, "exact", node.id),
            zlen_mm=_n(zlen, "exact", node.id) if zlen > 0 else NumericFact(),
            xmin_mm=_n(-max_r, "exact", node.id),
            xmax_mm=_n(max_r, "exact", node.id),
            ymin_mm=_n(-max_r, "exact", node.id),
            ymax_mm=_n(max_r, "exact", node.id),
            zmin_mm=_n(z_min, "exact", node.id) if z_min < float("inf") else NumericFact(),
            zmax_mm=_n(z_max, "exact", node.id) if z_max > float("-inf") else NumericFact(),
        ),
        radius_min_mm=_n(min_r, "exact", node.id),
        radius_max_mm=_n(max_r, "exact", node.id),
        length_z_mm=_n(zlen, "exact", node.id) if zlen > 0 else NumericFact(),
        traits=["closed_candidate", "axisymmetric", "z_axis"],
        faces={
            "top": FaceFact(
                role="top",
                surface_type="plane",
                normal=(0.0, 0.0, 1.0),
                source_node=node.id,
            ),
            "bottom": FaceFact(
                role="bottom",
                surface_type="plane",
                normal=(0.0, 0.0, -1.0),
                source_node=node.id,
            ),
            "outer_cylindrical": FaceFact(
                role="outer_cylindrical",
                surface_type="cylinder",
                axis=(0.0, 0.0, 1.0),
                source_node=node.id,
            ),
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# axisymmetric.cut_center_bore
# ═══════════════════════════════════════════════════════════════════════════════


def rule_cut_center_bore(node, component_id: str, store=None) -> ShapeFacts:
    """Derive ShapeFacts after cut_center_bore.

    Reads input facts to get radius_max_mm.
    Checks bore diameter feasibility.
    Propagates input facts with inner_cylindrical face added.
    """
    dia = float(_typed(node, "diameter_mm", 0))
    bore_r = dia / 2.0 if dia > 0 else None

    # Try to get input facts
    input_facts = None
    if store is not None and node.inputs:
        inp = node.inputs[0]
        if inp.producer_node:
            input_facts = store.get_node_output(inp.producer_node, inp.output)

    # Start from input facts or create minimal
    if input_facts is not None:
        facts = input_facts.model_copy(deep=True)
        facts.value_id = _make_value_id(node)
        facts.producer_node = node.id
        facts.derived_from = [input_facts.value_id]
    else:
        facts = ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["no input facts available — minimal facts"],
        )

    if bore_r is not None:
        facts.extra["center_bore_radius_mm"] = bore_r
        facts.notes.append(f"center bore: dia={dia}mm, r={bore_r}mm")

        # Add inner cylindrical face
        facts.faces["inner_cylindrical"] = FaceFact(
            role="inner_cylindrical",
            surface_type="cylinder",
            axis=(0.0, 0.0, 1.0),
            source_node=node.id,
        )

        # Feasibility check: bore must be smaller than outer radius
        outer_r = facts.radius_max_mm.value
        if outer_r is not None:
            if bore_r >= outer_r:
                facts.notes.append(
                    f"FEASIBILITY ERROR: bore radius ({bore_r}mm) >= "
                    f"outer radius ({outer_r}mm) — geometrically impossible"
                )
            elif bore_r >= outer_r - MIN_WALL_MARGIN_MM:
                facts.notes.append(
                    f"FEASIBILITY WARNING: wall thickness only "
                    f"{outer_r - bore_r:.1f}mm (margin={MIN_WALL_MARGIN_MM}mm)"
                )

    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# axisymmetric.cut_circular_hole_pattern
# ═══════════════════════════════════════════════════════════════════════════════


def rule_cut_circular_hole_pattern(node, component_id: str, store=None) -> ShapeFacts:
    """Derive ShapeFacts after cut_circular_hole_pattern.

    Checks:
    - pcd/2 + hole_dia/2 < radius_max_mm - margin
    - pcd/2 - hole_dia/2 > center_bore_radius + margin (if bore exists)
    """
    count = int(_typed(node, "count", 0))
    pcd = float(_typed(node, "pcd_mm", 0))
    hole_dia = float(_typed(node, "hole_dia_mm", 0))

    # Get input facts
    input_facts = None
    if store is not None and node.inputs:
        inp = node.inputs[0]
        if inp.producer_node:
            input_facts = store.get_node_output(inp.producer_node, inp.output)

    if input_facts is not None:
        facts = input_facts.model_copy(deep=True)
        facts.value_id = _make_value_id(node)
        facts.producer_node = node.id
        facts.derived_from = [input_facts.value_id]
    else:
        facts = ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["no input facts available"],
        )

    if count > 0 and pcd > 0 and hole_dia > 0:
        hole_r = hole_dia / 2.0
        pcd_r = pcd / 2.0
        outer_edge = pcd_r + hole_r
        inner_edge = pcd_r - hole_r

        # Record pattern info
        hole_patterns = facts.extra.get("hole_patterns", [])
        if isinstance(hole_patterns, list):
            hole_patterns.append({
                "count": count,
                "pcd_mm": pcd,
                "hole_dia_mm": hole_dia,
                "outer_edge_mm": round(outer_edge, 1),
                "inner_edge_mm": round(inner_edge, 1),
            })
        facts.extra["hole_patterns"] = hole_patterns

        # Feasibility against outer radius
        outer_r = facts.radius_max_mm.value
        if outer_r is not None:
            if outer_edge >= outer_r - MIN_WALL_MARGIN_MM:
                facts.notes.append(
                    f"FEASIBILITY ERROR: hole pattern outer edge ({outer_edge:.1f}mm) "
                    f">= outer radius ({outer_r:.1f}mm) - margin ({MIN_WALL_MARGIN_MM}mm)"
                )

        # Feasibility against center bore
        bore_r = facts.extra.get("center_bore_radius_mm")
        if bore_r is not None and isinstance(bore_r, (int, float)):
            if inner_edge <= bore_r + MIN_WALL_MARGIN_MM:
                facts.notes.append(
                    f"FEASIBILITY ERROR: hole pattern inner edge ({inner_edge:.1f}mm) "
                    f"<= bore radius ({bore_r:.1f}mm) + margin ({MIN_WALL_MARGIN_MM}mm)"
                )

    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# axisymmetric.cut_annular_groove
# ═══════════════════════════════════════════════════════════════════════════════


def rule_cut_annular_groove(node, component_id: str, store=None) -> ShapeFacts:
    """Derive ShapeFacts after cut_annular_groove.

    Checks outer_dia/2 < radius_max_mm - margin.
    """
    inner_dia = float(_typed(node, "inner_dia_mm", 0))
    outer_dia = float(_typed(node, "outer_dia_mm", 0))

    input_facts = None
    if store is not None and node.inputs:
        inp = node.inputs[0]
        if inp.producer_node:
            input_facts = store.get_node_output(inp.producer_node, inp.output)

    if input_facts is not None:
        facts = input_facts.model_copy(deep=True)
        facts.value_id = _make_value_id(node)
        facts.producer_node = node.id
        facts.derived_from = [input_facts.value_id]
    else:
        facts = ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
        )

    if inner_dia > 0 and outer_dia > 0:
        outer_r = outer_dia / 2.0
        facts.extra["groove_inner_dia_mm"] = inner_dia
        facts.extra["groove_outer_dia_mm"] = outer_dia

        body_outer_r = facts.radius_max_mm.value
        if body_outer_r is not None and outer_r >= body_outer_r - MIN_WALL_MARGIN_MM:
            facts.notes.append(
                f"FEASIBILITY ERROR: groove outer radius ({outer_r:.1f}mm) "
                f">= body outer radius ({body_outer_r:.1f}mm) - margin"
            )

    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# sketch_extrude.extrude_rectangle
# ═══════════════════════════════════════════════════════════════════════════════


def rule_extrude_rectangle(node, component_id: str, _store=None) -> ShapeFacts:
    """Derive ShapeFacts from extrude_rectangle parameters.

    Input: width_mm, height_mm, depth_mm, plane, centered
    Output: bbox (xlen, ylen, zlen), traits=['prismatic']
    """
    w = float(_typed(node, "width_mm", 0))
    h = float(_typed(node, "height_mm", 0))
    d = float(_typed(node, "depth_mm", 0))
    plane = _typed(node, "plane", "XY")
    centered = _typed(node, "centered", True)

    if w <= 0 or h <= 0 or d <= 0:
        return ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["invalid dimensions — cannot derive facts"],
        )

    # BBox depends on plane orientation
    if plane == "XY":
        xlen, ylen, zlen = w, h, d
    elif plane == "XZ":
        xlen, ylen, zlen = w, d, h
    elif plane == "YZ":
        xlen, ylen, zlen = d, h, w
    else:
        xlen, ylen, zlen = w, h, d

    if centered:
        xmin, ymin, zmin = -xlen / 2.0, -ylen / 2.0, 0.0
        xmax, ymax, zmax = xlen / 2.0, ylen / 2.0, zlen
    else:
        xmin, ymin, zmin = 0.0, 0.0, 0.0
        xmax, ymax, zmax = xlen, ylen, zlen

    faces = {
        "top": FaceFact(role="top", surface_type="plane", normal=(0.0, 0.0, 1.0), source_node=node.id),
        "bottom": FaceFact(role="bottom", surface_type="plane", normal=(0.0, 0.0, -1.0), source_node=node.id),
        "front": FaceFact(role="front", surface_type="plane", normal=(0.0, 1.0, 0.0), source_node=node.id),
        "back": FaceFact(role="back", surface_type="plane", normal=(0.0, -1.0, 0.0), source_node=node.id),
        "left": FaceFact(role="left", surface_type="plane", normal=(-1.0, 0.0, 0.0), source_node=node.id),
        "right": FaceFact(role="right", surface_type="plane", normal=(1.0, 0.0, 0.0), source_node=node.id),
    }

    return ShapeFacts(
        value_id=_make_value_id(node),
        value_type="solid",
        component_id=component_id,
        producer_node=node.id,
        bbox=BBoxFacts(
            xlen_mm=_n(xlen, "exact", node.id),
            ylen_mm=_n(ylen, "exact", node.id),
            zlen_mm=_n(zlen, "exact", node.id),
            xmin_mm=_n(xmin, "exact", node.id),
            xmax_mm=_n(xmax, "exact", node.id),
            ymin_mm=_n(ymin, "exact", node.id),
            ymax_mm=_n(ymax, "exact", node.id),
            zmin_mm=_n(zmin, "exact", node.id),
            zmax_mm=_n(zmax, "exact", node.id),
        ),
        length_z_mm=_n(zlen, "exact", node.id),
        traits=["prismatic", "rectangular"],
        faces=faces,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# composition.translate_solid
# ═══════════════════════════════════════════════════════════════════════════════


def rule_translate_solid(node, component_id: str, store=None) -> ShapeFacts:
    """Derive ShapeFacts after translate_solid.

    Shifts bbox min/max by translation vector if exact facts exist.
    Bbox lengths unchanged.
    """
    input_facts = None
    if store is not None and node.inputs:
        inp = node.inputs[0]
        if inp.producer_node:
            input_facts = store.get_node_output(inp.producer_node, inp.output)

    if input_facts is not None:
        facts = input_facts.model_copy(deep=True)
        facts.value_id = _make_value_id(node)
        facts.producer_node = node.id
        facts.derived_from = [input_facts.value_id]
    else:
        facts = ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["no input facts — cannot propagate bbox"],
        )
        return facts

    # Shift bbox by translation vector
    vec = node.params.get("vector_mm", (0, 0, 0))
    if isinstance(vec, (list, tuple)) and len(vec) == 3:
        dx, dy, dz = float(vec[0]), float(vec[1]), float(vec[2])
        if any(v != 0 for v in (dx, dy, dz)):
            for attr, delta in [("xmin_mm", dx), ("xmax_mm", dx),
                                ("ymin_mm", dy), ("ymax_mm", dy),
                                ("zmin_mm", dz), ("zmax_mm", dz)]:
                old = getattr(facts.bbox, attr)
                if old.value is not None:
                    setattr(facts.bbox, attr, _n(old.value + delta, old.confidence, node.id))
            facts.notes.append(f"bbox shifted by ({dx}, {dy}, {dz})")

    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# composition.boolean_union
# ═══════════════════════════════════════════════════════════════════════════════


def rule_boolean_union(node, component_id: str, store=None) -> ShapeFacts:
    """Derive ShapeFacts after boolean_union.

    Conservative: bbox is union of input bboxes.
    """
    facts_a = None
    facts_b = None
    if store is not None and len(node.inputs) >= 2:
        if node.inputs[0].producer_node:
            facts_a = store.get_node_output(node.inputs[0].producer_node, node.inputs[0].output)
        if node.inputs[1].producer_node:
            facts_b = store.get_node_output(node.inputs[1].producer_node, node.inputs[1].output)

    facts = ShapeFacts(
        value_id=_make_value_id(node),
        component_id=component_id,
        producer_node=node.id,
        traits=["merged_by_boolean_union"],
        derived_from=[
            f.value_id for f in (facts_a, facts_b) if f is not None
        ],
    )

    if facts_a is not None and facts_b is not None:
        # Conservative bbox: union of individual bboxes
        bbox = facts.bbox
        for attr in ("xmin_mm", "ymin_mm", "zmin_mm"):
            va = getattr(facts_a.bbox, attr).value
            vb = getattr(facts_b.bbox, attr).value
            if va is not None and vb is not None:
                setattr(bbox, attr, _n(min(va, vb), "conservative", node.id))
        for attr in ("xmax_mm", "ymax_mm", "zmax_mm"):
            va = getattr(facts_a.bbox, attr).value
            vb = getattr(facts_b.bbox, attr).value
            if va is not None and vb is not None:
                setattr(bbox, attr, _n(max(va, vb), "conservative", node.id))
        for attr in ("xlen_mm", "ylen_mm", "zlen_mm"):
            suffix = attr[0]  # x, y, z
            min_v = getattr(bbox, f"{suffix}min_mm").value
            max_v = getattr(bbox, f"{suffix}max_mm").value
            if min_v is not None and max_v is not None:
                setattr(bbox, attr, _n(max_v - min_v, "conservative", node.id))

    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# composition.boolean_cut
# ═══════════════════════════════════════════════════════════════════════════════


def rule_boolean_cut(node, component_id: str, store=None) -> ShapeFacts:
    """Derive ShapeFacts after boolean_cut.

    Conservative: copy target facts. Check if cutter bbox warning-worthy.
    """
    facts_target = None
    facts_cutter = None
    if store is not None and len(node.inputs) >= 2:
        if node.inputs[0].producer_node:
            facts_target = store.get_node_output(node.inputs[0].producer_node, node.inputs[0].output)
        if node.inputs[1].producer_node:
            facts_cutter = store.get_node_output(node.inputs[1].producer_node, node.inputs[1].output)

    if facts_target is not None:
        facts = facts_target.model_copy(deep=True)
        facts.value_id = _make_value_id(node)
        facts.producer_node = node.id
        facts.derived_from = [facts_target.value_id]
        facts.traits.append("modified_by_boolean_cut")
    else:
        facts = ShapeFacts(
            value_id=_make_value_id(node),
            component_id=component_id,
            producer_node=node.id,
            notes=["no target facts — cannot evaluate boolean_cut"],
        )
        return facts

    if facts_cutter is not None:
        facts.extra["cutter_node_id"] = facts_cutter.producer_node or ""
        facts.notes.append(f"cutter: node {facts_cutter.producer_node}")

        # Check if cutter bbox clearly doesn't intersect target
        if _bboxes_disjoint(facts_target.bbox, facts_cutter.bbox):
            facts.notes.append(
                "WARNING: cutter bbox does not intersect target bbox — "
                "boolean_cut may be a no-op"
            )
        # Check if cutter bbox completely swallows target
        if _bbox_contains(facts_cutter.bbox, facts_target.bbox):
            facts.notes.append(
                "WARNING: cutter bbox fully contains target bbox — "
                "boolean_cut may remove entire body"
            )

    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# BBox comparison helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _bboxes_disjoint(a: BBoxFacts, b: BBoxFacts) -> bool:
    """Return True if bboxes a and b are clearly disjoint."""
    for axis in ("x", "y", "z"):
        a_min = getattr(a, f"{axis}min_mm").value
        a_max = getattr(a, f"{axis}max_mm").value
        b_min = getattr(b, f"{axis}min_mm").value
        b_max = getattr(b, f"{axis}max_mm").value
        if None in (a_min, a_max, b_min, b_max):
            return False  # unknown → can't confirm disjoint
        if a_max < b_min or b_max < a_min:
            return True
    return False


def _bbox_contains(outer: BBoxFacts, inner: BBoxFacts) -> bool:
    """Return True if bbox 'outer' fully contains bbox 'inner'."""
    for axis in ("x", "y", "z"):
        o_min = getattr(outer, f"{axis}min_mm").value
        o_max = getattr(outer, f"{axis}max_mm").value
        i_min = getattr(inner, f"{axis}min_mm").value
        i_max = getattr(inner, f"{axis}max_mm").value
        if None in (o_min, o_max, i_min, i_max):
            return False  # unknown → can't confirm
        if o_min > i_min or o_max < i_max:
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Rule registry — maps (dialect, op) → rule function
# ═══════════════════════════════════════════════════════════════════════════════


FACT_RULES: dict[tuple[str, str], Callable[..., ShapeFacts]] = {
    ("axisymmetric", "revolve_profile"): rule_revolve_profile,
    ("axisymmetric", "cut_center_bore"): rule_cut_center_bore,
    ("axisymmetric", "cut_circular_hole_pattern"): rule_cut_circular_hole_pattern,
    ("axisymmetric", "cut_annular_groove"): rule_cut_annular_groove,
    ("sketch_extrude", "extrude_rectangle"): rule_extrude_rectangle,
    ("composition", "translate_solid"): rule_translate_solid,
    ("composition", "boolean_union"): rule_boolean_union,
    ("composition", "boolean_cut"): rule_boolean_cut,
}


def get_fact_rule(dialect: str, op: str):
    """Look up a fact derivation rule by (dialect, op) key.

    Returns None if no rule is registered for this op.
    """
    return FACT_RULES.get((dialect, op))
