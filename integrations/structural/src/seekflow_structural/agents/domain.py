"""Deciding what piece of the part to analyse.

Everything downstream is built for the domain this agent picks, so an
ill-chosen domain silently answers a question about a different component: the
wedge still meshes, still solves, and still produces numbers - they are just
numbers about a piece of material that is not the part.

The agent is given measurements, not a recipe. Nothing here knows what a
turbine disc or a blade is. A part that repeats twenty times about an axis can
be analysed as one twentieth of itself; a part that does not repeat must be
analysed whole. Which is true is a measurement.

Two things the previous standalone version could do but this one does not:
  * it took the outer radius and half-thickness on the command line, so the
    cutting tool could be smaller than the part and truncate it - the case now
    carries measured extents and they are the tool's size;
  * it could choose a full revolution, which the materialiser then refused.
    That disagreement is gone: the domain decides, and the deck is written for
    whatever was decided.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_structural.case.model import DomainDecision, Vec3, Written
from seekflow_structural.core.domain_preview import DomainPreviewer
from seekflow_structural.core.mesh_profile import (
    azimuthal_feature_profile,
    dominant_periods,
    probe_periodicity,
    test_finer_periods,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.runtime.loop import (
    AgentSpec,
    dispatch_table,
    exhausted_final,
    run_agent,
)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "get_geometry",
        "inspect_azimuthal_profile",
        "probe_periodicity",
        "test_finer_periods",
        "preview_domain",
        "submit_domain",
        "needs_input",
    ]
    orders: list[int] = Field(default_factory=list)
    candidate_order: int = 0
    sector_deg: float = 360.0
    theta_low_deg: float = 0.0
    z_symmetry: bool = True
    rationale: str = ""
    questions: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """\
You are an FEA planning engineer. Before anything can be meshed or solved, you
must decide what piece of the part to analyse. Everything downstream is built
for the domain you choose.

A part can often be analysed as a fraction of itself. If it repeats N times
about an axis, one repeat unit carries the whole answer and the repetition is
supplied as a boundary condition. If it is symmetric about a plane, one half
carries the whole answer. If neither is true, the whole part must be analysed.
The saving is real, but only when the repetition actually exists.

Your tools, all measured from the geometry:

- get_geometry: overall size, mass and surface area, plus the axis candidates
  the frame stage measured and how well each symmetry plane maps the surface
  onto itself. The axis and any symmetry you use should come from those
  measurements, not from an assumption.
- inspect_azimuthal_profile: surface area, face count and shortest edge per
  2-degree bin, covering the whole circumference in one call. It also reports
  where the profile repeats, under two measures - treat those as a shortlist
  of periods worth testing, not as the answer.
- probe_periodicity: for each order you name, the fraction of surface area
  that maps onto itself when rotated by one period, and where the part that
  does NOT map sits. residual_bins_holding_90pct is the count of bins needed
  to cover 90% of the residual: a handful beside a high fraction is a
  confirmed period, a large share is a period the part does not have however
  close the fraction looks.
- test_finer_periods: given an order you believe is a repeat unit, probe every
  order that could be a finer one. This settles "is this the finest period?"
  in one call. Call it once, on your candidate, rather than walking the orders
  one at a time - every order that is not a multiple of your candidate cannot
  be a repeat unit whatever it scores.
- preview_domain: cut the candidate domain and report the fraction of the
  part's volume it holds against the fraction a true repeat unit would have,
  plus the faces lying on each cut plane. This is the decisive confirmation,
  and a cut costs a couple of minutes, so reach for it once you have narrowed
  to the domain you intend to submit.

A sector's two boundary planes must carry the same number of faces: a cyclic
sector is solved by tying its two cut faces to each other, which is only
coherent if they are the same shape. Unequal counts mean a boundary ran
through a feature and cut it in two. Turning the sector fixes it - the same
angle starting somewhere else is still the same repeat unit.

Once the period you chose is confirmed and test_finer_periods has come back
with nothing finer, you have your answer. Submit it.
"""


@dataclass
class DomainState:
    step: Path
    r_outer_mm: float
    z_half_mm: float
    model: object = None
    previewer: object = None
    submitted: dict | None = None
    cache: dict = field(default_factory=dict)

    def open_previewer(self):
        # Importing the STEP is one to two minutes, so it happens once and
        # every later tool reads from the same open model.
        if self.previewer is None:
            self.previewer = DomainPreviewer(
                self.step, self.r_outer_mm, self.z_half_mm
            )
        return self.previewer

    def close(self):
        if self.previewer is not None:
            self.previewer.close()
            self.previewer = None


def _geometry(action, state: DomainState) -> dict:
    summary = dict(state.open_previewer().geometry_summary())
    if state.model is not None:
        summary["axis_origin_mm"] = list(
            state.model.frame.axis_origin_mm.as_tuple()
        )
        summary["axis_direction"] = list(
            state.model.frame.axis_direction.as_tuple()
        )
        summary["symmetry_planes"] = [
            {
                "id": plane.id,
                "matched_area_fraction": plane.matched_area_fraction,
                "note": plane.note,
            }
            for plane in state.model.symmetry_planes
        ]
        summary["measured"] = {
            "r_max_mm": state.model.r_max_mm,
            "bore_radius_mm": state.model.bore_radius_mm,
        }
    summary["note"] = (
        "r_max_mm is measured from the surface, not from a configuration "
        "value or a bounding-box corner"
    )
    return {"ok": True, "result": summary}


def _profile(action, state: DomainState) -> dict:
    profile = azimuthal_feature_profile(state.open_previewer().faces(), 180)
    areas = [b["surface_area_mm2"] for b in profile]
    return {
        "ok": True,
        "result": {
            "bin_width_deg": 2.0,
            "note": (
                "entry i covers [i*2, (i+1)*2) degrees; this is the whole "
                "circumference, no further calls needed"
            ),
            "where_the_surface_repeats": {
                "by_face_count": dominant_periods(
                    [float(b["face_count"]) for b in profile], 2.0
                ),
                "by_surface_area": dominant_periods(areas, 2.0),
            },
            "theta_min_deg": [b["theta_min_deg"] for b in profile],
            "surface_area_mm2": areas,
            "face_count": [b["face_count"] for b in profile],
            "shortest_edge_mm": [b["shortest_edge_mm"] for b in profile],
        },
    }


def _probe(action, state: DomainState) -> dict:
    if not action.orders:
        raise StructuralError(
            "no_orders", "probe_periodicity needs at least one order",
            "domain",
        )
    if len(action.orders) > 24:
        raise StructuralError(
            "too_many_orders", "at most 24 orders per probe", "domain"
        )
    return {
        "ok": True,
        "result": probe_periodicity(
            state.open_previewer().faces(), action.orders
        ),
    }


def _finer(action, state: DomainState) -> dict:
    if action.candidate_order < 1:
        raise StructuralError(
            "no_candidate",
            "test_finer_periods needs the order you believe is the repeat unit",
            "domain",
        )
    return {
        "ok": True,
        "result": test_finer_periods(
            state.open_previewer().faces(), action.candidate_order
        ),
    }


def _preview(action, state: DomainState) -> dict:
    if not 0.0 < action.sector_deg <= 360.0:
        raise StructuralError(
            "bad_sector", "sector_deg must be in (0, 360]", "domain"
        )
    return {
        "ok": True,
        "result": state.open_previewer().preview(
            action.sector_deg, action.theta_low_deg, action.z_symmetry
        ),
    }


def _submit(action, state: DomainState) -> dict:
    if not 0.0 < action.sector_deg <= 360.0:
        raise StructuralError(
            "bad_sector", "sector_deg must be in (0, 360]", "domain"
        )
    if not action.rationale.strip():
        raise StructuralError(
            "no_rationale",
            "submit_domain requires a rationale naming the measurements the "
            "domain rests on",
            "domain",
        )
    sector = float(action.sector_deg)
    full = sector >= 359.9
    state.submitted = {
        "accepted": True,
        "domain": {
            # None means the whole part. Stored as an absence rather than
            # 360.0 so that "no repeat unit" cannot be confused with "a sector
            # that happens to be a full turn".
            "sector_deg": None if full else round(sector, 8),
            "theta_low_deg": (
                0.0 if full else float(action.theta_low_deg) % 360.0
            ),
            "z_symmetry": bool(action.z_symmetry),
        },
        "rationale": action.rationale,
    }
    return {"ok": True, "result": state.submitted}


def _needs_input(action, state: DomainState) -> dict:
    return {
        "ok": True,
        "result": {"accepted": False, "questions": action.questions},
    }


DISPATCH = dispatch_table({
    "get_geometry": _geometry,
    "inspect_azimuthal_profile": _profile,
    "probe_periodicity": _probe,
    "test_finer_periods": _finer,
    "preview_domain": _preview,
    "submit_domain": _submit,
    "needs_input": _needs_input,
})


def spec(max_calls: int = 14) -> AgentSpec:
    return AgentSpec(
        name="domain",
        tool_name="domain_action",
        tool_description=(
            "Measure the geometry or submit the analysis domain."
        ),
        action_model=Action,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "Decide the analysis domain. Start with get_geometry to see the "
            "measured extent and the symmetry the frame stage found, then "
            "inspect_azimuthal_profile."
        ),
        submit_actions=frozenset({"submit_domain", "needs_input"}),
        max_calls=max_calls,
        timeout_s=300,
    )


def to_case_domain(payload: dict, source: str) -> DomainDecision:
    domain = payload["domain"]
    sector = domain["sector_deg"]
    return DomainDecision(
        sector_deg=None if sector is None else float(sector),
        theta_low_deg=float(domain["theta_low_deg"]),
        symmetry_planes_used=["z0"] if domain["z_symmetry"] else [],
        evidence={"source": source},
        rationale=str(payload.get("rationale", "")),
        written=Written(
            by_stage="domain", kind="agent_decision", source=source
        ),
    )


def domain(ctx: RunContext, *, api_key_file: Path | None = None,
           max_calls: int = 14):
    """The stage: open the model, run the agent, close it, write the case."""
    from seekflow_structural.runtime.caller import build_caller

    case = ctx.case
    if case is None or case.model is None:
        raise StructuralError(
            "case_incomplete",
            "the domain needs the measured model facts; the frame stage runs "
            "first",
            "domain",
        )

    bundle = Path(case.bundle.path)
    state = DomainState(
        step=bundle / "model.step",
        # The tool must clear the part. A tool smaller than the part does not
        # fail, it truncates - so these come from the measurements, and the
        # DomainPreviewer raises them again from the bounding box regardless.
        r_outer_mm=float(case.model.r_max_mm),
        z_half_mm=max(
            abs(case.model.bounds_min_mm.z), abs(case.model.bounds_max_mm.z)
        ),
        model=case.model,
    )
    try:
        caller, model_config = build_caller(api_key_file)
        outcome = run_agent(
            spec(max_calls=max_calls), caller=caller,
            model_config=model_config, dispatch=DISPATCH, context=state,
        )
    finally:
        state.close()

    ctx.charge_tool_calls(outcome.calls, "domain")
    ctx.job.write("agent/domain.json", {
        "schema_version": "domain_run_v1",
        "trace": outcome.trace,
        "final": outcome.final,
        "calls": outcome.calls,
        "exhausted": outcome.exhausted,
    })
    if outcome.final is None:
        raise StructuralError(
            "domain_not_decided",
            "the domain agent used its whole budget without deciding",
            "domain",
        )
    if not outcome.final.get("accepted"):
        raise StructuralError(
            "domain_needs_input",
            "the domain agent asked for input: "
            + "; ".join(outcome.final.get("questions", [])),
            "domain",
        )

    case.domain = to_case_domain(outcome.final, str(bundle))
    ctx.job.event({
        "kind": "domain_decided",
        "stage": "domain",
        "sector_deg": case.domain.sector_deg,
        "theta_low_deg": case.domain.theta_low_deg,
        "symmetry_planes_used": case.domain.symmetry_planes_used,
    })
    return case


def main(argv=None) -> int:
    """Standalone entry, for a single stage outside the chain."""
    from seekflow_structural.runtime.caller import build_caller

    parser = argparse.ArgumentParser()
    parser.add_argument("step", type=Path)
    parser.add_argument("r_outer_mm", type=float)
    parser.add_argument("z_half_mm", type=float)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--max-tool-calls", type=int, default=14)
    args = parser.parse_args(argv)

    state = DomainState(
        step=args.step.resolve(),
        r_outer_mm=args.r_outer_mm,
        z_half_mm=args.z_half_mm,
    )
    try:
        caller, model_config = build_caller(args.api_key_file)
        outcome = run_agent(
            spec(max_calls=args.max_tool_calls), caller=caller,
            model_config=model_config, dispatch=DISPATCH, context=state,
        )
    finally:
        state.close()
    final = outcome.final or exhausted_final("domain")
    print(json.dumps({"trace": outcome.trace, "final": final},
                     ensure_ascii=False, indent=2))
    return 0 if final.get("accepted") else 1
