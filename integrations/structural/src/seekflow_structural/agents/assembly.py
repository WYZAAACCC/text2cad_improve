"""The stage where the physics is decided and the load's faces are found.

Two things happen here that used to be spread across two standalone agents and
a hand-written intent file.

The physical values come from the user's parameter file and are copied
through. They are then checked against each other: a stated blade force beside
a stated mass, radius and speed is two answers to one question, and a
temperature profile whose radii do not match the part's is a profile for a
different part. Those checks report a residual and never stop the run.

The faces come from the face-finding sub-agent, which is given a requirement
in words and states a criterion for it. The load radius is measured from what
it returns and written into the case by this same stage - which is the whole
fix for the seam where a mesh was refined at radius 288 for faces at 212.67.
Nothing downstream can be told a different number, because there is nowhere
else for the number to live.
"""
from __future__ import annotations

from pathlib import Path

from seekflow_structural.agents import facefind
from seekflow_structural.case.model import Case, LoadBinding, Physics
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext

# The face-finding budget has to cover exploration before it covers
# selection: a model with eight features has to look at several of them before
# it knows which one produced the body, and a budget that only covers the
# search produces a run that explores and then stops.
#
# Measured on the reference part: the agent submits at call 22, having spent
# the first four finding the body and the rest narrowing to the slot flanks.
# Twenty is below that and produced a run that ran out two calls short.
DEFAULT_FACE_TOOL_CALLS = 30

# What the load's faces are, in words. The requirement is derived from the
# load the user declared rather than hard-coded, because the words the
# face-finding agent needs are a statement about this physics - and there is
# no other physics in the chain yet. When loads other than a blade root arrive,
# this is where their requirement is added.
REQUIREMENTS = {
    "flank_surface_normal": (
        "the faces that carry the blade load into the body. The load acts "
        "normal to the bearing surface, pressing into the material, so the "
        "outward normal of each of these faces points into the space the "
        "blade root occupies."
    ),
    "radial_outward_from_rotation_axis": (
        "the faces the load is applied to, where a radial pull acts outward "
        "from the rotation axis."
    ),
}


def requirement_for(physics: Physics) -> str:
    rule = physics.blade_load.direction_rule
    return REQUIREMENTS.get(
        rule,
        "the faces the external load is applied to.",
    )


def assembly(ctx: RunContext, *, api_key_file: Path | None = None,
             max_tool_calls: int = DEFAULT_FACE_TOOL_CALLS) -> Case:
    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "assembly has no case", "assembly")

    # The physics is the setup stage's to define, from a parameter file or
    # from a brief. This stage used to derive it here, from the parameter file
    # alone; that made the file the only way in, and it put the physical
    # decisions in the same stage as the face selection, where a reader had to
    # scroll past one to see the other.
    if case.physics is None:
        raise StructuralError(
            "case_incomplete",
            "assembly needs the physics the setup stage defines, and the case "
            "has none",
            "assembly",
        )

    # Named for what was done, not for what was hoped for. This stage makes
    # every comparison it can and reports the residual of each, so most of
    # these entries agree - a reader taking `count` for a number of problems
    # would see two on a run where nothing is wrong. The two counts are
    # reported side by side so that reading is not available.
    findings = case.physics.consistency
    disagreeing = [
        finding for finding in findings
        if (finding.relative_difference or 0.0) > 0.0
    ]
    if findings:
        ctx.job.event({
            "kind": "consistency_checks",
            "stage": "assembly",
            "comparisons": len(findings),
            "disagreeing": len(disagreeing),
            "disagreeing_quantities": [f.quantity for f in disagreeing],
        })

    requirement = requirement_for(case.physics)
    outcome, direction = _find_faces(
        ctx, requirement=requirement, api_key_file=api_key_file,
        max_tool_calls=max_tool_calls,
    )
    case.load_surface = outcome

    ctx.job.event({
        "kind": "faces_selected",
        "stage": "assembly",
        "feature": case.load_surface.feature,
        "solid_index": case.load_surface.solid_index,
        "face_count": len(case.load_surface.face_indices),
        "load_radius_mm": case.load_surface.load_radius_mm,
        "criterion_satisfied": (
            case.load_surface.criterion_residuals or {}
        ).get("satisfied"),
        # Which way the load on these faces would push, measured here rather
        # than three stages later when the deck is written. A selection that
        # resolves inward is a wrong answer, and the cheapest place to find
        # that out is where it was made - before a mesh and a solve have been
        # paid for. It is reported and not enforced: what a load face is, is
        # the agent's judgement, and the verification stage is where a
        # contradiction is turned into a verdict.
        "pressure_radial_fraction": direction.residual,
        "pressure_direction_note": direction.note,
    })
    return case


def _find_faces(ctx: RunContext, *, requirement: str,
                api_key_file: Path | None, max_tool_calls: int):
    """Run the sub-agent and turn its submission into the case's selection.

    Returns the selection and the comparison saying which way the load on it
    pushes. The comparison is made here, while the rows the agent worked from
    are still in hand, so a selection that cannot be the one asked for is
    visible at the stage that made it.
    """
    from seekflow_structural.runtime.caller import build_caller

    from seekflow_structural.tools import geometry

    bundle = Path(ctx.case.bundle.path)
    session = geometry.open_bundle(bundle)
    # The sector the domain stage chose is read from the case, not restated
    # here: a selection has to land inside the part that is actually meshed,
    # and the only place that knows which part that is is case.domain.
    domain = ctx.case.domain
    state = facefind.FaceFinderState(
        session=session,
        bundle=bundle,
        sector=(
            {
                "theta_low_deg": domain.theta_low_deg,
                "theta_high_deg": (
                    (domain.theta_low_deg + domain.sector_deg) % 360.0
                    if domain.sector_deg is not None
                    else None
                ),
            }
            if domain and domain.sector_deg is not None
            else None
        ),
        # Scripts the agent writes run under the job, so their text and output
        # are artifacts like everything else the run produced.
        workdir=ctx.path / "agent" / "analyses",
        # Where the face-evolution index goes. Built lazily, for the feature
        # the agent ends up choosing - indexing every feature up front would
        # read the document once per feature to answer a question about one.
        evolution_db=ctx.path / "model" / "face_evolution.sqlite",
    )
    try:
        caller, model_config = build_caller(api_key_file)
        spec = facefind.spec(
            requirement=requirement,
            sector_deg=(domain.sector_deg if domain else None),
            theta_low_deg=(domain.theta_low_deg if domain else 0.0),
            max_calls=max_tool_calls,
        )
        outcome = facefind.run(
            spec=spec, caller=caller, model_config=model_config, state=state
        )
        # One more attempt when the agent ran out of calls without deciding.
        #
        # A fresh conversation, not a larger budget: the failure this answers
        # is an agent that has reasoned itself into a corner and keeps
        # re-reading its own transcript, and a bigger budget gives it more
        # room to stay there. Measured on the reference part, where the same
        # setup submitted at call 22 on one run and spent thirty calls
        # circling on another - and where, in the run that failed, the agent
        # had the right twenty-four faces in hand at call fifteen and talked
        # itself out of them.
        #
        # Safe to retry because a rejected stage has started nothing: no
        # external process, no artifact, nothing to clean up. This is what
        # `recoverable` means, and it is the only stage in the chain where it
        # is true of exhaustion.
        # `outcome.exhausted`, not `outcome.final is None`: the agent's run
        # replaces a missing final with an `exhausted_final` dict, so the
        # final is never None and a check on it never fires. That is exactly
        # what happened - the retry was written, never ran, and the stage
        # failed the same way twice before the reason was found.
        if outcome.exhausted:
            # Charge the abandoned attempt here; the one that replaces it is
            # charged below, so each attempt lands on the ledger exactly once.
            ctx.charge_tool_calls(outcome.calls, "facefind-abandoned")
            ctx.job.event({
                "kind": "agent_retry",
                "stage": "assembly",
                "agent": "facefind",
                "reason": "tool_call_budget_exhausted",
                "calls": outcome.calls,
            })
            # The abandoned attempt, under a name that says what it is. Both
            # attempts used to be written from the same post-retry object
            # under two names, so `facefind.json` held the retry's result and
            # the attempt it replaced was nowhere in the job. Read back, that
            # looks exactly like a retry which reproduced the first attempt -
            # and on D27 it rescued the run, submitting in thirteen calls
            # after the first attempt spent thirty and decided nothing.
            ctx.job.write("agent/facefind_abandoned.json", outcome.record())
            retry = facefind.run(
                spec=spec, caller=caller, model_config=model_config, state=state
            )
            ctx.job.write("agent/facefind_retry.json", retry.record())
            outcome = retry

        ctx.charge_tool_calls(outcome.calls, "facefind")
        ctx.job.write("agent/facefind.json", outcome.record())
        if outcome.final is None or not outcome.final.get("accepted"):
            raise StructuralError(
                "faces_not_found",
                "the face-finding agent did not produce a selection: "
                + "; ".join(outcome.final.get("questions", []) if outcome.final
                            else ["its tool-call budget ran out"]),
                "assembly",
            )
        surface = facefind.to_case_selection(state, bundle)
        direction = _load_direction(state, surface)
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            close()

    return surface, direction


def _load_direction(state, surface):
    """Which way the pressure on the submitted faces pushes.

    Measured from the same rows the agent worked from, so it describes the set
    that was actually submitted rather than the one that was meant. Reported
    by this stage and judged by the verification stage; nothing here refuses
    the selection, because what a load face is, is the agent's judgement and
    not the harness's.
    """
    from seekflow_structural.tools import checks

    submitted = state.submitted or {}
    rows = facefind._rows_for(
        state, str(submitted.get("feature") or ""),
        int(submitted.get("solid_index") or 0),
    )
    per_face = {
        str(index): rows[index]
        for index in surface.face_indices
        if 0 <= index < len(rows)
    }
    return checks.load_pushes_outward(per_face)


def load_radius_for_mesh(case: Case) -> float:
    """The radius the meshing stage must refine, read from the case.

    A function rather than a parameter on purpose. There is exactly one way
    for the meshing stage to learn where the load is, and it is this one; a
    command-line argument would be a second way, and the second way is how the
    two came apart last time.
    """
    if case.load_surface is None or case.load_surface.load_radius_mm is None:
        raise StructuralError(
            "no_load_surface",
            "the load radius is not known yet; the assembly stage measures it "
            "from the faces it selects",
            "mesh",
        )
    return float(case.load_surface.load_radius_mm)
