from __future__ import annotations

import math
from typing import Any

KERNEL_NAME = "cadquery_turbine_disk_reference_v5"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
GEOMETRY_FAMILY = "axisymmetric_base_with_symmetric_multistage_fir_tree_slots"


# -- Parameter helpers --
def _get_float(params, key, default=0.0):
    return float(params.get(key, default))

def _get_int(params, key, default=0):
    return int(params.get(key, default))

def _get_bool(params, key, default=False):
    return bool(params.get(key, default))


# -- Hole pattern metadata helper --
def _hole_pattern_metadata(name, count, pcd_mm, dia_mm, axis):
    return {"name": name, "count": int(count), "pcd_mm": float(pcd_mm),
            "hole_dia_mm": float(dia_mm), "axis": axis}


# -- Base body --
def _build_base_body(cq, params):
    """Build revolved disk body. Returns (result, profile_points, axial_zones)."""
    outer_d = _get_float(params, "outer_dia_mm")
    bore_d = _get_float(params, "bore_dia_mm")
    hub_d = _get_float(params, "hub_outer_dia_mm")
    web_d = _get_float(params, "web_outer_dia_mm")
    rim_inner_d = _get_float(params, "rim_inner_dia_mm")
    hub_w = _get_float(params, "hub_width_mm")
    web_w = _get_float(params, "web_width_mm")
    rim_w = _get_float(params, "rim_width_mm")

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    t_hub = hub_w / 2.0
    t_web = web_w / 2.0
    t_rim = rim_w / 2.0

    profile_points = [
        (r_bore, -t_hub), (r_hub, -t_hub), (r_hub, -t_web),
        (r_web, -t_web), (r_rim_inner, -t_rim), (r_outer, -t_rim),
        (r_outer, t_rim), (r_rim_inner, t_rim), (r_web, t_web),
        (r_hub, t_web), (r_hub, t_hub), (r_bore, t_hub),
    ]

    result = (
        cq.Workplane("XZ")
        .polyline(profile_points)
        .close()
        .revolve()
    )

    axial_zones = {
        "rim_z_min_mm": -t_rim,
        "rim_z_max_mm": t_rim,
        "hub_z_min_mm": -t_hub,
        "hub_z_max_mm": t_hub,
        "web_z_min_mm": -t_web,
        "web_z_max_mm": t_web,
        "base_z_min_mm": -t_hub,
        "base_z_max_mm": t_hub,
    }

    return result, profile_points, axial_zones


# -- Hub sleeves --
def _add_front_hub_sleeve(cq, result, params):
    front_outer = _get_float(params, "front_hub_sleeve_outer_dia_mm")
    front_inner = _get_float(params, "front_hub_sleeve_inner_dia_mm")
    front_height = _get_float(params, "front_hub_sleeve_height_mm")
    front_chamfer = _get_float(params, "front_hub_sleeve_chamfer_mm")
    if front_height <= 0:
        return result
    base_front_z = _get_float(params, "axial_width_mm") / 2.0
    sleeve = (
        cq.Workplane("XY")
        .circle(front_outer / 2.0)
        .circle(front_inner / 2.0)
        .extrude(front_height)
        .translate((0, 0, base_front_z))
    )
    result = result.union(sleeve)
    if front_chamfer > 0:
        try:
            result = result.edges(">Z").chamfer(front_chamfer)
        except Exception:
            pass
    return result


def _add_rear_hub_sleeve(cq, result, params):
    rear_outer = _get_float(params, "rear_hub_sleeve_outer_dia_mm")
    rear_inner = _get_float(params, "rear_hub_sleeve_inner_dia_mm")
    rear_height = _get_float(params, "rear_hub_sleeve_height_mm")
    rear_chamfer = _get_float(params, "rear_hub_sleeve_chamfer_mm")
    if rear_height <= 0:
        return result
    base_rear_z = -_get_float(params, "axial_width_mm") / 2.0
    sleeve = (
        cq.Workplane("XY")
        .circle(rear_outer / 2.0)
        .circle(rear_inner / 2.0)
        .extrude(rear_height)
        .translate((0, 0, base_rear_z - rear_height))
    )
    result = result.union(sleeve)
    if rear_chamfer > 0:
        try:
            result = result.edges("<Z").chamfer(rear_chamfer)
        except Exception:
            pass
    return result


# -- Annular details -- (keep existing v0.2 implementation unchanged)
def _add_annular_details(cq, result, params):
    enabled = _get_bool(params, "enable_annular_details", default=True)
    if not enabled:
        return result
    axial = _get_float(params, "axial_width_mm") / 2.0
    outer_d = _get_float(params, "outer_dia_mm")
    bore_d = _get_float(params, "bore_dia_mm")
    r_bore = bore_d / 2.0
    r_outer = outer_d / 2.0

    inner_hub_step_height = _get_float(params, "inner_hub_step_height_mm")
    inner_hub_step_outer_d = _get_float(params, "inner_hub_step_outer_dia_mm")
    if inner_hub_step_height > 0 and inner_hub_step_outer_d > bore_d:
        r_step = inner_hub_step_outer_d / 2.0
        step = (
            cq.Workplane("XY").circle(r_step).circle(r_bore)
            .extrude(inner_hub_step_height).translate((0, 0, axial))
        )
        result = result.union(step)

    mid_web_recess_depth = _get_float(params, "mid_web_recess_depth_mm")
    mid_web_recess_inner_d = _get_float(params, "mid_web_recess_inner_dia_mm")
    mid_web_recess_outer_d = _get_float(params, "mid_web_recess_outer_dia_mm")
    if mid_web_recess_depth > 0 and mid_web_recess_outer_d > mid_web_recess_inner_d:
        r_mid_inner = mid_web_recess_inner_d / 2.0
        r_mid_outer = mid_web_recess_outer_d / 2.0
        recess = (
            cq.Workplane("XY").circle(r_mid_outer).circle(r_mid_inner)
            .extrude(mid_web_recess_depth).translate((0, 0, axial - mid_web_recess_depth))
        )
        result = result.cut(recess)

    outer_rim_recess_depth = _get_float(params, "outer_rim_recess_depth_mm")
    outer_rim_recess_inner_d = _get_float(params, "outer_rim_recess_inner_dia_mm")
    outer_rim_recess_outer_d = _get_float(params, "outer_rim_recess_outer_dia_mm")
    if outer_rim_recess_depth > 0 and outer_rim_recess_outer_d > outer_rim_recess_inner_d:
        r_outer_inner = outer_rim_recess_inner_d / 2.0
        r_outer_outer = outer_rim_recess_outer_d / 2.0
        recess = (
            cq.Workplane("XY").circle(r_outer_outer).circle(r_outer_inner)
            .extrude(outer_rim_recess_depth).translate((0, 0, axial - outer_rim_recess_depth))
        )
        result = result.cut(recess)

    seal_land_count = _get_int(params, "seal_land_count")
    seal_land_height = _get_float(params, "seal_land_height_mm")
    seal_land_width = _get_float(params, "seal_land_width_mm")
    seal_land_start_d = _get_float(params, "seal_land_start_dia_mm")
    seal_land_pitch = _get_float(params, "seal_land_pitch_mm")
    if seal_land_count > 0 and seal_land_height > 0 and seal_land_width > 0:
        for i in range(seal_land_count):
            z_offset = axial + i * seal_land_pitch
            r_start = seal_land_start_d / 2.0 + i * seal_land_pitch
            land = (
                cq.Workplane("XY").circle(r_start + seal_land_width).circle(r_start)
                .extrude(seal_land_height).translate((0, 0, z_offset))
            )
            result = result.union(land)
    return result


# -- Hole rings --
def _cut_hole_ring(result, *, count, pcd_mm, hole_dia_mm, axis):
    if count == 0:
        return result
    if axis != "Z":
        raise ValueError(f"Only Z-axis through holes are supported, got {axis!r}")
    radius = pcd_mm / 2.0
    return (
        result.faces(">Z").workplane(centerOption="CenterOfBoundBox")
        .polarArray(radius, 0, 360, count).hole(hole_dia_mm)
    )


# -- Coverplate bolt ring --
def _cut_coverplate_bolt_ring(result, params):
    count = _get_int(params, "coverplate_bolt_count")
    pcd = _get_float(params, "coverplate_bolt_pcd_mm")
    dia = _get_float(params, "coverplate_bolt_dia_mm")
    axis = str(params.get("coverplate_bolt_axis", "Z"))
    return _cut_hole_ring(result, count=count, pcd_mm=pcd, hole_dia_mm=dia, axis=axis)


# -- Balance hole ring --
def _cut_balance_hole_ring(result, params):
    count = _get_int(params, "balance_hole_count")
    pcd = _get_float(params, "balance_hole_pcd_mm")
    dia = _get_float(params, "balance_hole_dia_mm")
    axis = str(params.get("balance_hole_axis", "Z"))
    return _cut_hole_ring(result, count=count, pcd_mm=pcd, hole_dia_mm=dia, axis=axis)


# =====================================================================
# v4 INTERNAL-LOBE FIR-TREE SOCKET PROFILE
# =====================================================================

def _slot_widths(params):
    mouth = _get_float(params, "rim_slot_mouth_width_mm")
    throat = _get_float(params, "rim_slot_throat_width_mm")
    neck = _get_float(params, "rim_slot_stage_neck_width_mm")
    lobe = _get_float(params, "rim_slot_stage_lobe_width_mm")
    root = _get_float(params, "rim_slot_root_width_mm")
    growth = _get_float(params, "rim_slot_stage_width_growth")
    return mouth, throat, neck, lobe, root, growth


def _fir_tree_stage_stations(params):
    outer_d = _get_float(params, "outer_dia_mm")
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm")
    stage_count = _get_int(params, "rim_slot_stage_count", default=3)
    stage_pitch = _get_float(params, "rim_slot_stage_pitch_mm")
    lobe_height = _get_float(params, "rim_slot_stage_lobe_height_mm")
    dist_mode = str(params.get("rim_slot_stage_depth_distribution", "uniform"))

    r_outer = outer_d / 2.0
    r_ref = r_outer + outer_clearance
    mouth_w, throat_w, neck_w, lobe_w, root_w, growth = _slot_widths(params)

    stations = []
    stations.append((r_ref, 0.0, "entry"))
    stations.append((r_ref - depth * 0.06, mouth_w, "mouth"))
    stations.append((r_outer - depth * 0.25, throat_w, "throat"))

    for s in range(stage_count):
        w_growth = 1.0 + growth * s
        stage_lobe_w = lobe_w * w_growth
        if dist_mode == "uniform":
            base_x = r_outer - depth * (0.40 + s * 0.16)
        else:
            base_x = r_outer - depth * (0.35 + s * 0.20)

        stations.append((base_x - lobe_height * 0.3, neck_w * w_growth, f"stage{s+1}_neck"))
        stations.append((base_x, stage_lobe_w, f"stage{s+1}_lobe"))
        stations.append((base_x + lobe_height * 0.5, stage_lobe_w * 0.85, f"stage{s+1}_base"))

    last_stage_x = r_outer - depth * (0.40 + (stage_count - 1) * 0.16)
    stations.append((r_outer - depth * 0.92, root_w, "root"))

    return stations


def _symmetric_slot_profile_from_stations(stations):
    left = []
    right = []
    for x, width, name in stations:
        hw = width / 2.0
        left.append((float(x), -float(hw)))
        right.append((float(x), float(hw)))

    profile = left + list(reversed(right))
    return profile


def _assert_profile_mirror_y(profile):
    n = len(profile)
    if n % 2 != 0:
        raise ValueError(f"Profile must have even number of points for mirror_y, got {n}")
    half = n // 2
    for i in range(half):
        xl, yl = profile[i]
        xr, yr = profile[n - 1 - i]
        if abs(float(xl) - float(xr)) > 0.001:
            raise ValueError(f"Profile not mirror-symmetric: x[{i}]={xl} != x[{n-1-i}]={xr}")
        if abs(float(yl) + float(yr)) > 0.001:
            raise ValueError(f"Profile not mirror-symmetric: y[{i}]={yl} != -y[{n-1-i}]={yr}")


def _fir_tree_symmetric_multistage_profile_xy(params):
    stations = _fir_tree_stage_stations(params)
    profile = _symmetric_slot_profile_from_stations(stations)
    _assert_profile_mirror_y(profile)
    return profile, stations


def _make_axial_through_slot_cutter(cq, params, rim_z_min, rim_z_max):
    outer_d = _get_float(params, "outer_dia_mm")
    r_outer = outer_d / 2.0
    through_clearance = _get_float(params, "rim_slot_through_clearance_mm")

    z_min = float(rim_z_min) - through_clearance
    z_max = float(rim_z_max) + through_clearance
    height = z_max - z_min

    profile, stations = _fir_tree_symmetric_multistage_profile_xy(params)

    xs = [p[0] for p in profile]
    max_x = max(xs)
    min_x = min(xs)
    stage_count = _get_int(params, "rim_slot_stage_count", default=3)

    cutter = (
        cq.Workplane("XY")
        .polyline(profile)
        .close()
        .extrude(height)
        .translate((0, 0, z_min))
    )

    cutter_metadata = {
        "profile_points_xy": [[float(p[0]), float(p[1])] for p in profile],
        "max_x_mm": float(max_x),
        "min_x_mm": float(min_x),
        "outer_radius_mm": float(r_outer),
        "z_min_mm": float(z_min),
        "z_max_mm": float(z_max),
        "height_mm": float(height),
        "rim_z_min_mm": float(rim_z_min),
        "rim_z_max_mm": float(rim_z_max),
        "through_clearance_mm": through_clearance,
        "opens_front_face": float(z_max) > float(rim_z_max),
        "opens_back_face": float(z_min) < float(rim_z_min),
        "opens_outer_diameter": float(max_x) > r_outer,
        "exposes_lobes_on_od": False,
        "is_mirror_symmetric": True,
        "profile_symmetry": "mirror_y",
        "stage_count": int(stage_count),
        "stage_stations": [[float(x), float(w), str(n)] for x, w, n in stations],
    }

    return cutter, cutter_metadata


def _cut_rim_slots(cq, result, params, axial_zones):
    count = _get_int(params, "rim_slot_count")
    style = str(params.get("rim_slot_style", "none"))
    orientation = str(params.get("rim_slot_orientation", "axial_through"))
    socket_mode = str(params.get("rim_slot_socket_mode", "internal_lobes"))
    expose_lobes = params.get("rim_slot_expose_lobes_on_od", False)
    require_stages = params.get("rim_slot_require_multiple_stages", True)
    stage_count = _get_int(params, "rim_slot_stage_count", default=3)
    sym = str(params.get("rim_slot_profile_symmetry", "mirror_y"))

    if count <= 0 or style == "none":
        return result, {
            "enabled": False, "slot_count": 0, "slot_style": "none",
            "slot_orientation": orientation, "socket_mode": socket_mode,
            "opens_front_face": False, "opens_back_face": False,
            "opens_outer_diameter": False, "exposes_lobes_on_od": False,
            "is_mirror_symmetric": False, "profile_symmetry": sym,
            "stage_count": 0,
        }

    if orientation != "axial_through":
        raise ValueError(f"v5 only supports axial_through, got {orientation!r}")
    if socket_mode != "internal_lobes":
        raise ValueError(f"v5 only supports internal_lobes, got {socket_mode!r}")
    if expose_lobes is not False:
        raise ValueError("rim_slot_expose_lobes_on_od must be False")
    if require_stages and stage_count < 2:
        raise ValueError(f"rim_slot_require_multiple_stages=True requires stage_count>=2, got {stage_count}")
    if sym != "mirror_y":
        raise ValueError(f"v5 requires profile_symmetry='mirror_y', got {sym!r}")

    rim_z_min = float(axial_zones["rim_z_min_mm"])
    rim_z_max = float(axial_zones["rim_z_max_mm"])
    cutter, cutter_meta = _make_axial_through_slot_cutter(cq, params, rim_z_min, rim_z_max)

    for i in range(count):
        angle = 360.0 * i / count
        rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
        result = result.cut(rotated)

    slot_metadata = {
        "enabled": True, "slot_count": int(count), "slot_style": style,
        "slot_orientation": orientation, "socket_mode": socket_mode,
        "exposes_lobes_on_od": False,
        "profile_symmetry": "mirror_y",
        "is_mirror_symmetric": True,
        "stage_count": int(stage_count),
        "stage_stations": cutter_meta["stage_stations"],
        "slot_depth_mm": _get_float(params, "rim_slot_depth_mm"),
        "mouth_width_mm": _get_float(params, "rim_slot_mouth_width_mm"),
        "throat_width_mm": _get_float(params, "rim_slot_throat_width_mm"),
        "stage_neck_width_mm": _get_float(params, "rim_slot_stage_neck_width_mm"),
        "stage_lobe_width_mm": _get_float(params, "rim_slot_stage_lobe_width_mm"),
        "root_width_mm": _get_float(params, "rim_slot_root_width_mm"),
        "slot_profile_points_xy": cutter_meta["profile_points_xy"],
        "reference_only": True,
        "opens_front_face": cutter_meta["opens_front_face"],
        "opens_back_face": cutter_meta["opens_back_face"],
        "opens_outer_diameter": cutter_meta["opens_outer_diameter"],
        "z_min_mm": cutter_meta["z_min_mm"], "z_max_mm": cutter_meta["z_max_mm"],
        "rim_z_min_mm": cutter_meta["rim_z_min_mm"], "rim_z_max_mm": cutter_meta["rim_z_max_mm"],
        "max_x_mm": cutter_meta["max_x_mm"], "min_x_mm": cutter_meta["min_x_mm"],
        "outer_radius_mm": cutter_meta["outer_radius_mm"],
        "through_clearance_mm": cutter_meta["through_clearance_mm"],
    }

    return result, slot_metadata



def _reference_dimensions(params, axial_zones=None, slot_metadata=None):
    total_hole_count = (
        1 + int(params.get("bolt_hole_count", 0))
        + int(params.get("lightening_hole_count", 0))
        + int(params.get("cooling_hole_count", 0))
        + int(params.get("coverplate_bolt_count", 0))
        + int(params.get("balance_hole_count", 0))
    )
    rim_count = int(params.get("rim_slot_count", 0))
    rim_orientation = str(params.get("rim_slot_orientation", "axial_through"))
    sm = slot_metadata or {}

    return {
        "outer_dia_mm": float(params["outer_dia_mm"]),
        "bore_dia_mm": float(params["bore_dia_mm"]),
        "axial_width_mm": float(params["axial_width_mm"]),
        "hub_outer_dia_mm": float(params["hub_outer_dia_mm"]),
        "web_outer_dia_mm": float(params["web_outer_dia_mm"]),
        "rim_inner_dia_mm": float(params["rim_inner_dia_mm"]),
        "hub_width_mm": float(params["hub_width_mm"]),
        "web_width_mm": float(params["web_width_mm"]),
        "rim_width_mm": float(params["rim_width_mm"]),
        "bolt_hole_count": int(params.get("bolt_hole_count", 0)),
        "lightening_hole_count": int(params.get("lightening_hole_count", 0)),
        "cooling_hole_count": int(params.get("cooling_hole_count", 0)),
        "coverplate_bolt_count": int(params.get("coverplate_bolt_count", 0)),
        "balance_hole_count": int(params.get("balance_hole_count", 0)),
        "rim_slot_count": rim_count,
        "rim_slot_style": str(params.get("rim_slot_style", "none")),
        "rim_slot_orientation": rim_orientation,
        "rim_slot_socket_mode": str(params.get("rim_slot_socket_mode", "internal_lobes")),
        "rim_slot_profile_symmetry": str(params.get("rim_slot_profile_symmetry", "mirror_y")),
        "rim_slot_stage_count": int(params.get("rim_slot_stage_count", 3)),
        "rim_slot_is_mirror_symmetric": True,
        "rim_slot_exposes_lobes_on_od": bool(params.get("rim_slot_expose_lobes_on_od", False)),
        "rim_slot_mouth_width_mm": _get_float(params, "rim_slot_mouth_width_mm"),
        "rim_slot_throat_width_mm": _get_float(params, "rim_slot_throat_width_mm"),
        "rim_slot_stage_neck_width_mm": _get_float(params, "rim_slot_stage_neck_width_mm"),
        "rim_slot_stage_lobe_width_mm": _get_float(params, "rim_slot_stage_lobe_width_mm"),
        "rim_slot_root_width_mm": _get_float(params, "rim_slot_root_width_mm"),
        "rim_slot_depth_mm": _get_float(params, "rim_slot_depth_mm"),
        "rim_slot_width_mm": _get_float(params, "rim_slot_width_mm"),
        "rim_slot_opens_front_face": bool(sm.get("opens_front_face", False)),
        "rim_slot_opens_back_face": bool(sm.get("opens_back_face", False)),
        "rim_slot_opens_outer_diameter": bool(sm.get("opens_outer_diameter", False)),
        "rim_slot_z_min_mm": float(sm.get("z_min_mm", 0.0)),
        "rim_slot_z_max_mm": float(sm.get("z_max_mm", 0.0)),
        "rim_slot_profile_max_x_mm": float(sm.get("max_x_mm", 0.0)),
        "rim_slot_profile_min_x_mm": float(sm.get("min_x_mm", 0.0)),
        "front_hub_sleeve_height_mm": _get_float(params, "front_hub_sleeve_height_mm"),
        "front_hub_sleeve_outer_dia_mm": _get_float(params, "front_hub_sleeve_outer_dia_mm"),
        "front_hub_sleeve_inner_dia_mm": _get_float(params, "front_hub_sleeve_inner_dia_mm"),
        "expected_periodic_slot_count": rim_count,
        "expected_fir_tree_stage_count": int(params.get("rim_slot_stage_count", 3)) if rim_count > 0 else 0,
        "expected_through_hole_count": total_hole_count,
        "expected_bbox_mm": [
            float(params["outer_dia_mm"]),
            float(params["outer_dia_mm"]),
            float(params["axial_width_mm"])
            + _get_float(params, "front_hub_sleeve_height_mm")
            + _get_float(params, "rear_hub_sleeve_height_mm"),
        ],
    }


# -- Metadata --
def _build_metadata(params, profile_points, axial_zones, slot_metadata, warnings):
    outer_d = float(params["outer_dia_mm"])
    bore_d = float(params["bore_dia_mm"])
    hub_d = float(params["hub_outer_dia_mm"])
    web_d = float(params["web_outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    ref_dims = _reference_dimensions(params, axial_zones, slot_metadata)

    sm = slot_metadata or {}
    rim_count = int(params.get("rim_slot_count", 0))
    rim_orientation = str(params.get("rim_slot_orientation", "axial_through"))
    socket_mode = str(params.get("rim_slot_socket_mode", "internal_lobes"))

    return {
        "primitive": PRIMITIVE_NAME,
        "metadata_version": "primitive_metadata_v1",
        "kernel": KERNEL_NAME,
        "geometry_family": GEOMETRY_FAMILY,
        "parameters": dict(params),
        "reference_dimensions": ref_dims,
        "warnings": list(warnings),
        "radial_zones": {
            "bore_radius_mm": r_bore,
            "hub_outer_radius_mm": r_hub,
            "web_outer_radius_mm": r_web,
            "rim_inner_radius_mm": r_rim_inner,
            "outer_radius_mm": r_outer,
        },
        "axial_zones": dict(axial_zones) if axial_zones else {},
        "profile_points": [[float(r), float(z)] for r, z in profile_points],
        "hole_patterns": [
            _hole_pattern_metadata("bolt", int(params.get("bolt_hole_count", 0)),
                float(params.get("bolt_pcd_mm", 0)), float(params.get("bolt_hole_dia_mm", 0)),
                str(params.get("bolt_hole_axis", "Z"))),
            _hole_pattern_metadata("lightening", int(params.get("lightening_hole_count", 0)),
                float(params.get("lightening_hole_pcd_mm", 0)), float(params.get("lightening_hole_dia_mm", 0)),
                str(params.get("lightening_hole_axis", "Z"))),
            _hole_pattern_metadata("cooling", int(params.get("cooling_hole_count", 0)),
                float(params.get("cooling_hole_pcd_mm", 0)), float(params.get("cooling_hole_dia_mm", 0)),
                str(params.get("cooling_hole_axis", "Z"))),
            _hole_pattern_metadata("coverplate_bolt", int(params.get("coverplate_bolt_count", 0)),
                float(params.get("coverplate_bolt_pcd_mm", 0)), float(params.get("coverplate_bolt_dia_mm", 0)),
                str(params.get("coverplate_bolt_axis", "Z"))),
            _hole_pattern_metadata("balance", int(params.get("balance_hole_count", 0)),
                float(params.get("balance_hole_pcd_mm", 0)), float(params.get("balance_hole_dia_mm", 0)),
                str(params.get("balance_hole_axis", "Z"))),
        ],
        "slot_generation": {
            "version": "rim_slot_v5_symmetric_multistage",
            "orientation": rim_orientation,
            "socket_mode": socket_mode,
            "profile_symmetry": "mirror_y",
            "is_mirror_symmetric": True,
            "stage_count": int(params.get("rim_slot_stage_count", 3)),
            "stage_stations": sm.get("stage_stations", []),
            "exposes_lobes_on_od": False,
            "profile_max_x_mm": float(sm.get("max_x_mm", 0.0)),
            "profile_min_x_mm": float(sm.get("min_x_mm", 0.0)),
            "outer_radius_mm": float(sm.get("outer_radius_mm", r_outer)),
            "opens_front_face": bool(sm.get("opens_front_face", False)),
            "opens_back_face": bool(sm.get("opens_back_face", False)),
            "opens_outer_diameter": bool(sm.get("opens_outer_diameter", False)),
            "z_min_mm": float(sm.get("z_min_mm", 0.0)),
            "z_max_mm": float(sm.get("z_max_mm", 0.0)),
            "rim_z_min_mm": float(sm.get("rim_z_min_mm", 0.0)) if sm else float(axial_zones.get("rim_z_min_mm", 0.0)),
            "rim_z_max_mm": float(sm.get("rim_z_max_mm", 0.0)) if sm else float(axial_zones.get("rim_z_max_mm", 0.0)),
            "through_clearance_mm": _get_float(params, "rim_slot_through_clearance_mm"),
        },
        "rim_features": {
            "slot_count": rim_count,
            "slot_style": str(params.get("rim_slot_style", "none")),
            "slot_orientation": rim_orientation,
            "socket_mode": socket_mode,
            "stage_count": int(params.get("rim_slot_stage_count", 3)),
            "mouth_width_mm": _get_float(params, "rim_slot_mouth_width_mm"),
            "throat_width_mm": _get_float(params, "rim_slot_throat_width_mm"),
            "stage_neck_width_mm": _get_float(params, "rim_slot_stage_neck_width_mm"),
            "stage_lobe_width_mm": _get_float(params, "rim_slot_stage_lobe_width_mm"),
            "root_width_mm": _get_float(params, "rim_slot_root_width_mm"),
            "slot_profile_points_xy": sm.get("slot_profile_points_xy", []),
            "stage_stations": sm.get("stage_stations", []),
            "reference_only": True,
        },
        "visual_fidelity": {
            "target": "reference_turbine_rotor_disk",
            "contains_cyclic_rim_slots": rim_count > 0,
            "contains_symmetric_fir_tree_slots": rim_count > 0 and socket_mode == "internal_lobes",
            "contains_multistage_sidewall_grooves": rim_count > 0 and int(params.get("rim_slot_stage_count", 3)) >= 2,
            "contains_hub_sleeve": _get_float(params, "front_hub_sleeve_height_mm") > 0
                                    or _get_float(params, "rear_hub_sleeve_height_mm") > 0,
            "contains_annular_details": _get_bool(params, "enable_annular_details", default=True),
            "contains_coverplate_interface": int(params.get("coverplate_bolt_count", 0)) > 0,
            "contains_real_blade_attachment": False,
        },
        "hub_sleeve": {
            "front_enabled": _get_float(params, "front_hub_sleeve_height_mm") > 0,
            "rear_enabled": _get_float(params, "rear_hub_sleeve_height_mm") > 0,
            "front_outer_dia_mm": _get_float(params, "front_hub_sleeve_outer_dia_mm"),
            "front_inner_dia_mm": _get_float(params, "front_hub_sleeve_inner_dia_mm"),
            "front_height_mm": _get_float(params, "front_hub_sleeve_height_mm"),
        },
        "annular_details": {
            "enabled": _get_bool(params, "enable_annular_details", default=True),
            "mid_web_recess": _get_float(params, "mid_web_recess_depth_mm") > 0,
            "outer_rim_recess": _get_float(params, "outer_rim_recess_depth_mm") > 0,
            "seal_lands": int(params.get("seal_land_count", 0)),
        },
        "safety": {
            "non_flight_reference_only": True,
            "not_for_manufacturing": True,
            "not_airworthy": True,
            "not_certified": True,
            "not_for_installation": True,
            "no_structural_validation": True,
            "no_life_prediction": True,
        },
    }


# -- Main entry --
def build_axisymmetric_turbine_disk_cadquery(params: dict):
    import cadquery as cq

    # 1. Build base body
    result, profile_points, axial_zones = _build_base_body(cq, params)

    # 2. Add sleeves
    result = _add_front_hub_sleeve(cq, result, params)
    result = _add_rear_hub_sleeve(cq, result, params)

    # 3. Add annular details
    result = _add_annular_details(cq, result, params)

    # 4. Cut legacy hole rings
    result = _cut_hole_ring(result,
        count=_get_int(params, "bolt_hole_count"),
        pcd_mm=_get_float(params, "bolt_pcd_mm"),
        hole_dia_mm=_get_float(params, "bolt_hole_dia_mm"),
        axis=str(params.get("bolt_hole_axis", "Z")))
    result = _cut_hole_ring(result,
        count=_get_int(params, "lightening_hole_count"),
        pcd_mm=_get_float(params, "lightening_hole_pcd_mm"),
        hole_dia_mm=_get_float(params, "lightening_hole_dia_mm"),
        axis=str(params.get("lightening_hole_axis", "Z")))
    result = _cut_hole_ring(result,
        count=_get_int(params, "cooling_hole_count"),
        pcd_mm=_get_float(params, "cooling_hole_pcd_mm"),
        hole_dia_mm=_get_float(params, "cooling_hole_dia_mm"),
        axis=str(params.get("cooling_hole_axis", "Z")))

    # 5. Coverplate bolt ring
    result = _cut_coverplate_bolt_ring(result, params)

    # 6. Balance hole ring
    result = _cut_balance_hole_ring(result, params)

    # 7. Rim slots (axial_through, internal_lobes socket mode)
    result, slot_metadata = _cut_rim_slots(cq, result, params, axial_zones)

    # 8. Build metadata
    warnings: list[str] = [
        "axisymmetric_turbine_disk is non-flight reference geometry only.",
        "Not airworthy, not certified, not manufacturing-ready.",
        "Not for installation.",
        "Rim slots are visual/reference internal-lobe socket features only.",
        "They are not certified blade attachment geometry.",
        "No contact stress, centrifugal load path, fatigue life, burst margin, or thermal validation is performed.",
    ]

    metadata = _build_metadata(params, profile_points, axial_zones, slot_metadata, warnings)

    return result, metadata
