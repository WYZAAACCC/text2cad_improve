"""Measure what the geometry is, before anything is decided about it.

Every stage below this one describes the part in some frame - radii, angles,
an axial direction, a symmetry plane. If that frame is taken from a config
file rather than measured, it is a claim, and D27 is what happens when the
claim is wrong: the config said the part was 38 mm half-thick when it was
42.207, and four millimetres of rim were cut off without an error.

So this stage measures the part with the tools that already exist - the
surface profile for radii and axial extent - and reports what it found. It
does not decide anything. The symmetry plane candidates it produces are
measurements with scores, and the domain agent is the one that chooses among
them.
"""
from __future__ import annotations

from pathlib import Path

from seekflow_structural.case.model import (
    Case,
    Frame,
    ModelFacts,
    Plane,
    Vec3,
    Written,
)
from seekflow_structural.core.mesh_profile import (
    build_profile,
    probe_mirror_plane,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext

# Candidate symmetry planes are the coordinate planes through the part's own
# centre. They are offered as measurements with a score, not as facts: the
# domain agent is told how well each maps the surface onto itself and decides
# what to use.
CANDIDATE_PLANES = (
    ("z0", (0.0, 0.0, 1.0), "the plane normal to the axis"),
    ("x0", (1.0, 0.0, 0.0), "the plane containing the axis"),
    ("y0", (0.0, 1.0, 0.0), "the plane containing the axis"),
)


def frame(ctx: RunContext) -> Case:
    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "frame has no case", "frame")

    bundle = Path(case.bundle.path)
    step = bundle / "model.step"
    if not step.is_file():
        raise StructuralError(
            "model_missing",
            f"{step} does not exist; the bundle needs model.step for the "
            "mesher and design.xbf for the topology",
            "frame",
        )

    axes = (
        _declared_axis(case)
        or _declared_axis_from_params(getattr(ctx, "params", None))
        or (Vec3(x=0.0, y=0.0, z=0.0), Vec3(x=0.0, y=0.0, z=1.0))
    )
    origin, direction = axes
    profile_path = ctx.path / "model" / "radial_profile.json"
    profile = None
    if profile_path.is_file():
        import json

        cached = json.loads(profile_path.read_text(encoding="utf-8"))
        same_axis = (
            cached.get("frame_axis_origin_mm") == list(origin.as_tuple())
            and cached.get("frame_axis_direction_mm") == list(
                direction.as_tuple()
            )
        )
        if same_axis:
            profile = cached
    if profile is None:
        profile = build_profile(
            step,
            12,
            axis_origin_mm=list(origin.as_tuple()),
            axis_direction_mm=list(direction.as_tuple()),
        )
        ctx.job.write("model/radial_profile.json", profile)

    r_max = float(profile["r_max_mm"])
    r_min = float(profile.get("r_min_mm") or 0.0)
    z_min = float(profile.get("z_min_mm") or 0.0)
    z_max = float(profile.get("z_max_mm") or 0.0)

    from seekflow_structural.tools.frames import Normalisation

    normalisation = Normalisation(
        list(origin.as_tuple()), list(direction.as_tuple())
    )
    case.model = ModelFacts(
        bounds_min_mm=Vec3(x=-r_max, y=-r_max, z=z_min),
        bounds_max_mm=Vec3(x=r_max, y=r_max, z=z_max),
        r_max_mm=r_max,
        has_rotation_axis=True,
        frame=Frame(
            axis_origin_mm=origin,
            axis_direction=direction,
            to_z=normalisation.as_matrix(),
            measured_from=f"profile of {bundle.name}",
        ),
        symmetry_planes=_plane_candidates(
            profile, centre_z=(z_min + z_max) / 2.0
        ),
        bore_radius_mm=r_min if r_min > 0 else None,
        face_count=int(profile.get("face_count") or 0),
        written=Written(
            by_stage="frame", kind="measured",
            source=f"surface profile of {step.name}",
        ),
    )
    ctx.job.event({
        "kind": "frame_measured",
        "stage": "frame",
        "r_max_mm": r_max,
        "r_min_mm": r_min,
        "z_min_mm": z_min,
        "z_max_mm": z_max,
        "symmetry_candidates": [
            {"id": plane.id, "score": plane.matched_area_fraction}
            for plane in case.model.symmetry_planes
        ],
    })
    return case




def _declared_axis_from_params(params: dict | None):
    """The rotation axis stated in the parameter file.

    Frame runs before setup, so  is intentionally empty at this
    point. The parameter file is already loaded into ; reading its
    rotation block here is what lets a tilted model be normalised before the
    domain agent measures the part.
    """
    if not isinstance(params, dict):
        return None
    rotation = params.get("rotation") or {}
    if not isinstance(rotation, dict):
        return None
    origin = rotation.get("axis_origin_mm")
    direction = rotation.get("axis_direction")
    if origin is None or direction is None:
        return None
    if isinstance(origin, dict):
        origin = [origin.get("x"), origin.get("y"), origin.get("z")]
    if isinstance(direction, dict):
        direction = [
            direction.get("x"), direction.get("y"), direction.get("z")
        ]
    try:
        return Vec3.of(origin), Vec3.of(direction)
    except (TypeError, ValueError):
        return None


def _declared_axis(case: Case):
    """An axis the user stated, if they stated one."""
    physics = case.physics
    if physics is None:
        return None
    rotation = physics.rotation
    if rotation.axis_origin_mm is None or rotation.axis_direction is None:
        return None
    return rotation.axis_origin_mm, rotation.axis_direction


def _plane_candidates(profile: dict, centre_z: float) -> list[Plane]:
    """Each candidate plane, with how much of the surface it maps onto itself.

    The score is the evidence. A part that is genuinely symmetric about z=0
    scores near 1; one that is not scores well below it, and the domain agent
    reads the number rather than being told which plane is symmetric.
    """
    faces = profile.get("faces")
    if not faces:
        return []
    out = []
    for plane_id, normal, note in CANDIDATE_PLANES:
        point = (
            Vec3(x=0.0, y=0.0, z=centre_z)
            if plane_id == "z0"
            else Vec3(x=0.0, y=0.0, z=0.0)
        )
        score = probe_mirror_plane(
            faces, point.as_tuple(), normal
        )
        out.append(
            Plane(
                id=plane_id,
                origin_mm=point,
                normal=Vec3(x=normal[0], y=normal[1], z=normal[2]),
                matched_area_fraction=round(float(score), 5),
                note=note,
            )
        )
    return out
