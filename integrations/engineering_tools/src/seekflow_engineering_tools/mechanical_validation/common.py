"""Common mechanical validation utilities."""

from __future__ import annotations

import json
from pathlib import Path


def load_metadata(path: str | Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _unwrap_primitive_metadata(raw_metadata: dict | None, primitive_name: str) -> dict | None:
    """Extract the primitive-specific metadata from the nested structure.

    The compiler writes: {"primitive_metadata": {"involute_spur_gear": {...}}}
    We need the inner dict for validation.
    """
    if raw_metadata is None:
        return None

    pm = raw_metadata.get("primitive_metadata", {})
    if isinstance(pm, dict) and primitive_name in pm:
        return pm[primitive_name]

    # Fallback: if the top-level already has kernel/primitive keys, use it directly
    if "kernel" in raw_metadata and "primitive" in raw_metadata:
        return raw_metadata

    return None


def validate_mechanical_primitives(spec, step_path: Path, inspection: dict) -> dict:
    """Run mechanical validation for all primitive features in a CADPartSpec.

    Returns {"ok": bool, "results": list[dict]}.
    """
    results: list[dict] = []
    overall_ok = True

    for feature in spec.features:
        if getattr(feature, "type", None) != "primitive":
            continue

        name = feature.primitive_name
        if name == "involute_spur_gear":
            metadata_path = Path(str(step_path)).with_suffix(".metadata.json")
            raw_metadata = load_metadata(metadata_path)
            metadata = _unwrap_primitive_metadata(raw_metadata, name)

            from seekflow_engineering_tools.mechanical_validation.gear_validation import (
                validate_involute_spur_gear_result,
            )
            result = validate_involute_spur_gear_result(
                params=feature.parameters,
                inspection=inspection,
                metadata=metadata,
                tolerance_mm=spec.validation.tolerance_mm,
            )
            results.append(result)
            if not result.get("ok", True):
                overall_ok = False

    return {"ok": overall_ok, "results": results}
