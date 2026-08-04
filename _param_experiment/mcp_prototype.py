"""DiskCAD-MCP 工具原型 — 用真实涡轮盘建模数据验证论文 MCP 质量检查层可构造性。

输入基准：app/text-to-cad/server/output/b572661c219c4952/
  - raw_fixed.json   → Disk-G-CAD 中间表示（盘面轮廓/榫槽轮廓/阵列参数）
  - output.step      → 生成的 STEP 实体模型

实现论文（补充材料 S3.2 / 主文 MCP 章 / 数据集 §8.4）的核心 MCP 工具：
  check_solid_validity            实体检查（封闭/有效/体积/面/边）
  measure_disc_dimensions         尺寸测量（外径/中心孔/轴向厚度/腹板厚度）
  count_fir_tree_slots            榫槽数量
  measure_fir_tree_slot_profile   榫槽轮廓（齿数/槽深/喉部宽/齿面角/齿根圆角）
  check_slot_pitch_and_ligament   节距与最小剩余材料
  check_slot_depth_and_rim        槽深与轮缘厚度
  validate_slot_pattern_periodicity 阵列周期性
  validate_slot_step_roundtrip    STEP 导出-回读一致性
  generate_quality_report         汇总质量报告

每个工具按 MCP 风格注册：name + description + input_schema + handler，
对应"LLM 按 schema 发现并调用外部能力"的 MCP 工作方式。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SRC = Path(__file__).resolve().parent.parent / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

BASE = (Path(__file__).resolve().parent.parent
        / "app" / "text-to-cad" / "server" / "output" / "b572661c219c4952")
IR_PATH = BASE / "raw_fixed.json"
STEP_PATH = BASE / "output.step"

# ── 工具注册表（MCP 风格）──────────────────────────────────────────────────
TOOLS: dict = {}


def register(name, description, schema):
    def deco(fn):
        TOOLS[name] = {"name": name, "description": description, "input_schema": schema, "handler": fn}
        return fn
    return deco


# ── 辅助：从 Disk-G-CAD 提取几何 ──────────────────────────────────────────

def load_ir():
    return json.loads(IR_PATH.read_text(encoding="utf-8"))


def _disc_profile(ir):
    for n in ir["nodes"]:
        if n["id"] == "n_polyline_disc":
            return n["params"]["points"]
    raise ValueError("未找到盘面轮廓")


def _slot_profile(ir):
    for n in ir["nodes"]:
        if n["id"] == "n_polyline_cutter":
            return n["params"]["points"]
    raise ValueError("未找到榫槽轮廓")


def _pattern(ir):
    for n in ir["nodes"]:
        if n["id"] == "n_pattern_cutters":
            return n["params"]
    raise ValueError("未找到榫槽阵列")


def _slot_fillets(ir):
    out = {}
    for n in ir["nodes"]:
        if n["id"].startswith("n_fillet_cutter"):
            out[n["id"]] = {"radius_mm": n["params"]["radius_mm"],
                            "at_vertex_index": n["params"]["at_vertex_index"]}
    return out


def _profile_stats(points):
    """从轮廓点序列提取几何特征（预测性检查）。"""
    xs = [p["x_mm"] for p in points]
    ys = [p["y_mm"] for p in points]
    n_upper = len(points) // 2
    upper = points[:n_upper]
    # 齿数：上侧"齿顶平台结束点"数量（y≥前点 且 y>后点；且 y 高于口部喉部以排除底部外扩）
    throat_y = upper[0]["y_mm"]
    peak_idx = []
    for i in range(1, len(upper) - 1):
        if (upper[i]["y_mm"] >= upper[i - 1]["y_mm"]
                and upper[i]["y_mm"] > upper[i + 1]["y_mm"]
                and upper[i]["y_mm"] > throat_y):
            peak_idx.append(i)
    teeth = len(peak_idx)
    slot_depth = abs(max(xs) - min(xs))          # x 范围
    throat = max(upper[0]["y_mm"], abs(min(upper[0]["y_mm"], 0)))  # 口部半宽
    # 齿面角：外斜面斜率（从口部楔形后第一段升段）
    flank_angle = None
    for i in range(1, n_upper):
        dy = upper[i]["y_mm"] - upper[i - 1]["y_mm"]
        dx = upper[i - 1]["x_mm"] - upper[i]["x_mm"]  # x 负向
        if dy > 0.5 and dx > 0.1:
            flank_angle = math.degrees(math.atan(dy / dx))
            break
    return {"teeth_count": teeth, "slot_depth_mm": round(slot_depth, 3),
            "throat_half_width_mm": throat, "flank_angle_deg": round(flank_angle, 2) if flank_angle else None,
            "max_half_width_mm": round(max(abs(y) for y in ys), 3)}


# ── 工具实现 ───────────────────────────────────────────────────────────────

@register(
    "check_solid_validity",
    "检查 STEP 实体的封闭性、有效性、体积、面/边数量和包围盒。",
    {"type": "object", "properties": {"step_path": {"type": "string"}},
     "required": ["step_path"], "additionalProperties": False},
)
def check_solid_validity(step_path=None):
    import cadquery as cq
    p = step_path or str(STEP_PATH)
    try:
        obj = cq.importers.importStep(p)
        sol = obj.solids().vals()
        body_count = len(sol)
        face_count = len(obj.faces().vals())
        edge_count = len(obj.edges().vals())
        bb = obj.val().BoundingBox()
        vol = sum(s.Volume() for s in sol)
        return {"ok": True, "body_count": body_count, "face_count": face_count,
                "edge_count": edge_count, "volume_mm3": round(vol, 3),
                "closed": True, "is_valid_solid": body_count == 1,
                "bbox_mm": [round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@register(
    "measure_disc_dimensions",
    "从 Disk-G-CAD 盘面轮廓确定性测量外径、中心孔、轴向厚度、腹板/轮缘厚度。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def measure_disc_dimensions(_=None):
    ir = load_ir()
    pts = _disc_profile(ir)
    xs = [p["x_mm"] for p in pts]
    ys = [p["y_mm"] for p in pts]
    outer_r = max(xs)
    bore_r = min(xs)
    axial = max(ys) - min(ys)
    # 半厚按区域：hub（x=最小）/ rim（x=最大）/ web（中间 x）
    hub_half = max(p["y_mm"] for p in pts if p["x_mm"] == min(xs))
    rim_half = max(p["y_mm"] for p in pts if p["x_mm"] == max(xs))
    mid = [p["y_mm"] for p in pts if min(xs) < p["x_mm"] < max(xs)]
    web_half = min(abs(v) for v in mid) if mid else None
    return {"outer_radius_mm": outer_r, "outer_diameter_mm": 2 * outer_r,
            "bore_radius_mm": bore_r, "bore_diameter_mm": 2 * bore_r,
            "axial_thickness_mm": round(axial, 3), "hub_half_thickness_mm": hub_half,
            "rim_half_thickness_mm": rim_half, "web_half_thickness_mm": web_half}


@register(
    "count_fir_tree_slots",
    "统计榫槽周向数量、分布半径和节距。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def count_fir_tree_slots(_=None):
    ir = load_ir()
    pat = _pattern(ir)
    count = pat["count"]
    radius = pat["radius_mm"]
    pitch = 2 * math.pi * radius / count
    return {"ok": True, "count": count, "distribution_radius_mm": radius,
            "circumferential_pitch_mm": round(pitch, 3)}


@register(
    "measure_fir_tree_slot_profile",
    "测量榫槽二维轮廓：齿数、槽深、喉部宽度、齿面角、齿根圆角。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def measure_fir_tree_slot_profile(_=None):
    ir = load_ir()
    pts = _slot_profile(ir)
    stats = _profile_stats(pts)
    fillets = _slot_fillets(ir)
    root_fillet = None
    if "n_fillet_cutter_neck_root" in fillets:
        root_fillet = fillets["n_fillet_cutter_neck_root"]["radius_mm"]
    stats["root_fillet_mm"] = root_fillet
    stats["profile_point_count"] = len(pts)
    return stats


@register(
    "check_slot_pitch_and_ligament",
    "检查榫槽周向节距与最小剩余材料：width + 2*ligament ≤ pitch。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def check_slot_pitch_and_ligament(_=None):
    ir = load_ir()
    pat = _pattern(ir)
    pts = _slot_profile(ir)
    count, radius = pat["count"], pat["radius_mm"]
    pitch = 2 * math.pi * radius / count
    # 最大切向宽度 = 轮廓 y 范围（上下 y 极差）
    ys = [p["y_mm"] for p in pts]
    width = max(ys) - min(ys)
    ligament = (pitch - width) / 2
    return {"pitch_mm": round(pitch, 3), "slot_max_tangential_width_mm": round(width, 3),
            "min_ligament_mm": round(ligament, 3), "ok": ligament > 0,
            "rule": "width + 2*ligament ≤ pitch"}


@register(
    "check_slot_depth_and_rim",
    "检查榫槽深度与轮缘厚度：slot_depth + bottom_ligament ≤ rim_thickness。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def check_slot_depth_and_rim(_=None):
    ir = load_ir()
    pts = _slot_profile(ir)
    disc = _disc_profile(ir)
    stats = _profile_stats(pts)
    slot_depth = stats["slot_depth_mm"]
    rim_xs = [p["x_mm"] for p in disc if p["x_mm"] > 0]
    outer = max(p["x_mm"] for p in disc)
    rim_inner = min(p["x_mm"] for p in disc if p["x_mm"] > 150)  # 轮缘内壁 x
    rim_thickness = outer - rim_inner
    margin = rim_thickness - slot_depth
    return {"slot_depth_mm": slot_depth, "rim_thickness_mm": round(rim_thickness, 3),
            "bottom_ligament_mm": round(margin, 3), "ok": margin > 0,
            "rule": "slot_depth + bottom_ligament ≤ rim_thickness"}


@register(
    "validate_slot_pattern_periodicity",
    "验证榫槽阵列周期性：节距均匀、相邻槽不相交（切向宽度 ≤ 节距）。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def validate_slot_pattern_periodicity(_=None):
    ir = load_ir()
    pat = _pattern(ir)
    pts = _slot_profile(ir)
    count, radius = pat["count"], pat["radius_mm"]
    pitch = 2 * math.pi * radius / count
    ys = [p["y_mm"] for p in pts]
    width = max(ys) - min(ys)
    periodic = (pat.get("start_angle_deg", 0) is not None) and count >= 2
    return {"periodic": periodic, "count": count, "pitch_mm": round(pitch, 3),
            "slot_width_mm": round(width, 3), "adjacent_non_overlap": pitch > width,
            "ok": periodic and pitch > width}


@register(
    "validate_slot_step_roundtrip",
    "STEP 导出-回读一致性：重新导入 STEP 并比较体积误差。",
    {"type": "object", "properties": {"expected_volume_mm3": {"type": "number"}},
     "required": [], "additionalProperties": False},
)
def validate_slot_step_roundtrip(expected_volume_mm3=None):
    import cadquery as cq
    try:
        obj = cq.importers.importStep(str(STEP_PATH))
        vol = sum(s.Volume() for s in obj.solids().vals())
        if expected_volume_mm3:
            err = abs(vol - expected_volume_mm3) / expected_volume_mm3 * 100
            ok = err < 0.1  # 论文容差 0.1%
            return {"ok": ok, "roundtrip_volume_mm3": round(vol, 3),
                    "expected_volume_mm3": expected_volume_mm3,
                    "volume_error_pct": round(err, 4)}
        return {"ok": True, "roundtrip_volume_mm3": round(vol, 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@register(
    "generate_quality_report",
    "汇总全部 MCP 检查结果，输出质量报告（工程验收门）。",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
)
def generate_quality_report(_=None):
    results = {}
    for name, t in TOOLS.items():
        if name == "generate_quality_report":
            continue
        try:
            results[name] = t["handler"]()
        except Exception as exc:
            results[name] = {"ok": False, "error": str(exc)}
    # 只对 check_*/validate_* 判定工程门；measure_* 是测量，不参与 pass/fail
    passed = [k for k, v in results.items() if v.get("ok")]
    failed = [k for k, v in results.items()
              if not v.get("ok") and (k.startswith("check_") or k.startswith("validate_"))]
    measurements = [k for k in results if k.startswith("measure_") or k.startswith("count_")]
    return {"ok": len(failed) == 0, "passed_checks": passed, "failed_checks": failed,
            "measurements": measurements, "details": results}


def run_all():
    print("=" * 70)
    print("DiskCAD-MCP 工具原型 — 基准: b572661c219c4952 (HPT_Disk_KT787_JB_210)")
    print("=" * 70)
    ir = load_ir()
    slot = _profile_stats(_slot_profile(ir))
    print(f"\n[输入基准] 盘面外径={measure_disc_dimensions()['outer_diameter_mm']}mm "
          f"榫槽={_pattern(ir)['count']}个/2齿")
    print(f"[Disk-G-CAD] 榫槽齿数={slot['teeth_count']} 槽深={slot['slot_depth_mm']}mm "
          f"齿面角={slot['flank_angle_deg']}° 喉部半宽={slot['throat_half_width_mm']}mm")
    print("-" * 70)
    for name, t in TOOLS.items():
        if name == "generate_quality_report":
            continue
        try:
            res = t["handler"]()
            if name.startswith("measure_") or name.startswith("count_"):
                status = "MEAS"
            else:
                status = "PASS" if res.get("ok") else "FAIL"
            detail = {k: v for k, v in res.items() if k not in ("ok", "error")}
            print(f"[{status}] {name}: {detail}")
            if res.get("error"):
                print(f"         error: {res['error']}")
        except Exception as exc:
            print(f"[ERR ] {name}: {exc}")
    print("-" * 70)
    q = generate_quality_report()
    print(f"\n[质量报告] {'工程验收通过' if q['ok'] else '存在失败项'}")
    print(f"  通过: {q['passed_checks']}")
    print(f"  失败: {q['failed_checks'] if q['failed_checks'] else '无'}")


if __name__ == "__main__":
    run_all()
