"""Authoring run metrics — track pipeline success/failure at each stage."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthoringRunMetrics(BaseModel):
    """Metrics for a single authoring pipeline run."""

    model_config = ConfigDict(extra="forbid")

    model_router: str = ""
    model_author: str = ""
    model_repair: str | None = None

    # Stage success flags
    route_success: bool = False
    feature_sequence_success: bool = False
    params_success_rate: float = 0.0
    raw_assembly_success: bool = False
    parse_success: bool = False
    canonicalize_success: bool = False
    validation_success: bool = False
    runtime_success: bool | None = None

    # Repair
    repair_attempts: int = 0

    # Failure
    final_failure_code: str | None = None

    # Provider info
    strict_tools_used: bool = True
    json_output_fallback_used: bool = False

    # Context
    context_hash: str = ""
    selected_base_packages: list[str] = Field(default_factory=list)
    tool_schema_hashes: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump()
