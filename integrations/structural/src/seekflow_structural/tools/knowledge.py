"""What the loop has learned, and how much of it to believe.

An engineering rule of the form "when the bore is hoop-driven, taking thickness
off the rim brings the peak down" is a hypothesis. It is taught to every
engineer, it is written in every handbook, and on a particular component it may
still be wrong - because the rim's mass and the rim's own stress pull in
opposite directions, and which one wins depends on the geometry.

This module does not decide which rules are true. It keeps a record of every
time the loop has acted on one, whether the result matched what was predicted,
and what else moved at the same time. A rule that has been right three times
and never wrong is marked `trusted`; a rule that has been wrong twice is marked
`refuted` and stops being offered. A rule that was trusted and then failed is
demoted back to a candidate - because the honest reading of a trusted rule
failing is not that the failure is noise, it is that the rule was narrower than
it looked.

Two things about the record are deliberate.

The first is that the seed rules ship marked `seed`, not `trusted`. They are
the textbook mappings, and the whole point of the loop is that a textbook
mapping is a starting hypothesis rather than an answer. A system that began by
trusting them would have no way to discover that one of them is wrong on this
component.

The second is that a rule is scored on the *direction* of what happened, not
the magnitude. A prediction that the peak would fall and a measurement showing
it fell by a third of what was expected is a confirmed mechanism with a bad
constant, and those are worth telling apart: the mechanism is what the next
change depends on, and the constant is what a second observation fixes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# How many times a rule has to hold before it is treated as settled, and how
# many failures retire it. Three and two are conventions, not truths, and they
# are here rather than distributed through the code so that a reader can
# disagree with them in one place.
TRUSTED_AFTER = 3
REFUTED_AFTER = 2

# How far off a prediction may be and still count as the mechanism working.
# A sign that matches with a magnitude out by more than this factor is
# `partial`: the direction was right, the size was not.
MAGNITUDE_TOLERANCE = 3.0

# What a metric has to move by before a run is read as having moved it at all,
# when the run has not said how far its own numbers move under a re-mesh.
#
# This is a floor of last resort and it is set low on purpose, because it is
# not a measurement. Measured on D27: the same part meshed at 181,362 nodes
# and at 194,011 - seven per cent more - moved the peak stress by 5.09%. So
# the real floor is around five per cent, a hundred times this constant, and a
# run that does not supply its own floor will confirm rules it has not tested.
# `score_prediction` prefers whatever floor the caller measured, and says so
# in the observation when it has to fall back to this one.
MOVED_BY = 0.005

Outcome = Literal["confirmed", "partial", "refuted", "unmoved", "unmeasurable"]
Status = Literal["seed", "candidate", "trusted", "refuted"]


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["structural_knowledge_v1"] = "structural_knowledge_v1"
    entries: list["KnowledgeEntry"] = Field(default_factory=list)

    # --- reading ---------------------------------------------------------

    def for_mechanism(
        self, mechanism: str, *, include_refuted: bool = False
    ) -> list["KnowledgeEntry"]:
        """The rules recorded for a mechanism, best first.

        Refuted rules are left out by default, because offering one as advice
        is proposing it again. They are kept in the record all the same, and
        `include_refuted` returns them: a rule that was tried and made things
        worse is the most useful thing in this file to the agent about to try
        it a second time, and a reader who cannot see it has no way to avoid
        repeating the mistake.

        Which of the two a caller wants depends on the question. "What should
        I do?" wants them out. "Has this been tried?" wants them in. A rule
        that no mechanism matches is not offered either way, which is why an
        unknown mechanism returns nothing rather than everything.
        """
        return sorted(
            (
                entry for entry in self.entries
                if entry.mechanism == mechanism
                and (include_refuted or entry.status != "refuted")
            ),
            key=lambda entry: (entry.status != "trusted", -entry.confirmations,
                               entry.refutations),
        )

    def get(self, entry_id: str) -> "KnowledgeEntry | None":
        return next(
            (entry for entry in self.entries if entry.id == entry_id), None
        )

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return {
            "entries": len(self.entries),
            "by_status": counts,
            "trusted": [entry.id for entry in self.entries
                        if entry.status == "trusted"],
            "refuted": [entry.id for entry in self.entries
                        if entry.status == "refuted"],
        }

    # --- writing ---------------------------------------------------------

    def record(
        self, entry_id: str, observation: "Observation"
    ) -> "KnowledgeEntry":
        """Add one result to a rule and re-decide what to think of it."""
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(f"no knowledge entry {entry_id!r}")
        entry.observations.append(observation)
        entry.status = _status_for(entry)
        return entry

    def upsert(self, entry: "KnowledgeEntry") -> "KnowledgeEntry":
        """Add a rule, or return the existing one with the same id.

        A rule proposed twice is one rule with two tests, not two rules. The
        identity is what it says to do - mechanism, variable, direction - and
        not the revision that happened to propose it.
        """
        existing = self.get(entry.id)
        if existing is not None:
            return existing
        self.entries.append(entry)
        return entry

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "KnowledgeBase":
        """Read the base, or start from the seed rules if there is none.

        Starting from the seeds rather than from nothing is deliberate: an
        empty base would leave the first revision with no hypothesis to test,
        and a loop whose first step is a guess learns nothing from it.
        """
        path = Path(path)
        if not path.is_file():
            base = cls()
            base.entries = seed_entries()
            return base
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class Observation(BaseModel):
    """One test of one rule: what was predicted, and what the run measured."""

    model_config = ConfigDict(extra="forbid")

    revision: str
    metric: str
    predicted_relative_change: float
    measured_relative_change: float | None = None
    outcome: Outcome
    # Other reported quantities that moved the wrong way over the same change.
    # A rule that fixes one number by breaking another is not a rule that
    # works, and the record has to be able to say so.
    side_effects: list[str] = Field(default_factory=list)
    note: str = ""


class KnowledgeEntry(BaseModel):
    """A rule: for a mechanism, changing a variable this way does that.

    `parameter` is empty for the two mechanisms whose action is not a design
    change - a load applied to the wrong faces and a peak on a plane the model
    cut on are both fixed by changing the model, and recording them as rules
    about geometry would put them in the same list as the rules that are.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    mechanism: str
    parameter: str = ""
    direction: Literal["increase", "decrease", ""] = ""
    at: str = ""
    expected_metric: str = "max_von_mises_mpa"
    expected_direction: Literal["increase", "decrease"] = "decrease"
    status: Status = "seed"
    observations: list[Observation] = Field(default_factory=list)
    note: str = ""

    @property
    def confirmations(self) -> int:
        return sum(
            1 for item in self.observations
            if item.outcome in ("confirmed", "partial")
        )

    @property
    def refutations(self) -> int:
        return sum(1 for item in self.observations if item.outcome == "refuted")

    @property
    def is_design_change(self) -> bool:
        return bool(self.parameter)


def _status_for(entry: KnowledgeEntry) -> Status:
    """What to think of a rule, given everything recorded about it.

    A trusted rule that fails is demoted rather than kept: the failure is
    evidence that the rule was narrower than it looked - true for some
    components and not this one - and leaving it trusted would keep offering
    it with the same confidence.
    """
    if entry.refutations >= REFUTED_AFTER:
        return "refuted"
    if entry.confirmations >= TRUSTED_AFTER and entry.refutations == 0:
        return "trusted"
    return "candidate"


def score_prediction(
    predicted_relative_change: float,
    measured_relative_change: float | None,
    *,
    metric: str = "max_von_mises_mpa",
    revision: str = "",
    noise_floor: float | None = None,
) -> Observation:
    """Compare what a change was expected to do with what it did.

    The direction decides the outcome and the magnitude only grades it. A
    prediction of a fall that produced a fall is a mechanism that works, even
    if the size was wrong by a factor; a prediction of a fall that produced a
    rise is a mechanism that does not, however small the rise.

    `unmoved` is kept apart from both. A change that moved the metric by less
    than the noise of a re-mesh has not refuted the rule - it has failed to
    test it, and counting it either way would put a number into the record
    that the run did not produce.

    `noise_floor` is how far this run's own reported numbers move when only
    the mesh changes, and it is the caller's to measure - `results.
    mesh_noise_floor` reads it off the two mesh levels the chain already
    solves. Passing None falls back to `MOVED_BY`, and the observation says
    so: a run that has not measured its own floor does not know whether a
    difference is a design effect or a meshing one, and the record should
    carry that uncertainty rather than resolve it silently.
    """
    if measured_relative_change is None:
        return Observation(
            revision=revision, metric=metric,
            predicted_relative_change=predicted_relative_change,
            measured_relative_change=None, outcome="unmeasurable",
            note="the run did not report the metric this change was aimed at",
        )

    floor = MOVED_BY if noise_floor is None else abs(noise_floor)
    basis = (
        "re-meshing this same part moved it, which this run measured"
        if noise_floor is not None else
        "this is assumed, because the run measured no re-mesh of its own"
    )
    if abs(measured_relative_change) < floor:
        return Observation(
            revision=revision, metric=metric,
            predicted_relative_change=predicted_relative_change,
            measured_relative_change=measured_relative_change, outcome="unmoved",
            note=(
                f"{metric} moved {measured_relative_change:+.4%}, and "
                f"{floor:.2%} of that is what {basis}. The change was made and "
                "this run does not say whether it worked."
            ),
        )

    same_direction = (
        (predicted_relative_change >= 0) == (measured_relative_change >= 0)
    )
    if not same_direction:
        return Observation(
            revision=revision, metric=metric,
            predicted_relative_change=predicted_relative_change,
            measured_relative_change=measured_relative_change, outcome="refuted",
            note=(
                f"{metric} was expected to move "
                f"{'up' if predicted_relative_change >= 0 else 'down'} and "
                f"moved {measured_relative_change:+.4%} instead"
            ),
        )

    predicted_size = abs(predicted_relative_change)
    measured_size = abs(measured_relative_change)
    if predicted_size <= 1e-9:
        ratio = float("inf")
    else:
        ratio = max(measured_size / predicted_size, predicted_size / measured_size)
    if ratio > MAGNITUDE_TOLERANCE:
        return Observation(
            revision=revision, metric=metric,
            predicted_relative_change=predicted_relative_change,
            measured_relative_change=measured_relative_change, outcome="partial",
            note=(
                f"the direction was right and the size was out by "
                f"{ratio:.1f}x - the mechanism held, the constant did not"
            ),
        )
    return Observation(
        revision=revision, metric=metric,
        predicted_relative_change=predicted_relative_change,
        measured_relative_change=measured_relative_change, outcome="confirmed",
        note="the direction and the size both matched what was predicted",
    )


def relative_change(before: float | None, after: float | None) -> float | None:
    """How much a reported quantity moved between two revisions."""
    if before is None or after is None:
        return None
    if abs(before) < 1e-12:
        return None
    return (after - before) / abs(before)


def side_effects(
    prediction_metric: str,
    before: dict,
    after: dict,
    *,
    watched: tuple[str, ...] = (
        "max_von_mises_mpa", "min_safety_factor",
        "max_load_surface_von_mises_mpa", "max_displacement_mm",
    ),
    threshold: float = 0.02,
) -> list[str]:
    """Reported quantities that moved the wrong way while the aimed one moved.

    A change that lowers the peak by taking material out of the rim may raise
    the stress in the rim, and a record that held only the aimed metric would
    mark that rule as working. Safety factor is read in the opposite
    direction from the stresses - lower is worse - so it is handled apart
    rather than by a rule about signs.
    """
    out = []
    for name in watched:
        if name == prediction_metric:
            continue
        change = relative_change(before.get(name), after.get(name))
        if change is None or abs(change) < threshold:
            continue
        worse = change < 0 if name == "min_safety_factor" else change > 0
        if worse:
            out.append(
                f"{name} moved {change:+.2%} while {prediction_metric} was "
                "being changed"
            )
    return out


def seed_entries() -> list[KnowledgeEntry]:
    """The textbook mappings, as hypotheses rather than as answers.

    Each is a rule an engineer would state without looking anything up. They
    ship as `seed` because the loop exists to find out which of them hold on
    the components this machine builds, and a rule that arrived already
    trusted could never be found out.
    """
    def entry(entry_id, mechanism, parameter, direction, at, note):
        return KnowledgeEntry(
            id=entry_id, mechanism=mechanism, parameter=parameter,
            direction=direction, at=at, status="seed", note=note,
        )

    return [
        entry(
            "bore-hoop-rim-mass", "hoop_driven", "rim_half_thickness_mm",
            "decrease", "bore",
            "Bore hoop stress on a spinning disc is carried by material that "
            "has to hold the rim in. Less rim mass is less to hold. The "
            "counter-pressure is that the rim itself gets thinner, so the "
            "peak can move outward rather than down.",
        ),
        entry(
            "bore-hoop-bore-radius", "hoop_driven", "bore_radius_mm",
            "increase", "bore",
            "Hoop stress falls as the radius it acts over grows, for the same "
            "radial load. Bounded by the shaft it has to fit.",
        ),
        entry(
            "rim-radial-section", "radial_driven", "rim_half_thickness_mm",
            "increase", "rim",
            "Radial stress where the blade pull enters is a load over an area. "
            "More section is less stress - and more mass, which is the "
            "opposite of what the bore wants.",
        ),
        entry(
            "concentration-root-fillet", "stress_concentration",
            "root_fillet_mm", "increase", "fir-tree root",
            "A local peak whose value collapses within a few millimetres is a "
            "notch, and a bigger radius spreads the same load over more "
            "material.",
        ),
        entry(
            "concentration-web-fillet", "stress_concentration",
            "web_rim_fillet_mm", "increase", "web-rim junction",
            "The same argument at the web-to-rim transition, where the section "
            "changes fastest.",
        ),
        entry(
            "section-overload-web", "section_overload",
            "web_outer_half_thickness_mm", "increase", "web",
            "A broad high-stress region is a section carrying more than it "
            "has material for. A fillet does nothing for it.",
        ),
        KnowledgeEntry(
            id="load-application-not-a-design-problem",
            mechanism="load_application", status="seed",
            note=(
                "A peak sitting on the faces the load enters through, or a "
                "run whose reported numbers the verification stage would not "
                "quote, is a problem with the model and not with the part. The "
                "action is to fix the load or the mesh and run again; a "
                "geometry change made here would be a change to a component "
                "that was never analysed."
            ),
        ),
        KnowledgeEntry(
            id="idealisation-edge-not-a-design-problem",
            mechanism="idealisation_edge", status="seed",
            note=(
                "A peak on the z = 0 plane, a sector boundary or a constraint "
                "is where the model was cut, not where the part is weak. "
                "Changing the geometry moves nothing."
            ),
        ),
    ]


KnowledgeBase.model_rebuild()
