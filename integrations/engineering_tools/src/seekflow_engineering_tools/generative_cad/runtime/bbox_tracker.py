"""Component bbox measurement — post leaf-component execution.

Measures each leaf component's root solid bounding box after execution.
Results feed into ConstraintResolver for numerical placement computation.
"""

from __future__ import annotations
from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import ComponentBBox


def measure_component_bbox(solid_obj: Any, component_id: str) -> ComponentBBox | None:
    """Measure a single component's root solid bounding box.

    Handles CadQuery Workplane (unwraps via .val()) and direct Solid objects.
    Returns None if measurement fails (non-fatal — component will use defaults).
    """
    try:
        if hasattr(solid_obj, 'val'):
            solid_obj = solid_obj.val()
        if hasattr(solid_obj, 'BoundingBox'):
            bb = solid_obj.BoundingBox()
            return ComponentBBox(
                component_id=component_id,
                xmin=bb.xmin, xmax=bb.xmax,
                ymin=bb.ymin, ymax=bb.ymax,
                zmin=bb.zmin, zmax=bb.zmax,
            )
        return None
    except Exception:
        return None


def measure_all_component_bboxes(
    ctx: Any,  # RuntimeContext (avoid circular import)
    component_ids: list[str],
) -> dict[str, ComponentBBox]:
    """Measure all leaf component bboxes from the object store.

    Looks up each component's "body" output and measures its bounding box.
    Non-fatal: components that fail measurement are silently skipped.
    """
    bboxes: dict[str, ComponentBBox] = {}
    for cid in component_ids:
        try:
            handle_id = ctx.resolve_component_output(cid, "body")
            solid = ctx.object_store.get(handle_id)
            bbox = measure_component_bbox(solid, cid)
            if bbox is not None:
                bboxes[cid] = bbox
        except (KeyError, Exception):
            continue
    return bboxes
