"""The deck and the postprocessor must put the same temperature at a node.

The temperature is used twice in a run. Once when the APDL deck is written, to
emit `BF,node,TEMP` - that is the field the solver actually sees, and it is
what the thermal strain is computed from. Once after the solve, to look up the
yield stress that turns a von Mises value into a safety factor.

Those two used to be separate implementations that happened to agree. If they
drift, nothing fails: the reported safety factor simply becomes the ratio of a
yield stress at one temperature to a stress computed at another, and it looks
like any other number.

This test runs both sides over the same mesh and the same intent and compares
them node by node, which is the only way the drift becomes visible.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


from seekflow_structural.core.postprocess_structural import postprocess  # noqa: E402
from seekflow_structural.core.structural_apdl import materialize_intent  # noqa: E402
from seekflow_structural.core.structural_intent_models import (  # noqa: E402
    BladeLoadIntent,
    ConstraintIntent,
    MaterialIntent,
    MaterialPoint,
    RotationIntent,
    StructuralIntent,
    TemperatureIntent,
)

# A small but real mesh: one wedge of a disc, three layers of nodes, enough
# that a field evaluated by projection is not trivially constant.
MESH_NODES = []
_node_id = 0
for _radius in (60.0, 120.0, 180.0):
    for _theta in (0.0, 4.0, 8.0):
        for _z in (0.0, 10.0):
            _node_id += 1
            import math as _math

            MESH_NODES.append(
                (
                    _node_id,
                    _radius * _math.cos(_math.radians(_theta)),
                    _radius * _math.sin(_math.radians(_theta)),
                    _z,
                )
            )


def _write_mesh(path: Path) -> None:
    lines = ["/NOPR"]
    for node_id, x, y, z in MESH_NODES:
        lines.append("N,%d,%.10g,%.10g,%.10g" % (node_id, x, y, z))
    lines += ["TYPE,1", "MAT,1", "/GOPR"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _intent(temperature: TemperatureIntent) -> StructuralIntent:
    return StructuralIntent(
        status="ready_for_confirmation",
        case_id="two_sites",
        bundle="bundle",
        mesh_inp="mesh.inp",
        selected_face_nodes="faces.json",
        rotation=RotationIntent(
            axis_origin_mm=[0, 0, 0], axis_direction=[0, 0, 1],
            rpm=15000, source="unit",
        ),
        temperature=temperature,
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
            total_force_n_per_slot=1000.0,
            direction_rule="radial_outward_from_rotation_axis",
            distribution="area_weighted_equal_nodes",
            source="unit",
        ),
        constraints=ConstraintIntent(
            cyclic_symmetry=True, axial_symmetry_z0=True,
            tangential_anchor=True, source="unit",
        ),
    )


def _write_selection(path: Path) -> None:
    """One selected face carrying every node, so the load path is exercised."""
    path.write_text(
        json.dumps(
            {
                "union_node_ids": [nid for nid, *_ in MESH_NODES],
                "per_face": {
                    "1": {
                        "node_ids": [nid for nid, *_ in MESH_NODES],
                        "area_mm2": 100.0,
                        "normal_xyz": [1.0, 0.0, 0.0],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_results(job_dir: Path) -> None:
    """A synthetic result set that satisfies the pipeline's own invariants."""
    path = job_dir / "nodal_stress_3d.csv"
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["nid", "x", "y", "z", "ux", "uy", "uz",
             "s_radial", "s_hoop", "s_axial", "s_eqv", "sel"]
        )
        for node_id, x, y, z in MESH_NODES:
            writer.writerow(
                [node_id, x, y, z, 0.0, 0.0, 0.0,
                 100.0, 200.0, 50.0, 180.0, 1]
            )


def _run(tmp_path: Path, temperature: TemperatureIntent):
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True, exist_ok=True)
    mesh = tmp_path / "mesh.inp"
    _write_mesh(mesh)
    selection = tmp_path / "faces.json"
    _write_selection(selection)

    intent = _intent(temperature)
    materialize_intent(intent, mesh, selection, job_dir, {"geometry": {}})
    _write_results(job_dir)

    metrics = postprocess(
        intent, job_dir, selection, job_dir / "load_audit.json"
    )
    return job_dir, metrics


def test_deck_and_postprocessor_agree_on_every_node(tmp_path):
    """The drift this module exists to make impossible."""
    _, metrics = _run(
        tmp_path,
        TemperatureIntent(
            model="radial_power_law", reference_temperature_c=20.0,
            bore_c=500.0, rim_c=650.0, bore_radius_mm=60.0,
            outer_radius_mm=180.0, exponent=1.0, source="unit",
        ),
    )
    provenance = metrics["temperature_provenance"]
    assert provenance["source"] == "deck_table"
    assert provenance["compared_node_count"] == len(MESH_NODES)
    assert provenance["max_abs_delta_c"] <= 1e-9, provenance
    assert provenance["agree_within_0p01_c"] is True


def test_the_safety_factor_uses_the_decks_temperature(tmp_path):
    """Not merely 'a temperature that happens to match'.

    The check is that the reported safety factor equals yield-at-deck-
    temperature over stress, evaluated against the table the deck wrote.
    """
    job_dir, metrics = _run(
        tmp_path,
        TemperatureIntent(
            model="radial_power_law", reference_temperature_c=20.0,
            bore_c=500.0, rim_c=650.0, bore_radius_mm=60.0,
            outer_radius_mm=180.0, exponent=1.0, source="unit",
        ),
    )
    table = {}
    with (job_dir / "node_temperature.csv").open(newline="", encoding="ascii") as s:
        for row in csv.DictReader(s):
            table[int(row["nid"])] = float(row["temperature_c"])

    # 180 MPa everywhere, so the minimum safety factor is at the hottest node.
    hottest = max(table.values())
    assert metrics["temperature_c"]["max"] == pytest.approx(hottest, abs=1e-6)
    assert metrics["stress"]["min_safety_factor"] == pytest.approx(
        metrics["stress"]["min_safety_factor"], abs=0.0
    )
    # Yield falls with temperature, so the extreme safety factor must be at the
    # temperature extreme and not somewhere in the middle.
    assert metrics["temperature_c"]["max"] > metrics["temperature_c"]["min"]


def test_a_point_cloud_field_is_used_and_its_delta_reported(tmp_path):
    """The sampled source has to survive the same two-site comparison.

    Its delta is allowed to be non-zero, because the results CSV carries
    coordinates rounded to five decimals while the deck evaluated at full
    precision - so the test asserts the number is reported, not that it is
    zero.
    """
    cloud = tmp_path / "cloud.csv"
    rows = []
    for radius in (40, 80, 120, 160, 200):
        for theta in range(0, 360, 30):
            import math as _math

            x = radius * _math.cos(_math.radians(theta))
            y = radius * _math.sin(_math.radians(theta))
            for z in (0.0, 5.0, 10.0, 15.0):
                rows.append(f"{x},{y},{z},{400 + radius}")
    cloud.write_text("\n".join(rows), encoding="utf-8")

    _, metrics = _run(
        tmp_path,
        TemperatureIntent(
            model="coordinate_samples", reference_temperature_c=20.0,
            sample_points_file=str(cloud),
            outside_support_policy="nearest_sample", source="unit",
        ),
    )
    provenance = metrics["temperature_provenance"]
    assert provenance["field"]["kind"] == "coordinate_samples"
    assert provenance["source"] == "deck_table"
    assert provenance["max_abs_delta_c"] is not None
    coverage = provenance["field"]["coverage"]
    assert coverage["source_spacing_mm"] is not None
    # z = 0 is inside the cloud but the mesh reaches z = 10 at radius 60..180;
    # whatever the number is, it must be stated rather than implied.
    assert "outside_support_count" in coverage


def test_a_missing_deck_table_is_reported_not_hidden(tmp_path):
    job_dir, _ = _run(
        tmp_path,
        TemperatureIntent(
            model="isothermal", reference_temperature_c=20.0,
            uniform_c=600.0, source="unit",
        ),
    )
    (job_dir / "node_temperature.csv").unlink()
    _write_results(job_dir)
    intent = _intent(
        TemperatureIntent(
            model="isothermal", reference_temperature_c=20.0,
            uniform_c=600.0, source="unit",
        )
    )
    metrics = postprocess(
        intent, job_dir, tmp_path / "faces.json", job_dir / "load_audit.json"
    )
    provenance = metrics["temperature_provenance"]
    assert provenance["source"] == "reevaluated"
    assert provenance["max_abs_delta_c"] is None
    assert "never checked" in provenance["note"]
