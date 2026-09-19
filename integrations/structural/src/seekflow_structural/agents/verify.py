"""Judging which of the reported numbers may be quoted.

The stage is not a validation gate and it is not a checklist of limits. Every
verdict it produces rests on two measurements that were arrived at
independently - the solver's reactions against the load written into the deck,
the deck's temperature table against a re-evaluation of the same field, the
z=0 plane's displacement against the constraint that was asked for. Nothing
here compares a number with a threshold, because what counts as adequate is an
engineering decision about a specific component and the harness does not know
it.

It is deliberately not an agent with a language model. The judgement it makes
is a comparison of numbers, and a model in the loop would add a way for that
comparison to be reported as something other than what it was. What the
language model is for is upstream: choosing the domain, the faces, the
physics, the regions. What this stage does is arithmetic on evidence, and it
belongs in code.

The three verdicts, and none of them means "correct":

    confirmed_wrong   an independent pair of measurements contradicts.
    suspect           nothing contradicts, but the quantity moved between
                      mesh levels, so it has not settled.
    unverified        no independent second opinion exists. This is the state
                      of most numbers, and saying so is the point.
"""
from __future__ import annotations

import json
from pathlib import Path

from seekflow_structural.case.model import Case, QuantityVerdict
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.tools import checks, results

# What a reader would want to quote, and therefore what has to be judged.
QUOTABLE = (
    ("max_von_mises_mpa", "the global peak stress"),
    ("max_load_surface_von_mises_mpa", "the peak on the loaded surface"),
    ("min_safety_factor", "the minimum safety factor"),
    ("max_displacement_mm", "the maximum displacement"),
)


def _metrics(ctx: RunContext) -> dict:
    path = ctx.path / "solve" / "structural_metrics.json"
    if not path.is_file():
        raise StructuralError(
            "no_metrics",
            f"{path} does not exist; the solve has to finish before anything "
            "can be judged",
            "verify",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_audit(ctx: RunContext) -> dict:
    path = ctx.path / "solve" / "load_audit.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _reaction_sum(ctx: RunContext) -> list[float] | None:
    """The solver's reactions, read from the summary the deck wrote.

    The deck accumulates these from the nodal `RF` arrays rather than through
    `FSUM`, which excludes reactions - so this is the solver's own answer and
    not a restatement of the input.
    """
    path = ctx.path / "solve" / "result_summary.txt"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("REACTION_SUM_N"):
            try:
                return [float(v) for v in line.split("=")[1].split()]
            except (IndexError, ValueError):
                return None
    return None


def _selected_faces(ctx: RunContext) -> dict:
    """The face-to-node mapping the meshing stage wrote.

    Carries each selected face's area and its normal, which is what says
    which way the pressure on it pushes - the one thing about the load the
    force-versus-target comparison cannot see.
    """
    path = ctx.path / "solve" / "selected_face_nodes.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("per_face") or {}


def _load_surface_sum(ctx: RunContext) -> float | None:
    path = ctx.path / "solve" / "result_summary.txt"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("LOAD_SURFACE_SUM_N"):
            try:
                values = [float(v) for v in line.split("=")[1].split()]
            except (IndexError, ValueError):
                return None
            import math

            return math.dist(values, (0.0, 0.0, 0.0))
    return None


def build_verdicts(ctx: RunContext, case: Case) -> list[QuantityVerdict]:
    metrics = _metrics(ctx)
    audit = _load_audit(ctx)
    stress = metrics.get("stress", {})
    displacement = metrics.get("displacement", {})
    provenance = metrics.get("temperature_provenance", {})
    symmetry = metrics.get("axial_symmetry", {})

    # --- the checks, each an independent pair -----------------------------
    # A cyclic model has no external load path: the sector stands for a whole
    # ring and the constraint that completes it is inside the model. The
    # reaction sum is then zero by construction, and comparing it with the
    # load applied to one sector would report a disagreement that is not one.
    constraints = case.physics.constraints if case and case.physics else None
    reactions = checks.reaction_vs_applied(
        _reaction_sum(ctx), audit.get("applied_resultant_n"),
        closed_ring=bool(constraints and constraints.cyclic_symmetry),
    )
    temperature = checks.temperature_two_sites(
        provenance.get("max_abs_delta_c"),
        provenance.get("compared_node_count"),
    )
    symmetry_check = checks.symmetry_residual(
        symmetry.get("max_abs_uz_mm"),
        bool(symmetry.get("node_count")),
    )
    load_surface = checks.load_surface_vs_target(
        _load_surface_sum(ctx),
        audit.get("emission", {}).get("centrifugal_estimate_n"),
        audit.get("target_force_n_per_slot"),
    )
    convergence = checks.mesh_convergence(
        _convergence_change(ctx)
    )
    # Each quantity gets the convergence evidence about *itself*.
    #
    # Attaching the whole list to every quantity made one metric's movement
    # settle every other metric's verdict: `classify` filters the evidence by
    # name, every convergence comparison shares the `mesh_convergence` prefix,
    # and `any` over them then says a peak has moved because a displacement
    # did. Measured on D27, where the four movements are 5.09%, 4.94%, 0.63%
    # and 0.02% - so the two numbers that had settled were being reported as
    # unsettled alongside the two that had not.
    convergence_for = {
        comparison.name.split(".", 1)[1]: [comparison]
        for comparison in convergence
        if "." in comparison.name
    }

    def settled_evidence(quantity: str):
        """The convergence comparisons about this quantity, if any were made."""
        if convergence_for:
            return convergence_for.get(quantity, [])
        # No study was run, or none of its numbers could be compared - so the
        # one comparison saying so is attached to everything, which is what it
        # is about.
        return convergence
    # The load-surface check above compares a force against a target force and
    # is silent about direction, so a load applied to the wrong face passes it
    # as long as it sums to the right magnitude. Measured: nine wrong
    # submissions in twenty-four runs, every one of them through every check
    # the chain had.
    load_direction = checks.load_pushes_outward(_selected_faces(ctx))

    # --- what each reported number may be quoted on ------------------------
    # The load-surface peak carries the convergence evidence, because a peak
    # sampled where the load is applied is the first thing to suspect of being
    # an artefact of the application rather than of the component.
    #
    # The direction check is evidence for every stress-derived number, not
    # only for the peak on the loaded surface. If the pressure resolves inward
    # on a load driven by rotation, then the load is on the wrong faces, and
    # every field computed from it is wrong - the peak in the web and the
    # minimum safety factor as much as the peak at the load. Confining it to
    # the load-surface number would leave the headline numbers saying
    # "unverified" about a solve that answered a different question.
    # The convergence evidence is attached to every quantity, for the same
    # reason the direction check is. A number that moved between mesh levels
    # has not settled wherever it sits, and confining the evidence to the peak
    # at the load left the headline number unchecked against the one
    # measurement that bore on it.
    #
    # Measured on D27, and it was the wrong way round: the peak von Mises
    # stress moved 5.09% between a mesh of 181,362 nodes and one of 194,011,
    # while the peak on the loaded surface moved 0.63%. The convergence check
    # was the only one that could have said so, and it was attached to the
    # number that did not need it.
    specs = {
        "max_von_mises_mpa": [
            reactions, temperature, symmetry_check, load_direction
        ] + settled_evidence("max_von_mises_mpa"),
        "max_load_surface_von_mises_mpa": [
            load_surface, load_direction
        ] + settled_evidence("max_load_surface_von_mises_mpa"),
        "min_safety_factor": [
            temperature, symmetry_check, load_direction
        ] + settled_evidence("min_safety_factor"),
        "max_displacement_mm": [
            reactions, symmetry_check, load_direction
        ] + settled_evidence("max_displacement_mm"),
    }

    values = {
        "max_von_mises_mpa": stress.get("max_von_mises_mpa"),
        "max_load_surface_von_mises_mpa": stress.get(
            "max_load_surface_von_mises_mpa"
        ),
        "min_safety_factor": stress.get("min_safety_factor"),
        "max_displacement_mm": displacement.get("max_mm"),
    }

    verdicts = []
    for name, description in QUOTABLE:
        evidence = specs[name]
        verdict = checks.classify(evidence)
        verdicts.append(
            QuantityVerdict(
                quantity=name,
                verdict=verdict,
                checks=evidence,
                rationale=_rationale(name, description, verdict, values[name],
                                     evidence),
            )
        )
    return verdicts


def _convergence_change(ctx: RunContext) -> dict | None:
    """How far each reported quantity moved between two mesh levels.

    Read from the two levels' own metrics when no summary was written, which
    is the usual case: nothing in this package writes
    `convergence_report.json`, so the first branch never fired and this
    function returned None on every run that had in fact run a study. The
    meshing stage had already paid for the second solve; the only thing
    missing was the subtraction.

    What that cost: measured on D27, the peak von Mises stress moved 5.09%
    between a mesh of 181,362 nodes and one of 194,011, and every verdict came
    back `unverified` - which says no second opinion exists. One did.
    """
    path = ctx.path / "mesh" / "convergence" / "convergence_report.json"
    if path.is_file():
        summary = json.loads(path.read_text(encoding="utf-8")).get(
            "relative_change_percent"
        )
        if summary:
            return summary
    # a convergence run may have been written beside the mesh instead
    for candidate in (ctx.path / "mesh").rglob("convergence*.json"):
        if candidate.name == "convergence_report.json":
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "relative_change_percent" in payload:
            return payload["relative_change_percent"]
    # Neither summary form exists, so the two levels are compared here.
    return results.mesh_convergence_percent(ctx.path)


def _rationale(name: str, description: str, verdict: str, value,
               evidence) -> str:
    if verdict == "confirmed_wrong":
        return (
            f"{description} is contradicted by two measurements that should "
            "agree; the value is reported but must not be used."
        )
    if verdict == "suspect":
        return (
            f"{description} moved between mesh levels, so it has not settled. "
            "It may be converging towards the right answer, but the number as "
            "reported is mesh-dependent."
        )
    if value is None:
        return f"{description} was not produced by this run."
    return (
        f"{description} has no independent second opinion: nothing in this "
        "run can contradict it, and nothing outside it was compared against "
        "it. It is reported as measured and not as confirmed."
    )


def verify(ctx: RunContext) -> Case:
    from seekflow_structural.case.model import Written

    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "verify has no case", "verify")
    case.verdicts = build_verdicts(ctx, case)
    if case.solve is not None:
        case.solve.written = case.solve.written or Written(
            by_stage="verify", kind="measured"
        )

    ctx.job.write("verification.json", {
        "schema_version": "structural_verification_v1",
        "verdicts": [v.model_dump(mode="json") for v in case.verdicts],
    })
    ctx.job.event({
        "kind": "verified",
        "stage": "verify",
        "verdicts": {v.quantity: v.verdict for v in case.verdicts},
    })
    return case


def report_lines(case: Case) -> list[str]:
    """What the verification contributes to the written report."""
    if not case.verdicts:
        return []
    out = ["", "## What may be quoted", ""]
    for verdict in case.verdicts:
        out.append(f"- **{verdict.quantity}**: `{verdict.verdict}` — "
                   f"{verdict.rationale}")
        for check in verdict.checks:
            if check.residual is None and check.relative is None:
                continue
            out.append(
                f"  - {check.name}: {check.left} vs {check.right}"
            )
    return out
