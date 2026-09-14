"""Resolve one range of face-role entries in an isolated process."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

STRUCTURAL_ROOT = Path(__file__).resolve().parents[1]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from seekflow_structural.core.pattern_solids import (  # noqa: E402
    _explode_solids,
    _feature_entry,
    _open,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts  # noqa: E402
from OCP.TopAbs import TopAbs_FACE  # noqa: E402

from face_evolution.face_index import connect, initialize_index  # noqa: E402


def _relation_kind(role_key: str) -> tuple[str, str]:
    for marker, kind in (
        ("/gen/", "generated"),
        ("/mod/", "modified"),
        ("/carry", "carry"),
    ):
        if marker in role_key:
            return kind, role_key.split(marker, 1)[0]
    return "role", role_key


def _center(row) -> list[float]:
    return [
        float(row["centroid_x"]),
        float(row["centroid_y"]),
        float(row["centroid_z"]),
    ]


def _bbox(row) -> list[float] | None:
    value = json.loads(row["bbox_json"]) if row["bbox_json"] else None
    return value


def _prefilter(facts: dict, canonical_rows: list) -> list:
    candidate_rows = []
    area = float(facts["area_mm2"])
    center = facts["centroid_mm"]
    bbox = facts.get("bbox_mm")
    for row in canonical_rows:
        area_error = abs(area - float(row["area_mm2"])) / max(
            area, float(row["area_mm2"]), 1e-30
        )
        if area_error > 1e-7:
            continue
        row_center = _center(row)
        center_error = math.dist(center, row_center)
        if center_error > 1e-5:
            continue
        row_bbox = _bbox(row)
        if bbox is not None and row_bbox is not None:
            bbox_error = max(
                abs(float(bbox[index]) - float(row_bbox[index]))
                for index in range(6)
            )
            if bbox_error > 1e-5:
                continue
        candidate_rows.append(row)
    return candidate_rows


def _final_faces(bundle: Path, feature_id: str):
    session = _open(bundle)
    try:
        feature = _feature_entry(session, feature_id)
        shape = session.get_current_result_shape(
            feature.tag_path.resolve(session.main_label)
        )
        if shape is None:
            raise RuntimeError("final feature has no current shape")
        solids = _explode_solids(shape)
        faces = {}
        for solid_index, solid in enumerate(solids):
            _, solid_faces = _solid_facts(solid)
            for face_index, face in enumerate(solid_faces):
                faces[(solid_index, face_index)] = face
        return faces
    finally:
        session.close()


def _resolve_role(session, entry):
    role_label = entry.tag_path.resolve(session.main_label)
    feature_label = role_label.Father().Father()
    role_tag = role_label.Tag()
    return session.get_current_role_result(feature_label, role_tag)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("namespace")
    parser.add_argument("final_feature")
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    connection = connect(args.database)
    initialize_index(connection)
    session = _open(bundle)
    try:
        entries = [
            entry
            for entry in session.label_index.entries()
            if entry.retired_revision is None
            and entry.key.object_kind == "face_role"
            and entry.key.namespace == args.namespace
        ]
        rows = entries[args.start : args.end]
        canonical_rows = connection.execute(
            """
            SELECT * FROM canonical_faces
            WHERE feature_id = ?
            ORDER BY solid_index, face_index
            """,
            (args.final_feature,),
        ).fetchall()
        if not canonical_rows:
            raise RuntimeError(
                "canonical final faces must be indexed before face roles"
            )
        final_faces = _final_faces(bundle, args.final_feature)
        history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        counts = {
            "requested": len(rows),
            "resolved": 0,
            "unresolved": 0,
            "ambiguous": 0,
            "errors": 0,
        }
        with args.output.resolve().open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            for entry in rows:
                role_key = entry.key.object_id
                relation_kind, source_key = _relation_kind(role_key)
                base = {
                    "role_id": args.namespace + "|" + role_key,
                    "revision_id": history["revision_id"],
                    "namespace": args.namespace,
                    "feature_id": args.namespace.split(":", 1)[-1],
                    "role_key": role_key,
                    "role_tag": entry.tag_path.tags[-1],
                    "label_path": list(entry.tag_path.tags),
                    "created_revision": entry.created_revision,
                    "relation_kind": relation_kind,
                    "source_key": source_key,
                    "operation_id": args.final_feature,
                    "resolution_method": "role_result",
                }
                try:
                    shape = _resolve_role(session, entry)
                    if shape is None:
                        row = {
                            **base,
                            "resolution_status": "unresolved",
                            "error": "role result is None",
                        }
                        counts["unresolved"] += 1
                    elif shape.ShapeType() != TopAbs_FACE:
                        row = {
                            **base,
                            "resolution_status": "not_face",
                            "error": f"shape type {shape.ShapeType()}",
                        }
                        counts["errors"] += 1
                    else:
                        facts = face_facts(shape)
                        radius, theta, z = facts["centroid_cyl_mm_deg"]
                        candidates = _prefilter(facts, canonical_rows)
                        exact = []
                        for candidate in candidates:
                            face = final_faces.get(
                                (
                                    int(candidate["solid_index"]),
                                    int(candidate["face_index"]),
                                )
                            )
                            if face is not None and face.IsSame(shape):
                                exact.append(candidate["canonical_face_id"])
                        if len(exact) == 1:
                            resolution_status = "resolved"
                            resolved_face_id = exact[0]
                            counts["resolved"] += 1
                        elif len(exact) > 1:
                            resolution_status = "ambiguous"
                            resolved_face_id = None
                            counts["ambiguous"] += 1
                        else:
                            resolution_status = "unresolved"
                            resolved_face_id = None
                            counts["unresolved"] += 1
                        row = {
                            **base,
                            "resolution_status": resolution_status,
                            "resolved_face_id": resolved_face_id,
                            "surface_type": facts["surface_type"],
                            "area_mm2": facts["area_mm2"],
                            "centroid_mm": facts["centroid_mm"],
                            "radius_mm": radius,
                            "theta_deg": theta,
                            "z_mm": z,
                            "normal_xyz": facts.get("normal_xyz"),
                            "normal_cylindrical": facts.get(
                                "normal_cylindrical"
                            ),
                            "bbox_mm": facts.get("bbox_mm"),
                            "fact_json": json.dumps(
                                facts, ensure_ascii=False, sort_keys=True
                            ),
                        }
                except Exception as exc:  # noqa: BLE001
                    counts["errors"] += 1
                    row = {
                        **base,
                        "resolution_status": "error",
                        "error": str(exc),
                    }
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(counts, ensure_ascii=False))
    finally:
        session.close()
        connection.close()


if __name__ == "__main__":
    main()
