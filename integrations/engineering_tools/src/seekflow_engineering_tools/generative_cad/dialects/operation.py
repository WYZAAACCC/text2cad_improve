"""OperationSpec — full typed operation definition with handler."""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict

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

    def validate_params(self, raw_params: dict[str, Any]) -> BaseModel:
        return self.params_model.model_validate(raw_params)
