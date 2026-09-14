"""Recover malformed carry roles from the unchanged previous-body face."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
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

from face_evolution.face_index import (  # noqa: E402
    connect,
    initialize_index,
    insert_face_role,
)


def _facts_map(faces):
    result = []
    for index, face in enumerate(faces):
        facts = face_facts(face)
        radius, theta, z = facts["centroid_cyl_mm_deg"]
        result.append(
            {
                "index": index,
                "face": face,
                "facts": facts,
                "radius": radius,
                "theta": theta,
                "z": z,
            }
        )
    return result


def recover(
    bundle: Path,
    database: Path,
    previous_feature: str,
    final_feature: str,
    carry_indices: list[int],
) -> dict:
    bundle = bundle.resolve()
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    revision_id = history["revision_id"]
    connection = connect(database)
    initialize_index(connection)
    session = _open(bundle)
    recovered = []
    failed = []
    try:
        previous_entry = _feature_entry(session, previous_feature)
        previous_shape = session.get_current_result_shape(
            previous_entry.tag_path.resolve(session.main_label)
        )
        previous_solids = _explode_solids(previous_shape)
        if len(previous_solids) != 1:
            raise RuntimeError("previous body must contain one solid")
        _, previous_faces = _solid_facts(previous_solids[0])

        final_entry = _feature_entry(session, final_feature)
        final_shape = session.get_current_result_shape(
            final_entry.tag_path.resolve(session.main_label)
        )
        final_solids = _explode_solids(final_shape)
        if len(final_solids) != 1:
            raise RuntimeError("final body must contain one solid")
        _, final_faces = _solid_facts(final_solids[0])
        final_rows = _facts_map(final_faces)

        for index in carry_indices:
            role_key = f"target_face_{index}/carry"
            entry = session.label_index.get_existing(
                "face_role", f"feature:{final_feature}", role_key
            )
            if entry is None:
                failed.append({"face_index": index, "error": "role entry missing"})
                continue
            if index >= len(previous_faces):
                failed.append(
                    {"face_index": index, "error": "previous face index out of range"}
                )
                continue
            source_face = previous_faces[index]
            source_facts = face_facts(source_face)
            matches = []
            for row in final_rows:
                if row["face"].IsSame(source_face):
                    matches.append(row)
            if not matches:
                area = source_facts["area_mm2"]
                center = source_facts["centroid_mm"]
                for row in final_rows:
                    area_error = abs(area - row["facts"]["area_mm2"]) / max(
                        area, row["facts"]["area_mm2"], 1e-30
                    )
                    center_error = math.dist(
                        center, row["facts"]["centroid_mm"]
                    )
                    if area_error <= 1e-7 and center_error <= 1e-5:
                        matches.append(row)
            if len(matches) != 1:
                failed.append(
                    {
                        "face_index": index,
                        "error": f"carry match count {len(matches)}",
                    }
                )
                continue
            final_row = matches[0]
            canonical_face_id = (
                f"{revision_id}:solid:0:face:{final_row['index']}"
            )
            role_id = f"feature:{final_feature}|{role_key}"
            row = {
                "role_id": role_id,
                "revision_id": revision_id,
                "namespace": f"feature:{final_feature}",
                "feature_id": final_feature,
                "role_key": role_key,
                "role_tag": entry.tag_path.tags[-1],
                "label_path": list(entry.tag_path.tags),
                "created_revision": entry.created_revision,
                "relation_kind": "carry",
                "source_key": f"target_face_{index}",
                "operation_id": final_feature,
                "resolution_status": "resolved",
                "resolution_method": "target_carry_shape_match",
                "resolved_face_id": canonical_face_id,
                "surface_type": final_row["facts"]["surface_type"],
                "area_mm2": final_row["facts"]["area_mm2"],
                "centroid_mm": final_row["facts"]["centroid_mm"],
                "radius_mm": final_row["radius"],
                "theta_deg": final_row["theta"],
                "z_mm": final_row["z"],
                "normal_xyz": final_row["facts"].get("normal_xyz"),
                "normal_cylindrical": final_row["facts"].get(
                    "normal_cylindrical"
                ),
                "bbox_mm": final_row["facts"].get("bbox_mm"),
                "fact_json": json.dumps(
                    final_row["facts"], ensure_ascii=False, sort_keys=True
                ),
            }
            insert_face_role(connection, row)
            recovered.append(
                {
                    "face_index": index,
                    "role_id": role_id,
                    "resolved_face_id": canonical_face_id,
                    "method": "target_carry_shape_match",
                }
            )
        connection.commit()
        return {
            "schema_version": "carry_role_recovery_v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "recovered_count": len(recovered),
            "failed_count": len(failed),
            "recovered": recovered,
            "failed": failed,
        }
    finally:
        session.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--previous-feature", default="n_disc_revolve")
    parser.add_argument("--final-feature", default="n_final_cut")
    parser.add_argument(
        "--carry-indices",
        default="0,1,2,3,4,5,9,10,11,12,13,14,15",
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = recover(
        args.bundle,
        args.database,
        args.previous_feature,
        args.final_feature,
        [int(value) for value in args.carry_indices.split(",") if value],
    )
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

