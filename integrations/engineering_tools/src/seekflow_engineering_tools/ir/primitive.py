from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrimitiveFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["primitive"] = "primitive"
    primitive_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    placement: dict[str, Any] = Field(default_factory=dict)
    operation: Literal["new_body", "add", "cut"] = "new_body"

    @model_validator(mode="after")
    def validate_primitive_name(self):
        if not self.primitive_name.strip():
            raise ValueError("primitive_name must not be empty")
        return self
