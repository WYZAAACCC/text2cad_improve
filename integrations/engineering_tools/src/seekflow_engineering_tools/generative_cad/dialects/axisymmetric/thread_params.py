"""Thread feature params — ISO metric and UN standard thread profiles."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CutInternalThreadParams(BaseModel):
    """Cut an internal thread (tapped hole) in a bore."""
    model_config = ConfigDict(extra="forbid")

    nominal_dia_mm: float = Field(gt=0, description="Nominal thread diameter (e.g. 8 for M8)")
    pitch_mm: float = Field(gt=0, description="Thread pitch in mm (e.g. 1.25 for M8 coarse)")
    depth_mm: float = Field(gt=0, description="Thread depth along the bore axis")
    standard: Literal["ISO_metric", "ISO_metric_fine"] = "ISO_metric"
    thread_class: Literal["6H", "6G", "7H"] = "6H"
    start_angle_deg: float = Field(default=0.0, description="Thread start angle offset")


class CutExternalThreadParams(BaseModel):
    """Cut an external thread on a cylindrical surface."""
    model_config = ConfigDict(extra="forbid")

    nominal_dia_mm: float = Field(gt=0, description="Nominal thread diameter")
    pitch_mm: float = Field(gt=0, description="Thread pitch in mm")
    length_mm: float = Field(gt=0, description="Threaded length along the axis")
    standard: Literal["ISO_metric", "ISO_metric_fine"] = "ISO_metric"
    thread_class: Literal["6g", "6h", "8g"] = "6g"
    start_z_mm: float = Field(default=0.0, description="Z position where thread starts")
    start_angle_deg: float = Field(default=0.0)


# Standard metric coarse thread data (diameter -> pitch)
METRIC_COARSE_PITCH: dict[float, float] = {
    1.0: 0.25, 1.2: 0.25, 1.6: 0.35, 2.0: 0.4, 2.5: 0.45,
    3.0: 0.5, 4.0: 0.7, 5.0: 0.8, 6.0: 1.0, 8.0: 1.25,
    10.0: 1.5, 12.0: 1.75, 16.0: 2.0, 20.0: 2.5, 24.0: 3.0,
    30.0: 3.5, 36.0: 4.0, 42.0: 4.5, 48.0: 5.0, 56.0: 5.5,
    64.0: 6.0,
}
