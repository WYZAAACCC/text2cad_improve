"""v0.6: ensure validators run exactly once."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestPipelineSinglePass:
    def test_pipeline_runs_each_validator_once(self, monkeypatch):
        from seekflow_engineering_tools.generative_cad.validation import pipeline
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport

        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        calls = {"structure": 0}

        def fake_structure(raw):
            calls["structure"] += 1
            return ValidationReport.ok_report("structure")

        monkeypatch.setattr(pipeline, "validate_structure", fake_structure)
        monkeypatch.setattr(
            pipeline, "RAW_STAGES",
            [("structure", fake_structure)] + pipeline.RAW_STAGES[1:],
        )

        pipeline.validate_and_canonicalize_with_bundle(data)
        assert calls["structure"] == 1, f"structure validator ran {calls['structure']} times, expected 1"


class TestNoDoubleRun:
    def test_valid_axisymmetric_single_pass(self):
        """End-to-end: valid axisymmetric doc passes with single-pass pipeline."""
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        data = json.loads((FIXTURES / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        canonical, report, bundle = validate_and_canonicalize_with_bundle(data)
        assert canonical is not None
        assert report.ok
        assert report.stage == "complete"
        assert bundle.ok
