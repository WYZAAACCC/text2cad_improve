"""参数化盘面/榫槽轮廓描述模板 + 参数组合定义（隔离实验专用，不触碰主程序）。"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 盘面（R-Z 截面）参数化描述 —— 纯文字规则，无硬编码坐标
# ---------------------------------------------------------------------------

DISC_PROFILE_RULES = """\
### 涡轮盘盘面轮廓（R-Z 截面，XZ 平面，x=半径mm，y=轴向mm，关于 y=0 对称）

盘面是轴对称旋转盘，轮廓为闭合多边形。由以下参数决定：
- bore_radius_mm: 内孔半径（轮廓最内 x）
- hub_radius_mm: 轮毂外半径（hub 段结束的 x）
- rim_web_junction_mm: 腹板外端 / 轮缘内壁处的 x
- rim_radius_mm: 轮缘外半径（轮廓最外 x）
- hub_half_thickness_mm: 轮毂轴向半厚（y 绝对值最大的 hub 段）
- web_inner_half_thickness_mm: 轮毂侧腹板半厚（hub 外壁处的 y）
- web_outer_half_thickness_mm: 轮缘侧腹板半厚（junction 处的 y）
- rim_half_thickness_mm: 轮缘轴向半厚
- hub_web_fillet_mm: 轮毂-腹板过渡圆角（在 x=hub_radius_mm 处）
- web_rim_fillet_mm: 腹板-轮缘过渡圆角（在 x=rim_web_junction_mm 处）

轮廓点生成规则（必须恰好 12 个点，闭合顺序，关于 y=0 严格对称）：
下侧（y<0），从内（小 x）到外（大 x）：
  1. (bore_radius_mm, -hub_half_thickness_mm)            # bore 内壁点
  2. (hub_radius_mm, -hub_half_thickness_mm)             # hub 底转角
  3. (hub_radius_mm, -web_inner_half_thickness_mm)       # hub 外壁顶部（hub→web 过渡）
  4. (rim_web_junction_mm, -web_outer_half_thickness_mm) # 腹板外端（web→rim 过渡）
  5. (rim_web_junction_mm, -rim_half_thickness_mm)       # rim 内壁阶梯
  6. (rim_radius_mm, -rim_half_thickness_mm)             # rim 外端
上侧（y>0）为下侧精确镜像，顺序相反（外→内）：
  7. (rim_radius_mm, +rim_half_thickness_mm)
  8. (rim_web_junction_mm, +rim_half_thickness_mm)
  9. (rim_web_junction_mm, +web_outer_half_thickness_mm)
 10. (hub_radius_mm, +web_inner_half_thickness_mm)
 11. (hub_radius_mm, +hub_half_thickness_mm)
 12. (bore_radius_mm, +hub_half_thickness_mm)
然后回到点 1 闭合。

约束：
- 12 个点必须全部满足 bore_radius_mm <= x <= rim_radius_mm
- hub 外壁是垂直段（点2→点3 同 x），rim 内壁是垂直阶梯（点4→点5 同 x）
- 腹板是单一直线段（点3→点4），不拆多段
- 两个过渡圆角 hub_web_fillet/web_rim_fillet 是后续 fillet_sketch 的半径提示，不在坐标中体现，但要回传
"""

# ---------------------------------------------------------------------------
# 榫槽（枞树形）参数化描述 —— 点数随 teeth_count 动态变化
# ---------------------------------------------------------------------------

SLOT_PROFILE_RULES = """\
### 榫槽（枞树形）轮廓（XY 平面，x=径向 0=轮缘表面 负向=向中心，y=切向半宽，关于 y=0 对称）

榫槽是两侧对称的枞树形槽截面。由以下参数决定：
- teeth_count: 每侧凸台（lobe）数量（整数，1~4）
- mouth_half_width_mm: 槽口半宽（x=0 处的 y）
- slot_depth_mm: 槽总深（x 从 0 到 -slot_depth_mm）
- neck_half_width_mm: 颈部半宽（凸台之间凹槽的 y）
- lobe_half_width_mm: 凸台顶部半宽（最大的 y）
- bottom_half_width_mm: 槽底半宽（小于 lobe_half_width_mm）
- flank_angle_deg: 齿面角（凸台侧斜面与径向 x 方向的夹角，度）
- root_fillet_mm: 齿根圆角（凸台顶部转角半径，后续 fillet_sketch 用）
- bottom_fillet_mm: 槽底圆角（半径，后续 fillet_sketch 用）

轮廓点生成规则（每侧点数 = 2 + 4×teeth_count + 3；总点数 = 每侧×2，关于 y=0 对称）：
每侧（y>0 侧）从外（x=0）到内（x=-slot_depth_mm）：
  口部楔形 2 点：
    1. (0, mouth_half_width_mm)          # 口部上缘
    2. (-3, neck_half_width_mm)          # 口部楔形入口结束（斜面）
  对每个齿 i（i=1..teeth_count，从外到内，每齿 4 点）：
    3. 外斜面顶点: 从颈部平缓升至凸台顶, y = lobe_half_width_mm（x 由 flank_angle_deg 决定，越陡 x 跨度越小）
    4. 凸台顶部: y = lobe_half_width_mm（沿 x 延伸一小段, 齿顶平台）
    5. 内斜面: 从凸台顶回落到颈部, y = neck_half_width_mm
    6. 颈部平台: y = neck_half_width_mm（沿 x 延伸一小段, 进入下一齿或底部）
  槽底 3 点：
    7. 底外扩: y = bottom_half_width_mm（从最后颈部外扩）
    8. 槽底顶: y = bottom_half_width_mm（槽底平台）
    9. 根部: y = bottom_half_width_mm - 1.5（x = -slot_depth_mm，槽底最深处）
下侧（y<0）为 y>0 侧关于 y=0 的精确镜像，从内到外。

约束：
- 总点数必须严格等于 2 × (2 + 4×teeth_count + 3)
- 外宽内窄: lobe_half_width_mm > neck_half_width_mm > bottom_half_width_mm
- 凸台越靠内 x 跨度可稍小（越靠近槽底）
- 所有 x <= 0；x=0 处是口部；x=-slot_depth_mm 处是槽底
- root_fillet_mm / bottom_fillet_mm 是圆角提示，不在坐标中体现，但要回传
"""


# ---------------------------------------------------------------------------
# 参数组合定义
# ---------------------------------------------------------------------------

COMBINATIONS = {
    # 组合 A：基准 ≈ KT787 参考盘
    "A_baseline": {
        "label": "A 基准(≈KT787)",
        "disc": {
            "bore_radius_mm": 60,
            "hub_radius_mm": 120,
            "rim_web_junction_mm": 215,
            "rim_radius_mm": 250,
            "hub_half_thickness_mm": 38,
            "web_inner_half_thickness_mm": 22,
            "web_outer_half_thickness_mm": 15,
            "rim_half_thickness_mm": 30,
            "hub_web_fillet_mm": 12,
            "web_rim_fillet_mm": 10,
        },
        "slot": {
            "teeth_count": 2,
            "mouth_half_width_mm": 4,
            "slot_depth_mm": 24,
            "neck_half_width_mm": 2,
            "lobe_half_width_mm": 7,
            "bottom_half_width_mm": 3,
            "flank_angle_deg": 60,
            "root_fillet_mm": 1.0,
            "bottom_fillet_mm": 0.8,
        },
    },
    # 组合 B：小型盘 + 浅槽
    "B_small": {
        "label": "B 小型盘",
        "disc": {
            "bore_radius_mm": 40,
            "hub_radius_mm": 80,
            "rim_web_junction_mm": 150,
            "rim_radius_mm": 180,
            "hub_half_thickness_mm": 25,
            "web_inner_half_thickness_mm": 15,
            "web_outer_half_thickness_mm": 10,
            "rim_half_thickness_mm": 20,
            "hub_web_fillet_mm": 8,
            "web_rim_fillet_mm": 6,
        },
        "slot": {
            "teeth_count": 2,
            "mouth_half_width_mm": 3,
            "slot_depth_mm": 18,
            "neck_half_width_mm": 1.5,
            "lobe_half_width_mm": 5,
            "bottom_half_width_mm": 2,
            "flank_angle_deg": 65,
            "root_fillet_mm": 0.8,
            "bottom_fillet_mm": 0.6,
        },
    },
    # 组合 C：大型厚缘盘 + 3 齿榫槽（重点：验证 teeth_count 动态点数）
    "C_large_3tooth": {
        "label": "C 大型厚缘+3齿",
        "disc": {
            "bore_radius_mm": 80,
            "hub_radius_mm": 140,
            "rim_web_junction_mm": 250,
            "rim_radius_mm": 300,
            "hub_half_thickness_mm": 45,
            "web_inner_half_thickness_mm": 30,
            "web_outer_half_thickness_mm": 20,
            "rim_half_thickness_mm": 45,
            "hub_web_fillet_mm": 16,
            "web_rim_fillet_mm": 14,
        },
        "slot": {
            "teeth_count": 3,
            "mouth_half_width_mm": 4,
            "slot_depth_mm": 30,
            "neck_half_width_mm": 2,
            "lobe_half_width_mm": 7,
            "bottom_half_width_mm": 3,
            "flank_angle_deg": 55,
            "root_fillet_mm": 1.2,
            "bottom_fillet_mm": 1.0,
        },
    },
    # 组合 D：榫槽变体 —— 2 齿 + 大齿根圆角 + 陡齿面角（齿面更陡、圆角更大）
    "D_steep_flank": {
        "label": "D 陡齿面+大圆角",
        "disc": {
            "bore_radius_mm": 60,
            "hub_radius_mm": 120,
            "rim_web_junction_mm": 215,
            "rim_radius_mm": 250,
            "hub_half_thickness_mm": 38,
            "web_inner_half_thickness_mm": 22,
            "web_outer_half_thickness_mm": 15,
            "rim_half_thickness_mm": 30,
            "hub_web_fillet_mm": 12,
            "web_rim_fillet_mm": 10,
        },
        "slot": {
            "teeth_count": 2,
            "mouth_half_width_mm": 4,
            "slot_depth_mm": 24,
            "neck_half_width_mm": 2,
            "lobe_half_width_mm": 8,
            "bottom_half_width_mm": 4,
            "flank_angle_deg": 70,
            "root_fillet_mm": 2.0,
            "bottom_fillet_mm": 1.5,
        },
    },
}


# ---------------------------------------------------------------------------
# 精简 tool schema（经 to_deepseek_strict_schema 转换后用于 DeepSeek 调用）
# ---------------------------------------------------------------------------

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "disc_points": {
            "type": "array",
            "description": "盘面轮廓 12 点，XZ 平面（x=半径mm, y=轴向mm），闭合顺序，关于 y=0 对称",
            "items": {
                "type": "object",
                "properties": {
                    "x_mm": {"type": "number", "description": "半径坐标"},
                    "y_mm": {"type": "number", "description": "轴向坐标"},
                },
                "required": ["x_mm", "y_mm"],
                "additionalProperties": False,
            },
        },
        "slot_points": {
            "type": "array",
            "description": "榫槽轮廓点，XY 平面（x=径向 0=轮缘表面 负向=向中心, y=切向半宽），闭合顺序，关于 y=0 对称",
            "items": {
                "type": "object",
                "properties": {
                    "x_mm": {"type": "number", "description": "径向坐标"},
                    "y_mm": {"type": "number", "description": "切向半宽坐标"},
                },
                "required": ["x_mm", "y_mm"],
                "additionalProperties": False,
            },
        },
        "disc_params_used": {
            "type": "object",
            "description": "实际采用的盘面参数值（逐项回传输入参数）",
            "additionalProperties": False,
            "properties": {
                "bore_radius_mm": {"type": "number"},
                "hub_radius_mm": {"type": "number"},
                "rim_web_junction_mm": {"type": "number"},
                "rim_radius_mm": {"type": "number"},
                "hub_half_thickness_mm": {"type": "number"},
                "web_inner_half_thickness_mm": {"type": "number"},
                "web_outer_half_thickness_mm": {"type": "number"},
                "rim_half_thickness_mm": {"type": "number"},
                "hub_web_fillet_mm": {"type": "number"},
                "web_rim_fillet_mm": {"type": "number"},
            },
            "required": [
                "bore_radius_mm", "hub_radius_mm", "rim_web_junction_mm", "rim_radius_mm",
                "hub_half_thickness_mm", "web_inner_half_thickness_mm",
                "web_outer_half_thickness_mm", "rim_half_thickness_mm",
                "hub_web_fillet_mm", "web_rim_fillet_mm",
            ],
        },
        "slot_params_used": {
            "type": "object",
            "description": "实际采用的榫槽参数值（逐项回传输入参数）",
            "additionalProperties": False,
            "properties": {
                "teeth_count": {"type": "integer"},
                "mouth_half_width_mm": {"type": "number"},
                "slot_depth_mm": {"type": "number"},
                "neck_half_width_mm": {"type": "number"},
                "lobe_half_width_mm": {"type": "number"},
                "bottom_half_width_mm": {"type": "number"},
                "flank_angle_deg": {"type": "number"},
                "root_fillet_mm": {"type": "number"},
                "bottom_fillet_mm": {"type": "number"},
            },
            "required": [
                "teeth_count", "mouth_half_width_mm", "slot_depth_mm", "neck_half_width_mm",
                "lobe_half_width_mm", "bottom_half_width_mm", "flank_angle_deg",
                "root_fillet_mm", "bottom_fillet_mm",
            ],
        },
    },
    "required": ["disc_points", "slot_points", "disc_params_used", "slot_params_used"],
    "additionalProperties": False,
}


def build_system_prompt(combo: dict) -> str:
    """构造参数化 system prompt：规则 + 给定参数值，要求 LLM 推导轮廓点。"""
    disc = combo["disc"]
    slot = combo["slot"]
    disc_params_str = "\n".join(f"- {k}: {v}" for k, v in disc.items())
    slot_params_str = "\n".join(f"- {k}: {v}" for k, v in slot.items())
    return f"""\
你是航空发动机涡轮盘几何专家。请根据给定的【参数化规则】和【参数值】，推导出涡轮盘盘面与榫槽的轮廓点坐标。你必须严格按照规则推导，不能跳过任何点，不能臆造规则之外的几何。

{DISC_PROFILE_RULES}

本次盘面参数值：
{disc_params_str}

{SLOT_PROFILE_RULES}

本次榫槽参数值：
{slot_params_str}

请输出：
1. disc_points: 按规则生成 12 个盘面轮廓点
2. slot_points: 按规则生成榫槽轮廓点（每侧 = 2 + 4×teeth_count + 3 个点，总数 = 每侧×2）
3. disc_params_used / slot_params_used: 逐项回传你实际采用的参数值（应与输入一致）
注意：这是参考几何，仅用于验证参数化轮廓生成。
【精度要求】所有坐标 x_mm/y_mm 和 params_used 中的参数值必须**保留输入值的小数精度**，禁止取整为整数（例如 0.8 必须输出 0.8，不能是 0；1.5 必须输出 1.5，不能是 1）。"""
