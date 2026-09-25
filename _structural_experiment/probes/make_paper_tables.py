"""Render the frozen paper metrics JSON into Markdown tables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * float(value):.1f}%"


def _interval(row) -> str:
    interval = (row or {}).get("wilson95")
    if not interval:
        return ""
    return f"[{interval[0]:.3f}, {interval[1]:.3f}]"


def render(report: dict) -> str:
    lines = ["# Structural-agent paper metrics", ""]
    selection = report.get("selection_combined") or report.get("selection_summary") or {}
    lines += [
        "## Selection benchmark",
        "",
        "| Runs | Families | Exact | Wrong accepted | Submission | Exact 95% CI |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {selection.get('valid_runs')} | {selection.get('families')} | "
            f"{selection.get('exact_correct')} | {selection.get('wrong_accepted')} | "
            f"{_pct((selection.get('submission_rate') or {}).get('fraction'))} | "
            f"{_interval(selection.get('exact_accuracy_all_valid'))} |"
        ),
        "",
    ]
    graph = report.get("feature_graph") or {}
    coverage = graph.get("coverage") or {}
    lines += [
        "## Feature dependency coverage",
        "",
        "| Family coverage relation | Present | Missing |",
        "|---|---:|---|",
    ]
    for kind, row in coverage.items():
        lines.append(
            f"| {kind} | {row.get('present_families')} | "
            f"{', '.join(row.get('missing_families') or []) or 'none'} |"
        )
    lines += ["", "## Feedback and repair", "",
              "| Stage | Accepted | Evidence | Mechanism | Grounded patches |",
              "|---|---:|---:|---:|---:|"]
    feedback = report.get("feedback") or {}
    revise = report.get("revise") or {}
    lines.append(
        f"| feedback | {_pct((feedback.get('acceptance_rate') or {}).get('fraction'))} | "
        f"{_pct((feedback.get('evidence_reread_rate') or {}).get('fraction'))} | "
        f"{_pct((feedback.get('mechanism_hit_rate') or {}).get('fraction'))} | n/a |"
    )
    lines.append(
        f"| revise | {revise.get('accepted_runs')}/{revise.get('runs')} | n/a | n/a | "
        f"{revise.get('applied_patch_runs')}/{revise.get('runs_with_applied')} |"
    )
    lines += ["", "## Prediction and knowledge", "",
              "| Prediction outcome | Count |", "|---|---:|"]
    loop = report.get("loop") or {}
    for outcome, count in sorted((loop.get("prediction_outcomes") or {}).items()):
        lines.append(f"| {outcome} | {count} |")
    lines += ["", "## Pre-solve solid effect replay", "",
              "| Before | After | Target changed | Local min r (mm) | Local area (mm2) |",
              "|---|---|---:|---:|---:|"]
    replay = report.get("design_effect_replay") or {}
    effect = replay.get("effect") or {}
    target = (effect.get("targets") or [{}])[0]
    lines.append(
        f"| {replay.get('before_revision')} | {replay.get('after_revision')} | "
        f"{effect.get('target_changed')} | "
        f"{target.get('before_min_r_mm')} -> {target.get('after_min_r_mm')} | "
        f"{target.get('before_area_mm2')} -> {target.get('after_area_mm2')} |"
    )
    lines += [
        "",
        "## Limits stated with the numbers",
        "",
        "- D19/D27 use verified references; the additional families in the multi-family batch use deterministic measured oracles.",
        "- Feedback and revise replay evidence is concentrated on D27; cross-family loop evidence is reported separately when available.",
        "- Trusted/refuted knowledge rules are only reported when their real observation count reaches the promotion rule.",
        "- Non-global-Z transform and mapping contracts are unit-tested; solver-level validation is reported separately when present.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    args.output.write_text(render(report), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
