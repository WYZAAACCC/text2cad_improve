"""The stages a run moves through, in order.

The order is the dependency order of the decisions, not the order of the menu
items in a solver. `frame` measures what the geometry is before anything is
decided about it; `domain` decides what piece to analyse; `setup` fixes what
the simulation is - the rotation, the temperature field, the material, the
load - from the user's description of it, and it sits after both of those so
that what the user stated can be compared with the part rather than taken on
trust, and so that a load stated per blade can become the load this model
carries; `assembly` decides
the physics and, through its face-finding sub-stage, which faces the load
enters through; `mesh` spends resolution knowing where the load is; then the
deterministic half materialises, solves and post-processes; `verify` judges
what may be quoted; `feedback` reads the judged results and decides what the
next revision of the part should be. The last of those is the only stage that
looks forward rather than at the part in front of it, and it is deliberately
last: it rests on the verdicts, so a change is never asked for on the strength
of a number that has not settled.

`assembly` is one stage rather than several because its parts share a single
evidence loop - the criterion the agent declares and the measurements it is
checked against. Splitting constraints, loads and materials apart would give
each a decision with no measurement of its own.
"""
from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    PREFLIGHT = "preflight"
    FRAME = "frame"
    SETUP = "setup"
    DOMAIN = "domain"
    ASSEMBLY = "assembly"
    MESH = "mesh"
    MATERIALIZE = "materialize"
    SOLVE = "solve"
    POSTPROCESS = "postprocess"
    VERIFY = "verify"
    FEEDBACK = "feedback"
    COMPLETE = "complete"


STAGE_ORDER: tuple[Stage, ...] = (
    Stage.PREFLIGHT,
    Stage.FRAME,
    Stage.DOMAIN,
    Stage.SETUP,
    Stage.ASSEMBLY,
    Stage.MESH,
    Stage.MATERIALIZE,
    Stage.SOLVE,
    Stage.POSTPROCESS,
    Stage.VERIFY,
    Stage.FEEDBACK,
    Stage.COMPLETE,
)

# What each stage must find in the case before it can run. A stage that needs
# the domain fails here, by name, rather than somewhere deeper with an
# attribute error on None.
REQUIRES: dict[Stage, tuple[str, ...]] = {
    Stage.PREFLIGHT: (),
    Stage.FRAME: (),
    # The setup stage reads what the frame measured and what the domain
    # decided, so a value the user stated can be compared with the part before
    # it is used rather than after - and so a load stated per blade can be
    # turned into the load this model carries, which is a question about how
    # much of the part is being analysed.
    Stage.SETUP: ("model", "domain"),
    Stage.DOMAIN: ("model",),
    # The physics is the setup stage's to produce; this one uses it.
    Stage.ASSEMBLY: ("model", "domain", "physics"),
    Stage.MESH: ("model", "domain", "load_surface"),
    Stage.MATERIALIZE: ("model", "domain", "load_surface", "physics", "mesh"),
    Stage.SOLVE: ("model", "domain", "load_surface", "physics", "mesh"),
    Stage.POSTPROCESS: ("physics", "solve"),
    Stage.VERIFY: ("physics", "solve"),
    # Changing the design on the strength of a number the verification stage
    # has not allowed to be quoted is how a loop converges on an artefact, so
    # the verdicts are a named requirement of the stage that decides what to
    # change rather than something it is trusted to go and read.
    Stage.FEEDBACK: ("physics", "solve", "verdicts"),
    Stage.COMPLETE: (),
}

# The case field group each stage writes, so a resume can work out what a
# changed upstream decision has invalidated.
PRODUCES: dict[Stage, str | None] = {
    Stage.PREFLIGHT: None,
    Stage.FRAME: "model",
    Stage.SETUP: "physics",
    Stage.DOMAIN: "domain",
    # The physics used to be written here, beside the face selection it was
    # needed for. It moved to `setup` when the values started arriving from a
    # brief: what the simulation *is* and which faces the load enters through
    # are separate decisions, and this stage's evidence - a criterion checked
    # against the geometry - belongs to the second.
    Stage.ASSEMBLY: None,
    Stage.MESH: "mesh",
    Stage.MATERIALIZE: None,
    Stage.SOLVE: "solve",
    Stage.POSTPROCESS: None,
    Stage.VERIFY: "verdicts",
    # The change request the next revision is built from. Written here and
    # applied elsewhere: a stage that both diagnosed a part and rebuilt it
    # would leave no record of which measurement asked for which change.
    Stage.FEEDBACK: "feedback",
    Stage.COMPLETE: None,
}


def next_stage(stage: Stage) -> Stage:
    index = STAGE_ORDER.index(stage)
    if index + 1 >= len(STAGE_ORDER):
        return Stage.COMPLETE
    return STAGE_ORDER[index + 1]
