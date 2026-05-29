"""Axisymmetric base runner — executes axisymmetric feature graphs via CadQuery.

This runner calls registered operation handlers. It NEVER accepts LLM-generated
CadQuery code. All geometry comes from parameterized operation handlers.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from seekflow_engineering_tools.generative_cad.base import OperationDefinition
from seekflow_engineering_tools.generative_cad.bases.axisymmetric.contract import (
    AXISYMMETRIC_CONTRACT,
)
from seekflow_engineering_tools.generative_cad.bases.axisymmetric.manifest import (
    AXISYMMETRIC_MANIFEST,
)
from seekflow_engineering_tools.generative_cad.bases.axisymmetric.models import (
    ApplySafeChamferParams,
    CutAnnularGrooveParams,
    CutCenterBoreParams,
    CutCircularHolePatternParams,
    CutRimSlotPatternParams,
    RevolveProfileParams,
    SlotProfileStation,
    RimSlotProfile,
    ProfileStation,
)
from seekflow_engineering_tools.generative_cad.bases.axisymmetric.preflight import (
    AXISYMMETRIC_PREFLIGHT_HANDLERS,
)


class AxisymmetricBase:
    """Axisymmetric grammar base — rotationally symmetric solids."""

    base_id = "axisymmetric_base"
    version = "0.1.0"
    phase_order = (
        "base_solid",
        "primary_cut",
        "annular_detail",
        "pattern_cut",
        "rim_detail",
        "edge_treatment",
        "cleanup",
    )

    operation_definitions: dict[str, OperationDefinition] = {
        "revolve_profile": OperationDefinition(
            op="revolve_profile",
            phase="base_solid",
            params_model=RevolveProfileParams,
            description="Create a rotational solid from radial-axial profile stations.",
        ),
        "cut_center_bore": OperationDefinition(
            op="cut_center_bore",
            phase="primary_cut",
            params_model=CutCenterBoreParams,
            description="Cut a coaxial cylindrical bore through the center.",
        ),
        "cut_annular_groove": OperationDefinition(
            op="cut_annular_groove",
            phase="annular_detail",
            params_model=CutAnnularGrooveParams,
            description="Cut an annular groove on front or rear face.",
        ),
        "cut_circular_hole_pattern": OperationDefinition(
            op="cut_circular_hole_pattern",
            phase="pattern_cut",
            params_model=CutCircularHolePatternParams,
            description="Cut a circular pattern of through holes along the Z axis.",
        ),
        "cut_rim_slot_pattern": OperationDefinition(
            op="cut_rim_slot_pattern",
            phase="rim_detail",
            params_model=CutRimSlotPatternParams,
            description="Cut a circular pattern of slots at the outer rim.",
        ),
        "apply_safe_chamfer": OperationDefinition(
            op="apply_safe_chamfer",
            phase="edge_treatment",
            params_model=ApplySafeChamferParams,
            description="Apply a chamfer to all external edges.",
            optional=True,
        ),
    }

    _preflight_handlers = AXISYMMETRIC_PREFLIGHT_HANDLERS

    # ── Public API ──

    def export_manifest(self) -> dict[str, Any]:
        return dict(AXISYMMETRIC_MANIFEST)

    def export_contract(self) -> dict[str, Any]:
        return dict(AXISYMMETRIC_CONTRACT)

    def validate_semantics(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
        """Semantic validation: at least one base_solid node must exist."""
        issues: list[dict[str, Any]] = []
        nodes = graph.get("nodes", [])
        has_base_solid = any(n.get("phase") == "base_solid" for n in nodes)
        if not has_base_solid:
            issues.append({
                "code": "missing_base_solid",
                "message": "Feature graph must contain at least one base_solid node.",
                "severity": "error",
            })
        return issues

    def preflight(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
        """Run geometry preflight for all nodes."""
        issues: list[dict[str, Any]] = []
        nodes = graph.get("nodes", [])
        for node in nodes:
            op = node.get("op", "")
            handler = self._preflight_handlers.get(op)
            if handler is not None:
                try:
                    issues.extend(handler(node, nodes))
                except Exception as exc:
                    issues.append({
                        "code": "preflight_error",
                        "message": f"Preflight for node {node.get('id', '?')!r} op {op!r}: {exc}",
                        "node_id": node.get("id"),
                        "severity": "error",
                    })
        return issues

    def run(self, graph: dict[str, Any], context) -> Any:
        """Execute the feature graph via CadQuery operation handlers.

        Returns GenerativeRunResult.
        """
        from seekflow_engineering_tools.generative_cad.runner import (
            GenerativeRunResult,
        )

        import cadquery as cq

        nodes = graph.get("nodes", [])
        if not nodes:
            return GenerativeRunResult(ok=False, error="Feature graph has no nodes")

        # Sort nodes by phase order then by depends_on
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        nodes_sorted = sorted(
            nodes,
            key=lambda n: (phase_rank.get(n.get("phase", ""), 999), len(n.get("depends_on", []))),
        )

        body: cq.Workplane | None = None
        warnings: list[str] = list(context.warnings)
        degraded: list[dict] = list(context.degraded_features)
        metrics: list[dict] = list(context.operation_metrics)
        node_results: dict[str, cq.Workplane] = {}

        for node in nodes_sorted:
            op = node.get("op", "")
            node_id = node.get("id", "?")
            params = node.get("params", {})
            required = node.get("required", True)
            degradation = node.get("degradation_policy", "fail")

            try:
                if op == "revolve_profile":
                    body = _op_revolve_profile(params)
                    node_results[node_id] = body
                elif op == "cut_center_bore":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body to cut from"
                        )
                    body = _op_cut_center_bore(body, params)
                elif op == "cut_annular_groove":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body to cut from"
                        )
                    body = _op_cut_annular_groove(body, params)
                elif op == "cut_circular_hole_pattern":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body to cut from"
                        )
                    body = _op_cut_circular_hole_pattern(body, params)
                elif op == "cut_rim_slot_pattern":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body to cut from"
                        )
                    body = _op_cut_rim_slot_pattern(body, params)
                elif op == "apply_safe_chamfer":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body to chamfer"
                        )
                    body = _op_apply_safe_chamfer(body, params)
                else:
                    # Unknown op — fail closed
                    return GenerativeRunResult(
                        ok=False, error=f"Unknown op {op!r} for axisymmetric_base"
                    )

                metrics.append({
                    "node_id": node_id,
                    "op": op,
                    "status": "ok",
                })

            except Exception as exc:
                if not required and degradation == "may_skip_with_warning":
                    warnings.append(f"Optional node {node_id!r} ({op}) skipped: {exc}")
                    degraded.append({"node_id": node_id, "op": op, "reason": str(exc)})
                    metrics.append({
                        "node_id": node_id, "op": op, "status": "degraded", "reason": str(exc),
                    })
                    continue
                return GenerativeRunResult(
                    ok=False,
                    error=f"Node {node_id!r} ({op}) failed: {exc}",
                    warnings=warnings,
                    degraded_features=degraded,
                    operation_metrics=metrics,
                )

        if body is None:
            return GenerativeRunResult(ok=False, error="No body was produced")

        # Export STEP
        try:
            cq.exporters.export(body, str(context.out_step))
        except Exception as exc:
            return GenerativeRunResult(
                ok=False,
                error=f"STEP export failed: {exc}",
                warnings=warnings,
                operation_metrics=metrics,
            )

        # Build metadata
        metadata = _build_axisymmetric_metadata(graph, warnings, degraded, metrics)

        try:
            context.metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            return GenerativeRunResult(
                ok=False,
                error=f"Metadata write failed: {exc}",
                warnings=warnings,
                operation_metrics=metrics,
            )

        return GenerativeRunResult(
            ok=True,
            step_path=context.out_step,
            metadata=metadata,
            warnings=warnings,
            degraded_features=degraded,
            operation_metrics=metrics,
        )


# ── Operation Handlers ──

def _op_revolve_profile(params: dict) -> Any:
    """Create axisymmetric body by revolving a profile around Z axis."""
    import cadquery as cq
    import math

    stations = params.get("profile_stations", [])
    if len(stations) < 2:
        raise ValueError("Need at least 2 profile stations")

    # Build a 2D wire profile in RZ plane and revolve
    pts_2d: list[tuple[float, float]] = []
    for s in stations:
        r = float(s["r_mm"])
        z_front = float(s.get("z_front_mm", 0))
        z_rear = float(s.get("z_rear_mm", 0))
        # Each station defines a rectangle segment in RZ
        pts_2d.append((r, z_front))
        pts_2d.append((r, z_rear))

    if len(pts_2d) < 2:
        raise ValueError("Profile has fewer than 2 points after expansion")

    # Build outer profile — connect points in order
    # Sort by Z then R for a well-defined profile
    pts_2d.sort(key=lambda p: (p[1], p[0]))

    # Create workplane in XZ, draw the profile, and revolve
    result = (
        cq.Workplane("XZ")
        .moveTo(pts_2d[0][0], pts_2d[0][1])
    )

    # Draw outer profile with lines
    for (r, z) in pts_2d[1:]:
        result = result.lineTo(r, z)

    # Close the profile by going to Z axis and back to origin
    last_r, last_z = pts_2d[-1]
    first_r, first_z = pts_2d[0]
    result = result.lineTo(0, last_z).lineTo(0, first_z).close()

    # Revolve around Z
    result = result.revolve(360, (0, 0, 0), (0, 0, 1))

    return result


def _op_cut_center_bore(body: Any, params: dict) -> Any:
    """Cut a center bore hole."""
    import cadquery as cq

    dia = float(params.get("diameter_mm", 0))
    if dia <= 0:
        raise ValueError("diameter_mm must be positive")

    # Find bounding box to determine bore length
    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10  # extra margin

    bore = (
        cq.Workplane("XY")
        .circle(dia / 2.0)
        .extrude(z_len, both=True)
    )

    return body.cut(bore)


def _op_cut_annular_groove(body: Any, params: dict) -> Any:
    """Cut an annular groove on front or rear face."""
    import cadquery as cq

    inner = float(params.get("inner_dia_mm", 0))
    outer = float(params.get("outer_dia_mm", 0))
    depth = float(params.get("depth_mm", 0))
    side = params.get("side", "front")

    bb = body.val().BoundingBox()

    if side == "front":
        z_pos = bb.zmax
        extrude_dir = -depth
    else:
        z_pos = bb.zmin
        extrude_dir = depth

    groove = (
        cq.Workplane("XY")
        .workplane(offset=z_pos)
        .circle(outer / 2.0)
        .cutThruAll()
    )

    # Create annular ring by subtracting inner
    inner_cut = (
        cq.Workplane("XY")
        .workplane(offset=z_pos)
        .circle(inner / 2.0)
        .extrude(extrude_dir)
    )

    # Apply the groove
    groove_ring = (
        cq.Workplane("XY")
        .workplane(offset=z_pos)
        .circle(outer / 2.0)
        .circle(inner / 2.0)
        .extrude(extrude_dir)
    )

    return body.cut(groove_ring)


def _op_cut_circular_hole_pattern(body: Any, params: dict) -> Any:
    """Cut a circular pattern of holes."""
    import cadquery as cq
    import math

    count = int(params.get("count", 0))
    pcd = float(params.get("pcd_mm", 0))
    hole_dia = float(params.get("hole_dia_mm", 0))

    if count < 2:
        raise ValueError("count must be >= 2")
    if pcd <= 0 or hole_dia <= 0:
        raise ValueError("pcd_mm and hole_dia_mm must be positive")

    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10

    # Create one hole cutter
    cutter = (
        cq.Workplane("XY")
        .transformed(offset=(pcd / 2.0, 0, 0))
        .circle(hole_dia / 2.0)
        .extrude(z_len, both=True)
    )

    # Pattern it around Z axis
    if count > 1:
        angle_step = 360.0 / count
        # Circular pattern via individual placements
        import cadquery as cq
        cutters = []
        for i in range(count):
            angle = math.radians(i * angle_step)
            x = (pcd / 2.0) * math.cos(angle)
            y = (pcd / 2.0) * math.sin(angle)
            cutters.append(
                cq.Workplane("XY")
                .transformed(offset=(0, 0, 0))
                .workplane()
                .center(x, y)
                .circle(hole_dia / 2.0)
                .extrude(z_len, both=True)
            )
        # Combine all cutters
        combined = cutters[0]
        for c in cutters[1:]:
            combined = combined.union(c)
        return body.cut(combined)

    return body.cut(cutter)


def _op_cut_rim_slot_pattern(body: Any, params: dict) -> Any:
    """Cut a circular pattern of profiled rim slots."""
    import cadquery as cq
    import math

    count = int(params.get("count", 0))
    slot_depth = float(params.get("slot_depth_mm", 0))
    profile = params.get("slot_profile", {})
    stations = profile.get("stations", [])

    if count < 2:
        raise ValueError("count must be >= 2")
    if slot_depth <= 0:
        raise ValueError("slot_depth_mm must be positive")
    if len(stations) < 2:
        raise ValueError("slot profile needs at least 2 stations")

    bb = body.val().BoundingBox()
    outer_r = max(bb.xlen, bb.ylen) / 2.0

    # Build slot profile as a polygon in XY plane at outer rim
    # Each station: depth from rim, half_width
    slot_pts: list[tuple[float, float]] = []
    inner_r = outer_r - slot_depth
    # Start at depth 0 (outer rim)
    slot_pts.append((outer_r, 0))
    for s in stations:
        sd = float(s.get("depth_mm", 0))
        hw = float(s.get("half_width_mm", 0))
        r_at_depth = outer_r - sd
        slot_pts.append((r_at_depth, hw))
        slot_pts.append((r_at_depth, -hw))
    slot_pts.append((outer_r, 0))

    # Build one slot cutter
    slot_wp = cq.Workplane("XY")
    for i, (r, w) in enumerate(slot_pts):
        if i == 0:
            slot_wp = slot_wp.moveTo(r, w)
        else:
            slot_wp = slot_wp.lineTo(r, w)
    slot_wp = slot_wp.close()

    bb_z = bb.zlen + 10
    slot_cutter = slot_wp.extrude(bb_z, both=True)

    # Pattern around Z
    import cadquery as cq
    combined = None
    for i in range(count):
        angle = math.radians(i * 360.0 / count)
        rotated = slot_cutter.rotate((0, 0, 0), (0, 0, 1), math.degrees(angle))
        if combined is None:
            combined = rotated
        else:
            combined = combined.union(rotated)

    if combined is not None:
        return body.cut(combined)
    return body


def _op_apply_safe_chamfer(body: Any, params: dict) -> Any:
    """Apply chamfer to all external edges."""
    distance = float(params.get("distance_mm", 0))
    if distance <= 0:
        raise ValueError("distance_mm must be positive")
    try:
        return body.chamfer(distance)
    except Exception:
        # Chamfer may fail on complex topology — skip gracefully
        return body


def _build_axisymmetric_metadata(
    graph: dict, warnings: list, degraded: list, metrics: list,
) -> dict:
    """Build metadata sidecar for axisymmetric run."""
    import hashlib

    graph_json = json.dumps(graph, sort_keys=True, default=str)
    graph_hash = "sha256:" + hashlib.sha256(graph_json.encode()).hexdigest()

    return {
        "generative_metadata": {
            "metadata_version": "generative_metadata_v1",
            "source_route": "llm_skill_base",
            "trust_level": "reference_geometry",
            "part_name": graph.get("part_name", "unknown"),
            "base_stack": [
                {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
            ],
            "skill_stack": graph.get("skill_stack", []),
            "feature_graph_hash": graph_hash,
            "base_contract_hashes": {
                "axisymmetric_base": "sha256:" + hashlib.sha256(
                    json.dumps(AXISYMMETRIC_CONTRACT, sort_keys=True).encode()
                ).hexdigest(),
            },
            "runner_version": "0.1.0",
            "operation_metrics": metrics,
            "degraded_features": degraded,
            "repair_attempts": 0,
            "warnings": warnings,
            "safety": {
                "non_flight_reference_only": True,
                "not_airworthy": True,
                "not_certified": True,
                "not_for_manufacturing": True,
                "not_for_installation": True,
                "no_structural_validation": True,
                "no_life_prediction": True,
            },
        },
        "build_warnings": warnings,
        "validation": {
            "graph_validation": {},
            "geometry_preflight": {},
            "inspection_validation": {},
        },
    }


AXISYMMETRIC_BASE = AxisymmetricBase()
