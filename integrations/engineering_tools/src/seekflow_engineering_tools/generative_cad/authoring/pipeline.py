"""End-to-end authoring pipeline — mocked LLM, real validation.

For production use, inject a real LlmToolCaller implementation.
For testing, use mock callers that return pre-scripted ToolCallResults.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.context_builder import (
    AuthoringContext,
    build_authoring_context,
)
from seekflow_engineering_tools.generative_cad.authoring.failure_taxonomy import (
    AuthoringFailure,
    AuthoringFailureCode,
    map_validation_issue_to_failure,
)
from seekflow_engineering_tools.generative_cad.authoring.metrics import (
    AuthoringRunMetrics,
)
from seekflow_engineering_tools.generative_cad.authoring.prompt_builders import (
    FEATURE_SEQUENCE_SYSTEM_PROMPT,
    NODE_PARAMS_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    ROUTE_SYSTEM_PROMPT,
    _build_dialect_summary,
    _build_op_contract,
    _build_operation_summary,
    build_feature_sequence_user_prompt,
    build_node_params_user_prompt,
    build_repair_user_prompt,
    build_route_user_prompt,
)
from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import (
    assemble_raw_gcad_document,
)
from seekflow_engineering_tools.generative_cad.authoring.schemas import (
    FeatureSequenceDraft,
    NodeParamsDraft,
    RawAssemblyResult,
    RoutePlan,
)
from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig
from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import (
    build_feature_sequence_tool_schema,
    build_node_params_tool_schema,
    build_repair_patch_tool_schema,
    build_route_plan_tool_schema,
)
from seekflow_engineering_tools.generative_cad.llm.provider import (
    LlmToolCaller,
    ToolCallResult,
)


class AuthoringPipelineResult:
    """Result of a full authoring pipeline run."""

    def __init__(self):
        self.route_plan: RoutePlan | None = None
        self.feature_sequence: FeatureSequenceDraft | None = None
        self.node_params: dict[str, NodeParamsDraft] = {}
        self.raw_assembly: RawAssemblyResult | None = None
        self.canonical_document: Any = None
        self.validation_bundle: Any = None
        self.metrics: AuthoringRunMetrics = AuthoringRunMetrics()
        self.failures: list[AuthoringFailure] = []
        # v6: Spatial frontend result
        self.spatial_frontend: Any = None


# ── Mock callers for testing ────────────────────────────────────────────────


class MockRouteCaller:
    """Returns a fixed RoutePlan."""

    def __init__(self, route_plan: RoutePlan):
        self._plan = route_plan

    def call_strict_tool(self, **kwargs) -> ToolCallResult:
        return ToolCallResult(
            tool_name="emit_route_plan",
            arguments=self._plan.model_dump(),
            model="mock-router",
            provider="mock",
        )


class MockFeatureSequenceCaller:
    """Returns a fixed FeatureSequenceDraft."""

    def __init__(self, fs: FeatureSequenceDraft):
        self._fs = fs

    def call_strict_tool(self, **kwargs) -> ToolCallResult:
        return ToolCallResult(
            tool_name="emit_feature_sequence",
            arguments=self._fs.model_dump(),
            model="mock-author",
            provider="mock",
        )


class MockNodeParamsCaller:
    """Returns fixed NodeParamsDrafts keyed by node_id."""

    def __init__(self, param_map: dict[str, NodeParamsDraft]):
        self._map = param_map
        self._call_count = 0
        self._keys = list(param_map.keys())

    def call_strict_tool(self, **kwargs) -> ToolCallResult:
        if self._call_count >= len(self._keys):
            raise RuntimeError("MockNodeParamsCaller exhausted")
        key = self._keys[self._call_count]
        self._call_count += 1
        np = self._map[key]
        return ToolCallResult(
            tool_name="emit_node_params",
            arguments=np.model_dump(),
            model="mock-author",
            provider="mock",
        )


class MockRepairCaller:
    """Returns empty repair (give_up)."""

    def call_strict_tool(self, **kwargs) -> ToolCallResult:
        return ToolCallResult(
            tool_name="emit_repair_patch",
            arguments={"give_up": True, "reason": "mock repair", "changes": []},
            model="mock-repair",
            provider="mock",
        )


# ── Pipeline ────────────────────────────────────────────────────────────────


def generate_gcad_from_user_request(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry,
    base_package_registry,
    route_caller: LlmToolCaller | None = None,
    feature_sequence_caller: LlmToolCaller | None = None,
    node_params_caller: LlmToolCaller | None = None,
    repair_caller: LlmToolCaller | None = None,
    primitive_catalog_summary: dict | None = None,
    max_repair_attempts: int = 3,
    # v6: Spatial frontend
    enable_spatial_frontend: bool = False,
    spatial_mode: str = "guided",
    spatial_user_answers: list | None = None,
    spatial_session_state: Any = None,
    question_budget: int = 3,
    object_graph_caller: LlmToolCaller | None = None,
    spatial_plan_caller: LlmToolCaller | None = None,
    question_caller: LlmToolCaller | None = None,
    answer_normalizer_caller: LlmToolCaller | None = None,
) -> AuthoringPipelineResult:
    """Run the full staged authoring pipeline.

    If callers are not provided, the pipeline validates pre-loaded data
    from route_plan, feature_sequence, and node_params in metrics only.
    Production usage requires injecting real LlmToolCaller instances.

    v6: enable_spatial_frontend=True adds Stage 0 spatial intent resolution
    before routing. Single-component cases automatically skip the frontend.
    """
    result = AuthoringPipelineResult()
    metrics = result.metrics
    metrics.model_router = llm_config.router.model
    metrics.model_author = llm_config.author.model
    metrics.model_repair = llm_config.repair.model

    # ════════════════════════════════════════════════════════════
    # v6: Stage 0 — Spatial Frontend
    # ════════════════════════════════════════════════════════════
    if enable_spatial_frontend and object_graph_caller is not None:
        try:
            from seekflow_engineering_tools.generative_cad.authoring.spatial.pipeline import (
                run_spatial_authoring_frontend,
            )
            spatial_result = run_spatial_authoring_frontend(
                user_request=user_request,
                llm_config=llm_config,
                dialect_registry=dialect_registry,
                base_package_registry=base_package_registry,
                object_graph_caller=object_graph_caller,
                spatial_plan_caller=spatial_plan_caller,
                question_caller=question_caller,
                answer_normalizer_caller=answer_normalizer_caller,
                user_answers=spatial_user_answers,
                session_state=spatial_session_state,
                mode=spatial_mode,
                question_budget=question_budget,
            )
            result.spatial_frontend = spatial_result

            if spatial_result.needs_clarification:
                # Do not continue to CAD generation; return questions to UI layer
                result.failures.append(AuthoringFailure(
                    code=AuthoringFailureCode(
                        getattr(AuthoringFailureCode, 'NEEDS_SPATIAL_CLARIFICATION', 'PROVIDER_NO_TOOL_CALL')
                    ),
                    stage="spatial_frontend",
                    message="spatial clarification needed — present questions to user",
                ))
                return result
        except Exception as exc:
            result.failures.append(AuthoringFailure(
                code=AuthoringFailureCode.CONTEXT_BUILD_ERROR,
                stage="spatial_frontend",
                message=f"spatial frontend failed: {exc}",
            ))
    # ════════════════════════════════════════════════════════════

    # ── Stage 1: Route ──
    if route_caller is not None:
        try:
            dialect_summary = _build_dialect_summary(dialect_registry)
            tc_result = route_caller.call_strict_tool(
                messages=[
                    {"role": "system", "content": ROUTE_SYSTEM_PROMPT},
                    {"role": "user", "content": build_route_user_prompt(user_request, dialect_summary)},
                ],
                tool_name="emit_route_plan",
                tool_description="Select CAD route and dialects",
                tool_schema=build_route_plan_tool_schema(
                    dialect_registry=dialect_registry,
                ),
                model_config=llm_config.router,
            )
            route_plan = RoutePlan.model_validate(tc_result.arguments)
            metrics.route_success = True
        except Exception as exc:
            result.failures.append(AuthoringFailure(
                code=AuthoringFailureCode.PROVIDER_NO_TOOL_CALL,
                stage="route", message=str(exc),
            ))
            return result
    else:
        route_plan = None  # type: ignore[assignment]

    result.route_plan = route_plan

    if route_plan is None:
        result.failures.append(AuthoringFailure(
            code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
            stage="route", message="No route_plan produced",
        ))
        return result

    # Stop early for non-generative routes
    if route_plan.route_decision.value != "generative_cad_ir":
        return result

    # ── Stage 2: Build context ──
    try:
        ctx = build_authoring_context(
            route_plan=route_plan,
            dialect_registry=dialect_registry,
            base_package_registry=base_package_registry,
        )
        metrics.context_hash = ctx.context_hash
        metrics.selected_base_packages = ctx.selected_dialects
    except Exception as exc:
        result.failures.append(AuthoringFailure(
            code=AuthoringFailureCode.CONTEXT_BUILD_ERROR,
            stage="context", message=str(exc),
        ))
        return result

    # ── Stage 3: Feature sequence ──
    if feature_sequence_caller is not None:
        try:
            operation_summary = _build_operation_summary(ctx)
            tc_result = feature_sequence_caller.call_strict_tool(
                messages=[
                    {"role": "system", "content": FEATURE_SEQUENCE_SYSTEM_PROMPT},
                    {"role": "user", "content": build_feature_sequence_user_prompt(
                        user_request, route_plan, ctx, operation_summary,
                    )},
                ],
                tool_name="emit_feature_sequence",
                tool_description="Plan operation sequence",
                tool_schema=build_feature_sequence_tool_schema(ctx),
                model_config=llm_config.author,
            )
            fs = FeatureSequenceDraft.model_validate(tc_result.arguments)
            metrics.feature_sequence_success = True
        except Exception as exc:
            result.failures.append(AuthoringFailure(
                code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
                stage="feature_sequence", message=str(exc),
            ))
            return result
    else:
        fs = None  # type: ignore[assignment]

    result.feature_sequence = fs
    if fs is None:
        return result

    # ── Stage 4: Node params (per node) ──
    if node_params_caller is not None:
        param_map: dict[str, NodeParamsDraft] = {}
        total = len(fs.node_sequence)
        ok_count = 0
        for node_plan in fs.node_sequence:
            try:
                op_contract = _build_op_contract(node_plan, dialect_registry)
                tc_result = node_params_caller.call_strict_tool(
                    messages=[
                        {"role": "system", "content": NODE_PARAMS_SYSTEM_PROMPT},
                        {"role": "user", "content": build_node_params_user_prompt(
                            user_request, route_plan, fs, node_plan, op_contract,
                        )},
                    ],
                    tool_name="emit_node_params",
                    tool_description=f"Fill params for {node_plan.op}",
                    tool_schema=build_node_params_tool_schema(node_plan, dialect_registry),
                    model_config=llm_config.author,
                )
                np = NodeParamsDraft.model_validate(tc_result.arguments)

                # ── Strict consistency checks ──
                if np.node_id != node_plan.node_id:
                    raise ValueError(
                        f"NodeParamsDraft node_id {np.node_id!r} != "
                        f"expected {node_plan.node_id!r}"
                    )
                if np.dialect != node_plan.dialect:
                    raise ValueError(
                        f"NodeParamsDraft dialect {np.dialect!r} != "
                        f"expected {node_plan.dialect!r}"
                    )
                if np.op != node_plan.op:
                    raise ValueError(
                        f"NodeParamsDraft op {np.op!r} != "
                        f"expected {node_plan.op!r}"
                    )
                if np.op_version != node_plan.op_version:
                    raise ValueError(
                        f"NodeParamsDraft op_version {np.op_version!r} != "
                        f"expected {node_plan.op_version!r}"
                    )

                # Validate params against OperationSpec
                dialect = dialect_registry.get(np.dialect)
                if dialect:
                    spec = dialect.get_op_spec(np.op, np.op_version)
                    spec.validate_params(np.params)
                param_map[node_plan.node_id] = np
                ok_count += 1
            except Exception as exc:
                result.failures.append(AuthoringFailure(
                    code=AuthoringFailureCode.PARAMS_TYPE_ERROR,
                    stage=f"node_params:{node_plan.node_id}",
                    message=str(exc),
                    node_id=node_plan.node_id,
                    dialect=node_plan.dialect,
                    op=node_plan.op,
                ))

        result.node_params = param_map
        metrics.params_success_rate = ok_count / total if total > 0 else 0.0

    # ── Stage 5: Assemble RawGcadDocument ──
    try:
        assembly = assemble_raw_gcad_document(
            user_request=user_request,
            route_plan=route_plan,
            feature_sequence=fs,
            node_params=result.node_params,
            dialect_registry=dialect_registry,
        )
        result.raw_assembly = assembly
        metrics.raw_assembly_success = True
    except Exception as exc:
        result.failures.append(AuthoringFailure(
            code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
            stage="assembly", message=str(exc),
        ))
        return result

    # ── Stage 6: Parse + Validate + Canonicalize ──
    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize_with_bundle,
    )

    canonical, report, bundle = validate_and_canonicalize_with_bundle(
        assembly.raw_document,
    )
    metrics.parse_success = canonical is not None or (report is not None)
    metrics.validation_success = report.ok if report else False
    metrics.canonicalize_success = canonical is not None

    if canonical:
        result.canonical_document = canonical
        result.validation_bundle = bundle

    if not metrics.validation_success and report:
        for issue in (report.issues or []):
            failure = map_validation_issue_to_failure(
                issue.model_dump() if hasattr(issue, "model_dump") else issue,
                stage=getattr(issue, "stage", "validation"),
            )
            result.failures.append(failure)

    # ── Stage 7a: Deterministic autofix (before LLM repair) ──
    if not metrics.validation_success:
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix
        try:
            fixed_doc = auto_fix(assembly.raw_document, dialect_registry)
            canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed_doc)
            if canonical and report.ok:
                metrics.validation_success = True
                metrics.canonicalize_success = True
                result.canonical_document = canonical
                result.validation_bundle = bundle
                # Update assembly raw_document to the fixed version
                assembly.raw_document = fixed_doc
        except Exception:
            pass  # autofix failed, fall through to LLM repair
    # ── Stage 7b: LLM Repair loop ──
    if not metrics.validation_success and repair_caller is not None:
        from seekflow_engineering_tools.generative_cad.repair.governor import (
            RepairStateV2,
            can_repair_v2,
            stage_rank_for,
            update_repair_state_v2,
        )
        from seekflow_engineering_tools.generative_cad.repair.patch import (
            RepairPatchV2,
            apply_repair_patch_v2,
        )

        state = RepairStateV2(max_attempts=max_repair_attempts)
        current_doc = assembly.raw_document

        for _attempt in range(max_repair_attempts):
            metrics.repair_attempts += 1

            # Compute repair state hashes
            from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
            raw_hash = stable_hash(current_doc)
            error_sig = stable_hash(
                [(i.code if hasattr(i, 'code') else i.get('code', ''))
                 for i in (report.issues if report else [])]
            )

            # Determine stage rank (单一来源: validation_kernel/stages.py)
            stage_name = report.stage if report and hasattr(report, 'stage') else "structure"
            stage_rank = stage_rank_for(stage_name)

            # Check if repair is still allowed
            can, reason = can_repair_v2(
                state,
                raw_graph_hash=raw_hash,
                error_sig_hash=error_sig,
                current_stage_rank=stage_rank,
            )
            if not can:
                result.failures.append(AuthoringFailure(
                    code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
                    stage="repair", message=f"Repair stopped: {reason}",
                ))
                break

            # Get repair patch from LLM
            try:
                # Convert ValidationIssue objects to dict for prompt
                issues_dicts: list[dict] = []
                if report and hasattr(report, "issues"):
                    for i in report.issues:
                        if hasattr(i, "model_dump"):
                            issues_dicts.append(i.model_dump())
                        elif isinstance(i, dict):
                            issues_dicts.append(i)
                        else:
                            issues_dicts.append({
                                "code": getattr(i, "code", ""),
                                "message": getattr(i, "message", ""),
                                "stage": getattr(i, "stage", ""),
                                "node_id": getattr(i, "node_id", None),
                            })
                tc_result = repair_caller.call_strict_tool(
                    messages=[
                        {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                        {"role": "user", "content": build_repair_user_prompt(
                            current_doc=current_doc,
                            validation_issues=issues_dicts,
                        )},
                    ],
                    tool_name="emit_repair_patch",
                    tool_description="Local repair patch",
                    tool_schema=build_repair_patch_tool_schema(),
                    model_config=llm_config.repair,
                )
                if tc_result.arguments.get("give_up"):
                    break
                patch = RepairPatchV2.model_validate(tc_result.arguments)
            except Exception as exc:
                result.failures.append(AuthoringFailure(
                    code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
                    stage="repair", message=str(exc),
                ))
                break

            # Apply patch (副本上应用 — apply_repair_patch_v2 内部 deepcopy)
            try:
                candidate_doc = apply_repair_patch_v2(current_doc, patch)
            except Exception as exc:
                result.failures.append(AuthoringFailure(
                    code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
                    stage="repair:apply", message=str(exc),
                ))
                break

            # Revalidate + 质量验收 (标准 6: LLM 补丁与确定性修复同一验收合同 —
            # 质量向量严格改善才提交, 否则丢弃候选保留原文档, 防止补丁越修越坏)
            from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
                QualityVector, is_strict_improvement,
            )
            q_before = QualityVector.from_report(report) if report else None
            baseline_codes = {getattr(i, "code", "") for i in (report.issues if report else [])
                              if getattr(i, "severity", "") == "error"}
            canonical_c, report_c, bundle_c = validate_and_canonicalize_with_bundle(candidate_doc)
            q_after = QualityVector.from_report(report_c, baseline_error_codes=baseline_codes)

            if canonical_c and report_c.ok:
                current_doc = candidate_doc
                canonical, report, bundle = canonical_c, report_c, bundle_c
                metrics.validation_success = True
                metrics.canonicalize_success = True
                result.canonical_document = canonical
                result.validation_bundle = bundle
                break
            if q_before is None or is_strict_improvement(q_before, q_after):
                # 未达 ok 但严格改善 → 提交候选, 继续下一轮
                current_doc = candidate_doc
                canonical, report, bundle = canonical_c, report_c, bundle_c
            else:
                result.failures.append(AuthoringFailure(
                    code=AuthoringFailureCode.LOCAL_SCHEMA_ERROR,
                    stage="repair:rejected",
                    message=(f"patch rejected: quality not strictly improved "
                             f"(before={q_before.key()} after={q_after.key()})"),
                ))
                # 候选丢弃 (原子回滚): current_doc/report 保持不变

            state = update_repair_state_v2(
                state,
                raw_graph_hash=raw_hash,
                error_sig_hash=error_sig,
                stage_rank=stage_rank,
            )

    # Final failure code
    if result.failures:
        metrics.final_failure_code = result.failures[-1].code.value

    return result
