"""Replay the pre-solve STEP effect check on a completed loop revision pair."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.core.mesh_profile import build_profile  # noqa: E402
from seekflow_structural.pipeline.design_effect import (  # noqa: E402
    compare_design,
    surface_cells,
)


def _step(root: Path, revision: str) -> Path:
    matches = list(root.glob(f"**/{revision}/**/model.step"))
    if not matches:
        raise FileNotFoundError(f"no model.step under {root} for {revision}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("loop_result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bands", type=int, default=12)
    args = parser.parse_args()
    payload = json.loads(args.loop_result.read_text(encoding="utf-8"))
    revisions = payload.get("revisions") or []
    if len(revisions) < 2:
        raise SystemExit("the loop result has fewer than two revisions")
    first, second = revisions[0], revisions[1]
    findings = [
        finding for finding in (first.get("findings") or [])
        if str(finding.get("id")) in set(first.get("applied") or [])
    ]
    root = args.loop_result.parent
    before_step = _step(root, str(first.get("revision")))
    after_step = _step(root, str(second.get("revision")))
    before = build_profile(before_step, args.bands)
    after = build_profile(after_step, args.bands)
    before["surface_cells"] = surface_cells(before)
    after["surface_cells"] = surface_cells(after)
    document = json.loads(
        (root / "revisions" / str(second.get("revision")) / "document.json")
        .read_text(encoding="utf-8")
    )
    effect = compare_design(before, after, findings, document)
    report = {
        "schema_version": "design_effect_replay_v1",
        "loop_result": str(args.loop_result),
        "before_revision": first.get("revision"),
        "after_revision": second.get("revision"),
        "findings": findings,
        "effect": effect,
        "before_step": str(before_step),
        "after_step": str(after_step),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "before_revision": report["before_revision"],
        "after_revision": report["after_revision"],
        "target_changed": effect.get("target_changed"),
        "global_changed": effect.get("global_changed"),
        "changed_cell_count": effect.get("changed_cell_count"),
        "targets": effect.get("targets"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
