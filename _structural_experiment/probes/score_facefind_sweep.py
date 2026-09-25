"""Score face-finding sweeps against the frozen D27 reference selection.

The sweep captures behavior. This turns it into the numbers the upgrade loop
acts on: exact-set accuracy, wrong-accepted rate, submission rate, calls to
decision, and the shape of each wrong set. It never calls the model and never
opens the CAD kernel, so a historical batch can be rescored after the harness
changes.

    python score_facefind_sweep.py <sweep-dir> [correct.json] [summary.json]
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics
import sys
from collections import Counter


REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CORRECT = REPO / "_structural_experiment" / "input" / "D27_face_submission_correct24.json"


def load_correct(path: pathlib.Path) -> set[int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    final = payload.get("final") or payload
    return {int(value) for value in final.get("selected_face_indices") or []}


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    z = 1.96
    p = successes / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denom
    spread = z * math.sqrt(
        p * (1.0 - p) / total + z * z / (4.0 * total * total)
    ) / denom
    return max(0.0, centre - spread), min(1.0, centre + spread)


def classify(run: dict, correct: set[int], tolerance: float) -> dict:
    selected = {int(value) for value in run.get("selected") or []}
    overlap = selected & correct
    union = selected | correct
    jaccard = len(overlap) / len(union) if union else 1.0
    if not run.get("ok"):
        outcome = "transport_error"
    elif not run.get("submitted"):
        outcome = "not_submitted"
    elif selected == correct:
        outcome = "correct"
    else:
        outcome = "wrong"
    return {
        "tag": str(run.get("tag")),
        "outcome": outcome,
        "calls": run.get("calls"),
        "wall_s": run.get("wall_s"),
        "selected_count": len(selected),
        "overlap_count": len(overlap),
        "missing_count": len(correct - selected),
        "extra_count": len(selected - correct),
        "jaccard": round(jaccard, 6),
        "near_exact": jaccard >= tolerance,
        "load_radius_mm": run.get("load_radius_mm"),
        "criterion_satisfied": run.get("criterion_satisfied"),
        "error": run.get("error"),
    }


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sweep = pathlib.Path(sys.argv[1]).resolve()
    correct_path = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else DEFAULT_CORRECT
    output_path = pathlib.Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
    tolerance = 0.98
    correct = load_correct(correct_path)
    runs = [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(sweep.glob("run_*.json"))]
    rows = [classify(run, correct, tolerance) for run in runs]
    valid = [row for row in rows if row["outcome"] != "transport_error"]
    submitted = [row for row in valid if row["outcome"] in ("correct", "wrong")]
    exact = [row for row in submitted if row["outcome"] == "correct"]
    wrong = [row for row in submitted if row["outcome"] == "wrong"]
    near = [row for row in submitted if row["near_exact"] and row["outcome"] == "wrong"]
    failed = [row for row in valid if row["outcome"] == "not_submitted"]

    def rate(items: list[dict], population: list[dict]) -> dict:
        n, total = len(items), len(population)
        low, high = wilson(n, total)
        return {
            "count": n,
            "total": total,
            "fraction": round(n / total, 6) if total else None,
            "wilson95": [round(low, 6), round(high, 6)],
        }

    calls = [int(row["calls"]) for row in submitted if row.get("calls") is not None]
    summary = {
        "sweep": str(sweep),
        "reference": str(correct_path),
        "reference_face_count": len(correct),
        "runs": len(rows),
        "transport_errors": sum(r["outcome"] == "transport_error" for r in rows),
        "valid_runs": len(valid),
        "submitted_runs": len(submitted),
        "exact_correct": len(exact),
        "wrong_accepted": len(wrong),
        "near_exact_wrong": len(near),
        "not_submitted": len(failed),
        "submission_rate": rate(submitted, valid),
        "exact_accuracy_all_valid": rate(exact, valid),
        "exact_accuracy_when_submitted": rate(exact, submitted),
        "wrong_acceptance_rate": rate(wrong, valid),
        "calls_median": statistics.median(calls) if calls else None,
        "calls_min": min(calls) if calls else None,
        "calls_max": max(calls) if calls else None,
        "selected_face_counts": dict(Counter(row["selected_count"] for row in submitted)),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "rows": rows,
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())