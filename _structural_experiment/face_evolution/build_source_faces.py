"""Index actual operation-output faces used as later feature inputs."""

from __future__ import annotations

import argparse
import json
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

from face_evolution.face_index import (  # noqa: E402
    connect,
    initialize_index,
    insert_source_face,
    set_meta,
)
from face_evolution.build_face_evolution_index import (  # noqa: E402
    _index_relation_metadata,
)


def build_source_faces(
    bundle: Path,
    database: Path,
    feature_id: str,
) -> dict:
    bundle = bundle.resolve()
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    revision_id = history["revision_id"]
    connection = connect(database)
    initialize_index(connection)
    try:
        connection.execute(
            "DELETE FROM source_faces WHERE revision_id = ? AND feature_id = ?",
            (revision_id, feature_id),
        )
        session = _open(bundle)
        try:
            entry = _feature_entry(session, feature_id)
            shape = session.get_current_result_shape(
                entry.tag_path.resolve(session.main_label)
            )
            if shape is None:
                raise RuntimeError(f"feature {feature_id} has no current result")
            solids = _explode_solids(shape)
            global_index = 0
            for solid_index, solid in enumerate(solids):
                _, faces = _solid_facts(solid)
                for face_index, face in enumerate(faces):
                    facts = face_facts(face)
                    radius, theta, z = facts["centroid_cyl_mm_deg"]
                    row = {
                        "source_face_id": (
                            f"{feature_id}:shape:{solid_index}:{face_index}"
                        ),
                        "revision_id": revision_id,
                        "feature_id": feature_id,
                        "solid_index": solid_index,
                        "face_index": global_index,
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
                    insert_source_face(connection, row)
                    global_index += 1
            connection.commit()
            relation_count = _index_relation_metadata(
                connection, bundle, f"feature:{feature_id}"
            )
            connection.commit()
            summary = {
                "revision_id": revision_id,
                "feature_id": feature_id,
                "solid_count": len(solids),
                "face_count": global_index,
                "relation_count": relation_count,
            }
            set_meta(
                connection,
                f"source_faces:{revision_id}:{feature_id}",
                summary,
            )
            return summary
        finally:
            session.close()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("feature_id")
    args = parser.parse_args()
    print(
        json.dumps(
            build_source_faces(
                args.bundle, args.database, args.feature_id
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
