"""G-CAD Core runner — vNext: MetadataProofV3, canonical_ir_path/validation_seed_path.

Split entrypoints:
- run_gcad_core_from_files / run_gcad_core: accepts RAW JSON, validates+canonicalizes with bundle
- run_canonical_gcad_from_files / run_canonical_gcad: accepts PRE-VALIDATED canonical JSON

Metadata v3 requires paths, runtime proof, artifact hash, and import policy.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import build_generative_metadata_v3
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle


# ── Raw entrypoints (validate + canonicalize) ──

def run_gcad_core_from_files(
    input_json: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    try:
        raw = json.loads(Path(input_json).read_text(encoding="utf-8"))
    except Exception as exc:
        return GcadRunResult(ok=False, error=f"failed to load input JSON: {exc}")
    return run_gcad_core(raw, out_step=out_step, metadata_path=metadata_path)


def run_gcad_core(
    raw: dict,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
    if canonical is None or not report.ok:
        return GcadRunResult(
            ok=False,
            error="validation failed: " + "; ".join(i.message for i in report.issues),
        )
    return run_canonical_gcad(
        canonical,
        out_step=out_step,
        metadata_path=metadata_path,
        validation_seed=bundle.to_metadata_dict(),
        canonical_ir_path="<in_memory>",
        validation_seed_path="<in_memory>",
        require_full_validation_seed=True,
    )


# ── Canonical entrypoints (pre-validated) ──

def run_canonical_gcad_from_files(
    canonical_json: str | Path,
    validation_seed_json: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    """Load and run a pre-validated canonical document with validation proof.

    validation_seed_json is required — no production path may generate STEP
    from canonical IR without validation proof.
    """
    try:
        data = json.loads(Path(canonical_json).read_text(encoding="utf-8"))
        canonical = CanonicalGcadDocument.model_validate(data)
    except Exception as exc:
        return GcadRunResult(ok=False, error=f"failed to load canonical JSON: {exc}")
    try:
        validation_seed = json.loads(Path(validation_seed_json).read_text(encoding="utf-8"))
    except Exception as exc:
        return GcadRunResult(ok=False, error=f"failed to load validation seed JSON: {exc}")
    return run_canonical_gcad(
        canonical,
        out_step=out_step,
        metadata_path=metadata_path,
        validation_seed=validation_seed,
        canonical_ir_path=canonical_json,
        validation_seed_path=validation_seed_json,
        require_full_validation_seed=True,
    )


def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    validation_seed: dict,
    *,
    canonical_ir_path: str | Path | None = None,
    validation_seed_path: str | Path | None = None,
    require_full_validation_seed: bool = True,
) -> GcadRunResult:
    if require_full_validation_seed and not validation_seed:
        return GcadRunResult(
            ok=False,
            error=(
                "run_canonical_gcad requires non-empty validation_seed when "
                "require_full_validation_seed=True. Use run_gcad_core for raw input "
                "or pass ValidationBundle.to_metadata_dict()."
            ),
        )

    out_step = Path(out_step)
    metadata_path = Path(metadata_path)
    ctx = RuntimeContext(
        out_step=out_step,
        metadata_path=metadata_path,
        workspace_root=out_step.parent,
    )

    try:
        _run_components(canonical, ctx)
        final_handle_id = _run_composition_or_select_final(canonical, ctx)

        from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
        runtime_pc = validate_runtime_postconditions(canonical, ctx, final_handle_id)
        if not runtime_pc["ok"]:
            return GcadRunResult(
                ok=False,
                error="runtime postconditions failed: "
                + "; ".join(i["message"] for i in runtime_pc["issues"]),
                warnings=ctx.warnings,
                degraded_features=ctx.degraded_features,
                operation_metrics=ctx.operation_metrics,
            )

        _export_final_solid(final_handle_id, ctx)

        validation = copy.deepcopy(validation_seed)
        validation["runtime_postconditions"] = runtime_pc

        metadata = build_generative_metadata_v3(
            canonical=canonical, ctx=ctx,
            validation=validation,
            canonical_ir_path=Path(canonical_ir_path) if canonical_ir_path else Path("<in_memory>"),
            validation_seed_path=Path(validation_seed_path) if validation_seed_path else Path("<in_memory>"),
            step_path=out_step,
            metadata_path=metadata_path,
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        artifact = build_canonical_step_artifact(
            canonical=canonical, step_path=out_step,
            metadata_path=metadata_path,
            validation=metadata["validation"],
            ctx=ctx,
        )

        # v0.9: artifact/metadata consistency check for direct runner path
        if artifact.get("validation") != metadata.get("validation"):
            return GcadRunResult(
                ok=False,
                error="runner artifact/metadata validation mismatch",
                warnings=ctx.warnings,
                degraded_features=ctx.degraded_features,
                operation_metrics=ctx.operation_metrics,
            )

        return GcadRunResult(
            ok=True,
            step_path=out_step,
            metadata_path=metadata_path,
            artifact=artifact,
            metadata=metadata,
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )

    except Exception as exc:
        return GcadRunResult(
            ok=False,
            error=str(exc),
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )


# ── Internal helpers ──

def _run_components(canonical: CanonicalGcadDocument, ctx: RuntimeContext) -> None:
    components = [c for c in canonical.components if c.id != "__assembly__"]
    for component in components:
        dialect = require_dialect(component.owner_dialect)
        nodes = [n for n in canonical.nodes if n.component == component.id]
        component_outputs = dialect.run_component(component, nodes, ctx)
        for name, handle_id in component_outputs.items():
            ctx.bind_component_output(component.id, name, handle_id)


def _run_composition_or_select_final(
    canonical: CanonicalGcadDocument, ctx: RuntimeContext,
) -> str:
    assembly = next((c for c in canonical.components if c.id == "__assembly__"), None)

    if assembly is not None:
        dialect = require_dialect("composition")
        nodes = [n for n in canonical.nodes if n.component == "__assembly__"]
        outputs = dialect.run_component(assembly, nodes, ctx)
        if "body" not in outputs:
            raise RuntimeError("composition did not produce final body")
        return outputs["body"]

    non_assembly = [c for c in canonical.components if c.id != "__assembly__"]
    if len(non_assembly) != 1:
        raise RuntimeError("multiple components require __assembly__ composition component")

    comp = non_assembly[0]
    root = next((n for n in canonical.nodes if n.id == comp.root_node), None)
    if root is None:
        raise RuntimeError(f"component {comp.id!r} root_node {comp.root_node!r} not found")
    try:
        return ctx.resolve_node_output(root.id, "body")
    except KeyError:
        raise RuntimeError(f"component {comp.id!r} root node {root.id!r} did not produce body output")


def _export_final_solid(handle_id: str, ctx: RuntimeContext) -> None:
    obj = ctx.object_store.get(handle_id)
    ctx.geometry_runtime.export_step(obj, ctx.out_step)
