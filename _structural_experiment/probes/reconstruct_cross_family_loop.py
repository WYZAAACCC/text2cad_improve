"""Reconstruct prediction observations from stored cross-family job pairs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.pipeline import iterate  # noqa: E402
from seekflow_structural.tools import knowledge, results  # noqa: E402


def _metrics(job: Path) -> dict:
    return json.loads(
        (job / "solve" / "structural_metrics.json").read_text(encoding="utf-8")
    )


def _findings(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("findings") or [])


def _floors(job: Path) -> dict:
    payload = results.mesh_noise_floor(job)
    return {
        metric: entry["relative_spread"]
        for metric, entry in (payload.get("floors") or {}).items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", required=True)
    parser.add_argument("--job", action="append", type=Path, required=True)
    parser.add_argument("--feedback", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.job) != len(args.feedback) + 1:
        raise SystemExit("one more job than feedback file is required")
    base = knowledge.KnowledgeBase()
    revisions = []
    for index, feedback_path in enumerate(args.feedback):
        before_job = args.job[index]
        after_job = args.job[index + 1]
        before = _metrics(before_job)
        after = _metrics(after_job)
        findings = _findings(feedback_path)
        observations = iterate.score_applied(
            findings,
            before,
            after,
            revision=f"rev-{index + 2:06d}",
            base=base,
            noise_floors=_floors(after_job) | _floors(before_job),
        )
        revisions.append({
            "revision": f"rev-{index + 2:06d}",
            "workspace_root": str(after_job),
            "metrics": after,
            "findings": findings,
            "applied": [finding.get("id") for finding in findings],
            "observations": observations,
            "noise_floors": _floors(after_job),
            "document_edits": [],
        })
    payload = {
        "schema_version": "structural_iteration_v1_reconstructed",
        "lineage": args.lineage,
        "knowledge": base.summary(),
        "limits": [
            "Reconstructed from completed stored solves after a pre-fix revise "
            "failure exited the original loop before loop_result.json was written."
        ],
        "revisions": revisions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: payload[key] for key in ("lineage", "knowledge")}, ensure_ascii=False, indent=2))
    for revision in revisions:
        print(revision["revision"], revision["observations"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
