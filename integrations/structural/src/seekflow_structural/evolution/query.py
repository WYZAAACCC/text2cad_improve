"""Asking the index which face came from where.

The index answers one question per face: which recorded role names it, and what
that role says about where the face came from. Two facts come out of it and
they are the ones worth naming:

  `origin_relation`  whether the face was **modified** by the operation that
                     produced it, or **carried** through it unchanged. A
                     carried face was already in the operand; a modified one
                     is what the operation made.
  `origin_operand`   which side of the operation it came from - the `tool`
                     that did the cutting, or the `target` being cut.

Both are discrete. That matters more than it sounds: two sets of faces can be
indistinguishable on every measurement a face has - same surface type, same
area, same normal range, same symmetry - and still come from different places,
because where a face came from is not a property of its shape. A search that
only knows measurements cannot separate them; one that knows this can, and can
say why.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from seekflow_structural.evolution import store

# How many source faces of a class are listed before the rest are summarised
# as a count. A class is often thousands of faces and the list is a sample.
MAX_SOURCES_LISTED = 24


def _operand(source_key: str) -> str:
    """`tool_face_72` -> `tool`; `target_face_9` -> `target`."""
    if not source_key:
        return ""
    return source_key.split("_", 1)[0]


def origins_for_faces(database, revision_id: str, feature_id: str,
                      solid_index: int = 0) -> dict[int, dict]:
    """face index -> what the index knows about where it came from.

    A face can be named by more than one role. When they agree on the origin
    the answer is that origin; when they disagree the face is reported with
    both, because a face that two operations claim is a fact about the model
    and not something to be resolved by picking one.
    """
    path = Path(database)
    if not path.exists():
        return {}
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT resolved_face_id, relation_kind, source_key, resolution_status
            FROM face_roles
            WHERE resolution_status = 'resolved' AND resolved_face_id IS NOT NULL
            """,
        ).fetchall()
    finally:
        connection.close()

    prefix = store.face_id(revision_id, solid_index, "")
    out: dict[int, dict] = {}
    for row in rows:
        resolved = row["resolved_face_id"]
        if not resolved.startswith(prefix):
            continue
        try:
            index = int(resolved[len(prefix):])
        except ValueError:
            continue
        entry = out.setdefault(index, {
            "origin_relation": set(), "origin_operand": set(),
            "origin_source": set(),
        })
        entry["origin_relation"].add(row["relation_kind"] or "")
        entry["origin_operand"].add(_operand(row["source_key"] or ""))
        entry["origin_source"].add(row["source_key"] or "")

    return {
        index: {
            "origin_relation": sorted(v for v in entry["origin_relation"] if v),
            "origin_operand": sorted(v for v in entry["origin_operand"] if v),
            "origin_source": sorted(v for v in entry["origin_source"] if v),
            # The single value a filter compares against, present only when the
            # roles agree - so a filter never silently picks one of two.
            "origin_relation_agreed": (
                next(iter(entry["origin_relation"]))
                if len(entry["origin_relation"]) == 1 else None
            ),
            "origin_operand_agreed": (
                next(iter(entry["origin_operand"]))
                if len(entry["origin_operand"]) == 1 else None
            ),
        }
        for index, entry in out.items()
    }


def decorate(rows: list[dict], origins: dict[int, dict]) -> list[dict]:
    """Put what is known about each face's origin onto its row.

    Done once per body rather than per query, so a filter on origin costs no
    more than a filter on radius and the rows stay plain dictionaries that
    anything downstream can read.
    """
    for index, row in enumerate(rows):
        found = origins.get(index)
        row["origin"] = found
        row["origin_relation"] = (
            found["origin_relation_agreed"] if found else None
        )
        row["origin_operand"] = found["origin_operand_agreed"] if found else None
    return rows


def summarise_origins(rows: list[dict], sector: dict | None = None) -> dict:
    """What a body's faces are made of, by where they came from.

    This is the answer to a question a measurement summary cannot answer. A
    summary of radius reports a minimum, a median and a maximum, and a set
    that is two separate bands 70 mm apart comes back as "median 285" - one
    number standing in the gap between them. Grouped by origin the same faces
    report as what they are: a small class carried through from one body and a
    large class cut by another, each with its own range.

    `sector` is the repeat unit being solved, when there is one. Both counts
    are reported - the class over the whole body and the class inside the
    sector - because they answer different questions and only one of them is
    the model: a class of 3,835 faces of which 29 are in the sector is a large
    family and a small selection, and a reader given only the first has to do
    the arithmetic to find that out.
    """
    sector_rows = _within_sector(rows, sector)
    classes: dict[tuple, dict] = {}
    without = 0
    for row in rows:
        relation = row.get("origin_relation")
        operand = row.get("origin_operand")
        if not relation and not operand:
            without += 1
            continue
        key = (relation or "unknown", operand or "unknown")
        entry = classes.setdefault(key, {
            "origin_relation": relation or "unknown",
            "origin_operand": operand or "unknown",
            "faces": 0,
            "faces_in_sector": 0,
            "surface_types": {},
            "radius_mm": [],
            "sources": set(),
        })
        entry["faces"] += 1
        kind = str(row.get("surface_type") or "unknown")
        entry["surface_types"][kind] = entry["surface_types"].get(kind, 0) + 1
        radius = (row.get("centroid_cyl_mm_deg") or [None])[0]
        if radius is not None:
            entry["radius_mm"].append(float(radius))
        for source in (row.get("origin") or {}).get("origin_source", []):
            entry["sources"].add(source)

    in_sector: dict[tuple, int] = {}
    for row in sector_rows:
        key = (
            row.get("origin_relation") or "unknown",
            row.get("origin_operand") or "unknown",
        )
        in_sector[key] = in_sector.get(key, 0) + 1

    out = []
    for key, entry in classes.items():
        radii = sorted(entry.pop("radius_mm"))
        sources = sorted(entry["sources"])
        # A class can be thousands of source faces. The count is the fact; the
        # list is a sample, and a full one would crowd out every other class
        # in the reply.
        entry["sources"] = sources[:MAX_SOURCES_LISTED]
        entry["sources_truncated"] = len(sources) > MAX_SOURCES_LISTED
        entry["source_count"] = len(sources)
        entry["faces_in_sector"] = in_sector.get(key, 0)
        entry["radius_mm"] = (
            {"min": round(radii[0], 4), "median": round(radii[len(radii) // 2], 4),
             "max": round(radii[-1], 4)}
            if radii else None
        )
        out.append(entry)
    out.sort(key=lambda item: -item["faces"])

    result = {
        "face_count": len(rows),
        "classes": out,
        "faces_without_a_recorded_origin": without,
        "note": (
            "classes group the faces by where they came from, not by what they "
            "measure. A face that two operations both claim is reported under "
            "neither, and counted in faces_without_a_recorded_origin."
        ),
    }
    if sector is not None:
        result["sector"] = dict(sector)
        result["faces_in_sector"] = len(sector_rows)
        result["note"] += (
            " `faces_in_sector` counts the ones inside the repeat unit being "
            "solved, which is the only part that will be meshed."
        )
    return result


def _within_sector(rows: list[dict], sector: dict | None) -> list[dict]:
    """The rows whose azimuth falls inside the repeat unit being solved."""
    if not sector:
        return []
    low = sector.get("theta_low_deg")
    high = sector.get("theta_high_deg")
    if low is None or high is None:
        return []
    out = []
    for row in rows:
        theta = (row.get("centroid_cyl_mm_deg") or [None, None])[1]
        if theta is None:
            continue
        if low <= high:
            if low <= theta <= high:
                out.append(row)
        elif theta >= low or theta <= high:  # a sector that wraps past zero
            out.append(row)
    return out


__all__ = ["decorate", "origins_for_faces", "summarise_origins"]
