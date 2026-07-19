"""OperationSpec — full typed operation definition with handler."""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode, ValueType
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext

Effect = Literal[
    "creates_solid",
    "modifies_solid",
    "cuts_material",
    "adds_material",
    "creates_frame",
    "places_component",
    "patterns_component",
    "boolean_union",
    "boolean_cut",
    "boolean_intersect",
    "exports_artifact",
]

OperationHandler = Callable[..., dict[str, str]]
"""Legacy handler type — returns dict[str, str] mapping output name → handle_id.
New operations should return OperationResult instead. Use handler_kind='v2_result'.
"""


class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    dialect: str
    op: str
    op_version: str
    phase: str

    input_types: list[ValueType]
    output_types: list[ValueType]

    params_model: type[BaseModel]
    effects: list[Effect]

    required_context: list[str] = []
    postconditions: list[str] = []

    handler: OperationHandler
    handler_kind: Literal["v1_dict", "v2_result"] = "v1_dict"

    # ── Persistent topology (Phase 2+) ──
    topology_contract: object | None = None  # TopologyContract | None (lazy to avoid circular import)

    # ── LLM-facing metadata (for skill generation / docs only) ──
    # These fields do NOT affect validation semantics.
    # They are used by Level-2 skill generators and tool schema compilers
    # to produce rich, accurate LLM guidance without hard-coding in the orchestrator.
    summary: str | None = None
    usage_notes: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)
    anti_examples: list[dict] = Field(default_factory=list)
    llm_param_hints: dict[str, str] = Field(default_factory=dict)

    def validate_params(self, raw_params: dict[str, Any]) -> BaseModel:
        return self.params_model.model_validate(raw_params)
