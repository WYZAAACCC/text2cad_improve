"""Verify Agent role selections against the live CAD revision."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STRUCTURAL_ROOT = Path(__file__).resolve().parents[1]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from OCP.TopAbs import TopAbs_FACE  # noqa: E402

from seekflow_structural.core.pattern_solids import (  # noqa: E402
    _explode_solids,
    _feature_entry,
    _open,
    _solid_facts,
)
from seekflow_structural.core.role_facts import face_facts  # noqa: E402

from face_evolution.face_search import roles_for_face  # noqa: E402


def _parse_face_id(canonical_face_id: str) -> tuple[int, int]:
    parts = canonical_face_id.split(":solid:", 1)
    if len(parts) != 2 or ":face:" not in parts[1]:
        raise ValueError(f"invalid canonical face id: {canonical_face_id}")
    solid_text, face_text = parts[1].split(":face:", 1)
    return int(solid_text), int(face_text)


def _parse_role_id(role_id: str) -> tuple[str, str]:
    if "|" not in role_id:
        raise ValueError(f"invalid role id: {role_id}")
    return tuple(role_id.split("|", 1))


def _live_final_face(session, feature_id: str, solid_index: int, face_index: int):
    feature = _feature_entry(session, feature_id)
    shape = session.get_current_result_shape(
        feature.tag_path.resolve(session.main_label)
    )
    if shape is None:
        raise RuntimeError("final feature has no current shape")
    solids = _explode_solids(shape)
    _, faces = _solid_facts(solids[solid_index])
    return faces[face_index]


def _live_role_face(session, role_id: str):
    namespace, role_key = _parse_role_id(role_id)
    entry = session.label_index.get_existing("face_role", namespace, role_key)
    if entry is None or entry.retired_revision is not None:
        raise RuntimeError(f"face role is not active: {role_id}")
    role_label = entry.tag_path.resolve(session.main_label)
    feature_label = role_label.Father().Father()
    shape = session.get_current_role_result(feature_label, role_label.Tag())
    if shape is None or shape.ShapeType() != TopAbs_FACE:
        raise RuntimeError(f"role does not resolve to a live face: {role_id}")
    return shape


def verify(
    bundle: Path,
    database: Path,
    selection_file: Path,
    feature_id: str = "n_final_cut",
) -> dict:
    payload = json.loads(selection_file.read_text(encoding="utf-8"))
    final = payload["final"]
    if not final.get("accepted"):
        raise ValueError("agent selection was not accepted")
    selection = final["selection"]
    results = []
    session = _open(bundle)
    try:
        final_face_cache = {}
        for item in selection:
            canonical_face_id = item["canonical_face_id"]
            role_id = item["role_id"]
            solid_index, face_index = _parse_face_id(canonical_face_id)
            cache_key = (solid_index, face_index)
            if cache_key not in final_face_cache:
                final_face_cache[cache_key] = _live_final_face(
                    session, feature_id, solid_index, face_index
                )
            live_final = final_face_cache[cache_key]
            live_role = _live_role_face(session, role_id)
            same_shape = bool(live_final.IsSame(live_role))
            final_facts = face_facts(live_final)
            role_facts = face_facts(live_role)
            area_error = abs(
                final_facts["area_mm2"] - role_facts["area_mm2"]
            ) / max(final_facts["area_mm2"], role_facts["area_mm2"], 1e-30)
            centroid_error = sum(
                (
                    final_facts["centroid_mm"][axis]
                    - role_facts["centroid_mm"][axis]
                )
                ** 2
                for axis in range(3)
            ) ** 0.5
            database_roles = {
                row["role_id"]: row
                for row in roles_for_face(database, canonical_face_id)
            }
            indexed = database_roles.get(role_id)
            results.append(
                {
                    "canonical_face_id": canonical_face_id,
                    "role_id": role_id,
                    "role_resolves_to_face": same_shape,
                    "area_relative_error": area_error,
                    "centroid_error_mm": centroid_error,
                    "index_status": indexed["resolution_status"]
                    if indexed
                    else "missing",
                    "index_resolved_face_id": indexed["resolved_face_id"]
                    if indexed
                    else None,
                }
            )
    finally:
        session.close()
    accepted = all(
        row["role_resolves_to_face"]
        and row["area_relative_error"] <= 1e-9
        and row["centroid_error_mm"] <= 1e-6
        and row["index_status"] == "resolved"
        and row["index_resolved_face_id"] == row["canonical_face_id"]
        for row in results
    )
    return {
        "schema_version": "role_selection_verification_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bundle": str(bundle.resolve()),
        "database": str(database.resolve()),
        "selection_file": str(selection_file.resolve()),
        "accepted": accepted,
        "face_count": len(results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--feature", default="n_final_cut")
    args = parser.parse_args()
    result = verify(
        args.bundle, args.database, args.selection, args.feature
    )
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
