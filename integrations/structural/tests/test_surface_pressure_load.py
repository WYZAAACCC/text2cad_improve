"""The surface-pressure load path: what it emits, and what its audit means.

The load was always a uniform pressure - the direction rule takes the inward
face normal and the force was already proportional to area - but it reached
the material as point forces at nodes. This path states it as a pressure and
lets ANSYS build the consistent load vector.

Two things need pinning. The emission has to name the right element and the
right local face, and the audit has to be honest about what it can no longer
tell you: because the pressure is *defined* as target over mapped area, the
integrated resultant equals the target by construction, so its near-zero
relative error stops being evidence of anything.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest


from seekflow_structural.core.element_face_map import read_mesh  # noqa: E402
from seekflow_structural.core.structural_apdl import (  # noqa: E402
    _contiguous_runs,
    _build_force_rows,
    emission_mode,
    materialize_intent,
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

MIDSIDE_PAIRS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))

# A tetrahedron sitting out at radius 200 with its {I, J, K} face in the plane
# x = 200 and its fourth corner further out. That face's outward normal points
# back towards the axis - the way a fir-tree slot flank is oriented - so the
# pressure acting into the element pulls radially outward, which is what a
# blade root does to the disc.
CORNERS = (
    (200.0, 0.0, 0.0),
    (200.0, 10.0, 0.0),
    (200.0, 0.0, 10.0),
    (210.0, 0.0, 0.0),
)

# A second tetrahedron whose {I, J, K} face has outward normal -y, so it is
# perpendicular to the first one's -x. Same 50 mm^2 area.
SECOND_CORNERS = (
    (0.0, 200.0, 0.0),
    (10.0, 200.0, 0.0),
    (0.0, 200.0, 10.0),
    (0.0, 210.0, 0.0),
)

# A third whose {I, J, K} face has outward normal +x - the first one's exact
# opposite, with the same area, which is the cancelling case.
MIRROR_CORNERS = (
    (500.0, 0.0, 0.0),
    (500.0, 10.0, 0.0),
    (500.0, 0.0, 10.0),
    (490.0, 0.0, 0.0),
)


def write_mesh(path: Path, corners=CORNERS) -> None:
    lines = ["/NOPR"]
    points = list(corners)
    for a, b in MIDSIDE_PAIRS:
        points.append(
            tuple((corners[a][i] + corners[b][i]) / 2.0 for i in range(3))
        )
    for index, xyz in enumerate(points, start=1):
        lines.append("N,%d,%.10g,%.10g,%.10g" % (index, *xyz))
    lines.append("EN,1,1,2,3,4,5,6,7,8")
    lines.append("EMORE,9,10")
    lines += ["TYPE,1", "MAT,1", "/GOPR"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def write_mesh_multi(path: Path, corner_sets) -> None:
    """One tetrahedron per corner set, numbered contiguously as APDL does."""
    lines = ["/NOPR"]
    node_id = 0
    for index, corners in enumerate(corner_sets, start=1):
        points = list(corners)
        for a, b in MIDSIDE_PAIRS:
            points.append(
                tuple((corners[a][i] + corners[b][i]) / 2.0 for i in range(3))
            )
        ids = []
        for xyz in points:
            node_id += 1
            ids.append(node_id)
            lines.append("N,%d,%.10g,%.10g,%.10g" % (node_id, *xyz))
        lines.append("EN,%d,%s" % (index, ",".join(str(v) for v in ids[:8])))
        lines.append("EMORE,%d,%d" % (ids[8], ids[9]))
    lines += ["TYPE,1", "MAT,1", "/GOPR"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def write_selection(path: Path, node_ids, normal, area) -> None:
    path.write_text(
        json.dumps(
            {
                "union_node_ids": list(node_ids),
                "per_face": {
                    "1": {
                        "node_ids": list(node_ids),
                        "normal_xyz": list(normal),
                        "area_mm2": area,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def intent_for(total_force: float, distribution: str,
               direction_rule: str = "flank_surface_normal") -> StructuralIntent:
    return StructuralIntent(
        status="ready_for_confirmation",
        case_id="pressure",
        bundle="bundle",
        mesh_inp="mesh.inp",
        selected_face_nodes="faces.json",
        rotation=RotationIntent(
            axis_origin_mm=[0, 0, 0], axis_direction=[0, 0, 1],
            rpm=15000, source="unit",
        ),
        temperature=TemperatureIntent(
            model="isothermal", reference_temperature_c=20.0,
            uniform_c=600.0, source="unit",
        ),
        material=MaterialIntent(
            name="unit", source="unit", poisson_ratio=0.3,
            density_t_mm3=8.24e-9,
            points=[
                MaterialPoint(temperature_c=20, young_mpa=205000,
                              alpha_per_c=1.18e-5, yield_mpa=1100),
                MaterialPoint(temperature_c=650, young_mpa=165000,
                              alpha_per_c=1.54e-5, yield_mpa=950),
            ],
        ),
        blade_load=BladeLoadIntent(
            model="equivalent_total_force",
            total_force_n_per_slot=total_force,
            direction_rule=direction_rule,
            distribution=distribution,
            source="unit",
        ),
        constraints=ConstraintIntent(
            cyclic_symmetry=True, axial_symmetry_z0=True,
            tangential_anchor=True, source="unit",
        ),
    )


def test_emission_mode_covers_every_legal_combination():
    assert emission_mode(intent_for(
        1000.0, "area_weighted_uniform_pressure")) == "surface_pressure"
    assert emission_mode(intent_for(
        1000.0, "area_weighted_equal_nodes")) == "nodal_force"
    assert emission_mode(intent_for(
        1000.0, "area_weighted_equal_nodes",
        "radial_outward_from_rotation_axis")) == "nodal_force"


def test_a_pressure_is_refused_on_the_radial_rule():
    """A pressure acts along the face normal; the radial rule does not.

    Silently treating them as the same thing would misplace the traction on
    every inclined face, so this is refused with a message that says which
    combination to use instead.
    """
    with pytest.raises(ValueError, match="cannot express"):
        emission_mode(intent_for(
            1000.0, "area_weighted_uniform_pressure",
            "radial_outward_from_rotation_axis"))


def test_the_pressure_is_the_target_over_the_mapped_area(tmp_path):
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    # The face's own area, as the CAD reports it.
    write_selection(selection, [1, 2, 3], [-1.0, 0.0, 0.0], 50.0)

    nodes = {nid: list(xyz) for nid, xyz in read_mesh(mesh)[0].items()}
    rows, audit = _build_force_rows(
        intent_for(1000.0, "area_weighted_uniform_pressure"),
        selection, nodes, mesh,
    )

    assert rows == [], "a pressure load emits no nodal forces"
    emission = audit["emission"]
    assert emission["mechanism"] == "surface_pressure"
    expected_area = 0.5 * 10.0 * 10.0
    assert audit["applied_resultant_magnitude_n"] == pytest.approx(
        1000.0, rel=1e-9
    )
    assert emission["pressure_mpa"] == pytest.approx(
        1000.0 / expected_area, rel=1e-9
    )
    assert emission["element_face_count"] == 1
    assert emission["element_faces"][0]["lkey"] == 1


def test_faces_that_do_not_share_a_normal_still_hit_the_target(tmp_path):
    """The bug this caught on D27: dividing by the area sum, not the resultant.

    A fir-tree slot's two flanks face different ways, so their area-weighted
    normals partly cancel. Dividing the target by the plain sum of areas gives
    a pressure whose resultant is short of the target - 21% short on D27 -
    and nothing about the pressure itself looks wrong.
    """
    mesh = tmp_path / "mesh.inp"
    # Two tetrahedra side by side, loaded on faces whose normals are 90 apart.
    write_mesh_multi(tmp_path / "mesh.inp", (CORNERS, SECOND_CORNERS))
    selection = tmp_path / "faces.json"
    selection.write_text(
        json.dumps(
            {
                "union_node_ids": [],
                "per_face": {
                    "1": {"node_ids": [1, 2, 3], "normal_xyz": [-1.0, 0.0, 0.0],
                          "area_mm2": 50.0},
                    "2": {"node_ids": [11, 12, 13],
                          "normal_xyz": [0.0, -1.0, 0.0], "area_mm2": 50.0},
                },
            }
        ),
        encoding="utf-8",
    )
    nodes = {nid: list(xyz) for nid, xyz in read_mesh(mesh)[0].items()}
    _, audit = _build_force_rows(
        intent_for(1000.0, "area_weighted_uniform_pressure"),
        selection, nodes, mesh,
    )
    emission = audit["emission"]
    # The two faces are perpendicular, so the resultant direction is the
    # diagonal: sqrt(50^2 + 50^2), not 100.
    assert emission["area_sum_mm2"] == pytest.approx(100.0)
    # The audit rounds to four decimals, so compare at that resolution.
    assert emission["resultant_direction_mm2"] == pytest.approx(
        math.hypot(50.0, 50.0), abs=1e-3
    )
    assert audit["applied_resultant_magnitude_n"] == pytest.approx(
        1000.0, rel=1e-9
    )


def test_faces_that_cancel_are_refused(tmp_path):
    """Two equal and opposite faces cannot be loaded by one pressure."""
    write_mesh_multi(tmp_path / "mesh.inp", (CORNERS, MIRROR_CORNERS))
    selection = tmp_path / "faces.json"
    selection.write_text(
        json.dumps(
            {
                "union_node_ids": [],
                "per_face": {
                    "1": {"node_ids": [1, 2, 3], "normal_xyz": [-1.0, 0.0, 0.0],
                          "area_mm2": 50.0},
                    "2": {"node_ids": [11, 12, 13],
                          "normal_xyz": [1.0, 0.0, 0.0], "area_mm2": 50.0},
                },
            }
        ),
        encoding="utf-8",
    )
    nodes = {nid: list(xyz) for nid, xyz in read_mesh(tmp_path / "mesh.inp")[0].items()}
    with pytest.raises(ValueError, match="cancel each other out"):
        _build_force_rows(
            intent_for(1000.0, "area_weighted_uniform_pressure"),
            selection, nodes, tmp_path / "mesh.inp",
        )


def test_the_audit_says_the_resultant_is_an_identity(tmp_path):
    """The one thing a reader is most likely to misread."""
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    write_selection(selection, [1, 2, 3], [-1.0, 0.0, 0.0], 50.0)
    nodes = {nid: list(xyz) for nid, xyz in read_mesh(mesh)[0].items()}

    _, audit = _build_force_rows(
        intent_for(1000.0, "area_weighted_uniform_pressure"),
        selection, nodes, mesh,
    )
    assert audit["resultant_relative_error"] < 1e-12
    assert any("identity by construction" in note for note in audit["limits"])
    assert audit["area_accounting_by_face"]["1"]["mapped_area_mm2"] == (
        pytest.approx(50.0)
    )


def test_the_load_audit_contract_keys_all_survive(tmp_path):
    """postprocess reads these by name; the pressure path must still emit them."""
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    write_selection(selection, [1, 2, 3], [-1.0, 0.0, 0.0], 50.0)
    nodes = {nid: list(xyz) for nid, xyz in read_mesh(mesh)[0].items()}

    _, audit = _build_force_rows(
        intent_for(1000.0, "area_weighted_uniform_pressure"),
        selection, nodes, mesh,
    )
    for key in (
        "target_force_n_per_slot",
        "applied_resultant_n",
        "resultant_relative_error",
        "applied_twist_moment_about_axis_nmm",
    ):
        assert key in audit, f"{key} is read by postprocess_structural"
    assert audit["target_force_n_per_slot"] == 1000.0


def test_faces_on_the_wrong_side_of_the_slot_are_caught(tmp_path):
    """With the sign automatic, this guard is about the selection geometry."""
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    # Normal flipped: the pressure then pushes the wrong way round the axis.
    write_selection(selection, [1, 2, 3], [1.0, 0.0, 0.0], 50.0)
    nodes = {nid: list(xyz) for nid, xyz in read_mesh(mesh)[0].items()}

    with pytest.raises(ValueError, match="produced no element face"):
        _build_force_rows(
            intent_for(1000.0, "area_weighted_uniform_pressure"),
            selection, nodes, mesh,
        )


def test_an_empty_mapping_never_reaches_the_solver(tmp_path):
    """A zero-area load would integrate to zero while the audit claimed 1000 N."""
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    write_selection(selection, [99], [-1.0, 0.0, 0.0], 50.0)
    nodes = {nid: list(xyz) for nid, xyz in read_mesh(mesh)[0].items()}

    with pytest.raises(ValueError, match="produced no element face"):
        _build_force_rows(
            intent_for(1000.0, "area_weighted_uniform_pressure"),
            selection, nodes, mesh,
        )


def test_materialize_emits_sfe_lines_and_names_the_loaded_surface(tmp_path):
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    write_selection(selection, [1, 2, 3], [-1.0, 0.0, 0.0], 50.0)
    job = tmp_path / "job"

    materialize_intent(
        intent_for(1000.0, "area_weighted_uniform_pressure"),
        mesh, selection, job, {"geometry": {}},
    )
    table = (job / "load_table.inp").read_text(encoding="ascii")
    sfe = [line for line in table.splitlines() if line.startswith("SFE,")]
    assert len(sfe) == 1
    assert sfe[0].startswith("SFE,1,1,PRES,0,")
    # No nodal forces at all on this path.
    assert not any(line.startswith("F,") for line in table.splitlines())
    # The loaded surface is named so POST1 can measure across it.
    assert "CM,LOADELM,ELEM" in table
    assert "CM,LOADNOD,NODE" in table
    # The temperature table is unaffected by which load path was taken.
    assert any(line.startswith("BF,") for line in table.splitlines())
    assert (job / "node_temperature.csv").is_file()


def test_the_nodal_path_still_emits_forces(tmp_path):
    """It is the control the pressure path is measured against."""
    mesh = tmp_path / "mesh.inp"
    write_mesh(mesh)
    selection = tmp_path / "faces.json"
    write_selection(selection, [1, 2, 3], [-1.0, 0.0, 0.0], 50.0)
    job = tmp_path / "job"

    materialize_intent(
        intent_for(1000.0, "area_weighted_equal_nodes"),
        mesh, selection, job, {"geometry": {}},
    )
    table = (job / "load_table.inp").read_text(encoding="ascii")
    assert any(line.startswith("F,") for line in table.splitlines())
    assert not any(line.startswith("SFE,") for line in table.splitlines())


def test_contiguous_runs_collapse_an_id_list():
    assert _contiguous_runs([1, 2, 3, 7, 8, 20]) == [
        (1, 3), (7, 8), (20, 20)
    ]
    assert _contiguous_runs([]) == []
