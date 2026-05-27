"""Test gear primitive metadata sidecar read/write."""

import json
import tempfile
from pathlib import Path


def test_write_and_read_metadata():
    from seekflow_engineering_tools.geometry_primitives.gears.metadata import (
        write_primitive_metadata,
        read_primitive_metadata,
    )

    with tempfile.TemporaryDirectory() as tmp:
        step_path = Path(tmp) / "test_gear.step"
        step_path.write_text("placeholder")

        metadata = {
            "kernel": "cq_gears",
            "is_standard_involute": True,
            "primitive": "involute_spur_gear",
            "reference_dimensions": {"pitch_diameter_mm": 48.0},
        }

        meta_path = write_primitive_metadata(step_path, metadata)
        assert meta_path.exists()
        assert meta_path.suffix == ".json"

        loaded = read_primitive_metadata(step_path)
        assert loaded is not None
        assert loaded["kernel"] == "cq_gears"
        assert loaded["is_standard_involute"] is True
        assert loaded["reference_dimensions"]["pitch_diameter_mm"] == 48.0


def test_write_metadata_with_validation():
    from seekflow_engineering_tools.geometry_primitives.gears.metadata import (
        write_primitive_metadata,
    )
    import json as _json

    with tempfile.TemporaryDirectory() as tmp:
        step_path = Path(tmp) / "gear.step"
        step_path.write_text("x")

        meta_path = write_primitive_metadata(step_path, {"kernel": "test"}, validation={"ok": True})
        content = _json.loads(meta_path.read_text(encoding="utf-8"))
        assert "validation" in content
        assert content["validation"]["ok"] is True


def test_read_missing_metadata_returns_none():
    from seekflow_engineering_tools.geometry_primitives.gears.metadata import (
        read_primitive_metadata,
    )

    result = read_primitive_metadata("/nonexistent/path/gear.step")
    assert result is None
