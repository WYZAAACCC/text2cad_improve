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
)
from validate_req_params import extract_requirements  # noqa: E402

# ⑦b 参数向量固定 8 键（extract_requirements 的键，缺失补 None 抗漂移）
PARAM_VECTOR_KEYS = ["outer_diameter_mm", "bore_diameter_mm", "axial_thickness_mm",
                     "slots", "teeth_count", "slot_depth_mm",
                     "throat_half_width_mm", "root_fillet_mm"]

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
    ("teeth_count", "齿数", False, None),
]


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
    """Disk-G-CAD 文档哈希：RawGcadDocument.model_dump（对齐 raw_graph_hash 风格）→ params 符号化 → stable_hash。

    注意：须走 model_dump（pydantic 补 autofix_hints 等默认字段），不能直接 hash raw JSON。
    """
    try:
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
        doc = RawGcadDocument.model_validate(raw).model_dump()
    except Exception as exc:  # noqa: BLE001
        return _json_hash({"error": str(exc)})
    # 仅对参数做符号化（其余字段保留）；节点 id 保留（已知取舍：命名漂移影响 hash）
    symbolized = copy.deepcopy(doc)
    for node in symbolized.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("params"), dict):
            node["params"] = _symbolize(node["params"])
    return _json_hash(symbolized)


def _param_template_id(text: str) -> str:
    """参数模板 id：需求文本提取的 8 参数向量（缺失补 None、float 化）→ stable_hash。"""
    req = extract_requirements(text)
    vec = {k: (float(req[k]) if k in req and req[k] is not None else None)
           for k in PARAM_VECTOR_KEYS}
    return _json_hash(vec)


def _measure_all(base: str) -> dict:
    agg = {}
    for fn in (measure_disc_dimensions, count_fir_tree_slots,
               measure_fir_tree_slot_profile, check_slot_pitch_and_ligament,
               check_slot_depth_and_rim):
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


def run_one(task_id: str) -> dict:
    base = OUTPUT / task_id
    rep = {"task_id": task_id, "schema": "dataset_enrich_v1", "Ro_mm": None,
           "Ro_source": None, "normalized_params": [], "param_template_id": None,
           "ir_doc_hash": None, "error": None,
           "timestamp": datetime.now().isoformat(timespec="seconds")}

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

    # ⑦b param_template_id（request.json 的需求文本）
    try:
        req = json.loads((base / "request.json").read_text(encoding="utf-8"))
        rep["param_template_id"] = _param_template_id(req.get("text", ""))
    except Exception:  # noqa: BLE001
        pass

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
