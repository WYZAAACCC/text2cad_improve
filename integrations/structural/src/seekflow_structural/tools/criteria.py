"""Checking a set of faces against the criterion its selector declared.

What this replaces: a validator that hard-coded one component's idea of a load
face - planar, a radial normal of at least 0.2, no axial component, a single
radial sign, an even count, every face mirrored by a partner. That is a
fir-tree flank. A blade platform that curves, or a bracket bolted through a
cylindrical boss, was rejected by it without being told why, and the message
said "must be planar" as though planarity were a law of physics.

The agent now states what it means and this checks the submission against
*that*. Load faces, constraint faces, symmetry faces and post-processing
sections are the same machinery with a different criterion, and the harness no
longer knows what any of them are.

Every function here returns measurements. Nothing raises on a failed clause:
a clause that is not met is a residual to report, and whether it matters is
the agent's call.
"""
from __future__ import annotations

import math

from seekflow_structural.case.model import Criterion, NormalClause, Vec3

# A face normal's components are measured in the frame the case chose, so a
# part whose axis is not global Z is described by its own geometry rather than
# by how it happened to be modelled.
COMPONENTS = ("face_normal", "radial", "axial", "tangential", "frame_axis")


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a):
    length = _norm(a)
    return [v / length for v in a] if length > 0 else [0.0, 0.0, 0.0]


def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _reference_frame(axis):
    """Two unit vectors spanning the plane perpendicular to the axis.

    An azimuth has to be measured from a direction that is fixed in the model.
    Deriving it from the face's own radial direction is what this used to do,
    and it makes every point's azimuth zero by construction - the face is at
    zero degrees in a frame that rotates with the face. A symmetry check that
    matches partners by azimuth then never matches one, so every clause
    reported `unmatched_fraction: 1.0` and an agent that read it would
    conclude a correct set was wrong.

    The first world axis with a usable projection is taken as the reference,
    which for an axis of +Z gives +X and so agrees with the azimuth the rest
    of the package measures.
    """
    for candidate in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        projection = [
            candidate[i] - _dot(candidate, axis) * axis[i] for i in range(3)
        ]
        if _norm(projection) > 1e-6:
            e1 = _unit(projection)
            return e1, _cross(axis, e1)
    # Only reachable for a degenerate axis, which the caller has already
    # normalised away; returned rather than raised so the projection stays
    # total.
    return [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]


def cylindrical(
    point: Vec3, normal: Vec3, axis_origin: Vec3, axis_direction: Vec3
) -> dict:
    """Radius, angle and the three normal components, in the case frame.

    Radius and the normal decomposition are relative to the axis the case
    chose. Computing them about global Z instead would describe a part by
    where it sits in the assembly rather than by its own geometry.
    """
    axis = _unit(axis_direction.as_tuple())
    rel = [
        point.as_tuple()[i] - axis_origin.as_tuple()[i] for i in range(3)
    ]
    axial = _dot(rel, axis)
    radial_vec = [rel[i] - axial * axis[i] for i in range(3)]
    radius = _norm(radial_vec)
    radial_dir = (
        [v / radius for v in radial_vec] if radius > 0 else [0.0, 0.0, 0.0]
    )
    tangential_dir = [
        axis[1] * radial_dir[2] - axis[2] * radial_dir[1],
        axis[2] * radial_dir[0] - axis[0] * radial_dir[2],
        axis[0] * radial_dir[1] - axis[1] * radial_dir[0],
    ]

    n = _unit(normal.as_tuple())
    e1, e2 = _reference_frame(axis)
    return {
        "radius_mm": radius,
        "axial_mm": axial,
        "theta_deg": (
            math.degrees(math.atan2(_dot(rel, e2), _dot(rel, e1))) % 360.0
            if radius > 0 else 0.0
        ),
        "radial": _dot(n, radial_dir),
        "tangential": _dot(n, tangential_dir),
        "axial": _dot(n, axis),
        "frame_axis": _dot(n, axis),
        "face_normal": n,
    }


def _component(clause: NormalClause, measured: dict) -> float | None:
    if clause.component == "face_normal":
        return None
    value = measured.get(clause.component)
    return None if value is None else float(value)


# A bound left at its default is not a bound. Measured against it, any excess
# would be divided by ~1e30 and read as zero - which is precisely the
# distinction this number exists to make.
UNBOUNDED = 1e29


def _excess_fraction(value: float, clause: NormalClause) -> float:
    """How far outside the clause, relative to the bound that was crossed.

    Relative to that bound and not to the wider of the two: a clause that
    bounds only above has an unbounded below, and scaling by the unbounded
    side would report every violation as zero.
    """
    if clause.maximum < UNBOUNDED and value > clause.maximum:
        return (value - clause.maximum) / max(abs(clause.maximum), 1e-9)
    if clause.minimum > -UNBOUNDED and value < clause.minimum:
        return (clause.minimum - value) / max(abs(clause.minimum), 1e-9)
    return 0.0


def clause_residuals(
    criterion: Criterion, measured: dict
) -> list[dict]:
    """Each clause against one face: what was asked, what was measured."""
    out = []
    for index, clause in enumerate(criterion.normal_clauses):
        value = _component(clause, measured)
        if value is None:
            out.append({
                "clause": index,
                "component": clause.component,
                "status": "unmeasurable",
                "note": f"{clause.component} has no scalar form to compare",
            })
            continue
        within = clause.minimum <= value <= clause.maximum
        out.append({
            "clause": index,
            "component": clause.component,
            "value": round(value, 6),
            "minimum": (
                None if clause.minimum <= -UNBOUNDED else clause.minimum
            ),
            "maximum": (
                None if clause.maximum >= UNBOUNDED else clause.maximum
            ),
            "within": within,
            "excess_fraction": round(_excess_fraction(value, clause), 6),
        })
    return out


def _relative_difference(a: float, b: float) -> float:
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale


def _normal_sign_satisfied(rule: str, dot: float) -> bool:
    """`same` and `opposite` are claims about the pair; anything else is not.

    Stated as a bound on the dot product rather than on a sign of the radial
    component, because the two faces of a pair sit on opposite sides of the
    feature: it is the angle between them that says whether they face the same
    way, and that is what the dot product of two unit normals already is.
    """
    if rule == "same":
        return dot >= 0.0
    if rule == "opposite":
        return dot < 0.0
    return True


def symmetry_residuals(
    criterion: Criterion,
    rows: list[dict],
    measured: list[dict],
    mirror_azimuth_deg: float | None = None,
) -> dict:
    """Whether the submitted set is closed under the symmetry it claims.

    Reported, never enforced. A set that is not closed may be exactly what the
    agent meant - a single flank, a half section - and it is the residual, not
    a rejection, that lets it say so.

    Three of the clause's four fields used to be inert: `kind` was echoed back
    but never consulted, so a mirror was silently evaluated as a rotation;
    `area_rel_tol` was declared and pair areas were never compared; and
    `normal_sign` was declared and never looked at. The agent could set all
    three and get a `satisfied: true` that had tested none of them. A control
    the schema offers and the check ignores is worse than no control, because
    the residual is read as evidence.
    """
    clause = criterion.symmetry
    if clause is None:
        return {"declared": False}

    if clause.kind == "mirror_plane":
        if mirror_azimuth_deg is None:
            # The plane's azimuth is a fact about the model, not about this
            # clause, and without it there is nothing to reflect about. Said
            # plainly rather than assumed to be zero.
            return {
                "declared": True,
                "kind": clause.kind,
                "ref": clause.ref,
                "status": "unmeasurable",
                "note": (
                    "a mirror_plane clause needs the plane's azimuth; this "
                    "check was not given one, so the clause was not evaluated"
                ),
            }

        def target_theta(theta: float) -> float:
            return (2.0 * mirror_azimuth_deg - theta) % 360.0
    else:
        step = 360.0 / float(clause.ref or 1.0)

        def target_theta(theta: float) -> float:
            return (theta + step) % 360.0

    unmatched: list[int] = []
    detail: list[dict] = []
    pairs: list[dict] = []
    for index, (row, item) in enumerate(zip(rows, measured, strict=False)):
        target = target_theta(item["theta_deg"])
        partner = None
        rejected: list[dict] = []
        for other_index, other in enumerate(measured):
            if other_index == index:
                continue
            if abs(other["radius_mm"] - item["radius_mm"]) > 1e-6 + (
                1e-3 * item["radius_mm"]
            ):
                continue
            delta = abs((other["theta_deg"] - target + 180.0) % 360.0 - 180.0)
            if delta > 0.2:
                continue
            gap = _relative_difference(
                float(row.get("area_mm2") or 0.0),
                float(rows[other_index].get("area_mm2") or 0.0),
            )
            if gap > clause.area_rel_tol:
                rejected.append({
                    "candidate": other_index,
                    "clause": "area_rel_tol",
                    "relative_difference": round(gap, 6),
                })
                continue
            dot = _dot(item["face_normal"], other["face_normal"])
            if not _normal_sign_satisfied(clause.normal_sign, dot):
                rejected.append({
                    "candidate": other_index,
                    "clause": "normal_sign",
                    "normal_dot": round(dot, 6),
                })
                continue
            partner = other_index
            break
        if partner is None:
            unmatched.append(index)
            if rejected:
                detail.append({"index": index, "rejected": rejected[:4]})
        else:
            pairs.append({"index": index, "partner": partner})

    return {
        "declared": True,
        "kind": clause.kind,
        "ref": clause.ref,
        "normal_sign": clause.normal_sign,
        "area_rel_tol": clause.area_rel_tol,
        "paired_count": len(pairs),
        "unmatched_indices": unmatched,
        "unmatched_detail": detail,
        "unmatched_fraction": (
            round(len(unmatched) / len(rows), 6) if rows else 0.0
        ),
    }


def check_selection(
    criterion: Criterion,
    rows: list[dict],
    axis_origin: Vec3,
    axis_direction: Vec3,
    mirror_azimuth_deg: float | None = None,
) -> dict:
    """The whole criterion against the whole submitted set.

    Returns the per-face clause residuals, the count clause, and the symmetry
    residual. `satisfied` summarises them, but the residuals are the substance:
    a set that fails one clause by a hair and a set that fails it completely
    are different outcomes, and a boolean cannot say which happened.

    `mirror_azimuth_deg` is the azimuth of the plane a `mirror_plane` clause
    reflects about. It is a fact about the model rather than about the clause,
    so it is passed in; a mirror clause without one is reported unmeasurable
    rather than quietly evaluated as something else.
    """
    measured = [
        cylindrical(
            Vec3(x=row["centroid_mm"][0], y=row["centroid_mm"][1],
                 z=row["centroid_mm"][2]),
            Vec3(x=row["normal_xyz"][0], y=row["normal_xyz"][1],
                 z=row["normal_xyz"][2]),
            axis_origin,
            axis_direction,
        )
        if row.get("centroid_mm") and row.get("normal_xyz")
        else {"radius_mm": 0.0, "theta_deg": 0.0, "radial": 0.0,
              "axial": 0.0, "tangential": 0.0, "frame_axis": 0.0,
              "face_normal": [0.0, 0.0, 0.0]}
        for row in rows
    ]

    per_face = [clause_residuals(criterion, item) for item in measured]
    failed = [
        index for index, residuals in enumerate(per_face)
        if any(r.get("within") is False for r in residuals)
    ]

    types = {str(row.get("surface_type", "")) for row in rows}
    type_ok = (
        not criterion.surface_types
        or types <= set(criterion.surface_types)
    )

    count = criterion.count
    count_result: dict[str, object] = {"declared": count is not None}
    if count is not None:
        count_result.update({
            "count": len(rows),
            "min_count": count.min_count,
            "max_count": count.max_count,
            "even": count.even,
            "satisfied": (
                len(rows) >= count.min_count
                and (count.max_count is None or len(rows) <= count.max_count)
                and (count.even is None or (len(rows) % 2 == 0) == count.even)
            ),
        })

    symmetry = symmetry_residuals(
        criterion, rows, measured, mirror_azimuth_deg
    )

    return {
        "intent": criterion.intent,
        "face_count": len(rows),
        "surface_types_seen": sorted(t for t in types if t),
        "surface_types_within_declared": type_ok,
        "per_face": per_face,
        "faces_failing_a_normal_clause": failed,
        "count_clause": count_result,
        "symmetry": symmetry,
        "satisfied": (
            not failed
            and type_ok
            and count_result.get("satisfied", True)
            and not symmetry.get("unmatched_indices")
        ),
    }
