"""The CAD document, which is the thing a design change is actually made to.

`param_templates.build(params)` is a way of *asking* for a document. What it
returns is the document, and that is where the geometry is: thirty-one
operations on D27, each carrying its own parameters, wired into a dependency
graph. The parameters the template accepts name about a dozen scalar
dimensions and none of the operation parameters at all.

The distinction cost a run, and it cost it in the worst way. The feedback
agent located a peak on the fir-tree flanks, diagnosed it as a local stress
concentration, and asked for the root fillet to be enlarged - which is the
textbook remedy and which the document supports exactly: `n_fillet_cutter_0`
through `_6` are `fillet_sketch` operations with a `radius_mm` each, between
0.466 and 0.698 mm. The harness refused it, because the vocabulary it had
been given was the template's parameter dict and `root_fillet_mm` is not in
it. The agent then filed the finding as one that could not be carried out,
with a reason that read as though it had checked.

Nothing about that failure was visible in the output. A finding that says
"the generator cannot do this" and a finding that says "this harness does not
know how to ask" are the same sentence from the outside, and only one of them
is true.

So this module reads the document as what it is. Everything a change can name
lives in `nodes[].params`, and every one of those is reachable at
`/nodes/<id>/params/<field>` - which is the path pattern the generator's own
repair kernel already accepts, so a change made here is one the rest of the
system was built to carry.

What it does not do is decide whether a value is geometrically possible. A
fillet radius larger than the edge it rounds is rejected by the kernel with
`BRep_API: command not done`, and that is the right place for it: the kernel
knows the local geometry and this module does not. Measured on D27, doubling
the fir-tree fillets fails and one and a half times works, and no rule
written here could have told you where between the two the line is.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

# Operations whose parameters a design change is likely to want, with what
# each one's numbers mean. Not a whitelist - `nodes()` reports every
# parameter of every operation, and a change may name any of them. This is
# the vocabulary a reader is given so that a first look at a document is
# legible rather than thirty-one entries of equal weight.
KNOWN_OPS: dict[str, str] = {
    "create_2d_sketch": "an empty sketch, the start of a profile",
    "add_polyline": "the profile's points, as explicit coordinates",
    "close_profile": "closes the contour",
    "fillet_sketch": "rounds a vertex: radius_mm, at_vertex_index",
    "extrude_profile": "extrudes a closed profile",
    "revolve_profile": "revolves a closed profile about the axis",
    "circular_pattern_component": "repeats a body about the axis",
    "boolean_cut": "subtracts one body from another",
}

# Parameters that are a list of coordinates rather than a scalar, and so are
# set as a whole rather than one number at a time.
POINT_PARAMS = ("points",)

# `<node>.points[3].y_mm` - one coordinate of one vertex of a profile. A
# profile has no name of its own in the document, so a change that has to move
# one is named by where it sits in the list. On this part that is the only
# handle on the web, and the web is where the peak is.
VERTEX_PARAM = re.compile(r"^points\[(\d+)\]\.(x_mm|y_mm)$")


def nodes(document: dict) -> list[dict]:
    """Every operation in the document, with what a change could set on it.

    The scalars are separated from the structure because they are edited
    differently: a radius is one number and a profile is a list of points,
    and handing them to an agent in one undifferentiated blob is how a change
    gets aimed at the wrong kind of thing.
    """
    out = []
    for node in document.get("nodes") or []:
        params = node.get("params") or {}
        scalars = {
            name: value for name, value in params.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        point_lists = {
            name: len(value) for name, value in params.items()
            if name in POINT_PARAMS and isinstance(value, list)
        }
        out.append({
            "id": node.get("id"),
            "op": node.get("op"),
            "component": node.get("component"),
            "phase": node.get("phase"),
            "means": KNOWN_OPS.get(str(node.get("op")), ""),
            "scalar_params": scalars,
            "point_lists": point_lists,
        })
    return out


def summary(document: dict) -> dict:
    """The document at a glance: what it is made of and what can be set on it."""
    ops: dict[str, int] = {}
    settable = 0
    for node in document.get("nodes") or []:
        op = str(node.get("op"))
        ops[op] = ops.get(op, 0) + 1
        params = node.get("params") or {}
        settable += sum(
            1 for value in params.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
    return {
        "document_id": document.get("document_id"),
        "part_name": document.get("part_name"),
        "component_count": len(document.get("components") or []),
        "node_count": len(document.get("nodes") or []),
        "operations": ops,
        "settable_scalar_count": settable,
        "note": (
            "every scalar in every node's params can be changed, at "
            "/nodes/<id>/params/<field> - the path the generator's own repair "
            "kernel accepts. Whether a value is geometrically possible is the "
            "kernel's answer, not this module's: a fillet larger than its edge "
            "is rejected when the document is built."
        ),
    }


def find(document: dict, node_id: str) -> dict | None:
    return next(
        (node for node in document.get("nodes") or []
         if node.get("id") == node_id),
        None,
    )


def set_scalar(document: dict, node_id: str, param: str, value: float) -> dict:
    """Change one number on one operation.

    Returns the change as a patch in the shape the generator's repair kernel
    uses - `path`, `old_value`, `new_value` - so that a change made here can
    be recorded, replayed and refused by the same code that handles the
    generator's own repairs rather than by a second mechanism with its own
    idea of what a change is.
    """
    node = find(document, node_id)
    if node is None:
        raise KeyError(
            f"no operation {node_id!r} in this document. It has: "
            + ", ".join(sorted(
                str(n.get("id")) for n in document.get("nodes") or []
            ))
        )
    params = node.setdefault("params", {})
    # `points[3].y_mm` is one coordinate of one vertex, and it is written by a
    # different function because it is a different kind of thing - a contour
    # is not a number and moving a vertex is not scaling a dimension.
    vertex = VERTEX_PARAM.match(param)
    if vertex:
        index = int(vertex.group(1))
        axis = vertex.group(2)
        patch = set_vertex(
            document, node_id, index,
            **({"x_mm": value} if axis == "x_mm" else {"y_mm": value}),
        )
        patch["op"] = node.get("op")
        return patch
    if param in POINT_PARAMS:
        raise ValueError(
            f"{param!r} on {node_id!r} is a list of points, not a number. Use "
            "set_points, which replaces the whole list."
        )
    if param not in params:
        raise KeyError(
            f"{node_id!r} has no parameter {param!r}. It has: "
            + ", ".join(sorted(params)) or "(none)"
        )
    old = params[param]
    if not isinstance(old, (int, float)) or isinstance(old, bool):
        raise ValueError(
            f"{node_id!r}.{param} is {type(old).__name__}, not a number"
        )
    params[param] = value
    return {
        "path": f"/nodes/{node_id}/params/{param}",
        "old_value": old,
        "new_value": value,
        "node": node_id,
        "op": node.get("op"),
    }


def set_points(document: dict, node_id: str, points: list) -> dict:
    """Replace the whole point list of a profile.

    Replaced rather than edited point by point, because a profile is a closed
    contour and moving one vertex of it changes the shape everywhere the two
    edges that meet there go - which is a decision about the contour, not
    about a number.
    """
    node = find(document, node_id)
    if node is None:
        raise KeyError(f"no operation {node_id!r} in this document")
    params = node.setdefault("params", {})
    if "points" not in params:
        raise KeyError(
            f"{node_id!r} is a {node.get('op')!r} and carries no point list"
        )
    old = params["points"]
    # Written back in the shape the list already has. The generator writes
    # `{"x_mm": .., "y_mm": ..}` and this used to rebuild the list as pairs,
    # which would have silently changed the spelling of every vertex - and a
    # profile whose vertices are written in a shape the reader does not expect
    # is a profile with no vertices.
    template = old[0] if old else None
    normalised = []
    for pair in points:
        x, y = _xy(pair) or (None, None)
        if x is None:
            raise ValueError(f"{pair!r} is not a coordinate pair")
        normalised.append(
            {"x_mm": x, "y_mm": y} if isinstance(template, dict) else [x, y]
        )
    if len(normalised) != len(old):
        raise ValueError(
            f"{node_id!r} has {len(old)} points and {len(normalised)} were "
            "given. A profile is a closed contour; replacing it with a "
            "different number of vertices changes which edges meet where, and "
            "that is a different operation rather than a moved point."
        )
    params["points"] = normalised
    return {
        "path": f"/nodes/{node_id}/params/points",
        "old_value": old,
        "new_value": normalised,
        "node": node_id,
    }


def _xy(point) -> tuple[float, float] | None:
    """A profile vertex, whichever of the two shapes it is written in.

    The generator writes `{"x_mm": .., "y_mm": ..}`; a hand-written document
    may carry a pair. Reading both costs nothing, and a profile that silently
    reported no vertices because of a spelling would look like a profile with
    no vertices.
    """
    if isinstance(point, dict):
        try:
            return float(point["x_mm"]), float(point["y_mm"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        try:
            return float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
    return None


# --- where a parameter is, not only what it is -----------------------------
#
# A value without a position is a value whose meaning the reader has to guess,
# and that guess has been made wrongly. Measured: the feedback agent located a
# peak at r = 208.09 mm on the web's outer surface and asked for
# `n_fillet_cutter_0.radius_mm` to be enlarged - because it is a fillet and
# the agent had decided the problem was a fillet problem. That parameter acts
# on the fir-tree cutter, whose profile runs from r = 277.9 mm to 300 mm. It
# was 70 mm from the peak. The change was made, built, solved, and came back
# at -0.00%, and nothing in the run said why.


def _consumers(document: dict) -> dict[str, list[dict]]:
    """node id -> the nodes that take it as an input."""
    out: dict[str, list[dict]] = {}
    for node in document.get("nodes") or []:
        for entry in node.get("inputs") or []:
            source = entry.get("node")
            if source:
                out.setdefault(str(source), []).append(node)
    return out


def placement(document: dict, node_id: str) -> dict:
    """How a sketch node's own coordinates are placed in the world.

    Walked forward through the consumers rather than read off the sketch node,
    because the sketch says `plane: XY, origin: 0, 0` and its points sit at a
    local radius of 6 to 22 mm - which is not where the part is. What puts
    them there is a `circular_pattern_component` further down that repeats the
    body about the axis at a stated radius.

    A placement this does not understand is reported as `unknown`, and a
    position is then not reported at all. A guessed position would be worse
    than none, because it would be acted on.
    """
    consumers = _consumers(document)
    seen = {node_id}
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        for consumer in consumers.get(current, []):
            cid = str(consumer.get("id"))
            if cid in seen:
                continue
            seen.add(cid)
            if str(consumer.get("op")) == "circular_pattern_component":
                params = consumer.get("params") or {}
                return {
                    "kind": "patterned_about_axis",
                    "radius_mm": float(params.get("radius_mm") or 0.0),
                    "count": params.get("count"),
                    "by": cid,
                }
            queue.append(cid)

    node = find(document, node_id) or {}
    # The plane is on the sketch this profile is drawn in, not on the profile.
    # `add_polyline` has no plane of its own; it takes a sketch as an input and
    # that is where the plane is written.
    for entry in node.get("inputs") or []:
        source = find(document, str(entry.get("node") or ""))
        if source is None:
            continue
        plane = str((source.get("params") or {}).get("plane") or "")
        if plane:
            if plane == "XZ":
                # A radial-axial cross-section: the points are already (r, z).
                return {"kind": "meridional", "plane": plane,
                        "by": str(source.get("id"))}
            return {"kind": "unknown", "plane": plane,
                    "by": str(source.get("id"))}
    return {"kind": "unknown", "plane": "", "by": node_id}


def world_positions(document: dict, node_id: str) -> dict:
    """Where each vertex of a profile lands, in the part's own frame.

    The two placements this understands are the two the generator produces: a
    meridional sketch, whose points are (r, z) as written, and a profile that a
    circular pattern places at a stated radius, where the local x is the radial
    offset inward and so `r = radius + x`.

    The second was checked rather than assumed. Enlarging `n_fillet_cutter_0`
    from 0.698 mm to 1.05 mm - one parameter, nothing else - moved 1,064 faces
    whose centroids run from r = 283.7 mm to r = 295.4 mm. Its six vertices are
    at x = -5.760, -10.892 and -15.721, giving r = 294.24, 289.11 and
    284.28 mm, and all three are in that set.
    """
    node = find(document, node_id)
    if node is None:
        return {"placed": False, "reason": f"no operation {node_id!r}"}
    points = (node.get("params") or {}).get("points")
    if not isinstance(points, list):
        return {"placed": False,
                "reason": f"{node_id!r} carries no point list"}

    how = placement(document, node_id)
    vertices = []
    for index, point in enumerate(points):
        local = _xy(point)
        if local is None:
            continue
        x, y = local
        if how["kind"] == "meridional":
            vertices.append({"index": index, "r_mm": x, "z_mm": y})
        elif how["kind"] == "patterned_about_axis":
            radius = how["radius_mm"]
            vertices.append({
                "index": index,
                "r_mm": math.hypot(radius + x, y),
                "local_x_mm": x,
                "local_y_mm": y,
            })
    return {
        "placed": bool(vertices),
        "placement": how,
        "vertices": vertices,
    }


def set_vertex(document: dict, node_id: str, index: int,
               *, x_mm: float | None = None,
               y_mm: float | None = None) -> dict:
    """Move one coordinate of one vertex of a profile.

    The other half of not being able to name the right parameter: on this part
    the peak sits on the web, and the web is not a named dimension anywhere -
    it is two profile vertices. Editing a vertex is how a section is changed,
    and until it could be named the only parameters the agent could see were
    the fillets, which are all at the rim.
    """
    node = find(document, node_id)
    if node is None:
        raise KeyError(f"no operation {node_id!r} in this document")
    points = (node.get("params") or {}).get("points")
    if not isinstance(points, list):
        raise KeyError(f"{node_id!r} carries no point list")
    if not 0 <= index < len(points):
        raise IndexError(
            f"{node_id!r} has {len(points)} vertices and was asked for "
            f"vertex {index}"
        )
    point = points[index]
    old = _xy(point)
    if old is None:
        raise ValueError(
            f"vertex {index} of {node_id!r} is not a coordinate pair"
        )
    new_x = old[0] if x_mm is None else float(x_mm)
    new_y = old[1] if y_mm is None else float(y_mm)
    if isinstance(point, dict):
        point["x_mm"], point["y_mm"] = new_x, new_y
    else:
        points[index] = [new_x, new_y]
    return {
        "path": f"/nodes/{node_id}/params/points/{index}",
        "old_value": [old[0], old[1]],
        "new_value": [new_x, new_y],
        "node": node_id,
    }


def _neighbour_radii(where: dict, index: int) -> list[float]:
    """The radii a vertex reaches, through the two edges that meet it.

    A profile is closed, so the last vertex's next neighbour is the first. The
    span is the lowest and highest of the three radii, which is the region a
    move of this one vertex can reshape.
    """
    if index not in where:
        return []
    order = sorted(where)
    position = order.index(index)
    neighbours = [order[(position - 1) % len(order)],
                  order[(position + 1) % len(order)]]
    radii = [where[index]["r_mm"]]
    radii += [where[n]["r_mm"] for n in neighbours if "r_mm" in where[n]]
    if len(radii) < 2:
        return []
    return [round(min(radii), 3), round(max(radii), 3)]


# How far a parameter that is not a profile vertex is taken to act. A fillet's
# influence is a property of the local geometry rather than of its radius, so
# this is a convention and is reported beside every answer it shapes.
DEFAULT_REACH_MM = 10.0


def reaching(document: dict, r_mm: float,
             reach_mm: float = DEFAULT_REACH_MM) -> dict[str, dict]:
    """The editable things that could touch a given radius.

    The question an agent actually has is "what can I change about this peak",
    and the answer to it is a handful of names. Handed all 161 of them, it
    scanned the ones whose *names* sounded like the problem - it looked at the
    fillets and at the disc profile - and missed the one that was exactly on the
    peak, because nothing about the name `feat_holes_poly` says "at r = 208".

    Measured: on D27 the peak at r = 208.087 is the edge of a lightening hole.
    `feat_holes_poly.points[12]` sits at r = 208.087 exactly, spanning 205.8 to
    210.4, and `n_pat_holes.radius_mm` is 208 - the pitch radius the twenty
    holes are placed on. Neither was considered.

    A profile vertex reaches across the edges that meet it, so its span decides
    it. Everything else reaches a neighbourhood of where it acts, and `reach_mm`
    is a convention rather than a measurement - reported beside the answer so a
    reader can disagree with it.
    """
    table = editable(document)
    out: dict[str, dict] = {}
    for name, entry in table.items():
        span = entry.get("spans_r_mm")
        if span:
            low, high = span
        elif entry.get("at_r_mm") is not None:
            low = entry["at_r_mm"] - reach_mm
            high = entry["at_r_mm"] + reach_mm
        elif entry.get("vertex_index") is None and entry.get("at_r_mm") is None:
            continue
        else:
            continue
        if low <= r_mm <= high:
            out[name] = entry
    return out


def placement_of(document: dict, node_id: str) -> dict | None:
    """The pattern radius a node's profile is placed on, if it is placed.

    `n_pat_holes.radius_mm` is 208 on D27 and it is the pitch radius the holes
    sit on - a number that means nothing until it is read as a radius. It is a
    parameter of the pattern rather than of the profile, so it is reported
    here rather than through the profile's vertices.
    """
    node = find(document, node_id)
    if node is None or str(node.get("op")) != "circular_pattern_component":
        return None
    params = node.get("params") or {}
    radius = params.get("radius_mm")
    if not isinstance(radius, (int, float)):
        return None
    return {"at_r_mm": float(radius), "count": params.get("count")}


def _vertex_span(document: dict, node: dict, param: str) -> dict:
    """Where an operation sits, when it sits on named vertices of a profile.

    A fillet is not anywhere itself: it is a radius applied at
    `at_vertex_index`. Reading the vertices it names, through the profile's own
    placement, is what turns `radius_mm` into a number with a place attached -
    and a place is what the change has to be aimed at.
    """
    if param != "radius_mm":
        return {}
    indices = (node.get("params") or {}).get("at_vertex_index")
    if not isinstance(indices, list) or not indices:
        return {}
    profile = _profile_behind(document, str(node.get("id")))
    if profile is None:
        return {}
    rows = {row["index"]: row for row in
            world_positions(document, profile).get("vertices") or []}
    radii = [rows[i]["r_mm"] for i in indices
             if isinstance(i, int) and i in rows and "r_mm" in rows[i]]
    if not radii:
        return {}
    out = {
        "at_r_mm": round(min(radii), 3),
        "at_vertex_index": list(indices),
    }
    if max(radii) - min(radii) > 1e-6:
        out["at_r_mm_range"] = [round(min(radii), 3), round(max(radii), 3)]
    return out


def _profile_behind(document: dict, node_id: str) -> str | None:
    """The `add_polyline` an operation on a profile is ultimately applied to.

    Walked backwards rather than read off the operation's own input, because
    the chain between them is `add_polyline -> close_profile -> fillet_sketch`
    and only the first of the three carries any coordinates.
    """
    seen = {node_id}
    queue = [node_id]
    while queue:
        node = find(document, queue.pop(0))
        if node is None:
            continue
        if isinstance((node.get("params") or {}).get("points"), list):
            return str(node.get("id"))
        for entry in node.get("inputs") or []:
            source = str(entry.get("node") or "")
            if source and source not in seen:
                seen.add(source)
                queue.append(source)
    return None


def editable(document: dict) -> dict[str, dict]:
    """Every scalar a change can name, keyed `"<node_id>.<param>"`.

    A flat map because a change names one thing: the finding says what to
    move, and the harness has to be able to say yes or no to that name without
    knowing which operation it belongs to. The value beside each name carries
    what the operation is and what the number currently is, so a reader can
    tell a radius from a count without a second lookup.
    """
    out: dict[str, dict] = {}
    for node in document.get("nodes") or []:
        node_id = str(node.get("id"))
        for name, value in (node.get("params") or {}).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            out[f"{node_id}.{name}"] = {
                "node": node_id,
                "op": node.get("op"),
                "component": node.get("component"),
                "current_value": value,
            }
            # An operation that acts on named vertices of a profile - a fillet,
            # a chamfer - is *at* those vertices, and that is where a reader
            # needs to see it. A fillet radius with no position is what let a
            # rim fillet be proposed for a peak on the web.
            out[f"{node_id}.{name}"].update(
                _vertex_span(document, node, name)
            )
            # A pattern's radius is where it puts things, and on D27 that is
            # the number that matters most: `n_pat_holes.radius_mm` is 208,
            # and the peak is at 208.09.
            placed = placement_of(document, node_id)
            if placed and name == "radius_mm":
                out[f"{node_id}.{name}"]["at_r_mm"] = round(
                    placed["at_r_mm"], 3
                )
        # Profile vertices are settable too, and on this part they are the
        # only handle on the web - which is where the peak is.
        points = (node.get("params") or {}).get("points")
        if not isinstance(points, list):
            continue
        where = {row["index"]: row for row in
                 world_positions(document, node_id).get("vertices") or []}
        for index, point in enumerate(points):
            local = _xy(point)
            if local is None:
                continue
            # What a vertex *is* and what it *reaches* are different, and only
            # reporting the first left the agent stuck. Measured: it read
            # "the disc polyline vertices are at r=160 and r=240" and concluded
            # that no parameter controlled r=208 - which is on the edge between
            # those two vertices, and is controlled by exactly this vertex.
            span = _neighbour_radii(where, index)
            for axis, value in (("x_mm", local[0]), ("y_mm", local[1])):
                entry = {
                    "node": node_id,
                    "op": node.get("op"),
                    "component": node.get("component"),
                    "current_value": value,
                    "vertex_index": index,
                    "axis": axis,
                }
                spot = where.get(index) or {}
                if "r_mm" in spot:
                    entry["at_r_mm"] = round(spot["r_mm"], 3)
                if "z_mm" in spot:
                    entry["at_z_mm"] = round(spot["z_mm"], 3)
                if span:
                    entry["spans_r_mm"] = span
                out[f"{node_id}.points[{index}].{axis}"] = entry
    return out


def resolve(document: dict, parameter: str) -> tuple[str, str] | None:
    """`"n_fillet_cutter_0.radius_mm"` -> `("n_fillet_cutter_0", "radius_mm")`.

    Returns None when the name is not in the document, which is the answer a
    caller needs - a name that cannot be resolved cannot be changed, and
    saying so is the whole point of asking.
    """
    if "." not in parameter:
        return None
    node_id, _, param = parameter.partition(".")
    if node_id and param and f"{node_id}.{param}" in editable(document):
        return node_id, param
    return None


def relative_change(old: float, new: float) -> float | None:
    if not isinstance(old, (int, float)) or abs(old) < 1e-12:
        return None
    return (new - old) / abs(old)


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(document: dict, path: Path) -> None:
    Path(path).write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
