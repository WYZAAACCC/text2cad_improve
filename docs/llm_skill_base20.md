# SeekFlow Generative CAD v6 工程实施文档（细化落地版）

## Interactive Spatial Intent + Robust Geometry Kernel + Auditable CAD Compiler

版本：v6.1 Engineering Design (Refined)
基于：`docs/llm_skill_base19.md` + 深度代码审核
目标仓库：`WYZAAACCC/seekflow-engineering`
目标链路：非 primitive Text-to-CAD（Generative CAD IR 链路）

---

# 0. 与 llm_skill_base19.md 的关键变更摘要

本细化版对原 v6 文档做了以下根本性修正与补全：

| 原文档问题 | 本版方案 |
|---|---|
| Solver 需要组件尺寸但尺寸在后续阶段才产生（致命鸡生蛋问题） | **约束延迟 + 两阶段求解**：SpatialConstraintGraph 携带符号约束，ConstraintResolver 在 leaf components 执行后、assembly 执行前求解数值 placement |
| Archetype 系统完全缺失 | 完整的 `ArchetypeRegistry` + 4 个初始 archetype + 匹配引擎 |
| spatial_contract 存放位置矛盾 | **Sidecar 模式**：`spatial_contract.json` 独立于 RawGcadDocument，通过作者管线传递 |
| 多轮交互状态管理缺失 | `SpatialSessionState` 序列化状态，支持多轮问答 |
| 与 raw_assembler AvailabilityMap 交互未定义 | `PlacedSolid` scope entry + `_build_assembly_nodes` 改造方案 |
| OCP pipe/helix 实现无算法细节 | 完整的 OCP 原生 API 调用链 + 分段 sweep + Frenet 标架 |
| 缺少 tool schema factory | 新增 `build_object_graph_tool_schema()` 等 4 个 schema factory |
| Archetype 字段注解隐晦 | 独立 `SpatialRelationType` Literal 类型 |

---

# 1. 架构总览：约束延迟两阶段求解

## 1.1 核心架构决策

v6 的根本架构问题是：**spatial solver 需要组件尺寸来计算 placement，但组件尺寸在 FeatureSequence→Runtime 阶段才产生。** 解决此问题有三种方案：

| 方案 | 描述 | 评价 |
|---|---|---|
| A: 迭代式 | guess 尺寸 → solve → 生成 → 真实尺寸 → 偏差大则重来 | 浪费 LLM 调用，不稳定 |
| B: 两阶段求解（本版采用） | Spatial frontend 输出符号约束；Runtime 中用真实 bbox 求解数值 placement | 一次通过，确定性 |
| C: 混合式 | 已知尺寸直接求解，未知尺寸延迟 | 复杂度高 |

**本版采用方案 B：约束延迟两阶段求解。**

## 1.2 完整数据流

```text
Phase A — Spatial Frontend（RoutePlan 之后、FeatureSequence 之前）
══════════════════════════════════════════════════════════════════

User Prompt
  │
  ├─→ [LLM] MechanicalObjectGraphDraft
  │     components, roles, known_dimensions, candidate_relations, unknowns
  │
  ├─→ [LLM] SpatialQuestion list（如果需要 clarification）
  │     └─→ 用户回答 → [LLM] NormalizedSpatialAnswer → 更新 object_graph
  │
  ├─→ [System] ArchetypeMatcher
  │     匹配 archetype → 注入默认 SpatialRelationDraft
  │
  ├─→ [System] ConstraintGraphBuilder
  │     relation drafts → SpatialConstraintGraph（符号约束）
  │     约束含符号维度引用，如 "$component.top_plate.extent_z"
  │
  ├─→ [System] SpatialValidator（Phase A，仅检查约束一致性）
  │     V001-V009，使用已知尺寸和符号引用
  │
  └─→ SpatialFrontendResult
        object_graph, constraint_graph, assumption_ledger,
        needs_clarification, session_state


Phase B — Staged Authoring（现有管线 + 空间上下文注入）
══════════════════════════════════════════════════════════════════

RoutePlan（沿用现有）
  │
FeatureSequenceDraft（注入 SPATIAL CONTRACT）
  │  place_component 节点使用 PLACEHOLDER 坐标
  │  placement_source = "solver_derived"
  │
NodeParamsDraft（注入 SOLVED PLACEMENT CONTEXT）
  │
RawGcadDocument assembly（raw_assembler 不做 placement 坐标填充）
  │
Validation + Canonicalize（沿用现有，含新增 C011-C015 规则）
  │
AutoFix（沿用现有 + 新增空间分类）


Phase C — Runtime with Constraint Resolution（改造 run_canonical_gcad）
══════════════════════════════════════════════════════════════════

_run_components(canonical, ctx)
  │  执行所有 leaf components
  │  每个 component 构建完成后测量 bbox，记录到 ctx
  │
  │  ╔══════════════════════════════════════════════════════╗
  ═══╣  NEW: ConstraintResolver                              ║
  │  ║  读取 SpatialConstraintGraph（符号约束）               ║
  │  ║  读取 MeasuredComponentBBoxes（实际尺寸）              ║
  │  ║  求解数值 PlacementTransform                          ║
  │  ║  更新 ctx 中的 placement 坐标                         ║
  │  ╚══════════════════════════════════════════════════════╝
  │
_run_composition_or_select_final(canonical, ctx)
  │  执行 assembly composition
  │  place_component handler 从 ctx 读取求解后的坐标
  │  boolean_union 消费 placed solids
  │
GeometrySpatialAudit
  │  测量最终装配体 bbox
  │  验证 spatial constraints 是否满足
  │
_export_final_solid(ctx)
```

## 1.3 关键不变原则

```text
1. LLM 不做 CAD compiler —— 不输出最终坐标
2. LLM 不做 spatial solver —— 只抽取关系与未知
3. validation 永远不修复数据
4. fail-closed：任何未解决的约束导致装配失败
5. 不破坏 primitive 与 generative CAD 链路隔离
6. 不引入 part-specific operation
7. 单零件 case（无 composition dialect）spatial frontend 自动跳过
8. AUTO = 采用 archetype 默认 + 记录假设 + 验证 + 失败则问
```

---

# 2. 新目录结构

基于原文档 §2，补充了 archetypes、constraint_resolver、spatial_audit 的完整文件列表：

```text
seekflow_engineering_tools/generative_cad/

  authoring/
    spatial/                          # NEW — 空间意图前端
      __init__.py
      schemas.py                      # 所有 Pydantic 模型
      prompts.py                      # 4 个空间 LLM prompt
      tool_schemas.py                 # 4 个 DeepSeek strict schema factory
      pipeline.py                     # SpatialFrontend 入口
      object_graph.py                 # MechanicalObjectGraphDraft 构建
      ambiguity.py                    # SpatialUnknown 优先级计算
      question_planner.py             # 问题生成与预算管理
      answer_normalizer.py            # 用户回答归一化
      constraint_graph.py             # SpatialConstraintGraph 构建器
      solver.py                       # Phase A 符号约束求解
      validators.py                   # Phase A 约束一致性检查
      archetypes/
        __init__.py
        registry.py                   # ArchetypeRegistry
        pillar_support.py             # 立柱支撑 archetype
        axial_coupling.py             # 轴向联轴器 archetype
        bearing_on_base.py            # 轴承座 archetype
        flanged_connection.py         # 法兰连接 archetype
      assumption_ledger.py            # 假设账本
      reports.py                      # SpatialSolverReport, SpatialValidationReport
      integration.py                  # placement 注入 FeatureSequence
      session_state.py                # 多轮交互状态序列化

  runtime/
    constraint_resolver.py            # NEW — Phase C 数值求解器
    bbox_tracker.py                   # NEW — Component bbox 测量与记录
    spatial_audit.py                  # NEW — 装配体空间审计
    geometry_measure.py               # NEW — 通用几何测量工具
    contact_measure.py                # NEW — 接触面距离测量

  dialects/
    geometry_utils/
      __init__.py
      ocp_wire.py                     # 3D wire 构建（polyline + spline）
      ocp_pipe.py                     # 管道 sweep（含 Frenet 标架）
      boolean_safe.py                 # 安全布尔操作 + fillet/chamfer
      bbox.py                         # BBox 工具
      measurements.py                 # 几何测量（volume, area, distance）

  validation/
    spatial_contract.py               # NEW — spatial_contract sidecar 验证

  tests/
    generative_cad/
      authoring/spatial/
        test_schemas.py
        test_object_graph.py
        test_question_planner.py
        test_solver.py
        test_validators.py
        test_archetype_registry.py
        test_assumption_ledger.py
        test_integration.py
        test_session_state.py
      runtime/
        test_constraint_resolver.py
        test_spatial_audit.py
        test_bbox_tracker.py
      dialects/geometry_utils/
        test_ocp_wire.py
        test_ocp_pipe.py
        test_boolean_safe.py
      test_spatial_integration_workbench.py
      test_spatial_integration_coupling.py
```

---

# 3. 数据模型（完整可落地代码）

## 3.1 文件：`authoring/spatial/schemas.py`

所有模型 `extra="forbid"`，Pydantic v2。

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════════════
# 独立类型别名（避免 model_fields 隐式引用）
# ═══════════════════════════════════════════════════════════════════════════════

SpatialModeType = Literal[
    "guided", "auto_conservative", "auto_mechanical",
    "auto_complex_verified", "precision",
]

AxisNameType = Literal["X", "Y", "Z"]

SourceKindType = Literal[
    "user_explicit", "user_selected_option", "llm_inferred",
    "archetype_default", "system_default", "solver_derived",
]

SpatialRelationType = Literal[
    "above", "below", "left_of", "right_of", "front_of", "behind",
    "between", "coaxial", "concentric", "parallel", "perpendicular",
    "symmetric_pair", "face_contact", "flush", "offset", "clearance",
    "centered_on", "inside", "surrounds", "supports", "attached_to",
]

UnknownKindType = Literal[
    "component_count", "relative_placement", "axis_direction",
    "face_selection", "contact_relation", "spacing", "symmetry",
    "assembly_vs_fused", "feature_location", "port_direction",
]

OriginSemanticsType = Literal[
    "center", "center_bottom", "center_top", "axis_front",
    "axis_midpoint", "mounting_face_center", "unknown",
]

ClarificationMode = Literal["option", "custom", "auto"]

AutoLevelType = Literal[
    "auto_conservative", "auto_mechanical", "auto_complex_verified",
]

ValidationStatusType = Literal["not_checked", "pass", "fail", "warning"]

# Solver 输出状态
SpatialFinalStatus = Literal["VERIFIED", "ASSUMPTION_BASED", "NEEDS_CLARIFICATION"]


# ═══════════════════════════════════════════════════════════════════════════════
# 置信度
# ═══════════════════════════════════════════════════════════════════════════════

class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0.0, le=1.0, description="0.0=纯猜测, 1.0=用户显式确认")
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# 已知尺寸（结构化，替换原文档的自由 dict）
# ═══════════════════════════════════════════════════════════════════════════════

class KnownDimension(BaseModel):
    """用户显式给出的单个尺寸。"""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="如 'outer_diameter', 'height', 'length', 'width', 'thickness'")
    value_mm: float = Field(gt=0)
    axis: AxisNameType | None = Field(
        default=None,
        description="此尺寸对应的主轴方向（Z=轴向高度, X/Y=横向尺寸）"
    )
    is_exact: bool = Field(
        default=True,
        description="True=用户明确指定, False=近似值（如'大约100mm'）"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ComponentRole：LLM 提取的组件语义
# ═══════════════════════════════════════════════════════════════════════════════

class ComponentRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(description="与后续 FeatureSequence 中的 component_id 对应")
    display_name: str = ""
    role: str = Field(description="机械角色：'top_plate', 'pillar', 'hub', 'spider', 'base' 等")
    kind_hint: str = Field(default="", description="几何类型提示：'plate', 'cylinder', 'ring', 'spring'")
    primary_dialect_hint: str | None = Field(
        default=None,
        description="预期的方言：'axisymmetric', 'sketch_extrude', 'loft_sweep' 等"
    )
    known_dimensions: list[KnownDimension] = Field(default_factory=list)
    source_text: str = Field(default="", description="用户 prompt 中描述此组件的原始文本")
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))


# ═══════════════════════════════════════════════════════════════════════════════
# LocalFrameDraft：组件本地坐标系假设
# ═══════════════════════════════════════════════════════════════════════════════

class LocalFrameDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    origin_semantics: OriginSemanticsType = "unknown"
    x_axis_semantics: str = Field(default="global_X", description="X轴方向语义")
    y_axis_semantics: str = Field(default="global_Y")
    z_axis_semantics: str = Field(default="global_Z")
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialRelationDraft：LLM 推断的空间关系（不精确，待求解）
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialRelationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_id: str
    type: SpatialRelationType
    entities: list[str] = Field(description="涉及的 component_id 列表")
    value_mm: float | None = Field(default=None, description="offset/clearance 值（如有）")
    direction: str | None = Field(default=None, description="方向：'+Z', '-X' 等")
    source: SourceKindType = "llm_inferred"
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))
    rationale: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialUnknown：LLM 识别的不确定性
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialUnknown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unknown_id: str
    kind: UnknownKindType
    entities: list[str]
    question_hint: str = Field(description="可问用户的问题草稿")
    impact: float = Field(ge=0.0, le=1.0, description="错误时对 CAD 模型的影响程度")
    uncertainty: float = Field(ge=0.0, le=1.0, description="LLM 对此判断的不确定程度")
    answer_cost: float = Field(ge=0.0, le=1.0, description="用户回答的难度")
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# MechanicalObjectGraphDraft：Level-1 空间 IR（LLM 输出）
# ═══════════════════════════════════════════════════════════════════════════════

class MechanicalObjectGraphDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: SpatialModeType = "guided"
    global_frame_assumption: str = "X=left-right, Y=front-back, Z=bottom-top, units=mm"
    components: list[ComponentRole] = Field(default_factory=list, min_length=1)
    local_frames: list[LocalFrameDraft] = Field(default_factory=list)
    candidate_relations: list[SpatialRelationDraft] = Field(default_factory=list)
    unknowns: list[SpatialUnknown] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_invariants(self):
        # component_id 唯一性
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component_id values must be unique")
        # local_frames 必须引用已存在的 component_id
        frame_ids = {f.component_id for f in self.local_frames}
        unknown_frames = frame_ids - set(ids)
        if unknown_frames:
            raise ValueError(f"local_frames reference unknown component_ids: {unknown_frames}")
        # relations 中的 entities 必须引用已存在的 component_id
        for rel in self.candidate_relations:
            unknown_entities = set(rel.entities) - set(ids)
            if unknown_entities:
                raise ValueError(
                    f"relation {rel.relation_id} references unknown entities: {unknown_entities}"
                )
        # unknowns 同理
        for unk in self.unknowns:
            unknown_entities = set(unk.entities) - set(ids)
            if unknown_entities:
                raise ValueError(
                    f"unknown {unk.unknown_id} references unknown entities: {unknown_entities}"
                )
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# SymbolicDimensionRef：符号维度引用（Solver 的核心抽象）
# ═══════════════════════════════════════════════════════════════════════════════

class SymbolicDimensionRef(BaseModel):
    """引用组件在某个轴上的 extent。

    例如 SymbolicDimensionRef(component_id="top_plate", axis="Z")
    表示 top_plate 的 Z 向高度（bbox.zlen）。

    这是约束延迟求解的核心机制——solver 不计算绝对坐标，
    而是建立符号方程，在 Runtime 中代入实际 bbox 值求解。
    """
    model_config = ConfigDict(extra="forbid")
    component_id: str
    axis: AxisNameType
    # offset 用于表达 "A 的 zmax" vs "A 的 zmin"
    edge: Literal["min", "max", "extent"] = "extent"


# ═══════════════════════════════════════════════════════════════════════════════
# PlacementConstraint：符号约束（替代原文档的绝对 PlacementTransform）
# ═══════════════════════════════════════════════════════════════════════════════

class PlacementConstraint(BaseModel):
    """单个符号约束方程。

    约束类型：
    - "stack": A.zmax + offset = B.zmin（Z轴堆叠）
    - "align_axis": A.{axis} = B.{axis}（同轴对齐）
    - "symmetric": A.x = -d/2, B.x = +d/2（对称布局）
    - "contact": distance(A.face, B.face) <= tolerance
    """
    model_config = ConfigDict(extra="forbid")
    constraint_id: str
    type: Literal["stack", "align_axis", "symmetric", "contact", "identity"]
    entities: list[str] = Field(min_length=1)
    # 符号维度绑定
    bindings: dict[str, SymbolicDimensionRef] = Field(
        default_factory=dict,
        description="key=占位符名, value=符号维度引用"
    )
    # 数值参数（已知的）
    offset_mm: float = 0.0
    spacing_mm: float | None = None  # symmetric_pair 的间距
    axis: AxisNameType | None = None
    tolerance_mm: float = 0.5
    source: SourceKindType = "solver_derived"
    required: bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialConstraintGraph：符号约束图（Phase A 输出）
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialConstraintGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    components: list[ComponentRole]
    local_frames: list[LocalFrameDraft]
    constraints: list[PlacementConstraint] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    # NOTE: 改名为 solved_assembly_bbox_mm（区别于 RawConstraints.expected_bbox_mm）
    solved_assembly_bbox_mm: tuple[float, float, float] | None = Field(
        default=None,
        description="solver 根据已知尺寸推导的装配体 bbox（仅作参考）"
    )
    expected_body_count: int | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# NumericPlacement：数值放置（Phase C 输出，供 composition handler 使用）
# ═══════════════════════════════════════════════════════════════════════════════

class NumericPlacement(BaseModel):
    """ConstraintResolver 求解后的数值放置。"""
    model_config = ConfigDict(extra="forbid")
    component_id: str
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    source: SourceKindType = "solver_derived"
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=1.0))
    assumptions: list[str] = Field(default_factory=list)
    # 如果 solver 无法确定，标记为待定
    is_pending: bool = False
    pending_reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# 问答系统
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str
    label: str
    description: str = ""
    recommended: bool = False
    geometric_consequence: str = Field(
        default="",
        description="选择此选项后的空间布局后果（展示给用户）"
    )
    auto_policy: str | None = None
    constraints_to_add: list[SpatialRelationDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpatialQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    unknown_id: str
    type: str
    entities: list[str]
    question_text: str
    why_it_matters: str
    impact: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    answer_cost: float = Field(ge=0.0, le=1.0)
    priority: float = Field(ge=0.0, le=1.0)
    options: list[SpatialQuestionOption] = Field(default_factory=list)
    allow_custom: bool = True
    allow_auto: bool = True


class UserSpatialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    mode: ClarificationMode
    selected_option_id: str | None = None
    custom_text: str | None = None
    auto_level: AutoLevelType | None = None


class NormalizedSpatialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    source_answer: UserSpatialAnswer
    relations_added: list[SpatialRelationDraft] = Field(default_factory=list)
    assumptions_added: list[str] = Field(default_factory=list)
    requires_replanning: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# AssumptionLedger
# ═══════════════════════════════════════════════════════════════════════════════

class AssumptionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumption_id: str
    statement: str
    source: SourceKindType
    confidence: float = Field(ge=0.0, le=1.0)
    user_delegated: bool = False
    user_confirmed: bool = False
    validation_status: ValidationStatusType = "not_checked"
    evidence: list[str] = Field(default_factory=list)


class AssumptionLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[AssumptionEntry] = Field(default_factory=list)

    def add(self, entry: AssumptionEntry) -> None:
        self.entries.append(entry)

    def high_risk_unconfirmed(self) -> list[AssumptionEntry]:
        """高风险的未确认假设（confidence < 阈值 且 未通过验证 且 用户未确认）"""
        return [
            e for e in self.entries
            if e.confidence < 0.65
            and not e.user_confirmed
            and e.validation_status != "pass"
        ]

    def all_by_source(self, source: SourceKindType) -> list[AssumptionEntry]:
        return [e for e in self.entries if e.source == source]


# ═══════════════════════════════════════════════════════════════════════════════
# 多轮交互状态
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialSessionState(BaseModel):
    """可序列化的多轮交互状态。

    当 needs_clarification=True 时，此状态随 SpatialFrontendResult 返回。
    上层在下一轮调用时原样传入 run_spatial_authoring_frontend()。
    """
    model_config = ConfigDict(extra="forbid")
    session_id: str
    object_graph_json: str = Field(description="MechanicalObjectGraphDraft.model_dump_json()")
    constraint_graph_json: str | None = Field(default=None)
    ledger_json: str = Field(description="AssumptionLedger.model_dump_json()")
    answered_question_ids: list[str] = Field(default_factory=list)
    round_number: int = 1
    max_rounds: int = 3


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialSolver / SpatialValidator 报告
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialSolverIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["warning", "error"]
    code: str
    message: str
    entities: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)


class SpatialSolverReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    constraints_total: int = 0
    constraints_solved: int = 0
    constraints_unsolved: int = 0
    pending_placements: list[str] = Field(default_factory=list)
    issues: list[SpatialSolverIssue] = Field(default_factory=list)


class SpatialValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["warning", "error"]
    code: str
    message: str
    entities: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)


class SpatialValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    issues: list[SpatialValidationIssue] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# SpatialFrontendResult：Phase A 最终输出
# ═══════════════════════════════════════════════════════════════════════════════

class SpatialFrontendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    needs_clarification: bool = False
    final_status: SpatialFinalStatus = "ASSUMPTION_BASED"
    questions: list[SpatialQuestion] = Field(default_factory=list)
    object_graph: MechanicalObjectGraphDraft | None = None
    constraint_graph: SpatialConstraintGraph | None = None
    solver_report: SpatialSolverReport | None = None
    validation_report: SpatialValidationReport | None = None
    assumption_ledger: AssumptionLedger = Field(default_factory=AssumptionLedger)
    session_state: SpatialSessionState | None = Field(
        default=None,
        description="非 None 时需要上层保存并在下一轮传入"
    )
    failures: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# GeometrySpatialAudit 模型（Phase C）
# ═══════════════════════════════════════════════════════════════════════════════

class ComponentBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    xmin: float; xmax: float
    ymin: float; ymax: float
    zmin: float; zmax: float

    @property
    def xlen(self) -> float: return self.xmax - self.xmin
    @property
    def ylen(self) -> float: return self.ymax - self.ymin
    @property
    def zlen(self) -> float: return self.zmax - self.zmin
    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.xmin + self.xmax) / 2,
            (self.ymin + self.ymax) / 2,
            (self.zmin + self.zmax) / 2,
        )


class PairwiseSpatialMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str; b: str
    overlap_volume_mm3: float = 0.0
    overlap_ratio_min: float = Field(
        ge=0.0, le=1.0,
        description="min(overlap_volume/A_volume, overlap_volume/B_volume)"
    )
    bbox_distance_mm: float = 0.0
    contacts: bool = False


class GeometrySpatialAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    component_bboxes: list[ComponentBBox] = Field(default_factory=list)
    pairwise_metrics: list[PairwiseSpatialMetric] = Field(default_factory=list)
    issues: list[SpatialValidationIssue] = Field(default_factory=list)
    assembly_bbox_mm: tuple[float, float, float] | None = None
    solid_count: int | None = None
    connectivity_graph_connected: bool | None = None
```

## 3.2 关键设计决策说明

### 3.2.1 `SymbolicDimensionRef`：约束延迟的核心

这是对原文档最关键的修正。原文档的 `PlacementTransform` 包含数值坐标（`translation_mm: tuple[float,float,float]`），但 solver 在 Phase A 运行时组件尺寸未知。本方案引入符号维度引用：

```python
# Phase A：solver 不输出数值坐标，输出符号约束
PlacementConstraint(
    constraint_id="stack_pillar_on_bottom",
    type="stack",
    entities=["pillar_left", "bottom_plate"],
    bindings={
        "pillar_zmin": SymbolicDimensionRef(component_id="bottom_plate", axis="Z", edge="max"),
        "pillar_zmax": SymbolicDimensionRef(component_id="pillar_left", axis="Z", edge="extent"),
    },
    offset_mm=0.0,
)

# Phase C：ConstraintResolver 代入实际 bbox 求解
# bottom_plate.bbox.zmax = 20.0
# pillar_left.bbox.zlen = 200.0
# → pillar_left.translation_mm = (0, 0, 20.0)
```

### 3.2.2 为什么 `ComponentRole.known_dimensions` 用结构化列表而非 dict

原文档用 `dict[str, float]`，但 key 的语义不明确（是 `"height"` 还是 `"z_extent"`？）。结构化 `KnownDimension` 携带 axis 信息，solver 可以直接使用。

### 3.2.3 `SpatialSessionState` 的设计

多轮交互需要保持状态。这个模型序列化所有 LLM 输出，第二轮调用时恢复，避免重复 LLM 调用：

```python
# 第一轮
result = run_spatial_authoring_frontend(user_request=prompt, ...)
# result.needs_clarification == True
# result.session_state -> 序列化保存

# 第二轮
answers = [UserSpatialAnswer(question_id="q_001", mode="option", selected_option_id="A")]
result = run_spatial_authoring_frontend(
    user_request=prompt,
    user_answers=answers,
    session_state=round1_state,  # 恢复状态
    ...
)
```

---

# 4. Archetype 系统

## 4.1 文件：`authoring/spatial/archetypes/registry.py`

```python
"""ArchetypeRegistry — 已知机械布局模板匹配引擎。

Archetype 不生成零件几何，只提供默认空间关系。
匹配到 archetype 后，注入 SpatialRelationDraft（SourceKind=ARCHETYPE_DEFAULT）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    ComponentRole,
    MechanicalObjectGraphDraft,
    SpatialRelationDraft,
)


@dataclass(frozen=True)
class ArchetypeSpec:
    """单个 archetype 定义。"""
    archetype_id: str
    description: str
    # 匹配条件：接收 object_graph，返回是否匹配
    matcher: Callable[[MechanicalObjectGraphDraft], bool]
    # 默认空间关系生成器
    relations: Callable[[MechanicalObjectGraphDraft], list[SpatialRelationDraft]]
    # 此 archetype 适用的 AUTO 模式
    applicable_modes: tuple[str, ...] = ("auto_mechanical", "auto_complex_verified")


class ArchetypeRegistry:
    """Archetype 注册表。"""

    def __init__(self):
        self._archetypes: dict[str, ArchetypeSpec] = {}

    def register(self, spec: ArchetypeSpec) -> None:
        if spec.archetype_id in self._archetypes:
            raise ValueError(f"duplicate archetype: {spec.archetype_id}")
        self._archetypes[spec.archetype_id] = spec

    def match(self, graph: MechanicalObjectGraphDraft) -> list[ArchetypeSpec]:
        """返回所有匹配的 archetype。"""
        return [a for a in self._archetypes.values() if a.matcher(graph)]

    def list_ids(self) -> list[str]:
        return sorted(self._archetypes.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# 默认注册表（4 个初始 archetype）
# ═══════════════════════════════════════════════════════════════════════════════

def _build_default_archetypes() -> ArchetypeRegistry:
    from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes import (
        pillar_support,
        axial_coupling,
        bearing_on_base,
        flanged_connection,
    )
    reg = ArchetypeRegistry()
    for spec in [
        pillar_support.SPEC,
        axial_coupling.SPEC,
        bearing_on_base.SPEC,
        flanged_connection.SPEC,
    ]:
        reg.register(spec)
    return reg


_default_archetypes = None

def default_archetypes() -> ArchetypeRegistry:
    global _default_archetypes
    if _default_archetypes is None:
        _default_archetypes = _build_default_archetypes()
    return _default_archetypes
```

## 4.2 初始 Archetype 定义

### `pillar_support.py`

```python
"""立柱支撑 archetype：上下板 + 对称支柱。"""

from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import ArchetypeSpec
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft, SpatialRelationDraft, Confidence,
)

SPEC = ArchetypeSpec(
    archetype_id="pillar_support",
    description="上下板 + 对称立柱支撑结构（如工作台、支架）",
    matcher=lambda g: (
        len(g.components) >= 3
        and any("plate" in c.role.lower() or "plate" in c.component_id.lower() for c in g.components)
        and any("pillar" in c.role.lower() or "pillar" in c.component_id.lower() or
                "column" in c.role.lower() or "column" in c.component_id.lower()
                for c in g.components)
    ),
    relations=lambda g: _pillar_support_relations(g),
)


def _pillar_support_relations(g: MechanicalObjectGraphDraft) -> list[SpatialRelationDraft]:
    plates = [c for c in g.components if "plate" in c.role.lower() or "plate" in c.component_id.lower()]
    pillars = [c for c in g.components if "pillar" in c.role.lower() or "pillar" in c.component_id.lower()
               or "column" in c.role.lower() or "column" in c.component_id.lower()]

    relations: list[SpatialRelationDraft] = []
    rid = 0

    # 上板在立柱上方，下板在立柱下方
    if len(plates) >= 2 and len(pillars) >= 1:
        top_plate = next((p for p in plates if "top" in p.component_id.lower() or "top" in p.role.lower()), plates[0])
        bottom_plate = next((p for p in plates if "bottom" in p.component_id.lower() or "bottom" in p.role.lower()), plates[-1])
        pillar_ref = pillars[0]

        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_pillar_support_{rid}",
            type="above",
            entities=[top_plate.component_id, pillar_ref.component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.75, reason="pillar_support archetype: top plate above pillars"),
        ))
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_pillar_support_{rid}",
            type="above",
            entities=[pillar_ref.component_id, bottom_plate.component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.75, reason="pillar_support archetype: pillars above bottom plate"),
        ))

    # 对称立柱
    if len(pillars) == 2:
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_pillar_support_{rid}",
            type="symmetric_pair",
            entities=[pillars[0].component_id, pillars[1].component_id],
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="pillar_support archetype: two pillars are symmetric"),
        ))
    elif len(pillars) == 4:
        # 四角支撑：两组对称对
        for pair in [(0, 1), (2, 3)]:
            if pair[1] < len(pillars):
                rid += 1
                relations.append(SpatialRelationDraft(
                    relation_id=f"archetype_pillar_support_{rid}",
                    type="symmetric_pair",
                    entities=[pillars[pair[0]].component_id, pillars[pair[1]].component_id],
                    source="archetype_default",
                    confidence=Confidence(value=0.70, reason="pillar_support archetype: corner pillar symmetry"),
                ))

    for rel in relations:
        g.assumptions.append(f"[archetype:pillar_support] {rel.rationale}")

    return relations
```

### `axial_coupling.py`

```python
"""轴向联轴器 archetype：同轴串联的 hub-spider-hub 结构。"""

from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import ArchetypeSpec
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft, SpatialRelationDraft, Confidence,
)

SPEC = ArchetypeSpec(
    archetype_id="axial_coupling",
    description="轴向联轴器：hub-spider-hub 串联或同心结构",
    matcher=lambda g: (
        len(g.components) >= 3
        and any("hub" in c.role.lower() or "hub" in c.component_id.lower() for c in g.components)
        and any("spider" in c.role.lower() or "spider" in c.component_id.lower() for c in g.components)
    ),
    relations=lambda g: _axial_coupling_relations(g),
)


def _axial_coupling_relations(g: MechanicalObjectGraphDraft) -> list[SpatialRelationDraft]:
    hubs = [c for c in g.components if "hub" in c.role.lower() or "hub" in c.component_id.lower()]
    spiders = [c for c in g.components if "spider" in c.role.lower() or "spider" in c.component_id.lower()]

    relations: list[SpatialRelationDraft] = []
    rid = 0

    # 同轴约束
    all_axial = hubs + spiders
    if len(all_axial) >= 2:
        for i in range(len(all_axial) - 1):
            rid += 1
            relations.append(SpatialRelationDraft(
                relation_id=f"archetype_axial_{rid}",
                type="coaxial",
                entities=[all_axial[i].component_id, all_axial[i+1].component_id],
                source="archetype_default",
                confidence=Confidence(value=0.80, reason="axial_coupling archetype: coaxial alignment"),
            ))

    # 串联 face_contact（按 hub_a → spider → hub_b 顺序）
    if len(hubs) == 2 and len(spiders) == 1:
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_axial_{rid}",
            type="face_contact",
            entities=[hubs[0].component_id, spiders[0].component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="axial_coupling archetype: hub_a contacts spider"),
        ))
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_axial_{rid}",
            type="face_contact",
            entities=[spiders[0].component_id, hubs[1].component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="axial_coupling archetype: spider contacts hub_b"),
        ))

    for rel in relations:
        g.assumptions.append(f"[archetype:axial_coupling] {rel.rationale}")

    return relations
```

### `bearing_on_base.py` 和 `flanged_connection.py`

按同模式实现，此处省略完整代码。核心逻辑：
- `bearing_on_base`：检测 "bearing" + "base" 组件 → 创建 face_contact + above 关系
- `flanged_connection`：检测 "flange" 组件 → 创建 face_contact + coaxial 关系

---

# 5. ConstraintGraphBuilder + Phase A Solver

## 5.1 文件：`authoring/spatial/constraint_graph.py`

将 `MechanicalObjectGraphDraft.candidate_relations` + archetype 注入的关系转换为 `SpatialConstraintGraph`（符号约束）。

```python
"""ConstraintGraphBuilder — relation drafts → SpatialConstraintGraph（符号约束）。"""

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialConstraintGraph,
    SpatialRelationDraft,
    PlacementConstraint,
    SymbolicDimensionRef,
    ComponentRole,
)


def build_constraint_graph(
    object_graph: MechanicalObjectGraphDraft,
) -> SpatialConstraintGraph:
    """将 candidate_relations 转换为符号约束图。

    规则：
    - "above" + direction="+Z" → stack 约束：lower.zmax + 0 = upper.zmin
    - "coaxial" → align_axis 约束：横向坐标对齐
    - "symmetric_pair" → symmetric 约束：X 轴对称
    - "face_contact" + direction="+Z" → stack 约束：offset=0
    - "attached_to" → contact 约束
    """
    constraints: list[PlacementConstraint] = []
    component_map = {c.component_id: c for c in object_graph.components}

    for rel in object_graph.candidate_relations:
        pc = _convert_relation(rel, component_map)
        if pc is not None:
            constraints.append(pc)

    return SpatialConstraintGraph(
        components=object_graph.components,
        local_frames=object_graph.local_frames,
        constraints=constraints,
        assumptions=list(object_graph.assumptions),
    )


def _convert_relation(
    rel: SpatialRelationDraft,
    component_map: dict[str, ComponentRole],
) -> PlacementConstraint | None:
    """单条关系草案 → 符号约束。"""

    if len(rel.entities) < 2:
        return None

    a, b = rel.entities[0], rel.entities[1]

    if rel.type == "above":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="stack",
            entities=[b, a],  # lower, upper
            bindings={
                "lower_zmax": SymbolicDimensionRef(component_id=b, axis="Z", edge="max"),
                "upper_zmin": SymbolicDimensionRef(component_id=a, axis="Z", edge="min"),
            },
            offset_mm=rel.value_mm or 0.0,
            axis="Z",
            source=rel.source,
        )

    elif rel.type == "below":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="stack",
            entities=[a, b],
            bindings={
                "lower_zmax": SymbolicDimensionRef(component_id=a, axis="Z", edge="max"),
                "upper_zmin": SymbolicDimensionRef(component_id=b, axis="Z", edge="min"),
            },
            offset_mm=rel.value_mm or 0.0,
            axis="Z",
            source=rel.source,
        )

    elif rel.type == "coaxial":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="align_axis",
            entities=[a, b],
            axis="Z" if rel.direction is None else _direction_to_axis(rel.direction),
            source=rel.source,
        )

    elif rel.type == "symmetric_pair":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="symmetric",
            entities=[a, b],
            spacing_mm=rel.value_mm,
            source=rel.source,
        )

    elif rel.type == "face_contact":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="stack",
            entities=[a, b],
            bindings={
                "a_face": SymbolicDimensionRef(component_id=a, axis="Z", edge="max"),
                "b_face": SymbolicDimensionRef(component_id=b, axis="Z", edge="min"),
            },
            offset_mm=0.0,
            axis="Z",
            source=rel.source,
        )

    elif rel.type == "supports":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="stack",
            entities=[a, b],
            bindings={
                "support_zmax": SymbolicDimensionRef(component_id=a, axis="Z", edge="max"),
                "supported_zmin": SymbolicDimensionRef(component_id=b, axis="Z", edge="min"),
            },
            offset_mm=0.0,
            axis="Z",
            source=rel.source,
        )

    elif rel.type == "attached_to":
        return PlacementConstraint(
            constraint_id=f"constraint_{rel.relation_id}",
            type="contact",
            entities=[a, b],
            tolerance_mm=1.0,
            source=rel.source,
        )

    return None


def _direction_to_axis(direction: str) -> str:
    """'+Z' → 'Z', '-X' → 'X'"""
    return direction.lstrip("+-")
```

## 5.2 文件：`authoring/spatial/solver.py`（Phase A — 仅做约束一致性检查）

Phase A 的 solver **不计算数值坐标**（尺寸未知）。它只验证约束图的一致性：
- 无循环依赖
- 无矛盾的约束对（如同一个 pair 同时要求 above 和 below）
- 所有约束的 entity 都存在

```python
"""Phase A Spatial Solver — 约束一致性检查。

在组件尺寸未知的情况下，solver 不输出数值 placement。
它只检查 SpatialConstraintGraph 的逻辑一致性。
数值求解在 Phase C 的 ConstraintResolver 中完成。
"""

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
    SpatialSolverReport,
    SpatialSolverIssue,
    PlacementConstraint,
)


def validate_constraint_graph(
    graph: SpatialConstraintGraph,
) -> SpatialSolverReport:
    """Phase A：验证约束图的逻辑一致性。"""
    issues: list[SpatialSolverIssue] = []

    # 检查 1：无循环堆叠依赖
    _check_stack_cycles(graph, issues)

    # 检查 2：无矛盾约束
    _check_contradictory_constraints(graph, issues)

    # 检查 3：所有约束的 entity 都存在
    component_ids = {c.component_id for c in graph.components}
    for c in graph.constraints:
        for eid in c.entities:
            if eid not in component_ids:
                issues.append(SpatialSolverIssue(
                    severity="error",
                    code="unknown_entity",
                    message=f"constraint {c.constraint_id!r} references unknown entity {eid!r}",
                    entities=[eid],
                ))

    total = len(graph.constraints)
    unsolved = sum(1 for i in issues if i.severity == "error")
    return SpatialSolverReport(
        ok=unsolved == 0,
        constraints_total=total,
        constraints_solved=total - unsolved,
        constraints_unsolved=unsolved,
        issues=issues,
    )


def _check_stack_cycles(graph: SpatialConstraintGraph, issues: list[SpatialSolverIssue]) -> None:
    """检查 Z 轴堆叠约束无环。"""
    stack_edges: dict[str, list[str]] = {}
    for c in graph.constraints:
        if c.type == "stack" and c.axis == "Z" and len(c.entities) == 2:
            lower, upper = c.entities[0], c.entities[1]
            stack_edges.setdefault(lower, []).append(upper)

    # DFS 环检测
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in stack_edges}
    for node in list(stack_edges.keys()):
        if node not in color:
            color[node] = WHITE

    def dfs(u, path):
        color[u] = GRAY
        for v in stack_edges.get(u, []):
            if v not in color:
                color[v] = WHITE
            if color.get(v) == GRAY:
                cycle = path + [v]
                issues.append(SpatialSolverIssue(
                    severity="error",
                    code="stack_cycle",
                    message=f"cyclic Z stacking: {' → '.join(cycle)}",
                    entities=cycle,
                ))
            elif color.get(v) == WHITE:
                dfs(v, path + [v])
        color[u] = BLACK

    for node in list(stack_edges.keys()):
        if color.get(node) == WHITE:
            dfs(node, [node])


def _check_contradictory_constraints(
    graph: SpatialConstraintGraph, issues: list[SpatialSolverIssue]
) -> None:
    """检查矛盾约束。"""
    pairs: dict[tuple[str, str], list[PlacementConstraint]] = {}
    for c in graph.constraints:
        if len(c.entities) >= 2:
            key = (c.entities[0], c.entities[1])
            pairs.setdefault(key, []).append(c)

    for (a, b), constraints in pairs.items():
        types = {c.type for c in constraints}
        # above + below 矛盾
        if "stack" in types:
            directions = {c.offset_mm for c in constraints}
            # 如果既有 offset≥0 又有 offset<0，矛盾
            offsets = [c.offset_mm for c in constraints if c.type == "stack"]
            if any(o > 0 for o in offsets) and any(o < 0 for o in offsets):
                issues.append(SpatialSolverIssue(
                    severity="error",
                    code="contradictory_stack",
                    message=f"contradictory stack constraints between {a!r} and {b!r}",
                    entities=[a, b],
                ))
```

---

# 6. Prompt 系统

## 6.1 文件：`authoring/spatial/prompts.py`

```python
"""空间意图抽取的 LLM prompt 常量。"""

OBJECT_GRAPH_SYSTEM_PROMPT = """
You are a mechanical CAD spatial-intent extractor for a deterministic CAD compiler.

You do not generate CAD code.
You do not generate RawGcadDocument.
You do not generate final numeric placements unless explicitly provided by the user.
You only extract:
- mechanical components (their roles, approximate shape, known user-stated dimensions)
- functional roles (what each component does mechanically)
- known dimensions (only what the user explicitly stated, with units and axis)
- likely spatial relations (qualitative: above/below/coaxial/symmetric_pair/face_contact...)
- local frame assumptions (center_bottom, center, axis_midpoint...)
- high-impact unknowns (what you need to know but the user didn't say)

You must distinguish source for EVERY fact:
1. USER_EXPLICIT: directly stated by the user with numbers or explicit words ("left", "right", "top", "bottom", "coaxial")
2. LLM_INFERRED: inferred from mechanical convention or component names
3. (ARCHETYPE_DEFAULT and SYSTEM_DEFAULT are added by the code, not by you)

Use millimeters.
Assume global frame: X=left-right, Y=front-back, Z=bottom-top unless user says otherwise.

CRITICAL: component_id MUST match what will appear in FeatureSequence.
Good: "top_plate", "pillar_left", "hub_a"
Bad: "component_1", "part_A"

Do not hide uncertainty.
If relative placement, contact, axis direction, face selection, symmetry, or component count is unclear, emit SpatialUnknown.
For each unknown, estimate:
- impact: how badly the CAD model changes if wrong (0-1)
- uncertainty: how unclear the prompt is (0-1)
- answer_cost: how hard it is for the user to answer (0-1)

Never convert uncertainty into silent coordinates.
Return only strict tool arguments matching the EXACT MechanicalObjectGraphDraft schema.
"""

SPATIAL_PLAN_SYSTEM_PROMPT = """
You are a mechanical spatial planner for a CAD compiler.

You receive:
- the original user request,
- the MechanicalObjectGraphDraft,
- any user answers to clarification questions,
- available component dimensions (known_dimensions),
- available dialect capabilities.

Your task is to emit refined SpatialRelationDraft list that fills gaps and resolves answered unknowns.

Important rules:
- boolean_union is NOT placement. Components need explicit placement before merging.
- multi-component assemblies require placement constraints before boolean_union.
- left/right, front/back, top/bottom component names imply distinct non-overlapping placements.
- supported components must contact their supports (face_contact).
- coaxial mechanical parts must have coaxial constraints.
- stacked parts must have face_contact or offset constraints.
- if a component is intended to connect to another, emit contact/attached_to constraints.
- if unsure, do not invent final coordinates; emit unresolved unknowns.
- if the user answered "AUTO", you may infer conventional mechanical layouts.

Return only strict tool arguments.
"""

QUESTION_PLANNER_SYSTEM_PROMPT = """
You are a clarification question planner for an interactive CAD system.

Your goal is to ask the fewest questions needed to avoid major spatial CAD errors.

Generate questions only for high-priority unknowns:
priority = impact * uncertainty / max(answer_cost, 0.1)

Do not ask questions that code can solve deterministically:
- coordinate system defaults
- fillet/chamfer radii (low spatial impact)
- exact hole positions within a face
Do not ask low-impact aesthetic questions.
Do not ask for full coordinates unless absolutely necessary.

Every question must include:
- why it matters (what CAD error occurs if wrong)
- recommended option (marked recommended: true)
- at least two concrete choices when possible
- CUSTOM option (for free-text answers)
- AUTO option (delegates to system default)
- geometric_consequence for each option (what the layout looks like)

AUTO means:
the system chooses a conventional mechanical layout,
records all assumptions in the assumption ledger,
runs spatial validation,
and asks again if validation fails.

Prefer multiple-choice questions over free text.
Return only strict tool arguments.
"""

ANSWER_NORMALIZER_SYSTEM_PROMPT = """
You normalize a user's clarification answer into SpatialRelationDraft constraints.

Input:
- the original SpatialQuestion,
- the user's answer (option, custom text, or AUTO),
- current MechanicalObjectGraphDraft,
- current SpatialConstraintGraph (if any).

Do not generate CAD code.
Do not generate RawGcadDocument.
Do not add unrelated design intent.

Convert the answer into:
- relations_added: new SpatialRelationDraft objects,
- assumptions_added: statements about what was assumed,
- requires_replanning: whether the object graph needs to be re-extracted.

If the user selected AUTO:
- choose the recommended conventional option unless it violates constraints.
- mark assumptions as user_delegated.
- do not skip validation.

If the user entered custom text:
- extract only spatially relevant constraints.
- preserve uncertainty if incomplete.

Return only strict tool arguments.
"""
```

## 6.2 文件：`authoring/spatial/tool_schemas.py`

```python
"""DeepSeek strict tool schema factories for spatial LLM calls."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialRelationDraft,
    SpatialQuestion,
    NormalizedSpatialAnswer,
)
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
    to_deepseek_strict_schema,
)


def build_object_graph_tool_schema() -> dict[str, Any]:
    """Strict schema for MechanicalObjectGraphDraft extraction."""
    schema = MechanicalObjectGraphDraft.model_json_schema()
    # 移除 mode 的 enum 约束（LLM 不应自由选择模式）
    # 模式由系统在调用时通过 const 注入
    return to_deepseek_strict_schema(schema)


def build_object_graph_tool_schema_for_mode(mode: str) -> dict[str, Any]:
    """注入 mode const 约束的 object graph schema。"""
    schema = MechanicalObjectGraphDraft.model_json_schema()
    _inject_const(schema, ["properties", "mode"], const=mode)
    return to_deepseek_strict_schema(schema)


def build_spatial_plan_tool_schema() -> dict[str, Any]:
    """Strict schema for spatial plan refinement (list of SpatialRelationDraft)."""
    from pydantic import BaseModel, Field
    class SpatialPlanOutput(BaseModel):
        relations: list[SpatialRelationDraft] = Field(default_factory=list)
        unknowns: list = Field(default_factory=list)
        assumptions: list[str] = Field(default_factory=list)
        model_config = {"extra": "forbid"}
    return to_deepseek_strict_schema(SpatialPlanOutput.model_json_schema())


def build_question_planner_tool_schema() -> dict[str, Any]:
    """Strict schema for question generation."""
    from pydantic import BaseModel, Field
    class QuestionPlannerOutput(BaseModel):
        questions: list[SpatialQuestion] = Field(default_factory=list)
        no_questions_needed: bool = False
        reasoning: str = ""
        model_config = {"extra": "forbid"}
    return to_deepseek_strict_schema(QuestionPlannerOutput.model_json_schema())


def build_answer_normalizer_tool_schema() -> dict[str, Any]:
    """Strict schema for answer normalization."""
    return to_deepseek_strict_schema(NormalizedSpatialAnswer.model_json_schema())


def _inject_const(schema: dict, path: list[str], **kwargs) -> None:
    """在 JSON schema 路径注入 const/enum 约束。"""
    current = schema
    for key in path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    last = path[-1]
    if last not in current:
        current[last] = {}
    for k, v in kwargs.items():
        if k not in current[last]:
            current[last][k] = v
```

---

# 7. SpatialPipeline 集成现有 AuthoringPipeline

## 7.1 文件：`authoring/spatial/pipeline.py`

```python
"""Spatial Frontend Pipeline — Phase A 入口。

在 RoutePlan 之后、FeatureSequence 之前运行。
返回 SpatialFrontendResult，可能要求用户澄清。

单组件 case（len(components)==1）：自动跳过，返回空结果。
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig
from seekflow_engineering_tools.generative_cad.llm.provider import LlmToolCaller
from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry
from seekflow_engineering_tools.generative_cad.base_packages.registry import BasePackageRegistry
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialConstraintGraph,
    SpatialFrontendResult,
    SpatialModeType,
    SpatialSessionState,
    AssumptionLedger,
    AssumptionEntry,
    SpatialFinalStatus,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.constraint_graph import (
    build_constraint_graph,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.solver import (
    validate_constraint_graph,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.validators import (
    validate_spatial_contract_phase_a,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import (
    default_archetypes,
)


def run_spatial_authoring_frontend(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry: DialectRegistry,
    base_package_registry: BasePackageRegistry,
    object_graph_caller: LlmToolCaller | None = None,
    spatial_plan_caller: LlmToolCaller | None = None,
    question_caller: LlmToolCaller | None = None,
    answer_normalizer_caller: LlmToolCaller | None = None,
    user_answers: list[UserSpatialAnswer] | None = None,
    session_state: SpatialSessionState | None = None,
    mode: SpatialModeType = "guided",
    question_budget: int = 3,
) -> SpatialFrontendResult:
    """Phase A：空间意图解析。

    多轮交互流程：
    1. 第一轮：无 session_state → LLM 提取 object_graph → 可能需要 clarification
    2. 如果需要 clarification：返回 questions + session_state（上层保存）
    3. 第二轮：传入 user_answers + session_state → 恢复状态 → 归一化回答 → 重新求解
    """
    failures: list[str] = []
    ledger = AssumptionLedger()

    # ── Step 0: 单组件快速路径 ──
    # (延迟判断：先检查是否有 session_state)

    # ── Step 1: 恢复或提取 object graph ──
    object_graph: MechanicalObjectGraphDraft | None = None

    if session_state is not None:
        object_graph = MechanicalObjectGraphDraft.model_validate_json(
            session_state.object_graph_json
        )
        ledger = AssumptionLedger.model_validate_json(session_state.ledger_json)

    if object_graph is None:
        if object_graph_caller is None:
            return SpatialFrontendResult(
                ok=False,
                failures=["object_graph_caller is required for initial round"],
            )
        object_graph = _extract_object_graph(
            user_request, object_graph_caller, llm_config, mode
        )
        if object_graph is None:
            return SpatialFrontendResult(
                ok=False,
                failures=["failed to extract MechanicalObjectGraphDraft"],
            )

    # 单组件：跳过 spatial frontend（直接返回成功）
    if len(object_graph.components) == 1:
        return SpatialFrontendResult(
            ok=True,
            final_status="VERIFIED",
            object_graph=object_graph,
            assumption_ledger=ledger,
        )

    # ── Step 2: 匹配 archetype ──
    _apply_archetypes(object_graph, mode, ledger)

    # ── Step 3: 处理用户回答（第二轮）──
    if user_answers and answer_normalizer_caller is not None:
        from seekflow_engineering_tools.generative_cad.authoring.spatial.answer_normalizer import (
            normalize_answers,
        )
        normalized_list = normalize_answers(
            user_answers, object_graph, answer_normalizer_caller, llm_config
        )
        for na in normalized_list:
            object_graph.candidate_relations.extend(na.relations_added)
            for assumption_text in na.assumptions_added:
                ledger.add(AssumptionEntry(
                    assumption_id=f"user_answer_{na.question_id}",
                    statement=assumption_text,
                    source="user_selected_option",
                    confidence=0.9,
                    user_confirmed=True,
                ))

    # ── Step 4: 构建 SpatialConstraintGraph ──
    constraint_graph = build_constraint_graph(object_graph)

    # ── Step 5: Phase A solver 一致性验证 ──
    solver_report = validate_constraint_graph(constraint_graph)
    if not solver_report.ok:
        return SpatialFrontendResult(
            ok=False,
            object_graph=object_graph,
            constraint_graph=constraint_graph,
            solver_report=solver_report,
            assumption_ledger=ledger,
            failures=[f"solver error: {i.message}" for i in solver_report.issues],
        )

    # ── Step 6: 检查是否需要 clarification ──
    if object_graph.unknowns and mode in ("guided", "precision"):
        from seekflow_engineering_tools.generative_cad.authoring.spatial.question_planner import (
            plan_questions,
        )
        questions = plan_questions(object_graph, budget=question_budget)
        if questions:
            import uuid
            session = SpatialSessionState(
                session_id=(
                    session_state.session_id if session_state
                    else f"spatial_{uuid.uuid4().hex[:12]}"
                ),
                object_graph_json=object_graph.model_dump_json(),
                constraint_graph_json=constraint_graph.model_dump_json(),
                ledger_json=ledger.model_dump_json(),
                answered_question_ids=(
                    session_state.answered_question_ids if session_state else []
                ),
                round_number=(session_state.round_number + 1) if session_state else 1,
                max_rounds=3,
            )
            return SpatialFrontendResult(
                ok=True,
                needs_clarification=True,
                final_status="NEEDS_CLARIFICATION",
                questions=questions,
                object_graph=object_graph,
                constraint_graph=constraint_graph,
                solver_report=solver_report,
                assumption_ledger=ledger,
                session_state=session,
            )

    # ── Step 7: Phase A spatial validation ──
    validation_report = validate_spatial_contract_phase_a(constraint_graph)
    final_status: SpatialFinalStatus = (
        "VERIFIED" if validation_report.ok else "ASSUMPTION_BASED"
    )

    return SpatialFrontendResult(
        ok=True,
        final_status=final_status,
        object_graph=object_graph,
        constraint_graph=constraint_graph,
        solver_report=solver_report,
        validation_report=validation_report,
        assumption_ledger=ledger,
    )


def _extract_object_graph(
    user_request: str,
    caller: LlmToolCaller,
    llm_config: AuthoringLlmConfig,
    mode: SpatialModeType,
) -> MechanicalObjectGraphDraft | None:
    from seekflow_engineering_tools.generative_cad.authoring.spatial.prompts import (
        OBJECT_GRAPH_SYSTEM_PROMPT,
    )
    from seekflow_engineering_tools.generative_cad.authoring.spatial.tool_schemas import (
        build_object_graph_tool_schema_for_mode,
    )
    try:
        result = caller.call_strict_tool(
            messages=[
                {"role": "system", "content": OBJECT_GRAPH_SYSTEM_PROMPT},
                {"role": "user", "content": user_request},
            ],
            tool_name="emit_object_graph",
            tool_description="Extract components and spatial relationships",
            tool_schema=build_object_graph_tool_schema_for_mode(mode),
            model_config=llm_config.author,
        )
        return MechanicalObjectGraphDraft.model_validate(result.arguments)
    except Exception:
        return None


def _apply_archetypes(
    graph: MechanicalObjectGraphDraft,
    mode: SpatialModeType,
    ledger: AssumptionLedger,
) -> None:
    if mode not in ("auto_mechanical", "auto_complex_verified", "guided"):
        return
    registry = default_archetypes()
    for spec in registry.match(graph):
        if mode in spec.applicable_modes:
            relations = spec.relations(graph)
            graph.candidate_relations.extend(relations)
            for rel in relations:
                ledger.add(AssumptionEntry(
                    assumption_id=f"archetype_{spec.archetype_id}_{rel.relation_id}",
                    statement=rel.rationale,
                    source="archetype_default",
                    confidence=rel.confidence.value,
                ))
```

## 7.2 文件：`authoring/spatial/integration.py`

将 SpatialConstraintGraph 注入 FeatureSequence 生成。

```python
"""Placement 约束注入 FeatureSequence 生成过程。"""

from seekflow_engineering_tools.generative_cad.authoring.schemas import (
    FeatureSequenceDraft,
    NodePlanDraft,
    ComponentDraft,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
)


def inject_placements_into_feature_sequence(
    feature_sequence: FeatureSequenceDraft,
    spatial_graph: SpatialConstraintGraph,
) -> FeatureSequenceDraft:
    """为多组件装配注入 placement 节点。

    规则：
    1. 多组件必须存在 __assembly__ component
    2. 每个 leaf component root body 在 boolean_union 前插入 place_component
    3. place_component 使用 PLACEHOLDER 坐标（solver 在 Runtime 中填充）
    4. boolean_union 消费 placed solid（由 raw_assembler scope 机制保证）
    """
    components = list(feature_sequence.components)
    nodes = list(feature_sequence.node_sequence)

    non_assembly = [c for c in components if c.component_id != "__assembly__"]
    if len(non_assembly) <= 1:
        return feature_sequence

    # 确保 __assembly__ 存在
    assembly = next((c for c in components if c.component_id == "__assembly__"), None)
    if assembly is None:
        assembly = ComponentDraft(
            component_id="__assembly__",
            owner_dialect="composition",
            kind_hint="assembly",
        )
        components.append(assembly)

    existing_ids = {n.node_id for n in nodes}

    # 为每个 leaf component root body 插入 place_component
    placement_nodes: list[NodePlanDraft] = []
    for comp in non_assembly:
        place_id = f"place_{comp.component_id}"
        if place_id not in existing_ids:
            placement_nodes.append(NodePlanDraft(
                node_id=place_id,
                component_id="__assembly__",
                dialect="composition",
                op="place_component",
                op_version="1.0.0",
                phase="transform",
                purpose=f"Place {comp.component_id} root body at solver-derived coordinates",
                expected_input_source=comp.component_id,
                expected_output_name="body",
            ))

    # 插入到 boolean_union 之前
    assembly_nodes = [n for n in nodes if n.component_id == "__assembly__"]
    union_indices = [
        i for i, n in enumerate(assembly_nodes)
        if n.op == "boolean_union"
    ]
    insert_index = union_indices[0] if union_indices else len(nodes)
    for pn in reversed(placement_nodes):
        nodes.insert(insert_index, pn)

    return FeatureSequenceDraft(
        components=components,
        node_sequence=nodes,
        assumptions=feature_sequence.assumptions,
        unsupported_details=feature_sequence.unsupported_details,
    )


def build_spatial_context_for_prompt(
    spatial_graph: SpatialConstraintGraph,
) -> str:
    """构建注入 FeatureSequence user prompt 的 SPATIAL CONTRACT 文本。"""
    if not spatial_graph.constraints:
        return ""

    lines = [
        "SPATIAL CONTRACT (symbolic constraints — numeric values will be solved at runtime):",
        "",
    ]
    for c in spatial_graph.constraints:
        entities_str = ", ".join(c.entities)
        lines.append(f"- [{c.constraint_id}] {c.type}({entities_str})")
        if c.bindings:
            for k, v in c.bindings.items():
                lines.append(f"    {k} = ${v.component_id}.{v.axis}_{v.edge}")
        if c.offset_mm != 0.0:
            lines.append(f"    offset={c.offset_mm}mm")
        lines.append(f"    source={c.source}")

    if spatial_graph.assumptions:
        lines.append("")
        lines.append("ASSUMPTIONS:")
        for a in spatial_graph.assumptions[:20]:
            lines.append(f"- {a}")

    return "\n".join(lines)
```

## 7.3 现有 `authoring/pipeline.py` 的修改点

在 `generate_gcad_from_user_request()` 中：

```python
# 新增参数：
enable_spatial_frontend: bool = True
spatial_mode: SpatialModeType = "guided"
spatial_user_answers: list[UserSpatialAnswer] | None = None
spatial_session_state: SpatialSessionState | None = None
question_budget: int = 3
object_graph_caller = None
spatial_plan_caller = None
question_caller = None
answer_normalizer_caller = None

# 新增字段在 AuthoringPipelineResult：
spatial_frontend: SpatialFrontendResult | None = None

# 在 Route (Stage 1) 之前插入 Stage 0：
if enable_spatial_frontend:
    spatial_result = run_spatial_authoring_frontend(...)
    result.spatial_frontend = spatial_result
    if spatial_result.needs_clarification:
        return result  # 不继续，返回问题给上层 UI
```

修改 `build_feature_sequence_user_prompt` 调用，注入 spatial context：

```python
if spatial_result is not None and spatial_result.constraint_graph is not None:
    spatial_context_text = build_spatial_context_for_prompt(
        spatial_result.constraint_graph
    )
    user_prompt = build_feature_sequence_user_prompt(
        ...,
        spatial_context=spatial_context_text,  # 在 prompt 末尾追加
    )
```

---

# 8. Phase C：ConstraintResolver（核心数值求解器）

这是整个 v6 架构中最重要的新模块。它在 `_run_components` 和 `_run_composition_or_select_final` 之间运行。

## 8.1 文件：`runtime/constraint_resolver.py`

```python
"""Phase C ConstraintResolver — 符号约束 → 数值 Placement。

运行时机：所有 leaf components 执行完毕后、assembly composition 执行前。

输入: SpatialConstraintGraph（符号约束）+ 实际 bbox 测量
输出: dict[component_id, NumericPlacement]
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph, PlacementConstraint,
    NumericPlacement, ComponentBBox, ComponentRole,
    SymbolicDimensionRef, Confidence,
)


@dataclass
class ResolverCtx:
    component_bboxes: dict[str, ComponentBBox] = field(default_factory=dict)
    placements: dict[str, NumericPlacement] = field(default_factory=dict)
    graph: SpatialConstraintGraph | None = None
    default_spacing_mm: float = 30.0
    issues: list[str] = field(default_factory=list)


def resolve_placements(
    constraint_graph: SpatialConstraintGraph,
    bboxes: dict[str, ComponentBBox],
    default_spacing_mm: float = 30.0,
) -> tuple[dict[str, NumericPlacement], list[str]]:
    """符号约束 + 实际 bbox → 数值 placement。

    求解顺序:
    1. identity 约束 → 直接设为 (0,0,0)
    2. stack 约束 → Z 轴堆叠方程求解 (topological sort)
    3. align_axis 约束 → 同轴对齐横向坐标
    4. symmetric 约束 → X 轴对称布局
    5. contact 约束 → 验证 (不修改 placement)

    返回 (placements, issues)。
    """
    ctx = ResolverCtx(
        component_bboxes=bboxes,
        graph=constraint_graph,
        default_spacing_mm=default_spacing_mm,
    )

    # 初始化所有 placement 为 identity
    for cid in bboxes:
        ctx.placements[cid] = NumericPlacement(
            component_id=cid,
            translation_mm=(0.0, 0.0, 0.0),
            source="solver_derived",
            is_pending=True,
            pending_reason="not yet solved",
        )

    _resolve_identity(ctx)
    _resolve_stack(ctx)
    _resolve_align_axis(ctx)
    _resolve_symmetric(ctx)

    # 标记已求解
    for p in ctx.placements.values():
        if p.is_pending and p.pending_reason == "not yet solved":
            p.is_pending = False
            p.pending_reason = "default identity (no constraint applied)"

    return ctx.placements, ctx.issues


def _resolve_identity(ctx: ResolverCtx) -> None:
    if ctx.graph is None:
        return
    for c in ctx.graph.constraints:
        if c.type == "identity" and len(c.entities) >= 1:
            cid = c.entities[0]
            if cid in ctx.placements:
                ctx.placements[cid] = NumericPlacement(
                    component_id=cid,
                    translation_mm=(0.0, 0.0, 0.0),
                    source="solver_derived",
                    is_pending=False,
                    confidence=Confidence(value=1.0, reason="explicit identity constraint"),
                )


def _resolve_stack(ctx: ResolverCtx) -> None:
    """Z 轴堆叠求解 (topological sort)。

    约束形式: lower.zmax + offset = upper.zmin

    算法:
    1. 构建 DAG (lower → upper)
    2. Kahn topological sort
    3. 按拓扑序计算 zmin = max(all lower.zmax + offset)
    """
    if ctx.graph is None:
        return

    stack_cs = [
        c for c in ctx.graph.constraints
        if c.type == "stack" and c.axis == "Z" and len(c.entities) >= 2
    ]
    if not stack_cs:
        return

    # 构建邻接和入度
    above: dict[str, list[tuple[str, float]]] = {}
    in_deg: dict[str, int] = {}
    all_ids: set[str] = set()

    for c in stack_cs:
        lower, upper = c.entities[0], c.entities[1]
        above.setdefault(lower, []).append((upper, c.offset_mm))
        in_deg[upper] = in_deg.get(upper, 0) + 1
        in_deg.setdefault(lower, 0)
        all_ids.add(lower); all_ids.add(upper)

    # Kahn topological sort
    queue = [cid for cid in all_ids if in_deg.get(cid, 0) == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for upper, _ in above.get(node, []):
            in_deg[upper] -= 1
            if in_deg[upper] == 0:
                queue.append(upper)

    if len(order) != len(all_ids):
        ctx.issues.append("stack constraint cycle detected, using partial order")
        order = list(all_ids)

    # 按拓扑序计算 zmin
    # 找到每个 cid 的所有直接 lower neighbor 及其 zmax
    lower_of: dict[str, list[tuple[str, float]]] = {}
    for lower, edges in above.items():
        for upper, offset in edges:
            lower_of.setdefault(upper, []).append((lower, offset))

    for cid in order:
        bbox = ctx.component_bboxes.get(cid)
        if bbox is None:
            continue

        zmin_candidates = [0.0]
        for lower_cid, offset in lower_of.get(cid, []):
            lower_bbox = ctx.component_bboxes.get(lower_cid)
            if lower_bbox is None:
                continue
            lower_placement = ctx.placements.get(lower_cid)
            lower_z = lower_placement.translation_mm[2] if lower_placement else 0.0
            zmin_candidates.append(lower_z + lower_bbox.zlen + offset)

        new_zmin = max(zmin_candidates)
        current = ctx.placements.get(cid)
        if current:
            ctx.placements[cid] = NumericPlacement(
                component_id=cid,
                translation_mm=(current.translation_mm[0], current.translation_mm[1], new_zmin),
                rotation_deg_xyz=current.rotation_deg_xyz,
                source="solver_derived",
                confidence=Confidence(value=1.0, reason="solved from stack constraints"),
                is_pending=False,
            )


def _resolve_align_axis(ctx: ResolverCtx) -> None:
    """同轴对齐 (S040)。默认 Z 轴同轴: X,Y 对齐到参考组件中心。"""
    if ctx.graph is None:
        return
    for c in ctx.graph.constraints:
        if c.type != "align_axis" or len(c.entities) < 2:
            continue

        ref_id = c.entities[0]
        ref_bbox = ctx.component_bboxes.get(ref_id)
        ref_pl = ctx.placements.get(ref_id)
        if ref_bbox is None or ref_pl is None or ref_pl.is_pending:
            continue

        ref_center = (
            ref_pl.translation_mm[0] + ref_bbox.xlen / 2,
            ref_pl.translation_mm[1] + ref_bbox.ylen / 2,
            ref_pl.translation_mm[2] + ref_bbox.zlen / 2,
        )
        axis = c.axis or "Z"

        for target_id in c.entities[1:]:
            t_bbox = ctx.component_bboxes.get(target_id)
            t_pl = ctx.placements.get(target_id)
            if t_bbox is None or t_pl is None:
                continue

            if axis == "Z":
                new_x = ref_center[0] - t_bbox.xlen / 2
                new_y = ref_center[1] - t_bbox.ylen / 2
                ctx.placements[target_id] = NumericPlacement(
                    component_id=target_id,
                    translation_mm=(new_x, new_y, t_pl.translation_mm[2]),
                    rotation_deg_xyz=t_pl.rotation_deg_xyz,
                    source="solver_derived",
                    confidence=Confidence(value=1.0, reason="solved from coaxial constraint"),
                    is_pending=False,
                )


def _resolve_symmetric(ctx: ResolverCtx) -> None:
    """对称对求解 (S030)。默认 YZ 对称面 X=0。"""
    if ctx.graph is None:
        return
    for c in ctx.graph.constraints:
        if c.type != "symmetric" or len(c.entities) < 2:
            continue

        a_id, b_id = c.entities[0], c.entities[1]
        a_bb = ctx.component_bboxes.get(a_id)
        b_bb = ctx.component_bboxes.get(b_id)
        if a_bb is None or b_bb is None:
            continue

        # 确定间距
        if c.spacing_mm is not None:
            d = c.spacing_mm
        else:
            d = max(a_bb.xlen, b_bb.xlen) * 3.0
            ctx.issues.append(
                f"[assumption] symmetric_pair({a_id}, {b_id}): "
                f"no spacing specified, using derived = {d:.1f}mm"
            )

        half_d = d / 2.0
        a_pl = ctx.placements.get(a_id, NumericPlacement(component_id=a_id))
        b_pl = ctx.placements.get(b_id, NumericPlacement(component_id=b_id))

        ctx.placements[a_id] = NumericPlacement(
            component_id=a_id,
            translation_mm=(-half_d - a_bb.xlen / 2, a_pl.translation_mm[1], a_pl.translation_mm[2]),
            source="solver_derived",
            confidence=Confidence(value=0.85, reason="solved from symmetric_pair"),
            is_pending=False,
            assumptions=[f"derived symmetric spacing={d:.1f}mm"] if c.spacing_mm is None else [],
        )
        ctx.placements[b_id] = NumericPlacement(
            component_id=b_id,
            translation_mm=(half_d - b_bb.xlen / 2, b_pl.translation_mm[1], b_pl.translation_mm[2]),
            source="solver_derived",
            confidence=Confidence(value=0.85, reason="solved from symmetric_pair"),
            is_pending=False,
            assumptions=[f"derived symmetric spacing={d:.1f}mm"] if c.spacing_mm is None else [],
        )
```

---

# 9. Pipeline Runner 改造 + RuntimeContext 扩展

## 9.1 修改 `pipeline/run.py` 中的 `run_canonical_gcad`

在 `_run_components` 和 `_run_composition_or_select_final` 之间插入：

```python
try:
    _run_components(canonical, ctx)

    # ════════════════════════════════════════════════════════════
    # v6 NEW: Constraint Resolution
    # ════════════════════════════════════════════════════════════
    spatial_graph = _load_spatial_contract(ctx)
    if spatial_graph is not None:
        from seekflow_engineering_tools.generative_cad.runtime.bbox_tracker import (
            measure_all_component_bboxes,
        )
        from seekflow_engineering_tools.generative_cad.runtime.constraint_resolver import (
            resolve_placements,
        )

        component_ids = [
            c.id for c in canonical.components
            if c.id != "__assembly__"
        ]
        bboxes = measure_all_component_bboxes(ctx, component_ids)
        placements, issues = resolve_placements(spatial_graph, bboxes)
        ctx.spatial_placements = placements
        for issue in issues:
            ctx.warnings.append(f"[spatial solver] {issue}")

        unsolved = [cid for cid, p in placements.items() if p.is_pending]
        if unsolved:
            ctx.warnings.append(
                f"spatial: {len(unsolved)} unsolved placements: {unsolved}"
            )
    # ════════════════════════════════════════════════════════════

    final_handle_id = _run_composition_or_select_final(canonical, ctx)

    # ════════════════════════════════════════════════════════════
    # v6 NEW: GeometrySpatialAudit
    # ════════════════════════════════════════════════════════════
    if spatial_graph is not None:
        from seekflow_engineering_tools.generative_cad.runtime.spatial_audit import (
            run_geometry_spatial_audit,
        )
        audit = run_geometry_spatial_audit(
            final_handle_id=final_handle_id,
            ctx=ctx,
            spatial_graph=spatial_graph,
            placements=getattr(ctx, 'spatial_placements', {}),
        )
        ctx.spatial_audit_report = audit
        if not audit.ok:
            errors = [i for i in audit.issues if i.severity == "error"]
            if errors:
                return GcadRunResult(
                    ok=False,
                    error="spatial audit failed: " + "; ".join(i.message for i in errors),
                    warnings=ctx.warnings,
                    degraded_features=ctx.degraded_features,
                    operation_metrics=ctx.operation_metrics,
                )
    # ════════════════════════════════════════════════════════════

    validate_runtime_postconditions(...)
    _export_final_solid(...)
```

## 9.2 RuntimeContext 新增字段

在 `runtime/context.py` 的 `RuntimeContext` dataclass 中新增：

```python
spatial_placements: dict[str, Any] = field(default_factory=dict)
spatial_audit_report: Any = None
spatial_contract_hash: str | None = None
```

## 9.3 spatial_contract 加载

```python
def _load_spatial_contract(ctx) -> SpatialConstraintGraph | None:
    """从 workspace 加载 spatial_contract.json sidecar。"""
    import json
    sp = ctx.workspace_root / "spatial_contract.json"
    if not sp.exists():
        return None
    from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
        SpatialConstraintGraph,
    )
    data = json.loads(sp.read_text(encoding="utf-8"))
    return SpatialConstraintGraph.model_validate(data)
```

---

# 10. Composition Dialect 与 raw_assembler 改造

## 10.1 `dialects/composition/handlers.py` — `handle_place_component` 改造

```python
def handle_place_component(node, ctx) -> dict:
    """v6: 从 ctx.spatial_placements 读取 solver 求解的坐标。"""
    import cadquery as cq
    import math
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object

    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    translation = p.get("translation_mm", (0.0, 0.0, 0.0))
    rotation = p.get("rotation_deg_xyz", (0.0, 0.0, 0.0))
    identity_ok = p.get("identity_ok", False)

    # v6: solver 覆盖
    placements = getattr(ctx, 'spatial_placements', {})
    if placements and node.inputs:
        inp = node.inputs[0]
        comp_id = inp.producer_component if hasattr(inp, 'producer_component') else None
        if comp_id and comp_id in placements:
            solved = placements[comp_id]
            if not solved.is_pending:
                translation = solved.translation_mm
                rotation = solved.rotation_deg_xyz
                ctx.operation_metrics.append({
                    "node_id": node.id, "op": "place_component",
                    "translation_mm": list(translation),
                    "placement_source": "solver_derived",
                })

    # Identity check
    is_identity = (translation == (0.0, 0.0, 0.0) and rotation == (0.0, 0.0, 0.0))
    if is_identity and not identity_ok:
        ctx.warnings.append(
            f"place_component '{node.id}': identity placement without identity_ok=True"
        )

    # Transform
    try:
        result = body
        if rotation != (0.0, 0.0, 0.0):
            rx, ry, rz = math.radians(rotation[0]), math.radians(rotation[1]), math.radians(rotation[2])
            result = result.rotate((0, 0, 0), (1, 0, 0), math.degrees(rx))
            result = result.rotate((0, 0, 0), (0, 1, 0), math.degrees(ry))
            result = result.rotate((0, 0, 0), (0, 0, 1), math.degrees(rz))
        if translation != (0.0, 0.0, 0.0):
            result = result.translate(translation)
    except Exception as e:
        ctx.warnings.append(f"place_component failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}

    return {"body": _store_solid(node, ctx, result)}
```

## 10.2 `authoring/raw_assembler.py` — placement 节点的 scope 处理

在 `_build_assembly_nodes()` 中，placement 节点（`place_component`/`translate_solid`/`rotate_solid`）的输出应注册到 `__assembly__` scope（而非自身 component scope）：

```python
elif node_plan.op in ("place_component", "translate_solid", "rotate_solid"):
    node_dict = _build_single_node(node_plan, node_params, dialect_registry, available, system_filled)
    assembled.append(node_dict)
    # 关键: placed solid 注册到 __assembly__ scope
    ref = ValueRef(
        node_id=node_plan.node_id,
        output_name="body",
        value_type="solid",
        component_id="__assembly__",
        dialect="composition",
        op=node_plan.op,
    )
    available["__assembly__"]["solid"].append(ref)
```

这确保了后续 `boolean_union` 通过 typed wiring 自动消费 placed solid 而非原始 component root solid。

---

# 11. 几何内核改造（关键实现）

## 11.1 `dialects/geometry_utils/ocp_wire.py`

```python
"""OCP 3D wire builders — 完全绕过 CadQuery XY 平面限制。"""

def make_3d_polyline_wire(points: list[tuple[float, float, float]]):
    """从 3D 点列表构建 TopoDS_Wire。纯垂直/水平/倾斜段全部支持。"""
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

    if len(points) < 2:
        raise ValueError("Need at least 2 points for polyline wire")

    wb = BRepBuilderAPI_MakeWire()
    for i in range(len(points) - 1):
        p0, p1 = points[i], points[i + 1]
        edge = BRepBuilderAPI_MakeEdge(
            gp_Pnt(p0[0], p0[1], p0[2]),
            gp_Pnt(p1[0], p1[1], p1[2]),
        ).Edge()
        wb.Add(edge)

    if not wb.IsDone():
        raise RuntimeError("BRepBuilderAPI_MakeWire failed for 3D polyline")
    return wb.Wire()


def make_3d_spline_wire(points: list[tuple[float, float, float]]):
    """3D B-spline wire（通过所有点）。"""
    from OCP.gp import gp_Pnt
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

    if len(points) < 2:
        raise ValueError("Need at least 2 points for spline wire")

    ocp_pts = [gp_Pnt(p[0], p[1], p[2]) for p in points]
    spline_api = GeomAPI_PointsToBSpline(ocp_pts)
    if not spline_api.IsDone():
        raise RuntimeError("GeomAPI_PointsToBSpline failed")
    spline = spline_api.Curve()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wb = BRepBuilderAPI_MakeWire()
    wb.Add(edge)
    return wb.Wire()
```

## 11.2 `dialects/geometry_utils/ocp_pipe.py`

```python
"""OCP pipe sweeper — 圆形截面沿任意 3D 路径构建管道。"""
import math

def make_circular_pipe_along_path(
    path_points: list[tuple[float, float, float]],
    radius_mm: float,
):
    """沿 3D 点路径构建圆形截面管道。

    2 点直线: BRepPrimAPI_MakeCylinder + rotate (fast path)
    3+ 点折线: 分段 straight pipe + BRepAlgoAPI_Fuse
    """
    import cadquery as cq

    if len(path_points) < 2:
        raise ValueError("Need at least 2 path points")

    if len(path_points) == 2:
        return _make_straight_pipe(path_points[0], path_points[1], radius_mm)

    # 分段构建 + fuse
    segments = [
        _make_straight_pipe(path_points[i], path_points[i + 1], radius_mm)
        for i in range(len(path_points) - 1)
    ]

    result = segments[0]
    for seg in segments[1:]:
        try:
            result = result.union(seg)
        except Exception:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
            fuse = BRepAlgoAPI_Fuse(result.wrapped, seg.wrapped)
            fuse.Build()
            if fuse.IsDone():
                result = cq.Solid(fuse.Shape())
    return result


def _make_straight_pipe(p0, p1, radius_mm):
    """两点间直管段（任意方向）。"""
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    length = math.sqrt(dx*dx + dy*dy + dz*dz)
    if length < 1e-9:
        raise ValueError("Pipe segment length too small")

    direction = gp_Dir(dx / length, dy / length, dz / length)
    z_axis = gp_Dir(0, 0, 1)

    cyl = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, 0), z_axis), radius_mm, length
    ).Shape()
    solid = cq.Solid(cyl)

    if not direction.IsEqual(z_axis, 0.001):
        # 计算 Z→target 的旋转
        cross_x = z_axis.Y() * direction.Z() - z_axis.Z() * direction.Y()
        cross_y = z_axis.Z() * direction.X() - z_axis.X() * direction.Z()
        cross_z = z_axis.X() * direction.Y() - z_axis.Y() * direction.X()
        angle = math.degrees(math.acos(min(1.0, z_axis.Dot(direction))))
        norm = math.sqrt(cross_x**2 + cross_y**2 + cross_z**2)
        if norm > 1e-12:
            solid = solid.rotate((0, 0, 0), (cross_x/norm, cross_y/norm, cross_z/norm), angle)

    solid = solid.translate((p0[0], p0[1], p0[2]))
    return solid
```

## 11.3 Helix Sweep 分段 + 体积强校验

修改 `dialects/loft_sweep/handlers.py`:

```python
def handle_helix_sweep_v6(node, ctx) -> dict:
    """v6 helix sweep: ≤8 turns 一次性, >8 turns 分段 (max 3 turns/段)。

    体积 ratio < 0.55 或 > 1.65: 默认 fail runtime。
    仅 degradation_policy="may_skip_with_warning" 且 required=False 时允许降级。
    """
    import cadquery as cq, math
    params = node.params
    turns = float(params.get("turns", 1.0))
    radius = float(params.get("radius_mm", 10))
    profile_r = float(params.get("profile_radius_mm", 2))
    pitch = float(params.get("pitch_mm", 0.0))
    height_raw = params.get("height_mm")

    if turns <= 0: raise RuntimeError("helix_sweep requires turns > 0")
    if radius <= 0: raise RuntimeError("helix_sweep requires radius_mm > 0")
    if profile_r <= 0: raise RuntimeError("helix_sweep requires profile_radius_mm > 0")

    if height_raw is not None:
        total_z = float(height_raw)
    elif pitch > 0:
        total_z = pitch * turns
    else:
        raise RuntimeError("helix_sweep requires height_mm or positive pitch_mm")

    # 自交检查
    if pitch > 0 and profile_r >= pitch * 0.45:
        ctx.warnings.append(f"helix_sweep: profile_r >= 0.45*pitch, may self-intersect")

    # 构建
    MAX_TURNS_PER_SEG = 3
    if turns <= 8:
        solid = _helix_sweep_oneshot(radius, total_z, turns, profile_r, ctx, node.id)
    else:
        solid = _helix_sweep_segmented(radius, total_z, turns, profile_r, MAX_TURNS_PER_SEG, ctx)

    # 体积强校验
    expected = _estimate_helix_sweep_volume(radius, profile_r, turns, total_z)
    actual = solid.val().Volume() if hasattr(solid, 'val') else solid.Volume()
    ratio = actual / expected if expected > 0 else 0

    if ratio < 0.55 or ratio > 1.65:
        if node.degradation_policy == "may_skip_with_warning" and not node.required:
            ctx.warnings.append(f"helix_sweep volume ratio={ratio:.3f} (degraded)")
            ctx.degraded_features.append({
                "node_id": node.id, "op": "helix_sweep",
                "reason": f"volume deviation ratio={ratio:.3f}",
            })
        else:
            raise RuntimeError(
                f"helix_sweep volume ratio={ratio:.3f} "
                f"(actual={actual:.0f}, expected={expected:.0f}). FAILING."
            )

    return {"body": _store_solid(node, ctx, solid)}


def _helix_sweep_segmented(radius, total_z, turns, profile_r, max_turns_per_seg, ctx):
    """分段 helix sweep + boolean fuse。"""
    import math, cadquery as cq

    n_segs = int(math.ceil(turns / max_turns_per_seg))
    turns_per = turns / n_segs
    z_per = total_z / n_segs

    seg_solids = []
    for i in range(n_segs):
        z_start = z_per * i
        seg_z = z_per
        sample_n = max(360, int(math.ceil(turns_per * 60)))
        n_pts = sample_n + 1

        from OCP.gp import gp_Pnt
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.GeomAPI import GeomAPI_PointsToBSpline
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

        arr = TColgp_Array1OfPnt(1, n_pts)
        for j in range(n_pts):
            t = j / sample_n
            angle = 2.0 * math.pi * turns_per * t
            z = z_start + seg_z * t
            arr.SetValue(j + 1, gp_Pnt(radius*math.cos(angle), radius*math.sin(angle), z))

        spline_api = GeomAPI_PointsToBSpline(arr)
        if not spline_api.IsDone():
            raise RuntimeError(f"segment {i} GeomAPI_PointsToBSpline failed")
        spline = spline_api.Curve()
        edge = BRepBuilderAPI_MakeEdge(spline).Edge()
        wire_builder = BRepBuilderAPI_MakeWire()
        wire_builder.Add(edge)
        seg_wire = wire_builder.Wire()

        profile = cq.Workplane("XZ").center(radius, 0).circle(profile_r)
        pf = profile.val()
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
        pipe = BRepOffsetAPI_MakePipe(seg_wire, pf.wrapped if hasattr(pf, 'wrapped') else pf)
        pipe.Build()
        if not pipe.IsDone():
            raise RuntimeError(f"segment {i} OCP MakePipe failed")
        seg_solids.append(cq.Solid(pipe.Shape()))

    result = seg_solids[0]
    for seg in seg_solids[1:]:
        result = result.union(seg)
    return result
```

## 11.4 Side Drilling: `handle_drill_hole_3d`

新增到 `dialects/sketch_extrude/handlers.py`:

```python
def handle_drill_hole_3d(node, ctx) -> dict:
    """在任意 3D 方向钻孔（侧孔、交叉孔）。

    Params: diameter_mm, start_point_mm, direction, depth_mm (or through=True),
            counterbore_diameter_mm, counterbore_depth_mm (optional)
    """
    import cadquery as cq, math
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object

    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p["diameter_mm"])
    if dia <= 0: raise ValueError("diameter_mm must be positive")

    start = (float(p["start_point_mm"][0]), float(p["start_point_mm"][1]), float(p["start_point_mm"][2]))
    direction = (float(p["direction"][0]), float(p["direction"][1]), float(p["direction"][2]))

    d_len = math.sqrt(direction[0]**2 + direction[1]**2 + direction[2]**2)
    if d_len < 1e-9: raise ValueError("direction vector is zero")
    dir_norm = (direction[0]/d_len, direction[1]/d_len, direction[2]/d_len)

    through = p.get("through", False)
    if through:
        bb = body.val().BoundingBox()
        depth = (bb.xlen**2 + bb.ylen**2 + bb.zlen**2) ** 0.5 * 1.5
    else:
        depth = float(p.get("depth_mm", 0))
        if depth <= 0: raise ValueError("depth_mm must be positive")

    # 在原点构建 Z 向圆柱，旋转+平移
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    cyl = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), dia / 2.0, depth
    ).Shape()
    cutter = cq.Solid(cyl)

    z_axis = gp_Dir(0, 0, 1)
    target = gp_Dir(dir_norm[0], dir_norm[1], dir_norm[2])
    if not target.IsEqual(z_axis, 0.001):
        cx = z_axis.Y()*target.Z() - z_axis.Z()*target.Y()
        cy = z_axis.Z()*target.X() - z_axis.X()*target.Z()
        cz = z_axis.X()*target.Y() - z_axis.Y()*target.X()
        angle = math.degrees(math.acos(min(1.0, z_axis.Dot(target))))
        norm = math.sqrt(cx**2 + cy**2 + cz**2)
        if norm > 1e-12:
            cutter = cutter.rotate((0, 0, 0), (cx/norm, cy/norm, cz/norm), angle)

    cutter = cutter.translate(start)

    try:
        result = body.cut(cutter)
    except Exception as e:
        ctx.warnings.append(f"drill_hole_3d cut failed: {e}")
        return {"body": _store_solid(node, ctx, body)}

    # Counterbore
    cb_dia = p.get("counterbore_diameter_mm")
    cb_depth = p.get("counterbore_depth_mm")
    if cb_dia and cb_depth and cb_dia > dia and cb_depth > 0:
        cb_cyl = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), cb_dia / 2.0, cb_depth
        ).Shape()
        cb_cutter = cq.Solid(cb_cyl)
        if not target.IsEqual(z_axis, 0.001):
            cb_cutter = cb_cutter.rotate((0, 0, 0), (cx/norm, cy/norm, cz/norm), angle)
        cb_cutter = cb_cutter.translate(start)
        try:
            result = result.cut(cb_cutter)
        except Exception as e:
            ctx.warnings.append(f"drill_hole_3d counterbore failed: {e}")

    return {"body": _store_solid(node, ctx, result)}
```

同步注册: `dialects/sketch_extrude/dialect.py` 的 `op_specs` 中添加 `drill_hole_3d`。

---

# 12. GeometrySpatialAudit

## 文件：`runtime/spatial_audit.py`

```python
"""Phase C GeometrySpatialAudit — 装配后空间关系验证。"""

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph, GeometrySpatialAuditReport,
    ComponentBBox, PairwiseSpatialMetric, SpatialValidationIssue,
    NumericPlacement,
)


def run_geometry_spatial_audit(
    *, final_handle_id, ctx, spatial_graph, placements
) -> GeometrySpatialAuditReport:
    """装配后空间审计。检查 overlap, Z order, connectivity, solid count, bbox。"""
    issues = []
    final_solid = ctx.object_store.get(final_handle_id)

    # 1. 组件 bbox
    comp_bboxes = _measure_component_bboxes(ctx, placements)

    # 2. Pairwise overlap
    pairwise = []
    for i in range(len(comp_bboxes)):
        for j in range(i + 1, len(comp_bboxes)):
            a, b = comp_bboxes[i], comp_bboxes[j]
            overlap = _bbox_overlap_ratio(a, b)
            dist = _bbox_distance(a, b)
            metric = PairwiseSpatialMetric(
                a=a.component_id, b=b.component_id,
                overlap_ratio_min=overlap, bbox_distance_mm=dist,
                contacts=(dist < 1.0),
            )
            pairwise.append(metric)
            if overlap > 0.8:
                issues.append(SpatialValidationIssue(
                    severity="error", code="spatial_overlap",
                    message=f"{a.component_id} and {b.component_id} overlap > 80%",
                    entities=[a.component_id, b.component_id],
                ))

    # 3. Z order
    _check_z_order(comp_bboxes, issues)

    # 4. Connectivity
    connected = _check_connectivity(pairwise, len(comp_bboxes))
    if len(comp_bboxes) > 1 and not connected:
        issues.append(SpatialValidationIssue(
            severity="error", code="spatial_disconnected",
            message="assembly has disconnected component groups",
        ))

    # 5. Assembly bbox
    asm_bb = _measure_single_bbox(final_solid)
    solid_count = _count_solids(final_solid)

    return GeometrySpatialAuditReport(
        ok=not any(i.severity == "error" for i in issues),
        component_bboxes=comp_bboxes, pairwise_metrics=pairwise,
        issues=issues,
        assembly_bbox_mm=((asm_bb.xlen, asm_bb.ylen, asm_bb.zlen) if asm_bb else None),
        solid_count=solid_count,
        connectivity_graph_connected=connected,
    )


def _bbox_overlap_ratio(a: ComponentBBox, b: ComponentBBox) -> float:
    ix = max(0.0, min(a.xmax, b.xmax) - max(a.xmin, b.xmin))
    iy = max(0.0, min(a.ymax, b.ymax) - max(a.ymin, b.ymin))
    iz = max(0.0, min(a.zmax, b.zmax) - max(a.zmin, b.zmin))
    overlap_vol = ix * iy * iz
    a_vol, b_vol = a.xlen * a.ylen * a.zlen, b.xlen * b.ylen * b.zlen
    if a_vol <= 0 or b_vol <= 0: return 0.0
    return min(overlap_vol / a_vol, overlap_vol / b_vol)


def _bbox_distance(a: ComponentBBox, b: ComponentBBox) -> float:
    dx = max(0.0, max(a.xmin, b.xmin) - min(a.xmax, b.xmax))
    dy = max(0.0, max(a.ymin, b.ymin) - min(a.ymax, b.ymax))
    dz = max(0.0, max(a.zmin, b.zmin) - min(a.zmax, b.zmax))
    return (dx**2 + dy**2 + dz**2) ** 0.5


def _check_z_order(bboxes, issues):
    for bb in bboxes:
        if "top" in bb.component_id.lower():
            for other in bboxes:
                if "bottom" in other.component_id.lower():
                    if bb.zmin <= other.zmax + 1.0:
                        issues.append(SpatialValidationIssue(
                            severity="error", code="spatial_z_order",
                            message=f"top {bb.component_id} (zmin={bb.zmin:.1f}) below bottom {other.component_id} (zmax={other.zmax:.1f})",
                            entities=[bb.component_id, other.component_id],
                        ))


def _check_connectivity(pairwise, count) -> bool:
    if count <= 1: return True
    adj: dict[str, set[str]] = {}
    for pm in pairwise:
        if pm.contacts or pm.bbox_distance_mm < 2.0:
            adj.setdefault(pm.a, set()).add(pm.b)
            adj.setdefault(pm.b, set()).add(pm.a)
    if not adj: return False
    visited = set()
    def dfs(n):
        visited.add(n)
        for nb in adj.get(n, set()):
            if nb not in visited: dfs(nb)
    dfs(list(adj.keys())[0])
    return len(visited) == count


def _measure_component_bboxes(ctx, placements) -> list[ComponentBBox]:
    result = []
    for cid in placements:
        try:
            hid = ctx.resolve_component_output(cid, "body")
            solid = ctx.object_store.get(hid)
            bb = solid.val().BoundingBox() if hasattr(solid, 'val') else solid.BoundingBox()
            result.append(ComponentBBox(
                component_id=cid,
                xmin=bb.xmin, xmax=bb.xmax, ymin=bb.ymin,
                ymax=bb.ymax, zmin=bb.zmin, zmax=bb.zmax,
            ))
        except Exception:
            continue
    return result


def _measure_single_bbox(solid) -> ComponentBBox | None:
    try:
        if hasattr(solid, 'val'): solid = solid.val()
        bb = solid.BoundingBox()
        return ComponentBBox(component_id="assembly", xmin=bb.xmin, xmax=bb.xmax,
                             ymin=bb.ymin, ymax=bb.ymax, zmin=bb.zmin, zmax=bb.zmax)
    except Exception: return None


def _count_solids(solid) -> int | None:
    try:
        if hasattr(solid, 'Solids'): return len(list(solid.Solids()))
        return 1
    except Exception: return None
```

---

# 13. AutoFixer v6 分类系统

在 `authoring/auto_fixer.py` 中新增:

```python
from enum import Enum

class AutoFixCategory(str, Enum):
    SYNTACTIC_ALIAS = "syntactic_alias"
    SCHEMA_DEFAULT = "schema_default"
    CONTEXT_SAFE = "context_safe"
    SEMANTIC_GUESS = "semantic_guess"
    DESTRUCTIVE = "destructive"

# 现有 17 个 fix 函数的分类:
FIX_CATEGORIES = {
    "fix_output_names": AutoFixCategory.SYNTACTIC_ALIAS,
    "fix_input_output_names": AutoFixCategory.SYNTACTIC_ALIAS,
    "fix_op_versions": AutoFixCategory.SCHEMA_DEFAULT,
    "fix_dialect_names": AutoFixCategory.CONTEXT_SAFE,
    "fix_qualified_op_names": AutoFixCategory.SYNTACTIC_ALIAS,
    "fix_param_names": AutoFixCategory.SYNTACTIC_ALIAS,
    "fix_param_values": AutoFixCategory.CONTEXT_SAFE,
    "fix_path_points": AutoFixCategory.SYNTACTIC_ALIAS,
    "fix_unknown_ops": AutoFixCategory.DESTRUCTIVE,      # v6: 默认禁止
    "fix_target_values": AutoFixCategory.SYNTACTIC_ALIAS,
    "fix_cross_component_refs": AutoFixCategory.CONTEXT_SAFE,
    "fix_root_node": AutoFixCategory.CONTEXT_SAFE,
    "fix_phase_names": AutoFixCategory.SCHEMA_DEFAULT,
    "fix_phase_ordering": AutoFixCategory.SCHEMA_DEFAULT,
    "fix_profile_stations": AutoFixCategory.SEMANTIC_GUESS,  # v6: 默认禁止
    "fill_default_params": AutoFixCategory.SCHEMA_DEFAULT,
    "remove_extra_params": AutoFixCategory.CONTEXT_SAFE,
}

DEFAULT_ALLOWED = {
    AutoFixCategory.SYNTACTIC_ALIAS,
    AutoFixCategory.SCHEMA_DEFAULT,
    AutoFixCategory.CONTEXT_SAFE,
}

# 在 auto_fix_with_report() 中增加 category 过滤:
def auto_fix_with_report(raw_doc, dialect_registry=None, *,
                         allowed_categories=DEFAULT_ALLOWED):
    """应用 AutoFix，仅执行 allowed_categories 中的修复。默认禁止 SEMANTIC_GUESS 和 DESTRUCTIVE。"""
    ...
    for fix_name, fix_fn in FIX_FUNCTIONS:
        category = FIX_CATEGORIES.get(fix_name, AutoFixCategory.CONTEXT_SAFE)
        if category not in allowed_categories:
            continue  # skip this fix
        ...  # 其余逻辑不变
```

---

# 14. 实施顺序（修订版 8 Phase）

| Phase | 内容 | 工作量 | 前置依赖 |
|-------|------|--------|----------|
| 0 | **前置研究**: ConstraintResolver 算法 + 手写测试数据验证 | 1-2天 | 无 |
| 1 | Spatial Schema + Question Loop | 3-4天 | Phase 0 |
| 2 | Archetype + ConstraintGraph + Phase A Solver | 3-4天 | Phase 1 |
| 3 | SpatialPipeline 集成 | 3-4天 | Phase 2 |
| 4 | Phase C ConstraintResolver + BBox Tracker | 4-5天 | Phase 0,3 |
| 5 | Composition Placement + raw_assembler | 3-4天 | Phase 4 |
| 6 | GeometrySpatialAudit | 3-4天 | Phase 5 |
| 7 | 几何内核修复 (可并行于 Phase 3-6) | 4-5天 | 无 |
| 8 | AutoFixer v6 + 全量回归 | 2-3天 | Phase 6,7 |

**总计: 26-35 天 (单人全职)**

---

# 15. 关键验收标准

## 空间正确性
- **s11_coupling**: final bbox_z ≈ sum(component z lengths), coaxial
- **s19_workbench**: top > pillar > bottom Z order, left/right distinct
- **s12_reducer_base**: bearings distinct, contact base top

## 几何内核
- **s13_pipe_system**: 竖直 path 不崩溃, pipe volume ≈ πr²·length
- **tm06_spring (≤8 turns)**: 0.80 ≤ volume_ratio ≤ 1.20
- **s05_long_spring (>8 turns)**: 0.65 ≤ ratio ≤ 1.35 or explicit fail (never silent 2%)

## 审计可解释性
每个最终模型输出: 用户事实 / LLM推断 / Archetype假设 / AUTO假设 / Solver派生坐标 / 验证结果 / Audit结果 / Degraded列表

## 不确定性处理
- VERIFIED: 全部约束满足且通过 audit
- ASSUMPTION_BASED: AUTO/archetype 默认, 已记录并通过验证
- NEEDS_CLARIFICATION: 高影响未解决, 不继续静默生成

---

# 16. 禁止实现方式

1. 不得把用户回答拼接成 prompt 让 LLM 重新生成 CAD
2. 不得让 LLM 直接输出 NumericPlacement (必须过 solver)
3. 不得在 validation 失败时删节点
4. 不得把 boolean_union 当 placement
5. 不得让多组件默认 identity (C012 强制)
6. 不得让 spring/pipe 体积严重异常时通过
7. 不得把 AUTO 实现为"跳过提问+完全信任 LLM"
8. 不破坏 primitive/generative CAD 隔离
9. 不引入 part-specific op
10. Archetype 只产生 SpatialRelationDraft, 不生成几何

---

# 17. 新增文件清单 (~26 个新文件, ~3500 行新代码)

```
authoring/spatial/schemas.py             (~450 loc)
authoring/spatial/prompts.py             (~150 loc)
authoring/spatial/tool_schemas.py        (~120 loc)
authoring/spatial/pipeline.py            (~250 loc)
authoring/spatial/question_planner.py    (~120 loc)
authoring/spatial/answer_normalizer.py   (~100 loc)
authoring/spatial/constraint_graph.py    (~200 loc)
authoring/spatial/solver.py              (~180 loc)
authoring/spatial/validators.py          (~120 loc)
authoring/spatial/assumption_ledger.py   (~60 loc)
authoring/spatial/session_state.py       (~50 loc)
authoring/spatial/integration.py         (~180 loc)
authoring/spatial/archetypes/registry.py (~80 loc)
authoring/spatial/archetypes/pillar_support.py    (~100 loc)
authoring/spatial/archetypes/axial_coupling.py    (~80 loc)
authoring/spatial/archetypes/bearing_on_base.py   (~80 loc)
authoring/spatial/archetypes/flanged_connection.py(~80 loc)
runtime/constraint_resolver.py           (~300 loc)
runtime/bbox_tracker.py                  (~60 loc)
runtime/spatial_audit.py                 (~200 loc)
dialects/geometry_utils/ocp_wire.py      (~100 loc)
dialects/geometry_utils/ocp_pipe.py      (~180 loc)
dialects/geometry_utils/boolean_safe.py  (~120 loc)
validation/spatial_contract.py           (~80 loc)

修改文件 (~13 files):
authoring/pipeline.py, authoring/raw_assembler.py,
authoring/auto_fixer.py, authoring/prompt_builders.py,
pipeline/run.py, runtime/context.py,
dialects/composition/params.py, dialects/composition/handlers.py,
dialects/loft_sweep/handlers.py, dialects/sketch_extrude/dialect.py,
dialects/sketch_extrude/handlers.py,
validation/composition.py, validation/pipeline.py
```

---

# 附录 A: 与原文档 llm_skill_base19.md 的关键差异

| 原文档问题 | 本细化版方案 |
|---|---|
| Solver 输出数值 PlacementTransform (尺寸未知) | 约束延迟: Phase A 符号约束 + Phase C 数值求解 |
| Archetype 零定义 | ArchetypeRegistry + 4 个 archetype + 匹配引擎 |
| spatial_contract 存放矛盾 (§3.3.3 vs §11.4) | Sidecar: spatial_contract.json 独立传递 |
| 多轮交互无状态管理 | SpatialSessionState 完整序列化 |
| OCP pipe 仅一行注释 | 完整算法: straight pipe + multi-segment + rotation alignment |
| Helix 分段仅一句话 | 完整实现: 分段构建 + 独立 sweep + fuse + 体积强校验 |
| raw_assembler 集成未定义 | placement 输出到 `__assembly__` scope + 代码 |
| Tool schema factory 缺失 | 4 个 build_*_tool_schema() factory + const 注入 |
| Side drilling 仅参数定义 | 完整 handler: BRepPrimAPI_MakeCylinder + rotation + counterbore |
| 回归策略模糊 | 明确 breaking change 列表 (tm06, s05) |
| AutoFix 分类无现有函数映射 | 17 个 fix 函数逐个分类 + 默认策略 |
| Solver 规则 (S060/S070) 放置错误 | Name heuristic 移至 LLM prompt (Object Graph Extractor) |
| PlaceComponent 兼容性未处理 | backward-compat: translation_mm fallback to position_mm |
| Composition C011-C014 无条件 | 区分 unconditional vs spatial_contract 条件规则 |
| Metadata v3→v4 升级 | 明确 import_gate 兼容性 + 同步更新方案 |

---

# 附录 B: Solver 依赖循环的最终解决方案

```
问题: Solver 需要组件尺寸 → 尺寸在后续阶段产生
方案: 约束延迟两阶段求解

Phase A (无尺寸):
  关系草案 → 符号约束 (SymbolicDimensionRef)
  约束引用 $component_id.axis_edge
  不计算绝对坐标

Phase C (有尺寸):
  真实 bbox 测量 → 代入符号约束
  ConstraintResolver 求解数值 placement
  composition handler 执行实际 placement

流程:
  _run_components()  ← 构建 leaf components, 测量 bbox
       ↓
  ConstraintResolver ← NEW: 符号→数值求解
       ↓
  _run_composition_or_select_final()  ← 执行 placement + boolean_union
       ↓
  GeometrySpatialAudit  ← NEW: 验证空间关系
       ↓
  _export_final_solid()
```

