"""BasePackage Pydantic models — LLM authoring package, not an executor.

BasePackage does NOT import CadQuery, does NOT execute geometry, and does
NOT contain runner source. It CAN read dialect.contract() and op_specs()
for skill generation, but that happens at build time, not at runtime.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BasePackageId(str, Enum):
    AXISYMMETRIC = "axisymmetric"
    SKETCH_EXTRUDE = "sketch_extrude"
    COMPOSITION = "composition"


class BasePackageManifest(BaseModel):
    """Lightweight manifest — safe to include in every LLM prompt.

    Contains routing hints (typical_parts, typical_geometry) but does NOT
    encode part-specific ops. The dialect contract / OperationSpec provide
    the machine-readable schema; this provides the human-readable summary.
    """

    model_config = ConfigDict(extra="forbid")

    package_id: str
    dialect_id: str
    dialect_version: str
    title: str
    summary: str
    modeling_paradigm: str
    typical_geometry: list[str]
    typical_parts: list[str]
    main_ops: list[str]
    unsupported_cases: list[str]
    safety_notes: list[str]
    primitive_preferred_when: list[str]
    composition_notes: list[str] = Field(default_factory=list)


class BasePackageExample(BaseModel):
    """A curated few-shot example for LLM authoring.

    Supports both staged generation (route_plan, feature_sequence) and
    legacy single-shot (raw_document) formats.
    """

    model_config = ConfigDict(extra="forbid")

    example_id: str
    title: str
    user_request: str
    route_plan: dict | None = None
    feature_sequence: dict | None = None
    raw_document: dict | None = None
    expected_dialects: list[str] = Field(default_factory=list)
    expected_validation_stages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BasePackageAntiExample(BaseModel):
    """A curated anti-example showing forbidden patterns."""

    model_config = ConfigDict(extra="forbid")

    anti_example_id: str
    title: str
    bad_output: dict | str
    reason: str
    expected_validator_error: str | None = None


class BasePackage(BaseModel):
    """LLM-facing authoring package.

    Contains everything the LLM needs to author valid RawGcadDocument
    graphs for a specific dialect. Does NOT contain runtime handlers,
    CadQuery imports, or geometry execution code.
    """

    model_config = ConfigDict(extra="forbid")

    manifest: BasePackageManifest
    level2_usage_markdown: str
    examples: list[BasePackageExample] = Field(default_factory=list)
    anti_examples: list[dict] = Field(default_factory=list)
    contract_hash: str
    level2_usage_skill_hash: str | None = None
