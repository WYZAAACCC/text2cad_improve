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
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


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
        if not any(n.phase == "base_solid" for n in nodes):
            return ValidationReport.fail("dialect_semantics", "missing_base_solid", "sketch_extrude needs base_solid", component_id=component.id)
        return ValidationReport.ok_report("dialect_semantics")
    def preflight_component(self, component, nodes): return ValidationReport.ok_report("preflight")

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


SKETCH_EXTRUDE_DIALECT = SketchExtrudeDialect()
