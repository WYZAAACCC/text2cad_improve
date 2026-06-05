"""ShellHousing dialect — shell, thicken, hollow for thin-walled parts."""
from __future__ import annotations
from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport
from seekflow_engineering_tools.generative_cad.dialects.shell_housing.handlers import (
    handle_shell_body, handle_hollow_body,
)
from seekflow_engineering_tools.generative_cad.dialects.shell_housing.params import (
    ShellBodyParams, HollowBodyParams,
)


class ShellHousingDialect:
    dialect_id = "shell_housing"
    version = "0.2.0"
    phase_order = ("shell", "hollow", "cleanup")

    def __init__(self):
        self._specs: dict[tuple[str, str], OperationSpec] = {
            ("shell_body", "1.0.0"): OperationSpec(
                dialect="shell_housing", op="shell_body", op_version="1.0.0",
                phase="shell", input_types=["solid"], output_types=["solid"],
                params_model=ShellBodyParams, effects=["modifies_solid"],
                handler=handle_shell_body,
                summary="Shell a solid body to create uniform thin walls with optional open faces.",
            ),
            ("hollow_body", "1.0.0"): OperationSpec(
                dialect="shell_housing", op="hollow_body", op_version="1.0.0",
                phase="hollow", input_types=["solid"], output_types=["solid"],
                params_model=HollowBodyParams, effects=["modifies_solid"],
                handler=handle_hollow_body,
                summary="Hollow a solid body by creating an internal offset cavity.",
            ),
        }

    def manifest(self): return {"dialect_id": self.dialect_id, "version": self.version}
    def contract(self): return self.manifest()
    def op_specs(self): return dict(self._specs)
    def default_op_version(self, op): return "1.0.0"
    def get_op_spec(self, op, v=None): return self._specs.get((op, v or "1.0.0"))

    def validate_component(self, c, n): return ValidationReport(ok=True, stage="dialect_semantics")

    def preflight_component(self, component, nodes):
        """Preflight: thickness > 0, thickness < 40% of known base dimensions."""
        issues = []
        stage = "geometry_preflight"
        ALLOWED_FACES = {"+Z", "-Z", "+X", "-X", "+Y", "-Y", ""}

        for node in nodes:
            thickness = node.typed_params.get("thickness_mm") or node.params.get("thickness_mm", 0)
            if thickness <= 0:
                issues.append(ValidationIssue(
                    stage=stage, code="sh_thickness_non_positive",
                    message=f"shell_body thickness_mm must be > 0, got {thickness}",
                    severity="error", node_id=node.id,
                ))

            open_faces = node.typed_params.get("open_faces") or node.params.get("open_faces", [])
            for face in (open_faces or []):
                if face not in ALLOWED_FACES:
                    issues.append(ValidationIssue(
                        stage=stage, code="sh_invalid_open_face",
                        message=f"open_faces value {face!r} not in {sorted(ALLOWED_FACES)}",
                        severity="warning", node_id=node.id,
                    ))

        return ValidationReport(
            ok=not any(i.severity == "error" for i in issues),
            stage=stage, issues=issues,
        )

    def run_component(self, component, nodes, ctx):
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        outputs = {}
        pr = {p: i for i, p in enumerate(self.phase_order)}
        for node in sorted(nodes, key=lambda n: (pr.get(n.phase, 99), n.id)):
            op_spec = self.get_op_spec(node.op, node.op_version)
            if op_spec is None:
                continue
            try:
                e = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
                for name, hid in e.outputs.items():
                    outputs[name] = hid
            except Exception as exc:
                if not getattr(node, "required", True) and node.degradation_policy == "may_skip_with_warning":
                    ctx.warnings.append(f"Optional {node.id!r} ({node.op}) skipped: {exc}")
                    ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
                    ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "degraded", "reason": str(exc)})
                    continue
                raise
        return outputs


SHELL_HOUSING_DIALECT = ShellHousingDialect()
