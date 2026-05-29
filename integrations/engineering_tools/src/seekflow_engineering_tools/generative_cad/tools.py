"""SeekFlow tools for the generative CAD path (v0.5: dialect tools + SW/NX import wrappers)."""

from __future__ import annotations

from pathlib import Path

from seekflow import tool
from seekflow.types import ToolPolicy

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
from seekflow_engineering_tools.generative_cad.dialects.registry import (

    export_dialect_catalog,
    get_dialect,
    list_dialects,
)
from seekflow_engineering_tools.generative_cad.native_importers import (
    import_step_to_solidworks,
    import_step_to_nx,
)
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize


def _list_dialects_result() -> dict:
    """Shared helper: list all registered generative CAD dialects."""
    try:
        catalog = export_dialect_catalog()
        return EngineeringActionResult(
            ok=True, software="cadquery", action="generative_cad_list_dialects",
            message=f"Found {len(catalog['dialects'])} generative CAD dialect(s).",
            metrics={"catalog": catalog},
        ).model_dump()
    except Exception as exc:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="generative_cad_list_dialects",
            error=str(exc),
        ).model_dump()


def _get_dialect_contract_result(dialect_id: str) -> dict:
    """Shared helper: get full contract for a registered dialect."""
    try:
        dialect = get_dialect(dialect_id)
        if dialect is None:
            return EngineeringActionResult(
                ok=False, software="cadquery", action="generative_cad_get_dialect_contract",
                error=f"Unknown dialect: {dialect_id!r}. Available: {list_dialects()}",
            ).model_dump()
        return EngineeringActionResult(
            ok=True, software="cadquery", action="generative_cad_get_dialect_contract",
            message=f"Contract for {dialect_id!r}.",
            metrics={"manifest": dialect.manifest(), "contract": dialect.contract()},
        ).model_dump()
    except Exception as exc:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="generative_cad_get_dialect_contract",
            error=str(exc),
        ).model_dump()


# Native import helpers moved to generative_cad/native_importers.py for testability


def build_generative_cad_tools(config):
    """Build generative CAD tools for the SeekFlow agent (v0.5)."""
    tools: list = []

    # ── Canonical: generative_cad_list_dialects ──
    @tool(
        name="generative_cad_list_dialects",
        description="List all registered generative CAD grammar dialects. Returns dialect_id and summary for each.",
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_list_dialects() -> dict:
        return _list_dialects_result()

    generative_cad_list_dialects = generative_cad_list_dialects.with_policy(
        ToolPolicy(capabilities={"cad.generative.read"}, risk="read", timeout_s=30, parallel_safe=True)
    )

    # ── Legacy alias: generative_cad_list_bases ──
    @tool(
        name="generative_cad_list_bases",
        description="Deprecated alias. 'base' means 'dialect'; prefer generative_cad_list_dialects.",
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_list_bases() -> dict:
        return _list_dialects_result()

    generative_cad_list_bases = generative_cad_list_bases.with_policy(
        ToolPolicy(capabilities={"cad.generative.read"}, risk="read", timeout_s=30, parallel_safe=True)
    )

    # ── Canonical: generative_cad_get_dialect_contract ──
    @tool(
        name="generative_cad_get_dialect_contract",
        description="Get the full contract for a specific generative CAD dialect. Includes phase order and all allowed operations with parameter schemas.",
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_get_dialect_contract(dialect_id: str) -> dict:
        return _get_dialect_contract_result(dialect_id)

    generative_cad_get_dialect_contract = generative_cad_get_dialect_contract.with_policy(
        ToolPolicy(capabilities={"cad.generative.read"}, risk="read", timeout_s=30, parallel_safe=True)
    )

    # ── Legacy alias: generative_cad_get_base_contract ──
    @tool(
        name="generative_cad_get_base_contract",
        description="Deprecated alias. 'base' means 'dialect'; prefer generative_cad_get_dialect_contract.",
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_get_base_contract(base_id: str) -> dict:
        return _get_dialect_contract_result(base_id)

    generative_cad_get_base_contract = generative_cad_get_base_contract.with_policy(
        ToolPolicy(capabilities={"cad.generative.read"}, risk="read", timeout_s=30, parallel_safe=True)
    )

    # ── Validate IR ──
    @tool(
        name="generative_cad_validate_ir",
        description="Validate a G-CAD Core IR document (RawGcadDocument) against all validation rules.",
        cache=False, sanitize=True, trusted=False,
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
                ok=report.ok, software="cadquery", action="generative_cad_validate_ir",
                message="Validation completed." if report.ok else "Validation found issues.",
                metrics=metrics,
            ).model_dump()
        except Exception as exc:
            return EngineeringActionResult(
                ok=False, software="cadquery", action="generative_cad_validate_ir", error=str(exc),
            ).model_dump()

    generative_cad_validate_ir = generative_cad_validate_ir.with_policy(
        ToolPolicy(capabilities={"cad.generative.read"}, risk="read", timeout_s=30, parallel_safe=True)
    )

    # ── Build IR ──
    @tool(
        name="generative_cad_build_from_ir",
        description="Build a STEP file from a G-CAD Core IR document (RawGcadDocument format).",
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_build_from_ir(
        spec: dict, out_step: str,
        inspect: bool = True, strict_inspection: bool = True,
    ) -> dict:
        try:
            return build_generative_cad_model(
                spec=spec, config=config, out_step=out_step,
                inspect=inspect, strict_inspection=strict_inspection,
            )
        except Exception as exc:
            return EngineeringActionResult(
                ok=False, software="cadquery", action="build_generative_cad", error=str(exc),
            ).model_dump()

    generative_cad_build_from_ir = generative_cad_build_from_ir.with_policy(
        ToolPolicy(
            capabilities={"cad.generative.write", "filesystem.write"},
            risk="write", timeout_s=180,
            workspace_root=config.workspace_root,
            path_params=frozenset({"out_step"}),
            parallel_safe=False, requires_approval=False, idempotent=False,
        )
    )

    # ── Generative SW import wrapper ──
    @tool(
        name="generative_cad_import_artifact_to_solidworks",
        description=(
            "Import a validated Generative CAD canonical STEP artifact into SolidWorks "
            "as SLDPRT. Requires generative_metadata_v2.1 import gate to pass. "
            "Does not rebuild native feature tree."
        ),
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_import_artifact_to_solidworks(
        step_path: str, metadata_path: str, out_sldprt: str,
    ) -> dict:
        try:
            from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
                validate_generative_step_artifact_for_native_import,
            )

            step = ensure_inside_workspace(config.workspace_root, step_path)
            meta = ensure_inside_workspace(config.workspace_root, metadata_path)
            out = ensure_inside_workspace(config.workspace_root, out_sldprt)
            ensure_extension(step, {".step", ".stp"})
            ensure_extension(meta, {".json"})
            ensure_extension(out, {".sldprt"})

            gate = validate_generative_step_artifact_for_native_import(
                step, meta, require_inspection_ok=True,
                require_geometry_preflight_ok=True, registry_check=True,
            )
            if not gate["ok"]:
                return EngineeringActionResult(
                    ok=False, software="solidworks",
                    action="generative_cad_import_artifact_to_solidworks",
                    error="Generative artifact import gate failed: "
                    + "; ".join(i["message"] for i in gate["issues"]),
                    metrics={"import_gate": gate["gate"]},
                ).model_dump()

            sw_result = import_step_to_solidworks(config, step, out)

            return EngineeringActionResult(
                ok=sw_result.get("ok", True),
                software="solidworks",
                action="generative_cad_import_artifact_to_solidworks",
                message="Validated generative STEP imported into SolidWorks.",
                files_created=[str(out)] if sw_result.get("ok", True) else [],
                error=sw_result.get("error"),
                metrics={
                    "source_route": "llm_skill_base",
                    "strategy": "validated_generative_step_import",
                    "native_rebuild_allowed": False,
                    "step_import_allowed": True,
                    "source_step": str(step),
                    "source_metadata": str(meta),
                    "native_path": str(out),
                    "import_gate": gate["gate"],
                    "canonical_graph_hash": gate.get("metadata", {}).get("generative_metadata", {}).get("canonical_graph_hash", ""),
                    "selected_dialects": gate.get("metadata", {}).get("generative_metadata", {}).get("selected_dialects", []),
                },
                warnings=[
                    "Native SolidWorks file was created by importing validated generative canonical STEP.",
                    "Native feature tree was not regenerated.",
                    "Generative output is reference geometry only.",
                    "Not certified, not manufacturing-ready, not installable.",
                ],
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False, software="solidworks",
                action="generative_cad_import_artifact_to_solidworks",
                error=str(exc),
            ).model_dump()

    generative_cad_import_artifact_to_solidworks = (
        generative_cad_import_artifact_to_solidworks.with_policy(
            ToolPolicy(
                capabilities={"cad.generative.read", "cad.solidworks.write", "filesystem.write"},
                risk="write", timeout_s=180,
                workspace_root=config.workspace_root,
                path_params=frozenset({"step_path", "metadata_path", "out_sldprt"}),
                parallel_safe=False, requires_approval=False, idempotent=False,
            )
        )
    )

    # ── Generative NX import wrapper ──
    @tool(
        name="generative_cad_import_artifact_to_nx",
        description=(
            "Import a validated Generative CAD canonical STEP artifact into Siemens NX "
            "as PRT. Requires generative_metadata_v2.1 import gate to pass. "
            "Does not rebuild native feature tree."
        ),
        cache=False, sanitize=True, trusted=False,
    )
    def generative_cad_import_artifact_to_nx(
        step_path: str, metadata_path: str, out_prt: str,
    ) -> dict:
        try:
            from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
                validate_generative_step_artifact_for_native_import,
            )

            step = ensure_inside_workspace(config.workspace_root, step_path)
            meta = ensure_inside_workspace(config.workspace_root, metadata_path)
            out = ensure_inside_workspace(config.workspace_root, out_prt)
            ensure_extension(step, {".step", ".stp"})
            ensure_extension(meta, {".json"})
            ensure_extension(out, {".prt"})

            gate = validate_generative_step_artifact_for_native_import(
                step, meta, require_inspection_ok=True,
                require_geometry_preflight_ok=True, registry_check=True,
            )
            if not gate["ok"]:
                return EngineeringActionResult(
                    ok=False, software="nx",
                    action="generative_cad_import_artifact_to_nx",
                    error="Generative artifact import gate failed: "
                    + "; ".join(i["message"] for i in gate["issues"]),
                    metrics={"import_gate": gate["gate"]},
                ).model_dump()

            nx_result = import_step_to_nx(config, config.workspace_root, step, out)

            return EngineeringActionResult(
                ok=nx_result.get("ok", True),
                software="nx",
                action="generative_cad_import_artifact_to_nx",
                message="Validated generative STEP imported into Siemens NX.",
                files_created=[str(out)] if nx_result.get("ok", True) else [],
                error=nx_result.get("error"),
                metrics={
                    "source_route": "llm_skill_base",
                    "strategy": "validated_generative_step_import",
                    "native_rebuild_allowed": False,
                    "step_import_allowed": True,
                    "source_step": str(step),
                    "source_metadata": str(meta),
                    "native_path": str(out),
                    "import_gate": gate["gate"],
                    "canonical_graph_hash": gate.get("metadata", {}).get("generative_metadata", {}).get("canonical_graph_hash", ""),
                    "selected_dialects": gate.get("metadata", {}).get("generative_metadata", {}).get("selected_dialects", []),
                },
                warnings=[
                    "Native NX file was created by importing validated generative canonical STEP.",
                    "Native feature tree was not regenerated.",
                    "Generative output is reference geometry only.",
                    "Not certified, not manufacturing-ready, not installable.",
                ],
            ).model_dump()

        except Exception as exc:
            return EngineeringActionResult(
                ok=False, software="nx",
                action="generative_cad_import_artifact_to_nx",
                error=str(exc),
            ).model_dump()

    generative_cad_import_artifact_to_nx = (
        generative_cad_import_artifact_to_nx.with_policy(
            ToolPolicy(
                capabilities={"cad.generative.read", "cad.nx.write", "filesystem.write"},
                risk="write", timeout_s=180,
                workspace_root=config.workspace_root,
                path_params=frozenset({"step_path", "metadata_path", "out_prt"}),
                parallel_safe=False, requires_approval=False, idempotent=False,
            )
        )
    )

    tools.extend([
        generative_cad_list_dialects,
        generative_cad_get_dialect_contract,
        generative_cad_list_bases,
        generative_cad_get_base_contract,
        generative_cad_validate_ir,
        generative_cad_build_from_ir,
        generative_cad_import_artifact_to_solidworks,
        generative_cad_import_artifact_to_nx,
    ])
    return tools
