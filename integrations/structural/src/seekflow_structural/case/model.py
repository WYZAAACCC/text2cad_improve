"""The one document every stage reads and writes.

Two silent failures motivated this. The domain agent chose an 18 degree sector
while the face selector was still working to a hard-coded 3-9 degrees; later,
the mesh agent was told the load sat at radius 288 when the faces it was
refining for sat at 212.67. Both were the same mistake - an upstream decision
changed and a downstream *input* did not, because the value was restated on a
command line instead of carried in something.

So there is one case, every stage takes it and returns it, and no stage is
handed a scalar describing what an earlier stage measured. A stage that needs
the load radius reads `case.load_surface.load_radius_mm`; there is no argument
that could hold a stale copy of it.

Every field group carries a `Written` stamp saying which stage produced it and
whether it came from the user, from a measurement, or from an agent's
judgement. That is what makes a resume able to invalidate exactly the
downstream work a changed upstream decision has invalidated.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Provenance = Literal["user_input", "measured", "agent_decision", "derived"]


class Written(Model):
    """Where a field group came from, and what produced it."""

    by_stage: str
    kind: Provenance
    source: str = ""


class Vec3(Model):
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @classmethod
    def of(cls, values) -> "Vec3":
        x, y, z = values
        return cls(x=float(x), y=float(y), z=float(z))


class Frame(Model):
    """The axis the analysis is expressed about, and the transform onto +Z.

    Choosing the axis is the agent's; normalising the model so that axis is
    the deck's +Z is mechanical. Keeping both here means the choice and its
    consequence travel together, and no module has to guess which frame its
    coordinates are in.

    `to_z` is a rigid rotation about the chosen axis followed by a translation
    with only components perpendicular to it. That composition preserves
    distance from the axis, which is what keeps every radius in the rest of
    the package - bore radii, band edges, load radius - valid after the
    transform.
    """

    axis_origin_mm: Vec3
    axis_direction: Vec3
    to_z: list[list[float]] | None = None
    measured_from: str = ""


class Plane(Model):
    """A measured candidate symmetry plane, with the evidence for it."""

    id: str
    origin_mm: Vec3
    normal: Vec3
    matched_area_fraction: float
    note: str = ""


class ModelFacts(Model):
    """What the geometry is, measured before any physics is decided."""

    bounds_min_mm: Vec3
    bounds_max_mm: Vec3
    r_max_mm: float
    has_rotation_axis: bool = False
    frame: Frame | None = None
    symmetry_planes: list[Plane] = Field(default_factory=list)
    bore_radius_mm: float | None = None
    face_count: int = 0
    limits: list[str] = Field(default_factory=list)
    written: Written


class DomainDecision(Model):
    """Which piece of the part is analysed."""

    # None means the whole part: there is no repeat unit to cut out. Stored as
    # an explicit absence rather than 360.0 so that "full" and "a 360 degree
    # sector" cannot be confused by anything downstream.
    sector_deg: float | None = None
    theta_low_deg: float = 0.0
    symmetry_planes_used: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    rationale: str = ""
    written: Written


class NormalClause(Model):
    """A bound on one component of a face normal, in the case frame."""

    component: Literal[
        "face_normal", "radial", "axial", "tangential", "frame_axis"
    ]
    minimum: float = -1e30
    maximum: float = 1e30


class SymmetryClause(Model):
    kind: Literal["mirror_plane", "rotational_order"]
    ref: str
    normal_sign: Literal["same", "opposite", "unconstrained"] = "unconstrained"
    area_rel_tol: float = 0.05


class CountClause(Model):
    min_count: int = 1
    max_count: int | None = None
    even: bool | None = None


class Criterion(Model):
    """What a set of faces is required to be - stated by the agent, not by us.

    This replaces a fixed gate. The previous validator hard-coded one
    component's idea of a load face: planar, a radial normal of at least 0.2,
    no axial component, one radial sign, an even count, and every face mirrored
    by a partner. That is a fir-tree flank, and it rejected a curved blade
    platform or a bracket's cylindrical boss without saying why.

    Now the agent declares the criterion it means, the harness checks the
    submitted faces against *that*, and reports each clause's residual. The
    harness no longer knows what a load face is. Load faces, constraint faces,
    symmetry faces and post-processing sections are all the same tool with a
    different criterion.
    """

    intent: str
    surface_types: list[str] = Field(default_factory=list)
    normal_clauses: list[NormalClause] = Field(default_factory=list)
    symmetry: SymmetryClause | None = None
    count: CountClause | None = None
    notes: str = ""


class LoadSurface(Model):
    """The faces the load enters through, and what was measured about them.

    `load_radius_mm` is written here, by the same stage that chose the faces.
    The meshing stage can only read it. That is the whole fix for the second
    seam: there is nowhere for a stale copy to live.
    """

    feature: str
    solid_index: int = 0
    face_indices: list[int] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    criterion: Criterion | None = None
    criterion_residuals: dict = Field(default_factory=dict)
    area_mm2_total: float = 0.0
    load_radius_mm: float | None = None
    radius_min_mm: float | None = None
    radius_max_mm: float | None = None
    centroid_mm: Vec3 | None = None
    written: Written


class RotationBinding(Model):
    rpm: float | None = None
    axis_origin_mm: Vec3 | None = None
    axis_direction: Vec3 | None = None
    source: str = ""


class TemperatureBinding(Model):
    model: str = ""
    reference_temperature_c: float | None = None
    payload: dict = Field(default_factory=dict)
    source: str = ""


class MaterialPoint(Model):
    temperature_c: float
    young_mpa: float
    alpha_per_c: float
    yield_mpa: float


class MaterialBinding(Model):
    name: str = ""
    poisson_ratio: float | None = None
    density_t_mm3: float | None = None
    points: list[MaterialPoint] = Field(default_factory=list)
    source: str = ""


class LoadBinding(Model):
    model: str = ""
    total_force_n_per_slot: float | None = None
    effective_mass_kg: float | None = None
    center_of_mass_radius_mm: float | None = None
    blades_per_slot: int = 1
    direction_rule: str = ""
    distribution: str = ""
    source: str = ""


class ConstraintBinding(Model):
    cyclic_symmetry: bool = False
    axial_symmetry_z0: bool = False
    tangential_anchor: bool = False
    source: str = ""


class ConsistencyFinding(Model):
    """A pair of the user's own numbers that do not agree.

    A measurement, not a verdict: it says which two quantities were compared
    and by how much they differ. Whether that matters is the agent's call, and
    the run is not stopped by it.
    """

    quantity: str
    stated: float | str | None = None
    implied: float | str | None = None
    relative_difference: float | None = None
    note: str = ""


class Physics(Model):
    """The loads, constraints and materials - values from the user only."""

    rotation: RotationBinding = Field(default_factory=RotationBinding)
    temperature: TemperatureBinding = Field(default_factory=TemperatureBinding)
    material: MaterialBinding = Field(default_factory=MaterialBinding)
    blade_load: LoadBinding = Field(default_factory=LoadBinding)
    constraints: ConstraintBinding = Field(default_factory=ConstraintBinding)
    consistency: list[ConsistencyFinding] = Field(default_factory=list)
    written: Written


class MeshRegion(Model):
    """Where resolution is spent, described rather than named by a radius.

    A refinement zone used to be a radius plus a ramp, which can only express
    a full annulus about one axis - a bracket's bolt hole or a blade's tip
    cannot be described that way at all. `kind` now selects one of the three
    analytic shapes the mesher can size on, each of which is a distance.

    `faces` is still accepted here so a plan written before that vocabulary
    was withdrawn still loads; the mesher has no way to express proximity to a
    face set, and nothing produces one any more.
    """

    name: str
    kind: Literal["sphere", "cylinder", "box", "faces"]
    size_mm: float
    ramp_mm: float
    center_mm: Vec3 | None = None
    radius_mm: float | None = None
    half_height_mm: float | None = None
    min_mm: Vec3 | None = None
    max_mm: Vec3 | None = None
    face_indices: list[int] = Field(default_factory=list)
    distance_mm: float | None = None
    rationale: str = ""


class MeshPlan(Model):
    regions: list[MeshRegion] = Field(default_factory=list)
    web_size_mm: float = 0.0
    element_budget: int = 0
    measured: dict = Field(default_factory=dict)
    written: Written


class BundleRef(Model):
    """The model input, and the hashes that bind it.

    The chain opens `design.xbf` for topology and `model.step` for meshing;
    `history.json` carries the topology hash of the former. A pipeline that
    does not check these can be pointed at a mismatched pair and will not
    notice.
    """

    path: str
    lineage_id: str = ""
    revision_id: str = ""
    model_step_sha256: str = ""
    design_xbf_sha256: str = ""
    history_topology_hash: str = ""


class SolveRecord(Model):
    job_dir: str = ""
    started_at_utc: str = ""
    finished_at_utc: str = ""
    ansys_exit_ok: bool = False
    metrics: dict = Field(default_factory=dict)
    load_audit: dict = Field(default_factory=dict)
    scientific_status: str = ""
    written: Written | None = None


class Comparison(Model):
    """Two independent measurements and the residual between them."""

    name: str
    left: str
    right: str
    residual: float | None = None
    relative: float | None = None
    note: str = ""


class QuantityVerdict(Model):
    """Whether one reported number may be quoted, and on what evidence.

    `confirmed_wrong` requires two independent measurements that contradict
    each other. `unverified` is the honest answer when only one measurement
    exists - it is not a failure, it is the absence of a second opinion, and
    a report that omits it overstates what was done.
    """

    quantity: str
    verdict: Literal["confirmed_wrong", "suspect", "unverified"]
    checks: list[Comparison] = Field(default_factory=list)
    rationale: str = ""


class Case(Model):
    schema_version: Literal["structural_case_v1"] = "structural_case_v1"
    case_id: str
    params_hash: str = ""
    bundle: BundleRef
    model: ModelFacts | None = None
    domain: DomainDecision | None = None
    load_surface: LoadSurface | None = None
    physics: Physics | None = None
    mesh: MeshPlan | None = None
    solve: SolveRecord | None = None
    verdicts: list[QuantityVerdict] = Field(default_factory=list)

    def stage_hash(self) -> str:
        from seekflow_structural.serialize import digest

        return digest(self)
