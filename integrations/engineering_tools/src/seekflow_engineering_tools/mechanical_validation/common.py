"""Common mechanical validation utilities — handler registry for primitives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

# ── Mechanical validator handler type ──
# Signature: (params: dict, inspection: dict, metadata: dict | None,
#             tolerance_mm: float, expected: dict | None) -> dict
PrimitiveMechanicalValidator = Callable[..., dict]

PRIMITIVE_MECHANICAL_VALIDATORS: dict[str, PrimitiveMechanicalValidator] = {}


def register_primitive_mechanical_validator(name: str, handler: PrimitiveMechanicalValidator) -> None:
    if name in PRIMITIVE_MECHANICAL_VALIDATORS:
        raise RuntimeError(
            f"Duplicate mechanical validator registration: '{name}'"
        )
    PRIMITIVE_MECHANICAL_VALIDATORS[name] = handler


def list_primitive_mechanical_validator_names() -> list[str]:
    return sorted(PRIMITIVE_MECHANICAL_VALIDATORS.keys())


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


# ── Gear mechanical validator adapter ──

def _gear_mechanical_validator(
    params: dict,
    inspection: dict,
    metadata: dict | None,
    tolerance_mm: float,
    expected: dict | None = None,
    raw_metadata: dict | None = None,
) -> dict:
    """Adapter: delegates to validate_involute_spur_gear_result."""
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )
    return validate_involute_spur_gear_result(
        params=params,
        inspection=inspection,
        metadata=metadata,
        tolerance_mm=tolerance_mm,
        expected=expected or {},
        raw_metadata=raw_metadata,
    )


register_primitive_mechanical_validator("involute_spur_gear", _gear_mechanical_validator)


# ── Main dispatch ──

def validate_mechanical_primitives(spec, step_path: Path, inspection: dict) -> dict:
    """Run mechanical validation for all primitive features in a CADPartSpec.

    Dispatches through PRIMITIVE_MECHANICAL_VALIDATORS registry.
    Returns {"ok": bool, "results": list[dict]}.
    """
    results: list[dict] = []
    overall_ok = True

    for feature in spec.features:
        if getattr(feature, "type", None) != "primitive":
            continue

        name = feature.primitive_name

        # Load metadata
        metadata_path = Path(str(step_path)).with_suffix(".metadata.json")
        raw_metadata = load_metadata(metadata_path)
        metadata = _unwrap_primitive_metadata(raw_metadata, name)

        # Look up handler
        handler = PRIMITIVE_MECHANICAL_VALIDATORS.get(name)
        if handler is None:
            results.append({
                "ok": False,
                "issues": [{
                    "code": "primitive_mechanical_validator_missing",
                    "message": (
                        f"No mechanical validator registered for primitive '{name}'. "
                        f"Available: {list_primitive_mechanical_validator_names()}"
                    ),
                    "severity": "error",
                }],
                "reference_dimensions": {},
                "kernel": metadata.get("kernel", "unknown") if metadata else "unknown",
            })
            overall_ok = False
            continue

        # Build expected dict from spec.validation (top-level + per-feature)
        expected: dict[str, Any] = {}
        if hasattr(spec, "validation"):
            v = spec.validation
            for attr in [
                "expected_kernel", "expected_tooth_count",
                "expected_bore_diameter_mm", "expected_face_width_mm",
                "expected_pitch_diameter_mm", "expected_base_diameter_mm",
                "expected_outer_diameter_mm", "expected_root_diameter_mm",
                "expected_body_count",
            ]:
                val = getattr(v, attr, None)
                if val is not None:
                    expected[attr] = val

        # Merge per-feature primitive_validation
        if hasattr(spec, "validation") and hasattr(spec.validation, "primitive_validation"):
            pv = spec.validation.primitive_validation
            if isinstance(pv, dict) and feature.id in pv:
                feat_expected = pv[feature.id]
                if isinstance(feat_expected, dict):
                    expected.update(feat_expected)

        # Call handler
        try:
            result = handler(
                params=feature.parameters,
                inspection=inspection,
                metadata=metadata,
                tolerance_mm=getattr(spec.validation, "tolerance_mm", 0.1)
                if hasattr(spec, "validation") else 0.1,
                expected=expected if expected else None,
                raw_metadata=raw_metadata,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "issues": [{
                    "code": "primitive_mechanical_validator_error",
                    "message": f"Mechanical validator for '{name}' raised: {exc}",
                    "severity": "error",
                }],
                "reference_dimensions": {},
                "kernel": "unknown",
            }

        results.append(result)
        if not result.get("ok"):
            overall_ok = False

    return {"ok": overall_ok, "results": results}
