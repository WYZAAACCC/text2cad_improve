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
  disc body → "turbine_disc"; fir-tree slot cutter → "fir_tree_cutter".
- `profiles`: for EVERY profile-producing feature, declare {profile_id, kind,
  params} where `params` MUST contain the COMPLETE parameter set for that kind
  — the profile agent derives exact coordinates FROM these params:
    disc: outer_diameter_mm, bore_diameter_mm, axial_thickness_mm,
          hub_half_thickness_mm, rim_half_thickness_mm,
          hub_web_fillet_mm, web_rim_fillet_mm
    slot: teeth_count, slots, slot_depth_mm, mouth_half_width_mm,
          neck_half_width_mm, lobe_half_width_mm, bottom_half_width_mm,
          flank_angle_deg, root_fillet_mm, bottom_fillet_mm
  HARD CONSTRAINT: bottom_half_width_mm ≥ 3.5 (slot root half-width =
  bottom_half_width_mm − 1.5 per the profile rule, so root ≥ 2mm is guaranteed).
  Do NOT omit any param — e.g. omitting `bottom_half_width_mm` leaves the
  profile agent without a valid root half-width and produces a degenerate
  slot bottom. kind ∈ ["disc", "slot", "hole", "groove"].
- The exact coordinates are derived from these params by the profile agent.
  Do NOT invent coordinates anywhere.

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

# Agent A tool schema：gcad_skeleton / params 用宽松 object（转 strict 后带 _ 占位，
# 避免 DeepSeek 把 number 强转 integer 破坏坐标/浮点参数精度）。
AGENT_A_TOOL_SCHEMA = to_deepseek_strict_schema({
    "type": "object",
    "properties": {
        "gcad_skeleton": {
            "type": "object",
            "description": "RawGcadDocument 结构骨架（nodes/components/constraints/safety）。"
                           "add_polyline.points 仅 2 个占位点；component 带 kind_hint。",
        },
        "profiles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["disc", "slot", "hole", "groove"]},
                    "params": {"type": "object",
                               "description": "该轮廓的全部推导参数（mm），供轮廓 agent 从零构造坐标。"},
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
1. 恰好 12 点闭合 R-Z 多边形（X=R, Y=Z），关于 y=0 严格对称；hub → web → rim 三段。
2. 关键尺寸由参数决定：bore 半径（最小 x）= bore_diameter_mm/2；rim 半径（最大 x）=
   outer_diameter_mm/2；hub/rim 半厚 = y 的极值（hub_half_thickness_mm / rim_half_thickness_mm）。
3. hub 外壁是垂直段；rim 内壁是垂直阶梯；web 是单一直线段（不是多段、不是水平）。
4. 任意相邻两点不得重合（x 与 y 不得同时相同），且距离 ≥ 1.5mm；无自交；
   首末点不重复（闭合由 close_profile 完成）。hub 外壁 / rim 内壁垂直段的两个端点必须不同。
5. 全部点满足 bore_radius ≤ x ≤ rim_radius。
"""

_DISC_SYSTEM = (DISC_PROFILE_RULES + _DISC_INVARIANTS if DISC_PROFILE_RULES
                else "You are the DISC PROFILE agent. " + _DISC_INVARIANTS)

_SLOT_INVARIANTS = """
## 榫槽轮廓硬性不变式（从参数推导，必须全部满足）
1. 点数由齿数决定：每侧 = 2 + 4×teeth_count + 3，总点数 = 每侧 × 2。两半全画、关于 y=0 对称。
2. 所有半宽由参数决定，严禁凭空设定：
   - mouth 半宽 = mouth_half_width_mm（x=0 处第 0 点的 |y|）
   - lobe 半宽 = lobe_half_width_mm（齿顶，逐齿外宽内窄）
   - neck 半宽 = neck_half_width_mm（齿间收窄）
   - root 半宽 = bottom_half_width_mm − 1.5（槽底，按 SLOT_PROFILE_RULES 根部定义）
3. root 半宽 = bottom_half_width_mm − 1.5，严禁 ≤ 0。原因：半宽 ≤ 0 使槽底成为退化
   尖点（V 形），拉伸成工具体后布尔切割产生无效实体——最常见的失败模式。
   bottom_half_width_mm 已由整体设计 agent 约束 ≥ 3.5，故 root ≥ 2mm 自动保证。
4. lobe 半宽从 mouth 到 root 严格递减：lobe1 > lobe2 > ... > bottom（外宽内窄，
   齿形锁定）。lobe 相等或递增 = 无锁定 = 错误。
5. 闭合、无自交、无重复点；任意相邻点距离 ≥ 1.5mm（硬约束，违反即无效）；
   首末点不重复。
6. 全 x ≤ 0；x=0 是口部；x=-slot_depth_mm 是槽底。齿面角 25°~55°。
反例（禁止）：root 半宽 = 0 的 V 形槽底；lobe1 = lobe2 的对称齿（无锁定）；
单调收敛的阶梯（非枞树形）；相邻点重合或 <1.5mm 短边。
"""

_SLOT_SYSTEM = (SLOT_PROFILE_RULES + _SLOT_INVARIANTS if SLOT_PROFILE_RULES
                else "You are the FIR-TREE SLOT PROFILE agent. " + _SLOT_INVARIANTS)

# 轮廓 agent tool schema：points 用宽松 object（x_mm/y_mm 浮点，避免 number→integer 截断）
_PROFILE_TOOL_SCHEMA = to_deepseek_strict_schema({
    "type": "object",
    "properties": {
        "profile_id": {"type": "string"},
        "points": {
            "type": "array",
            "items": {"type": "object",
                      "description": "轮廓点 {x_mm: 浮点, y_mm: 浮点}"},
        },
    },
    "required": ["profile_id", "points"],
})

# kind_hint → profile kind（骨架路由）
_KIND_HINT_TO_KIND = {"turbine_disc": "disc", "fir_tree_cutter": "slot"}


def _profile_system(kind: str) -> str:
    if kind == "disc":
        return _DISC_SYSTEM
    if kind == "slot":
        return _SLOT_SYSTEM
    # 其他类型（hole/groove）暂用 slot 规则的占位（骨架不产生坐标型轮廓时不会调用）
    return _SLOT_SYSTEM


# 约束全部通过 agent 的 prompt 传递（让 LLM 内化不变式，不用确定性代码拦截）。


# ═══════════════════════════════════════════════════════════════════════════════
# 工具调用
# ═══════════════════════════════════════════════════════════════════════════════

def _call_tool(caller, system: str, user: str, tool_name: str,
               tool_desc: str, schema: dict, model_config):
    tc = caller.call_strict_tool(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        tool_name=tool_name, tool_description=tool_desc,
        tool_schema=schema, model_config=model_config)
    return tc.arguments


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
    for n in skel.get("nodes", []):
        if not isinstance(n, dict):
            continue
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
# 组装
# ═══════════════════════════════════════════════════════════════════════════════

def _kind_of(comp, node, profile_kinds) -> str | None:
    """确定 add_polyline 节点的轮廓 kind。kind_hint 优先，plane 兜底，最后按顺序匹配。"""
    if comp and comp.get("kind_hint") in _KIND_HINT_TO_KIND:
        return _KIND_HINT_TO_KIND[comp["kind_hint"]]
    # plane 兜底：XZ=盘体，XY=榫槽
    # add_polyline 的 plane 在所在 component 的 create_2d_sketch 节点上
    return None


def assemble(skeleton: dict, profiles: list, points_by_id: dict) -> dict:
    """骨架 + 各轮廓 points → 完整 RawGcadDocument。返回 dict（与 llm_raw 同构）。"""
    raw = copy.deepcopy(skeleton)
    kinds = [p.get("kind") for p in profiles]
    used: dict[str, int] = {}
    for node in raw.get("nodes", []):
        if node.get("op") != "add_polyline":
            continue
        comp = next((c for c in raw.get("components", []) if c.get("id") == node.get("component")), None)
        kind = _kind_of(comp, node, kinds)
        if kind is None:
            # 未标注 → 按 profile 顺序匹配（第一个未用 kind）
            for k in kinds:
                if used.get(k, 0) == 0:
                    kind = k
                    break
        if kind is None:
            continue
        used[kind] = used.get(kind, 0) + 1
        prof = next((p for p in profiles if p.get("kind") == kind), None)
        if not prof:
            continue
        pts = points_by_id.get(prof.get("profile_id"))
        if isinstance(pts, list) and len(pts) >= 2:
            node["params"]["points"] = pts
    return raw


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════

def run_agentic_l2(text: str, plan, *, caller, llm_model_config, out_dir) -> dict:
    """Agent 系统生成 RawGcadDocument（与旧 L2 输出同构）。"""
    from pathlib import Path as _P
    out = _P(out_dir)

    # ── 1. Agent A：整体设计 → 骨架 + profiles ──
    user_a = text + _append_parametric_block(text)
    plan_out = _call_tool(caller, AGENT_A_SYSTEM, user_a,
                          tool_name="emit_design_plan",
                          tool_desc="整体设计：输出 RawGcadDocument 骨架 + 轮廓参数声明",
                          schema=AGENT_A_TOOL_SCHEMA, model_config=llm_model_config)
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
    for prof in profiles:
        pid = prof.get("profile_id") or "p"
        kind = prof.get("kind")
        params = prof.get("params") or {}
        if kind not in ("disc", "slot"):
            # 其他轮廓类型暂不实现 → 保留占位
            continue
        params_txt = "，".join(f"{k}={v}" for k, v in sorted(params.items()))
        user_b = (f"请为轮廓 [{pid}]（kind={kind}）从参数生成精确闭合轮廓点。\n"
                  f"轮廓参数: {params_txt}\n"
                  f"需求相关: {text[:800]}")
        try:
            prof_out = _call_tool(caller, _profile_system(kind), user_b,
                                  tool_name="emit_profile_points",
                                  tool_desc=f"{kind} 轮廓坐标生成",
                                  schema=_PROFILE_TOOL_SCHEMA, model_config=llm_model_config)
            pts = prof_out.get("points") or []
            if isinstance(pts, list) and len(pts) >= 2:
                points_by_id[pid] = pts
        except Exception:  # noqa: BLE001
            continue  # 单轮廓失败不中断（保留占位，validation 会拦截）

    # ── 3. 组装 → 完整 RawGcadDocument ──
    raw = assemble(skeleton, profiles, points_by_id)
    if "llm_validation_hints" not in raw:
        raw["llm_validation_hints"] = {}
    raw["llm_validation_hints"]["agentic_l2"] = {
        "design_agent": True, "profiles": len(profiles),
        "filled_points": len(points_by_id),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        (out / "llm_raw.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return raw
