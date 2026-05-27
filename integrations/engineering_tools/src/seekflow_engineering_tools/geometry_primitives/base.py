from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PrimitiveParameter(BaseModel):
    name: str
    type: Literal["float", "int", "str", "bool"]
    unit: str | None = None
    required: bool = True
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    description: str = ""


class PrimitiveDefinition(BaseModel):
    name: str
    category: str
    description: str
    parameters: list[PrimitiveParameter]
    supported_kernels: list[str] = Field(default_factory=list)
    supported_backends: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    validation_defaults: dict[str, Any] = Field(default_factory=dict)
