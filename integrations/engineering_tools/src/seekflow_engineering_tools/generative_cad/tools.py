"""SeekFlow tools for the generative CAD path.

Registers read tools (list bases, get contracts, validate IR) and a write tool (build).
"""

from __future__ import annotations

from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec
from seekflow_engineering_tools.generative_cad.graph_validation import run_graph_validation
from seekflow_engineering_tools.generative_cad.registry import (
    export_base_catalog,
    get_base,
    list_bases,
)


def build_generative_cad_tools(config):
    """Build generative CAD tools for the SeekFlow agent."""
    tools: list = []

    # ── Read tools ──

    @tool(
        name="generative_cad_list_bases",
        description=(
            "List all registered generative CAD grammar bases. "
            "Returns base_id and summary for each base."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_list_bases() -> dict:
        try:
            catalog = export_base_catalog()
            return EngineeringActionResult(
                ok=True,
                software="cadquery",
                action="generative_cad_list_bases",
                message=f"Found {len(catalog['bases'])} generative CAD base(s).",
                metrics={"catalog": catalog},
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="generative_cad_list_bases",
                error=str(exc),
            ).model_dump()

    generative_cad_list_bases = generative_cad_list_bases.with_policy(
        ToolPolicy(
            capabilities={"cad.generative.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    @tool(
        name="generative_cad_get_base_contract",
        description=(
            "Get the full contract for a specific generative CAD base. "
            "Includes phase order and all allowed operations with parameter schemas."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_get_base_contract(base_id: str) -> dict:
        try:
            base = get_base(base_id)
            if base is None:
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="generative_cad_get_base_contract",
                    error=f"Unknown base: {base_id!r}. Available: {list_bases()}",
                ).model_dump()

            return EngineeringActionResult(
                ok=True,
                software="cadquery",
                action="generative_cad_get_base_contract",
                message=f"Contract for {base_id!r}.",
                metrics={
                    "manifest": base.export_manifest(),
                    "contract": base.export_contract(),
                },
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="generative_cad_get_base_contract",
                error=str(exc),
            ).model_dump()

    generative_cad_get_base_contract = generative_cad_get_base_contract.with_policy(
        ToolPolicy(
            capabilities={"cad.generative.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    @tool(
        name="generative_cad_validate_ir",
        description=(
            "Validate a GenerativeCADSpec against all graph validation rules. "
            "Returns validation report with any issues found."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_validate_ir(spec: dict) -> dict:
        try:
            gen_spec = GenerativeCADSpec.model_validate(spec)
            report = run_graph_validation(gen_spec)
            return EngineeringActionResult(
                ok=report.ok,
                software="cadquery",
                action="generative_cad_validate_ir",
                message="Graph validation completed." if report.ok else "Graph validation found issues.",
                metrics={"validation": report.model_dump()},
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="generative_cad_validate_ir",
                error=str(exc),
            ).model_dump()

    generative_cad_validate_ir = generative_cad_validate_ir.with_policy(
        ToolPolicy(
            capabilities={"cad.generative.read"},
            risk="read",
            timeout_s=30,
            parallel_safe=True,
        )
    )

    # ── Write tool ──

    @tool(
        name="generative_cad_build_from_ir",
        description=(
            "Build a STEP file from a GenerativeCADSpec using the fixed runner harness. "
            "Validates the IR, runs geometry preflight, executes the graph, "
            "exports STEP, validates metadata, and inspects the result."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_build_from_ir(
        spec: dict,
        out_step: str,
        inspect: bool = True,
    ) -> dict:
        try:
            gen_spec = GenerativeCADSpec.model_validate(spec)
            return build_generative_cad_model(
                spec=gen_spec,
                config=config,
                out_step=out_step,
                inspect=inspect,
            )
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_generative_cad",
                error=str(exc),
            ).model_dump()

    generative_cad_build_from_ir = generative_cad_build_from_ir.with_policy(
        ToolPolicy(
            capabilities={"cad.generative.write", "filesystem.write"},
            risk="write",
            timeout_s=180,
            workspace_root=config.workspace_root,
            path_params=frozenset({"out_step"}),
            parallel_safe=False,
            requires_approval=False,
            idempotent=False,
        )
    )

    tools.extend([
        generative_cad_list_bases,
        generative_cad_get_base_contract,
        generative_cad_validate_ir,
        generative_cad_build_from_ir,
    ])
    return tools
