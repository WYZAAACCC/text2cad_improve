"""What a sandboxed analysis script is given, and how it asks for more.

An agent that writes code to answer a question needs a cheap starting point
and an expensive way to go deeper, and it should be obvious which is which.

The faces it is already looking at are handed over as plain rows in a JSON
file: the common question - what shape is this set, is it one cluster or two -
costs a JSON load and nothing else. The part itself can be opened as well, at
the price of starting up the whole geometry stack and reading the document,
which is around twenty seconds. That is there for the questions that genuinely
need the model and not for the ones that only need the numbers.

The path to the input document arrives in `SEEKFLOW_SANDBOX_INPUT`. This module
is imported by the child process, which is why it reads the environment rather
than taking arguments: the script the agent wrote is the entry point and it has
nowhere to pass them.

Nothing here decides anything. It hands over measurements and lets the script
do whatever it was written to do.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

INPUT_ENV = "SEEKFLOW_SANDBOX_INPUT"


def _input_path() -> Path:
    raw = os.environ.get(INPUT_ENV)
    if not raw:
        raise RuntimeError(
            f"{INPUT_ENV} is not set; this module only works inside the "
            "analysis sandbox"
        )
    return Path(raw)


def context() -> dict:
    """The whole document: paths, the scope, and the rows."""
    return json.loads(_input_path().read_text(encoding="utf-8"))


# What every row carries, and under which name. Listed here because the
# docstring that used to stand in for this said "read them with the keys you
# would see in a tool reply" - and that was false. A tool reply reports
# `radius_mm`, flat; these rows carried `centroid_cyl_mm_deg[0]`, nested.
# Three separate runs wrote a script whose only purpose was to print the key
# names and find that out, spending an LLM round trip each to rediscover the
# same mismatch. Both spellings are present below so neither habit is wrong.
ROW_FIELDS = {
    "surface_type": "plane, cylinder, cone, torus, ...",
    "area_mm2": "face area",
    "radius_mm": "centroid distance from the axis",
    "theta_deg": "centroid azimuth",
    "z_mm": "centroid axial position",
    "normal_radial": "outward unit normal, radial component (-1..1)",
    "normal_tangential": "outward unit normal, hoop component (-1..1)",
    "normal_axial": "outward unit normal, axial component (-1..1)",
    "normal_xyz": "[x, y, z] of the outward unit normal",
    "centroid_mm": "[x, y, z] of the centroid",
    "centroid_cyl_mm_deg": "[radius, theta_deg, z_mm] of the centroid",
    "normal_cylindrical": "{radial, tangential, axial} of the outward normal",
    "edge_count": "how many edges bound the face",
    "bbox_mm": "[xmin, ymin, zmin, xmax, ymax, zmax]",
    "uv_bounds": "the parametric range of the face",
    "plane_axis": "a planar face's {origin_mm, direction}",
    "origin_relation": "whether the operation modified the face or carried it",
    "origin_operand": "whether it descends from the tool or the target",
    "origin": "the full provenance record, or None if none was indexed",
}


def rows() -> list[dict]:
    """The measured faces the agent could already see, as plain dictionaries.

    Every row carries the fields named in `ROW_FIELDS`. Both the flat names a
    tool reply uses (`radius_mm`, `normal_radial`) and the nested ones the
    measured facts arrive in (`centroid_cyl_mm_deg`, `normal_cylindrical`) are
    present, so a script can be written from either habit.

    A field is None when the face has no measured value for it - a normal on a
    face whose centroid sits on the axis, for instance. That is a fact about
    the face, not an error, and a filter written over such a field should say
    what it does with those rows rather than assuming they are absent.

    THE POSITION IS THE FACE INDEX. There is no `face_index` field, because
    the list is already in that order: `rows()[i]` is face `i`, and the index
    a submission names is exactly the position a script filtered to. Said here
    because it is not guessable and was not written down: a run spent one of
    its thirty calls on a script whose only line was
    `print(sorted(rows[0].keys()))`, under the title "Find the index field
    name in rows", looking for a field that does not exist.
    """
    out = []
    for row in context().get("rows") or []:
        flat = dict(row)
        cylindrical = row.get("centroid_cyl_mm_deg") or [None, None, None]
        normal = row.get("normal_cylindrical") or {}
        flat["radius_mm"] = cylindrical[0]
        flat["theta_deg"] = cylindrical[1]
        flat["z_mm"] = cylindrical[2]
        flat["normal_radial"] = normal.get("radial")
        flat["normal_tangential"] = normal.get("tangential")
        flat["normal_axial"] = normal.get("axial")
        out.append(flat)
    return out


def scope() -> dict:
    """Which part of the model this run is about.

    `feature` and `solid_index` name the body the rows came from, and `sector`
    is the repeating sector being solved when the analysis is not of the whole
    part - absent when it is.
    """
    document = context()
    return {
        "feature": document.get("feature"),
        "solid_index": document.get("solid_index"),
        "sector": document.get("sector"),
    }


def open_bundle():
    """Open the part itself. Slow, and the caller must close it.

    Use this for a question the measurements cannot answer - topology, the
    relationship between faces, a quantity no tool reports. For anything that
    is a function of the numbers already in `rows()`, use those instead: this
    costs about twenty seconds before it has done anything, and a script that
    reaches for it to compute a histogram is a script that waited for nothing.
    """
    from seekflow_structural.tools import geometry

    bundle = context().get("bundle")
    if not bundle:
        raise RuntimeError("no bundle path was provided to this sandbox")
    return geometry.open_bundle(Path(bundle))


def live_rows(feature: str | None = None, solid_index: int | None = None):
    """Re-measure a body from the model rather than from the handed-over rows."""
    from seekflow_structural.tools import geometry

    document = context()
    name = feature or document.get("feature")
    if not name:
        raise RuntimeError(
            "no feature was named and the sandbox input does not carry one"
        )
    index = document.get("solid_index", 0) if solid_index is None else solid_index
    session = open_bundle()
    try:
        return geometry.face_rows(session, str(name), int(index))
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            close()


__all__ = ["ROW_FIELDS", "context", "rows", "scope", "open_bundle",
           "live_rows"]
