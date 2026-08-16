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
from typing import Any

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

def _selections_from_canonical(canonical):
    """Convert canonical IR selections to OCAF SelectionSpec objects."""
    if not getattr(canonical, "selections", None):
        return ()
    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
        SelectionSpec,
        SelectionPolicy,
        TopologyEntityKind,
        SelectionCardinality,
    )
    specs = []
    for s in canonical.selections:
        ek = TopologyEntityKind.FACE if s.entity_kind == "face" else TopologyEntityKind.EDGE
        card = (
            SelectionCardinality.EXACT_ONE if s.cardinality == "exact_one"
            else SelectionCardinality.SET_ALLOWED
        )
        specs.append(SelectionSpec(
            selection_id=s.selection_id,
            component_id=s.component_id,
            face_selector=s.face_selector,
            role_key=getattr(s, "role_key", None),
            edge_selector=getattr(s, "edge_selector", ""),
            policy=SelectionPolicy(entity_kind=ek, cardinality=card),
        ))
    return tuple(specs)


def _bindings_from_canonical(canonical):
    """Convert canonical IR cae_bindings to OCAF CaeBinding objects."""
    if not getattr(canonical, "cae_bindings", None):
        return ()
    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import CaeBinding
    return tuple(
        CaeBinding(
            binding_id=b.binding_id, selection_id=b.selection_id,
            analysis_role=b.analysis_role, required=b.required,
        )
        for b in canonical.cae_bindings
    )


def _create_selections_from_specs(
    ctx: RuntimeContext,
    ocaf_session: Any,
    selection_specs: list,
) -> Any:
    """Create persistent topology selections from SelectionSpec objects.

    Resolves each spec's component "body" output from the runtime object store,
    selects the target face via a CadQuery selector or a named role, and
    registers it as a persistent TNaming selection. The returned service has a
    ``selection_feature_map`` attribute so CAE preflight can build a
    feature-level Solve scope where possible.
    """
    from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
        PersistentSelectionService,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
        TopologyEntityKind,
    )

    svc = PersistentSelectionService(ocaf_session)
    created = 0
    selection_feature_map: dict[str, tuple[str, str]] = {}
    for spec in selection_specs:
        try:
            handle_id = ctx.resolve_component_output(spec.component_id, "body")
            body = ctx.object_store.get(handle_id)
            # Normalize a Workplane to its underlying Shape/Solid.
            if hasattr(body, "val") and not hasattr(body, "wrapped"):
                body = body.val()

            policy = spec.policy
            entity_kind = (
                policy.entity_kind if policy is not None else TopologyEntityKind.FACE
            )
            if entity_kind == TopologyEntityKind.EDGE:
                if not getattr(spec, "edge_selector", ""):
                    raise ValueError(
                        f"edge selection {spec.selection_id!r} requires edge_selector"
                    )
                selected_wrapped = body.edges(spec.edge_selector).wrapped
                selection_feature_map[spec.selection_id] = (
                    spec.component_id,
                    _resolve_component_terminal_node(ctx, spec.component_id),
                )
            else:
                role_key = getattr(spec, "role_key", None)
                if role_key:
                    feature_node_id = _resolve_role_node(
                        ctx, spec.component_id, role_key,
                    )
                    selected_wrapped = _resolve_role_face(
                        ctx, spec.component_id, role_key
                    )
                    selection_feature_map[spec.selection_id] = (
                        spec.component_id, feature_node_id,
                    )
                else:
                    selected_wrapped = body.faces(spec.face_selector).wrapped
                    selection_feature_map[spec.selection_id] = (
                        spec.component_id,
                        _resolve_component_terminal_node(ctx, spec.component_id),
                    )

            svc.create(
                spec.selection_id, selected_wrapped, body.wrapped,
                spec.policy, spec.contract,
            )
            created += 1
        except Exception as exc:
            ctx.warnings.append(
                f"selection create failed for {spec.selection_id}: {exc}"
            )
    if created:
        ctx.warnings.append(f"created {created} persistent selection(s)")
    svc.selection_feature_map = selection_feature_map
    return svc


def _resolve_role_face(ctx: RuntimeContext, component_id: str, role_key: str):
    """Resolve a named role face from the captured batches of a component.

    The role face is a live TopoDS_Shape stored in a tracked batch's
    construction_roles. It is only available while the capture session is still
    alive in the current run (selection creation happens inside the same run).
    """
    if ctx.capture_session is None:
        raise KeyError("no capture session available for role resolution")
    for batch in ctx.capture_session.iter_batches():
        if batch.scope.component_id != component_id:
            continue
        roles = batch.construction_roles or {}
        face = roles.get(role_key)
        if face is not None:
            return face
    raise KeyError(
        f"role {role_key!r} not found for component {component_id!r}"
    )


def _resolve_role_node(ctx: RuntimeContext, component_id: str, role_key: str):
    """Return the feature node id that owns a named role face."""
    if ctx.capture_session is None:
        raise KeyError("no capture session available for role resolution")
    for batch in ctx.capture_session.iter_batches():
        if batch.scope.component_id != component_id:
            continue
        roles = batch.construction_roles or {}
        if roles.get(role_key) is not None:
            return batch.scope.node_id
    raise KeyError(
        f"role {role_key!r} not found for component {component_id!r}"
    )


def _resolve_component_terminal_node(
    ctx: RuntimeContext, component_id: str,
) -> str | None:
    """Return the last captured feature node for a component, if available."""
    if ctx.capture_session is None:
        return None
    batches = [
        batch for batch in ctx.capture_session.iter_batches()
        if batch.scope.component_id == component_id
    ]
    if not batches:
        return None
    return batches[-1].scope.node_id


def _resolve_edge_role(ctx: RuntimeContext, component_id: str, edge_role_key: str):
    """Resolve a named edge role from the captured batches of a component."""
    if ctx.capture_session is None:
        raise KeyError("no capture session available for edge role resolution")
    for batch in ctx.capture_session.iter_batches():
        if batch.scope.component_id != component_id:
            continue
        edge_roles = getattr(batch, "edge_roles", {}) or {}
        edge = edge_roles.get(edge_role_key)
        if edge is not None:
            return edge
    raise KeyError(
        f"edge role {edge_role_key!r} not found for component {component_id!r}"
    )


def _build_feature_dependency_map(canonical: Any) -> dict:
    """Build (component_id, feature_id) -> upstream feature refs from IR."""
    if canonical is None:
        return {}
    nodes = getattr(canonical, "nodes", ()) or ()
    ref_by_node = {n.id: (n.component, n.id) for n in nodes}
    dependency_map: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for node in nodes:
        deps: list[tuple[str, str]] = []
        for inp in getattr(node, "inputs", ()) or ():
            producer_node = getattr(inp, "producer_node", None)
            if producer_node and producer_node in ref_by_node:
                deps.append(ref_by_node[producer_node])
        dependency_map[(node.component, node.id)] = deps
    return dependency_map


def _run_ocaf_write_and_save(
    ctx: RuntimeContext,
    ocaf_session: Any,
    ocaf_path: Path,
    *,
    topology_config: Any = None,
    canonical: Any = None,
) -> bool:
    """Write captured topology batches to OCAF, persist index, verify, and save.

    v5.0 §6.3: correct order — begin → write → index → commit → save → verify → publish.
    Returns True on success.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
            TopologyNamingWriter,
        )
        # 1. Begin transaction
        ocaf_session.begin_write()

        # 2. Write history with previous_result for non-initial revisions
        writer = TopologyNamingWriter(ocaf_session)
        for batch in ctx.capture_session.iter_batches():
            # v6.0 §8.1: inject previous_result for existing features
            scope = batch.scope
            feat_label = writer._ensure_feature_label(scope.component_id, scope.node_id)
            prev = ocaf_session.get_current_result_shape(feat_label)
            writer.write_batch(batch, previous_result=prev)

        # 2.5 v7 T12-a: create persistent selections from specs (inside txn)
        selection_svc = None
        if topology_config is not None:
            selection_specs = list(getattr(topology_config, 'selection_specs', ()))
            if selection_specs:
                selection_svc = _create_selections_from_specs(
                    ctx, ocaf_session, selection_specs,
                )
                selection_feature_map = getattr(
                    selection_svc, "selection_feature_map", {},
                )
            else:
                selection_feature_map = {}
        else:
            selection_feature_map = {}

        # 3. Persist StableLabelIndex to OCAF (P0-02)
        ocaf_session.label_index.save_to_ocaf(ocaf_session.main_label)

        # 4. Commit
        ocaf_session.commit_write()

        # 5. Save to temp
        temp = ocaf_session.save_temp()

        # 6. CAE preflight gate (v6.0 §8.3: use real bindings, not faked)
        cae_ok = True
        if topology_config is not None:
            bindings = list(getattr(topology_config, 'cae_bindings', ()))
            # Fallback: legacy required_cae_binding_ids
            if not bindings and getattr(topology_config, 'required_cae_binding_ids', ()):
                from seekflow_engineering_tools.generative_cad.topology.ocaf.models import CaeBinding
                for bid in topology_config.required_cae_binding_ids:
                    bindings.append(CaeBinding(
                        binding_id=bid, selection_id=bid, analysis_role="load",
                        required=True,
                    ))
            if bindings:
                try:
                    from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import (
                        run_cae_preflight,
                    )
                    from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
                        PersistentSelectionService,
                    )
                    svc = selection_svc or PersistentSelectionService(ocaf_session)
                    from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
                        collect_tnaming_labels,
                    )
                    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
                        EvolutionKind,
                    )
                    selection_component_map = {
                        spec.selection_id: spec.component_id
                        for spec in selection_specs
                    }
                    relevant_components = {
                        selection_component_map[b.selection_id]
                        for b in bindings
                        if b.selection_id in selection_component_map
                    }
                    seed_refs: list[tuple[str, str]] = []
                    missing_feature_ref = False
                    for binding in bindings:
                        component_id = selection_component_map.get(binding.selection_id)
                        if component_id is None:
                            continue
                        feature_ref = selection_feature_map.get(binding.selection_id)
                        if feature_ref and feature_ref[0] == component_id and feature_ref[1]:
                            seed_refs.append(feature_ref)
                        else:
                            missing_feature_ref = True

                    dependency_map = _build_feature_dependency_map(canonical)
                    if seed_refs and dependency_map and not missing_feature_ref:
                        label_map = ocaf_session.collect_feature_dependency_labels(
                            seed_refs, dependency_map,
                        )
                    elif relevant_components:
                        label_map = collect_tnaming_labels(
                            ocaf_session.design_root_label,
                            restrict_to=[
                                ocaf_session.ensure_component(cid)
                                for cid in relevant_components
                            ],
                        )
                    else:
                        label_map = collect_tnaming_labels(ocaf_session.design_root_label)
                    deleted_shapes = tuple(
                        r.old_shape
                        for b in ctx.capture_session.iter_batches()
                        for r in b.relations
                        if r.kind == EvolutionKind.DELETED and r.old_shape is not None
                    )
                    preflight = run_cae_preflight(
                        bindings, svc, label_map,
                        deleted_shapes=deleted_shapes,
                        history_complete=ctx.capture_session.history_complete,
                    )
                    if not preflight.ok:
                        cae_ok = False
                        for err in preflight.errors:
                            ctx.warnings.append(f"CAE preflight: {err}")
                except Exception as exc:
                    ctx.warnings.append(f"CAE preflight error: {exc}")
                    cae_ok = False

        # 7. Verify in subprocess (v5.0 §6.6)
        verify_ok = True
        if topology_config is not None and getattr(topology_config, "verify_in_subprocess", False):
            from seekflow_engineering_tools.generative_cad.topology.ocaf.verify_worker import (
                verify_xbf,
            )
            vresult = verify_xbf(temp)
            if not vresult.ok:
                verify_ok = False
                if vresult.native_crash:
                    ctx.warnings.append(f"OCAF verify: native crash detected in {temp}")
                for err in vresult.errors:
                    ctx.warnings.append(f"OCAF verify: {err}")

        # 8. Close session FIRST to release file handles (v6.0 §7.3)
        ocaf_session.close()

        # 9. Publish (on verify + CAE success or skipped)
        all_ok = verify_ok and cae_ok
        if all_ok:
            ocaf_session.publish(temp, ocaf_path)
        else:
            ctx.warnings.append(f"OCAF gates failed for {temp}, XBF not published")

        if not all_ok and ctx.topology_mode == "enforce":
            return False
        return True
    except Exception as exc:
        msg = f"OCAF write/save failed: {exc}"
        if ctx.topology_mode == "enforce":
            raise
        ctx.warnings.append(msg)
        return False


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
    ocaf_path: str | Path | None = None,  # deprecated — use topology=TopologyRunConfig(...)
    topology: Any = None,  # TopologyRunConfig | None — v5.0 §6.2 formal config
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

    # ── v5.0 §6.2: TopologyRunConfig — formal pipeline config ──
    _topology_config = topology  # TopologyRunConfig | None
    _ocaf_target: Path | None = None

    # Backwards-compat: deprecated ocaf_path → auto-create TopologyRunConfig
    if _topology_config is None and ocaf_path is not None:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            TopologyRunConfig,
        )
        _topology_config = TopologyRunConfig(
            mode="audit",
            verify_in_subprocess=False,
        )
        _ocaf_target = Path(ocaf_path)

    # v7 IR integration: canonical IR selections/bindings override the config.
    if _topology_config is not None and _topology_config.mode != "off":
        from dataclasses import replace
        canon_sels = _selections_from_canonical(canonical)
        canon_binds = _bindings_from_canonical(canonical)
        if canon_sels or canon_binds:
            _topology_config = replace(
                _topology_config,
                selection_specs=(canon_sels if canon_sels else _topology_config.selection_specs),
                cae_bindings=(canon_binds if canon_binds else _topology_config.cae_bindings),
            )

    if _topology_config is not None and _topology_config.mode != "off":
        if _ocaf_target is None:
            _ocaf_target = _topology_config.ocaf_path
        if _ocaf_target is None and ocaf_path is not None:
            _ocaf_target = Path(ocaf_path)

        if ctx.topology_mode == "off":
            ctx.topology_mode = _topology_config.mode
        from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import (
            CaptureSession,
        )
        ctx.enable_topology_capture = True
        ctx.capture_session = CaptureSession()
        # ★ OcafDocumentSession creation deferred to AFTER postcheck (v5.0 §6.3)

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

        # ════════════════════════════════════════════════════════════
        # v6.3: STEP export + geometry postcheck (BEFORE OCAF — v5.0 §6.3)
        # ════════════════════════════════════════════════════════════
        _export_final_solid(final_handle_id, ctx)

        from seekflow_engineering_tools.generative_cad.runtime.geometry_postcheck import (
            validate_final_geometry,
            validate_step_post_export,
        )
        geo_postcheck = validate_final_geometry(
            ctx, final_handle_id,
            expected_body_count=canonical.constraints.expected_body_count,
        )
        step_postcheck = validate_step_post_export(out_step, min_size_bytes=200)

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
                    repairability="non_repairable",
                ) for msg in step_postcheck.errors],
            )

        # ════════════════════════════════════════════════════════════
        # v5.0 §6.3: OCAF topology — AFTER STEP/postcheck gates pass
        # ════════════════════════════════════════════════════════════
        if _topology_config is not None and _topology_config.mode != "off" and ctx.capture_session is not None:
            from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
                OcafDocumentSession,
            )
            # Create/open OCAF session at the RIGHT time
            if _ocaf_target is not None and _ocaf_target.exists():
                _ocaf_session = OcafDocumentSession.open(_ocaf_target)
            else:
                _ocaf_session = OcafDocumentSession.create()

            ocaf_ok = _run_ocaf_write_and_save(
                ctx, _ocaf_session, _ocaf_target or Path("design.xbf"),
                topology_config=_topology_config,
                canonical=canonical,
            )
            if not ocaf_ok and ctx.topology_mode == "enforce":
                return _fail_result(
                    ctx,
                    stage="ocaf_write",
                    error="OCAF write/save failed in enforce mode",
                    issues=[RuntimeIssue(
                        stage="ocaf_write",
                        code="ocaf_write_failed",
                        message="OCAF topology write or save failed",
                        repairability="conditionally_repairable",
                    )],
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


def run_lineage_revisions(
    *,
    lineage_id: str,
    output_root: str | Path,
    revisions: list[dict],
) -> list[GcadRunResult]:
    """Run a design lineage across multiple revisions with immutable snapshots.

    Each ``revisions`` entry is a dict:
      - ``canonical``: CanonicalGcadDocument for this revision.
      - ``validation_seed``: dict — the validation proof for this canonical.
      - ``selection_specs``: optional iterable of SelectionSpec (Rev1 creates;
        later revisions typically omit it and solve existing selections).

    The same lineage_id/output_root is used for every revision so the OCAF
    document evolves in place (open previous -> Modify). Each successful
    revision is published to an immutable RevisionStore snapshot.
    """
    import shutil

    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
        TopologyRunConfig,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.revision_store import (
        RevisionStore,
    )

    output_root = Path(output_root)
    store = RevisionStore(output_root, lineage_id)
    store.init_lineage()

    results: list[GcadRunResult] = []
    for i, rev in enumerate(revisions, 1):
        canonical = rev["canonical"]
        validation_seed = rev["validation_seed"]
        selection_specs = tuple(rev.get("selection_specs", ()))

        staging = store.staging_dir(i)
        staging.mkdir(parents=True, exist_ok=True)
        out_step = staging / "model.step"
        metadata_path = staging / "metadata.json"

        config = TopologyRunConfig(
            mode="enforce",
            lineage_id=lineage_id,
            revision_id=store.format_revision_id(i),
            parent_revision_id=store.format_revision_id(i - 1) if i > 1 else None,
            output_root=output_root,
            selection_specs=selection_specs,
            verify_in_subprocess=False,
        )

        result = run_canonical_gcad(
            canonical,
            out_step=out_step,
            metadata_path=metadata_path,
            validation_seed=validation_seed,
            topology=config,
        )
        results.append(result)
        if not result.ok:
            continue

        # Snapshot the evolving OCAF XBF into the immutable revision bundle.
        evolving_xbf = config.ocaf_path
        if evolving_xbf is not None and evolving_xbf.exists():
            shutil.copy2(str(evolving_xbf), str(staging / "design.xbf"))
        store.publish_revision(
            staging, i, step_path=out_step, metadata_path=metadata_path,
        )

    return results


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
    # 数据集字段 MBRep：导出原生 B-rep（与 STEP 同一实体；容错，失败不阻塞）
    try:
        ctx.geometry_runtime.export_brep(obj, ctx.out_step.parent / "output.brep")
    except Exception:
        pass
