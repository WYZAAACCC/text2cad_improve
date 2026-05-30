"""CompositionDialect — transform, pattern, boolean. v0.2.1 fixes."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.composition.contract import COMPOSITION_CONTRACT
from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import (
    handle_boolean_cut, handle_boolean_union,
    handle_circular_pattern_component, handle_linear_pattern_component,
    handle_place_component, handle_rotate_solid, handle_translate_solid,
)
from seekflow_engineering_tools.generative_cad.dialects.composition.manifest import COMPOSITION_MANIFEST
from seekflow_engineering_tools.generative_cad.dialects.composition.params import (
    BooleanCutParams, BooleanUnionParams,
    CircularPatternComponentParams, LinearPatternComponentParams,
    PlaceComponentParams, RotateSolidParams, TranslateSolidParams,
)
from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport


class CompositionDialect:
    dialect_id = "composition"
    version = "0.2.0"
    phase_order = ("transform", "pattern", "boolean", "export")

    _op_version_map = {k: "1.0.0" for k in [
        "translate_solid", "rotate_solid", "place_component",
        "circular_pattern_component", "linear_pattern_component",
        "boolean_union", "boolean_cut",
    ]}

    def manifest(self): return dict(COMPOSITION_MANIFEST)
    def contract(self): return dict(COMPOSITION_CONTRACT)

    def op_specs(self) -> dict[tuple[str, str], OperationSpec]:
        S = ["solid"]; SO = ["solid"]
        return {
            ("translate_solid", "1.0.0"): OperationSpec(
                dialect="composition", op="translate_solid", op_version="1.0.0",
                phase="transform", input_types=S, output_types=SO,
                params_model=TranslateSolidParams, effects=["places_component"],
                postconditions=["valid_solid"], handler=handle_translate_solid,
            ),
            ("rotate_solid", "1.0.0"): OperationSpec(
                dialect="composition", op="rotate_solid", op_version="1.0.0",
                phase="transform", input_types=S, output_types=SO,
                params_model=RotateSolidParams, effects=["places_component"],
                postconditions=["valid_solid"], handler=handle_rotate_solid,
            ),
            ("place_component", "1.0.0"): OperationSpec(
                dialect="composition", op="place_component", op_version="1.0.0",
                phase="transform", input_types=S, output_types=SO,
                params_model=PlaceComponentParams, effects=["places_component"],
                postconditions=["valid_solid"], handler=handle_place_component,
            ),
            # Pattern ops: solid → solid in v0.2 (handlers union copies into single solid)
            ("circular_pattern_component", "1.0.0"): OperationSpec(
                dialect="composition", op="circular_pattern_component", op_version="1.0.0",
                phase="pattern", input_types=S, output_types=SO,
                params_model=CircularPatternComponentParams, effects=["patterns_component"],
                postconditions=["valid_solid"], handler=handle_circular_pattern_component,
            ),
            ("linear_pattern_component", "1.0.0"): OperationSpec(
                dialect="composition", op="linear_pattern_component", op_version="1.0.0",
                phase="pattern", input_types=S, output_types=SO,
                params_model=LinearPatternComponentParams, effects=["patterns_component"],
                postconditions=["valid_solid"], handler=handle_linear_pattern_component,
            ),
            ("boolean_union", "1.0.0"): OperationSpec(
                dialect="composition", op="boolean_union", op_version="1.0.0",
                phase="boolean", input_types=["solid", "solid"], output_types=SO,
                params_model=BooleanUnionParams, effects=["boolean_union"],
                postconditions=["valid_solid"], handler=handle_boolean_union,
            ),
            ("boolean_cut", "1.0.0"): OperationSpec(
                dialect="composition", op="boolean_cut", op_version="1.0.0",
                phase="boolean", input_types=["solid", "solid"], output_types=SO,
                params_model=BooleanCutParams, effects=["boolean_cut"],
                postconditions=["valid_solid"], handler=handle_boolean_cut,
            ),
        }

    def default_op_version(self, op: str) -> str:
        if op not in self._op_version_map:
            raise KeyError(f"unknown op {op!r} in {self.dialect_id!r}")
        return self._op_version_map[op]

    def get_op_spec(self, op: str, op_version: str | None = None) -> OperationSpec:
        v = op_version or self.default_op_version(op)
        key = (op, v)
        specs = self.op_specs()
        if key not in specs:
            raise KeyError(f"unknown op/version: {op!r}/{v!r}")
        return specs[key]

    def validate_component(self, component, nodes):
        issues = []
        stage = "dialect_semantics"
        # 1. component id must be __assembly__
        if component.id != "__assembly__":
            issues.append(ValidationIssue(stage=stage, code="composition_not_assembly",
                message=f"composition dialect only allows __assembly__, got {component.id!r}",
                severity="error", component_id=component.id))
        # 2. all nodes must use composition dialect
        for n in nodes:
            if n.dialect != "composition":
                issues.append(ValidationIssue(stage=stage, code="comp_node_wrong_dialect",
                    message=f"Node {n.id!r} in __assembly__ must use composition dialect, got {n.dialect!r}",
                    severity="error", node_id=n.id, component_id=component.id))
        # 3. final root_node must output body:solid
        if component.root_node:
            root_nodes = [n for n in nodes if n.id == component.root_node]
            if root_nodes:
                rn = root_nodes[0]
                if not any(o.name == "body" and o.type == "solid" for o in rn.outputs):
                    issues.append(ValidationIssue(stage=stage, code="comp_root_no_body",
                        message=f"composition root_node {rn.id!r} must output body:solid",
                        severity="error", node_id=rn.id, component_id=component.id))
        # 4. boolean_cut requires exactly 2 inputs
        for n in nodes:
            if n.op == "boolean_cut" and len(n.inputs) != 2:
                issues.append(ValidationIssue(stage=stage, code="comp_boolean_cut_binary",
                    message=f"boolean_cut requires exactly 2 inputs, got {len(n.inputs)}",
                    severity="error", node_id=n.id, component_id=component.id))
        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)
    def preflight_component(self, component, nodes):
        issues = []
        stage = "geometry_preflight"
        max_instances = 360
        for n in nodes:
            if n.op in ("circular_pattern_component", "linear_pattern_component"):
                count = n.typed_params.get("count") or n.params.get("count", 0)
                if count > max_instances:
                    issues.append(ValidationIssue(stage=stage, code="comp_pattern_count",
                        message=f"pattern count {count} exceeds max {max_instances}",
                        severity="error", node_id=n.id))
            if n.op == "rotate_solid":
                axis = n.typed_params.get("axis_dir") or n.params.get("axis_dir", [0, 0, 0])
                if isinstance(axis, list) and all(v == 0 for v in axis):
                    issues.append(ValidationIssue(stage=stage, code="comp_zero_axis",
                        message="rotate_solid axis_dir must not be zero vector",
                        severity="error", node_id=n.id))
            if n.op == "translate_solid":
                vec = [
                    n.typed_params.get("x_mm") or n.params.get("x_mm", 0),
                    n.typed_params.get("y_mm") or n.params.get("y_mm", 0),
                    n.typed_params.get("z_mm") or n.params.get("z_mm", 0),
                ]
                # Check all are finite numbers
                for v in vec:
                    if not isinstance(v, (int, float)):
                        issues.append(ValidationIssue(stage=stage, code="comp_nonfinite_vec",
                            message=f"translate_solid vector contains non-numeric value: {v}",
                            severity="error", node_id=n.id))
                        break
            if n.op in ("boolean_union", "boolean_cut"):
                if len(n.inputs) < 2:
                    issues.append(ValidationIssue(stage=stage, code="comp_boolean_inputs",
                        message=f"{n.op} requires at least 2 inputs, got {len(n.inputs)}",
                        severity="error", node_id=n.id))
        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)

    def run_component(
        self, component: CanonicalComponent, nodes: list[CanonicalNode], ctx: RuntimeContext,
    ) -> dict[str, str]:
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        node_map = {n.id: n for n in nodes}

        # in_degree only counts assembly-local node-to-node deps (composition nodes only)
        # external component inputs are already ready
        in_degree: dict[str, int] = {}
        for n in nodes:
            deg = 0
            for i in n.inputs:
                if i.producer_node and i.producer_node in node_map:
                    deg += 1
            in_degree[n.id] = deg

        sorted_nodes: list[CanonicalNode] = []
        queue = [n for n in nodes if in_degree[n.id] == 0]
        while queue:
            queue.sort(key=lambda n: (phase_rank.get(n.phase, 999), n.id))
            n = queue.pop(0)
            sorted_nodes.append(n)
            for other in nodes:
                for inp in other.inputs:
                    if inp.producer_node == n.id:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0 and other not in sorted_nodes and other not in queue:
                            queue.append(other)

        # Fail if not all nodes scheduled
        if len(sorted_nodes) != len(nodes):
            unscheduled = [n.id for n in nodes if n not in sorted_nodes]
            raise RuntimeError(f"composition: could not schedule nodes: {unscheduled}")

        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

        final_outputs: dict[str, str] = {}
        for node in sorted_nodes:
            op_spec = self.get_op_spec(node.op, node.op_version)
            try:
                executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
            except Exception as exc:
                if not node.required and node.degradation_policy == "may_skip_with_warning":
                    ctx.warnings.append(f"Optional node {node.id!r} ({node.op}) skipped: {exc}")
                    ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
                    ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "degraded", "reason": str(exc)})
                    continue
                raise
            for name, handle_id in executed.outputs.items():
                final_outputs[name] = handle_id
            ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "ok"})

        if "body" in final_outputs:
            ctx.bind_component_output("__assembly__", "body", final_outputs["body"])
        return final_outputs


COMPOSITION_DIALECT = CompositionDialect()
