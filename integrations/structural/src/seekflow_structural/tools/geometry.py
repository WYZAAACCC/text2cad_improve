"""Reading faces off a real solid, and filtering them by measurement.

These are the tools a face-finding agent uses. They are deliberately about
geometry in general: a face has an area, a position, a normal, a surface type,
and a place in the feature tree. Nothing here knows what a "load face" or a
"constraint face" is, and nothing here decides - every call returns a measured
set, and the agent reads it.

The raw OCAF facts are measured in the model's source frame. When a case
normalisation is supplied, the numeric facts returned to the agent are
transformed into the case frame before filtering; the face index itself stays
the source TopoDS index. The same transform is supplied to mesh generation and
face-to-node mapping, so every downstream radius and normal has one meaning.
"""
from __future__ import annotations

from pathlib import Path
import math

from seekflow_structural.core.pattern_solids import (
    _explode_solids,
    _feature_entries,
    _feature_entry,
    _load_solids,
    _open,
    _role_face_map,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts
from seekflow_structural.errors import StructuralError

# The filters a query may use, and the fact each is compared against. Kept as
# data so a new filter is one line here rather than a new branch in a loop -
# and so that the filter and the fact it reads cannot drift apart. They did:
# this table said "area" reads "area_mm2" while the predicate looked up the key
# "area", which no face has. Every face failed the area filter on every query,
# so every search came back empty and the agent spent its budget narrowing
# bounds that were already correct. A fact lives on the row directly
# ("area_mm2"), in a slot of centroid_cyl_mm_deg ("r"), or in a slot of
# normal_cylindrical, written here as "normal.<slot>".
CYLINDRICAL_FILTERS = {
    "area": "area_mm2",
    "radial": "r",
    "theta": "theta",
    "z": "z",
    "normal_radial": "normal.radial",
    "normal_tangential": "normal.tangential",
    "normal_axial": "normal.axial",
}

_CYLINDRICAL_SLOTS = {"r": 0, "theta": 1, "z": 2}
_NORMAL_PREFIX = "normal."


def open_bundle(bundle):
    """Open the model bundle's OCAF document - the topology, not the STEP."""
    return _open(bundle)


def features(session) -> list[dict]:
    """Every feature in the document, with a summary of what it produced.

    The agent's starting point, and it is a summary rather than a list of
    names. Naming the features alone forces the agent to call list_solids on
    each one to learn which of them produced the part - on a disc with seven
    features that is seven calls, two of them returning sixty cutter solids
    and twenty thousand characters between them, all to answer a question that
    is one number per feature. So each entry carries its solid count, its
    total face count, and the volume and bounding box of its largest solid.

    The body a boolean cut leaves behind is the largest solid its feature
    produced; that is a property of cutting, not of this part, which is why
    the summary is reported for every model rather than looked up for one.
    """
    out = []
    for entry in _feature_entries(session):
        item = {
            "feature": entry.key.object_id,
            "kind": getattr(entry, "kind", ""),
        }
        try:
            loaded = _load_solids(session, str(entry.key.object_id))
        except Exception as exc:
            # One unreadable feature should not cost the agent the whole
            # listing - but it must not be hidden either, or the feature would
            # simply go missing with no explanation.
            item["error"] = f"{type(exc).__name__}: {exc}"
            out.append(item)
            continue
        if loaded:
            facts = [_solid_facts(solid)[0] for solid in loaded]
            largest = max(
                facts, key=lambda f: f.get("volume_mm3") or 0.0
            )
            item["solids"] = len(loaded)
            item["faces_total"] = sum(
                int(f.get("face_count") or 0) for f in facts
            )
            item["volume_mm3_max"] = round(
                float(largest.get("volume_mm3") or 0.0), 3
            )
            item["bbox_mm_max"] = largest.get("bbox_mm")
        out.append(item)
    return out


def solids(session, feature: str) -> list[dict]:
    """The solids one feature's boolean produced, with their measurements."""
    loaded = _load_solids(session, feature)
    out = []
    for index, solid in enumerate(loaded):
        facts, _faces = _solid_facts(solid)
        entry = {"solid_index": index}
        entry.update(facts)
        out.append(entry)
    return out


def _case_frame_facts(facts: dict, normalisation) -> dict:
    """Express one face's measured facts in the case frame.

    The OCAF face is opened once and its facts are transformed here, not in a
    second geometry backend. The face index remains the original TopoDS index;
    only the numeric frame an agent filters on changes.
    """
    if normalisation is None or facts is None:
        return facts
    out = dict(facts)
    out["source_centroid_mm"] = facts.get("centroid_mm")
    out["source_normal_xyz"] = facts.get("normal_xyz")
    out["source_bbox_mm"] = facts.get("bbox_mm")
    out["source_plane_axis"] = facts.get("plane_axis")
    centroid = facts.get("centroid_mm")
    if centroid is not None:
        x, y, z = normalisation.point(*centroid)
        out["centroid_mm"] = [x, y, z]
        radius = math.hypot(x, y)
        out["centroid_cyl_mm_deg"] = [
            radius,
            math.degrees(math.atan2(y, x)),
            z,
        ]
    normal = facts.get("normal_xyz")
    if normal is not None:
        nx, ny, nz = normalisation.direction(*normal)
        out["normal_xyz"] = [nx, ny, nz]
        centroid = out.get("centroid_mm") or [0.0, 0.0, 0.0]
        radius = math.hypot(centroid[0], centroid[1])
        if radius > 1e-12:
            radial = [centroid[0] / radius, centroid[1] / radius, 0.0]
            tangential = [-radial[1], radial[0], 0.0]
            out["normal_cylindrical"] = {
                "radial": sum([nx, ny, nz][i] * radial[i] for i in range(3)),
                "tangential": sum(
                    [nx, ny, nz][i] * tangential[i] for i in range(3)
                ),
                "axial": nz,
            }
        else:
            out["normal_cylindrical"] = {
                "radial": None, "tangential": None, "axial": nz
            }
    bbox = facts.get("bbox_mm")
    if bbox is not None:
        corners = [
            normalisation.point(x, y, z)
            for x in (bbox[0], bbox[3])
            for y in (bbox[1], bbox[4])
            for z in (bbox[2], bbox[5])
        ]
        out["bbox_mm"] = [
            min(point[0] for point in corners),
            min(point[1] for point in corners),
            min(point[2] for point in corners),
            max(point[0] for point in corners),
            max(point[1] for point in corners),
            max(point[2] for point in corners),
        ]
    plane = facts.get("plane_axis")
    if plane is not None:
        origin = plane.get("origin_mm")
        direction = plane.get("direction")
        if origin is not None:
            plane = dict(plane)
            plane["origin_mm"] = list(normalisation.point(*origin))
        if direction is not None:
            plane = dict(plane)
            plane["direction"] = list(normalisation.direction(*direction))
        out["plane_axis"] = plane
    return out


def face_rows(
    session, feature: str, solid_index: int, normalisation=None
) -> list[dict]:
    """Every face of one solid, measured in the requested case frame."""
    loaded = _load_solids(session, feature)
    if not 0 <= solid_index < len(loaded):
        raise StructuralError(
            "solid_index_out_of_range",
            f"solid_index {solid_index} is outside 0..{len(loaded) - 1} for "
            f"feature {feature!r}",
            "facefind",
        )
    out = []
    for index, face in enumerate(faces_of_solid(loaded[solid_index])):
        row = _case_frame_facts(face_facts(face), normalisation)
        # The row's index is not a geometric fact, but it is the handle the
        # agent and the benchmark use to name the face. Keeping it beside the
        # measured facts avoids a second enumeration order being assumed
        # somewhere else.
        row["face_index"] = index
        out.append(row)
    return out


def faces_of_solid(solid):
    """The live TopoDS faces of one solid.

    `_solid_facts` returns its scalar facts and the faces together, because
    walking the solid for one and then again for the other would double the
    kernel work on a part with thousands of faces.
    """
    _facts, faces = _solid_facts(solid)
    return faces


def _get(row: dict, name: str):
    """The fact a filter compares against, resolved through the table above.

    None means the face has no value for it - a normal on a face whose centroid
    sits on the axis is not measured, and `query` treats that as "this filter
    cannot speak for this face" rather than as a failure to match.
    """
    fact = CYLINDRICAL_FILTERS.get(name)
    if fact is None:
        return None
    if fact.startswith(_NORMAL_PREFIX):
        slot = fact[len(_NORMAL_PREFIX):]
        return (row.get("normal_cylindrical") or {}).get(slot)
    if fact in _CYLINDRICAL_SLOTS:
        return row["centroid_cyl_mm_deg"][_CYLINDRICAL_SLOTS[fact]]
    return row.get(fact)


def query(
    rows: list[dict], filters: dict, *, surface_type: str = "",
    origin_relation: str = "", origin_operand: str = "",
) -> list[int]:
    """Indices of the faces that satisfy every filter given.

    A filter whose value is None is not applied. Out-of-range bounds are the
    caller's business: this reports what matched, not what should have.

    `origin_relation` and `origin_operand` are the one part of the filter that
    is not a measurement. They ask where a face came from - whether the
    operation modified it or carried it through, and which of the operation's
    inputs it descends from - and they are what makes two sets of faces
    separable when every measurement they have is the same.
    """
    matched = []
    for index, row in enumerate(rows):
        if surface_type and row.get("surface_type") != surface_type:
            continue
        if origin_relation and row.get("origin_relation") != origin_relation:
            continue
        if origin_operand and row.get("origin_operand") != origin_operand:
            continue
        ok = True
        for name, bounds in filters.items():
            if bounds is None:
                continue
            low, high = bounds
            value = _get(row, name)
            if value is None:
                # The face has no measured value for a filter that was set.
                # It cannot be claimed to satisfy a bound nobody could check,
                # so it is left out - and the caller sees the count drop.
                ok = False
                break
            if value < low or value > high:
                ok = False
                break
        if ok:
            matched.append(index)
    return matched


# There was a `histogram` here, reported beside the spans so a set of two
# clusters would not come back as one median in the gap between them. It
# was removed after being measured: over twenty-four runs each way it
# raised the submit rate from 39% to 67% and the number of *wrong*
# submissions from none to nine, every one the same mistake. It made the
# agent more decisive without making it better informed, and the chain
# accepted all nine. A confident wrong answer is worse than a slow one.
# The fields a listing carries, in order. A delimited row is five times
# smaller than the same values under long JSON keys, and the keys are what
# stop a set of two hundred from being shown at all.
COMPACT_COLUMNS = ("index", "type", "radius_mm", "theta_deg", "z_mm",
                   "normal_radial", "normal_tangential", "area_mm2")


def compact_row(rows: list[dict], index: int) -> str:
    row = rows[index]
    radius, theta, z = row["centroid_cyl_mm_deg"]
    normal = row.get("normal_cylindrical") or {}
    fields = [
        str(index),
        str(row.get("surface_type") or "unknown"),
        f"{float(radius):.2f}",
        f"{float(theta):.1f}",
        f"{float(z):.2f}",
        "" if normal.get("radial") is None else f"{float(normal['radial']):.3f}",
        "" if normal.get("tangential") is None
        else f"{float(normal['tangential']):.3f}",
        f"{float(row.get('area_mm2') or 0.0):.1f}",
    ]
    return "|".join(fields)


def compact(rows: list[dict], indices: list[int], budget_chars: int) -> dict:
    """A terse listing, as many faces as a reply can carry.

    `describe` reports ten fields a face under their long names, which is right
    for the three faces an agent has asked about and wrong for the two hundred
    it is trying to search: 195 faces cost 43 KB that way and 9 KB this way,
    and the difference is whether the set can be shown at all. An agent that
    cannot see the set it just selected asks for it again - measured, up to
    twenty-five times, which is a whole budget.

    Bounded by characters rather than by a count, because the constraint is
    the size of the reply. A limit of sixty faces meant a set of sixty-one was
    shown in full and a set of sixty-two was not shown at all, and the sets
    this agent actually selects land just the wrong side of that line.
    """
    listed = []
    used = 0
    for index in indices:
        if not 0 <= index < len(rows):
            continue
        line = compact_row(rows, index)
        if listed and used + len(line) + 3 > budget_chars:
            break
        listed.append(line)
        used += len(line) + 3
    return {
        "columns": list(COMPACT_COLUMNS),
        "faces": listed,
        "faces_listed": len(listed),
        "faces_withheld": len(indices) - len(listed),
    }


def _rounded(value, digits: int):
    """A fact that was never measured stays None.

    `face_facts` reports radial and tangential as None for a face whose
    centroid lies on the axis, and `dict.get(key, 0.0)` does not guard that -
    the key is present and its value is None, so the default never applies.
    Defaulting to 0.0 would be worse than the crash it replaces: it reports a
    normal of zero as a measurement, and a face that was never measured would
    then be filtered on as though it had been.
    """
    return None if value is None else round(float(value), digits)


def describe(rows: list[dict], indices: list[int]) -> list[dict]:
    """The measured facts for the named faces, in a shape an agent can read."""
    out = []
    for index in indices:
        if not 0 <= index < len(rows):
            continue
        row = rows[index]
        radius, theta, z = row["centroid_cyl_mm_deg"]
        normal = row.get("normal_cylindrical") or {}
        out.append({
            "face_index": index,
            "surface_type": row.get("surface_type"),
            "area_mm2": _rounded(row.get("area_mm2"), 4),
            "radius_mm": _rounded(radius, 4),
            "theta_deg": _rounded(theta, 4),
            "z_mm": _rounded(z, 4),
            "normal_radial": _rounded(normal.get("radial"), 6),
            "normal_axial": _rounded(normal.get("axial"), 6),
            "normal_tangential": _rounded(normal.get("tangential"), 6),
            "edge_count": row.get("edge_count"),
        })
    return out


def summarise(rows: list[dict], indices: list[int]) -> dict:
    """What a matched set is made of, without listing it.

    The counts and ranges an agent needs to choose its next filter: which
    surface types are in the set, over what radial range, and which way the
    normals point. A page of sixty faces out of several thousand says none of
    that, and an agent given only pages has no way to narrow a search - it can
    only walk, and it cannot finish walking.
    """
    if not indices:
        return {"empty": True}
    selected = [rows[i] for i in indices]

    types: dict[str, int] = {}
    for row in selected:
        key = str(row.get("surface_type") or "unknown")
        types[key] = types.get(key, 0) + 1

    def span(name, getter):
        values = []
        for row in selected:
            value = getter(row)
            if value is not None:
                values.append(float(value))
        if not values:
            return None
        values.sort()
        return {
            "min": round(values[0], 4),
            "median": round(values[len(values) // 2], 4),
            "max": round(values[-1], 4),
        }

    return {
        "count": len(selected),
        "surface_types": dict(
            sorted(types.items(), key=lambda item: -item[1])
        ),
        "area_mm2": span("area", lambda r: r.get("area_mm2")),
        "radius_mm": span("r", lambda r: r["centroid_cyl_mm_deg"][0]),
        "z_mm": span("z", lambda r: r["centroid_cyl_mm_deg"][2]),
        "normal_radial": span(
            "nr", lambda r: (r.get("normal_cylindrical") or {}).get("radial")
        ),
        "normal_axial": span(
            "na", lambda r: (r.get("normal_cylindrical") or {}).get("axial")
        ),
    }


def role_ids(session, faces) -> list[str]:
    """Persistent OCAF names for a set of faces, where they have one.

    These survive a design revision - measured on D19 across a 2% cutter
    perturbation at under 1.7% area change and under 0.14 mm of centroid
    movement - which is why a selection is worth recording with them. A run
    that records only face indices has to re-find its faces by geometry the
    next time the part changes.

    NOT SAFE ON A WHOLE PART. Resolving a role reads a TNaming attribute, and
    on a real document some of those attributes are corrupt badly enough to
    fault the process natively - 0xC0000005, measured at 13 roles on one
    19,473-role part. A native fault is not an exception: this function used to
    wrap the call in `except Exception` and return an empty list, which reads
    as "this part has no role names" but is in fact reached only for the
    Python-level failures, while the case that actually happens kills the run.
    There is no fallback here to rely on.

    Resolve roles through the face-evolution index instead, which does it one
    slice per subprocess so a crash costs a retry rather than the run.
    """
    mapping = _role_face_map(session, faces)
    return [str(value) for value in mapping.values()]


def faces_of(session, feature: str, solid_index: int):
    """The live TopoDS faces, for callers that need more than the facts."""
    loaded = _load_solids(session, feature)
    if not 0 <= solid_index < len(loaded):
        raise StructuralError(
            "solid_index_out_of_range",
            f"solid_index {solid_index} is outside 0..{len(loaded) - 1}",
            "facefind",
        )
    return faces_of_solid(loaded[solid_index])


def read_mesh_nodes(mesh_inp) -> dict:
    """Node coordinates from an APDL mesh."""
    nodes = {}
    for line in Path(mesh_inp).read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if not line.startswith("N,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 5:
            continue
        try:
            nodes[int(parts[1])] = tuple(float(v) for v in parts[2:5])
        except ValueError:
            continue
    return nodes


def _plane_distance(coord, facts):
    """How far a point is from a face's plane, or None if it is not in range.

    Only planar faces are handled, and the limitation is the caller's to
    report: a curved selected face maps to nothing here, and a mapping that
    silently returns an empty set is how that becomes a load applied to no
    material at all.
    """
    plane = facts.get("plane_axis")
    bbox = facts.get("bbox_mm")
    if not plane or not bbox:
        return None
    for i in range(3):
        if not (bbox[i] - 1e-4 <= coord[i] <= bbox[i + 3] + 1e-4):
            return None
    origin = plane["origin_mm"]
    normal = plane["direction"]
    return abs(
        (coord[0] - origin[0]) * normal[0]
        + (coord[1] - origin[1]) * normal[1]
        + (coord[2] - origin[2]) * normal[2]
    )


def map_selection_to_nodes(
    bundle, feature: str, solid_index: int, face_indices, mesh_inp,
    tolerance_mm: float = 1e-4, normalisation=None,
) -> dict:
    """Which mesh nodes lie on each selected face.

    The bridge between the faces a selection named and the nodes a load can be
    applied to. Kept in the package rather than in the retired standalone
    script, so the chain has one implementation of it.
    """
    session = open_bundle(Path(bundle))
    try:
        loaded = _load_solids(session, feature)
        if not 0 <= solid_index < len(loaded):
            raise StructuralError(
                "solid_index_out_of_range",
                f"solid_index {solid_index} does not exist on {feature!r}",
                "mesh",
            )
        faces = faces_of_solid(loaded[solid_index])
        nodes = read_mesh_nodes(mesh_inp)
        per_face = {}
        counts: dict[int, int] = {}
        union: set[int] = set()
        for face_index in face_indices:
            if not 0 <= face_index < len(faces):
                raise StructuralError(
                    "face_index_out_of_range",
                    f"face index {face_index} does not exist on {feature!r}",
                    "mesh",
                )
            facts = _case_frame_facts(face_facts(faces[face_index]), normalisation)
            matches = []
            worst = 0.0
            for node_id, coord in nodes.items():
                distance = _plane_distance(coord, facts)
                if distance is None or distance > tolerance_mm:
                    continue
                matches.append(node_id)
                union.add(node_id)
                counts[node_id] = counts.get(node_id, 0) + 1
                worst = max(worst, distance)
            per_face[str(face_index)] = {
                "node_count": len(matches),
                "node_ids": matches,
                "max_plane_distance_mm": worst,
                "area_mm2": facts["area_mm2"],
                "centroid_mm": facts.get("centroid_mm"),
                "normal_xyz": facts.get("normal_xyz"),
                "normal_cylindrical": facts.get("normal_cylindrical"),
            }
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            close()

    return {
        "bundle": str(Path(bundle).resolve()),
        "mesh_inp": str(Path(mesh_inp).resolve()),
        "feature": feature,
        "solid_index": solid_index,
        "selected_face_indices": list(face_indices),
        "tolerance_mm": tolerance_mm,
        "mapped_face_count": sum(
            1 for row in per_face.values() if row["node_count"] > 0
        ),
        "union_node_count": len(union),
        "union_node_ids": sorted(union),
        "overlap_node_count": sum(1 for c in counts.values() if c > 1),
        "per_face": per_face,
    }


# Re-exported so a caller does not have to know which module each helper
# lives in; they are all part of the same geometry vocabulary.
__all__ = [
    "open_bundle", "features", "solids", "face_rows", "query", "describe",
    "role_ids", "faces_of", "face_facts", "_explode_solids", "_feature_entry",
    "CYLINDRICAL_FILTERS",
]
