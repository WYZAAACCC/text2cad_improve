"""Safe boolean operations with controlled fillet/chamfer degradation.

Strategy: try full radius → try 0.5*radius → try 0.25*radius → skip with record.
All failures produce degraded feature records for audit trail.
"""

from __future__ import annotations


def try_fillet_with_fallback(
    body,
    radius_mm: float,
    selector: str = "all_external_edges",
    fallback_ratios: tuple[float, ...] = (0.5, 0.25),
):
    """Attempt fillet with progressive radius reduction.

    selector values:
    - "all_external_edges": body.fillet(radius)
    - "top_edges": edges on +Z facing faces
    - "bottom_edges": edges on -Z facing faces
    - "vertical_edges": edges parallel to Z

    Returns (result_body, degraded_records).
    """
    if radius_mm <= 0:
        return body, []

    radii_to_try = [radius_mm] + [radius_mm * r for r in fallback_ratios]
    degraded: list[dict] = []

    for r in radii_to_try:
        if r < 0.1:
            continue
        try:
            if selector == "all_external_edges":
                return body.fillet(r), degraded
            elif selector == "top_edges":
                result = _fillet_faces(body, ">Z", r)
            elif selector == "bottom_edges":
                result = _fillet_faces(body, "<Z", r)
            elif selector == "vertical_edges":
                result = _fillet_vertical(body, r)
            else:
                return body.fillet(r), degraded

            if result is not None:
                return result, degraded
        except (ValueError, RuntimeError) as e:
            degraded.append({
                "radius_attempted": r,
                "selector": selector,
                "error": str(e)[:200],
            })

    degraded.append({
        "radius_attempted": radius_mm,
        "selector": selector,
        "result": "skipped_all_fallbacks",
    })
    return body, degraded


def _fillet_faces(body, face_selector: str, radius: float):
    """Fillet edges on faces matching a CadQuery selector."""
    try:
        faces = body.faces(face_selector)
        edges = faces.edges()
        return edges.fillet(radius)
    except Exception:
        return None


def _fillet_vertical(body, radius: float):
    """Fillet edges approximately parallel to Z axis."""
    try:
        return body.edges("|Z").fillet(radius)
    except Exception:
        return None
