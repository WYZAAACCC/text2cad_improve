"""DeepSeek strict tool schema factories for spatial LLM calls.

Each factory produces a DeepSeek-compatible strict JSON schema
for a specific spatial LLM stage.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialRelationDraft,
    SpatialQuestion,
    NormalizedSpatialAnswer,
)
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
    to_deepseek_strict_schema,
)


def build_object_graph_tool_schema() -> dict[str, Any]:
    """Strict schema for MechanicalObjectGraphDraft extraction (no mode constraint)."""
    schema = MechanicalObjectGraphDraft.model_json_schema()
    return to_deepseek_strict_schema(schema)


def build_object_graph_tool_schema_for_mode(mode: str) -> dict[str, Any]:
    """Strict schema with mode const-injected for a specific mode."""
    schema = MechanicalObjectGraphDraft.model_json_schema()
    _inject_const(schema, ["properties", "mode"], const=mode)
    return to_deepseek_strict_schema(schema)


def build_spatial_plan_tool_schema() -> dict[str, Any]:
    """Strict schema for spatial plan refinement output."""
    from pydantic import BaseModel, Field

    class SpatialPlanOutput(BaseModel):
        relations: list[SpatialRelationDraft] = Field(default_factory=list)
        unknowns: list[dict] = Field(default_factory=list)
        assumptions: list[str] = Field(default_factory=list)
        model_config = {"extra": "forbid"}

    return to_deepseek_strict_schema(SpatialPlanOutput.model_json_schema())


def build_question_planner_tool_schema() -> dict[str, Any]:
    """Strict schema for question generation output."""
    from pydantic import BaseModel, Field

    class QuestionPlannerOutput(BaseModel):
        questions: list[SpatialQuestion] = Field(default_factory=list)
        no_questions_needed: bool = False
        reasoning: str = ""
        model_config = {"extra": "forbid"}

    return to_deepseek_strict_schema(QuestionPlannerOutput.model_json_schema())


def build_answer_normalizer_tool_schema() -> dict[str, Any]:
    """Strict schema for answer normalization output."""
    return to_deepseek_strict_schema(NormalizedSpatialAnswer.model_json_schema())


def _inject_const(schema: dict, path: list[str], **kwargs) -> None:
    """Inject const/enum constraints at a JSON Schema path.

    Creates intermediate dicts as needed.
    Only sets keys that do not conflict with existing constraints.
    """
    current = schema
    for key in path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    last = path[-1]
    if last not in current:
        current[last] = {}
    for k, v in kwargs.items():
        if k not in current[last]:
            current[last][k] = v
