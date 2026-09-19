"""Measuring the solved field, so that a finding can rest on a number.

Everything downstream of the solve reads two files: `structural_metrics.json`,
which holds eight scalars, and `structural_report.md`, which holds the same
eight in prose. Between them they describe a 257,401 node field by its single
largest value and four radial bands - and on D27 those bands are fifty
millimetres wide, against a fir-tree fillet of two. A concentration cannot be
located at that resolution, and a design change cannot be aimed by a number
that does not say where it came from.

The field itself is already on disk and is far richer than what is read from
it. `nodal_stress_3d.csv` carries, per node, the position, the displacement,
and the three cylindrical stress components the deck asked ANSYS for - and
`postprocess_structural.py` parses all of them into each row before keeping
only `s_eqv`. On D27 the hoop component reaches 1443 MPa where the radial
reaches 1.5, and which of the two is carrying the peak is the difference
between a rim problem and a bore problem. That distinction was being computed
and then discarded.

So this module reads the field once and answers questions about it. The rules
it obeys are the ones the rest of the package obeys:

  - Nothing here decides what is acceptable. There is no threshold a stress is
    compared against, because what counts as adequate is an engineering
    decision about a specific component. Where a fraction appears - "the part
    of the peak that counts as one concentration" - it is the caller's, and it
    is echoed back in the answer.
  - A quantity that could not be measured says so. Every function returns a
    `limits` list, and an empty answer with no limit recorded would be a lie
    of omission.
  - `sel` is not used, because it does not mean anything. The deck writes the
    ANSYS `NSEL` mask into that column (`*VGET,MSK(1),NODE,1,NSEL`) at a point
    where nothing has narrowed the selection, and measured on `d27-correct24`
    it is 1 on all 257,401 rows. Which nodes carry the load is read from
    `selected_face_nodes.json`, which is a join against the CAD faces and not
    a flag the solver set.

The one thing this module does not do is say what a concentration *is* - a
notch, a section that is too thin, a load that entered wrongly. It measures;
the agent attributes.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# The three cylindrical components the deck writes, in the order it writes
# them. `s_eqv` is the von Mises equivalent and is not a component.
COMPONENTS = ("s_radial", "s_hoop", "s_axial")

# Every quantity a caller may ask a profile about. Named rather than taken
# from the row, so a caller cannot ask for a profile of a column that does not
# exist and receive a plausible-looking empty curve.
QUANTITIES = COMPONENTS + ("s_eqv", "safety_factor", "temperature_c", "u_sum")

# The axes a field can be profiled along. `r` and `z` are metric; `theta` is
# degrees about the case's axis and is reported in the sector's own frame -
# the deck writes CSYS,1 so the angle is the one the model was built in.
AXES = ("r", "z", "theta")

# The `Node` field each axis reads. Two of the three are spelled the same as
# the axis and the third is not, which is how `theta` came to be advertised
# and unreadable at once: the tool listed it in `axes`, the agent asked for it,
# and `getattr(node, "theta")` raised. The cost was a real measurement - the
# angular extent of a stress concentration - silently missing from a run whose
# findings were filed anyway, with the failure recorded only as a limit in
# prose.
AXIS_FIELDS = {"r": "r", "z": "z", "theta": "theta_deg"}


@dataclass(frozen=True, slots=True)
class Node:
    """One result node, with the cylindrical frame derived once at load.

    `stressed` is not a judgement about the node; it records whether ANSYS
    stored a stress result there. SOLID187 keeps results at corner nodes only,
    so on D27 41,284 of 257,401 nodes carry a stress and the rest carry zeros
    that would otherwise read as "no stress here" - the same zero a genuinely
    unloaded node has. Every stress measurement filters on it, and the count
    that was filtered out is reported rather than dropped.
    """

    nid: int
    x: float
    y: float
    z: float
    r: float
    theta_deg: float
    ux: float
    uy: float
    uz: float
    u_sum: float
    s_radial: float
    s_hoop: float
    s_axial: float
    s_eqv: float
    stressed: bool
    # Filled at load when the post-processor's node table and a material curve
    # are both available. None is a real state - it means this run cannot
    # answer a question about margin, not that the margin is zero.
    temperature_c: float | None = None
    yield_mpa: float | None = None
    safety_factor: float | None = None

    def distance_to(self, other: "Node") -> float:
        """Metric distance in the model frame.

        Measured in x, y, z rather than in (r, theta, z). A sector is a wedge
        and two nodes at the same radius and axial station but at opposite
        edges of it are far apart; treating the angle as a metric coordinate
        would call them neighbours. Only `r` and `z` are used for profiling,
        where the angle has already been fixed by the filter.
        """
        return math.dist((self.x, self.y, self.z),
                         (other.x, other.y, other.z))


@dataclass
class ResultField:
    """The solved field, loaded once and queried many times."""

    nodes: list[Node]
    source: str = ""
    limits: list[str] = field(default_factory=list)
    # Set by `with_temperature` when the post-processor's per-node table is
    # available. Absent means the safety factor cannot be asked for, and the
    # measurement says so rather than reporting a zero.
    has_safety_factor: bool = False
    has_temperature: bool = False

    # --- loading ---------------------------------------------------------

    @classmethod
    def load(
        cls,
        solve_dir: Path,
        material_points: list[tuple[float, float]] | None = None,
    ) -> "ResultField":
        """Read `nodal_stress_3d.csv` into memory.

        The whole file, not a sample. Every measurement below is a reduction
        over all of it - a peak that is the maximum of a sample is not the
        peak - and a 36 MB CSV is a few seconds once per run.

        `material_points` is the yield curve as `(temperature_c, yield_mpa)`
        pairs. Given it, and the deck's own `node_temperature.csv`, each node
        also gets a temperature and a safety factor. The temperature is the
        deck's, not a re-evaluation of the field: the post-processor computes
        the reported safety factor against the table the solver actually ran
        with, and a second evaluation would make this module disagree with the
        report about the same node for a reason that has nothing to do with
        the part.
        """
        path = Path(solve_dir) / "nodal_stress_3d.csv"
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} does not exist; there is no solved field to measure"
            )

        temperatures: dict[int, float] = {}
        temperature_path = Path(solve_dir) / "node_temperature.csv"
        if temperature_path.is_file():
            with temperature_path.open(
                newline="", encoding="utf-8", errors="replace"
            ) as stream:
                for row in csv.DictReader(stream):
                    try:
                        temperatures[int(float(row["nid"]))] = float(
                            row["temperature_c"]
                        )
                    except (KeyError, TypeError, ValueError):
                        continue

        curve = sorted(material_points or [])
        nodes: list[Node] = []
        skipped = 0
        with path.open(newline="", encoding="utf-8", errors="replace") as stream:
            for row in csv.DictReader(stream):
                try:
                    x = float(row["x"])
                    y = float(row["y"])
                    z = float(row["z"])
                    s_eqv = float(row["s_eqv"])
                    nid = int(float(row["nid"]))
                    temperature = temperatures.get(nid)
                    yield_mpa = (
                        _interpolate_yield(temperature, curve)
                        if temperature is not None and curve else None
                    )
                    parsed = Node(
                        nid=nid,
                        x=x, y=y, z=z,
                        r=math.hypot(x, y),
                        theta_deg=math.degrees(math.atan2(y, x)),
                        ux=float(row["ux"]),
                        uy=float(row["uy"]),
                        uz=float(row["uz"]),
                        u_sum=math.sqrt(
                            float(row["ux"]) ** 2
                            + float(row["uy"]) ** 2
                            + float(row["uz"]) ** 2
                        ),
                        s_radial=float(row["s_radial"]),
                        s_hoop=float(row["s_hoop"]),
                        s_axial=float(row["s_axial"]),
                        s_eqv=s_eqv,
                        stressed=s_eqv != 0.0,
                        temperature_c=temperature,
                        yield_mpa=yield_mpa,
                        safety_factor=(
                            yield_mpa / s_eqv
                            if yield_mpa is not None and s_eqv > 1e-12
                            else None
                        ),
                    )
                except (KeyError, TypeError, ValueError):
                    skipped += 1
                    continue
                nodes.append(parsed)

        if not nodes:
            raise ValueError(f"{path} contains no readable nodes")

        limits: list[str] = []
        if skipped:
            limits.append(
                f"{skipped} row(s) of {path.name} could not be parsed and were "
                "left out; every measurement below is over the rows that were"
            )
        stressed = sum(1 for node in nodes if node.stressed)
        if stressed < len(nodes):
            limits.append(
                f"{len(nodes) - stressed} of {len(nodes)} nodes carry no stress "
                "result - SOLID187 stores results at corner nodes only, so "
                "mid-side stress is not retrievable from the result file. "
                "Stress measurements are over the "
                f"{stressed} nodes that have one"
            )
        has_sf = any(node.safety_factor is not None for node in nodes)
        if not has_sf:
            if not temperature_path.is_file():
                limits.append(
                    "node_temperature.csv is not present, so no node has a "
                    "temperature and the safety factor cannot be measured; "
                    "only stress and displacement can be asked about"
                )
            elif not curve:
                limits.append(
                    "no material yield curve was supplied, so the safety "
                    "factor cannot be computed even though node temperatures "
                    "are available"
                )
        return ResultField(
            nodes=nodes,
            source=str(path),
            limits=limits,
            has_temperature=bool(temperatures),
            has_safety_factor=has_sf,
        )

    # --- views -----------------------------------------------------------

    def stressed(self) -> list[Node]:
        return [node for node in self.nodes if node.stressed]

    def where(
        self,
        *,
        r_min: float | None = None,
        r_max: float | None = None,
        z_min: float | None = None,
        z_max: float | None = None,
        theta_min: float | None = None,
        theta_max: float | None = None,
        node_ids: set[int] | None = None,
        stressed_only: bool = True,
    ) -> list[Node]:
        """The nodes inside every bound that was stated.

        A bound left as None does not filter - it does not mean zero. That
        distinction is the one the face-finding agent needed and did not get
        from an earlier filter vocabulary, where an unset bound defaulted to a
        number and silently excluded everything.
        """
        out = []
        for node in self.nodes:
            if stressed_only and not node.stressed:
                continue
            if node_ids is not None and node.nid not in node_ids:
                continue
            if r_min is not None and node.r < r_min:
                continue
            if r_max is not None and node.r > r_max:
                continue
            if z_min is not None and node.z < z_min:
                continue
            if z_max is not None and node.z > z_max:
                continue
            if theta_min is not None and node.theta_deg < theta_min:
                continue
            if theta_max is not None and node.theta_deg > theta_max:
                continue
            out.append(node)
        return out

    def extreme(
        self, quantity: str = "s_eqv", *, largest: bool = True, **bounds
    ) -> Node | None:
        """The node holding the largest or smallest value of one quantity.

        The direction is stated rather than assumed, because it is a property
        of the quantity and not of the search. The largest von Mises stress is
        the one to worry about; the largest safety factor is the one to
        ignore, and taking it returns a node that is the least interesting in
        the field. `peak` is the largest case, which is right for stress and
        displacement and wrong for margin - so margin asks for `largest=False`
        instead of being handed a peak and quietly misreading it.
        """
        nodes = [
            node for node in self.where(**bounds)
            if getattr(node, quantity) is not None
        ]
        if not nodes:
            return None
        return (max if largest else min)(
            nodes, key=lambda node: getattr(node, quantity)
        )

    def peak(self, quantity: str = "s_eqv", **bounds) -> Node | None:
        """The largest value of one quantity. Use `extreme` for a minimum."""
        return self.extreme(quantity, largest=True, **bounds)

    def worst_margin(self, **bounds) -> Node | None:
        """The smallest safety factor, which is what a margin is read by."""
        return self.extreme("safety_factor", largest=False, **bounds)


# --- measurement ---------------------------------------------------------


def _interpolate_yield(
    temperature_c: float, curve: list[tuple[float, float]]
) -> float:
    """Yield strength at a temperature, from a curve that is not extrapolated.

    Clamped at both ends rather than extrapolated, which is what the
    post-processor does and therefore what keeps the two agreeing. A curve
    evaluated past its last point by extending the last segment would report a
    yield strength for a temperature nobody measured.
    """
    if temperature_c <= curve[0][0]:
        return curve[0][1]
    if temperature_c >= curve[-1][0]:
        return curve[-1][1]
    for index in range(len(curve) - 1):
        low_t, low_y = curve[index]
        high_t, high_y = curve[index + 1]
        if low_t <= temperature_c <= high_t:
            fraction = (temperature_c - low_t) / (high_t - low_t)
            return low_y + fraction * (high_y - low_y)
    return curve[-1][1]


def profile(
    nodes: list[Node],
    quantity: str = "s_eqv",
    axis: str = "r",
    bins: int = 20,
) -> dict:
    """One quantity, binned along one axis.

    This is the measurement that says where the load is carried. A single
    maximum says a peak exists; the shape of the curve through it says whether
    the material around it is sharing the load or whether the peak is alone -
    and those call for different design changes.

    Each band reports the maximum, the mean and the count, because the three
    disagree in a way that matters. A band whose maximum is high and whose
    mean is low holds a concentration; a band where both are high holds a
    section that is uniformly too thin.
    """
    if quantity not in QUANTITIES:
        raise ValueError(
            f"{quantity!r} is not a measurable quantity; the field carries "
            + ", ".join(QUANTITIES)
        )
    if axis not in AXES:
        raise ValueError(
            f"{axis!r} is not an axis of this field; profile along "
            + ", ".join(AXES)
        )
    field = AXIS_FIELDS[axis]
    if not nodes:
        return {
            "axis": axis, "quantity": quantity, "bands": [],
            "limits": ["the filter matched no nodes, so no profile exists"],
        }
    if bins < 1:
        raise ValueError("bins must be at least 1")

    limits: list[str] = []
    # A quantity that is None on some nodes is reported rather than dropped
    # silently: a margin profile over a third of the mesh is a different
    # measurement from one over all of it, and the reader has to know which.
    unmeasured = [node for node in nodes if getattr(node, quantity) is None]
    if unmeasured:
        nodes = [node for node in nodes if getattr(node, quantity) is not None]
        limits.append(
            f"{len(unmeasured)} of the filtered nodes have no {quantity} - "
            "the temperature table or the material curve needed to derive it "
            "is not present for them - so this profile is over the "
            f"{len(nodes)} that do"
        )
        if not nodes:
            return {
                "axis": axis, "quantity": quantity, "bands": [],
                "limits": limits,
            }

    values = [getattr(node, field) for node in nodes]
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return {
            "axis": axis, "quantity": quantity,
            "bands": [{
                "low": low, "high": high, "count": len(nodes),
                "max": max(getattr(node, quantity) for node in nodes),
                "mean": sum(getattr(node, quantity) for node in nodes) / len(nodes),
                "at_node": max(nodes, key=lambda n: getattr(n, quantity)).nid,
                "at_r_mm": max(nodes, key=lambda n: getattr(n, quantity)).r,
                "at_z_mm": max(nodes, key=lambda n: getattr(n, quantity)).z,
            }],
            "limits": [
                f"every node in this filter sits at the same {axis}, so there "
                "is nothing to resolve along it"
            ],
        }

    width = (high - low) / bins
    bands = []
    for index in range(bins):
        band_low = low + width * index
        band_high = low + width * (index + 1)
        last = index == bins - 1
        members = [
            node for node in nodes
            if (band_low <= getattr(node, field) < band_high)
            or (last and math.isclose(getattr(node, field), band_high))
        ]
        if not members:
            bands.append({
                "low": round(band_low, 4), "high": round(band_high, 4),
                "count": 0, "max": None, "mean": None,
                "at_node": None, "at_r_mm": None, "at_z_mm": None,
            })
            continue
        top = max(members, key=lambda node: getattr(node, quantity))
        bands.append({
            "low": round(band_low, 4),
            "high": round(band_high, 4),
            "count": len(members),
            "max": round(getattr(top, quantity), 6),
            "mean": round(
                sum(getattr(node, quantity) for node in members) / len(members),
                6,
            ),
            "at_node": top.nid,
            "at_r_mm": round(top.r, 4),
            "at_z_mm": round(top.z, 4),
        })
    return {"axis": axis, "quantity": quantity, "bands": bands, "limits": limits}


def _cells(nodes: list[Node], cell_mm: float) -> dict[tuple[int, int, int], list[Node]]:
    out: dict[tuple[int, int, int], list[Node]] = {}
    for node in nodes:
        key = (
            int(math.floor(node.x / cell_mm)),
            int(math.floor(node.y / cell_mm)),
            int(math.floor(node.z / cell_mm)),
        )
        out.setdefault(key, []).append(node)
    return out


def _components(
    occupied: dict, start: tuple[int, int, int]
) -> list[tuple[int, int, int]]:
    """The 26-neighbour connected component of one occupied cell.

    Grid connectivity rather than a distance sweep, because a cluster is
    defined by being connected and not by fitting inside a radius: a long thin
    concentration along a slot flank is one finding, and a ball grown from its
    peak would cut it in half.
    """
    seen = {start}
    stack = [start]
    while stack:
        cx, cy, cz = stack.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if dx == dy == dz == 0:
                        continue
                    key = (cx + dx, cy + dy, cz + dz)
                    if key in occupied and key not in seen:
                        seen.add(key)
                        stack.append(key)
    return list(seen)


def concentrations(
    nodes: list[Node],
    relative_threshold: float = 0.9,
    cell_mm: float | None = None,
) -> dict:
    """The regions where the stress is close to its own maximum.

    A peak is a node; a concentration is a place. The difference matters to
    whatever is going to change the design, because a node cannot be edited
    and a region can - and because a single high node at the bottom of a
    fillet and a broad band of high stress around a rim are the same number
    and different problems.

    `relative_threshold` is the caller's, not this module's: a fraction of the
    peak, above which nodes are counted as part of a concentration. It is
    echoed back so a reader knows what was asked for.

    `cell_mm` defaults to a length derived from the field's own density, so
    the clustering does not depend on a number chosen for one part. It is
    reported either way.
    """
    if not nodes:
        return {
            "relative_threshold": relative_threshold,
            "concentrations": [],
            "limits": ["the filter matched no nodes"],
        }
    limits: list[str] = []
    if not 0.0 < relative_threshold <= 1.0:
        raise ValueError("relative_threshold must be in (0, 1]")

    peak = max(node.s_eqv for node in nodes)
    if peak <= 0:
        return {
            "relative_threshold": relative_threshold,
            "concentrations": [],
            "limits": ["every node in this filter has zero stress"],
        }
    cutoff = peak * relative_threshold
    hot = [node for node in nodes if node.s_eqv >= cutoff]
    if not hot:
        return {
            "relative_threshold": relative_threshold,
            "concentrations": [],
            "limits": ["no node reaches the stated fraction of the peak"],
        }

    cell: float
    if cell_mm is None or cell_mm <= 0:
        span = [
            max(node.x for node in nodes) - min(node.x for node in nodes),
            max(node.y for node in nodes) - min(node.y for node in nodes),
            max(node.z for node in nodes) - min(node.z for node in nodes),
        ]
        volume = max(span[0] * span[1] * span[2], 1e-9)
        # Three cells across the mean spacing, so a cluster joins across the
        # gaps between neighbouring nodes and does not join across the gap
        # between two genuinely separate concentrations.
        cell = max(3.0 * (volume / len(nodes)) ** (1.0 / 3.0), 1e-6)
        limits.append(
            f"cell_mm was derived from the field's own node density "
            f"({len(nodes)} nodes over the filter's bounding box) rather than "
            "stated; pass cell_mm to cluster at a length of your choosing"
        )
    else:
        cell = cell_mm

    occupied = _cells(hot, cell)
    remaining = set(occupied)
    found = []
    while remaining:
        start = next(iter(remaining))
        members_cells = _components(occupied, start)
        remaining.difference_update(members_cells)
        members = [
            node for key in members_cells for node in occupied[key]
        ]
        top = max(members, key=lambda node: node.s_eqv)
        radii = [node.r for node in members]
        zs = [node.z for node in members]
        # The extent is the largest distance between any two members, which is
        # what says whether this is a spot or a band. Computed as the diameter
        # of the members' bounding box rather than the true pairwise diameter:
        # the two agree for the elongated shapes a concentration takes, and
        # the true diameter is quadratic in a set that can hold thousands.
        extent = math.dist(
            (min(node.x for node in members), min(node.y for node in members),
             min(node.z for node in members)),
            (max(node.x for node in members), max(node.y for node in members),
             max(node.z for node in members)),
        )
        found.append({
            "peak_mpa": round(top.s_eqv, 6),
            "peak_node": top.nid,
            "peak_radius_mm": round(top.r, 6),
            "peak_z_mm": round(top.z, 6),
            "peak_theta_deg": round(top.theta_deg, 6),
            "peak_components_mpa": {
                name: round(getattr(top, name), 6) for name in COMPONENTS
            },
            "node_count": len(members),
            "r_mm": [round(min(radii), 6), round(max(radii), 6)],
            "z_mm": [round(min(zs), 6), round(max(zs), 6)],
            "extent_mm": round(extent, 6),
            "lowest_mpa": round(min(node.s_eqv for node in members), 6),
            "fraction_of_peak": round(top.s_eqv / peak, 6),
        })
    found.sort(key=lambda entry: entry["peak_mpa"], reverse=True)
    return {
        "relative_threshold": relative_threshold,
        "cell_mm": round(cell, 6),
        "peak_mpa": round(peak, 6),
        "cutoff_mpa": round(cutoff, 6),
        "concentrations": found,
        "limits": limits,
    }


def decay(
    field: ResultField,
    node: Node,
    quantity: str = "s_eqv",
    fractions: tuple[float, ...] = (0.9, 0.5, 0.25),
    nodes: list[Node] | None = None,
) -> dict:
    """How far the stress falls, going out from one node.

    The measurement that separates a notch from a section. A fillet raises the
    stress over a length comparable to its own radius, so the value collapses
    within a few millimetres of the peak; a web that is too thin carries a
    high stress over tens of millimetres and falls away slowly. The two want
    opposite changes - a bigger radius, or more material - and the peak value
    alone cannot tell them apart.

    `nodes` is the set the walk happens in, and passing it is not optional in
    spirit: a walk over the whole part measures the distance to the nearest
    *other* surface, because a node on the bore is a few millimetres from a
    node on the web and the stress crosses a gap the material does not. Pass
    the region the node sits in - a radius band, a face's own nodes - and the
    answer is the fall along this surface. The count walked over is reported
    so a reader can see how wide the question was.

    An earlier version tried to guess the surface by filtering on radius and
    quadrant. It was dropped because the guess was invisible in the answer:
    the same call on the same node returned different distances depending on
    which other regions happened to be in the field.
    """
    if quantity not in QUANTITIES:
        raise ValueError(f"{quantity!r} is not a measurable quantity")
    reference = getattr(node, quantity)
    if reference is None or reference <= 0:
        return {
            "node": node.nid,
            "limits": [f"node {node.nid} has {quantity} = {reference}"],
        }

    candidates = [
        other for other in (nodes if nodes is not None else field.stressed())
        if other.nid != node.nid and getattr(other, quantity) is not None
    ]
    if not candidates:
        return {
            "node": node.nid,
            "limits": ["there was no other node in the set to walk out to"],
        }

    distances = sorted(
        (node.distance_to(other), getattr(other, quantity), other)
        for other in candidates
    )
    reached: dict[str, dict | None] = {}
    limits: list[str] = []
    for fraction in fractions:
        target = reference * fraction
        hit = next(
            (entry for entry in distances if entry[1] <= target), None
        )
        if hit is None:
            reached[f"{fraction:g}"] = None
            limits.append(
                f"{quantity} never falls to {fraction:g} of the node's value "
                f"({target:.6g}) anywhere in the {len(candidates)} nodes "
                "walked; over this region the peak is not local"
            )
        else:
            distance, value, other = hit
            reached[f"{fraction:g}"] = {
                "distance_mm": round(distance, 6),
                "value_mpa": round(value, 6),
                "node": other.nid,
            }
    return {
        "node": node.nid,
        "quantity": quantity,
        "at_node": round(reference, 6),
        "at_r_mm": round(node.r, 6),
        "at_z_mm": round(node.z, 6),
        "reached": reached,
        "walked_node_count": len(candidates),
        "limits": limits,
    }


def components(nodes: list[Node]) -> dict:
    """The cylindrical breakdown over a set of nodes, and which one dominates.

    Reported as ratios as well as values, because the ratio is what names the
    mechanism: a peak where hoop is a large multiple of radial is a
    hoop-driven problem, and one where radial is comparable is a radial
    bending problem, and the two are relieved by different geometry.

    Nothing here decides which mechanism it is - it reports the numbers and
    the dominant component, and the agent attributes.
    """
    hot = [node for node in nodes if node.stressed]
    if not hot:
        return {"limits": ["no stressed nodes in this set"]}
    top = max(hot, key=lambda node: node.s_eqv)
    means = {
        name: sum(getattr(node, name) for node in hot) / len(hot)
        for name in COMPONENTS
    }
    peak = max(top.s_eqv, 1e-12)
    return {
        "node_count": len(hot),
        "at_peak_node": top.nid,
        "at_peak_radius_mm": round(top.r, 6),
        "at_peak_z_mm": round(top.z, 6),
        "at_peak_theta_deg": round(top.theta_deg, 6),
        "peak": {
            name: round(getattr(top, name), 6) for name in COMPONENTS
        },
        "peak_ratios": {
            name: round(getattr(top, name) / peak, 6) for name in COMPONENTS
        },
        "mean": {name: round(value, 6) for name, value in means.items()},
        "dominant": max(COMPONENTS, key=lambda name: abs(getattr(top, name))),
        "limits": [],
    }


def _angular_span_deg(nodes: list[Node]) -> float:
    """The angle a set of nodes covers, wrapping around zero correctly.

    `max(theta) - min(theta)` is right until a sector straddles the +/-180
    degree line, at which point it reports about 359 degrees for a model that
    covers twenty. The span is the complement of the largest gap instead,
    which is the same number when the set does not wrap and the right number
    when it does.
    """
    if len(nodes) < 2:
        return 0.0
    angles = sorted(node.theta_deg % 360.0 for node in nodes)
    gaps = [
        angles[index + 1] - angles[index]
        for index in range(len(angles) - 1)
    ]
    gaps.append(angles[0] + 360.0 - angles[-1])
    return 360.0 - max(gaps)


def section_resultant(
    nodes: list[Node],
    r_mm: float,
    half_width_mm: float | None = None,
) -> dict:
    """The area-weighted radial stress across a cylindrical cut, and its resultant.

    The mean radial stress over a band at a chosen radius is the measurement
    that follows the load path: it says how much of a pull is being carried by
    the material at that radius, and comparing two radii says where the load
    has been shed and where it has not.

    `nodes` is the reference set and should be the whole field, because the
    cut's area is a property of the model and not of whichever nodes happen to
    fall in the band. An earlier version took the area from the band's own
    node span, which was wrong in a way that was invisible in the answer: at
    r = 200 mm on D27 the band's nodes reach only z = 19.3 mm of the model's
    38 mm - the fir-tree has taken the rest - so the area came out half what it
    is and the resultant came out half what it is. Measured down a disc, that
    produced a sequence rising to r = 200 and falling after, which a constant
    slab of material cannot do. The area now comes from the reference set, and
    how much of the cut the band actually covers is reported beside it.

    What the number does NOT isolate: on a rotating disc the radial stress at
    a cut carries the outboard centrifugal load *and* the part of it the hoop
    stress has already absorbed, so it is not a reading of blade pull alone.
    Reading it as the blade load would overstate that load by the disc's own
    weight, which on D27 is the larger of the two by an order of magnitude.
    """
    if half_width_mm is None:
        half_width_mm = max(r_mm * 0.02, 1.0)
    band = [
        node for node in nodes
        if abs(node.r - r_mm) <= half_width_mm and node.stressed
    ]
    if not band:
        return {
            "r_mm": r_mm,
            "half_width_mm": half_width_mm,
            "limits": [
                f"no stressed node lies within {half_width_mm} mm of r = "
                f"{r_mm} mm"
            ],
        }

    # Area weighting: a node stands for an annular patch whose area grows with
    # r, so an unweighted mean over a band that spans radii over-counts the
    # inner nodes.
    weights = [node.r for node in band]
    total = sum(weights)
    mean_radial = sum(
        node.s_radial * weight for node, weight in zip(band, weights)
    ) / total
    mean_hoop = sum(
        node.s_hoop * weight for node, weight in zip(band, weights)
    ) / total

    # The cut belongs to the model, not to the band.
    reference_z = [
        node.z for node in nodes if node.stressed
    ] or [node.z for node in nodes]
    axial_span_mm = max(reference_z) - min(reference_z)
    angular_span_deg = _angular_span_deg([node for node in nodes if node.stressed])
    area_mm2 = r_mm * math.radians(angular_span_deg) * axial_span_mm

    band_z = [node.z for node in band]
    band_z_span = max(band_z) - min(band_z)
    coverage = band_z_span / axial_span_mm if axial_span_mm > 0 else 0.0

    limits = [
        "the resultant is the radial stress over the cut as modelled - over "
        "the sector's angle and the modelled thickness, not over the whole "
        "component. No scaling factor has been applied",
        "the radial stress at a cut carries the outboard centrifugal load and "
        "the part of it the hoop stress has already taken, so this is not the "
        "blade pull on its own",
    ]
    if coverage < 0.8:
        limits.append(
            f"the nodes within {half_width_mm} mm of r = {r_mm} mm span only "
            f"{band_z_span:.4g} mm of the model's {axial_span_mm:.4g} mm in z, "
            f"so the band samples {coverage:.0%} of the thickness it is being "
            "averaged over. The mean is over real nodes; whether they "
            "represent the whole cut is a question about the mesh"
        )

    return {
        "r_mm": r_mm,
        "half_width_mm": half_width_mm,
        "node_count": len(band),
        "r_span_mm": [round(min(n.r for n in band), 6),
                      round(max(n.r for n in band), 6)],
        "z_span_mm": [round(min(band_z), 6), round(max(band_z), 6)],
        "theta_span_deg": [round(min(n.theta_deg for n in band), 6),
                           round(max(n.theta_deg for n in band), 6)],
        "model_z_span_mm": round(axial_span_mm, 6),
        "model_angular_span_deg": round(angular_span_deg, 6),
        "z_coverage_fraction": round(coverage, 6),
        "mean_s_radial_mpa": round(mean_radial, 6),
        "mean_s_hoop_mpa": round(mean_hoop, 6),
        "cut_area_mm2": round(area_mm2, 6),
        "radial_resultant_n": round(mean_radial * area_mm2, 6),
        "limits": limits,
    }


# --- what is on disk -----------------------------------------------------


def reported_scalars(metrics: dict | None) -> dict[str, float | None]:
    """The scalars a run reports, lifted out of the structure they sit in.

    `structural_metrics.json` groups them - stress under `stress`, displacement
    under `displacement`, loads under `load_audit` - and anything comparing two
    revisions wants them flat. Reading `metrics["max_von_mises_mpa"]` finds
    nothing, and finding nothing reads as "the run did not report it", which
    is a different statement from "it was looked for under the wrong key".

    Every name here is one the verification stage produces a verdict about, so
    a caller comparing two revisions is comparing quantities whose quotability
    has already been judged rather than quantities nobody has looked at.
    """
    metrics = metrics or {}
    stress = metrics.get("stress") or {}
    displacement = metrics.get("displacement") or {}
    audit = metrics.get("load_audit") or {}
    return {
        "max_von_mises_mpa": stress.get("max_von_mises_mpa"),
        "min_safety_factor": stress.get("min_safety_factor"),
        "max_load_surface_von_mises_mpa": stress.get(
            "max_load_surface_von_mises_mpa"
        ),
        "max_displacement_mm": displacement.get("max_mm"),
        "target_force_n_per_slot": audit.get("target_force_n_per_slot"),
    }


def mesh_noise_floor(
    job_dir: Path, metrics: tuple[str, ...] | None = None
) -> dict:
    """How far a reported number moves when only the mesh changes.

    This is the measurement that decides whether a comparison between two
    revisions means anything. Measured on D27: the same part, the same load,
    the same parameters, meshed at 181,362 nodes and again at 194,011 - seven
    per cent more nodes - moved the peak von Mises stress by 5.09%. Any
    difference between two revisions smaller than that is a difference the
    mesh could have produced on its own, and reading it as a design effect is
    reading noise.

    The chain already runs the study: the meshing stage solves the part at two
    resolutions and leaves both results on disk. Nothing computes the
    difference between them, so the numbers are read one at a time and the
    spread between them is thrown away. This reads it.

    Returns the spread per metric and, for each, which two levels it came
    from. An empty result means no study was run, which is not the same as a
    spread of zero - a run with no study has no idea what its noise floor is,
    and a caller that treats the absence as zero will read every coincidence
    as a finding.
    """
    wanted = metrics or (
        "max_von_mises_mpa", "min_safety_factor",
        "max_load_surface_von_mises_mpa", "max_displacement_mm",
    )
    root = Path(job_dir) / "mesh" / "convergence"
    levels: list[tuple[str, int, dict]] = []
    if root.is_dir():
        for level_dir in sorted(root.iterdir()):
            path = level_dir / "structural_metrics.json"
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            node_count = (
                (payload.get("stress_sampling") or {}).get("mesh_node_count")
                or payload.get("node_count") or 0
            )
            levels.append((level_dir.name, int(node_count),
                           reported_scalars(payload)))

    if len(levels) < 2:
        return {
            "levels": [
                {"name": name, "mesh_node_count": count} for name, count, _ in levels
            ],
            "floors": {},
            "limits": [
                "fewer than two mesh levels were solved, so this run cannot "
                "say how far its own reported numbers move when only the mesh "
                "changes. A difference measured against it has no floor to be "
                "compared with"
            ],
        }

    # Coarsest and finest, by node count rather than by directory name - the
    # names are the mesher's convention and this is a question about size.
    levels.sort(key=lambda item: item[1])
    coarse, fine = levels[0], levels[-1]
    floors: dict[str, dict] = {}
    for metric in wanted:
        change = relative_change(
            coarse[2].get(metric), fine[2].get(metric)
        )
        if change is None:
            continue
        floors[metric] = {
            "relative_spread": round(abs(change), 8),
            "signed_change": round(change, 8),
            "coarse": {"level": coarse[0], "mesh_node_count": coarse[1],
                       "value": coarse[2].get(metric)},
            "fine": {"level": fine[0], "mesh_node_count": fine[1],
                     "value": fine[2].get(metric)},
            "note": (
                f"{metric} moved {change:+.2%} between a mesh of "
                f"{coarse[1]} nodes and one of {fine[1]}. A change smaller "
                "than this between two revisions is one the mesh could have "
                "produced on its own."
            ),
        }
    return {
        "levels": [
            {"name": name, "mesh_node_count": count} for name, count, _ in levels
        ],
        "floors": floors,
        "limits": [],
    }


def mesh_convergence_percent(job_dir: Path) -> dict[str, float] | None:
    """The change between two mesh levels, in the shape `checks` reads.

    `checks.mesh_convergence` takes a metric-name-to-percent map and turns each
    entry into a comparison; `verify` then uses those to decide whether a
    reported number has settled. Both were written and neither was ever given
    anything: the meshing stage solves the part at two resolutions and leaves
    both `structural_metrics.json` files on disk, and the only thing that ever
    read them was `convergence_report.json`, which nothing writes.

    Measured on D27: the peak von Mises stress moved 5.09% between a mesh of
    181,362 nodes and one of 194,011 - so on that run the headline number had
    not settled, and the verification stage reported it as `unverified`, which
    says only that no second opinion existed. It did exist. This is it.
    """
    floor = mesh_noise_floor(job_dir)
    floors = floor.get("floors") or {}
    if not floors:
        return None
    return {
        metric: entry["signed_change"] * 100.0
        for metric, entry in floors.items()
    }


def relative_change(before: float | None, after: float | None) -> float | None:
    """How much a reported quantity moved between two measurements."""
    if before is None or after is None:
        return None
    if abs(before) < 1e-12:
        return None
    return (after - before) / abs(before)


def load_context(solve_dir: Path, job_dir: Path | None = None) -> dict:
    """Everything the solve left behind, read without interpreting it.

    Gathered in one place so an agent can find out what it is able to ask
    before it starts asking, and so a tool that needs a file reports the file
    rather than the absence of a number. `metrics` and `verdicts` are passed
    through as they were written - this returns what the run said about
    itself, not a second opinion about it.
    """
    solve_dir = Path(solve_dir)
    job_dir = Path(job_dir) if job_dir is not None else solve_dir.parent

    def _json(path: Path):
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    metrics = _json(solve_dir / "structural_metrics.json")
    audit = _json(solve_dir / "load_audit.json")
    selection = _json(solve_dir / "selected_face_nodes.json")
    verification = _json(job_dir / "verification.json")

    limits = []
    for name, payload in (
        ("structural_metrics.json", metrics),
        ("load_audit.json", audit),
        ("selected_face_nodes.json", selection),
        ("verification.json", verification),
    ):
        if payload is None:
            limits.append(
                f"{name} is not present, so whatever it carries cannot be "
                "measured in this run"
            )

    return {
        "solve_dir": str(solve_dir),
        "metrics": metrics,
        "load_audit": audit,
        "selection": selection,
        "verdicts": (verification or {}).get("verdicts"),
        "limits": limits,
    }


def face_stress(field: ResultField, selection: dict | None) -> dict:
    """Stress per CAD face, over the faces the selection names.

    This is the join that turns a location into a feature. A finding that says
    "1482 MPa at r = 212.3 mm" cannot be acted on by anything; one that says
    "1482 MPa on CAD face 3954" can, because that face is a named piece of
    geometry that a design change can move.

    The faces available here are the ones the selection carries - on D27 the
    24 fir-tree faces the load enters through. The rest of the part's faces
    are not in this file; joining the whole body needs the CAD document and is
    a separate measurement, not a bigger version of this one.
    """
    if not selection:
        return {
            "faces": [],
            "limits": [
                "no selected_face_nodes.json, so no node-to-CAD-face join is "
                "available for this run"
            ],
        }
    per_face = selection.get("per_face") or {}
    if not per_face:
        return {
            "faces": [],
            "limits": ["the selection names no faces"],
        }

    by_id = {node.nid: node for node in field.nodes}
    faces = []
    absent = 0
    unstressed = 0
    for key, row in per_face.items():
        named = list(row.get("node_ids", ()))
        members = [by_id[nid] for nid in named if nid in by_id]
        absent += len(named) - len(members)
        stressed = [node for node in members if node.stressed]
        # Two different things, and conflating them made the report wrong in
        # the direction that matters: a node the field has never heard of
        # means the selection and the solve are different meshes, which is a
        # broken run, while a node with no stress result is an ordinary
        # mid-side node on a run that is fine. Measured on d27-correct24, the
        # second is 11,334 of a 16,376-node selection and the first is zero.
        unstressed += len(members) - len(stressed)
        normal = row.get("normal_cylindrical") or {}
        entry = {
            "cad_face": int(key),
            "area_mm2": round(float(row.get("area_mm2") or 0.0), 6),
            "centroid_mm": [round(float(v), 6) for v in row.get("centroid_mm", [])],
            "centroid_radius_mm": (
                round(math.hypot(*row["centroid_mm"][:2]), 6)
                if len(row.get("centroid_mm") or []) >= 2 else None
            ),
            "normal_cylindrical": {
                k: round(float(v), 6) for k, v in normal.items()
            } if normal else None,
            "node_count": len(members),
            "stressed_node_count": len(stressed),
        }
        if stressed:
            top = max(stressed, key=lambda node: node.s_eqv)
            entry.update({
                "max_von_mises_mpa": round(top.s_eqv, 6),
                "max_node": top.nid,
                "max_at_r_mm": round(top.r, 6),
                "max_at_z_mm": round(top.z, 6),
                "mean_von_mises_mpa": round(
                    sum(node.s_eqv for node in stressed) / len(stressed), 6
                ),
                "dominant_component": max(
                    COMPONENTS, key=lambda name: abs(getattr(top, name))
                ),
                "components_at_max_mpa": {
                    name: round(getattr(top, name), 6) for name in COMPONENTS
                },
            })
        else:
            entry.update({
                "max_von_mises_mpa": None,
                "max_node": None,
                "mean_von_mises_mpa": None,
                "dominant_component": None,
                "components_at_max_mpa": None,
            })
        faces.append(entry)

    faces.sort(
        key=lambda entry: entry["max_von_mises_mpa"] or float("-inf"),
        reverse=True,
    )
    limits = []
    if absent:
        limits.append(
            f"{absent} node(s) named by the selection are not in the result "
            "field at all - the selection and the solve are from different "
            "meshes and the per-face numbers below are over whatever did "
            "match"
        )
    if unstressed:
        limits.append(
            f"{unstressed} node(s) named by the selection carry no stress "
            "result - they are mid-side nodes, whose stress SOLID187 does not "
            "store. The per-face maximum is over corner nodes only, as it is "
            "everywhere else in this package"
        )
    limits.append(
        f"only the {len(faces)} face(s) the selection names are covered. The "
        "rest of the part's CAD faces are not joined here; locating a peak "
        "that falls outside these faces needs the CAD document"
    )
    return {"faces": faces, "limits": limits}
