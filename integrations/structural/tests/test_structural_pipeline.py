from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError


from seekflow_structural.pipeline.params import (  # noqa: E402
    ParamsIncomplete,
    physics_from_params,
)
from seekflow_structural.core.structural_apdl import (  # noqa: E402
    _build_force_rows,
    render_apdl,
)
from seekflow_structural.core.structural_intent_models import (  # noqa: E402
    BladeLoadIntent,
    ConstraintIntent,
    MaterialIntent,
    MaterialPoint,
    RotationIntent,
    StructuralIntent,
    TemperatureIntent,
)


def _intent(total_force_n: float) -> StructuralIntent:
    return StructuralIntent(
        status="ready_for_confirmation",
        case_id="unit",
        bundle="bundle",
        mesh_inp="mesh.inp",
        selected_face_nodes="faces.json",
        rotation=RotationIntent(
            axis_origin_mm=[0, 0, 0],
            axis_direction=[0, 0, 1],
            rpm=15000,
            source="unit",
        ),
        temperature=TemperatureIntent(
            model="radial_power_law",
            reference_temperature_c=20,
            bore_c=500,
            rim_c=650,
            bore_radius_mm=60,
            outer_radius_mm=250,
            exponent=1,
            source="unit",
        ),
        material=MaterialIntent(
            name="unit",
            source="unit",
            poisson_ratio=0.3,
            density_t_mm3=8.24e-9,
            points=[
                MaterialPoint(
                    temperature_c=20,
                    young_mpa=205000,
                    alpha_per_c=1.18e-5,
                    yield_mpa=1100,
                ),
                MaterialPoint(
                    temperature_c=650,
                    young_mpa=165000,
                    alpha_per_c=1.54e-5,
                    yield_mpa=950,
                ),
            ],
        ),
        blade_load=BladeLoadIntent(
            model="equivalent_total_force",
            total_force_n_per_slot=total_force_n,
            direction_rule="radial_outward_from_rotation_axis",
            distribution="area_weighted_equal_nodes",
            source="unit",
        ),
        constraints=ConstraintIntent(
            cyclic_symmetry=True,
            axial_symmetry_z0=True,
            tangential_anchor=True,
            source="unit",
        ),
    )


def test_a_missing_hard_input_is_a_refusal_not_a_guess():
    """The behaviour the retired intent agent's `_expected_status` encoded,
    now expressed where the values actually enter the chain."""
    with pytest.raises(ParamsIncomplete) as exc:
        physics_from_params(
            {
                "rotation": {"rpm": 1},
                "temperature": {"model": "isothermal"},
                # material absent
            },
            "unit",
        )
    assert "material" in exc.value.missing


def test_tangential_anchor_is_inside_the_cyclic_sector(tmp_path):
    mesh = tmp_path / "mesh.inp"
    mesh.write_text("", encoding="utf-8")
    load = tmp_path / "load_table.inp"
    load.write_text("", encoding="utf-8")
    deck = render_apdl(
        _intent(1000.0),
        mesh,
        tmp_path,
        load,
        {"geometry": {"sector_deg": 18.0, "theta_low_deg": 9.0,
                      "r_bore_mm": 66.0}},
    )
    text = deck.read_text(encoding="utf-8")
    assert "LOC,X,65.5,66.5" in text
    assert "LOC,Y,17,19" in text


def test_ready_intent_requires_load_section():
    with pytest.raises(ValidationError):
        StructuralIntent(
            status="ready",
            case_id="unit",
            bundle="bundle",
            mesh_inp="mesh.inp",
            selected_face_nodes="faces.json",
        )


def _selection_file(tmp_path: Path, per_face: dict) -> Path:
    path = tmp_path / "faces.json"
    path.write_text(json.dumps({"per_face": per_face}), encoding="utf-8")
    return path


def _box_faces():
    import cadquery as cq

    return [face.wrapped for face in cq.Workplane("XY").box(10, 10, 10).val().Faces()]


def _face_indices_by_normal(faces, target, tol: float = 1e-6) -> list[int]:
    from seekflow_structural.core.role_facts import face_facts

    indices = []
    for index, face in enumerate(faces):
        normal = face_facts(face).get("normal_xyz")
        if normal is None:
            continue
        if all(abs(normal[axis] - target[axis]) <= tol for axis in range(3)):
            indices.append(index)
    return indices



def test_shared_node_receives_force_from_both_faces(tmp_path: Path):
    """A node on two selected faces must accumulate, not be overwritten."""
    nodes = {1: [100.0, 0.0, 0.0], 2: [100.0, 10.0, 0.0]}
    selection = _selection_file(
        tmp_path,
        {"1": {"area_mm2": 1.0, "node_ids": [1, 2]},
         "2": {"area_mm2": 1.0, "node_ids": [1]}},
    )
    rows, audit = _build_force_rows(_intent(10000.0), selection, nodes)
    by_node = dict(rows)

    # Face 1 splits 5000 N over two nodes (2500 each); face 2 puts 5000 N on the
    # shared node. Node 1 must therefore carry more than node 2.
    assert by_node[1][0] > by_node[2][0]
    assert math.isclose(
        audit["applied_resultant_magnitude_n"], 10000.0, rel_tol=0, abs_tol=1e-8
    )




def test_face_normals_point_out_of_the_solid():
    """Regression: REVERSED faces used to report inward-pointing normals.

    A box centred on the origin must report an outward normal on every face,
    i.e. normal . centroid > 0. Without the orientation flip the three faces at
    negative coordinates report inward normals.
    """
    from seekflow_structural.core.role_facts import face_facts

    for index, face in enumerate(_box_faces()):
        facts = face_facts(face)
        normal = facts["normal_xyz"]
        centroid = facts["centroid_mm"]
        outward = sum(normal[axis] * centroid[axis] for axis in range(3))
        assert outward > 0, f"face {index} reports an inward normal"





def test_force_distribution_reproduces_resultant_and_zero_twist(tmp_path: Path):
    nodes = {
        1: [100.0, 10.0, 0.0],
        2: [200.0, 20.0, 20.0],
        3: [100.0, 10.0, 30.0],
        4: [200.0, 20.0, 40.0],
    }
    selection = {
        "per_face": {
            "1": {
                "area_mm2": 1.0,
                "node_ids": [1, 2],
            },
            "2": {
                "area_mm2": 3.0,
                "node_ids": [3, 4],
            },
        }
    }
    selection_path = tmp_path / "faces.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")

    _, audit = _build_force_rows(_intent(10000.0), selection_path, nodes)

    assert math.isclose(
        audit["applied_resultant_magnitude_n"], 10000.0, rel_tol=0, abs_tol=1e-8
    )
    assert abs(audit["applied_twist_moment_about_axis_nmm"]) < 1e-7
    assert audit["resultant_relative_error"] < 1e-12

