"""LoftSweep dialect — sweep, loft, helix for complex 3D geometry."""
from __future__ import annotations
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
        return ValidationReport(ok=True, stage="dialect_semantics")

    def preflight_component(self, component: CanonicalComponent, nodes: list[CanonicalNode]) -> ValidationReport:
        return ValidationReport(ok=True, stage="geometry_preflight")

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
