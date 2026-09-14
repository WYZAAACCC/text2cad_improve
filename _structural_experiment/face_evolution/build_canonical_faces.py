"""Build the canonical final-face catalog for one CAD revision."""

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
    insert_canonical_face,
    set_meta,
)


def build_canonical_faces(
    bundle: Path,
    database: Path,
    feature_id: str = "n_final_cut",
) -> dict:
    bundle = Path(bundle).resolve()
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    revision_id = history["revision_id"]
    connection = connect(database)
    try:
        initialize_index(connection)
        connection.execute(
            """
            DELETE FROM face_roles
            WHERE resolved_face_id IN (
                SELECT canonical_face_id FROM canonical_faces
                WHERE revision_id = ? AND feature_id = ?
            )
            """,
            (revision_id, feature_id),
        )
        connection.execute(
            "DELETE FROM canonical_faces WHERE revision_id = ? AND feature_id = ?",
            (revision_id, feature_id),
        )
        session = _open(bundle)
        try:
            feature = _feature_entry(session, feature_id)
            shape = session.get_current_result_shape(
                feature.tag_path.resolve(session.main_label)
            )
            if shape is None:
                raise RuntimeError(f"feature {feature_id} has no current result")
            solids = _explode_solids(shape)
            count = 0
            for solid_index, solid in enumerate(solids):
                _, faces = _solid_facts(solid)
                for face_index, face in enumerate(faces):
                    facts = face_facts(face)
                    radius, theta, z = facts["centroid_cyl_mm_deg"]
                    canonical_face_id = (
                        f"{revision_id}:solid:{solid_index}:face:{face_index}"
                    )
                    row = {
                        "canonical_face_id": canonical_face_id,
                        "revision_id": revision_id,
                        "feature_id": feature_id,
                        "solid_index": solid_index,
                        "face_index": face_index,
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
                    insert_canonical_face(connection, row)
                    count += 1
            connection.commit()
            set_meta(
                connection,
                f"canonical:{revision_id}:{feature_id}",
                {
                    "bundle": str(bundle),
                    "feature_id": feature_id,
                    "revision_id": revision_id,
                    "solid_count": len(solids),
                    "face_count": count,
                    "geometry_hash": history.get("geometry_hash"),
                    "topology_hash": history.get("topology_hash"),
                },
            )
            return {
                "revision_id": revision_id,
                "feature_id": feature_id,
                "solid_count": len(solids),
                "face_count": count,
                "database": str(Path(database).resolve()),
            }
        finally:
            session.close()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--feature", default="n_final_cut")
    args = parser.parse_args()
    print(
        json.dumps(
            build_canonical_faces(args.bundle, args.database, args.feature),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

