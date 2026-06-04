"""Spatial Frontend Pipeline — Phase A entry point.

Runs after RoutePlan, before FeatureSequence.
Orchestrates: object graph extraction → archetype matching → constraint graph →
solver → validation → clarification loop.
"""

from __future__ import annotations
import uuid

from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig
from seekflow_engineering_tools.generative_cad.llm.provider import LlmToolCaller
from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry
from seekflow_engineering_tools.generative_cad.base_packages.registry import BasePackageRegistry
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialConstraintGraph,
    SpatialFrontendResult,
    SpatialModeType,
    SpatialSessionState,
    AssumptionLedger,
    AssumptionEntry,
    UserSpatialAnswer,
    SpatialFinalStatus,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.constraint_graph import (
    build_constraint_graph,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.solver import (
    validate_constraint_graph,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.validators import (
    validate_spatial_contract_phase_a,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import (
    default_archetypes,
)


def run_spatial_authoring_frontend(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry: DialectRegistry,
    base_package_registry: BasePackageRegistry,
    object_graph_caller: LlmToolCaller | None = None,
    spatial_plan_caller: LlmToolCaller | None = None,
    question_caller: LlmToolCaller | None = None,
    answer_normalizer_caller: LlmToolCaller | None = None,
    user_answers: list[UserSpatialAnswer] | None = None,
    session_state: SpatialSessionState | None = None,
    mode: SpatialModeType = "guided",
    question_budget: int = 3,
) -> SpatialFrontendResult:
    """Phase A: Spatial intent resolution.

    Multi-round flow:
    1. First round (no session_state): LLM extracts object_graph → maybe clarification
    2. If clarification needed: return questions + session_state (caller persists)
    3. Subsequent round: pass user_answers + session_state → restore → resolve → continue

    Single-component case: automatically skipped (returns empty success).
    """
    failures: list[str] = []
    ledger = AssumptionLedger()

    # ── Step 1: Restore or extract object graph ──
    object_graph: MechanicalObjectGraphDraft | None = None

    if session_state is not None:
        object_graph = MechanicalObjectGraphDraft.model_validate_json(
            session_state.object_graph_json
        )
        ledger = AssumptionLedger.model_validate_json(session_state.ledger_json)

    if object_graph is None:
        if object_graph_caller is None:
            return SpatialFrontendResult(
                ok=False,
                failures=["object_graph_caller is required for initial round"],
            )
        object_graph = _extract_object_graph(
            user_request, object_graph_caller, llm_config, mode
        )
        if object_graph is None:
            return SpatialFrontendResult(
                ok=False,
                failures=["failed to extract MechanicalObjectGraphDraft"],
            )

    # ── Single-component fast path ──
    if len(object_graph.components) <= 1:
        return SpatialFrontendResult(
            ok=True,
            final_status="VERIFIED",
            object_graph=object_graph,
            assumption_ledger=ledger,
        )

    # ── Step 2: Archetype matching ──
    _apply_archetypes(object_graph, mode, ledger)

    # ── Step 3: Process user answers (subsequent rounds) ──
    if user_answers:
        from seekflow_engineering_tools.generative_cad.authoring.spatial.answer_normalizer import (
            normalize_answers,
        )
        normalized_list = normalize_answers(
            user_answers, object_graph, answer_normalizer_caller, llm_config
        )
        for na in normalized_list:
            object_graph.candidate_relations.extend(na.relations_added)
            for assumption_text in na.assumptions_added:
                ledger.add(AssumptionEntry(
                    assumption_id=f"user_answer_{na.question_id}",
                    statement=assumption_text,
                    source="user_selected_option",
                    confidence=0.9,
                    user_confirmed=True,
                ))

    # ── Step 4: Build SpatialConstraintGraph ──
    constraint_graph = build_constraint_graph(object_graph)

    # ── Step 5: Phase A solver consistency check ──
    solver_report = validate_constraint_graph(constraint_graph)
    if not solver_report.ok:
        return SpatialFrontendResult(
            ok=False,
            object_graph=object_graph,
            constraint_graph=constraint_graph,
            solver_report=solver_report,
            assumption_ledger=ledger,
            failures=[f"solver error: {i.message}" for i in solver_report.issues],
        )

    # ── Step 6: Clarification needed? ──
    if object_graph.unknowns and mode in ("guided", "precision"):
        from seekflow_engineering_tools.generative_cad.authoring.spatial.question_planner import (
            plan_questions,
        )
        questions = plan_questions(object_graph, budget=question_budget)
        if questions:
            session = SpatialSessionState(
                session_id=(
                    session_state.session_id if session_state
                    else f"spatial_{uuid.uuid4().hex[:12]}"
                ),
                object_graph_json=object_graph.model_dump_json(),
                constraint_graph_json=constraint_graph.model_dump_json(),
                ledger_json=ledger.model_dump_json(),
                answered_question_ids=(
                    session_state.answered_question_ids if session_state else []
                ),
                round_number=(session_state.round_number + 1) if session_state else 1,
                max_rounds=3,
            )
            return SpatialFrontendResult(
                ok=True,
                needs_clarification=True,
                final_status="NEEDS_CLARIFICATION",
                questions=questions,
                object_graph=object_graph,
                constraint_graph=constraint_graph,
                solver_report=solver_report,
                assumption_ledger=ledger,
                session_state=session,
            )

    # ── Step 7: Phase A spatial validation ──
    validation_report = validate_spatial_contract_phase_a(constraint_graph)
    final_status: SpatialFinalStatus = (
        "VERIFIED" if validation_report.ok else "ASSUMPTION_BASED"
    )

    return SpatialFrontendResult(
        ok=True,
        final_status=final_status,
        object_graph=object_graph,
        constraint_graph=constraint_graph,
        solver_report=solver_report,
        validation_report=validation_report,
        assumption_ledger=ledger,
    )


def _extract_object_graph(
    user_request: str,
    caller: LlmToolCaller,
    llm_config: AuthoringLlmConfig,
    mode: SpatialModeType,
) -> MechanicalObjectGraphDraft | None:
    """Call LLM to extract MechanicalObjectGraphDraft."""
    from seekflow_engineering_tools.generative_cad.authoring.spatial.prompts import (
        OBJECT_GRAPH_SYSTEM_PROMPT,
    )
    from seekflow_engineering_tools.generative_cad.authoring.spatial.tool_schemas import (
        build_object_graph_tool_schema_for_mode,
    )
    try:
        result = caller.call_strict_tool(
            messages=[
                {"role": "system", "content": OBJECT_GRAPH_SYSTEM_PROMPT},
                {"role": "user", "content": user_request},
            ],
            tool_name="emit_object_graph",
            tool_description="Extract components and spatial relationships",
            tool_schema=build_object_graph_tool_schema_for_mode(mode),
            model_config=llm_config.author,
        )
        return MechanicalObjectGraphDraft.model_validate(result.arguments)
    except Exception:
        return None


def _apply_archetypes(
    graph: MechanicalObjectGraphDraft,
    mode: SpatialModeType,
    ledger: AssumptionLedger,
) -> None:
    """Match archetypes and inject default relations."""
    if mode not in ("auto_mechanical", "auto_complex_verified", "guided"):
        return

    registry = default_archetypes()
    for spec in registry.match(graph):
        if mode in spec.applicable_modes:
            relations = spec.relations(graph)
            graph.candidate_relations.extend(relations)
            for rel in relations:
                ledger.add(AssumptionEntry(
                    assumption_id=f"archetype_{spec.archetype_id}_{rel.relation_id}",
                    statement=rel.rationale,
                    source="archetype_default",
                    confidence=rel.confidence.value,
                ))
