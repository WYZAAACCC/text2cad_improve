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

        # ════════════════════════════════════════════════════════════
        # v6: Constraint Resolution (symbolic → numeric placements)
        # ════════════════════════════════════════════════════════════
        spatial_graph = _load_spatial_contract(ctx)
        if spatial_graph is not None:
            from seekflow_engineering_tools.generative_cad.runtime.bbox_tracker import (
                measure_all_component_bboxes,
            )
            from seekflow_engineering_tools.generative_cad.runtime.constraint_resolver import (
                resolve_placements,
            )

            component_ids = [
                c.id for c in canonical.components
                if c.id != "__assembly__"
            ]
            bboxes = measure_all_component_bboxes(ctx, component_ids)
            placements, resolver_issues = resolve_placements(spatial_graph, bboxes)
            ctx.spatial_placements = placements
            for issue in resolver_issues:
                ctx.warnings.append(f"[spatial solver] {issue}")

            unsolved = [cid for cid, p in placements.items() if p.is_pending]
            if unsolved:
                ctx.warnings.append(
                    f"spatial: {len(unsolved)} unsolved placements: {unsolved}"
                )

        final_handle_id = _run_composition_or_select_final(canonical, ctx)

        # ════════════════════════════════════════════════════════════
        # v6: GeometrySpatialAudit
        # ════════════════════════════════════════════════════════════
        if spatial_graph is not None:
            from seekflow_engineering_tools.generative_cad.runtime.spatial_audit import (
                run_geometry_spatial_audit,
            )
            audit = run_geometry_spatial_audit(
                final_handle_id=final_handle_id,
                ctx=ctx,
                spatial_graph=spatial_graph,
                placements=getattr(ctx, 'spatial_placements', {}),
            )
            ctx.spatial_audit_report = audit
            if not audit.ok:
                errors = [i for i in audit.issues if i.severity == "error"]
                if errors:
                    return GcadRunResult(
                        ok=False,
                        error="spatial audit failed: " + "; ".join(i.message for i in errors),
                        warnings=ctx.warnings,
                        degraded_features=ctx.degraded_features,
                        operation_metrics=ctx.operation_metrics,
                    )
        # ════════════════════════════════════════════════════════════

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
        import traceback
        tb = traceback.format_exc()
        ctx.warnings.append(f"runner exception traceback:\n{tb}")
        return GcadRunResult(
            ok=False,
            error=f"{exc}\n{tb[-2000:]}",
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )


# ── Internal helpers ──

def _load_spatial_contract(ctx) -> "SpatialConstraintGraph | None":
    """Load spatial_contract.json sidecar from workspace root."""
    import json
    sp = ctx.workspace_root / "spatial_contract.json"
    if not sp.exists():
        return None
    from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
        SpatialConstraintGraph,
    )
    data = json.loads(sp.read_text(encoding="utf-8"))
    return SpatialConstraintGraph.model_validate(data)


def _run_components(canonical: CanonicalGcadDocument, ctx: RuntimeContext) -> None:
    """Run each non-assembly component, dispatching nodes to their actual dialect.

    v5.1: Mixed-dialect components (e.g. sketch_extrude + shell_housing)
    are handled by dispatching each node to its node.dialect, not the
    component's owner_dialect. Nodes are run in topological order within
    the component so cross-dialect dependencies resolve correctly.
    """
    components = [c for c in canonical.components if c.id != "__assembly__"]
    for component in components:
        nodes = [n for n in canonical.nodes if n.component == component.id]
        if not nodes:
            continue
        # Check if all nodes share the same dialect
        dialects_in_use = set(n.dialect for n in nodes)
        if len(dialects_in_use) == 1:
            # Fast path: single dialect, delegate to dialect.run_component
            dialect = require_dialect(component.owner_dialect)
            component_outputs = dialect.run_component(component, nodes, ctx)
            for name, handle_id in component_outputs.items():
                ctx.bind_component_output(component.id, name, handle_id)
        else:
            # Mixed-dialect component: run each node individually via its own dialect
            _run_mixed_dialect_component(component, nodes, ctx, dialects_in_use)


def _run_mixed_dialect_component(component, nodes, ctx, dialects_in_use):
    """Run a component containing nodes from multiple dialects.

    Each node is dispatched to its own dialect for execution, in
    topological order. Outputs are bound to the component after all
    nodes complete.
    """
    from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

    # Topological sort: build in-degree map
    node_map = {n.id: n for n in nodes}
    in_degree = {n.id: sum(1 for i in n.inputs if i.producer_node and i.producer_node in node_map) for n in nodes}
    queue = [n for n in nodes if in_degree[n.id] == 0]
    processed = []

    while queue:
        # Stable sort by id for determinism
        queue.sort(key=lambda n: n.id)
        node = queue.pop(0)
        processed.append(node)

        for other in nodes:
            for inp in other.inputs:
                if inp.producer_node == node.id:
                    in_degree[other.id] -= 1
                    if in_degree[other.id] == 0 and other not in queue and other not in processed:
                        queue.append(other)

    if len(processed) != len(nodes):
        unscheduled = [n.id for n in nodes if n not in processed]
        raise RuntimeError(f"Mixed-dialect component {component.id!r}: unscheduled nodes: {unscheduled}")

    # Execute each node using its own dialect
    final_outputs = {}
    for node in processed:
        dialect = require_dialect(node.dialect)
        op_spec = dialect.get_op_spec(node.op, node.op_version)
        if op_spec is None:
            raise RuntimeError(
                f"Unknown op {node.op!r}/{node.op_version!r} "
                f"in dialect {node.dialect!r} for node {node.id!r}"
            )
        try:
            executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
        except Exception as exc:
            if not node.required and node.degradation_policy == "may_skip_with_warning":
                ctx.warnings.append(f"Optional {node.id!r} ({node.op}) skipped: {exc}")
                ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
                continue
            raise
        for name, hid in executed.outputs.items():
            final_outputs[name] = hid

    # Bind component outputs from the last solid-producing node
    root_node_id = component.root_node
    root = next((n for n in processed if n.id == root_node_id), processed[-1] if processed else None)
    if root:
        for o in root.outputs:
            try:
                ctx.bind_component_output(component.id, o.name, ctx.resolve_node_output(root.id, o.name))
            except KeyError:
                pass


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
