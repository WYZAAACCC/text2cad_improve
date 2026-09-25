"""Finding the faces a stated requirement describes.

The previous version of this agent was framed as a fir-tree flank finder: its
prompt talked about slot cutters, working flanks and lobes, and a validator
enforced one component's idea of a load face - planar, a radial normal of at
least 0.2, no axial component, one radial sign, an even count, every face
mirrored by a partner. A curved blade platform failed that without being told
why, and so would a bracket bolted through a boss.

What the agent does now is narrower and more general: it states what it is
looking for as a criterion, searches the geometry with measured filters, and
submits a set. The harness checks the set against *its own* criterion and
reports the residuals. Load faces, constraint faces, symmetry faces and
post-processing sections are all this same tool with a different criterion,
which is why the harness no longer has to know what a load face is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from seekflow_structural.case.model import Criterion, LoadSurface, Written, Vec3
from seekflow_structural.errors import StructuralError
from seekflow_structural.evolution import query as evolution_query
from seekflow_structural.evolution import store
from seekflow_structural.runtime import analysis
from seekflow_structural.runtime.loop import (
    AgentSpec,
    ToolAction,
    dispatch_table,
    exhausted_final,
    run_agent,
)
from seekflow_structural.tools import criteria as criteria_tool
from seekflow_structural.tools import geometry

MAX_FACES_PER_PAGE = 60

# A load applied through a finished bearing surface has a direction, and the
# faces that actually carry it align with that direction. Other tooth flanks
# can point the same way and still be relief/non-working surfaces; on D27 the
# working flanks formed one radial-alignment family at 0.715..0.869 while the
# non-working tooth faces formed a second at 0.261..0.511. The gap between the
# families is measured rather than assumed. When it is this clear, a selection
# that mixes the families (or omits the strongly aligned one) is refused before
# a mesh and solve are paid for.
MIN_ALIGNMENT_GAP = 0.15
MIN_STRONG_FAMILY_AREA_FRACTION = 0.05
# A blade root load enters at the outer rim. Before the normal families are
# compared, the measured radii have to show that outer load band as a separate
# group; otherwise the gate declines instead of inventing one.
MIN_RADIAL_GAP_FRACTION = 0.05
# Even when the population has no significant separation, a face whose normal
# is nearly tangential cannot be a bearing flank for a radial blade load. The
# measured D25/D26 failure selected faces at `-normal_radial` 0.01..0.04 and
# passed because the population gap was too small to gate. This floor is a
# physical direction check, not a family split.
MIN_RADIAL_LOAD_ALIGNMENT = 0.20

# How much of a reply a listing may take. A delimited face row is about fifty
# characters, so this carries roughly four hundred of them - which covers the
# sets this agent actually selects (195, 308) whole, and still bounds the
# reply on a body of thousands.
LISTING_BUDGET_CHARS = 20_000

# What a written script may hand back. Generous enough for a table an agent
# asked for and bounded, because the reply goes into the conversation and an
# unbounded one would crowd out everything after it.
MAX_ANALYSIS_OUTPUT = analysis.SANDBOX_STDOUT_CAP
MAX_ANALYSIS_ERROR = 1200


class Action(ToolAction):

    action: Literal[
        "list_features",
        "list_solids",
        "list_origins",
        "query_faces",
        "inspect_faces",
        "check_criterion",
        "run_analysis",
        "submit_faces",
        "needs_input",
    ]
    feature: str = ""
    solid_index: int = 0

    # Filters, all optional. A filter affects the query only when its bound is
    # set, so the agent composes the search it means rather than picking from
    # a menu of prepared ones. Each carries what it measures and its unit:
    # the schema is the only description of these fields the agent ever sees,
    # and a bound whose meaning is unstated - "normal_tangential_min" with no
    # word on the frame it is measured in - is a parameter that cannot be used
    # correctly however good the reasoning around it.
    surface_type: str = Field(
        default="",
        description=(
            "keep only faces of this surface type: plane, cylinder, cone, "
            "torus, sphere, bspline, or a type list_solids/query_faces has "
            "reported. Empty applies no type filter."
        ),
    )
    area_min: float = Field(
        default=-1e30, description="lowest face area to keep, in mm^2"
    )
    area_max: float = Field(
        default=1e30, description="highest face area to keep, in mm^2"
    )
    radial_min: float = Field(
        default=-1e30,
        description=(
            "lowest distance from the rotation axis to the face's centroid, "
            "in mm. This is the radius the mesh is refined at, so it is how "
            "a load-bearing band is named."
        ),
    )
    radial_max: float = Field(
        default=1e30,
        description="highest centroid distance from the rotation axis, in mm",
    )
    theta_min: float = Field(
        default=-1e30,
        description=(
            "lowest azimuth of the face centroid, in degrees, measured about "
            "the rotation axis from the model's +X axis"
        ),
    )
    theta_max: float = Field(
        default=1e30, description="highest centroid azimuth, in degrees"
    )
    z_min: float = Field(
        default=-1e30,
        description="lowest axial position of the face centroid, in mm",
    )
    z_max: float = Field(
        default=1e30, description="highest axial position of the face centroid"
    )
    normal_radial_min: float = Field(
        default=-1e30,
        description=(
            "lowest radial component of the outward face normal, as a "
            "fraction of unit length: +1 is a face pointing straight out from "
            "the axis, -1 straight in towards it. This is the component that "
            "says whether a face presses into the material or pulls away."
        ),
    )
    normal_radial_max: float = Field(
        default=1e30, description="highest radial component of the outward normal"
    )
    normal_tangential_min: float = Field(
        default=-1e30,
        description=(
            "lowest tangential (hoop) component of the outward normal, in "
            "-1..1. It is the component around the axis, so a face that leans "
            "sideways into a slot flank shows up here rather than in radial."
        ),
    )
    normal_tangential_max: float = Field(
        default=1e30, description="highest tangential component of the outward normal"
    )
    normal_axial_min: float = Field(
        default=-1e30,
        description=(
            "lowest axial component of the outward normal, in -1..1: +1 faces "
            "the +Z end, -1 the -Z end, 0 is a face that stands parallel to "
            "the axis."
        ),
    )
    normal_axial_max: float = Field(
        default=1e30, description="highest axial component of the outward normal"
    )

    origin_relation: str = Field(
        default="",
        description=(
            "keep only faces whose origin is this kind of evolution: "
            "'modified' for a face the operation produced, 'carry' for one it "
            "passed through unchanged. Empty applies no origin filter. This is "
            "not a measurement - two sets of faces can be identical in every "
            "measurement and still differ here - so it is often the only "
            "filter that can separate them."
        ),
    )
    origin_operand: str = Field(
        default="",
        description=(
            "keep only faces that descend from this input of the operation: "
            "'tool' for the body that did the cutting, 'target' for the body "
            "being cut. Empty applies no filter."
        ),
    )
    offset: int = Field(
        default=0, description="skip this many matched faces before listing"
    )
    limit: int = Field(
        default=0,
        description=(
            "how many matched faces to list. 0 - the default - lets the "
            "harness list the whole set when its compact text fits the reply "
            "budget, and otherwise returns as much as fits plus the summary. "
            "Set a positive limit to request a bounded page of at most 60."
        ),
    )
    face_indices: list[int] = Field(
        default_factory=list,
        description="faces to act on for inspect_faces and check_criterion",
    )
    criterion: Criterion | None = Field(
        default=None, description="the criterion for check_criterion/submit_faces"
    )
    rationale: str = Field(
        default="",
        description="why this action, in one or two sentences",
    )
    questions: list[str] = Field(
        default_factory=list, description="what to ask the user, for needs_input"
    )
    code: str = Field(
        default="",
        description=(
            "for run_analysis: the Python to run. Import "
            "`seekflow_structural.sandbox_kit` for what you have been given - "
            "`kit.rows()` is every measured face you can already see, as "
            "dictionaries; `kit.open_bundle()` opens the part itself and is "
            "slow. Print what you want to read; only stdout and stderr come "
            "back."
        ),
    )
    purpose: str = Field(
        default="",
        description=(
            "for run_analysis: the question this script answers, in one "
            "sentence. It is recorded with the script, so a later reader knows "
            "what was being asked rather than having to infer it from the code."
        ),
    )


SYSTEM_PROMPT = """\
You are an FEA planning engineer deciding which faces of a part a stated
requirement applies to. You are not told what kind of part this is and there is
no list of faces to pick from.

The requirement comes with the task. It might be "the faces the load enters
through", "the faces the part is held by", "a section to cut for a path plot" -
whatever it is, your job is to turn it into a statement about geometry that can
be checked, and then find the faces that satisfy it.

Your tools:

- list_features: what the model was built from, and a summary of what each
  feature produced - its solid count, its total face count, and the volume and
  bounding box of its largest solid. A part made by one revolve looks nothing
  like one made by sixty boolean cuts, and this is where you find out which
  you have. Nothing is preselected. A cut leaves the body it cut as its
  largest solid, so the summary usually names the feature that produced the
  part without your having to open any of them; list_solids is for going
  deeper once you have chosen one.
- list_solids: the solids one feature's boolean produced, each with its volume,
  centroid, bounding box and face count. A cut feature leaves the tool body
  and the result as separate solids; you want the result. A feature with sixty
  solids is a pattern of cutters, and its listing is long - prefer the summary
  in list_features unless you need the individual bodies.
- list_origins: group a body's faces by where they came from - how many
  descend from the body that did the cutting, how many were carried through
  from the body being cut, and what each group measures. Read this before
  trusting a measurement summary: a summary reports one minimum, one median
  and one maximum, and a body whose faces form two bands far apart comes back
  as a single median sitting in the gap between them. Grouped by origin the
  same faces report as the separate groups they are.
- query_faces: filter one solid's faces by surface type, area, radius, angle,
  axial position, and the radial/tangential/axial components of the face
  normal, or by where the face came from. Filters combine; leave one unset to
  ignore it. Each bound's
  field in the schema says what it measures and in what unit - read it there,
  because a radius is a distance from the axis in millimetres while a normal
  component is a fraction of unit length in -1..1, and confusing the two
  returns an empty set that looks like a fact about the part.

  The answer is a SUMMARY of the whole matched set: its surface types with
  counts, the range of area, radius, axial position and normal components
  across it, and a sector-coverage count when only one repeating sector is
  solved. It also reports filters_applied and whether the compact listing fits
  the reply budget. For a `flank_surface_normal` load it reports
  `load_normal_alignment`: the outer radial load band and the strongly aligned
  normal family measured inside it. `strong_family.measured_query_bounds` gives
  the signed bounds of that family - for a centrifugal blade load,
  `normal_radial_max` is negative because the useful pressure direction is
  inward on the face normal. When those families have a significant gap,
  submission is refused if they are mixed or if the strong family is
  incomplete. Filter until the summary describes what you mean, then read the
  listed set or ask for a bounded page with limit.

  origin_relation and origin_operand are not measurements. They ask where a
  face came from - whether the operation produced it or carried it through,
  and which of the operation's inputs it descends from. Two sets of faces can
  be identical in every measurement and differ here, which makes this the only
  filter that separates them when nothing else will.

  This is a measurement, not a search that can fail. An empty result with
  filters_applied non-empty means those bounds describe nothing on this part -
  widen them. An empty result with nothing applied is not a property of the
  part at all, since nothing was asked of it, and you should say so rather
  than keep narrowing.
- inspect_faces: the measured facts for faces you have already identified.
- check_criterion: check a candidate set against a criterion you have written,
  without submitting it. Use this before you submit. Name the set exactly as
  you would submit it - the same filters, or indices - so checking and
  submitting are the same statement and there is no need to list faces in
  between just to read their indices.
- run_analysis: run a Python script you write, when no tool answers the
  question you have. Import `seekflow_structural.sandbox_kit`; `kit.rows()` is
  every measured face you can already see, as dictionaries with the same keys
  your tools report, and `kit.open_bundle()` opens the part itself - slow, for
  questions the numbers cannot answer. Print what you want to read.
  Reach for this when the shape of the data is the question: whether a set of
  radii is one cluster or two is not something a filter can tell you, and a
  summary that reports a median will hide the second cluster rather than show
  it. The script runs in a subprocess against the same measurements, so a
  failure is the script's and not a fact about the part.
- submit_faces: state the criterion and the faces that satisfy it. Origin
  filters count as describing the set, so a set narrowed by origin can be
  submitted the same way as one narrowed by radius. You may
  name the faces by index, or - and this is usually the only workable way -
  submit the same filters you would have given query_faces and let the harness
  resolve them. Naming indices means reading them off a listing that comes
  sixty at a time; on a body with thousands of faces that is not reachable, so
  describe the faces with filters and submit those.

About the criterion. It is a statement about the geometry you are looking for,
and you write it yourself. It has:
  - surface_types: the kinds of surface acceptable, e.g. ["plane"].
  - normal_clauses: bounds on components of the face normal - radial, axial,
    tangential, or frame_axis. Each clause is a component and a min and max.
  - symmetry, if the set must be closed under a symmetry of the part.
  - count, if the set has to have a particular size or parity.
The harness checks the faces you submit against the criterion YOU declared and
reports each clause's residual. It does not have its own idea of what you
should have selected, so a criterion that is too narrow will show up as faces
failing your own clauses rather than as an error from somewhere else.

Two things worth stating plainly, because they are what the residuals are for:
- If your criterion is met but you are unsure it describes the right thing,
  say so in the rationale. The residuals are evidence; the judgement is yours.
- If the geometry genuinely cannot answer the question, say needs_input and ask.
  That is a valid answer - but it ends the run, so it is the answer for a
  question this part cannot settle, not for one you have not finished looking
  at. Distinguish the two before you use it. A question the part can settle is
  settled by measuring it. A question the part cannot settle is usually one
  about the machine rather than the model - which of two identical features
  the load really acts on, say - and for that, submit the set you judge the
  more likely and record what you could not settle in the rationale. A
  selection that was made and marked uncertain can be checked against the
  residuals and corrected by whoever knows the machine. One that was never
  made cannot be corrected by anyone.

Your last call offers only these two actions. Budget the rest accordingly.
"""


@dataclass
class FaceFinderState:
    """What the tools share between calls: the open document and its caches."""

    session: object
    feature: str = ""
    solid_index: int = 0
    rows: list[dict] = field(default_factory=list)
    cache: dict = field(default_factory=dict)
    # The transform from the model's source frame into the case frame. The
    # face index stays in the source topology; only the numeric facts the
    # agent filters on are transformed.
    normalisation: object | None = None
    submitted: dict | None = None
    # Where a written script runs, and what it is handed. A state built for an
    # offline test leaves these unset, which is what makes `run_analysis`
    # refuse rather than reach for a session that is not there.
    bundle: Path | None = None
    sector: dict | None = None
    # Set by the assembly stage for a load the deck will apply as surface
    # pressure. The current mapper can materialise a planar face; submitting a
    # curved face records a selection that later maps to no element face.
    require_planar: bool = False
    # The declared relationship between the load and the selected surface.
    # `flank_surface_normal` means the load presses along the face normal; for
    # a centrifugal blade load the useful normal family is the one pointing
    # most directly towards the axis. Other rules are not given this gate.
    load_direction_rule: str = ""
    workdir: Path | None = None
    analyses: list[dict] = field(default_factory=list)
    # The face-evolution index, when one was built for this bundle. Absent is
    # a supported state: the tools lose one thing to filter on and nothing
    # else, which is better than a run that refuses because an optional
    # artifact is missing.
    evolution_db: Path | None = None
    revision_id: str = ""
    origins_cache: dict = field(default_factory=dict)


def _ensure_indexed(state: FaceFinderState, feature: str) -> str:
    """Build this feature's part of the index if it is not there yet.

    Lazily, and per feature, because the feature is the agent's to choose -
    indexing all of them up front would mean reading the document once for
    every feature in it to answer a question about one. Measured on a
    4,216-face part: about half a minute, dominated by reading the document
    rather than by the 19,792 roles in it.
    """
    if state.evolution_db is None or not feature:
        return ""
    namespace = f"feature:{feature}"
    if not store.has_namespace(state.evolution_db, namespace):
        from seekflow_structural.evolution import build_index

        try:
            build_index(
                state.bundle if state.bundle else state.evolution_db,
                state.evolution_db,
                namespace=namespace,
                final_feature=feature,
            )
        except Exception:
            # An index that cannot be built costs the origin filters and
            # nothing else. Failing the run here would trade every other tool
            # for this one.
            return ""
    return store.revision_of(state.evolution_db)


def _origins_for(state: FaceFinderState, feature: str, solid_index: int) -> dict:
    """What the face-evolution index knows about this body, if it was built.

    Read once per body and kept, because it is a lookup over the whole index
    and every query afterwards is a dictionary access. An absent index is not
    an error - the tools work without it, they simply have one fewer thing to
    filter on - so this returns nothing rather than refusing.
    """
    if state.evolution_db is None:
        return {}
    key = (feature, solid_index)
    if key not in state.origins_cache:
        revision = state.revision_id or _ensure_indexed(state, feature)
        state.revision_id = revision
        state.origins_cache[key] = (
            evolution_query.origins_for_faces(
                state.evolution_db, revision, feature, solid_index
            )
            if revision else {}
        )
    return state.origins_cache[key]


def _rows_for(state: FaceFinderState, feature: str, solid_index: int):
    key = (feature, solid_index)
    if key not in state.cache:
        rows = geometry.face_rows(
            state.session, feature, solid_index,
            normalisation=state.normalisation,
        )
        state.cache[key] = evolution_query.decorate(
            rows, _origins_for(state, feature, solid_index)
        )
    state.feature = feature
    state.solid_index = solid_index
    state.rows = state.cache[key]
    return state.rows


# What an unset bound looks like in the action schema. A bound is only a
# filter when the agent set it; passing the sentinel through as a number would
# apply a bound that merely happens to be wide, and any face whose fact was
# never measured - a normal whose centroid sits on the axis - would then be
# dropped by a filter the agent never wrote.
UNSET_MIN = -1e30
UNSET_MAX = 1e30


def _bounds(low: float, high: float):
    """The bounds to filter on, or None when the agent left them unset."""
    if low <= UNSET_MIN and high >= UNSET_MAX:
        return None
    return (low, high)


def _filters(action: Action) -> dict:
    return {
        "area": _bounds(action.area_min, action.area_max),
        "radial": _bounds(action.radial_min, action.radial_max),
        "theta": _bounds(action.theta_min, action.theta_max),
        "z": _bounds(action.z_min, action.z_max),
        "normal_radial": _bounds(
            action.normal_radial_min, action.normal_radial_max
        ),
        "normal_tangential": _bounds(
            action.normal_tangential_min, action.normal_tangential_max
        ),
        "normal_axial": _bounds(
            action.normal_axial_min, action.normal_axial_max
        ),
    }


def _sector_report(rows: list[dict], state: FaceFinderState) -> dict:
    """How much of a candidate set lies in the sector that will be solved.

    The domain stage solves one repeating sector while the CAD body still
    contains every copy. A filter written on origin, normal and radius can
    therefore match the correct physical feature in twenty sectors and still
    describe a set the mesh cannot contain. This is a measured residual, not a
    hidden preference: it says how many matched faces are inside and outside
    the sector actually meshed.
    """
    sector = state.sector or {}
    low = sector.get("theta_low_deg")
    high = sector.get("theta_high_deg")
    if low is None or high is None:
        return {"applicable": False}
    low = float(low)
    high = float(high)
    if high <= low:
        high += 360.0

    inside: list[int] = []
    outside: list[int] = []
    for index, row in enumerate(rows):
        (inside if _inside_sector(row, state) else outside).append(index)
    return {
        "applicable": True,
        "theta_low_deg": low,
        "theta_high_deg": high % 360.0,
        "inside_count": len(inside),
        "outside_count": len(outside),
        "outside_indices": outside[:12],
    }


def _inside_sector(row: dict, state: FaceFinderState) -> bool:
    """Whether this face's centroid lies in the part that will be meshed."""
    sector = state.sector or {}
    low = sector.get("theta_low_deg")
    high = sector.get("theta_high_deg")
    if low is None or high is None:
        return True
    low = float(low)
    high = float(high)
    if high <= low:
        high += 360.0
    theta = float((row.get("centroid_cyl_mm_deg") or [0.0, 0.0, 0.0])[1])
    while theta < low:
        theta += 360.0
    return theta <= high


def _weak_alignment_problems(selected: list[dict]) -> tuple[list[dict], list[str]]:
    weak = []
    for row in selected:
        radial = (row.get("normal_cylindrical") or {}).get("radial")
        if radial is None or -float(radial) < MIN_RADIAL_LOAD_ALIGNMENT:
            weak.append(row)
    if not weak:
        return weak, []
    areas = sum(float(row.get("area_mm2") or 0.0) for row in weak)
    return weak, [
        "selection_includes_non_radial_faces: "
        f"{len(weak)} selected face(s) covering {areas:.4g} mm^2 have "
        f"-normal_radial below {MIN_RADIAL_LOAD_ALIGNMENT:.2f}. For a radial "
        "blade load these are tangential/non-working surfaces, not bearing "
        "flanks."
    ]


def _alignment_family_report(
    all_rows: list[dict], selected: list[dict], state: FaceFinderState
) -> dict:
    """Separate the strongly aligned load-normal family from neighbouring faces.

    The separation is not a hard-coded normal threshold. Candidate faces are
    ordered by how directly their pressure opposes the centrifugal load
    (`-normal_radial`), and the largest gap in that distribution defines the
    two families when the gap is materially larger than ordinary variation.
    The gate is active only for `flank_surface_normal`; it is a measurement of
    the declared load path, not a guess about what every face on every part
    means.
    """
    if state.load_direction_rule != "flank_surface_normal":
        return {"applicable": False, "direction_rule": state.load_direction_rule}

    candidates: list[tuple[float, float, dict]] = []
    for row in all_rows:
        if state.require_planar and str(row.get("surface_type") or "") != "plane":
            continue
        if not _inside_sector(row, state):
            continue
        radius = (row.get("centroid_cyl_mm_deg") or [None, None, None])[0]
        radial = (row.get("normal_cylindrical") or {}).get("radial")
        if radius is None or radial is None:
            continue
        alignment = -float(radial)
        if alignment <= 0.0:
            continue
        candidates.append((float(radius), alignment, row))

    weak, weak_problems = _weak_alignment_problems(selected)
    if len(candidates) < 8:
        return {
            "applicable": True,
            "direction_rule": state.load_direction_rule,
            "candidate_face_count": len(candidates),
            "separation": {"significant": False, "reason": "too_few_candidates"},
            "weak_alignment_face_count": len(weak),
            "problems": weak_problems,
        }

    def largest_gap(values: list[float]) -> tuple[float, float, float]:
        ordered = sorted(values)
        gaps = [
            (
                ordered[index + 1] - ordered[index],
                ordered[index],
                ordered[index + 1],
            )
            for index in range(len(ordered) - 1)
        ]
        return max(gaps, key=lambda item: item[0])

    candidate_area = sum(
        float(row.get("area_mm2") or 0.0)
        for _radius, _alignment, row in candidates
    )
    radial_gap, radial_lower, radial_upper = largest_gap(
        [radius for radius, _alignment, _row in candidates]
    )
    radial_scale = max(radius for radius, _alignment, _row in candidates)
    outer = [
        (alignment, row) for radius, alignment, row in candidates
        if radius >= radial_upper
    ]
    outer_area = sum(
        float(row.get("area_mm2") or 0.0) for _alignment, row in outer
    )
    outer_area_fraction = outer_area / candidate_area if candidate_area else 0.0
    radial_significant = (
        radial_gap >= MIN_RADIAL_GAP_FRACTION * max(radial_scale, 1.0)
        and len(outer) >= 4
        and outer_area_fraction >= MIN_STRONG_FAMILY_AREA_FRACTION
    )
    if not radial_significant:
        return {
            "applicable": True,
            "direction_rule": state.load_direction_rule,
            "candidate_face_count": len(candidates),
            "candidate_area_mm2": round(candidate_area, 6),
            "separation": {
                "significant": False,
                "reason": "no_distinct_outer_load_band",
                "radial": {
                    "largest_gap": round(radial_gap, 6),
                    "lower_family_radius_max": round(radial_lower, 6),
                    "upper_family_radius_min": round(radial_upper, 6),
                },
            },
            "weak_alignment_face_count": len(weak),
            "problems": weak_problems,
        }

    normal_gap, normal_lower, normal_upper = largest_gap(
        [alignment for alignment, _row in outer]
    )
    strong = [row for alignment, row in outer if alignment >= normal_upper]
    strong_area = sum(float(row.get("area_mm2") or 0.0) for row in strong)
    strong_area_fraction = strong_area / outer_area if outer_area else 0.0
    normal_significant = (
        normal_gap >= MIN_ALIGNMENT_GAP
        and len(strong) >= 2
        and strong_area_fraction >= MIN_STRONG_FAMILY_AREA_FRACTION
    )
    significant = radial_significant and normal_significant

    if not normal_significant:
        return {
            "applicable": True,
            "direction_rule": state.load_direction_rule,
            "candidate_face_count": len(candidates),
            "candidate_area_mm2": round(candidate_area, 6),
            "separation": {
                "significant": False,
                "reason": "no_distinct_normal_family_in_outer_band",
                "radial": {
                    "largest_gap": round(radial_gap, 6),
                    "lower_family_radius_max": round(radial_lower, 6),
                    "upper_family_radius_min": round(radial_upper, 6),
                },
                "normal": {
                    "largest_gap": round(normal_gap, 6),
                    "lower_family_alignment_max": round(normal_lower, 6),
                    "upper_family_alignment_min": round(normal_upper, 6),
                },
            },
            "weak_alignment_face_count": len(weak),
            "problems": weak_problems,
        }

    selected_ids = {id(row) for row in selected}
    strong_ids = {id(row) for row in strong}
    extra_selected = [row for row in selected if id(row) not in strong_ids]
    missing_strong = [row for row in strong if id(row) not in selected_ids]
    extra_area = sum(
        float(row.get("area_mm2") or 0.0) for row in extra_selected
    )
    missing_area = sum(
        float(row.get("area_mm2") or 0.0) for row in missing_strong
    )

    problems: list[str] = []
    if extra_selected:
        problems.append(
            "selection_mixes_normal_families: the measured outer load band "
            f"begins at r = {radial_upper:.4g} mm and its strongly aligned "
            f"family begins at radial alignment {normal_upper:.3f} "
            f"(normal_radial <= {-normal_upper:.3f}); the "
            f"selection includes {len(extra_selected)} other face(s) covering "
            f"{extra_area:.4g} mm^2. They are outside the finished "
            "`flank_surface_normal` load path: either the wrong radial band or "
            "the non-working side of the tooth."
        )
    if missing_strong:
        problems.append(
            "selection_misses_strong_normal_family: "
            f"{len(missing_strong)} strongly aligned face(s) covering "
            f"{missing_area:.4g} mm^2 are omitted. The surface-pressure load "
            "would enter only part of the measured bearing family."
        )

    return {
        "applicable": True,
        "direction_rule": state.load_direction_rule,
        "candidate_face_count": len(candidates),
        "candidate_area_mm2": round(candidate_area, 6),
        "separation": {
            "significant": significant,
            "radial": {
                "largest_gap": round(radial_gap, 6),
                "lower_family_radius_max": round(radial_lower, 6),
                "upper_family_radius_min": round(radial_upper, 6),
            },
            "normal": {
                "largest_gap": round(normal_gap, 6),
                "lower_family_alignment_max": round(normal_lower, 6),
                "upper_family_alignment_min": round(normal_upper, 6),
            },
        },
        "strong_family": {
            "face_count": len(strong),
            "face_indices": sorted(
                int(row["face_index"]) for row in strong
                if row.get("face_index") is not None
            ),
            "area_mm2": round(strong_area, 6),
            "area_fraction": round(strong_area_fraction, 6),
            "measured_query_bounds": {
                "radial_min": round(radial_upper, 6),
                "normal_radial_max": round(-normal_upper, 6),
            },
        },
        "selected": {
            "face_count": len(selected),
            "outside_strong_family_face_count": len(extra_selected),
            "outside_strong_family_area_mm2": round(extra_area, 6),
            "missing_strong_family_face_count": len(missing_strong),
            "missing_strong_family_area_mm2": round(missing_area, 6),
        },
        "problems": problems,
        "note": (
            "`strong_family` is the strongly aligned family inside the outer "
            "radial band measured from this model. It is not a face list: the "
            "gate acts only when both the radial band and the normal family "
            "have a significant measured gap."
        ),
    }


def _submission_readiness(
    rows: list[dict], state: FaceFinderState, *,
    all_rows: list[dict] | None = None,
) -> dict:
    """Whether a set can be solved, before it is recorded as the decision.

    Two failures are structural rather than a matter of engineering taste. A
    face outside the solved sector is not in the mesh; a curved face is not
    mappable by the current surface-pressure emission path. Both used to pass
    selection and only became visible as a missing fraction of the load after a
    mesh and solve had already been paid for.
    """
    sector = _sector_report(rows, state)
    surface_types: dict[str, int] = {}
    for row in rows:
        kind = str(row.get("surface_type") or "unknown")
        surface_types[kind] = surface_types.get(kind, 0) + 1
    non_planar = [
        index for index, row in enumerate(rows)
        if str(row.get("surface_type") or "") != "plane"
    ]
    problems: list[str] = []
    if sector.get("applicable") and sector.get("outside_count"):
        problems.append(
            "selection_outside_sector: "
            f"{sector['outside_count']} of {len(rows)} faces have centroids "
            f"outside theta {sector['theta_low_deg']:g}.."
            f"{sector['theta_high_deg']:g} deg; add a theta filter for the "
            "solved sector. Outside indices: "
            + ", ".join(str(value) for value in sector["outside_indices"])
        )
    if state.require_planar and non_planar:
        problems.append(
            "selection_not_mappable: the load is emitted as surface pressure, "
            "whose current mapper accepts planar CAD faces only; "
            f"{len(non_planar)} selected face(s) are not planes (indices: "
            + ", ".join(str(value) for value in non_planar[:12])
            + "). Narrow surface_types to ['plane'] or choose planar faces."
        )
    alignment = _alignment_family_report(all_rows or rows, rows, state)
    problems.extend(alignment.get("problems") or [])
    return {
        "ready": not problems,
        "problems": problems,
        "sector": sector,
        "load_normal_alignment": alignment,
        "surface_types": surface_types,
        "planar_count": len(rows) - len(non_planar),
        "non_planar_count": len(non_planar),
        "non_planar_indices": non_planar[:12],
    }


def _list_features(action, state: FaceFinderState) -> dict:
    return {"ok": True, "result": {"features": geometry.features(state.session)}}


def _list_solids(action, state: FaceFinderState) -> dict:
    if not action.feature:
        raise StructuralError(
            "no_feature", "list_solids needs the feature to look in", "facefind"
        )
    return {
        "ok": True,
        "result": {"solids": geometry.solids(state.session, action.feature)},
    }


def _list_origins(action, state: FaceFinderState) -> dict:
    """Group this body's faces by where they came from.

    The answer to a question a measurement summary cannot answer. A summary of
    radius reports a minimum, a median and a maximum - and a body whose faces
    form two bands 70 mm apart comes back as "median 285", one number standing
    in the gap. Grouped by origin the same faces report as what they are: a
    small class carried through from one body, a large class cut by another,
    each with its own range.
    """
    if not action.feature:
        raise StructuralError(
            "no_feature", "list_origins needs the feature to look in", "facefind"
        )
    rows = _rows_for(state, action.feature, action.solid_index)
    summary = evolution_query.summarise_origins(rows, state.sector)
    if not summary["classes"]:
        summary["note"] = (
            "no face of this body has a recorded origin. That means no "
            "face-evolution index was built for it, not that the faces have "
            "no origin - the other tools work the same either way."
        )
    return {"ok": True, "result": summary}


def _query_faces(action, state: FaceFinderState) -> dict:
    if not action.feature:
        raise StructuralError(
            "no_feature", "query_faces needs the feature to look in", "facefind"
        )
    rows = _rows_for(state, action.feature, action.solid_index)
    filters = _filters(action)
    matched = geometry.query(
        rows, filters, surface_type=action.surface_type,
        origin_relation=action.origin_relation,
        origin_operand=action.origin_operand,
    )
    offset = max(0, action.offset)
    # A set the reply can carry is listed without being asked for.
    #
    # The default of listing nothing exists so an agent does not page through
    # thousands of faces, and that is not what a set of two hundred is. Both
    # ways of getting this wrong have now been measured: leaving a small set
    # behind the default had an agent write "list the carried faces to read
    # their normals" as its reason, get a summary anyway, and spend fourteen
    # calls re-running the query; and a cutoff of sixty faces meant the sets
    # this agent selects - 195, 308 - all landed on the wrong side of it, so
    # it re-ran the identical query up to twenty-five times. Neither is a
    # budget problem. Both are the harness declining to show a set it can
    # afford to show.
    if action.limit:
        limit = max(0, min(action.limit, MAX_FACES_PER_PAGE))
        page = matched[offset: offset + limit]
        listing = {
            "columns": list(geometry.COMPACT_COLUMNS),
            "faces": [geometry.compact_row(rows, i) for i in page],
            "faces_listed": len(page),
            "faces_withheld": len(matched) - len(page),
        }
    else:
        listing = geometry.compact(rows, matched[offset:], LISTING_BUDGET_CHARS)
        page = matched[offset: offset + listing["faces_listed"]]
    listed_in_full = (
        listing["faces_withheld"] == 0 and offset == 0
        and listing["faces_listed"] > 0
    )

    applied = {
        name: list(bounds)
        for name, bounds in filters.items()
        if bounds is not None
    }
    if action.surface_type:
        applied["surface_type"] = action.surface_type
    if action.origin_relation:
        applied["origin_relation"] = action.origin_relation
    if action.origin_operand:
        applied["origin_operand"] = action.origin_operand

    # An empty answer has two very different meanings and the agent has to be
    # able to tell them apart. "The bounds describe nothing here" is a fact
    # about the part and the answer is to widen them. "Nothing was asked and
    # nothing matched" is not a fact about the part at all - no bound was set,
    # so every face should have come back - and the answer is to say so rather
    # than keep narrowing a query that is not running. Told only "empty", an
    # agent does the reasonable thing and keeps trying, which is how a broken
    # predicate cost a budget without ever naming itself.
    if listed_in_full:
        note = (
            "the whole matched set is listed under `listing`, one face a line "
            "in the column order given there. The summary above describes all "
            "of it."
        )
    elif matched:
        note = (
            f"the summary describes the whole matched set; `listing` carries "
            f"the first {listing['faces_listed']} of {len(matched)} faces. "
            "Narrow with filters, or read the summary."
        )
    elif applied:
        note = (
            "no face matched the filters listed in filters_applied. That "
            "means those bounds describe nothing on this part - widen them "
            "rather than concluding the part is wrong."
        )
    else:
        note = (
            "no filter was set and yet nothing matched. That cannot be a "
            "property of the part, since nothing was asked of it; the query "
            "itself is not working. Say so instead of searching further."
        )

    return {
        "ok": True,
        "result": {
            "face_count_total": len(rows),
            "matched": len(matched),
            "offset": offset,
            "filters_applied": applied,
            "faces_listed": len(page),
            "listed_in_full": listed_in_full,
            # A page alone cannot be reasoned about: a set of several thousand
            # faces comes back sixty at a time, and an agent that has to walk
            # it never finishes. The summary is what lets a criterion be
            # written without seeing every face - it says what the matched set
            # is made of, so the next filter can be chosen from its shape.
            "summary": geometry.summarise(rows, matched),
            "sector_coverage": _sector_report(
                [rows[index] for index in matched], state
            ),
            "load_normal_alignment": _alignment_family_report(
                rows, [rows[index] for index in matched], state
            ),
            "listing": listing,
            "note": note,
        },
    }


def _inspect_faces(action, state: FaceFinderState) -> dict:
    rows = _rows_for(state, action.feature, action.solid_index)
    out_of_range = [
        index for index in action.face_indices
        if not 0 <= index < len(rows)
    ]
    if out_of_range:
        raise StructuralError(
            "face_index_out_of_range",
            f"these indices do not exist on feature {action.feature!r} solid "
            f"{action.solid_index}: {out_of_range[:8]}",
            "facefind",
        )
    return {
        "ok": True,
        "result": {"faces": geometry.describe(rows, action.face_indices)},
    }


def _resolve_indices(action, rows: list[dict], what: str) -> tuple[list[int], str]:
    """Which faces the action names, by filters or by index, and which it was.

    A selection can be stated two ways, and the second exists because the
    first does not scale. Naming indices means reading them off a listing, and
    a body with several thousand faces comes back sixty at a time - an agent
    that has to enumerate its answer cannot reach it. So the filters that
    describe the faces are an acceptable statement of them: the criterion says
    what the set must be, the filters say which faces it is, and this resolves
    them. Both may be given; the filters win when they are.

    Both actions that take a set go through here, so an agent that has already
    narrowed a set with filters can check it and submit it without listing it
    in between just to read its own indices off a page.

    The method is returned rather than left for the caller to infer. It was
    inferred once, by asking whether the resolved list was the same object as
    the action's `face_indices`, and that is a question about a list identity
    rather than about what the agent did - it reported "filters" for a
    submission that named only indices.
    """
    filters = _filters(action)
    if (any(bounds is not None for bounds in filters.values())
            or action.surface_type
            or action.origin_relation
            or action.origin_operand):
        resolved = geometry.query(
            rows, filters, surface_type=action.surface_type,
            origin_relation=action.origin_relation,
            origin_operand=action.origin_operand,
        )
        if not resolved:
            raise StructuralError(
                "filters_match_nothing",
                f"the filters describe no face on this solid, so there is "
                f"nothing for {what} to act on. Widen them - an empty match "
                "means the bounds describe nothing here, not that the part is "
                "wrong.",
                "facefind",
            )
        return resolved, "filters"
    if action.face_indices:
        indices = list(action.face_indices)
    else:
        raise StructuralError(
            "no_faces",
            f"{what} needs either face_indices or the filters that describe "
            "the faces. Prefer filters: naming indices means reading them off "
            "a listing that may be thousands of faces long.",
            "facefind",
        )

    bad = [index for index in indices if not 0 <= index < len(rows)]
    if bad:
        raise StructuralError(
            "face_index_out_of_range",
            f"these indices do not exist on feature {action.feature!r} solid "
            f"{action.solid_index}: {bad[:8]}. An index is only meaningful "
            "against the solid you name.",
            "facefind",
        )
    return indices, "indices"


def _check_criterion(action, state: FaceFinderState) -> dict:
    if action.criterion is None:
        raise StructuralError(
            "no_criterion", "check_criterion needs the criterion", "facefind"
        )
    rows = _rows_for(state, action.feature, action.solid_index)
    face_indices, _method = _resolve_indices(action, rows, "check_criterion")
    selected = [rows[index] for index in face_indices]
    result = criteria_tool.check_selection(
        action.criterion,
        selected,
        Vec3(x=0.0, y=0.0, z=0.0),
        Vec3(x=0.0, y=0.0, z=1.0),
    )
    result["checked_face_count"] = len(selected)
    result["submission"] = _submission_readiness(
        selected, state, all_rows=rows
    )
    return {"ok": True, "result": result}


def _submit_faces(action, state: FaceFinderState) -> dict:
    if action.criterion is None:
        raise StructuralError(
            "no_criterion",
            "a submission must state the criterion the faces were chosen "
            "against, so the check can be run against what you meant",
            "facefind",
        )
    if not action.feature:
        raise StructuralError(
            "no_feature",
            "a face index means nothing on its own; name the feature and "
            "solid_index the indices belong to",
            "facefind",
        )

    rows = _rows_for(state, action.feature, action.solid_index)
    face_indices, method = _resolve_indices(action, rows, "submit_faces")
    selected = [rows[index] for index in face_indices]
    readiness = _submission_readiness(selected, state, all_rows=rows)
    if readiness["problems"]:
        first = readiness["problems"][0].split(":", 1)[0]
        raise StructuralError(
            first,
            "the submitted set is not the set this analysis can solve: "
            + " | ".join(readiness["problems"]),
            "facefind",
        )
    residuals = criteria_tool.check_selection(
        action.criterion,
        selected,
        Vec3(x=0.0, y=0.0, z=0.0),
        Vec3(x=0.0, y=0.0, z=1.0),
    )
    total_area = sum(float(row["area_mm2"]) for row in selected)
    radii = [float(row["centroid_cyl_mm_deg"][0]) for row in selected]
    weighted = (
        sum(
            float(row["centroid_cyl_mm_deg"][0]) * float(row["area_mm2"])
            for row in selected
        ) / total_area
        if total_area
        else (sum(radii) / len(radii) if radii else 0.0)
    )

    state.submitted = {
        "accepted": True,
        "feature": action.feature,
        "solid_index": action.solid_index,
        "selected_face_indices": list(face_indices),
        "selection_method": method,
        "criterion": action.criterion.model_dump(mode="json"),
        "criterion_residuals": residuals,
        "submission_readiness": readiness,
        "area_mm2_total": round(total_area, 6),
        "load_radius_mm": round(weighted, 6),
        "radius_min_mm": round(min(radii), 6) if radii else None,
        "radius_max_mm": round(max(radii), 6) if radii else None,
        "rationale": action.rationale,
    }
    return {"ok": True, "result": state.submitted}


def _run_analysis(action, state: FaceFinderState) -> dict:
    """Run a script the agent wrote, against what it can already see.

    The tools answer the questions someone thought to ask. This is for the
    rest: an agent that needs to know whether a set of radii is one cluster or
    two has no filter that answers it, and a summary reporting a median will
    hide the second cluster rather than reveal it. Writing three lines and
    looking is what a person does, and it is what this allows.

    The script gets the same measured rows the agent has been reading, handed
    over as plain dictionaries, and may open the part itself if the question
    genuinely needs the model. It runs in a subprocess, so a crash in the
    geometry kernel ends the script rather than the run.
    """
    from seekflow_structural.runtime import analysis

    if not action.code.strip():
        raise StructuralError(
            "no_code", "run_analysis needs the code to run", "facefind"
        )
    if state.workdir is None:
        raise StructuralError(
            "no_sandbox",
            "this run has no sandbox directory, so a script cannot be run. "
            "Read the measurements with the other tools instead.",
            "facefind",
        )

    # Resolved the way every other tool resolves it, so a script run before
    # any query still gets the body it asked for rather than an empty set -
    # which would read as "this part has no faces" instead of "you have not
    # looked at one yet".
    if not action.feature:
        raise StructuralError(
            "no_feature",
            "run_analysis needs the feature whose faces the script works on",
            "facefind",
        )
    rows = _rows_for(state, action.feature, action.solid_index)
    payload = {
        "bundle": str(state.bundle) if state.bundle else None,
        "feature": action.feature,
        "solid_index": action.solid_index,
        "sector": state.sector,
        "rows": rows,
    }
    run_dir = state.workdir / f"{len(state.analyses):03d}"
    result = analysis.run_analysis(
        action.code, payload=payload, workdir=run_dir
    )
    state.analyses.append({
        "purpose": action.purpose,
        "code": action.code,
        "ok": result.ok,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
    })

    # The trailing end of stderr is where a traceback's actual message is, and
    # the sandbox truncates from the front - so the part that says what went
    # wrong is the part that survives.
    return {
        "ok": True,
        "result": {
            "ran": True,
            "succeeded": result.ok,
            "elapsed_ms": result.elapsed_ms,
            "stdout": result.stdout[:MAX_ANALYSIS_OUTPUT],
            # The sandbox truncates to exactly this length, so a reply that
            # fills it exactly is the only evidence there is that something
            # was cut - it cannot distinguish "the output was 4000 characters"
            # from "the output was 50000 and stopped here", and it says so
            # rather than implying the first.
            "stdout_truncated": len(result.stdout) >= MAX_ANALYSIS_OUTPUT,
            "stderr": result.stderr[-MAX_ANALYSIS_ERROR:],
            "error": result.error,
            "note": (
                "the script ran against the faces you can see; print what you "
                "want to read. A failure here is the script's, not the part's - "
                "the rows are the same measurements your other tools report."
            ),
        },
    }


def _needs_input(action, state: FaceFinderState) -> dict:
    return {
        "ok": True,
        "result": {"accepted": False, "questions": action.questions},
    }


class CommitAction(Action):
    """The action model for the agent's last call: decide, or say why not.

    Same fields as every other call, with the action narrowed to the two that
    end the run. Nothing here says which faces are right - the agent still
    chooses - but it does mean the choice gets a turn. Measured on D27: the
    agent had built the full table it needed by call nineteen, then asked the
    same question nine more times, and the run ended with no selection and
    twenty-four correct faces sitting in its own transcript.
    """

    action: Literal["submit_faces", "needs_input"]


DISPATCH = dispatch_table({
    "list_features": _list_features,
    "list_solids": _list_solids,
    "list_origins": _list_origins,
    "query_faces": _query_faces,
    "inspect_faces": _inspect_faces,
    "check_criterion": _check_criterion,
    "run_analysis": _run_analysis,
    "submit_faces": _submit_faces,
    "needs_input": _needs_input,
})


def _scope_lines(sector_deg: float | None, theta_low_deg: float) -> str:
    """Which part of the model is being analysed, when it is not all of it.

    Handed over as a measured fact about the case rather than as a filter the
    agent is told to apply. It comes from the domain stage's decision, and the
    agent is the one that decides what it implies for the faces it wants.

    It matters because a part solved as one sector of twenty has that sector's
    faces in the mesh and no others. A selection that reaches across all
    twenty describes a different model from the one being solved - and it
    looks correct, because every one of those faces genuinely does carry the
    load. The repeated copies are simply not in the analysis.
    """
    if sector_deg is None or sector_deg >= 360.0:
        return ""
    high = (theta_low_deg + sector_deg) % 360.0
    return (
        f"\n\nThe part is analysed as one repeating sector: azimuth "
        f"{theta_low_deg:g} to {high:g} degrees about the rotation axis, out "
        f"of a full revolution. Only that sector is meshed and solved, so it "
        f"is the only place a selection can land; the same faces recur in "
        f"every sector and one sector's worth is what is wanted. A submission "
        f"whose faces fall outside this sector is refused with their indices, "
        f"because they are not in the mesh."
    )


def spec(*, requirement: str, sector_deg: float | None = None,
         theta_low_deg: float = 0.0, max_calls: int = 10) -> AgentSpec:
    return AgentSpec(
        name="facefind",
        tool_name="face_action",
        tool_description=(
            "Inspect the model's features, solids and faces, or submit the "
            "faces that satisfy a stated criterion."
        ),
        action_model=Action,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            f"The requirement: {requirement}"
            + _scope_lines(sector_deg, theta_low_deg)
            + "\n\nStart with list_features to see what the model was built "
            "from."
        ),
        submit_actions=frozenset({"submit_faces", "needs_input"}),
        max_calls=max_calls,
        terminal_model=CommitAction,
    )


def to_case_selection(state: FaceFinderState, bundle: Path) -> LoadSurface:
    """The submission, in the form the rest of the chain reads."""
    payload = state.submitted
    if payload is None:
        raise StructuralError(
            "nothing_submitted",
            "the face-finding agent produced no selection",
            "facefind",
        )
    return LoadSurface(
        feature=str(payload["feature"]),
        solid_index=int(payload["solid_index"]),
        face_indices=[int(v) for v in payload["selected_face_indices"]],
        criterion=Criterion.model_validate(payload["criterion"]),
        criterion_residuals=payload.get("criterion_residuals") or {},
        area_mm2_total=float(payload.get("area_mm2_total") or 0.0),
        load_radius_mm=payload.get("load_radius_mm"),
        radius_min_mm=payload.get("radius_min_mm"),
        radius_max_mm=payload.get("radius_max_mm"),
        written=Written(
            by_stage="assembly", kind="agent_decision", source=str(bundle)
        ),
    )


@dataclass
class Outcome:
    """What one run of the agent leaves behind: the decision and the record."""

    final: dict | None
    trace: list[dict]
    calls: int
    exhausted: bool
    requirement: str
    state: FaceFinderState
    rejected: list[dict] = field(default_factory=list)

    def record(self) -> dict:
        """The audit artifact. The trace is the whole transcript, so a
        decision can be read back without re-running the model."""
        return {
            "schema_version": "facefind_run_v1",
            "requirement": self.requirement,
            "trace": self.trace,
            "rejected_calls": self.rejected,
            "final": self.final,
            "calls": self.calls,
            "exhausted": self.exhausted,
            # The scripts the agent wrote, with the question each was answering
            # and what it printed. Kept whole rather than summarised: a
            # selection that rests on a computation should be readable as the
            # computation, not as a description of one.
            "analyses": self.state.analyses,
        }


def run(*, spec: AgentSpec, caller, model_config, state: FaceFinderState
        ) -> Outcome:
    """Run the loop against an already-open document."""
    loop_outcome = run_agent(
        spec, caller=caller, model_config=model_config,
        dispatch=DISPATCH, context=state,
    )
    final = loop_outcome.final
    if final is None:
        final = exhausted_final("face-finding")
    return Outcome(
        final=final,
        trace=loop_outcome.trace,
        calls=loop_outcome.calls,
        exhausted=loop_outcome.exhausted,
        requirement=spec.user_prompt,
        state=state,
        rejected=loop_outcome.rejected,
    )
