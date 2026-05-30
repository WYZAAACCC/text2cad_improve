"""G-CAD Core runner — raw validation → canonical → components → STEP → metadata. v0.8: require_full_validation_seed.

Split entrypoints:
- run_gcad_core_from_files / run_gcad_core: accepts RAW JSON, validates+canonicalizes with bundle
- run_canonical_gcad_from_files / run_canonical_gcad: accepts PRE-VALIDATED canonical JSON

run_canonical_gcad_from_files: This entrypoint is for pre-validated canonical documents.
Metadata produced here is runner-local and may not contain full validation proof unless
validation_seed is provided. Production build_generative_cad_model rewrites metadata
with ValidationBundle and inspection proof before returning success.
"""

from __future__ import annotations

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata
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
        require_full_validation_seed=True,
    )


# ── Canonical entrypoints (pre-validated) ──

def run_canonical_gcad_from_files(
    canonical_json: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    """Load and run a pre-validated canonical document.

    This entrypoint does not pass validation_seed — metadata produced here is
    runner-local. Builder rewrites metadata with full ValidationBundle proof
    after process return.
    """
    try:
        data = json.loads(Path(canonical_json).read_text(encoding="utf-8"))
        canonical = CanonicalGcadDocument.model_validate(data)
    except Exception as exc:
        return GcadRunResult(ok=False, error=f"failed to load canonical JSON: {exc}")
    return run_canonical_gcad(canonical, out_step=out_step, metadata_path=metadata_path)


def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    validation_seed: dict | None = None,
    require_full_validation_seed: bool = False,
) -> GcadRunResult:
    if require_full_validation_seed and validation_seed is None:
        return GcadRunResult(
            ok=False,
            error=(
                "run_canonical_gcad requires validation_seed when "
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

    if validation_seed is None:
        ctx.warnings.append(
            "Canonical runner executed without validation_seed; metadata is runner-local "
            "and not a full importable proof until builder attaches validation bundle and inspection."
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

        validation = validation_seed or {}
        validation["runtime_postconditions"] = runtime_pc

        metadata = build_generative_metadata(
            canonical=canonical, ctx=ctx,
            validation=validation,
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        artifact = build_canonical_step_artifact(
            canonical=canonical, step_path=out_step,
            metadata_path=metadata_path, ctx=ctx,
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
    import cadquery as cq
    cq.exporters.export(obj, str(ctx.out_step))
