# SeekFlow Generative CAD Dialect Compiler 架构改进实施文档

版本：v1.0
目标读者：Claude Code / 工程实现 Agent
适用范围：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad`
目标：在不推翻现有 Raw IR、Canonical IR、Dialect Registry、OperationSpec、Executor、RuntimeContext、STEP artifact pipeline 的前提下，把当前 dialect 层从 L1 语法驱动 CAD 操作编译器升级为具备语义事实传播、几何可行性分析、规划优化、结构化恢复与导出质量控制的 CAD compiler middle-end。

---

# 1. 总原则

本项目不是重写 generative CAD 系统。

本项目要做的是在现有 pipeline 中插入一个保守、可关闭、可测试、可回滚的 compiler middle-end。

当前系统已经有这些必须保留的资产：

```text
RawGcadDocument
CanonicalGcadDocument
DialectRegistry / default_registry
OperationSpec
execute_operation
RuntimeContext
RuntimeObjectStore
GeometryRuntime / CadQueryRuntime
ValidationBundle
MetadataProofV3
CanonicalStepArtifact
STEP export
```

严禁做以下破坏性操作：

```text
不要替换 RawGcadDocument
不要让 LLM 直接输出 Python/CadQuery
不要让 LLM 直接输出 STEP
不要删除现有 dialect
不要删除现有 OperationSpec.handler
不要跳过 validate_and_canonicalize_with_bundle
不要跳过 runtime_postconditions
不要破坏 current STEP export
不要把 NX/SolidWorks 接入作为第一阶段目标
不要一次性实现真正工业级 persistent topology naming
不要把所有 handler 重写为新 backend
```

本次升级的核心策略：

```text
保留前端：
  Raw IR → validation → canonicalize → Canonical IR

新增中端 sidecar：
  Canonical IR → CompilerModule → ShapeFacts → Semantic checks → Plan hints → Execution policy

保留后端：
  现有 dialect.run_component / execute_operation / CadQuery handlers 继续工作

逐步增强：
  facts、health、recovery、planner、feature trace 都以可选字段和 sidecar 形式加入
```

---

# 2. 当前架构核实结论

## 2.1 当前 Raw IR 是正确资产，不应推翻

`RawGcadDocument` 是 LLM 唯一允许输出的结构化格式。它有：

```text
schema_version
document_id
part_name
units
trust_level
selected_dialects
components
nodes
constraints
safety
llm_validation_hints
```

`RawNode` 有：

```text
id
component
dialect
op
op_version
phase
inputs
outputs
params
required
degradation_policy
```

这个设计是正确的。它已经把 LLM 从不可验证文本约束到结构化 IR。

结论：

```text
Raw IR 继续保留。
第一阶段不要改 Raw schema。
所有新语义表达都必须先放进 node.params，由各 op 的 params_model 解析。
```

---

## 2.2 当前 Canonical IR 是可扩展资产，但语义密度不足

`CanonicalNode` 当前已有：

```text
inputs: list[CanonicalValueRef]
outputs: list[CanonicalValueDecl]
params
typed_params
required
degradation_policy
operation_effects
postconditions
```

这足够作为 middle-end 输入。

但 `CanonicalValueRef` 只能表达：

```text
producer_node / producer_component
output
resolved_type
```

它不能表达：

```text
component.body.faces.top
component.body.bbox.xlen
feature.created_faces.inner_cylindrical
body.radius_max - margin
face center + uv offset
```

结论：

```text
不要直接替换 CanonicalValueRef。
新增 sidecar RefPath / DimExpr / PlacementExpr。
第一阶段不要要求 CanonicalNode.inputs 支持属性路径。
只允许新表达式出现在 typed_params 中。
```

---

## 2.3 当前 ValueType 是名义类型，不足以支撑复杂几何

当前 ValueType 包含：

```text
solid
solid_array
frame
plane
point
curve
profile
sketch
face_set
edge_set
component_ref
```

这只能做浅层类型检查。

它不能表达：

```text
closed_profile
open_profile
manifold_solid
closed_solid
planar_face
cylindrical_face
bbox_dim
distance
angle
datum_axis
topology_ref
```

结论：

```text
不要直接替换 ValueType。
新增 SemanticType sidecar。
旧 ValueType 继续用于现有 typecheck 和 runtime handle ABI。
SemanticType 用于新增 semantic_typecheck pass。
```

---

## 2.4 当前 OperationSpec 是核心 ABI，应扩展而非替换

当前 OperationSpec 已有：

```text
dialect
op
op_version
phase
input_types
output_types
params_model
effects
required_context
postconditions
handler
handler_kind
summary / usage_notes / common_mistakes / examples / anti_examples / llm_param_hints
```

这是非常好的 compiler operation descriptor。

结论：

```text
保留 OperationSpec。
第一阶段不要修改 OperationSpec 构造参数，避免大量 dialect 同步修改。
新增 OperationSemanticSpec registry，用 op key 旁路关联 semantic rule / fact rule / recovery rule。
第二阶段再考虑把 semantic 字段并回 OperationSpec。
```

---

## 2.5 当前 executor 是正确执行入口，但 geometry validation 太弱

`execute_operation` 已经统一处理：

```text
handler 调用
legacy dict 适配 OperationResult
输出名校验
输出类型校验
handle 存在性校验
handle value_type 校验
warnings / degraded_features / metrics 传播
solid geometry validation
```

问题：

```text
geometry error 现在主要 append 到 ctx.warnings
没有累积 GeometryHealth
没有事务 rollback
没有按 required/degradation_policy 统一恢复策略
handler 内部仍存在 warn + return original body 的模式
```

结论：

```text
保留 execute_operation。
新增 execute_operation_v3 不合适，风险太大。
应在 execute_operation 内部最小增强：
  1. geometry health sidecar
  2. required feature degraded detection
  3. operation result health metrics
  4. 不改变现有返回类型 ExecutedNode
```

---

## 2.6 当前 geometry_preflight 方向正确，但不应继续手写扩张

当前 `validate_geometry_preflight` 做：

```text
max_nodes
max_boolean_ops
max_profile_points
per-dialect preflight_component
```

`axisymmetric.preflight_component` 已经做了实际有价值的 envelope tracking，例如：

```text
profile_max_radius
profile_min_radius
center_bore_radius
hole outer edge
hole inner edge
min/max PCD
```

这是正确方向。

问题：

```text
envelope 只在 axisymmetric 内部可见
变量名硬编码
不能跨 dialect
不能作为后续 planner 输入
不能被 executor/runtime 复用
```

结论：

```text
新增 ShapeFacts pass。
第一阶段不要删除任何 dialect.preflight_component。
geometry_preflight 先继续调用旧 preflight。
ShapeFacts 作为额外 canonical stage 运行，默认 warning-only。
当 ShapeFacts 稳定后，再把部分手写 preflight 迁移进去。
```

---

## 2.7 当前 RuntimeContext 已经有 sidecar 插槽，适合渐进增强

`RuntimeContext` 已经有：

```text
object_store
geometry_runtime
tolerance
cache
node_outputs
component_outputs
warnings
degraded_features
operation_metrics
spatial_placements
spatial_audit_report
spatial_contract_hash
placed_component_bboxes
strict_geometry_semantics
```

结论：

```text
不要新建全局运行时。
扩展 RuntimeContext 是合理的。
新增字段必须有 default_factory 或默认值。
不得改变构造函数必填参数。
```

建议新增字段：

```python
compiler_facts: dict[str, Any] = field(default_factory=dict)
feature_traces: list[dict[str, Any]] = field(default_factory=list)
geometry_health: dict[str, Any] = field(default_factory=dict)
planning_report: dict[str, Any] | None = None
```

---

# 3. 本次升级的真实价值判断

下面逐项审查之前提出的方案，判断是否值得做、是否兼容、是否会提升边界。

## 3.1 SemanticType

判断：值得做，但必须 sidecar 化。

真实价值：

```text
可以在不破坏 ValueType 的情况下表达 solid 的 closed/manifold/body_count/bbox 等附加语义。
可以让 cut/shell/fillet/chamfer 等高级操作在执行前得到更强校验。
可以逐步替代 shallow typecheck。
```

风险：

```text
如果直接替换 ValueType，会破坏所有 dialect spec 和 runtime handles。
如果要求 LLM 输出 SemanticType，会扩大 prompt 面和失败率。
```

落地方式：

```text
新增 ir/semantic.py
不要修改 ir/values.py
不要修改 RawValueDecl.type
不要修改 OperationSpec.input_types/output_types
新增 analysis/semantic_specs.py，把 semantic rule 与现有 op key 绑定
```

结论：

```text
做，但不改旧 ABI。
```

---

## 3.2 DimExpr / PlacementExpr / RefPath

判断：值得做，但第一阶段只允许进入 params，不进入 graph edge。

真实价值：

```text
解决“LLM 必须猜死坐标”的问题。
让参数可以表达 bbox、radius、offset、distance 等派生尺寸。
让 cut_hole、slot、boss、rib 等高级特征共享 placement 模型。
```

风险：

```text
如果让 CanonicalValueRef 直接支持属性路径，会影响 canonicalize、typecheck、graph、hash、repair hints。
如果表达式求值不严格，可能引入 NaN、单位混乱、循环引用。
```

落地方式：

```text
新增 ir/expr.py
DimExpr 只支持有限白名单 op
RefPath 第一阶段只允许 root 为 node/component + output + property
不允许任意 Python expression
不允许字符串 eval
不允许递归自引用
表达式求值失败时 fail-closed
```

结论：

```text
做，但必须有严格 JSON schema 和 evaluator。
```

---

## 3.3 ShapeFacts

判断：最高优先级，最能拓宽几何边界。

真实价值：

```text
把 axisymmetric 手写 envelope tracking 升级成通用事实传播。
为 pattern、boolean、shell、fillet、placement 提供静态几何依据。
为 planner 提供成本与风险输入。
```

风险：

```text
如果要求 ShapeFacts 精确等于真实 B-Rep，会不现实。
如果一开始跨所有 dialect 精确传播，会实现过大。
```

落地方式：

```text
ShapeFacts 第一阶段只做 conservative facts。
facts 可以 unknown。
unknown 不等于 error。
只有明确违反安全边界才 error。
facts source 必须记录 derived_from node id。
```

结论：

```text
必须做，先从 axisymmetric revolve_profile/cut_center_bore/cut_circular_hole_pattern 做样板。
```

---

## 3.4 Feature IR / CAD SSA

判断：有价值，但不能第一阶段重写执行流。

真实价值：

```text
可以建立特征树、rollback、topology delta、incremental rebuild 的基础。
```

风险：

```text
如果把所有 handler 改成生成 Feature IR 再 lowering，会导致大重构。
当前 dialect.run_component 已经能工作，不应替换。
```

落地方式：

```text
第一阶段做 FeatureTrace，不做 FeatureIR executor。
FeatureTrace 是运行时记录，不参与执行。
等 ShapeFacts 和 Health 稳定后，再升级为 PlannedFeature。
```

结论：

```text
先做 trace，不做 full Feature IR。
```

---

## 3.5 Topology Naming

判断：必要，但第一阶段只能做弱拓扑命名。

真实价值：

```text
改善 chamfer/fillet/hole-on-face/shell-opening 的稳定性。
```

风险：

```text
工业级 persistent topology naming 是大工程。
在 OCC/CadQuery 上强行保证 persistent naming 会失败。
```

落地方式：

```text
第一阶段做 TopologySelector + TopologyFingerprint。
不要承诺永久稳定。
selector 基于 bbox extreme、normal、area rank、surface type、centroid。
用于 runtime selection 和 diagnostics。
```

结论：

```text
做弱版本，不叫 persistent naming，叫 topology selection facts。
```

---

## 3.6 Planner / Optimizer

判断：值得做，但第一阶段只做 analysis + hints，不做自动改写。

真实价值：

```text
HolePatternFusion、BooleanBatching、FilletChamferLatePass 可以显著提升复杂模型成功率。
```

风险：

```text
如果自动重排节点，会破坏当前 phase_order、root_node、component output 语义。
布尔顺序改变可能改变几何结果。
```

落地方式：

```text
第一阶段 Planner 只输出 PlanningReport：
  should_batch_holes
  risky_boolean_sequence
  fillet_too_early
  pattern_instance_too_high
  suggested_phase_order

不自动改写 Canonical IR。
第二阶段对明确等价的 pattern fusion 做 opt-in rewrite。
```

结论：

```text
先做 planner report，不做自动 rewrite。
```

---

## 3.7 Structured Recovery

判断：必须做，但应先收敛 handler 私自降级。

真实价值：

```text
required feature 失败不能静默返回原 body。
optional feature 可降级，但必须统一记录。
```

风险：

```text
如果直接引入 transaction rollback，会触及所有 handler。
```

落地方式：

```text
第一阶段：
  executor 检查 result.degraded_features
  handler 若 required node 返回原 body，必须通过 metrics/health 暴露
  新增 lint/test 捕捉 required handler swallow failure

第二阶段：
  RecoveryPolicy sidecar
  optional retry/degrade 归 executor 管
```

结论：

```text
先做检测与约束，再做恢复策略。
```

---

## 3.8 GeometryHealth

判断：高价值，低破坏，优先做。

真实价值：

```text
比 warning list 更适合判断复杂几何是否还能继续。
可以阻止坏 B-Rep 进入 STEP。
可以为 repair prompt 提供定量信息。
```

风险：

```text
如果过度依赖 OCC 检测，在缺少 OCP 环境时测试会脆弱。
```

落地方式：

```text
best-effort health model。
OCP 不可用时 health.status = unknown，不 fail。
只在明确检测到 invalid closed solid / missing volume / body count mismatch 时 fail。
```

结论：

```text
必须做。
```

---

## 3.9 Backend Lowering

判断：方向正确，但不是当前第一阶段。

真实价值：

```text
未来接 OCP/NX/SolidWorks 必须需要 backend abstraction。
```

风险：

```text
现在已有 GeometryRuntime 只覆盖 export/inspect，不覆盖建模操作。
若此阶段强拆 handler，改动面过大。
```

落地方式：

```text
第一阶段不要拆 handler。
先扩展 GeometryRuntime inspection/export。
新增 BackendOp 仅作为规划数据结构，不参与执行。
```

结论：

```text
延后到 Phase 4。
```

---

# 4. 推荐目标架构：GCAD Compiler Middle-End v0.3

新增中端不替代现有 pipeline，而是插入在 canonical validation 与 runtime execution 之间。

当前：

```text
Raw
  → validate_and_canonicalize_with_bundle
  → Canonical
  → run_canonical_gcad
  → _run_components
  → _run_composition_or_select_final
  → runtime_postconditions
  → export_step
```

升级后：

```text
Raw
  → validate_and_canonicalize_with_bundle
  → Canonical
  → build_compiler_module
  → semantic_analysis
  → fact_propagation
  → geometry_feasibility
  → planning_analysis
  → run_canonical_gcad
  → _run_components
  → runtime health collection
  → runtime_postconditions
  → pre_export_health_gate
  → export_step
  → metadata with compiler reports
```

关键要求：

```text
middle-end 默认不修改 CanonicalGcadDocument。
middle-end 产物放入 CompilerModule。
CompilerModule 报告写入 validation 或 metadata extra diagnostics。
若 middle-end disabled，旧系统必须完全按原路径工作。
```

---

# 5. 新增模块清单

新增目录：

```text
generative_cad/
  compiler/
    __init__.py
    module.py
    pass_manager.py
    reports.py
    config.py

  ir/
    expr.py
    semantic.py

  analysis/
    __init__.py
    semantic_specs.py
    facts.py
    fact_rules.py
    fact_propagation.py
    expr_eval.py
    feasibility.py
    topology_selectors.py

  planning/
    __init__.py
    planner.py
    planning_report.py
    risk_model.py

  runtime/
    health.py
```

尽量不要修改：

```text
ir/raw.py
ir/values.py
dialects/base.py
existing params.py
existing handler signatures
```

允许小幅修改：

```text
ir/canonical.py
runtime/context.py
dialects/executor.py
validation/pipeline.py
pipeline/run.py
pipeline/metadata_v3.py
```

---

# 6. 数据模型规格

## 6.1 `ir/expr.py`

实现严格 JSON-safe expression model。

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


DimOp = Literal[
    "const",
    "ref",
    "add",
    "sub",
    "mul",
    "div",
    "min",
    "max",
    "abs",
    "clamp",
]


class RefPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_kind: Literal["node", "component"]
    root_id: str
    output: str = "body"
    path: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_path(self):
        if not self.root_id.strip():
            raise ValueError("RefPath.root_id must be non-empty")
        for item in self.path:
            if not item or not item.replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"unsafe RefPath path segment: {item!r}")
        return self


class DimExpr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dim_expr"] = "dim_expr"
    op: DimOp
    args: list[Any] = Field(default_factory=list)
    unit: Literal["mm", "deg", "unitless"] = "mm"

    @model_validator(mode="after")
    def validate_args(self):
        if self.op == "const":
            if len(self.args) != 1 or not isinstance(self.args[0], (int, float)):
                raise ValueError("const DimExpr requires one numeric arg")
        if self.op == "ref":
            if len(self.args) != 1:
                raise ValueError("ref DimExpr requires one RefPath-like arg")
        if self.op in ("add", "sub", "mul", "div", "min", "max") and len(self.args) < 2:
            raise ValueError(f"{self.op} DimExpr requires at least 2 args")
        if self.op == "abs" and len(self.args) != 1:
            raise ValueError("abs DimExpr requires one arg")
        if self.op == "clamp" and len(self.args) != 3:
            raise ValueError("clamp DimExpr requires value, min, max")
        return self
```

实现约束：

```text
禁止 eval
禁止 Python expression string
禁止 function name 动态调度
禁止任意属性访问
递归深度默认最大 16
除法分母接近 0 时 fail-closed
结果必须 finite
```

---

## 6.2 `ir/semantic.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class SemanticType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "solid",
        "solid_array",
        "frame",
        "plane",
        "point",
        "curve",
        "profile",
        "sketch",
        "face",
        "edge",
        "datum",
        "dimension",
    ]
    traits: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)


class FaceSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: dict
    role: Literal[
        "top",
        "bottom",
        "front",
        "back",
        "left",
        "right",
        "outer_cylindrical",
        "inner_cylindrical",
        "largest_planar",
        "all",
    ] | None = None
    normal_hint: tuple[float, float, float] | None = None
    area_rank: int | None = None


class PlacementExpr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["placement_expr"] = "placement_expr"
    face: FaceSelector
    origin: Literal["center", "centroid", "datum", "uv"] = "center"
    u: float | dict = 0.0
    v: float | dict = 0.0
    direction: Literal["face_normal", "reverse_face_normal"] = "face_normal"
```

第一阶段不要强制任何现有 op 使用 `PlacementExpr`。

---

## 6.3 `analysis/facts.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class NumericFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None = None
    expr: dict | None = None
    confidence: Literal["exact", "conservative", "measured", "unknown"] = "unknown"
    source_node: str | None = None


class BBoxFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    xlen_mm: NumericFact = Field(default_factory=NumericFact)
    ylen_mm: NumericFact = Field(default_factory=NumericFact)
    zlen_mm: NumericFact = Field(default_factory=NumericFact)
    xmin_mm: NumericFact = Field(default_factory=NumericFact)
    xmax_mm: NumericFact = Field(default_factory=NumericFact)
    ymin_mm: NumericFact = Field(default_factory=NumericFact)
    ymax_mm: NumericFact = Field(default_factory=NumericFact)
    zmin_mm: NumericFact = Field(default_factory=NumericFact)
    zmax_mm: NumericFact = Field(default_factory=NumericFact)


class FaceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    surface_type: Literal["plane", "cylinder", "cone", "sphere", "unknown"] = "unknown"
    normal: tuple[float, float, float] | None = None
    axis: tuple[float, float, float] | None = None
    area_mm2: NumericFact = Field(default_factory=NumericFact)
    selector: dict[str, Any] = Field(default_factory=dict)
    source_node: str | None = None


class ShapeFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_id: str
    value_type: str
    component_id: str
    producer_node: str | None = None

    bbox: BBoxFacts = Field(default_factory=BBoxFacts)
    radius_min_mm: NumericFact = Field(default_factory=NumericFact)
    radius_max_mm: NumericFact = Field(default_factory=NumericFact)
    length_z_mm: NumericFact = Field(default_factory=NumericFact)
    volume_mm3: NumericFact = Field(default_factory=NumericFact)

    traits: list[str] = Field(default_factory=list)
    faces: dict[str, FaceFact] = Field(default_factory=dict)
    derived_from: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FactStore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_value_id: dict[str, ShapeFacts] = Field(default_factory=dict)
    by_node_output: dict[str, str] = Field(default_factory=dict)

    def bind(self, node_id: str, output_name: str, facts: ShapeFacts) -> None:
        key = f"{node_id}.{output_name}"
        self.by_node_output[key] = facts.value_id
        self.by_value_id[facts.value_id] = facts

    def get_node_output(self, node_id: str, output_name: str) -> ShapeFacts | None:
        fid = self.by_node_output.get(f"{node_id}.{output_name}")
        if not fid:
            return None
        return self.by_value_id.get(fid)
```

---

# 7. CompilerModule 与 PassManager

## 7.1 `compiler/module.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.analysis.facts import FactStore


@dataclass
class CompilerModule:
    canonical: CanonicalGcadDocument
    facts: FactStore = field(default_factory=FactStore)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    planning_report: dict[str, Any] = field(default_factory=dict)
    feature_trace_plan: list[dict[str, Any]] = field(default_factory=list)
    enabled_passes: list[str] = field(default_factory=list)

    def add_issue(
        self,
        *,
        stage: str,
        code: str,
        message: str,
        severity: str = "warning",
        node_id: str | None = None,
        component_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.diagnostics.append({
            "stage": stage,
            "code": code,
            "message": message,
            "severity": severity,
            "node_id": node_id,
            "component_id": component_id,
            "details": details or {},
        })

    @property
    def ok(self) -> bool:
        return not any(i.get("severity") == "error" for i in self.diagnostics)
```

---

## 7.2 `compiler/pass_manager.py`

第一阶段不要做复杂依赖图调度，保持简单稳定。

```python
from __future__ import annotations

from typing import Protocol
from seekflow_engineering_tools.generative_cad.compiler.module import CompilerModule


class CompilerPass(Protocol):
    name: str

    def run(self, module: CompilerModule) -> CompilerModule:
        ...


def run_compiler_passes(module: CompilerModule, passes: list[CompilerPass]) -> CompilerModule:
    for p in passes:
        module.enabled_passes.append(p.name)
        try:
            module = p.run(module)
        except Exception as exc:
            module.add_issue(
                stage=p.name,
                code="compiler_pass_exception",
                message=f"{p.name} failed: {exc}",
                severity="error",
            )
            return module
    return module
```

---

# 8. Fact Propagation 第一阶段规则

第一阶段只实现这些 op 的 fact rule：

```text
axisymmetric.revolve_profile
axisymmetric.cut_center_bore
axisymmetric.cut_circular_hole_pattern
axisymmetric.cut_annular_groove
composition.translate_solid
composition.rotate_solid
composition.boolean_union
composition.boolean_cut
```

## 8.1 `axisymmetric.revolve_profile`

输入：

```text
profile_stations: list[{r_mm, z_front_mm, z_rear_mm}]
```

输出 facts：

```text
radius_max_mm = max(r_mm)
radius_min_mm = min(r_mm)
zmin = min(z_front_mm)
zmax = max(z_rear_mm)
length_z_mm = zmax - zmin
bbox.xlen = 2 * radius_max
bbox.ylen = 2 * radius_max
bbox.zlen = length_z
traits += ["closed_candidate", "axisymmetric", "z_axis"]
faces:
  front: plane near zmin
  rear: plane near zmax
  outer_cylindrical: cylinder radius radius_max
```

## 8.2 `axisymmetric.cut_center_bore`

读取 input solid facts。

参数：

```text
diameter_mm
```

校验：

```text
diameter_mm > 0
diameter_mm / 2 < input.radius_max_mm - min_wall_margin_mm
```

输出 facts：

```text
copy input facts
add note center_bore_radius_mm = diameter / 2
faces.inner_cylindrical = cylinder radius diameter/2
```

事实存储中可以把 `center_bore_radius_mm` 放进 `facts.notes` 或 `traits` 不够结构化。更好：

```python
facts.extra = dict
```

因此 `ShapeFacts` 应增加：

```python
extra: dict[str, Any] = Field(default_factory=dict)
```

## 8.3 `axisymmetric.cut_circular_hole_pattern`

读取 input facts：

```text
radius_max_mm
extra.center_bore_radius_mm
```

参数：

```text
count
pcd_mm
hole_dia_mm
```

校验：

```text
count >= 3
hole_dia_mm > 0
pcd_mm > 0
pcd_mm / 2 + hole_dia_mm / 2 < radius_max_mm - margin
if center_bore exists:
  pcd_mm / 2 - hole_dia_mm / 2 > center_bore_radius_mm + margin
```

输出 facts：

```text
copy input facts
extra.hole_patterns append pattern summary
```

## 8.4 `composition.translate_solid`

输出 facts：

```text
copy input facts
bbox min/max shifted by x/y/z if exact numeric facts exist
bbox lengths unchanged
```

## 8.5 `composition.boolean_cut`

第一阶段不尝试精确计算 new bbox。

输出 facts：

```text
copy target input facts
traits add "modified_by_boolean_cut"
notes add cutter node id
```

如果 cutter bbox 与 target bbox 明确不相交，warning：

```text
boolean_cut_may_be_noop
```

如果 cutter bbox 完全 swallows target bbox，error：

```text
boolean_cut_may_remove_entire_body
```

只在 facts 都 exact/conservative 且可判断时触发。

---

# 9. Expression Evaluator

## 9.1 `analysis/expr_eval.py`

实现：

```python
def evaluate_dim_expr(expr: float | int | dict, module: CompilerModule) -> float | None:
    ...
```

要求：

```text
int/float 直接返回 float
dict 必须能 model_validate 为 DimExpr
op=const 返回数字
op=ref 解析 RefPath
op=add/sub/mul/div/min/max/abs/clamp 递归求值
任何 unknown 返回 None
任何 invalid 抛 ValueError
```

RefPath 第一阶段支持：

```text
component.<id>.body.radius_max_mm
component.<id>.body.bbox.xlen_mm
node.<id>.<output>.radius_max_mm
node.<id>.<output>.bbox.zlen_mm
node.<id>.<output>.extra.center_bore_radius_mm
```

不要支持：

```text
arbitrary object path
method call
CadQuery object inspection
runtime object_store lookup
```

---

# 10. Semantic Analysis 第一阶段

新增 `analysis/semantic_specs.py`。

不要改 OperationSpec。

```python
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass(frozen=True)
class OperationSemanticSpec:
    dialect: str
    op: str
    op_version: str = "1.0.0"
    required_input_traits: tuple[str, ...] = ()
    produced_traits: tuple[str, ...] = ()
    fact_rule: Callable[..., Any] | None = None
    feasibility_rule: Callable[..., Any] | None = None
    risk_tags: tuple[str, ...] = ()
```

registry：

```python
SEMANTIC_SPECS: dict[tuple[str, str, str], OperationSemanticSpec] = {}
```

提供：

```python
def get_semantic_spec(dialect: str, op: str, op_version: str) -> OperationSemanticSpec | None:
    ...
```

第一阶段只给上面列出的少量 op 加 spec。

---

# 11. 新增 validation stage 的接入方式

不要改原 `validate_and_canonicalize_with_bundle` 的行为。

新增函数：

```python
def analyze_canonical_with_middle_end(canonical: CanonicalGcadDocument) -> CompilerModule:
    ...
```

在 `pipeline/run.py` 的 `run_canonical_gcad` 内部：

```python
module = analyze_canonical_with_middle_end(canonical)
if not module.ok:
    return GcadRunResult(ok=False, error="compiler middle-end failed: ...")
ctx.compiler_facts = module.facts.model_dump()
ctx.planning_report = module.planning_report
```

新增配置：

```text
环境变量 SEEKFLOW_GCAD_ENABLE_MIDDLE_END
默认 "1"
测试可设为 "0" 回到旧路径
```

实现：

```python
if os.environ.get("SEEKFLOW_GCAD_ENABLE_MIDDLE_END", "1") != "0":
    module = analyze_canonical_with_middle_end(canonical)
    ...
```

---

# 12. PlanningReport 第一阶段

第一阶段 planner 不改图，只报告。

## 12.1 `planning/planning_report.py`

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PlanningIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str = "warning"
    message: str
    node_id: str | None = None
    component_id: str | None = None
    suggestion: str | None = None
    details: dict = Field(default_factory=dict)


class PlanningReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    issues: list[PlanningIssue] = Field(default_factory=list)
    optimization_opportunities: list[dict] = Field(default_factory=list)
```

## 12.2 Planner rules

### Rule: hole pattern batching opportunity

如果一个 node 是：

```text
axisymmetric.cut_circular_hole_pattern
count >= 8
```

输出 opportunity：

```text
code = hole_pattern_should_batch
message = large hole pattern should use compound cutter / batched boolean
```

第一阶段只报告，不修改。

### Rule: fillet/chamfer before boolean warning

如果 `apply_safe_chamfer` 出现在后续 boolean/cut 之前，warning：

```text
edge treatment should usually be late
```

### Rule: too many sequential boolean-like ops

如果同 component 内 cuts_material op 数量超过阈值，例如 32，warning：

```text
many destructive ops; future planner should batch or reorder
```

### Rule: pattern explosion

如果 pattern count 超过 120，但低于当前硬阈值 360，warning：

```text
large pattern count may cause slow booleans
```

---

# 13. GeometryHealth

新增 `runtime/health.py`。

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class GeometryHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "warning", "error", "unknown"] = "unknown"
    valid_brep: bool | None = None
    closed: bool | None = None
    body_count: int | None = None
    bbox_mm: list[float] | None = None
    volume_mm3: float | None = None
    small_edges_count: int | None = None
    small_faces_count: int | None = None
    score: float | None = None
    issues: list[dict] = Field(default_factory=list)


def inspect_geometry_health(obj, geometry_runtime, tolerance) -> GeometryHealth:
    ...
```

第一阶段可用现有 `geometry_runtime`：

```text
inspect_solid
validate_closed_solid
compute_bbox_mm
count_bodies
```

评分规则：

```text
unknown → score None
closed false → error score 0.5
body_count > 1 for expected single solid → warning score 0.8
bbox missing → warning score 0.85
valid closed single body → ok score 1.0
```

修改 `execute_operation._validate_geometry`：

```text
保留原 warnings 行为
新增 ctx.geometry_health[node.id.output] = health.model_dump()
如果 health.status == "error" 且 node.required:
  raise RuntimeError
如果 health.status == "error" 且 optional:
  warning，不 raise
```

注意：

```text
不要在 OCP 缺失时 fail。
不要让 health 检查破坏现有测试。
```

---

# 14. Handler 降级规则收紧

发现现状中一些 handler 仍会：

```text
except Exception:
  ctx.warnings.append(...)
  return original body
```

这对 optional feature 合理，但对 required feature 不合理。

实施要求：

```text
新增 helper:
  runtime/recovery.py 或 dialects/recovery.py

函数:
  handle_feature_failure(node, ctx, original_body, op_name, exc) -> dict[str, str] or raises
```

语义：

```python
if node.required:
    raise RuntimeError(...)
if node.degradation_policy == "may_skip_with_warning":
    store original body
    record degraded_features
    return original body
else:
    raise RuntimeError(...)
```

第一阶段只改 axisymmetric handlers 中最明显的 destructive ops：

```text
cut_center_bore
cut_circular_hole_pattern
cut_annular_groove
cut_rim_slot_pattern
apply_safe_chamfer
cut_internal_thread
cut_external_thread
```

验收要求：

```text
required=True 的 cut_center_bore 如果 boolean 抛异常，run 失败。
required=False + may_skip_with_warning 的 cut_center_bore 如果 boolean 抛异常，run 成功但 degraded_features 有记录。
```

---

# 15. Metadata 集成

当前 metadata_v3 已保存：

```text
warnings
degraded_features
operation_metrics
validation
runtime proof
artifact hash
```

新增字段不要破坏 `MetadataProofV3` 的 extra=forbid。

推荐方式：

```text
不要直接给 GenerativeMetadataV3 添加大量字段。
在 validation dict 中添加额外 section：
  compiler_middle_end
  planning_report
  geometry_health_summary
```

因为现有 normalize_validation_proof 会保留 extra diagnostic sections。

新增 metadata 注入点：

```python
validation = copy.deepcopy(validation_seed)
validation["runtime_postconditions"] = runtime_pc
validation["compiler_middle_end"] = module diagnostics
validation["planning_report"] = ctx.planning_report
validation["geometry_health_summary"] = summarize ctx.geometry_health
```

要求：

```text
compiler_middle_end section 必须 JSON-serializable
不要放 CadQuery/OCP objects
不要放 non-deterministic repr
```

---

# 16. STEP 生成能力保持原则

STEP export 必须保留。

现有 `_export_final_solid(final_handle_id, ctx)` 调用：

```python
obj = ctx.object_store.get(handle_id)
ctx.geometry_runtime.export_step(obj, ctx.out_step)
```

本次升级不得改变此路径。

新增 `pre_export_health_gate`：

```text
位置：
  runtime_postconditions 之后
  _export_final_solid 之前

行为：
  如果 geometry health 明确 error，禁止 STEP
  如果 health unknown，允许 STEP 但 warning
  如果 health warning，允许 STEP 但 metadata 记录
```

不要让 ShapeFacts 静态 unknown 阻止 STEP。

---

# 17. 测试计划

新增测试目录：

```text
tests/generative_cad/test_middle_end_expr.py
tests/generative_cad/test_shape_facts_axisymmetric.py
tests/generative_cad/test_middle_end_pipeline_compat.py
tests/generative_cad/test_geometry_health.py
tests/generative_cad/test_required_degradation_semantics.py
tests/generative_cad/test_planning_report.py
```

## 17.1 兼容性测试

输入一个现有最小 axisymmetric raw JSON。

断言：

```text
SEEKFLOW_GCAD_ENABLE_MIDDLE_END=0 时旧路径 ok
SEEKFLOW_GCAD_ENABLE_MIDDLE_END=1 时新路径 ok
输出 STEP 存在
metadata 存在
canonical_graph_hash 不因 middle-end 改变
```

## 17.2 ShapeFacts 测试

输入：

```text
revolve_profile radius 50 z 0..20
```

断言：

```text
radius_max_mm == 50
bbox.xlen == 100
bbox.ylen == 100
bbox.zlen == 20
faces.outer_cylindrical exists
```

## 17.3 center bore feasibility 测试

Case A：

```text
outer radius 50
bore diameter 20
```

断言 ok。

Case B：

```text
outer radius 50
bore diameter 100
```

断言 middle-end error。

## 17.4 hole pattern feasibility 测试

Case：

```text
outer radius 50
center bore diameter 40
hole_dia 10
pcd 46
```

断言 intersects center bore error 或 margin violation。

## 17.5 planner report 测试

Case：

```text
cut_circular_hole_pattern count 32
```

断言 planning_report.optimization_opportunities 包含 `hole_pattern_should_batch`。

## 17.6 required degradation 测试

用 monkeypatch 让 body.cut 抛异常。

断言：

```text
required=True → RuntimeError
required=False + may_skip_with_warning → ok + degraded_features
```

---

# 18. 分阶段实施计划

## Phase 0：安全保护与开关

目标：

```text
新增 middle-end enable/disable 开关
不改变旧行为
```

实现：

```text
compiler/module.py
compiler/pass_manager.py
compiler/config.py
pipeline/run.py 接入开关但不开启任何实质 pass
```

验收：

```text
所有现有测试通过
```

---

## Phase 1：Expression + ShapeFacts for axisymmetric

目标：

```text
实现 DimExpr / RefPath / ShapeFacts
实现 axisymmetric facts
实现 compiler_middle_end metadata section
```

实现文件：

```text
ir/expr.py
ir/semantic.py
analysis/facts.py
analysis/expr_eval.py
analysis/fact_rules.py
analysis/fact_propagation.py
analysis/semantic_specs.py
compiler/module.py
compiler/pass_manager.py
```

验收：

```text
axisymmetric shape facts 测试通过
旧模型仍可 STEP export
```

---

## Phase 2：GeometryHealth + required degradation 收紧

目标：

```text
建立 runtime health model
required feature 不允许 silent degradation
```

实现文件：

```text
runtime/health.py
dialects/executor.py
dialects/axisymmetric/handlers.py
```

验收：

```text
required degradation tests 通过
metadata 中出现 geometry_health_summary
```

---

## Phase 3：PlanningReport

目标：

```text
新增只读 planner，不改写图
```

实现文件：

```text
planning/planning_report.py
planning/planner.py
planning/risk_model.py
pipeline/run.py metadata 注入
```

验收：

```text
large hole pattern 产生 optimization opportunity
fillet/chamfer early 产生 warning
```

---

## Phase 4：Opt-in Planner Rewrite

目标：

```text
只对严格等价场景做 rewrite
默认关闭
```

允许 rewrite：

```text
同一个 op 已经表达为 pattern 的内部 batching hint
不要跨节点改写用户图
不要改变 root_node
不要改变 output name
```

不允许 rewrite：

```text
任意 boolean 重排
跨 component 重排
required/optional 语义改变
```

本阶段可以延后，不是第一轮必做。

---

## Phase 5：Backend Lowering 准备

目标：

```text
新增 BackendOp 数据结构，但仍不替代 handler
```

实现：

```text
planning/backend_ops.py
runtime/backend_protocol.py
```

仅用于 report，不执行。

---

# 19. Claude Code 实施约束

Claude Code 必须遵守：

```text
每个 Phase 单独 commit。
每个 commit 必须保持测试可运行。
不得做大规模格式化。
不得重命名已有 public API。
不得删除 legacy adapter。
不得修改 Raw schema_version。
不得修改 canonical_graph_hash 计算逻辑。
不得修改 STEP artifact policy。
不得在 params 中使用 eval。
不得引入非标准 heavyweight dependency。
不得要求 OCP 在所有测试环境可用。
```

新增代码风格：

```text
Pydantic model 使用 extra="forbid"
所有新 pass 失败必须生成 diagnostic，不得裸崩，除非严重 runtime invariant
所有新增 section 必须 JSON-serializable
所有 feature flag 默认保守
```

---

# 20. Claude Code 主 Prompt

把下面这段作为 Claude Code 的执行 prompt。

```text
你正在修改 seekflow-engineering 仓库中的 generative_cad 编译器。目标是在不推翻现有 RawGcadDocument、CanonicalGcadDocument、DialectRegistry、OperationSpec、execute_operation、RuntimeContext、STEP export pipeline 的前提下，新增一个保守的 compiler middle-end。

你必须先阅读以下文件：
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/values.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/object_store.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/geometry_preflight.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py
- integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py

第一阶段只做以下事情：
1. 新增 compiler/module.py、compiler/pass_manager.py、compiler/config.py。
2. 新增 ir/expr.py、ir/semantic.py。
3. 新增 analysis/facts.py、analysis/expr_eval.py、analysis/fact_rules.py、analysis/fact_propagation.py、analysis/semantic_specs.py。
4. 在 pipeline/run.py 中用环境变量 SEEKFLOW_GCAD_ENABLE_MIDDLE_END 控制是否运行 middle-end，默认开启；但 middle-end 必须是 sidecar，不得修改 canonical_graph_hash，不得修改 CanonicalGcadDocument。
5. ShapeFacts 第一阶段只支持 axisymmetric.revolve_profile、axisymmetric.cut_center_bore、axisymmetric.cut_circular_hole_pattern、axisymmetric.cut_annular_groove，以及 composition.translate_solid 的保守传播。
6. middle-end 产生 diagnostics。error 时 run_canonical_gcad 返回 GcadRunResult(ok=False)。warning 不阻断。
7. metadata validation dict 中增加 compiler_middle_end section，必须 JSON serializable。
8. 所有旧测试必须通过。新增测试覆盖 ShapeFacts、center bore feasibility、hole pattern feasibility、middle-end disable compatibility。

严禁：
- 修改 RawGcadDocument schema。
- 替换 ValueType。
- 替换 OperationSpec。
- 删除 execute_operation。
- 让 LLM 输出 Python 或 CadQuery。
- 改变 STEP export 的最终路径。
- 使用 eval。
- 引入要求 OCP 必装的新测试。
- 做自动 graph rewrite。

实现完成后，运行现有测试和新增测试。若测试环境没有 CadQuery/OCP，相关 runtime geometry 测试应 skip，而非失败。
```

---

# 21. Claude Code Phase 2 Prompt

```text
在 Phase 1 已通过测试的基础上，实现 GeometryHealth 和 required feature degradation 收紧。

目标：
1. 新增 runtime/health.py，定义 GeometryHealth 和 inspect_geometry_health。
2. 使用现有 GeometryRuntime 的 inspect_solid、validate_closed_solid、compute_bbox_mm、count_bodies 做 best-effort 检查。
3. 修改 RuntimeContext，增加 geometry_health: dict[str, Any] = field(default_factory=dict)。
4. 修改 dialects/executor.py 的 _validate_geometry：保留原 warnings 行为，同时把每个 solid output 的 health 写入 ctx.geometry_health。
5. 如果 health.status == "error" 且 node.required 为 True，则 raise RuntimeError。
6. 修改 axisymmetric handlers 中 destructive ops 的 except 降级逻辑：required=True 时不得返回原 body，必须 raise；required=False 且 degradation_policy="may_skip_with_warning" 时才可返回原 body，并记录 degraded_features。
7. metadata validation dict 中增加 geometry_health_summary。
8. 新增 tests/generative_cad/test_geometry_health.py 和 test_required_degradation_semantics.py。

约束：
- 不改变 execute_operation 的返回类型。
- 不改变 OperationResult schema，除非新增字段有默认值且不破坏 legacy adapter。
- OCP/CadQuery 不可用时测试应 skip。
- 不要实现 transaction rollback。
```

---

# 22. Claude Code Phase 3 Prompt

```text
在 Phase 1/2 稳定后，实现只读 PlanningReport。

目标：
1. 新增 planning/planning_report.py、planning/planner.py、planning/risk_model.py。
2. Planner 不修改 CanonicalGcadDocument。
3. Planner 只产生 warning 和 optimization_opportunities。
4. 实现规则：
   - axisymmetric.cut_circular_hole_pattern count >= 8 → opportunity hole_pattern_should_batch
   - destructive cut/material removal ops 数量超过 32 → warning many_destructive_ops
   - edge treatment op 在后续 destructive op 前出现 → warning edge_treatment_too_early
   - pattern count >= 120 → warning large_pattern_risk
5. 把 PlanningReport 写入 ctx.planning_report 和 metadata validation["planning_report"]。
6. 新增 tests/generative_cad/test_planning_report.py。

约束：
- 不做 graph rewrite。
- 不改变 run order。
- 不改变 phase_order。
- 不改变 root_node。
```

---

# 23. 成功标准

本架构改进成功的判断标准不是“新增了多少抽象类”，而是：

```text
1. 旧 Raw JSON 仍然能生成 STEP。
2. canonical_graph_hash 不因 middle-end sidecar 改变。
3. axisymmetric 的越界孔、过大中心孔能在执行前被 middle-end 报出。
4. required destructive feature 失败不能静默成功。
5. optional decorative feature 仍可降级并记录。
6. metadata 中可看到 compiler_middle_end、planning_report、geometry_health_summary。
7. 大 pattern 能被 planner 识别为需要 batching。
8. 所有新增能力都可以通过环境变量关闭。
```

---

# 24. 不做事项

以下事项本轮明确不做：

```text
不做完整工业级 persistent topology naming。
不做 SolidWorks/NX backend。
不做 Parasolid/ACIS backend。
不做自动 boolean reorder。
不做跨 component 全局优化。
不做全量 Feature IR executor。
不做 schema_version 大升级。
不做 LLM prompt 大改。
不做直接 STEP 生成。
```

这些不是不重要，而是当前阶段做会破坏可落地性。

---

# 25. 最终架构判断

这套方案能拓宽编译器边界，原因是它直接补上当前系统最薄弱但最关键的中端能力：

```text
DimExpr 解决派生尺寸表达。
ShapeFacts 解决静态几何事实传播。
Feasibility checks 解决执行前几何冲突发现。
GeometryHealth 解决坏 B-Rep 继续传播的问题。
Required degradation 收紧解决必需特征静默失败的问题。
PlanningReport 解决复杂模型优化方向不可见的问题。
Metadata integration 解决 repair 和审计闭环问题。
```

这套方案不会破坏现有架构，原因是：

```text
Raw IR 不动。
ValueType 不动。
OperationSpec 不动。
handler 不重写。
STEP export 不动。
middle-end sidecar 可关闭。
所有新增结构 JSON-safe。
所有新增 pass 都能 warning-only 渐进启用。
```

第一阶段目标不是把 SeekFlow 立刻变成 NX/SolidWorks，而是把它从“能跑的 CAD 操作翻译器”升级成“开始理解几何事实的 CAD 编译器”。这一步完成后，后续才有资格安全地做 batch boolean、feature planning、topology selection、backend lowering 和更高复杂度模型生成。
