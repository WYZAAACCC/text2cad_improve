"""Turning a solved field into a change the generation side can act on.

This is the stage that closes the loop. Everything before it answers a
question about the part that was given; this one asks what the *next* part
should be, and the answer has to be in the vocabulary of whatever is going to
build it.

Two things make that harder than reading the peak off a report, and both are
about attribution rather than measurement.

The first is that a peak is not a place. On D27 the reported maximum is 1482.7
MPa and sits at r = 60 mm, and the same run holds 1353.1 MPa at r = 210.4 mm.
Those are four millimetres of radius apart in a report and two entirely
different problems in the part: the first is hoop stress at the bore, which is
relieved by changing the rim's mass or the web's profile, and the second is
radial stress where the blade pull enters, which is relieved by changing the
rim section. A system that hands "1482 MPa" to a generator has said nothing it
can use.

The second is that the most likely reason for a surprising number is not the
part. The load in `d27-correct24` was a 10 kN smoke-test value against a brief
that implies 181 kN, and across four runs of the same disc the peak moves from
r = 60 to r = 210.4 to r = 293.3 as the load and the selected faces change.
Before anything is changed about the geometry, the question of whether the
number describes the component has to have an answer - and `load_application`
and `idealisation_edge` are answers to it that ask for the model to be fixed
rather than the part.

So a finding is submitted as an argument: the mechanism it claims, the
measurements it rests on, the variable it wants changed, and what it expects
that change to do. The harness re-reads every measurement and compares the
mechanism against its own signature, and reports the residual of each. It does
not reject - the agent is the one making an engineering judgement, and the
harness does not know what the right answer is. It makes the argument
checkable, which is the same thing the face-finding stage does with a
criterion and the verification stage does with a verdict.

What the diagnostics have to say about the mechanism is stated as evidence and
not as a rule. `checks.py` puts it this way about a comparison of two numbers:
a disagreement is a finding to report, and the reader decides what it means.
The same applies here, with one difference that is the point of the stage -
the reader is the next revision, and it decides by running.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from seekflow_structural.case.model import (
    Case,
    Comparison,
    Evidence,
    FeedbackReport,
    Finding,
    Prediction,
    ProposedChange,
    Written,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.runtime.loop import (
    AgentSpec,
    ToolAction,
    dispatch_table,
    exhausted_final,
    run_agent,
)
from seekflow_structural.tools import (
    design_variables,
    document as document_tools,
    face_join,
    results,
)
from seekflow_structural.tools.design_variables import (
    DESIGN_VARIABLES,
    MAX_RELATIVE_CHANGE,
)

# How close to a symmetry plane or an axis a peak has to be before its
# position is a property of the model rather than of the part.
EDGE_TOLERANCE_MM = 0.5


class Action(ToolAction):
    """The feedback agent's tool call."""

    action: Literal[
        "get_result_context",
        "query_nodes",
        "profile",
        "find_concentrations",
        "inspect_region",
        "section_resultant",
        "face_stress",
        "locate_point",
        "list_document_params",
        "check_finding",
        "submit_feedback",
        "needs_input",
    ]

    # --- filters, shared by the querying tools ---------------------------
    r_min: float | None = Field(
        default=None, description="lowest radius to keep, in mm. Unset does not filter."
    )
    r_max: float | None = Field(
        default=None, description="highest radius to keep, in mm"
    )
    z_min: float | None = Field(default=None, description="lowest z to keep, in mm")
    z_max: float | None = Field(default=None, description="highest z to keep, in mm")
    quantity: str = Field(
        default="s_eqv",
        description=(
            "which quantity to measure: s_eqv (von Mises), s_radial, s_hoop, "
            "s_axial, u_sum, safety_factor, temperature_c. The three "
            "components are in the cylindrical frame the deck solved in - "
            "radial away from the axis, hoop around it, axial along it."
        ),
    )
    axis: str = Field(
        default="r", description="axis to profile along: r, z or theta"
    )
    bins: int = Field(default=16, description="how many bands to divide the axis into")
    relative_threshold: float = Field(
        default=0.9,
        description=(
            "for find_concentrations: a node counts as part of a concentration "
            "when its value reaches this fraction of the peak. 0.9 finds the "
            "regions near the maximum; 0.7 finds a wider halo around them."
        ),
    )
    cell_mm: float | None = Field(
        default=None,
        description=(
            "for find_concentrations: how far apart two hot nodes may be and "
            "still count as one region. Leave unset to derive it from the "
            "mesh density, which is right unless you are looking for "
            "concentrations at a length you already have in mind."
        ),
    )
    node: int = Field(default=0, description="a node id, for inspect_region")
    r_mm: float | None = Field(
        default=None, description="the radius of a cylindrical cut, for section_resultant"
    )
    half_width_mm: float | None = Field(
        default=None, description="how wide a band around that cut to integrate over"
    )
    near_r_mm: float | None = Field(
        default=None,
        description=(
            "for list_document_params: report only what could act at this "
            "radius, in mm. Use it with the radius of the peak you are trying "
            "to relieve - it answers 'what can I change about this' instead of "
            "listing all 161 things the model has."
        ),
    )

    # --- the draft finding, for check_finding and submit_feedback --------
    finding: dict | None = Field(
        default=None,
        description=(
            "a draft finding. Its keys are fixed and are checked on "
            "submission:\n"
            "  feature        str, the name of the piece of geometry\n"
            "  faces          list[int], CAD face ids\n"
            "  radius_mm      float, where the problem is\n"
            "  z_mm           float\n"
            "  mechanism      str, from the list in your instructions\n"
            "  evidence       list of {quantity, value, where, source}\n"
            "  change         {parameter, current_value, proposed_value, "
            "relative_change, rationale} or null\n"
            "  prediction     {metric, direction, expected_relative_change, "
            "at} or null\n"
            "  rationale      str\n"
            "Those key names are the ones read, not a description of them: a "
            "change submitted as {'variable': ..., 'proposed': ...} is a "
            "change nothing can apply."
        ),
    )
    findings: list[dict] = Field(
        default_factory=list,
        description="the findings to file, each in the same shape",
    )
    summary: str = Field(default="", description="one paragraph for a reader")
    limits: list[str] = Field(
        default_factory=list,
        description=(
            "what you could not measure or could not decide. An empty list "
            "says you found everything you needed, which is a claim."
        ),
    )
    rationale: str = ""
    questions: list[str] = Field(default_factory=list)


@dataclass
class FeedbackState:
    """What the tools share: the field, what the run said, the verdicts."""

    # Named `field` for what it is, which shadows the dataclasses helper of
    # the same name inside this class body - so the defaults below are spelled
    # out through the module rather than through the imported name.
    field: results.ResultField
    context: dict
    solve_dir: Path
    job_dir: Path
    # Where the model is, so a peak can be joined to a face of it. Without
    # this an agent can measure a peak precisely and still not say what it is
    # a peak *in* - which is what the first real run reported, and what
    # stopped the loop.
    bundle: Path | None = None
    feature: str = ""
    solid_index: int = 0
    # The CAD document the model was built from. This is the surface a change
    # is made on: the template's parameter dict names about a dozen scalar
    # dimensions, the document names every scalar of every operation.
    document: dict | None = None
    # Node ids the load enters through, from the selection rather than from
    # the `sel` column - which is 1 on every row and carries nothing.
    load_nodes: set[int] = dataclasses.field(default_factory=set)
    load_faces: list[int] = dataclasses.field(default_factory=list)
    submitted: dict | None = None
    checks: list[dict] = dataclasses.field(default_factory=list)

    def selection(self) -> dict | None:
        return self.context.get("selection")

    def metrics(self) -> dict:
        return self.context.get("metrics") or {}


# --- reading -------------------------------------------------------------


def _quotable(state: FeedbackState) -> dict[str, str]:
    """Which reported numbers the verification stage allows to be built on.

    A finding that rests on a quantity marked `suspect` is optimising a number
    that moved between mesh levels, and one that rests on `confirmed_wrong` is
    optimising a number two independent measurements contradict. Both are how
    a loop converges on an artefact, so the verdicts travel with every reply
    this agent gets.
    """
    out = {}
    for verdict in state.context.get("verdicts") or []:
        out[str(verdict.get("quantity"))] = str(verdict.get("verdict"))
    return out


def _get_result_context(action, state: FeedbackState) -> dict:
    metrics = state.metrics()
    stress = metrics.get("stress") or {}
    limits = list(state.field.limits) + list(state.context.get("limits") or [])
    return {
        "ok": True,
        "result": {
            "case_id": metrics.get("case_id"),
            "rotation_rpm": metrics.get("rotation_rpm"),
            "scientific_status": metrics.get("scientific_status"),
            "node_count": metrics.get("node_count"),
            "stress_node_count": metrics.get("stress_result_node_count"),
            "reported": {
                "max_von_mises_mpa": stress.get("max_von_mises_mpa"),
                "at_radius_mm": stress.get("max_radius_mm"),
                "min_safety_factor": stress.get("min_safety_factor"),
                "max_load_surface_von_mises_mpa": stress.get(
                    "max_load_surface_von_mises_mpa"
                ),
                "max_displacement_mm": (metrics.get("displacement") or {}).get("max_mm"),
            },
            "radial_bands": metrics.get("radial_bands"),
            "load": {
                "target_force_n_per_slot": (metrics.get("load_audit") or {}).get(
                    "target_force_n_per_slot"
                ),
                "applied_resultant_n": (metrics.get("load_audit") or {}).get(
                    "applied_resultant_n"
                ),
                "mechanism": ((metrics.get("load_audit") or {}).get("emission") or {}).get(
                    "mechanism"
                ),
            },
            # What may be built on, and what may not. This is the verification
            # stage's judgement, passed through rather than second-guessed.
            "verdicts": _quotable(state),
            "measurable": {
                "quantities": list(results.QUANTITIES),
                "axes": list(results.AXES),
                "safety_factor_available": state.field.has_safety_factor,
                "temperature_available": state.field.has_temperature,
            },
            "load_path": {
                "selected_face_count": len(state.load_faces),
                "selected_face_nodes": len(state.load_nodes),
            },
            "limits": limits,
        },
    }


def _where(state: FeedbackState, action) -> list[results.Node]:
    return state.field.where(
        r_min=action.r_min, r_max=action.r_max,
        z_min=action.z_min, z_max=action.z_max,
    )


def _query_nodes(action, state: FeedbackState) -> dict:
    """What the field holds in a box, as aggregates rather than a node dump.

    A model cannot read twenty thousand rows and the answer is in the shape of
    them, so the reply is the count, the extremes, and the few nodes that hold
    them. The nodes are named by id so anything they show can be taken to
    `inspect_region` and followed up.
    """
    nodes = _where(state, action)
    if not nodes:
        return {
            "ok": True,
            "result": {
                "node_count": 0,
                "limits": ["no node in the field falls inside those bounds"],
            },
        }
    values = [
        (getattr(node, action.quantity), node) for node in nodes
        if getattr(node, action.quantity) is not None
    ]
    if not values:
        return {
            "ok": True,
            "result": {
                "node_count": len(nodes),
                "limits": [f"no node in those bounds has a {action.quantity}"],
            },
        }
    numbers = [value for value, _ in values]
    top = max(values, key=lambda pair: pair[0])[1]
    low = min(values, key=lambda pair: pair[0])[1]
    return {
        "ok": True,
        "result": {
            "node_count": len(nodes),
            "measured_node_count": len(values),
            "quantity": action.quantity,
            "max": round(max(numbers), 6),
            "max_node": top.nid,
            "max_at_radius_mm": round(top.r, 6),
            "max_at_z_mm": round(top.z, 6),
            "min": round(min(numbers), 6),
            "min_node": low.nid,
            "mean": round(sum(numbers) / len(numbers), 6),
            "components_at_max_mpa": {
                name: round(getattr(top, name), 6)
                for name in results.COMPONENTS
            },
        },
    }


def _profile(action, state: FeedbackState) -> dict:
    nodes = _where(state, action)
    payload = results.profile(nodes, action.quantity, action.axis, action.bins)
    return {"ok": True, "result": payload}


def _find_concentrations(action, state: FeedbackState) -> dict:
    nodes = _where(state, action)
    payload = results.concentrations(
        nodes, action.relative_threshold, action.cell_mm
    )
    return {"ok": True, "result": payload}


def _inspect_region(action, state: FeedbackState) -> dict:
    """The component breakdown and the fall-off around one node.

    The two measurements that name a mechanism. Which component dominates says
    whether the material there is being pulled around the axis or outward from
    it, and how far the value falls says whether the peak is a local feature or
    the whole section. Both are needed before a change can be aimed: they
    point at different variables.
    """
    if not action.node:
        raise StructuralError(
            "no_node", "inspect_region needs the id of a node to inspect", "feedback"
        )
    node = next(
        (item for item in state.field.nodes if item.nid == action.node), None
    )
    if node is None:
        raise StructuralError(
            "unknown_node",
            f"node {action.node} is not in this run's result field",
            "feedback",
        )
    # The walk stays in the node's own neighbourhood, so the fall it measures
    # is the fall along the surface rather than across to the next one.
    band = max(abs(node.r) * 0.25, 20.0)
    neighbours = state.field.where(
        r_min=node.r - band, r_max=node.r + band,
        z_min=node.z - band, z_max=node.z + band,
    )
    return {
        "ok": True,
        "result": {
            "node": node.nid,
            "r_mm": round(node.r, 6),
            "z_mm": round(node.z, 6),
            "components": results.components([node]),
            "decay": results.decay(state.field, node, action.quantity,
                                   nodes=neighbours),
            "on_a_loaded_face": node.nid in state.load_nodes,
            "at_a_symmetry_plane": abs(node.z) <= EDGE_TOLERANCE_MM,
        },
    }


def _section_resultant(action, state: FeedbackState) -> dict:
    if action.r_mm is None:
        raise StructuralError(
            "no_radius",
            "section_resultant needs r_mm - the radius of the cut to integrate "
            "across",
            "feedback",
        )
    nodes = state.field.stressed()
    payload = results.section_resultant(nodes, action.r_mm, action.half_width_mm)
    return {"ok": True, "result": payload}


def _face_stress(action, state: FeedbackState) -> dict:
    payload = results.face_stress(state.field, state.selection())
    return {"ok": True, "result": payload}


def _locate_point(action, state: FeedbackState) -> dict:
    """Which face of the model a node sits on.

    `face_stress` answers "how much stress is on each of these named faces" and
    covers only the faces the load enters through. This answers the question
    that comes first - "which face is this place" - over every face of the
    solid, and without it a peak away from the loaded faces can be measured
    exactly and still not be nameable.

    Measured on D27's first real run: the peak at r = 210.4 mm lies on two
    planar faces of 84 and 83 mm2 whose centroids are at r = 209.2 and
    r = 211.3 mm, and on a 71,347 mm2 cone whose bounding box also contains
    it but whose surface is 18.75 mm away. Only the distance separates them.
    """
    if not action.node:
        raise StructuralError(
            "no_node", "locate_point needs the id of a node to locate", "feedback"
        )
    if state.bundle is None or not state.feature:
        raise StructuralError(
            "no_model",
            "this run did not record which model it solved, so a node cannot "
            "be joined to a face of it",
            "feedback",
        )
    node = next(
        (item for item in state.field.nodes if item.nid == action.node), None
    )
    if node is None:
        raise StructuralError(
            "unknown_node",
            f"node {action.node} is not in this run's result field",
            "feedback",
        )
    payload = face_join.locate_point(
        state.bundle, feature=state.feature, solid_index=state.solid_index,
        point_mm=(node.x, node.y, node.z),
        cache_dir=state.job_dir / "mesh",
    )
    payload["node"] = node.nid
    payload["node_stress"] = {
        "s_eqv_mpa": round(node.s_eqv, 6),
        **{name: round(getattr(node, name), 6)
           for name in results.COMPONENTS},
    }
    return {"ok": True, "result": payload}


# --- checking the argument -----------------------------------------------


def _list_document_params(action, state: FeedbackState) -> dict:
    """What the model can actually be changed to.

    The template's parameter dict names about a dozen scalar dimensions and
    is how the first revision was asked for. The document it produced holds
    thirty-one operations, each with its own scalars, and `fillet_sketch` on
    the fir-tree cutter is one of them with a radius that exists nowhere in
    the template's vocabulary.

    Measured, and this tool is the fix: the agent diagnosed a stress
    concentration on the fir-tree flanks and asked for the root fillet to be
    enlarged. The harness refused it - `root_fillet_mm` is not a template
    parameter - and the agent filed the finding as one the generator could
    not carry out, with a reason that read as though it had checked. The
    document has seven such radii and enlarging them by half builds.
    """
    if state.document is None:
        return {
            "ok": True,
            "result": {
                "available": False,
                "limits": [
                    "this run's model carries no document.json, so what can be "
                    "changed about it cannot be listed. A change may still be "
                    "named as a template parameter."
                ],
            },
        }
    table = document_tools.editable(state.document)
    total = len(table)
    if action.near_r_mm is not None:
        # The question an agent has is "what can I change about this peak",
        # and the answer is a handful of names. Handed all of them it scanned
        # the ones whose names sounded like the problem and missed the one
        # sitting exactly on it - `feat_holes_poly.points[12]` at r = 208.087.
        table = document_tools.reaching(
            state.document, float(action.near_r_mm)
        )
        return {
            "ok": True,
            "result": {
                "available": True,
                "filtered_to_r_mm": float(action.near_r_mm),
                "editable_count": len(table),
                "of_total": total,
                "editable": table,
                "note": (
                    "only what could act within "
                    f"{document_tools.DEFAULT_REACH_MM:g} mm of r = "
                    f"{action.near_r_mm} mm is listed - every parameter whose "
                    "own position is there, and every profile vertex whose "
                    "edges span it. A parameter whose `at_r_mm` is nowhere "
                    "near this radius cannot relieve a peak here however "
                    "suggestive its name is."
                ),
            },
        }
    by_component: dict[str, list[str]] = {}
    for name, entry in sorted(table.items()):
        by_component.setdefault(str(entry["component"]), []).append(name)
    return {
        "ok": True,
        "result": {
            "available": True,
            "summary": document_tools.summary(state.document),
            "editable_count": len(table),
            "by_component": by_component,
            "editable": table,
            "note": (
                "name a change as one of these, exactly - `<node_id>.<param>`, "
                "for example `n_fillet_cutter_0.radius_mm`. Every one is a "
                "scalar the generator's own repair kernel accepts a patch for. "
                "Whether a value is geometrically possible is not answered "
                "here: a fillet larger than its edge is refused by the kernel "
                "when the document is built."
            ),
        },
    }


def _verify_evidence(
    evidence: list[dict], state: FeedbackState
) -> list[Comparison]:
    """Re-read every number a finding says it rests on.

    A premise that cannot be read again is a recollection, and the point of
    asking is that a model asked to justify a conclusion it has already
    reached will produce a plausible number. The number is either in the field
    or it is not.

    `source` names where the number should be found: `node:<id>` for a value
    on one node, `face:<id>` for a value on one CAD face, `field:<name>` for
    one of the reported scalars.
    """
    out = []
    for entry in evidence:
        quantity = str(entry.get("quantity", ""))
        claimed = entry.get("value")
        source = str(entry.get("source", ""))
        actual: float | None = None
        note = ""

        if source.startswith("node:"):
            try:
                nid = int(source.split(":", 1)[1])
            except ValueError:
                nid = -1
            node = next(
                (item for item in state.field.nodes if item.nid == nid), None
            )
            if node is None:
                note = f"node {nid} is not in this run's result field"
            elif not hasattr(node, quantity):
                note = f"a result node has no quantity called {quantity!r}"
            else:
                actual = getattr(node, quantity)
        elif source.startswith("face:"):
            try:
                face_id = int(source.split(":", 1)[1])
            except ValueError:
                face_id = -1
            payload = results.face_stress(state.field, state.selection())
            face = next(
                (row for row in payload["faces"] if row["cad_face"] == face_id),
                None,
            )
            if face is None:
                note = (
                    f"CAD face {face_id} is not among the faces this run's "
                    "selection names"
                )
            elif quantity not in face:
                note = f"a face measurement has no quantity called {quantity!r}"
            else:
                actual = face[quantity]
        elif source.startswith("field:"):
            name = source.split(":", 1)[1]
            actual = _reported_scalar(state, name)
            if actual is None:
                note = f"this run reports no scalar called {name!r}"
        else:
            note = (
                f"{source!r} does not name where to look. Use node:<id>, "
                "face:<id> or field:<name>."
            )

        if actual is None:
            out.append(Comparison(
                name=f"evidence.{quantity}", left=f"claimed {claimed}",
                right="not measurable", note=note,
            ))
            continue
        try:
            claimed_number = float(claimed)
        except (TypeError, ValueError):
            out.append(Comparison(
                name=f"evidence.{quantity}", left=f"claimed {claimed!r}",
                right=f"measured {actual}", note="the claimed value is not a number",
            ))
            continue
        scale = max(abs(claimed_number), abs(float(actual)), 1e-12)
        out.append(Comparison(
            name=f"evidence.{quantity}",
            left=f"claimed {claimed_number:.6g}",
            right=f"measured {float(actual):.6g}",
            residual=claimed_number - float(actual),
            relative=abs(claimed_number - float(actual)) / scale,
            note=note or f"re-read from {source}",
        ))
    return out


def _reported_scalar(state: FeedbackState, name: str) -> float | None:
    value = results.reported_scalars(state.metrics()).get(name)
    return float(value) if value is not None else None


def _mechanism_consistency(
    finding: dict, state: FeedbackState
) -> list[Comparison]:
    """Whether the mechanism claimed matches the signature it should leave.

    Each mechanism has a shape in the measurements, and this compares the
    claim against it. The comparisons are reported and not enforced: the agent
    is making an engineering judgement about a specific component and this
    package does not know what the right answer is. What it can do is make the
    claim answerable - a finding that says `hoop_driven` while its own peak
    has radial as the dominant component is a finding whose reasoning can be
    seen to have come apart, before a design change is paid for.
    """
    mechanism = str(finding.get("mechanism") or "")
    out: list[Comparison] = []

    if mechanism in ("", "unresolved"):
        return out

    # Where the finding says the problem is. Every positional check reads this
    # node, so a finding that names none cannot be checked and is told so.
    node = None
    radius = finding.get("radius_mm")
    z_mm = finding.get("z_mm")
    if radius is not None and z_mm is not None:
        candidates = state.field.where(
            r_min=float(radius) - 1.0, r_max=float(radius) + 1.0,
            z_min=float(z_mm) - 1.0, z_max=float(z_mm) + 1.0,
        )
        if candidates:
            node = max(candidates, key=lambda item: item.s_eqv)

    if mechanism in ("hoop_driven", "radial_driven", "section_overload",
                     "stress_concentration", "thermal_gradient"):
        if node is None:
            out.append(Comparison(
                name="mechanism.location",
                left=f"{mechanism} at r={radius}, z={z_mm}",
                right="a node the field can be read at",
                note=(
                    "no node in the result field lies within 1 mm of the "
                    "location this finding states, so nothing about the "
                    "mechanism could be measured. State radius_mm and z_mm as "
                    "they come back from a measurement."
                ),
            ))
            return out

    if mechanism in ("hoop_driven", "radial_driven"):
        want = "s_hoop" if mechanism == "hoop_driven" else "s_radial"
        assert node is not None
        breakdown = results.components([node])
        dominant = breakdown.get("dominant")
        other = "s_radial" if want == "s_hoop" else "s_hoop"
        out.append(Comparison(
            name=f"mechanism.{mechanism}",
            left=f"dominant component {dominant}",
            right=f"{want}, which is what {mechanism} claims",
            residual=0.0 if dominant == want else 1.0,
            relative=(
                0.0 if dominant == want
                else abs(getattr(node, other)) / max(abs(getattr(node, want)), 1e-12)
            ),
            note=(
                f"at node {node.nid}: {want} = "
                f"{getattr(node, want):.6g} MPa, {other} = "
                f"{getattr(node, other):.6g} MPa"
            ),
        ))

    if mechanism == "idealisation_edge":
        assert node is not None
        out.append(Comparison(
            name="mechanism.idealisation_edge",
            left=f"peak at z = {node.z:.6g} mm",
            right=f"within {EDGE_TOLERANCE_MM} mm of a plane the model cut on",
            residual=abs(node.z),
            relative=0.0 if abs(node.z) <= EDGE_TOLERANCE_MM else 1.0,
            note=(
                "a peak on the z = 0 plane or on a sector boundary is a "
                "property of what was modelled. It does not mean the part is "
                "wrong, and changing the part will not move it."
            ),
        ))

    if mechanism in ("stress_concentration", "section_overload"):
        assert node is not None
        band = max(abs(node.r) * 0.25, 20.0)
        neighbours = state.field.where(
            r_min=node.r - band, r_max=node.r + band,
            z_min=node.z - band, z_max=node.z + band,
        )
        fall = results.decay(state.field, node, nodes=neighbours)
        half = (fall.get("reached") or {}).get("0.5")
        cluster = results.concentrations(neighbours, 0.9)
        extent = None
        for entry in cluster.get("concentrations") or []:
            if entry["peak_node"] == node.nid:
                extent = entry["extent_mm"]
                break
        if half is None:
            out.append(Comparison(
                name=f"mechanism.{mechanism}",
                left="stress never falls to half over the neighbourhood",
                right=(
                    "a local concentration"
                    if mechanism == "stress_concentration"
                    else "a broad region"
                ),
                residual=1.0,
                relative=1.0,
                note=(
                    "over this neighbourhood the value does not fall away at "
                    "all, which is what a broad region looks like and not what "
                    "a local concentration does"
                ),
            ))
        else:
            distance = float(half["distance_mm"])
            scale = float(extent) if extent else band
            ratio = distance / max(scale, 1e-9)
            # A peak that falls to half within a small part of its own
            # concentration is local; one that takes most of the region to
            # fall is the region.
            local = ratio < 0.25
            agrees = local if mechanism == "stress_concentration" else not local
            out.append(Comparison(
                name=f"mechanism.{mechanism}",
                left=f"half the value gone within {distance:.4g} mm",
                right=f"the region extends {scale:.4g} mm",
                residual=ratio,
                relative=0.0 if agrees else min(1.0, abs(ratio - 0.25) / 0.25),
                note=(
                    "the ratio of the fall-off distance to the size of the "
                    "region. A small ratio is a local feature and a large one "
                    "is the section itself; the two want different variables "
                    "changed"
                ),
            ))

    if mechanism == "load_application":
        assert node is not None
        on_load = node.nid in state.load_nodes
        verdicts = _quotable(state)
        suspect = any(
            value in ("suspect", "confirmed_wrong") for value in verdicts.values()
        )
        out.append(Comparison(
            name="mechanism.load_application",
            left=(
                f"peak node {node.nid} is on a loaded face"
                if on_load else
                f"peak node {node.nid} is not on any loaded face"
            ),
            right="a peak that the load application could have produced",
            residual=0.0 if on_load else 1.0,
            # Zero when the peak is where the load enters, which is what the
            # mechanism predicts, and one when it is not. `relative` is what
            # carries a comparison into `classify`, and a check that leaves it
            # None is filtered out before it can contradict anything - which
            # would make this the one mechanism that could never be wrong.
            relative=0.0 if on_load else 1.0,
            note=(
                "a peak on the faces the load enters through is the first "
                "thing to suspect of being an artefact of how the load was "
                "applied rather than of the component"
                + (
                    "; the verification stage also marked a reported quantity "
                    "as not settled or contradicted, which is consistent with "
                    "that reading"
                    if suspect else ""
                )
            ),
        ))

    return out


def _change_consistency(finding: dict, state: FeedbackState) -> list[Comparison]:
    """Whether the change asked for is one the generator can carry out.

    A change may name either of two layers, and the document is checked first
    because it is the wider one.

    A *document* parameter is `<node_id>.<param>` - `n_fillet_cutter_0.radius_mm`
    - a scalar on one of the operations the model actually holds. A *template*
    parameter is one of the dozen scalar dimensions `param_templates.build`
    accepts, which is how the first revision was asked for.

    Getting the order wrong has already cost a run. The agent diagnosed a
    stress concentration on the fir-tree flanks and asked for the root fillet
    to be enlarged; the harness checked the name against the template's
    vocabulary, refused it, and the agent filed the finding as one the
    generator could not carry out - with a reason that read as though it had
    checked. The document has seven such radii, and enlarging them by half
    builds. A refusal has to be about the model, not about the list of names
    this harness happens to know.
    """
    out: list[Comparison] = []
    change = finding.get("change") or {}
    if not change:
        return out
    parameter = str(change.get("parameter") or "")
    document = state.document

    resolved = (
        document_tools.resolve(document, parameter)
        if document is not None and parameter else None
    )
    if resolved is not None and document is not None:
        _node_id, _param = resolved
        entry = document_tools.editable(document)[parameter]
        proposed = change.get("proposed_value")
        out.append(Comparison(
            name="change.parameter",
            left=f"{parameter} on a {entry['op']}",
            right="an operation parameter this model has",
            residual=0.0, relative=0.0,
            note=(
                f"currently {entry['current_value']}"
                + (f", proposed {proposed}" if proposed is not None else "")
                + ". Whether the value is geometrically possible is not "
                "answered here - the kernel answers it when the document is "
                "built, and a fillet larger than the edge it rounds is refused "
                "there."
            ),
        ))
    elif document is not None:
        # The revision has a document, so the template layer is not an
        # alternative vocabulary - it is a dead one. From the revision that has
        # a document onward the generator reads the document and never calls
        # `param_templates.build`, so a change named after a template parameter
        # is written into `params.json`, which nothing opens. The revision that
        # follows is the previous geometry, and its numbers get recorded as the
        # effect of the change.
        #
        # Measured on D27: all 18 template variables this harness knows are
        # absent from the document. There is no name in that layer that reaches
        # this part.
        out.append(Comparison(
            name="change.parameter",
            left=f"{parameter!r}",
            right="an operation parameter of this model",
            note=(
                "this revision is built from its document, and the template "
                "layer is not consulted for a revision that has one - so a "
                "template parameter is a change the generator never reads. "
                "`list_document_params` reports what this model actually has, "
                "as `<node_id>.<param>` or `<node_id>.points[<i>].<axis>`, and "
                "`near_r_mm` narrows it to the names that act at a radius. If "
                "nothing in the document acts where the finding is, say so and "
                "propose no change."
            ),
        ))
    else:
        kind = DESIGN_VARIABLES.get(parameter)
        if kind is None:
            out.append(Comparison(
                name="change.parameter",
                left=f"{parameter!r}",
                right="a parameter of this model, or a template parameter",
                note=(
                    "that name is in neither layer. A model parameter is "
                    "`<node_id>.<param>` and `list_document_params` reports "
                    "every one of them; a template parameter is one of: "
                    + ", ".join(
                        sorted(name for name, k in DESIGN_VARIABLES.items()
                               if k == "free")
                    )
                ),
            ))
        elif kind == "derived":
            out.append(Comparison(
                name="change.parameter",
                left=f"{parameter!r}",
                right="computed by the generator from other variables",
                note=(
                    "the generator derives this one by a rule it states as a "
                    "hard constraint, so a value written here is recomputed "
                    "away. Change the variable it is derived from instead."
                ),
            ))
        elif kind == "categorical":
            out.append(Comparison(
                name="change.parameter",
                left=f"{parameter!r}",
                right="a numeric change",
                note=(
                    "this variable selects between named alternatives rather "
                    "than taking a magnitude; state the alternative in the "
                    "rationale instead of a value"
                ),
            ))

    relative = change.get("relative_change")
    if relative is not None:
        try:
            magnitude = abs(float(relative))
        except (TypeError, ValueError):
            magnitude = None
        if magnitude is not None and magnitude > MAX_RELATIVE_CHANGE:
            out.append(Comparison(
                name="change.magnitude",
                left=f"{magnitude:.4g} relative change",
                right=(
                    f"at most {MAX_RELATIVE_CHANGE:.4g} in one step, which is "
                    "the repair kernel's own budget"
                ),
                residual=magnitude - MAX_RELATIVE_CHANGE,
                relative=(magnitude - MAX_RELATIVE_CHANGE) / MAX_RELATIVE_CHANGE,
                note=(
                    "a larger change is refused downstream. Split it into "
                    "steps, or say in the rationale why this step is the one "
                    "that matters."
                ),
            ))
    return out

def check_finding(finding: dict, state: FeedbackState) -> list[Comparison]:
    """Everything the harness can measure about one finding's argument."""
    return (
        _verify_evidence(finding.get("evidence") or [], state)
        + _mechanism_consistency(finding, state)
        + _change_consistency(finding, state)
    )


def _check_finding(action, state: FeedbackState) -> dict:
    if not action.finding:
        raise StructuralError(
            "no_finding",
            "check_finding needs a finding to check, in the `finding` field",
            "feedback",
        )
    comparisons = check_finding(action.finding, state)
    payload = {
        "comparisons": [c.model_dump(mode="json") for c in comparisons],
        "disagreeing": [
            c.name for c in comparisons
            if c.relative is not None and c.relative > 0.0
        ],
    }
    state.checks.append({"finding": action.finding, "comparisons": payload})
    return {
        "ok": True,
        "result": payload,
        "note": (
            "each comparison is two measurements and the residual between "
            "them. A non-zero residual is not a rejection - it is this "
            "package saying that the claim and the measurement do not agree, "
            "and the choice of what to do about it is the agent's."
        ),
    }


# The keys each nested object is read under. Listed rather than inferred,
# because the failure they prevent is silent: a change written as
# `{"variable": ..., "proposed": ...}` reads as a change with no parameter and
# no proposed value, and the finding is then filed as one that asks for
# nothing.
CHANGE_KEYS = ("parameter", "current_value", "proposed_value",
               "relative_change", "rationale")
PREDICTION_KEYS = ("metric", "direction", "expected_relative_change", "at")
EVIDENCE_KEYS = ("quantity", "value", "where", "source")

# Names a model reaches for when it has not been told the exact ones. Measured
# on the first end-to-end run, where the change came back as `variable`,
# `current`, `proposed` and `relative` - every one of them a reasonable guess
# and none of them read.
CHANGE_SYNONYMS = {
    "variable": "parameter", "param": "parameter", "name": "parameter",
    "variable_name": "parameter",
    "current": "current_value", "from": "current_value",
    "old_value": "current_value", "before": "current_value",
    "proposed": "proposed_value", "to": "proposed_value",
    "new_value": "proposed_value", "after": "proposed_value",
    "relative": "relative_change", "delta": "relative_change",
    "change": "relative_change", "relative_delta": "relative_change",
}


def normalise_change(change: dict) -> tuple[dict, list[str]]:
    """A submitted change under the names it is read by.

    Returns the change and the keys that were dropped. Dropping them rather
    than refusing the whole finding is deliberate: the first end-to-end run
    ended with a validation error that destroyed a completed solve over four
    key names, and a solve costs minutes to hours. A change whose names can be
    recognised is recognised; what cannot is reported, and the finding carries
    the report.
    """
    if not isinstance(change, dict):
        return {}, [f"change was {type(change).__name__}, not an object"]
    out: dict = {}
    dropped: list[str] = []
    for key, value in change.items():
        target = key if key in CHANGE_KEYS else CHANGE_SYNONYMS.get(key)
        if target is None:
            dropped.append(key)
        elif target not in out:
            out[target] = value
    return out, dropped


# How far from the thing it names a change can still reach.
#
# The distance is not a convention; the reach of a *fillet* is. Moving a
# profile vertex pivots the two edges that meet there, so the region it can
# affect is the span between its neighbours and that is read from the
# document. A fillet's influence is a property of the local geometry rather
# than of its radius, so ten millimetres is stated rather than derived - and
# the radius is reported beside it, in the message, so a reader who disagrees
# can see what was assumed.
FILLET_REACH_MM = 10.0


def _reach(finding: dict, document: dict | None) -> dict | None:
    """Where the change acts, and whether that includes the peak.

    Returns None when either end of the comparison is unknown, which is not
    the same as the comparison passing - it is the comparison not being made.
    """
    if document is None:
        return None
    change = finding.get("change") or {}
    parameter = str(change.get("parameter") or "")
    peak_r = finding.get("radius_mm")
    if not parameter or peak_r is None:
        return None
    entry = document_tools.editable(document).get(parameter)
    if entry is None:
        return None
    at_r = entry.get("at_r_mm")
    if at_r is None:
        return None

    index = entry.get("vertex_index")
    if index is None:
        # A fillet, or another operation that acts at named vertices.
        radius = entry.get("current_value")
        low = at_r - FILLET_REACH_MM
        high = at_r + FILLET_REACH_MM
        how = (
            f"a {radius} mm fillet is taken to act within "
            f"{FILLET_REACH_MM:g} mm of the vertex it rounds"
        )
    else:
        # A vertex of a profile: the edges that meet it.
        rows = {row["index"]: row for row in document_tools.world_positions(
            document, str(entry["node"])).get("vertices") or []}
        neighbours = [
            rows[other]["r_mm"] for other in (index - 1, index + 1)
            if other in rows and "r_mm" in rows[other]
        ]
        if not neighbours:
            return None
        low = min([at_r, *neighbours])
        high = max([at_r, *neighbours])
        how = "moving a vertex pivots the edges that meet it"

    reaches = low <= float(peak_r) <= high
    return {
        "parameter": parameter,
        "acts_at_r_mm": round(at_r, 3),
        "spans_r_mm": [round(low, 3), round(high, 3)],
        "peak_r_mm": float(peak_r),
        "reaches": reaches,
        "how": how,
        "distance_mm": round(abs(float(peak_r) - at_r), 3),
    }


def _reach_problem(finding: dict, document: dict | None) -> str | None:
    """A change that cannot reach the peak it is filed for.

    Measured, and this check is the fix. A run located a peak at r = 208.09 mm
    on the web and asked for `n_fillet_cutter_0.radius_mm` - a fillet on the
    fir-tree cutter, which acts at r = 284.3 mm. The change was made, built,
    solved and came back at -0.00%, and the loop recorded a rule as tested
    that had never been tried anywhere near the problem.
    """
    reach = _reach(finding, document)
    if reach is None or reach["reaches"]:
        return None
    return (
        f"change names {reach['parameter']}, which acts at r = "
        f"{reach['acts_at_r_mm']} mm - {reach['distance_mm']} mm from the "
        f"r = {reach['peak_r_mm']} mm this finding is about. Its reach is "
        f"r = {reach['spans_r_mm'][0]} to {reach['spans_r_mm'][1]} mm "
        f"({reach['how']}), so it cannot affect that peak. Name a parameter "
        "whose `at_r_mm` spans the peak, or file the finding without a change "
        "and say what you would have needed."
    )


def finding_shape_problems(finding: dict,
                          document: dict | None = None) -> list[str]:
    """What about a finding's keys would make it unusable.

    Reported at submission so the agent gets another turn, rather than at the
    end where the only thing left to do with a malformed finding is record it.
    """
    problems: list[str] = []
    if not isinstance(finding, dict):
        return [f"a finding has to be an object, not {type(finding).__name__}"]
    if not finding.get("evidence"):
        problems.append(
            "no evidence: every finding has to carry the measurements it was "
            "drawn from, as a list of {quantity, value, where, source}"
        )
    else:
        for index, entry in enumerate(finding["evidence"]):
            missing = [key for key in ("quantity", "value", "source")
                       if key not in (entry or {})]
            if missing:
                problems.append(
                    f"evidence[{index}] is missing {', '.join(missing)}; each "
                    "entry needs a quantity, its value, and the source it was "
                    "read at (node:<id>, face:<id> or field:<name>)"
                )
                continue
            try:
                float(entry["value"])
            except (TypeError, ValueError):
                problems.append(
                    f"evidence[{index}].value is {entry['value']!r}, which is "
                    "not a number. It is re-read and compared, so it has to be "
                    "the value a measurement returned."
                )
    change = finding.get("change")
    if change:
        normalised, dropped = normalise_change(change)
        if dropped:
            problems.append(
                "change has key(s) that are not read and were dropped: "
                + ", ".join(sorted(dropped))
                + ". It is read as: " + ", ".join(CHANGE_KEYS)
            )
        parameter = str(normalised.get("parameter") or "")
        if not parameter:
            problems.append(
                "change names no parameter. It is read from the key "
                "'parameter' (also accepted: 'variable'), and it has to be a "
                "variable the generator takes."
            )
        elif "." in parameter:
            # A model parameter - `<node_id>.<param>` - which this function
            # cannot check, because it is handed a finding and not the model.
            # Left to `check_finding`, which has the document. Checking it
            # here against the template's vocabulary is exactly the mistake
            # that cost a run: a document name is not a template name, and
            # refusing it on that ground told the agent the generator could
            # not do something it can.
            pass
        else:
            # The name is checked here as well as in `check_finding`, and the
            # difference matters. `check_finding` is a tool the agent may not
            # call; this runs on submission, where a refusal is a turn the
            # agent gets back. Measured on the second real run: the agent
            # located the peak on the fir-tree flanks correctly and then asked
            # for `fir_tree_flank_fillet_radius_mm`, which the generator has
            # never heard of - the variable it meant is `root_fillet_mm`. The
            # geometry was right and the finding was unapplicable.
            kind = design_variables.kind(parameter)
            if kind is None:
                problems.append(
                    f"change names {parameter!r}, which is not a variable the "
                    "generation side takes. It takes: "
                    + ", ".join(design_variables.free_variables())
                )
            elif kind == "derived":
                problems.append(
                    f"change names {parameter!r}, which the generator computes "
                    "from other variables - a value written there is "
                    "recomputed away. Name the variable it is derived from."
                )
            elif kind == "categorical":
                problems.append(
                    f"change names {parameter!r}, which selects between named "
                    "alternatives and takes no magnitude."
                )
            elif kind == "not_in_template":
                problems.append(
                    f"change names {parameter!r}, which the authoring side "
                    "knows but this generator has no control for - the "
                    "fir-tree profile, for one, is built from half-widths and "
                    "angles and has no fillet parameter at all. The diagnosis "
                    "may be right and there is nothing here that can act on "
                    "it; file it without a change and say which variable you "
                    "would have wanted."
                )
        if (normalised.get("proposed_value") is None
                and normalised.get("relative_change") is None):
            problems.append(
                "change says what to change but not what to change it to: "
                "give a proposed_value, or a relative_change to move the "
                "current value by. A finding without one cannot be carried "
                "out, and the revision it asks for would be the one before it."
            )
        # And it has to be able to reach the peak it is filed for.
        unreachable = _reach_problem(finding, document)
        if unreachable:
            problems.append(unreachable)
    prediction = finding.get("prediction")
    if prediction:
        missing = [key for key in ("metric", "direction")
                   if key not in prediction]
        if missing:
            problems.append(
                "prediction is missing " + ", ".join(missing)
                + "; it is read as: " + ", ".join(PREDICTION_KEYS)
            )
        direction = prediction.get("direction")
        if direction not in (None, "increase", "decrease"):
            problems.append(
                f"prediction.direction is {direction!r}; it has to be "
                "'increase' or 'decrease', with the size as a positive "
                "fraction in expected_relative_change"
            )
    return problems


def _submit_feedback(action, state: FeedbackState) -> dict:
    findings = list(action.findings)
    if not findings:
        raise StructuralError(
            "no_findings",
            "no findings were submitted. If the results contain nothing that "
            "should change, submit an empty list and say so in the summary; "
            "if they contain something you cannot attribute, file it with "
            "mechanism 'unresolved' rather than leaving it out.",
            "feedback",
        )
    known = {"stress_concentration", "section_overload", "hoop_driven",
             "radial_driven", "thermal_gradient", "load_application",
             "idealisation_edge", "unresolved"}
    for index, finding in enumerate(findings):
        mechanism = str(finding.get("mechanism") or "")
        if mechanism not in known:
            raise StructuralError(
                "unknown_mechanism",
                f"finding {index} claims mechanism {mechanism!r}, which is not "
                "one of: " + ", ".join(sorted(known)),
                "feedback",
            )
        problems = finding_shape_problems(finding, state.document)
        if problems:
            raise StructuralError(
                "finding_malformed",
                f"finding {index} was not filed: " + " ".join(problems),
                "feedback",
            )
    state.submitted = {
        "findings": findings,
        "summary": action.summary,
        "limits": list(action.limits),
        "rationale": action.rationale,
    }
    return {"ok": True, "result": {"accepted": True, "count": len(findings)}}


def _needs_input(action, state: FeedbackState) -> dict:
    return {
        "ok": True,
        "result": {"accepted": False, "questions": action.questions},
    }


class CommitAction(Action):
    """The last call: file the findings, or say what is missing."""

    action: Literal["submit_feedback", "needs_input"]


DISPATCH = dispatch_table({
    "get_result_context": _get_result_context,
    "query_nodes": _query_nodes,
    "profile": _profile,
    "find_concentrations": _find_concentrations,
    "inspect_region": _inspect_region,
    "section_resultant": _section_resultant,
    "face_stress": _face_stress,
    "locate_point": _locate_point,
    "list_document_params": _list_document_params,
    "check_finding": _check_finding,
    "submit_feedback": _submit_feedback,
    "needs_input": _needs_input,
})

SYSTEM_PROMPT = """\
You are reading the results of a structural finite element analysis of a
turbine disc, and deciding what the next revision of the design should be.

What happened before you: a disc was built, a load and a temperature field and
a material were decided for it, the faces the load enters through were chosen,
it was meshed and solved, and the reported numbers were judged. What has not
happened is any change to the disc. That is yours.

The one rule that matters most: **a peak is not a place, and a number is not a
reason.** A report that says 1482 MPa at r = 60 mm has told you where a
maximum is and nothing about what to do. The same disc in another run holds
1353 MPa at r = 210 mm, and those want opposite changes: the first is hoop
stress at the bore, relieved by moving mass off the rim or changing how the
web carries load outward; the second is radial stress where the blade pulls,
relieved in the rim section. Before proposing anything you have to know which
of those you are looking at, and that means measuring.

The mechanisms, and what distinguishes each in the measurements you can take:

- stress_concentration  a local peak. The value falls to half within a small
  part of the region it sits in. Relieved by local geometry - a fillet radius,
  a local thickness.
- section_overload      a broad region at high stress. The value takes most of
  the region to fall to half. Relieved by a section change, not a fillet.
- hoop_driven           the peak has hoop as its dominant component. That is
  material being pulled around the axis, and it is relieved by changing what
  is pulling it there - rim mass, bore radius, the web's radial stiffness.
- radial_driven         the peak has radial as its dominant component. That is
  load being pulled outward from the axis, and it is relieved in the section
  that carries it.
- thermal_gradient      the peak sits where the temperature changes fastest.
  Relieved by the cooling or the wall thickness, not by the load path.
- load_application      the peak sits on the faces the load enters through, or
  the verification stage marked a reported number as not settled. Before the
  disc is changed, check that the number describes the disc: on this machine
  the load has been applied to the wrong faces, and to the right faces at a
  smoke-test magnitude, and both produced a plausible-looking peak in a
  plausible-looking place.
- idealisation_edge     the peak sits on the z = 0 plane, a sector boundary,
  or a constraint. It is a property of what was modelled. Changing the part
  will not move it.
- unresolved            you cannot attribute it. This is a real answer and a
  better one than a mechanism you do not believe.

Your tools:

- get_result_context   what this run reported, what the verification stage
  decided may be quoted, and what could not be measured. Read it first.
- query_nodes          the field inside a box: count, extremes, mean, and the
  node holding each extreme. r_min/r_max/z_min/z_max; unset does not filter.
- profile              one quantity binned along r, z or theta. This is what
  shows where the load is carried and whether a high band is a spike or a
  section.
- find_concentrations  the regions reaching a fraction of the peak, each with
  its own peak, extent, radius span and node count. A peak is a node; this is
  the list of places.
- inspect_region       everything about one node: its component breakdown, how
  far its value falls going outward, whether it is on a loaded face, whether
  it is on a symmetry plane. This is where a mechanism is decided.
- section_resultant    the radial force crossing a cylindrical cut at a radius
  you choose. Use it to follow the load from where it enters to where it is
  reacted: a cut inside the rim should already carry the blade pull.
- face_stress         stress per CAD face, over the faces the load enters
  through. This is the join from a face to a number.
- locate_point        the other direction, and do this one first: given a node,
  which faces of the model is it on. It searches every face of the solid, not
  only the loaded ones, and reports how far the point is from each candidate -
  so a face the point merely falls near is told apart from the face it is on.
  A finding whose change names a design variable has to name the geometry that
  variable belongs to, and this is what names it. Measured on D27: the peak
  at r = 210.4 mm lies on two planar faces of 84 and 83 mm2 at r = 209.2 and
  r = 211.3 mm - the fir-tree flanks - and also inside the bounding box of a
  71,347 mm2 cone whose surface is 18.75 mm away.
- list_document_params  what the model can actually be changed to, and where
  each of those things is. Every scalar of every operation comes back with an
  `at_r_mm`, and profile vertices come back as `<node>.points[i].x_mm` /
  `.y_mm` with the radius and axial station they sit at.

  **Read the `at_r_mm` before you name anything.** Measured, and this is the
  mistake this field exists to stop: a run located a peak at r = 208.09 on the
  web, searched the parameter list, found `n_fillet_cutter_0.radius_mm`, and
  asked for it to be enlarged - because it is a fillet and the run had decided
  the problem was a fillet problem. That parameter acts on the fir-tree cutter
  at r = 284.3. It is 76 mm from the peak. The change was made, built, solved
  and came back at -0.00%, and the run had no way to notice it had aimed at
  the wrong place.

  So: a parameter whose `at_r_mm` is far from your peak is not a parameter
  that can relieve it, however suggestive its name is. On D27 every one of the
  seven cutter fillets is between r = 277.9 and r = 284.3, and none of the
  three disc fillets is between r = 160 and r = 240 - so a peak at r = 208 is
  not addressable by a fillet at all.

  A profile vertex carries `spans_r_mm` as well as `at_r_mm`, and for deciding
  reach the span is the one that matters: a vertex acts through the two edges
  that meet it, so it can reshape anything between its neighbours' radii.
  Measured: an earlier run read "the disc polyline vertices are at r = 160 and
  r = 240" and concluded that nothing controlled r = 208 - which sits on the
  edge between those two, and is controlled by exactly those vertices. Read
  `spans_r_mm`, and if it contains your peak, that vertex is a handle on it.

  **Pass `near_r_mm` with the peak's radius.** The model has 161 editable
  numbers and the question is "what can I change about this peak", which is a
  question about one radius. Asked that way the tool returns the handful that
  could act there - every parameter whose own position is there and every
  profile vertex whose edges span it.

  Measured, and this is what the filter is for: on D27 the peak at r = 208.09
  is the edge of a lightening hole. `feat_holes_poly.points[12]` sits at
  r = 208.087 exactly and `n_pat_holes.radius_mm` is 208 - the pitch radius the
  twenty holes are placed on. Given all 161 numbers at once, a run looked at
  the fillets and at the disc profile, found both too far away, and concluded
  that nothing could be done; it never saw the hole, because nothing about the
  name `feat_holes_poly` says "at r = 208".

  Name a parameter exactly as it comes back.
- check_finding        measure a draft finding before filing it: it re-reads
  every number you cite and compares your mechanism against its own signature.
- submit_feedback      file the findings.

What a finding must carry, and the exact key names - they are read, not
paraphrased, and a field under another name is a field nothing can use:

    {
      "feature": "the piece of geometry this is about",
      "faces": [cad face ids],
      "radius_mm": 210.4,
      "z_mm": 17.9,
      "mechanism": "one of the names above",
      "evidence": [
        {"quantity": "s_hoop", "value": 1482.0, "where": "bore",
         "source": "node:469"}
      ],
      "change": {
        "parameter": "rim_half_thickness_mm",
        "current_value": 15.0,
        "proposed_value": 13.5,
        "relative_change": -0.10,
        "rationale": "why this variable and this direction"
      },
      "prediction": {
        "metric": "max_von_mises_mpa",
        "direction": "decrease",
        "expected_relative_change": 0.05,
        "at": "bore"
      },
      "rationale": "the argument, in a paragraph"
    }

- `evidence` is the measurements the finding rests on. Each entry names a
  quantity, its value, and where it was read - `node:<id>`, `face:<id>` or
  `field:<name>`. Every one is re-read and reported. A number you did not
  measure will be found out.
- `change.parameter` is the generator's own name for the variable, spelled
  exactly. The names it takes, and there are no others:

{free_variables}

  Those are the template layer's - how the first revision was asked for. They
  are not the limit of what can be changed. A model parameter is
  `<node_id>.<param>` and `list_document_params` reports every one of them;
  prefer those, because they name the geometry directly. Measured on the
  second real run: the agent located the peak on the fir-tree flanks
  correctly and then asked for `fir_tree_flank_fillet_radius_mm`, which
  exists in neither layer - the variable it meant was one of the seven
  `fillet_sketch` radii on the cutter. The geometry was right and the name
  was not.
- Every change has to say what to change the variable *to*: a `proposed_value`,
  or a `relative_change` to move the current one by. A change with neither
  asks for the revision that already exists. Asking for more than a quarter of
  a change in one step is refused by the repair kernel that would apply it.
- A change has to be one you can point at: use `locate_point` on the peak, and
  put the faces it returns in `faces`. A variable named without the geometry
  it belongs to is a guess, and a finding that asks for no change at all is a
  better answer than a guess - but only after `locate_point` has been tried,
  because the reason to file no change is that the geometry cannot be
  identified, and that is a thing you can check.
- `prediction` is the metric, the direction, and the size as a positive
  fraction. Write it so the next revision can prove it wrong. That is what
  makes this a loop rather than a sequence of runs - the next result does not
  just give a new number, it says whether the reasoning that asked for the
  change was right.
- `change` and `prediction` may be null, and must be null together for the two
  mechanisms whose fix is not a geometry change.

A finding whose keys are wrong is refused with the reason and you get another
turn, so it is worth checking one before filing it.

Do not optimise a number the verification stage marked suspect or
confirmed_wrong. A suspect number moved between mesh levels; a confirmed_wrong
one is contradicted by two measurements that should agree. Building on either
is how a loop converges on an artefact.

If the honest answer is that the results do not justify changing the disc -
because the load was wrong, because the peak is an artefact of the model,
because nothing is near a margin - then say that. Filing a finding that asks
for a geometry change on the strength of a number that describes the model is
worse than filing nothing.

Your last call offers only submit_feedback and needs_input. Budget accordingly.
"""


# What the agent may spend. Measured on the fourth real run: it used all 26 it
# had - 24 plus the terminal reasks - and filed one of its two findings with
# "I ran out of budget before locating the specific geometry variable". The
# budget was a number picked before there was a run to measure it against, and
# it was short. A call is a tool reply and not a solve, so the cost of being
# generous here is small next to the cost of a diagnosis that stops halfway.
DEFAULT_MAX_CALLS = 32


def spec(*, max_calls: int = DEFAULT_MAX_CALLS) -> AgentSpec:
    return AgentSpec(
        name="feedback",
        tool_name="feedback_action",
        tool_description=(
            "Measure the solved field, inspect a region, check a draft finding, "
            "or file the findings for the next revision."
        ),
        action_model=Action,
        # Filled from the generator's own vocabulary rather than written into
        # the prompt by hand, so a variable added or withdrawn downstream
        # reaches the agent without anyone remembering to edit this file.
        #
        # Substituted rather than formatted: the prompt carries a worked JSON
        # example, and `str.format` reads its braces as fields of its own.
        system_prompt=SYSTEM_PROMPT.replace(
            "{free_variables}",
            "\n".join(
                f"    {name}" for name in design_variables.free_variables()
            ),
        ),
        user_prompt=(
            "The solve has finished and the results have been judged. Decide "
            "what the next revision of this disc should be.\n\n"
            "Start with get_result_context, then find where the stress "
            "actually is before deciding what it means. Every finding you file "
            "must rest on measurements you took, and carry a prediction the "
            "next run can refute."
        ),
        submit_actions=frozenset({"submit_feedback", "needs_input"}),
        max_calls=max_calls,
        timeout_s=600,
        terminal_model=CommitAction,
    )


def _load_state(ctx: RunContext) -> FeedbackState:
    """Read the field and everything the run said about it, once."""
    solve_dir = Path(ctx.path) / "solve"
    case = ctx.case
    material = None
    if case is not None and case.physics is not None:
        points = case.physics.material.points
        if points:
            material = [(point.temperature_c, point.yield_mpa) for point in points]
    field = results.ResultField.load(solve_dir, material)
    context = results.load_context(solve_dir, Path(ctx.path))

    load_nodes: set[int] = set()
    load_faces: list[int] = []
    selection = context.get("selection") or {}
    for node_id in selection.get("union_node_ids") or []:
        load_nodes.add(int(node_id))
    for face_id in selection.get("selected_face_indices") or []:
        load_faces.append(int(face_id))

    # The model the run solved, so a peak can be joined to a face of it. Read
    # from the case rather than guessed from a directory name: a bundle that
    # does not match the solve is a join to a different part.
    bundle = None
    feature = ""
    solid_index = 0
    if case is not None and case.bundle is not None and case.bundle.path:
        bundle = Path(case.bundle.path)
        if not bundle.is_dir():
            bundle = None
    if case is not None and case.load_surface is not None:
        feature = case.load_surface.feature
        solid_index = case.load_surface.solid_index

    document = None
    if bundle is not None:
        path = bundle / "document.json"
        if path.is_file():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                document = None

    return FeedbackState(
        field=field,
        context=context,
        solve_dir=solve_dir,
        job_dir=Path(ctx.path),
        bundle=bundle,
        feature=feature,
        solid_index=solid_index,
        document=document,
        load_nodes=load_nodes,
        load_faces=load_faces,
    )


def to_case_feedback(state: FeedbackState) -> FeedbackReport:
    """The submitted findings, as the case's feedback."""
    submitted = state.submitted or {}
    findings = []
    for index, raw in enumerate(submitted.get("findings") or []):
        # Rebuilt field by field rather than splatted, so that a submission
        # carrying a key this model does not have is recorded with the rest of
        # the finding intact. Splatting it raised a validation error that
        # ended a completed solve over four key names.
        change, dropped = normalise_change(raw.get("change") or {})
        prediction = {
            key: value for key, value in (raw.get("prediction") or {}).items()
            if key in PREDICTION_KEYS
        }
        evidence = []
        for entry in raw.get("evidence") or []:
            if not isinstance(entry, dict):
                continue
            try:
                value = float(entry["value"])
            except (KeyError, TypeError, ValueError):
                # A citation with no number is not a citation. It is left out
                # rather than stored with a zero, which would read as a
                # measurement of zero and be re-read as one.
                continue
            evidence.append({
                "quantity": str(entry.get("quantity") or ""),
                "value": value,
                "where": str(entry.get("where") or ""),
                "source": str(entry.get("source") or ""),
            })
        findings.append(Finding(
            id=str(raw.get("id") or f"F{index + 1}"),
            feature=str(raw.get("feature") or ""),
            faces=[int(v) for v in raw.get("faces") or []],
            role_keys=[str(v) for v in raw.get("role_keys") or []],
            radius_mm=raw.get("radius_mm"),
            z_mm=raw.get("z_mm"),
            mechanism=raw.get("mechanism") or "unresolved",
            severity_metric=str(raw.get("severity_metric") or ""),
            severity_value=raw.get("severity_value"),
            evidence=[Evidence(**entry) for entry in evidence],
            change=ProposedChange(**change) if change.get("parameter") else None,
            prediction=(
                Prediction(**prediction)
                if {"metric", "direction"} <= set(prediction) else None
            ),
            consistency=check_finding(raw, state),
            rationale=(
                str(raw.get("rationale") or "")
                + (f" [keys dropped: {', '.join(sorted(dropped))}]"
                   if dropped else "")
            ),
        ))

    verdicts = _quotable(state)
    excluded = [
        f"{name}: {verdict}"
        for name, verdict in sorted(verdicts.items())
        if verdict in ("suspect", "confirmed_wrong")
    ]
    return FeedbackReport(
        findings=findings,
        summary=str(submitted.get("summary") or ""),
        excluded_quantities=excluded,
        limits=list(submitted.get("limits") or []) + list(state.field.limits),
        written=Written(
            by_stage="feedback", kind="agent_decision",
            source="measured from the solve's own result field",
        ),
    )


def feedback(ctx: RunContext, *, api_key_file: Path | None = None,
             max_calls: int = 24) -> Case:
    """The stage: read the results and decide what the next revision should be.

    It writes the report into the case and into the job, and it does not
    change anything. Applying a finding is the generation side's job and a
    different run's problem; keeping the two apart is what lets a change be
    traced back to the measurement that asked for it.
    """
    from seekflow_structural.runtime.caller import build_caller

    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "feedback has no case", "feedback")

    state = _load_state(ctx)
    caller, model_config = build_caller(api_key_file)
    outcome = run_agent(
        spec(max_calls=max_calls), caller=caller,
        model_config=model_config, dispatch=DISPATCH, context=state,
    )
    ctx.charge_tool_calls(outcome.calls, "feedback")
    ctx.job.write("agent/feedback.json", {
        "schema_version": "feedback_run_v1",
        "trace": outcome.trace,
        "rejected_calls": outcome.rejected,
        "final": outcome.final,
        "checks": state.checks,
        "calls": outcome.calls,
        "exhausted": outcome.exhausted,
    })

    final = outcome.final or exhausted_final("feedback")
    if not final.get("accepted"):
        raise StructuralError(
            "feedback_not_filed",
            "the feedback agent did not file its findings: "
            + "; ".join(final.get("questions", [])),
            "feedback",
        )
    if state.submitted is None:
        raise StructuralError(
            "feedback_not_filed",
            "the feedback agent reported a submission it did not make",
            "feedback",
        )

    report = to_case_feedback(state)
    case.feedback = report
    ctx.job.write("feedback.json", {
        "schema_version": "structural_feedback_v1",
        "summary": report.summary,
        "excluded_quantities": report.excluded_quantities,
        "limits": report.limits,
        "findings": [
            {
                **finding.model_dump(mode="json"),
                "consistency": [
                    comparison.model_dump(mode="json")
                    for comparison in finding.consistency
                ],
            }
            for finding in report.findings
        ],
    })
    ctx.job.event({
        "kind": "feedback_filed",
        "stage": "feedback",
        "findings": len(report.findings),
        "mechanisms": [finding.mechanism for finding in report.findings],
        "with_a_change": sum(1 for f in report.findings if f.change is not None),
        "excluded_quantities": report.excluded_quantities,
    })
    return case
