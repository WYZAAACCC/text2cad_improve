"""PlanningReport — read-only optimization analysis output.

Phase 3: produces optimization_opportunities and risk warnings.
Phase 4+: may include suggested_action for opt-in graph rewrite.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PlanningIssue(BaseModel):
    """A single planning finding — optimization opportunity or risk warning."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Issue code (e.g. 'hole_pattern_should_batch').")
    severity: str = Field(
        default="warning",
        description="Severity: 'warning' or 'info'.",
    )
    message: str = Field(description="Human-readable description.")
    node_id: str | None = Field(default=None, description="Related node ID.")
    component_id: str | None = Field(default=None, description="Related component ID.")
    suggestion: str | None = Field(
        default=None,
        description="Actionable suggestion for the LLM or autofixer.",
    )
    details: dict = Field(
        default_factory=dict,
        description="Supporting data (e.g. count, threshold).",
    )


class PlanningReport(BaseModel):
    """Planning analysis output — optimization opportunities + risk warnings.

    Produced by PlannerPass. Not persisted in canonical graph.
    Injected into metadata for repair and audit tooling.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=True, description="True if no error-severity issues.")
    issues: list[PlanningIssue] = Field(
        default_factory=list,
        description="All planning findings.",
    )
    optimization_opportunities: list[dict] = Field(
        default_factory=list,
        description="Opportunities for optimization (subset of issues with severity='info').",
    )
