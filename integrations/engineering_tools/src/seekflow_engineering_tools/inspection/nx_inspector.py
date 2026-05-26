"""NX model inspector — via file inspection or NXOpen bridge."""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.inspection.common import ModelInspection


def inspect_prt_file(prt_path: Path) -> ModelInspection:
    """Inspect an NX .prt file for basic metadata.

    Full geometric inspection requires submitting a job to the NX bridge
    or running inside NXOpen.
    """
    inspection = ModelInspection()

    if not prt_path.exists():
        inspection.warnings.append(f"File not found: {prt_path}")
        return inspection

    file_size = prt_path.stat().st_size
    inspection.warnings.append(
        f"PRT inspection limited to file metadata ({file_size} bytes). "
        "Full bbox/body_count requires NX bridge job."
    )

    return inspection


def inspect_step_file(step_path: Path) -> ModelInspection:
    """Inspect a STEP file using CadQuery (if available) as a fallback."""
    try:
        from seekflow_engineering_tools.cadquery_backend.inspector import (
            inspect_step_with_cadquery,
        )
        info = inspect_step_with_cadquery(step_path)
        if info.get("error"):
            return ModelInspection(warnings=[f"STEP inspection failed: {info['error']}"])
        return ModelInspection(
            bbox_mm=info.get("bbox_mm"),
            volume_mm3=info.get("volume_mm3"),
            body_count=info.get("solid_count"),
        )
    except ImportError:
        return ModelInspection(
            warnings=["CadQuery not installed. Cannot inspect STEP files."]
        )
