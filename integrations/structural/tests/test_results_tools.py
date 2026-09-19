"""Measuring the solved field, on fields whose answer is known by construction.

These are built rather than read off a real run, so each one can assert a
number that was decided before the code ran. A concentration that is two
clusters is two clusters because the nodes were placed that way; a safety
factor is 0.5 because the curve and the stress were chosen to make it 0.5. The
real run is checked too, but in one place and against the report it produced -
a test that reads a 36 MB CSV and agrees with itself proves only that the file
parsed.

The distinction these exist to protect is the one the module is for: a peak is
a node and a concentration is a place, and a notch and a thin section produce
the same maximum and different measurements.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from seekflow_structural.tools import results


def _node(nid: int, x: float, y: float, z: float, s_eqv: float,
          s_radial: float = 0.0, s_hoop: float = 0.0,
          s_axial: float = 0.0) -> results.Node:
    return results.Node(
        nid=nid, x=x, y=y, z=z, r=math.hypot(x, y),
        theta_deg=math.degrees(math.atan2(y, x)),
        ux=0.0, uy=0.0, uz=0.0, u_sum=0.0,
        s_radial=s_radial, s_hoop=s_hoop, s_axial=s_axial,
        s_eqv=s_eqv, stressed=s_eqv != 0.0,
    )


def _field(nodes: list[results.Node]) -> results.ResultField:
    return results.ResultField(nodes=nodes)


# --- filters -------------------------------------------------------------


def test_a_bound_that_was_not_stated_does_not_filter():
    """An unset bound means "no opinion", not zero.

    The face-finding agent lost runs to a filter vocabulary where an unset
    bound defaulted to a number and silently excluded everything outside it.
    """
    field = _field([
        _node(1, 10.0, 0.0, 0.0, 100.0),
        _node(2, 200.0, 0.0, 0.0, 100.0),
    ])
    assert len(field.where()) == 2
    assert len(field.where(r_min=50.0)) == 1
    assert len(field.where(r_max=50.0)) == 1
    assert len(field.where(r_min=50.0, r_max=250.0)) == 1


def test_nodes_without_a_stress_result_are_excluded_by_default():
    """SOLID187 stores results at corner nodes only, and the others read zero.

    A zero that means "not computed" and a zero that means "no stress here"
    are the same number, so the filter has to be on whether a result exists.
    """
    field = _field([
        _node(1, 10.0, 0.0, 0.0, 100.0),
        _node(2, 10.0, 0.0, 0.0, 0.0),
    ])
    assert [node.nid for node in field.where()] == [1]
    assert len(field.where(stressed_only=False)) == 2


# --- profile -------------------------------------------------------------


def test_a_band_whose_max_is_high_and_mean_is_low_holds_a_concentration():
    """The distinction the profile exists to make.

    Nine nodes at 100 MPa and one at 1000 MPa is a concentration; ten nodes at
    550 MPa is a section carrying the same load. Both average the same and
    they are not the same problem.
    """
    spread = [_node(index, 100.0 + index, 0.0, 0.0, 550.0) for index in range(10)]
    spiked = [_node(index, 100.0 + index, 0.0, 0.0, 100.0) for index in range(9)]
    spiked.append(_node(99, 105.0, 0.0, 0.0, 1000.0))

    flat_band = results.profile(spread, "s_eqv", "r", 1)["bands"][0]
    peak_band = results.profile(spiked, "s_eqv", "r", 1)["bands"][0]

    assert flat_band["mean"] == pytest.approx(550.0)
    assert peak_band["max"] == pytest.approx(1000.0)
    assert peak_band["mean"] < 0.3 * peak_band["max"]


def test_profiling_along_an_axis_the_field_does_not_have_is_refused():
    field = _field([_node(1, 10.0, 0.0, 0.0, 100.0)])
    with pytest.raises(ValueError, match="not an axis"):
        results.profile(field.nodes, "s_eqv", "phi", 4)
    with pytest.raises(ValueError, match="not a measurable quantity"):
        results.profile(field.nodes, "s_mises", "r", 4)


def test_a_quantity_absent_on_some_nodes_is_reported_not_dropped():
    """A margin profile over a third of the mesh is a different measurement."""
    field = _field([_node(1, 10.0, 0.0, 0.0, 100.0)])
    payload = results.profile(field.nodes, "safety_factor", "r", 2)
    assert payload["bands"] == []
    assert any("no safety_factor" in note for note in payload["limits"])


# --- concentrations ------------------------------------------------------


def test_two_separated_clusters_are_two_concentrations():
    """A cluster is connected, not "within a radius".

    Two hot patches thirty millimetres apart are two findings, and a ball
    grown from one peak would find only one of them.
    """
    nodes = [
        _node(1, 100.0, 0.0, 0.0, 1000.0),
        _node(2, 100.5, 0.0, 0.0, 990.0),
        _node(3, 130.0, 0.0, 0.0, 980.0),
        _node(4, 130.5, 0.0, 0.0, 970.0),
    ]
    payload = results.concentrations(nodes, relative_threshold=0.9, cell_mm=1.0)
    assert len(payload["concentrations"]) == 2
    assert payload["peak_mpa"] == pytest.approx(1000.0)
    assert payload["cutoff_mpa"] == pytest.approx(900.0)


def test_a_contiguous_band_is_one_concentration_however_long():
    """A long thin concentration is one finding, not several."""
    nodes = [
        _node(index, 100.0 + index * 0.5, 0.0, 0.0, 1000.0 - index)
        for index in range(40)
    ]
    payload = results.concentrations(nodes, relative_threshold=0.9, cell_mm=1.0)
    assert len(payload["concentrations"]) == 1
    assert payload["concentrations"][0]["node_count"] == 40
    assert payload["concentrations"][0]["extent_mm"] > 15.0


def test_the_threshold_and_the_cell_size_are_echoed_back():
    """Nothing here decides what counts as a concentration."""
    nodes = [_node(1, 100.0, 0.0, 0.0, 1000.0)]
    payload = results.concentrations(nodes, relative_threshold=0.75)
    assert payload["relative_threshold"] == pytest.approx(0.75)
    assert payload["cell_mm"] > 0
    assert any("derived from the field" in note for note in payload["limits"])


def test_asking_for_a_fraction_above_the_peak_finds_nothing_and_says_why():
    nodes = [_node(1, 100.0, 0.0, 0.0, 10.0)]
    payload = results.concentrations(nodes, relative_threshold=1.0, cell_mm=1.0)
    assert payload["concentrations"]
    empty = results.concentrations(
        [n for n in nodes if n.s_eqv > 100.0], cell_mm=1.0
    )
    assert empty["concentrations"] == []


# --- components ----------------------------------------------------------


def test_the_dominant_component_names_the_mechanism():
    """Hoop-driven and radial-driven peaks want opposite changes.

    Measured on D27: the bore peak is 1482 MPa of hoop against 0.8 MPa of
    radial, and the fir-tree peak is 1188 MPa of radial against 268 of hoop.
    The two are different problems with the same headline number.
    """
    bore = results.components([
        _node(1, 60.0, 0.0, 0.0, 1482.7, s_radial=0.8, s_hoop=1482.0)
    ])
    rim = results.components([
        _node(1, 210.0, 0.0, 0.0, 1042.0, s_radial=1188.1, s_hoop=268.3)
    ])
    assert bore["dominant"] == "s_hoop"
    assert rim["dominant"] == "s_radial"


def test_components_over_an_empty_set_says_so():
    assert "limits" in results.components([])


# --- decay ---------------------------------------------------------------


def test_a_notch_collapses_within_millimetres_and_a_section_does_not():
    """The measurement that separates the two causes of a high peak.

    A fillet raises the stress over a length like its own radius; a web that
    is too thin carries it over tens of millimetres. One wants a bigger
    radius, the other wants more material, and the peak cannot tell them
    apart.
    """
    notch = [_node(0, 100.0, 0.0, 0.0, 1000.0)]
    notch += [_node(i, 100.0 + i * 0.5, 0.0, 0.0, 1000.0 * math.exp(-i * 0.5))
              for i in range(1, 20)]
    broad = [_node(1000, 100.0, 0.0, 0.0, 1000.0)]
    broad += [_node(1000 + i, 100.0 + i * 0.5, 0.0, 0.0,
                    1000.0 * math.exp(-i * 0.02))
              for i in range(1, 60)]

    field = _field(notch + broad)
    # The set the walk happens in is the caller's, and it is what makes the
    # answer mean "along this surface" rather than "to the nearest other one".
    sharp = results.decay(field, notch[0], nodes=notch)
    gentle = results.decay(field, broad[0], nodes=broad)

    assert sharp["reached"]["0.5"]["distance_mm"] < 3.0
    assert gentle["reached"]["0.5"] is None or (
        gentle["reached"]["0.5"]["distance_mm"]
        > sharp["reached"]["0.5"]["distance_mm"]
    )
    assert sharp["walked_node_count"] == 19
    assert gentle["walked_node_count"] == 59


# --- section resultant ---------------------------------------------------


def test_the_resultant_is_the_radial_stress_over_the_cut_area():
    """The one measurement that follows the load path.

    Area weighting, because an unweighted mean over a band that spans radii
    over-counts the inner nodes where the annular patches are smaller.
    """
    nodes = [
        _node(index, 100.0 + index * 0.1, 0.0, 0.0, 10.0, s_radial=100.0)
        for index in range(21)
    ]
    nodes += [
        _node(100 + index, 100.0, 0.0, index * 0.1, 10.0, s_radial=100.0)
        for index in range(21)
    ]
    payload = results.section_resultant(nodes, 100.0, 2.0)
    assert payload["mean_s_radial_mpa"] == pytest.approx(100.0)
    assert payload["radial_resultant_n"] == pytest.approx(
        payload["mean_s_radial_mpa"] * payload["cut_area_mm2"], rel=1e-6
    )
    # The half-thickness caveat is stated rather than applied.
    assert any("scaling factor" in note for note in payload["limits"])


def test_the_cut_area_comes_from_the_model_not_from_the_band():
    """The bug this replaced, which was invisible in the answer.

    Taking the area from the band's own node span made a cut through the
    fir-tree - where the slot has removed material over part of the thickness
    - come out half the size it is, and halved the resultant with it.
    """
    # The model is 40 mm thick in z, set by nodes further out; the band at
    # r = 100 only has nodes over the first 10 mm of it.
    nodes = [
        _node(1, 100.0, 0.0, 0.0, 10.0, s_radial=100.0),
        _node(2, 100.0, 0.0, 10.0, 10.0, s_radial=100.0),
        _node(3, 150.0, 0.0, 0.0, 10.0, s_radial=100.0),
        _node(4, 150.0, 0.0, 40.0, 10.0, s_radial=100.0),
    ]
    payload = results.section_resultant(nodes, 100.0, 2.0)
    assert payload["model_z_span_mm"] == pytest.approx(40.0)
    # Area is r * theta_span * model_z_span, not * band_z_span.
    assert payload["z_coverage_fraction"] < 0.3
    assert any("samples" in note for note in payload["limits"])


def test_a_span_that_crosses_the_angle_wrap_is_not_reported_as_a_full_circle():
    """A sector straddling +/-180 must not read as 359 degrees.

    Six nodes from -178 to +188 degrees cover 17 degrees of a sector that
    straddles +/-180. `max - min` calls that 355 degrees, and every area that
    depends on it comes out twenty times too large.
    """
    nodes = []
    for index, angle in enumerate([-178.0, -175.0, -172.0, 177.0, 174.0, 171.0]):
        radians = math.radians(angle)
        nodes.append(_node(
            index, 100.0 * math.cos(radians), 100.0 * math.sin(radians),
            0.0, 10.0, s_radial=100.0,
        ))
    payload = results.section_resultant(nodes, 100.0, 2.0)
    assert payload["model_angular_span_deg"] == pytest.approx(17.0, abs=1.0)


def test_a_cut_through_empty_space_says_so():
    nodes = [_node(1, 100.0, 0.0, 0.0, 10.0, s_radial=100.0)]
    payload = results.section_resultant(nodes, 900.0, 1.0)
    assert payload["limits"]


# --- loading and the safety factor ---------------------------------------


def _write_run(tmp_path: Path, rows, temperatures):
    solve = tmp_path / "solve"
    solve.mkdir(parents=True, exist_ok=True)
    header = ["nid", "x", "y", "z", "ux", "uy", "uz",
              "s_radial", "s_hoop", "s_axial", "s_eqv", "sel"]
    with (solve / "nodal_stress_3d.csv").open("w", newline="",
                                              encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
    if temperatures is not None:
        with (solve / "node_temperature.csv").open("w", newline="",
                                                   encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["nid", "temperature_c"])
            for nid, value in temperatures.items():
                writer.writerow([nid, value])
    return solve


def test_the_safety_factor_is_yield_at_the_deck_temperature_over_stress(tmp_path):
    """Reproduces, rather than re-derives, the post-processor's arithmetic.

    The check is against the number the report quotes, so a second evaluation
    of the temperature field cannot make this module disagree with the report
    about the same node.
    """
    solve = _write_run(
        tmp_path,
        [[1, 60.0, 0.0, 0.0, 0, 0, 0, 0.8, 1482.0, -2.0, 1482.673, 1]],
        {1: 500.0},
    )
    field = results.ResultField.load(solve, [(20.0, 1100.0), (500.0, 1000.0),
                                             (650.0, 950.0)])
    node = field.nodes[0]
    assert node.temperature_c == pytest.approx(500.0)
    assert node.yield_mpa == pytest.approx(1000.0)
    assert node.safety_factor == pytest.approx(1000.0 / 1482.673, rel=1e-9)
    assert field.has_safety_factor


def test_without_a_material_curve_the_margin_is_unmeasured_not_zero(tmp_path):
    solve = _write_run(
        tmp_path,
        [[1, 60.0, 0.0, 0.0, 0, 0, 0, 0.8, 1482.0, -2.0, 1482.673, 1]],
        {1: 500.0},
    )
    field = results.ResultField.load(solve)
    assert not field.has_safety_factor
    assert field.nodes[0].safety_factor is None
    assert any("material yield curve" in note for note in field.limits)
    assert field.peak().s_eqv == pytest.approx(1482.673)


def test_the_mid_side_nodes_are_counted_out_loud(tmp_path):
    """A zero that means "not computed" is not a stress of zero."""
    solve = _write_run(
        tmp_path,
        [[1, 60.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 1482.673, 1],
         [2, 61.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0.0, 1]],
        None,
    )
    field = results.ResultField.load(solve)
    assert len(field.stressed()) == 1
    assert any("carry no stress result" in note for note in field.limits)


def test_extreme_states_its_direction_so_margin_is_not_read_as_a_peak():
    """The largest safety factor is the least interesting node in the field.

    Taking a maximum when the question is about margin returns the safest
    place in the component and reads as its worst.
    """
    field = _field([
        _node(1, 60.0, 0.0, 0.0, 1000.0),
        _node(2, 61.0, 0.0, 0.0, 100.0),
    ])
    for node, sf in zip(field.nodes, (0.5, 5.0)):
        object.__setattr__(node, "safety_factor", sf)
    assert field.peak("safety_factor").nid == 2
    assert field.extreme("safety_factor", largest=False).nid == 1
    assert field.worst_margin().nid == 1


# --- the join to CAD faces -----------------------------------------------


def test_face_stress_turns_a_location_into_a_named_feature():
    """A finding that says "1482 MPa at r = 212" can be acted on by nothing."""
    field = _field([
        _node(1, 210.0, 0.0, 0.0, 1042.0, s_radial=1188.0),
        _node(2, 211.0, 0.0, 0.0, 900.0, s_radial=1000.0),
    ])
    selection = {"per_face": {"3954": {
        "area_mm2": 147.96,
        "centroid_mm": [207.0, 0.0, 0.0],
        "normal_cylindrical": {"radial": -0.72, "tangential": -0.69, "axial": 0.0},
        "node_ids": [1, 2],
    }}}
    payload = results.face_stress(field, selection)
    face = payload["faces"][0]
    assert face["cad_face"] == 3954
    assert face["max_von_mises_mpa"] == pytest.approx(1042.0)
    assert face["dominant_component"] == "s_radial"
    assert face["max_node"] == 1


def test_a_selection_naming_nodes_the_field_never_heard_of_is_a_broken_run():
    """The selection and the solve have to be the same mesh."""
    field = _field([_node(1, 210.0, 0.0, 0.0, 1042.0)])
    selection = {"per_face": {"3954": {
        "area_mm2": 1.0, "centroid_mm": [207.0, 0.0, 0.0],
        "normal_cylindrical": None, "node_ids": [1, 2, 3],
    }}}
    payload = results.face_stress(field, selection)
    assert any("not in the result field at all" in note
               for note in payload["limits"])


def test_a_mid_side_node_with_no_stress_is_not_reported_as_a_broken_run():
    """Measured: 11,334 of d27-correct24's 16,376 selected nodes are mid-side.

    Reading that as a mesh mismatch would report every healthy run as broken,
    and the two counts call for opposite next actions.
    """
    field = _field([
        _node(1, 210.0, 0.0, 0.0, 1042.0),
        _node(2, 211.0, 0.0, 0.0, 0.0),
    ])
    selection = {"per_face": {"3954": {
        "area_mm2": 1.0, "centroid_mm": [207.0, 0.0, 0.0],
        "normal_cylindrical": None, "node_ids": [1, 2],
    }}}
    payload = results.face_stress(field, selection)
    assert not any("not in the result field at all" in note
                   for note in payload["limits"])
    assert any("carry no stress result" in note for note in payload["limits"])
    assert payload["faces"][0]["stressed_node_count"] == 1


def test_without_a_selection_the_join_says_it_cannot_be_made():
    payload = results.face_stress(_field([]), None)
    assert payload["faces"] == []
    assert payload["limits"]


# --- against the real run ------------------------------------------------


def _real_job() -> Path | None:
    from conftest import STRUCTURAL_EXPERIMENT

    job = (STRUCTURAL_EXPERIMENT / "output" / "structural" / "jobs"
           / "d27-correct24")
    return job if (job / "solve" / "nodal_stress_3d.csv").is_file() else None


@pytest.mark.skipif(_real_job() is None, reason="the D27 job is not on disk")
def test_the_safety_factor_agrees_with_the_report_on_a_real_run():
    """The one check that a synthetic field cannot make.

    The report quotes a minimum safety factor and the node it belongs to. If
    this module's arithmetic disagrees with it, then every margin this agent
    reasons about is measuring something other than what the run reported.
    """
    job = _real_job()
    assert job is not None
    metrics = json.loads(
        (job / "solve" / "structural_metrics.json").read_text(encoding="utf-8")
    )
    field = results.ResultField.load(
        job / "solve",
        [(20.0, 1100.0), (300.0, 1050.0), (500.0, 1000.0), (650.0, 950.0)],
    )
    worst = field.worst_margin()
    assert worst is not None
    assert worst.nid == metrics["stress"]["min_safety_factor_node"]
    assert worst.safety_factor == pytest.approx(
        metrics["stress"]["min_safety_factor"], abs=1e-6
    )


def test_mesh_convergence_is_read_from_the_two_levels_that_were_solved(tmp_path):
    """The subtraction nobody was doing.

    The meshing stage solves the part twice and leaves both metric files on
    disk. The only thing that ever read them was a summary file nothing
    writes, so on every run that had in fact run a study, the verification
    stage was told no study existed.
    """
    for name, peak, nodes in (("convergence_coarse", 1789.481, 181_362),
                              ("convergence_fine", 1880.635, 194_011)):
        level = tmp_path / "mesh" / "convergence" / name
        level.mkdir(parents=True)
        (level / "structural_metrics.json").write_text(
            json.dumps({"node_count": nodes,
                        "stress_sampling": {"mesh_node_count": nodes},
                        "stress": {"max_von_mises_mpa": peak}}),
            encoding="utf-8",
        )
    percent = results.mesh_convergence_percent(tmp_path)
    assert percent is not None
    assert percent["max_von_mises_mpa"] == pytest.approx(
        (1880.635 - 1789.481) / 1789.481 * 100.0, rel=1e-6
    )


def test_a_run_with_one_mesh_level_has_no_convergence_to_report(tmp_path):
    """No study is not a study that found nothing."""
    level = tmp_path / "mesh" / "convergence" / "convergence_fine"
    level.mkdir(parents=True)
    (level / "structural_metrics.json").write_text(
        json.dumps({"node_count": 1, "stress_sampling": {"mesh_node_count": 1},
                    "stress": {"max_von_mises_mpa": 100.0}}),
        encoding="utf-8",
    )
    assert results.mesh_convergence_percent(tmp_path) is None


@pytest.mark.skipif(_real_job() is None, reason="the D27 job is not on disk")
def test_each_reported_quantity_is_judged_by_its_own_convergence():
    """One metric's movement must not settle another metric's verdict.

    On this job the loaded surface is the number that has not settled, at
    -3.26% between mesh levels, while the global peak is settled to 0.03%.
    Attaching every convergence comparison to every quantity made the 3.26%
    decide all four, so the peak - which had settled - was reported as
    unsettled. The loop's own run of this disc has it the other way round,
    which is why the check has to be per quantity and not per run.
    """
    from seekflow_structural.agents import verify
    from seekflow_structural.case.store import CaseStore
    from seekflow_structural.pipeline.orchestrator import Budget, RunContext
    from seekflow_structural.runtime.store import JobStore

    job_path = _real_job()
    assert job_path is not None
    convergence = results.mesh_convergence_percent(job_path)
    assert convergence is not None

    # `JobStore` lays a job out at `<output_root>/jobs/<job_id>`.
    job = JobStore(job_path.parent.parent, job_path.name)
    case = CaseStore(job).load()
    assert case is not None
    ctx = RunContext(job=job, case_store=CaseStore(job), budget=Budget(),
                     case=case)
    verdicts = {v.quantity: v.verdict for v in verify.build_verdicts(ctx, case)}

    # The unsettled number is suspect, and only it.
    assert abs(convergence["max_load_surface_von_mises_mpa"]) > 2.0
    assert verdicts["max_load_surface_von_mises_mpa"] == "suspect"
    # The settled ones are not, however much the unsettled one moved.
    for quantity in ("max_von_mises_mpa", "min_safety_factor",
                     "max_displacement_mm"):
        assert abs(convergence[quantity]) < 2.0, quantity
        assert verdicts[quantity] != "suspect", quantity


@pytest.mark.skipif(_real_job() is None, reason="the D27 job is not on disk")
def test_the_peak_this_module_finds_is_the_peak_the_report_quotes():
    job = _real_job()
    assert job is not None
    metrics = json.loads(
        (job / "solve" / "structural_metrics.json").read_text(encoding="utf-8")
    )
    field = results.ResultField.load(job / "solve")
    peak = field.peak()
    assert peak is not None
    assert peak.s_eqv == pytest.approx(
        metrics["stress"]["max_von_mises_mpa"], abs=1e-6
    )
    assert peak.r == pytest.approx(metrics["stress"]["max_radius_mm"], abs=1e-3)


# --- the axes the profile advertises -------------------------------------


def test_every_axis_the_profile_advertises_can_be_read():
    """The tool listed an axis it could not read.

    `AXES` named `theta` and `Node` stores `theta_deg`, so `profile(axis=
    "theta")` raised `AttributeError: 'Node' object has no attribute 'theta'`
    - and the reply that offers the axes is the same reply that offers the
    profile. Measured on the first complete loop run: the feedback agent asked
    for the theta profile, the call raised, and the angular extent of the
    stress concentration was never measured. The finding was filed anyway and
    the failure survived only as a line of prose in the agent's own list of
    limits.
    """
    nodes = [_node(nid, 10.0, float(nid), float(nid), 100.0 * nid)
             for nid in range(1, 6)]
    for axis in results.AXES:
        out = results.profile(nodes, "s_eqv", axis, bins=4)
        assert out["axis"] == axis
        # Every axis carries a spread here, so a limit would mean the band
        # came back empty rather than that the fixture was flat along it.
        assert out["limits"] == [], axis
        assert len(out["bands"]) == 4, axis


def test_the_theta_profile_resolves_along_the_angle():
    """Not merely "does not raise" - the bands follow theta."""
    nodes = [_node(nid, 10.0, 0.0, 0.0, 100.0) for nid in range(1, 5)]
    for node, theta in zip(nodes, (0.0, 20.0, 40.0, 60.0)):
        object.__setattr__(node, "theta_deg", theta)
        object.__setattr__(node, "s_eqv", 100.0 + theta)
    out = results.profile(nodes, "s_eqv", "theta", bins=3)
    assert len(out["bands"]) == 3
    assert out["bands"][0]["low"] == 0.0
    assert out["bands"][-1]["high"] == 60.0
    # The maximum in each band is the node that band holds, so the curve rises
    # with theta rather than being flat.
    maxima = [band["max"] for band in out["bands"]]
    assert maxima == sorted(maxima)


def test_an_axis_that_is_not_advertised_is_still_refused():
    nodes = [_node(1, 10.0, 0.0, 0.0, 100.0)]
    with pytest.raises(ValueError) as excinfo:
        results.profile(nodes, "s_eqv", "radius", 4)
    assert "theta" in str(excinfo.value)
