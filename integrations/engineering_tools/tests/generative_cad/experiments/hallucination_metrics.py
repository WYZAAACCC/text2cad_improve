"""Hallucination metrics — quantify LLM output quality in CAD-IR generation.

Defines what "hallucination" means for G-CAD IR and how to measure it.
Each metric is a concrete, countable failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HallucinationCategory(str, Enum):
    """Categories of LLM hallucination in G-CAD IR generation."""
    SCHEMA = "schema"             # Pydantic validation failure
    DIALECT = "dialect"           # Unknown/unregistered dialect
    OP = "op"                     # Unknown/invented operation
    OP_VERSION = "op_version"     # Wrong op_version
    PARAMS_EXTRA = "params_extra"        # Extra/unknown parameter field
    PARAMS_MISSING = "params_missing"    # Missing required parameter
    PARAMS_TYPE = "params_type"         # Wrong parameter type
    PARAMS_RANGE = "params_range"       # Parameter out of valid range
    PHASE = "phase"               # Wrong phase for operation
    GRAPH_WIRING = "graph_wiring" # Incorrect input/output references
    GRAPH_CYCLE = "graph_cycle"   # Cyclic dependency
    TYPE_MISMATCH = "type_mismatch"  # Input type != expected
    SAFETY = "safety"             # Safety flag not true
    CONSTRAINT = "constraint"     # Constraint violation
    OUTPUT_NAMING = "output_naming"  # Wrong output field names
    CROSS_DIALECT = "cross_dialect"  # Direct cross-dialect reference
    UNKNOWN = "unknown"


@dataclass
class HallucinationEvent:
    """A single detected hallucination."""
    category: HallucinationCategory
    path: str
    detail: str
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "path": self.path,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class GenerationMetrics:
    """Per-generation hallucination metrics."""
    # Counts by category
    total_hallucinations: int = 0
    by_category: dict[str, int] = field(default_factory=dict)

    # Stage-level success
    parse_success: bool = False
    validate_success: bool = False
    canonicalize_success: bool = False

    # Operation accuracy
    total_ops: int = 0
    valid_ops: int = 0
    invented_ops: int = 0

    # Param accuracy
    total_params: int = 0
    valid_params: int = 0
    extra_params: int = 0
    missing_params: int = 0
    type_error_params: int = 0

    # Events
    events: list[HallucinationEvent] = field(default_factory=list)

    def record(self, category: HallucinationCategory, path: str, detail: str, severity: str = "error") -> None:
        self.total_hallucinations += 1
        self.by_category[category.value] = self.by_category.get(category.value, 0) + 1
        self.events.append(HallucinationEvent(category=category, path=path, detail=detail, severity=severity))

    @property
    def schema_adherence_rate(self) -> float:
        return 1.0 if self.parse_success else 0.0

    @property
    def op_accuracy_rate(self) -> float:
        if self.total_ops == 0:
            return 1.0
        return self.valid_ops / self.total_ops

    @property
    def params_accuracy_rate(self) -> float:
        if self.total_params == 0:
            return 1.0
        return self.valid_params / self.total_params

    @property
    def overall_quality_score(self) -> float:
        """Composite quality score 0.0–1.0."""
        scores = [
            self.schema_adherence_rate,
            self.op_accuracy_rate,
            self.params_accuracy_rate,
            1.0 if self.validate_success else 0.0,
            1.0 if self.canonicalize_success else 0.0,
        ]
        return sum(scores) / len(scores)

    def to_dict(self) -> dict:
        return {
            "total_hallucinations": self.total_hallucinations,
            "by_category": dict(self.by_category),
            "parse_success": self.parse_success,
            "validate_success": self.validate_success,
            "canonicalize_success": self.canonicalize_success,
            "total_ops": self.total_ops,
            "valid_ops": self.valid_ops,
            "invented_ops": self.invented_ops,
            "total_params": self.total_params,
            "valid_params": self.valid_params,
            "extra_params": self.extra_params,
            "missing_params": self.missing_params,
            "type_error_params": self.type_error_params,
            "schema_adherence_rate": self.schema_adherence_rate,
            "op_accuracy_rate": self.op_accuracy_rate,
            "params_accuracy_rate": self.params_accuracy_rate,
            "overall_quality_score": self.overall_quality_score,
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class ExperimentComparison:
    """A/B comparison result between old and new pipelines."""
    case_id: str
    prompt: str
    difficulty: str  # simple | medium | complex | negative

    old_metrics: GenerationMetrics = field(default_factory=GenerationMetrics)
    new_metrics: GenerationMetrics = field(default_factory=GenerationMetrics)

    @property
    def hallucination_reduction(self) -> float:
        """Fractional reduction in total hallucinations."""
        if self.old_metrics.total_hallucinations == 0:
            return 0.0
        return 1.0 - (self.new_metrics.total_hallucinations / self.old_metrics.total_hallucinations)

    @property
    def quality_improvement(self) -> float:
        """Absolute improvement in overall quality score."""
        return self.new_metrics.overall_quality_score - self.old_metrics.overall_quality_score

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "difficulty": self.difficulty,
            "old": self.old_metrics.to_dict(),
            "new": self.new_metrics.to_dict(),
            "hallucination_reduction_pct": round(self.hallucination_reduction * 100, 1),
            "quality_improvement": round(self.quality_improvement, 3),
        }
