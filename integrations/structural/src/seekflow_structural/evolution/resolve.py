"""Resolve a batch of roles, in a process of its own.

This is the part that has to be isolated. Reading a role means reading a
`TNaming_NamedShape`, and on a real document some of those attributes are
corrupt badly enough to fault the process natively - 0xC0000005, which no
`except` clause sees. Run in the parent, one bad attribute ends the run.

So the parent hands a batch here, this process opens the document once, works
through the batch, and writes a line per role. If it dies, the parent splits
the batch and tries again; a batch of one that still dies is quarantined by
name.

What is *not* done here is as important as what is. Roles are resolved by
reading the document, and that is worth avoiding wherever something cheaper
will do - a `carry` role is a face that passed through the operation
unchanged, so the face it names is already in the operand and can be found by
matching shapes against it. Doing that in `build` rather than here removes the
largest single source of native faults from this process entirely.

Usage:
    python -m seekflow_structural.evolution.resolve <bundle> <batch.json> <out.jsonl>
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from seekflow_structural.core.pattern_solids import (
    _explode_solids,
    _feature_entry,
    _open,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts

# Role keys carry their evolution kind in the key itself. Kept as data so a
# new kind is one line here rather than a new branch.
KIND_MARKERS = (
    ("/mod/", "modified"),
    ("/gen/", "generated"),
    ("/final/", "final"),
    ("/carry", "carry"),
)


def role_kind(role_key: str) -> tuple[str, str]:
    """The evolution kind, and the key of the shape it came from."""
    for marker, kind in KIND_MARKERS:
        if marker in role_key:
            return kind, role_key.split(marker, 1)[0]
    return "role", role_key


def _fact_row(facts: dict, *, revision_id: str, feature_id: str,
              solid_index: int, face_index: int) -> dict:
    cylindrical = facts.get("centroid_cyl_mm_deg") or [0.0, 0.0, 0.0]
    normal = facts.get("normal_cylindrical") or {}
    bbox = facts.get("bbox_mm")
    return {
        "revision_id": revision_id,
        "feature_id": feature_id,
        "solid_index": solid_index,
        "face_index": face_index,
        "surface_type": facts.get("surface_type") or "unknown",
        "area_mm2": float(facts.get("area_mm2") or 0.0),
        "centroid_x": float((facts.get("centroid_mm") or [0, 0, 0])[0]),
        "centroid_y": float((facts.get("centroid_mm") or [0, 0, 0])[1]),
        "centroid_z": float((facts.get("centroid_mm") or [0, 0, 0])[2]),
        "radius_mm": float(cylindrical[0]),
        "theta_deg": float(cylindrical[1]),
        "z_mm": float(cylindrical[2]),
        "normal_x": (facts.get("normal_xyz") or [None, None, None])[0],
        "normal_y": (facts.get("normal_xyz") or [None, None, None])[1],
        "normal_z": (facts.get("normal_xyz") or [None, None, None])[2],
        "normal_radial": normal.get("radial"),
        "normal_tangential": normal.get("tangential"),
        "normal_axial": normal.get("axial"),
        "bbox_json": json.dumps(bbox, ensure_ascii=False) if bbox else None,
        "fact_json": json.dumps(facts, ensure_ascii=False),
    }


def measure_final_faces(session, feature_id: str, revision_id: str
                        ) -> tuple[list[dict], dict]:
    """The finished part's faces, measured, and the live shapes behind them.

    Takes a session rather than opening one. The shapes it returns are only
    usable while that session lives - in an earlier version this opened its
    own, closed it on the way out, and handed the shapes to a resolver that
    opened the document again. Every `IsSame` against them then answered
    "no", so every role came back unresolved while looking perfectly healthy.
    """
    feature = _feature_entry(session, feature_id)
    shape = session.get_current_result_shape(
        feature.tag_path.resolve(session.main_label)
    )
    if shape is None:
        raise RuntimeError(f"feature {feature_id!r} has no current shape")
    rows: list[dict] = []
    live: dict[tuple[int, int], object] = {}
    for solid_index, solid in enumerate(_explode_solids(shape)):
        _facts, faces = _solid_facts(solid)
        for face_index, face in enumerate(faces):
            facts = face_facts(face)
            rows.append(_fact_row(
                facts, revision_id=revision_id, feature_id=feature_id,
                solid_index=solid_index, face_index=face_index,
            ))
            live[(solid_index, face_index)] = face
    return rows, live


def measure_and_resolve(bundle: Path, feature_id: str, revision_id: str,
                        canonical: list[dict], batch: list[dict]) -> list[dict]:
    """One document load for the whole batch: measure the part, then resolve."""
    session = _open(bundle)
    try:
        _rows, live = measure_final_faces(session, feature_id, revision_id)
        return resolve_batch(session, batch, canonical, live)
    finally:
        session.close()


def _prefilter(area: float, centroid, bbox, canonical: list[dict]) -> list[dict]:
    """Rows that could be this shape, judged on numbers before touching OCC.

    Every comparison here is on quantities already measured. It exists so the
    expensive `IsSame` runs against a handful of candidates rather than
    against every face of the part - and on a 4,216-face body that is the
    difference between a lookup and a scan.
    """
    out = []
    for row in canonical:
        other_area = float(row["area_mm2"])
        if abs(area - other_area) / max(area, other_area, 1e-30) > 1e-7:
            continue
        if math.dist(
            centroid,
            (float(row["centroid_x"]), float(row["centroid_y"]),
             float(row["centroid_z"])),
        ) > 1e-5:
            continue
        if bbox is not None and row["bbox_json"]:
            other = json.loads(row["bbox_json"])
            if max(
                abs(float(bbox[i]) - float(other[i])) for i in range(6)
            ) > 1e-5:
                continue
        out.append(row)
    return out


def resolve_batch(session, batch: list[dict], canonical: list[dict],
                  live: dict) -> list[dict]:
    """One row per role in the batch, resolved or explained.

    Takes the session the shapes came from, because the comparison is against
    those shapes and they are only valid while it lives.
    """
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS

    by_id = {
        (int(r["solid_index"]), int(r["face_index"])): r for r in canonical
    }
    results = []
    for item in batch:
        row = dict(item)
        try:
            label = session.main_label
            for tag in item["label_path"]:
                label = label.FindChild(int(tag), False)
                if label.IsNull():
                    break
            if label.IsNull():
                row.update(
                    resolution_status="error",
                    error="label path does not resolve",
                )
                results.append(row)
                continue
            shape = session.get_current_role_result(
                label.Father().Father(), label.Tag()
            )
            if shape is None or shape.IsNull():
                row.update(
                    resolution_status="unresolved",
                    error="role has no current shape",
                )
                results.append(row)
                continue
            if shape.ShapeType() != TopAbs_FACE:
                # Edge and vertex history is recorded the same way and is not
                # a face candidate. Kept as history, marked as such.
                row.update(resolution_status="not_face")
                results.append(row)
                continue
            face = TopoDS.Face_s(shape)
            facts = face_facts(face)
            for candidate in _prefilter(
                float(facts["area_mm2"]),
                facts.get("centroid_mm") or [0.0, 0.0, 0.0],
                facts.get("bbox_mm"),
                canonical,
            ):
                key = (
                    int(candidate["solid_index"]),
                    int(candidate["face_index"]),
                )
                other = live.get(key)
                if other is None:
                    continue
                if not (face.IsSame(other) or face.IsPartner(other)):
                    continue
                cylindrical = facts.get("centroid_cyl_mm_deg") or [0.0] * 3
                normal = facts.get("normal_cylindrical") or {}
                centroid = facts.get("centroid_mm") or [0.0] * 3
                row.update(
                    resolution_status="resolved",
                    resolution_method="shape_identity",
                    resolved_face_id=by_id[key]["canonical_face_id"],
                    solid_index=key[0],
                    face_index=key[1],
                    surface_type=facts.get("surface_type"),
                    area_mm2=float(facts.get("area_mm2") or 0.0),
                    centroid_x=float(centroid[0]),
                    centroid_y=float(centroid[1]),
                    centroid_z=float(centroid[2]),
                    radius_mm=float(cylindrical[0]),
                    theta_deg=float(cylindrical[1]),
                    z_mm=float(cylindrical[2]),
                    normal_radial=normal.get("radial"),
                    normal_tangential=normal.get("tangential"),
                    normal_axial=normal.get("axial"),
                    fact_json=json.dumps(facts, ensure_ascii=False),
                )
                break
            else:
                row.update(
                    resolution_status="unresolved",
                    error="no final face matches this role's shape",
                )
        except Exception as exc:  # noqa: BLE001
            row.update(
                resolution_status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        results.append(row)
    return results


def _main(argv: list[str]) -> int:
    bundle = Path(argv[1]).resolve()
    batch_path = Path(argv[2])
    out_path = Path(argv[3])

    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    results = measure_and_resolve(
        bundle,
        payload["final_feature"],
        payload["revision_id"],
        payload["canonical"],
        payload["batch"],
    )
    with out_path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
