"""SeekFlow tools for the generative CAD path (v0.2 dialect-based).

Preserves old tool names: generative_cad_list_bases, generative_cad_get_base_contract,
generative_cad_validate_ir, generative_cad_build_from_ir.
"""

from __future__ import annotations

from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
from seekflow_engineering_tools.generative_cad.dialects.registry import (
    export_dialect_catalog,
    get_dialect,
    list_dialects,
)
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize


def build_generative_cad_tools(config):
    """Build generative CAD tools for the SeekFlow agent."""
    tools: list = []

    @tool(
        name="generative_cad_list_bases",
        description=(
            "List all registered generative CAD grammar dialects. "
            "Returns dialect_id and summary for each dialect."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_list_bases() -> dict:
        try:
            catalog = export_dialect_catalog()
            return EngineeringActionResult(
                ok=True,
                software="cadquery",
                action="generative_cad_list_bases",
                message=f"Found {len(catalog['dialects'])} generative CAD dialect(s).",
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
            "Get the full contract for a specific generative CAD dialect. "
            "Includes phase order and all allowed operations with parameter schemas."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_get_base_contract(base_id: str) -> dict:
        try:
            dialect = get_dialect(base_id)
            if dialect is None:
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="generative_cad_get_base_contract",
                    error=f"Unknown dialect: {base_id!r}. Available: {list_dialects()}",
                ).model_dump()

            return EngineeringActionResult(
                ok=True,
                software="cadquery",
                action="generative_cad_get_base_contract",
                message=f"Contract for {base_id!r}.",
                metrics={
                    "manifest": dialect.manifest(),
                    "contract": dialect.contract(),
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
            "Validate a G-CAD Core IR document (RawGcadDocument) against all validation rules. "
            "Returns validation report with any issues found and canonical graph hash."
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def generative_cad_validate_ir(spec: dict) -> dict:
        try:
            canonical, report = validate_and_canonicalize(spec)
            metrics = {"validation": report.model_dump()}
            if canonical is not None:
                metrics["canonical_graph_hash"] = canonical.canonical_graph_hash
                metrics["canonical_preview"] = {
                    "components": len(canonical.components),
                    "nodes": len(canonical.nodes),
                    "dialects": [d.dialect for d in canonical.selected_dialects],
                }
            return EngineeringActionResult(
                ok=report.ok,
                software="cadquery",
                action="generative_cad_validate_ir",
                message="Validation completed." if report.ok else "Validation found issues.",
                metrics=metrics,
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

    @tool(
        name="generative_cad_build_from_ir",
        description=(
            "Build a STEP file from a G-CAD Core IR document (RawGcadDocument format). "
            "Validates the IR, canonicalizes, executes the graph, exports STEP, "
            "validates metadata, and inspects the result."
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
            return build_generative_cad_model(
                spec=spec,
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
