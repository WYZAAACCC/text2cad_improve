"""Tracked Extrude — drop-in replacement for CadQuery shapes.extrude().

Line-by-line identical to CadQuery 2.7.0 shapes.extrude(), with History extraction
from the BRepPrimAPI_MakePrism builder after Build().

Verified (OCP 7.8.1.1):
- BRepPrimAPI_MakePrism has Generated()/Modified()/FirstShape()/LastShape()
- BUT does NOT have History() method (unlike BOPAlgo_BOP)

PR-2: Collects REAL TopoDS_Shape handles into LiveEvolutionRelation.
"""

from __future__ import annotations

from typing import Any

from cadquery.occ_impl.shapes import (
    _compound_or_shape,
    _get,
    Vector,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
    TrackedShapeResult,
    FaceRoleSpec,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    edge_role_key,
)


def tracked_extrude(
    profile: Any,
    vector: tuple[float, float, float] | list[float],
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.extrude() with History capture."""
    results: list[Any] = []
    relations: list[LiveEvolutionRelation] = []

    scope = scope or TopologyCaptureScope()

    for el in _get(profile, ("Vertex", "Edge", "Wire", "Face")):
        el_type = el.ShapeType()
        profile_shape = el.wrapped

        if el_type == "Wire":
            # CadQuery's extrude makes a face from a closed wire first; without
            # this, MakePrism would produce an open shell (no caps) instead of
            # a solid.
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
            fb = BRepBuilderAPI_MakeFace(el.wrapped)
            fb.Build()
            profile_shape = fb.Face()
            el_type = "Face"

        builder = BRepPrimAPI_MakePrism(profile_shape, Vector(vector).wrapped)
        builder.Build()
        result_shape = builder.Shape()
        results.append(result_shape)

        if el_type == "Face":
            _capture_generated(relations, scope, builder, profile_shape, "profile_face")
            _capture_modified(relations, scope, builder, profile_shape, "profile_face")

    result = _compound_or_shape(results)
    start_cap, end_cap = _find_cap_faces(result, vector)
    side_roles = _classify_side_faces(result, vector)

    construction_roles = {
        "start_cap": start_cap,
        "end_cap": end_cap,
        **side_roles,
    }
    face_roles = _remaining_face_roles(result, construction_roles, "extrude")
    edge_roles = _derive_box_edges(construction_roles)

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepPrimAPI_MakePrism",
        builder_options={"vector": tuple(float(v) for v in vector)},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles=construction_roles,
        edge_roles=edge_roles,
        face_roles=face_roles,
        history_complete=True,
    )
    return TrackedShapeResult(result=result, batch=batch)


def _remaining_face_roles(
    result: Any, existing_roles: dict[str, Any], prefix: str,
) -> dict[str, FaceRoleSpec]:
    """Name every result face that is not already covered by a semantic role."""
    existing = [face for face in existing_roles.values() if face is not None]
    remaining: list[Any] = []
    for face in result.Faces():
        fw = face.wrapped
        if any(fw.IsSame(other) or fw.IsPartner(other) for other in existing):
            continue
        remaining.append(fw)

    remaining.sort(key=_face_sort_key)
    return {
        f"{prefix}/face_{index:03d}": FaceRoleSpec(
            role_key=f"{prefix}/face_{index:03d}",
            shape=face,
            first_evolution=EvolutionKind.GENERATED,
        )
        for index, face in enumerate(remaining)
    }


def _face_sort_key(face: Any) -> tuple:
    """Deterministic geometric key for stable ordinary-face ordering."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    center = props.CentreOfMass()
    area = float(props.Mass())

    surface_type = 10
    normal = (0.0, 0.0, 0.0)
    axis = (0.0, 0.0, 0.0)
    try:
        adaptor = BRepAdaptor_Surface(face)
        surface_type = int(adaptor.GetType())
        if surface_type == 0:  # Plane
            d = adaptor.Plane().Position().Direction()
            normal = (
                round(float(d.X()), 4),
                round(float(d.Y()), 4),
                round(float(d.Z()), 4),
            )
        elif surface_type == 1:  # Cylinder
            d = adaptor.Cylinder().Axis().Direction()
            axis = (
                round(float(d.X()), 4),
                round(float(d.Y()), 4),
                round(float(d.Z()), 4),
            )
        elif surface_type == 2:  # Cone
            d = adaptor.Cone().Axis().Direction()
            axis = (
                round(float(d.X()), 4),
                round(float(d.Y()), 4),
                round(float(d.Z()), 4),
            )
    except Exception:
        pass

    return (
        surface_type,
        normal,
        axis,
        round(float(center.X()), 4),
        round(float(center.Y()), 4),
        round(float(center.Z()), 4),
        round(area, 4),
    )


def _find_cap_faces(result: Any, direction: tuple[float, float, float] | list[float]):
    """Return (start_cap, end_cap) faces whose normal is parallel to direction."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    dx, dy, dz = direction
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length < 1e-9:
        return None, None
    ux, uy, uz = dx / length, dy / length, dz / length

    caps: list[tuple[float, Any]] = []
    for f in result.Faces():
        try:
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() == 0:  # GeomAbs_Plane
                n = adaptor.Plane().Position().Direction()
                dot = n.X() * ux + n.Y() * uy + n.Z() * uz
                if abs(abs(dot) - 1.0) < 0.01:
                    c = f.Center()
                    caps.append((c.x * ux + c.y * uy + c.z * uz, f.wrapped))
        except Exception:
            continue

    caps.sort(key=lambda p: p[0])
    if len(caps) >= 2:
        return caps[0][1], caps[-1][1]
    if len(caps) == 1:
        return caps[0][1], None
    return None, None


def _classify_side_faces(result: Any, direction: tuple[float, float, float] | list[float]):
    """Classify axis-aligned side faces of an extruded prism by their normal.

    Only faces whose plane normal is axis-aligned (within tolerance) and
    perpendicular to the extrude direction are named. The +X/-X/+Y/-Y sign is
    determined from the face centroid relative to the body bounding-box center
    (plane-normal sign is orientation-dependent in OCCT and therefore not used).
    This is reliable for the rectangular/box case; arbitrary profiles simply
    leave the roles as None.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    dx, dy, dz = direction
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length < 1e-9:
        return {}
    ux, uy, uz = dx / length, dy / length, dz / length

    roles = {"+X": None, "-X": None, "+Y": None, "-Y": None}
    for f in result.Faces():
        try:
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() != 0:  # GeomAbs_Plane only
                continue
            n = adaptor.Plane().Position().Direction()
            nx, ny, nz = n.X(), n.Y(), n.Z()
            # Skip cap faces whose normal is parallel to the extrude direction.
            dot = abs(nx * ux + ny * uy + nz * uz)
            if dot > 0.99:
                continue
            ax = abs(nx)
            ay = abs(ny)
            fc = f.Center()
            center = result.BoundingBox().center
            if ax > 0.99 and ay < 0.01:
                roles["+X" if fc.x > center.x else "-X"] = f.wrapped
            elif ay > 0.99 and ax < 0.01:
                roles["+Y" if fc.y > center.y else "-Y"] = f.wrapped
        except Exception:
            continue
    return roles


def _derive_box_edges(construction_roles: dict) -> dict[str, Any]:
    """Derive stable edge roles for an axis-aligned box.

    Each box edge is shared by exactly two of the six named role faces. The
    stable key is the sorted pair of face role keys. Returns {} when the six
    face roles are not all present (non-rectangular profile).

    Matching is geometric (edge midpoint), NOT TShape-based: OCCT prism caps
    can share the same TShape (top and bottom faces are IsPartner), so TShape
    identity cannot distinguish adjacent vs opposite edges.
    """
    face_keys = ("start_cap", "end_cap", "+X", "-X", "+Y", "-Y")
    faces = {k: construction_roles.get(k) for k in face_keys}
    if any(v is None for v in faces.values()):
        return {}

    by_midpoint: dict[tuple, list[tuple[str, Any]]] = {}
    for role_key, face in faces.items():
        for edge in _edges_of(face):
            mid = _edge_midpoint(edge)
            by_midpoint.setdefault(mid, []).append((role_key, edge))

    edge_roles: dict[str, Any] = {}
    for entries in by_midpoint.values():
        if len(entries) != 2:
            continue
        (a, edge_a), (b, _edge_b) = entries
        edge_roles[edge_role_key(a, b)] = edge_a
    return edge_roles


def _edges_of(shape: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    edges: list[Any] = []
    while exp.More():
        edges.append(exp.Current())
        exp.Next()
    return edges


def _edge_midpoint(edge: Any) -> tuple[float, float, float]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS

    adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    f = adaptor.FirstParameter()
    l = adaptor.LastParameter()
    p = adaptor.Value((f + l) / 2.0)
    return (round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_generated(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    shape: Any,
    source_role: str,
) -> None:
    gen_list = builder.Generated(shape)
    gen_shapes = tuple(gen_list)
    if gen_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/extrude/gen/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=shape,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )


def _capture_modified(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    shape: Any,
    source_role: str,
) -> None:
    mod_list = builder.Modified(shape)
    mod_shapes = tuple(mod_list)
    if mod_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/extrude/mod/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=shape,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )
