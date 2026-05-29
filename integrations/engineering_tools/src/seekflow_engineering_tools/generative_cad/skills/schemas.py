"""Skills schemas — DialectSelectionPlan, Level-1 / Level-2 output schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DialectSelectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dialect: str
    version: str
    reason: str


class DomainSkillSelectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str
    skill_version: str
    reason: str


class DialectSelectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_intent: dict[str, str] = Field(default_factory=dict)
    route_decision: Literal[
        "deterministic_primitive",
        "generative_cad_ir",
        "unsupported",
    ]
    selected_dialects: list[DialectSelectionItem] = Field(default_factory=list)
    selected_domain_skills: list[DomainSkillSelectionItem] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
