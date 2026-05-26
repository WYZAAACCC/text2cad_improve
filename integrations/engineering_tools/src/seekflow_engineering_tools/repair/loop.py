"""Repair loop — classify failures and orchestrate retries."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.ir.cad import CADPartSpec


def classify_failure(result: EngineeringActionResult | dict) -> dict:
    """Classify a failed build result into structured error categories.

    Returns a dict with *stage*, *feature_id*, *error_type*, and *suggested_fix*.
    """
    r = result if isinstance(result, dict) else result.model_dump()
    error_msg = str(r.get("error", ""))
    stage = "execute"
    feature_id = "unknown"
    error_type = "unknown_error"
    suggested_fix = "Check the error message and retry."

    if "VBS_ERR" in error_msg or "vbs" in error_msg.lower():
        stage = "execute"
        error_type = "vbs_execution_failed"
        suggested_fix = "Check VBS syntax and COM object availability."

    if "validation" in error_msg.lower() or "bbox" in error_msg.lower():
        stage = "validate"
        error_type = "validation_failed"
        suggested_fix = "Check CAD-IR dimensions against expected bbox."

    if "compile" in error_msg.lower() or "unsupported" in error_msg.lower():
        stage = "compile"
        error_type = "compilation_failed"
        suggested_fix = "Check feature type and backend compatibility."

    if "missing" in error_msg.lower() or "not found" in error_msg.lower():
        if "file" in error_msg.lower():
            stage = "inspect"
            error_type = "missing_file"
            suggested_fix = "Verify output file path and export settings."

    return {
        "stage": stage,
        "feature_id": feature_id,
        "error_type": error_type,
        "suggested_fix": suggested_fix,
    }


def run_build_once(
    spec: CADPartSpec, backend: str, **kwargs: Any
) -> dict:
    """Run a single build attempt and return the raw result.

    This is a pass-through for the actual backend-specific build logic.
    The caller (agent loop) uses classify_failure to interpret results.
    """
    from seekflow_engineering_tools.natural_language.tools import (
        engineering_build_cad_model,
    )

    return engineering_build_cad_model(
        spec=spec.model_dump(),
        backend=backend,
        **kwargs,
    )
