"""Test demo_full_chain gear case report schema and exit code."""

import json
import sys
import subprocess
from pathlib import Path
import pytest
import tempfile


def test_demo_full_chain_gear_cadquery():
    """Run --case involute_spur_gear --backend cadquery and verify report schema."""
    pytest.importorskip("cadquery")

    with tempfile.TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "demo_out"
        output_root.mkdir(exist_ok=True)
        models_dir = output_root / "models"
        models_dir.mkdir(exist_ok=True)

        from demo_full_chain import run_case_involute_spur_gear

        report = run_case_involute_spur_gear("cadquery", output_root)

        assert "overall_ok" in report
        assert report["case"] == "involute_spur_gear"
        assert report["backend"] == "cadquery"

        stages = report.get("stages", {})
        for s in ["validate_cad_ir", "normalize_primitives", "choose_backend",
                   "build", "inspect", "mechanical_validate"]:
            assert s in stages, f"Stage '{s}' missing from report"

        # Check report schema
        assert "files_created" in report
        assert "metrics" in report
        metrics = report.get("metrics", {})

        if report["overall_ok"]:
            assert "kernel_used" in metrics
            assert metrics["kernel_used"] in ("cq_gears", "cadquery_visual_fallback")
            ref = metrics.get("reference_dimensions", {})
            for key in ["pitch_diameter_mm", "base_diameter_mm",
                         "outer_diameter_mm", "root_diameter_mm"]:
                assert key in ref, f"reference_dimensions missing '{key}'"


def test_demo_full_chain_failure_exits_nonzero():
    """Test that an invalid case/backend causes non-zero exit."""
    import subprocess, sys, os

    script = Path(__file__).parent.parent / "demo_full_chain.py"
    r = subprocess.run(
        [sys.executable, str(script), "--case", "involute_spur_gear",
         "--backend", "solidworks2025"],
        capture_output=True, text=True, timeout=30,
        cwd=str(Path(__file__).parent.parent),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    # Without --allow-step-import, should fail
    assert r.returncode != 0, f"Should exit non-zero without --allow-step-import"
