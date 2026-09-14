"""Cross-consistency between measurements that do not depend on each other.

The rule these obey, and the reason they are not a checklist of limits: a
check compares two independent measurements and reports the residual. A rule
asserts a threshold. "The reaction sum should equal minus the applied load" is
a check - two numbers arrived at by different routes, which must agree.
"Safety factor must exceed 1.5" is a rule, and it does not belong here: what
counts as adequate is an engineering decision about a specific component, not
something the harness knows.

Every function returns a `Comparison` and none of them raises. A disagreement
is a finding to report, and the reader decides what it means.
"""
from __future__ import annotations

import math

from seekflow_structural.case.model import Comparison

# A measurement is independent of another when arriving at it did not involve
# the other. The reaction sum comes from the solver's constrained degrees of
# freedom; the applied load comes from what was written into the deck. Nothing
# computed the second from the first, so agreement between them is evidence.


def _relative(a: float, b: float) -> float:
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale


def reaction_vs_applied(
    reaction_sum: list[float] | None,
    applied: list[float] | None,
    *,
    closed_ring: bool = False,
) -> Comparison:
    """The solver's reactions against the load the deck was given.

    `FSUM` is deliberately not used: measured on ANSYS 18.1, it sums element
    surface and body loads and excludes both nodal forces and reactions, so on
    a deck whose load is applied as nodal forces it reports the centrifugal
    body load alone. The reaction sum here is accumulated from the nodal `RF`
    arrays instead, which are the solver's own answer.

    `closed_ring` is set when the deck was written with cyclic symmetry, and
    it means this comparison does not apply. `CPCYC` makes the sector stand
    for a complete ring: the blade load is carried by hoop tension in the
    neighbouring sectors the constraint supplies, which is a force inside the
    model and not a reaction to it. Measured on D27, the deck's only external
    supports are the z=0 symmetry plane in UZ and a single anchored node in
    UY - neither can carry a radial load - and the solver duly reported a
    reaction sum of 0.0004 N against 10 000 N applied. Reading that as a
    contradiction marked both headline numbers `confirmed_wrong` on a model
    whose load path was closed, and the load path is something this file can
    see from the deck rather than guess at from the number.
    """
    if closed_ring:
        return Comparison(
            name="reaction_vs_applied",
            left="solver reactions", right="applied load",
            note=(
                "the deck was written with cyclic symmetry, so the sector "
                "stands for a complete ring and the applied load is reacted "
                "inside it by the cyclic constraint. The net reaction over "
                "the nodes is zero by construction and is not comparable with "
                "the load applied to one sector; nothing is concluded here."
            ),
        )
    if reaction_sum is None or applied is None:
        return Comparison(
            name="reaction_vs_applied",
            left="solver reactions", right="applied load",
            note="one of the two was not available in the results",
        )
    reaction_magnitude = math.dist(reaction_sum, (0.0, 0.0, 0.0))
    applied_magnitude = math.dist(applied, (0.0, 0.0, 0.0))
    # Statically, the reactions cancel the applied load - the magnitudes are
    # equal and the vectors opposite.
    return Comparison(
        name="reaction_vs_applied",
        left=f"|sum RF| = {reaction_magnitude:.6g} N",
        right=f"|applied| = {applied_magnitude:.6g} N",
        residual=reaction_magnitude - applied_magnitude,
        relative=_relative(reaction_magnitude, applied_magnitude),
        note=(
            "the reactions and the applied load are arrived at independently "
            "and must cancel"
        ),
    )


def temperature_two_sites(
    deck_delta_max: float | None, compared_nodes: int | None
) -> Comparison:
    """The deck's own temperature table against an independent evaluation."""
    if deck_delta_max is None:
        return Comparison(
            name="temperature_two_sites",
            left="deck table", right="independent evaluation",
            note=(
                "the deck's node_temperature.csv was not found, so the two "
                "were never compared"
            ),
        )
    return Comparison(
        name="temperature_two_sites",
        left="deck table", right="independent evaluation",
        residual=deck_delta_max,
        relative=deck_delta_max,
        note=(
            f"largest disagreement over {compared_nodes} nodes; the safety "
            "factor is computed against the deck's values, so any drift here "
            "is a drift in the reported safety factor"
        ),
    )


def symmetry_residual(max_abs_uz_mm: float | None,
                      plane_present: bool) -> Comparison:
    """The axial symmetry the deck asked for, as the solver delivered it."""
    if not plane_present:
        return Comparison(
            name="symmetry_residual",
            left="z=0 plane present", right="required by the domain",
            note=(
                "the results contain no z=0 nodes, so the symmetry could not "
                "be checked at all"
            ),
        )
    return Comparison(
        name="symmetry_residual",
        left=f"max |UZ| on z=0 = {max_abs_uz_mm:.3g} mm",
        right="exactly zero, by the constraint",
        residual=max_abs_uz_mm,
        relative=None,
        note=(
            "ANSYS drops D,ALL,UZ,0 on CPCYC slave nodes and logs a warning "
            "per node; the constraint survives only as an emergent property "
            "of the master/slave pairing, so it is worth checking every run"
        ),
    )


def mesh_convergence(relative_change: dict | None) -> list[Comparison]:
    """How far each reported quantity moved between two mesh levels."""
    if not relative_change:
        return [Comparison(
            name="mesh_convergence", left="two mesh levels",
            right="one mesh level",
            note="no convergence study was run for this case",
        )]
    out = []
    for name, percent in relative_change.items():
        out.append(
            Comparison(
                name=f"mesh_convergence.{name}",
                left="fine mesh", right="coarse mesh",
                residual=percent,
                relative=abs(percent) / 100.0 if percent is not None else None,
                note=(
                    "the change between a mesh and one thirty percent finer. "
                    "A global field moving under a percent has settled; a peak "
                    "sampled at a concentration often has not"
                ),
            )
        )
    return out


def load_surface_vs_target(
    load_surface_sum_n: float | None,
    centrifugal_estimate_n: float | None,
    target_n: float | None,
) -> Comparison:
    """The force crossing the loaded surface against the load asked for.

    The ANSYS-side sum includes the centrifugal load of those elements, so the
    estimate of that contamination is reported beside it rather than silently
    subtracted: on D27 it is roughly a tenth of the blade load, and a reader
    who does not know that would read a one-tenth disagreement as a bug.
    """
    if load_surface_sum_n is None or target_n is None:
        return Comparison(
            name="load_surface_vs_target",
            left="force across the loaded surface", right="target load",
            note="the loaded surface was not named in the deck, or no target",
        )

    # The ANSYS-side sum includes the centrifugal load of the loaded elements.
    # That term is real and known to be there; leaving it in and comparing
    # anyway would report a disagreement that is not a disagreement, so with
    # no estimate for it the comparison declines to conclude rather than
    # producing a relative difference it cannot stand behind.
    if centrifugal_estimate_n is None:
        return Comparison(
            name="load_surface_vs_target",
            left=f"{load_surface_sum_n:.6g} N across the loaded surface",
            right=f"{target_n:.6g} N target",
            note=(
                "the left-hand number includes the centrifugal load of the "
                "loaded elements, which this run did not estimate. Without "
                "that term the two cannot be compared, so no residual is "
                "reported - a difference here would be the contamination, "
                "not a finding."
            ),
        )

    net = load_surface_sum_n - centrifugal_estimate_n
    return Comparison(
        name="load_surface_vs_target",
        left=f"{net:.6g} N across the loaded surface",
        right=f"{target_n:.6g} N target",
        residual=net - target_n,
        relative=_relative(net, target_n),
        note=(
            "the centrifugal load of the loaded elements "
            f"({centrifugal_estimate_n:.6g} N) is subtracted as an estimate "
            "and reported here rather than hidden"
        ),
    )


def section_equilibrium(
    section_resultant_n: float | None, crossing_load_n: float | None
) -> Comparison:
    """The stress field across a cut against the load that must cross it."""
    if section_resultant_n is None or crossing_load_n is None:
        return Comparison(
            name="section_equilibrium",
            left="stress resultant across a cut", right="load crossing it",
            note="no section was integrated for this case",
        )
    return Comparison(
        name="section_equilibrium",
        left=f"{section_resultant_n:.6g} N from the stress field",
        right=f"{crossing_load_n:.6g} N crossing the section",
        residual=section_resultant_n - crossing_load_n,
        relative=_relative(section_resultant_n, crossing_load_n),
        note=(
            "integrating the stress across a cut and comparing it with the "
            "load that has to pass through is the one check that follows the "
            "load path from where it enters to where it is reacted"
        ),
    )


def classify(comparisons: list[Comparison],
             relative_tolerance: float = 0.02) -> str:
    """A verdict for one quantity, from the evidence about it.

    Three states, and none of them means "correct".

      confirmed_wrong  an independent pair of measurements contradicts.
      suspect          nothing contradicts, but the quantity moved between
                       mesh levels, so its value is not settled.
      unverified       there is no independent second opinion. This is the
                       honest default, and it is the state of most numbers a
                       chain like this produces.

    Two measurements agreeing is deliberately not a fourth state. Agreement
    between two measurements of the same model is not validation - only
    agreement with something outside the model would be, and this chain has no
    analytic oracle. Reporting "verified" on the strength of internal
    agreement would overstate exactly what a report is for.
    """
    measured = [
        c for c in comparisons
        if c.relative is not None and c.relative == c.relative
    ]
    if not measured:
        return "unverified"
    # A quantity that moved between mesh levels has not settled. That is not
    # the same as being contradicted - it may well be converging towards the
    # right answer - so it is judged before the contradiction test.
    settled = [
        c for c in measured if c.name.startswith("mesh_convergence")
    ]
    if any(c.relative > relative_tolerance for c in settled):
        return "suspect"
    contradicted = [
        c for c in measured if not c.name.startswith("mesh_convergence")
    ]
    if any(c.relative > relative_tolerance for c in contradicted):
        return "confirmed_wrong"
    return "unverified"


def load_pushes_outward(per_face: dict) -> Comparison:
    """Which way, on balance, the pressure on the selected faces pushes.

    Every check above compares two numbers. This one compares a number against
    a direction, because a magnitude cannot carry one: a load of ten thousand
    newtons pulling a disc outward and a load of ten thousand newtons pushing
    it inward are the same number and opposite physics, and the check that
    compares force against target says nothing about which was applied.

    That mattered. Measured over twenty-four runs of the face-finding agent
    with one extra summary field in its replies, nine submissions were wrong
    and every one of them passed every check the chain had - four of them
    having put the load on the disc's outer cylindrical face, where the
    pressure acts inward and the blade load is centrifugal and pulls outward.

    The quantity is the area-weighted radial component of the inward face
    normal, which is the direction pressure acts in. +1 is a set whose
    pressure pushes straight out from the axis, -1 straight in, 0 a set that
    cancels. Nothing here decides what the right value is.

    WHAT IT DOES NOT CATCH, because the name invites more than it delivers:
    it sees which way the pressure pushes, not where it pushes. A selection of
    inward-facing flanks at the wrong radius scores just as well as one at the
    right radius - measured, a wrong submission on the mid-web faces scored
    +0.652 against the correct answer's +0.742, and nothing here separates
    them. It catches a load on the wrong *kind* of surface and is silent about
    a load on the right kind in the wrong place. Which of two similarly-facing
    surfaces a blade bears on is engineering knowledge, not arithmetic, and no
    check in this file can supply it.

    The `relative` it reports is zero for a load that pushes outward and the
    size of the inward fraction for one that does not, which is what lets
    `classify` act on it: a check whose relative is None is filtered out
    before the verdict, so this one used to be reported beside a number
    without ever being able to contradict it. An inward resultant on a load
    driven by rotation is a contradiction of the stated physics, and
    `confirmed_wrong` is the verdict that says so.
    """
    if not per_face:
        return Comparison(
            name="load_pushes_outward",
            left="no selected faces",
            right="the direction a centrifugal blade load acts in",
            note="the face-to-node mapping named no faces",
        )

    total_area = 0.0
    outward = 0.0
    without_a_normal = 0
    for row in per_face.values():
        area = float(row.get("area_mm2") or 0.0)
        radial = (
            (row.get("normal_cylindrical") or {}).get("radial")
        )
        if radial is None:
            without_a_normal += 1
            continue
        # Pressure acts along the inward normal, so the force the face puts on
        # the body runs opposite to the outward normal it reports.
        total_area += area
        outward += area * (-float(radial))

    if total_area <= 0:
        return Comparison(
            name="load_pushes_outward",
            left="no measured face area",
            right="the direction a centrifugal blade load acts in",
            note="every selected face had zero area or no measured normal",
        )

    fraction = outward / total_area
    return Comparison(
        name="load_pushes_outward",
        left=f"{fraction:+.6g} (radial fraction of the pressure resultant)",
        right="outward, for a load driven by rotation",
        residual=fraction,
        # Zero when the pressure pushes outward, and how far inward it pushes
        # when it does not. Without this the comparison is filtered out of
        # `classify` and cannot contradict anything.
        relative=max(0.0, -fraction),
        note=(
            "the area-weighted direction the applied pressure pushes in, "
            "positive meaning away from the axis. A blade load is centrifugal "
            "and pulls outward, so a selection whose pressure pushes inward "
            "is not the surface it enters through - however much force it "
            "sums to, which is all the force-versus-target check can see."
            + (f"; {without_a_normal} faces had no measured normal"
               if without_a_normal else "")
        ),
    )
