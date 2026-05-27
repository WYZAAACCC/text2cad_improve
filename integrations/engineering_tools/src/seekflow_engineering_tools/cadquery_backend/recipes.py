"""CadQuery recipe generators — translate recipe params into Python code."""

from __future__ import annotations


def cadquery_box(params: dict) -> str:
    return f"""result = (
    cq.Workplane("XY")
    .box({params["length_mm"]}, {params["width_mm"]}, {params["height_mm"]})
)"""


def cadquery_cylinder(params: dict) -> str:
    return f"""result = (
    cq.Workplane("XY")
    .circle({params["diameter_mm"]} / 2.0)
    .extrude({params["height_mm"]})
)"""


def cadquery_block_with_hole(params: dict) -> str:
    hx = params.get("hole_x_mm", params["length_mm"] / 2.0)
    hz = params.get("hole_z_mm", params["width_mm"] / 2.0)
    return f"""result = (
    cq.Workplane("XY")
    .box({params["length_mm"]}, {params["width_mm"]}, {params["height_mm"]})
    .faces(">Z").workplane()
    .center({hx} - {params["length_mm"]} / 2.0, {hz} - {params["width_mm"]} / 2.0)
    .hole({params["hole_dia_mm"]})
)"""


def cadquery_l_bracket(params: dict) -> str:
    """L-bracket: horizontal base + vertical leg, united via union()."""
    bl = params["base_length_mm"]
    bw = params["base_width_mm"]
    t = params["thickness_mm"]
    lh = params["leg_height_mm"]
    return f"""base = (
    cq.Workplane("XY")
    .box({bl}, {bw}, {t})
)
leg = (
    cq.Workplane("XY")
    .transformed(offset=(0, 0, 0))
    .box({t}, {bw}, {lh})
)
result = base.union(leg)"""


def cadquery_stepped_block(params: dict) -> str:
    bl = params["base_length_mm"]
    bw = params["base_width_mm"]
    bh = params["base_height_mm"]
    tl = params["top_length_mm"]
    tw = params["top_width_mm"]
    th = params["top_height_mm"]
    return f"""base = (
    cq.Workplane("XY")
    .box({bl}, {bw}, {bh})
)
result = (
    base.faces(">Z").workplane()
    .center(0, 0)
    .rect({tl}, {tw})
    .extrude({th})
)"""


def cadquery_flanged_hub(params: dict) -> str:
    fd = params["flange_dia_mm"]
    ft = params["flange_thickness_mm"]
    hd = params["hub_dia_mm"]
    hh = params["hub_height_mm"]
    bd = params["bore_dia_mm"]
    pcd = params["bolt_pcd_mm"]
    bolt_d = params["bolt_dia_mm"]
    bc = params["bolt_count"]

    return f"""flange = (
    cq.Workplane("XY")
    .circle({fd} / 2.0)
    .extrude({ft})
)
hub = (
    flange.faces(">Z").workplane()
    .circle({hd} / 2.0)
    .extrude({hh})
)
bored = (
    hub.faces(">Z").workplane()
    .hole({bd})
)
result = (
    bored.faces(">Z").workplane()
    .polarArray({pcd} / 2.0, 0, 360, {bc})
    .hole({bolt_d})
)"""


def cadquery_spur_gear(params: dict) -> str:
    m = params["module_mm"]
    z = params["teeth"]
    fw = params["face_width_mm"]
    bd = params["bore_dia_mm"]
    pitch_r = m * z / 2.0
    outer_r = pitch_r + m
    root_r = pitch_r - 1.25 * m

    return f"""import math
pitch_r = {pitch_r}
outer_r = {outer_r}
root_r = {root_r}
z = {z}
pts = []
for i in range(z):
    c = 2.0 * math.pi * i / z
    pts.append((outer_r * math.cos(c), outer_r * math.sin(c)))
    pts.append((root_r * math.cos(c + math.pi/z), root_r * math.sin(c + math.pi/z)))
pts.append(pts[0])
gear = (
    cq.Workplane("XY")
    .polyline(pts).close()
    .extrude({fw})
)
result = (
    gear.faces(">Z").workplane()
    .hole({bd})
)"""


def cadquery_shaft_basic(params: dict) -> str:
    return f"""result = (
    cq.Workplane("XY")
    .circle({params["shaft_dia_mm"]} / 2.0)
    .extrude({params["total_length_mm"]})
)"""


def cadquery_shaft_with_keyway(params: dict) -> str:
    kw = params["keyway_width_mm"]
    kd = params["keyway_depth_mm"]
    offset = params.get("keyway_offset_from_end_mm", 0)
    return f"""result = (
    cq.Workplane("XY")
    .circle({params["shaft_dia_mm"]} / 2.0)
    .extrude({params["total_length_mm"]})
)
result = (
    result.faces(">Z").workplane(offset={offset})
    .center(0, -{params["shaft_dia_mm"]} / 2.0 + {kd})
    .rect({kw}, {kd} * 2)
    .cutBlind(-{kd})
)"""


CADQUERY_RECIPE_GENERATORS = {
    "box": cadquery_box,
    "cylinder": cadquery_cylinder,
    "block_with_hole": cadquery_block_with_hole,
    "l_bracket": cadquery_l_bracket,
    "stepped_block": cadquery_stepped_block,
    "flanged_hub": cadquery_flanged_hub,
    "spur_gear": cadquery_spur_gear,
    "spur_gear_visual_legacy": cadquery_spur_gear,
    "shaft_basic": cadquery_shaft_basic,
    "shaft_with_keyway": cadquery_shaft_with_keyway,
}

# ── Golden test data: expected bbox and body_count per recipe (default params) ──

GOLDEN_DATA: dict[str, dict] = {
    "box": {
        "defaults": {"length_mm": 100, "width_mm": 50, "height_mm": 25},
        "expected_bbox_mm": [100, 50, 25],
        "expected_body_count": 1,
    },
    "cylinder": {
        "defaults": {"diameter_mm": 20, "height_mm": 50},
        "expected_bbox_mm": [20, 20, 50],
        "expected_body_count": 1,
    },
    "block_with_hole": {
        "defaults": {"length_mm": 100, "width_mm": 50, "height_mm": 25, "hole_dia_mm": 16},
        "expected_body_count": 1,
    },
    "l_bracket": {
        "defaults": {"base_length_mm": 100, "base_width_mm": 60, "thickness_mm": 15, "leg_height_mm": 60},
        "expected_body_count": 1,
    },
    "stepped_block": {
        "defaults": {"base_length_mm": 80, "base_width_mm": 80, "base_height_mm": 20, "top_length_mm": 60, "top_width_mm": 60, "top_height_mm": 30},
        "expected_body_count": 1,
    },
    "flanged_hub": {
        "defaults": {"flange_dia_mm": 80, "flange_thickness_mm": 10, "hub_dia_mm": 40, "hub_height_mm": 30, "bore_dia_mm": 20, "bolt_pcd_mm": 60, "bolt_dia_mm": 8, "bolt_count": 4},
        "expected_body_count": 1,
        "expected_through_hole_count": 5,
    },
    "spur_gear": {
        "defaults": {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15},
        "expected_body_count": 1,
    },
    "spur_gear_visual_legacy": {
        "defaults": {"module_mm": 3, "teeth": 20, "face_width_mm": 20, "bore_dia_mm": 15},
        "expected_body_count": 1,
    },
    "shaft_basic": {
        "defaults": {"shaft_dia_mm": 20, "total_length_mm": 100},
        "expected_bbox_mm": [20, 20, 100],
        "expected_body_count": 1,
    },
    "shaft_with_keyway": {
        "defaults": {"shaft_dia_mm": 20, "total_length_mm": 100, "keyway_width_mm": 6, "keyway_depth_mm": 4},
        "expected_body_count": 1,
    },
}
