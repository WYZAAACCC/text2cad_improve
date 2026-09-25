"""Radial geometry facts a meshing agent needs in order to size a mesh.

The agent must size the mesh from the part it was actually handed, not from a
per-family template. This module gives it exactly the facts an engineer would
gather before choosing element sizes:

  * surface area per radial band - where there is surface there are fillets,
    corners and load-transfer faces, i.e. places a coarse element cannot
    represent. This is the primary signal for where refinement earns its keep;
  * face inventory - how many faces, how small the smallest face is, and how
    much of the surface is non-planar (curved faces are the ones carrying
    fillets and bores);
  * overall extents and volume - for scale and for a mesh-budget estimate.

Everything comes from OCC mass properties of the imported STEP. No volume mesh
is generated, so the agent can query this freely before it commits to a
refinement proposal.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


def _inspect(
    step_path: Path,
    surface_size_mm: float,
    axis_origin_mm: list[float] | None = None,
    axis_direction_mm: list[float] | None = None,
):
    """Boundary triangulation plus kernel mass properties.

    Triangulating the boundary is far cheaper than a volume mesh, and binning
    triangles (not whole faces) by radius is what makes the profile meaningful:
    on a disc the two large side faces have centroids near the axis, so a
    per-face bin would put almost all the surface area in the innermost band.
    """
    import gmsh

    normalisation = None
    if axis_origin_mm is not None and axis_direction_mm is not None:
        from seekflow_structural.tools.frames import Normalisation

        normalisation = Normalisation(axis_origin_mm, axis_direction_mm)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("profile")
        imported = gmsh.model.occ.importShapes(str(step_path))
        volumes = [tag for dim, tag in imported if dim == 3]
        if not volumes:
            raise ValueError(f"{step_path} contains no solid")
        gmsh.model.occ.synchronize()
        volume = float(gmsh.model.occ.getMass(3, volumes[0]))

        gmsh.option.setNumber("Mesh.MeshSizeMax", surface_size_mm)
        gmsh.option.setNumber("Mesh.MeshSizeMin", surface_size_mm * 0.2)
        gmsh.model.mesh.generate(2)

        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        points = {
            int(node_tags[i]): (
                coords[3 * i],
                coords[3 * i + 1],
                coords[3 * i + 2],
            )
            for i in range(len(node_tags))
        }
        if normalisation is not None:
            points = {
                tag: normalisation.point(*point)
                for tag, point in points.items()
            }
        _, _, conn = gmsh.model.mesh.getElements(2, -1)
        triangles = [
            (int(conn[0][3 * i]), int(conn[0][3 * i + 1]), int(conn[0][3 * i + 2]))
            for i in range(len(conn[0]) // 3)
        ]
        # Exact face centroids and areas. The tessellation is too coarse to
        # decide rotational symmetry by binning triangles; matching real faces
        # under a candidate rotation is a combinatorial test that noise in the
        # tessellation cannot break.
        faces = []
        for dim, tag in gmsh.model.getEntities(2):
            if dim != 2:
                continue
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
            if normalisation is not None:
                cx, cy, cz = normalisation.point(cx, cy, cz)
            # Shortest topological edge of the face, from the kernel - not from
            # the tessellation, whose edge lengths only reflect how finely the
            # boundary happened to be triangulated. A short edge means the
            # geometry itself has a small feature there.
            shortest = None
            full_revolution = False
            for bdim, btag in gmsh.model.getBoundary([(2, tag)], combined=False):
                if bdim != 1:
                    continue
                length = float(gmsh.model.occ.getMass(1, abs(btag)))
                if shortest is None or length < shortest:
                    shortest = length
                # A boundary edge that is a full circle about the z axis means
                # the face is a surface of revolution - an annulus, a bore, a
                # fillet torus - and is therefore invariant under every
                # rotation about that axis. Detected from the edge's bounding
                # box: centred on the axis, and as wide as it is deep.
                bx0, by0, bz0, bx1, by1, bz1 = gmsh.model.getBoundingBox(
                    1, abs(btag)
                )
                if normalisation is not None:
                    corners = [
                        normalisation.point(x, y, z)
                        for x in (bx0, bx1)
                        for y in (by0, by1)
                        for z in (bz0, bz1)
                    ]
                    bx0 = min(point[0] for point in corners)
                    bx1 = max(point[0] for point in corners)
                    by0 = min(point[1] for point in corners)
                    by1 = max(point[1] for point in corners)
                scale = max(abs(bx1), abs(by1), 1e-6)
                if (
                    bx1 > 0
                    and abs(bx0 + bx1) < 1e-4 * scale
                    and abs(by0 + by1) < 1e-4 * scale
                    and abs((bx1 - bx0) - (by1 - by0)) < 1e-4 * scale
                ):
                    full_revolution = True
            faces.append(
                {
                    "r": math.hypot(cx, cy),
                    "theta": math.degrees(math.atan2(cy, cx)) % 360.0,
                    "z": cz,
                    "area": float(gmsh.model.occ.getMass(2, tag)),
                    "shortest_edge_mm": shortest,
                    "full_revolution": full_revolution,
                }
            )
        return volume, points, triangles, faces
    finally:
        gmsh.finalize()


# How far apart two faces may sit in azimuth and still count as the same
# feature. It is also the finest period this probe can resolve: once a period
# is shorter than the tolerance, every face matches one of its neighbours and
# the measurement stops meaning anything. Callers are told when they cross it
# rather than being handed a meaningless number.
ANGULAR_TOL_DEG = 0.2


def _area_fraction_repeating(
    faces, period_deg: float, bins: int = 72
) -> dict:
    """Fraction of surface area that maps onto itself under `period_deg`.

    A face repeats if rotating its centroid by one period lands on a face with
    the same radius, axial position and area. Weighting by area rather than by
    face count is what makes the answer trustworthy: a part whose large smooth
    faces repeat but whose small features do not is not periodic, and a count
    would let thousands of tiny faces outvote the few big ones.

    Binning area by azimuth was tried first and cannot work here. A 60-slot
    rim at a 6-degree period aliases badly against any practical bin width,
    and with thousands of faces most bins hold nothing, so the profile is
    spike noise and every order looks equally wrong.

    The residual is reported as well as its size, because the size alone does
    not say whether the period is right. A correct period leaves a residual
    only where the CAD kernel sewed the model to itself - a seam, one place
    around the circumference - while a wrong period leaves its residual
    scattered across every feature that the rotation failed to line up. Both
    can leave a few percent of the area unmatched, and only where it sits
    tells them apart.
    """
    if not faces:
        return {
            "matched_area_fraction": 0.0,
            "unmatched_face_count": 0,
            "unmatched_area_mm2": 0.0,
            "total_area_mm2": 0.0,
            "residual_bins": bins,
            "residual_bins_holding_90pct": 0,
            "residual_busiest_bin_fraction": 0.0,
        }
    rs = [face["r"] for face in faces]
    zs = [face["z"] for face in faces]
    extent = max(max(rs) - min(rs), max(zs) - min(zs), 1e-6)
    tol_r = max(extent * 1e-4, 1e-5)
    tol_z = max(extent * 1e-4, 1e-5)
    tol_theta = ANGULAR_TOL_DEG
    tol_area = 0.05

    # Bucket by (r, z) so the candidate search stays local rather than O(n^2)
    # over four thousand faces.
    buckets: dict[tuple[int, int], list[dict]] = {}
    for face in faces:
        key = (
            math.floor(face["r"] / tol_r),
            math.floor(face["z"] / tol_z),
        )
        buckets.setdefault(key, []).append(face)

    # A face whose centroid sits on the rotation axis is a surface of
    # revolution - an annulus, a bore, a cone. Spinning it maps it onto itself
    # at every period, so it is invariant by construction and carries no
    # information about what the period is. It also has no defined azimuth,
    # which is why a rotated centroid can never be made to land on it. Counting
    # these as matched is the honest reading; they simply dilute every order
    # equally.
    axis_tol = max(extent * 1e-6, 1e-9)

    matched_area = 0.0
    total_area = 0.0
    unmatched = 0
    unmatched_area = 0.0
    residual = [0.0] * bins
    for face in faces:
        total_area += face["area"]
        if face.get("full_revolution") or face["r"] <= axis_tol:
            matched_area += face["area"]
            continue
        target = (face["theta"] + period_deg) % 360.0
        kr = math.floor(face["r"] / tol_r)
        kz = math.floor(face["z"] / tol_z)
        hit = None
        for dr in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for other in buckets.get((kr + dr, kz + dz), ()):
                    if abs(other["r"] - face["r"]) > tol_r:
                        continue
                    if abs(other["z"] - face["z"]) > tol_z:
                        continue
                    delta = abs(
                        (other["theta"] - target + 180.0) % 360.0 - 180.0
                    )
                    if delta > tol_theta:
                        continue
                    if (
                        face["area"] > 0
                        and abs(other["area"] - face["area"]) / face["area"]
                        > tol_area
                    ):
                        continue
                    hit = other
                    break
                if hit is not None:
                    break
            if hit is not None:
                break
        if hit is not None:
            matched_area += face["area"]
        else:
            unmatched += 1
            unmatched_area += face["area"]
            residual[
                int(face["theta"] / 360.0 * bins) % bins
            ] += face["area"]

    # How concentrated the residual is: of the azimuth bins holding any of it,
    # how many are needed to cover 90% of it. A seam lands in one or two bins
    # however widely the part is subdivided; a period that is simply wrong
    # spreads across every feature the rotation missed.
    ranked = sorted((v for v in residual if v > 0), reverse=True)
    covered = 0.0
    bins_holding_90pct = 0
    for value in ranked:
        covered += value
        bins_holding_90pct += 1
        if covered >= 0.9 * unmatched_area:
            break
    return {
        "matched_area_fraction": (
            matched_area / total_area if total_area else 0.0
        ),
        "unmatched_face_count": unmatched,
        "unmatched_area_mm2": unmatched_area,
        "total_area_mm2": total_area,
        "residual_bins": bins,
        "residual_bins_holding_90pct": bins_holding_90pct,
        "residual_busiest_bin_fraction": (
            ranked[0] / unmatched_area if unmatched_area else 0.0
        ),
    }


def probe_mirror_plane(faces, point, normal) -> float:
    """Fraction of surface area that maps onto itself under a reflection.

    The mirror analogue of the rotation probe: reflect each face's centroid
    through the plane and look for a face at the reflected position with the
    same area. A part that is genuinely symmetric about the plane scores near
    1; one that is not scores well below it.

    Reported as a measurement with a score rather than as a verdict. Whether a
    plane is symmetric enough to halve the model is a judgement about the
    part, and the score is what that judgement is made on.
    """
    if not faces:
        return 0.0

    def to_cartesian(face):
        theta = math.radians(face["theta"])
        return (
            face["r"] * math.cos(theta),
            face["r"] * math.sin(theta),
            face["z"],
        )

    def to_cylindrical(x, y, z):
        return (math.hypot(x, y), math.degrees(math.atan2(y, x)) % 360.0, z)

    nx, ny, nz = _unit(list(normal))
    px, py, pz = point
    rs = [face["r"] for face in faces]
    zs = [face["z"] for face in faces]
    extent = max(max(rs) - min(rs), max(zs) - min(zs), 1e-6)
    tol = max(extent * 1e-4, 1e-5)

    buckets: dict[tuple[int, int], list[dict]] = {}
    for face in faces:
        buckets.setdefault(
            (math.floor(face["r"] / tol), math.floor(face["z"] / tol)), []
        ).append(face)

    matched = 0.0
    total = 0.0
    for face in faces:
        total += face["area"]
        if face.get("full_revolution"):
            matched += face["area"]
            continue
        cx, cy, cz = to_cartesian(face)
        d = (cx - px) * nx + (cy - py) * ny + (cz - pz) * nz
        rx, ry, rz = cx - 2 * d * nx, cy - 2 * d * ny, cz - 2 * d * nz
        target_r, target_theta, target_z = to_cylindrical(rx, ry, rz)

        kr = math.floor(target_r / tol)
        kz = math.floor(target_z / tol)
        hit = False
        for dr in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for other in buckets.get((kr + dr, kz + dz), ()):
                    if abs(other["r"] - target_r) > tol:
                        continue
                    if abs(other["z"] - target_z) > tol:
                        continue
                    delta = abs(
                        (other["theta"] - target_theta + 180.0) % 360.0 - 180.0
                    )
                    if delta > ANGULAR_TOL_DEG:
                        continue
                    if (
                        face["area"] > 0
                        and abs(other["area"] - face["area"]) / face["area"]
                        > 0.05
                    ):
                        continue
                    hit = True
                    break
                if hit:
                    break
            if hit:
                break
        if hit:
            matched += face["area"]
    return matched / total if total else 0.0


def _unit(values):
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm > 0 else [0.0, 0.0, 0.0]


def azimuthal_feature_profile(faces, bins: int = 72) -> list[dict]:
    """Per azimuth bin: surface area, face count, and the shortest edge in it.

    This is where an engineer looks to find out what is around the
    circumference. A bin holding many small faces joined by short edges is a
    slotted, perforated or otherwise detailed region; a bin holding one large
    face with long edges is a smooth web. Nothing here knows what a slot or a
    hole is - it reports the geometry and leaves the reading to the caller.

    It is also how a repeat unit is found by eye: if the profile from bin i
    matches the profile from bin i+k all the way round, the part repeats every
    k bins, and a sector covering k bins is a candidate analysis domain.
    """
    area = [0.0] * bins
    count = [0] * bins
    smallest: list[float | None] = [None] * bins
    for face in faces:
        index = int(face["theta"] / 360.0 * bins) % bins
        area[index] += face["area"]
        count[index] += 1
        edge = face.get("shortest_edge_mm")
        if edge is not None and (smallest[index] is None or edge < smallest[index]):
            smallest[index] = edge
    width = 360.0 / bins
    rows = []
    for i in range(bins):
        edge = smallest[i]
        rows.append(
            {
                "theta_min_deg": round(i * width, 4),
                "theta_max_deg": round((i + 1) * width, 4),
                "surface_area_mm2": round(area[i], 3),
                "face_count": count[i],
                "shortest_edge_mm": round(edge, 5) if edge is not None else None,
            }
        )
    return rows


def dominant_periods(areas: list[float], bin_width_deg: float,
                     max_periods: int = 8) -> list[dict]:
    """Where the azimuthal profile most strongly repeats itself.

    A period hidden in an array of a few hundred numbers is not something a
    reader can be expected to see, and testing candidate periods one at a time
    turns the search into an endless scan. Autocorrelation is the ordinary way
    to find repetition in a signal, and it answers in a single step: a peak at
    lag L says the surface looks like itself again L bins further round.

    This reports where repetition exists; it does not say which of those
    periods is the repeat unit. Several will be real - a part repeating every
    6 degrees also repeats every 12 - and choosing between them is what
    probe_periodicity is for.
    """
    n = len(areas)
    if n < 8:
        return []
    mean = sum(areas) / n
    centred = [value - mean for value in areas]
    energy = sum(value * value for value in centred)
    if energy <= 0:
        return []
    correlations = []
    for lag in range(1, n // 2 + 1):
        total = sum(centred[i] * centred[(i + lag) % n] for i in range(n))
        correlations.append(total / energy)
    peaks = []
    for index, value in enumerate(correlations):
        lag = index + 1
        before = correlations[index - 1] if index > 0 else -2.0
        after = correlations[index + 1] if index + 1 < len(correlations) else -2.0
        if value >= before and value >= after and value > 0:
            period = lag * bin_width_deg
            peaks.append(
                {
                    "period_deg": round(period, 4),
                    "order_at_this_period": (
                        round(360.0 / period, 4) if period > 0 else None
                    ),
                    "autocorrelation": round(value, 5),
                }
            )
    peaks.sort(key=lambda entry: -entry["autocorrelation"])
    return peaks[:max_periods]


def probe_periodicity(faces, orders: list[int]) -> list[dict]:
    """Measure how much of the part's surface maps onto itself under rotation.

    A probe for the agent to test its own hypothesis, not a rule the framework
    enforces. An engineer who suspects a part repeats 20 times around the axis
    checks that before committing to an 18-degree sector; this is that check.
    The agent chooses which orders to test and is free to act on the answer
    however it judges best - nothing gates on the result.

    `matched_area_fraction` near 1 means the surface genuinely repeats at that
    period. A part repeating every 6 degrees also repeats every 12 and every
    30, so any whole multiple of the true period also scores 1. That is the
    trap: on a 20-fold part the orders 20, 10, 5, 4 and 2 all score the same
    0.989, and reading the *smallest* of them gives 180 degrees - a sector
    that tiles the part and analyses a twentieth of it. Validity at a coarse
    period is *implied* by validity at a finer one, so the repeat unit is the
    **largest** order that is a confirmed period, and the only one no finer
    order in the same call explains. Each row reports that relation as
    `explained_by_finer_order`, so the answer is in the reply rather than in
    a rule the reader has to know.

    A fraction short of 1 is not by itself a rejection, which is why the
    residual is reported alongside it. Real CAD leaves a seam where the model
    was closed, and those faces match nothing at any period; a correct period
    therefore scores slightly under 1 with its residual piled into one or two
    azimuth bins. A wrong period scores under 1 too, but scatters its residual
    over every feature the rotation failed to line up, so it fills many bins.
    `residual_bins_holding_90pct` separates the two, and `confirmed_period` is
    that comparison made rather than left to the reader.

    Several orders in one call, because a hypothesis about a repeat unit is
    usually a short list of candidates rather than a single guess.
    """
    results = []
    for order in orders:
        if order < 1:
            results.append({"order": order, "error": "order must be >= 1"})
            continue
        period = 360.0 / order
        if period < ANGULAR_TOL_DEG:
            results.append(
                {
                    "order": order,
                    "period_deg": round(period, 8),
                    "matched_area_fraction": None,
                    "confirmed_period": False,
                    "below_probe_resolution": True,
                    "note": (
                        f"a period of {period:.6g} deg is finer than this "
                        f"probe's {ANGULAR_TOL_DEG} deg azimuthal resolution. "
                        "At this scale neighbouring faces match each other "
                        "whatever the part's real structure is, so any number "
                        "returned here would be an artefact. This is a limit "
                        "of the instrument, not a property of the part."
                    ),
                }
            )
            continue
        repeat = _area_fraction_repeating(faces, period)
        results.append(
            {
                "order": order,
                "period_deg": round(period, 6),
                "matched_area_fraction": round(
                    repeat["matched_area_fraction"], 5
                ),
                "confirmed_period": _is_confirmed_period(repeat),
                "unmatched_face_count": repeat["unmatched_face_count"],
                "unmatched_area_mm2": repeat["unmatched_area_mm2"],
                "residual_bins": repeat["residual_bins"],
                "residual_bins_holding_90pct": repeat[
                    "residual_bins_holding_90pct"
                ],
                "residual_busiest_bin_fraction": round(
                    repeat["residual_busiest_bin_fraction"], 4
                ),
                "face_count": len(faces),
            }
        )
    return _annotate_multiples(results)


# How concentrated a period's residual has to be to count as a real period.
#
# A confirmed period's residual is the seam where the model was closed: a small
# pile in a few azimuth bins. A period the part does not have spreads its
# residual over every feature the rotation failed to line up. Measured on D27,
# the 18-degree period puts 90% of its residual in 5 of 72 bins and the
# 180-degree multiple in 4 - while 30 degrees needs 25 bins and 20 degrees
# needs 63. The threshold sits between the two groups by a factor of two on
# either side, and the share rather than the count is what makes it independent
# of how finely the profile was binned.
SEAM_BIN_SHARE_MAX = 0.15


def _is_confirmed_period(repeat: dict) -> bool:
    bins = repeat.get("residual_bins") or 0
    if not bins:
        return False
    holding = repeat.get("residual_bins_holding_90pct")
    if holding is None:
        return False
    return holding / bins <= SEAM_BIN_SHARE_MAX


def _annotate_multiples(results: list[dict]) -> list[dict]:
    """Say, for each order, whether a finer confirmed order in the same call
    already accounts for it.

    This is the measurement the probe was missing. Five orders scoring 0.989
    look like five candidate repeat units and are not: 10, 5, 4 and 2 are all
    multiples of 20's period, and a part that repeats every 18 degrees
    necessarily repeats every 36, 72, 90 and 180. Reporting the relation is
    what turns the reply into an answer - without it the reader has to know
    the rule, and an agent that did not know it swept the whole divisor space
    of 360 over twelve calls and produced nothing.
    """
    confirmed = [
        row["order"] for row in results
        if row.get("confirmed_period")
        and isinstance(row.get("order"), int)
        and row["order"] > 0
    ]
    for row in results:
        order = row.get("order")
        row["explained_by_finer_order"] = None
        if not isinstance(order, int) or order < 1:
            continue
        finer = [
            other for other in confirmed
            if other > order and other % order == 0
        ]
        if finer:
            row["explained_by_finer_order"] = max(finer)
    return results


def finest_confirmed_order(results: list[dict]) -> dict | None:
    """The one order in a probe's reply that could be the repeat unit.

    The largest confirmed period, and the only one no finer order explains. A
    caller that named a coarse order and a finer one in the same call gets the
    finer one back, which is the whole point of naming several.
    """
    candidates = [
        row for row in results
        if row.get("confirmed_period")
        and row.get("explained_by_finer_order") is None
        and isinstance(row.get("order"), int)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row["order"])


_PRIMES = (
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67,
    71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149,
    151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223, 227, 229,
    233, 239, 241, 251, 257, 263, 269, 271, 277, 281, 283, 293, 307, 311, 313,
    317, 331, 337, 347, 349, 353, 359,
)


def finer_candidate_orders(order: int) -> list[int]:
    """The only orders that could be a finer repeat unit than `order`.

    A surface repeating at period P also repeats at 2P, 3P, ... so if period
    360/order is valid, the true repeat unit is 360/(order*m) for some whole
    m. A finer unit means m >= 2, and then order*q is valid for any prime q
    dividing m, because 360/(order*q) is a whole multiple of 360/(order*m).

    So `order` is the repeat unit exactly when none of order*q - q prime,
    order*q <= 360 - is a valid period. That is what makes "is this the finest
    period?" answerable: it is seven measurements on a 20-fold part, not the
    three hundred and forty orders between 20 and 360. Without it the question
    has no end, and an agent asked to settle it can only sweep until its budget
    runs out.
    """
    if order < 1:
        return []
    return [
        order * prime
        for prime in _PRIMES
        if order * prime <= 360 and 360.0 / (order * prime) >= ANGULAR_TOL_DEG
    ]


def test_finer_periods(faces, order: int) -> dict:
    """Probe every order that could be a finer repeat unit than `order`.

    Reports them next to `order` itself, so the comparison is direct: a valid
    finer unit scores at least as well as the candidate, and one that scores
    below it is not the unit. Nothing here decides; it reports the measurements
    that make the decision a comparison rather than a search.
    """
    candidates = finer_candidate_orders(order)
    if not candidates:
        return {
            "candidate_order": order,
            "finer_orders": [],
            "note": (
                f"order {order} admits no finer order within 360; nothing to "
                "test"
            ),
        }
    probed = probe_periodicity(faces, [order] + candidates)
    return {
        "candidate_order": order,
        "candidate_period_deg": round(360.0 / order, 6),
        "finer_orders": candidates,
        "logic": (
            "a period finer than the candidate must have the form "
            "360/(order*q) for prime q; a valid one scores at least as well as "
            "the candidate does, so if every row below the first scores lower, "
            "the candidate is the repeat unit"
        ),
        "measurements": probed,
    }


def _triangle_area(a, b, c) -> float:
    ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def _triangle_surface_cells(
    points: dict,
    triangles: list[tuple[int, int, int]],
    *,
    radial_step_mm: float = 2.0,
    axial_step_mm: float = 2.0,
    angular_step_deg: float = 10.0,
) -> list[dict]:
    """Aggregate the boundary tessellation into local surface cells.

    Whole-face centroids are the wrong coordinate for a cylindrical bore or a
    full-revolution face: their centroid lies on the axis even though the
    surface is tens of millimetres away from it. The triangulation carries the
    actual radial position, so the pre-solve design-effect check uses these
    cells rather than the face-centroid list.
    """
    if not triangles:
        return []
    radii = {tag: math.hypot(point[0], point[1]) for tag, point in points.items()}
    z_values = [point[2] for point in points.values()]
    r_min = min(radii.values())
    z_min = min(z_values)
    r_step = max(float(radial_step_mm), 1e-9)
    z_step = max(float(axial_step_mm), 1e-9)
    a_step = max(float(angular_step_deg), 1e-9)
    cells: dict[tuple[int, int, int], dict] = {}
    for tri in triangles:
        a, b, c = points[tri[0]], points[tri[1]], points[tri[2]]
        area = _triangle_area(a, b, c)
        x = (a[0] + b[0] + c[0]) / 3.0
        y = (a[1] + b[1] + c[1]) / 3.0
        z = (a[2] + b[2] + c[2]) / 3.0
        radius = math.hypot(x, y)
        theta = math.degrees(math.atan2(y, x)) % 360.0
        key = (
            int(math.floor((radius - r_min) / r_step)),
            int(math.floor((z - z_min) / z_step)),
            int(math.floor(theta / a_step)) % int(round(360.0 / a_step)),
        )
        row = cells.setdefault(key, {
            "key": list(key),
            "face_count": 0,
            "area_mm2": 0.0,
            "r_mm": 0.0,
            "z_mm": 0.0,
            "theta_deg": 0.0,
        })
        row["face_count"] += 1
        row["area_mm2"] += area
        row["r_mm"] += radius * max(area, 1e-12)
        row["z_mm"] += z * max(area, 1e-12)
        row["theta_deg"] += theta * max(area, 1e-12)
    out = []
    for row in cells.values():
        weight = max(row["area_mm2"], 1e-12)
        row["r_mm"] = round(row["r_mm"] / weight, 6)
        row["z_mm"] = round(row["z_mm"] / weight, 6)
        row["theta_deg"] = round(row["theta_deg"] / weight, 6)
        row["area_mm2"] = round(row["area_mm2"], 6)
        out.append(row)
    return sorted(out, key=lambda row: tuple(row["key"]))


def build_profile(
    step_path: Path,
    band_count: int = 12,
    surface_size_mm: float = 8.0,
    axis_origin_mm: list[float] | None = None,
    axis_direction_mm: list[float] | None = None,
) -> dict:
    volume, points, triangles, faces = _inspect(
        step_path,
        surface_size_mm,
        axis_origin_mm=axis_origin_mm,
        axis_direction_mm=axis_direction_mm,
    )
    if not triangles:
        raise ValueError("model has no surface triangles")

    radii = {tag: math.hypot(p[0], p[1]) for tag, p in points.items()}
    r_min, r_max = min(radii.values()), max(radii.values())
    width = (r_max - r_min) / band_count if band_count else 0.0

    areas = [0.0] * band_count
    smallest_edge = [float("inf")] * band_count
    total_area = 0.0
    for tri in triangles:
        a, b, c = points[tri[0]], points[tri[1]], points[tri[2]]
        area = _triangle_area(a, b, c)
        total_area += area
        centroid_r = (radii[tri[0]] + radii[tri[1]] + radii[tri[2]]) / 3.0
        index = int((centroid_r - r_min) / width) if width else 0
        index = min(max(index, 0), band_count - 1)
        areas[index] += area
        smallest_edge[index] = min(
            smallest_edge[index],
            math.dist(a, b),
            math.dist(b, c),
            math.dist(c, a),
        )

    # Characteristic wall thickness: for a plate of thickness t the surface
    # area is 2A and the volume At, so t = 2V/S. Used only to turn a proposed
    # element size into an order-of-magnitude element count; the harness
    # measures the real count after meshing.
    thickness = 2.0 * volume / total_area if total_area else 0.0

    bands = []
    for index in range(band_count):
        lo = r_min + width * index
        hi = r_min + width * (index + 1)
        band_area = areas[index]
        # material sits on one side of each surface element
        band_volume = band_area * thickness / 2.0
        bands.append(
            {
                "radius_min_mm": round(lo, 3),
                "radius_max_mm": round(hi, 3),
                "surface_area_mm2": round(band_area, 2),
                "estimated_volume_mm3": round(band_volume, 1),
                "finest_surface_edge_mm": (
                    round(smallest_edge[index], 4)
                    if smallest_edge[index] != float("inf")
                    else None
                ),
            }
        )

    # Raw azimuthal evidence, in 5-degree bins so an agent can read it. What
    # rotational structure exists, and therefore what sector is a legal
    # analysis domain, is a judgement the agent makes from this; probe_periodicity
    # is the tool it uses to test that judgement.
    return {
        "step_file": str(step_path),
        "frame_axis_origin_mm": axis_origin_mm,
        "frame_axis_direction_mm": axis_direction_mm,
        "azimuthal_profile_5deg": azimuthal_feature_profile(faces, 72),
        "r_min_mm": round(r_min, 3),
        "r_max_mm": round(r_max, 3),
        # The axial extent, from the same surface sampling as the radii. The
        # frame stage needs it to describe the part, and taking it from a
        # config value instead is how D27's rim came to be truncated by four
        # millimetres without a word.
        # The per-face facts, so a caller that needs to reason about
        # individual faces - the symmetry candidates, for instance - does not
        # have to open the STEP a second time. Binned profiles cannot serve
        # this: a bin has an area and a count, not a position.
        "faces": [
            {
                "r": round(face["r"], 6),
                "theta": round(face["theta"], 6),
                "z": round(face["z"], 6),
                "area": round(face["area"], 6),
                "full_revolution": bool(face.get("full_revolution")),
            }
            for face in faces
        ],
        "z_min_mm": round(min(p[2] for p in points.values()), 3),
        "z_max_mm": round(max(p[2] for p in points.values()), 3),
        "face_count": len(faces),
        "total_volume_mm3": round(volume, 2),
        "total_surface_area_mm2": round(total_area, 2),
        "triangle_count": len(triangles),
        "characteristic_thickness_mm": round(thickness, 3),
        "band_count": band_count,
        "bands": bands,
        "triangle_cells": _triangle_surface_cells(points, triangles),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("step", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bands", type=int, default=12)
    args = parser.parse_args()

    profile = build_profile(args.step.resolve(), args.bands)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in profile.items() if k not in ("bands", "largest_faces")},
            indent=2,
        )
    )
