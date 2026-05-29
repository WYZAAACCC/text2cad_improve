"""Sketch-extrude base runner — executes prismatic feature graphs via CadQuery."""

from __future__ import annotations

import json
from typing import Any

from seekflow_engineering_tools.generative_cad.base import OperationDefinition
from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.contract import (
    SKETCH_EXTRUDE_CONTRACT,
)
from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.manifest import (
    SKETCH_EXTRUDE_MANIFEST,
)
from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.models import (
    AddRectangularBossParams,
    AddRibParams,
    ApplySafeChamferParams as SEChamferParams,
    ApplySafeFilletParams,
    CutHoleParams,
    CutHolePatternLinearParams,
    CutRectangularPocketParams,
    ExtrudeRectangleParams,
)
from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.preflight import (
    SKETCH_EXTRUDE_PREFLIGHT_HANDLERS,
)


class SketchExtrudeBase:
    """Sketch-extrude grammar base — prismatic machined parts."""

    base_id = "sketch_extrude_base"
    version = "0.1.0"
    phase_order = (
        "base_solid",
        "primary_cut",
        "hole_pattern",
        "boss_rib",
        "edge_treatment",
        "cleanup",
    )

    operation_definitions: dict[str, OperationDefinition] = {
        "extrude_rectangle": OperationDefinition(
            op="extrude_rectangle",
            phase="base_solid",
            params_model=ExtrudeRectangleParams,
            description="Create a rectangular prism by extruding a 2D rectangle.",
        ),
        "cut_rectangular_pocket": OperationDefinition(
            op="cut_rectangular_pocket",
            phase="primary_cut",
            params_model=CutRectangularPocketParams,
            description="Cut a rectangular pocket into the solid.",
        ),
        "cut_hole": OperationDefinition(
            op="cut_hole",
            phase="primary_cut",
            params_model=CutHoleParams,
            description="Cut a circular hole at a specified position.",
        ),
        "cut_hole_pattern_linear": OperationDefinition(
            op="cut_hole_pattern_linear",
            phase="hole_pattern",
            params_model=CutHolePatternLinearParams,
            description="Cut a rectangular grid pattern of holes.",
        ),
        "add_rectangular_boss": OperationDefinition(
            op="add_rectangular_boss",
            phase="boss_rib",
            params_model=AddRectangularBossParams,
            description="Add a rectangular boss protruding from a face.",
            optional=True,
        ),
        "add_rib": OperationDefinition(
            op="add_rib",
            phase="boss_rib",
            params_model=AddRibParams,
            description="Add a reinforcing rib.",
            optional=True,
        ),
        "apply_safe_fillet": OperationDefinition(
            op="apply_safe_fillet",
            phase="edge_treatment",
            params_model=ApplySafeFilletParams,
            description="Apply a fillet to all external edges.",
            optional=True,
        ),
        "apply_safe_chamfer": OperationDefinition(
            op="apply_safe_chamfer",
            phase="edge_treatment",
            params_model=SEChamferParams,
            description="Apply a chamfer to all external edges.",
            optional=True,
        ),
    }

    _preflight_handlers = SKETCH_EXTRUDE_PREFLIGHT_HANDLERS

    def export_manifest(self) -> dict[str, Any]:
        return dict(SKETCH_EXTRUDE_MANIFEST)

    def export_contract(self) -> dict[str, Any]:
        return dict(SKETCH_EXTRUDE_CONTRACT)

    def validate_semantics(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
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
        """Execute the feature graph via CadQuery operation handlers."""
        from seekflow_engineering_tools.generative_cad.runner import GenerativeRunResult

        import cadquery as cq

        nodes = graph.get("nodes", [])
        if not nodes:
            return GenerativeRunResult(ok=False, error="Feature graph has no nodes")

        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        nodes_sorted = sorted(
            nodes,
            key=lambda n: (phase_rank.get(n.get("phase", ""), 999), len(n.get("depends_on", []))),
        )

        body: cq.Workplane | None = None
        warnings: list[str] = list(context.warnings)
        degraded: list[dict] = list(context.degraded_features)
        metrics: list[dict] = list(context.operation_metrics)

        for node in nodes_sorted:
            op = node.get("op", "")
            node_id = node.get("id", "?")
            params = node.get("params", {})
            required = node.get("required", True)
            degradation = node.get("degradation_policy", "fail")

            try:
                if op == "extrude_rectangle":
                    body = _op_extrude_rectangle(params)
                elif op == "cut_rectangular_pocket":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_cut_rectangular_pocket(body, params)
                elif op == "cut_hole":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_cut_hole(body, params)
                elif op == "cut_hole_pattern_linear":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_cut_hole_pattern_linear(body, params)
                elif op == "add_rectangular_boss":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_add_rectangular_boss(body, params)
                elif op == "add_rib":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_add_rib(body, params)
                elif op == "apply_safe_fillet":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_apply_safe_fillet(body, params)
                elif op == "apply_safe_chamfer":
                    if body is None:
                        return GenerativeRunResult(
                            ok=False, error=f"Node {node_id!r}: no base body"
                        )
                    body = _op_apply_safe_chamfer(body, params)
                else:
                    return GenerativeRunResult(
                        ok=False, error=f"Unknown op {op!r} for sketch_extrude_base"
                    )

                metrics.append({"node_id": node_id, "op": op, "status": "ok"})

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
                ok=False, error=f"STEP export failed: {exc}",
                warnings=warnings, operation_metrics=metrics,
            )

        metadata = _build_se_metadata(graph, warnings, degraded, metrics)

        try:
            context.metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            return GenerativeRunResult(
                ok=False, error=f"Metadata write failed: {exc}",
                warnings=warnings, operation_metrics=metrics,
            )

        return GenerativeRunResult(
            ok=True, step_path=context.out_step, metadata=metadata,
            warnings=warnings, degraded_features=degraded, operation_metrics=metrics,
        )


# ── Operation Handlers ──

def _op_extrude_rectangle(params: dict) -> Any:
    import cadquery as cq

    w = float(params["width_mm"])
    h = float(params["height_mm"])
    d = float(params["depth_mm"])
    plane = params.get("plane", "XY")
    centered = params.get("centered", True)
    direction = params.get("direction", "+")

    wp = cq.Workplane(plane)
    if centered:
        wp = wp.center(0, 0)
    rect = wp.rect(w, h)
    if direction == "-":
        d = -d
    return rect.extrude(d)


def _op_cut_rectangular_pocket(body: Any, params: dict) -> Any:
    import cadquery as cq

    w = float(params["width_mm"])
    h = float(params["height_mm"])
    d = float(params["depth_mm"])
    plane = params.get("plane", "XY")
    centered = params.get("centered", True)

    cutter = (
        cq.Workplane(plane)
        .rect(w, h)
        .extrude(-d)
    )
    return body.cut(cutter)


def _op_cut_hole(body: Any, params: dict) -> Any:
    import cadquery as cq

    dia = float(params["diameter_mm"])
    pos = params.get("position_mm", [0, 0, 0])
    through = params.get("through_all", True)

    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10

    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    cutter = (
        cq.Workplane("XY")
        .center(x, y)
        .circle(dia / 2.0)
        .extrude(z_len, both=True)
    )
    return body.cut(cutter)


def _op_cut_hole_pattern_linear(body: Any, params: dict) -> Any:
    import cadquery as cq

    dia = float(params["hole_dia_mm"])
    cx = int(params["count_x"])
    cy = int(params["count_y"])
    sx = float(params["spacing_x_mm"])
    sy = float(params["spacing_y_mm"])

    bb = body.val().BoundingBox()
    z_len = bb.zlen + 10

    combined = None
    for ix in range(cx):
        for iy in range(cy):
            x_off = (ix - (cx - 1) / 2.0) * sx
            y_off = (iy - (cy - 1) / 2.0) * sy
            cutter = (
                cq.Workplane("XY")
                .center(x_off, y_off)
                .circle(dia / 2.0)
                .extrude(z_len, both=True)
            )
            if combined is None:
                combined = cutter
            else:
                combined = combined.union(cutter)

    if combined is not None:
        return body.cut(combined)
    return body


def _op_add_rectangular_boss(body: Any, params: dict) -> Any:
    import cadquery as cq

    w = float(params["width_mm"])
    h = float(params["height_mm"])
    d = float(params["depth_mm"])
    pos = params.get("position_mm", [0, 0, 0])
    centered = params.get("centered", True)

    x, y = pos[0], pos[1] if len(pos) > 1 else 0
    boss = (
        cq.Workplane("XY")
        .center(x, y)
        .rect(w, h)
        .extrude(d)
    )
    return body.union(boss)


def _op_add_rib(body: Any, params: dict) -> Any:
    import cadquery as cq

    t = float(params["thickness_mm"])
    h = float(params["height_mm"])
    length = float(params["length_mm"])
    pos = params.get("position_mm", [0, 0, 0])
    direction = params.get("direction", "X")

    x, y = pos[0], pos[1] if len(pos) > 1 else 0

    if direction == "X":
        rib = (
            cq.Workplane("YZ")
            .center(y, 0)
            .rect(t, h)
            .extrude(length)
        )
    else:
        rib = (
            cq.Workplane("XZ")
            .center(x, 0)
            .rect(t, h)
            .extrude(length)
        )

    return body.union(rib)


def _op_apply_safe_fillet(body: Any, params: dict) -> Any:
    r = float(params.get("radius_mm", 0))
    if r <= 0:
        return body
    try:
        return body.fillet(r)
    except Exception:
        return body


def _op_apply_safe_chamfer(body: Any, params: dict) -> Any:
    d = float(params.get("distance_mm", 0))
    if d <= 0:
        return body
    try:
        return body.chamfer(d)
    except Exception:
        return body


def _build_se_metadata(
    graph: dict, warnings: list, degraded: list, metrics: list,
) -> dict:
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
                {"base_id": "sketch_extrude_base", "base_version": "0.1.0"}
            ],
            "skill_stack": graph.get("skill_stack", []),
            "feature_graph_hash": graph_hash,
            "base_contract_hashes": {
                "sketch_extrude_base": "sha256:" + hashlib.sha256(
                    json.dumps(SKETCH_EXTRUDE_CONTRACT, sort_keys=True).encode()
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


SKETCH_EXTRUDE_BASE = SketchExtrudeBase()
