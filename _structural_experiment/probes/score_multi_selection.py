"""Score the multi-family face-finding sweeps against frozen references."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "_structural_experiment" / "probes"))

from score_facefind_sweep import classify, load_correct, wilson  # noqa: E402


def _rate(rows: list[dict], predicate) -> dict:
    count = sum(1 for row in rows if predicate(row))
    total = len(rows)
    low, high = wilson(count, total)
    return {
        "count": count,
        "total": total,
        "fraction": round(count / total, 6) if total else None,
        "wilson95": [round(low, 6), round(high, 6)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sweep-root", type=Path,
        default=REPO / "_structural_experiment" / "output" / "sweep_multi",
    )
    parser.add_argument(
        "--reference-root", type=Path,
        default=REPO / "_structural_experiment" / "input" / "face_refs_multi",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tolerance", type=float, default=0.98)
    args = parser.parse_args()
    rows = []
    reference_kinds: dict[str, str] = {}
    for family_dir in sorted(args.sweep_root.glob("D*")):
        family = family_dir.name
        reference = args.reference_root / f"{family}.json"
        if not reference.is_file():
            continue
        reference_payload = json.loads(reference.read_text(encoding="utf-8"))
        reference_kind = str(
            reference_payload.get("reference_kind") or "unknown"
        )
        reference_kinds[family] = reference_kind
        correct = load_correct(reference)
        for path in sorted(family_dir.glob("run_*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            row = classify(payload, correct, args.tolerance)
            row["family"] = family
            row["reference_kind"] = reference_kind
            row["path"] = str(path)
            rows.append(row)
    valid = [row for row in rows if row["outcome"] != "transport_error"]
    submitted = [row for row in valid if row["outcome"] in ("correct", "wrong")]
    by_family = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row)
    summary = {
        "schema_version": "multi_family_selection_v1",
        "families": len(by_family),
        "runs": len(rows),
        "valid_runs": len(valid),
        "submitted_runs": len(submitted),
        "exact_correct": sum(1 for row in submitted if row["outcome"] == "correct"),
        "wrong_accepted": sum(1 for row in submitted if row["outcome"] == "wrong"),
        "not_submitted": sum(1 for row in valid if row["outcome"] == "not_submitted"),
        "transport_errors": sum(1 for row in rows if row["outcome"] == "transport_error"),
        "submission_rate": _rate(valid, lambda row: row["outcome"] in ("correct", "wrong")),
        "exact_accuracy_all_valid": _rate(valid, lambda row: row["outcome"] == "correct"),
        "exact_accuracy_when_submitted": _rate(submitted, lambda row: row["outcome"] == "correct"),
        "wrong_acceptance_rate": _rate(valid, lambda row: row["outcome"] == "wrong"),
        "reference_kinds": dict(sorted(reference_kinds.items())),
        "verified_families": sorted(
            family for family, kind in reference_kinds.items() if kind == "verified"
        ),
        "provisional_families": sorted(
            family for family, kind in reference_kinds.items() if kind != "verified"
        ),
        "by_family": {
            family: {
                "runs": len(family_rows),
                "submitted": sum(
                    1 for row in family_rows
                    if row["outcome"] in ("correct", "wrong")
                ),
                "exact_correct": sum(
                    1 for row in family_rows if row["outcome"] == "correct"
                ),
                "wrong_accepted": sum(
                    1 for row in family_rows if row["outcome"] == "wrong"
                ),
                "submission_rate": _rate(
                    family_rows,
                    lambda row: row["outcome"] in ("correct", "wrong"),
                ),
                "exact_accuracy_when_submitted": _rate(
                    family_rows,
                    lambda row: row["outcome"] == "correct",
                ),
            }
            for family, family_rows in sorted(by_family.items())
        },
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "rows": rows,
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
