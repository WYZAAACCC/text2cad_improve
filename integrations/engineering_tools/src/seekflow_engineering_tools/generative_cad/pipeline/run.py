"""G-CAD Core runner — canonicalize → run components → export STEP → metadata."""

from __future__ import annotations

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize


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
    canonical, report = validate_and_canonicalize(raw)
    if canonical is None or not report.ok:
        return GcadRunResult(
            ok=False,
            error="validation failed: " + "; ".join(i.message for i in report.issues),
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
        _export_final_solid(final_handle_id, ctx)

        metadata = build_generative_metadata(canonical=canonical, ctx=ctx)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        return GcadRunResult(
            ok=True,
            step_path=out_step,
            metadata_path=metadata_path,
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


def _run_components(canonical: CanonicalGcadDocument, ctx: RuntimeContext) -> None:
    components = [c for c in canonical.components if c.id != "__assembly__"]

    # Simple topological order — no inter-component deps without composition
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
        raise RuntimeError(
            "multiple components require __assembly__ composition component"
        )

    comp = non_assembly[0]
    comp_outputs = ctx.component_outputs.get(comp.id, {})
    if "body" not in comp_outputs:
        # Try to find body output from any node in this component
        for n in canonical.nodes:
            if n.component == comp.id:
                for o in n.outputs:
                    if o.name == "body":
                        try:
                            return ctx.resolve_node_output(n.id, "body")
                        except KeyError:
                            pass
        raise RuntimeError(f"component {comp.id!r} did not expose body output")
    return comp_outputs["body"]


def _export_final_solid(handle_id: str, ctx: RuntimeContext) -> None:
    obj = ctx.object_store.get(handle_id)
    import cadquery as cq
    cq.exporters.export(obj, str(ctx.out_step))
