"""The pre-solve STEP check: a design edit must reach the final solid."""
from __future__ import annotations

from seekflow_structural.pipeline.design_effect import (
    compare_design,
    surface_cells,
    target_window,
)


def _profile(area: float = 10.0, face_count: int = 1):
    return {
        "faces": [
            {"r": 208.0, "theta": 12.0, "z": 0.0,
             "area": area, "full_revolution": False},
            {"r": 60.0, "theta": 180.0, "z": -38.0,
             "area": 22.0, "full_revolution": False},
        ],
        "r_min_mm": 60.0,
        "r_max_mm": 240.0,
        "z_min_mm": -38.0,
        "z_max_mm": 38.0,
        "total_volume_mm3": 1000.0,
        "total_surface_area_mm2": area + 22.0,
        "face_count": face_count,
    }


def _finding(parameter: str = "feat_holes_poly.points[0].x_mm"):
    return {
        "id": "F1",
        "radius_mm": 208.0,
        "z_mm": 0.0,
        "change": {"parameter": parameter, "relative_change": 0.1},
    }


def test_surface_cells_detect_a_local_final_solid_change():
    before = _profile()
    after = _profile(area=12.0)
    before["surface_cells"] = surface_cells(before)
    after["surface_cells"] = surface_cells(after)
    effect = compare_design(
        before,
        after,
        [_finding()],
        document={"nodes": [{
            "id": "feat_holes_poly", "op": "add_polyline",
            "component": "feat_holes",
            "params": {"points": [{"x_mm": -6.0, "y_mm": -6.0}]},
        }]},
    )
    assert effect["global_changed"] is True
    assert effect["target_changed"] is True
    assert effect["changed_cell_count"] == 1


def test_a_missing_target_is_a_measured_limitation_not_a_false_pass():
    before = _profile()
    after = _profile()
    before["surface_cells"] = surface_cells(before)
    after["surface_cells"] = surface_cells(after)
    effect = compare_design(before, after, [_finding()], document=None)
    assert effect["target_changed"] is False
    assert effect["target_reason"] in (
        "target_surface_area_changed", "target_window_unresolved",
        "no_comparable_target_window", "no_finding_target",
    )


def test_the_target_window_uses_the_measured_finding_location():
    window = target_window(_finding(), _profile(), document=None)
    assert window is not None
    assert window["r_min_mm"] <= 208.0 <= window["r_max_mm"]
    assert window["z_min_mm"] <= 0.0 <= window["z_max_mm"]


def test_a_mirrored_bore_vertex_target_uses_both_axial_ends():
    document = {"nodes": [
        {"id": "disc_sketch", "op": "create_2d_sketch",
         "component": "disc_body",
         "params": {"plane": "XZ"}},
        {"id": "disc_poly", "op": "add_polyline",
         "component": "disc_body",
         "inputs": [{"node": "disc_sketch", "output": "sketch"}],
         "params": {"points": [
             {"x_mm": 60.0, "y_mm": -38.0},
             {"x_mm": 160.0, "y_mm": 0.0},
             {"x_mm": 60.0, "y_mm": 38.0},
         ]}},
    ]}
    finding = {
        "id": "F1", "radius_mm": 60.0, "z_mm": 0.0,
        "change": {"parameter": "disc_poly.points[0].x_mm",
                   "relative_change": 0.05},
    }
    window = target_window(finding, _profile(), document)
    assert window is not None
    assert window["z_min_mm"] <= -38.0
    assert window["z_max_mm"] >= 38.0
    assert window["r_min_mm"] <= 60.0


def test_triangle_cells_keep_the_surface_radius_of_a_cylindrical_bore():
    from seekflow_structural.core.mesh_profile import _triangle_surface_cells

    points = {
        1: (60.0, 0.0, 0.0),
        2: (60.0, 10.0, 0.0),
        3: (60.0, 0.0, 10.0),
    }
    cells = _triangle_surface_cells(points, [(1, 2, 3)])
    assert cells
    assert cells[0]["r_mm"] > 50.0
    assert cells[0]["r_mm"] < 65.0
