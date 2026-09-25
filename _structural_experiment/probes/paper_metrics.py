"""Aggregate structural-agent experiment artifacts into paper metrics.

Artifact-only by design: this never calls a model, CAD kernel or solver. It
consumes frozen selection summaries/sweeps, feedback/revise replays, loop
results and the deterministic feature-graph experiment, then emits one JSON
report with proportions and Wilson 95% intervals.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

KINDS = (
    "mirror_vertex_pair",
    "fillet_family",
    "pattern_instances",
    "profile_contour",
    "feature_bundle",
)


def _wilson(successes: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    z = 1.96
    p = successes / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denom
    spread = z * math.sqrt(
        p * (1.0 - p) / total + z * z / (4.0 * total * total)
    ) / denom
    return [round(max(0.0, centre - spread), 6),
            round(min(1.0, centre + spread), 6)]


def _rate(successes: int, total: int) -> dict:
    return {
        "count": successes,
        "total": total,
        "fraction": round(successes / total, 6) if total else None,
        "wilson95": _wilson(successes, total),
    }


def _json_files(directory: Path) -> list[Path]:
    return sorted(
        path for path in Path(directory).glob("*.json")
        if path.name != "summary.json"
    )


def _family_from(path, payload: dict | None = None) -> str:
    candidates = [str(path)]
    if isinstance(payload, dict):
        for key in (
            "bundle", "sweep", "reference", "job_dir", "document",
            "source_revision",
        ):
            candidates.insert(0, str(payload.get(key) or ""))
    for text in candidates:
        for part in Path(text).parts:
            if part.startswith("D") and part[1:].isdigit():
                return part
            match = re.match(r"(D\d+)", part)
            if match:
                return match.group(1)
    return "unknown"


def _combine_selection_reports(*reports: dict) -> dict:
    valid = sum(int(report.get("valid_runs") or 0) for report in reports)
    submitted = sum(int(report.get("submitted_runs") or 0) for report in reports)
    exact = sum(int(report.get("exact_correct") or 0) for report in reports)
    wrong = sum(int(report.get("wrong_accepted") or 0) for report in reports)
    families = set()
    for report in reports:
        if isinstance(report.get("by_family"), list):
            families.update(
                str(row.get("family") or "") for row in report["by_family"]
            )
        elif isinstance(report.get("by_family"), dict):
            families.update(str(name) for name in report["by_family"])
    return {
        "valid_runs": valid,
        "submitted_runs": submitted,
        "exact_correct": exact,
        "wrong_accepted": wrong,
        "families": len({name for name in families if name and name != "unknown"}),
        "submission_rate": _rate(submitted, valid),
        "exact_accuracy_all_valid": _rate(exact, valid),
        "exact_accuracy_when_submitted": _rate(exact, submitted),
        "wrong_acceptance_rate": _rate(wrong, valid),
        "sources": [str(report.get("schema_version") or "selection") for report in reports],
    }


def selection_metrics_from_summaries(paths: list[Path]) -> dict:
    summaries = []
    for path in paths:
        if not Path(path).is_file():
            continue
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        family = _family_from(path, payload)
        summaries.append({
            "path": str(path),
            "family": family,
            "valid_runs": int(payload.get("valid_runs") or payload.get("runs") or 0),
            "submitted_runs": int(payload.get("submitted_runs") or 0),
            "exact_correct": int(payload.get("exact_correct") or 0),
            "wrong_accepted": int(payload.get("wrong_accepted") or 0),
            "not_submitted": int(payload.get("not_submitted") or 0),
            "transport_errors": int(payload.get("transport_errors") or 0),
            "median_calls": payload.get("calls_median"),
            "reference": payload.get("reference"),
        })
    valid = sum(row["valid_runs"] for row in summaries)
    submitted = sum(row["submitted_runs"] for row in summaries)
    exact = sum(row["exact_correct"] for row in summaries)
    wrong = sum(row["wrong_accepted"] for row in summaries)
    by_family = {}
    for row in summaries:
        by_family.setdefault(row["family"], []).append(row)
    family_rows = []
    for family, rows in sorted(by_family.items()):
        f_valid = sum(row["valid_runs"] for row in rows)
        f_submitted = sum(row["submitted_runs"] for row in rows)
        f_exact = sum(row["exact_correct"] for row in rows)
        f_wrong = sum(row["wrong_accepted"] for row in rows)
        family_rows.append({
            "family": family,
            "valid_runs": f_valid,
            "submitted_runs": f_submitted,
            "exact_correct": f_exact,
            "wrong_accepted": f_wrong,
            "exact_accuracy_all_valid": _rate(f_exact, f_valid),
            "exact_accuracy_when_submitted": _rate(f_exact, f_submitted),
            "wrong_acceptance_rate": _rate(f_wrong, f_valid),
        })
    return {
        "summaries": len(summaries),
        "families": len(by_family),
        "valid_runs": valid,
        "submitted_runs": submitted,
        "exact_correct": exact,
        "wrong_accepted": wrong,
        "submission_rate": _rate(submitted, valid),
        "exact_accuracy_all_valid": _rate(exact, valid),
        "exact_accuracy_when_submitted": _rate(exact, submitted),
        "wrong_acceptance_rate": _rate(wrong, valid),
        "by_family": family_rows,
        "runs_detail": summaries,
    }


def selection_metrics(directories: list[Path]) -> dict:
    runs = []
    for directory in directories:
        for path in _json_files(Path(directory)):
            payload = json.loads(path.read_text(encoding="utf-8"))
            selected = {int(value) for value in payload.get("selected") or []}
            runs.append({
                "path": str(path),
                "family": _family_from(path, payload),
                "submitted": bool(payload.get("submitted")),
                "calls": payload.get("calls"),
                "selected_count": len(selected),
                "selected": sorted(selected),
            })
    submitted = [row for row in runs if row["submitted"]]
    calls = [int(row["calls"]) for row in submitted if row["calls"] is not None]
    by_family = {}
    for row in runs:
        by_family.setdefault(row["family"], []).append(row)
    return {
        "runs": len(runs),
        "families": len(by_family),
        "submitted": len(submitted),
        "submission_rate": _rate(len(submitted), len(runs)),
        "median_calls": median(calls) if calls else None,
        "by_family": {
            family: {
                "runs": len(rows),
                "submitted": sum(1 for row in rows if row["submitted"]),
                "submission_rate": _rate(
                    sum(1 for row in rows if row["submitted"]), len(rows)
                ),
            }
            for family, rows in sorted(by_family.items())
        },
        "runs_detail": runs,
    }


def feedback_metrics(directory) -> dict:
    directories = (
        list(directory) if isinstance(directory, (list, tuple)) else [directory]
    )
    paths = []
    for item in directories:
        if item is not None and Path(item).is_dir():
            paths.extend(_json_files(Path(item)))
    if not paths:
        return {"available": False}
    records = []
    evidence_total = evidence_ok = 0
    mechanism_total = mechanism_ok = 0
    invalid_parameter = 0
    by_family: dict[str, list[dict]] = defaultdict(list)
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        findings = payload.get("findings") or []
        accepted = bool((payload.get("final") or {}).get("accepted"))
        record = {
            "path": str(path),
            "family": _family_from(path, payload),
            "model": payload.get("model"),
            "calls": payload.get("calls"),
            "accepted": accepted,
            "findings": len(findings),
            "with_change": sum(
                1 for finding in findings if finding.get("change")
            ),
            "exhausted": bool(payload.get("exhausted")),
        }
        for finding in findings:
            for comparison in finding.get("consistency") or []:
                name = str(comparison.get("name") or "")
                relative = comparison.get("relative")
                if name.startswith("evidence."):
                    evidence_total += 1
                    if relative is not None and float(relative) <= 1e-4:
                        evidence_ok += 1
                if name.startswith("mechanism."):
                    mechanism_total += 1
                    if relative is not None and float(relative) <= 1e-4:
                        mechanism_ok += 1
                if name.startswith("change.parameter"):
                    invalid_parameter += not bool(comparison.get("ok", True))
        records.append(record)
        by_family[record["family"]].append(record)
    accepted = sum(row["accepted"] for row in records)
    calls = [int(row["calls"]) for row in records if row["calls"] is not None]
    return {
        "available": True,
        "runs": len(records),
        "families": len(by_family),
        "accepted": accepted,
        "acceptance_rate": _rate(accepted, len(records)),
        "median_calls": median(calls) if calls else None,
        "with_change": sum(row["with_change"] for row in records),
        "exhausted": sum(row["exhausted"] for row in records),
        "evidence_reread_rate": _rate(evidence_ok, evidence_total),
        "mechanism_hit_rate": _rate(mechanism_ok, mechanism_total),
        "invalid_change_parameter_count": invalid_parameter,
        "by_family": {
            family: {
                "runs": len(rows),
                "accepted": sum(1 for row in rows if row["accepted"]),
                "acceptance_rate": _rate(
                    sum(1 for row in rows if row["accepted"]), len(rows)
                ),
            }
            for family, rows in sorted(by_family.items())
        },
        "runs_detail": records,
    }


def _canonical_edit_parameter(path: str) -> str:
    parts = str(path).strip("/").split("/")
    if len(parts) == 4 and parts[:1] == ["nodes"] and parts[2] == "params":
        return f"{parts[1]}.{parts[3]}"
    if len(parts) == 6 and parts[:1] == ["nodes"] and parts[2] == "params" and parts[3] == "points":
        return f"{parts[1]}.points[{parts[4]}].{parts[5]}"
    if len(parts) == 2 and parts[0] == "params":
        return parts[1]
    return str(path)


def _patch_correct_for_revision(revision: dict) -> tuple[int, int, int]:
    findings = {
        str(finding.get("id")): finding
        for finding in revision.get("findings") or []
    }
    edits = list(revision.get("document_edits") or [])
    applied = list(revision.get("applied") or [])
    matched = 0
    for finding_id in applied:
        finding = findings.get(str(finding_id)) or {}
        change = finding.get("change") or {}
        expected_parameter = str(change.get("parameter") or "")
        expected_value = change.get("proposed_value")
        matching = [
            edit for edit in edits
            if _canonical_edit_parameter(str(edit.get("path") or "")) == expected_parameter
        ]
        if not matching:
            continue
        if expected_value is None or any(
            abs(float(edit.get("new_value", 0.0)) - float(expected_value)) <= 1e-9
            for edit in matching
        ):
            matched += 1
    return matched, len(applied), len(edits)


def revise_metrics(directory) -> dict:
    directories = (
        list(directory) if isinstance(directory, (list, tuple)) else [directory]
    )
    paths = []
    for item in directories:
        if item is not None and Path(item).is_dir():
            paths.extend(_json_files(Path(item)))
    if not paths:
        return {"available": False}
    records = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        edits = payload.get("document_edits") or []
        grounded = all(
            str(edit.get("path") or "").startswith("/nodes/") for edit in edits
        )
        records.append({
            "path": str(path),
            "family": _family_from(path, payload),
            "accepted": bool(payload.get("accepted", not payload.get("error"))),
            "error_code": str(payload.get("error_code") or ""),
            "refused": bool(payload.get("error_code") or payload.get("error")),
            "applied": list(payload.get("applied") or []),
            "skipped": list(payload.get("skipped") or []),
            "document_edits": edits,
            "edit_count": len(edits),
            "patch_grounded": grounded if edits else True,
            "no_op": bool(payload.get("applied") and not edits),
            "master_changes": list(payload.get("changed_from_master") or []),
        })
    applied_runs = [row for row in records if row["applied"]]
    return {
        "available": True,
        "runs": len(records),
        "accepted_runs": sum(1 for row in records if row["accepted"]),
        "refused_runs": sum(1 for row in records if row["refused"]),
        "refusal_rate": _rate(
            sum(1 for row in records if row["refused"]), len(records)
        ),
        "runs_with_applied": len(applied_runs),
        "applied_patch_runs": sum(
            1 for row in applied_runs if row["edit_count"] > 0
        ),
        "patch_grounded_runs": sum(1 for row in records if row["patch_grounded"]),
        "no_op_runs": sum(1 for row in records if row["no_op"]),
        "master_changed_runs": sum(
            1 for row in records if row["master_changes"]
        ),
        "total_document_edits": sum(row["edit_count"] for row in records),
        "error_codes": {
            code: sum(1 for row in records if row["error_code"] == code)
            for code in sorted({row["error_code"] for row in records if row["error_code"]})
        },
        "runs_detail": records,
    }


def _load_knowledge(path: Path) -> dict:
    sidecar = Path(path).with_name("knowledge.json")
    if not sidecar.is_file():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def loop_metrics(paths: list[Path]) -> dict:
    observations = []
    revisions = 0
    applied_findings = 0
    correct_patches = 0
    evaluated_patches = 0
    correct_document_patches = 0
    document_patch_findings = 0
    knowledge_statuses: dict[str, int] = defaultdict(int)
    knowledge_samples: dict[str, int] = defaultdict(int)
    entries = []
    inline_trusted = inline_refuted = 0
    lineages = set()
    loop_files = 0
    design_effects = []
    for path in paths:
        if not Path(path).is_file():
            continue
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        lineage = str(payload.get("lineage") or "unknown")
        lineages.add(lineage)
        loop_files += 1
        for revision in payload.get("revisions") or []:
            revisions += 1
            observations.extend(revision.get("observations") or [])
            matched, applied, edits = _patch_correct_for_revision(revision)
            correct_patches += matched
            evaluated_patches += applied
            if edits:
                correct_document_patches += matched
                document_patch_findings += applied
            applied_findings += applied
            if revision.get("design_effect"):
                design_effects.append(revision["design_effect"])
        knowledge = _load_knowledge(Path(path))
        inline = payload.get("knowledge") or {}
        if not knowledge.get("entries") and isinstance(inline, dict):
            for status, count in (inline.get("by_status") or {}).items():
                knowledge_statuses[str(status)] += int(count)
            inline_trusted += len(inline.get("trusted") or [])
            inline_refuted += len(inline.get("refuted") or [])
        for entry in knowledge.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "unknown")
            knowledge_statuses[status] += 1
            knowledge_samples[status] += len(entry.get("observations") or [])
            entries.append({**entry, "lineage": lineage})
    outcomes: dict[str, int] = defaultdict(int)
    for observation in observations:
        outcomes[str(observation.get("outcome") or "unknown")] += 1
    trusted = [entry for entry in entries if entry.get("status") == "trusted"]
    refuted = [entry for entry in entries if entry.get("status") == "refuted"]
    trusted_count = max(len(trusted), inline_trusted)
    refuted_count = max(len(refuted), inline_refuted)
    key_families: dict[tuple, set[str]] = defaultdict(set)
    for entry in entries:
        key = (
            str(entry.get("mechanism") or ""),
            str(entry.get("parameter") or ""),
            str(entry.get("direction") or ""),
        )
        key_families[key].add(str(entry.get("lineage") or "unknown"))
    return {
        "loops": loop_files,
        "lineages": sorted(lineages),
        "revisions": revisions,
        "prediction_observations": len(observations),
        "prediction_outcomes": dict(outcomes),
        "prediction_outcome_fractions": {
            key: round(count / len(observations), 6) if observations else None
            for key, count in sorted(outcomes.items())
        },
        "knowledge_statuses": dict(knowledge_statuses),
        "knowledge_observation_samples": dict(knowledge_samples),
        "trusted_rules": trusted_count,
        "refuted_rules": refuted_count,
        "trusted_rules_with_samples": sum(
            len(entry.get("observations") or []) > 0 for entry in trusted
        ) + (inline_trusted if inline_trusted and trusted_count > len(trusted) else 0),
        "refuted_rules_with_samples": sum(
            len(entry.get("observations") or []) > 0 for entry in refuted
        ) + (inline_refuted if inline_refuted and refuted_count > len(refuted) else 0),
        "rules_seen_in_multiple_families": sum(
            1 for families in key_families.values() if len(families) > 1
        ),
        "applied_findings": applied_findings,
        "patch_correctness": _rate(correct_patches, evaluated_patches),
        "document_patch_correctness": _rate(
            correct_document_patches, document_patch_findings
        ),
        "design_effect_checks": len(design_effects),
        "design_effect_target_changed": sum(
            1 for effect in design_effects
            if effect.get("target_changed") is True
        ),
        "observations": observations,
        "knowledge_entries": entries,
    }


def feature_graph_metrics(path: Path | None) -> dict:
    if path is None or not Path(path).is_file():
        return {"available": False}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["available"] = True
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-sweep", action="append", type=Path,
                        default=[])
    parser.add_argument("--selection-summary", action="append", type=Path,
                        default=[])
    parser.add_argument("--multi-selection-summary", type=Path)
    parser.add_argument("--design-effect-replay", type=Path)
    parser.add_argument("--feedback-replay", action="append", type=Path,
                        default=[])
    parser.add_argument("--revise-replay", action="append", type=Path,
                        default=[])
    parser.add_argument("--loop-result", action="append", type=Path,
                        default=[])
    parser.add_argument(
        "--feature-graph", type=Path,
        default=Path(__file__).resolve().parents[1] / "output" / "feature_graph_metrics.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    primary_selection = selection_metrics_from_summaries(
        args.selection_summary
    )
    multi_selection = (
        json.loads(args.multi_selection_summary.read_text(encoding="utf-8"))
        if args.multi_selection_summary
        and args.multi_selection_summary.is_file()
        else {"available": False}
    )
    report = {
        "schema_version": "structural_paper_metrics_v2",
        "selection": selection_metrics(args.selection_sweep),
        "selection_summary": primary_selection,
        "multi_selection": multi_selection,
        "selection_combined": _combine_selection_reports(
            primary_selection,
            multi_selection if multi_selection.get("available", True) else {},
        ),
        "feedback": feedback_metrics(args.feedback_replay),
        "revise": revise_metrics(args.revise_replay),
        "loop": loop_metrics(args.loop_result),
        "feature_graph": feature_graph_metrics(args.feature_graph),
        "design_effect_replay": (
            json.loads(args.design_effect_replay.read_text(encoding="utf-8"))
            if args.design_effect_replay and args.design_effect_replay.is_file()
            else {"available": False}
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(
        {key: value for key, value in report.items()
         if key not in ("selection", "selection_summary", "loop", "feature_graph")},
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
