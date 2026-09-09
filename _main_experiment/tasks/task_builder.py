"""Deterministic 40-task builder for the main benchmark.

The builder uses the existing design families and parameter templates, so the
experiment never depends on LLM output to construct its own task set.
"""

from __future__ import annotations

from typing import Any

from ..adapters import load_design_families
from ..config import ExperimentConfig
from ..paths import task_gold_dir
from ..schemas import (
    DifficultyLevel,
    GoldReference,
    KeyDimension,
    SlotReference,
    TaskSpec,
    TaskType,
)

_FEATURE_KEY_MAP = {
    "R": "R_mm",
    "depth": "depth_mm",
    "throat": "throat_half_width_mm",
    "fr": "fr_mm",
    "pcd": "pcd_mm",
    "hdia": "hdia_mm",
    "gw": "gw_mm",
    "gd": "gd_mm",
    "lh_pcd": "lh_pcd_mm",
    "lh_hdia": "lh_hdia_mm",
    "cl_pcd": "cl_pcd_mm",
    "cl_hdia": "cl_hdia_mm",
    "cl_pcd2": "cl_pcd2_mm",
    "rs_depth": "rs_depth_mm",
    "rs_half_width": "rs_half_width_mm",
    "cavity_width": "cavity_width_mm",
    "cavity_depth": "cavity_depth_mm",
    "rim_arc_radius": "rim_arc_radius_mm",
}


def _family_params(family_id: str) -> dict[str, Any]:
    families = load_design_families()
    fam = families[family_id]
    params: dict[str, Any] = {
        "category": fam["category"],
        "form": fam.get("form", "standard"),
        "od_mm": fam["od"],
        "bore_mm": fam["bore"],
        "thick_mm": fam["thick"],
        "hub_mm": fam["hub"],
        "rim_mm": fam["rim"],
    }
    features = fam.get("features") or {}
    for key, value in features.items():
        mapped = _FEATURE_KEY_MAP.get(key, key)
        params[mapped] = value
    if "transition" in features:
        params["transition"] = features["transition"]
    return params


def _prompt(params: dict[str, Any], *, edit: bool = False) -> str:
    verb = "修改后的" if edit else ""
    form_label = {"thin_web": "薄腹板", "thick_rim": "厚轮缘",
                  "large_hub": "大轮毂", "conical": "锥形腹板"}.get(
        params.get("form"), "")
    parts = [f"生成一个{form_label}{verb}高压涡轮盘参考几何"]
    if params.get("od_mm"):
        parts.append(f"外径{params['od_mm']}mm")
    if params.get("bore_mm"):
        parts.append(f"中心孔直径{params['bore_mm']}mm")
    if params.get("thick_mm"):
        parts.append(f"轴向最大厚度{params['thick_mm']}mm")
    if params.get("hub_mm"):
        parts.append(f"轮毂半厚{params['hub_mm']}mm")
    if params.get("rim_mm"):
        parts.append(f"轮缘半厚{params['rim_mm']}mm")
    if params.get("slots"):
        parts.append(
            f"轮缘上{params['slots']}个{params.get('teeth', 2)}齿枞树形榫槽，"
            f"槽深{params.get('depth_mm', 24)}mm，"
            f"喉部半宽{params.get('throat_half_width_mm', 4)}mm"
        )
    if params.get("holes"):
        parts.append(
            f"周向均布{params['holes']}个安装孔，孔径{params.get('hdia_mm', 14)}mm，"
            f"分布半径{params.get('pcd_mm', 180)}mm"
        )
    if params.get("grooves"):
        parts.append(
            f"轮缘内侧{params['grooves']}道环槽，槽宽{params.get('gw_mm', 10)}mm，"
            f"槽深{params.get('gd_mm', 12)}mm"
        )
    if params.get("rim_arc_radius_mm"):
        tr_label = {"s_curve": "S形曲线", "ellipse": "椭圆弧", "power": "幂函数曲线",
                    "arc_out": "外凸圆弧", "arc_in": "内凹圆弧"}.get(
            params.get("transition"), "曲线")
        parts.append(
            f"轮缘与腹板交界采用{tr_label}过渡，过渡幅度{params['rim_arc_radius_mm']}mm")
    if edit:
        parts.append("保持原有主体结构，仅调整上述参数")
    return "，".join(parts) + "。参考几何，非适航件。"


def _blueprints() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(level: DifficultyLevel, source: str, overrides: dict[str, Any], task_type: TaskType):
        params = _family_params(source)
        params.update(overrides)
        out.append({
            "level": level,
            "task_type": task_type,
            "family_id": source,
            "params": params,
            "prompt": _prompt(params, edit=task_type == TaskType.EDIT),
            "description": f"{level.value} {source} {task_type.value}",
        })

    # Level 1: 8 basic hub-web-rim tasks, first 2 are edit tasks.
    basic = [
        (DifficultyLevel.L1, "D04", {"form": "standard", "od_mm": 500, "bore_mm": 120, "thick_mm": 76, "hub_mm": 38, "rim_mm": 30}),
        (DifficultyLevel.L1, "D04", {"form": "thin_web", "od_mm": 460, "bore_mm": 110, "thick_mm": 70, "hub_mm": 36, "rim_mm": 28}),
        (DifficultyLevel.L1, "D04", {"form": "thick_rim", "od_mm": 600, "bore_mm": 150, "thick_mm": 90, "hub_mm": 45, "rim_mm": 38}),
        (DifficultyLevel.L1, "D04", {"form": "large_hub", "od_mm": 700, "bore_mm": 180, "thick_mm": 110, "hub_mm": 52, "rim_mm": 44}),
        (DifficultyLevel.L1, "D04", {"form": "conical", "od_mm": 520, "bore_mm": 120, "thick_mm": 76, "hub_mm": 38, "rim_mm": 30}),
        (DifficultyLevel.L1, "D04", {"form": "standard", "od_mm": 540, "bore_mm": 120, "thick_mm": 76, "hub_mm": 38, "rim_mm": 30}),
        (DifficultyLevel.L1, "D04", {"form": "thin_web", "od_mm": 620, "bore_mm": 150, "thick_mm": 90, "hub_mm": 45, "rim_mm": 38}),
        (DifficultyLevel.L1, "D04", {"form": "large_hub", "od_mm": 480, "bore_mm": 110, "thick_mm": 70, "hub_mm": 36, "rim_mm": 28}),
    ]
    for i, (level, source, overrides) in enumerate(basic):
        task_type = TaskType.EDIT if i < 2 else TaskType.GENERATION
        add(level, source, overrides, task_type)

    # Level 2: 10 hole/groove tasks, first 2 are edit tasks.
    hole_groove = [
        (DifficultyLevel.L2, "D09", {"holes": 16, "pcd_mm": 210, "hdia_mm": 14}),
        (DifficultyLevel.L2, "D09", {"holes": 24, "pcd_mm": 220, "hdia_mm": 12}),
        (DifficultyLevel.L2, "D09", {"holes": 30, "pcd_mm": 230, "hdia_mm": 10}),
        (DifficultyLevel.L2, "D09", {"holes": 20, "pcd_mm": 216, "hdia_mm": 18}),
        (DifficultyLevel.L2, "D14", {"grooves": 1, "gw_mm": 10, "gd_mm": 14}),
        (DifficultyLevel.L2, "D14", {"grooves": 2, "gw_mm": 8, "gd_mm": 12}),
        (DifficultyLevel.L2, "D14", {"grooves": 1, "gw_mm": 12, "gd_mm": 16}),
        (DifficultyLevel.L2, "D14", {"grooves": 2, "gw_mm": 10, "gd_mm": 13}),
        (DifficultyLevel.L2, "D09", {"holes": 12, "pcd_mm": 200, "hdia_mm": 16}),
        (DifficultyLevel.L2, "D14", {"grooves": 1, "gw_mm": 9, "gd_mm": 15}),
    ]
    for i, (level, source, overrides) in enumerate(hole_groove):
        task_type = TaskType.EDIT if i < 2 else TaskType.GENERATION
        add(level, source, overrides, task_type)

    # Level 3: 12 slot/coupled tasks, first 2 are edit tasks.
    slot_coupled = [
        (DifficultyLevel.L3, "D21", {"slots": 60, "teeth": 2, "depth_mm": 24, "throat_half_width_mm": 5.0, "fr_mm": 1.2}),
        (DifficultyLevel.L3, "D21", {"slots": 72, "teeth": 3, "depth_mm": 28, "throat_half_width_mm": 5.5, "fr_mm": 1.0}),
        (DifficultyLevel.L3, "D21", {"slots": 84, "teeth": 3, "depth_mm": 30, "throat_half_width_mm": 6.0, "fr_mm": 1.1}),
        (DifficultyLevel.L3, "D22", {"slots": 60, "teeth": 2, "depth_mm": 26, "throat_half_width_mm": 5.0, "fr_mm": 1.0}),
        (DifficultyLevel.L3, "D22", {"slots": 72, "teeth": 3, "depth_mm": 30, "throat_half_width_mm": 6.0, "fr_mm": 1.0}),
        (DifficultyLevel.L3, "D28", {"slots": 48, "teeth": 2, "depth_mm": 24, "throat_half_width_mm": 5.0, "fr_mm": 1.0,
                                     # pcd=205：孔外缘(212)留在 rim_junc(215) 内，避免 OCC 重合面布尔细缝
                                     "holes": 16, "pcd_mm": 205, "hdia_mm": 14, "grooves": 1, "gw_mm": 8, "gd_mm": 10}),
        (DifficultyLevel.L3, "D28", {"slots": 60, "teeth": 3, "depth_mm": 28, "throat_half_width_mm": 6.0, "fr_mm": 1.0,
                                     "holes": 20, "pcd_mm": 220, "hdia_mm": 12, "grooves": 2, "gw_mm": 8, "gd_mm": 10}),
        (DifficultyLevel.L3, "D28", {"slots": 72, "teeth": 3, "depth_mm": 32, "throat_half_width_mm": 6.5, "fr_mm": 1.0,
                                     "holes": 24, "pcd_mm": 230, "hdia_mm": 10, "grooves": 1, "gw_mm": 10, "gd_mm": 12}),
        (DifficultyLevel.L3, "D21", {"slots": 90, "teeth": 3, "depth_mm": 34, "throat_half_width_mm": 6.0, "fr_mm": 1.0}),
        (DifficultyLevel.L3, "D22", {"slots": 84, "teeth": 3, "depth_mm": 32, "throat_half_width_mm": 6.0, "fr_mm": 1.0}),
        (DifficultyLevel.L3, "D28", {"slots": 60, "teeth": 2, "depth_mm": 26, "throat_half_width_mm": 5.5, "fr_mm": 1.0,
                                     "holes": 16, "pcd_mm": 215, "hdia_mm": 14, "grooves": 2, "gw_mm": 9, "gd_mm": 11}),
        (DifficultyLevel.L3, "D28", {"slots": 72, "teeth": 3, "depth_mm": 30, "throat_half_width_mm": 6.0, "fr_mm": 1.2,
                                     "holes": 20, "pcd_mm": 225, "hdia_mm": 12, "grooves": 1, "gw_mm": 10, "gd_mm": 12}),
    ]
    for i, (level, source, overrides) in enumerate(slot_coupled):
        task_type = TaskType.EDIT if i < 2 else TaskType.GENERATION
        add(level, source, overrides, task_type)

    # Level 4: 10 unseen four-tooth / complex rim / boundary tasks, first 2 edit.
    hard = [
        (DifficultyLevel.L4, "D22", {"slots": 84, "teeth": 4, "depth_mm": 34, "throat_half_width_mm": 6.5, "fr_mm": 0.9}),
        (DifficultyLevel.L4, "D31", {"slots": 44, "teeth": 3, "depth_mm": 40, "throat_half_width_mm": 7.0, "fr_mm": 0.7,
                                     "rim_arc_radius_mm": 24, "transition": "ellipse"}),
        (DifficultyLevel.L4, "D31", {"slots": 48, "teeth": 4, "depth_mm": 42, "throat_half_width_mm": 7.5, "fr_mm": 0.8,
                                     "rim_arc_radius_mm": 26, "transition": "s_curve"}),
        (DifficultyLevel.L4, "D32", {"slots": 40, "teeth": 4, "depth_mm": 38, "throat_half_width_mm": 8.0, "fr_mm": 0.9,
                                     "rim_arc_radius_mm": 28, "transition": "power"}),
        (DifficultyLevel.L4, "D32", {"slots": 44, "teeth": 4, "depth_mm": 40, "throat_half_width_mm": 8.5, "fr_mm": 0.8,
                                     "rim_arc_radius_mm": 30, "transition": "arc_out"}),
        (DifficultyLevel.L4, "D28", {"slots": 72, "teeth": 4, "depth_mm": 34, "throat_half_width_mm": 7.0, "fr_mm": 0.8,
                                     "holes": 30, "pcd_mm": 240, "hdia_mm": 12, "grooves": 2, "gw_mm": 10, "gd_mm": 13}),
        (DifficultyLevel.L4, "D28", {"slots": 84, "teeth": 4, "depth_mm": 36, "throat_half_width_mm": 7.5, "fr_mm": 0.8,
                                     "holes": 36, "pcd_mm": 245, "hdia_mm": 10, "grooves": 2, "gw_mm": 8, "gd_mm": 12}),
        (DifficultyLevel.L4, "D22", {"slots": 96, "teeth": 4, "depth_mm": 36, "throat_half_width_mm": 7.0, "fr_mm": 0.8}),
        (DifficultyLevel.L4, "D31", {"slots": 52, "teeth": 4, "depth_mm": 44, "throat_half_width_mm": 8.0, "fr_mm": 0.7,
                                     "rim_arc_radius_mm": 30, "transition": "power"}),
        (DifficultyLevel.L4, "D32", {"slots": 48, "teeth": 4, "depth_mm": 42, "throat_half_width_mm": 8.0, "fr_mm": 0.8,
                                     "rim_arc_radius_mm": 30, "transition": "arc_in"}),
    ]
    for i, (level, source, overrides) in enumerate(hard):
        task_type = TaskType.EDIT if i < 2 else TaskType.GENERATION
        add(level, source, overrides, task_type)

    return out


def build_task_specs(config: ExperimentConfig) -> list[TaskSpec]:
    specs: list[TaskSpec] = []
    for index, blueprint in enumerate(_blueprints(), start=1):
        task_id = f"T{index:02d}"
        gold_dir = task_gold_dir(task_id, config)
        params = blueprint["params"]
        key_dims = [
            KeyDimension(name="outer_diameter_mm", expected_mm=float(params["od_mm"])),
            KeyDimension(name="bore_diameter_mm", expected_mm=float(params["bore_mm"])),
            KeyDimension(name="axial_thickness_mm", expected_mm=float(params["thick_mm"])),
        ]
        slot_ref = None
        if params.get("teeth") is not None:
            slot_ref = SlotReference(
                teeth_count=int(params["teeth"]),
                slot_depth_mm=float(params.get("depth_mm", 0.0)),
                throat_half_width_mm=float(params.get("throat_half_width_mm", 0.0)),
            )
        gold = GoldReference(
            fdg_path=gold_dir / "fdg.json",
            canonical_ir_path=gold_dir / "canonical_ir.json",
            step_path=gold_dir / "output.step",
            brep_path=gold_dir / "output.brep",
            key_dimensions=key_dims,
            slot_reference=slot_ref,
        )
        specs.append(TaskSpec(
            task_id=task_id,
            level=blueprint["level"],
            task_type=blueprint["task_type"],
            family_id=blueprint["family_id"],
            prompt=blueprint["prompt"],
            normalized_params=params,
            gold=gold,
            description=blueprint["description"],
        ))
    return specs
