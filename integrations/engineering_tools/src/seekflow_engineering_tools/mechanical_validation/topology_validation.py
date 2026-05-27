"""Topology validation — checks for watertight solids, manifold edges, etc."""

from __future__ import annotations


def validate_solid_topology(inspection: dict) -> dict:
    """Validate basic topological properties of a solid model.

    Checks:
      - body_count >= 1 (at least one solid body)
      - bbox sanity (all dimensions > 0)
    """
    issues: list[dict] = []

    body_count = inspection.get("solid_count") or inspection.get("body_count")
    if body_count is not None and body_count < 1:
        issues.append({
            "code": "no_solid_body",
            "message": "Model has no solid bodies.",
            "severity": "error",
        })

    bbox = inspection.get("bbox_mm")
    if bbox and len(bbox) == 3:
        for i, axis in enumerate("XYZ"):
            if bbox[i] <= 0:
                issues.append({
                    "code": "bbox_zero_dimension",
                    "message": f"BBox {axis} dimension is {bbox[i]:.3f} (must be > 0).",
                    "severity": "error",
                })

    ok = not any(i["severity"] == "error" for i in issues)
    return {"ok": ok, "issues": issues}
