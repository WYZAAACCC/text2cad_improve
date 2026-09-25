"""The load surface must reach the mesh before a solve may learn from it."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from seekflow_structural.pipeline.materialize import load_surface_coverage


def _case(face_indices, area):
    return SimpleNamespace(load_surface=SimpleNamespace(
        face_indices=list(face_indices), area_mm2_total=area
    ))


def _selection(path, rows):
    path.write_text(json.dumps({"per_face": rows}), encoding="utf-8")


def test_a_selected_face_that_mapped_no_node_reduces_the_measured_coverage(tmp_path):
    selection = tmp_path / "selected.json"
    _selection(selection, {
        "1": {"node_count": 2, "area_mm2": 50.0},
        "2": {"node_count": 0, "area_mm2": 50.0},
    })

    coverage = load_surface_coverage(selection, _case([1, 2], 100.0))

    assert coverage["complete"] is False
    assert coverage["mapped_face_count"] == 1
    assert coverage["missing_face_indices"] == [2]
    assert coverage["area_coverage_fraction"] == 0.5


def test_a_measured_sector_area_difference_is_not_a_missing_face(tmp_path):
    """A sector/half model can map 97.5% of CAD area without losing a face."""
    selection = tmp_path / "selected.json"
    _selection(selection, {
        "1": {"node_count": 10, "area_mm2": 48.73},
        "2": {"node_count": 12, "area_mm2": 48.73},
    })
    coverage = load_surface_coverage(selection, _case([1, 2], 100.0))
    assert coverage["missing_face_indices"] == []
    assert coverage["area_coverage_fraction"] == pytest.approx(0.9746, abs=1e-4)
    assert coverage["complete"] is True


def test_the_whole_selected_area_must_be_present(tmp_path):
    selection = tmp_path / "selected.json"
    _selection(selection, {
        "1": {"node_count": 2, "area_mm2": 50.0},
        "2": {"node_count": 3, "area_mm2": 50.0},
    })

    coverage = load_surface_coverage(selection, _case([1, 2], 100.0))

    assert coverage["complete"] is True
    assert coverage["area_coverage_fraction"] == 1.0
