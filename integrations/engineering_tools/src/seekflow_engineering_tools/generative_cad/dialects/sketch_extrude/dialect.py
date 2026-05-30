"""SketchExtrudeDialect — v0.2.1: centralized degradation, shared resolver."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.contract import SKETCH_EXTRUDE_CONTRACT
from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.handlers import (
    handle_add_rectangular_boss, handle_add_rib, handle_cut_hole,
    handle_cut_hole_pattern_linear, handle_cut_rectangular_pocket,
    handle_extrude_rectangle, handle_se_chamfer, handle_se_fillet,
)
from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.manifest import SKETCH_EXTRUDE_MANIFEST
from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.params import (
    AddRectangularBossParams, AddRibParams, ApplySafeChamferParams, ApplySafeFilletParams,
    CutHoleParams, CutHolePatternLinearParams, CutRectangularPocketParams, ExtrudeRectangleParams,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport


class SketchExtrudeDialect:
    dialect_id = "sketch_extrude"
    version = "0.2.0"
    phase_order = ("base_solid", "primary_cut", "hole_pattern", "boss_rib", "edge_treatment", "cleanup")

    _op_version_map = {k: "1.0.0" for k in [
        "extrude_rectangle", "cut_rectangular_pocket", "cut_hole", "cut_hole_pattern_linear",
        "add_rectangular_boss", "add_rib", "apply_safe_fillet", "apply_safe_chamfer",
    ]}

    def manifest(self): return dict(SKETCH_EXTRUDE_MANIFEST)
    def contract(self): return dict(SKETCH_EXTRUDE_CONTRACT)

    def op_specs(self) -> dict[tuple[str, str], OperationSpec]:
        S = ["solid"]; SO = ["solid"]
        return {
            ("extrude_rectangle", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="extrude_rectangle", op_version="1.0.0", phase="base_solid", input_types=[], output_types=SO, params_model=ExtrudeRectangleParams, effects=["creates_solid"], postconditions=["valid_solid"], handler=handle_extrude_rectangle),
            ("cut_rectangular_pocket", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="cut_rectangular_pocket", op_version="1.0.0", phase="primary_cut", input_types=S, output_types=SO, params_model=CutRectangularPocketParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_rectangular_pocket),
            ("cut_hole", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="cut_hole", op_version="1.0.0", phase="primary_cut", input_types=S, output_types=SO, params_model=CutHoleParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_hole),
            ("cut_hole_pattern_linear", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="cut_hole_pattern_linear", op_version="1.0.0", phase="hole_pattern", input_types=S, output_types=SO, params_model=CutHolePatternLinearParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_hole_pattern_linear),
            ("add_rectangular_boss", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="add_rectangular_boss", op_version="1.0.0", phase="boss_rib", input_types=S, output_types=SO, params_model=AddRectangularBossParams, effects=["adds_material"], postconditions=["valid_solid"], handler=handle_add_rectangular_boss),
            ("add_rib", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="add_rib", op_version="1.0.0", phase="boss_rib", input_types=S, output_types=SO, params_model=AddRibParams, effects=["adds_material"], postconditions=["valid_solid"], handler=handle_add_rib),
            ("apply_safe_fillet", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="apply_safe_fillet", op_version="1.0.0", phase="edge_treatment", input_types=S, output_types=SO, params_model=ApplySafeFilletParams, effects=["modifies_solid"], postconditions=["valid_solid"], handler=handle_se_fillet),
            ("apply_safe_chamfer", "1.0.0"): OperationSpec(dialect="sketch_extrude", op="apply_safe_chamfer", op_version="1.0.0", phase="edge_treatment", input_types=S, output_types=SO, params_model=ApplySafeChamferParams, effects=["modifies_solid"], postconditions=["valid_solid"], handler=handle_se_chamfer),
        }

    def default_op_version(self, op): return self._op_version_map[op]
    def get_op_spec(self, op, v=None):
        v = v or self.default_op_version(op); key = (op, v)
        if key not in self.op_specs(): raise KeyError(f"unknown op/version: {op!r}/{v!r}")
        return self.op_specs()[key]

    def validate_component(self, component, nodes):
        issues = []
        stage = "dialect_semantics"
        # 1. exactly one base_solid creation op
        base_solid_nodes = [n for n in nodes if n.phase == "base_solid"]
        if len(base_solid_nodes) != 1:
            issues.append(ValidationIssue(stage=stage, code="se_base_solid_count",
                message=f"sketch_extrude requires exactly 1 base_solid node, got {len(base_solid_nodes)}",
                severity="error", component_id=component.id))
        # 2. first solid-producing node must be extrude_rectangle
        for n in base_solid_nodes:
            if n.op != "extrude_rectangle":
                issues.append(ValidationIssue(stage=stage, code="se_first_must_be_extrude",
                    message=f"sketch_extrude base_solid node must be extrude_rectangle, got {n.op!r}",
                    severity="error", node_id=n.id, component_id=component.id))
        # 3. pocket/hole/rib/boss ops must consume solid and output solid
        for n in nodes:
            if n.phase != "base_solid":
                output_types = [o.type for o in n.outputs]
                if not any(t == "solid" for t in output_types):
                    issues.append(ValidationIssue(stage=stage, code="se_op_must_output_solid",
                        message=f"Node {n.id!r} ({n.op}) must output solid",
                        severity="error", node_id=n.id, component_id=component.id))
        # 4. root_node must output body:solid
        if component.root_node:
            root_nodes = [n for n in nodes if n.id == component.root_node]
            if root_nodes:
                rn = root_nodes[0]
                if not any(o.name == "body" and o.type == "solid" for o in rn.outputs):
                    issues.append(ValidationIssue(stage=stage, code="se_root_no_body_solid",
                        message=f"sketch_extrude root_node {rn.id!r} must output body:solid",
                        severity="error", node_id=rn.id, component_id=component.id))
        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)
    def preflight_component(self, component, nodes):
        issues = []
        stage = "geometry_preflight"
        MARGIN = 1.0  # mm

        # ── Envelope tracking ──
        base_width: float | None = None
        base_height: float | None = None
        base_depth: float | None = None

        # First pass: gather base envelope
        for n in nodes:
            if n.op == "extrude_rectangle":
                w = n.typed_params.get("width_mm") or n.params.get("width_mm", 0)
                h = n.typed_params.get("height_mm") or n.params.get("height_mm", 0)
                d = n.typed_params.get("depth_mm") or n.params.get("depth_mm", 0)
                if w <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_width",
                        message=f"width_mm must be > 0, got {w}", severity="error", node_id=n.id))
                if h <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_height",
                        message=f"height_mm must be > 0, got {h}", severity="error", node_id=n.id))
                if d <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_depth",
                        message=f"depth_mm must be > 0, got {d}", severity="error", node_id=n.id))
                if w > 0 and h > 0:
                    base_width = w
                    base_height = h
                    base_depth = d if d > 0 else None

        # Second pass: validate features against envelope
        for n in nodes:
            if n.op == "cut_hole":
                dia = n.typed_params.get("diameter_mm") or n.params.get("diameter_mm", 0)
                if dia <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_hole_dia",
                        message=f"hole diameter must be > 0, got {dia}", severity="error", node_id=n.id))
                if base_width is not None and base_height is not None and dia > 0:
                    min_base = min(base_width, base_height)
                    if dia >= min_base - 2 * MARGIN:
                        issues.append(ValidationIssue(stage=stage, code="se_hole_too_large",
                            message=f"hole diameter ({dia}) must be < min(base width, height) ({min_base}) - 2*margin",
                            severity="error", node_id=n.id))

            if n.op == "cut_rectangular_pocket":
                pw = n.typed_params.get("width_mm") or n.params.get("width_mm", 0)
                pd = n.typed_params.get("depth_mm") or n.params.get("depth_mm", 0)
                if pw <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_pocket_width",
                        message=f"pocket width must be > 0, got {pw}", severity="error", node_id=n.id))
                if pd <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_pocket_depth",
                        message=f"pocket depth must be > 0, got {pd}", severity="error", node_id=n.id))
                if base_width is not None and pw > 0 and pw >= base_width:
                    issues.append(ValidationIssue(stage=stage, code="se_pocket_oversized",
                        message=f"pocket width ({pw}) must be < base width ({base_width})",
                        severity="error", node_id=n.id))

            if n.op == "add_rectangular_boss":
                w = n.typed_params.get("width_mm") or n.params.get("width_mm", 0)
                h = n.typed_params.get("height_mm") or n.params.get("height_mm", 0)
                if w <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_boss_width",
                        message=f"boss width must be > 0, got {w}", severity="error", node_id=n.id))
                if h <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_boss_height",
                        message=f"boss height must be > 0, got {h}", severity="error", node_id=n.id))

            if n.op == "add_rib":
                thickness = n.typed_params.get("thickness_mm") or n.params.get("thickness_mm", 0)
                if thickness <= 0:
                    issues.append(ValidationIssue(stage=stage, code="se_rib_thickness",
                        message=f"rib thickness must be > 0, got {thickness}", severity="error", node_id=n.id))

            if n.op == "cut_hole_pattern_linear":
                count = n.typed_params.get("count") or n.params.get("count", 0)
                spacing = n.typed_params.get("spacing_mm") or n.params.get("spacing_mm", 0)
                dia = n.typed_params.get("diameter_mm") or n.params.get("diameter_mm", 0)
                if base_width is not None and count > 0 and spacing > 0 and dia > 0:
                    total_span = (count - 1) * spacing + dia
                    if total_span >= base_width:
                        issues.append(ValidationIssue(stage=stage, code="se_pattern_exceeds_base",
                            message=f"hole pattern span ({total_span}) must be < base width ({base_width})",
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
            raise RuntimeError(f"sketch_extrude: unscheduled nodes: {unscheduled}")

        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

        final_outputs = {}
        for node in sorted_nodes:
            op_spec = self.get_op_spec(node.op, node.op_version)
            try:
                executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
            except Exception as exc:
                if not node.required and node.degradation_policy == "may_skip_with_warning":
                    ctx.warnings.append(f"Optional {node.id!r} ({node.op}) skipped: {exc}")
                    ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
                    ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "degraded", "reason": str(exc)})
                    continue
                raise
            for name, hid in executed.outputs.items():
                final_outputs[name] = hid
            ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "ok"})
        root = next((n for n in sorted_nodes if n.id == component.root_node), sorted_nodes[-1] if sorted_nodes else None)
        if root:
            for o in root.outputs:
                try: ctx.bind_component_output(component.id, o.name, ctx.resolve_node_output(root.id, o.name))
                except KeyError: pass  # postconditions.py independently validates root outputs
        return final_outputs


SKETCH_EXTRUDE_DIALECT = SketchExtrudeDialect()
