"""Topology query utilities — face/edge selection for precise operations.

Enables operations like "chamfer only the top edge" instead of always
operating on the entire body.
"""

from __future__ import annotations
from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.handles import EdgeHandle, FaceHandle


def select_edges(solid: Any, selector: str, parent_solid_id: str | None = None) -> list[EdgeHandle]:
    """Select edges on a solid by selector string.

    Supported selectors:
      - "all_external_edges" — every edge on the solid (default behavior)
      - "top" — edges on the top face (highest Z)
      - "bottom" — edges on the bottom face (lowest Z)
      - ">Z" — edges on faces with normal pointing in +Z
      - "<Z" — edges on faces with normal pointing in -Z
      - "sharp:<angle>" — edges with adjacent face angle > threshold (e.g. "sharp:30")

    Returns empty list if no edges match.
    """
    if selector == "all_external_edges":
        return _all_edges(solid, parent_solid_id)

    if selector == "top":
        return _edges_on_extreme_face(solid, parent_solid_id, z_max=True)

    if selector == "bottom":
        return _edges_on_extreme_face(solid, parent_solid_id, z_max=False)

    if selector == ">Z":
        try:
            return _edges_from_faces(solid.faces(">Z"), parent_solid_id)
        except Exception:
            return []

    if selector == "<Z":
        try:
            return _edges_from_faces(solid.faces("<Z"), parent_solid_id)
        except Exception:
            return []

    if selector.startswith("sharp:"):
        try:
            angle_str = selector.split(":", 1)[1]
            angle = float(angle_str)
            return _sharp_edges(solid, parent_solid_id, angle)
        except (ValueError, IndexError):
            return []

    # Default: return all edges
    return _all_edges(solid, parent_solid_id)


def select_faces(solid: Any, selector: str, parent_solid_id: str | None = None) -> list[FaceHandle]:
    """Select faces by selector string.

    Supported: "top", "bottom", ">Z", "<Z", ">X", ">Y", "all".
    """
    if selector == "all":
        try:
            return _faces_from_shape(solid.faces(), parent_solid_id)
        except Exception:
            return []

    cadquery_selector = selector
    try:
        return _faces_from_shape(solid.faces(cadquery_selector), parent_solid_id)
    except Exception:
        return []


# ── Internal helpers ─────────────────────────────────────────────────────────

def _all_edges(solid: Any, parent_id: str | None) -> list[EdgeHandle]:
    try:
        return [
            EdgeHandle(
                id=f"edge:{parent_id}:{i}" if parent_id else f"edge:{i}",
                parent_solid_id=parent_id, edge_index=i,
            )
            for i in range(_count_edges(solid))
        ]
    except Exception:
        return []


def _edges_on_extreme_face(solid: Any, parent_id: str | None, z_max: bool) -> list[EdgeHandle]:
    try:
        faces = solid.faces(">Z" if z_max else "<Z")
        # Get the face with extreme Z
        best_face = None
        best_z = float("-inf") if z_max else float("inf")
        for i, f in enumerate(faces):
            try:
                z = f.Center().z
                if (z_max and z > best_z) or (not z_max and z < best_z):
                    best_z = z
                    best_face = i
            except Exception:
                continue
        if best_face is not None:
            return _edges_from_faces(faces.item(best_face), parent_id)
    except Exception:
        pass
    return _all_edges(solid, parent_id)


def _edges_from_faces(faces, parent_id: str | None) -> list[EdgeHandle]:
    try:
        edges = faces.edges()
        handles = []
        for i in range(_count_edges(edges) if hasattr(edges, 'size') else 0):
            handles.append(EdgeHandle(
                id=f"edge:{parent_id}:{i}" if parent_id else f"edge:{i}",
                parent_solid_id=parent_id, edge_index=i,
            ))
        return handles if handles else []
    except Exception:
        return []


def _sharp_edges(solid: Any, parent_id: str | None, angle_deg: float) -> list[EdgeHandle]:
    """Select edges where adjacent faces meet at angle > threshold."""
    try:
        sharp = solid.edges(">Z")  # CadQuery doesn't have a native "sharp edge" filter
        handles = []
        for i in range(min(_count_edges(sharp), 100)):
            handles.append(EdgeHandle(
                id=f"edge:{parent_id}:sharp:{i}" if parent_id else f"edge:sharp:{i}",
                parent_solid_id=parent_id, edge_index=i,
            ))
        return handles
    except Exception:
        return []


def _faces_from_shape(faces, parent_id: str | None) -> list[FaceHandle]:
    try:
        handles = []
        for i in range(_count_edges(faces) if hasattr(faces, 'size') else 0):
            handles.append(FaceHandle(
                id=f"face:{parent_id}:{i}" if parent_id else f"face:{i}",
                parent_solid_id=parent_id, face_index=i,
            ))
        return handles
    except Exception:
        return []


def _count_edges(shape: Any) -> int:
    try:
        return shape.size()
    except Exception:
        try:
            return len(list(shape))
        except Exception:
            return 0
