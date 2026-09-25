"""Compare a baseline solve with a rigidly tilted copy of the same case."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _first_metrics(loop_result: Path) -> tuple[dict, dict, dict]:
    payload = json.loads(loop_result.read_text(encoding="utf-8"))
    revisions = payload.get("revisions") or []
    if not revisions:
        raise ValueError(f"{loop_result} has no revisions")
    revision = revisions[0]
    metrics = revision.get("metrics") or {}
    job = Path(revision.get("workspace_root") or "")
    case_path = None
    for parent in [job, *job.parents]:
        candidate = parent / "jobs" / "jobs"
        if candidate.is_dir():
            jobs = list(candidate.glob("*/case.json"))
            if jobs:
                case_path = jobs[0]
                break
    case = json.loads(case_path.read_text(encoding="utf-8")) if case_path else {}
    return metrics, case, revision


def _metric(metrics: dict, path: list[str]):
    value = metrics
    for key in path:
        value = (value or {}).get(key)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("tilted", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base, base_case, base_rev = _first_metrics(args.baseline)
    tilt, tilt_case, tilt_rev = _first_metrics(args.tilted)
    comparison = {}
    for name, path in (
        ("max_von_mises_mpa", ["stress", "max_von_mises_mpa"]),
        ("max_displacement_mm", ["displacement", "max_mm"]),
        ("max_von_mises_radius_mm", ["stress", "max_radius_mm"]),
        ("applied_resultant_n", ["load_audit", "applied_resultant_n"]),
    ):
        left = _metric(base, path)
        right = _metric(tilt, path)
        relative = None
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            relative = (float(right) - float(left)) / max(abs(float(left)), 1e-12)
        comparison[name] = {
            "baseline": left,
            "tilted": right,
            "relative_difference": relative,
        }
    report = {
        "schema_version": "non_global_z_solver_comparison_v1",
        "baseline_loop": str(args.baseline),
        "tilted_loop": str(args.tilted),
        "baseline_frame": ((base_case.get("model") or {}).get("frame") or {}),
        "tilted_frame": ((tilt_case.get("model") or {}).get("frame") or {}),
        "baseline_revision": base_rev.get("revision"),
        "tilted_revision": tilt_rev.get("revision"),
        "comparison": comparison,
        "limits": (base_rev.get("limits") or []) + (tilt_rev.get("limits") or []),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
