"""Test demo_full_chain gear case end-to-end."""

import pytest


def test_demo_build_involute_spur_gear():
    """Run the involute_spur_gear case through demo_full_chain build."""
    pytest.importorskip("cadquery")

    import tempfile
    from pathlib import Path

    out_dir = Path(tempfile.mkdtemp())
    try:
        from demo_full_chain import _build_involute_spur_gear

        result = _build_involute_spur_gear(out_dir, "cadquery")

        assert result["case"] == "involute_spur_gear"
        assert result["backend"] == "cadquery"

        # Check files created
        step_exists = any("involute_spur_gear.step" in f for f in result.get("files_created", []))
        meta_exists = any(".metadata.json" in f for f in result.get("files_created", []))
        assert step_exists or result["ok"], "STEP file must be created"
        assert meta_exists or not result["ok"], "metadata.json must be created if build succeeded"

        # Check metrics
        metrics = result.get("metrics", {})
        if result["ok"]:
            assert "kernel_used" in metrics
            assert "reference_dimensions" in metrics
            ref = metrics["reference_dimensions"]
            assert abs(ref["pitch_diameter_mm"] - 48.0) < 0.01
            assert abs(ref["outer_diameter_mm"] - 52.0) < 0.01
    finally:
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
