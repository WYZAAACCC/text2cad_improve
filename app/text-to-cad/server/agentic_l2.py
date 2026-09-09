"""生成层 agent 化：整体设计 agent + 轮廓实现 agent（AGENTIC_L2=1 启用）。

把原 L2"单 LLM 生成完整 RawGcadDocument"替换为两阶段 agent 系统：
  Agent A 整体设计：需求 → RawGcadDocument 骨架（节点/op/依赖/参数，add_polyline.points 占位）
                     + 轮廓参数声明（profiles，每个轮廓的 kind 与全部推导参数）。
  Agent B 轮廓实现：每类型一个 agent（盘体 disc / 榫槽 slot），从参数生成精确 points。
  assemble()：骨架 + 各轮廓 points → 完整 RawGcadDocument。

输出格式与旧 L2 的 llm_raw.json 完全一致（RawGcadDocument dict），
下游 fillet clamp → validation → repair loop 全部不变。仅生成模块替换。

设计原则：
  - 不硬编码坐标：骨架 points 只占位，轮廓 agent 用参数化规则（param_prompts）推导。
  - prompt 特化：Agent A 只做结构/依赖/参数决策；轮廓 agent 只算单一轮廓。
  - 输出一致：最终是 RawGcadDocument dict，与 llm_raw 同构。

用法（main.py L2 段，AGENTIC_L2=1 时）:
  from agentic_l2 import run_agentic_l2
  raw = run_agentic_l2(text, plan, caller=caller, llm_model_config=config, out_dir=out_dir)
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path
from datetime import datetime

_HERE = Path(__file__).resolve().parent
_PARAM = _HERE.parent.parent / "_param_experiment"
if str(_PARAM) not in sys.path:
    sys.path.insert(0, str(_PARAM))

from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (  # noqa: E402
    to_deepseek_strict_schema,
)
from seekflow_engineering_tools.generative_cad.llm.errors import LlmToolCallError  # noqa: E402
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument  # noqa: E402

try:
    from seekflow_engineering_tools.generative_cad.skills.prompts import (  # noqa: E402
        LEVEL2_AUTHORING_SYSTEM_PROMPT,
    )
except Exception:  # noqa: BLE001
    LEVEL2_AUTHORING_SYSTEM_PROMPT = ""

try:
    from param_prompts import DISC_PROFILE_RULES, SLOT_PROFILE_RULES  # noqa: E402
except Exception:  # noqa: BLE001
    DISC_PROFILE_RULES = SLOT_PROFILE_RULES = ""

try:
    from validate_req_params import extract_requirements  # noqa: E402
except Exception:  # noqa: BLE001
    extract_requirements = lambda t: {}  # noqa: E731


# ═══════════════════════════════════════════════════════════════════════════════
# Agent A（整体设计）prompt
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_A_ADDENDUM = """

## 整体设计 agent 职责（两 agent 系统的顶层）
You are the TOP-LEVEL DESIGN AGENT. A separate PROFILE AGENT will compute exact
profile coordinates. Therefore:
- Output the AgentDesignPlan JSON (NOT a bare RawGcadDocument).
- `gcad_skeleton`: a RawGcadDocument structure (nodes/components/constraints/
  safety) that fully specifies HOW to build the part — operations, dependency
  wiring (inputs/outputs), parameters (extrude depth, pattern count, fillet
  radii, etc.), and component root nodes. It must pass RawGcadDocument schema.
- In `gcad_skeleton`, every `add_polyline.params.points` MUST contain exactly 2
  valid placeholder points (e.g. [(0,0),(1,1)]) — the PROFILE AGENT will
  replace them with the exact closed contour. Do NOT compute coordinates.
- Mark each component's `kind_hint` so the assembler can route its profile:
  disc body → "turbine_disc"; fir-tree slot cutter → "fir_tree_cutter";
  hole cutter → "hole_cutter"; groove cutter → "groove_cutter".
- `profiles`: for EVERY profile-producing feature, declare {profile_id, kind,
    params} where `params` MUST contain the COMPLETE parameter set for that kind
    — the profile agent derives exact coordinates FROM these params:
    disc (盘体 R-Z 截面，全部半径/半厚体系；需求的直径必须 ÷2，例如外径Φ500
          → rim_radius_mm=250, 中心孔直径Φ120 → bore_radius_mm=60):
          bore_radius_mm, hub_radius_mm, rim_web_junction_mm, rim_radius_mm,
          hub_half_thickness_mm, web_inner_half_thickness_mm,
          web_outer_half_thickness_mm, rim_half_thickness_mm,
          hub_web_fillet_mm, web_rim_fillet_mm
    complex_rim（仅当需求含“过渡”字样时，disc params 额外必须给出）:
          rim_transition_radius_mm = 需求中的过渡幅度/过渡半径（如 28）
          若需求未给出过渡幅度，按参数化兜底公式计算：
          rim_transition_radius_mm = clamp(0.12 × rim_radial, 6, 15)
          （rim_radial = rim_radius_mm − rim_web_junction_mm）
          rim_transition_type ∈ {s_curve, ellipse, power, arc_out, arc_in}
          （S形曲线→s_curve，椭圆弧→ellipse，幂函数曲线→power，
            外凸圆弧→arc_out，内凹圆弧→arc_in）
    slot (枞树形榫槽；`slots` 是 circular_pattern_component.count，属骨架节点参数，
          不在此 profiles.params 内):
          teeth_count, slot_depth_mm, mouth_half_width_mm, neck_half_width_mm,
          lobe_half_width_mm, bottom_half_width_mm, flank_angle_deg,
          root_fillet_mm, bottom_fillet_mm
    hole (孔 cutter 的 XY 16 边形轮廓；`count/pcd_mm` 属于骨架中
          circular_pattern_component 的 params，不在此 profiles.params 内):
          center_x_mm, center_y_mm, diameter_mm
          HARD: center_x_mm/center_y_mm 必须是 0/0（cutter 局部原点）；
          PCD 只在 circular_pattern_component.params.radius_mm 中体现。
    groove (环槽/环形腔 cutter 的 XZ 矩形截面；旋转切除由骨架中
            revolve_profile 完成):
          inner_radius_mm, outer_radius_mm, z_base_mm, depth_mm
          HARD (collar 卡环槽语义，必须按此推导，不得自行换方向):
          - 槽宽 gw 是轴向宽度 → depth_mm = gw；
          - 槽深 gd 是径向跨度 → inner_radius_mm = rim_web_junction_mm，
            outer_radius_mm = rim_web_junction_mm + gd；
          - 轴向贴 web-rim 交界：web 交界半厚 wb 按形态取
            thin_web=clamp(0.3×rim_half,4,18)、conical=clamp(0.4×rim_half,8,24)、
            其余=clamp(0.5×rim_half,6,32)；
            单道 collar → z_base_mm = −(wb + gw)；
            多道对称 → 第 i 道中心 z_c = (wb + gw/2)×(2i/(n−1) − 1)，
            z_base_mm = z_c − gw/2。
  HARD CONSTRAINT: neck/lobe/bottom 半宽必须等于 EXACT FIR-TREE 算法的实际
  轮廓值（槽底半宽即 bottom_half_width_mm 本身，无 −1.5 折算），禁止用
  1.1/2.25/0.875×mouth 名义比例；可用 run_python_code 按 EXACT 算法复核。
  Do NOT omit any param — 每个字段都要给出，且必须与最终轮廓一致。
  kind ∈ ["disc", "slot", "hole", "groove"].
- profile_id 必须使用固定契约：盘体轮廓必须叫 `disc_polyline`；榫槽轮廓必须叫
  `cutter_polyline`；孔/环槽轮廓必须叫 `<component_id>_profile`（例如
  `feat_holes_profile`、`feat_groove_0_profile`）。禁止使用 `disc_profile`、
  `slot_profile` 等非契约名称。
- 特征组件 id 必须固定：安装孔 `feat_holes`、减重孔 `feat_lh`、
  冷却孔 `feat_cl_0`/`feat_cl_1`、环槽 `feat_groove_0`/`feat_groove_1`。
  对应 profile_id 必须为 `feat_holes_profile`、`feat_lh_profile`、
  `feat_cl_0_profile`、`feat_groove_0_profile` 等。
- 只有当用户需求明确包含枞树形榫槽时，才允许输出 kind="slot" 的 profile；
  基础盘、孔盘、环槽盘禁止输出 slot profile。
- The exact coordinates are derived from these params by the profile agent.
  Do NOT invent coordinates anywhere.
- 需要复杂计算时，可使用通用工具 evaluate_math / run_python_code 计算参数；
  禁止把模板或专用特征生成逻辑当作工具。
- 计算复杂度标注：
  - disc 参数：SIMPLE，可直接由输入推导。
  - slot / hole / groove 参数：COMPLEX，必须先调用 run_python_code 或
    evaluate_math 计算后再写入 profiles；禁止直接心算。

## 思考链输出要求（必须严格遵守）
`reasoning` 字段必须是一段完整、可审计的中文推导过程，不少于 500 字。必须逐段说明：
  1. 需求解析：从用户文本中识别出的关键尺寸与特征，以及直径→半径的换算；
  2. 参数推导：hub_radius / rim_web_junction / 榫槽深度 / 齿数 / 喉部半宽 / 圆角等
     是如何由需求值或确定性公式算出的，写出具体数值与计算式；
  3. 结构方案：为什么选择 sketch_profile + revolve / extrude + circular_pattern +
     boolean_cut，组件如何划分，依赖如何接线；
  4. 关键决策：槽数、分布半径、圆角分组、是否保留孔/环槽等，说明取舍理由；
  5. 自查清单：逐项确认点数、参数完整、装配操作位置、输出名契约。
禁止只写一句结论；禁止省略计算过程。这一字段会原样展示给用户，作为系统思考链证据。

## 盘体（turbine_disc）参数唯一推导硬规则 —— 必须按下述确定性公式计算，严禁凭经验臆测
### 可选显式盘体径向参数（优先于比例公式）
若需求文本明确给出 `hub径向高度`（= hub_radius_mm − bore_radius_mm）或 `web径向长度`
（= rim_web_junction_mm − hub_radius_mm），必须优先采用显式值，不得再用比例系数：
  hub_radius_mm = bore_radius_mm + hub径向高度
  rim_web_junction_mm = hub_radius_mm + web径向长度
  （若 rim_web_junction_mm ≥ rim_radius_mm，则钳到 rim_radius_mm − 1）
需求未给出显式值时，才使用下方 0.16/0.12 比例公式。
`hub_radius_mm / rim_web_junction_mm / web_inner_half_thickness_mm / web_outer_half_thickness_mm`
四个派生参数必须由单一确定性内核公式从需求算得（保证盘面草图各径向站彼此一致），
不允许取整、不允许手填近似值。设需求给出 外径=OD，中心孔直径=BORE，轮毂半厚=HUB_HALF，
轮缘半厚=RIM_HALF（注意所有"直径"必须先 ÷2 得半径）：
  1. bore_radius_mm = BORE / 2
  2. rim_radius_mm   = OD / 2
  3. hub_extend     = clamp(HUB_FAC × OD, 25, 100)    # clamp(v,lo,hi)=max(lo, min(hi, v))
  4. hub_radius_mm  = bore_radius_mm + hub_extend
  5. rim_extend     = clamp(RIM_FAC × OD, 25, 95)
  6. rim_web_junction_mm = rim_radius_mm − rim_extend
  7. 若 hub_radius_mm ≥ rim_web_junction_mm（腹板过薄）：
     hub_radius_mm = (bore_radius_mm + rim_web_junction_mm) / 2
  8. web_inner_half_thickness_mm：thin_web 用 clamp(0.35 × HUB_HALF, 5, 22)，
     其余形态 clamp(0.6 × HUB_HALF, 8, 40)
  9. web_outer_half_thickness_mm：thin_web 用 clamp(0.3 × RIM_HALF, 4, 18)，
     conical 用 clamp(0.4 × RIM_HALF, 8, 24)（锥形腹板 rim 侧更薄，
     rim_junc 处的 y 必须是该值，不是 0.5×RIM_HALF），
     其余形态 clamp(0.5 × RIM_HALF, 6, 32)
  10. hub_web_fillet_mm / web_rim_fillet_mm：需求未给时默认 10 / 8
  形态系数：standard / thin_web / conical 用 HUB_FAC=0.16, RIM_FAC=0.12；
  thick_rim 用 HUB_FAC=0.14, RIM_FAC=0.17；large_hub 用 HUB_FAC=0.22, RIM_FAC=0.10。
示例校验（OD=500, BORE=120, HUB_HALF=38, RIM_HALF=30）：
  bore_r=60, rim_r=250, hub_extend=clamp(80,25,100)=80 → hub_radius_mm=140,
  rim_extend=clamp(60,25,95)=60 → rim_web_junction_mm=190,
  web_inner=clamp(22.8,8,40)=22.8 → web_inner_half_thickness_mm=22.8,
  web_outer=clamp(15,6,32)=15 → web_outer_half_thickness_mm=15。
所有值保留小数（22.8 必须写 22.8，不得取整 23）。

## 榫槽圆周分布 radius_mm 硬规则（修复"榫槽未切开轮缘外表面"）
`circular_pattern_component`（在 __assembly__ 组件）的 `params.radius_mm` 必须等于该盘的
`rim_radius_mm`（即 外径/2），使每个榫槽中心落在轮缘外表面圆周上，boolean_cut 才能切透轮缘外壁。
需求文本中的"分布半径 R"（如 `分布半径235mm`）只是提示槽数期望的圆心位置，**绝不可**直接当作
pattern 的 radius_mm 使用——若两者不等，一律以 `rim_radius_mm` 为准。

## 防占位 / 完整性硬规则
- profiles 中每个轮廓的 params 必须完整（盘体 10 项、榫槽 9 项全部给出），禁止省略任何字段。
- add_polyline.params.points 在骨架阶段仅允许 2 个占位点；最终 llm_raw 中每个 add_polyline 必须由
  profile agent 输出真实闭合轮廓点。若某项无法推导，也应给出最接近需求的合理近似值，绝不得落后于占位点。
- 特征完整性：需求文本中出现的全部特征都必须生成，不得省略。安装孔 → feat_holes；
  减重孔 → feat_lh；冷却孔 → feat_cl_0 / feat_cl_1（需求给几道就建几个组件）；
  环槽 → feat_groove_0 / feat_groove_1；枞树形榫槽 → fir_tree_cutter。逐项对照需求清单，
  在 reasoning 中列出“已生成特征 vs 需求特征”自查表。

## 图结构接线硬规则（骨架必须满足，否则 validation 拒绝）
- Composition 操作（circular_pattern_component / boolean_cut / boolean_union /
  place_component / linear_pattern_component）必须放在 `__assembly__` 组件
  （owner_dialect="composition"）的节点里。严禁放进 leaf 组件
  （turbine_disc / fir_tree_cutter 等 sketch_profile 组件）。
- boolean_cut / boolean_union 恰好 2 个 inputs（target body + tool body）；
  3+ 实体的 boolean_union 必须两两链式展开。
- 每个 sketch_profile 组件内保持完整链：create_2d_sketch → add_polyline →
  close_profile（close_profile 的 input 引用该 add_polyline 的 profile 输出）→
  (fillet_sketch) → extrude/revolve_profile。
- 榫槽 profile 的 neck/lobe/bottom 半宽必须等于 EXACT 算法实际轮廓值
  （例如 mouth=6/3齿：neck≈5.4、lobe≈7.56、bottom≈1.44），禁止使用
  1.1/2.25/0.875×mouth 名义比例；flank_angle_deg 默认 45。
- 盘体 fillet 默认：hub_web_fillet_mm=10，web_rim_fillet_mm=8；
  禁止把榫槽齿根圆角 root_fillet_mm 错填到盘体 fillet 参数中。
- 孔/环槽 cutter 组件也必须保持相同链：create_2d_sketch → add_polyline →
  close_profile → extrude_profile（孔）或 revolve_profile（环槽），
  再由 __assembly__ 中的 circular_pattern_component / boolean_cut 完成阵列与切除。
- 不要放 place_component 在 circular_pattern_component 之前（pattern 自带定位）。
- 输出名与类型契约（handler 固定返回，必须使用）：
  create_2d_sketch → 输出名 "sketch"（type=sketch）
  add_polyline / close_profile / fillet_sketch → 输出名 "profile"（type=profile）
  extrude_profile / revolve_profile / circular_pattern_component /
  linear_pattern_component / boolean_cut / boolean_union → 输出名 "body"（type=solid）
  下游 inputs 必须引用这些固定输出名（NOT 自定义名如 closed_profile / patterned_bodies）。
  boolean_cut/union 的 2 个 inputs 类型均为 "solid"。
"""

AGENT_A_SYSTEM = LEVEL2_AUTHORING_SYSTEM_PROMPT + AGENT_A_ADDENDUM

# Agent A tool schema：gcad_skeleton 用结构化 schema（显式 properties，根除 LLM
# 只回 placeholder 的空 object 空子）。浮点坐标/尺寸一律放在 nodes[].params 这个
# 宽松 object 里（to_deepseek_strict_schema 会把 type=number 强转 integer，故浮点
# 字段不能在此声明为 number，必须靠 params 宽松 object + description 保精度）。
AGENT_A_GCAD_SKELETON_SCHEMA = {
    "type": "object",
    "description": "RawGcadDocument 结构骨架：必须给出完整 nodes/components 图结构，"
                   "绝不能只回 {'_':'placeholder'} 之类占位。add_polyline.params.points 仅放 2 个占位点。",
    "properties": {
        "schema_version": {"type": "string"},
        "document_id": {"type": "string"},
        "part_name": {"type": "string"},
        "units": {"type": "string"},
        "trust_level": {"type": "string"},
        "selected_dialects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"dialect": {"type": "string"}, "version": {"type": "string"}},
                "required": ["dialect", "version"],
            },
        },
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "description": "盘体 kind_hint='turbine_disc'；榫槽切割件 kind_hint='fir_tree_cutter'；"
                               "结构根组件必须有 id='__assembly__', owner_dialect='composition'。",
                "properties": {
                    "id": {"type": "string"},
                    "owner_dialect": {"type": "string"},
                    "kind_hint": {"type": "string"},
                    "root_node": {"type": "string"},
                },
                "required": ["id", "owner_dialect"],
            },
        },
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "component": {"type": "string"},
                    "dialect": {"type": "string"},
                    "op": {"type": "string"},
                    "phase": {"type": "string"},
                    "inputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"node": {"type": "string"},
                                           "component": {"type": "string"},
                                           "output": {"type": "string"}},
                            "required": ["output"],
                        },
                    },
                    "outputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "type": {"type": "string"}},
                            "required": ["name", "type"],
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "操作参数（浮点值必须保留小数，如 points 坐标、depth_mm=21.2，"
                                       "严禁取整）。create_2d_sketch 用 plane；add_polyline 用 points；"
                                       "extrude_profile/revolve_profile 用 depth_mm/axis；"
                                       "circular_pattern_component 用 count/radius_mm/axis/rotate_copies。",
                    },
                },
                "required": ["id", "component", "dialect", "op", "phase"],
            },
        },
        "constraints": {
            "type": "object",
            "properties": {
                "require_step_file": {"type": "boolean"},
                "require_metadata_sidecar": {"type": "boolean"},
                "require_closed_solid": {"type": "boolean"},
                "expected_body_count": {"type": "integer"},
            },
            "required": ["require_step_file", "require_metadata_sidecar",
                         "require_closed_solid", "expected_body_count"],
        },
        "safety": {
            "type": "object",
            "properties": {
                "non_flight_reference_only": {"type": "boolean"},
                "not_airworthy": {"type": "boolean"},
                "not_certified": {"type": "boolean"},
                "not_for_manufacturing": {"type": "boolean"},
                "not_for_installation": {"type": "boolean"},
                "no_structural_validation": {"type": "boolean"},
                "no_life_prediction": {"type": "boolean"},
            },
            "required": ["non_flight_reference_only", "not_airworthy", "not_certified",
                         "not_for_manufacturing", "not_for_installation",
                         "no_structural_validation", "no_life_prediction"],
        },
    },
    "required": ["schema_version", "document_id", "part_name", "units", "trust_level",
                 "selected_dialects", "components", "nodes", "constraints", "safety"],
}

_DISC_PROFILE_PARAMS_SCHEMA = {
    "type": "object",
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
        "rim_transition_radius_mm": {"type": "number",
                                      "description": "复杂轮缘过渡幅度（仅复杂轮缘盘需要）"},
        "rim_transition_type": {"type": "string",
                                "description": "复杂轮缘过渡曲线类型：s_curve/ellipse/power/arc_out/arc_in"},
    },
    "required": [
        "bore_radius_mm", "hub_radius_mm", "rim_web_junction_mm", "rim_radius_mm",
        "hub_half_thickness_mm", "web_inner_half_thickness_mm",
        "web_outer_half_thickness_mm", "rim_half_thickness_mm",
        "hub_web_fillet_mm", "web_rim_fillet_mm",
    ],
    "additionalProperties": False,
}

_SLOT_PROFILE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "teeth_count": {"type": "integer"},
        "slot_depth_mm": {"type": "number"},
        "mouth_half_width_mm": {"type": "number"},
        "neck_half_width_mm": {"type": "number"},
        "lobe_half_width_mm": {"type": "number"},
        "bottom_half_width_mm": {"type": "number"},
        "flank_angle_deg": {"type": "number"},
        "root_fillet_mm": {"type": "number"},
        "bottom_fillet_mm": {"type": "number"},
    },
    "required": [
        "teeth_count", "slot_depth_mm", "mouth_half_width_mm", "neck_half_width_mm",
        "lobe_half_width_mm", "bottom_half_width_mm", "flank_angle_deg",
        "root_fillet_mm", "bottom_fillet_mm",
    ],
    "additionalProperties": False,
}

_HOLE_PROFILE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "center_x_mm": {"type": "number"},
        "center_y_mm": {"type": "number"},
        "diameter_mm": {"type": "number"},
    },
    "required": ["center_x_mm", "center_y_mm", "diameter_mm"],
    "additionalProperties": False,
}

_GROOVE_PROFILE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "inner_radius_mm": {"type": "number"},
        "outer_radius_mm": {"type": "number"},
        "z_base_mm": {"type": "number"},
        "depth_mm": {"type": "number"},
    },
    "required": ["inner_radius_mm", "outer_radius_mm", "z_base_mm", "depth_mm"],
    "additionalProperties": False,
}

AGENT_A_TOOL_SCHEMA = to_deepseek_strict_schema({
    "type": "object",
    "properties": {
        "reasoning": {"type": "string",
                      "description": "中文思考链，不少于 500 字：完整分步说明需求解析、"
                                     "参数计算、结构方案、关键决策与自查清单。"},
        "gcad_skeleton": AGENT_A_GCAD_SKELETON_SCHEMA,
        "profiles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["disc", "slot", "hole", "groove"]},
                    "params": {
                        "oneOf": [
                            _DISC_PROFILE_PARAMS_SCHEMA,
                            _SLOT_PROFILE_PARAMS_SCHEMA,
                            _HOLE_PROFILE_PARAMS_SCHEMA,
                            _GROOVE_PROFILE_PARAMS_SCHEMA,
                        ],
                        "description": "该轮廓的全部推导参数（mm）。kind=disc 必须用盘体 schema，"
                                       "kind=slot 必须用榫槽 schema，kind=hole 必须用孔 schema，"
                                       "kind=groove 必须用环槽 schema。",
                    },
                },
                "required": ["profile_id", "kind", "params"],
            },
        },
    },
    "required": ["gcad_skeleton", "profiles"],
})


# ═══════════════════════════════════════════════════════════════════════════════
# Agent B（轮廓实现）prompt —— 每类型一个 agent
# ═══════════════════════════════════════════════════════════════════════════════

_DISC_INVARIANTS = """
## 盘体轮廓硬性不变式（从参数推导，必须全部满足）
1. 默认恰好 12 点闭合 R-Z 多边形（X=R, Y=Z），hub → web → rim 三段。先给下半 6 点（y<0，
   从 bore 内壁到 rim 外端），再给上半 6 点（y>0）；上半 = 下半的精确镜像（顺序倒置、
   x 相同、y 取相反数）。
   复杂轮缘过渡例外（params 含 rim_transition_type 与 rim_transition_radius_mm）：
   总点数必须恰好 28，每侧 14 点；web-rim 交界每侧插入 8 个曲线过渡点
   （站序与曲线公式见 DISC_PROFILE_RULES，禁止省略过渡点或退回 12 点）。
2. 关键尺寸由参数直接决定：bore 半径（最小 x）= bore_radius_mm；rim 半径（最大 x）=
   rim_radius_mm；hub/rim 半厚 = y 的极值（hub_half_thickness_mm / rim_half_thickness_mm）。
3. hub 外壁是垂直段；rim 内壁是垂直阶梯；默认 web 是单一直线段（不是多段、不是水平），
   复杂轮缘时 web-rim 由曲线过渡点表达。
4. 任意相邻两点不得重合（x 与 y 不得同时相同），且距离 ≥ 1.5mm；无自交；
   首末点不重复（闭合由 close_profile 完成）。hub 外壁 / rim 内壁垂直段的两个端点必须不同。
5. 全部点满足 bore_radius_mm <= x <= rim_radius_mm。
"""

_DISC_SYSTEM = (DISC_PROFILE_RULES + _DISC_INVARIANTS if DISC_PROFILE_RULES
                else "You are the DISC PROFILE agent. " + _DISC_INVARIANTS)

_SLOT_INVARIANTS = """
## 榫槽轮廓硬性不变式（从参数推导，必须全部满足）
1. 点数由齿数决定：每侧 = 2 + 4×teeth_count + 3，总点数 = 每侧 × 2。先画上半
   （y≥0，从口部 x=0 到槽底 x=-slot_depth_mm），再画下半（y≤0）；下半 = 上半的
   精确镜像：顺序倒置、x 不变、每个 y 取相反数（y_负 = -y_正）。严禁把下半画成
   y>0 的重复折返。
   点数崩溃根因（must-fix）：Agent 常漏画槽底 3 点，导致 20/24 点而不是 26。必须补强：
   - teeth_count=T 时，上半严格 = 2（口部）+ 4×T（每齿 4 段）+ 3（槽底）= 13；T=2 时总点数必须恰好 = 26。
   - 槽底 3 段（外扩 → 槽底平台 → 收窄根部）必须逐点完整输出，缺任一点即整槽无效。
   - 逐齿 4 段（外斜面齿顶 → 齿顶平台 → 内斜面/降面 → 连接线到下一齿根）逐点完整，不得省略。
   - 逐齿 lobe 半宽强制递减：齿1 > 齿2 > ...（外宽内窄，相邻至少差 0.5mm），同子齿根 neck 也递减。
   - 输出前必须自查计数：上半点数列出后数一遍必须 = 2 + 4×teeth_count + 3；总点数 = 2 × 该值。
   - 严禁把两点合并为一点、严禁用上/下半重复折返替代槽底三段。
2. 轮廓半宽由 EXACT 算法从 mouth/teeth/depth/角度计算，严禁把 profiles 里的
   lobe_half_width_mm / neck_half_width_mm / bottom_half_width_mm 直接当坐标：
   - mouth 半宽 = mouth_half_width_mm（x=0 处第 0 点的 |y|）
   - 齿顶半宽 = 算法 crest 半宽（X_neck + h_i，逐齿外宽内窄）
   - 齿根/颈部半宽 = 算法 neck 半宽（沿共线颈部线）
   - 槽底半宽 = 算法底部收窄半宽 B_tip（≈0.24×mouth）
   输入参数是验收参考；若与算法输出不一致，一律以 EXACT 算法输出为准。
3. 所有半宽必须 > 0；lobe 之间严格递减（相邻至少差 0.5mm）。
4. lobe 半宽从 mouth 到 槽底 严格递减：lobe1 > lobe2 > ... > bottom（外宽内窄，
   齿形锁定）。相邻 lobe 必须至少相差 0.5mm；lobe 相等或递增 = 无锁定 = 错误。
5. 闭合、无自交、无重复点；任意相邻点距离 ≥ 0.5mm（模板短边修正口径，违反即无效）；
   首末点不重复。
6. 全 x ≤ 0；x=0 是口部；x=-slot_depth_mm 是槽底。齿面角 25°~55°。
反例（禁止）：root 半宽 = 0 的 V 形槽底；lobe1 = lobe2 的对称齿（无锁定）；
下半 y 未取负的折返轮廓；单调收敛的阶梯（非枞树形）；相邻点重合或 <1.5mm 短边。
"""

_SLOT_PARAMETRIC_RULES = """
### EXACT FIR-TREE SLOT SKELETON ALGORITHM (must match template exactly)
Let m = mouth_half_width_mm, n = teeth_count, target_depth = slot_depth_mm.
The following values are DERIVED from m, n, and target_depth only; do not use
neck_half_width_mm / lobe_half_width_mm / bottom_half_width_mm as direct inputs.
Use fixed angles: tfa = 45 deg, ufa = 75 deg, beta = 90 - tfa = 45 deg,
alpha = 90 + ufa = 165 deg.

Neck ratios (half-width / m), length n+1:
  n=2: [0.84, 0.64, 0.44]
  n=3: [0.90, 0.68, 0.46, 0.24]
  n=4: [0.84, 0.70, 0.56, 0.42, 0.28]

Tooth height ratios (height / m), length n:
  n=2: [0.36, 0.30]
  n=3: [0.36, 0.32, 0.28]
  n=4: [0.28, 0.26, 0.24, 0.22]

Tooth thickness ratio:
  n=2: 0.16 * m
  n=3: 0.20 * m
  n=4: 0.20 * m

Other fixed values:
  neck_platform = 1.2 (mm), H_neck = 0.6 * m,
  bottom_half_width = max(0.44 * m, last_neck_ratio * m + 0.10 * m),
  bottom_platform = 0.24 * m, bottom_tip_half = 0.24 * m,
  bottom_tip_depth = 0.16 * m, bottom_flare_angle = 60 deg.

Y-layout (fir coordinates: X = half-width, Y = radial negative):
  ys_root[0] = -H_neck, y = ys_root[0]
  For i in 0..n-1:
    h_i = height_ratio[i] * m
    thick = thickness
    dy_ext = h_i * tan(beta)
    y_tip = y - dy_ext
    y_plat = y_tip - thick
    dx_under = h_i + neck_half[i] - neck_half[i+1]
    dy_under = dx_under * (-tan(alpha))
    y_under = y_plat - dy_under
    y_conn = y_under - neck_platform
    append y_tip, y_plat, y_under, y_conn; y = y_conn
    ys_root.append(y_conn)   # 下一齿根 = 当前连接线终点（i+1 的 root）

Neck collinearity line:
  X_neck(y) passes through (neck_half[0], ys_root[0]) and
  (neck_half[n], ys_under[n-1]); interpolate linearly.
  # MUST-FIX（必须写进沙箱代码）：
  # root_i / under_i / conn_last 必须由 X_neck(y) 显式线性插值得到；
  # 禁止把 neck_half_width_mm / lobe_half_width_mm / bottom_half_width_mm 当坐标直接使用。

Depth fitting:
  Natural depth = abs(B_tip_Y) after building the skeleton.
  If natural depth > target_depth, reduce neck_platform by
  (natural_depth - target_depth) / n, but never below 0.3, and repeat.
  If natural depth < target_depth, keep the natural depth.
  禁止为凑满 target_depth 而拉长卡榫平台/连接线：模板按自然深度输出，
  槽底 x 就是自然深度对应的值（可小于 slot_depth_mm）。

Short-edge correction (must match template):
  对生成的 upper 点序列（槽坐标 x_mm=径向、y_mm=半宽），相邻点欧氏距离 < 0.5mm 时，
  把后一点的 x_mm 沿 -x 方向（更向中心）外推到与前一点欧氏距离恰为 0.5mm 的位置
  （dx = sqrt(0.5^2 - dy^2)，保持 y_mm 半宽不变），迭代至所有边 >= 0.5mm；
  首点 (0, mouth) 固定不移动。下侧镜像继承修正后的上侧坐标。

Half-vertices (right side):
  A0 = (m, 0)
  root_i = (X_neck(ys_root[i]), ys_root[i])   # i>0 时 ys_root[i] = ys_conn[i-1]
  crest_i = (root_i.X + h_i, ys_tip[i])
  # MUST-FIX：crest_i.X 必须使用第 i 齿自己的根（ys_root[i]），
  # 禁止全部用 ys_root[0]；否则第 2..n 齿顶半宽会偏大。
  plat_i = (crest_i.X, ys_plat[i])
  under_i = (X_neck(ys_under[i]), ys_under[i])
  conn_last = (X_neck(ys_conn[-1]), ys_conn[-1])
  conn_last_X = X_neck(ys_conn[-1])
  conn_last_Y = ys_conn[-1]
  flare_y = conn_last_Y - (bottom_half_width - conn_last_X) / tan(60 deg)
  # MUST-FIX：flare 必须用 X_neck(ys_conn[-1])（连接线终点的实际半宽），
  # 禁止用 neck_half[n]（最后一个名义颈部半宽）代替，否则槽底 x 整体偏移约 0.18mm。
  B_flare = (bottom_half_width, flare_y)
  B_plat = (bottom_half_width, B_flare.Y - bottom_platform)
  B_tip = (bottom_tip_half, B_plat.Y - bottom_tip_depth)
  最终槽底收窄半宽 = B_tip 的半宽 = bottom_tip_half = 0.24 × m；
  profiles 的 bottom_half_width_mm 必须等于该最终槽底半宽（不是 flare/平台值）。

Convert to slot coordinates: x = Y, y = X.
Upper points:
  0: (0, m)
  1: (ys_root[0], neck_half[0])
  For each i: crest, plat, under, root_next/conn in that order.
  Bottom: flare, platform, tip.
Upper count must be 2 + 4*n + 3.
Lower half = reversed mirror of upper with y negated.

## COORDINATE CONVERSION EXAMPLE (must-fix)
fir 坐标 (X=半宽, Y=径向负) 与槽坐标 (x_mm=径向深度, y_mm=半宽) 必须交换：
  A0 = (X=8.0, Y=0.0)   → (x_mm=0.0, y_mm=8.0)   # 口部
  root1 = (X=6.72, Y=-4.8) → (x_mm=-4.8, y_mm=6.72)
  crest1 = (X=9.6, Y=-7.68) → (x_mm=-7.68, y_mm=9.6)
绝不允许把 fir 坐标原样写进 x_mm/y_mm；mouth 点的 x_mm 必须等于 0，
y_mm 必须等于 mouth_half_width_mm。

## OUTPUT PROTOCOL (must-fix)
1. run_python_code 的最后一行必须 print(json.dumps({"points": [...]}))，
   输出最终 26/34/42 个点（{"x_mm":..., "y_mm":...} 字典数组）。
2. run_python_code 内必须显式计算 X_neck(y) 并输出齿根/颈部/连接线点；
   若代码直接把 neck_half_width_mm / lobe_half_width_mm / bottom_half_width_mm
   当作齿根/齿顶/槽底坐标，视为无效。
3. emit_profile_points 的 points 必须逐字复制该 JSON 内容，禁止手抄、重算或改写任何坐标。
"""

_SLOT_SYSTEM = (SLOT_PROFILE_RULES + _SLOT_PARAMETRIC_RULES + _SLOT_INVARIANTS
                if SLOT_PROFILE_RULES
                else "You are the FIR-TREE SLOT PROFILE agent. " + _SLOT_INVARIANTS)

_HOLE_INVARIANTS = """
## 孔 cutter 轮廓硬性不变式（从参数推导）
1. 恰好 16 点闭合 XY 多边形，近似圆心位于 (center_x_mm, center_y_mm)，半径 = diameter_mm / 2。
2. 所有点必须满足半径误差 ≤ 2%（|distance(center, point) - radius| ≤ 0.02×radius）。
3. 相邻点不重合，轮廓无自交，首末点不重复（闭合由 close_profile 完成）。
4. 必须只输出一个孔的 cutter 轮廓；阵列数量和分布半径由整体设计 agent 在
   circular_pattern_component 中声明，不属于本轮廓。
"""

_HOLE_SYSTEM = "You are the HOLE CUTTER PROFILE agent. " + _HOLE_INVARIANTS

_GROOVE_INVARIANTS = """
## 环槽 cutter 轮廓硬性不变式（从参数推导）
1. 恰好 4 点闭合 XZ 矩形截面，代表旋转切除的环槽/环形腔截面。
2. 四个角点由 inner_radius_mm / outer_radius_mm / z_base_mm / depth_mm 决定：
   (inner_radius_mm, z_base_mm) → (outer_radius_mm, z_base_mm) →
   (outer_radius_mm, z_base_mm + depth_mm) → (inner_radius_mm, z_base_mm + depth_mm)。
3. outer_radius_mm 必须大于 inner_radius_mm，depth_mm > 0。
4. 相邻点不重合，无自交，首末点不重复。
"""

_GROOVE_SYSTEM = "You are the GROOVE CUTTER PROFILE agent. " + _GROOVE_INVARIANTS

# 轮廓 agent tool schema：points 显式声明 x_mm/y_mm 属性。
# 此前 items 是裸 object（无 properties），to_deepseek_strict_schema 会自动补
# {"_":{"type":"string"}} 占位键 → DeepSeek 只能把坐标拼成 "_":"0,8" 字符串，
# 导致榫槽坐标格式崩溃（_compare_agentic 三 run 全部复现）。补全 properties 后
# LLM 被要求逐点输出 {x_mm, y_mm} 字典。
_PROFILE_TOOL_SCHEMA = to_deepseek_strict_schema({
    "type": "object",
    "properties": {
        "profile_id": {"type": "string"},
        "reasoning": {"type": "string",
                      "description": "中文思考链，不少于 400 字：完整分步说明参数→坐标推导、"
                                     "点数公式、对称镜像、不变式逐项自查。"},
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "x_mm": {"type": "number",
                             "description": "轮廓点 x 坐标（浮点，保留输入小数精度）"},
                    "y_mm": {"type": "number",
                             "description": "轮廓点 y 坐标（浮点，保留输入小数精度）"},
                },
                "required": ["x_mm", "y_mm"],
                "additionalProperties": False,
                "description": "轮廓点，必须为含 x_mm/y_mm 的浮点字典，严禁用字符串拼接",
            },
        },
    },
    "required": ["profile_id", "points"],
})



# kind_hint → profile kind（骨架路由）
_KIND_HINT_TO_KIND = {
    "turbine_disc": "disc",
    "fir_tree_cutter": "slot",
    "hole_cutter": "hole",
    "groove_cutter": "groove",
}


def _profile_system(kind: str) -> str:
    if kind == "disc":
        return _DISC_SYSTEM
    if kind == "slot":
        return _SLOT_SYSTEM
    if kind == "hole":
        return _HOLE_SYSTEM
    if kind == "groove":
        return _GROOVE_SYSTEM
    return _SLOT_SYSTEM


def _is_mirror_of(a: list, b: list, tol: float = 0.05) -> bool:
    """判断 b 是否为 a 的精确镜像（顺序倒置 + y 取负）。"""
    if len(a) != len(b):
        return False
    for p, q in zip(a, reversed(b)):
        try:
            if abs(float(p["x_mm"]) - float(q["x_mm"])) > tol:
                return False
            if abs(float(p["y_mm"]) + float(q["y_mm"])) > tol:
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def _normalize_profile_points(points: list | None) -> list | None:
    """把轮廓点统一为 [{x_mm, y_mm}, ...]，兼容 {"_":"x,y"} 与 [x, y] 形式。"""
    if not isinstance(points, list) or not points:
        return points

    def _to_point(p):
        if isinstance(p, dict):
            if "x_mm" in p and "y_mm" in p:
                return {"x_mm": float(p["x_mm"]), "y_mm": float(p["y_mm"])}
            raw = p.get("_")
            if isinstance(raw, str) and "," in raw:
                parts = raw.split(",")
                if len(parts) == 2:
                    return {"x_mm": float(parts[0]), "y_mm": float(parts[1])}
            return None
        if isinstance(p, (list, tuple)) and len(p) == 2:
            try:
                return {"x_mm": float(p[0]), "y_mm": float(p[1])}
            except (TypeError, ValueError):
                return None
        return None

    out = []
    for p in points:
        converted = _to_point(p)
        if converted is None:
            return points
        out.append(converted)
    deduped = []
    for p in out:
        if deduped:
            last = deduped[-1]
            if abs(p["x_mm"] - last["x_mm"]) < 1e-9 \
                    and abs(p["y_mm"] - last["y_mm"]) < 1e-9:
                continue
        deduped.append(p)
    return deduped


def _expected_profile_point_count(kind: str, params: dict) -> int | None:
    if kind == "disc":
        if params.get("rim_transition_type") or params.get("rim_transition_radius_mm") is not None:
            return 28
        return 12
    if kind == "slot":
        try:
            teeth = int(params.get("teeth_count") or 2)
        except (TypeError, ValueError):
            teeth = 2
        return 2 * (2 + 4 * teeth + 3)
    if kind == "hole":
        return 16
    if kind == "groove":
        return 4
    return None


def _slot_shape_issue(pts: list, params: dict) -> str | None:
    """榫槽轮廓形状问题描述（None=通过）。只做确定性可判的硬约束。"""
    try:
        depth = float(params.get("slot_depth_mm", 0) or 0)
        mouth = float(params.get("mouth_half_width_mm", 0) or 0)
        teeth = int(params.get("teeth_count") or 0)
    except (TypeError, ValueError):
        return "榫槽参数无效"
    if teeth > 0:
        expected = 2 * (2 + 4 * teeth + 3)
        if len(pts) != expected:
            return f"点数 {len(pts)} != 期望 {expected}（teeth_count={teeth}）"
    xs = [float(p.get("x_mm", 0)) for p in pts]
    ys = [float(p.get("y_mm", 0)) for p in pts]
    if max(xs) > 0.5:
        return f"榫槽口部 x 越界：实际最大 {round(max(xs), 3)}"
    if depth > 0 and min(xs) < -depth - 1.0:
        return f"榫槽深度超出上限 slot_depth_mm={depth}：实际最深 {round(min(xs), 3)}"
    if len(pts) % 2 != 0:
        return "榫槽点数必须为偶数（关于 y=0 对称）"
    half = len(pts) // 2
    for i in range(half):
        r = pts[i]
        l = pts[len(pts) - 1 - i]
        try:
            if abs(float(r["x_mm"]) - float(l["x_mm"])) > 0.05 \
                    or abs(float(r["y_mm"]) + float(l["y_mm"])) > 0.05:
                return f"榫槽上下半不镜像对称（点 {i}）"
        except (KeyError, TypeError, ValueError):
            return "榫槽点格式非法"
    if mouth > 0 and (abs(abs(ys[0]) - mouth) > 0.5
                      or abs(abs(ys[-1]) - mouth) > 0.5):
        return (f"榫槽口部半宽必须为 mouth_half_width_mm={mouth}："
                f"实际 {round(abs(ys[0]), 3)}/{round(abs(ys[-1]), 3)}")
    if mouth > 0:
        upper = [abs(v) for v in ys[:half]]
        peaks = []
        for i in range(1, half - 1):
            if upper[i] > upper[i - 1] and upper[i] >= upper[i + 1]:
                peaks.append(upper[i])
        if peaks and any(a <= b for a, b in zip(peaks, peaks[1:])):
            return f"榫槽 lobe 半宽未严格递减：{[round(v, 3) for v in peaks]}"
        for i in range(teeth):
            ci = 2 + 4 * i
            pi = ci + 1
            ui = ci + 2
            conn_i = ci + 3
            if conn_i >= half:
                break
            yc, yp, yu = upper[ci], upper[pi], upper[ui]
            if abs(yc - yp) > 0.2:
                return f"齿 {i + 1} 齿顶/平台半宽不一致（点序可能多插了齿根点）"
            prev = upper[1] if i == 0 else upper[conn_i - 1]
            if yc <= prev + 0.1:
                return f"齿 {i + 1} 齿顶半宽应高于前一连接线终点（点序可能多插了齿根点）"
            if yu >= yc - 0.1:
                return f"齿 {i + 1} 内斜面终点应低于齿顶"
        for i in range(1, half):
            if math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]) < 0.1:
                return f"相邻点距离过近（点 {i - 1}→{i}），轮廓退化"
    return None


def _disc_shape_issue(pts: list, params: dict) -> str | None:
    """盘体轮廓通用校验：只核对需求直接给出的关键尺寸，不校验模板派生站。"""
    try:
        bore_r = float(params.get("bore_radius_mm", 0) or 0)
        rim_r = float(params.get("rim_radius_mm", 0) or 0)
        hub_half = float(params.get("hub_half_thickness_mm", 0) or 0)
        rim_half = float(params.get("rim_half_thickness_mm", 0) or 0)
    except (TypeError, ValueError):
        return "盘体参数无效"
    if not pts:
        return "没有有效轮廓点"
    xs = [float(p.get("x_mm", 0)) for p in pts]
    tol = 0.5
    if bore_r and abs(min(xs) - bore_r) > tol:
        return f"bore 半径应为 {bore_r}：实际最小 x {round(min(xs), 3)}"
    if rim_r and abs(max(xs) - rim_r) > tol:
        return f"rim 半径应为 {rim_r}：实际最大 x {round(max(xs), 3)}"
    if hub_half and not any(
            abs(abs(p["y_mm"]) - hub_half) <= tol and abs(p["x_mm"] - bore_r) <= tol
            for p in pts):
        return f"bore 内壁点 y 应等于 ±hub_half_thickness_mm={hub_half}"
    if rim_half and not any(
            abs(abs(p["y_mm"]) - rim_half) <= tol and abs(p["x_mm"] - rim_r) <= tol
            for p in pts):
        return f"rim 外端点 y 应等于 ±rim_half_thickness_mm={rim_half}"
    return None


def _feature_shape_issue(kind: str, pts: list, params: dict) -> str | None:
    """hole/groove 轮廓的轻量几何不变式检查（None=通过）。"""
    if not all(isinstance(p, dict) for p in pts):
        return "轮廓点格式非法"
    if kind == "groove":
        try:
            inner = float(params.get("inner_radius_mm") or 0)
            outer = float(params.get("outer_radius_mm") or 0)
            z_base = float(params.get("z_base_mm") or 0)
            depth = float(params.get("depth_mm") or 0)
        except (TypeError, ValueError):
            return "groove 参数无效"
        if len(pts) != 4:
            return "groove 点数 != 4"
        if any(abs(float(p.get("x_mm", 0)) - inner) > 0.01
               and abs(float(p.get("x_mm", 0)) - outer) > 0.01 for p in pts):
            return "groove x 不在 inner/outer 半径上"
        if any(abs(float(p.get("y_mm", 0)) - z_base) > 0.01
               and abs(float(p.get("y_mm", 0)) - (z_base + depth)) > 0.01
               for p in pts):
            return "groove y 不在 z_base/z_base+depth 上"
        return None
    if kind == "hole":
        try:
            cx = float(params.get("center_x_mm", 0) or 0)
            cy = float(params.get("center_y_mm", 0) or 0)
            radius = float(params.get("diameter_mm") or 0) / 2.0
        except (TypeError, ValueError):
            return "hole 参数无效"
        if radius <= 0:
            return "hole 半径无效"
        for p in pts:
            d = math.hypot(float(p.get("x_mm", 0)) - cx,
                           float(p.get("y_mm", 0)) - cy)
            if abs(d - radius) > 0.02 * radius + 0.01:
                return f"hole 点半径误差超 2%: {round(d, 3)} vs {radius}"
        return None
    return None


def _profile_points_issue(kind: str, pts: list, params: dict) -> str | None:
    """轮廓点的统一轻量校验：点数 + 几何不变式（None=通过）。"""
    if not isinstance(pts, list) or not pts:
        return "没有有效轮廓点"
    expected = _expected_profile_point_count(kind, params)
    if expected is not None and len(pts) != expected:
        return f"点数 {len(pts)} != 期望 {expected}"
    if kind == "slot":
        return _slot_shape_issue(pts, params)
    if kind == "disc":
        return _disc_shape_issue(pts, params)
    if kind in ("hole", "groove"):
        return _feature_shape_issue(kind, pts, params)
    if kind == "disc" and len(pts) % 2 == 0:
        half = len(pts) // 2
        if not _is_mirror_of(pts[:half], pts[half:]):
            return "轮廓上下半不镜像对称"
    return None


def _profile_user_requirements(kind: str) -> str:
    """Agent B user 层的逐项操作指令（与 system 不变式配套，强化关键点）。"""
    if kind == "disc":
        return ("  - reasoning 字段必须完整分步说明：参数如何映射到坐标、"
                "点数选择（默认 12 / 复杂轮缘 28）、上下半如何镜像、逐项自查点数/范围/最小边长。"
                "不少于 400 字。\n"
                "  - 默认恰好 12 点（params 未含 rim_transition_type/rim_transition_radius_mm）："
                "先下半 6 点(y<0, 从 bore 内壁到 rim 外端)，再上半 6 点(y>0)；"
                "上半 = 下半倒序且 y 取负。\n"
                "  - 复杂轮缘过渡（params 含 rim_transition_type 与 rim_transition_radius_mm）："
                "总点数必须恰好 28，每侧 14 点；除默认 12 点站序外，web-rim 交界每侧插入 8 个"
                "曲线过渡点：u=i/9（i=1..8），z 从 -web_outer_half_thickness_mm 到 "
                "-rim_half_thickness_mm 线性均分，r = rim_web_junction_mm + "
                "rim_transition_radius_mm × f(u)，f(u) 按 rim_transition_type 取值"
                "（s_curve=sin(πu)²、ellipse=sin(πu)^0.7、power=sin(πu)·√u、"
                "arc_out=sin(πu)、arc_in=0.5·sin(πu)）；过渡点必须用 run_python_code "
                "计算并逐字复制，禁止手工近似或省略。\n"
                "  - x 范围 [bore_radius_mm, rim_radius_mm]。\n"
                "  - 下半 6 点必须严格按站序输出（x 从小到大）：\n"
                "      1 (bore_radius_mm, -hub_half_thickness_mm)\n"
                "      2 (hub_radius_mm, -hub_half_thickness_mm)\n"
                "      3 (hub_radius_mm, -web_inner_half_thickness_mm)\n"
                "      4 (rim_web_junction_mm, -web_outer_half_thickness_mm)\n"
                "      5 (rim_web_junction_mm, -rim_half_thickness_mm)\n"
                "      6 (rim_radius_mm, -rim_half_thickness_mm)\n"
                "    其中 2→3 是 x=hub_radius_mm 的垂直 hub 外壁，3→4 是唯一一段腹板直线，"
                "4→5 是 x=rim_web_junction_mm 的垂直 rim 内壁；\n"
                "    严禁把 hub 外壁画在 bore 处，严禁缺少 hub 底角或 rim 内壁阶梯。\n"
                "  - 必须先调用 run_python_code/evaluate_math 按上述站序生成并自查，再 emit。\n")
    if kind == "slot":
        return ("  - reasoning 字段必须完整分步说明：点数公式 2+4×N+3 的推导、"
                "每个关键点坐标如何由 EXACT 算法算出、lobe 递减与槽底半宽计算、"
                "下半镜像与自查结果。不少于 400 字。\n"
                "  - 每侧点数 = 2 + 4×teeth_count + 3，总点 = 每侧×2；先上半(y≥0)后下半(y≤0)。\n"
                "  - 下半 = 上半倒序且每个 y 取负（y_负 = -y_正），严禁 y>0 折返。\n"
                "  - lobe 半宽从口部到槽底严格递减，每级至少差 0.5mm。\n"
                "  - 槽底最终收窄半宽 = 0.24×mouth_half_width_mm（EXACT 算法实际值，"
                "不是参数表里的名义 bottom_half_width_mm），必须 > 0；所有 x ≤ 0。\n"
                "  - 禁止把 lobe_half_width_mm / neck_half_width_mm 直接当齿顶/齿根坐标："
                "它们只是验收参考，坐标必须按 EXACT 算法（neck 比例 + 齿高 + X_neck）计算；"
                "若按名义 lobe=2.25×mouth 画，槽宽会超过周向节距导致槽重叠。\n"
                "  - 齿根/颈部/连接线点必须位于 X_neck(y) 直线上：在 run_python_code 中"
                "先由 (neck_half[0], ys_root[0]) 与 (neck_half[n], ys_under[n-1]) 定义直线，"
                "再输出 root/under/conn 点；禁止把参数表中的 neck_half_width_mm 当作齿根 y "
                "直接使用。\n"
                "  - 每个齿顶 crest_i.X = X_neck(ys_root[i]) + h_i，其中 i>0 的 ys_root[i] "
                "是上一齿连接线终点（ys_conn[i-1]），严禁全部用 ys_root[0]。\n"
                "  - 必须在本轮 仅一次 的 emit_profile_points 调用中返回 points（合法 JSON 数组）；\n"
                "    禁止省略调用、禁止返回空数组、禁止仅返回占位点。\n"
                "  - 若已用 run_python_code 得到 points JSON，emit 时必须逐字复制，禁止手工重抄/重算。\n"
                "  - 总点数必须恰好 = 2 × (2 + 4×teeth_count + 3)；teeth_count=2 时 = 26。返回前逐点自查计数，绝不缺槽底点。\n"
                "  - 关键派生值自查（EXACT 算法必须满足）：\n"
                "      第 1 点（口部楔入）x ≈ -0.6×mouth_half_width_mm，|y| ≈ 0.84/0.90/0.84×mouth（齿数 2/3/4）；\n"
                "      首齿齿顶 |y| ≈ (0.84/0.90/0.84 + 0.36/0.36/0.28)×mouth；\n"
                "      槽底最深处 |y| = 0.24×mouth；\n"
                "      用 run_python_code 计算这些数值并逐点核对后再 emit。\n")
    if kind == "hole":
        return ("  - reasoning 字段必须完整分步说明：圆心、半径、16 点角度分布与自查结果。不少于 200 字。\n"
                "  - 恰好 16 点；所有点到圆心距离 = diameter_mm / 2，误差不超过 2%。\n"
                "  - 相邻点不重合，无自交；首末点不重复。\n")
    if kind == "groove":
        return ("  - reasoning 字段必须完整分步说明：四个角点坐标如何由 inner/outer/z_base/depth 推出。不少于 200 字。\n"
                "  - 恰好 4 点，闭合矩形截面；outer > inner，depth > 0。\n")
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# 工具调用
# ═══════════════════════════════════════════════════════════════════════════════

def _call_tool(caller, system: str, user: str, tool_name: str,
               tool_desc: str, schema: dict, model_config,
               stream: bool = False, on_reasoning_token=None):
    tc = caller.call_strict_tool(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        tool_name=tool_name, tool_description=tool_desc,
        tool_schema=schema, model_config=model_config,
        stream=stream, on_reasoning_token=on_reasoning_token)
    return tc.arguments


def _eval_math_expression(expression: str, variables: dict) -> float:
    import ast
    import math
    node = ast.parse(expression, mode="eval")
    allowed = {name: getattr(math, name) for name in dir(math) if not name.startswith("_")}
    allowed["clamp"] = lambda v, lo, hi: max(lo, min(hi, v))
    allowed["min"] = min
    allowed["max"] = max
    allowed["round"] = round
    allowed["abs"] = abs
    allowed["range"] = range
    allowed["len"] = len
    allowed["sum"] = sum
    allowed["list"] = list
    allowed["tuple"] = tuple
    allowed["dict"] = dict
    allowed["str"] = str
    allowed["int"] = int
    allowed["float"] = float
    allowed.update({k: v for k, v in (variables or {}).items() if isinstance(v, (int, float))})
    code = compile(node, "<math_expr>", "eval")
    allowed["__builtins__"] = {}
    return eval(code, allowed)


def _eval_math_tool(args: dict) -> dict:
    """evaluate_math 的容错 handler：单表达式错误返回提示，不中断整个流程。"""
    try:
        return {"ok": True,
                "result": _eval_math_expression(
                    args.get("expression", ""), args.get("variables", {}) or {})}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "hint": "evaluate_math 只接受单个表达式；多语句计算请改用 run_python_code。",
        }


def _run_python_sandbox(code: str, variables: dict) -> dict:
    import json
    import os
    wrapped = (
        "import json, math, sys\n"
        f"INPUTS = {json.dumps(variables or {}, ensure_ascii=False)}\n"
        f"{code}"
    )
    try:
        from seekflow.sandbox import LocalThreadSandbox
        result = LocalThreadSandbox().execute(
            wrapped,
            timeout=10.0,
            env=os.environ.copy(),
        )
        return {
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": result.error,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


_EVAL_MATH_SCHEMA = {
    "type": "object",
    "properties": {
        "expression": {"type": "string",
                       "description": "数学表达式，可使用 math 函数与 variables 中的变量"},
        "variables": {"type": "object", "description": "数值变量字典"},
    },
    "required": ["expression"],
    "additionalProperties": False,
}

_RUN_PYTHON_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string",
                 "description": "纯 Python 计算代码，INPUTS 为输入字典，最后 print 结果"},
        "variables": {"type": "object", "description": "输入变量字典"},
    },
    "required": ["code"],
    "additionalProperties": False,
}

def _loads_json(raw):
    try:
        return json.loads(raw)
    except Exception:
        fixed = raw.replace(": {}}", ": {}").replace(": }", ": {}")
        if fixed != raw:
            opens = fixed.count("{")
            closes = fixed.count("}")
            if opens > closes:
                fixed += "}" * (opens - closes)
            try:
                return json.loads(fixed)
            except Exception:
                pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end+1])
        raise


def _decode_tool_arguments(raw):
    """Decode tool arguments that may be JSON double-encoded or wrapped."""
    value = _loads_json(raw)
    if isinstance(value, str):
        try:
            value = _loads_json(value)
        except Exception:
            pass
    return value


_GENERIC_CALC_TOOLS = {
    "evaluate_math": {
        "description": "通用数学表达式计算，避免 LLM 手动做复杂算术。",
        "schema": _EVAL_MATH_SCHEMA,
        "handler": _eval_math_tool,
    },
    "run_python_code": {
        "description": "通用 Python 沙箱，LLM 可写代码计算几何量；INPUTS 为输入字典。",
        "schema": _RUN_PYTHON_SCHEMA,
        "handler": lambda args: _run_python_sandbox(
            args.get("code", ""), args.get("variables", {}) or {}),
    },
}

# 计算复杂度标注：
# - simple: 只含加减乘除/直接赋值，LLM 可直接输出，出错风险极低。
# - complex: 含三角函数、迭代求解、多参数联动，必须调用通用计算工具。
_PROFILE_COMPLEXITY = {
    "disc": "simple",
    "hole": "complex",
    "slot": "complex",
    "groove": "simple",
}


def _complexity_note(kind: str) -> str:
    if _PROFILE_COMPLEXITY.get(kind) == "complex":
        return (f"该 {kind} 轮廓属于 COMPLEX 计算：必须先调用 run_python_code 或 "
                f"evaluate_math 完成计算，禁止直接手工构造 points。")
    return (f"该 {kind} 轮廓属于 SIMPLE 计算：可直接根据参数构造 points；"
            f"如不放心也可调用通用工具复核。")


def _accumulate_usage(usage: dict | None, response) -> None:
    """Record OpenAI-style usage counters into the caller-provided dict."""
    if usage is None:
        return
    try:
        u = response.usage
        usage["prompt_tokens"] += int(getattr(u, "prompt_tokens", 0) or 0)
        usage["completion_tokens"] += int(getattr(u, "completion_tokens", 0) or 0)
        usage["total_tokens"] += int(getattr(u, "total_tokens", 0) or 0)
    except Exception:  # noqa: BLE001
        pass


def _call_profile_with_tools(caller, system: str, user: str, kind: str,
                             model_config, max_rounds: int = 8,
                             trace: list | None = None,
                             params: dict | None = None,
                             usage: dict | None = None) -> dict:
    """Profile agent tool loop.

    The LLM may call the matching compute_profile tool to obtain exact points,
    then must call emit_profile_points with those points unchanged.
    """
    if type(caller).__name__ != "DeepSeekToolCaller" and not hasattr(caller, "call_with_tools"):
        return _call_tool(
            caller, system, user,
            "emit_profile_points", f"{kind} 轮廓坐标生成",
            _PROFILE_TOOL_SCHEMA, model_config,
        )

    import json
    import os
    import re
    from openai import OpenAI
    from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
        to_deepseek_strict_schema,
    )

    _api_key_env = getattr(model_config, "api_key_env", "DEEPSEEK_API_KEY")
    api_key = os.environ.get(_api_key_env, "")
    if not api_key:
        raise LlmToolCallError(f"{_api_key_env} not set for profile tool loop",
                               code="provider_no_auth")
    client = OpenAI(api_key=api_key, base_url=model_config.base_url,
                    timeout=model_config.timeout_s)

    tools = []
    for tool_name, spec in _GENERIC_CALC_TOOLS.items():
        tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": spec["description"],
                "strict": False,
                "parameters": spec["schema"],
            },
        })
    tools.append({
        "type": "function",
        "function": {
            "name": "emit_profile_points",
            "description": "输出最终轮廓点",
            "strict": False,
            "parameters": _PROFILE_TOOL_SCHEMA,
        },
    })
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    used_tool = False
    tool_rounds = 0
    if trace is not None:
        trace.append({"stage": f"profile_{kind}_start", "user": user[:800]})

    for _ in range(max_rounds):
        create_kwargs = {
            "model": model_config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "extra_body": ({"thinking": model_config.thinking} if getattr(model_config, "thinking", None) else {}),
            "temperature": model_config.temperature if model_config.temperature is not None else 0.3,
        }
        if getattr(model_config, "seed", None) is not None:
            create_kwargs["seed"] = model_config.seed
        response = client.chat.completions.create(**create_kwargs)
        _accumulate_usage(usage, response)
        message = response.choices[0].message
        if not message.tool_calls:
            retry_messages = messages + [
                {"role": "assistant", "content": message.content or ""},
                {"role": "user", "content": "You must call one of the provided tools now."},
            ]
            retry_kwargs = dict(create_kwargs)
            retry_kwargs["messages"] = retry_messages
            retry_kwargs.pop("seed", None)
            response = client.chat.completions.create(**retry_kwargs)
            message = response.choices[0].message
        if not message.tool_calls:
            raise LlmToolCallError("profile tool loop returned no tool call",
                                   code="provider_no_tool_call")
        call = message.tool_calls[0]
        if call.function.name == "emit_profile_points":
            if tool_rounds < 2 and _PROFILE_COMPLEXITY.get(kind) == "complex" and not used_tool:
                messages.append({
                    "role": "user",
                    "content": _complexity_note(kind) + " 请先调用工具，再 emit_profile_points。",
                })
                continue
            try:
                final = _decode_tool_arguments(call.function.arguments)
            except Exception:
                messages.append({
                    "role": "user",
                    "content": "上一次工具输出不是合法 JSON。请重新调用 emit_profile_points，输出完整、合法的 JSON arguments。",
                })
                continue
            if params:
                pts = _normalize_profile_points(final.get("points") or []) or []
                issue = _profile_points_issue(kind, pts, params)
                if issue:
                    if trace is not None:
                        trace.append({
                            "stage": f"profile_{kind}_validation",
                            "kind": kind,
                            "issue": issue,
                        })
                    messages.append({
                        "role": "user",
                        "content": f"轮廓校验未通过：{issue}。"
                                   "请修正后重新 emit_profile_points，禁止原样重复。",
                    })
                    continue
            if trace is not None:
                trace.append({"stage": f"profile_{kind}_final",
                              "kind": kind, "final": final})
            return final
        if call.function.name not in _GENERIC_CALC_TOOLS:
            raise LlmToolCallError(f"unexpected tool {call.function.name}",
                                   code="provider_wrong_tool_name")
        if tool_rounds >= 6:
            messages.append({
                "role": "user",
                "content": "已达到 6 次工具调用上限，禁止再调用工具；请立即 emit_profile_points。",
            })
            continue
        used_tool = True
        tool_rounds += 1
        try:
            args = _decode_tool_arguments(call.function.arguments)
        except Exception:
            messages.append({
                "role": "user",
                "content": "上一次工具参数输出不是合法 JSON。请重新调用工具，输出完整、合法的 JSON arguments。",
            })
            continue
        tool_result = _GENERIC_CALC_TOOLS[call.function.name]["handler"](args)
        if trace is not None:
            trace.append({
                "stage": f"profile_{kind}_tool",
                "kind": kind,
                "tool": call.function.name,
                "args": args,
                "result": str(tool_result)[:2000],
            })
        if call.function.name == "run_python_code":
            stdout = str(tool_result.get("stdout") or "")
            try:
                parsed = json.loads(stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                parsed = None
            if isinstance(parsed, dict) and isinstance(parsed.get("points"), list):
                match = re.search(r"\[([\w\-]+)\]", user)
                pid = match.group(1) if match else "profile"
                pts = _normalize_profile_points(parsed["points"]) or []
                issue = _profile_points_issue(kind, pts, params) if params else None
                if issue:
                    if trace is not None:
                        trace.append({
                            "stage": f"profile_{kind}_validation",
                            "kind": kind,
                            "issue": issue,
                        })
                    messages.append({
                        "role": "user",
                        "content": f"沙箱输出的轮廓校验未通过：{issue}。"
                                   "请修正代码后重新计算，再 emit_profile_points。",
                    })
                    continue
                if trace is not None:
                    trace.append({
                        "stage": f"profile_{kind}_sandbox_final",
                        "kind": kind,
                        "profile_id": pid,
                        "final": {"profile_id": pid, "points": parsed["points"]},
                    })
                return {"profile_id": pid, "points": parsed["points"]}
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name,
                             "arguments": call.function.arguments},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(tool_result, ensure_ascii=False),
        })
        messages.append({
            "role": "user",
            "content": "计算完成。若还需要其他计算可继续调用工具；"
                       "一旦 ready，请立即调用 emit_profile_points 输出最终 points。",
        })
        if tool_rounds >= 4:
            messages.append({
                "role": "user",
                "content": "你已反复调用计算工具多次。请立即调用 emit_profile_points "
                           "一次性输出最终 points，禁止再次调用任何计算工具。",
            })
    raise LlmToolCallError("profile tool loop did not emit points",
                           code="tool_loop_exhausted")


def _call_design_with_tools(caller, system: str, user: str,
                            model_config, max_rounds: int = 8,
                            trace: list | None = None,
                            usage: dict | None = None,
                            requirement_text: str | None = None) -> dict:
    """Agent A tool loop: resolve groove params via tool, then emit design plan."""
    if type(caller).__name__ != "DeepSeekToolCaller" and not hasattr(caller, "call_with_tools"):
        return _call_tool(caller, system, user, "emit_design_plan",
                          "整体设计", AGENT_A_TOOL_SCHEMA, model_config)

    import json
    import os
    from openai import OpenAI

    _api_key_env = getattr(model_config, "api_key_env", "DEEPSEEK_API_KEY")
    api_key = os.environ.get(_api_key_env, "")
    if not api_key:
        raise LlmToolCallError(f"{_api_key_env} not set for design tool loop",
                               code="provider_no_auth")
    client = OpenAI(api_key=api_key, base_url=model_config.base_url,
                    timeout=model_config.timeout_s)
    tools = []
    for tool_name, spec in _GENERIC_CALC_TOOLS.items():
        tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": spec["description"],
                "strict": False,
                "parameters": spec["schema"],
            },
        })
    tools.append({
        "type": "function",
        "function": {
            "name": "emit_design_plan",
            "description": "输出最终 AgentDesignPlan",
            "strict": False,
            "parameters": AGENT_A_TOOL_SCHEMA,
        },
    })
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    used_tool = False
    tool_rounds = 0
    last_validation_issues: list[str] = []
    if trace is not None:
        trace.append({"stage": "design_start", "user": user[:800]})
    for _ in range(max_rounds):
        create_kwargs = {
            "model": model_config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "extra_body": ({"thinking": model_config.thinking} if getattr(model_config, "thinking", None) else {}),
            "temperature": model_config.temperature if model_config.temperature is not None else 0.3,
        }
        if getattr(model_config, "seed", None) is not None:
            create_kwargs["seed"] = model_config.seed
        response = client.chat.completions.create(**create_kwargs)
        _accumulate_usage(usage, response)
        message = response.choices[0].message
        if not message.tool_calls:
            retry_messages = messages + [
                {"role": "assistant", "content": message.content or ""},
                {"role": "user", "content": "You must call one of the provided tools now."},
            ]
            retry_kwargs = dict(create_kwargs)
            retry_kwargs["messages"] = retry_messages
            retry_kwargs.pop("seed", None)
            response = client.chat.completions.create(**retry_kwargs)
            message = response.choices[0].message
        if not message.tool_calls:
            raise LlmToolCallError("design tool loop returned no tool call",
                                   code="provider_no_tool_call")
        call = message.tool_calls[0]
        if call.function.name == "emit_design_plan":
            try:
                plan = _decode_tool_arguments(call.function.arguments)
            except Exception:
                messages.append({
                    "role": "user",
                    "content": "上一次工具输出不是合法 JSON。请重新调用 emit_design_plan，输出完整、合法的 JSON arguments。",
                })
                continue
            has_groove = any(
                p.get("kind") == "groove"
                for p in plan.get("profiles", [])
            )
            if tool_rounds < 2 and has_groove and not used_tool:
                messages.append({
                    "role": "user",
                    "content": "groove 参数属于 COMPLEX 计算，必须先调用 "
                               "run_python_code 或 evaluate_math 计算后再 emit_design_plan。",
                })
                continue
            last_validation_issues = _validate_agent_a_plan(
                plan, requirement_text or user)
            if last_validation_issues:
                if trace is not None:
                    trace.append({
                        "stage": "design_validation",
                        "issues": last_validation_issues[:10],
                    })
                detail = "\n".join(f"- {s}" for s in last_validation_issues[:10])
                messages.append({
                    "role": "user",
                    "content": ("Agent A 参数校验未通过，禁止原样重复，必须修正后再 "
                                "emit_design_plan：\n"
                                f"{detail}\n"
                                "以需求文本与 prompt 中的权威参数为准；如不确定可先调用 "
                                "run_python_code / evaluate_math 复核，再输出最终 plan。"),
                })
                continue
            if trace is not None:
                trace.append({"stage": "design_final", "final": plan})
            return plan
        if call.function.name not in _GENERIC_CALC_TOOLS:
            raise LlmToolCallError(f"unexpected design tool {call.function.name}",
                                   code="provider_wrong_tool_name")
        if tool_rounds >= 2:
            messages.append({
                "role": "user",
                "content": "已达到 2 次工具调用上限，禁止再调用工具；请立即 emit_design_plan。",
            })
            continue
        used_tool = True
        tool_rounds += 1
        try:
            args = _decode_tool_arguments(call.function.arguments)
        except Exception:
            messages.append({
                "role": "user",
                "content": "上一次工具参数输出不是合法 JSON。请重新调用工具，输出完整、合法的 JSON arguments。",
            })
            continue
        tool_result = _GENERIC_CALC_TOOLS[call.function.name]["handler"](args)
        if trace is not None:
            trace.append({
                "stage": "design_tool",
                "tool": call.function.name,
                "args": args,
                "result": str(tool_result)[:2000],
            })
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name,
                             "arguments": call.function.arguments},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(tool_result, ensure_ascii=False),
        })
        messages.append({
            "role": "user",
            "content": "计算完成。若还需要其他计算可继续调用工具；"
                       "一旦 ready，请立即调用 emit_design_plan 输出最终 plan。",
        })
    if last_validation_issues:
        raise LlmToolCallError(
            "design tool loop did not emit a valid plan: "
            + "; ".join(last_validation_issues[:3]),
            code="plan_validation_failed",
        )
    raise LlmToolCallError("design tool loop did not emit plan",
                           code="tool_loop_exhausted")


def _groove_index(profile_id: str):
    import re
    m = re.search(r"feat_groove_(\d+)_profile$", profile_id or "")
    return int(m.group(1)) if m else None


def _validate_agent_a_plan(plan: dict, text: str) -> list:
    """Agent A plan 后验证：需求一致性 + 轮廓间几何自洽（不依赖模板公式）。"""
    issues: list[str] = []
    import re as _re
    profiles = plan.get("profiles") or []
    req = extract_requirements(text)
    if "枞树形" not in text and any(p.get("kind") == "slot" for p in profiles):
        issues.append("需求未包含枞树形榫槽，但 plan 输出 slot profile")

    disc = next((p for p in profiles if p.get("kind") == "disc"), None)
    if disc is None:
        issues.append("缺少 disc profile")
    else:
        params = disc.get("params") or {}
        for key, req_key, tol, fn in (
            ("bore_radius_mm", "bore_diameter_mm", 0.5, lambda v: v / 2.0),
            ("rim_radius_mm", "outer_diameter_mm", 0.5, lambda v: v / 2.0),
            ("hub_half_thickness_mm", "hub_half_mm", 0.5, lambda v: v),
            ("rim_half_thickness_mm", "rim_half_mm", 0.5, lambda v: v),
        ):
            expected = req.get(req_key)
            if expected is None:
                continue
            actual = params.get(key)
            if actual is None:
                issues.append(f"disc 缺参数 {key}")
            elif abs(float(actual) - fn(float(expected))) > tol:
                issues.append(f"disc.{key}: {actual} vs 需求 {expected}")
        complex_rim_hint = _re.search(
            r"(?:轮缘与腹板交界采用.{0,12}过渡|过渡(?:幅度|半径|类型)|轮缘过渡(?:类型|幅度|半径))",
            text)
        if complex_rim_hint:
            if not params.get("rim_transition_type"):
                issues.append("需求含复杂轮缘过渡，disc 缺 rim_transition_type")
            if params.get("rim_transition_radius_mm") is None:
                issues.append("需求含复杂轮缘过渡，disc 缺 rim_transition_radius_mm")
            else:
                trans_m = _re.search(r"过渡(?:幅度|半径)([\d.]+)mm", text)
                if trans_m and abs(float(params["rim_transition_radius_mm"])
                                   - float(trans_m.group(1))) > 0.6:
                    issues.append(
                        f"disc.rim_transition_radius_mm: {params['rim_transition_radius_mm']}"
                        f" vs 需求 {trans_m.group(1)}")
    disc_params = (disc or {}).get("params") or {}
    rim_junc = disc_params.get("rim_web_junction_mm")
    rim_half = disc_params.get("rim_half_thickness_mm")
    groove_m = _re.search(
        r"(\d+)道环槽[^。；]*?槽宽([\d.]+)mm[^。；]*?槽深([\d.]+)mm", text)
    gw = float(groove_m.group(2)) if groove_m else None
    gd = float(groove_m.group(3)) if groove_m else None
    n_req = int(req.get("grooves") or 0)
    groove_profiles = [
        p for p in profiles
        if p.get("kind") == "groove" and _groove_index(p.get("profile_id")) is not None
    ]
    if n_req and len(groove_profiles) != n_req:
        issues.append(f"环槽数量 {len(groove_profiles)} != 需求 {n_req}")
    for gp in groove_profiles:
        pid = gp.get("profile_id")
        params = gp.get("params") or {}
        inner = float(params.get("inner_radius_mm") or 0)
        outer = float(params.get("outer_radius_mm") or 0)
        if rim_junc is not None and abs(inner - float(rim_junc)) > 0.6:
            issues.append(f"{pid}.inner_radius_mm 应与盘体 rim_web_junction_mm={rim_junc} 一致")
        if gd is not None and abs((outer - inner) - gd) > 0.6:
            issues.append(f"{pid} 径向跨度 != 环槽槽深 {gd}")
        if gw is not None and abs(float(params.get("depth_mm") or 0) - gw) > 0.6:
            issues.append(f"{pid}.depth_mm != 环槽槽宽 {gw}")
        if rim_half is not None:
            zb = float(params.get("z_base_mm") or 0)
            dep = float(params.get("depth_mm") or 0)
            if zb < -float(rim_half) - 0.6 or zb + dep > float(rim_half) + 0.6:
                issues.append(f"{pid} 轴向范围超出 rim 半厚")
    for p in profiles:
        if p.get("kind") != "hole":
            continue
        pid = p.get("profile_id") or "?"
        params = p.get("params") or {}
        if abs(float(params.get("center_x_mm", 0) or 0)) > 0.01 or \
                abs(float(params.get("center_y_mm", 0) or 0)) > 0.01:
            issues.append(f"{pid} center 必须为 0/0（cutter 局部原点）")

    # 未在需求中出现的特征禁止出现在 plan 中（防止幻觉特征污染几何）
    has_slot_req = "枞树形" in text
    has_holes_req = "安装孔" in text
    has_lh_req = "减重孔" in text
    has_cl_req = "冷却孔" in text
    has_groove_req = "环槽" in text
    for p in profiles:
        pid = p.get("profile_id") or ""
        kind = p.get("kind")
        if kind == "slot" and not has_slot_req:
            issues.append("需求未包含枞树形榫槽，禁止输出 slot profile")
        elif kind == "hole":
            if pid.startswith("feat_holes") and not has_holes_req:
                issues.append("需求未包含安装孔，禁止输出 feat_holes_profile")
            elif pid.startswith("feat_lh") and not has_lh_req:
                issues.append("需求未包含减重孔，禁止输出减重孔 profile")
            elif pid.startswith("feat_cl") and not has_cl_req:
                issues.append("需求未包含冷却孔，禁止输出冷却孔 profile")
        elif kind == "groove" and not has_groove_req:
            issues.append("需求未包含环槽，禁止输出 groove profile")

    # 阵列参数：count>=2；孔阵列半径必须等于需求分布半径；环槽不阵列
    skel = plan.get("gcad_skeleton") or {}
    skel_nodes = skel.get("nodes") or []
    skel_comps = {c.get("id"): c for c in (skel.get("components") or [])}
    node_comp = {n.get("id"): n.get("component") for n in skel_nodes}
    for n in skel_nodes:
        if n.get("op") != "circular_pattern_component":
            continue
        params = n.get("params") or {}
        try:
            count_i = int(params.get("count"))
        except (TypeError, ValueError):
            count_i = 0
        if count_i < 2:
            issues.append(f"{n.get('id')} circular_pattern count 必须 >= 2，实际 {params.get('count')}")
        inputs = n.get("inputs") or []
        if not inputs:
            continue
        tool_node = inputs[0].get("node")
        comp = skel_comps.get(node_comp.get(tool_node)) or {}
        cid = str(comp.get("id") or "")
        kh = str(comp.get("kind_hint") or "")
        if "groove" in cid or "groove" in kh:
            issues.append(f"{n.get('id')} 对环槽组件使用了 circular_pattern（环槽应 revolve，不阵列）")
            continue
        expected_pcd = None
        if cid == "feat_holes" or (cid.startswith("feat_holes") and "hole" in kh):
            expected_pcd = req.get("pcd_mm")
        elif cid.startswith("feat_lh"):
            expected_pcd = req.get("lh_pcd_mm")
        elif cid.startswith("feat_cl"):
            idx_m = _re.search(r"feat_cl_(\d+)", cid)
            expected_pcd = (req.get("cl_pcd_mm") if idx_m and idx_m.group(1) == "0"
                            else req.get("cl_pcd2_mm"))
        if expected_pcd is not None:
            actual = params.get("radius_mm")
            if actual is None or abs(float(actual) - float(expected_pcd)) > 0.6:
                issues.append(f"{n.get('id')} 阵列半径 {actual} 应为需求分布半径 {expected_pcd}")
    return issues


def _append_parametric_block(text: str) -> str:
    """复刻 main._append_parametric_block（避免循环 import）：注入参数化轮廓规则 + 参数映射。"""
    try:
        from param_prompts import DISC_PROFILE_RULES as _d, SLOT_PROFILE_RULES as _s
    except Exception:  # noqa: BLE001
        _d = _s = ""
    lines = [
        "",
        "### PARAMETRIC PROFILE CONSTRUCTION (STRICTLY OBEY) ###",
        _d, _s,
        "### 本次用户需求参数值（必须严格采用）###",
    ]
    req = extract_requirements(text)
    mapping = [
        ("throat_half_width_mm", "喉部半宽 → mouth_half_width（榫槽轮廓第 0 点 y，X=0 处）"),
        ("teeth_count", "齿数 → 榫槽每侧点数 = 2+4×齿数+3"),
        ("slot_depth_mm", "槽深 → 榫槽轮廓 x 范围 0 到 -槽深"),
        ("root_fillet_mm", "齿根圆角 → 覆盖 neck/root 顶点的 fillet_sketch radius_mm"),
        ("slots", "槽数 → circular_pattern_component count"),
    ]
    for k, hint in mapping:
        if req.get(k) is not None:
            lines.append(f"- {hint} = {req[k]}")
    lines.append("- 严格按上述参数构造轮廓点；fillet 的 at_vertex_index 按轮廓角色语义重算。")

    # ==== 需求显式数值：直接采用；所有直径先 ÷2 得半径 ====
    lines.append("")
    lines.append("### 用户需求显式数值（必须直接采用；所有直径先 ÷2 得半径）###")
    od = req.get("outer_diameter_mm"); bore = req.get("bore_diameter_mm")
    hub = req.get("hub_half_mm"); rim = req.get("rim_half_mm")
    if od is not None:
        lines.append(f"- 外径 {od}mm → rim_radius_mm = {od / 2}")
    if bore is not None:
        lines.append(f"- 中心孔直径 {bore}mm → bore_radius_mm = {bore / 2}")
    if hub is not None:
        lines.append(f"- 轮毂半厚 {hub}mm → hub_half_thickness_mm = {hub}")
    if rim is not None:
        lines.append(f"- 轮缘半厚 {rim}mm → rim_half_thickness_mm = {rim}")
    if req.get("hub_radial_height_mm") is not None:
        lines.append(f"- hub 径向高度 {req['hub_radial_height_mm']}mm → "
                     f"hub_radius_mm = bore_radius_mm + {req['hub_radial_height_mm']}")
    if req.get("web_radial_length_mm") is not None:
        lines.append(f"- web 径向长度 {req['web_radial_length_mm']}mm → "
                     f"rim_web_junction_mm = hub_radius_mm + {req['web_radial_length_mm']}")
    import re as _re
    groove_m = _re.search(
        r"(\d+)道环槽[^。；]*?槽宽([\d.]+)mm[^。；]*?槽深([\d.]+)mm", text)
    if groove_m:
        gw = float(groove_m.group(2)); gd = float(groove_m.group(3))
        lines.append(f"- 环槽槽宽 {gw}mm → depth_mm = {gw}（轴向宽度）")
        lines.append(f"- 环槽槽深 {gd}mm → outer_radius_mm − inner_radius_mm = {gd}（径向跨度）")
    for label, key in (("减重孔", "lh_hdia_mm"), ("冷却孔", "cl_hdia_mm"),
                       ("安装孔", "hdia_mm")):
        if req.get(key) is not None:
            lines.append(f"- {label} 孔径 {req[key]}mm → diameter_mm = {req[key]}")
    rim_m = _re.search(r"过渡(?:幅度|半径)([\d.]+)mm", text)
    if rim_m:
        lines.append(f"- 轮缘过渡幅度 {rim_m.group(1)}mm → rim_transition_radius_mm = {rim_m.group(1)}")
    for label, key in (("S形曲线", "s_curve"), ("椭圆弧", "ellipse"),
                       ("幂函数曲线", "power"), ("外凸圆弧", "arc_out"),
                       ("内凹圆弧", "arc_in")):
        if label in text:
            lines.append(f"- 轮缘过渡类型 {label} → rim_transition_type = {key}")
    lines.append("")
    lines.append("### 派生参数规则（不是答案：必须按规则自行计算，可用 evaluate_math / run_python_code）###")
    lines.append("- 盘体 hub_radius / rim_web_junction / web 半厚：按 AGENT_A_ADDENDUM 形态系数公式计算，禁止取整。")
    lines.append("- 榫槽 neck/lobe/bottom 半宽：按 EXACT FIR-TREE 算法由 neck 比例 + 齿高 + "
                 "X_neck 共线插值推导（禁止 1.1 / 2.25 / 0.875 × mouth 名义比例）；"
                 "可用 run_python_code 复核。")
    lines.append("- 环槽位置：collar 环槽贴 web-rim 交界，inner_radius_mm = rim_web_junction_mm，轴向按 AGENT_A_ADDENDUM 规则。")
    r_req = req.get("R_mm")
    if rim is not None and od is not None:
        lines.append("- 榫槽 circular_pattern_component.params.radius_mm 必须 = rim_radius_mm = "
                     f"{od / 2}（槽口贴轮缘外表面）；需求文本'分布半径'="
                     f"{r_req if r_req is not None else '无'} 仅作参考。")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 骨架通用修复（RawGcadDocument 必填默认，不随零件种类变化）
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_SAFETY = {
    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
    "not_for_manufacturing": True, "not_for_installation": True,
    "no_structural_validation": True, "no_life_prediction": True,
}
_DEFAULT_CONSTRAINTS = {
    "require_step_file": True, "require_metadata_sidecar": True,
    "require_closed_solid": True, "expected_body_count": 1,
}

# op → 所属 dialect 的确定性映射（通用，不随零件种类变）。
# Agent A 偶尔把 extrude/circular_pattern 标成 loft_sweep 等 → 按 op 强制纠正。
_OP_TO_DIALECT = {
    # sketch_profile 方言
    "create_2d_sketch": "sketch_profile", "add_polyline": "sketch_profile",
    "add_line_segment": "sketch_profile", "add_arc_segment": "sketch_profile",
    "add_circle": "sketch_profile", "add_slot": "sketch_profile",
    "close_profile": "sketch_profile", "fillet_sketch": "sketch_profile",
    "extrude_profile": "sketch_profile", "cut_profile": "sketch_profile",
    "revolve_profile": "sketch_profile",
    # composition 方言
    "circular_pattern_component": "composition", "linear_pattern_component": "composition",
    "boolean_cut": "composition", "boolean_union": "composition",
    "place_component": "composition", "translate_solid": "composition",
    "rotate_solid": "composition",
}


def _repair_skeleton(skel: dict) -> dict:
    """确定性补 RawGcadDocument 必填项 + 修正引用二义 + 按 op 纠正 dialect。

    仅补通用默认与修正结构性错误（不随零件种类变），不改变设计意图。
    若骨架仍不合法，交由下游 validation_kernel 给 issue、repair loop 修复。
    """
    skel = copy.deepcopy(skel)
    if not skel.get("document_id"):
        skel["document_id"] = f"agentic_{datetime.now().strftime('%H%M%S')}"
    if not skel.get("part_name"):
        skel["part_name"] = "reference_disc"
    if not skel.get("safety"):
        skel["safety"] = dict(_DEFAULT_SAFETY)
    if not skel.get("constraints"):
        skel["constraints"] = dict(_DEFAULT_CONSTRAINTS)
    elif isinstance(skel["constraints"], dict):
        # 只保留 RawConstraints 认的键（Agent A 偶尔加 assembly_root 等 extra，extra=forbid 会拒绝）
        allowed = set(_DEFAULT_CONSTRAINTS) | {"expected_bbox_mm"}
        skel["constraints"] = {k: v for k, v in skel["constraints"].items() if k in allowed}
        for k, v in _DEFAULT_CONSTRAINTS.items():
            skel["constraints"].setdefault(k, v)

    # 先扫描盘体轮廓，供 circular_pattern radius 缺失时兜底（槽口贴轮缘外表面）。
    disc_rim_r = None
    for n in skel.get("nodes", []):
        if not isinstance(n, dict) or n.get("op") != "add_polyline":
            continue
        comp = next((c for c in skel.get("components", [])
                     if isinstance(c, dict) and c.get("id") == n.get("component")), None)
        kind = (comp or {}).get("kind_hint") or ""
        if not any(k in kind for k in ("disc", "turbine_disc", "axisymmetric_disc")):
            continue
        xs = [p.get("x_mm", 0) for p in (n.get("params") or {}).get("points", [])
              if isinstance(p, dict)]
        if xs:
            disc_rim_r = max(xs)

    for n in skel.get("nodes", []):
        if not isinstance(n, dict):
            continue
        if n.get("op") == "add_polyline":
            params = n.setdefault("params", {})
            params.pop("closed", None)
            params.pop("plane", None)
        if n.get("op") == "revolve_profile":
            params = n.setdefault("params", {})
            if "degrees" in params:
                if "angle_deg" not in params:
                    params["angle_deg"] = params.pop("degrees")
                else:
                    params.pop("degrees", None)
            params.setdefault("angle_deg", 360.0)
            comp = next((c for c in skel.get("components", [])
                         if isinstance(c, dict) and c.get("id") == n.get("component")), None)
            kind = (comp or {}).get("kind_hint") or ""
            if any(k in kind for k in ("disc", "turbine_disc", "axisymmetric_disc")):
                params["axis"] = "Z"
        if n.get("op") == "boolean_cut":
            n.setdefault("params", {})["clean_after"] = True
        if n.get("op") == "circular_pattern_component":
            p = n.setdefault("params", {})
            if isinstance(p.get("count"), (int, float)) and int(p["count"]) >= 1:
                p["count"] = int(p["count"])
            if not isinstance(p.get("radius_mm"), (int, float)) or float(p["radius_mm"]) <= 0:
                if disc_rim_r:
                    p["radius_mm"] = float(disc_rim_r)
            else:
                p["radius_mm"] = float(p["radius_mm"])
            if p.get("axis") != "Z":
                p["axis"] = "Z"
        if n.get("op") == "fillet_sketch":
            p = n.setdefault("params", {})
            radius = p.get("radius_mm")
            if isinstance(radius, list):
                radius = next((r for r in radius if isinstance(r, (int, float)) and r > 0), 1.0)
            if not isinstance(radius, (int, float)) or radius <= 0:
                radius = 1.0
            p["radius_mm"] = float(radius)
        # 按 op 纠正 dialect（Agent A 偶尔标错为 loft_sweep 等）
        d = _OP_TO_DIALECT.get(n.get("op"))
        if d and n.get("dialect") != d:
            n["dialect"] = d
        for inp in n.get("inputs", []) or []:
            # RawValueRef 必须恰好 node 或 component 其一（boolean_cut 等 assembly 用 node ref）
            if inp.get("node") and inp.get("component"):
                inp.pop("component", None)
    # __assembly__ 组件 owner_dialect 必须为 composition
    for comp in skel.get("components", []):
        if isinstance(comp, dict) and comp.get("id") == "__assembly__":
            comp["owner_dialect"] = "composition"
    return skel


# ═══════════════════════════════════════════════════════════════════════════════
# fillet 参数化规则层：按公开轮廓结构与输入参数重建 fillet 节点。
# 这是论文“确定性规则层”的一部分，不从 golden/参考文件读取任何数值。
# ═══════════════════════════════════════════════════════════════════════════════

def _disc_fillet_specs(n_pts: int) -> list:
    """盘体 fillet 分组（半径与索引来自公开参数化规则，非 golden）。"""
    if n_pts > 12:  # 复杂轮缘：曲线过渡由轮廓点表达，仅保留 hub-web 圆角
        return [(12.0, [2]), (12.0, [n_pts - 3])]
    return [(12.0, [2]), (10.0, [3]), (10.0, [n_pts - 4]), (12.0, [n_pts - 3])]


def _disc_fillet_specs_with_features(n_pts: int, n_grooves: int, has_slot: bool) -> list:
    """带特征取舍的盘体 fillet 分组：环槽占据内壁时移除 web-rim 圆角。"""
    if n_pts > 12:
        return [(12.0, [2]), (12.0, [n_pts - 3])]
    if n_grooves >= 2:
        return [(12.0, [2]), (12.0, [9])]
    if n_grooves == 1:
        return [(12.0, [2]), (10.0, [8]), (12.0, [9])]
    if has_slot:
        return [(10.0, [2]), (10.0, [3]), (10.0, [8]), (10.0, [9])]
    return _disc_fillet_specs(n_pts)


def _slot_fillet_groups(teeth: int, mouth_half, root_fillet,
                        depth_mm: float | None = None,
                        exact_fr_mm: float | None = None) -> list:
    """榫槽 fillet 分组：半径 = 分组系数 × mouth × fr_mm（公开参数化规则）。"""
    n = int(teeth or 2)
    m = float(mouth_half or 8.0)
    fr = float(root_fillet or 0.97)
    n_upper = 2 + 4 * n + 3

    def _mirror(idxs):
        return sorted({int(i) for i in idxs}
                      | {2 * n_upper - 1 - int(i) for i in idxs})

    if exact_fr_mm is not None:
        fr_eff = float(exact_fr_mm)
    else:
        fr_eff = fr * 1.8
        limit = max(0.3, min(1.5, 0.25 * m, 0.4 * (depth_mm or 24.0) / (n + 1)))
        if limit > 0.05:
            fr_eff = min(fr_eff, limit)

    r_dome = 0.12 * m * fr_eff
    r_flank = 0.08 * m * fr_eff
    r_neck = 0.10 * m * fr_eff
    r_shoulder = 0.08 * m * fr_eff
    r_flare = 0.08 * m * fr_eff
    r_plat = 0.08 * m * fr_eff
    r_bottom_tip = 0.10 * m * fr_eff

    groups = [
        (r_dome, [2 + 4 * i for i in range(n)]),
        (r_flank, [3 + 4 * i for i in range(n)]),
        (r_neck, [1] + [4 + 4 * i for i in range(n)]
         + [5 + 4 * i for i in range(n - 1)]),
        (r_shoulder, [n_upper - 4]),
        (r_flare, [n_upper - 3]),
        (r_plat, [n_upper - 2]),
        (r_bottom_tip, [n_upper - 1]),
    ]
    return [(round(r, 3), _mirror(idxs)) for r, idxs in groups if idxs]


def _replace_component_fillets(nodes: list, cid: str, close_id: str,
                               specs: list, kind: str) -> None:
    """删除组件旧 fillet 节点并插入规则层计算的新 fillet 链。"""
    old = [n for n in nodes
           if n.get("component") == cid and n.get("op") == "fillet_sketch"]
    old_ids = {n.get("id") for n in old}
    new = []
    prev = close_id
    for i, (radius, idxs) in enumerate(specs):
        nid = f"fillet_{kind}_{i}_{close_id}"
        new.append({
            "id": nid, "component": cid, "dialect": "sketch_profile",
            "op": "fillet_sketch", "op_version": "1.0.0",
            "phase": "edge_treatment",
            "inputs": [{"node": prev, "output": "profile"}],
            "outputs": [{"name": "profile", "type": "profile"}],
            "params": {"radius_mm": radius, "at_vertex_index": list(idxs)},
            "required": True, "degradation_policy": "fail",
        })
        prev = nid
    last_id = new[-1]["id"]

    for n in nodes:
        for inp in n.get("inputs", []) or []:
            if inp.get("node") in old_ids:
                inp["node"] = last_id
            elif not old_ids and inp.get("node") == close_id \
                    and n.get("op") != "fillet_sketch":
                inp["node"] = last_id

    out: list = []
    inserted = False
    for n in nodes:
        if n.get("id") in old_ids:
            if not inserted:
                out.extend(new)
                inserted = True
            continue
        out.append(n)
        if not inserted and not old_ids and n.get("id") == close_id:
            out.extend(new)
            inserted = True
    if not inserted:
        out.extend(new)
    nodes[:] = out


def _rebuild_fillet_nodes(raw: dict, profiles: list, req: dict | None = None) -> dict:
    """按规则层重建 fillet 节点（不使用任何 golden/参考坐标）。"""
    raw = copy.deepcopy(raw)
    nodes = raw.get("nodes", [])
    for comp in raw.get("components", []):
        cid = comp.get("id")
        kind = _KIND_HINT_TO_KIND.get(comp.get("kind_hint"))
        if kind not in ("disc", "slot"):
            continue
        comp_nodes = [n for n in nodes if n.get("component") == cid]
        poly = next((n for n in comp_nodes if n.get("op") == "add_polyline"), None)
        close = next((n for n in comp_nodes if n.get("op") == "close_profile"), None)
        if poly is None or close is None:
            continue
        pts = (poly.get("params") or {}).get("points") or []
        prof = next((p for p in profiles if p.get("kind") == kind), None)
        params = (prof or {}).get("params") or {}
        if kind == "disc":
            n_grooves = sum(
                1 for c in raw.get("components", [])
                if "groove" in str(c.get("id", ""))
                or "groove" in str(c.get("kind_hint", ""))
            )
            has_slot = any(p.get("kind") == "slot" for p in profiles)
            specs = _disc_fillet_specs_with_features(len(pts), n_grooves, has_slot)
        else:
            specs = _slot_fillet_groups(
                params.get("teeth_count", 2),
                params.get("mouth_half_width_mm",
                           params.get("throat_half_width_mm", 8.0)),
                params.get("root_fillet_mm", 0.97),
                params.get("slot_depth_mm"),
                exact_fr_mm=(req or {}).get("fr_mm"),
            )
        if specs:
            _replace_component_fillets(nodes, cid, close.get("id"), specs, kind)
    return raw


def _kind_of(comp, node, profile_kinds) -> str | None:
    """确定 add_polyline 节点的轮廓 kind。kind_hint 优先。"""
    if comp and comp.get("kind_hint") in _KIND_HINT_TO_KIND:
        return _KIND_HINT_TO_KIND[comp["kind_hint"]]
    return None


def assemble(skeleton: dict, profiles: list, points_by_id: dict) -> dict:
    """骨架 + 各轮廓 points → 完整 RawGcadDocument。返回 dict（与 llm_raw 同构）。"""
    raw = copy.deepcopy(skeleton)
    kinds = [p.get("kind") for p in profiles]
    used: dict[str, int] = {}
    for node in raw.get("nodes", []):
        if node.get("op") != "add_polyline":
            continue
        comp = next((c for c in raw.get("components", [])
                     if c.get("id") == node.get("component")), None)
        kind = _kind_of(comp, node, kinds)
        if kind is None:
            # 无 kind_hint 的特征切割组件保留其模板坐标
            if comp is None or not comp.get("kind_hint"):
                continue
            for k in kinds:
                if used.get(k, 0) == 0:
                    kind = k
                    break
        if kind is None:
            continue
        used[kind] = used.get(kind, 0) + 1
        kind_profiles = [p for p in profiles if p.get("kind") == kind]
        prof = None
        if comp is not None:
            prof = next(
                (p for p in kind_profiles
                 if p.get("profile_id") == f"{comp['id']}_profile"),
                None)
        if prof is None:
            idx = used[kind] - 1
            if idx < len(kind_profiles):
                prof = kind_profiles[idx]
        if not prof:
            continue
        pts = points_by_id.get(prof.get("profile_id"))
        if isinstance(pts, list) and len(pts) >= 2:
            node["params"]["points"] = pts
    return raw


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════

def run_agentic_l2(text: str, plan, *, caller, llm_model_config, out_dir,
                   on_reasoning=None, on_status=None,
                   on_reasoning_token=None, usage: dict | None = None,
                   explicit_req: dict | None = None) -> dict:
    """Agent 系统生成 RawGcadDocument（与旧 L2 输出同构）。"""
    from pathlib import Path as _P
    out = _P(out_dir)
    trace: list[dict] = []

    # ── 1. Agent A：整体设计 → 骨架 + profiles ──
    user_a = text + _append_parametric_block(text)
    if on_status:
        try:
            on_status("Agent A · 整体设计", "design", "calling")
        except Exception:  # noqa: BLE001
            pass
    plan_out = _call_design_with_tools(
        caller, AGENT_A_SYSTEM, user_a, llm_model_config,
        trace=trace, usage=usage, requirement_text=text,
    )
    agent_reasoning: list[dict] = []
    if isinstance(plan_out, dict) and plan_out.get("reasoning"):
        agent_reasoning.append({
            "agent": "Agent A · 整体设计",
            "kind": "design",
            "reasoning": plan_out["reasoning"],
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
        if on_reasoning:
            try:
                on_reasoning("Agent A · 整体设计", "design", None, plan_out["reasoning"])
            except Exception:  # noqa: BLE001
                pass
    skeleton = _repair_skeleton(plan_out.get("gcad_skeleton") or {})
    profiles = plan_out.get("profiles") or []
    try:
        (out / "agent_a_plan.json").write_text(
            json.dumps(plan_out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    # 骨架通用修复后尽量过 RawGcadDocument（points 占位也须 schema 合法）；
    # 仍不合法不阻断 —— 下游 validation_kernel 给 issue、repair loop 修复。
    try:
        RawGcadDocument.model_validate(skeleton)
    except Exception as exc:  # noqa: BLE001
        try:
            (out / "agent_a_skeleton_warn.json").write_text(
                json.dumps({"error": str(exc)[:400]}, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ── 2. Agent B：每个轮廓一个调用 → 不变式校验 → 反馈重试 → points ──
    points_by_id: dict = {}
    profile_issues: list = []
    for prof in profiles:
        pid = prof.get("profile_id") or "p"
        kind = prof.get("kind")
        params = prof.get("params") or {}
        if kind not in ("disc", "slot"):
            # 其他轮廓类型暂不实现 → 保留占位
            continue
        if kind == "slot":
            params_txt = "\n".join(
                f"  - {k} = {v}"
                for k, v in sorted(params.items())
                if k not in ("neck_half_width_mm", "lobe_half_width_mm",
                             "bottom_half_width_mm"))
            params_txt += ("\n  - 注意：neck/lobe/bottom 半宽不直接提供，"
                           "必须按 EXACT 算法从 mouth/teeth/depth 推导"
                           "（它们是验收参考，不是坐标）。")
        else:
            params_txt = "\n".join(f"  - {k} = {v}" for k, v in sorted(params.items()))
        user_b = (f"请为轮廓 [{pid}]（kind={kind}）从下列逐行参数生成精确闭合轮廓点。\n"
                  f"{params_txt}\n"
                  f"关键要求：\n"
                  f"{_profile_user_requirements(kind)}"
                  f"{_complexity_note(kind)}\n"
                  f"需要精确坐标时，可使用通用工具 evaluate_math / run_python_code "
                  f"进行计算，然后通过 emit_profile_points 输出最终 points。"
                  f"需求相关：{text[:800]}")
        if on_status:
            try:
                on_status(f"Agent B · {kind} 轮廓", kind, f"calling {pid}")
            except Exception:  # noqa: BLE001
                pass
        prof_out = None
        pts: list = []
        for _attempt in range(3):
            try:
                cand = _call_profile_with_tools(
                    caller, _profile_system(kind), user_b, kind, llm_model_config,
                    trace=trace, params=params, usage=usage,
                )
            except Exception:  # noqa: BLE001
                continue  # 本次调用失败（如工具循环耗尽），换一次全新预算重试
            cand_pts = _normalize_profile_points(cand.get("points") or []) or []
            shape_issue = _profile_points_issue(kind, cand_pts, params)
            if not shape_issue:
                prof_out = cand
                pts = cand_pts
                break
            profile_issues.append({"profile_id": pid, "kind": kind,
                                   "reason": shape_issue})
            user_b = user_b + f"\n\n上次轮廓校验未通过：{shape_issue}。" \
                              "请重新调用工具计算并 emit 修正后的 points，禁止重复原错误。"
        if prof_out is not None:
            if isinstance(prof_out, dict) and prof_out.get("reasoning"):
                agent_reasoning.append({
                    "agent": f"Agent B · {kind} 轮廓",
                    "kind": kind,
                    "profile_id": pid,
                    "reasoning": prof_out["reasoning"],
                    "ts": datetime.now().isoformat(timespec="seconds"),
                })
                if on_reasoning:
                    try:
                        on_reasoning(f"Agent B · {kind} 轮廓", kind, pid, prof_out["reasoning"])
                    except Exception:  # noqa: BLE001
                        pass
            expected = _expected_profile_point_count(kind, params)
            if isinstance(pts, list) and (expected is None or len(pts) >= expected):
                points_by_id[pid] = pts

    # ── 2b. Feature Workers：孔/环槽轮廓（不修改 Agent B/C 逻辑）────────────
    for prof in profiles:
        pid = prof.get("profile_id") or "p"
        kind = prof.get("kind")
        params = prof.get("params") or {}
        if kind not in ("hole", "groove"):
            continue
        params_txt = "\n".join(f"  - {k} = {v}" for k, v in sorted(params.items()))
        user_b = (f"请为特征轮廓 [{pid}]（kind={kind}）从下列逐行参数生成精确闭合轮廓点。\n"
                  f"{params_txt}\n"
                  f"关键要求：\n"
                  f"{_profile_user_requirements(kind)}"
                  f"{_complexity_note(kind)}\n"
                  f"需要精确坐标时，可使用通用工具 evaluate_math / run_python_code "
                  f"进行计算，然后通过 emit_profile_points 输出最终 points。"
                  f"需求相关：{text[:800]}")
        if on_status:
            try:
                on_status(f"Feature Worker · {kind} 轮廓", kind, f"calling {pid}")
            except Exception:  # noqa: BLE001
                pass
        try:
            prof_out = _call_profile_with_tools(
                caller, _profile_system(kind), user_b, kind, llm_model_config,
                trace=trace, params=params, usage=usage,
            )
            if isinstance(prof_out, dict) and prof_out.get("reasoning"):
                agent_reasoning.append({
                    "agent": f"Feature Worker · {kind} 轮廓",
                    "kind": kind,
                    "profile_id": pid,
                    "reasoning": prof_out["reasoning"],
                    "ts": datetime.now().isoformat(timespec="seconds"),
                })
                if on_reasoning:
                    try:
                        on_reasoning(f"Feature Worker · {kind} 轮廓", kind, pid, prof_out["reasoning"])
                    except Exception:  # noqa: BLE001
                        pass
            pts = _normalize_profile_points(prof_out.get("points") or []) or []
            expected = _expected_profile_point_count(kind, params)
            shape_issue = _profile_points_issue(kind, pts, params)
            if shape_issue:
                profile_issues.append({"profile_id": pid, "kind": kind,
                                       "reason": shape_issue})
            if isinstance(pts, list) and (expected is None or len(pts) >= expected):
                points_by_id[pid] = pts
        except Exception:  # noqa: BLE001
            continue

    # ── 3. 组装 → 完整 RawGcadDocument ──
    raw = assemble(skeleton, profiles, points_by_id)
    req = extract_requirements(text)
    if explicit_req:
        req.update(explicit_req)
    raw = _rebuild_fillet_nodes(raw, profiles, req)
    if "llm_validation_hints" not in raw:
        raw["llm_validation_hints"] = {}
    raw["llm_validation_hints"]["agentic_l2"] = {
        "design_agent": True, "profiles": len(profiles),
        "filled_points": len(points_by_id),
        "profile_issues": profile_issues,
        "trace_events": len(trace),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        (out / "llm_raw.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        if agent_reasoning:
            (out / "agent_reasoning.json").write_text(
                json.dumps(agent_reasoning, ensure_ascii=False, indent=2),
                encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        if trace:
            (out / "agent_trace.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return raw
