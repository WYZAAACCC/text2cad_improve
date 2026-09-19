"""What the meshing agent asks for, and what the mesher is told.

A refinement region is a target size at a place. The agent describes the place
as a cylinder, a sphere or a box; the mesher sizes on a gmsh expression, which
is a distance. Those two vocabularies met in `_config_from`, which collapsed
every kind to a single `r_center_mm` - the radius of the region's centre.

Measured on D27: the agent asked for a fine region at the load and a coarse
web, and submitted four regions. All four arrived at the mesher as annuli
about the rotation axis, which on that part is the bore - the one place there
is no material at all. The requested refinement did nothing, and the mesh
came out uniform at the web size with the fine elements anywhere curvature
happened to put them. Nothing failed; the plan was just not the one that ran.

So these tests are about the translation being faithful rather than about the
mesher: every kind arrives as itself, and the test that guards the load path
asks its question in the terms of the shape it is asking about.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from seekflow_structural.agents import mesh
from seekflow_structural.errors import StructuralError


def a_state(*, load_radius_mm=288.5, centroids=None) -> mesh.MeshState:
    return mesh.MeshState(
        bundle=Path("E:/bundle"),
        step=Path("E:/bundle/model.step"),
        work_dir=Path("E:/job/mesh"),
        profile={"r_min_mm": 60.0, "r_max_mm": 300.0},
        load_radius_mm=load_radius_mm,
        load_face_centroids=(
            centroids if centroids is not None else [[288.5, 0.0, 0.0]]
        ),
        base_config={"geometry": {}, "mesh": {}},
    )


def _zone(config: dict, name: str) -> dict:
    for zone in config["mesh"]["refinement"]["zones"]:
        if zone["name"] == name:
            return zone
    raise AssertionError(f"no zone named {name}")


# --- the translation -------------------------------------------------------

def test_a_cylinder_arrives_as_a_radius_from_the_axis():
    config = mesh._config_from(a_state(), 12.0, [
        mesh.RegionSpec(name="rim", kind="cylinder", size_mm=1.0, ramp_mm=20.0,
                        radius_mm=288.5, rationale="the load path"),
    ])
    zone = _zone(config, "rim")
    assert zone["kind"] == "cylinder"
    assert zone["r_center_mm"] == 288.5


def test_a_sphere_keeps_its_centre_and_radius():
    """The bug this file exists for.

    A sphere of radius 300 centred on the axis contains the whole part. It
    used to arrive at the mesher as `r_center_mm: 0.0`, which refines the
    axis and coarsens everything outward - the opposite of what was asked.
    """
    config = mesh._config_from(a_state(), 12.0, [
        mesh.RegionSpec(name="whole", kind="sphere", size_mm=3.0, ramp_mm=40.0,
                        center_mm=[0.0, 0.0, 0.0], radius_mm=300.0,
                        rationale="everything"),
    ])
    zone = _zone(config, "whole")
    assert zone["kind"] == "sphere"
    assert zone["center_mm"] == [0.0, 0.0, 0.0]
    assert zone["radius_mm"] == 300.0
    assert "r_center_mm" not in zone, (
        "a sphere has no radius from the axis; writing one is how it came to "
        "be meshed as an annulus"
    )


def test_a_box_keeps_both_corners():
    config = mesh._config_from(a_state(), 12.0, [
        mesh.RegionSpec(name="rim_box", kind="box", size_mm=2.0, ramp_mm=25.0,
                        min_mm=[200.0, -50.0, -38.0],
                        max_mm=[300.0, 50.0, 38.0], rationale="the rim"),
    ])
    zone = _zone(config, "rim_box")
    assert zone["min_mm"] == [200.0, -50.0, -38.0]
    assert zone["max_mm"] == [300.0, 50.0, 38.0]


def test_a_shape_missing_what_it_needs_is_refused_by_name():
    with pytest.raises(StructuralError) as exc:
        mesh._config_from(a_state(), 12.0, [
            mesh.RegionSpec(name="s", kind="sphere", size_mm=2.0, ramp_mm=5.0,
                            rationale="no centre, no radius"),
        ])
    assert exc.value.diagnostic.code == "region_needs_centre"


def test_the_vocabulary_no_longer_offers_what_the_mesher_cannot_size_on():
    """`faces` was advertised in the prompt and silently meshed as an annulus.

    The mesher places resolution by distance and has no way to express
    proximity to a face set, so the field is gone rather than accepted and
    reinterpreted.
    """
    with pytest.raises(ValidationError):
        mesh.RegionSpec(name="near_load", kind="faces", size_mm=2.0,
                        ramp_mm=30.0, distance_mm=30.0)


# --- the load path ---------------------------------------------------------

def test_a_cylinder_at_the_load_radius_resolves_the_load():
    regions = [mesh.RegionSpec(name="r", kind="cylinder", size_mm=1.0,
                               ramp_mm=20.0, radius_mm=288.5,
                               rationale="at the load")]
    assert mesh._resolves_load(regions, a_state())


def test_a_sphere_containing_the_load_resolves_it():
    regions = [mesh.RegionSpec(name="s", kind="sphere", size_mm=1.0,
                               ramp_mm=5.0, center_mm=[288.5, 0.0, 0.0],
                               radius_mm=30.0, rationale="over the load")]
    assert mesh._resolves_load(regions, a_state())


def test_a_sphere_the_load_sits_outside_of_does_not():
    """It is the distance to the load's own point that decides, not the
    radius the sphere's centre happens to sit at."""
    regions = [mesh.RegionSpec(name="s", kind="sphere", size_mm=1.0,
                               ramp_mm=5.0, center_mm=[-288.5, 0.0, 0.0],
                               radius_mm=10.0, rationale="the far side")]
    assert not mesh._resolves_load(regions, a_state())


def test_a_box_containing_the_load_resolves_it():
    regions = [mesh.RegionSpec(name="b", kind="box", size_mm=1.0,
                               ramp_mm=5.0, min_mm=[250.0, -60.0, -38.0],
                               max_mm=[300.0, 60.0, 38.0],
                               rationale="the rim block")]
    assert mesh._resolves_load(regions, a_state())


def test_a_region_that_misses_the_load_entirely_is_refused():
    regions = [mesh.RegionSpec(name="hub", kind="cylinder", size_mm=4.0,
                               ramp_mm=10.0, radius_mm=80.0,
                               rationale="the hub")]
    assert not mesh._resolves_load(regions, a_state())


def test_the_load_is_compared_at_its_own_azimuth():
    """A radius alone cannot say whether a sphere covers the load.

    The load acts through a point at this azimuth; a sphere the same distance
    from the axis but a quarter turn away refines nothing that carries it.
    """
    state = a_state(centroids=[[0.0, 288.5, 0.0]])
    regions = [mesh.RegionSpec(name="s", kind="sphere", size_mm=1.0,
                               ramp_mm=1.0, center_mm=[288.5, 0.0, 0.0],
                               radius_mm=5.0, rationale="the wrong side")]
    assert not mesh._resolves_load(regions, state)


def test_a_sphere_centred_on_the_axis_is_not_outside_the_part():
    """Its centre is at radius zero, which is the bore.

    The check that a region is inside the part reads a cylinder's radius. For
    a sphere or a box the centre is a centre, and one sitting on the axis is
    how a region covering the part is written.
    """
    state = a_state()
    state.submitted = None
    action = mesh.Action(
        action="submit_refinement", web_size_mm=12.0,
        regions=[mesh.RegionSpec(
            name="whole", kind="sphere", size_mm=3.0, ramp_mm=40.0,
            center_mm=[0.0, 0.0, 0.0], radius_mm=300.0,
            rationale="everything within 300mm of the centre",
        )],
        rationale="cover the part",
    )
    result = mesh._submit(action, state)
    assert result["ok"] is True
    assert state.submitted["accepted"] is True


def test_a_cylinder_outside_the_part_is_still_refused():
    state = a_state()
    action = mesh.Action(
        action="submit_refinement", web_size_mm=12.0,
        regions=[mesh.RegionSpec(
            name="beyond", kind="cylinder", size_mm=2.0, ramp_mm=5.0,
            radius_mm=400.0, rationale="past the rim",
        )],
        rationale="out of range",
    )
    with pytest.raises(StructuralError) as exc:
        mesh._submit(action, state)
    assert exc.value.diagnostic.code == "region_outside_part"


# --- the study behind the run's noise floor --------------------------------
#
# The floor the loop's scoring compares a difference against is read from the
# two-level study these tests are about. It used to be reachable only as a
# tool the agent might call, and both ways of not calling it were measured: a
# supplied plan runs with no agent at all, and an agent submitted after
# thirteen calls without ever calling it. Either way the revision closed with
# `floors: {}` and the loop fell back to the constant.

class _Job:
    def __init__(self):
        self.events = []

    def event(self, payload):
        self.events.append(payload)


class _Ctx:
    def __init__(self):
        self.job = _Job()


class _Plan:
    web_size_mm = 8.0
    regions: list = []


class _Case:
    mesh = _Plan()


def test_the_stage_runs_the_study_the_agent_did_not(monkeypatch):
    calls = []

    def fake(state, web, regions):
        # The real one marks the study as run; a stub that does not would test
        # a stage that calls the study forever.
        calls.append((web, regions))
        state.convergence_run = True
        return {"ok": True}

    monkeypatch.setattr(mesh, "_run_convergence", fake)
    state = a_state()
    ctx = _Ctx()
    mesh._ensure_convergence(ctx, _Case(), state)
    assert calls == [(8.0, [])]
    assert state.convergence_run is True
    assert [event["kind"] for event in ctx.job.events] == ["convergence_checked"]


def test_a_study_the_agent_already_ran_is_not_run_again(monkeypatch):
    """The agent's own call was the study; a second one is two more solves."""
    calls = []
    monkeypatch.setattr(
        mesh, "_run_convergence",
        lambda state, web, regions: calls.append(1) or {"ok": True},
    )
    state = a_state()
    state.convergence_run = True
    ctx = _Ctx()
    mesh._ensure_convergence(ctx, _Case(), state)
    assert calls == []
    assert ctx.job.events == []


def test_a_study_that_fails_is_recorded_rather_than_passed_over(monkeypatch):
    """A missing floor is a state the report names. Invisible is not the same.

    The agent path already tolerates a failure - a tool that raises comes back
    as a tool reply the model can react to - so this path continues as well.
    What it must not do is continue without saying so, which is how the
    absence went unnoticed across a whole run.
    """
    def boom(state, web, regions):
        raise RuntimeError("no space left on device")

    monkeypatch.setattr(mesh, "_run_convergence", boom)
    state = a_state()
    ctx = _Ctx()
    mesh._ensure_convergence(ctx, _Case(), state)
    assert state.convergence_run is False
    (event,) = ctx.job.events
    assert event["kind"] == "convergence_failed"
    assert "no space left on device" in event["error"]
    assert "noise floor" in event["consequence"]
