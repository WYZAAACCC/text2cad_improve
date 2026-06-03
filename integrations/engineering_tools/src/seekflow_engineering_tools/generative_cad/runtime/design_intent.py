"""Design intent metrics — expected geometry properties extracted from prompts.

These models define what the system expects the generated CAD to look like
and are used by semantic_postcheck to verify output correctness.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RangeMm(BaseModel):
    """A min-max range in millimeters."""
    min: float
    max: float


class BBoxExpectation(BaseModel):
    """Expected bounding box dimensions."""
    x_mm: RangeMm | None = None
    y_mm: RangeMm | None = None
    z_mm: RangeMm | None = None


class VolumeExpectation(BaseModel):
    """Expected volume range."""
    min_mm3: float | None = None
    max_mm3: float | None = None


class CriticalDimensionExpectation(BaseModel):
    """A single critical dimension that must be verified."""
    name: str
    target_mm: float
    tolerance_mm: float
    measurement: Literal[
        "bbox_x", "bbox_y", "bbox_z",
        "outer_diameter_xy",
        "height_z",
        "volume_mm3",
        "helix_centerline_length",
        "helix_turns",
    ]


class FeatureExpectation(BaseModel):
    """Expected count of a feature type."""
    kind: Literal[
        "hole", "rib", "boss", "groove", "thread",
        "shell", "sweep", "loft", "boolean_union",
    ]
    min_count: int = 0
    max_count: int | None = None


class DesignIntentMetrics(BaseModel):
    """Aggregated design intent extracted from user prompt.

    All fields are optional — when not set, the corresponding check
    is skipped (semantic_valid = True with low confidence).
    """
    bbox: BBoxExpectation | None = None
    volume: VolumeExpectation | None = None
    critical_dimensions: list[CriticalDimensionExpectation] = Field(
        default_factory=list,
    )
    features: list[FeatureExpectation] = Field(default_factory=list)
    expected_body_count: int | None = 1
    allow_degraded_ops: bool = False
