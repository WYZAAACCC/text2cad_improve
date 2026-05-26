"""Configuration for all engineering tools – env vars + Pydantic model."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class EngineeringToolsConfig(BaseModel):
    """Master configuration for SolidWorks / NX / ANSYS integration.

    Every path that an engineering tool writes to is constrained to
    *workspace_root*.  Set it via ``ENGINEERING_WORKSPACE`` env var or
    pass it explicitly.
    """

    workspace_root: Path = Field(default_factory=lambda: Path(
        os.environ.get("ENGINEERING_WORKSPACE", str(Path.home() / "seekflow_workspace"))
    ))

    # ── SolidWorks 2025 ─────────────────────────────────────────────
    solidworks_enabled: bool = Field(
        default_factory=lambda: os.environ.get("SOLIDWORKS_ENABLED", "1") == "1"
    )
    solidworks_visible: bool = Field(
        default_factory=lambda: os.environ.get("SOLIDWORKS_VISIBLE", "1") == "1"
    )
    solidworks_part_template: Path | None = Field(
        default_factory=lambda: _optional_path_env("SOLIDWORKS_PART_TEMPLATE")
    )
    solidworks_default_timeout_s: int = 180

    # ── Siemens NX 12.0 ─────────────────────────────────────────────
    nx_enabled: bool = Field(
        default_factory=lambda: os.environ.get("NX_ENABLED", "1") == "1"
    )
    nx_job_root: Path | None = Field(
        default_factory=lambda: _optional_path_env("NX_JOB_ROOT")
    )
    nx_default_timeout_s: int = 300

    # ── ANSYS 18.1 ──────────────────────────────────────────────────
    ansys_enabled: bool = Field(
        default_factory=lambda: os.environ.get("ANSYS_ENABLED", "1") == "1"
    )
    ansys181_exe: Path | None = Field(
        default_factory=lambda: _optional_path_env("ANSYS181_EXE")
    )
    ansys_default_timeout_s: int = 600
    ansys_default_nproc: int = Field(
        default_factory=lambda: int(os.environ.get("ANSYS_DEFAULT_NPROC", "2"))
    )

    # ── Security ────────────────────────────────────────────────────
    allow_overwrite: bool = Field(
        default_factory=lambda: os.environ.get("ENGINEERING_ALLOW_OVERWRITE", "0") == "1"
    )
    max_input_file_mb: int = 200
    max_output_file_mb: int = 1000


def _optional_path_env(key: str) -> Path | None:
    val = os.environ.get(key)
    return Path(val) if val else None
