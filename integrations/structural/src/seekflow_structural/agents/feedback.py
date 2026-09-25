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
import math
import re
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
    knowledge,
    results,
)
from seekflow_structural.tools.design_variables import (
    DESIGN_VARIABLES,
    MAX_RELATIVE_CHANGE,
)

# How close to a symmetry plane or an axis a peak has to be before its
# position is a property of the model rather than of the part.
EDGE_TOLERANCE_MM = 0.5

# A claimed measurement is re-read from the solved field at submission. The
# tolerance allows ordinary decimal rounding in the agent's JSON while still
# rejecting a number that was not measured.
EVIDENCE_RELATIVE_TOLERANCE = 1e-4


class Action(ToolAction):
    """The feedback agent's tool call."""

    action: Literal[
        "get_result_context",
        "rank_problem_regions",
        "snapshot_evidence",
        "query_nodes",
        "profile",
        "find_concentrations",
        "inspect_region",
        "section_resultant",
        "face_stress",
        "locate_point",
        "list_document_params",
        "get_rules",
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
    limit: int = Field(
        default=6,
        description="for rank_problem_regions: how many candidate regions to return",
    )
    reducer: Literal["max", "min", "mean", "sum"] = Field(
        default="max",
        description=(
            "for snapshot_evidence: how to reduce the selected nodes. "
            "`max`/`min` return the extreme and its node id; `mean` and `sum` "
            "return the aggregate without a node."
        ),
    )
    mechanism: str = Field(
        default="",
        description=(
            "for get_rules: which mechanism to report the loop's record for, "
            "by the same name the findings use - hoop_driven, radial_driven, "
            "stress_concentration, section_overload, thermal_gradient. Empty "
            "reports every mechanism the loop holds a rule for."
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
    normalisation: object | None = None
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
    # What the loop has already learnt. Absent is a supported state - a run
    # that has no knowledge base attached loses one tool and nothing else -
    # and the record is read rather than enforced, exactly as it is for the
    # revision agent.
    base: knowledge.KnowledgeBase | None = None
    submitted: dict | None = None
    checks: list[dict] = dataclasses.field(default_factory=list)
    # Whether the deterministic region ranking has been measured. Submission
    # waits for it because the ranking is what keeps a suspect global mesh peak
    # from being treated as an addressable design problem.
    ranked: bool = False

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
            "load_integrity": _load_integrity(state),
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


def _load_integrity(state: FeedbackState) -> dict:
    """What the load actually reached, as the emission path measured it.

    The audit is written by the load path and, until now, this stage read
    three fields out of it - the target force, the applied resultant and the
    mechanism - of which the first two are equal by construction. So the one
    question that has to be settled before a peak is treated as a property of
    the design, whether the load reached the surface it was meant to reach,
    had no measurement behind it here.

    Two different things are reported apart, because they have different
    meanings and the raw fraction in the audit conflates them. A selected face
    that produced no element face at all received no load: nothing was pressed
    there. A pressed face whose element faces cover only part of its CAD area
    is a property of the model rather than of the selection - a half-thickness
    model with z=0 symmetry contains half of every face that straddles the
    mid-plane, and a sector contains one sector's worth.
    """
    audit = state.context.get("load_audit") or {}
    emission = audit.get("emission") or {}
    by_face = audit.get("area_accounting_by_face") or {}

    unpressed: list[tuple[int, float]] = []
    pressed_area = 0.0
    reached_area = 0.0
    lowest_coverage: float | None = None
    for key, row in by_face.items():
        try:
            face_index = int(key)
        except (TypeError, ValueError):
            continue
        occ = float(row.get("occ_area_mm2") or 0.0)
        mapped = float(row.get("mapped_area_mm2") or 0.0)
        if not row.get("element_face_count"):
            unpressed.append((face_index, occ))
            continue
        if occ > 0:
            coverage = mapped / occ
            lowest_coverage = (
                coverage if lowest_coverage is None
                else min(lowest_coverage, coverage)
            )
        pressed_area += mapped
        reached_area += occ
    unpressed.sort()

    selection_area = float(emission.get("occ_area_total_mm2") or 0.0)
    unpressed_area = sum(area for _, area in unpressed)
    limits: list[str] = []
    if unpressed:
        limits.append(
            f"{len(unpressed)} of {len(by_face)} selected faces "
            f"({unpressed_area:.4g} mm^2 of {selection_area:.4g} mm^2) produced "
            "no element face, so no load reached them at all: "
            + " | ".join(
                str(text) for text in (emission.get("limits") or [])[:2]
            )
        )
    if lowest_coverage is not None and lowest_coverage < 0.999:
        limits.append(
            "a pressed face carries element faces over only "
            f"{lowest_coverage:.3f} of its CAD area. That is what a model that "
            "contains part of the part looks like - a half thickness with z=0 "
            "symmetry holds half of every face that straddles the mid-plane - "
            "and it is not the same thing as a face the load never reached"
        )
    return {
        "mechanism": emission.get("mechanism"),
        "pressure_mpa": emission.get("pressure_mpa"),
        "pressed_area_mm2": round(pressed_area, 4),
        "reached_selection_area_mm2": round(reached_area, 4),
        "declared_selection_area_mm2": round(selection_area, 4),
        "mesh_coverage_of_reached_faces": (
            round(pressed_area / reached_area, 6) if reached_area else None
        ),
        "lowest_single_face_coverage": (
            round(lowest_coverage, 6) if lowest_coverage is not None else None
        ),
        "faces_with_no_element_face": [index for index, _ in unpressed],
        "faces_with_no_element_face_area_mm2": round(unpressed_area, 4),
        "limits": limits,
    }


def _entry_shape(entry) -> dict:
    """One knowledge entry, with the observations behind its status."""
    return {
        "id": entry.id,
        "status": entry.status,
        "parameter": entry.parameter,
        "direction": entry.direction,
        "at": entry.at,
        "expected_metric": entry.expected_metric,
        "expected_direction": entry.expected_direction,
        "confirmations": entry.confirmations,
        "refutations": entry.refutations,
        "note": entry.note,
        "observations": [
            {
                "revision": item.revision,
                "outcome": item.outcome,
                "predicted_relative_change": item.predicted_relative_change,
                "measured_relative_change": item.measured_relative_change,
                "side_effects": item.side_effects,
                "note": item.note,
            }
            for item in entry.observations
        ],
    }


def _get_rules(action, state: FeedbackState) -> dict:
    """The hypotheses the loop holds, and which of them it has never tested.

    This agent decides what the next revision should be, and until now it
    decided that with no sight of what the loop had learnt: the record of
    hypotheses and outcomes was written by every revision and read by the
    revision agent alone. A rule settles only when the same direction has been
    proposed and measured more than once - one observation cannot tell a
    mechanism from a coincidence - so an agent that cannot see the record has
    nothing to propose from but its own reading of the field, and it drifts.

    What is reported is the record and not advice. `untested` is the part
    worth reading: a hypothesis for one of this part's mechanisms that the
    loop has never measured is a question it already holds and has no evidence
    for.
    """
    if state.base is None:
        return {
            "ok": True,
            "result": {
                "attached": False,
                "limits": [
                    "no knowledge base is attached to this run, so what the "
                    "loop has already learnt cannot be read here. Every other "
                    "tool works the same either way"
                ],
            },
        }
    wanted = [
        part.strip()
        for part in str(action.mechanism or "").split(",")
        if part.strip()
    ]
    mechanisms = wanted or sorted(
        {entry.mechanism for entry in state.base.entries}
    )
    out: dict[str, dict] = {}
    untested: list[str] = []
    for mechanism in mechanisms:
        entries = state.base.for_mechanism(mechanism, include_refuted=True)
        never = [
            entry.id
            for entry in entries
            if entry.status != "refuted"
            and not entry.observations
            and entry.is_design_change
        ]
        untested.extend(never)
        out[mechanism] = {
            "rules": [
                _entry_shape(entry)
                for entry in entries if entry.status != "refuted"
            ],
            "retired": [
                _entry_shape(entry)
                for entry in entries if entry.status == "refuted"
            ],
            "untested": never,
        }
    return {
        "ok": True,
        "result": {
            "attached": True,
            "mechanisms": out,
            "untested": untested,
            "note": (
                "`rules` is what the loop holds and how often each has held - "
                "a record, not a recommendation, and `retired` names changes "
                "that were already made and did not do what they were for. "
                "`untested` names hypotheses for these mechanisms that this "
                "loop has never measured. A change that tests one of them is "
                "worth more than a change that tests nothing the record "
                "already covers, because the loop can only tell a mechanism "
                "from a coincidence by meeting it twice."
            ),
        },
    }


def _rank_problem_regions(action, state: FeedbackState) -> dict:
    """Rank measured problem regions by whether they can be acted on.

    The largest von Mises value on an FEA mesh is often a local load or mesh
    artefact. Verification may mark it `suspect` while a lower, broad region is
    stable and controllable. A flat list of concentrations leaves the agent to
    re-discover that distinction from several tools; this one joins the
    verification verdict, load/symmetry context, decay measurement and nearby
    document parameters into one ranked list.

    It does not choose the engineering mechanism. It removes a known blind
    spot: a suspect global peak appearing above an actionable stable region.
    """
    limit = max(1, min(int(action.limit or 6), 12))
    clusters = results.concentrations(
        state.field.stressed(), action.relative_threshold, action.cell_mm
    )
    by_id = {node.nid: node for node in state.field.nodes}
    verdicts = _quotable(state)
    stress = state.metrics().get("stress") or {}
    global_peak = float(clusters.get("peak_mpa") or 0.0)
    global_verdict = verdicts.get("max_von_mises_mpa", "unverified")
    load_verdict = verdicts.get(
        "max_load_surface_von_mises_mpa", "unverified"
    )
    bad = {"suspect", "confirmed_wrong"}
    ranked: list[dict] = []
    for entry in clusters.get("concentrations") or []:
        node = by_id.get(int(entry.get("peak_node") or 0))
        if node is None:
            continue
        band = max(abs(node.r) * 0.25, 20.0)
        neighbours = state.field.where(
            r_min=node.r - band, r_max=node.r + band,
            z_min=node.z - band, z_max=node.z + band,
        )
        fall = results.decay(state.field, node, nodes=neighbours)
        half = (fall.get("reached") or {}).get("0.5") or {}
        half_distance = half.get("distance_mm")
        extent = float(entry.get("extent_mm") or 0.0)
        shape_ratio = (
            float(half_distance) / extent if half_distance is not None and extent
            else None
        )
        components = entry.get("peak_components_mpa") or {}
        dominant = (
            max(components, key=lambda name: abs(float(components[name])))
            if components else ""
        )
        on_loaded = node.nid in state.load_nodes
        at_symmetry = abs(node.z) <= EDGE_TOLERANCE_MM
        is_global = node.nid == stress.get("max_node")

        reasons: list[str] = []
        allowed = True
        if is_global and global_verdict in bad:
            allowed = False
            reasons.append(
                f"the global maximum is {global_verdict}; optimising it would "
                "optimise a number the verification stage will not quote"
            )
        if on_loaded and load_verdict in bad:
            allowed = False
            reasons.append(
                f"the loaded-surface maximum is {load_verdict}; check the "
                "load model before changing the part"
            )
        if at_symmetry:
            reasons.append(
                f"the peak lies on the z={node.z:.4g} symmetry plane; decide "
                "from the surrounding field whether this is a section maximum "
                "or only a cut-face artefact before aiming a change at it"
            )
        if not reasons:
            reasons.append("no verification veto applies")

        nearby: list[dict] = []
        if state.document is not None:
            table = document_tools.reaching(state.document, float(node.r))
            for name, meta in table.items():
                at_r = meta.get("at_r_mm")
                nearby.append({
                    "parameter": name,
                    "op": meta.get("op"),
                    "component": meta.get("component"),
                    "current_value": meta.get("value"),
                    "at_r_mm": at_r,
                    "distance_mm": (
                        round(abs(float(at_r) - node.r), 6)
                        if isinstance(at_r, (int, float)) else None
                    ),
                })
            nearby.sort(key=lambda item: (
                item["distance_mm"] is None, item["distance_mm"] or 0.0,
                item["parameter"],
            ))
            nearby = nearby[:6]
        if nearby:
            reasons.append(
                f"{len(nearby)} editable parameter(s) reach this radius"
            )
        elif state.document is not None:
            reasons.append(
                "no document parameter was measured as reaching this radius"
            )

        fraction = entry["peak_mpa"] / global_peak if global_peak else 0.0
        score = fraction
        if not allowed:
            score *= 0.05
        if nearby:
            score *= 1.2
        ranked.append({
            **entry,
            "dominant_component": dominant,
            "on_a_loaded_face": on_loaded,
            "at_a_symmetry_plane": at_symmetry,
            "is_global_peak": is_global,
            "verification": global_verdict if is_global else "local_region",
            "mechanism_hint": (
                "idealisation_edge" if at_symmetry else
                "load_application" if on_loaded else
                "hoop_driven" if dominant == "s_hoop" else
                "radial_driven" if dominant == "s_radial" else
                "unresolved"
            ),
            "shape_hint": (
                "stress_concentration" if shape_ratio is not None
                and shape_ratio < 0.3 else "section_overload"
            ),
            "half_fall_mm": half_distance,
            "half_fall_to_extent": shape_ratio,
            "optimisation_allowed": allowed,
            "actionability": reasons,
            "nearby_editable": nearby,
            "rank_score": round(score, 9),
        })
    ranked.sort(
        key=lambda item: (
            item["optimisation_allowed"], item["rank_score"], item["peak_mpa"],
            -item["peak_node"],
        ),
        reverse=True,
    )
    top = ranked[:limit]
    state.ranked = True
    return {
        "ok": True,
        "result": {
            "global_peak_mpa": clusters.get("peak_mpa"),
            "global_peak_verdict": global_verdict,
            "relative_threshold": clusters.get("relative_threshold"),
            "cell_mm": clusters.get("cell_mm"),
            "ranked_regions": top,
            "selected_region": next(
                (item for item in top if item["optimisation_allowed"]), None
            ),
            "limits": list(clusters.get("limits") or []) + [
                "the ranking does not decide the mechanism; it orders regions "
                "by whether a design change there is admissible and editable"
            ],
        },
    }


def _where(state: FeedbackState, action) -> list[results.Node]:
    return state.field.where(
        r_min=action.r_min, r_max=action.r_max,
        z_min=action.z_min, z_max=action.z_max,
    )


def _aggregate_evidence_value(
    state: FeedbackState,
    quantity: str,
    reducer: str,
    bounds: dict,
) -> dict:
    """Compute a replayable aggregate over the solved field."""
    nodes = state.field.where(
        r_min=bounds.get("r_min"),
        r_max=bounds.get("r_max"),
        z_min=bounds.get("z_min"),
        z_max=bounds.get("z_max"),
    )
    values = [
        (getattr(node, quantity), node)
        for node in nodes
        if getattr(node, quantity, None) is not None
    ]
    if not values:
        raise StructuralError(
            "no_aggregate_samples",
            f"no node with a measured {quantity!r} falls inside those bounds",
            "feedback",
        )
    numbers = [float(value) for value, _node in values]
    if reducer == "max":
        value, node = max(values, key=lambda pair: pair[0])
        return {"value": float(value), "node": node.nid, "count": len(values)}
    if reducer == "min":
        value, node = min(values, key=lambda pair: pair[0])
        return {"value": float(value), "node": node.nid, "count": len(values)}
    if reducer == "mean":
        return {"value": sum(numbers) / len(numbers), "node": None,
                "count": len(values)}
    if reducer == "sum":
        return {"value": sum(numbers), "node": None, "count": len(values)}
    raise StructuralError(
        "unknown_reducer",
        f"{reducer!r} is not one of max, min, mean, sum",
        "feedback",
    )


def _aggregate_source(
    quantity: str, reducer: str, bounds: dict
) -> str:
    selected = []
    for name in ("r_min", "r_max", "z_min", "z_max"):
        value = bounds.get(name)
        if value is not None:
            selected.append(f"{name}={float(value):.12g}")
    return "agg:" + quantity + ":" + reducer + (":" + ";".join(selected)
                                                   if selected else "")


def _parse_aggregate_source(source: str) -> tuple[str, str, dict] | None:
    parts = source.split(":", 3)
    if len(parts) < 3 or parts[0] != "agg":
        return None
    quantity, reducer = parts[1], parts[2]
    if reducer not in ("max", "min", "mean", "sum"):
        return None
    bounds: dict[str, float] = {}
    if len(parts) == 4 and parts[3]:
        for item in parts[3].split(";"):
            if "=" not in item:
                return None
            name, raw = item.split("=", 1)
            if name not in ("r_min", "r_max", "z_min", "z_max"):
                return None
            try:
                bounds[name] = float(raw)
            except ValueError:
                return None
    return quantity, reducer, bounds


def _snapshot_evidence(action, state: FeedbackState) -> dict:
    """Return a self-describing aggregate that can be re-read later."""
    bounds = {
        "r_min": action.r_min,
        "r_max": action.r_max,
        "z_min": action.z_min,
        "z_max": action.z_max,
    }
    result = _aggregate_evidence_value(
        state, action.quantity, action.reducer, bounds
    )
    source = _aggregate_source(action.quantity, action.reducer, bounds)
    return {
        "ok": True,
        "result": {
            "source": source,
            "quantity": action.quantity,
            "reducer": action.reducer,
            "bounds": {key: value for key, value in bounds.items()
                       if value is not None},
            "value": round(result["value"], 6),
            "node": result["node"],
            "node_count": result["count"],
            "note": (
                "Cite this exact `source` string in evidence. The harness "
                "recomputes it from the solved field; a remembered aggregate "
                "without this source will not re-read."
            ),
        },
    }


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
        normalisation=state.normalisation,
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
    graph = document_tools.dependency_graph(state.document)
    return {
        "ok": True,
        "result": {
            "available": True,
            "summary": document_tools.summary(state.document),
            "editable_count": len(table),
            "by_component": by_component,
            "editable": table,
            "joint_edit_groups": graph.get("joint_edit_groups") or [],
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
        elif source.startswith("agg:"):
            parsed = _parse_aggregate_source(source)
            if parsed is None:
                note = (
                    "this aggregate source is not well formed. Use the exact "
                    "`source` returned by snapshot_evidence."
                )
            else:
                quantity, reducer, bounds = parsed
                try:
                    actual = _aggregate_evidence_value(
                        state, quantity, reducer, bounds
                    )["value"]
                except Exception as exc:  # noqa: BLE001
                    note = f"aggregate could not be recomputed: {exc}"
        elif source.startswith("field:"):
            name = source.split(":", 1)[1]
            actual = _reported_scalar(state, name)
            if actual is None:
                allowed = ", ".join(sorted(results.reported_scalars(state.metrics())))
                note = (
                    f"this run reports no scalar called {name!r}. `field:` "
                    "sources are only for the reported global scalars: "
                    + allowed
                    + ". Use snapshot_evidence for band means, region maxima "
                    "and other aggregates."
                )
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

def _location_consistency(
    finding: dict, state: FeedbackState
) -> list[Comparison]:
    """Whether the feature the finding names can be where it says it is.

    A finding names the piece of geometry it is about and the radius the
    problem sits at, and both are claims about the same model measured from
    different places - the name out of the document, the radius out of the
    field. A disagreement is reported and not enforced: a feature is described
    in words, and a word the document does not use is a naming convention
    rather than an error. What a mismatch does say is that the reasoning
    cannot be followed from the model, and that is worth seeing before a
    revision is spent on it.
    """
    reach = _feature_reach(finding, state.document)
    if reach is None:
        return []
    spans = ", ".join(
        f"{node_id} r = {low}..{high} mm"
        for node_id, (low, high) in reach["spans_r_mm"].items()
    )
    return [Comparison(
        name="location.feature",
        left=f"{reach['feature']!r}",
        right=f"a feature acting at r = {reach['peak_r_mm']} mm",
        residual=0.0 if reach["reaches"] else 1.0,
        relative=0.0 if reach["reaches"] else 1.0,
        note=(
            f"the named feature's own parameters act at {spans}; the finding "
            f"places its problem at r = {reach['peak_r_mm']} mm"
            if reach["spans_r_mm"] else "the named feature carries no radius"
        ),
    )]


def check_finding(finding: dict, state: FeedbackState) -> list[Comparison]:
    """Everything the harness can measure about one finding's argument."""
    return (
        _verify_evidence(finding.get("evidence") or [], state)
        + _mechanism_consistency(finding, state)
        + _location_consistency(finding, state)
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


# A feature name is prose, so the node it names is found by matching
# whole words against the document's own node ids and never by substring: an
# id like `disc_poly` must not be read out of the words "the disc profile".
_FEATURE_TOKEN = re.compile(r"[^A-Za-z0-9_]+")


def _feature_radius_span(
    document: dict, node_id: str
) -> tuple[float, float] | None:
    """Where one document operation's own parameters act, in radius.

    Read from the same `editable` table a change is checked against, so the
    span and the change vocabulary cannot disagree about where an operation
    is. Operations whose parameters carry no radius - a count, a plane that
    does not move radially - contribute nothing and do not make the span
    wrong; they make it partial, which is why the span is reported next to the
    verdict rather than used silently.
    """
    radii = [
        float(entry["at_r_mm"])
        for entry in document_tools.editable(document).values()
        if str(entry.get("node") or "") == node_id
        and isinstance(entry.get("at_r_mm"), (int, float))
    ]
    return (min(radii), max(radii)) if radii else None


def _feature_reach(finding: dict, document: dict | None) -> dict | None:
    """Where the feature a finding names acts, and whether that covers the peak.

    Returns None when the comparison cannot be made - no document, no stated
    radius, no node id among the words the feature is described with - which
    is not the same as the comparison passing. It declines rather than
    concluding, exactly as `_reach` does, because a feature described in
    words the document does not use is a naming convention and not an error.
    """
    if document is None:
        return None
    radius = finding.get("radius_mm")
    if radius is None:
        return None
    text = str(finding.get("feature") or "")
    node_ids = {
        str(node.get("id"))
        for node in (document.get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    named = sorted(
        token for token in _FEATURE_TOKEN.split(text) if token in node_ids
    )
    if not named:
        return None
    spans = {}
    for node_id in named:
        span = _feature_radius_span(document, node_id)
        if span is not None:
            spans[node_id] = span
    if not spans:
        return None
    peak = float(radius)
    return {
        "feature": text,
        "named_features": named,
        "spans_r_mm": {
            node_id: [round(low, 3), round(high, 3)]
            for node_id, (low, high) in spans.items()
        },
        "peak_r_mm": peak,
        "reaches": any(
            low - FILLET_REACH_MM <= peak <= high + FILLET_REACH_MM
            for low, high in spans.values()
        ),
    }


def _feature_reach_problem(finding: dict, document: dict | None) -> str | None:
    """A finding whose own feature cannot be where it says the problem is.

    Measured, and this check is the fix. A run located its peak at
    r = 208.09 mm and named the feature it was about as the fir-tree flank of
    the final cut. That operation's own parameters act at r = 277.9 to
    300.0 mm; r = 208.087 mm is where the lightening holes are, and the one
    editable parameter the model has exactly there is a vertex of the hole
    profile - the same vertex an earlier revision had already moved and
    measured the peak move with. The finding concluded that nothing editable
    controlled the place, which was true of the feature it named and false of
    the place the peak was at. The revision proposed no change, the loop
    stopped, and nothing was learnt from a solve that had already been paid
    for.

    Both halves of the disagreement are the agent's own measurements - the
    name comes from the document and the radius from the field - so reporting
    it does not tell the agent which one is wrong, only that they cannot both
    be right.
    """
    reach = _feature_reach(finding, document)
    if reach is None or reach["reaches"]:
        return None
    if document is None:
        return None
    spans = " and ".join(
        f"{node_id} acts at r = {low} to {high} mm"
        for node_id, (low, high) in reach["spans_r_mm"].items()
    )
    available = sorted(
        document_tools.reaching(document, reach["peak_r_mm"])
    )
    return (
        f"the finding is about r = {reach['peak_r_mm']} mm and names "
        f"{reach['feature']!r}, but {spans} - so the feature it names is not "
        "where it says the problem is. The name and the radius are both its "
        "own measurements and they cannot both be right: measure the node "
        "again, locate_point it, and name the geometry that is actually there. "
        "What this model does have at r = "
        f"{reach['peak_r_mm']} mm is: "
        + (", ".join(available) if available else "nothing")
        + "."
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
    # And the geometry it names has to be where it says the problem is, which
    # is checked whether or not a change is proposed - a finding that asks for
    # nothing on the grounds that no parameter controls the place is only a
    # finding if the place it names is the place it measured.
    misplaced = _feature_reach_problem(finding, document)
    if misplaced:
        problems.append(misplaced)
    prediction = finding.get("prediction")
    if prediction:
        missing = [
            key for key in ("metric", "direction", "expected_relative_change")
            if key not in prediction
        ]
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
        size = prediction.get("expected_relative_change")
        try:
            size_number = float(size)
        except (TypeError, ValueError):
            size_number = None
        if size_number is None or size_number < 0.0:
            problems.append(
                "prediction.expected_relative_change has to be a non-negative "
                "number. Direction carries the sign; size carries only the "
                "magnitude."
            )
    return problems


def finding_argument_problems(
    finding: dict, state: FeedbackState
) -> list[str]:
    """Measure the claims that must hold before a finding can be filed.

    `finding_shape_problems` checks whether a finding can be read. This checks
    whether its argument can survive the measurements the harness already
    owns: evidence values have to re-read from the field, a geometry change has
    to name a real document parameter, and a change has to carry the
    falsifiable prediction that makes the next revision informative.

    Mechanism agreement is deliberately not a rejection. Whether a radial peak
    is best described as local concentration or section overload is engineering
    judgement. Whether the number 1807.906 is actually present at node 246 is
    not.
    """
    problems: list[str] = []
    mechanism = str(finding.get("mechanism") or "")
    position_mechanisms = {
        "stress_concentration", "section_overload", "hoop_driven",
        "radial_driven", "thermal_gradient",
    }
    non_design_mechanisms = {
        "load_application", "idealisation_edge", "unresolved",
    }

    change = finding.get("change")
    prediction = finding.get("prediction")
    if change and not prediction:
        problems.append(
            "the finding asks for a geometry change but states no prediction. "
            "The next revision can only test a change if the finding commits "
            "to a metric, direction and expected size before the change is "
            "made."
        )
    if prediction and not change:
        problems.append(
            "the finding states a prediction but asks for no change. There is "
            "nothing for the next revision to test, so the prediction is not "
            "an argument."
        )
    if mechanism in non_design_mechanisms and (change or prediction):
        problems.append(
            f"mechanism {mechanism!r} is not a geometry-change diagnosis; its "
            "change and prediction must both be null. Report the model or "
            "load-path problem without proposing a design edit."
        )
    if mechanism in position_mechanisms and change:
        if finding.get("radius_mm") is None or finding.get("z_mm") is None:
            problems.append(
                f"mechanism {mechanism!r} proposes a geometry change but does "
                "not state both radius_mm and z_mm. A change cannot be aimed "
                "at a peak that the finding has not located."
            )

    if change and prediction:
        metric = str(prediction.get("metric") or "")
        reported = results.reported_scalars(state.metrics())
        if metric not in reported or reported.get(metric) is None:
            problems.append(
                f"prediction names metric {metric!r}, which this solve did "
                "not report as a number. The next revision would run and "
                "could not test the prediction. Use one of: "
                + ", ".join(sorted(reported)) + "."
            )

    normalised, _dropped = normalise_change(change or {})
    parameter = str(normalised.get("parameter") or "")
    proposed = normalised.get("proposed_value")
    relative = normalised.get("relative_change")
    current = normalised.get("current_value")
    if (
        proposed is not None
        and relative is not None
        and current is not None
        and abs(float(current)) > 1e-12
    ):
        implied = float(current) * (1.0 + float(relative))
        if not math.isclose(
            float(proposed), implied, rel_tol=1e-4, abs_tol=1e-9
        ):
            problems.append(
                f"change.proposed_value {float(proposed):g} and "
                f"change.relative_change {float(relative):g} disagree: from "
                f"the stated current value {float(current):g}, the relative "
                f"change implies {implied:g}. State one magnitude, not two."
            )
    if state.document is not None and parameter and "." in parameter:
        if document_tools.resolve(state.document, parameter) is None:
            radius = finding.get("radius_mm")
            available = (
                sorted(document_tools.reaching(state.document, float(radius)))
                if radius is not None else []
            )
            problems.append(
                f"change names document parameter {parameter!r}, but this "
                "model has no such operation parameter. "
                + (
                    "The measured editable parameters reaching r = "
                    f"{float(radius):g} mm are: " + ", ".join(available) + "."
                    if available else
                    "Call list_document_params and name one of the parameters "
                    "reported for this model."
                )
            )

    comparisons = _verify_evidence(finding.get("evidence") or [], state)
    for comparison in comparisons:
        if comparison.relative is None:
            problems.append(
                f"{comparison.name} cannot be re-read from this solve: "
                f"{comparison.note or comparison.right}. Evidence has to name "
                "a source that exists in the result field."
            )
        elif comparison.relative > EVIDENCE_RELATIVE_TOLERANCE:
            problems.append(
                f"{comparison.name} does not re-read: {comparison.left}, but "
                f"the field holds {comparison.right}. File the measured value, "
                "not a recollection."
            )
    return problems


def existing_feedback_problems(
    findings: list[dict], state: FeedbackState
) -> list[str]:
    """Why a stored feedback file is no longer valid for this revision.

    A stored job can survive a disk move or resume with a bundle path that no
    longer resolves. The current loop has the revision document even then, so
    it validates the stored findings against that document before deciding not
    to rerun feedback.
    """
    problems: list[str] = []
    if not findings:
        return ["the stored feedback has no findings"]
    ids = [
        str(finding.get("id") or f"F{index + 1}")
        for index, finding in enumerate(findings)
    ]
    duplicates = sorted(
        finding_id for finding_id in set(ids) if ids.count(finding_id) > 1
    )
    if duplicates:
        problems.append("duplicate finding ids: " + ", ".join(duplicates))
    changes: list[str] = []
    for index, finding in enumerate(findings):
        parameter = str(((finding.get("change") or {}).get("parameter")) or "")
        if parameter:
            changes.append(f"{ids[index]}:{parameter}")
        for problem in (finding_shape_problems(finding, state.document)
                        + finding_argument_problems(finding, state)):
            problems.append(f"finding {index}: {problem}")
    if len(changes) > 1:
        problems.append(
            "multiple design changes in one stored submission: "
            + ", ".join(changes)
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
    if not state.ranked:
        raise StructuralError(
            "missing_region_ranking",
            "rank_problem_regions has not been run. It joins the peak regions "
            "to the verification verdict, load and symmetry context, fall-off "
            "shape and editable parameters; without it a suspect global peak "
            "can be mistaken for a changeable design problem. Run it before "
            "submitting findings.",
            "feedback",
        )
    known = {"stress_concentration", "section_overload", "hoop_driven",
             "radial_driven", "thermal_gradient", "load_application",
             "idealisation_edge", "unresolved"}
    finding_ids = [
        str(finding.get("id") or f"F{index + 1}")
        for index, finding in enumerate(findings)
    ]
    duplicates = sorted(
        finding_id for finding_id in set(finding_ids)
        if finding_ids.count(finding_id) > 1
    )
    if duplicates:
        raise StructuralError(
            "duplicate_finding_id",
            "these finding ids are used more than once: "
            + ", ".join(duplicates),
            "feedback",
        )
    design_changes: list[str] = []
    for index, finding in enumerate(findings):
        normalised, _dropped = normalise_change(finding.get("change") or {})
        parameter = str(normalised.get("parameter") or "")
        if parameter:
            design_changes.append(f"{finding_ids[index]}:{parameter}")
    if len(design_changes) > 1:
        raise StructuralError(
            "multiple_design_changes",
            "one revision can test one design change, but this submission "
            "contains " + ", ".join(design_changes) + ". Keep one finding with "
            "a change and prediction; file the others as diagnosis without a "
            "change so the next solve can attribute its result correctly.",
            "feedback",
        )
    for index, finding in enumerate(findings):
        mechanism = str(finding.get("mechanism") or "")
        if mechanism not in known:
            raise StructuralError(
                "unknown_mechanism",
                f"finding {index} claims mechanism {mechanism!r}, which is not "
                "one of: " + ", ".join(sorted(known)),
                "feedback",
            )
        problems = (
            finding_shape_problems(finding, state.document)
            + finding_argument_problems(finding, state)
        )
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
    "get_rules": _get_rules,
    "rank_problem_regions": _rank_problem_regions,
    "snapshot_evidence": _snapshot_evidence,
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
  decided may be quoted, and what could not be measured. Read it first. It
  also reports what the load actually reached: how much of the selected
  surface was pressed, and which selected faces received no load at all.
- get_rules            what the loop has already learnt about these mechanisms:
  every rule it holds with how many times that rule has held and been refuted,
  the changes it made and had to stop believing, and which hypotheses for these
  mechanisms this loop has never measured. Read it before you decide. A change
  that tests a hypothesis the record does not yet cover is worth more than a
  change that tests nothing it covers, because a mechanism and a coincidence
  look the same once and differ when the loop meets them twice.
- rank_problem_regions  join stress concentrations to the verification
  verdict, load/symmetry context, fall-off shape and editable parameters near
  each radius. Call this immediately after get_result_context and start from
  the highest-ranked region with `optimisation_allowed: true`. A region with
  `optimisation_allowed: false` may still be diagnosed, but it must not carry a
  geometry change.
- snapshot_evidence    compute a replayable aggregate - max, min, mean or sum
  - over nodes in an r/z box and return an exact `agg:<quantity>:<reducer>:<bounds>`
  source string to cite in evidence. Use it for band means, regional maxima, section resultants and
  other statistics that a single node cannot represent. A number cited under
  a different source will not be accepted merely because the model believes
  it was measured.
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
is how a loop converges on an artefact. If rank_problem_regions reports an
allowed region lower than a suspect global peak, the lower region is the one to
diagnose and change. Submit no change only when every allowed region has no
editable parameter that can affect it, and say which region and measurement
rule out each candidate.

The loop learns one observation at a time, and a rule only settles after
the same direction has been proposed and measured more than once. So when a
mechanism in `get_rules` has a hypothesis this loop has never tested, the
change that tests it is a real answer to "what should the next revision be" -
better than a change that tests nothing the record already covers, even if
that other change is the one you would have reached for first.

If the honest answer is that the results do not justify changing the disc -
because the load was wrong, because the peak is an artefact of the model,
because nothing is near a margin - then say that. Filing a finding that asks
for a geometry change on the strength of a number that describes the model is
worse than filing nothing.

One revision can test only one design change. Submit at most one finding with
a non-null `change`; file other diagnoses without a change so the next solve
can attribute its result to one action. The prediction metric must be one the
solve actually reported as a number, and the change must carry a prediction
with both direction and expected_relative_change.

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
            "Start with get_result_context, then rank_problem_regions, then "
            "measure the top allowed region before deciding what it means. "
            "Every finding you file "
            "must rest on measurements you took, and carry a prediction the "
            "next run can refute."
        ),
        submit_actions=frozenset({"submit_feedback", "needs_input"}),
        max_calls=max_calls,
        timeout_s=600,
        terminal_model=CommitAction,
    )


def _load_state(
    ctx: RunContext,
    base: knowledge.KnowledgeBase | None = None,
    document_override: dict | None = None,
) -> FeedbackState:
    """Read the field and everything the run said about it, once."""
    from seekflow_structural.pipeline.materialize import normalisation_for

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

    document = document_override
    if document is None and bundle is not None:
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
        normalisation=(normalisation_for(case) if case is not None else None),
        feature=feature,
        solid_index=solid_index,
        document=document,
        load_nodes=load_nodes,
        load_faces=load_faces,
        base=base,
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
             max_calls: int = DEFAULT_MAX_CALLS,
             base: knowledge.KnowledgeBase | None = None,
             document: dict | None = None) -> Case:
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

    state = _load_state(ctx, base=base, document_override=document)
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
