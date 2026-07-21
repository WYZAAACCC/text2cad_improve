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
from seekflow_engineering_tools.generative_cad.runtime.diagnostics import (
    RuntimeIssue,
    RuntimeReport,
)
from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle


def _build_runtime_report(
    ctx: RuntimeContext,
    *,
    ok: bool,
    failed_stage: str | None = None,
    issues: list[RuntimeIssue] | None = None,
    runtime_postconditions: dict | None = None,
    geometry_postcheck: dict | None = None,
    sanitized_traceback: list[str] | None = None,
) -> RuntimeReport:
    """从 ctx 收集结构化证据 (Stage B) — 失败时不再丢弃 geometry health 等."""
    issues = issues or []
    primary = next((i for i in issues if i.severity in ("error", "fatal")),
                   issues[0] if issues else None)
    return RuntimeReport(
        ok=ok,
        failed_stage=failed_stage,
        issues=issues,
        failing_node_id=primary.node_id if primary else None,
        failing_component_id=primary.component_id if primary else None,
        failing_operation=primary.operation if primary else None,
        geometry_health=dict(getattr(ctx, "geometry_health_log", {}) or {}),
        operation_metrics=list(ctx.operation_metrics),
        degraded_features=list(ctx.degraded_features),
        runtime_postconditions=runtime_postconditions,
        geometry_postcheck=geometry_postcheck,
        sanitized_traceback=sanitized_traceback or [],
    )


def _fail_result(
    ctx: RuntimeContext,
    *,
    stage: str,
    error: str,
    issues: list[RuntimeIssue],
    runtime_postconditions: dict | None = None,
    geometry_postcheck: dict | None = None,
    sanitized_traceback: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> GcadRunResult:
    """失败出口统一构造: error 字符串与旧行为逐字节一致 + RuntimeReport."""
    return GcadRunResult(
        ok=False,
        error=error,
        warnings=ctx.warnings + (extra_warnings or []),
        degraded_features=ctx.degraded_features,
        operation_metrics=ctx.operation_metrics,
        runtime_report=_build_runtime_report(
            ctx, ok=False, failed_stage=stage, issues=issues,
            runtime_postconditions=runtime_postconditions,
            geometry_postcheck=geometry_postcheck,
            sanitized_traceback=sanitized_traceback,
        ),
    )


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
        document_id=canonical.document_id,
        canonical_graph_hash=canonical.canonical_graph_hash,
        design_identity=canonical.design_identity,
    )

    try:
        # ════════════════════════════════════════════════════════════
        # v6.3: Compiler Middle-End (sidecar analysis)
        # ════════════════════════════════════════════════════════════
        from seekflow_engineering_tools.generative_cad.compiler.pass_manager import (
            build_compiler_module,
        )
        from seekflow_engineering_tools.generative_cad.compiler.config import (
            middle_end_enabled,
            FAIL_ON_MIDDLE_END_ERROR,
        )

        compiler_module = build_compiler_module(canonical)
        ctx.compiler_diagnostics = list(compiler_module.diagnostics)
        ctx.planning_report = compiler_module.planning_report

        if middle_end_enabled() and not compiler_module.ok:
            if FAIL_ON_MIDDLE_END_ERROR:
                me_errors = [i for i in compiler_module.diagnostics
                             if i.get("severity") == "error"]
                return _fail_result(
                    ctx,
                    stage="compiler_middle_end",
                    error=(
                        "compiler middle-end failed: "
                        + "; ".join(i["message"] for i in me_errors)
                    ),
                    issues=[RuntimeIssue(
                        stage="compiler_middle_end",
                        code=str(i.get("code") or "compiler_middle_end_error"),
                        message=str(i.get("message", "")),
                        node_id=i.get("node_id"),
                        repairability="non_repairable",   # 编译器侧缺陷, 禁进 LLM (§6.3)
                    ) for i in me_errors],
                )
            ctx.warnings.append(
                "compiler middle-end errors suppressed (FAIL_ON_MIDDLE_END_ERROR=False)"
            )
        # ════════════════════════════════════════════════════════════

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

            # ── v6.3: Build spatial→canonical component ID mapping ──
            # The spatial graph (from LLM's MechanicalObjectGraphDraft) may
            # use different component IDs than the canonical document (from
            # FeatureSequenceDraft). Build a best-effort mapping and remap
            # constraint entities in-place to bridge the two naming conventions.
            spatial_to_canonical: dict[str, str] = {}
            canonical_bbox_keys = set(bboxes.keys())
            # Step 1: Exact match
            for constraint in spatial_graph.constraints:
                for eid in constraint.entities:
                    if eid in canonical_bbox_keys:
                        spatial_to_canonical[eid] = eid
            # Step 2: Case-insensitive match for remaining
            remaining_spatial = {
                eid for c in spatial_graph.constraints
                for eid in c.entities
                if eid not in spatial_to_canonical
            }
            for seid in sorted(remaining_spatial):
                seid_lower = seid.lower()
                for cid in canonical_bbox_keys:
                    if cid.lower() == seid_lower and cid not in spatial_to_canonical.values():
                        spatial_to_canonical[seid] = cid
                        break
            # Step 3: Position-based fallback
            still_remaining = [eid for eid in remaining_spatial if eid not in spatial_to_canonical]
            unused_canonical = [cid for cid in component_ids if cid not in spatial_to_canonical.values()]
            for i, seid in enumerate(still_remaining):
                if i < len(unused_canonical):
                    spatial_to_canonical[seid] = unused_canonical[i]
                    ctx.warnings.append(
                        f"[spatial] fuzzy ID mapping: '{seid}' → '{unused_canonical[i]}'"
                    )
                else:
                    ctx.warnings.append(
                        f"[spatial] cannot map entity '{seid}' to any canonical component"
                    )

            # Remap constraint entities in-place to canonical IDs
            for constraint in spatial_graph.constraints:
                constraint.entities = [
                    spatial_to_canonical.get(eid, eid) for eid in constraint.entities
                ]

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
                    return _fail_result(
                        ctx,
                        stage="spatial_audit",
                        error="spatial audit failed: " + "; ".join(i.message for i in errors),
                        issues=[RuntimeIssue(
                            stage="spatial_audit",
                            code=str(getattr(i, "code", "") or "spatial_audit_failed"),
                            message=i.message,
                            repairability="conditionally_repairable",
                        ) for i in errors],
                    )
        # ════════════════════════════════════════════════════════════

        from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
        runtime_pc = validate_runtime_postconditions(canonical, ctx, final_handle_id)
        if not runtime_pc["ok"]:
            return _fail_result(
                ctx,
                stage="runtime_postconditions",
                error="runtime postconditions failed: "
                + "; ".join(i["message"] for i in runtime_pc["issues"]),
                issues=[RuntimeIssue(
                    stage=str(i.get("stage") or "runtime_postconditions"),
                    code=str(i.get("code") or "runtime_postcondition_failed"),
                    severity=i.get("severity", "error"),
                    message=str(i.get("message", "")),
                    node_id=i.get("node_id"),
                    component_id=i.get("component_id"),
                    expected=i.get("expected"),
                    actual=i.get("actual"),
                    repairability="conditionally_repairable",
                ) for i in runtime_pc["issues"]],
                runtime_postconditions=runtime_pc,
            )

        _export_final_solid(final_handle_id, ctx)

        # ════════════════════════════════════════════════════════════
        # v6.3: Geometry postcondition gate (post-STEP export)
        # ════════════════════════════════════════════════════════════
        from seekflow_engineering_tools.generative_cad.runtime.geometry_postcheck import (
            validate_final_geometry,
            validate_step_post_export,
        )
        geo_postcheck = validate_final_geometry(
            ctx, final_handle_id,
            expected_body_count=canonical.constraints.expected_body_count,
        )
        step_postcheck = validate_step_post_export(out_step, min_size_bytes=200)

        # ════════════════════════════════════════════════════════════
        # V3: Write topology sidecar after successful STEP export
        # ════════════════════════════════════════════════════════════
        _write_topology_sidecar_if_entities(ctx, out_step, canonical)

        if not geo_postcheck.ok:
            gp_dict = {
                "ok": geo_postcheck.ok,
                "volume_mm3": geo_postcheck.volume_mm3,
                "n_solids": geo_postcheck.n_solids,
                "closed": geo_postcheck.closed,
                "errors": geo_postcheck.errors,
            }
            return _fail_result(
                ctx,
                stage="geometry_postcheck",
                error="geometry postcheck failed: " + "; ".join(geo_postcheck.errors),
                issues=[RuntimeIssue(
                    stage="geometry_postcheck",
                    code="final_geometry_postcheck_failed",
                    message=msg,
                    repairability="conditionally_repairable",
                    evidence=gp_dict,
                ) for msg in geo_postcheck.errors],
                geometry_postcheck=gp_dict,
                extra_warnings=geo_postcheck.warnings,
            )
        if not step_postcheck.ok:
            return _fail_result(
                ctx,
                stage="step_postcheck",
                error="STEP postcheck failed: " + "; ".join(step_postcheck.errors),
                issues=[RuntimeIssue(
                    stage="step_postcheck",
                    code="step_post_export_failed",
                    message=msg,
                    repairability="non_repairable",   # 导出器/文件级, 非 IR 参数 (§6.3)
                ) for msg in step_postcheck.errors],
            )
        # ════════════════════════════════════════════════════════════

        validation = copy.deepcopy(validation_seed)
        validation["runtime_postconditions"] = runtime_pc
        validation["geometry_postcheck"] = {
            "ok": geo_postcheck.ok,
            "volume_mm3": geo_postcheck.volume_mm3,
            "n_solids": geo_postcheck.n_solids,
            "bbox_mm": geo_postcheck.bbox_mm,
            "closed": geo_postcheck.closed,
            "is_valid_solid": geo_postcheck.is_valid_solid,
            "errors": geo_postcheck.errors,
            "warnings": geo_postcheck.warnings,
        }

        # ── v6.3: Compiler middle-end diagnostics in metadata ──
        # Always write this section, even when diagnostics are empty —
        # provides an audit trail that the compiler ran and found no issues.
        validation["compiler_middle_end"] = {
            "ok": not any(
                d.get("severity") == "error" for d in ctx.compiler_diagnostics
            ),
            "passes_run": getattr(compiler_module, "enabled_passes", []),
            "diagnostics": ctx.compiler_diagnostics,
        }

        # ── v6.3 Phase 2: Geometry health summary ──
        if ctx.geometry_health_log:
            health_entries = list(ctx.geometry_health_log.values())
            error_count = sum(
                1 for h in health_entries if h.get("status") == "error"
            )
            warning_count = sum(
                1 for h in health_entries if h.get("status") == "warning"
            )
            validation["geometry_health_summary"] = {
                "ok": error_count == 0,
                "total_ops_checked": len(health_entries),
                "errors": error_count,
                "warnings": warning_count,
                "entries": {
                    key: {
                        "status": h.get("status"),
                        "score": h.get("score"),
                        "closed": h.get("closed"),
                        "volume_mm3": h.get("volume_mm3"),
                        "body_count": h.get("body_count"),
                    }
                    for key, h in ctx.geometry_health_log.items()
                },
            }

        # ── v6.3 Phase 3: Planning report in metadata ──
        if ctx.planning_report:
            validation["planning_report"] = ctx.planning_report

        metadata = build_generative_metadata_v3(
            canonical=canonical, ctx=ctx,
            validation=validation,
            canonical_ir_path=Path(canonical_ir_path) if canonical_ir_path else Path("<in_memory>"),
            validation_seed_path=Path(validation_seed_path) if validation_seed_path else Path("<in_memory>"),
            step_path=out_step,
            metadata_path=metadata_path,
            unsupported_capabilities=getattr(canonical, 'unsupported_capabilities', None) or [],
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
            return _fail_result(
                ctx,
                stage="artifact_consistency",
                error="runner artifact/metadata validation mismatch",
                issues=[RuntimeIssue(
                    stage="artifact_consistency",
                    code="artifact_metadata_validation_mismatch",
                    message="runner artifact/metadata validation mismatch",
                    repairability="non_repairable",   # 元数据构建器缺陷 (§6.3)
                )],
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
            runtime_report=_build_runtime_report(ctx, ok=True),
        )

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        ctx.warnings.append(f"runner exception traceback:\n{tb}")
        from seekflow_engineering_tools.generative_cad.runtime.errors import (
            GcadRuntimeError,
        )
        if isinstance(exc, GcadRuntimeError):
            issues = [exc.issue]
        else:
            issues = [RuntimeIssue(
                stage="internal_exception",
                code="unhandled_runtime_exception",
                message=str(exc)[:500],
                exception_type=type(exc).__name__,
                repairability="unknown",   # 未分类 → 分类器 fail-closed
            )]
        return _fail_result(
            ctx,
            stage="component_execution",
            error=f"{exc}\n{tb[-2000:]}",
            issues=issues,
            sanitized_traceback=tb.splitlines()[-30:],
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
    # ── V3 Phase 9: build stable feature identity context ──
    try:
        from seekflow_engineering_tools.generative_cad.topology.design_identity import (
            DesignIdentityContext, FeatureIdentityReconciler,
        )
        fids = {}
        for node in canonical.nodes:
            fids[node.id] = FeatureIdentityReconciler.generate_feature_uid(
                component_uid=node.component, operation_kind=node.op,
            )
        ctx.design_identity_context = DesignIdentityContext(
            document_lineage_id=ctx.document_id or canonical.document_id,
            feature_stable_ids=fids,
            design_identity=getattr(canonical, 'design_identity', None),
        )
    except Exception:
        pass

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


def _write_topology_sidecar_if_entities(
    ctx: RuntimeContext,
    out_step: Path,
    canonical: Any,
) -> None:
    """Write topology sidecar V3 if the registry has entities.

    Called after successful STEP export. Sidecar is always written when
    topology exists — topology_mode="required" operations will have
    already enforced delta production.
    """
    try:
        if ctx.topology_registry.entity_count == 0:
            return
        from seekflow_engineering_tools.generative_cad.topology.persistence import (
            write_topology_sidecar,
        )
        sidecar_path = out_step.with_suffix(".topology.json")
        write_topology_sidecar(
            ctx.topology_registry,
            sidecar_path,
            document_id=ctx.document_id or getattr(canonical, "document_id", ""),
            canonical_graph_hash=ctx.canonical_graph_hash
            or getattr(canonical, "canonical_graph_hash", ""),
            runtime_version=ctx.runner_version,
        )
    except Exception:
        pass  # Sidecar is best-effort in Phase 9; Phase 10+ will make it required


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
