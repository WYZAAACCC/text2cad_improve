"""Primitive metadata sidecar — every primitive output MUST have metadata."""

from __future__ import annotations

import json
from pathlib import Path


def write_primitive_metadata(step_path: str | Path, metadata: dict, validation: dict | None = None) -> Path:
    step_path = Path(step_path)
    meta_path = step_path.with_suffix(".metadata.json")

    payload = {
        "step_file": str(step_path),
        **metadata,
    }
    if validation is not None:
        payload["validation"] = validation

    meta_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return meta_path


def read_primitive_metadata(step_path: str | Path) -> dict | None:
    step_path = Path(step_path)
    meta_path = step_path.with_suffix(".metadata.json")
    if not meta_path.exists():
        # Also try the metadata.json convention
        alt_path = step_path.parent / (step_path.stem + ".metadata.json")
        if alt_path.exists():
            meta_path = alt_path
        else:
            return None

    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
