"""数据集字段：④ 归一化参数 + 派生标记、⑦a ir_doc_hash、⑦b param_template_id。

独立后处理脚本（不碰主流程），批量扫描任务目录补字段，产出
output/<task_id>/dataset_enrich.json：
  - normalized_params：绝对尺寸 + 相对 Ro 归一化 + 派生标记（论文"同时保存绝对尺寸和
    相对于盘体外半径 Ro 的归一化参数"）
  - ir_doc_hash：Disk-G-CAD 文档哈希（参数符号化，V3 四层隔离哈希之一，结构去重用）
  - param_template_id：需求参数向量哈希（同一参数组合的语言改写共享 id）

复用 mcp_tools 测量函数 + validate_req_params.extract_requirements + RawGcadDocument
（全部只读 import，不碰 src）。

用法:
  .conda/python.exe _param_experiment/run_enrich.py --only mon_sweep_q2_slots_96
  .conda/python.exe _param_experiment/run_enrich.py        # 批量扫描
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
SERVER = ROOT / "app" / "text-to-cad" / "server"
OUTPUT = SERVER / "output"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from mcp_tools import (  # noqa: E402
    check_slot_depth_and_rim, check_slot_pitch_and_ligament,
    count_fir_tree_slots, measure_disc_dimensions, measure_fir_tree_slot_profile,
    measure_groove, measure_hole_pattern,
)
from validate_req_params import extract_requirements  # noqa: E402

# ⑦b 参数向量键（extract_requirements 的键，缺失补 None 抗漂移）。
# 覆盖主体 + 榫槽 + 孔 + 环槽 + 减重结构 + 轮缘过渡，使 6 类盘的
# param_template_id/design_id 正确区分（含 groove 减重结构 / complex_rim 圆弧过渡）。
PARAM_VECTOR_KEYS = ["outer_diameter_mm", "bore_diameter_mm", "axial_thickness_mm",
                     "hub_half_mm", "rim_half_mm",
                     "slots", "teeth_count", "slot_depth_mm",
                     "throat_half_width_mm", "root_fillet_mm",
                     "holes", "hdia_mm", "pcd_mm",
                     "grooves", "gw_mm", "gd_mm",
                     "lh_holes", "lh_hdia_mm", "lh_pcd_mm",
                     "cl_holes", "cl_hdia_mm", "cl_pcd_mm", "cl_pcd2_mm",
                     "rs_count", "rs_depth_mm",
                     "cavity_width_mm", "cavity_depth_mm",
                     "rim_arc_radius_mm"]

# ④ 归一化参数注册表：(key, label, is_derived, expression)
NORMALIZED_PARAMS = [
    ("outer_radius_mm", "外半径", False, None),
    ("outer_diameter_mm", "外径", True, "2·Ro"),
    ("bore_radius_mm", "中心孔半径", False, None),
    ("bore_diameter_mm", "中心孔直径", True, "2·Rbore"),
    ("axial_thickness_mm", "轴向厚度", False, None),
    ("hub_half_thickness_mm", "轮毂半厚", False, None),
    ("rim_half_thickness_mm", "轮缘半厚", False, None),
    ("web_half_thickness_mm", "腹板半厚", False, None),
    ("distribution_radius_mm", "榫槽分布半径", False, None),
    ("slot_depth_mm", "榫槽深度", False, None),
    ("throat_half_width_mm", "喉部半宽", False, None),
    ("max_half_width_mm", "最大半宽", False, None),
    ("root_fillet_mm", "齿根圆角", False, None),
    ("circumferential_pitch_mm", "周向节距", True, "2π·rs/Ns"),
    ("min_ligament_mm", "最小剩料", True, "(pitch−width)/2"),
    ("rim_thickness_mm", "轮缘厚度", True, "Ro−rim_inner"),
    ("bottom_ligament_mm", "槽底剩料", True, "rim−depth"),
    ("flank_angle_deg", "齿面角", True, "atan(dy/dx)"),
    ("count", "榫槽数量", False, None),
    ("holes", "孔数量", False, None),
    ("pcd_mm", "孔分布半径", False, None),
    ("hdia_mm", "孔径", False, None),
    ("grooves", "环槽数量", False, None),
    ("gw_mm", "环槽槽宽", False, None),
    ("gd_mm", "环槽槽深", False, None),
    ("teeth_count", "齿数", False, None),
    ("lh_holes", "减重孔数量", False, None),
    ("lh_pcd_mm", "减重孔分布半径", False, None),
    ("lh_hdia_mm", "减重孔径", False, None),
    ("cl_holes", "冷却孔数量", False, None),
    ("cl_pcd_mm", "冷却孔分布半径", False, None),
    ("cl_hdia_mm", "冷却孔径", False, None),
    ("rs_count", "径向切槽数量", False, None),
    ("rs_depth_mm", "切槽深度", False, None),
    ("cavity_width_mm", "环形腔宽", False, None),
    ("cavity_depth_mm", "环形腔深", False, None),
    ("rim_arc_radius_mm", "轮缘过渡半径", False, None),
]

# design_family 匹配注册表（G1-G5 期望参数向量；离散键精确、连续键 tol）
FAMILY_REGISTRY = [
    {"id": "G1", "expect": {"outer_diameter_mm": 500, "bore_diameter_mm": 120, "axial_thickness_mm": 76,
                            "slots": 60, "teeth_count": 2, "slot_depth_mm": 24,
                            "throat_half_width_mm": 4.0, "root_fillet_mm": 1.0}},
    {"id": "G2", "expect": {"outer_diameter_mm": 500, "bore_diameter_mm": 120, "axial_thickness_mm": 76,
                            "slots": 48, "teeth_count": 2, "slot_depth_mm": 28,
                            "throat_half_width_mm": 4.0, "root_fillet_mm": 1.0}},
    {"id": "G3", "expect": {"outer_diameter_mm": 460, "bore_diameter_mm": 110, "axial_thickness_mm": 70,
                            "slots": 60, "teeth_count": 2, "slot_depth_mm": 24,
                            "throat_half_width_mm": 3.5, "root_fillet_mm": 1.0}},
    {"id": "G4", "expect": {"outer_diameter_mm": 500, "bore_diameter_mm": 110, "axial_thickness_mm": 76,
                            "slots": 60, "teeth_count": 2, "slot_depth_mm": 24,
                            "throat_half_width_mm": 3.0, "root_fillet_mm": 1.5}},
    {"id": "G5", "expect": {"outer_diameter_mm": 500, "bore_diameter_mm": 120, "axial_thickness_mm": 76,
                            "slots": 60, "teeth_count": 3, "slot_depth_mm": 30,
                            "throat_half_width_mm": 4.0, "root_fillet_mm": 1.2}},
]
FAMILY_TOL = {"outer_diameter_mm": 5, "bore_diameter_mm": 5, "axial_thickness_mm": 3,
              "slot_depth_mm": 2, "throat_half_width_mm": 0.5, "root_fillet_mm": 0.3}


def _match_family(vec: dict) -> str:
    """参数向量匹配 design_family：要求 8 键齐全，离散键精确、连续键 tol 内。未命中 custom。"""
    if not vec:
        return "custom"
    for f in FAMILY_REGISTRY:
        exp = f["expect"]
        ok = True
        for k, ev in exp.items():
            v = vec.get(k)
            if v is None:
                ok = False
                break
            if k in ("slots", "teeth_count"):
                if int(v) != int(ev):
                    ok = False
                    break
            elif abs(float(v) - float(ev)) > FAMILY_TOL.get(k, 1.0):
                ok = False
                break
        if ok:
            return f["id"]
    return "custom"


def _json_hash(obj) -> str:
    """JSON 稳定哈希（同 ir/hashing.stable_hash 语义：sort_keys + default=str → sha256）。"""
    try:
        return "sha256:" + hashlib.sha256(
            json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()
    except Exception:
        return ""


def _symbolize(obj):
    """参数符号化：数值/字符串/bool 值替换为类型占位符，保留结构（dict 键、list 长度）。

    ir_doc_hash 用：同结构不同参数值 → 同 hash（模板一致性）；改结构（点数/节点数）→ 变。
    """
    if isinstance(obj, dict):
        return {k: _symbolize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_symbolize(v) for v in obj]
    if obj is None:
        return "NULL"
    if isinstance(obj, bool):
        return "BOOL"
    if isinstance(obj, (int, float)):
        return "NUM"
    if isinstance(obj, str):
        return "STR"
    return type(obj).__name__


def _ir_doc_hash(raw: dict) -> str:
    """Disk-G-CAD 文档哈希：model_dump → 节点 id 归一（抗 LLM 命名漂移）→ params 符号化 → stable_hash。

    - nodes 按 (component, dialect, op, op_version, 参数符号化 hash) 稳定排序，抗节点顺序漂移；
    - 节点 id 替换为位置占位 n{i}，inputs/outputs/components.root_node 引用同步替换，抗命名漂移；
    - params 数值/字符串符号化：同结构不同参数值 → 同 hash；改结构（点数/节点数）→ 变。
    注意：须走 model_dump（pydantic 补 autofix_hints 等默认字段），不能直接 hash raw JSON。
    """
    try:
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        doc = RawGcadDocument.model_validate(raw).model_dump()
    except Exception as exc:  # noqa: BLE001
        return _json_hash({"error": str(exc)})
    symbolized = copy.deepcopy(doc)
    nodes = symbolized.get("nodes", [])
    for n in nodes:
        if isinstance(n, dict):
            n.setdefault("params", {})
    # 规范排序（component/dialect/op/op_version/参数结构），抗 LLM 自由命名与节点顺序漂移
    nodes.sort(key=lambda n: (str(n.get("component", "")), str(n.get("dialect", "")),
                              str(n.get("op", "")), str(n.get("op_version", "")),
                              _json_hash(_symbolize(n.get("params")))))
    # 节点 id → 位置占位
    id_map: dict = {}
    for i, n in enumerate(nodes):
        if isinstance(n, dict):
            old = n.get("id")
            if old is not None:
                id_map[old] = f"n{i}"
            n["id"] = f"n{i}"
    # 引用替换：inputs.producer_node / outputs.value_id(node 段) / components.root_node
    for n in nodes:
        for inp in n.get("inputs", []) or []:
            prod = inp.get("node")
            if prod in id_map:
                inp["node"] = id_map[prod]
        for out in n.get("outputs", []) or []:
            v = out.get("value_id")
            if isinstance(v, str):
                parts = v.split(":")
                if len(parts) >= 3 and parts[2] in id_map:
                    parts[2] = id_map[parts[2]]
                    out["value_id"] = ":".join(parts)
    for comp in symbolized.get("components", []) or []:
        rn = comp.get("root_node")
        if rn in id_map:
            comp["root_node"] = id_map[rn]
    # 参数符号化
    for n in nodes:
        if isinstance(n, dict) and isinstance(n.get("params"), dict):
            n["params"] = _symbolize(n["params"])
    return _json_hash(symbolized)


def _param_vector(req: dict) -> dict:
    """规范化 8 参数向量（缺失补 None、float 化）。"""
    return {k: (float(req[k]) if req.get(k) is not None else None) for k in PARAM_VECTOR_KEYS}


def _param_template_id(text: str) -> str:
    """参数模板 id：需求文本提取的 8 参数向量 → stable_hash。"""
    return _json_hash(_param_vector(extract_requirements(text)))


def _measure_all(base: str) -> dict:
    agg = {}
    for fn in (measure_disc_dimensions, count_fir_tree_slots,
               measure_fir_tree_slot_profile, check_slot_pitch_and_ligament,
               check_slot_depth_and_rim, measure_hole_pattern, measure_groove):
        try:
            agg.update(fn({"base_dir": base}))
        except Exception:  # noqa: BLE001
            pass
    return agg


def _build_normalized(agg: dict, ro: float) -> list:
    out = []
    for key, label, is_derived, expr in NORMALIZED_PARAMS:
        value = agg.get(key)
        norm = None
        if isinstance(value, (int, float)) and ro and key.endswith("_mm"):
            norm = round(value / ro, 4)
        out.append({"key": key, "label": label,
                    "value": (round(value, 4) if isinstance(value, float) else value),
                    "normalized": norm, "is_derived": is_derived, "expression": expr})
    return out


def _mouth_wedge(ir: dict) -> dict | None:
    """槽口楔形段（榫槽轮廓前 2 点）：run=|Δx|、drop=|Δy|、angle=atan(drop/run)。

    语义 ≈ 论文"槽口倒角"的首齿楔形入口（非显式 chamfer op）。"""
    cutter_comp = None
    for n in ir.get("nodes", []):
        if n.get("op") == "extrude_profile":
            cutter_comp = n.get("component")
            break
    if not cutter_comp:
        return None
    for n in ir.get("nodes", []):
        if n.get("op") == "add_polyline" and n.get("component") == cutter_comp:
            pts = (n.get("params") or {}).get("points") or []
            if len(pts) >= 2:
                p0, p1 = pts[0], pts[1]
                run = abs(p1.get("x_mm", 0) - p0.get("x_mm", 0))
                drop = abs(p0.get("y_mm", 0) - p1.get("y_mm", 0))
                if run > 0:
                    return {"mouth_wedge_run_mm": round(run, 3),
                            "mouth_wedge_drop_mm": round(drop, 3),
                            "mouth_wedge_angle_deg": round(math.degrees(math.atan2(drop, run)), 3)}
            break
    return None


def _slot_axial_depth(ir: dict):
    for n in ir.get("nodes", []):
        if n.get("op") == "extrude_profile":
            return (n.get("params") or {}).get("depth_mm")
    return None


def _feature_counts(ir: dict) -> dict:
    ops: dict = {}
    for n in ir.get("nodes", []):
        op = n.get("op", "?")
        ops[op] = ops.get(op, 0) + 1
    return {"nodes": len(ir.get("nodes", [])),
            "components": len(ir.get("components", [])),
            "op_counts": ops}


def _constraints(agg: dict, ir: dict) -> list:
    """显式工程约束注册表（当前盘型适用 3 式；孔/环槽式 N/A）。"""
    ops = {n.get("op") for n in ir.get("nodes", [])}
    cons = []
    pitch = agg.get("circumferential_pitch_mm")
    if isinstance(pitch, (int, float)):
        cons.append({"id": "slot_pitch", "formula": "ps = 2π·rs/Ns", "applicable": True,
                     "params": {"count": agg.get("count"), "radius_mm": agg.get("distribution_radius_mm")},
                     "value_mm": round(pitch, 4), "validated_ok": True})
    width, lig = agg.get("slot_max_tangential_width_mm"), agg.get("min_ligament_mm")
    if isinstance(width, (int, float)) and isinstance(lig, (int, float)) and isinstance(pitch, (int, float)):
        lhs = width + 2 * lig
        cons.append({"id": "ws_plus_2cs_leq_ps", "formula": "ws + 2·cs ≤ ps", "applicable": True,
                     "params": {"width_mm": round(width, 4), "ligament_mm": round(lig, 4)},
                     "value_mm": round(lhs, 4), "bound_mm": round(pitch, 4),
                     "validated_ok": lhs <= pitch + 1e-6})
    depth, rim, bl = agg.get("slot_depth_mm"), agg.get("rim_thickness_mm"), agg.get("bottom_ligament_mm")
    if isinstance(depth, (int, float)) and isinstance(rim, (int, float)):
        lhs = depth + (bl if isinstance(bl, (int, float)) else 0)
        cons.append({"id": "hs_plus_cr_leq_tr", "formula": "hs + cr ≤ tr", "applicable": True,
                     "params": {"slot_depth_mm": round(depth, 4), "bottom_ligament_mm": bl},
                     "value_mm": round(lhs, 4), "bound_mm": round(rim, 4),
                     "validated_ok": lhs <= rim + 1e-6})
    if "cut_circular_hole_pattern" not in ops:
        cons.append({"id": "rp_plus_dh2_plus_cb_leq_rb", "formula": "rp + dh/2 + cb ≤ rb",
                     "applicable": False, "reason": "当前盘无孔阵列 op (cut_circular_hole_pattern)"})
    else:
        cons.append({"id": "rp_plus_dh2_plus_cb_leq_rb", "formula": "rp + dh/2 + cb ≤ rb",
                     "applicable": True, "validated_ok": None})
    if not {"cut_annular_groove", "cut_rim_slot_pattern"} & ops:
        cons.append({"id": "annular_groove_clearance", "formula": "环槽/rim_slot 约束",
                     "applicable": False, "reason": "当前盘无环槽/rim_slot op"})
    return cons


def _fingerprint(out_dir: Path) -> dict | None:
    """B-rep 几何指纹：体积/面积/包围盒/面边数/曲面类型分布 + stable hash。"""
    brep = out_dir / "output.brep"
    if not brep.exists():
        return None
    try:
        import cadquery as cq
        shape = cq.importers.importBrep(str(brep)).val()
        bb = shape.BoundingBox()
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.TopoDS import TopoDS
        from OCP.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                                 GeomAbs_Sphere, GeomAbs_Torus)
        _SURFACE_NAMES = {GeomAbs_Plane: "Plane", GeomAbs_Cylinder: "Cylinder",
                          GeomAbs_Cone: "Cone", GeomAbs_Sphere: "Sphere", GeomAbs_Torus: "Torus"}
        fexp = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
        eexp = TopExp_Explorer(shape.wrapped, TopAbs_EDGE)
        face_count = edge_count = 0
        types: dict = {}
        while fexp.More():
            face_count += 1
            ad = BRepAdaptor_Surface(TopoDS.Face_s(fexp.Current()))
            name = _SURFACE_NAMES.get(ad.GetType(), f"Type{ad.GetType()}")
            types[name] = types.get(name, 0) + 1
            fexp.Next()
        while eexp.More():
            edge_count += 1
            eexp.Next()
        fp = {"volume_mm3": round(shape.Volume(), 4), "area_mm2": round(shape.Area(), 4),
              "bbox_mm": [round(bb.xlen, 4), round(bb.ylen, 4), round(bb.zlen, 4)],
              "face_count": face_count, "edge_count": edge_count, "surface_types": types}
        fp["hash"] = _json_hash(fp)
        return fp
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _brep_source(base: Path) -> str | None:
    """B-rep 来源：pipeline 原生导出 = native；backfill 从 STEP 回读生成 = step_roundtrip。

    backfill_fields.py 生成回读 brep 时写 brep_source.json 标记；
    pipeline 原生导出（P1-6 后）无标记默认 native。
    """
    if not (base / "output.brep").exists():
        return None
    sentinel = base / "brep_source.json"
    if sentinel.exists():
        try:
            return json.loads(sentinel.read_text(encoding="utf-8")).get("source") or "step_roundtrip"
        except Exception:  # noqa: BLE001
            return "step_roundtrip"
    return "native"


def run_one(task_id: str) -> dict:
    base = OUTPUT / task_id
    rep = {"task_id": task_id, "schema": "dataset_enrich_v2", "Ro_mm": None,
           "Ro_source": None, "normalized_params": [], "param_template_id": None,
           "ir_doc_hash": None, "design_id": None, "design_vec_source": None,
           "model_id": None, "design_family_id": "custom", "role": "generated",
           "labels": None, "constraints": [], "b_rep_fingerprint": None,
           "b_rep_source": None, "request_source": None,
           "error": None, "timestamp": datetime.now().isoformat(timespec="seconds")}

    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        rep["error"] = "任务目录无 raw_fixed.json"
        (base / "dataset_enrich.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        return rep
    try:
        ir = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        rep["error"] = f"raw_fixed.json 读取失败: {exc}"
        return rep

    # ④ 归一化参数
    agg = {}
    try:
        agg = _measure_all(str(base))
        ro = agg.get("outer_radius_mm")
        rep["Ro_mm"] = round(ro, 4) if isinstance(ro, (int, float)) else None
        rep["Ro_source"] = "disk-g-cad-profile-max-x"
        rep["normalized_params"] = _build_normalized(agg, ro)
    except Exception as exc:  # noqa: BLE001
        rep["error"] = f"归一化失败: {exc}"

    # ⑦a ir_doc_hash
    rep["ir_doc_hash"] = _ir_doc_hash(ir)

    # ① 标识：继承源（E 阶段 Gen 3 描述变体显式继承源 design_id/model_id/family）
    inherited = False
    try:
        sr = json.loads((base / "source_ref.json").read_text(encoding="utf-8"))
        if sr.get("design_id"):
            rep["design_id"] = sr["design_id"]
            rep["param_template_id"] = sr["design_id"]
            rep["model_id"] = sr.get("model_id")
            rep["design_family_id"] = sr.get("design_family_id") or "custom"
            rep["design_vec_source"] = "inherited"
            inherited = True
    except Exception:  # noqa: BLE001
        pass

    if not inherited:
        # ⑦b param_template_id + ① 标识（design_id/model_id/design_family_id）
        design_vec = None
        try:
            req = json.loads((base / "request.json").read_text(encoding="utf-8"))
            rep["param_template_id"] = _param_template_id(req.get("text", ""))
            design_vec = _param_vector(extract_requirements(req.get("text", "")))
            rep["design_vec_source"] = "request"
        except Exception:  # noqa: BLE001
            pass
        if not design_vec or all(v is None for v in design_vec.values()):
            # 旧任务无 request.json → 用 req_param_report.extracted 兜底
            try:
                rp = json.loads((base / "req_param_report.json").read_text(encoding="utf-8"))
                design_vec = _param_vector(rp.get("extracted") or {})
                if rep["param_template_id"] is None and any(v is not None for v in design_vec.values()):
                    rep["param_template_id"] = _json_hash(design_vec)
                rep["design_vec_source"] = "req_param_report"
            except Exception:  # noqa: BLE001
                pass
        if not design_vec or all(v is None for v in design_vec.values()):
            # 最终兜底：从 IR 测量构造参数向量（早期任务两者都缺，如 mon_sweep_g5）
            try:
                measured = {"outer_diameter_mm": agg.get("outer_diameter_mm"),
                            "bore_diameter_mm": agg.get("bore_diameter_mm"),
                            "axial_thickness_mm": agg.get("axial_thickness_mm"),
                            "hub_half_mm": agg.get("hub_half_thickness_mm"),
                            "rim_half_mm": agg.get("rim_half_thickness_mm"),
                            "slots": agg.get("count"), "teeth_count": agg.get("teeth_count"),
                            "slot_depth_mm": agg.get("slot_depth_mm"),
                            "throat_half_width_mm": agg.get("throat_half_width_mm"),
                            "root_fillet_mm": agg.get("root_fillet_mm"),
                            "holes": agg.get("holes"), "hdia_mm": agg.get("hdia_mm"),
                            "pcd_mm": agg.get("pcd_mm"),
                            "grooves": agg.get("grooves"), "gw_mm": agg.get("gw_mm"),
                            "gd_mm": agg.get("gd_mm")}
                if any(v is not None for v in measured.values()):
                    design_vec = _param_vector(measured)
                    if rep["param_template_id"] is None:
                        rep["param_template_id"] = _json_hash(design_vec)
                    rep["design_vec_source"] = "ir-measured"
            except Exception:  # noqa: BLE001
                pass
        rep["design_id"] = rep["param_template_id"]
        rep["model_id"] = (rep["ir_doc_hash"] or "")[:12] if rep["ir_doc_hash"] else None
        # family_ref.json 显式标注（run_batch 候选生成时写入）；否则参数向量匹配兜底
        family_id = None
        try:
            family_id = json.loads((base / "family_ref.json").read_text(encoding="utf-8")).get("family_id")
        except Exception:  # noqa: BLE001
            pass
        rep["design_family_id"] = family_id if family_id else (
            _match_family(design_vec) if design_vec else "custom")

    # ⑤ role（参考 vs 生成）
    try:
        meta = json.loads((base / "output.metadata.json").read_text(encoding="utf-8"))
        tl = (meta.get("generative_metadata") or {}).get("trust_level") or meta.get("trust_level")
        if tl == "reference_geometry":
            rep["role"] = "reference"
    except Exception:  # noqa: BLE001
        pass

    # ③ labels（feasible / slot_key_dims / feature_counts）
    try:
        step_ok = (base / "output.step").exists()
        val_ok = False
        try:
            vr = json.loads((base / "validation_report.json").read_text(encoding="utf-8"))
            val_ok = bool(vr.get("ok"))
        except Exception:  # noqa: BLE001
            pass
        skd = {"pitch_mm": agg.get("circumferential_pitch_mm"),
               "min_ligament_mm": agg.get("min_ligament_mm"),
               "flank_angle_deg": agg.get("flank_angle_deg"),
               "slot_axial_depth_mm": _slot_axial_depth(ir)}
        wedge = _mouth_wedge(ir)
        if wedge:
            skd.update(wedge)
        rep["labels"] = {"feasible": step_ok and val_ok,
                         "slot_key_dims": {k: v for k, v in skd.items() if v is not None},
                         "feature_counts": _feature_counts(ir)}
    except Exception as exc:  # noqa: BLE001
        rep["error"] = f"labels 失败: {exc}"

    # ④ 约束注册表
    try:
        rep["constraints"] = _constraints(agg, ir)
    except Exception as exc:  # noqa: BLE001
        rep["error"] = f"constraints 失败: {exc}"

    # ② B-rep 指纹 + 来源（native / step_roundtrip / None）
    try:
        rep["b_rep_fingerprint"] = _fingerprint(base)
        rep["b_rep_source"] = _brep_source(base)
    except Exception as exc:  # noqa: BLE001
        rep["b_rep_fingerprint"] = {"error": str(exc)}

    # ① request 来源标记（backfill 重建 / existing / missing）
    try:
        req = json.loads((base / "request.json").read_text(encoding="utf-8"))
        if req.get("backfilled_from"):
            rep["request_source"] = "backfilled_cases"
        elif req.get("missing"):
            rep["request_source"] = "missing"
        else:
            rep["request_source"] = "existing"
    except Exception:  # noqa: BLE001
        rep["request_source"] = None

    (base / "dataset_enrich.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="④ 归一化参数 + ⑦a/b 隔离键（数据集 enrich）")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    args = ap.parse_args(argv)

    if args.only:
        tasks = [args.only]
    else:
        tasks = sorted(p.name for p in OUTPUT.iterdir()
                       if p.is_dir() and (p / "raw_fixed.json").exists())
    if not tasks:
        print("没有任务目录")
        return 1

    print(f"dataset enrich（{len(tasks)} 个任务）")
    for tid in tasks:
        r = run_one(tid)
        if r["error"]:
            print(f"- {tid}  FAIL  {r['error']}")
        else:
            n = len(r["normalized_params"])
            tpl = r["param_template_id"] or "None(无request.json)"
            print(f"- {tid}  OK  Ro={r['Ro_mm']}  params={n}  "
                  f"template={tpl[:20]}  doc={r['ir_doc_hash'][:10]}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
