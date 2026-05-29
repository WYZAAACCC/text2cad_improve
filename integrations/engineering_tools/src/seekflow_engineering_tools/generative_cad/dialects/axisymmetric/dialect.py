"""AxisymmetricDialect — v0.6: finite checks, envelope tracking, strengthened preflight."""

from __future__ import annotations

import math
from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.contract import AXISYMMETRIC_CONTRACT
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.handlers import (
    handle_apply_safe_chamfer, handle_cut_annular_groove, handle_cut_center_bore,
    handle_cut_circular_hole_pattern, handle_cut_rim_slot_pattern, handle_revolve_profile,
)
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.manifest import AXISYMMETRIC_MANIFEST
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.params import (
    ApplySafeChamferParams, CutAnnularGrooveParams, CutCenterBoreParams,
    CutCircularHolePatternParams, CutRimSlotPatternParams, RevolveProfileParams,
)
from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport


class AxisymmetricDialect:
    dialect_id = "axisymmetric"
    version = "0.2.0"
    phase_order = ("base_solid", "primary_cut", "annular_detail", "pattern_cut", "rim_detail", "edge_treatment", "cleanup")

    _op_version_map = {k: "1.0.0" for k in [
        "revolve_profile", "cut_center_bore", "cut_annular_groove",
        "cut_circular_hole_pattern", "cut_rim_slot_pattern", "apply_safe_chamfer",
    ]}

    def manifest(self): return dict(AXISYMMETRIC_MANIFEST)
    def contract(self): return dict(AXISYMMETRIC_CONTRACT)

    def op_specs(self) -> dict[tuple[str, str], OperationSpec]:
        return {
            ("revolve_profile", "1.0.0"): OperationSpec(dialect="axisymmetric", op="revolve_profile", op_version="1.0.0", phase="base_solid", input_types=[], output_types=["solid", "frame"], params_model=RevolveProfileParams, effects=["creates_solid", "creates_frame"], postconditions=["valid_solid"], handler=handle_revolve_profile),
            ("cut_center_bore", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_center_bore", op_version="1.0.0", phase="primary_cut", input_types=["solid"], output_types=["solid"], params_model=CutCenterBoreParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_center_bore),
            ("cut_annular_groove", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_annular_groove", op_version="1.0.0", phase="annular_detail", input_types=["solid"], output_types=["solid"], params_model=CutAnnularGrooveParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_annular_groove),
            ("cut_circular_hole_pattern", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_circular_hole_pattern", op_version="1.0.0", phase="pattern_cut", input_types=["solid"], output_types=["solid"], params_model=CutCircularHolePatternParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_circular_hole_pattern),
            ("cut_rim_slot_pattern", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_rim_slot_pattern", op_version="1.0.0", phase="rim_detail", input_types=["solid"], output_types=["solid"], params_model=CutRimSlotPatternParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_rim_slot_pattern),
            ("apply_safe_chamfer", "1.0.0"): OperationSpec(dialect="axisymmetric", op="apply_safe_chamfer", op_version="1.0.0", phase="edge_treatment", input_types=["solid"], output_types=["solid"], params_model=ApplySafeChamferParams, effects=["modifies_solid"], postconditions=["valid_solid"], handler=handle_apply_safe_chamfer),
        }

    def default_op_version(self, op): return self._op_version_map[op]
    def get_op_spec(self, op, v=None):
        v = v or self.default_op_version(op)
        key = (op, v); specs = self.op_specs()
        if key not in specs: raise KeyError(f"unknown op/version: {op!r}/{v!r}")
        return specs[key]

    def validate_component(self, component, nodes):
        issues = []
        stage = "dialect_semantics"
        # 1. exactly one base_solid root creation op
        base_solid_nodes = [n for n in nodes if n.phase == "base_solid"]
        if len(base_solid_nodes) != 1:
            issues.append(ValidationIssue(stage=stage, code="axisymmetric_base_solid_count",
                message=f"axisymmetric requires exactly 1 base_solid node, got {len(base_solid_nodes)}",
                severity="error", component_id=component.id))
        # 2. first solid-producing node must be revolve_profile
        solid_creators = [n for n in nodes if n.op == "revolve_profile"]
        for n in solid_creators:
            body_outputs = [o for o in n.outputs if o.name == "body" and o.type == "solid"]
            if not body_outputs:
                issues.append(ValidationIssue(stage=stage, code="revolve_no_body_solid",
                    message=f"revolve_profile node {n.id!r} must output body:solid",
                    severity="error", node_id=n.id, component_id=component.id))
            frame_outputs = [o for o in n.outputs if o.name == "outer_frame" and o.type == "frame"]
            if not frame_outputs:
                issues.append(ValidationIssue(stage=stage, code="revolve_no_outer_frame",
                    message=f"revolve_profile node {n.id!r} must output outer_frame:frame",
                    severity="error", node_id=n.id, component_id=component.id))
        # 3. all cut/modification ops must consume solid and output solid
        for n in nodes:
            if n.phase != "base_solid":
                input_types = [i.resolved_type for i in n.inputs]
                output_types = [o.type for o in n.outputs]
                if "solid" not in input_types and input_types:
                    issues.append(ValidationIssue(stage=stage, code="cut_op_must_consume_solid",
                        message=f"Node {n.id!r} ({n.op}) must consume solid input",
                        severity="error", node_id=n.id, component_id=component.id))
                if not any(t == "solid" for t in output_types):
                    issues.append(ValidationIssue(stage=stage, code="cut_op_must_output_solid",
                        message=f"Node {n.id!r} ({n.op}) must output solid",
                        severity="error", node_id=n.id, component_id=component.id))
        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)
    @staticmethod
    def _is_finite_number(x) -> bool:
        return isinstance(x, (int, float)) and math.isfinite(x)

    def preflight_component(self, component, nodes):
        issues = []
        stage = "geometry_preflight"
        MARGIN = 1.0  # mm
        is_finite = AxisymmetricDialect._is_finite_number

        # ── Envelope tracking ──
        profile_max_radius: float | None = None
        profile_min_radius: float | None = None
        center_bore_radius: float | None = None

        # First pass: gather envelope from revolve_profile
        for n in nodes:
            if n.op == "revolve_profile":
                ps = n.typed_params.get("profile_stations") or n.params.get("profile_stations", [])
                if len(ps) < 2:
                    issues.append(ValidationIssue(stage=stage, code="a001_stations_count",
                        message=f"revolve_profile needs >= 2 stations, got {len(ps)}",
                        severity="error", node_id=n.id))
                max_r = 0.0
                min_r = float("inf")
                for s in ps:
                    r = s.get("r_mm", 0)
                    if not is_finite(r) or r <= 0:
                        issues.append(ValidationIssue(stage=stage, code="a001_radius_non_positive",
                            message=f"revolve_profile station radius must be > 0 and finite, got {r}",
                            severity="error", node_id=n.id))
                    zf = s.get("z_front_mm", 0); zr = s.get("z_rear_mm", 0)
                    if not is_finite(zf) or not is_finite(zr) or zr <= zf:
                        issues.append(ValidationIssue(stage=stage, code="a001_z_order",
                            message=f"z_rear_mm ({zr}) must be > z_front_mm ({zf}) and finite",
                            severity="error", node_id=n.id))
                    if is_finite(r) and r > 0:
                        max_r = max(max_r, r)
                        min_r = min(min_r, r)
                if max_r > 0 and min_r < float("inf") and max_r > min_r:
                    profile_max_radius = max_r
                    profile_min_radius = min_r
                elif max_r <= 0 or min_r <= 0 or max_r <= min_r:
                    issues.append(ValidationIssue(stage=stage, code="a001_radius_range",
                        message=f"max radius ({max_r}) must be > min radius ({min_r})",
                        severity="error", node_id=n.id))

        # Second pass: validate cuts against envelope
        for n in nodes:
            # A002: center bore
            if n.op == "cut_center_bore":
                dia = n.typed_params.get("diameter_mm") or n.params.get("diameter_mm", 0)
                if not is_finite(dia) or dia <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a002_bore_dia",
                        message=f"center bore diameter must be > 0 and finite, got {dia}",
                        severity="error", node_id=n.id))
                elif profile_max_radius is not None and dia / 2 >= profile_max_radius - MARGIN:
                    issues.append(ValidationIssue(stage=stage, code="a002_bore_too_large",
                        message=f"center bore radius ({dia/2}) >= profile max radius ({profile_max_radius}) - margin ({MARGIN})",
                        severity="error", node_id=n.id))
                center_bore_radius = dia / 2 if is_finite(dia) and dia > 0 else None

            # A003: circular hole pattern
            if n.op == "cut_circular_hole_pattern":
                count = n.typed_params.get("count") or n.params.get("count", 0)
                hole_dia = n.typed_params.get("hole_dia_mm") or n.params.get("hole_dia_mm", 0)
                pcd = n.typed_params.get("pcd_mm") or n.params.get("pcd_mm", 0)
                if not is_finite(count) or count < 3:
                    issues.append(ValidationIssue(stage=stage, code="a003_pattern_count",
                        message=f"circular hole pattern count must be >= 3 and finite, got {count}",
                        severity="error", node_id=n.id))
                if not is_finite(hole_dia) or hole_dia <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a003_hole_dia",
                        message=f"hole diameter must be > 0 and finite, got {hole_dia}",
                        severity="error", node_id=n.id))
                if not is_finite(pcd) or pcd <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a003_pcd",
                        message=f"PCD must be > 0 and finite, got {pcd}",
                        severity="error", node_id=n.id))
                # Envelope check: pcd/2 + hole_dia/2 < profile_max_radius - margin
                if profile_max_radius is not None and is_finite(pcd) and pcd > 0 and is_finite(hole_dia) and hole_dia > 0:
                    pcd_radius = pcd / 2
                    hole_radius = hole_dia / 2
                    if pcd_radius + hole_radius >= profile_max_radius - MARGIN:
                        issues.append(ValidationIssue(stage=stage, code="hole_pattern_outside_profile",
                            message=f"hole pattern PCD radius ({pcd_radius}) + hole radius ({hole_radius}) >= profile max ({profile_max_radius}) - margin ({MARGIN})",
                            severity="error", node_id=n.id))
                    if center_bore_radius is not None and pcd_radius - hole_radius <= center_bore_radius + MARGIN:
                        issues.append(ValidationIssue(stage=stage, code="hole_pattern_intersects_center_bore",
                            message=f"hole pattern PCD radius ({pcd_radius}) - hole radius ({hole_radius}) <= bore radius ({center_bore_radius}) + margin ({MARGIN})",
                            severity="error", node_id=n.id))

            # A004: annular groove
            if n.op == "cut_annular_groove":
                inner = n.typed_params.get("inner_dia_mm") or n.params.get("inner_dia_mm", 0)
                outer = n.typed_params.get("outer_dia_mm") or n.params.get("outer_dia_mm", 0)
                if not is_finite(inner) or not is_finite(outer) or inner >= outer:
                    issues.append(ValidationIssue(stage=stage, code="a004_groove_dia",
                        message=f"inner_dia_mm ({inner}) must be < outer_dia_mm ({outer}) and both finite",
                        severity="error", node_id=n.id))
                if profile_max_radius is not None and outer / 2 >= profile_max_radius - MARGIN:
                    issues.append(ValidationIssue(stage=stage, code="a004_groove_outside_profile",
                        message=f"groove outer radius ({outer/2}) >= profile max ({profile_max_radius}) - margin ({MARGIN})",
                        severity="error", node_id=n.id))

        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)

    def run_component(self, component: CanonicalComponent, nodes: list[CanonicalNode], ctx: RuntimeContext) -> dict[str, str]:
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        node_map = {n.id: n for n in nodes}
        in_degree = {n.id: sum(1 for i in n.inputs if i.producer_node and i.producer_node in node_map) for n in nodes}
        sorted_nodes = []; queue = [n for n in nodes if in_degree[n.id] == 0]
        while queue:
            queue.sort(key=lambda n: (phase_rank.get(n.phase, 999), n.id))
            n = queue.pop(0); sorted_nodes.append(n)
            for other in nodes:
                for inp in other.inputs:
                    if inp.producer_node == n.id:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0 and other not in sorted_nodes and other not in queue:
                            queue.append(other)
        if len(sorted_nodes) != len(nodes):
            unscheduled = [n.id for n in nodes if n not in sorted_nodes]
            raise RuntimeError(f"axisymmetric: unscheduled nodes: {unscheduled}")

        final_outputs = {}
        for node in sorted_nodes:
            op_spec = self.get_op_spec(node.op, node.op_version)
            try:
                outputs = op_spec.handler(node, ctx)
            except Exception as exc:
                if not node.required and node.degradation_policy == "may_skip_with_warning":
                    ctx.warnings.append(f"Optional {node.id!r} ({node.op}) skipped: {exc}")
                    ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
                    ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "degraded", "reason": str(exc)})
                    continue
                raise
            for name, hid in outputs.items():
                ctx.bind_node_output(node.id, name, hid); final_outputs[name] = hid
            ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "ok"})
        root = next((n for n in sorted_nodes if n.id == component.root_node), sorted_nodes[-1] if sorted_nodes else None)
        if root:
            for o in root.outputs:
                try: ctx.bind_component_output(component.id, o.name, ctx.resolve_node_output(root.id, o.name))
                except KeyError: pass
        return final_outputs


AXISYMMETRIC_DIALECT = AxisymmetricDialect()
