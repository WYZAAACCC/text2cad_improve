"""数据集第三梯队：Gen 3 种描述样式 + SER 七步标注（独立后处理，不碰主流程/src）。

对每个有效模型（源任务目录）从 IR 实测参数生成 3 种自然语言描述
（cn_param 中文简洁参数化 / cn_semantic 中文工程语义 / en_mixed 英文混合）
并配套论文 SER 七步标注，落盘 output/<task_id>/descriptions.json。

用法:
  .conda/python.exe _param_experiment/run_descriptions.py --only verify_br_c735fc40
  .conda/python.exe _param_experiment/run_descriptions.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import run_enrich  # noqa: E402

CORE_SUBSET = ["check_solid_validity", "check_degenerate_geometry",
               "validate_slot_step_roundtrip", "check_slot_pitch_and_ligament",
               "check_adjacent_feature_clearance", "validate_slot_pattern_periodicity"]


def _num(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return round(v, 3) if isinstance(v, float) else v


def _f(v, unit="mm"):
    return None if v is None else f"{_num(v)}{unit}"


def _params(agg: dict) -> dict:
    return {k: agg.get(k) for k in (
        "outer_diameter_mm", "bore_diameter_mm", "axial_thickness_mm",
        "hub_half_thickness_mm", "rim_half_thickness_mm", "count", "teeth_count",
        "distribution_radius_mm", "slot_depth_mm", "throat_half_width_mm",
        "root_fillet_mm")}


# ── 3 种描述（确定性模板，IR 实测参数，None 参数省略）────────────────────
def _cn_param(p: dict) -> str:
    parts = ["生成一个高压涡轮盘参考几何：轮毂-腹板-轮缘盘体"]
    if p["outer_diameter_mm"] is not None:
        parts.append(f"外径{_num(p['outer_diameter_mm'])}mm")
    if p["bore_diameter_mm"] is not None:
        parts.append(f"中心孔直径{_num(p['bore_diameter_mm'])}mm")
    if p["axial_thickness_mm"] is not None:
        parts.append(f"轴向最大厚度{_num(p['axial_thickness_mm'])}mm")
    if p["hub_half_thickness_mm"] is not None:
        parts.append(f"轮毂半厚{_num(p['hub_half_thickness_mm'])}mm")
    if p["rim_half_thickness_mm"] is not None:
        parts.append(f"轮缘半厚{_num(p['rim_half_thickness_mm'])}mm")
    if p["count"] is not None and p["teeth_count"] is not None:
        parts.append(f"轮缘上{_num(p['count'])}个{_num(p['teeth_count'])}齿枞树形榫槽")
    if p["distribution_radius_mm"] is not None:
        parts.append(f"分布半径{_num(p['distribution_radius_mm'])}mm")
    if p["slot_depth_mm"] is not None:
        parts.append(f"槽深{_num(p['slot_depth_mm'])}mm")
    if p["throat_half_width_mm"] is not None:
        parts.append(f"喉部半宽{_num(p['throat_half_width_mm'])}mm")
    if p["root_fillet_mm"] is not None:
        parts.append(f"齿根圆角{_num(p['root_fillet_mm'])}mm")
    return "，".join(parts) + "。参考几何，非适航件。"


def _cn_semantic(p: dict, disk: str) -> str:
    # 工程语义 + 参数化清晰（措辞对齐 _text 正则，提高 LLM 参数遵循率）
    parts = [f"本设计为{disk}，采用轮毂-腹板-轮缘子午轮廓结构"]
    if p["outer_diameter_mm"] is not None:
        s = f"外径{_num(p['outer_diameter_mm'])}mm"
        if p["bore_diameter_mm"] is not None:
            s += f"，中心孔直径{_num(p['bore_diameter_mm'])}mm"
        if p["axial_thickness_mm"] is not None:
            s += f"，轴向最大厚度{_num(p['axial_thickness_mm'])}mm"
        parts.append(s)
    if p["hub_half_thickness_mm"] is not None:
        s = f"轮毂半厚{_num(p['hub_half_thickness_mm'])}mm"
        if p["rim_half_thickness_mm"] is not None:
            s += f"，轮缘半厚{_num(p['rim_half_thickness_mm'])}mm"
        parts.append(s)
    if p["count"] is not None and p["teeth_count"] is not None:
        s = f"轮缘上{_num(p['count'])}个{_num(p['teeth_count'])}齿枞树形榫槽（楔形齿面，承受叶片离心载荷）"
        if p["distribution_radius_mm"] is not None:
            s += f"，分布半径{_num(p['distribution_radius_mm'])}mm"
        parts.append(s)
    if p["slot_depth_mm"] is not None:
        s = f"榫槽槽深{_num(p['slot_depth_mm'])}mm"
        if p["throat_half_width_mm"] is not None:
            s += f"，喉部半宽{_num(p['throat_half_width_mm'])}mm"
        parts.append(s)
    if p["root_fillet_mm"] is not None:
        parts.append(f"齿根圆角{_num(p['root_fillet_mm'])}mm以降低应力集中")
    return "。".join(parts) + "。"


def _en_mixed(p: dict) -> str:
    # 英文骨架 + 中文参数（中英混合，提高 LLM 参数遵循率）
    parts = ["Generate a high-pressure turbine disk with hub-web-rim body"]
    if p["outer_diameter_mm"] is not None:
        parts.append(f"outer diameter {_num(p['outer_diameter_mm'])} mm（外径{_num(p['outer_diameter_mm'])}mm）")
    if p["bore_diameter_mm"] is not None:
        parts.append(f"bore diameter {_num(p['bore_diameter_mm'])} mm（中心孔直径{_num(p['bore_diameter_mm'])}mm）")
    if p["axial_thickness_mm"] is not None:
        parts.append(f"axial thickness {_num(p['axial_thickness_mm'])} mm（轴向最大厚度{_num(p['axial_thickness_mm'])}mm）")
    if p["count"] is not None and p["teeth_count"] is not None:
        parts.append(f"{_num(p['count'])} fir-tree slots ({_num(p['teeth_count'])} teeth)（轮缘上{_num(p['count'])}个{_num(p['teeth_count'])}齿枞树形榫槽）")
    if p["distribution_radius_mm"] is not None:
        parts.append(f"pitch radius {_num(p['distribution_radius_mm'])} mm（分布半径{_num(p['distribution_radius_mm'])}mm）")
    if p["slot_depth_mm"] is not None:
        parts.append(f"slot depth {_num(p['slot_depth_mm'])} mm（槽深{_num(p['slot_depth_mm'])}mm）")
    if p["throat_half_width_mm"] is not None:
        parts.append(f"throat half-width {_num(p['throat_half_width_mm'])} mm（喉部半宽{_num(p['throat_half_width_mm'])}mm）")
    if p["root_fillet_mm"] is not None:
        parts.append(f"root fillet {_num(p['root_fillet_mm'])} mm（齿根圆角{_num(p['root_fillet_mm'])}mm）")
    return ", ".join(parts) + "."


# ── SER 七步（确定性，测量/IR 驱动）──────────────────────────────────────
def _disk_type(ir: dict) -> dict:
    ops = {n.get("op") for n in ir.get("nodes", [])}
    has_slot = "extrude_profile" in ops and "circular_pattern_component" in ops
    has_hole = "cut_circular_hole_pattern" in ops
    has_groove = "cut_annular_groove" in ops or "cut_rim_slot_pattern" in ops
    if has_slot and (has_hole or has_groove):
        return {"disk_type": "榫槽-孔阵列-环槽耦合盘", "en": "coupled_slot_hole_groove_disk"}
    if has_slot:
        return {"disk_type": "标准枞树形榫槽盘", "en": "standard_fir_tree_slot_disk"}
    if has_hole or has_groove or "cut_center_bore" in ops:
        return {"disk_type": "中心孔-孔阵列-环槽盘", "en": "bore_hole_groove_disk"}
    return {"disk_type": "基础轮毂-腹板-轮缘盘", "en": "basic_hub_web_rim_disk"}


def _ser_step4(ir: dict) -> dict:
    ops = {n.get("op") for n in ir.get("nodes", [])}
    return {
        "center_bore": "present(cut_center_bore)" if "cut_center_bore" in ops else "none(in-revolve-profile)",
        "hole_array": "present" if "cut_circular_hole_pattern" in ops else "none",
        "annular_groove": "present" if ("cut_annular_groove" in ops or "cut_rim_slot_pattern" in ops) else "none",
        "fir_tree_slots": "present" if "extrude_profile" in ops else "none",
        "slot_array": "present" if "circular_pattern_component" in ops else "none",
        "fillet_features": sum(1 for n in ir.get("nodes", []) if n.get("op") == "fillet_sketch"),
        "boolean_cut": "present" if "boolean_cut" in ops else "none",
    }


def run_one(tid: str) -> dict | None:
    base = OUTPUT / tid
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        return None
    ir = json.loads(raw_path.read_text(encoding="utf-8"))
    agg = run_enrich._measure_all(str(base))
    p = _params(agg)

    dt = _disk_type(ir)
    descs = [
        {"style": "cn_param", "text": _cn_param(p), "source": "ir-measured"},
        {"style": "cn_semantic", "text": _cn_semantic(p, dt["disk_type"]), "source": "ir-measured"},
        {"style": "en_mixed", "text": _en_mixed(p), "source": "ir-measured"},
    ]

    ser = {
        "step1_disk_type": dt,
        "step2_params": {k: v for k, v in p.items() if v is not None},
        "step3_meridional_profile": {k: v for k, v in agg.items() if k in (
            "outer_radius_mm", "bore_radius_mm", "axial_thickness_mm",
            "hub_half_thickness_mm", "rim_half_thickness_mm", "web_half_thickness_mm")},
        "step4_feature_decomposition": _ser_step4(ir),
        "step5_slot_profile": {k: v for k, v in agg.items() if k in (
            "teeth_count", "slot_depth_mm", "throat_half_width_mm", "flank_angle_deg",
            "max_half_width_mm", "root_fillet_mm", "count", "distribution_radius_mm",
            "circumferential_pitch_mm", "min_ligament_mm")},
        "step6_constraints": {k: v for k, v in agg.items() if k in (
            "ok", "pitch_mm", "slot_max_tangential_width_mm", "min_ligament_mm",
            "rim_thickness_mm", "bottom_ligament_mm")},
        "step7_feature_graph": {
            "canonical_ir": "canonical_ir.json",
            "nodes": len(ir.get("nodes", [])),
            "components": len(ir.get("components", [])),
            "postcheck_requirements": CORE_SUBSET,
        },
    }

    inh = {"design_id": None, "model_id": None, "param_template_id": None}
    try:
        d = json.loads((base / "dataset_enrich.json").read_text(encoding="utf-8"))
        inh = {"design_id": d.get("design_id"), "model_id": d.get("model_id"),
               "param_template_id": d.get("param_template_id")}
    except Exception:  # noqa: BLE001
        pass

    doc = {"task_id": tid, "schema": "descriptions_v1", **inh,
           "descriptions": descs, "ser": ser,
           "timestamp": datetime.now().isoformat(timespec="seconds")}
    (base / "descriptions.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gen 3 种描述样式 + SER 七步标注")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    args = ap.parse_args(argv)

    tasks = ([args.only] if args.only
             else sorted(p.name for p in OUTPUT.iterdir()
                         if p.is_dir() and (p / "raw_fixed.json").exists()))
    if not tasks:
        print("没有任务目录")
        return 1

    done = 0
    for tid in tasks:
        try:
            doc = run_one(tid)
            if doc:
                done += 1
                print(f"- {tid}  OK  3 desc + SER  design={doc['design_id'] and doc['design_id'][:10]}")
        except Exception as exc:  # noqa: BLE001
            print(f"- {tid}  FAIL  {exc}")
    print(f"DONE  {done} descriptions -> output/<task>/descriptions.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
