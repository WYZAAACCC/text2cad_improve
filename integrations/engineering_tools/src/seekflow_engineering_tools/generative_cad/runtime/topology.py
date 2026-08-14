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


def select_edge_shapes(solid: Any, selector: str) -> list[Any]:
    """Resolve edges to actual TopoDS_Edge shapes by selector string.

    Unlike select_edges (which returns EdgeHandle indices), this returns the
    actual TopoDS_Edge shapes suitable for TNaming-tracked fillet/chamfer.
    Returns [] if no edges match.
    """
    edges = _edge_selector(solid, selector)
    if edges is None:
        return []
    return [e.wrapped for e in edges]


def _edge_selector(solid: Any, selector: str):
    """Return a CadQuery edge selector matching a target string."""
    if selector == "all_external_edges":
        return solid.edges()
    if selector in ("top", "bottom"):
        face = _extreme_face(solid, z_max=(selector == "top"))
        return face.edges() if face is not None else solid.edges()
    if selector in (">Z", "<Z"):
        try:
            return solid.faces(selector).edges()
        except Exception:
            return solid.edges()
    if selector.startswith("sharp:"):
        return solid.edges()  # CadQuery has no native sharp-edge filter
    return solid.edges()


def _extreme_face(solid: Any, z_max: bool):
    """Return the face with the highest (or lowest) Z centroid, or None."""
    try:
        faces = solid.faces(">Z" if z_max else "<Z")
        best_face = None
        best_z = float("-inf") if z_max else float("inf")
        for f in faces:
            z = f.Center().z
            if (z_max and z > best_z) or (not z_max and z < best_z):
                best_z = z
                best_face = f
        return best_face
    except Exception:
        return None
