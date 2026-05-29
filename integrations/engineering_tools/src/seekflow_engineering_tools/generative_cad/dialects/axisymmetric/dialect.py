"""AxisymmetricDialect — v0.2.1: centralized degradation policy, shared resolver."""

from __future__ import annotations

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
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


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
        if not any(n.phase == "base_solid" for n in nodes):
            return ValidationReport.fail("dialect_semantics", "missing_base_solid", "axisymmetric needs base_solid", component_id=component.id)
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
