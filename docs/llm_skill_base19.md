# SeekFlow Generative CAD v6 工程实施文档

## Interactive Spatial Intent + Robust Geometry Kernel + Auditable CAD Compiler

版本：v6.0 Engineering Design
目标仓库：`WYZAAACCC/seekflow-engineering`
目标目录：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/`
目标链路：非 primitive Text-to-CAD，即 Generative CAD IR 链路
读者：Claude Code / CAD 编译器开发者 / 几何内核工程师

---

# 0. 总目标

当前 SeekFlow Generative CAD 已经具备：

```text
Natural Language Prompt
→ RoutePlan
→ FeatureSequenceDraft
→ NodeParamsDraft
→ RawGcadDocument
→ AutoFixer
→ Validation
→ Canonical IR
→ Runtime
→ STEP
```

但当前系统仍有三个根本问题：

1. 生成模型的空间布局经常不符合用户真实意图。
2. 复杂零件的几何内核执行不够稳定，尤其是 sweep、helix、side hole、fillet/chamfer、shell、multi-body composition。
3. 当前审核与自动修复更多关注 JSON/schema/graph，不足以审计机械空间关系、用户假设、LLM 自动决策和几何语义。

v6 的目标不是简单“增强 prompt”，而是在现有 staged authoring 架构前后增加一套可审计、可求解、可验证的人-LLM-代码协同 CAD 编译层：

```text
User Prompt
→ RoutePlan
→ MechanicalObjectGraphDraft
→ SpatialPlanDraft
→ ClarificationLoop
→ SpatialConstraintGraph
→ DeterministicSpatialSolver
→ SpatialValidation
→ FeatureSequenceDraft
→ NodeParamsDraft
→ RawGcadDocument
→ AutoFixer
→ Validation
→ Canonical IR
→ Runtime
→ GeometrySpatialAudit
→ Repair / Ask / Accept
→ STEP / SolidWorks
```

核心原则：

```text
LLM 不做 CAD compiler。
LLM 不做最终 spatial solver。
LLM 只抽取机械意图、候选关系、假设、不确定性。
代码负责结构化约束求解、几何验证、失败反证。
人只回答少数高影响问题，不手写完整 CAD 坐标。
“你自己看着办”不是跳过验证，而是允许系统在假设审计和几何验证约束下自动决策。
```

---

# 1. v6 设计原则

## 1.1 不再让 LLM 直接决定最终空间坐标

错误方向：

```text
User prompt → LLM 直接输出所有组件坐标 → 生成 CAD
```

正确方向：

```text
User prompt
→ LLM 抽取组件、功能、候选机械关系
→ 代码把关系转成约束
→ solver 计算坐标
→ validator 验证关系是否满足
```

LLM 可以输出：

```json
{
  "relation": "pillar_left and pillar_right are symmetric supports between top_plate and bottom_plate",
  "confidence": 0.74,
  "source": "mechanical archetype and component names"
}
```

但最终坐标应由 solver 根据 plate 尺寸、pillar 高度、接触关系、对称关系推导。

## 1.2 只问用户高影响问题

不要让用户写完整 prompt 或 CAD 坐标。系统应自动识别：

* 高影响 + 高不确定 + 低回答成本的问题，问用户。
* 低风险问题，系统默认。
* 代码可推导问题，代码求解。
* 不重要美学问题，默认处理。

示例：

```text
应该问：
- 工作台是两根立柱还是四角立柱？
- hub_a / spider / hub_b 是轴向串联还是同心重叠？
- 侧孔在 +X/-X 面还是 +Y/-Y 面？

不应该问：
- fillet 1mm 还是 2mm？
- 孔边距 28mm 还是 30mm？
- 默认坐标系是否 X/Y/Z？
```

## 1.3 “你自己看着办”必须受控

`AUTO` 选项不是让 LLM 随便生成，而是：

```text
AUTO = 允许系统选择最常见机械布局
       + 必须记录 assumption
       + 必须生成至少一个可验证 SpatialConstraintGraph
       + 必须通过空间验证
       + 验证失败必须 repair 或继续 ask
```

## 1.4 boolean_union 不是装配约束

v6 必须强制：

```text
boolean_union 只表示几何融合。
boolean_union 不表示 place、mate、coaxial、contact、flush、offset。
多组件 assembly 中，任何 component root body 在进入 boolean_union 前必须已被 place/translate/rotate，或明确声明 identity placement 合法。
```

## 1.5 几何成功不等于 CAD 语义成功

STEP 生成成功只说明几何内核输出了实体，不说明：

* top 在 bottom 上方；
* left/right 不重叠；
* hub_a/spider/hub_b 正确串联；
* pipe branch 真正连接 main pipe；
* hole 在正确 face 上；
* shell open face 正确；
* feature 数量与位置符合用户意图。

v6 必须新增 GeometrySpatialAudit。

---

# 2. 新目录结构

在现有目录下新增：

```text
seekflow_engineering_tools/generative_cad/
  authoring/
    spatial/
      __init__.py
      schemas.py
      prompts.py
      pipeline.py
      object_graph.py
      ambiguity.py
      question_planner.py
      answer_normalizer.py
      constraint_graph.py
      solver.py
      validators.py
      archetypes.py
      assumption_ledger.py
      reports.py
      integration.py

  validation/
    spatial.py
    placement.py
    contact.py
    overlap.py

  runtime/
    spatial_audit.py
    geometry_measure.py
    contact_measure.py
    bbox.py
    feature_audit.py

  dialects/
    geometry_utils/
      __init__.py
      ocp_wire.py
      ocp_pipe.py
      frames.py
      boolean_safe.py
      bbox.py
      measurements.py

  repair/
    spatial_repair.py

  tests/
    generative_cad/
      test_spatial_object_graph.py
      test_spatial_question_planner.py
      test_spatial_solver.py
      test_spatial_validator.py
      test_spatial_integration_workbench.py
      test_spatial_integration_coupling.py
      test_geometry_kernel_sweep.py
      test_geometry_kernel_helix.py
      test_geometry_kernel_side_drilling.py
      test_geometry_spatial_audit.py
```

---

# 3. 新增 IR：MechanicalObjectGraphDraft

## 3.1 文件

```text
authoring/spatial/schemas.py
```

## 3.2 Pydantic 模型

实现以下模型，全部 `extra="forbid"`。

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpatialMode(str, Enum):
    GUIDED = "guided"
    AUTO_CONSERVATIVE = "auto_conservative"
    AUTO_MECHANICAL = "auto_mechanical"
    AUTO_COMPLEX_VERIFIED = "auto_complex_verified"
    PRECISION = "precision"


class AxisName(str, Enum):
    X = "X"
    Y = "Y"
    Z = "Z"


class SourceKind(str, Enum):
    USER_EXPLICIT = "user_explicit"
    USER_SELECTED_OPTION = "user_selected_option"
    LLM_INFERRED = "llm_inferred"
    ARCHETYPE_DEFAULT = "archetype_default"
    SYSTEM_DEFAULT = "system_default"
    SOLVER_DERIVED = "solver_derived"


class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class ComponentRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    display_name: str = ""
    role: str
    kind_hint: str = ""
    primary_dialect_hint: str | None = None
    known_dimensions_mm: dict[str, float] = Field(default_factory=dict)
    source_text: str = ""
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))


class LocalFrameDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    origin_semantics: Literal[
        "center",
        "center_bottom",
        "center_top",
        "axis_front",
        "axis_midpoint",
        "mounting_face_center",
        "unknown",
    ] = "unknown"
    x_axis_semantics: str = "global_X"
    y_axis_semantics: str = "global_Y"
    z_axis_semantics: str = "global_Z"
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))


class SpatialRelationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_id: str
    type: Literal[
        "above",
        "below",
        "left_of",
        "right_of",
        "front_of",
        "behind",
        "between",
        "coaxial",
        "concentric",
        "parallel",
        "perpendicular",
        "symmetric_pair",
        "face_contact",
        "flush",
        "offset",
        "clearance",
        "centered_on",
        "inside",
        "surrounds",
        "supports",
        "attached_to",
    ]
    entities: list[str]
    value_mm: float | None = None
    direction: str | None = None
    source: SourceKind = SourceKind.LLM_INFERRED
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=0.5))
    rationale: str = ""


class SpatialUnknown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unknown_id: str
    kind: Literal[
        "component_count",
        "relative_placement",
        "axis_direction",
        "face_selection",
        "contact_relation",
        "spacing",
        "symmetry",
        "assembly_vs_fused",
        "feature_location",
        "port_direction",
    ]
    entities: list[str]
    question_hint: str
    impact: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    answer_cost: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class MechanicalObjectGraphDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: SpatialMode = SpatialMode.GUIDED
    global_frame_assumption: str = "X=left-right, Y=front-back, Z=bottom-top, units=mm"
    components: list[ComponentRole] = Field(default_factory=list)
    local_frames: list[LocalFrameDraft] = Field(default_factory=list)
    candidate_relations: list[SpatialRelationDraft] = Field(default_factory=list)
    unknowns: list[SpatialUnknown] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_components_unique(self):
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component_id values must be unique")
        return self
```

## 3.3 要求

Claude Code 必须：

1. 使用 Pydantic v2。
2. 所有 schema 严格 `extra="forbid"`。
3. 不把这些 spatial schema 混入 RawGcadDocument。
4. Spatial IR 是 authoring-time IR，不是最终 CAD runtime IR。
5. 所有 LLM 输出必须能够被 `model_validate`。

---

# 4. 新增 IR：SpatialQuestion / Clarification

## 4.1 模型

继续在 `authoring/spatial/schemas.py` 添加：

```python
class SpatialQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str
    label: str
    description: str = ""
    recommended: bool = False
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
    options: list[SpatialQuestionOption]
    allow_custom: bool = True
    allow_auto: bool = True


class UserSpatialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    mode: Literal["option", "custom", "auto"]
    selected_option_id: str | None = None
    custom_text: str | None = None
    auto_level: Literal[
        "auto_conservative",
        "auto_mechanical",
        "auto_complex_verified",
    ] | None = None


class NormalizedSpatialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    source_answer: UserSpatialAnswer
    relations_added: list[SpatialRelationDraft] = Field(default_factory=list)
    assumptions_added: list[str] = Field(default_factory=list)
    requires_replanning: bool = False
```

## 4.2 交互要求

系统向用户展示问题时，必须包含：

```text
- 为什么问；
- 不回答可能导致什么 CAD 错误；
- 推荐选项；
- “你自己看着办”选项；
- “人工输入”选项；
- 每个选项的几何后果。
```

---

# 5. 新增 IR：SpatialConstraintGraph

## 5.1 模型

```python
class PlacementTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    source: SourceKind = SourceKind.SOLVER_DERIVED
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=1.0))
    assumptions: list[str] = Field(default_factory=list)


class SpatialConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint_id: str
    type: SpatialRelationDraft.model_fields["type"].annotation
    entities: list[str]
    value_mm: float | None = None
    direction: str | None = None
    source: SourceKind
    required: bool = True
    tolerance_mm: float = 0.5
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=1.0))


class SpatialConstraintGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    components: list[ComponentRole]
    local_frames: list[LocalFrameDraft]
    constraints: list[SpatialConstraint]
    placements: list[PlacementTransform] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    expected_bbox_mm: tuple[float, float, float] | None = None
    expected_body_count: int | None = None
```

---

# 6. 新增 AssumptionLedger

## 6.1 文件

```text
authoring/spatial/assumption_ledger.py
```

## 6.2 模型

```python
class AssumptionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumption_id: str
    statement: str
    source: SourceKind
    confidence: float = Field(ge=0.0, le=1.0)
    user_delegated: bool = False
    user_confirmed: bool = False
    validation_status: Literal["not_checked", "pass", "fail", "warning"] = "not_checked"
    evidence: list[str] = Field(default_factory=list)


class AssumptionLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[AssumptionEntry] = Field(default_factory=list)

    def add(self, entry: AssumptionEntry) -> None:
        self.entries.append(entry)

    def high_risk_unconfirmed(self) -> list[AssumptionEntry]:
        return [
            e for e in self.entries
            if e.confidence < 0.65 and not e.user_confirmed and e.validation_status != "pass"
        ]
```

## 6.3 要求

每个自动推断的空间关系必须进入 ledger。

---

# 7. Prompt 系统改造

## 7.1 新增文件

```text
authoring/spatial/prompts.py
```

## 7.2 Prompt 1：Object Graph Extractor

实现常量：

```python
OBJECT_GRAPH_SYSTEM_PROMPT = """
You are a mechanical CAD spatial-intent extractor for a deterministic CAD compiler.

You do not generate CAD code.
You do not generate RawGcadDocument.
You do not generate final numeric placements unless explicitly provided by the user.
You only extract:
- mechanical components,
- functional roles,
- known dimensions,
- likely spatial relations,
- local frame assumptions,
- high-impact unknowns.

You must distinguish:
1. USER_EXPLICIT facts: directly stated by the user.
2. LLM_INFERRED facts: inferred from mechanical convention or component names.
3. ARCHETYPE_DEFAULT facts: default mechanical layout for a known archetype.
4. SYSTEM_DEFAULT facts: coordinate system or harmless defaults.

Use millimeters.
Assume global frame: X=left-right, Y=front-back, Z=bottom-top unless user says otherwise.

Do not hide uncertainty.
If relative placement, contact, axis direction, face selection, symmetry, or component count is unclear, emit SpatialUnknown.
For each unknown, estimate:
- impact: how badly the CAD model changes if wrong;
- uncertainty: how unclear the prompt is;
- answer_cost: how hard it is for the user to answer.

Never convert uncertainty into silent coordinates.
Return only strict tool arguments.
"""
```

## 7.3 Prompt 2：Spatial Plan / Relation Builder

```python
SPATIAL_PLAN_SYSTEM_PROMPT = """
You are a mechanical spatial planner for a CAD compiler.

You receive:
- the original user request,
- the MechanicalObjectGraphDraft,
- any user answers,
- available component dimensions,
- available dialect capabilities.

Your task is to emit a SpatialConstraintGraph draft:
- qualitative relations,
- required constraints,
- assumptions,
- expected assembly-level measurements.

Important rules:
- boolean_union is not placement.
- multi-component assemblies require explicit placement constraints before boolean_union.
- left/right, front/back, top/bottom names imply distinct non-overlapping placements unless explicitly overridden.
- supported components must contact their supports.
- coaxial mechanical parts must have explicit coaxial constraints.
- stacked parts must have face_contact or offset constraints.
- if a component is intended to connect to another, emit contact/attached_to constraints.
- if unsure, do not invent final coordinates; emit unresolved unknowns.

You may infer conventional mechanical layouts only when:
- the user selected AUTO, or
- the relation has high confidence from the archetype,
- and the assumption is recorded.

Return only strict tool arguments.
"""
```

## 7.4 Prompt 3：Question Planner

```python
QUESTION_PLANNER_SYSTEM_PROMPT = """
You are a clarification question planner for an interactive CAD system.

Your goal is to ask the fewest questions needed to avoid major spatial CAD errors.

Generate questions only for high-priority unknowns:
priority = impact * uncertainty * user_visible_error / max(answer_cost, 0.1)

Do not ask questions that code can solve deterministically.
Do not ask low-impact aesthetic questions.
Do not ask for full coordinates unless necessary.

Every question must include:
- why it matters,
- recommended option,
- at least two concrete choices when possible,
- CUSTOM option,
- AUTO option.

AUTO means:
the system chooses a conventional mechanical layout,
records all assumptions,
runs spatial validation,
and asks again if validation fails.

Prefer multiple-choice questions over free text.
Return only strict tool arguments.
"""
```

## 7.5 Prompt 4：Answer Normalizer

```python
ANSWER_NORMALIZER_SYSTEM_PROMPT = """
You normalize a user's clarification answer into SpatialRelationDraft constraints.

Input:
- the original SpatialQuestion,
- the user's answer,
- current MechanicalObjectGraphDraft,
- current SpatialConstraintGraph.

Do not generate CAD code.
Do not generate RawGcadDocument.
Do not add unrelated design intent.
Convert the answer into:
- relations_added,
- assumptions_added,
- whether feature replanning is required.

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

## 7.6 Prompt 5：Feature Sequence Prompt 增强

修改现有 `FEATURE_SEQUENCE_SYSTEM_PROMPT`，加入以下段落：

```text
Spatial contract rules:
- A SpatialConstraintGraph may already define component placements and relations.
- Do not override solved placements.
- Do not assume identity placement for distinct components unless the spatial contract explicitly allows it.
- For multi-component assemblies, emit composition transform/placement operations before boolean_union.
- boolean_union is geometry fusion only; it is not placement, mate, contact, or alignment.
- If the spatial contract says two components are coaxial, preserve that alignment in feature planning.
- If the spatial contract says a component is on top of or attached to another, plan features so its local frame can be placed accordingly.
- Do not create leaf features using composition boolean_union.
```

## 7.7 Prompt 6：Node Params Prompt 增强

修改现有 `NODE_PARAMS_SYSTEM_PROMPT`，加入：

```text
Spatial parameter rules:
- When a placement transform is provided by SpatialConstraintGraph, use exactly that transform.
- Do not use [0,0,0] for multiple distinct assembly components unless identity placement is explicitly permitted.
- For holes, ports, ribs, bosses, and pockets, respect the selected face, axis, and local frame.
- If the schema cannot express the required face/axis relation, emit assumptions and choose the safest representable approximation.
- Do not silently collapse left/right, front/back, top/bottom parts into the same location.
```

## 7.8 Prompt 7：Repair Prompt 增强

修改现有 `REPAIR_SYSTEM_PROMPT`，加入：

```text
Spatial repair rules:
You may repair spatial layout only when the validation report explicitly identifies:
- component overlap,
- missing placement,
- failed contact,
- failed symmetry,
- failed coaxial alignment,
- expected bbox mismatch,
- floating or disconnected component.

Do not invent a new mechanical design.
Prefer repairs that satisfy existing SpatialConstraintGraph.
If multiple incompatible spatial repairs are possible, give up and request clarification.
```

---

# 8. SpatialPipeline 集成现有 AuthoringPipeline

## 8.1 文件

```text
authoring/spatial/pipeline.py
```

## 8.2 新入口

实现：

```python
def run_spatial_authoring_frontend(
    *,
    user_request: str,
    llm_config,
    dialect_registry,
    base_package_registry,
    object_graph_caller=None,
    spatial_plan_caller=None,
    question_caller=None,
    answer_normalizer_caller=None,
    user_answers: list[UserSpatialAnswer] | None = None,
    mode: SpatialMode = SpatialMode.GUIDED,
    question_budget: int = 3,
) -> SpatialFrontendResult:
    ...
```

## 8.3 Result 模型

```python
class SpatialFrontendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    needs_clarification: bool = False
    questions: list[SpatialQuestion] = Field(default_factory=list)
    object_graph: MechanicalObjectGraphDraft | None = None
    constraint_graph: SpatialConstraintGraph | None = None
    solver_report: SpatialSolverReport | None = None
    validation_report: SpatialValidationReport | None = None
    assumption_ledger: AssumptionLedger = Field(default_factory=AssumptionLedger)
    failures: list[str] = Field(default_factory=list)
```

## 8.4 现有 `generate_gcad_from_user_request` 改造

在 `authoring/pipeline.py` 中新增参数：

```python
enable_spatial_frontend: bool = True
spatial_mode: SpatialMode = SpatialMode.GUIDED
spatial_user_answers: list[UserSpatialAnswer] | None = None
question_budget: int = 3
```

流程改为：

```text
Stage 0: Spatial frontend
  - object graph
  - spatial plan
  - question generation
  - answer normalization
  - constraint solve
  - spatial validation

Stage 1: RoutePlan
Stage 2: Context
Stage 3: FeatureSequenceDraft, with spatial_context injected
Stage 4: NodeParamsDraft, with solved placements injected
Stage 5: RawAssembly
...
```

如果 `SpatialFrontendResult.needs_clarification=True`，则不要继续生成 CAD，返回问题给上层 UI。

## 8.5 User prompt builder 修改

`build_feature_sequence_user_prompt` 增加：

```python
spatial_context: dict | None = None
```

拼入：

```text
SPATIAL CONTRACT:
<compact JSON of SpatialConstraintGraph placements/constraints>

ASSUMPTION LEDGER:
<compact JSON of assumptions>

You must preserve this spatial contract.
```

`build_node_params_user_prompt` 同理。

---

# 9. Spatial Solver

## 9.1 文件

```text
authoring/spatial/solver.py
```

## 9.2 Solver 报告

```python
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
    placements: list[PlacementTransform] = Field(default_factory=list)
    expected_bbox_mm: tuple[float, float, float] | None = None
    issues: list[SpatialSolverIssue] = Field(default_factory=list)
```

## 9.3 Solver v1 支持规则

必须实现以下 deterministic 规则：

### Rule S001：default global frame

若未指定坐标系：

```text
X=left-right
Y=front-back
Z=bottom-top
units=mm
```

### Rule S010：face_contact Z stacking

若：

```text
A above B
A.bottom face_contact B.top
```

则：

```text
A.zmin = B.zmax + offset
```

### Rule S020：between axial chain

若：

```text
middle between left/right along Z
face_contact left.inner middle.left
face_contact middle.right right.inner
```

则按长度串联：

```text
left.zmin = 0
left.zmax = left.length
middle.zmin = left.zmax
middle.zmax = middle.zmin + middle.length
right.zmin = middle.zmax
right.zmax = right.zmin + right.length
```

### Rule S030：symmetric_pair

若：

```text
symmetric_pair(A, B, plane="YZ")
```

则：

```text
A.x = -d/2
B.x = +d/2
A.y = B.y
A.z = B.z
```

若用户未给 `d`，按 parent bbox 或 default spacing 推导：

```text
d = parent_width * 0.65
```

没有 parent 时：

```text
d = max(A_width, B_width) * 3.0
```

必须记录 assumption。

### Rule S040：coaxial

若：

```text
coaxial(A.axis, B.axis)
```

则对齐 axis origin 的横向坐标，默认 Z 轴同轴：

```text
A.x = B.x
A.y = B.y
```

如果 axis 是 X/Y，则按对应轴处理。

### Rule S050：on_top_of / supports

若：

```text
support supports upper
support on_top_of lower
```

则：

```text
support.bottom = lower.top
upper.bottom = support.top
```

### Rule S060：left/right name heuristic

当 component id 包含 `_left` / `_right`，且没有显式 placement：

```text
add symmetric_pair(left, right, YZ)
```

该规则只在 AUTO 或 GUIDED 且 confidence >= 0.65 时启用。否则生成 question。

### Rule S070：top/bottom name heuristic

当 component id 包含 `top` / `bottom`：

```text
top above bottom
```

若中间有 support，则 top 与 support face_contact。

### Rule S080：assembly identity placement ban

多组件 assembly 中，如果两个以上 component placement 是 identity，且无 explicit identity relation，报 error。

---

# 10. Spatial Validator

## 10.1 文件

```text
authoring/spatial/validators.py
```

## 10.2 报告模型

```python
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
```

## 10.3 必须实现的 validator

### V001：unplaced multi-component body

```text
if non_assembly_component_count > 1:
    every component must have explicit PlacementTransform
```

未放置时报 error：

```text
code="spatial_unplaced_component"
```

### V002：identity collapse

```text
if two distinct components have identical transform and no allow_identity_overlap:
    error
```

### V003：left/right collapse

```text
if names imply left/right and placed bbox overlap ratio > 0.8:
    error
```

### V004：top/bottom order

```text
if top.zmin <= bottom.zmax and no nesting relation:
    error
```

### V005：face_contact distance

检查 expected contact 的两 bbox 面距离：

```text
abs(A.face - B.face) <= tolerance
```

否则 error。

### V006：coaxial alignment

检查 axis 横向距离：

```text
distance <= tolerance
```

否则 error。

### V007：expected bbox

如果 `expected_bbox_mm` 存在，检查 solved bbox 与 expected bbox 的相对误差：

```text
abs(actual - expected) / max(expected, 1) <= 0.05
```

否则 warning 或 error。assembly 主尺寸 error，小特征 warning。

### V008：disconnected assembly graph

建立 contact/attached/union connectivity graph。若存在多个 disconnected components 且最终要求 single solid，error。

### V009：boolean_union before placement

在 RawGcadDocument 或 FeatureSequenceDraft 中检查：

```text
boolean_union input component root body must be placed or marked identity_ok
```

否则 error。

---

# 11. 将 SpatialConstraintGraph 编译到现有 composition ops

## 11.1 文件

```text
authoring/spatial/integration.py
```

## 11.2 功能

实现：

```python
def inject_placements_into_feature_sequence(
    feature_sequence: FeatureSequenceDraft,
    spatial_graph: SpatialConstraintGraph,
) -> FeatureSequenceDraft:
    ...
```

## 11.3 规则

1. 如果 assembly 存在多个 non-assembly components，则确保 `__assembly__` component 存在。
2. 对每个 non-assembly component root body，在进入 boolean_union 前生成 placement node。
3. placement node 优先使用现有 `composition.place_component`；如果该 op 不适合，则使用 `translate_solid` + `rotate_solid`。
4. placement node 的 `expected_input_source` 指向对应 component root。
5. boolean_union 消费 placed solid，而不是原始 component root solid。
6. 多组件 union 必须 pairwise 展开或保留由 raw_assembler 展开。
7. synthetic placement nodes 必须写入 `system_filled_fields` 或新增 `spatial_filled_fields`。

## 11.4 新字段建议

如果不想改 RawGcadDocument schema，placement 可通过现有 composition ops 表达。

如果允许改 RawGcadDocument，可在顶层增加可选 metadata：

```json
"spatial_contract": {
  "constraint_graph_hash": "...",
  "assumption_ledger_hash": "...",
  "solver_report_hash": "..."
}
```

该字段必须是 metadata，不参与 runtime 几何。

---

# 12. composition dialect 改造

## 12.1 params 修改

文件：

```text
dialects/composition/params.py
```

现有 `place_component` 如果只有 `position_mm`，需要增强为：

```python
class PlaceComponentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    placement_source: Literal[
        "user_explicit",
        "user_selected_option",
        "auto_assumption",
        "solver_derived",
    ] = "solver_derived"
    identity_ok: bool = False
```

为了兼容旧数据，可在 AutoFixer 中把旧 `position_mm` 转为 `translation_mm`。

## 12.2 handler 要求

文件：

```text
dialects/composition/handlers.py
```

必须确保：

1. `place_component` 从 input solid 复制/变换，不修改原对象。
2. rotation 按 XYZ Euler 顺序实现，角度为度。
3. translate 在 rotation 后执行。
4. 记录 operation_metrics：

```json
{
  "node_id": "...",
  "op": "place_component",
  "translation_mm": [x,y,z],
  "rotation_deg_xyz": [rx,ry,rz]
}
```

5. 对 identity transform：

```text
if identity and identity_ok is False:
    warning or error depending validation mode
```

---

# 13. GeometrySpatialAudit

## 13.1 文件

```text
runtime/spatial_audit.py
```

## 13.2 数据模型

```python
class ComponentBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float

    @property
    def xlen(self): ...
    @property
    def ylen(self): ...
    @property
    def zlen(self): ...


class PairwiseSpatialMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    overlap_volume_mm3: float
    overlap_ratio_min: float
    bbox_distance_mm: float
    contacts: bool


class GeometrySpatialAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    component_bboxes: list[ComponentBBox]
    pairwise_metrics: list[PairwiseSpatialMetric]
    issues: list[SpatialValidationIssue]
```

## 13.3 审计内容

必须检查：

1. 每个 component root solid 的 bbox。
2. 每个 placed component 的 bbox。
3. pairwise overlap ratio。
4. pairwise bbox distance。
5. contact graph connectivity。
6. left/right symmetry。
7. top/bottom order。
8. expected assembly bbox。
9. final solid count/body count。
10. degraded features 是否导致语义失败。

## 13.4 集成位置

在 `pipeline/run.py` 中：

```text
_run_components
_run_composition_or_select_final
validate_runtime_postconditions
run_geometry_spatial_audit
_export_final_solid
```

如果 `spatial_contract` 存在，audit 失败应使 run result 失败，除非 severity 仅 warning。

---

# 14. 几何内核改造总方案

v6 不仅要解决空间规划，还必须修几何内核。以下是强制实施项。

---

## 14.1 loft_sweep：彻底修复 3D sweep

### 问题

现有 sweep 如果仍依赖 `Workplane("XY").moveTo/lineTo/spline`，会丢失或错误处理 3D path，尤其是纯竖直路径、强空间弯管、多段管路。

### 文件

```text
dialects/geometry_utils/ocp_wire.py
dialects/geometry_utils/ocp_pipe.py
dialects/loft_sweep/handlers.py
```

### 实现

`ocp_wire.py`：

```python
def make_3d_polyline_wire(points: list[tuple[float, float, float]]):
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    wb = BRepBuilderAPI_MakeWire()
    for p0, p1 in zip(points[:-1], points[1:]):
        edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*p0), gp_Pnt(*p1)).Edge()
        wb.Add(edge)
    if not wb.IsDone():
        raise RuntimeError("failed to build 3D polyline wire")
    return wb.Wire()
```

`ocp_pipe.py`：

```python
def make_circular_pipe_along_wire(wire, radius_mm: float):
    # Build profile face perpendicular to start tangent.
    # Use BRepOffsetAPI_MakePipe.
    # Return cadquery Solid or Workplane-compatible object.
```

### fast path

For pure vertical pipe:

```python
if len(points) == 2 and x0 == x1 and y0 == y1:
    return cq.Workplane("XY").center(x0, y0).circle(radius).extrude(z1-z0).translate((0,0,z0))
```

For pure X/Y straight pipe, create cylinder along correct axis using rotation.

### 验收

新增测试：

```text
test_sweep_vertical_path_main_pipe
test_sweep_3d_polyline_preserves_z
test_sweep_pipe_volume_matches_length_area
test_s13_pipe_system_no_BRep_API_command_not_done
```

---

## 14.2 helix_sweep：分段 OCP MakePipe + 体积强校验

### 问题

长弹簧 OCP MakePipe 可能失败，CadQuery fallback 会产生 2%-5% 体积假实体。

### 改造

文件：

```text
dialects/loft_sweep/handlers.py
dialects/geometry_utils/ocp_pipe.py
```

新增策略：

```text
if turns <= 8:
    try one-shot OCP MakePipe
else:
    split into segments of max 3 turns
    sweep each segment
    boolean fuse segments
    validate volume
```

### 体积校验

无论 strict_semantic 是否 true，只要 ratio < 0.55 或 > 1.65：

```text
default behavior: fail runtime
optional compatibility: allow degraded only if node.degradation_policy == may_skip_with_warning
```

不要默认让体积 2% 的 spring 通过。

### 验收

```text
tm06_spring volume ratio 0.8~1.2
s05_long_spring either passes ratio 0.65~1.35 or fails explicitly, never silently passes 2%
```

---

## 14.3 side drilling / valve port 支持

### 问题

多端口阀块、侧孔、交叉孔无法用简单 top-face `cut_hole` 表达。

### 新 op

在 `sketch_extrude` 或新 dialect `machining` 中新增：

```text
drill_hole_3d
drill_port
```

推荐先放在 `sketch_extrude`，避免大迁移。

### Params

```python
class DrillHole3DParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diameter_mm: float = Field(gt=0)
    start_point_mm: tuple[float, float, float]
    direction: tuple[float, float, float]
    depth_mm: float = Field(gt=0)
    through: bool = False
    counterbore_diameter_mm: float | None = None
    counterbore_depth_mm: float | None = None
    thread: str | None = None
```

### Handler

1. Normalize direction vector.
2. Build cylinder along arbitrary 3D axis.
3. Cut from body.
4. If counterbore provided, cut larger shallow cylinder.
5. Record thread as metadata/degraded feature if not geometrically modeled.

### 验收

```text
side port on +X face cuts into block along -X
side port on +Y face cuts into block along -Y
cross holes intersect inside valve body
hole center outside target face fails preflight
```

---

## 14.4 rib / boss 三维位置修复

### 问题

`add_rib`、`add_boss` 等特征如果 schema 有 3D position，handler 必须完整尊重。

### 要求

1. `position_mm` 必须完整使用 x/y/z。
2. `direction` 必须表达真实 3D 方向或有限枚举。
3. rib 不得悬空，必须接触 base body。
4. rib 生成后必须与 base union，并检查体积增加。

### 新 preflight

```text
rib_base_contact_required
boss_base_contact_required
```

---

## 14.5 fillet/chamfer 稳定化

### 问题

复杂模型 fillet/chamfer 容易失败，当前可降级，但需要更可控。

### 改造

新增 `dialects/geometry_utils/boolean_safe.py`：

```python
def try_fillet_edges(body, radius, selector_policy):
    # attempt selected edges
    # fallback smaller radius
    # fallback skip
    # record degraded feature
```

策略：

1. Edge selection 不要全局 `.edges().fillet()`。
2. 支持 selector policy：

   * `all_safe_outer_edges`
   * `vertical_edges`
   * `top_edges`
   * `bottom_edges`
   * `by_bounding_box_zone`
3. 半径 fallback：

   * requested r
   * 0.5r
   * 0.25r
   * skip with degraded feature
4. 如果 feature 是 required，skip 应 fail。

---

## 14.6 shell_housing 增强

### 要求

1. `shell_body` 必须支持 `open_faces`，不能被 AutoFixer 删除。
2. 如果 CadQuery 面选择无法稳定表达，则用 bbox-based face selector：

   * `+Z`
   * `-Z`
   * `+X`
   * `-X`
   * `+Y`
   * `-Y`
3. shell 后检查：

   * volume reduced but positive；
   * bbox unchanged within tolerance；
   * wall thickness feasible；
   * if open face specified, body is not fully closed in semantic audit.

---

# 15. AutoFixer v6 改造

## 15.1 原则

AutoFixer 只能做确定性、低风险修复。不能为了通过 validation 而改变设计意图。

## 15.2 分类

新增 rule category：

```python
class AutoFixCategory(str, Enum):
    SYNTACTIC_ALIAS = "syntactic_alias"
    SCHEMA_DEFAULT = "schema_default"
    CONTEXT_SAFE = "context_safe"
    SEMANTIC_GUESS = "semantic_guess"
    DESTRUCTIVE = "destructive"
```

默认允许：

```text
SYNTACTIC_ALIAS
SCHEMA_DEFAULT
CONTEXT_SAFE
```

默认禁止：

```text
SEMANTIC_GUESS
DESTRUCTIVE
```

除非显式配置：

```python
AutoFixPolicy(allow_semantic_guess=True, allow_destructive=False)
```

## 15.3 禁止事项

1. 不得删除 `open_faces`。
2. 不得删除 unknown op 使 validation 通过；应转 repair 或 fail。
3. 不得自动把外螺纹等级改成内螺纹等级。
4. 不得补充关键设计尺寸，例如凭空补 revolve profile station。
5. 不得把缺失空间 placement 自动设为 identity。

## 15.4 必须新增审计字段

```json
{
  "rule_id": "...",
  "category": "context_safe",
  "path": "...",
  "old": "...",
  "new": "...",
  "confidence": 0.95,
  "design_intent_risk": "low",
  "requires_user_review": false
}
```

## 15.5 空间 AutoFix

允许的空间修复：

```text
- old position_mm → translation_mm
- x/y/z alias → translation_mm
- identity placement with explicit identity_ok
```

禁止的空间修复：

```text
- 自动把 left/right 分开，除非 SpatialConstraintGraph 已经要求 symmetric_pair
- 自动改变 top/bottom Z 顺序，除非 solver 已经给出 placement
```

---

# 16. Validation v6 改造

## 16.1 新 stage

在 `validation/pipeline.py` 中 raw stages 后新增：

```python
("spatial_contract", validate_spatial_contract_if_present)
```

canonical stages 后新增：

```python
("canonical_spatial", validate_canonical_spatial_if_present)
```

不要破坏旧路径。如果 raw 没有 spatial metadata，则跳过。

## 16.2 composition validator 增强

新增规则：

### C011：multi-component requires placement

```text
multiple non-assembly components require placement before boolean_union
```

### C012：identity placement must be explicit

```text
identity transform is legal only if identity_ok=True or single component
```

### C013：component names imply distinct placement

```text
left/right or a/b repeated components must not consume same unplaced root body
```

### C014：composition transform before union

```text
assembly boolean_union inputs should be transform outputs, not raw component roots, when spatial_contract exists
```

---

# 17. Runtime v6 改造

## 17.1 Metadata

`metadata_v3` 升级为 `metadata_v4` 或扩展 metadata：

```json
{
  "spatial": {
    "constraint_graph_hash": "...",
    "assumption_ledger": [...],
    "solver_report": {...},
    "spatial_validation": {...},
    "geometry_spatial_audit": {...}
  }
}
```

## 17.2 Run result

`GcadRunResult` 增加：

```python
spatial_audit: dict | None = None
semantic_postcheck: dict | None = None
```

## 17.3 Failure policy

如果 spatial_contract 存在：

```text
geometry_spatial_audit error => run failed
geometry_spatial_audit warning => run ok with warnings
```

---

# 18. 人-LLM-代码交互系统

## 18.1 模式

支持四种模式：

```text
guided:
  默认。最多问 3 个高价值问题。

auto_conservative:
  尽量少问，采用保守布局，复杂度较低。

auto_mechanical:
  “你自己看着办”。采用常见机械布局，必须记录假设和验证。

auto_complex_verified:
  尝试复杂一点，生成多个候选，代码验证后选择。

precision:
  尽可能问清楚，适合专家用户。
```

## 18.2 UI / CLI 协议

当需要 clarification，返回：

```json
{
  "needs_clarification": true,
  "questions": [
    {
      "question_id": "q_001",
      "question_text": "...",
      "why_it_matters": "...",
      "options": [
        {"option_id": "A", "label": "...", "recommended": true},
        {"option_id": "B", "label": "..."},
        {"option_id": "CUSTOM", "label": "人工输入"},
        {"option_id": "AUTO", "label": "你自己看着办"}
      ]
    }
  ]
}
```

用户回答：

```json
{
  "question_id": "q_001",
  "mode": "option",
  "selected_option_id": "A"
}
```

或：

```json
{
  "question_id": "q_001",
  "mode": "auto",
  "auto_level": "auto_mechanical"
}
```

或：

```json
{
  "question_id": "q_001",
  "mode": "custom",
  "custom_text": "两根立柱左右对称，中心距 360mm"
}
```

---

# 19. 典型 case 目标行为

## 19.1 s19_workbench

输入：

```text
top_plate, bottom_plate, pillar_left, pillar_right
```

v6 应问：

```text
两根柱子如何布置？
A. 左右对称，推荐
B. 前后对称
C. 四角支撑
D. 人工输入
E. 你自己看着办
```

若用户选 AUTO，系统应：

```text
assumption: 两根立柱左右对称支撑上下板
bottom_plate z=0..20
pillar z=20..220
top_plate z=220..245
expected bbox z≈245
```

验证：

```text
pillar_left/right overlap < 0.1
pillar top contacts top_plate bottom
pillar bottom contacts bottom_plate top
actual bbox z≈245
```

## 19.2 s11_coupling

应问：

```text
hub_a/spider/hub_b 是：
A. 轴向串联，推荐
B. 同心重叠
C. 人工输入
D. 你自己看着办
```

AUTO 选择 A。

验证：

```text
coaxial pass
hub_a.zmax == spider.zmin
spider.zmax == hub_b.zmin
final bbox_z == sum(lengths)
```

## 19.3 s12_reducer_base

应问或推断：

```text
bearing_a/bearing_b 是左右对称安装在 base 上。
```

如 prompt 未给中心距，AUTO 下：

```text
center_distance = base_length * 0.55~0.65
```

必须记录 assumption。

验证：

```text
bearing_a/bearing_b distinct
bearing bases contact base top
same shaft axis height
```

## 19.4 s13_pipe_system

不应因竖直 path 崩溃。应使用 3D wire / vertical cylinder fast path。

验证：

```text
main pipe bbox z covers 300..500
branch endpoints contact main pipe
pipe union connected
```

---

# 20. 测试计划

## 20.1 Unit tests

```text
test_object_graph_detects_components
test_object_graph_detects_left_right_unknown
test_question_planner_prioritizes_high_impact
test_auto_option_records_assumption
test_solver_stacks_top_pillar_bottom
test_solver_axial_coupling_chain
test_validator_detects_identity_collapse
test_validator_detects_left_right_overlap
test_validator_detects_missing_contact
test_validator_passes_workbench_layout
```

## 20.2 Geometry kernel tests

```text
test_vertical_sweep_pipe
test_horizontal_sweep_pipe
test_3d_polyline_sweep_pipe
test_helix_8_turn_volume_ratio
test_helix_15_turn_segmented_volume_ratio_or_fail_closed
test_side_drill_x_axis
test_side_drill_y_axis
test_shell_open_top_face
test_fillet_fallback_records_degraded
```

## 20.3 Integration tests

```text
test_s11_coupling_guided_auto
test_s12_reducer_base_auto_mechanical
test_s19_workbench_question_answer_A
test_s19_workbench_auto_mechanical
test_s20_ultimate_spatial_audit
test_s13_pipe_system_runtime_no_crash
```

## 20.4 Regression policy

旧 v5 通过 case 必须仍能通过，除非 v6 正确发现原来模型空间语义错误。
若 v6 拒绝旧 case，必须有明确 spatial issue，例如：

```text
spatial_identity_collapse
spatial_unplaced_component
spatial_expected_bbox_mismatch
```

---

# 21. Claude Code 实施顺序

## Phase 1：基础 spatial schema 与 question loop

实现：

```text
authoring/spatial/schemas.py
authoring/spatial/prompts.py
authoring/spatial/question_planner.py
authoring/spatial/assumption_ledger.py
```

测试：

```text
test_spatial_object_graph.py
test_spatial_question_planner.py
```

验收：

```text
能从 s19/s11 prompt 生成高价值问题。
问题包含 AUTO/CUSTOM。
```

## Phase 2：solver + validator

实现：

```text
authoring/spatial/constraint_graph.py
authoring/spatial/solver.py
authoring/spatial/validators.py
```

测试：

```text
test_spatial_solver.py
test_spatial_validator.py
```

验收：

```text
能解 workbench、coupling、reducer_base 的 placement。
能检测 identity collapse。
```

## Phase 3：集成 authoring pipeline

修改：

```text
authoring/pipeline.py
authoring/prompt_builders.py
authoring/tool_schemas.py
```

新增：

```text
authoring/spatial/integration.py
authoring/spatial/pipeline.py
```

验收：

```text
enable_spatial_frontend=True 时，FeatureSequencePrompt 包含 SPATIAL CONTRACT。
若需要 clarification，则不继续生成 CAD。
若 AUTO，则生成 assumptions + placements。
```

## Phase 4：composition placement 支持

修改：

```text
dialects/composition/params.py
dialects/composition/handlers.py
validation/composition.py
```

验收：

```text
多组件 assembly 中 boolean_union 消费 placed solids。
identity unplaced components 被拒绝。
```

## Phase 5：GeometrySpatialAudit

实现：

```text
runtime/bbox.py
runtime/geometry_measure.py
runtime/contact_measure.py
runtime/spatial_audit.py
```

修改：

```text
pipeline/run.py
pipeline/metadata_v3.py 或新增 metadata_v4.py
```

验收：

```text
s11 原点堆叠会失败。
s19 原点堆叠会失败。
正确放置后通过。
```

## Phase 6：几何内核修复

实现：

```text
dialects/geometry_utils/ocp_wire.py
dialects/geometry_utils/ocp_pipe.py
dialects/geometry_utils/boolean_safe.py
```

修改：

```text
loft_sweep/handlers.py
sketch_extrude/handlers.py
axisymmetric/handlers.py
shell_housing/dialect.py or handlers
```

验收：

```text
s13 竖直 sweep 不崩。
tm06 spring volume 正常。
s05 long spring 不允许 2% volume 假通过。
side drilling works.
```

## Phase 7：AutoFixer v6

修改：

```text
authoring/auto_fixer.py
```

新增：

```text
authoring/autofix_policy.py
```

验收：

```text
open_faces 不被删除。
unknown op 不被静默删除。
thread_class context-aware。
semantic_guess 默认禁止。
```

---

# 22. Build / run 示例

## 22.1 Guided 模式

```python
result = generate_gcad_from_user_request(
    user_request=prompt,
    llm_config=llm_config,
    dialect_registry=dialect_registry,
    base_package_registry=base_package_registry,
    enable_spatial_frontend=True,
    spatial_mode=SpatialMode.GUIDED,
    question_budget=3,
)
```

若：

```python
result.spatial_frontend.needs_clarification
```

上层展示问题。

## 22.2 用户回答后继续

```python
answers = [
    UserSpatialAnswer(
        question_id="q_001",
        mode="option",
        selected_option_id="A",
    )
]

result = generate_gcad_from_user_request(
    user_request=prompt,
    ...,
    enable_spatial_frontend=True,
    spatial_user_answers=answers,
)
```

## 22.3 AUTO 模式

```python
result = generate_gcad_from_user_request(
    user_request=prompt,
    ...,
    enable_spatial_frontend=True,
    spatial_mode=SpatialMode.AUTO_MECHANICAL,
)
```

---

# 23. 关键验收标准

v6 完成后，必须满足：

## 23.1 空间正确性

```text
s11_coupling:
  final bbox_z 接近 hub_a + spider + hub_b 的轴向总长。
  hub_a/spider/hub_b 同轴且不完全重叠。

s19_workbench:
  top_plate 在 pillar 上方。
  pillar_left/right 不重叠。
  top/bottom/pillar 接触关系满足。
  bbox_z 接近 bottom_thickness + pillar_height + top_thickness。

s12_reducer_base:
  bearing_a/bearing_b 不重叠。
  bearing 安装在 base 上。
```

## 23.2 几何内核

```text
s13_pipe_system:
  不因纯竖直 path 崩溃。

tm06_spring:
  volume ratio 合理。

s05_long_spring:
  不允许体积 2% 的假 solid 被当成成功。
```

## 23.3 审计可解释性

每个最终模型必须能输出：

```text
- 用户显式事实；
- LLM 推断；
- AUTO 假设；
- 用户确认；
- solver 派生坐标；
- spatial validation 结果；
- geometry spatial audit 结果；
- degraded feature 列表。
```

## 23.4 不确定性处理

系统必须有三种最终状态：

```text
VERIFIED:
  用户确认或代码验证满足全部关键空间关系。

ASSUMPTION_BASED:
  使用 AUTO 或 archetype 默认假设，已记录并通过验证。

NEEDS_CLARIFICATION:
  存在高影响未解决不确定性，不继续静默生成。
```

---

# 24. 禁止实现方式

Claude Code 不得采用以下捷径：

1. 不得把用户回答拼接成更长自然语言 prompt 后直接让 LLM 重新生成 CAD。
2. 不得让 LLM 直接输出最终坐标而不经过 solver/validator。
3. 不得在 validation 失败时删除节点使其通过。
4. 不得把 boolean_union 当 placement。
5. 不得让多个 distinct components 默认 identity transform 并通过。
6. 不得让 spring/pipe 体积严重异常但 STEP 合法时通过。
7. 不得把 AUTO 实现为“跳过提问并完全相信 LLM”。
8. 不得破坏 primitive 与 generative CAD 链路隔离。
9. 不得引入 part-specific operation，例如 `make_flange`、`make_bracket`、`make_workbench`。
10. 可以引入 archetype relation defaults，但它们只能产生关系约束，不能直接生成专用零件几何。

---

# 25. 最终架构定义

v6 的本质是：

```text
Interactive Spatial Intent Resolution
+ Deterministic CAD Spatial Constraint Solving
+ Robust Geometry Runtime
+ Auditable AutoFix/Repair
+ Semantic and Spatial Postcheck
```

不是：

```text
更长 prompt
更强 LLM
更多一次性 JSON
```

v6 必须让系统从：

```text
“生成了一个合法 STEP”
```

升级为：

```text
“生成了一个满足已知机械空间约束、关键假设可追溯、几何内核结果可验证的 CAD 模型”
```

---

# 26. 交付物清单

Claude Code 完成后应提供：

```text
1. 新增/修改文件列表
2. Spatial schema 单元测试结果
3. Solver/validator 测试结果
4. Geometry kernel 测试结果
5. v51_full35_output 关键 case 回归报告
6. 新 metadata 示例
7. s11/s12/s19/s13/tm06/s05 对比报告
8. Assumption ledger 示例
9. GeometrySpatialAudit 示例
10. 未完成能力与后续 TODO
```

---

# 27. 最重要的工程判断

这次改造的最高优先级不是让 LLM 更“聪明”，而是让系统更“诚实”。

系统必须做到：

```text
知道哪些是用户说的。
知道哪些是 LLM 猜的。
知道哪些是 AUTO 授权的。
知道哪些是 solver 推导的。
知道哪些被几何验证证明了。
知道哪些仍然不确定。
知道什么时候不该继续生成。
```

这就是工业级 Text-to-CAD 与玩具级 Text-to-STEP 的分界线。
