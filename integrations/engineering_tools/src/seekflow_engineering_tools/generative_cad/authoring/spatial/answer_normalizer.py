"""Answer normalizer — converts user answers into SpatialRelationDraft constraints.

Handles three answer modes: option (selected from choices), custom (free text),
and auto (delegate to system default).
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    UserSpatialAnswer,
    NormalizedSpatialAnswer,
    SpatialQuestion,
    SpatialRelationDraft,
    Confidence,
)
from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig
from seekflow_engineering_tools.generative_cad.llm.provider import LlmToolCaller


def normalize_answers(
    answers: list[UserSpatialAnswer],
    object_graph: MechanicalObjectGraphDraft,
    answer_normalizer_caller: LlmToolCaller | None = None,
    llm_config: AuthoringLlmConfig | None = None,
) -> list[NormalizedSpatialAnswer]:
    """Normalize a batch of user answers into spatial relations and assumptions.

    If answer_normalizer_caller is provided, uses LLM for normalization.
    Otherwise falls back to deterministic normalization based on option selection.
    """
    results: list[NormalizedSpatialAnswer] = []

    for answer in answers:
        if answer_normalizer_caller is not None and llm_config is not None:
            result = _normalize_with_llm(answer, object_graph, answer_normalizer_caller, llm_config)
        else:
            result = _normalize_deterministic(answer)
        results.append(result)

    return results


def _normalize_deterministic(answer: UserSpatialAnswer) -> NormalizedSpatialAnswer:
    """Deterministic normalization without LLM.

    Handles simple option-mode answers by recording the choice as an assumption.
    For custom and auto modes, records the intent but requires LLM for full processing.
    """
    relations: list[SpatialRelationDraft] = []
    assumptions: list[str] = []

    if answer.mode == "option":
        assumptions.append(
            f"User selected option '{answer.selected_option_id}' for question '{answer.question_id}'"
        )

    elif answer.mode == "custom":
        assumptions.append(
            f"User provided custom answer for question '{answer.question_id}': "
            f"{answer.custom_text[:200] if answer.custom_text else '(empty)'}"
        )
        # Custom text may contain spatial intent; mark for replanning
        return NormalizedSpatialAnswer(
            question_id=answer.question_id,
            source_answer=answer,
            relations_added=relations,
            assumptions_added=assumptions,
            requires_replanning=True,
        )

    elif answer.mode == "auto":
        auto_level = answer.auto_level or "auto_mechanical"
        assumptions.append(
            f"User delegated question '{answer.question_id}' to AUTO ({auto_level}). "
            f"System will use archetype defaults and record all assumptions."
        )

    return NormalizedSpatialAnswer(
        question_id=answer.question_id,
        source_answer=answer,
        relations_added=relations,
        assumptions_added=assumptions,
        requires_replanning=False,
    )


def _normalize_with_llm(
    answer: UserSpatialAnswer,
    object_graph: MechanicalObjectGraphDraft,
    caller: LlmToolCaller,
    llm_config: AuthoringLlmConfig,
) -> NormalizedSpatialAnswer:
    """Use LLM to normalize the answer into structured relations."""
    from seekflow_engineering_tools.generative_cad.authoring.spatial.prompts import (
        ANSWER_NORMALIZER_SYSTEM_PROMPT,
    )
    from seekflow_engineering_tools.generative_cad.authoring.spatial.tool_schemas import (
        build_answer_normalizer_tool_schema,
    )

    try:
        result = caller.call_strict_tool(
            messages=[
                {"role": "system", "content": ANSWER_NORMALIZER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question: {answer.question_id}\n"
                        f"Answer mode: {answer.mode}\n"
                        f"Selected option: {answer.selected_option_id}\n"
                        f"Custom text: {answer.custom_text or 'N/A'}\n"
                        f"Auto level: {answer.auto_level or 'N/A'}\n"
                        f"Object graph components: "
                        f"{[c.component_id for c in object_graph.components]}"
                    ),
                },
            ],
            tool_name="emit_normalized_answer",
            tool_description="Normalize user answer into spatial constraints",
            tool_schema=build_answer_normalizer_tool_schema(),
            model_config=llm_config.author,
        )
        return NormalizedSpatialAnswer.model_validate(result.arguments)
    except Exception:
        # Fall back to deterministic on LLM failure
        return _normalize_deterministic(answer)
