"""Build one paper metrics report from frozen structural artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "_structural_experiment" / "probes"))

import paper_metrics as pm  # noqa: E402


def _json(path: Path, fallback):
    return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else fallback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-summary", action="append", type=Path, default=[])
    parser.add_argument("--selection-sweep", action="append", type=Path, default=[])
    parser.add_argument("--multi-selection-summary", type=Path)
    parser.add_argument("--feedback-replay", action="append", type=Path, default=[])
    parser.add_argument("--revise-replay", action="append", type=Path, default=[])
    parser.add_argument("--loop-root", action="append", type=Path, default=[])
    parser.add_argument("--extra-loop-result", action="append", type=Path, default=[])
    parser.add_argument("--feature-graph", type=Path)
    parser.add_argument("--design-effect-replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    primary = pm.selection_metrics_from_summaries(args.selection_summary)
    multi = _json(args.multi_selection_summary, {"available": False})
    loops = []
    for root in args.loop_root:
        loops.extend(sorted(Path(root).glob("*/loop_result.json")))
    loops.extend(args.extra_loop_result)
    report = {
        "schema_version": "structural_paper_metrics_v5",
        "selection": pm.selection_metrics(args.selection_sweep),
        "selection_summary": primary,
        "multi_selection": multi,
        "selection_combined": pm._combine_selection_reports(
            primary, multi if multi.get("available", True) else {}
        ),
        "feedback": pm.feedback_metrics(args.feedback_replay),
        "revise": pm.revise_metrics(args.revise_replay),
        "loop": pm.loop_metrics(loops),
        "feature_graph": pm.feature_graph_metrics(args.feature_graph),
        "design_effect_replay": _json(
            args.design_effect_replay, {"available": False}
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
