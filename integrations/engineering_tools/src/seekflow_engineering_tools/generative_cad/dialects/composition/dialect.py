"""CompositionDialect — transform, pattern, boolean. Cannot create geometry."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.composition.contract import (
    COMPOSITION_CONTRACT,
)
from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import (
    handle_boolean_cut,
    handle_boolean_union,
    handle_circular_pattern_component,
    handle_linear_pattern_component,
    handle_place_component,
    handle_rotate_solid,
    handle_translate_solid,
)
from seekflow_engineering_tools.generative_cad.dialects.composition.manifest import (
    COMPOSITION_MANIFEST,
)
from seekflow_engineering_tools.generative_cad.dialects.composition.params import (
    BooleanCutParams,
    BooleanUnionParams,
    CircularPatternComponentParams,
    LinearPatternComponentParams,
    PlaceComponentParams,
    RotateSolidParams,
    TranslateSolidParams,
)
from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


class CompositionDialect:
    dialect_id = "composition"
    version = "0.2.0"
    phase_order = ("transform", "pattern", "boolean", "export")

    _op_version_map: dict[str, str] = {
        "translate_solid": "1.0.0",
        "rotate_solid": "1.0.0",
        "place_component": "1.0.0",
        "circular_pattern_component": "1.0.0",
        "linear_pattern_component": "1.0.0",
        "boolean_union": "1.0.0",
        "boolean_cut": "1.0.0",
    }

    def manifest(self) -> dict[str, Any]:
        return dict(COMPOSITION_MANIFEST)

    def contract(self) -> dict[str, Any]:
        return dict(COMPOSITION_CONTRACT)

    def op_specs(self) -> dict[tuple[str, str], OperationSpec]:
        solid_input = ["solid"]
        solid_output = ["solid"]
        return {
            ("translate_solid", "1.0.0"): OperationSpec(
                dialect="composition", op="translate_solid", op_version="1.0.0",
                phase="transform", input_types=solid_input, output_types=solid_output,
                params_model=TranslateSolidParams,
                effects=["places_component"],
                postconditions=["valid_solid"],
                handler=handle_translate_solid,
            ),
            ("rotate_solid", "1.0.0"): OperationSpec(
                dialect="composition", op="rotate_solid", op_version="1.0.0",
                phase="transform", input_types=solid_input, output_types=solid_output,
                params_model=RotateSolidParams,
                effects=["places_component"],
                postconditions=["valid_solid"],
                handler=handle_rotate_solid,
            ),
            ("place_component", "1.0.0"): OperationSpec(
                dialect="composition", op="place_component", op_version="1.0.0",
                phase="transform", input_types=solid_input, output_types=solid_output,
                params_model=PlaceComponentParams,
                effects=["places_component"],
                postconditions=["valid_solid"],
                handler=handle_place_component,
            ),
            ("circular_pattern_component", "1.0.0"): OperationSpec(
                dialect="composition", op="circular_pattern_component", op_version="1.0.0",
                phase="pattern", input_types=["solid_array", "solid"], output_types=["solid_array"],
                params_model=CircularPatternComponentParams,
                effects=["patterns_component"],
                postconditions=["valid_solid_array"],
                handler=handle_circular_pattern_component,
            ),
            ("linear_pattern_component", "1.0.0"): OperationSpec(
                dialect="composition", op="linear_pattern_component", op_version="1.0.0",
                phase="pattern", input_types=["solid_array", "solid"], output_types=["solid_array"],
                params_model=LinearPatternComponentParams,
                effects=["patterns_component"],
                postconditions=["valid_solid_array"],
                handler=handle_linear_pattern_component,
            ),
            ("boolean_union", "1.0.0"): OperationSpec(
                dialect="composition", op="boolean_union", op_version="1.0.0",
                phase="boolean", input_types=["solid", "solid"], output_types=["solid"],
                params_model=BooleanUnionParams,
                effects=["boolean_union"],
                postconditions=["valid_solid", "single_body"],
                handler=handle_boolean_union,
            ),
            ("boolean_cut", "1.0.0"): OperationSpec(
                dialect="composition", op="boolean_cut", op_version="1.0.0",
                phase="boolean", input_types=["solid", "solid"], output_types=["solid"],
                params_model=BooleanCutParams,
                effects=["boolean_cut"],
                postconditions=["valid_solid", "single_body"],
                handler=handle_boolean_cut,
            ),
        }

    def default_op_version(self, op: str) -> str:
        if op not in self._op_version_map:
            raise KeyError(f"unknown op {op!r} in dialect {self.dialect_id!r}")
        return self._op_version_map[op]

    def get_op_spec(self, op: str, op_version: str | None = None) -> OperationSpec:
        version = op_version or self.default_op_version(op)
        key = (op, version)
        specs = self.op_specs()
        if key not in specs:
            raise KeyError(f"unknown op/version: {op!r}/{version!r}")
        return specs[key]

    def validate_component(
        self, component: CanonicalComponent, nodes: list[CanonicalNode],
    ) -> ValidationReport:
        return ValidationReport.ok_report("dialect_semantics")

    def preflight_component(
        self, component: CanonicalComponent, nodes: list[CanonicalNode],
    ) -> ValidationReport:
        return ValidationReport.ok_report("preflight")

    def run_component(
        self, component: CanonicalComponent, nodes: list[CanonicalNode], ctx: RuntimeContext,
    ) -> dict[str, str]:
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        node_map = {n.id: n for n in nodes}

        in_degree: dict[str, int] = {n.id: sum(
            1 for i in n.inputs
            if (i.producer_node and i.producer_node in node_map)
            or (i.producer_component and i.producer_component in ctx.component_outputs)
        ) for n in nodes}

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

        final_outputs: dict[str, str] = {}
        for node in sorted_nodes:
            op_spec = self.get_op_spec(node.op, node.op_version)
            outputs = op_spec.handler(node, ctx)
            for name, handle_id in outputs.items():
                ctx.bind_node_output(node.id, name, handle_id)
                final_outputs[name] = handle_id
            ctx.operation_metrics.append({
                "node_id": node.id, "op": node.op, "status": "ok",
            })

        # Bind final body for assembly
        if "body" in final_outputs:
            ctx.bind_component_output("__assembly__", "body", final_outputs["body"])

        return final_outputs


COMPOSITION_DIALECT = CompositionDialect()
