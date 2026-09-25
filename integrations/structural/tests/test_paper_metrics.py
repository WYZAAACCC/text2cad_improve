"""The paper metric aggregator must count artifacts, not infer success."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "_structural_experiment" / "probes"))

import paper_metrics  # noqa: E402


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_selection_summaries_aggregate_families_and_intervals(tmp_path):
    first = _write(tmp_path / "d27_summary.json", {
        "valid_runs": 25, "submitted_runs": 25, "exact_correct": 24,
        "wrong_accepted": 1, "runs": 25,
        "reference": "D27_reference.json",
    })
    second = _write(tmp_path / "d19_summary.json", {
        "valid_runs": 3, "submitted_runs": 3, "exact_correct": 3,
        "wrong_accepted": 0, "runs": 3,
        "reference": "D19_reference.json",
    })
    report = paper_metrics.selection_metrics_from_summaries([first, second])
    assert report["valid_runs"] == 28
    assert report["exact_correct"] == 27
    assert report["wrong_accepted"] == 1
    assert report["exact_accuracy_all_valid"]["wilson95"] is not None
    assert {row["family"] for row in report["by_family"]} == {"D27", "D19"}


def test_feedback_metrics_distinguish_evidence_from_mechanism(tmp_path):
    _write(tmp_path / "run1.json", {
        "final": {"accepted": True},
        "findings": [{
            "change": {"parameter": "x.radius_mm"},
            "consistency": [
                {"name": "evidence.s_hoop", "relative": 0.0, "ok": True},
                {"name": "mechanism.hoop_driven", "relative": 0.2, "ok": False},
                {"name": "change.parameter", "ok": False},
            ],
        }],
        "job_dir": r"F:/run/D27-rev-000001",
    })
    report = paper_metrics.feedback_metrics(tmp_path)
    assert report["evidence_reread_rate"]["fraction"] == 1.0
    assert report["mechanism_hit_rate"]["fraction"] == 0.0
    assert report["invalid_change_parameter_count"] == 1
    assert report["families"] == 1


def test_revision_patch_correctness_uses_the_named_parameter():
    revision = {
        "findings": [{"id": "F1", "change": {
            "parameter": "disc_poly.points[1].y_mm", "proposed_value": 41.0,
        }}],
        "applied": ["F1"],
        "document_edits": [{
            "path": "/nodes/disc_poly/params/points/1/y_mm",
            "new_value": 41.0,
        }],
    }
    matched, applied, edits = paper_metrics._patch_correct_for_revision(revision)
    assert (matched, applied, edits) == (1, 1, 1)


def test_loop_metrics_loads_rule_observations_from_the_sidecar(tmp_path):
    root = tmp_path / "loop"
    root.mkdir()
    loop_path = _write(root / "loop_result.json", {
        "lineage": "D27",
        "revisions": [{
            "revision": "rev-000002",
            "observations": [{"outcome": "confirmed"}],
            "findings": [],
            "applied": [],
            "document_edits": [],
        }],
    })
    _write(root / "knowledge.json", {
        "entries": [{
            "status": "trusted", "mechanism": "hoop_driven",
            "parameter": "rim_half_thickness_mm", "direction": "decrease",
            "observations": [{"outcome": "confirmed"}],
        }],
    })
    report = paper_metrics.loop_metrics([loop_path])
    assert report["prediction_outcomes"] == {"confirmed": 1}
    assert report["trusted_rules"] == 1
    assert report["trusted_rules_with_samples"] == 1


def test_combined_selection_adds_frozen_and_multi_family_runs():
    primary = {
        "valid_runs": 28, "submitted_runs": 28, "exact_correct": 28,
        "wrong_accepted": 0, "by_family": [{"family": "D27"}, {"family": "D19"}],
    }
    multi = {
        "valid_runs": 23, "submitted_runs": 23, "exact_correct": 23,
        "wrong_accepted": 0, "by_family": {"D15": {}, "D27": {}},
    }
    combined = paper_metrics._combine_selection_reports(primary, multi)
    assert combined["valid_runs"] == 51
    assert combined["exact_correct"] == 51
    assert combined["wrong_accepted"] == 0
    assert combined["families"] == 3


def test_revise_metrics_counts_a_fail_closed_refusal(tmp_path):
    _write(tmp_path / "refusal.json", {
        "accepted": False,
        "error_code": "revision_not_reported",
        "error": "inconsistent finding",
        "applied": [], "skipped": [], "document_edits": [],
        "changed_from_master": [],
    })
    report = paper_metrics.revise_metrics(tmp_path)
    assert report["runs"] == 1
    assert report["refused_runs"] == 1
    assert report["accepted_runs"] == 0
    assert report["error_codes"]["revision_not_reported"] == 1
    assert report["master_changed_runs"] == 0


def test_feedback_metrics_accept_multiple_replay_directories(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory, accepted, family in (
        (first, True, "D27-rev-000001"),
        (second, False, "D19-rev-000001"),
    ):
        _write(directory / "run.json", {
            "final": {"accepted": accepted},
            "job_dir": f"F:/jobs/{family}",
            "findings": [],
        })
    report = paper_metrics.feedback_metrics([first, second])
    assert report["runs"] == 2
    assert report["accepted"] == 1
    assert report["families"] == 2
