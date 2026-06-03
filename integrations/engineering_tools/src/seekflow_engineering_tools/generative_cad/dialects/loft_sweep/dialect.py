"""LoftSweep dialect — sweep, loft, helix for complex 3D geometry."""
from __future__ import annotations
import math
from typing import Any
from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport
from seekflow_engineering_tools.generative_cad.dialects.loft_sweep.handlers import (
    handle_create_sweep_path, handle_sweep_profile, handle_loft_sections, handle_helix_sweep,
)
from seekflow_engineering_tools.generative_cad.dialects.loft_sweep.params import (
    CreateSweepPathParams, SweepProfileParams, LoftSectionsParams, HelixSweepParams,
)


class LoftSweepDialect:
    dialect_id = "loft_sweep"
    version = "0.2.0"
    phase_order = ("path", "sweep", "loft", "helix", "cleanup")

    def __init__(self):
        self._specs: dict[tuple[str, str], OperationSpec] = {
            ("create_sweep_path", "1.0.0"): OperationSpec(
                dialect="loft_sweep", op="create_sweep_path", op_version="1.0.0",
                phase="path", input_types=[], output_types=["curve"],
                params_model=CreateSweepPathParams, effects=["creates_frame"],
                handler=handle_create_sweep_path,
                summary="Define a 3D path from ordered points for sweep operations.",
            ),
            ("sweep_profile", "1.0.0"): OperationSpec(
                dialect="loft_sweep", op="sweep_profile", op_version="1.0.0",
                phase="sweep", input_types=["curve"], output_types=["solid"],
                params_model=SweepProfileParams, effects=["creates_solid"],
                handler=handle_sweep_profile,
                summary="Sweep a 2D profile (circle or rectangle) along a path to create a solid.",
            ),
            ("loft_sections", "1.0.0"): OperationSpec(
                dialect="loft_sweep", op="loft_sections", op_version="1.0.0",
                phase="loft", input_types=[], output_types=["solid"],
                params_model=LoftSectionsParams, effects=["creates_solid"],
                handler=handle_loft_sections,
                summary="Loft between multiple cross-sections at different positions to create a smooth solid.",
            ),
            ("helix_sweep", "1.0.0"): OperationSpec(
                dialect="loft_sweep", op="helix_sweep", op_version="1.0.0",
                phase="helix", input_types=[], output_types=["solid"],
                params_model=HelixSweepParams, effects=["creates_solid"],
                handler=handle_helix_sweep,
                summary="Sweep a profile along a helical path (spring, thread, coil).",
            ),
        }

    def manifest(self): return {"dialect_id": self.dialect_id, "version": self.version, "phase_order": list(self.phase_order), "op_count": len(self._specs)}
    def contract(self): return {"dialect_id": self.dialect_id, "version": self.version, "phase_order": list(self.phase_order), "allowed_ops": {n: {"phase": s.phase, "op_version": s.op_version} for (n, _), s in self._specs.items()}}
    def op_specs(self): return dict(self._specs)
    def default_op_version(self, op): return "1.0.0"
    def get_op_spec(self, op, v=None): return self._specs.get((op, v or "1.0.0"))

    def validate_component(self, component: CanonicalComponent, nodes: list[CanonicalNode]) -> ValidationReport:
        issues = []
        stage = "dialect_semantics"
        node_map = {n.id: n for n in nodes}
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}

        # 1. sweep_profile must consume curve and output solid
        for n in nodes:
            spec = self.get_op_spec(n.op, n.op_version)
            if spec is None:
                continue
            if n.op == "sweep_profile":
                input_types = [i.resolved_type for i in n.inputs]
                if "curve" not in input_types:
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_sweep_must_consume_curve",
                        message=f"sweep_profile node {n.id!r} must consume curve input",
                        severity="error", node_id=n.id, component_id=component.id,
                    ))
                output_types = [o.type for o in n.outputs]
                if "solid" not in output_types:
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_sweep_must_output_solid",
                        message=f"sweep_profile node {n.id!r} must output solid",
                        severity="error", node_id=n.id, component_id=component.id,
                    ))

        # 2. create_sweep_path must precede sweep_profile in phase order
        sweep_nodes = [n for n in nodes if n.op == "sweep_profile"]
        for sn in sweep_nodes:
            for inp in sn.inputs:
                producer = node_map.get(inp.producer_node or "")
                if producer and producer.op == "create_sweep_path":
                    path_rank = phase_rank.get(producer.phase, 99)
                    sweep_rank = phase_rank.get(sn.phase, 0)
                    if path_rank > sweep_rank:
                        issues.append(ValidationIssue(
                            stage=stage, code="ls_path_before_sweep",
                            message=f"create_sweep_path {producer.id!r} (phase={producer.phase}) "
                            f"must precede sweep_profile {sn.id!r} (phase={sn.phase})",
                            severity="error", node_id=sn.id, component_id=component.id,
                        ))

        # 3. component root_node must output body:solid
        if component.root_node:
            root_nodes = [n for n in nodes if n.id == component.root_node]
            if root_nodes:
                rn = root_nodes[0]
                if not any(o.name == "body" and o.type == "solid" for o in rn.outputs):
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_root_no_body_solid",
                        message=f"loft_sweep root_node {rn.id!r} must output body:solid",
                        severity="error", node_id=rn.id, component_id=component.id,
                    ))

        # 4. no multiple disconnected solid roots
        solid_roots = 0
        for n in nodes:
            has_solid_output = any(o.type == "solid" for o in n.outputs)
            is_consumed = any(
                inp.producer_node == n.id for other in nodes for inp in other.inputs
            ) if has_solid_output else True
            if has_solid_output and not is_consumed:
                solid_roots += 1
        if solid_roots > 1:
            issues.append(ValidationIssue(
                stage=stage, code="ls_multiple_solid_roots",
                message=f"loft_sweep component has {solid_roots} disconnected solid outputs",
                severity="warning", component_id=component.id,
            ))

        return ValidationReport(
            ok=not any(i.severity == "error" for i in issues),
            stage=stage, issues=issues,
        )

    @staticmethod
    def _is_finite(x) -> bool:
        return isinstance(x, (int, float)) and math.isfinite(x)

    def preflight_component(self, component: CanonicalComponent, nodes: list[CanonicalNode]) -> ValidationReport:
        issues = []
        stage = "geometry_preflight"
        is_finite = LoftSweepDialect._is_finite

        for n in nodes:
            # ── create_sweep_path ──
            if n.op == "create_sweep_path":
                pts = n.typed_params.get("path_points") or n.params.get("path_points", [])
                if len(pts) < 2:
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_path_points_count",
                        message=f"create_sweep_path needs >= 2 points, got {len(pts)}",
                        severity="error", node_id=n.id,
                    ))
                    continue

                # Check each point coordinate is finite
                for i, pt in enumerate(pts):
                    for axis in ("x_mm", "y_mm", "z_mm", "x", "y", "z"):
                        v = pt.get(axis)
                        if v is not None and not is_finite(v):
                            issues.append(ValidationIssue(
                                stage=stage, code="ls_point_not_finite",
                                message=f"path point {i} {axis}={v} is not finite",
                                severity="error", node_id=n.id,
                            ))

                # Adjacent point distance > 0.1mm
                valid_pts = []
                for pt in pts:
                    x = pt.get("x_mm", pt.get("x", 0))
                    y = pt.get("y_mm", pt.get("y", 0))
                    z = pt.get("z_mm", pt.get("z", 0))
                    if is_finite(x) and is_finite(y) and is_finite(z):
                        valid_pts.append((float(x), float(y), float(z)))

                min_seg = float("inf")
                for i in range(len(valid_pts) - 1):
                    dx = valid_pts[i+1][0] - valid_pts[i][0]
                    dy = valid_pts[i+1][1] - valid_pts[i][1]
                    dz = valid_pts[i+1][2] - valid_pts[i][2]
                    d = math.sqrt(dx*dx + dy*dy + dz*dz)
                    if d < 0.1:
                        issues.append(ValidationIssue(
                            stage=stage, code="ls_adjacent_too_close",
                            message=f"path points {i} and {i+1} are {d:.4f}mm apart (min 0.1mm)",
                            severity="error", node_id=n.id,
                        ))
                    min_seg = min(min_seg, d)

                # Non-adjacent point proximity check
                for i in range(len(valid_pts) - 2):
                    for j in range(i + 2, len(valid_pts)):
                        dx = valid_pts[j][0] - valid_pts[i][0]
                        dy = valid_pts[j][1] - valid_pts[i][1]
                        dz = valid_pts[j][2] - valid_pts[i][2]
                        d = math.sqrt(dx*dx + dy*dy + dz*dz)
                        if d < 0.01:
                            issues.append(ValidationIssue(
                                stage=stage, code="ls_duplicate_points",
                                message=f"path points {i} and {j} are nearly identical ({d:.6f}mm)",
                                severity="error", node_id=n.id,
                            ))

            # ── sweep_profile ──
            if n.op == "sweep_profile":
                radius = n.typed_params.get("radius_mm") or n.params.get("radius_mm", 0)
                if not is_finite(radius) or radius <= 0:
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_sweep_radius",
                        message=f"sweep_profile radius_mm must be > 0 and finite, got {radius}",
                        severity="error", node_id=n.id,
                    ))

                # radius_mm < shortest_segment * 0.45 (curvature safety)
                # Find the associated path node to get segment lengths
                for inp in n.inputs:
                    producer_id = inp.producer_node
                    if producer_id:
                        path_node = next((nn for nn in nodes if nn.id == producer_id), None)
                        if path_node and path_node.op == "create_sweep_path":
                            pts = path_node.typed_params.get("path_points") or path_node.params.get("path_points", [])
                            valid_pts = []
                            for pt in pts:
                                x = pt.get("x_mm", pt.get("x", 0))
                                y = pt.get("y_mm", pt.get("y", 0))
                                z = pt.get("z_mm", pt.get("z", 0))
                                if is_finite(x) and is_finite(y) and is_finite(z):
                                    valid_pts.append((float(x), float(y), float(z)))
                            if len(valid_pts) >= 2 and is_finite(radius) and radius > 0:
                                shortest = float("inf")
                                for i in range(len(valid_pts) - 1):
                                    dx = valid_pts[i+1][0] - valid_pts[i][0]
                                    dy = valid_pts[i+1][1] - valid_pts[i][1]
                                    dz = valid_pts[i+1][2] - valid_pts[i][2]
                                    d = math.sqrt(dx*dx + dy*dy + dz*dz)
                                    shortest = min(shortest, d)
                                if shortest < float("inf") and radius >= shortest * 0.45:
                                    issues.append(ValidationIssue(
                                        stage=stage, code="ls_sweep_self_intersection_risk",
                                        message=f"sweep radius ({radius:.1f}mm) >= 0.45 * "
                                        f"shortest segment ({shortest:.1f}mm). May self-intersect.",
                                        severity="warning", node_id=n.id,
                                    ))

            # ── helix_sweep ──
            if n.op == "helix_sweep":
                radius = n.typed_params.get("radius_mm") or n.params.get("radius_mm", 0)
                pitch = n.typed_params.get("pitch_mm") or n.params.get("pitch_mm", 0)
                profile_r = n.typed_params.get("profile_radius_mm") or n.params.get("profile_radius_mm", 2)
                if is_finite(radius) and radius <= 0:
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_helix_radius",
                        message=f"helix_sweep radius_mm must be > 0, got {radius}",
                        severity="error", node_id=n.id,
                    ))
                if is_finite(pitch) and pitch <= 0:
                    issues.append(ValidationIssue(
                        stage=stage, code="ls_helix_pitch",
                        message=f"helix_sweep pitch_mm must be > 0, got {pitch}",
                        severity="error", node_id=n.id,
                    ))
                # Self-intersection: profile_r must be < 0.45 * min_curvature_radius
                if is_finite(pitch) and pitch > 0 and is_finite(profile_r) and profile_r > 0:
                    min_curvature_radius = pitch / (2 * math.pi)
                    if profile_r >= min_curvature_radius * 0.45:
                        issues.append(ValidationIssue(
                            stage=stage, code="ls_helix_self_intersection",
                            message=f"helix_sweep profile_radius_mm ({profile_r:.1f}) >= "
                            f"0.45 * min curvature radius ({min_curvature_radius:.1f}). "
                            f"Helix will self-intersect. Increase pitch or reduce profile.",
                            severity="error", node_id=n.id,
                        ))

        return ValidationReport(
            ok=not any(i.severity == "error" for i in issues),
            stage=stage, issues=issues,
        )

    def run_component(self, component: CanonicalComponent, nodes: list[CanonicalNode], ctx: RuntimeContext) -> dict[str, str]:
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        outputs = {}
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        for node in sorted(nodes, key=lambda n: (phase_rank.get(n.phase, 99), n.id)):
            op_spec = self.get_op_spec(node.op, node.op_version)
            try:
                executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
                for name, hid in executed.outputs.items():
                    outputs[name] = hid
            except Exception:
                if node.degradation_policy == "may_skip_with_warning":
                    continue
                raise
        root = next((n for n in nodes if n.id == component.root_node), nodes[-1] if nodes else None)
        if root:
            for o in root.outputs:
                try:
                    ctx.bind_component_output(component.id, o.name, ctx.resolve_node_output(root.id, o.name))
                except KeyError:
                    pass
        return outputs


LOFT_SWEEP_DIALECT = LoftSweepDialect()
