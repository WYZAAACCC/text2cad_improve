"""Clarification question planner with priority-based budgeting.

Priority formula: priority = impact * uncertainty / max(answer_cost, 0.1)
Only high-priority unknowns are converted to questions.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialUnknown,
    SpatialQuestion,
)

DEFAULT_QUESTION_BUDGET = 3
MIN_PRIORITY_THRESHOLD = 0.15


def plan_questions(
    object_graph: MechanicalObjectGraphDraft,
    budget: int = DEFAULT_QUESTION_BUDGET,
    min_priority: float = MIN_PRIORITY_THRESHOLD,
) -> list[SpatialQuestion]:
    """Generate clarification questions for high-priority unknowns.

    Returns empty list if no unknowns meet the priority threshold
    or budget is exhausted.
    """
    if not object_graph.unknowns:
        return []

    # Compute priority for each unknown
    scored: list[tuple[float, SpatialUnknown]] = []
    for unk in object_graph.unknowns:
        priority = _compute_priority(unk)
        if priority >= min_priority:
            scored.append((priority, unk))

    # Sort by priority descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Generate questions within budget
    questions: list[SpatialQuestion] = []
    for priority, unk in scored[:budget]:
        q = _unknown_to_question(unk, priority)
        questions.append(q)

    return questions


def _compute_priority(unk: SpatialUnknown) -> float:
    """priority = impact * uncertainty / max(answer_cost, 0.1), clamped to [0, 1]"""
    impact = max(0.0, min(1.0, unk.impact))
    uncertainty = max(0.0, min(1.0, unk.uncertainty))
    answer_cost = max(0.1, unk.answer_cost)
    raw = (impact * uncertainty) / answer_cost
    return max(0.0, min(1.0, raw))


def _unknown_to_question(unk: SpatialUnknown, priority: float) -> SpatialQuestion:
    """Convert a SpatialUnknown into a SpatialQuestion with sensible defaults.

    The LLM (question planner) will refine these defaults.
    This function provides a baseline that works without LLM refinement.
    """
    from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
        SpatialQuestionOption,
        SpatialRelationDraft,
        Confidence,
    )

    options = _default_options_for_kind(unk)

    return SpatialQuestion(
        question_id=f"q_{unk.unknown_id}",
        unknown_id=unk.unknown_id,
        type=unk.kind,
        entities=list(unk.entities),
        question_text=unk.question_hint or f"How should {', '.join(unk.entities)} be arranged?",
        why_it_matters=unk.reason or f"Incorrect placement of {', '.join(unk.entities)} may cause assembly errors",
        impact=unk.impact,
        uncertainty=unk.uncertainty,
        answer_cost=unk.answer_cost,
        priority=round(priority, 3),
        options=options,
        allow_custom=True,
        allow_auto=True,
    )


def _default_options_for_kind(unk: SpatialUnknown) -> list[SpatialQuestionOption]:
    """Provide sensible default options based on unknown kind."""
    from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
        SpatialQuestionOption,
    )

    kind = unk.kind

    if kind == "component_count":
        return [
            SpatialQuestionOption(
                option_id="A", label="As described (default count)",
                description="Use the number of components as extracted from the prompt",
                recommended=True,
                geometric_consequence="Components will be generated as described",
            ),
            SpatialQuestionOption(
                option_id="B", label="Different count",
                description="Specify a different number of components",
                geometric_consequence="Component count will change the assembly layout",
            ),
        ]

    if kind == "relative_placement":
        return [
            SpatialQuestionOption(
                option_id="A", label="Conventional layout (recommended)",
                description="Use standard mechanical layout for this type of assembly",
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence="Components will be placed according to mechanical conventions",
            ),
            SpatialQuestionOption(
                option_id="B", label="Symmetric layout",
                description="Components placed symmetrically",
                geometric_consequence="Components will be mirrored across the central plane",
            ),
        ]

    if kind == "symmetry":
        return [
            SpatialQuestionOption(
                option_id="A", label="Symmetric (recommended)",
                description="Components placed symmetrically about center plane",
                recommended=True,
                geometric_consequence="Components will be mirror-images across YZ plane",
            ),
            SpatialQuestionOption(
                option_id="B", label="Asymmetric / independent",
                description="Each component placed independently",
                geometric_consequence="Components may have different X coordinates",
            ),
        ]

    if kind == "assembly_vs_fused":
        return [
            SpatialQuestionOption(
                option_id="A", label="Separate assembly (recommended)",
                description="Components remain as separate bodies, placed with spatial constraints",
                recommended=True,
                geometric_consequence="Components will be distinct solids with spatial relationships",
            ),
            SpatialQuestionOption(
                option_id="B", label="Fused into single body",
                description="Components merged via boolean union into one solid",
                geometric_consequence="All components will be combined into a single solid",
            ),
        ]

    if kind == "spacing":
        return [
            SpatialQuestionOption(
                option_id="A", label="Default spacing (recommended)",
                description="Use mechanically appropriate default clearance",
                recommended=True,
                auto_policy="auto_mechanical",
                geometric_consequence="Components will have standard mechanical clearance",
            ),
            SpatialQuestionOption(
                option_id="B", label="Tight fit",
                description="Minimal clearance between components",
                geometric_consequence="Components will be placed with near-zero clearance",
            ),
        ]

    # Default fallback for any unknown kind
    return [
        SpatialQuestionOption(
            option_id="A", label="Recommended default",
            description="Use the mechanically conventional layout",
            recommended=True,
            auto_policy="auto_mechanical",
            geometric_consequence="Standard mechanical layout will be used",
        ),
    ]
