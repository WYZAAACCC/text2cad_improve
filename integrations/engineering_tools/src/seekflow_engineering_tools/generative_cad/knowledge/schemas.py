"""Knowledge Pack data models — versioned, composable domain expertise.

Knowledge Packs separate professional engineering knowledge from code.
Each pack is a collection of rules, strategies, and source references
that can be loaded, validated, and compiled into LLM prompts without
hardcoding domain specifics in the pipeline.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Manifest ──────────────────────────────────────────────────────────

class KnowledgeSource(BaseModel):
    """Provenance reference for a knowledge entry."""
    title: str
    url: str = ""
    document_type: str = ""  # "standard", "textbook", "drawing", "internal"
    figure_ref: str = ""     # e.g. "图2-4", "Figure 3-2"


class KnowledgeDependency(BaseModel):
    """Version-pinned dependency on another knowledge pack."""
    skill_id: str
    min_version: str = "1.0.0"


class KnowledgePackManifest(BaseModel):
    """Machine-readable summary for routing and discovery.

    L1 routing reads this to decide whether to activate the pack.
    """
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(description="Unique identifier, e.g. 'turbomachinery.fir_tree_groove.kt787.figure_2_4'")
    version: str = Field(default="1.0.0", description="Semantic version")
    title: str = Field(description="Human-readable title")

    engineering_domain: str = Field(default="mechanical")
    object_types: list[str] = Field(default_factory=list)
    feature_types: list[str] = Field(default_factory=list)

    trigger_terms: list[str] = Field(default_factory=list)
    negative_trigger_terms: list[str] = Field(default_factory=list)

    required_dialects: list[str] = Field(default_factory=list)
    optional_dialects: list[str] = Field(default_factory=list)

    dependencies: list[KnowledgeDependency] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)

    applicable_when: list[str] = Field(default_factory=list)
    not_applicable_when: list[str] = Field(default_factory=list)

    source_documents: list[KnowledgeSource] = Field(default_factory=list)

    priority: int = Field(default=50, ge=0, le=100)
    status: Literal["draft", "reviewed", "validated", "deprecated"] = "draft"


# ── Rules ─────────────────────────────────────────────────────────────

class KnowledgeRule(BaseModel):
    """A single engineering rule with severity classification."""
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="Unique rule identifier within this pack")
    severity: Literal["hard", "strong_preference", "heuristic", "informational"] = "hard"
    statement: str = Field(description="The rule as a declarative statement")
    rationale: str = Field(default="")
    applies_to: list[str] = Field(default_factory=list, description="Feature or object types")
    source_refs: list[str] = Field(default_factory=list)


# ── Pack ──────────────────────────────────────────────────────────────

class KnowledgePack(BaseModel):
    """A complete versioned knowledge pack."""
    model_config = ConfigDict(extra="forbid")

    manifest: KnowledgePackManifest

    # Structured rules by category
    topology_rules: list[KnowledgeRule] = Field(default_factory=list)
    parameter_rules: list[KnowledgeRule] = Field(default_factory=list)
    self_check_rules: list[KnowledgeRule] = Field(default_factory=list)

    # Free-text guidance (markdown)
    construction_strategy: str = Field(default="")
    operation_guidance: str = Field(default="")

    # Documented conflicts within the source material
    known_conflicts: list[dict] = Field(default_factory=list)
