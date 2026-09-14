from __future__ import annotations

import sys
from pathlib import Path

import pytest

STRUCTURAL_ROOT = Path(__file__).resolve().parents[2]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from face_evolution.agent_evolution_face_intent import (  # noqa: E402
    SelectionItem,
    _validate_selection,
)
from face_evolution.face_index import (  # noqa: E402
    connect,
    initialize_index,
    insert_canonical_face,
    insert_face_role,
)
from face_evolution.face_search import search_final_faces  # noqa: E402


def _face(face_index: int, radial: float, tangential: float, area: float) -> dict:
    return {
        "canonical_face_id": f"rev-000001:solid:0:face:{face_index}",
        "revision_id": "rev-000001",
        "feature_id": "n_final_cut",
        "solid_index": 0,
        "face_index": face_index,
        "surface_type": "plane",
        "area_mm2": area,
        "centroid_mm": [float(face_index), float(face_index), 0.0],
        "radius_mm": 200.0 + face_index,
        "theta_deg": 3.0 + face_index,
        "z_mm": 0.0,
        "normal_xyz": [0.0, 0.0, 1.0],
        "normal_cylindrical": {
            "radial": radial,
            "tangential": tangential,
            "axial": 0.0,
        },
        "bbox_mm": [0.0, 0.0, -1.0, 1.0, 1.0, 1.0],
    }


def _role(face: dict, suffix: str) -> dict:
    return {
        "role_id": f"feature:n_final_cut|{suffix}",
        "revision_id": "rev-000001",
        "namespace": "feature:n_final_cut",
        "feature_id": "n_final_cut",
        "role_key": suffix,
        "role_tag": face["face_index"] + 1000,
        "label_path": [100, 2, 1001, 2, 1002, 2, face["face_index"] + 1000],
        "created_revision": 1,
        "relation_kind": "modified",
        "source_key": suffix.split("/", 1)[0],
        "operation_id": "n_final_cut",
        "resolution_status": "resolved",
        "resolved_face_id": face["canonical_face_id"],
        "surface_type": face["surface_type"],
        "area_mm2": face["area_mm2"],
        "centroid_mm": face["centroid_mm"],
        "radius_mm": face["radius_mm"],
        "theta_deg": face["theta_deg"],
        "z_mm": face["z_mm"],
        "normal_xyz": face["normal_xyz"],
        "normal_cylindrical": face["normal_cylindrical"],
        "bbox_mm": face["bbox_mm"],
    }


def test_validation_requires_symmetric_same_working_side(tmp_path):
    database = tmp_path / "index.sqlite"
    connection = connect(database)
    initialize_index(connection)
    faces = [
        _face(1, -0.8, 0.6, 100.0),
        _face(2, -0.8, -0.6, 100.0),
        _face(3, 0.8, 0.6, 90.0),
        _face(4, 0.8, -0.6, 90.0),
    ]
    for face in faces:
        insert_canonical_face(connection, face)
        insert_face_role(connection, _role(face, f"tool_face_{face['face_index']}/mod/0"))
    connection.commit()
    connection.close()

    selection = [
        SelectionItem(
            canonical_face_id=f"rev-000001:solid:0:face:{index}",
            role_id=f"feature:n_final_cut|tool_face_{index}/mod/0",
        )
        for index in (1, 2)
    ]
    result = _validate_selection(database, selection)
    assert result["pair_count"] == 1
    assert result["radial_normal_sign"] == -1

    with pytest.raises(ValueError):
        _validate_selection(
            database,
            [
                *selection,
                SelectionItem(
                    canonical_face_id="rev-000001:solid:0:face:3",
                    role_id="feature:n_final_cut|tool_face_3/mod/0",
                ),
            ],
        )


def test_search_final_faces_is_paged(tmp_path):
    database = tmp_path / "index.sqlite"
    connection = connect(database)
    initialize_index(connection)
    for index in range(1, 6):
        insert_canonical_face(connection, _face(index, -0.7, 0.7, 100.0))
    connection.commit()
    connection.close()

    result = search_final_faces(
        database,
        surface_type="plane",
        radial_min=200,
        limit=2,
        offset=1,
    )
    assert result["total"] == 5
    assert result["returned"] == 2
    assert result["truncated"] is True

