"""Resolve the same persistent role IDs in two immutable revisions."""

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

from OCP.TopAbs import TopAbs_FACE  # noqa: E402

from seekflow_structural.core.pattern_solids import _open  # noqa: E402
from seekflow_structural.core.role_facts import face_facts  # noqa: E402


def _resolve_role(session, role_id: str):
    if "|" not in role_id:
        raise ValueError(f"invalid role id: {role_id}")
    namespace, role_key = role_id.split("|", 1)
    entry = session.label_index.get_existing("face_role", namespace, role_key)
    if entry is None or entry.retired_revision is not None:
        raise KeyError(role_id)
    label = entry.tag_path.resolve(session.main_label)
    feature_label = label.Father().Father()
    shape = session.get_current_role_result(feature_label, label.Tag())
    if shape is None or shape.ShapeType() != TopAbs_FACE:
        raise RuntimeError(f"role does not resolve to a face: {role_id}")
    return shape


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _verify_pair(old_facts: dict, new_facts: dict) -> dict:
    old_normal = old_facts.get("normal_xyz")
    new_normal = new_facts.get("normal_xyz")
    normal_dot = None
    if old_normal is not None and new_normal is not None:
        normal_dot = abs(_dot(old_normal, new_normal))
    old_area = float(old_facts["area_mm2"])
    new_area = float(new_facts["area_mm2"])
    area_relative_change = abs(new_area - old_area) / max(old_area, 1e-30)
    centroid_move = math.dist(
        old_facts["centroid_mm"], new_facts["centroid_mm"]
    )
    accepted = (
        old_facts["surface_type"] == new_facts["surface_type"]
        and area_relative_change <= 0.15
        and centroid_move <= 50.0
        and normal_dot is not None
        and normal_dot >= 0.98
    )
    return {
        "surface_type_old": old_facts["surface_type"],
        "surface_type_new": new_facts["surface_type"],
        "area_old_mm2": old_area,
        "area_new_mm2": new_area,
        "area_relative_change": area_relative_change,
        "centroid_move_mm": centroid_move,
        "normal_absolute_dot": normal_dot,
        "accepted": accepted,
    }


def verify(
    old_bundle: Path,
    new_bundle: Path,
    selection_file: Path,
) -> dict:
    payload = json.loads(selection_file.read_text(encoding="utf-8"))
    role_ids = [item["role_id"] for item in payload["final"]["selection"]]
    old_session = _open(old_bundle.resolve())
    new_session = _open(new_bundle.resolve())
    results = []
    try:
        for role_id in role_ids:
            try:
                old_facts = face_facts(_resolve_role(old_session, role_id))
                new_facts = face_facts(_resolve_role(new_session, role_id))
                comparison = _verify_pair(old_facts, new_facts)
                results.append(
                    {
                        "role_id": role_id,
                        "old_resolved": True,
                        "new_resolved": True,
                        **comparison,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "role_id": role_id,
                        "old_resolved": False,
                        "new_resolved": False,
                        "accepted": False,
                        "error": str(exc),
                    }
                )
    finally:
        old_session.close()
        new_session.close()
    accepted = bool(results) and all(row["accepted"] for row in results)
    return {
        "schema_version": "cross_revision_role_verification_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "old_bundle": str(old_bundle.resolve()),
        "new_bundle": str(new_bundle.resolve()),
        "selection_file": str(selection_file.resolve()),
        "accepted": accepted,
        "role_count": len(results),
        "accepted_role_count": sum(1 for row in results if row["accepted"]),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old_bundle", type=Path)
    parser.add_argument("new_bundle", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = verify(args.old_bundle, args.new_bundle, args.selection)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

