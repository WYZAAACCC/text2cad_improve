"""Deciding where the mesh spends its resolution.

A refinement plan is a prediction. The harness turns it into mesh facts the
agent cannot get any other way - how many elements it actually cost, how many
came out badly shaped, and the size actually achieved per region - and the
agent revises against those.

Two things changed from the standalone version.

The load radius is no longer accepted from outside. It is read from the case,
where the stage that chose the load faces measured it. That is the fix for the
seam where a mesh was refined at radius 288 for faces that sat at 212.67: a
number supplied separately is a number that can be stale, and this one cannot
be supplied at all.

A region is described rather than named by a radius. The previous vocabulary
was "distance from the global Z axis", which can only express a full annulus -
a bracket's bolt hole or a blade's tip could not be refined at all. A region
is now a sphere, a cylinder, a box, or "within this distance of these faces",
and the last of those needs no axis at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_structural.case.model import (
    MeshPlan,
    MeshRegion,
    Vec3,
    Written,
)
from seekflow_structural.core.mesh_feedback import convergence_check, measure
from seekflow_structural.core.mesh_profile import build_profile
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.runtime.loop import (
    AgentSpec,
    ToolAction,
    dispatch_table,
    exhausted_final,
    run_agent,
)

BANDS_PER_PAGE = 24


class RegionSpec(ToolAction):
    """One place resolution is spent, described geometrically.

    `kind` selects the shape, and the three shapes are the ones the mesher can
    size on - each is a distance it can evaluate. There is deliberately no
    "near these faces": the mesher places resolution by distance and has no
    way to express proximity to a face set, and a region offered here that
    could not be honoured would be silently meshed as something else. The
    load path is named by where it is - its radius, or the point it acts
    through - which `get_geometry` reports.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["cylinder", "sphere", "box"] = Field(
        default="cylinder",
        description=(
            "the shape the target size applies within. 'cylinder' is a band "
            "at radius_mm from the rotation axis, unbounded axially; "
            "'sphere' is everything within radius_mm of center_mm; 'box' is "
            "everything inside min_mm..max_mm. Outside the shape the size "
            "ramps back to the web size over ramp_mm."
        ),
    )
    size_mm: float = Field(description="target element size inside the shape")
    ramp_mm: float = Field(
        description=(
            "how far outside the shape the size takes to return to the web "
            "size"
        )
    )
    center_mm: list[float] = Field(
        default_factory=list,
        description="a sphere's centre, [x, y, z] in mm",
    )
    radius_mm: float | None = Field(
        default=None,
        description=(
            "a cylinder's radius from the rotation axis, or a sphere's radius"
        ),
    )
    half_height_mm: float | None = Field(
        default=None, description="unused; kept so a saved plan reloads"
    )
    min_mm: list[float] = Field(
        default_factory=list, description="a box's lower corner [x, y, z]"
    )
    max_mm: list[float] = Field(
        default_factory=list, description="a box's upper corner [x, y, z]"
    )
    rationale: str = ""


class Action(ToolAction):

    action: Literal[
        "get_geometry",
        "inspect_radial_profile",
        "mesh_and_measure",
        "convergence_check",
        "submit_refinement",
        "needs_input",
    ]
    band_offset: int = 0
    band_limit: int = BANDS_PER_PAGE
    web_size_mm: float = 0.0
    regions: list[RegionSpec] = Field(default_factory=list)
    rationale: str = ""
    questions: list[str] = Field(default_factory=list)


class CommitAction(Action):
    """The action model for the agent's last call: decide, or say why not.

    Measured on D27: `convergence_check` on the plan the agent intended to
    submit cost two meshes and two solves, and by the time it came back the
    twelve-call budget was gone - so the run ended with a plan the agent had
    already measured and never submitted. The last call offers only the two
    actions that end the run. It does not say which plan is right; the agent
    still chooses.
    """

    action: Literal["submit_refinement", "needs_input"]


SYSTEM_PROMPT = """\
You are an FEA mesh planning engineer. Decide the element size per region for
a 3D solid that will be solved with quadratic tetrahedra under a known load
and rotation.

Principles you must apply:

- An element must be small enough to represent the geometry it covers. Where
  the surface carries small features - short edges, tight fillets - a coarse
  element cannot represent them, and the local stiffness and stress will be
  wrong.
- Stress concentrates where the load path changes direction and at geometric
  discontinuities. The region carrying the load must be resolved finely enough
  for the traction to be transferred without spurious peaks.
- Away from discontinuities and load paths the gradients are low and coarse
  elements are correct. Refining there spends budget and buys nothing.
- The budget is finite. Spend it where the answer is decided.

Do not assume this part is any particular machine component and do not apply a
remembered recipe. The load radius you are given was measured from the faces
the load actually enters through, so treat it as where the traction is.

Your tools:

- get_geometry: overall size, volume and the load radius. The load radius is
  a measurement from the assembly stage; you cannot be given a different one.
- inspect_radial_profile: per radial band, the surface area and the shortest
  surface edge - the size of the smallest geometry in that band. Derive your
  regions from those numbers and from the load radius, and state the
  connection in each rationale.
- mesh_and_measure: build the mesh and report what it cost. Real element
  count, how far over or under the budget, how many elements came out badly
  shaped, and the size actually achieved per band. Use it on any plan you are
  seriously considering, and revise if it is over budget or produces many bad
  elements. A plan that ignores measured feedback is a failed plan.
- convergence_check: mesh and solve at two levels and report how much the
  answer moved between them. Call it once, on the plan you intend to submit,
  to learn whether the numbers you are about to report have settled. Global
  fields usually converge; a peak sampled at a stress concentration often does
  not, and whether that is a real concentration or an artefact of where the
  load is applied is a judgement for the post-processing stage - report what
  you measured rather than concluding.

Each region is a target size at a place, ramping linearly back to the web size
over ramp_mm. Regions overlap by taking the minimum. The place is one of three
shapes, and the size applies throughout it:

- cylinder: a band at radius_mm from the rotation axis, of unlimited axial
  extent. This is how a load path at a known radius is named.
- sphere: everything within radius_mm of center_mm. This is how a place that
  is a point - the load's own centroid, a boss - is named.
- box: everything inside min_mm..max_mm. This is how a region bounded in all
  three directions is named.

There is no "near these faces": the mesher places resolution by distance and
cannot size on proximity to a face set. If what you want to refine is the load
path, name it by where it is - get_geometry reports the load radius and the
point the traction acts through, and both are measurements, not restatements
of what you were told.

The load path must be resolved by some region, or the traction cannot be
transferred and the plan is refused. A region reaches the load when it
contains the load's own point, or when its ramp covers the distance to it.
"""


@dataclass
class MeshState:
    bundle: Path
    step: Path
    work_dir: Path
    profile: dict
    load_radius_mm: float
    load_face_centroids: list[list[float]] = field(default_factory=list)
    base_config: dict = field(default_factory=dict)
    element_budget: int = 150_000
    mesh_report: dict | None = None
    submitted: dict | None = None
    # Whether the two-level study behind the run's noise floor has been run.
    # The agent may run it early with the tool; the stage runs it before
    # closing if the agent did not - see `_ensure_convergence`.
    convergence_run: bool = False


def _geometry(action, state: MeshState) -> dict:
    keys = (
        "r_min_mm", "r_max_mm", "total_volume_mm3", "total_surface_area_mm2",
        "characteristic_thickness_mm", "band_count",
    )
    out = {key: state.profile.get(key) for key in keys}
    out["load_radius_mm"] = state.load_radius_mm
    out["element_budget"] = state.element_budget
    out["load_face_centroids_mm"] = state.load_face_centroids
    return {"ok": True, "result": out}


def _profile(action, state: MeshState) -> dict:
    bands = state.profile["bands"]
    offset = max(0, action.band_offset)
    limit = max(1, min(action.band_limit, BANDS_PER_PAGE))
    return {
        "ok": True,
        "result": {
            "bands": bands[offset: offset + limit],
            "total": len(bands),
            "offset": offset,
            "load_radius_mm": state.load_radius_mm,
        },
    }


def _config_from(state: MeshState, web_size: float, regions) -> dict:
    """Fold a proposal into the case's base mesh config.

    The geometry block is already derived from the case and is not touched;
    only the refinement is replaced. That is the whole reason a stale sector
    angle can no longer survive in a config file.

    Each region's own shape is carried through as the shape it was declared
    as. This used to collapse every kind to a single `r_center_mm` - the
    radius of the region's centre - so a sphere of radius 300 centred on the
    origin arrived at the mesher as "refine at radius 0". Measured on D27: the
    agent asked for a fine region at the load path and a coarse web, and every
    zone became an annulus about the axis, which is the one place the part has
    no material at all.
    """
    config = json.loads(json.dumps(state.base_config))
    zones = []
    for region in regions:
        row = region if isinstance(region, dict) else region.model_dump()
        kind = row.get("kind") or "cylinder"
        zone = {
            "name": row["name"],
            "kind": kind,
            "size_mm": row["size_mm"],
            "ramp_mm": row["ramp_mm"],
        }
        if kind == "cylinder":
            # A cylinder is named by its radius from the rotation axis, which
            # is what the mesher sizes on, so the two spellings are collapsed
            # here rather than being passed along as two numbers that could
            # disagree.
            radius = row.get("radius_mm")
            if radius is None and row.get("center_mm"):
                centre = row["center_mm"]
                radius = (centre[0] ** 2 + centre[1] ** 2) ** 0.5
            if radius is None:
                raise StructuralError(
                    "region_needs_radius",
                    f"region {row['name']}: a cylinder needs radius_mm, the "
                    "distance from the rotation axis",
                    "mesh",
                )
            zone["r_center_mm"] = float(radius)
        elif kind == "sphere":
            centre = row.get("center_mm") or []
            if len(centre) != 3 or row.get("radius_mm") is None:
                raise StructuralError(
                    "region_needs_centre",
                    f"region {row['name']}: a sphere needs center_mm with "
                    "three components and a radius_mm",
                    "mesh",
                )
            zone["center_mm"] = [float(v) for v in centre]
            zone["radius_mm"] = float(row["radius_mm"])
        elif kind == "box":
            low = row.get("min_mm") or []
            high = row.get("max_mm") or []
            if len(low) != 3 or len(high) != 3:
                raise StructuralError(
                    "region_needs_corners",
                    f"region {row['name']}: a box needs min_mm and max_mm "
                    "with three components each",
                    "mesh",
                )
            zone["min_mm"] = [float(v) for v in low]
            zone["max_mm"] = [float(v) for v in high]
        zones.append(zone)

    config["mesh"]["refinement"] = {"web_size_mm": web_size, "zones": zones}
    sizes = [zone["size_mm"] for zone in zones]
    config["mesh"]["size_min_mm"] = min([0.4] + sizes)
    config["mesh"]["size_max_mm"] = max([web_size, 8.0])
    return config


def _mesh_and_measure(action, state: MeshState) -> dict:
    if not action.regions:
        raise StructuralError(
            "no_regions", "mesh_and_measure requires regions", "mesh"
        )
    config = _config_from(state, action.web_size_mm, action.regions)
    report = measure(config, state.work_dir / "candidate", state.element_budget)
    state.mesh_report = report
    return {"ok": True, "result": report}


def _run_convergence(state: MeshState, web_size, regions) -> dict:
    """Mesh and solve at two levels, leaving both results on disk.

    `results.mesh_noise_floor` reads what this writes, and the loop's scoring
    reads the floor from there: how far this run's own numbers move when only
    the mesh changes. A run that never gets here reports no floor at all,
    which is not the same as a floor of zero.
    """
    config = _config_from(state, web_size, regions)
    case = {
        "bundle": str(state.bundle),
        "face_intent": str(state.work_dir / "face_intent.json"),
        "intent_template": str(state.work_dir / "intent.json"),
        "element_budget": state.element_budget,
    }
    result = convergence_check(config, case, state.work_dir / "convergence")
    state.convergence_run = True
    return result


def _ensure_convergence(ctx: RunContext, case, state: MeshState) -> None:
    """Run the study unless something already did, on the plan that was built.

    The study used to be reachable only as a tool the agent might call, and
    both ways of not calling it were measured:

    - A supplied plan runs with no agent at all, so nothing called it, and
      every revision of the first controlled comparison closed with
      `floors: {}` and fell back to the constant.
    - An agent with the tool available submitted after thirteen calls without
      ever calling it, nine of them the same repeated inspection, and that
      revision reported no floor either.

    So it belongs to the stage rather than to the agent's judgement. The agent
    can still call it early - a plan informed by knowing how sensitive the
    part is to resolution is a better plan - and this only guarantees the
    measurement exists before the stage closes.

    A failure here is recorded and the stage continues. The agent path already
    tolerates one, because a tool that raises comes back as a tool reply, and
    a floor that is missing is a state the report already names; what it must
    not be is a state nobody can see.
    """
    if state.convergence_run:
        return
    plan = case.mesh
    try:
        _run_convergence(state, plan.web_size_mm, plan.regions)
        ctx.job.event({
            "kind": "convergence_checked",
            "stage": "mesh",
            "from": "run by the stage, on the plan it built",
            "web_size_mm": plan.web_size_mm,
        })
    except Exception as exc:
        ctx.job.event({
            "kind": "convergence_failed",
            "stage": "mesh",
            "error": f"{type(exc).__name__}: {exc}",
            "consequence": (
                "this revision reports no mesh noise floor, so a difference "
                "measured against it is compared with the constant instead of "
                "with a measurement of this part"
            ),
        })


def _convergence(action, state: MeshState) -> dict:
    if not action.regions:
        raise StructuralError(
            "no_regions", "convergence_check requires regions", "mesh"
        )
    return {
        "ok": True,
        "result": _run_convergence(state, action.web_size_mm, action.regions),
    }


def _submit(action, state: MeshState) -> dict:
    if not action.regions:
        raise StructuralError(
            "no_regions", "submit_refinement requires at least one region",
            "mesh",
        )
    if len(action.regions) > 6:
        raise StructuralError(
            "too_many_regions", "at most 6 refinement regions", "mesh"
        )
    if action.web_size_mm <= 0:
        raise StructuralError(
            "bad_web_size", "web_size_mm must be positive", "mesh"
        )

    r_min = float(state.profile.get("r_min_mm") or 0.0)
    r_max = float(state.profile.get("r_max_mm") or 0.0)
    for region in action.regions:
        if not (0.4 <= region.size_mm <= 12.0):
            raise StructuralError(
                "bad_size",
                f"region {region.name}: size_mm {region.size_mm} is outside "
                "the range this mesher accepts (0.4 to 12.0)",
                "mesh",
            )
        if region.ramp_mm <= 0:
            raise StructuralError(
                "bad_ramp",
                f"region {region.name}: ramp_mm must be positive", "mesh",
            )
        if not region.rationale.strip():
            raise StructuralError(
                "no_rationale",
                f"region {region.name}: a rationale is required", "mesh",
            )
        # A cylinder is named by a radius, so a radius outside the part is a
        # region that refines nothing. A sphere or a box is named by an
        # extent, and its centre sitting at the axis is not outside the part -
        # it is how a region that covers the part is written.
        if (region.kind or "cylinder") == "cylinder":
            radius = _region_radius(region)
            if not (r_min - 1e-6 <= radius <= r_max + 1e-6):
                raise StructuralError(
                    "region_outside_part",
                    f"region {region.name}: it refines radius {radius}, "
                    f"which is outside the part's {r_min}..{r_max}",
                    "mesh",
                )

    # The load path must be resolved, or the traction cannot be transferred.
    # This follows from where the load is, not from what the part is called.
    if not _resolves_load(action.regions, state):
        raise StructuralError(
            "load_not_resolved",
            f"no region reaches the load at radius {state.load_radius_mm} mm "
            f"({_load_point(state)}), which the assembly stage measured from "
            "the faces the load enters through. The load path has to be "
            "resolved: a cylinder at that radius, a sphere or box containing "
            "it, or any of those close enough that its ramp covers the "
            "distance.",
            "mesh",
        )

    state.submitted = {
        "accepted": True,
        "refinement": {
            "web_size_mm": action.web_size_mm,
            "regions": [r.model_dump(mode="json") for r in action.regions],
        },
        "rationale": action.rationale,
        "load_radius_resolved_mm": state.load_radius_mm,
    }
    return {"ok": True, "result": state.submitted}


def _region_radius(region: RegionSpec) -> float:
    if region.center_mm:
        centre = region.center_mm
        return (centre[0] ** 2 + centre[1] ** 2) ** 0.5
    return float(region.radius_mm or 0.0)


def _load_point(state: MeshState) -> list[float]:
    """Where the load acts, in the frame the regions are described in.

    The assembly stage measured the area-weighted centroid of the faces the
    load enters through, and the region the agent writes has to be compared
    against that same point - a radius alone cannot say whether a sphere
    centred off the load's azimuth actually covers it.
    """
    if state.load_face_centroids:
        return [float(v) for v in state.load_face_centroids[0]]
    return [state.load_radius_mm, 0.0, 0.0]


def _resolves_load(regions, state: MeshState) -> bool:
    """Whether any region puts resolution on the load, whatever shape it is.

    Each kind is asked the question in its own terms, because the question is
    "does this region reach the load", and the radius of a sphere's centre is
    not an answer to it. The old test compared every region's centre radius
    against the load radius, so a sphere of radius 300 centred on the axis -
    which contains the load - was read as "refines the axis, not the load",
    and refused; while a sphere genuinely centred at the load was the only
    shape that could pass.
    """
    point = _load_point(state)
    radius = float(state.load_radius_mm)
    for region in regions:
        kind = getattr(region, "kind", "cylinder") or "cylinder"
        ramp = float(region.ramp_mm)
        if kind == "cylinder":
            if abs(_region_radius(region) - radius) <= ramp + 1e-6:
                return True
        elif kind == "sphere":
            centre = region.center_mm or []
            if len(centre) != 3:
                continue
            distance = sum(
                (point[i] - centre[i]) ** 2 for i in range(3)
            ) ** 0.5
            if distance <= float(region.radius_mm or 0.0) + ramp + 1e-6:
                return True
        elif kind == "box":
            low, high = region.min_mm or [], region.max_mm or []
            if len(low) != 3 or len(high) != 3:
                continue
            outside = max(
                max(low[i] - point[i], point[i] - high[i], 0.0)
                for i in range(3)
            )
            if outside <= ramp + 1e-6:
                return True
    return False


def _needs_input(action, state: MeshState) -> dict:
    return {
        "ok": True,
        "result": {"accepted": False, "questions": action.questions},
    }


DISPATCH = dispatch_table({
    "get_geometry": _geometry,
    "inspect_radial_profile": _profile,
    "mesh_and_measure": _mesh_and_measure,
    "convergence_check": _convergence,
    "submit_refinement": _submit,
    "needs_input": _needs_input,
})


def spec(max_calls: int = 12) -> AgentSpec:
    return AgentSpec(
        name="mesh",
        tool_name="mesh_action",
        tool_description="Inspect geometry facts or submit a refinement plan.",
        action_model=Action,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "Call get_geometry and inspect_radial_profile to see the measured "
            "facts, then propose the refinement regions."
        ),
        submit_actions=frozenset({"submit_refinement", "needs_input"}),
        max_calls=max_calls,
        terminal_model=CommitAction,
    )


def to_case_mesh(payload: dict, element_budget: int, source: str) -> MeshPlan:
    refinement = payload["refinement"]
    regions = []
    for row in refinement["regions"]:
        centre = row.get("center_mm") or []
        regions.append(
            MeshRegion(
                name=row["name"],
                kind=row["kind"],
                size_mm=float(row["size_mm"]),
                ramp_mm=float(row["ramp_mm"]),
                center_mm=(
                    Vec3(x=centre[0], y=centre[1], z=centre[2])
                    if len(centre) == 3 else None
                ),
                radius_mm=row.get("radius_mm"),
                half_height_mm=row.get("half_height_mm"),
                min_mm=(
                    Vec3(x=row["min_mm"][0], y=row["min_mm"][1],
                         z=row["min_mm"][2])
                    if row.get("min_mm") else None
                ),
                max_mm=(
                    Vec3(x=row["max_mm"][0], y=row["max_mm"][1],
                         z=row["max_mm"][2])
                    if row.get("max_mm") else None
                ),
                face_indices=list(row.get("face_indices") or []),
                distance_mm=row.get("distance_mm"),
                rationale=row.get("rationale", ""),
            )
        )
    return MeshPlan(
        regions=regions,
        web_size_mm=float(refinement["web_size_mm"]),
        element_budget=element_budget,
        written=Written(
            by_stage="mesh", kind="agent_decision", source=source
        ),
    )


def mesh(ctx: RunContext, *, api_key_file: Path | None = None,
         max_calls: int = 12, element_budget: int = 150_000):
    """The stage: read the load radius from the case, run the agent."""
    from seekflow_structural.runtime.caller import build_caller

    from seekflow_structural.agents.assembly import load_radius_for_mesh

    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "mesh has no case", "mesh")

    work_dir = ctx.path / "mesh"
    work_dir.mkdir(parents=True, exist_ok=True)

    profile_path = ctx.path / "model" / "radial_profile.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    else:
        profile = build_profile(Path(case.bundle.path) / "model.step", 12)
        ctx.job.write("model/radial_profile.json", profile)

    centroids = _load_face_centroids(case)
    state = MeshState(
        bundle=Path(case.bundle.path),
        step=Path(case.bundle.path) / "model.step",
        work_dir=work_dir,
        profile=profile,
        # Read from the case. There is no argument that could carry a stale
        # copy of this number.
        load_radius_mm=load_radius_for_mesh(case),
        load_face_centroids=centroids,
        base_config=_base_config_from_case(case),
        element_budget=element_budget,
    )
    _stage_inputs(ctx, case, work_dir)

    # A plan handed to the run wins over asking for one. The reason it exists
    # is comparison: two revisions meshed by their own agents are meshed by two
    # different rules, and a peak that differs between them may differ because
    # one was resolved more finely. Measured on D27: revision one was meshed at
    # 1.0 mm at the rim and 8 mm in the web, revision two at 0.6 mm and 5 mm -
    # 240,051 nodes against 391,253 - over a change of one fillet radius from
    # 0.698 mm to 0.85 mm on a disc of radius 300 mm.
    if ctx.mesh_plan is not None:
        from seekflow_structural.case.model import MeshPlan, Written

        plan = dict(ctx.mesh_plan)
        plan["written"] = Written(
            by_stage="mesh", kind="user_input",
            source="a meshing plan supplied to the run, not chosen by the agent",
        )
        case.mesh = MeshPlan.model_validate(plan)
        # `_build_final_mesh` reads the refinement from the agent's
        # submission, and there is no agent here. Filling it with the supplied
        # plan is not a stand-in for a decision - it is the decision, made by
        # whoever handed the plan in. The geometry block of the config still
        # comes from this run's case, so the sector angle and the axial extent
        # are this model's and only the resolution is borrowed.
        state.submitted = {
            "refinement": {
                "web_size_mm": plan.get("web_size_mm"),
                "regions": plan.get("regions") or [],
            }
        }
        ctx.job.event({
            "kind": "mesh_planned",
            "stage": "mesh",
            "from": "supplied plan",
            "regions": [r.name for r in case.mesh.regions],
            "web_size_mm": case.mesh.web_size_mm,
        })
        built = _build_final_mesh(ctx, case, state)
        case.mesh.measured = built
        # There is no agent on this path, so nothing would call the study and
        # the revision would close with no floor. Run it here on the plan that
        # was built.
        _ensure_convergence(ctx, case, state)
        return case

    caller, model_config = build_caller(api_key_file)
    outcome = run_agent(
        spec(max_calls=max_calls), caller=caller,
        model_config=model_config, dispatch=DISPATCH, context=state,
    )
    # On the run's ledger as well as in the agent's own record. Without this
    # the stage closes reporting `tool_calls: 0` after the model was called a
    # dozen times, and the run's total means nothing.
    ctx.charge_tool_calls(outcome.calls, "mesh")
    ctx.job.write("agent/mesh.json", {
        "schema_version": "mesh_run_v1",
        "trace": outcome.trace,
        # Calls that did not match the action model, as they arrived. The
        # trace holds what the agent decided to do; when a run ends because
        # the model could not produce a well-formed call, these are the only
        # record of the call that ended it.
        "rejected_calls": outcome.rejected,
        "final": outcome.final,
        "calls": outcome.calls,
        "exhausted": outcome.exhausted,
    })
    final = outcome.final or exhausted_final("mesh")
    if not final.get("accepted"):
        raise StructuralError(
            "mesh_not_planned",
            "the meshing agent did not submit a plan: "
            + "; ".join(final.get("questions", [])),
            "mesh",
        )

    case.mesh = to_case_mesh(final, element_budget, str(case.bundle.path))

    # Building the mesh is not the agent's job; turning the plan it submitted
    # into the mesh the rest of the chain reads is. It goes where the
    # materialiser looks, and the selected faces are mapped onto its nodes
    # here, because the mapping needs the mesh that actually exists.
    built = _build_final_mesh(ctx, case, state)
    case.mesh.measured = built
    ctx.job.event({
        "kind": "mesh_planned",
        "stage": "mesh",
        "regions": [r.name for r in case.mesh.regions],
        "load_radius_mm": state.load_radius_mm,
        "elements": built.get("elements"),
        "mapped_face_count": built.get("mapped_face_count"),
    })
    # The agent may have run the study already; if it did not, run it on the
    # plan it submitted. Submitting without one costs the run its own noise
    # floor, and measured, an agent will do that - one submitted after
    # thirteen calls, nine of them the same repeated inspection, without ever
    # asking how much of its answer was the mesh.
    _ensure_convergence(ctx, case, state)
    return case


def _build_final_mesh(ctx: RunContext, case, state: MeshState) -> dict:
    """Build the submitted plan, then map the selected faces onto it.

    The mapping is the bridge between the faces the selection named and the
    nodes a load can be applied to. It runs against the mesh that exists,
    which is why it happens here rather than in the stage that chose the
    faces - a mapping against a mesh that has not been built yet would be a
    mapping against nothing.
    """
    from seekflow_structural.core.mesh_feedback import build_mesh
    from seekflow_structural.tools import geometry

    submitted = state.submitted or {}
    regions = (submitted.get("refinement") or {}).get("regions") or []
    config = _config_from(state, state.submitted["refinement"]["web_size_mm"],
                          regions)
    report = build_mesh(config, ctx.path / "mesh")

    surface = case.load_surface
    if surface is None:
        raise StructuralError(
            "no_load_surface",
            "the mesh cannot be mapped without the faces the assembly stage "
            "selected",
            "mesh",
        )
    mapping = geometry.map_selection_to_nodes(
        Path(case.bundle.path),
        surface.feature,
        surface.solid_index,
        surface.face_indices,
        ctx.path / "mesh" / "mesh.inp",
    )
    ctx.job.write("solve/selected_face_nodes.json", mapping)
    if mapping["union_node_count"] == 0:
        raise StructuralError(
            "mapping_empty",
            "the selected faces mapped to no mesh node. Either the mesh does "
            "not reach them, or they are not planar - the mapping handles "
            "planes only, and a curved selected face maps to nothing.",
            "mesh",
        )
    return {
        "elements": report.get("elements"),
        "nodes": report.get("nodes"),
        "min_sicn": (report.get("quality") or {}).get("min_sicn"),
        "mapped_face_count": mapping["mapped_face_count"],
        "union_node_count": mapping["union_node_count"],
    }


def _base_config_from_case(case) -> dict:
    from seekflow_structural.pipeline.materialize import mesh_config_from_case

    return mesh_config_from_case(case, None)


def _load_face_centroids(case) -> list[list[float]]:
    """Where the selected faces are, from the case, for the agent to refine near."""
    surface = case.load_surface
    if surface is None or surface.centroid_mm is None:
        return []
    return [list(surface.centroid_mm.as_tuple())]


def _stage_inputs(ctx: RunContext, case, work_dir: Path) -> None:
    """The files `convergence_check` needs, written from the case.

    Two of them, and the second was missing. `convergence_check` runs the
    structural chain on the two meshes it builds, and that chain reads an
    intent file - which nothing wrote, so the agent's first convergence check
    would have failed on a missing file rather than on anything about the
    mesh. It is written here from the case like every other value.

    Written before the agent runs because the agent is what calls it. The
    mesh and the mapping do not exist yet, and do not need to: the two paths
    below are placeholders that the check replaces with its own per level.
    """
    from seekflow_structural.pipeline.materialize import intent_from_case

    selection = ctx.path / "solve" / "selected_face_nodes.json"
    face_intent = work_dir / "face_intent.json"
    face_intent.write_text(
        json.dumps({
            "final": {
                "accepted": True,
                "feature": case.load_surface.feature,
                "solid_index": case.load_surface.solid_index,
                "selected_face_indices": case.load_surface.face_indices,
            },
            "per_face_path": str(selection),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    intent = intent_from_case(
        case, mesh_inp=work_dir / "mesh.inp", selection=selection
    )
    (work_dir / "intent.json").write_text(
        json.dumps(
            {"final": {"intent": intent.model_dump(mode="json")}},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
