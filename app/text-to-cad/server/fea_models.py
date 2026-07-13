"""FEA data models — parameter schemas, session state, result types."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Request / Response ──────────────────────────────────────────────────────

class FeaStartRequest(BaseModel):
    model_id: str = Field(description="Scene model ID from the frontend store")
    step_file_url: str = Field(description="URL to the STEP file on server")
    analysis_type: str = Field(
        default="auto",
        description="auto | static_structural | modal | thermal | explicit"
    )


class FeaContinueRequest(BaseModel):
    session_id: str
    answers: list[dict] = Field(description="List of {question_id, mode, value}")


class FeaExecuteRequest(BaseModel):
    template_name: str = Field(description="APDL template name")
    parameters: dict[str, Any] = Field(description="Template parameters dict")
    jobname: str = Field(default="fea_job", max_length=64)


# ── FEA Question (sent to frontend for FeaModal) ────────────────────────────

class FeaQuestionOption(BaseModel):
    option_id: str
    label: str
    description: str = ""
    recommended: bool = False


class FeaQuestion(BaseModel):
    question_id: str
    category: str          # material | load | boundary | mesh
    question_text: str
    why_it_matters: str = ""
    param_key: str         # maps to APDL template parameter name
    param_type: str        # float | int | choice | string
    options: list[FeaQuestionOption] = Field(default_factory=list)
    default_value: Any = None
    allow_custom: bool = True
    unit: str = ""         # e.g. "RPM", "°C", "mm"


class FeaAnswer(BaseModel):
    question_id: str
    mode: Literal["option", "custom", "auto"] = "option"
    selected_option_id: str | None = None
    custom_value: Any = None


# ── Region Definition (for 3D face highlighting) ────────────────────────────

class RegionDef(BaseModel):
    """A named geometric region on the turbine disc, defined by coordinate bounds."""
    region_id: str
    region_type: Literal["cylindrical", "planar", "conical", "axis", "plane"]
    label_cn: str                          # Chinese label for dropdown
    label_en: str = ""
    # Cylindrical face: constant R
    r_mm: float | None = None
    r_tolerance: float = 2.0
    # Planar face: constant Z
    z_mm: float | None = None
    # Range limits
    r_min: float | None = None
    r_max: float | None = None
    z_min: float | None = None
    z_max: float | None = None
    # Axis / plane
    origin: list[float] | None = None       # [x, y, z]
    direction: list[float] | None = None    # [dx, dy, dz] for axis
    normal: list[float] | None = None       # [nx, ny, nz] for plane
    # Display
    color: str = "#00ff00"
    highlight_opacity: float = 0.3


# ── FEA Session State ───────────────────────────────────────────────────────

class FeaSessionState(BaseModel):
    session_id: str
    model_id: str
    step_file_url: str
    selected_template: str = ""
    resolved_params: dict[str, Any] = Field(default_factory=dict)
    pending_questions: list[FeaQuestion] = Field(default_factory=list)
    round_number: int = 0
    max_rounds: int = 2


# ── FEA Result ──────────────────────────────────────────────────────────────

class FeaResult(BaseModel):
    task_id: str
    ok: bool
    template_name: str
    elapsed_s: float = 0
    message: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    files_created: list[str] = Field(default_factory=list)
    log_path: str | None = None
    error: str | None = None


class FeaTaskStatus(BaseModel):
    task_id: str
    status: str       # pending | processing | completed | failed
    progress: int = 0
    result: FeaResult | None = None
    error: str | None = None


# ── Template Schema (lightweight version of ANSYS_TEMPLATE_SCHEMAS) ─────────

class FeaTemplateParam(BaseModel):
    type: str
    required: bool = False
    default: Any = None
    min: float | None = None
    max: float | None = None
    description: str = ""


class FeaTemplateSchema(BaseModel):
    name: str
    analysis_type: str
    units: str
    parameters: dict[str, FeaTemplateParam]
    metrics: list[str]
