"""Turning a place in the field into a named face of the model.

A finding has to name a design variable, and a design variable belongs to a
piece of geometry. Nothing connects the two unless the peak can be joined to a
face of the part, and until it can the honest answer is the one the feedback
agent gave on its first real run:

    "I cannot name a generator parameter or CAD face for it from the
     measurements available, so I am filing it as a measured observation
     without a geometry change rather than guessing a variable."

That was correct and it stopped the loop. `face_stress` covers the faces the
load enters through - 72 of them on D27 - and the peak at r = 210.4 mm, z =
17.9 mm is not on any of them. So the agent could measure the peak precisely
and still not say what it was a peak *in*.

This is the missing join, and it is a different one from `face_stress`. That
answers "how much stress is on each of these named faces". This answers
"which face is this place", over every face of the solid rather than a chosen
few - and it is the second question that comes first, because until it is
answered there is no face to ask the first about.

The join is by bounding box rather than by distance to the surface. A face's
centroid can be far from a point that lies on it - the bore cylinder's
centroid sits on the axis, at the centre of the hole - so a proximity test on
the centroid would miss the one face the point is actually on and return the
faces near it instead. A bounding box contains the face, so a point on the
face is in the box, and the candidates that come back are a superset to be
narrowed by the measurements beside them.
"""
from __future__ import annotations

import json
from pathlib import Path

# How many candidate faces a lookup returns before the rest are counted. A
# point where several faces meet returns a handful; a point in open space
# returns nothing; the limit is for the case where a caller asks about a
# region so large that most of the part is inside it.
DEFAULT_LIMIT = 24

# A bounding box is exact, but a point measured from a mesh node and a face
# measured from the kernel can disagree at the last decimal - they come from
# different models of the same surface. This widens the box by a tolerance in
# each direction so a node on a face is not reported as outside it.
DEFAULT_TOLERANCE_MM = 1e-3

# How close a point has to be to a face to be said to lie on it. A mesh node
# sits on the surface the mesh was built from, and the kernel measures the
# surface the document holds; the two agree to within the mesher's own
# tolerance, which is far below this.
ON_FACE_TOLERANCE_MM = 0.05

# What a returned face carries. The measurements, not the whole fact table:
# `uv_bounds` and `edge_count` do not help anyone decide what a peak is, and
# a reply that is mostly noise is a reply that gets skimmed.
REPORTED = (
    "index", "surface_type", "area_mm2", "centroid_mm",
    "centroid_cyl_mm_deg", "normal_cylindrical", "bbox_mm",
)


def face_table(
    bundle: Path | str,
    *,
    feature: str,
    solid_index: int = 0,
    cache_dir: Path | str | None = None,
    normalisation=None,
) -> list[dict]:
    """Every face of one solid, measured. Built once and kept if given a place.

    Measuring a face means asking the geometry kernel about it, and on a part
    with a few thousand faces that is about half a minute - dominated by
    reading the document, not by the faces. A loop asks the same question once
    per revision, so paying it once per run is right and paying it once per
    tool call is not.
    """
    cache: Path | None = None
    if normalisation is not None and not normalisation.is_identity:
        # A cached table was written in a frame this call cannot know. Rebuild
        # into the case frame instead of joining a normalised point to raw
        # face facts.
        cache_dir = None
    if cache_dir is not None:
        cache = Path(cache_dir) / f"solid_faces_{feature}_{solid_index}.json"
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))["faces"]
            except (OSError, ValueError):
                # A cache that cannot be read is not a reason to fail: the
                # table is derivable from the document, which is still there.
                cache = None

    from seekflow_structural.tools import geometry

    session = geometry.open_bundle(Path(bundle))
    try:
        rows = geometry.face_rows(
            session, feature, solid_index, normalisation=normalisation
        )
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()

    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"feature": feature, "solid_index": solid_index,
                        "faces": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
    return rows


def _contains(bbox, point, tolerance: float) -> bool:
    """Whether a bounding box holds a point, within a tolerance.

    `bbox_mm` is `[xmin, ymin, zmin, xmax, ymax, zmax]`, which is the order
    `face_facts` writes and the order the rest of this package reads.
    """
    if not bbox or len(bbox) < 6:
        return False
    for axis in range(3):
        if point[axis] < bbox[axis] - tolerance:
            return False
        if point[axis] > bbox[axis + 3] + tolerance:
            return False
    return True


def locate(
    point_mm: tuple[float, float, float],
    rows: list[dict],
    *,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """The faces whose bounding box holds a point, largest first.

    Ordered by area, because when a point sits where several faces meet the
    largest is usually the one being asked about and the rest are the fillets
    and slivers around it. The order is a convenience and the areas are given,
    so a reader who disagrees can see why it was ordered that way.
    """
    if not rows:
        return {
            "point_mm": list(point_mm),
            "faces": [],
            "limits": ["there was no face table to search"],
        }

    candidates = [
        row for row in rows
        if _contains(row.get("bbox_mm"), point_mm, tolerance_mm)
    ]
    candidates.sort(key=lambda row: row.get("area_mm2") or 0.0, reverse=True)

    limits = []
    if not candidates:
        limits.append(
            "no face of this solid has a bounding box containing that point. "
            "Either the point is in a void - inside a bore, or outside the "
            "part - or the field and the document are not the same model."
        )
    if len(candidates) > limit:
        limits.append(
            f"{len(candidates)} faces contain that point and only the {limit} "
            "largest are listed; the count is the number that matched"
        )

    faces = []
    for row in candidates[:limit]:
        entry = {"index": row.get("index")}
        entry.update({name: row.get(name) for name in REPORTED if name != "index"})
        faces.append(entry)
    return {
        "point_mm": [round(float(v), 6) for v in point_mm],
        "tolerance_mm": tolerance_mm,
        "searched_face_count": len(rows),
        "matching_face_count": len(candidates),
        "faces": faces,
        "limits": limits,
    }


def point_face_distance_mm(face_shape, point_mm) -> float | None:
    """How far a point is from a face, measured by the kernel.

    This is the measurement the bounding box cannot make. A large face's box
    holds points that are nowhere near it - measured on D27, the point at
    r = 210.4 mm, z = 17.9 mm falls inside the box of a 71,347 mm2 cone whose
    centroid is on the axis, and that cone is not the surface the peak is on.
    The box says which faces *could* be the one; only the distance says which
    is, and zero is the answer that means "this point is on this face".

    Returns None when the kernel cannot answer, which is not the same as a
    distance of zero and must not be read as one.
    """
    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.gp import gp_Pnt

        vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*point_mm)).Vertex()
        measure = BRepExtrema_DistShapeShape(vertex, face_shape)
        measure.Perform()
        if not measure.IsDone():
            return None
        return float(measure.Value())
    except Exception:
        # A face the kernel will not measure is a face this tool cannot rank.
        # It stays in the list with no distance rather than dropping out, so
        # the reply does not silently get shorter.
        return None


def locate_point(
    bundle: Path | str,
    *,
    feature: str,
    solid_index: int = 0,
    point_mm: tuple[float, float, float],
    cache_dir: Path | str | None = None,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    limit: int = DEFAULT_LIMIT,
    normalisation=None,
) -> dict:
    """The whole join: a point in the field, and the faces of the model at it.

    Two passes. The bounding box is cheap and comes from the cached table, so
    it narrows a few thousand faces to a handful without touching the kernel.
    The distance then measures those few exactly, which is what tells a face
    the point is on from a face whose box merely contains it.
    """
    rows = face_table(
        bundle,
        feature=feature,
        solid_index=solid_index,
        cache_dir=cache_dir,
        normalisation=normalisation,
    )
    # `face_rows` returns facts without an index, so one is attached here -
    # a face the agent cannot name is a face it cannot ask a further question
    # about, and the index is what everything downstream identifies it by.
    indexed = [{"index": index, **row} for index, row in enumerate(rows)]
    out = locate(point_mm, indexed, tolerance_mm=tolerance_mm, limit=limit)
    out["feature"] = feature
    out["solid_index"] = solid_index

    # Distances are measured for every face whose box matched, not only for
    # the ones the listing kept, so the count of faces the point is actually
    # on is over all of them.
    candidates = [
        row for row in indexed
        if _contains(row.get("bbox_mm"), point_mm, tolerance_mm)
    ]
    if candidates:
        from seekflow_structural.tools import geometry

        distance_point = (
            normalisation.inverse_point(*point_mm)
            if normalisation is not None else point_mm
        )
        session = geometry.open_bundle(Path(bundle))
        try:
            shapes = geometry.faces_of(session, feature, solid_index)
            distances: dict[int, float | None] = {}
            for row in candidates:
                index = int(row["index"])
                if 0 <= index < len(shapes):
                    distances[index] = point_face_distance_mm(
                        shapes[index], distance_point
                    )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()
        for face in out["faces"]:
            face["distance_to_face_mm"] = distances.get(int(face["index"]))
        # A point on a face is at distance zero from it, and that is the
        # answer the join exists to produce - so it is reported at the top
        # level rather than left for a reader to pick out of the list.
        on = [
            index for index, value in distances.items()
            if value is not None and value <= ON_FACE_TOLERANCE_MM
        ]
        out["faces_the_point_lies_on"] = sorted(on)
        out["on_face_tolerance_mm"] = ON_FACE_TOLERANCE_MM
        if not on:
            out["limits"].append(
                "the point is not within "
                f"{ON_FACE_TOLERANCE_MM} mm of any face of this solid. It is "
                "inside the material or outside the part, and neither is a "
                "face a design change can be aimed at."
            )
    return out
