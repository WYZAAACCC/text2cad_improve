"""榫槽 LLM 生成 vs 确定性生成器 迭代对比实验。

目标：参数化 prompt → LLM 生成的槽轮廓点，与确定性生成器(fir_tree_parametric.py)
逐点对比，迭代 prompt 直到高概率完全一致。

用法:
  .conda/python.exe _param_experiment/llm_slot_iteration.py --combos T03,T02 --round v1
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from fir_tree_parametric import FirTreeParams, generate_profile

OUT = Path(__file__).resolve().parent / "output" / "llm_slot_rounds"
OUT.mkdir(parents=True, exist_ok=True)

MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")


# ── Prompt 模板（迭代更新）──────────────────────────────────────────────────

PROMPT_V2 = """\
你是枞树形榫槽轮廓的精确计算器。必须【精确使用给定参数值】，用给出的 tan 值做乘法/除法，绝不用视觉近似、绝不取整。

【坐标系】x=径向(mm)，0=轮缘表面，负=向圆心；y=切向半宽。关于 y=0 对称，先上侧后下侧镜像。

【给定参数（必须原样使用，不得近似）】
teeth_count={teeth_count}
tooth_height={tooth_height}          # 每齿 y 方向凸出高度
tooth_thickness={tooth_thickness}
top_flank_angle={top_flank}          # 度
under_flank_angle={under_flank}      # 度
neck_half_width={neck}               # 长度 teeth_count+1，第一齿根 y=neck[0]，最后颈部 y=neck[-1]
neck_platform={neck_platform}
mouth_half_width={mouth}
mouth_wedge_dx={mouth_dx}
bottom_half_width={bottom}
bottom_platform={bottom_platform}
bottom_flare_angle={flare}

【预计算 tan 值（直接用，别自己算）】
{tan_table}

【生成步骤（上侧）】
第0步: x = -mouth_wedge_dx（第一个齿根 x）。点[1]=(x, neck[0])；点[0]=(0, mouth_half_width)。

对每齿 i=0..teeth_count-1：
  w_neck_i = neck[i]                        # 必须用给定值
  w_tip = w_neck_i + tooth_height[i]
  dx_work = tooth_height[i] / tan_top[i]    # tan_top 用上表
  x_tip = x - dx_work
  x_tip_end = x_tip - tooth_thickness[i]
  若 i < teeth_count-1：
    w_next = neck[i+1]
    dx_back = (tooth_height[i] + w_neck_i - w_next) / tan_under[i]
    x_next = x_tip_end - dx_back
    x_work = x_next - neck_platform
    输出4点: 外斜面起点(x, w_neck_i), 外斜面顶(x_tip, w_tip), 齿顶平台端(x_tip_end, w_tip), 内斜面端(x_next, w_next), 连接线端(x_work, w_next)
    x = x_work
  否则（最后一个齿）：
    w_last = neck[i+1]
    dx_back = (tooth_height[i] + w_neck_i - w_last) / tan_under[i]
    x_next = x_tip_end - dx_back
    x_work = x_next - neck_platform
    输出: 外斜面起点(x, w_neck_i), 外斜面顶(x_tip, w_tip), 齿顶平台端(x_tip_end, w_tip), 内斜面端(x_next, w_last), 连接线端(x_work, w_last)
    # 底部
    dx_flare = (bottom - w_last) / tan(radians(bottom_flare_angle))  → 用近似: (bottom - w_last) / tan_bottom
    x_bottom = x_work - dx_flare
    输出: 槽底(x_bottom, bottom), 槽底平台端(x_bottom - bottom_platform, bottom), 根部(x_bottom - bottom_platform - 1.0, bottom - 1.5)

【下侧】上侧所有点 (x,y)→(x, -y)，顺序反转。

【输出】slot_points 数组，按上侧(口部→根部) + 下侧(根部→口部) 顺序，坐标保留 3 位小数。
"""


def _tan_table(p: FirTreeParams) -> str:
    import math
    lines = []
    for i in range(p.teeth_count):
        t_top = math.tan(math.radians(p.top_flank_angle_deg[i]))
        t_under = math.tan(math.radians(p.under_flank_angle_deg[i]))
        lines.append(f"  齿{i}: tan_top={t_top:.6f} (用于外斜面), tan_under={t_under:.6f} (用于内斜面)")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    lines.append(f"  底部外扩: tan_bottom={t_bottom:.6f}")
    return "\n".join(lines)


def build_prompt_v2(p: FirTreeParams) -> str:
    return PROMPT_V2.format(
        teeth_count=p.teeth_count,
        tooth_height=p.tooth_height_mm,
        tooth_thickness=p.tooth_thickness_mm,
        top_flank=p.top_flank_angle_deg,
        under_flank=p.under_flank_angle_deg,
        neck=p.neck_half_width_mm,
        neck_platform=p.neck_platform_mm,
        mouth=p.mouth_half_width_mm,
        mouth_dx=p.mouth_wedge_dx_mm,
        bottom=p.bottom_half_width_mm,
        bottom_platform=p.bottom_platform_mm,
        flare=p.bottom_flare_angle_deg,
        tan_table=_tan_table(p),
    )

PROMPT_V1 = """\
你是枞树形榫槽轮廓的精确参数化生成器。请根据给定参数，严格按几何规则计算出槽截面轮廓点。

【坐标系】x=径向(mm)，x=0 为轮缘表面，x<0 指向圆心；y=切向半宽(mm)。轮廓关于 y=0 对称，先输出上侧(y≥0)再输出下侧(y≤0 镜像)。

【给定参数】
teeth_count={teeth_count}
tooth_height={tooth_height}          # 每齿 y 方向凸出高度（w_tip = w_neck + tooth_height[i]）
tooth_thickness={tooth_thickness}    # 每齿齿顶平台 x 宽
top_flank_angle={top_flank}          # 每齿外斜面与径向 x 的夹角(度)
under_flank_angle={under_flank}      # 每齿内斜面与径向 x 的夹角(度)
neck_half_width={neck}               # 颈部半宽（长度 teeth_count+1）
neck_platform={neck_platform}        # 齿间连接线 x 长
mouth_half_width={mouth}
mouth_wedge_dx={mouth_dx}
bottom_half_width={bottom}
bottom_platform={bottom_platform}
bottom_flare_angle={flare}

【生成规则（上侧）】
1. 点[0]=(0, mouth_half_width)；点[1]=(-mouth_wedge_dx, neck_half_width[0])
2. 齿根斜线：y_neck(x)=neck[0]+(neck[-1]-neck[0])*(x+mouth_wedge_dx)/(x_last+mouth_wedge_dx)，
   其中 x_last 为最后颈部 x（由布局决定）。为简化，用"逐齿近似"：各齿根 y 依次取 neck_half_width[i]（线性递减已由数组给出）。
3. 对每齿 i（0..teeth_count-1，外→内）：
   - 齿根 x = xr（点[1] 的 x 开始）
   - w_neck_i = neck_half_width[i]
   - w_tip = w_neck_i + tooth_height[i]
   - dx_work = tooth_height[i] / tan(radians(top_flank_angle[i]))
   - x_tip = xr - dx_work
   - x_tip_end = x_tip - tooth_thickness[i]
   - w_next = neck_half_width[i+1]
   - dx_back = (tooth_height[i] + w_neck_i - w_next) / tan(radians(under_flank_angle[i]))
   - x_next = x_tip_end - dx_back
   - x_work = x_next - neck_platform
   - 输出点：
     外斜面起点 (xr, w_neck_i)
     外斜面终点 (x_tip, w_tip)
     齿顶平台终点 (x_tip_end, w_tip)
     内斜面终点 (x_next, w_next)
     连接线终点 (x_work, w_next)     ← 若 i 是最后一个齿，改为 (x_work, 斜线上最后颈部值≈neck[-1])
   - xr = x_work（进入下一齿）
4. 最后一个齿后（底部）：
   - 底部外扩：从 (x_work, neck[-1]) 到 (x_work - (bottom-half-width - neck[-1])/tan(radians(bottom_flare_angle)), bottom_half_width)
   - 槽底平台：继续 x 减 bottom_platform，y=bottom_half_width
   - 根部：(x_bottom_plat - 1.0, bottom_half_width - 1.5)
5. 下侧：上侧所有点 (x,y) → (x, -y)，顺序反转。

【输出】slot_points 数组，元素 {{"x_mm": <值>, "y_mm": <值>}}，按上述顺序（上侧从口部到根部，下侧从根部到口部）。
计算用三角公式精确到 3 位小数。
"""


def build_prompt_v1(p: FirTreeParams) -> str:
    return PROMPT_V1.format(
        teeth_count=p.teeth_count,
        tooth_height=p.tooth_height_mm,
        tooth_thickness=p.tooth_thickness_mm,
        top_flank=p.top_flank_angle_deg,
        under_flank=p.under_flank_angle_deg,
        neck=p.neck_half_width_mm,
        neck_platform=p.neck_platform_mm,
        mouth=p.mouth_half_width_mm,
        mouth_dx=p.mouth_wedge_dx_mm,
        bottom=p.bottom_half_width_mm,
        bottom_platform=p.bottom_platform_mm,
        flare=p.bottom_flare_angle_deg,
    )


SLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "slot_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "x_mm": {"type": "number"},
                    "y_mm": {"type": "number"},
                },
                "required": ["x_mm", "y_mm"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["slot_points"],
    "additionalProperties": False,
}


def call_llm(prompt: str) -> list:
    caller = DeepSeekToolCaller()
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "请按规则生成榫槽轮廓点。"},
    ]
    r = caller.call_strict_tool(
        messages=messages,
        tool_name="emit_slot",
        tool_description="Emit fir-tree slot profile points",
        tool_schema=to_deepseek_strict_schema(SLOT_SCHEMA),
        model_config=MODEL_CONFIG,
    )
    return list(r.arguments.get("slot_points", []))


# ── 对比评估 ────────────────────────────────────────────────────────────────

def compare(gt: list, llm: list) -> dict:
    """逐点对比。返回误差统计。"""
    n_gt, n_llm = len(gt), len(llm)
    if n_gt != n_llm:
        return {"match": False, "reason": f"点数不同: GT={n_gt} LLM={n_llm}",
                "max_dx": None, "max_dy": None, "mean_err": None}
    max_dx = max_dy = 0.0
    total = 0.0
    for g, l in zip(gt, llm):
        dx = abs(g["x_mm"] - l["x_mm"])
        dy = abs(g["y_mm"] - l["y_mm"])
        max_dx = max(max_dx, dx)
        max_dy = max(max_dy, dy)
        total += dx + dy
    mean_err = total / (2 * n_gt)
    # "完全正确" 阈值：0.1mm
    exact = max_dx < 0.1 and max_dy < 0.1
    return {"match": exact, "reason": "", "max_dx": round(max_dx, 3), "max_dy": round(max_dy, 3),
            "mean_err": round(mean_err, 3)}


def plot_compare(gt, llm, name, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, pts, title, col in [(axes[0], gt, "确定性 GT", "#1f77b4"), (axes[1], llm, "LLM 生成", "#d62728")]:
        xs = [pt["x_mm"] for pt in pts] + [pts[0]["x_mm"]]
        ys = [pt["y_mm"] for pt in pts] + [pts[0]["y_mm"]]
        ax.plot(xs, ys, "-o", ms=3, lw=1.2, color=col)
        ax.axhline(0, color="gray", lw=0.5, ls="--")
        ax.set_aspect("equal")
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.3)
    fig.suptitle(name, fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ── 组合定义（复用 test_capability）────────────────────────────────────────

def make_combo(name: str) -> FirTreeParams:
    from test_capability import COMBOS, build
    return build(COMBOS[name])


PROMPT_V3_HEAD = """\
你是枞树形榫槽轮廓的精确生成器。先学习下面的【完整示例】，然后为【新参数】用同样的方法生成轮廓点。
要求：坐标精确到 3 位小数，点数、顺序必须与示例结构完全一致（上侧从口部到根部，下侧镜像从根部到口部）。

【坐标系】x=径向(mm)，0=轮缘表面，负=向圆心；y=切向半宽。关于 y=0 对称。

【完整示例】（teeth_count=2 的完整轮廓）
参数：tooth_height=[5,5], tooth_thickness=[2,2], top_flank_angle=[66.7,66.7], under_flank_angle=[60,60],
      neck_half_width=[2.6,2.3,2.0], neck_platform=2.0, mouth_half_width=4, mouth_wedge_dx=3,
      bottom_half_width=4.0, bottom_platform=2.0, bottom_flare_angle=60
输出 26 点：
[0] (0.000, 4.000)
[1] (-3.000, 2.600)          # 口部楔形→颈部1（齿1根）
[2] (-5.153, 7.600)          # 齿1外斜面顶
[3] (-7.153, 7.600)          # 齿1齿顶平台端
[4] (-10.156, 2.425)         # 齿1内斜面→齿2根（颈部斜线）
[5] (-12.156, 2.375)         # 连接线→齿2根
[6] (-14.309, 7.375)         # 齿2外斜面顶
[7] (-16.309, 7.375)         # 齿2齿顶平台端
[8] (-19.311, 2.200)         # 齿2内斜面→最后颈部
[9] (-21.311, 2.151)         # 连接线→最后颈部
[10] (-22.379, 4.000)        # 底部外扩→槽底
[11] (-24.379, 4.000)        # 槽底平台端
[12] (-25.379, 2.500)        # 根部
[13] (-25.379, -2.500)       # 下侧根部
[14] (-24.379, -4.000)       # 下侧槽底平台
[15] (-22.379, -4.000)       # 下侧底部外扩
[16] (-21.311, -2.151)       # 下侧连接线
[17] (-19.311, -2.200)       # 下侧最后颈部
[18] (-16.309, -7.375)       # 下侧齿2顶
[19] (-14.309, -7.375)       # 下侧齿2平台
[20] (-12.156, -2.375)       # 下侧连接线
[21] (-10.156, -2.425)       # 下侧齿2根
[22] (-7.153, -7.600)        # 下侧齿1顶
[23] (-5.153, -7.600)        # 下侧齿1平台
[24] (-3.000, -2.600)        # 下侧颈部1
[25] (0.000, -4.000)         # 下侧口部

【几何公式】
- 齿顶半宽 w_tip = 颈部半宽 + tooth_height
- 外斜面 x 跨度 dx_work = tooth_height / tan(top_flank_angle)；内斜面 x 跨度 dx_back = (tooth_height + 当前颈部 - 下一颈部) / tan(under_flank_angle)
- 每齿结构：外斜面起点(颈部) → 外斜面顶 → 齿顶平台端 → 内斜面端(下一颈部) → 连接线端(再减 neck_platform)
- 颈部半宽线性：各齿根 y = neck_half_width[i]（数组给定）
- 底部：底部外扩(用 bottom_flare_angle) → 槽底平台 → 根部
- 下侧为精确镜像

【新参数】
{params}

【输出】slot_points 数组（元素为 {{"x_mm": x, "y_mm": y}}），结构、点数与示例一致。
"""


def build_prompt_v3(p: FirTreeParams) -> str:
    params = (
        f"teeth_count={p.teeth_count}\n"
        f"tooth_height={p.tooth_height_mm}\n"
        f"tooth_thickness={p.tooth_thickness_mm}\n"
        f"top_flank_angle={p.top_flank_angle_deg}\n"
        f"under_flank_angle={p.under_flank_angle_deg}\n"
        f"neck_half_width={p.neck_half_width_mm}\n"
        f"neck_platform={p.neck_platform_mm}\n"
        f"mouth_half_width={p.mouth_half_width_mm}\n"
        f"mouth_wedge_dx={p.mouth_wedge_dx_mm}\n"
        f"bottom_half_width={p.bottom_half_width_mm}\n"
        f"bottom_platform={p.bottom_platform_mm}\n"
        f"bottom_flare_angle={p.bottom_flare_angle_deg}"
    )
    return PROMPT_V3_HEAD.format(params=params)


PROMPT_V4 = """\
你是枞树形榫槽轮廓的精确计算器。必须用【给定 tan 值】和【给定参数值】精确计算，不取整、不近似。

【坐标系】x=径向(mm)，0=轮缘表面，负=向圆心；y=切向半宽。关于 y=0 对称：先输出上侧(口部→根部)，再输出下侧(镜像)。

【点数公式】总点数 = 2 × (5 + 4 × teeth_count)。teeth_count=2→26点，3→34点，4→42点。

【给定参数】
teeth_count={teeth_count}
tooth_height={tooth_height}
tooth_thickness={tooth_thickness}
top_flank_angle={top_flank}
under_flank_angle={under_flank}
neck_half_width={neck}             # 长度 teeth_count+1；第 i 齿根 y=neck[i]
neck_platform={neck_platform}
mouth_half_width={mouth}
mouth_wedge_dx={mouth_dx}
bottom_half_width={bottom}
bottom_platform={bottom_platform}
bottom_flare_angle={flare}

【tan 值（直接用，别重算）】
{tan_table}

【计算步骤（上侧）】
点[0] = (0, mouth_half_width)
x = -mouth_wedge_dx；输出点[1] = (x, neck[0])

对每齿 i = 0..teeth_count-1：
  w_neck = neck[i]
  w_tip = w_neck + tooth_height[i]
  dx_work = tooth_height[i] / tan_top[i]
  x_tip = x - dx_work
  x_tip_end = x_tip - tooth_thickness[i]
  若 i < teeth_count-1：
    w_next = neck[i+1]
    dx_back = (tooth_height[i] + w_neck - w_next) / tan_under[i]
    x_next = x_tip_end - dx_back
    x_work = x_next - neck_platform
    输出 5 点: (x, w_neck) (x_tip, w_tip) (x_tip_end, w_tip) (x_next, w_next) (x_work, w_next)
    x = x_work
  否则（最后齿 i=teeth_count-1）：
    w_last = neck[i+1]
    dx_back = (tooth_height[i] + w_neck - w_last) / tan_under[i]
    x_next = x_tip_end - dx_back
    x_work = x_next - neck_platform
    输出 5 点: (x, w_neck) (x_tip, w_tip) (x_tip_end, w_tip) (x_next, w_last) (x_work, w_last)
    # 底部
    dx_flare = (bottom_half_width - w_last) / tan_bottom
    x_bottom = x_work - dx_flare
    输出 3 点: (x_bottom, bottom_half_width) (x_bottom - bottom_platform, bottom_half_width) (x_bottom - bottom_platform - 1.0, bottom_half_width - 1.5)

【下侧】上侧所有点 (x, y) → (x, -y)，顺序反转。

【输出】slot_points 数组，坐标保留 3 位小数。
"""


def build_prompt_v4(p: FirTreeParams) -> str:
    import math
    tan_lines = []
    for i in range(p.teeth_count):
        t_top = math.tan(math.radians(p.top_flank_angle_deg[i]))
        t_under = math.tan(math.radians(p.under_flank_angle_deg[i]))
        tan_lines.append(f"  tan_top[{i}] = {t_top:.6f}   tan_under[{i}] = {t_under:.6f}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    tan_lines.append(f"  tan_bottom = {t_bottom:.6f}")
    return PROMPT_V4.format(
        teeth_count=p.teeth_count,
        tooth_height=p.tooth_height_mm,
        tooth_thickness=p.tooth_thickness_mm,
        top_flank=p.top_flank_angle_deg,
        under_flank=p.under_flank_angle_deg,
        neck=p.neck_half_width_mm,
        neck_platform=p.neck_platform_mm,
        mouth=p.mouth_half_width_mm,
        mouth_dx=p.mouth_wedge_dx_mm,
        bottom=p.bottom_half_width_mm,
        bottom_platform=p.bottom_platform_mm,
        flare=p.bottom_flare_angle_deg,
        tan_table="\n".join(tan_lines),
    )


def _fmt_example(p: FirTreeParams, pts: list) -> str:
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    lines = [f"参数: {params}", f"输出 {len(pts)} 点:"]
    for i, pt in enumerate(pts):
        lines.append(f"[{i}] ({pt['x_mm']:.3f}, {pt['y_mm']:.3f})")
    return "\n".join(lines)


PROMPT_V5 = """\
你是枞树形榫槽轮廓生成器。下面给出 2 齿和 3 齿两个【完整示例】（含参数与全部输出点）。请仔细学习示例的结构规律（口部→每齿[外斜面起点/外斜面顶/齿顶平台端/内斜面端/连接线端]→底部→下侧镜像），然后为【新参数】生成同样结构的轮廓点。

规则要点：
- 总点数 = 2 × (5 + 4 × teeth_count)。齿数每 +1，每侧 +4 点（每齿 5 点含连接线，但首齿起点是口部楔形点）。
- 齿顶半宽 w_tip = 颈部半宽 + tooth_height；外斜面 x 跨度 = tooth_height / tan(top_flank)；内斜面 x 跨度 = (tooth_height + 当前颈部 − 下一颈部) / tan(under_flank)；连接线 x 跨度 = neck_platform。
- 底部：底部外扩(角度 bottom_flare) → 槽底平台(宽 bottom_platform) → 根部。
- 下侧为精确镜像 (x, y)→(x, -y)。
- 坐标保留 3 位小数。

【示例1：2齿】
{example2}

【示例2：3齿】
{example3}

【新参数】
{params}

【输出】slot_points 数组（元素为 {{"x_mm": x, "y_mm": y}}），按上侧(口部→根部)+下侧(根部→口部)顺序。
"""


def build_prompt_v5(p: FirTreeParams) -> str:
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex2_p = _B(_C["T02_2tooth_equal"])
    ex3_p = _B(_C["T03_3tooth_standard"])
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    return PROMPT_V5.format(
        example2=_fmt_example(ex2_p, _gen(ex2_p)),
        example3=_fmt_example(ex3_p, _gen(ex3_p)),
        params=params,
    )


PROMPT_V6 = """\
你是枞树形榫槽轮廓生成器。下面给 2 齿和 3 齿完整示例（参数+全部点），请学习其结构规律，然后为【新参数】生成同样结构的轮廓点。

{example1}

【结构规律】
- 每侧：口部点[0]=(0,mouth), 点[1]=(-mouth_wedge_dx, neck[0])，然后每齿 5 点（外斜面起点/外斜面顶/齿顶平台端/内斜面端/连接线端），最后底部 3 点（槽底/槽底平台端/根部）。下侧镜像。
- 总点数 = 2 × (5 + 4 × teeth_count)。

【精确计算要求——必须用公式，禁止整数近似！】
- 齿顶半宽 w_tip = neck[i] + tooth_height[i]
- 外斜面 x 跨度 dx_work = tooth_height[i] / tan_top[i]
- 内斜面 x 跨度 dx_back = (tooth_height[i] + neck[i] − neck[i+1]) / tan_under[i]
- 连接线 x 跨度 = neck_platform；底部外扩 x 跨度 = (bottom − neck[-1]) / tan_bottom
- 每个点的 x、y 都要精确到 3 位小数，x 是逐齿累加的精确值（不是整数）。

【新参数】
{params}

【新参数 tan 值（直接用，别自己算）】
{tan_table}

【输出】slot_points 数组（元素 {{"x_mm":x,"y_mm":y}}），上侧(口部→根部)+下侧(根部→口部)。
"""


def build_prompt_v6(p: FirTreeParams) -> str:
    import math
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex2_p = _B(_C["T02_2tooth_equal"])
    ex3_p = _B(_C["T03_3tooth_standard"])
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    tan_lines = []
    for i in range(p.teeth_count):
        t_top = math.tan(math.radians(p.top_flank_angle_deg[i]))
        t_under = math.tan(math.radians(p.under_flank_angle_deg[i]))
        tan_lines.append(f"  齿{i}: tan_top={t_top:.6f}, tan_under={t_under:.6f}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    tan_lines.append(f"  底部: tan_bottom={t_bottom:.6f}")
    head = f"【示例1：2齿】\n{_fmt_example(ex2_p, _gen(ex2_p))}\n\n【示例2：3齿】\n{_fmt_example(ex3_p, _gen(ex3_p))}\n\n"
    return PROMPT_V6.format(
        example1=head,
        params=params,
        tan_table="\n".join(tan_lines),
    )


PROMPT_V7 = """\
你是枞树形榫槽轮廓生成器。下面给 2 齿和 3 齿完整示例，然后为【新参数】生成点。
关键：程序已算好每齿的【跨度值】，你只需从起点 x 做【减法累加】，坐标精确到 3 位小数。

【结构】每侧：点[0]=(0,mouth), 点[1]=(-mouth_wedge_dx, neck[0])，每齿 5 点，底部 3 点，下侧镜像。总点数=2×(5+4×teeth_count)。

{example1}

【新参数】
{params}

【每齿跨度值（程序预计算，直接用）】
{spans}

【计算步骤（上侧）】
x = -mouth_wedge_dx
点[0]=(0, mouth_half_width); 点[1]=(x, neck[0])
对每齿 i：
  齿顶半宽 w_tip = neck[i] + tooth_height[i]
  x_tip = x - dx_work[i]
  x_tip_end = x_tip - tooth_thickness[i]
  x_next = x_tip_end - dx_back[i]
  x_work = x_next - neck_platform
  输出 5 点: (x, neck[i]) (x_tip, w_tip) (x_tip_end, w_tip) (x_next, 下一颈部半宽) (x_work, 下一颈部半宽)
  x = x_work
最后齿后底部：
  槽底: (x - dx_flare, bottom_half_width)
  槽底平台端: (槽底x - bottom_platform, bottom_half_width)
  根部: (槽底平台端x - 1.0, bottom_half_width - 1.5)
下侧镜像。

【输出】slot_points 数组（上侧口部→根部 + 下侧根部→口部）。
"""


def build_prompt_v7(p: FirTreeParams) -> str:
    import math
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex2_p = _B(_C["T02_2tooth_equal"])
    ex3_p = _B(_C["T03_3tooth_standard"])
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}")
    # 预计算每齿跨度（标称 neck）
    spans = []
    for i in range(p.teeth_count):
        h_y = p.tooth_height_mm[i]
        w_neck = p.neck_half_width_mm[i]
        w_next = p.neck_half_width_mm[i + 1]
        dx_work = h_y / math.tan(math.radians(p.top_flank_angle_deg[i]))
        dx_back = (h_y + w_neck - w_next) / math.tan(math.radians(p.under_flank_angle_deg[i]))
        spans.append(f"  齿{i}: dx_work={dx_work:.4f}, dx_back={dx_back:.4f}, 下一颈部半宽={w_next}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    dx_flare = (p.bottom_half_width_mm - p.neck_half_width_mm[-1]) / t_bottom
    spans.append(f"  底部: dx_flare={dx_flare:.4f} (外扩到槽底)")
    head = f"【示例1：2齿】\n{_fmt_example(ex2_p, _gen(ex2_p))}\n\n【示例2：3齿】\n{_fmt_example(ex3_p, _gen(ex3_p))}\n\n"
    return PROMPT_V7.format(
        example1=head,
        params=params,
        spans="\n".join(spans),
    )


def _fmt_example_traced(p: FirTreeParams, pts: list) -> str:
    """示例：标注每个点的 x 累加来源，让 LLM 模仿计算过程。"""
    import math
    lines = [f"参数: teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
             f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, neck={p.neck_half_width_mm}, "
             f"neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, mouth_wedge_dx={p.mouth_wedge_dx_mm}, "
             f"bottom_half_width={p.bottom_half_width_mm}, bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}"]
    lines.append(f"输出 {len(pts)} 点 (标注了每个点的 x 来源):")
    # 计算每齿跨度用于注释
    x = -p.mouth_wedge_dx_mm
    # 直接标注结构
    for i, pt in enumerate(pts[: len(pts) // 2]):
        note = ""
        lines.append(f"[{i}] ({pt['x_mm']:.3f}, {pt['y_mm']:.3f}){note}")
    for i, pt in enumerate(pts[len(pts) // 2:], start=len(pts) // 2):
        lines.append(f"[{i}] ({pt['x_mm']:.3f}, {pt['y_mm']:.3f})")
    return "\n".join(lines)


PROMPT_V8 = """\
你是枞树形榫槽轮廓的精确计算器。下方示例展示了【每个点的 x 是如何逐齿累减得到的】。请模仿这个过程，为【新参数】计算轮廓点。

【结构】每侧：点[0]=(0,mouth)，点[1]=(-mouth_wedge_dx, neck[0])。每齿产生 5 点（外斜面起点/外斜面顶/齿顶平台端/内斜面端/连接线端），最后齿后底部 3 点，下侧镜像。总点数=2×(5+4×teeth_count)。

【累减规则（每齿）】
- 外斜面顶 x = 当前x − dx_work[i]   其中 dx_work[i] = tooth_height[i] / tan(top_flank[i])
- 齿顶平台端 x = 外斜面顶x − tooth_thickness[i]
- 内斜面端 x = 齿顶平台端x − dx_back[i]   其中 dx_back[i] = (tooth_height[i]+neck[i]−neck[i+1]) / tan(under_flank[i])
- 连接线端 x = 内斜面端x − neck_platform
- 底部外扩 x = 连接线端x − dx_flare   其中 dx_flare = (bottom−neck[-1]) / tan(bottom_flare_angle)
- 所有 y：齿顶半宽 = neck[i] + tooth_height[i]

【每齿 dx_work / dx_back / dx_flare（程序已算好，直接用，禁止重算或近似）】
{spans}

{example1}

【新参数】
{params}

【输出】slot_points 数组。坐标保留 3 位小数。x 必须逐齿精确累减，禁止用整数近似。
"""


def build_prompt_v8(p: FirTreeParams) -> str:
    import math
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex2_p = _B(_C["T02_2tooth_equal"])
    ex3_p = _B(_C["T03_3tooth_standard"])
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    spans = []
    for i in range(p.teeth_count):
        h_y = p.tooth_height_mm[i]
        w_neck = p.neck_half_width_mm[i]
        w_next = p.neck_half_width_mm[i + 1]
        dx_work = h_y / math.tan(math.radians(p.top_flank_angle_deg[i]))
        dx_back = (h_y + w_neck - w_next) / math.tan(math.radians(p.under_flank_angle_deg[i]))
        spans.append(f"  齿{i}: dx_work={dx_work:.4f}, dx_back={dx_back:.4f}, 齿顶半宽增量={h_y}, 下一颈部={w_next}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    dx_flare = (p.bottom_half_width_mm - p.neck_half_width_mm[-1]) / t_bottom
    spans.append(f"  底部: dx_flare={dx_flare:.4f}")
    head = f"【示例1：2齿】\n{_fmt_example(ex2_p, _gen(ex2_p))}\n\n【示例2：3齿】\n{_fmt_example(ex3_p, _gen(ex3_p))}"
    return PROMPT_V8.format(
        spans="\n".join(spans),
        example1=head,
        params=params,
    )


PROMPT_V9 = """\
你是枞树形榫槽轮廓生成器。你只需输出【上侧轮廓点】（y≥0，口部→根部），下侧由系统镜像。因此只需精确计算一半点数。

【上侧点数】= 5 + 4 × teeth_count

【结构】
点[0] = (0, mouth_half_width)
点[1] = (-mouth_wedge_dx, neck[0])
每齿 i 产生 5 点：
  (x, neck[i])                 外斜面起点
  (x - dx_work[i], neck[i] + tooth_height[i])   外斜面顶
  (外斜面顶x - tooth_thickness[i], 同y)         齿顶平台端
  (齿顶平台端x - dx_back[i], neck[i+1])         内斜面端
  (内斜面端x - neck_platform, neck[i+1])        连接线端
最后齿后底部 3 点：
  (连接线端x - dx_flare, bottom_half_width)     槽底
  (槽底x - bottom_platform, bottom_half_width)  槽底平台端
  (槽底平台端x - 1.0, bottom_half_width - 1.5)  根部

【每齿 dx 值（程序已精确算好，必须原样使用，禁止重算或近似）】
{spans}

【示例（2齿上侧 13 点，标注累减）】
{example_upper}

【新参数】
{params}

【输出】slot_points 数组，只含上侧点（口部→根部），坐标精确到 3 位小数。
"""


def _fmt_example_upper(p: FirTreeParams, pts: list) -> str:
    import math
    half = len(pts) // 2
    lines = [f"参数: teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
             f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, neck={p.neck_half_width_mm}, "
             f"neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, mouth_wedge_dx={p.mouth_wedge_dx_mm}, "
             f"bottom_half_width={p.bottom_half_width_mm}, bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}"]
    lines.append(f"上侧 {half} 点:")
    for i, pt in enumerate(pts[:half]):
        lines.append(f"[{i}] ({pt['x_mm']:.3f}, {pt['y_mm']:.3f})")
    return "\n".join(lines)


def build_prompt_v9(p: FirTreeParams) -> str:
    import math
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex2_p = _B(_C["T02_2tooth_equal"])
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    spans = []
    for i in range(p.teeth_count):
        h_y = p.tooth_height_mm[i]
        w_neck = p.neck_half_width_mm[i]
        w_next = p.neck_half_width_mm[i + 1]
        dx_work = h_y / math.tan(math.radians(p.top_flank_angle_deg[i]))
        dx_back = (h_y + w_neck - w_next) / math.tan(math.radians(p.under_flank_angle_deg[i]))
        spans.append(f"  齿{i}: dx_work={dx_work:.4f}, dx_back={dx_back:.4f}, 下一颈部半宽={w_next}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    dx_flare = (p.bottom_half_width_mm - p.neck_half_width_mm[-1]) / t_bottom
    spans.append(f"  底部: dx_flare={dx_flare:.4f}")
    return PROMPT_V9.format(
        spans="\n".join(spans),
        example_upper=_fmt_example_upper(ex2_p, _gen(ex2_p)),
        params=params,
    )


PROMPT_V10 = """\
你是枞树形榫槽轮廓的精确生成器。你的输出将被程序逐点验证。**绝对禁止用整数或近似值**——每个坐标必须是从下面参数和 dx 值精确计算的结果，保留 3 位小数。

【参数（必须原样使用，一个值都不能改）】
teeth_count={teeth_count}
tooth_height={tooth_height}
tooth_thickness={tooth_thickness}
neck_half_width={neck}          # 第i齿根 y 精确 = neck[i]（如 neck[0]=2.600，禁止写成 3）
neck_platform={neck_platform}
mouth_half_width={mouth}
mouth_wedge_dx={mouth_dx}
bottom_half_width={bottom}
bottom_platform={bottom_platform}
bottom_flare_angle={flare}

【每齿 dx 值（程序算好的唯一正确值，直接用于累加）】
{spans}

【计算方式】
起点 x = -{mouth_dx}（点[1]）。每齿从当前 x 开始：
  外斜面顶 x = 当前x − dx_work[i]
  齿顶平台端 x = 外斜面顶x − tooth_thickness[i]
  内斜面端 x = 齿顶平台端x − dx_back[i]
  连接线端 x = 内斜面端x − neck_platform
  下一齿当前x = 连接线端x
底部：槽底x = 最后连接线端x − dx_flare

【示例（2齿 26 点完整输出，注意坐标都是精确小数）】
{example_full}

【新参数】
{params}

【输出】slot_points 数组（上侧口部→根部 + 下侧根部→口部），完整 2×(5+4×teeth_count) 点，坐标精确到 3 位小数。
"""


def build_prompt_v10(p: FirTreeParams) -> str:
    import math
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex2_p = _B(_C["T02_2tooth_equal"])
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    spans = []
    for i in range(p.teeth_count):
        h_y = p.tooth_height_mm[i]
        w_neck = p.neck_half_width_mm[i]
        w_next = p.neck_half_width_mm[i + 1]
        dx_work = h_y / math.tan(math.radians(p.top_flank_angle_deg[i]))
        dx_back = (h_y + w_neck - w_next) / math.tan(math.radians(p.under_flank_angle_deg[i]))
        spans.append(f"  齿{i}: dx_work={dx_work:.4f}  dx_back={dx_back:.4f}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    dx_flare = (p.bottom_half_width_mm - p.neck_half_width_mm[-1]) / t_bottom
    spans.append(f"  底部: dx_flare={dx_flare:.4f}")
    return PROMPT_V10.format(
        teeth_count=p.teeth_count,
        tooth_height=p.tooth_height_mm,
        tooth_thickness=p.tooth_thickness_mm,
        neck=p.neck_half_width_mm,
        neck_platform=p.neck_platform_mm,
        mouth=p.mouth_half_width_mm,
        mouth_dx=p.mouth_wedge_dx_mm,
        bottom=p.bottom_half_width_mm,
        bottom_platform=p.bottom_platform_mm,
        flare=p.bottom_flare_angle_deg,
        spans="\n".join(spans),
        example_full=_fmt_example(ex2_p, _gen(ex2_p)),
        params=params,
    )


PROMPT_V11 = """\
你是枞树形榫槽轮廓生成器。下面是 3 个完整示例（覆盖不同齿面角：标准 66.7°/60°、陡 75°/70°、缓 50°/45°），请观察示例中【角度不同 → dx 跨度不同】的规律，然后为【新参数】生成同样结构的轮廓点。

【结构规律】
- 每侧：口部点[0]=(0,mouth)，点[1]=(-mouth_wedge_dx, neck[0])；每齿 5 点；底部 3 点；下侧镜像。
- 总点数 = 2 × (5 + 4 × teeth_count)。
- 齿顶半宽 w_tip = neck[i] + tooth_height[i]
- 外斜面 x 跨度 = tooth_height[i] / tan(top_flank[i])；内斜面 x 跨度 = (tooth_height[i]+neck[i]−neck[i+1]) / tan(under_flank[i])
- 底部外扩 x 跨度 = (bottom−neck[-1]) / tan(bottom_flare_angle)
- 必须精确计算（可用 tan 值表），保留 3 位小数，禁止整数近似。

【示例1：标准角度（66.7°/60°）】
{example1}

【示例2：陡齿面（75°/70°）】
{example2}

【示例3：缓齿面（50°/45°）】
{example3}

【新参数】
{params}

【tan 值（新参数的，直接用）】
{tan_table}

【输出】slot_points 数组（上侧口部→根部 + 下侧根部→口部）。
"""


def build_prompt_v11(p: FirTreeParams) -> str:
    import math
    from fir_tree_parametric import generate_profile as _gen
    from test_capability import COMBOS as _C, build as _B
    ex1_p = _B(_C["T04_4tooth"])     # 66.7/60
    ex2_p = _B(_C["T06_steep_flank"])  # 75/70
    ex3_p = _B(_C["T07_gentle_flank"]) # 50/45
    params = (f"teeth_count={p.teeth_count}, tooth_height={p.tooth_height_mm}, tooth_thickness={p.tooth_thickness_mm}, "
              f"top_flank={p.top_flank_angle_deg}, under_flank={p.under_flank_angle_deg}, "
              f"neck={p.neck_half_width_mm}, neck_platform={p.neck_platform_mm}, mouth={p.mouth_half_width_mm}, "
              f"mouth_wedge_dx={p.mouth_wedge_dx_mm}, bottom_half_width={p.bottom_half_width_mm}, "
              f"bottom_platform={p.bottom_platform_mm}, bottom_flare_angle={p.bottom_flare_angle_deg}")
    tan_lines = []
    for i in range(p.teeth_count):
        t_top = math.tan(math.radians(p.top_flank_angle_deg[i]))
        t_under = math.tan(math.radians(p.under_flank_angle_deg[i]))
        tan_lines.append(f"  齿{i}: tan_top={t_top:.6f}, tan_under={t_under:.6f}")
    t_bottom = math.tan(math.radians(p.bottom_flare_angle_deg))
    tan_lines.append(f"  底部: tan_bottom={t_bottom:.6f}")
    return PROMPT_V11.format(
        example1=_fmt_example(ex1_p, _gen(ex1_p)),
        example2=_fmt_example(ex2_p, _gen(ex2_p)),
        example3=_fmt_example(ex3_p, _gen(ex3_p)),
        params=params,
        tan_table="\n".join(tan_lines),
    )


def build_prompt(p: FirTreeParams, version: str) -> str:
    if version == "v2":
        return build_prompt_v2(p)
    if version == "v3":
        return build_prompt_v3(p)
    if version == "v4":
        return build_prompt_v4(p)
    if version == "v5":
        return build_prompt_v5(p)
    if version == "v6":
        return build_prompt_v6(p)
    if version == "v7":
        return build_prompt_v7(p)
    if version == "v8":
        return build_prompt_v8(p)
    if version == "v9":
        return build_prompt_v9(p)
    if version == "v10":
        return build_prompt_v10(p)
    if version == "v11":
        return build_prompt_v11(p)
    return build_prompt_v1(p)


def build_feedback(gt: list, llm: list) -> str:
    """构造修正反馈：按"齿"分组，精确指出第一个错误齿的 5 点正确坐标。"""
    n_upper = len(gt) // 2  # 上侧点数 = 5 + 4*teeth_count
    teeth_count = (n_upper - 5) // 4
    if teeth_count < 1 or n_upper != 5 + 4 * teeth_count:
        # 结构不匹配，退化为逐点反馈
        diffs = []
        for i, (g, l) in enumerate(zip(gt, llm)):
            if abs(g["x_mm"] - l["x_mm"]) > 0.1 or abs(g["y_mm"] - l["y_mm"]) > 0.1:
                diffs.append(f"点[{i}] 正确=( {g['x_mm']:.3f}, {g['y_mm']:.3f} )，你给出=( {l['x_mm']:.3f}, {l['y_mm']:.3f} )")
                if len(diffs) >= 6:
                    break
        return ("【修正反馈】以下点坐标错误（含正确值）。请重新输出全部点并修正。\n" + "\n".join(diffs)) if diffs else ""
    # 逐齿检查（上侧）
    for i in range(teeth_count):
        idx = [1 + 4 * i, 2 + 4 * i, 3 + 4 * i, 4 + 4 * i, 5 + 4 * i]
        tooth_err = []
        for k in idx:
            if k >= len(gt) or k >= len(llm):
                return f"点数不足，无法反馈。请重新输出完整 {len(gt)} 点。"
            g, l = gt[k], llm[k]
            if abs(g["x_mm"] - l["x_mm"]) > 0.1 or abs(g["y_mm"] - l["y_mm"]) > 0.1:
                tooth_err.append(f"点[{k}] 正确=( {g['x_mm']:.3f}, {g['y_mm']:.3f} )，你给出=( {l['x_mm']:.3f}, {l['y_mm']:.3f} )")
        if tooth_err:
            lines = [f"【修正反馈】齿 {i} 的坐标算错了，其 5 点正确值如下（这是齿 {i} 的完整轮廓）："]
            for k in idx:
                g = gt[k]
                lines.append(f"点[{k}] = ( {g['x_mm']:.3f}, {g['y_mm']:.3f} )")
            lines.append("请按此正确值修正齿 " + str(i) + " 的 5 点，其余齿也请检查是否用相同方法精确计算（不要改点数和顺序）。")
            return "\n".join(lines)
    # 所有齿正确，检查底部
    bottom_idx = [5 + 4 * teeth_count - 1]  # 连接线端（最后一个齿）
    for k in range(n_upper - 3, n_upper):  # 底部3点
        g, l = gt[k], llm[k]
        if abs(g["x_mm"] - l["x_mm"]) > 0.1 or abs(g["y_mm"] - l["y_mm"]) > 0.1:
            return f"【修正反馈】底部点[{k}] 正确=( {g['x_mm']:.3f}, {g['y_mm']:.3f} )，你给出=( {l['x_mm']:.3f}, {l['y_mm']:.3f} )。请修正。"
    return ""


def _is_sane(pts: list) -> bool:
    """异常值检测：坐标应为合理数值（非 NaN、非巨值）。"""
    for pt in pts:
        try:
            x = float(pt["x_mm"])
            y = float(pt["y_mm"])
            if abs(x) > 1000 or abs(y) > 1000:
                return False
        except Exception:
            return False
    return True


def _normalize_full(llm: list, gt: list) -> list:
    """若 LLM 只输出上侧（半量），镜像补齐下侧。"""
    if len(llm) == len(gt) // 2:
        pts = list(llm)
        lower = [{"x_mm": p["x_mm"], "y_mm": round(-p["y_mm"], 4)} for p in reversed(pts)]
        return pts + lower
    return llm


def call_llm_retry(prompt: str, gt: list, max_attempts: int = 3) -> tuple:
    """LLM 生成 + 程序反馈精炼，直到完全正确或达上限。
    异常值(离谱)输出直接重试，不消耗反馈轮次。
    """
    used = 0
    llm = _normalize_full(call_llm(prompt), gt)
    while True:
        if not _is_sane(llm):
            used += 1
            if used >= max_attempts * 2:
                return llm, compare(gt, llm), used
            llm = _normalize_full(call_llm(prompt), gt)  # 无反馈重试
            continue
        res = compare(gt, llm)
        if res.get("match"):
            return llm, res, used + 1
        fb = build_feedback(gt, llm)
        if not fb:
            return llm, res, used + 1
        used += 1
        if used >= max_attempts:
            return llm, res, used
        llm = _normalize_full(call_llm(prompt + "\n\n" + fb), gt)


def main(combos: list, prompt_name: str, repeat: int = 1, retry: int = 1):
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    os.environ["DEEPSEEK_API_KEY"] = key
    print(f"=== 榫槽 LLM 迭代实验 [round={prompt_name}] combos={combos} repeat={repeat} retry={retry} ===")

    report = {"round": prompt_name, "combos": {}}
    for name in combos:
        p = make_combo(name)
        gt = generate_profile(p)
        report["combos"][name] = {"gt_points": len(gt), "runs": []}
        for run in range(repeat):
            prompt = build_prompt(p, prompt_name)
            try:
                llm, res, attempts = call_llm_retry(prompt, gt, max_attempts=retry)
            except Exception as e:
                print(f"[{name} run{run}] LLM 调用失败: {e}")
                report["combos"][name]["runs"].append({"error": str(e)})
                continue
            status = "EXACT" if res.get("match") else "DIFF"
            print(f"[{name} run{run}] GT={len(gt)} LLM={len(llm)} -> {status} (用了{attempts}轮)"
                  + (f" max_dx={res['max_dx']} max_dy={res['max_dy']}" if res["max_dx"] is not None else f" ({res['reason']})"))
            report["combos"][name]["runs"].append({**res, "attempts": attempts, "llm_points_data": llm})
            if res["max_dx"] is not None and res["max_dx"] > 0.05:
                plot_compare(gt, llm, f"{name}_run{run} [{status}]", OUT / f"{prompt_name}_{name}_run{run}.png")
        runs = report["combos"][name]["runs"]
        exact_n = sum(1 for r in runs if r.get("match"))
        print(f"[{name}] 成功率: {exact_n}/{len(runs)}")
        report["combos"][name]["success_rate"] = f"{exact_n}/{len(runs)}"

    (OUT / f"report_{prompt_name}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {OUT / f'report_{prompt_name}.json'}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--combos", default="T03_3tooth_standard,T02_2tooth_equal")
    ap.add_argument("--round", default="v1")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--retry", type=int, default=1, help="每组合最多精炼轮数")
    args = ap.parse_args()
    main([c.strip() for c in args.combos.split(",") if c.strip()], args.round, repeat=args.repeat, retry=args.retry)
