"""Deciding what the simulation is, from a description of it.

Every other stage answers a question about the part. This one answers
questions about the *job*: how fast it turns, how hot it runs, what it is made
of, and what pulls on it. Those are not measurements - they are the user's
decisions - so the chain's oldest rule applies with full force: nothing here
invents one. Before this stage existed the decisions arrived as a hand-written
parameter file and were copied through untouched; now they can also arrive as
prose, and the agent's job is to turn one into the other without adding a
number that was not said.

The seam it fills was visible in the D27 runs. The blade force was a
smoke-test 10 kN while the part's own rim carried thousands of kN of
centrifugal load, so the fir-tree showed no sign of the load at all - and the
number that *would* have shown it, one blade's mass times omega squared times
its radius, was worked out on paper outside the chain. A number derived on
paper is a number nobody can check later. Here it is derived by something that
writes down what it did.

Two rules the prompt states and the tools enforce. A value the description
does not give is asked for, never filled in from a similar machine. And a
value the description *does* give is checked against the part before it is
used, because a bore radius or an outer radius that does not match the model
is a description of a different component.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from seekflow_structural.case.model import Case, ModelFacts
from seekflow_structural.core.structural_intent_models import (
    BladeLoadIntent,
    ConstraintIntent,
    MaterialIntent,
    RotationIntent,
    TemperatureIntent,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline import params as params_module
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.runtime.loop import (
    AgentSpec,
    ToolAction,
    dispatch_table,
    exhausted_final,
    run_agent,
)
from seekflow_structural.tools import materials

# How much of a sector may be described before the load arithmetic stops
# meaning anything. A part repeated twenty times has one slot in an 18 degree
# sector; asking for a single slot's worth over a sector holding three is a
# question the tool can still answer, but it has to say which it answered.
MAX_SLOTS_IN_SECTOR = 64


class Action(ToolAction):
    """The setup agent's tool call.

    The five sections are the models the deck itself validates against, nested
    here unchanged. That is deliberate: what the agent submits is not a
    description of a material or a load that something later has to
    interpret - it is the same object the solver's input is built from, so
    there is no translation step where the two can disagree.
    """

    action: Literal[
        "get_part_facts",
        "list_alloys",
        "lookup_material",
        "check_load",
        "check_setup",
        "submit_setup",
        "needs_input",
    ]

    # lookup_material
    material_name: str = Field(
        default="", description="the alloy to look up, by any name it is known by"
    )
    temperature_c: float = Field(
        default=0.0,
        description=(
            "the temperature to report the alloy's properties at, in C. "
            "Properties of a metal vary with temperature, and a run at 650 C "
            "needs the 650 C curve, not the one at room temperature."
        ),
    )

    # check_load
    rpm: float = Field(default=0.0, description="rotation speed, rev/min")
    blade_mass_kg: float = Field(
        default=0.0, description="the mass of one blade, in kg"
    )
    centre_of_mass_radius_mm: float = Field(
        default=0.0,
        description=(
            "the radius the blade's own centre of gravity turns at, in mm - "
            "not the tip radius and not the root radius"
        ),
    )
    blades_per_slot: int = Field(
        default=1, description="how many blades one fir-tree slot carries"
    )
    slots_in_the_part: int = Field(
        default=0,
        description=(
            "how many slots the whole part has, from the description. 0 means "
            "it was not stated, and only one blade's own force is reported."
        ),
    )
    thickness_fraction_modelled: float = Field(
        default=0.0,
        description=(
            "leave at 0. The fraction of the part's thickness this model "
            "represents is decided by the domain - a model built on the "
            "mid-plane is half the thickness and carries half the load - and "
            "the tool reads it from there. State a value only to override it, "
            "and the answer will say whether it agrees with the domain."
        ),
    )

    # check_setup / submit_setup - the parameter document, section by section
    rotation: RotationIntent | None = None
    temperature: TemperatureIntent | None = None
    material: MaterialIntent | None = None
    blade_load: BladeLoadIntent | None = None
    constraints: ConstraintIntent | None = None
    rationale: str = ""
    questions: list[str] = Field(default_factory=list)


@dataclass
class SetupState:
    """What the tools share: the part, the piece being analysed, the words."""

    model: ModelFacts | None = None
    sector_deg: float | None = None
    theta_low_deg: float = 0.0
    # Whether the analysed model is half the part's thickness, from the
    # domain's own choice of symmetry plane. Read here rather than asked of
    # the agent: it is a consequence of what is being analysed, and an agent
    # guessing it wrong doubles or halves the load.
    half_thickness: bool = False
    brief: str = ""
    submitted: dict | None = None
    checks: list[dict] = field(default_factory=list)


def _get_part_facts(action, state: SetupState) -> dict:
    """What the part is, and which piece of it is being analysed.

    Both halves matter to this agent and neither is guessable from the
    description: a bore radius stated in prose is only usable once it can be
    held against the bore the frame stage measured, and a load stated per
    blade is only usable once it is known how much of the part this model
    covers.
    """
    model = state.model
    if model is None:
        raise StructuralError(
            "no_model", "the frame stage has not measured the part yet", "setup"
        )
    bounds_min = model.bounds_min_mm.as_tuple()
    bounds_max = model.bounds_max_mm.as_tuple()
    return {
        "ok": True,
        "result": {
            "outer_radius_mm": model.r_max_mm,
            "bore_radius_mm": model.bore_radius_mm,
            "axial_extent_mm": [bounds_min[2], bounds_max[2]],
            "face_count": model.face_count,
            "has_rotation_axis": model.has_rotation_axis,
            "axis_origin_mm": (
                model.frame.axis_origin_mm.as_tuple() if model.frame else None
            ),
            "axis_direction": (
                model.frame.axis_direction.as_tuple() if model.frame else None
            ),
            "symmetry_planes": [
                {
                    "id": plane.id,
                    "normal": plane.normal.as_tuple(),
                    "origin_mm": plane.origin_mm.as_tuple(),
                    "matched_area_fraction": plane.matched_area_fraction,
                    "note": plane.note,
                }
                for plane in model.symmetry_planes
            ],
            "being_analysed": {
                "sector_deg": state.sector_deg,
                "theta_low_deg": state.theta_low_deg,
                "whole_part": state.sector_deg is None,
                "half_thickness": state.half_thickness,
            },
            "note": (
                "the extents and the axis are measurements of the model, and "
                "the symmetry planes are candidate mirrors with the fraction "
                "of the surface each one maps onto itself. What is being "
                "analysed is the domain decision: a sector of that many "
                "degrees, or the whole part."
            ),
        },
    }


def _list_alloys(action, state: SetupState) -> dict:
    return {"ok": True, "result": {"alloys": materials.describe()}}


def _lookup_material(action, state: SetupState) -> dict:
    if not action.material_name.strip():
        raise StructuralError(
            "no_material_named", "lookup_material needs a material name", "setup"
        )
    try:
        found = materials.lookup(
            action.material_name, action.temperature_c or None
        )
    except KeyError as exc:
        # The table's contents travel with the refusal. An agent told only
        # "not found" will try the same name again spelled differently.
        raise StructuralError("unknown_alloy", str(exc), "setup") from exc
    found["note"] = (
        "the points are the material card itself and can be submitted as "
        "they stand; they are not to be retyped. Every value here carries "
        "the source above it."
    )
    return {"ok": True, "result": found}


def _check_load(action, state: SetupState) -> dict:
    """One blade's centrifugal force, and what this model has to carry.

    The arithmetic is the reason this tool exists. A load stated as a force
    and a load stated as a blade are the same load only after three things are
    accounted for: the blade's own mass, the radius its centre of gravity
    turns at, and how much of the part this model stands for. Done on paper
    none of it is checkable afterwards.
    """
    if action.rpm <= 0:
        raise StructuralError("no_rpm", "check_load needs the rpm", "setup")
    if action.blade_mass_kg <= 0 or action.centre_of_mass_radius_mm <= 0:
        raise StructuralError(
            "no_blade",
            "check_load needs the blade's mass and the radius its centre of "
            "gravity turns at. A force cannot be derived from a speed alone.",
            "setup",
        )
    omega = action.rpm * 2.0 * math.pi / 60.0
    blade_force = (
        action.blade_mass_kg
        * (action.centre_of_mass_radius_mm / 1000.0)
        * omega
        * omega
    )
    result = {
        "blade_mass_kg": action.blade_mass_kg,
        "centre_of_mass_radius_mm": action.centre_of_mass_radius_mm,
        "rpm": action.rpm,
        "omega_rad_s": round(omega, 6),
        "omega_squared": round(omega * omega, 6),
        "one_blade_force_n": round(blade_force, 6),
        "formula": "F = m * omega^2 * r_cg",
        "blades_per_slot": action.blades_per_slot,
    }
    per_slot = blade_force * action.blades_per_slot
    result["force_per_slot_n"] = round(per_slot, 6)

    if action.slots_in_the_part <= 0 or state.sector_deg is None:
        result["sector"] = None
        result["note"] = (
            "only one slot's load is reported. How much the analysed model "
            "carries needs the number of slots in the part and the sector "
            "being analysed; supply slots_in_the_part to have it worked out."
        )
        return {"ok": True, "result": result}

    pitch = 360.0 / action.slots_in_the_part
    slots_in_sector = state.sector_deg / pitch
    if slots_in_sector > MAX_SLOTS_IN_SECTOR:
        raise StructuralError(
            "implausible_slot_count",
            f"a {state.sector_deg:g} degree sector of a part with "
            f"{action.slots_in_the_part} slots holds {slots_in_sector:.3f} "
            "slots, which is too many to be a sector of this part. Check the "
            "slot count against the geometry before using this.",
            "setup",
        )
    full = per_slot * slots_in_sector
    # The thickness fraction belongs to the domain, not to the description:
    # a model built on the mid-plane is half the part and carries half the
    # load, and that was decided two stages ago. An agent left to state it
    # would be guessing at something already settled, and a guess of 1.0 where
    # the answer is 0.5 doubles the load without anything downstream noticing.
    from_domain = 0.5 if state.half_thickness else 1.0
    stated = action.thickness_fraction_modelled
    used = stated if stated > 0 else from_domain
    result["sector"] = {
        "slot_pitch_deg": round(pitch, 6),
        "sector_deg": state.sector_deg,
        "slots_in_the_sector": round(slots_in_sector, 6),
        "full_thickness_force_n": round(full, 6),
        "thickness_fraction_modelled": used,
        "thickness_fraction_source": (
            "stated by the caller" if stated > 0
            else (
                "the domain uses a mid-plane symmetry plane, so this model is "
                "half the thickness" if state.half_thickness
                else "the domain uses no mid-plane symmetry, so the whole "
                     "thickness is modelled"
            )
        ),
        "force_this_model_must_carry_n": round(full * used, 6),
    }
    if stated > 0 and abs(stated - from_domain) > 1e-9:
        result["sector"]["disagrees_with_the_domain"] = (
            f"you stated {stated}, and the domain's symmetry choice implies "
            f"{from_domain}. One of the two is wrong, and the load differs by "
            "that factor."
        )
    result["note"] = (
        "force_this_model_must_carry_n is what has to be applied to the "
        "faces in the analysed sector. `mass_centroid_rpm` computes one "
        "slot's worth and multiplies by blades_per_slot, so it can express "
        "the slot count but not the thickness fraction; "
        "`equivalent_total_force` takes the figure directly."
    )
    return {"ok": True, "result": result}


def _document(action: Action) -> dict:
    """The submitted sections, in the parameter file's own shape."""
    document: dict = {}
    for name in ("rotation", "temperature", "material", "blade_load",
                 "constraints"):
        section = getattr(action, name)
        if section is not None:
            document[name] = section.model_dump(mode="json", exclude_none=True)
    return document


def _checked(action: Action, state: SetupState) -> tuple[dict, list[dict]]:
    """The document, and every way it fails to describe this part.

    Raises for the things that make the document unusable - a missing
    section, a section that does not validate - and returns the things that
    merely disagree, which the caller may judge. The distinction is the one
    the rest of the package draws: a missing input is a refusal, a pair of
    numbers that differ is a measurement.
    """
    document = _document(action)
    missing = [
        name for name in params_module.REQUIRED_SECTIONS
        if not document.get(name)
    ]
    if missing:
        raise StructuralError(
            "incomplete_setup",
            "the simulation cannot be defined without " + ", ".join(missing)
            + ". Ask for what is missing rather than supplying a plausible "
            "value.",
            "setup",
        )
    if not action.constraints:
        # Not a style preference: the deck this chain writes refuses to run
        # without cyclic symmetry and the mid-plane constraint, so a setup
        # that omits them is one the run will reach the deck stage to reject.
        raise StructuralError(
            "incomplete_setup",
            "the constraints are not stated. This chain writes a sector deck "
            "that needs to know whether the part is cyclic and whether the "
            "mid-plane is a mirror; state both.",
            "setup",
        )
    try:
        physics = params_module.physics_from_params(document, "submitted setup")
    except params_module.ParamsIncomplete as exc:
        raise StructuralError("incomplete_setup", str(exc), "setup") from exc
    findings = params_module.check_consistency(physics, state.model)
    return document, [
        {
            "quantity": finding.quantity,
            "stated": finding.stated,
            "measured": finding.implied,
            "relative_difference": finding.relative_difference,
            "note": finding.note,
        }
        for finding in findings
    ]


def _check_setup(action, state: SetupState) -> dict:
    """Everything `submit_setup` would say, without submitting.

    A submission ends the run, so an agent that could only learn by submitting
    would have one attempt at getting five sections right together. This is
    the same check on its own, which is what makes the attempt an informed
    one.
    """
    document, findings = _checked(action, state)
    state.checks.append({"document": document, "findings": findings})
    return {
        "ok": True,
        "result": {
            "sections": sorted(document),
            "agreements": [f for f in findings
                           if not (f["relative_difference"] or 0.0)],
            "disagreements": [f for f in findings
                              if (f["relative_difference"] or 0.0) > 0.0],
            "note": (
                "the disagreements are the stated values against the part "
                "that was measured. They are not errors - the part may be "
                "what is wrong - but a bore or an outer radius that does not "
                "match the model is a description of a different component, "
                "and the run should not proceed on one without saying so."
            ),
        },
    }


def _submit_setup(action, state: SetupState) -> dict:
    if not action.rationale.strip():
        raise StructuralError(
            "no_rationale",
            "a submission states where each value came from - which the "
            "description gave, which the material table gave, and which was "
            "worked out. A parameter set with no account of itself cannot be "
            "checked by anyone later.",
            "setup",
        )
    document, findings = _checked(action, state)
    state.submitted = {
        "accepted": True,
        "parameters": document,
        "consistency": findings,
        "rationale": action.rationale,
    }
    return {
        "ok": True,
        "result": {
            "accepted": True,
            "sections": sorted(document),
            "disagreements": [f for f in findings
                              if (f["relative_difference"] or 0.0) > 0.0],
            "rationale": action.rationale,
        },
    }


def _needs_input(action, state: SetupState) -> dict:
    return {
        "ok": True,
        "result": {"accepted": False, "questions": action.questions},
    }


class CommitAction(Action):
    """The last call: define the simulation, or say what is missing."""

    action: Literal["submit_setup", "needs_input"]


DISPATCH = dispatch_table({
    "get_part_facts": _get_part_facts,
    "list_alloys": _list_alloys,
    "lookup_material": _lookup_material,
    "check_load": _check_load,
    "check_setup": _check_setup,
    "submit_setup": _submit_setup,
    "needs_input": _needs_input,
})

SYSTEM_PROMPT = """\
You are setting up a structural finite element analysis. Someone has described
a machine and a duty in words; your job is to turn that description into the
values the solve needs, and nothing else. The geometry is not yours to decide
and neither is which piece of the part gets analysed - both are already
settled by the time you are called.

What the run needs from you:

- rotation    how fast it turns, and about which axis
- temperature how hot it runs, as a field over the part
- material    what it is made of
- blade_load  what pulls on it, and how that load reaches the material
- constraints how the part is held

Principles you must apply:

- A value the description does not give is not yours to supply. Do not use a
  typical value, a remembered figure, or one from a similar machine. Say
  needs_input and ask for it. A run built on an invented number is worse than
  no run: it produces a number that looks like an answer.
- Everything you state has a provenance, and the `source` field on each
  section is where you state it - which sentence of the description, which
  material table entry, or which calculation. Write it as something a reader
  could check.
- The description may state a value that the part disagrees with. That is
  worth finding before the solve, not after, so check what you are about to
  submit against the measured part and report the gap in your rationale. Do
  not silently reconcile the two and do not silently ignore it.

Your tools:

- get_part_facts: what the model is - outer radius, bore, axial extent, the
  measured rotation axis, and how well each candidate symmetry plane maps the
  surface onto itself - and which sector of it is being analysed. Read this
  before you submit anything with a radius in it, so the radii you state are
  the part's own.
- list_alloys: which alloys have property data available, each with what
  temperature range it covers and where its numbers came from. An alloy that
  is not here has no data, whatever its name suggests - ask for the
  properties instead.
- lookup_material: one alloy's properties, and optionally its values at a
  given temperature. Properties of a metal vary with temperature; take the
  curve, not a single point, and submit it as it comes back rather than
  retyping the numbers.
- check_load: works out what pulling force a blade exerts, from its mass, the
  radius its centre of gravity turns at, and the speed - and what the
  analysed model has to carry once the number of slots and the fraction of
  the thickness this model represents are accounted for. Use it rather than
  doing the arithmetic yourself, and use its answer in the load you submit.
- check_setup: everything submit_setup would say, without submitting. It
  reports what you stated against what the part measures. Call it before you
  submit.
- submit_setup: state the five sections.

The five sections are the exact structures the solver's input is built from,
so a submission that does not fit them is rejected with the reason. State
every one of them; a section left out is a question rather than a default.

Your last call offers only submit_setup and needs_input. Budget the rest
accordingly.
"""


def spec(*, brief: str, max_calls: int = 14) -> AgentSpec:
    return AgentSpec(
        name="setup",
        tool_name="setup_action",
        tool_description=(
            "Inspect the part or the material table, check a load or a "
            "parameter set, or submit the simulation's parameters."
        ),
        action_model=Action,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "Here is the description of the simulation to set up.\n\n"
            "---\n" + brief.strip() + "\n---\n\n"
            "Start with get_part_facts, then work through the sections. Ask "
            "for anything the description does not give."
        ),
        submit_actions=frozenset({"submit_setup", "needs_input"}),
        max_calls=max_calls,
        timeout_s=300,
        terminal_model=CommitAction,
    )


def to_case_physics(payload: dict, source: str):
    """The submitted document, as the case's physics."""
    physics = params_module.physics_from_params(payload["parameters"], source)
    return physics


def setup(ctx: RunContext, *, api_key_file: Path | None = None,
          max_calls: int = 14) -> Case:
    """The stage: fix the physics, from the file if there is one, else the brief.

    A written parameter file wins over a brief when both are supplied. Not
    because it was written first, but because a person who typed a number
    meant that number, and an agent reading prose around it is not entitled
    to overrule them.
    """
    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "setup has no case", "setup")

    if ctx.params:
        source = ctx.params_path or "parameter file"
        physics = params_module.physics_from_params(ctx.params, source)
        physics.consistency = params_module.check_consistency(
            physics, case.model
        )
        case.physics = physics
        ctx.job.event({
            "kind": "physics_defined",
            "stage": "setup",
            "from": "parameter file",
            "source": source,
            "load_model": physics.blade_load.model,
            "comparisons": len(physics.consistency),
        })
        return case

    if not ctx.brief.strip():
        raise StructuralError(
            "no_parameters",
            "the run was given neither a parameter file nor a brief, so there "
            "is nothing to say what the simulation is",
            "setup",
        )

    from seekflow_structural.pipeline.materialize import _has_axial_symmetry
    from seekflow_structural.runtime.caller import build_caller

    domain = case.domain
    state = SetupState(
        model=case.model,
        sector_deg=(domain.sector_deg if domain else None),
        theta_low_deg=(domain.theta_low_deg if domain else 0.0),
        # Decided by the plane's normal against the axis, the same way the
        # mesher decides it, so the two cannot disagree about whether the
        # model is half a part.
        half_thickness=bool(
            case.model and domain and _has_axial_symmetry(case.model, domain)
        ),
        brief=ctx.brief,
    )
    caller, model_config = build_caller(api_key_file)
    outcome = run_agent(
        spec(brief=ctx.brief, max_calls=max_calls), caller=caller,
        model_config=model_config, dispatch=DISPATCH, context=state,
    )
    ctx.charge_tool_calls(outcome.calls, "setup")
    ctx.job.write("agent/setup.json", {
        "schema_version": "setup_run_v1",
        "trace": outcome.trace,
        "rejected_calls": outcome.rejected,
        "final": outcome.final,
        "checks": state.checks,
        "calls": outcome.calls,
        "exhausted": outcome.exhausted,
    })

    final = outcome.final or exhausted_final("setup")
    if not final.get("accepted"):
        raise StructuralError(
            "setup_not_defined",
            "the setup agent did not define the simulation: "
            + "; ".join(final.get("questions", [])),
            "setup",
        )
    if state.submitted is None:
        raise StructuralError(
            "setup_not_defined",
            "the setup agent reported a submission it did not make",
            "setup",
        )

    document = state.submitted["parameters"]
    # Written out in the parameter file's own shape, so the next run of the
    # same case can be given it directly and the agent's reading stops being
    # something that only existed inside a conversation.
    ctx.job.write("params.resolved.json", document)

    source = ctx.brief_path or "brief"
    physics = to_case_physics(state.submitted, source)
    physics.consistency = params_module.check_consistency(physics, case.model)
    case.physics = physics
    ctx.job.event({
        "kind": "physics_defined",
        "stage": "setup",
        "from": "brief",
        "source": source,
        "load_model": physics.blade_load.model,
        "blade_force_n": (
            physics.blade_load.total_force_n_per_slot
            if physics.blade_load else None
        ),
        "comparisons": len(physics.consistency),
        "disagreeing": [
            finding.quantity for finding in physics.consistency
            if (finding.relative_difference or 0.0) > 0.0
        ],
    })
    return case


__all__ = ["Action", "SetupState", "setup", "spec", "to_case_physics"]
