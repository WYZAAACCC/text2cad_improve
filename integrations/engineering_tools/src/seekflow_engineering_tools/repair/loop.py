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


def make_repair_diagnostics(
    stage: str,
    error_type: str,
    message: str,
    spec: CADPartSpec | None = None,
    feature_id: str | None = None,
    validation_report: dict | None = None,
    suggested_fix: str | None = None,
) -> dict:
    """Generate structured repair diagnostics for failure returns.

    This is wired into build failure returns to provide actionable diagnostics
    for automated repair loops.
    """
    return {
        "stage": stage,
        "error_type": error_type,
        "message": message,
        "feature_id": feature_id,
        "spec_name": spec.name if spec else None,
        "validation": validation_report,
        "suggested_fix": suggested_fix or "Check error details and retry with corrected parameters.",
    }


def run_build_once(
    spec: CADPartSpec, backend: str, out_step: str, inspect: bool = True
) -> dict:
    """Run a single build attempt via the natural language build tool.

    Uses the build_natural_language_tools builder to create a fresh tool
    instance with the correct config, then executes the build.
    """
    from pathlib import Path
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools

    # Create minimal config for a single build attempt
    config = EngineeringToolsConfig(workspace_root=Path("."))
    tools = build_natural_language_tools(config)
    build_tool = next(t for t in tools if t.name == "engineering_build_cad_model")

    # The tool is decorated, so we call the underlying function via the __wrapped__ or directly
    # Since tools store the original function, call through the tool's execution path
    return build_tool(spec=spec.model_dump(), backend=backend, out_step=out_step, inspect=inspect)
