"""Map a selected face set onto a rigidly rotated copy of the same solid."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.tools import geometry  # noqa: E402


def _rotate_x(point, angle_deg):
    angle = math.radians(angle_deg)
    c, s = math.cos(angle), math.sin(angle)
    x, y, z = point
    return [x, c * y - s * z, s * y + c * z]


def _distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _rows(bundle, feature, solid_index=0):
    session = geometry.open_bundle(Path(bundle))
    try:
        return geometry.face_rows(session, feature, solid_index)
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_bundle", type=Path)
    parser.add_argument("baseline_case", type=Path)
    parser.add_argument("tilted_bundle", type=Path)
    parser.add_argument("tilted_feature")
    parser.add_argument("--angle-deg", type=float, required=True)
    parser.add_argument("--axis", choices=["x", "y", "z"], default="x")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = json.loads(args.baseline_case.read_text(encoding="utf-8"))
    surface = case["load_surface"]
    baseline = _rows(args.baseline_bundle, surface["feature"], surface.get("solid_index", 0))
    tilted = _rows(args.tilted_bundle, args.tilted_feature, 0)
    mapped = []
    details = []
    for index in surface["face_indices"]:
        row = baseline[index]
        centroid = _rotate_x(row["centroid_mm"], args.angle_deg)
        normal = _rotate_x(row["normal_xyz"], args.angle_deg)
        candidates = []
        for candidate_index, candidate in enumerate(tilted):
            distance = _distance(centroid, candidate["centroid_mm"])
            normal_dot = sum(
                normal[i] * candidate["normal_xyz"][i] for i in range(3)
            )
            area_error = abs(float(candidate["area_mm2"]) - float(row["area_mm2"])) / max(
                float(row["area_mm2"]), 1e-12
            )
            score = distance + 10.0 * max(0.0, 1.0 - normal_dot) + 10.0 * area_error
            candidates.append((score, candidate_index, distance, normal_dot, area_error))
        score, candidate_index, distance, normal_dot, area_error = min(candidates)
        if distance > 1e-3 or normal_dot < 0.999 or area_error > 1e-4:
            raise SystemExit(
                f"no rigid match for baseline face {index}: "
                f"candidate {candidate_index}, distance={distance}, "
                f"normal_dot={normal_dot}, area_error={area_error}"
            )
        mapped.append(candidate_index)
        details.append({
            "baseline_face": index,
            "tilted_face": candidate_index,
            "distance_mm": distance,
            "normal_dot": normal_dot,
            "area_relative_error": area_error,
        })
    if len(set(mapped)) != len(mapped):
        raise SystemExit(f"mapping is not one-to-one: {mapped}")
    payload = {
        "domain": case["domain"],
        "mesh_plan": case["mesh"],
        "face_selection": {
            **surface,
            "feature": args.tilted_feature,
            "solid_index": 0,
            "face_indices": mapped,
            "written": None,
        },
        "mapping": details,
    }
    payload["face_selection"].pop("written", None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"mapped": mapped, "details": details}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
