"""确定性参数化模板：设计族参数 → 合法 RawGcadDocument（llm_raw）。

用户流程：llm_raw 由确定性参数化模板生成（非 LLM），同族种子改参数得不同 llm_raw，
经 validation/repair/runtime/MCP 门采集数据；LLM 只用于生成三种描述。

蓝本：
  - 榫槽盘（sketch_profile 盘体 + slot_cutter + composition 布尔）：
    app/text-to-cad/server/output/mon_sweep_g1_baseline/raw_fixed.json
  - 盘型（axisymmetric 单组件）：
    demo_output_v5/v6_full35_output/tm01_flange_cover/raw_fixed.json

模板函数输入 design_families 风格参数，输出 RawGcadDocument dict（结构固定，参数可替换）。
独立于主流程/src；生成结果用 run_gcad_core_from_files 验证（validation+runtime）。

用法:
  .conda/python.exe -c "import param_templates as pt; doc=pt.build(pt.DEMO_SLOT); print('OK', len(doc['nodes']))"
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════════════════
# 盘体几何推导（od/bore/thick/hub/rim → 12 点 R-Z 轮廓）
# ═══════════════════════════════════════════════════════════════════════════════

# 盘体形态（几何结构差异——族间不只是参数不同，论文泛化/丰富性要求）
#   standard    标准 hub-web-rim（hub 径向 0.16od，rim 径向 0.12od，web 厚 0.5-0.6×半厚）
#   thin_web    薄腹板（web 轴向厚仅 0.3-0.35×半厚，腹板更轻）
#   thick_rim   厚轮缘（rim 径向高 0.17od，轮缘更厚重）
#   large_hub   大轮毂（hub 径向高 0.22od，轮毂更大）
#   conical      锥形腹板（web 斜面更陡，腹板呈锥形）
DISC_FORMS = ("standard", "thin_web", "thick_rim", "large_hub", "conical")
_RADIAL_FAC = {"standard": (0.16, 0.12), "thin_web": (0.16, 0.12),
               "thick_rim": (0.14, 0.17), "large_hub": (0.22, 0.10),
               "conical": (0.16, 0.12)}


def _disc_radii(od_mm, bore_mm, form="standard") -> dict:
    """盘体半径推导唯一真源——disc_profile 轮廓、build_axisym_disc 特征、
    sampling_constraints 约束全部用同一组半径（消除此前 build_axisym 硬编码
    0.12 系数导致的 rim_junc 偏差，如 thick_rim 偏差 -27mm）。

    返回 {bore_r, rim_r, hub_r, rim_junc, web_r, hub_radial, rim_radial}。
    """
    bore_r = bore_mm / 2.0
    rim_r = od_mm / 2.0
    h_fac, r_fac = _RADIAL_FAC.get(form, (0.16, 0.12))
    hub_radial = _clamp(h_fac * od_mm, 25.0, 100.0)
    rim_radial = _clamp(r_fac * od_mm, 25.0, 95.0)
    hub_r = bore_r + hub_radial
    rim_junc = rim_r - rim_radial
    if hub_r >= rim_junc:  # 保证腹板存在
        hub_r = (bore_r + rim_junc) / 2.0
    return {"bore_r": bore_r, "rim_r": rim_r, "hub_r": hub_r, "rim_junc": rim_junc,
            "web_r": (hub_r + rim_junc) / 2.0,
            "hub_radial": hub_radial, "rim_radial": rim_radial}


def _transition_pts(rim_junc, z0, z1, t, kind, n=4) -> list:
    """轮缘内壁 (rim_junc, z0)→(rim_junc, z1) 垂直台阶间插入过渡点（z 单调）。

    complex_rim 族用多点逼近曲线过渡（取代单一 fillet 圆弧，满足论文"丰富过渡"）。
    kind：linear=无插入 / arc_in=内凹弧 / arc_out=外凸弧 / s_curve=S形 /
    power=幂曲线 / ellipse=椭圆弧。返回 [(r, z), ...]（不含两端）。
    """
    if t <= 0 or kind == "linear":
        return []
    out = []
    for i in range(1, n + 1):
        u = i / (n + 1)
        z = z0 + (z1 - z0) * u
        if kind == "arc_in":
            r = rim_junc - t * math.sin(math.pi * u)
        elif kind == "arc_out":
            r = rim_junc + 0.5 * t * math.sin(math.pi * u)
        elif kind == "s_curve":
            r = rim_junc - t * math.sin(2 * math.pi * u)
        elif kind == "power":
            r = rim_junc - t * (1.0 - u) ** 1.5
        elif kind == "ellipse":
            r = rim_junc - t * math.cos(math.pi * u / 2.0)
        else:
            r = rim_junc
        out.append((round(r, 3), round(z, 3)))
    return out


def disc_profile(od_mm, bore_mm, hub_half_mm, rim_half_mm, thick_mm,
                 web_inner_half=None, web_outer_half=None, form="standard",
                 transition="linear") -> dict:
    """盘体 R-Z 轮廓（闭合顺序，关于 y=0 对称）→ {points, params}。

    径向站：bore_r → hub_r → rim_junc → rim_r。形态决定 hub/rim 径向高度与 web 厚度，
    使不同设计族（薄腹板/厚轮缘/大毂/锥形）轮廓结构可区分，而非仅尺寸参数不同。
    """
    _r = _disc_radii(od_mm, bore_mm, form)
    bore_r, rim_r = _r["bore_r"], _r["rim_r"]
    hub_r, rim_junc = _r["hub_r"], _r["rim_junc"]
    hub_radial, rim_radial = _r["hub_radial"], _r["rim_radial"]
    if form == "thin_web":
        web_inner = web_inner_half if web_inner_half else _clamp(0.35 * hub_half_mm, 5.0, 22.0)
        web_outer = web_outer_half if web_outer_half else _clamp(0.3 * rim_half_mm, 4.0, 18.0)
    else:
        web_inner = web_inner_half if web_inner_half else _clamp(0.6 * hub_half_mm, 8.0, 40.0)
        web_outer = web_outer_half if web_outer_half else _clamp(0.5 * rim_half_mm, 6.0, 32.0)
    # 复杂轮缘曲线过渡（transition != linear）：web-rim 台阶插入过渡点逼近曲线。
    # 幅度 ≤6mm（0.06×rim_radial）：过渡点 r 限制在 rim_junc±6 内，不深入腹板
    # （此前 0.2×rim_radial 使 D29 s_curve 点 r_min=148.8 深陷腹板 → 过渡完全错误）。
    trans_t = 0.0
    if transition != "linear":
        trans_t = _clamp(0.06 * rim_radial, 2.0, 6.0)

    def _wr(z0, z1):
        return _transition_pts(rim_junc, z0, z1, trans_t, transition)

    if form == "conical":
        # 锥形腹板：web 越朝外越薄（hub 侧厚、rim 侧薄）——rim 侧半厚 wo_cone 小于 hub 侧 web_inner。
        # 此前 0.85×rim_half 使 rim 侧比 hub 侧更厚（厚度方向反了，用户反馈）。
        wo_cone = _clamp(0.4 * rim_half_mm, 8.0, 24.0)
        lo_ins = _wr(-wo_cone, -rim_half_mm)              # 下半过渡点（z 递减）
        hi_ins = [(r, -z) for r, z in reversed(lo_ins)]    # 上半镜像（z 取正 + 反转，保证轮廓对称）
        pts = [
            (round(bore_r, 3), -hub_half_mm), (round(hub_r, 3), -hub_half_mm),
            (round(hub_r, 3), -web_inner), (round(rim_junc, 3), -wo_cone),
            *lo_ins,
            (round(rim_junc, 3), -rim_half_mm), (round(rim_r, 3), -rim_half_mm),
            (round(rim_r, 3), rim_half_mm), (round(rim_junc, 3), rim_half_mm),
            *hi_ins,
            (round(rim_junc, 3), wo_cone), (round(hub_r, 3), web_inner),
            (round(hub_r, 3), hub_half_mm), (round(bore_r, 3), hub_half_mm),
        ]
    else:
        lo_ins = _wr(-web_outer, -rim_half_mm)
        hi_ins = [(r, -z) for r, z in reversed(lo_ins)]
        pts = [
            (round(bore_r, 3), -hub_half_mm), (round(hub_r, 3), -hub_half_mm),
            (round(hub_r, 3), -web_inner), (round(rim_junc, 3), -web_outer),
            *lo_ins,
            (round(rim_junc, 3), -rim_half_mm), (round(rim_r, 3), -rim_half_mm),
            (round(rim_r, 3), rim_half_mm), (round(rim_junc, 3), rim_half_mm),
            *hi_ins,
            (round(rim_junc, 3), web_outer), (round(hub_r, 3), web_inner),
            (round(hub_r, 3), hub_half_mm), (round(bore_r, 3), hub_half_mm),
        ]
    return {"points": [{"x_mm": p[0], "y_mm": p[1]} for p in pts],
            "params": {"bore_radius_mm": round(bore_r, 3), "hub_radius_mm": round(hub_r, 3),
                       "rim_web_junction_mm": round(rim_junc, 3), "rim_radius_mm": round(rim_r, 3),
                       "hub_radial_mm": round(hub_radial, 3), "rim_radial_mm": round(rim_radial, 3),
                       "web_inner_half_mm": round(web_inner, 3), "web_outer_half_mm": round(web_outer, 3),
                       "form": form}}


# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽轮廓（2×(2+4×teeth+3) 点，XY 平面，x 0→-depth）
# ═══════════════════════════════════════════════════════════════════════════════

def slot_profile(teeth, depth_mm, mouth_half, neck_half, lobe_half,
                 bottom_half, tfa_deg=80.0, ufa_deg=70.0) -> list:
    """榫槽轮廓点（上侧 2+4×teeth+3 点 + 下侧镜像）。以 mon_e2b035beb218 为基准。

    mon 正确构造特征（throat=4 归一化）：
      - 口部 mouth=throat；楔入点 neck0=0.625×throat
      - 每齿 4 点：外斜面升 / 齿顶平台 / 内斜面降 / 颈部平台
      - neck 逐齿收窄（mon 2.5→2.0，step 0.125×throat）
      - lobe 逐齿平缓衰减（mon 7.5→6.5，step 0.25×throat）
      - 槽底：槽底肩 shoulder=1.25×throat → 平底 root=0.875×throat
        （平底而非圆弧/尖底；mon 槽底根半宽 3.5）

    齿面角由参数驱动（P6 修复，原 flank_angle_deg 死参数）：
      - tfa_deg：外斜面（承力面）与径向 x 夹角，默认 80°（mon 实测 78.7-82.9°）
      - ufa_deg：内斜面（非工作面）与径向 x 夹角，默认 70°（mon 实测 68.2-71.6°）
      - 斜面 x 跨度 dx = Δy / tan(θ)（参照 fir_tree_parametric.py）；齿顶/颈平台宽 = 0.5×mouth

    硬性要求（保证无退化）：x 单调递减到 -depth；相邻点距离 ≥1mm。
    """
    def upper():
        m = float(mouth_half)
        n = int(teeth)
        tfa = math.radians(max(30.0, min(float(tfa_deg), 89.0)))
        ufa = math.radians(max(30.0, min(float(ufa_deg), 89.0)))
        tan_tfa = math.tan(tfa)
        tan_ufa = math.tan(ufa)
        lobes = [lobe_half - 0.25 * m * i for i in range(n)]
        # 齿根（neck）更宽（neck_half=1.1×throat）+ 递减 0.25×throat（下限 1.5）
        # → 点 9/14 距离宽（2×2.4=4.8），齿根共线斜线斜率 ~0.095。
        necks = [max(neck_half - 0.25 * m * (i + 1), 1.5) for i in range(n)]
        # 齿区占用（P6-2 圆顶相切半圆，数学推导）：
        #   每齿 = 外斜面 dx + 半圆横向 r·(sin Tfa + sin Ufa) + 内斜面 dx + 连接线 w_plat
        #   斜面 dx 含半圆切点抬升（lobe + r·cos θ），合并后每齿 r·(1/sin Tfa + 1/sin Ufa)：
        #   占用 = Σbase_i + n·w_plat·(1 + (1/sin Tfa + 1/sin Ufa)/2)，r = w_plat/2
        prev_neck = float(neck_half)
        occ_base = 0.0
        for i in range(n):
            occ_base += (lobes[i] - prev_neck) / tan_tfa + (lobes[i] - necks[i]) / tan_ufa
            prev_neck = necks[i]
        # 齿区目标占用 = depth − 9（楔入3 + 槽底区6；齿顶 fillet ≤2.79 端面无微边）。
        # 齿根沿 y_neck 共线斜线（点4/5/8/9 一条线，斜率 = neck差/x跨度；neck_half=1.0×throat
        # 递减到 1.2 → 斜率大）。平台宽平分剩余填满（直线，轮缘端面无微边）。
        w_plat = max(0.5 * m, min((depth_mm - 9.0 - occ_base) / (2.0 * n), 1.6 * m))
        # Phase 1：布局 x——外斜面从上一齿根升到齿顶，内斜面降到齿根，连接线到下一齿根。
        xs_root = [-3.0]  # 各齿外斜面起点（齿根）
        xs_tip, xs_plat, xs_neck, xs_conn = [], [], [], []
        x = -3.0
        prev_neck = float(neck_half)
        for i in range(n):
            lobe = lobes[i]
            dx_ext = (lobe - prev_neck) / tan_tfa
            x_tip = x - dx_ext
            xs_tip.append(x_tip)
            x_plat = x_tip - w_plat
            xs_plat.append(x_plat)
            dx_int = (lobe - necks[i]) / tan_ufa
            x_neck = x_plat - dx_int
            xs_neck.append(x_neck)
            x_conn = x_neck - w_plat
            xs_conn.append(x_conn)
            xs_root.append(x_conn)
            prev_neck = necks[i]
            x = x_conn
        # Phase 2：齿根共线斜线 y_neck(x)——线性穿过楔入点(第一齿根)与最后齿根。
        x0r, y0r = xs_root[0], float(neck_half)
        x1r, y1r = xs_conn[-1], necks[-1]

        def y_neck(xx):
            if abs(x1r - x0r) < 1e-6:
                return y0r
            return y0r + (y1r - y0r) * (xx - x0r) / (x1r - x0r)

        pts = [(0.0, round(m, 3))]
        pts.append((-3.0, round(neck_half, 3)))  # 楔入点
        for i in range(n):
            lobe = round(lobes[i], 3)
            pts.append((round(xs_tip[i], 3), lobe))                            # 外斜面升（齿顶）
            pts.append((round(xs_plat[i], 3), lobe))                           # 齿顶平台（极小残留）
            pts.append((round(xs_neck[i], 3), round(y_neck(xs_neck[i]), 3)))   # 内斜面降（齿根共线）
            pts.append((round(xs_conn[i], 3), round(y_neck(xs_conn[i]), 3)))   # 连接线（斜，齿根共线）
        # 槽底：肩起点 → 平底（肩起点靠近平底 → 点10→11 距离短，不靠增大占用）
        shoulder = round(1.25 * m, 3)
        root = round(bottom_half, 3)
        x_last = xs_conn[-1]  # 最后连接线终点
        pts.append((round(min(x_last - 1.0, -depth_mm + 2.0), 3), shoulder))   # 槽底肩起点
        pts.append((-depth_mm, root))                    # 槽底平底
        return pts
    upper_pts = upper()
    # 迭代短边修正（仅上侧）：相邻点距离 <1mm 时把后一点沿 x 外推到前一点左侧 dx 处，
    # 迭代至全部 ≥1mm（处理连锁——齿区/槽底台阶/边/根逐点外推，允许槽底外推超过齿区终点）。
    # 下侧对称继承。首点 (0, mouth) 固定不修正。
    pts = list(upper_pts)
    for _ in range(60):
        changed = False
        for i in range(1, len(pts)):
            px, py = pts[i - 1]
            x, y = pts[i]
            d = math.hypot(x - px, y - py)
            # 阈值 0.5mm（放宽原 1.0）：凸半圆 9 点段距 ~0.74 不触发外推（保持圆弧几何）；
            # MCP 退化阈值 0.25mm，0.5mm 以上边安全。
            if d < 0.5:
                dx = math.sqrt(max(0.25 - (y - py) ** 2, 0.0))
                nx = px - dx
                if nx < x:  # 外推到更左（增大与前置点的距离）
                    pts[i] = (nx, y)
                    changed = True
        if not changed:
            break
    # y=0 的槽底最深点（凹半圆 θ=180°）镜像重合（-0=0）——跳过，U 形圆底保持单点闭合
    lower = [(p[0], -p[1]) for p in pts if abs(p[1]) > 1e-6]
    return [{"x_mm": round(p[0], 3), "y_mm": round(p[1], 3)}
            for p in pts + list(reversed(lower))]


def slot_fillet_fr_limit(teeth, depth_mm, throat_half, tfa_deg=80.0, ufa_deg=70.0) -> float:
    """5 组 fillet 全组安全的 fr 上限（OCC fillet2D 切线空间）。

    失败判据（实测）：r·tan(θ/2) > min(L1, L2) 时 fillet2D 抛 FILLET_SKETCH_FAILED。
    每组 fillet 半径 r_g = clamp(fr·factor, …, cap…)，要求对组内每个顶点 v：
        r_g ≤ min(L1_v, L2_v)/tan(θ_v/2)   →  fr ≤ r_max_v/factor 且 ≤ cap/factor
    返回 5 组中最小 fr 上限（采样 clamp 与 check_all 共用同一几何真源）。
    """
    m = float(throat_half)
    neck = round(1.1 * m, 3)
    lobe = round(2.25 * m, 3)
    bottom = round(0.875 * m, 3)
    sp = slot_profile(int(teeth), depth_mm, m, neck, lobe, bottom, tfa_deg, ufa_deg)
    pts = [(p["x_mm"], p["y_mm"]) for p in sp]
    n_upper = 2 + 4 * int(teeth) + 2

    def _r_max(idx):
        # 顶点 idx 两邻边长度与轮廓内角 θ（沿轮廓进入方向 p1−p0、离开方向 p2−p1）
        # → 单角可放最大半径 min(L1,L2)/tan(θ/2)（OCC fillet2D 失败判据）
        p0, p1, p2 = pts[idx - 1], pts[idx], pts[idx + 1]
        L1 = math.hypot(p0[0] - p1[0], p0[1] - p1[1])
        L2 = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        d = (v1[0] * v2[0] + v1[1] * v2[1]) / (math.hypot(*v1) * math.hypot(*v2) + 1e-9)
        theta = math.acos(max(-1.0, min(1.0, d)))
        return min(L1, L2) / math.tan(theta / 2.0 + 1e-9)

    n = int(teeth)
    # 与 _slot_cutter_nodes 分组一致（每齿 4 点，齿顶两端 fillet）：(factor, cap, 上侧目标顶点)
    _tfa_r = math.radians(max(30.0, min(float(tfa_deg), 89.0)))
    _ufa_r = math.radians(max(30.0, min(float(ufa_deg), 89.0)))
    w_tips = [abs(sp[3 + 4 * i]['x_mm'] - sp[2 + 4 * i]['x_mm']) for i in range(n)]
    r_tip = max(w_tips) / (math.tan(_tfa_r / 2.0) + math.tan(_ufa_r / 2.0))
    groups = [
        (3.0, r_tip * 0.8, [2 + 4 * i for i in range(n)] + [3 + 4 * i for i in range(n)]),  # 齿顶圆弧
        (1.2, 2.0, [4 + 4 * i for i in range(n)]),                                          # 内斜面降（圆角加大）
        (1.0, 1.6, [1] + [5 + 4 * i for i in range(n)]),                                    # 楔入/连接线（圆角加大）
        (3.0, bottom * 0.9, [n_upper - 1]),                                                 # 槽底圆弧
    ]
    limit = float("inf")
    for factor, cap, idxs in groups:
        for idx in idxs:
            if idx == 0 or idx >= n_upper - 1:
                continue  # 口部不 fillet
            # rad = min(fr×factor, cap)：fr 增大时 rad 被 cap 固定（≤r_max 则安全）。
            # 故 fr 上限只由 fr×factor ≤ r_max 决定（cap 不限制 fr 名义值）。
            fr_lim = _r_max(idx) / factor
            limit = min(limit, fr_lim)
    return round(limit, 3) if limit < float("inf") else 3.0


# ═══════════════════════════════════════════════════════════════════════════════
# RawGcadDocument 节点构造 helper
# ═══════════════════════════════════════════════════════════════════════════════

def _node(nid, comp, op, inputs, outputs, params, phase, dialect):
    return {"id": nid, "component": comp, "dialect": dialect, "op": op,
            "op_version": "1.0.0", "phase": phase, "inputs": inputs,
            "outputs": outputs, "params": params, "required": True,
            "degradation_policy": "fail"}


def _nref(nid, out):
    return {"node": nid, "output": out}


def _out(name, typ):
    return {"name": name, "type": typ}


_SAFETY = {
    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
    "not_for_manufacturing": True, "not_for_installation": True,
    "no_structural_validation": True, "no_life_prediction": True,
}


# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽 cutter 节点（sketch_profile：create_2d_sketch → polyline → close → fillet → extrude）
# 供 build_slot_disc / build_coupled_disc 复用（cutter 从轮缘外表面 rim_r 处切入）
# ═══════════════════════════════════════════════════════════════════════════════

def _slot_cutter_nodes(teeth, slots, depth_mm, throat_half, fr_mm, rim_r,
                       axial_depth_mm=80.0, tfa_deg=80.0, ufa_deg=70.0) -> list:
    # mon_e2b035beb218 尺寸比例（throat=4 归一化：neck0=2.5/0.625m, lobe1=7.5/1.875m,
    # 槽底平底=3.5/0.875m）
    m = float(throat_half)
    neck = round(1.1 * m, 3)
    lobe = round(2.25 * m, 3)
    bottom = round(0.875 * m, 3)
    sp = slot_profile(int(teeth), depth_mm, m, neck, lobe, bottom, tfa_deg, ufa_deg)
    n_sketch = _node("n_sketch_cutter", "slot_cutter", "create_2d_sketch", [],
                     [_out("sketch", "sketch")],
                     {"plane": "XY", "origin_x_mm": 0, "origin_y_mm": 0},
                     "sketch", "sketch_profile")
    n_polyline = _node("n_polyline_cutter", "slot_cutter", "add_polyline",
                       [_nref("n_sketch_cutter", "sketch")], [_out("profile", "profile")],
                       {"points": sp}, "profile", "sketch_profile")
    n_close = _node("n_close_cutter", "slot_cutter", "close_profile",
                    [_nref("n_polyline_cutter", "profile")], [_out("profile", "profile")],
                    {}, "profile", "sketch_profile")
    n_upper = 2 + 4 * int(teeth) + 2
    n = int(teeth)

    def _mirror(idxs):
        return sorted({int(i) for i in idxs} | {2 * n_upper - 1 - int(i) for i in idxs})

    # 点索引（每齿 4 点，齿根共线 P6-2）：0口 1楔入 | 齿 i: 2+4i(外斜面升=齿顶)
    #   3+4i(齿顶平台) 4+4i(内斜面降) 5+4i(连接线)
    #   | 槽底: n_upper-2(肩起点) n_upper-1(平底，大圆弧圆底)
    # 齿顶圆顶（P6-2）：两端 fillet 半径用数学公式 r_tip = w_tip/(tan(Tfa/2)+tan(Ufa/2))
    #   ×0.93 留 ~7% 平台——polyline 曲线在轮缘端面 z=−rim_half 处布尔产生 <0.25mm 微边，
    #   平台直线段使端面交线平直；圆角由 OCC fillet2D 真圆弧生成（端面无微边）。
    # 槽底圆底：平底点大半径 fillet（直线过渡段长 → r_max 大，真圆弧端面无微边）。
    _f = float(fr_mm)
    w_tips = [abs(sp[3 + 4 * i]['x_mm'] - sp[2 + 4 * i]['x_mm']) for i in range(n)]
    _tfa_r = math.radians(max(30.0, min(float(tfa_deg), 89.0)))
    _ufa_r = math.radians(max(30.0, min(float(ufa_deg), 89.0)))
    r_tip = max(w_tips) / (math.tan(_tfa_r / 2.0) + math.tan(_ufa_r / 2.0))
    rad_dome = round(max(min(_f * 3.0, r_tip * 0.8), 0.5), 3)   # 齿顶圆弧（公式×0.8 留平台防端面微边）
    rad_bottom = round(max(min(_f * 3.0, bottom * 0.9), 0.5), 3)  # 槽底圆弧（大，U 形圆底）
    rad_flank = round(max(min(_f * 1.2, 2.0), 0.3), 3)   # 内斜面降（点4/8，圆角加大）
    rad_neck = round(max(min(_f * 1.0, 1.6), 0.3), 3)    # 楔入、连接线（点5/9，圆角加大）
    rad_shoulder = 0.3                                    # 槽底肩起点小圆角（r_max 小，固定）
    groups = [
        (rad_dome, [2 + 4 * i for i in range(n)] + [3 + 4 * i for i in range(n)]),
        (rad_flank, [4 + 4 * i for i in range(n)]),
        (rad_neck, [1] + [5 + 4 * i for i in range(n)]),
        (rad_shoulder, [n_upper - 2]),
        (rad_bottom, [n_upper - 1]),
    ]
    cur = "n_close_cutter"
    fillet_nodes = []
    for gi, (rad, idxs) in enumerate(groups):
        if not idxs:
            continue
        fid = f"n_fillet_cutter_{gi}"
        fillet_nodes.append(_node(fid, "slot_cutter", "fillet_sketch",
                                  [_nref(cur, "profile")], [_out("profile", "profile")],
                                  {"radius_mm": rad, "at_vertex_index": _mirror(idxs)},
                                  "edge_treatment", "sketch_profile"))
        cur = fid
    n_extrude = _node("n_cutter_extrude", "slot_cutter", "extrude_profile",
                      [_nref(cur, "profile")], [_out("body", "solid")],
                      {"depth_mm": axial_depth_mm, "direction": "both", "taper_deg": 0},
                      "feature", "sketch_profile")
    return [n_sketch, n_polyline, n_close] + fillet_nodes + [n_extrude]



# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽盘模板（sketch_profile 盘体 + slot_cutter + composition 布尔）
# ═══════════════════════════════════════════════════════════════════════════════

def build_slot_disc(params: dict) -> dict:
    """榫槽盘 llm_raw。params 键：od_mm/bore_mm/thick_mm/hub_mm/rim_mm +
    slots/teeth/R_mm/depth_mm/throat_half_width_mm/fr_mm。"""
    dp = disc_profile(params["od_mm"], params["bore_mm"], params["hub_mm"], params["rim_mm"],
                      params["thick_mm"], form=params.get("form", "standard"),
                      transition=params.get("transition", "linear"))
    teeth = int(params.get("teeth", 2))
    slots = int(params.get("slots", 60))
    depth = params.get("depth_mm", 24.0)
    # 榫槽 cutter 从轮缘外表面(rim_r = od/2)切入（参考 mon_e2b035beb218 pattern radius=rim_r）。
    # circular_pattern 把 cutter 槽口(x=0)平移到 radius 处 → 槽口贴轮缘外表面，槽深 depth 切入轮缘。
    # 槽底剩料由 check_slot_depth 保证（depth + mr ≤ rim_radial，论文 5.3）。
    rim_r = params["od_mm"] / 2.0
    # pattern radius = rim_r：槽口在轮缘外表面切开（标准涡轮盘结构，叶片从外缘径向装入；
    # 此前 R_mm 作 pattern radius 使槽口内缩脱离外表面 → 用户反馈"没切开轮缘外部"）。
    # R_mm 保留为分布半径参数：用于周向节距约束（check_slot_pitch: 2πR/slots）与论文标注。
    R = rim_r
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)

    # 盘体统一 sketch_profile 轮廓 + fillet + revolve（与参考 mon_e2b035beb218 同架构）。
    # complex_rim 的曲线过渡由 disc_profile 插入点表达（transition 类型），不再用单一
    # fillet_sketch 圆弧（圆弧无法表达 S/双圆弧/幂曲线等丰富过渡）。
    n_sketch_disc = _node("n_sketch_disc", "disc_body", "create_2d_sketch", [],
                          [_out("sketch", "sketch")],
                          {"plane": "XZ", "origin_x_mm": 0, "origin_y_mm": 0},
                          "sketch", "sketch_profile")
    n_polyline_disc = _node("n_polyline_disc", "disc_body", "add_polyline",
                            [_nref("n_sketch_disc", "sketch")], [_out("profile", "profile")],
                            {"points": dp["points"]}, "profile", "sketch_profile")
    n_close_disc = _node("n_close_disc", "disc_body", "close_profile",
                         [_nref("n_polyline_disc", "profile")], [_out("profile", "profile")],
                         {}, "profile", "sketch_profile")
    # 盘体过渡圆角：complex_rim 的 web-rim 过渡由插入点表达 → 仅 hub-web 圆角（索引 2/n_pts-3）；
    # 非 complex_rim 保持 4 圆角（hub-web 2 处 + web-rim 2 处，索引 2/3/n_pts-4/n_pts-3）。
    is_complex = params.get("category") == "complex_rim"
    n_pts = len(dp["points"])
    fillet_vidx = (2, n_pts - 3) if is_complex else (2, 3, n_pts - 4, n_pts - 3)
    disc_fillets = []
    cur = "n_close_disc"
    for i, vidx in enumerate(fillet_vidx):
        fid = f"n_fillet_disc_{i}"
        radius = 12.0 if is_complex else params.get("disc_fillet_mm", 10.0)
        fil = _node(fid, "disc_body", "fillet_sketch", [_nref(cur, "profile")],
                    [_out("profile", "profile")],
                    {"radius_mm": radius, "at_vertex_index": [vidx]},
                    "edge_treatment", "sketch_profile")
        disc_fillets.append(fil)
        cur = fid
    n_disc_revolve = _node("n_disc_revolve", "disc_body", "revolve_profile",
                           [_nref(cur, "profile")], [_out("body", "solid")],
                           {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile")
    disc_nodes = ([n_sketch_disc, n_polyline_disc, n_close_disc] + disc_fillets
                  + [n_disc_revolve])

    cutter_nodes = _slot_cutter_nodes(teeth, slots, depth, throat, fr, R,
                                      params.get("axial_depth_mm", 80.0),
                                      params.get("tfa_deg", 80.0),
                                      params.get("ufa_deg", 70.0))
    n_cutter_extrude = cutter_nodes[-1]

    # assembly：周向阵列 + 布尔切除
    n_pattern = _node("n_pattern_cutters", "__assembly__", "circular_pattern_component",
                      [_nref("n_cutter_extrude", "body")], [_out("body", "solid")],
                      {"count": slots, "radius_mm": R, "axis": "Z",
                       "start_angle_deg": 0, "rotate_copies": True},
                      "pattern", "composition")
    n_final_cut = _node("n_final_cut", "__assembly__", "boolean_cut",
                        [_nref("n_disc_revolve", "body"), _nref("n_pattern_cutters", "body")],
                        [_out("body", "solid")],
                        {"clean_after": True}, "boolean", "composition")

    return {
        "document_id": f"tpl_slot_{params.get('_tag', 'ref')}",
        "part_name": "HP_Turbine_Disc_RefGeo",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": [
            {"id": "disc_body", "owner_dialect": "sketch_profile",
             "kind_hint": "axisymmetric_disc", "root_node": "n_disc_revolve"},
            {"id": "slot_cutter", "owner_dialect": "sketch_profile",
             "kind_hint": "fir_tree_slot_cutter", "root_node": "n_cutter_extrude"},
            {"id": "__assembly__", "owner_dialect": "composition",
             "kind_hint": "assembly", "root_node": "n_final_cut"},
        ],
        "nodes": (disc_nodes + cutter_nodes + [n_pattern, n_final_cut]),
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_slot_{teeth}tooth_{slots}slots"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 盘型模板（axisymmetric 单组件：revolve → bore → groove/hole pattern → chamfer）
# ═══════════════════════════════════════════════════════════════════════════════

def _axisym_stations(od_mm, bore_mm, thick_mm) -> list:
    """盘体 profile_stations（3 站 hub/web/rim，Z 区间相接不重叠——axisymmetric 要求）。

    每站恒定 r：hub 段 r=hub_r、web 段 r=(hub_r+rim_junc)/2、rim 段 r=rim_r。
    """
    rim_r = od_mm / 2.0
    bore_r = bore_mm / 2.0
    hub_r = bore_r + _clamp(0.16 * od_mm, 25.0, 100.0)
    rim_junc = rim_r - _clamp(0.12 * od_mm, 25.0, 95.0)
    if hub_r >= rim_junc:
        hub_r = (bore_r + rim_junc) / 2.0
    web_r = (hub_r + rim_junc) / 2.0
    z = thick_mm / 2.0
    z1 = round(z * 0.4, 3)
    z2 = round(z * 0.7, 3)
    return [
        {"r_mm": round(hub_r, 3), "z_front_mm": 0.0, "z_rear_mm": z1},
        {"r_mm": round(web_r, 3), "z_front_mm": z1, "z_rear_mm": z2},
        {"r_mm": round(rim_r, 3), "z_front_mm": z2, "z_rear_mm": z},
    ]


def _sketch_disc_body(params: dict) -> list:
    """sketch_profile 盘体组件：12 点轮廓 + 4 fillet + revolve（参考 mon_e2b035beb218）。
    顶点 2/9(hub-web) fillet r=12，3/8(web-rim) fillet r=10。
    有环槽时 web-rim fillet 减到 r=4（释放轮缘内壁轴向空间——否则 r=10 fillet 弧
    覆盖内壁 z∈±(web_outer~web_outer+10)，环槽无法从内壁表面开口且避开 fillet）。
    """
    thick = params["thick_mm"]
    hub_half = params.get("hub_mm", round(thick * 0.5, 1))
    rim_half = params.get("rim_mm", round(thick * 0.4, 1))
    dp = disc_profile(params["od_mm"], params["bore_mm"], hub_half, rim_half, thick,
                      form=params.get("form", "standard"))
    nodes = [
        _node("n_disc_sketch", "disc_body", "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XZ", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node("n_disc_polyline", "disc_body", "add_polyline", [_nref("n_disc_sketch", "sketch")],
              [_out("profile", "profile")], {"points": dp["points"]}, "profile", "sketch_profile"),
        _node("n_disc_close", "disc_body", "close_profile",
              [_nref("n_disc_polyline", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
    ]
    cur = "n_disc_close"
    n_grooves = int(params.get("grooves") or 0)
    # web-rim fillet（顶点 3=下半/8=上半，r=10）按环槽位置取舍：
    #   grooves=0 —— 两侧都保留（(2,3,8,9)）
    #   grooves=1 —— 单道卡环槽在下端面（z<0），切除侧取消下半 web-rim fillet（顶点 3），
    #                 未切除的上端面保留圆角（顶点 8）——fillet 弧与上端面无环槽交互。
    #   grooves≥2 —— 上下两端面各一道环槽，两侧都切除 → web-rim fillet 全取消
    #                 （否则 fillet 圆角环面与环槽开口交互产生旋转成形残留）。
    if n_grooves >= 2:
        _fillet_vidx = (2, 9)
    elif n_grooves == 1:
        _fillet_vidx = (2, 8, 9)
    else:
        _fillet_vidx = (2, 3, 8, 9)
    for i, vidx in enumerate(_fillet_vidx):
        fid = f"n_disc_fillet_{i}"
        r = 12.0 if vidx in (2, 9) else 10.0
        nodes.append(_node(fid, "disc_body", "fillet_sketch", [_nref(cur, "profile")],
                          [_out("profile", "profile")],
                          {"radius_mm": r, "at_vertex_index": [vidx]},
                          "edge_treatment", "sketch_profile"))
        cur = fid
    nodes.append(_node("n_disc_revolve", "disc_body", "revolve_profile",
                      [_nref(cur, "profile")], [_out("body", "solid")],
                      {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile"))
    return nodes


def _hole_cutter(comp_id: str, hole_dia_mm: float) -> list:
    """孔切割组件：XY 正 16 边形(近似圆) polyline → close → extrude（单孔；周向阵列在 assembly）。

    用 add_polyline 多边形近似圆（add_circle 的 spec input_types=["profile"] 与 sketch 输入不匹配，
    会被 strip_passthrough_nodes 误删）。16 边形对孔径 4-26mm 误差 <2%，足够。
    """
    r = hole_dia_mm / 2.0
    n_sides = 16
    pts = [{"x_mm": round(r * math.cos(2 * math.pi * i / n_sides), 3),
            "y_mm": round(r * math.sin(2 * math.pi * i / n_sides), 3)}
           for i in range(n_sides)]
    return [
        _node(f"{comp_id}_sketch", comp_id, "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XY", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node(f"{comp_id}_poly", comp_id, "add_polyline", [_nref(f"{comp_id}_sketch", "sketch")],
              [_out("profile", "profile")], {"points": pts}, "profile", "sketch_profile"),
        _node(f"{comp_id}_close", comp_id, "close_profile",
              [_nref(f"{comp_id}_poly", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
        _node(f"{comp_id}_extrude", comp_id, "extrude_profile",
              [_nref(f"{comp_id}_close", "profile")], [_out("body", "solid")],
              {"depth_mm": 800.0, "direction": "both"}, "feature", "sketch_profile"),
    ]


def _ring_cutter(comp_id: str, inner_dia_mm: float, outer_dia_mm: float,
                 depth_mm: float, z_base_mm: float) -> list:
    """环形切割组件（环槽/环形腔，旋转切除）：XZ 矩形环截面 revolve → 环形切割体。"""
    r_in, r_out = inner_dia_mm / 2.0, outer_dia_mm / 2.0
    pts = [{"x_mm": round(r_in, 3), "y_mm": round(z_base_mm, 3)},
           {"x_mm": round(r_out, 3), "y_mm": round(z_base_mm, 3)},
           {"x_mm": round(r_out, 3), "y_mm": round(z_base_mm + depth_mm, 3)},
           {"x_mm": round(r_in, 3), "y_mm": round(z_base_mm + depth_mm, 3)}]
    return [
        _node(f"{comp_id}_sketch", comp_id, "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XZ", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node(f"{comp_id}_poly", comp_id, "add_polyline", [_nref(f"{comp_id}_sketch", "sketch")],
              [_out("profile", "profile")], {"points": pts}, "profile", "sketch_profile"),
        _node(f"{comp_id}_close", comp_id, "close_profile",
              [_nref(f"{comp_id}_poly", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
        _node(f"{comp_id}_revolve", comp_id, "revolve_profile",
              [_nref(f"{comp_id}_close", "profile")], [_out("body", "solid")],
              {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile"),
    ]


def _rim_slot_cutter(comp_id: str, rim_r: float, rs_depth_mm: float,
                     rs_half_width_mm: float) -> list:
    """径向切槽切割组件：XY 槽截面 polyline + extrude（槽口在轮缘外表面 rim_r）。

    U 形槽底（半圆弧逼近，替代矩形尖底——用户反馈"直接用矩形切的槽"不真实）：
    直壁到 rim_r−rs_depth，底部圆弧下沉 arc_r（圆心向盘内），截面 5 点。
    """
    w = rs_half_width_mm
    arc_r = min(max(w * 0.6, 1.0), 0.4 * rs_depth_mm)  # 槽底圆弧半径（计入总深）
    pts = [{"x_mm": round(rim_r, 3), "y_mm": round(w, 3)},
           {"x_mm": round(rim_r - rs_depth_mm, 3), "y_mm": round(w, 3)},
           {"x_mm": round(rim_r - rs_depth_mm - arc_r, 3), "y_mm": 0.0},
           {"x_mm": round(rim_r - rs_depth_mm, 3), "y_mm": round(-w, 3)},
           {"x_mm": round(rim_r, 3), "y_mm": round(-w, 3)}]
    return [
        _node(f"{comp_id}_sketch", comp_id, "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XY", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node(f"{comp_id}_poly", comp_id, "add_polyline", [_nref(f"{comp_id}_sketch", "sketch")],
              [_out("profile", "profile")], {"points": pts}, "profile", "sketch_profile"),
        _node(f"{comp_id}_close", comp_id, "close_profile",
              [_nref(f"{comp_id}_poly", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
        _node(f"{comp_id}_extrude", comp_id, "extrude_profile",
              [_nref(f"{comp_id}_close", "profile")], [_out("body", "solid")],
              {"depth_mm": 800.0, "direction": "both"}, "feature", "sketch_profile"),
    ]


def _asm_pattern(nid: str, cutter_body: str, count: int, radius_mm: float, asm_nodes: list) -> str:
    """composition circular_pattern（周向阵列），返回 pattern 节点 id。"""
    asm_nodes.append(_node(nid, "__assembly__", "circular_pattern_component",
                          [_nref(cutter_body, "body")], [_out("body", "solid")],
                          {"count": count, "radius_mm": round(radius_mm, 3), "axis": "Z",
                           "start_angle_deg": 0, "rotate_copies": True},
                          "pattern", "composition"))
    return nid


def _asm_bool(nid: str, target_body: str, tool_body: str, asm_nodes: list) -> str:
    """composition boolean_cut（target - tool），返回新 body 节点 id。"""
    asm_nodes.append(_node(nid, "__assembly__", "boolean_cut",
                          [_nref(target_body, "body"), _nref(tool_body, "body")],
                          [_out("body", "solid")], {"clean_after": True},
                          "boolean", "composition"))
    return nid


def build_axisym_disc(params: dict) -> dict:
    """盘型（基础/孔/环槽减重）llm_raw — sketch_profile 盘体 + 特征切割组件 + composition。

    与参考 mon_e2b035beb218 同架构：盘体 12 点轮廓 + fillet + revolve；
    孔/环槽/减重孔/冷却孔/切槽/环形腔用独立 sketch_profile 切割组件（切除/旋转切除）+ composition 布尔。
    """
    od, bore = params["od_mm"], params["bore_mm"]
    _r = _disc_radii(od, bore, params.get("form", "standard"))
    rim_r, rim_junc, hub_r, web_r = _r["rim_r"], _r["rim_junc"], _r["hub_r"], _r["web_r"]
    rim_half = params.get("rim_mm", 30.0)

    disc_nodes = _sketch_disc_body(params)
    comps = [{"id": "disc_body", "owner_dialect": "sketch_profile",
              "kind_hint": "turbine_disc", "root_node": "n_disc_revolve"}]
    all_nodes = list(disc_nodes)
    asm_nodes = []
    cur_body = "n_disc_revolve"

    def feat_comp(cid: str, root: str):
        comps.append({"id": cid, "owner_dialect": "sketch_profile",
                      "kind_hint": None, "root_node": root})

    # 安装孔阵列（XY 单孔 cutter + 周向 pattern + 布尔）
    if params.get("holes"):
        cid = "feat_holes"
        feat_comp(cid, f"{cid}_extrude")
        all_nodes += _hole_cutter(cid, params["hdia_mm"])
        n_pat = _asm_pattern("n_pat_holes", f"{cid}_extrude", int(params["holes"]),
                             params["pcd_mm"], asm_nodes)
        cur_body = _asm_bool("n_bool_holes", cur_body, n_pat, asm_nodes)
    # 减重孔阵列（腹板大孔）
    if params.get("lh_holes"):
        cid = "feat_lh"
        feat_comp(cid, f"{cid}_extrude")
        all_nodes += _hole_cutter(cid, params["lh_hdia_mm"])
        n_pat = _asm_pattern("n_pat_lh", f"{cid}_extrude", int(params["lh_holes"]),
                             params["lh_pcd_mm"], asm_nodes)
        cur_body = _asm_bool("n_bool_lh", cur_body, n_pat, asm_nodes)
    # 冷却孔阵列（小孔，支持双排）
    if params.get("cl_holes"):
        for k, cl_pcd in enumerate((params["cl_pcd_mm"], params.get("cl_pcd2_mm"))):
            if not cl_pcd:
                break
            cid = f"feat_cl_{k}"
            feat_comp(cid, f"{cid}_extrude")
            all_nodes += _hole_cutter(cid, params["cl_hdia_mm"])
            n_pat = _asm_pattern(f"n_pat_cl_{k}", f"{cid}_extrude", int(params["cl_holes"]),
                                 cl_pcd, asm_nodes)
            cur_body = _asm_bool(f"n_bool_cl_{k}", cur_body, n_pat, asm_nodes)
    # 环槽（collar 卡环槽 / mid 中段集气环槽——旋转切除，从轮缘内壁表面向 +r 挖 gd 深）。
    # 盘体 web-rim fillet 已在 _sketch_disc_body 取消（有环槽时）→ 无 fillet 环面可残留。
    # 截面 [r ∈ rim_junc, rim_junc+gd] × [z ∈ z_c−gw/2, z_c+gw/2]。
    # collar（卡环/封严槽，US4247257）z_c 靠轮缘下端面；mid（冷却集气）z_c 中段。
    if params.get("grooves"):
        n = int(params["grooves"])
        gw = params.get("gw_mm", 14.0)
        gd = params.get("gd_mm", 8.0)
        gtype = params.get("groove_type", "collar")  # 默认卡环槽（用户决策：集气槽全部停用）
        margin = 3.0
        # web_outer（web-rim 交界 z）——collar 卡环槽紧贴该处
        _dp = disc_profile(params["od_mm"], params["bore_mm"], params.get("hub_mm", 38),
                           params.get("rim_mm", 30), params["thick_mm"],
                           form=params.get("form", "standard"))
        wb = _dp["params"]["web_outer_half_mm"]
        if params.get("form") == "conical":
            # conical 盘体 web-rim 交界半厚 = wo_cone（disc_profile rim 侧用 wo_cone，
            # 非 web_outer）——collar 卡环槽须贴该真实交界，否则环槽下缘与 WEB 之间留隙
            # （此前用 web_outer=15 而实际交界 z=-wo_cone，D14 环槽悬空 3mm）。
            wb = _clamp(0.4 * params.get("rim_mm", 30.0), 8.0, 24.0)
        if gtype == "collar":
            # 卡环槽：紧贴 web-rim 交界（槽下/上缘与 WEB 相接），向端面方向开槽。
            # 单道 → 下端面一侧（未切除的上端面保留 web-rim fillet，_sketch_disc_body）；
            # 多道 → 上下端面对称各一道（两侧都切除，两侧都无 fillet）。
            A = wb + gw / 2.0  # 槽中心贴 web 交界（z=∓A → 槽内缘 z=∓wb）
            z_cs = [-A] if n == 1 else [A * (2.0 * i / (n - 1) - 1.0) for i in range(n)]
        else:
            # 中段集气环槽：轴向中段，z 避开 web 交界 ±web_edge（否则环槽口与 web 交界
            # 几乎重合 → 布尔退化小边，D14 曾 r=220 z=-12 小边）
            if params.get("form") == "conical":
                web_edge = _clamp(0.4 * rim_half, 8.0, 24.0)  # wo_cone（conical web 交界）
            else:
                web_edge = _dp["params"]["web_outer_half_mm"]
            z_lo = -web_edge + 2.0 + gw / 2.0
            z_hi = +web_edge - 2.0 - gw / 2.0
            if z_hi <= z_lo:
                z_lo, z_hi = -gw / 2.0, gw / 2.0
            z_cs = [0.0] if n == 1 \
                else [z_lo + (z_hi - z_lo) * i / (n - 1) for i in range(n)]
        # 环槽从轮缘内壁表面开口（r=rim_junc）向 +r 挖。
        # mid 集气槽 = 轮缘内壁**浅环形槽**（深度 ≤3mm 引导冷却空气，不深挖进轮缘实体——
        # 真实集气腔是盘端面+静止件围成的轴向空腔，单盘用浅槽表达）；
        # collar 卡环槽 = gd 全深（卡挡环需要）。
        g_use = min(gd, 3.0) if gtype != "collar" else gd
        for i, z_c in enumerate(z_cs):
            cid = f"feat_groove_{i}"
            feat_comp(cid, f"{cid}_revolve")
            all_nodes += _ring_cutter(cid, 2.0 * rim_junc, 2.0 * (rim_junc + g_use),
                                      gw, z_c - gw / 2.0)
            cur_body = _asm_bool(f"n_bool_groove_{i}", cur_body, f"{cid}_revolve", asm_nodes)
    # 径向局部切槽（轮缘外表面周向矩形槽）
    if params.get("rs_count"):
        cid = "feat_rimslot"
        feat_comp(cid, f"{cid}_extrude")
        all_nodes += _rim_slot_cutter(cid, rim_r, params["rs_depth_mm"], params["rs_half_width_mm"])
        n_pat = _asm_pattern("n_pat_rimslot", f"{cid}_extrude", int(params["rs_count"]),
                             rim_r, asm_nodes)
        cur_body = _asm_bool("n_bool_rimslot", cur_body, n_pat, asm_nodes)
    # 腹板环形腔（旋转切除：从腹板中心面向 +Z 切 cavity_depth，不切穿）
    if params.get("cavity_width_mm") and params.get("cavity_depth_mm"):
        cid = "feat_cavity"
        feat_comp(cid, f"{cid}_revolve")
        cw = params["cavity_width_mm"]
        cd = params["cavity_depth_mm"]
        cav_inner = max(2.0 * (web_r - cw / 2.0), bore + 2.0)
        cav_outer = min(2.0 * (web_r + cw / 2.0), 2.0 * rim_junc - 2.0)
        if cav_outer > cav_inner:
            all_nodes += _ring_cutter(cid, cav_inner, cav_outer, cd, 0.0)
            cur_body = _asm_bool("n_bool_cavity", cur_body, f"{cid}_revolve", asm_nodes)

    final = cur_body
    if asm_nodes:
        comps.append({"id": "__assembly__", "owner_dialect": "composition",
                      "kind_hint": "assembly", "root_node": final})
    all_nodes += asm_nodes
    return {
        "document_id": f"tpl_axisym_{params.get('_tag', 'ref')}",
        "part_name": "Reference_Disc",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": comps, "nodes": all_nodes,
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_axisym_{params.get('_tag', 'ref')}"},
    }


def build_coupled_disc(params: dict) -> dict:
    """榫槽+孔阵列+环槽耦合盘：sketch 盘体+特征（build_axisym_disc）+ 榫槽 cutter + composition。"""
    disc = build_axisym_disc(params)
    all_nodes = list(disc["nodes"])
    comps = list(disc["components"])
    # 盘体+特征布尔后的 final body = assembly 组件 root_node；无特征（无 assembly）时 = 盘体 revolve
    disc_final = next((c["root_node"] for c in comps if c["id"] == "__assembly__"),
                      "n_disc_revolve")
    teeth = int(params.get("teeth", 2))
    slots = int(params.get("slots", 60))
    depth = params.get("depth_mm", 24.0)
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    rim_r = params["od_mm"] / 2.0
    R = rim_r  # 槽口在轮缘外表面（R_mm 为分布半径，节距约束/标注用，不移动槽口）
    cutter_nodes = _slot_cutter_nodes(teeth, slots, depth, throat, fr, R,
                                      params.get("axial_depth_mm", 80.0),
                                      params.get("tfa_deg", 80.0),
                                      params.get("ufa_deg", 70.0))
    all_nodes += cutter_nodes
    n_pattern = _node("n_pattern_cutters", "__assembly__", "circular_pattern_component",
                      [_nref("n_cutter_extrude", "body")], [_out("body", "solid")],
                      {"count": slots, "radius_mm": R, "axis": "Z",
                       "start_angle_deg": 0, "rotate_copies": True},
                      "pattern", "composition")
    n_final_cut = _node("n_final_cut", "__assembly__", "boolean_cut",
                        [_nref(disc_final, "body"), _nref("n_pattern_cutters", "body")],
                        [_out("body", "solid")], {"clean_after": True},
                        "boolean", "composition")
    all_nodes += [n_pattern, n_final_cut]
    comps.append({"id": "slot_cutter", "owner_dialect": "sketch_profile",
                  "kind_hint": "fir_tree_slot_cutter", "root_node": "n_cutter_extrude"})
    asm = next((c for c in comps if c["id"] == "__assembly__"), None)
    if asm is None:
        # 盘体无孔/环槽特征时 build_axisym_disc 不建 assembly → 补建
        comps.append({"id": "__assembly__", "owner_dialect": "composition",
                      "kind_hint": "assembly", "root_node": "n_final_cut"})
    else:
        asm["root_node"] = "n_final_cut"
    return {
        "document_id": f"tpl_coupled_{params.get('_tag', 'ref')}",
        "part_name": "HP_Turbine_Disc_Coupled",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": comps, "nodes": all_nodes,
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_coupled_{teeth}tooth_{slots}slots"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 分发
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 原生两阶段：plan()（Agent A 规划）→ disc_profile/slot_profile（B/C 轮廓）→ assemble
# ═══════════════════════════════════════════════════════════════════════════════

_KIND_HINT_MAP = {"axisymmetric_disc": "turbine_disc", "fir_tree_slot_cutter": "fir_tree_cutter"}
SLOT_CATS = ("slot", "coupled", "complex_rim")


def _skeletonize(raw: dict) -> dict:
    """完整 llm_raw → 骨架（Agent A 的 gcad_skeleton）：
    kind_hint 组件（盘体/榫槽 cutter）的 add_polyline 占位 2 点（由 assemble 按 B/C 轮廓填充）；
    无 kind_hint 的特征切割组件（孔/环槽/切槽）保留模板算好的最终坐标。
    kind_hint 改 agentic_l2 契约（turbine_disc/fir_tree_cutter）。"""
    skel = copy.deepcopy(raw)
    comp_hints = {}
    for c in skel.get("components", []):
        kh = c.get("kind_hint")
        c["kind_hint"] = _KIND_HINT_MAP.get(kh, kh)
        comp_hints[c.get("id")] = c["kind_hint"]
    for n in skel.get("nodes", []):
        if n.get("op") == "add_polyline" and comp_hints.get(n.get("component")):
            n["params"]["points"] = [{"x_mm": 0, "y_mm": 0}, {"x_mm": 1, "y_mm": 1}]
    return skel


def _disc_params(params: dict) -> dict:
    """候选参数 → Agent A disc profile 参数（AGENT_A_ADDENDUM 契约）。"""
    d = {
        "outer_diameter_mm": params.get("od_mm"), "bore_diameter_mm": params.get("bore_mm"),
        "axial_thickness_mm": params.get("thick_mm"),
        "hub_half_thickness_mm": params.get("hub_mm"), "rim_half_thickness_mm": params.get("rim_mm"),
        "hub_web_fillet_mm": params.get("disc_fillet_mm", 10.0),
        "web_rim_fillet_mm": params.get("disc_fillet_mm", 10.0),
    }
    if params.get("category") == "complex_rim":
        # 复杂轮缘：曲线过渡由 disc_profile 插入点表达（论文 2.1，transition 类型族间不同）
        d["rim_transition_radius_mm"] = params.get("rim_arc_radius_mm", 20.0)
        d["rim_transition_type"] = params.get("transition", "s_curve")
    return d


def _slot_params(params: dict) -> dict:
    """候选参数 → Agent C slot profile 参数（AGENT_A_ADDENDUM 契约）。"""
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    return {
        "teeth_count": params.get("teeth"), "slots": params.get("slots"),
        "slot_depth_mm": params.get("depth_mm"),
        "mouth_half_width_mm": throat, "neck_half_width_mm": round(1.1 * throat, 3),
        "lobe_half_width_mm": round(2.25 * throat, 3),
        "bottom_half_width_mm": round(0.875 * throat, 3),
        "tfa_deg": params.get("tfa_deg", 80.0), "ufa_deg": params.get("ufa_deg", 70.0),
        "root_fillet_mm": fr, "bottom_fillet_mm": round(0.8 * fr, 3),
    }


def _skeleton(params: dict) -> dict:
    """Agent A 的 gcad_skeleton：按 category 生成骨架节点（points 占位 + kind_hint 契约）。"""
    cat = params.get("category")
    if cat == "coupled":
        raw = build_coupled_disc(params)
    elif cat in ("slot", "complex_rim"):
        raw = build_slot_disc(params)
    else:
        raw = build_axisym_disc(params)
    return _skeletonize(raw)


def plan(params: dict) -> dict:
    """Agent A 输出：AgentDesignPlan（gcad_skeleton 骨架 + profiles 参数声明）。

    build() 的第一阶段。profiles 参数是 Agent B/C 的输入（参数 → 轮廓点）。
    """
    cat = params.get("category")
    skel = _skeleton(params)
    profiles = [{"profile_id": "disc_polyline", "kind": "disc",
                 "params": _disc_params(params)}]
    if cat in SLOT_CATS:
        profiles.append({"profile_id": "cutter_polyline", "kind": "slot",
                         "params": _slot_params(params)})
    return {"gcad_skeleton": skel, "profiles": profiles}


def build(params: dict) -> dict:
    """原生两阶段：plan()（Agent A）→ disc_profile/slot_profile（B/C）→ assemble。

    所有盘类盘体统一 sketch_profile add_polyline（12 点），assemble 按 kind_hint
    （turbine_disc/fir_tree_cutter）填充 points；特征切割组件的 add_polyline（kind_hint=None）
    保留模板坐标。不再区分 SLOT_CATS（axisym profile_stations 已废弃）。
    """
    from agentic_l2 import assemble
    ap = plan(params)
    points = {}
    for prof in ap["profiles"]:
        pid = prof["profile_id"]
        if prof["kind"] == "disc":
            points[pid] = disc_profile(params["od_mm"], params["bore_mm"],
                                       params.get("hub_mm", 38), params.get("rim_mm", 30),
                                       params["thick_mm"],
                                       form=params.get("form", "standard"),
                                       transition=params.get("transition", "linear"))["points"]
        elif prof["kind"] == "slot":
            teeth = int(params.get("teeth", 2))
            depth = params.get("depth_mm", 24.0)
            throat = params.get("throat_half_width_mm", 4.0)
            neck = round(1.1 * throat, 3)
            lobe = round(2.25 * throat, 3)
            bottom = round(0.875 * throat, 3)
            points[pid] = slot_profile(teeth, depth, throat, neck, lobe, bottom,
                                       params.get("tfa_deg", 80.0), params.get("ufa_deg", 70.0))
    return assemble(ap["gcad_skeleton"], ap["profiles"], points)


# 演示参数
DEMO_SLOT = {"category": "slot", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
             "hub_mm": 38, "rim_mm": 30, "slots": 60, "teeth": 2, "R_mm": 215,
             "depth_mm": 24, "throat_half_width_mm": 4.0, "fr_mm": 1.0, "_tag": "demo"}
DEMO_HOLE = {"category": "hole", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
             "holes": 16, "pcd_mm": 180, "hdia_mm": 14, "_tag": "demo_hole"}
DEMO_GROOVE = {"category": "groove", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
               "grooves": 2, "gw_mm": 14, "gd_mm": 8, "_tag": "demo_groove"}
DEMO_GROOVE_LH = {"category": "groove", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
                  "grooves": 1, "gw_mm": 12, "gd_mm": 8,
                  "lh_holes": 12, "lh_pcd_mm": 175, "lh_hdia_mm": 16,
                  "cl_holes": 24, "cl_pcd_mm": 225, "cl_hdia_mm": 6, "cl_pcd2_mm": 240,
                  "rs_count": 60, "rs_depth_mm": 10, "rs_half_width_mm": 3.0,
                  "cavity_width_mm": 40, "cavity_depth_mm": 4.0, "_tag": "demo_groove_lh"}
DEMO_COMPLEX = {"category": "complex_rim", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
                "hub_mm": 38, "rim_mm": 30, "slots": 60, "teeth": 3, "R_mm": 225,
                "depth_mm": 32, "throat_half_width_mm": 4.0, "fr_mm": 1.0,
                "rim_arc_radius_mm": 20.0, "_tag": "demo_complex"}


if __name__ == "__main__":
    for name, p in (("slot", DEMO_SLOT), ("hole", DEMO_HOLE), ("groove", DEMO_GROOVE),
                    ("groove_lh", DEMO_GROOVE_LH), ("complex", DEMO_COMPLEX)):
        doc = build(p)
        print(f"[{name}] nodes={len(doc['nodes'])} comps={len(doc['components'])} OK")
