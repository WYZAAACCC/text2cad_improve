"""Skills schemas — DialectSelectionPlan with route invariants."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    selected_primitive: str | None = Field(
        default=None,
        description="Primitive name when route_decision is deterministic_primitive.",
    )
    selected_domain_skills: list[DomainSkillSelectionItem] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_route_invariants(self):
        if self.route_decision == "generative_cad_ir":
            if not self.selected_dialects:
                raise ValueError("generative_cad_ir requires selected_dialects to be non-empty")

        if self.route_decision == "deterministic_primitive":
            if self.selected_dialects:
                raise ValueError("deterministic_primitive must not select generative dialects")
            if not self.selected_primitive:
                raise ValueError("deterministic_primitive requires selected_primitive to be set")

        if self.route_decision == "unsupported":
            if not self.unsupported_capabilities:
                raise ValueError("unsupported route requires unsupported_capabilities to be non-empty")

        seen = set()
        for d in self.selected_dialects:
            if d.dialect in seen:
                raise ValueError(f"duplicate selected dialect: {d.dialect}")
            seen.add(d.dialect)

        return self


def validate_selection_plan_against_catalog(
    plan: DialectSelectionPlan,
    catalog: dict,
) -> tuple[bool, list[dict]]:
    """Validate that all selected dialects exist in the catalog."""
    allowed = {d["dialect_id"] for d in catalog.get("dialects", [])}
    issues = []
    for item in plan.selected_dialects:
        if item.dialect not in allowed:
            issues.append({
                "code": "unknown_selected_dialect",
                "message": f"selected dialect {item.dialect!r} not present in catalog",
            })
    return len(issues) == 0, issues
