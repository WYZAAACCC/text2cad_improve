"""The stage that decides what the simulation is.

Two ways in, one way through. A written parameter file is parsed; a brief is
read by the agent. Either way the values land in `case.physics`, which is what
every stage below reads - so the two are not two paths through the chain, they
are two ways of filling the same field.

The tests that matter most are the ones about what the agent will *not* do. A
setup agent that fills a missing material with a plausible one produces a run
that looks like an answer, and nothing downstream can tell. So: a missing
section is a question, an unknown alloy is a question, and a submission with
no account of where its numbers came from is refused.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

# Not `setup_module`: pytest treats that name as its own xunit hook
# for the whole module and tries to call it before every test.
from seekflow_structural.agents import setup as setup_agent
from seekflow_structural.case.model import (
    BundleRef,
    Case,
    DomainDecision,
    Frame,
    ModelFacts,
    Plane,
    Vec3,
    Written,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline import params as params_module
from seekflow_structural.pipeline.orchestrator import Budget, RunContext
from seekflow_structural.runtime.store import JobStore

MEASURED = Written(by_stage="frame", kind="measured", source="test")
DECIDED = Written(by_stage="domain", kind="agent_decision", source="test")


class FakeCaller:
    """Replays a scripted list of tool calls, as the loop hands them over."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def call_strict_tool(self, *, messages, tool_name, tool_description,
                         tool_schema, model_config):
        self.seen.append([dict(m) for m in messages])
        if not self.script:
            raise AssertionError("the loop asked for more calls than scripted")
        arguments = self.script.pop(0)
        return SimpleNamespace(
            tool_name=tool_name, arguments=arguments,
            tool_call_id=f"call_{len(self.seen)}", assistant_content="",
            raw_response_id="r", model="fake", provider="fake",
        )


def a_case() -> Case:
    return Case(
        case_id="d27",
        bundle=BundleRef(path="E:/bundle/D27", lineage_id="D27",
                         revision_id="rev-000001"),
        model=ModelFacts(
            bounds_min_mm=Vec3(x=-300.0, y=-300.0, z=-38.0),
            bounds_max_mm=Vec3(x=300.0, y=300.0, z=38.0),
            r_max_mm=300.0, has_rotation_axis=True,
            frame=Frame(axis_origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
                        axis_direction=Vec3(x=0.0, y=0.0, z=1.0)),
            symmetry_planes=[Plane(id="z0", origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
                                   normal=Vec3(x=0.0, y=0.0, z=1.0),
                                   matched_area_fraction=1.0)],
            bore_radius_mm=60.0, face_count=4216, written=MEASURED,
        ),
        domain=DomainDecision(sector_deg=18.0, theta_low_deg=3.0,
                              symmetry_planes_used=["z0"], written=DECIDED),
    )


def a_context(tmp_path, *, params=None, brief="") -> RunContext:
    job = JobStore(tmp_path, "setup-test")
    return RunContext(
        job=job, case_store=None, budget=Budget(),
        case=a_case(), params=params or {},
        params_path="E:/params.json" if params else "",
        brief=brief, brief_path="E:/brief.md" if brief else "",
    )


def write_params(**overrides) -> dict:
    """A parameter file in the shape the chain has always accepted."""
    data = {
        "case_id": "d27",
        "confirmation_status": "unconfirmed",
        "rotation": {"rpm": 15000.0, "source": "given"},
        "temperature": {
            "model": "radial_power_law", "reference_temperature_c": 20.0,
            "bore_c": 500.0, "rim_c": 650.0, "bore_radius_mm": 60.0,
            "outer_radius_mm": 300.0, "exponent": 1.0, "source": "given",
        },
        "material": {
            "name": "GH4169", "source": "the table",
            "poisson_ratio": 0.3, "density_t_mm3": 8.24e-9,
            "points": [
                {"temperature_c": 20.0, "young_mpa": 205000.0,
                 "alpha_per_c": 1.18e-5, "yield_mpa": 1100.0},
                {"temperature_c": 650.0, "young_mpa": 165000.0,
                 "alpha_per_c": 1.54e-5, "yield_mpa": 950.0},
            ],
        },
        "blade_load": {
            "model": "equivalent_total_force",
            "total_force_n_per_slot": 271300.0,
            "direction_rule": "flank_surface_normal",
            "distribution": "area_weighted_uniform_pressure",
            "source": "given",
        },
        "constraints": {
            "cyclic_symmetry": True, "axial_symmetry_z0": True,
            "tangential_anchor": True, "source": "given",
        },
    }
    data.update(overrides)
    return data


# --- the written-parameter path -------------------------------------------


def test_a_parameter_file_needs_no_model_call_at_all(tmp_path):
    """The path that existed before this stage did, unchanged.

    A run given a written file must behave exactly as it did when assembly
    parsed it: same physics, field for field, and no agent involved.
    """
    params = write_params()
    ctx = a_context(tmp_path, params=params)
    case = setup_agent.setup(ctx)
    expected = params_module.physics_from_params(params, ctx.params_path)
    settled = {"written", "consistency"}
    assert case.physics.model_dump(exclude=settled) == \
        expected.model_dump(exclude=settled)
    assert case.physics.written.by_stage == "setup"
    # and the comparisons against the part are made here, where the numbers
    # are still the subject, rather than three stages down
    assert case.physics.consistency


def test_the_file_path_records_which_file_it_read(tmp_path):
    params = write_params()
    ctx = a_context(tmp_path, params=params)
    case = setup_agent.setup(ctx)
    assert case.physics.written.source == ctx.params_path


# --- the brief path --------------------------------------------------------


def sections(*, rpm=15000.0, total_force=271300.0) -> dict:
    return {
        "rotation": {
            "axis_origin_mm": [0.0, 0.0, 0.0],
            "axis_direction": [0.0, 0.0, 1.0],
            "rpm": rpm,
            "source": "the description says it turns at this speed",
        },
        "temperature": {
            "model": "radial_power_law",
            "reference_temperature_c": 20.0,
            "bore_c": 500.0, "rim_c": 650.0,
            "bore_radius_mm": 60.0, "outer_radius_mm": 300.0,
            "exponent": 1.0,
            "source": "the description gives both ends and the exponent",
        },
        "material": {
            "name": "GH4169 / Inconel 718",
            "source": "the material table entry for GH4169",
            "poisson_ratio": 0.3, "density_t_mm3": 8.24e-9,
            "points": [
                {"temperature_c": 20.0, "young_mpa": 205000.0,
                 "alpha_per_c": 1.18e-5, "yield_mpa": 1100.0},
                {"temperature_c": 650.0, "young_mpa": 165000.0,
                 "alpha_per_c": 1.54e-5, "yield_mpa": 950.0},
            ],
        },
        "blade_load": {
            "model": "equivalent_total_force",
            "total_force_n_per_slot": total_force,
            "direction_rule": "flank_surface_normal",
            "distribution": "area_weighted_uniform_pressure",
            "source": "check_load, from the blade mass and speed",
        },
        "constraints": {
            "cyclic_symmetry": True, "axial_symmetry_z0": True,
            "tangential_anchor": True, "source": "the description",
        },
    }


def a_submission(**overrides) -> dict:
    return {
        "action": "submit_setup",
        "rationale": "every value came from the description or the table",
        **sections(**overrides),
    }


@pytest.fixture
def patched_caller(monkeypatch):
    """Hand the stage a scripted caller instead of a real one."""
    holder = {}

    def install(script):
        caller = FakeCaller(script)
        holder["caller"] = caller
        monkeypatch.setattr(
            "seekflow_structural.runtime.caller.build_caller",
            lambda *a, **k: (caller, None),
        )
        return caller

    return install


def test_a_brief_becomes_the_same_physics_a_file_would_have(tmp_path, patched_caller):
    patched_caller([{"action": "get_part_facts"}, a_submission()])
    ctx = a_context(tmp_path, brief="a turbine disc, 15000 rpm, IN718")
    case = setup_agent.setup(ctx)
    assert case.physics.rotation.rpm == 15000.0
    assert case.physics.blade_load.total_force_n_per_slot == 271300.0
    assert case.physics.material.name == "GH4169 / Inconel 718"
    assert case.physics.constraints.cyclic_symmetry is True


def test_what_the_agent_read_is_written_out_as_a_parameter_file(
    tmp_path, patched_caller
):
    """So the reading can be reused, and so it can be read back later.

    A parameter set that only ever existed inside a conversation cannot be
    checked by anyone, and cannot be the starting point for the next run.
    """
    patched_caller([a_submission()])
    ctx = a_context(tmp_path, brief="...")
    setup_agent.setup(ctx)
    written = json.loads(
        (ctx.path / "params.resolved.json").read_text(encoding="utf-8")
    )
    assert sorted(written) == [
        "blade_load", "constraints", "material", "rotation", "temperature"
    ]
    # and it is a parameter file in its own right
    physics = params_module.physics_from_params(written, "round trip")
    assert physics.rotation.rpm == 15000.0


def test_the_agent_is_told_the_part_and_the_sector_it_is_setting_up(
    tmp_path, patched_caller
):
    """The load this model carries is a question about how much of the part
    is being analysed, so the agent has to be able to see that."""
    caller = patched_caller([{"action": "get_part_facts"}, a_submission()])
    ctx = a_context(tmp_path, brief="...")
    setup_agent.setup(ctx)
    reply = json.loads(
        [m for m in caller.seen[1] if m["role"] == "tool"][-1]["content"]
    )
    facts = reply["result"]
    assert facts["outer_radius_mm"] == 300.0
    assert facts["bore_radius_mm"] == 60.0
    assert facts["being_analysed"]["sector_deg"] == 18.0
    assert facts["being_analysed"]["whole_part"] is False


def test_the_brief_travels_into_the_conversation(tmp_path, patched_caller):
    caller = patched_caller([a_submission()])
    ctx = a_context(tmp_path, brief="a turbine disc at 15000 rpm")
    setup_agent.setup(ctx)
    system, user = caller.seen[0][0], caller.seen[0][1]
    assert "15000 rpm" in user["content"]
    assert "needs_input" in system["content"]


# --- what it refuses ------------------------------------------------------


def test_a_run_with_neither_file_nor_brief_is_refused(tmp_path):
    ctx = a_context(tmp_path)
    with pytest.raises(StructuralError) as exc:
        setup_agent.setup(ctx)
    assert exc.value.diagnostic.code == "no_parameters"


def test_the_agent_asking_a_question_ends_the_run_with_the_question(
    tmp_path, patched_caller
):
    patched_caller([{
        "action": "needs_input",
        "questions": [
            "the description gives no material, and no alloy is named",
        ],
    }])
    ctx = a_context(tmp_path, brief="a disc, spinning")
    with pytest.raises(StructuralError) as exc:
        setup_agent.setup(ctx)
    assert exc.value.diagnostic.code == "setup_not_defined"
    assert "no material" in exc.value.diagnostic.message


def test_a_submission_missing_a_section_is_refused_by_name(
    tmp_path, patched_caller
):
    """Not filled in from a similar machine, and not left to the deck."""
    incomplete = a_submission()
    del incomplete["material"]
    caller = patched_caller([
        incomplete,
        {"action": "needs_input", "questions": ["what is it made of?"]},
    ])
    ctx = a_context(tmp_path, brief="...")
    with pytest.raises(StructuralError) as exc:
        setup_agent.setup(ctx)
    assert exc.value.diagnostic.code == "setup_not_defined"
    # and the agent was told which section, at the call that failed
    reply = json.loads(
        [m for m in caller.seen[1] if m["role"] == "tool"][-1]["content"]
    )
    assert reply["error_code"] == "incomplete_setup"
    assert "material" in reply["error"]


def test_a_submission_without_a_rationale_is_refused(tmp_path, patched_caller):
    no_rationale = a_submission()
    no_rationale["rationale"] = ""
    caller = patched_caller([no_rationale, a_submission()])
    ctx = a_context(tmp_path, brief="...")
    case = setup_agent.setup(ctx)
    assert case.physics is not None
    reply = json.loads(
        [m for m in caller.seen[1] if m["role"] == "tool"][-1]["content"]
    )
    assert reply["error_code"] == "no_rationale"


def test_check_setup_reports_without_committing(tmp_path):
    """A submission ends the run, so there has to be a way to look first."""
    state = setup_agent.SetupState(model=a_case().model, sector_deg=18.0)
    action = setup_agent.Action.model_validate(a_submission())
    reply = setup_agent._check_setup(action, state)
    assert reply["ok"] is True
    assert "temperature" in reply["result"]["sections"]
    assert state.submitted is None
    assert state.checks, "the check is kept, so a run can be read back"


# --- the arithmetic the agent does not have to do in its head --------------


def test_check_load_derives_one_blades_force():
    state = setup_agent.SetupState(model=a_case().model, sector_deg=18.0)
    action = setup_agent.Action.model_validate({
        "action": "check_load", "rpm": 15000.0, "blade_mass_kg": 0.2136,
        "centre_of_mass_radius_mm": 343.24,
    })
    result = setup_agent._check_load(action, state)["result"]
    assert result["one_blade_force_n"] == pytest.approx(180900.0, rel=2e-3)
    # nothing about the sector, because the slot count was not supplied
    assert result["sector"] is None
    assert "slots_in_the_part" in result["note"]


def test_check_load_multiplies_up_to_what_this_model_carries():
    state = setup_agent.SetupState(model=a_case().model, sector_deg=18.0)
    action = setup_agent.Action.model_validate({
        "action": "check_load", "rpm": 15000.0, "blade_mass_kg": 0.2136,
        "centre_of_mass_radius_mm": 343.24, "slots_in_the_part": 60,
        "thickness_fraction_modelled": 0.5,
    })
    sector = setup_agent._check_load(action, state)["result"]["sector"]
    assert sector["slot_pitch_deg"] == pytest.approx(6.0)
    assert sector["slots_in_the_sector"] == pytest.approx(3.0)
    assert sector["force_this_model_must_carry_n"] == pytest.approx(
        271300.0, rel=3e-3
    )


def test_the_thickness_fraction_comes_from_the_domain_not_the_agent():
    """A model on the mid-plane carries half the load, and that was decided
    two stages earlier.

    Left to state it, an agent that reads nothing about symmetry would take
    the whole thickness and double the load - and nothing downstream could
    tell, because the deck scales the pressure to hit whatever target it is
    given.
    """
    state = setup_agent.SetupState(
        model=a_case().model, sector_deg=18.0, half_thickness=True
    )
    action = setup_agent.Action.model_validate({
        "action": "check_load", "rpm": 15000.0, "blade_mass_kg": 0.2136,
        "centre_of_mass_radius_mm": 343.24, "slots_in_the_part": 60,
    })
    sector = setup_agent._check_load(action, state)["result"]["sector"]
    assert sector["thickness_fraction_modelled"] == 0.5
    assert "mid-plane" in sector["thickness_fraction_source"]
    assert sector["force_this_model_must_carry_n"] == pytest.approx(
        271300.0, rel=3e-3
    )


def test_a_stated_thickness_fraction_that_contradicts_the_domain_is_flagged():
    state = setup_agent.SetupState(
        model=a_case().model, sector_deg=18.0, half_thickness=True
    )
    action = setup_agent.Action.model_validate({
        "action": "check_load", "rpm": 15000.0, "blade_mass_kg": 0.2136,
        "centre_of_mass_radius_mm": 343.24, "slots_in_the_part": 60,
        "thickness_fraction_modelled": 1.0,
    })
    sector = setup_agent._check_load(action, state)["result"]["sector"]
    assert sector["thickness_fraction_modelled"] == 1.0
    assert "disagrees_with_the_domain" in sector


def test_a_whole_part_model_takes_the_whole_load():
    state = setup_agent.SetupState(
        model=a_case().model, sector_deg=18.0, half_thickness=False
    )
    action = setup_agent.Action.model_validate({
        "action": "check_load", "rpm": 15000.0, "blade_mass_kg": 0.2136,
        "centre_of_mass_radius_mm": 343.24, "slots_in_the_part": 60,
    })
    sector = setup_agent._check_load(action, state)["result"]["sector"]
    assert sector["thickness_fraction_modelled"] == 1.0
    assert "no mid-plane symmetry" in sector["thickness_fraction_source"]


def test_check_load_refuses_to_derive_a_force_from_a_speed_alone():
    state = setup_agent.SetupState(model=a_case().model, sector_deg=18.0)
    action = setup_agent.Action.model_validate(
        {"action": "check_load", "rpm": 15000.0}
    )
    with pytest.raises(StructuralError) as exc:
        setup_agent._check_load(action, state)
    assert exc.value.diagnostic.code == "no_blade"


def test_an_unknown_alloy_is_refused_with_the_ones_that_are_known():
    state = setup_agent.SetupState(model=a_case().model)
    action = setup_agent.Action.model_validate(
        {"action": "lookup_material", "material_name": "Ti-6Al-4V"}
    )
    with pytest.raises(StructuralError) as exc:
        setup_agent._lookup_material(action, state)
    assert exc.value.diagnostic.code == "unknown_alloy"
    assert "GH4169" in exc.value.diagnostic.message


def test_looking_up_the_alloy_in_the_table_returns_its_card():
    state = setup_agent.SetupState(model=a_case().model)
    action = setup_agent.Action.model_validate({
        "action": "lookup_material", "material_name": "Inconel 718",
        "temperature_c": 500.0,
    })
    result = setup_agent._lookup_material(action, state)["result"]
    assert result["name"] == "GH4169"
    assert result["at_temperature"]["young_mpa"] == pytest.approx(178000.0)
    assert result["source"].strip()
