from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AnalysisType = Literal[
    "static_structural",
    "modal",
    "thermal_steady",
    "buckling",
    "bilinear_plastic",
]

ElementType = Literal["SOLID185", "PLANE182", "SOLID70", "BEAM188"]


class MaterialSpec(BaseModel):
    name: str
    ex_mpa: float | None = None
    nu: float | None = None
    density_tonne_per_mm3: float | None = None
    k_w_per_mm_c: float | None = None
    yield_mpa: float | None = None
    tangent_mpa: float | None = None


class MeshSpec(BaseModel):
    element_type: ElementType
    element_size_mm: float


class GeometrySource(BaseModel):
    type: Literal["primitive", "step_file", "template"]
    path: str | None = None
    template_name: str | None = None
    parameters: dict = Field(default_factory=dict)


class LoadSpec(BaseModel):
    id: str
    type: Literal["force", "pressure", "temperature", "displacement"]
    target: str
    value: float | list[float]
    units: str


class ConstraintSpec(BaseModel):
    id: str
    type: Literal["fixed", "symmetry", "displacement"]
    target: str
    value: float | list[float] | None = None


class ResultRequest(BaseModel):
    type: Literal[
        "max_displacement",
        "max_von_mises",
        "reaction_force",
        "modal_frequencies",
        "buckling_load_factor",
        "max_temperature",
    ]


class CAEJobSpec(BaseModel):
    nlcae_version: str = "0.1"
    name: str
    analysis_type: AnalysisType
    units: Literal["mm,N,MPa,C"] = "mm,N,MPa,C"
    geometry: GeometrySource
    materials: list[MaterialSpec]
    mesh: MeshSpec
    loads: list[LoadSpec] = Field(default_factory=list)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    results: list[ResultRequest]
