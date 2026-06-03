# SeekFlow Generative CAD 非 Primitive 链路修复与升级工程规格书

版本：v1.0
目标实现者：Claude Code
目标仓库根目录：`E:\auto_detection_process`
目标模块：`integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad`
适用链路：非 Primitive 生成链路，即 `Text → Staged LLM Authoring → RawGcadDocument → AutoFixer → Validation → Canonical IR → Runtime → STEP`

---

## 0. 执行原则

本工程不是“调 prompt”工程，也不是“换 LLM”工程。它是一个 CAD compiler 工程。

必须先修复确定性 compiler 边界：

1. Provider strict schema 必须真正接入 staged authoring。
2. Raw assembler 必须从 solid-only linear chain 升级为 typed feature graph wiring。
3. Helix/sweep/shell/composition 必须有 CAD 语义级约束。
4. Runtime 不能只证明“生成了合法 solid”，还必须证明“几何近似符合用户设计意图”。
5. Prompt 只负责让 LLM 做受限设计决策，不能让 LLM 承担几何内核、拓扑依赖、类型引用、装配布尔树等 compiler 职责。

不要新增 part-specific operation，例如 `make_flange`、`make_bracket`、`make_spring`。所有新增能力必须是通用 CAD operation、通用 validation、通用 metrics 或通用 prompt/context 能力。

不要修改 primitive 链路。Primitive 与 Generative CAD 链路必须保持隔离。

---

## 1. 当前主问题分级

### P0-1：Strict tool schema 未真正接入主 authoring pipeline

现状：

`authoring/pipeline.py` 中 route、feature sequence、node params、repair 四处调用 `call_strict_tool()` 时仍传入 `tool_schema={}`。

影响：

LLM 没有被 provider strict schema 约束，导致字段名、enum、operation、params 结构和 repair patch 都在弱约束状态下生成。本地 Pydantic 校验发生得太晚，AutoFixer 和 Repair Agent 会被迫处理本应由 schema 层拒绝的问题。

目标：

将 `authoring/tool_schemas.py` 中已经存在的 schema factory 接入 pipeline：

* `build_route_plan_tool_schema(dialect_registry, primitive_catalog_summary=None)`
* `build_feature_sequence_tool_schema(ctx)`
* `build_node_params_tool_schema(node_plan, dialect_registry)`
* `build_repair_patch_tool_schema()`

验收：

任何阶段不得再向生产 LLM caller 传 `tool_schema={}`。单元测试必须覆盖四个 stage 的 schema 非空、包含 `additionalProperties: false` 或 strict 后等价约束，并能约束 dialect/op/params。

---

### P0-2：Raw assembler 仍是 solid-only linear wiring

现状：

`authoring/raw_assembler.py` 通过 `last_solid[component_id]` 记录每个 component 的最后 solid 输出，并且 `_build_inputs()` 只在 operation input count 为 1 时把前一个 solid 接入。

影响：

以下场景会系统性断裂：

* `create_sweep_path → sweep_profile`：前者输出 `curve`，后者需要 `curve` 输入。
* `create_2d_sketch → close_profile → extrude_profile`：需要 `sketch/profile` typed wiring。
* `boolean_union`：需要两个 solid 输入，当前单输入 wiring 无法正确表达。
* `shell_body`：作为 solid transformer 消费 solid 并输出 solid，跨 dialect 后处理容易丢输入。
* 多组件 assembly：component root solid 与 assembly-level boolean tree 缺少可靠引用。
* 多输出 operation：输出名不能靠猜，必须由 OperationSpec 的 output type 确定。

目标：

实现 `last_output_by_type[scope][type] -> list[ValueRef]` 的 typed availability graph。系统侧 assembly 必须根据 `OperationSpec.input_types` 严格生成 inputs，缺输入则 fail closed，不得默默返回空 inputs。

---

### P0-3：`helix_sweep` 几何实现忽略 `turns`

现状：

`loft_sweep/params.py` 有 `turns` 参数，但 `loft_sweep/handlers.py` 的 helix 曲线只使用一圈 `2πt` 和 `pitch*t`。结果是弹簧/螺旋零件输出一个很短的单圈 sweep，STEP 合法但语义错误。

目标：

`helix_sweep` 必须按照以下几何关系构造中心线：

* 圈数：`turns`
* 总高度：优先使用 `height_mm`
* 常量 pitch：若 `height_mm` 缺失，则 `height_mm = pitch_mm * turns`
* 若 `height_mm` 与 `pitch_mm * turns` 同时存在且差异超过 2%，记录 warning；默认以 `height_mm` 为准
* 曲线：`x = R cos(2π turns t)`，`y = R sin(2π turns t)`，`z = height t`
* 采样数量：`N = max(160, ceil(turns * 48))`
* 输出体积必须接近理论体积：`π * profile_radius² * sqrt((2πRturns)² + height²)`

验收：

`Long Helix Spring` 与 `t2_spring` 不得再出现体积只有理论值 2% 或 1/45 的情况。semantic metrics 必须能捕捉 helix bbox、turns、volume 异常。

---

### P0-4：Validation 缺少语义后验质量闭环

现状：

当前 runtime postconditions 多数只验证：

* 是否为 solid；
* BRepCheck 是否通过；
* volume 是否大于 0；
* STEP 是否导出。

影响：

会出现“合法但错误”的 CAD 假阳性。弹簧案例就是典型：solid 合法，STEP 可导入，但几何完全不符合设计意图。

目标：

新增 `DesignIntentMetrics` 和 `semantic_postcheck`：

* bbox 范围；
* volume 范围；
* body count；
* critical dimension；
* feature count；
* helix expected length/volume；
* hole count / pattern count；
* shell wall thickness sanity；
* degraded operation count。

最终结果必须区分：

* `schema_valid`
* `graph_valid`
* `type_valid`
* `preflight_valid`
* `kernel_valid`
* `semantic_valid`
* `solidworks_import_valid`

只有全部关键项通过，case 才能标记为 `success`。

---

## 2. 目标架构

最终链路必须变成：

```text
User Prompt
  ↓
Prompt Normalizer / DesignIntentExtractor
  ↓
RoutePlan LLM call with strict route schema
  ↓
AuthoringContext build
  ↓
FeatureSequenceDraft LLM call with strict sequence schema
  ↓
NodeParamsDraft per node with operation-specific strict params schema
  ↓
Raw Assembler typed graph compiler
  ↓
Deterministic AutoFixer
  ↓
Fail-Closed Validation
  ↓
CanonicalGcadDocument
  ↓
Runtime executor
  ↓
Runtime postconditions
  ↓
Semantic postcheck
  ↓
STEP + metadata + audit reports
```

核心边界：

* LLM 不直接写完整 RawGcadDocument。
* LLM 不写 input refs，除非未来专门设计 explicit reference schema。
* LLM 不写 op_version、outputs、safety、constraints、root_node。
* 系统侧 assembler 负责 op_version、outputs、inputs、root_node、安全字段、constraints。
* LLM 只负责：

  * route decision；
  * component/operation sequence；
  * operation params；
  * assumptions。
* Validation 永远不修复，只报告。
* AutoFixer 只修安全别名、单位别名、枚举别名、低风险语义猜测；不得破坏性删除或重写设计意图。
* Repair Agent 只能在 validation issue 指向的最小范围内 patch。

---

## 3. 文件级实现任务

### 3.1 接入 Strict Tool Schema

修改文件：

`integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\authoring\pipeline.py`

新增 import：

```python
from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import (
    build_route_plan_tool_schema,
    build_feature_sequence_tool_schema,
    build_node_params_tool_schema,
    build_repair_patch_tool_schema,
)
```

#### 3.1.1 Route 阶段

替换：

```python
tool_schema={}
```

为：

```python
tool_schema=build_route_plan_tool_schema(
    dialect_registry=dialect_registry,
    primitive_catalog_summary=None,
)
```

并将 messages 改为：

```python
messages=[
    {"role": "system", "content": ROUTE_SYSTEM_PROMPT},
    {"role": "user", "content": build_route_user_prompt(user_request)},
]
```

若当前没有 prompt builder，新增文件：

`authoring/prompt_builders.py`

函数：

```python
def build_route_user_prompt(user_request: str) -> str:
    ...
```

#### 3.1.2 Feature sequence 阶段

替换：

```python
tool_schema={}
```

为：

```python
tool_schema=build_feature_sequence_tool_schema(ctx)
```

messages 必须包含：

* 原始 user request；
* route_plan JSON；
* selected dialect contracts；
* operation list；
* assembly governance；
* explicit instruction：不要写 input refs，不要写 params。

#### 3.1.3 Node params 阶段

每个 node 单独构建 schema：

```python
schema = build_node_params_tool_schema(
    node_plan=node_plan,
    dialect_registry=dialect_registry,
)
```

替换：

```python
tool_schema={}
```

为：

```python
tool_schema=schema
```

messages 必须包含：

* 原始 user request；
* route_plan 摘要；
* feature sequence 摘要；
* 当前 node_plan；
* 当前 node 的 operation contract；
* 前置 nodes 摘要；
* 已知 component 尺寸/基准面/坐标系；
* 禁止输出 schema 外字段。

#### 3.1.4 Repair 阶段

替换：

```python
tool_schema={}
```

为：

```python
tool_schema=build_repair_patch_tool_schema()
```

repair prompt 必须只包含：

* 当前 validation issues；
* 原始 RawGcadDocument；
* repairable paths；
* forbidden paths；
* 最小修复原则；
* 不允许改变 user intent、dialect、safety、schema_version。

#### 3.1.5 测试

新增测试文件：

`integrations\engineering_tools\tests\generative_cad\authoring\test_strict_schema_pipeline.py`

测试项：

1. `test_pipeline_uses_non_empty_route_schema`
2. `test_pipeline_uses_non_empty_feature_sequence_schema`
3. `test_pipeline_uses_operation_specific_node_params_schema`
4. `test_pipeline_uses_repair_schema`
5. `test_node_params_schema_rejects_extra_param`
6. `test_node_params_schema_constrains_node_identity`

实现方式：

* 用 `RecordingLlmToolCaller` mock，记录每次 `tool_schema`。
* assert 每次 schema 是 dict 且非空。
* assert route schema 有 selected dialect enum。
* assert node params schema 中 params 对应具体 Pydantic params model，而不是 open dict。
* 不需要真实 DeepSeek API。

---

### 3.2 重构 Raw Assembler 为 Typed Wiring Compiler

修改文件：

`authoring/raw_assembler.py`

新增数据类：

```python
from dataclasses import dataclass
from collections import defaultdict
from typing import DefaultDict

@dataclass(frozen=True)
class ValueRef:
    node_id: str
    output_name: str
    value_type: str
    component_id: str
    dialect: str
    op: str

AvailabilityMap = DefaultDict[str, DefaultDict[str, list[ValueRef]]]
```

scope 规则：

* `scope = component_id`：component 内可见值。
* `scope = "__assembly__"`：assembly-level 可见值。
* leaf component 的 root solid 在完成 component 后必须复制到 `__assembly__` scope。
* 非 composition operation 默认只能消费本 component scope。
* composition operation 默认消费 `__assembly__` scope。
* shell_housing 如果作为 solid transformer，在同 component scope 内消费 solid。

#### 3.2.1 输出命名规则

保留 `_output_name_for_type`，但必须统一：

```python
OUTPUT_NAME_BY_TYPE = {
    "solid": "body",
    "frame": "outer_frame",
    "curve": "curve",
    "profile": "profile",
    "sketch": "sketch",
}
```

未知 type 必须 fail closed，不得 fallback 到 solid。

```python
def _output_name_for_type(value_type: str) -> str:
    try:
        return OUTPUT_NAME_BY_TYPE[value_type]
    except KeyError:
        raise AssemblyError(f"Unsupported output type: {value_type}")
```

#### 3.2.2 `_build_outputs` 必须严格

当前 `_build_outputs` 在 dialect/spec 查找失败时 fallback 到 solid，这是危险行为。改为 fail closed：

```python
def _build_outputs(node_plan, dialect_registry) -> list[dict[str, str]]:
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        raise AssemblyError(f"Unknown dialect: {node_plan.dialect}")

    spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)

    outputs = []
    for t in spec.output_types:
        outputs.append({"name": _output_name_for_type(t), "type": t})
    return outputs
```

如果 `node_plan.op_version` 为空或不可靠，先 `_resolve_op_version`，再查 spec。

#### 3.2.3 输入选择算法

新增：

```python
def _choose_latest_available(
    available: AvailabilityMap,
    scope: str,
    expected_type: str,
) -> ValueRef:
    candidates = available.get(scope, {}).get(expected_type, [])
    if not candidates:
        raise AssemblyError(
            f"Missing input of type {expected_type!r} in scope {scope!r}"
        )
    return candidates[-1]
```

新增：

```python
def _build_inputs_typed(
    node_plan,
    spec,
    available: AvailabilityMap,
) -> list[dict[str, str]]:
    if not spec.input_types:
        return []

    scope = "__assembly__" if node_plan.dialect == "composition" else node_plan.component_id

    inputs = []
    for expected_type in spec.input_types:
        ref = _choose_latest_available(available, scope, expected_type)
        inputs.append({"node": ref.node_id, "output": ref.output_name})
    return inputs
```

这适用于单输入 transformer 和 curve/profile/sketch 链。

#### 3.2.4 Composition 的多 body union 特殊规则

不要让 LLM 写 3+ 输入的 `boolean_union`。当前 operation spec 如果是二输入 union，则系统自动生成 pairwise union tree。

实现策略：

1. LLM feature sequence 允许出现一个 assembly-level `boolean_union` 作为“combine all components”的意图节点。
2. assembler 检测该 node：

   * 如果 spec.input_types 是两个 solid；
   * 当前 `__assembly__` scope 有超过两个 solid；
   * 自动展开为多个 synthetic nodes：

     * `union_001`
     * `union_002`
     * ...
3. synthetic nodes 必须写入 nodes，并在 metadata/system_filled_fields 中记录来源。
4. 原 LLM union node 可以：

   * 方案 A：作为第一个 synthetic node 使用原 node_id；
   * 方案 B：被替换为 synthetic tree。
5. 推荐方案 A：保留原 node_id 作为首个 union，减少审计混乱。

伪代码：

```python
def _expand_boolean_union_if_needed(node_plan, spec, available):
    solids = list(available["__assembly__"]["solid"])
    if node_plan.dialect != "composition" or node_plan.op != "boolean_union":
        return None
    if len(spec.input_types) != 2:
        return None
    if len(solids) < 2:
        raise AssemblyError("boolean_union requires at least two assembly solids")
    if len(solids) == 2:
        return [_make_node(node_plan, inputs=[solids[0], solids[1]])]

    current = solids[0]
    synthetic_nodes = []
    for i, next_ref in enumerate(solids[1:], start=1):
        nid = node_plan.node_id if i == 1 else f"{node_plan.node_id}__auto_{i}"
        out = ValueRef(nid, "body", "solid", "__assembly__", "composition", "boolean_union")
        synthetic_nodes.append(_make_union_node(nid, current, next_ref, node_plan))
        current = out
    return synthetic_nodes
```

#### 3.2.5 Component root handling

每个 component 的 `root_node` 必须指向该 component 内最后一个 solid output 的 producer。

规则：

* 如果 component 没有 solid output，validation fail。
* assembly component `__assembly__` 的 root_node 指向 final union/place/pattern solid。
* leaf component root solid 必须在 component 完成后加入 `available["__assembly__"]["solid"]`。

#### 3.2.6 禁止 silent fallback

禁止以下行为：

* dialect unknown → fallback solid；
* op unknown → fallback solid；
* missing input → return empty；
* output type unknown → expected_output_name；
* op_version unknown → arbitrary version。

这些必须抛出 `AssemblyError`，并让 pipeline 返回 structured failure。

新增错误类：

```python
class AssemblyError(ValueError):
    pass
```

#### 3.2.7 测试

新增测试文件：

`tests\generative_cad\authoring\test_raw_assembler_typed_wiring.py`

必测：

1. `test_sweep_path_wires_curve_to_sweep_profile`
2. `test_sketch_profile_wires_sketch_profile_solid_chain`
3. `test_shell_body_consumes_previous_solid`
4. `test_boolean_union_wires_two_assembly_solids`
5. `test_boolean_union_expands_three_solids_pairwise`
6. `test_missing_required_input_fails_closed`
7. `test_unknown_output_type_fails_closed`
8. `test_component_root_node_is_last_solid`
9. `test_assembly_root_node_is_final_union`

每个测试使用 mock RoutePlan、FeatureSequenceDraft、NodeParamsDraft，不调用 LLM，不调用 CadQuery。

---

### 3.3 修复 `helix_sweep`

修改文件：

`dialects\loft_sweep\handlers.py`

#### 3.3.1 参数读取

目标逻辑：

```python
turns = float(params.get("turns", 1.0))
radius = float(params["radius_mm"])
profile_r = float(params["profile_radius_mm"])
pitch = float(params.get("pitch_mm", 0.0))
height = params.get("height_mm")

if turns <= 0:
    raise RuntimeError("helix_sweep requires turns > 0")
if radius <= 0:
    raise RuntimeError("helix_sweep requires radius_mm > 0")
if profile_r <= 0:
    raise RuntimeError("helix_sweep requires profile_radius_mm > 0")

if height is None:
    if pitch <= 0:
        raise RuntimeError("helix_sweep requires height_mm or positive pitch_mm")
    total_z = pitch * turns
else:
    total_z = float(height)

if total_z <= 0:
    raise RuntimeError("helix_sweep requires positive total height")
```

#### 3.3.2 常量 pitch 曲线

替换旧实现：

```python
radius * cos(2*pi*t)
radius * sin(2*pi*t)
pitch * t
```

为：

```python
sample_n = max(160, int(math.ceil(turns * 48)))

wire = cq.Workplane("XY").parametricCurve(
    lambda t: (
        radius * math.cos(2.0 * math.pi * turns * t),
        radius * math.sin(2.0 * math.pi * turns * t),
        total_z * t,
    ),
    N=sample_n,
)
```

#### 3.3.3 变 pitch 曲线

不要使用 `(start_p + (end_p - start_p) * t / 5.0) * t`。正确表达应通过积分近似总 z：

对于线性 pitch 从 `start_pitch` 到 `end_pitch`，总高度如果未给出：

```python
total_z = turns * 0.5 * (start_pitch + end_pitch)
```

如果给出 `height_mm`，以 height 为准。

角度仍是 `2π turns t`，z 可用线性归一：

```python
z = total_z * t
```

第一阶段不实现真实变螺距 z 积分也可以，但必须保证 turns 与 total_z 正确。若要表达变螺距，可实现：

```python
# normalized cumulative pitch integral for p(u)=p0+(p1-p0)u
# integral_0^t p(u) du / integral_0^1 p(u) du
den = 0.5 * (start_p + end_p)
num = start_p * t + 0.5 * (end_p - start_p) * t * t
z = total_z * (num / den)
```

#### 3.3.4 理论体积检查

新增 helper：

```python
def _estimate_helix_sweep_volume(radius: float, profile_r: float, turns: float, height: float) -> float:
    centerline_len = math.sqrt((2 * math.pi * radius * turns) ** 2 + height ** 2)
    return math.pi * profile_r ** 2 * centerline_len
```

在 solid 构建后：

```python
expected_v = _estimate_helix_sweep_volume(radius, profile_r, turns, total_z)
actual_v = _shape_volume_mm3(solid)

if actual_v <= 0:
    raise RuntimeError("helix_sweep produced non-positive volume")

ratio = actual_v / expected_v
if ratio < 0.55 or ratio > 1.65:
    ctx.add_warning(...)  # 如果 RuntimeContext 无 add_warning，则写入 build log mechanism
    if params.get("strict_semantic", True):
        raise RuntimeError(...)
```

第一阶段建议 fail closed，不要 warning-only。原因：弹簧体积偏差属于语义错误，不是可接受降级。

#### 3.3.5 测试

新增：

`tests\generative_cad\dialects\loft_sweep\test_helix_sweep_geometry.py`

测试：

1. `test_helix_sweep_uses_turns_in_bbox_height`
2. `test_helix_sweep_volume_close_to_theory`
3. `test_helix_sweep_rejects_zero_turns`
4. `test_helix_sweep_rejects_self_intersecting_profile`
5. `test_variable_pitch_uses_total_turns_and_height`

用 CadQuery/OCP 环境运行，若 CI 没有 CadQuery，标记 `pytest.mark.cadquery`.

---

### 3.4 新增 Design Intent Metrics 与 Semantic Postcheck

新增目录或文件：

`runtime\semantic_postcheck.py`
`runtime\design_intent.py`

#### 3.4.1 数据模型

```python
from pydantic import BaseModel, Field
from typing import Literal

class RangeMm(BaseModel):
    min: float
    max: float

class BBoxExpectation(BaseModel):
    x_mm: RangeMm | None = None
    y_mm: RangeMm | None = None
    z_mm: RangeMm | None = None

class VolumeExpectation(BaseModel):
    min_mm3: float | None = None
    max_mm3: float | None = None

class CriticalDimensionExpectation(BaseModel):
    name: str
    target_mm: float
    tolerance_mm: float
    measurement: Literal[
        "bbox_x", "bbox_y", "bbox_z",
        "outer_diameter_xy",
        "height_z",
        "volume_mm3",
        "helix_centerline_length",
        "helix_turns"
    ]

class FeatureExpectation(BaseModel):
    kind: Literal["hole", "rib", "boss", "groove", "thread", "shell", "sweep", "loft", "boolean_union"]
    min_count: int = 0
    max_count: int | None = None

class DesignIntentMetrics(BaseModel):
    bbox: BBoxExpectation | None = None
    volume: VolumeExpectation | None = None
    critical_dimensions: list[CriticalDimensionExpectation] = Field(default_factory=list)
    features: list[FeatureExpectation] = Field(default_factory=list)
    expected_body_count: int | None = 1
    allow_degraded_ops: bool = False
```

#### 3.4.2 从 prompt/route_plan 提取

短期实现：

* 不让 LLM 自由生成 metrics。
* 先用 deterministic regex 从 user prompt 中提取明显尺寸：

  * `150 x 150 x 25`
  * `150×150×25`
  * `diameter 100`
  * `OD 100`
  * `height 25`
  * `length 120`
  * `12 holes`
  * `10 ribs`
  * `12 turns`
* 无法提取时不强行设 expected range。

新增：

`authoring\design_intent_extractor.py`

函数：

```python
def extract_design_intent_metrics(user_request: str, route_plan: RoutePlan | None = None) -> DesignIntentMetrics:
    ...
```

容差策略：

* 明确尺寸：默认 ±5% 且最少 ±0.5 mm。
* 概念性尺寸：默认 ±20%。
* 测试 prompt 如果有 exact numbers，按 exact。
* 对 helix spring：

  * outer diameter = `2 * (radius + profile_r)`；
  * height = `height_mm`；
  * turns = `turns`；
  * volume = theory ±45%。

#### 3.4.3 Runtime 测量

新增：

```python
class MeasuredGeometry(BaseModel):
    bbox_x_mm: float
    bbox_y_mm: float
    bbox_z_mm: float
    volume_mm3: float
    body_count: int | None = None
    solid_count: int | None = None
```

CadQuery/OCP shape 测量：

```python
bb = shape.BoundingBox()
bbox_x = bb.xlen
bbox_y = bb.ylen
bbox_z = bb.zlen
volume = shape.Volume()
```

#### 3.4.4 Postcheck 结果

```python
class SemanticIssue(BaseModel):
    severity: Literal["warning", "error"]
    code: str
    message: str
    expected: dict
    actual: dict

class SemanticPostcheckReport(BaseModel):
    semantic_valid: bool
    measured: MeasuredGeometry
    issues: list[SemanticIssue]
```

#### 3.4.5 Pipeline 集成

修改：

`pipeline\artifact.py` 或 `authoring\build_pipeline.py`

在 STEP 构建成功后调用：

```python
semantic_report = run_semantic_postcheck(
    canonical_doc=canonical_doc,
    runtime_result=runtime_result,
    design_intent=design_intent_metrics,
)
```

保存：

`semantic_postcheck.json`

写入：

`output.metadata.json` 中增加：

```json
{
  "semantic_valid": true,
  "semantic_issues": [],
  "design_intent_metrics": {...},
  "measured_geometry": {...}
}
```

最终 build report 中新增字段：

```json
{
  "status": "success" | "validation_failed" | "runtime_failed" | "semantic_failed" | "degraded",
  "semantic_valid": true,
  "kernel_valid": true
}
```

#### 3.4.6 测试

新增：

`tests\generative_cad\runtime\test_semantic_postcheck.py`

测试：

1. bbox 超出范围 → semantic fail。
2. volume 过小 → semantic fail。
3. no expectations → semantic valid but low confidence。
4. helix theory volume mismatch → semantic fail。
5. degraded op but `allow_degraded_ops=False` → semantic fail。

---

## 4. Composition 修复规范

修改文件：

* `dialects\composition\dialect.py`
* `validation\composition.py`
* `authoring\raw_assembler.py`
* `authoring\prompt_builders.py`

### 4.1 Governance 规则

Composition 是 assembly/body-level dialect，不是 leaf feature dialect。

必须强制：

1. `composition` operation 只能出现在 component id `__assembly__`。
2. `boolean_union` 必须消费两个 solid。
3. 3+ solid union 由 assembler 自动展开 pairwise tree。
4. leaf component 内禁止 `composition` op。
5. `add_rib`、`add_boss`、`cut_hole` 等 feature 不得用 `boolean_union` 表达。
6. 如果目标是单零件，最终 assembly root 应为 union 后 single solid。
7. 如果目标是装配体，允许 expected body count > 1，但 constraints 必须明确。

### 4.2 Validation

在 `validation\composition.py` 中加入：

```python
if node.dialect == "composition" and node.component != "__assembly__":
    issue("composition operation must be in __assembly__ component")
```

加入：

```python
if node.op == "boolean_union" and len(node.inputs) != 2:
    issue("boolean_union requires exactly 2 solid inputs")
```

加入：

```python
if component.id != "__assembly__" and any(n.dialect == "composition" for n in component_nodes):
    issue("leaf component cannot contain composition dialect operations")
```

### 4.3 Prompt 约束

Feature sequence prompt 中必须包含：

```text
Do not use composition.boolean_union to create ribs, bosses, holes, pockets, plates, flanges, shafts, or other leaf features.
Use composition only in the __assembly__ component to combine already-created component solids.
For 3 or more solids, emit a single high-level boolean_union intent node; the system assembler will expand it into pairwise union nodes.
Do not attempt to provide input references.
```

---

## 5. Shell Housing 集成修复规范

### 5.1 当前问题

`shell_housing` 与 `sketch_extrude` 集成断裂，本质是 solid transformer 边界和 typed wiring 不清晰。Shell 是典型后处理特征：消费一个 closed solid，输出新的 thin-wall solid。它不应要求 LLM 猜输入。

### 5.2 短期方案：Shell 作为 solid transformer

保持 `shell_housing` dialect，但执行以下规则：

* `shell_body` input_types = `["solid"]`
* `shell_body` output_types = `["solid"]`
* `hollow_body` input_types = `["solid"]`
* `hollow_body` output_types = `["solid"]`
* shell node 必须与其消费的 base solid 在同 component 内，除非该 component 是 `__assembly__`。
* shell thickness 必须小于 base bbox 最小维度的 40%。
* shell 后续特征继续消费 shell 输出 solid。

### 5.3 Preflight

在 `dialects\shell_housing\dialect.py` 中加入：

1. `thickness_mm > 0`
2. `thickness_mm < min_bbox_dim * 0.4`，若 preflight 无 runtime bbox，则用 params 中已知 base dimensions；没有 base dimensions 时 warning，runtime postcheck 再判。
3. `open_faces` 只能使用受支持枚举，例如 `["+Z", "-Z", "+X", "-X", "+Y", "-Y"]`。
4. 不允许 shell 厚度小于 tolerance 的 5 倍。

### 5.4 测试

新增：

`tests\generative_cad\dialects\shell_housing\test_shell_housing_integration.py`

测试：

1. extrude rectangle → shell_body 自动接 solid。
2. shell_body → cut_hole 自动接 shell solid。
3. shell thickness too large → preflight fail。
4. shell missing input → assembly fail。
5. stress case `Shelled Housing` 不再 runtime fail。

---

## 6. Loft/Sweep 鲁棒性修复规范

### 6.1 Path 构造

`handle_sweep_profile` 不得在两点 3D path 情况下丢弃 z。必须使用真正 3D edge/wire。

新增 helper：

```python
def _make_3d_polyline_wire(points: list[tuple[float, float, float]]):
    ...
```

实现建议：

* 优先使用 CadQuery `polyline` 若确认支持 3D Vector；
* 若 CadQuery Workplane 丢 z，则使用 OCP：

  * `gp_Pnt`
  * `BRepBuilderAPI_MakeEdge`
  * `BRepBuilderAPI_MakeWire`

### 6.2 Spline sweep fallback

对于多点 3D path：

1. 首先尝试 3D BSpline wire。
2. 若 sweep 失败，尝试 polyline + fillet approximation。
3. 若仍失败，尝试 segmented cylinders + sphere/elbow blend。
4. 所有 fallback 必须记录 `degraded_ops`。

### 6.3 Sweep preflight

在 `dialects\loft_sweep\dialect.py` 增加：

* path points 数量 >= 2；
* 坐标 finite；
* 相邻点距离 > 0.1mm；
* 非相邻段距离不能小于 `2 * profile_radius * 1.1`；
* bend radius 估算不能小于 `2.5 * profile_radius`；
* helix pitch 不能小于 `2.2 * profile_radius`；
* helix radius 不能小于 `1.2 * profile_radius`。

### 6.4 测试

新增：

`tests\generative_cad\dialects\loft_sweep\test_sweep_path_3d.py`

测试：

1. 两点 3D path bbox z 正确。
2. 三点 3D path bbox x/y/z 正确。
3. 过近点 preflight fail。
4. 自交风险 preflight fail。
5. fallback 被记录为 degraded。

---

## 7. Prompt 重写规范

新增文件：

`authoring\prompt_builders.py`

不要继续用一个大而泛的 system prompt 让 LLM 输出完整 RawGcadDocument。改为四段 staged prompt。

---

### 7.1 Route System Prompt

```text
You are a CAD route planner for a constrained generative CAD compiler.

You must choose whether the request should be handled by the non-primitive Generative CAD IR path.

You do not create CAD code.
You do not create RawGcadDocument.
You do not invent dialects, operations, parameter names, versions, or safety fields.
You only emit the tool arguments required by the strict schema.

Use the generative CAD IR route only when the requested shape can be represented by the available dialects:
- axisymmetric: revolved solids, bores, grooves, circular holes, rim slots, threads, chamfers.
- sketch_extrude: rectangular plates/blocks, pockets, holes, linear hole patterns, bosses, ribs, safe fillets/chamfers.
- loft_sweep: 3D paths, pipe-like sweeps, simple loft sections, helices.
- shell_housing: shelling/hollowing an existing closed solid.
- sketch_profile: 2D sketch profiles and profile extrusion/cut.
- composition: assembly-level transforms, placement, boolean union/cut, patterns.

If the prompt asks for gears, involute teeth, bearings with rolling elements, or other primitive-specific recipe objects, do not route them into this path unless the user explicitly wants approximate reference geometry.

When uncertain, prefer the simplest reliable dialect combination.
Never select a dialect that is not registered in the provided context.
```

### 7.2 Route User Prompt Builder

```python
def build_route_user_prompt(user_request: str, dialect_summary: str) -> str:
    return f"""
USER REQUEST:
{user_request}

AVAILABLE DIALECTS AND CAPABILITIES:
{dialect_summary}

Return only the strict tool call arguments.
The selected route must be conservative and buildable.
"""
```

---

### 7.3 Feature Sequence System Prompt

```text
You are a CAD feature-tree planner for a deterministic CAD compiler.

You must output only a high-level feature sequence draft.
You must not output operation parameters.
You must not output input references.
You must not output full RawGcadDocument.
The system assembler will fill op_version, outputs, inputs, root_node, safety, constraints, and wiring.

Plan like a SolidWorks/NX feature tree:
1. Create a base solid first.
2. Apply subtractive cuts after the base solid exists.
3. Apply ribs/bosses after the base solid exists.
4. Apply edge treatments after main shape features.
5. Use shell only after a closed base solid exists.
6. Use composition only in the __assembly__ component to combine completed component solids.

Do not use boolean_union to create leaf features such as ribs, bosses, plates, holes, or pockets.
Use boolean_union only to combine completed component solids.

For sweep/loft workflows:
- create_sweep_path outputs a curve.
- sweep_profile consumes the latest curve and outputs a solid.
- sketch/profile operations output sketch/profile/solid in sequence.
The assembler handles these typed references. Do not write references manually.

For 3+ body assemblies:
emit one high-level assembly boolean_union intent node; the assembler will expand it into pairwise union operations.

If a requested object exceeds available dialect capability, create the closest conservative reference geometry and state assumptions.
```

### 7.4 Feature Sequence User Prompt Builder

必须包含：

```text
USER REQUEST:
...

ROUTE PLAN:
...

SELECTED DIALECTS:
...

ALLOWED OPERATIONS:
dialect.op@version
input_types -> output_types
phase
short contract

PLANNING REQUIREMENTS:
- Use only allowed dialects and ops.
- Do not include params.
- Do not include inputs.
- Keep component ids stable and descriptive.
- Include __assembly__ only when multiple completed component solids must be combined or transformed.
```

---

### 7.5 Node Params System Prompt

```text
You are filling parameters for exactly one CAD feature node in a deterministic feature-tree compiler.

You must emit only the strict tool arguments.
You must not change node_id, dialect, op, or op_version.
You must not add fields outside the strict schema.
You must not invent parameter names.
You must not include input references.
You must not include outputs.
You must not include safety or constraints.

Use millimeters for all length values unless the schema explicitly says otherwise.
Use degrees for angular values unless the schema explicitly says otherwise.
Prefer conservative dimensions that produce a closed, non-self-intersecting solid.

For subtractive features:
- Keep cuts within the base solid unless the operation explicitly allows through cuts.
- Hole centers must lie inside the parent face.
- Pocket depth must be less than base thickness unless through-cut is intended.

For ribs and bosses:
- Place them on or inside the base footprint.
- Do not create floating features.

For helix_sweep:
- turns must be positive.
- radius_mm is the centerline radius.
- profile_radius_mm is the swept wire/tube radius.
- height_mm is the total axial height.
- pitch_mm * turns should approximately equal height_mm if both are present.
- pitch_mm should be at least 2.2 * profile_radius_mm to avoid self-intersection.

For shell:
- thickness_mm must be positive.
- thickness_mm must be less than 40% of the smallest base dimension.
```

### 7.6 Node Params User Prompt Builder

必须包含：

```text
USER REQUEST:
...

CURRENT NODE:
node_id:
component_id:
dialect:
op:
op_version:
phase:

OPERATION CONTRACT:
input_types:
output_types:
params_schema_summary:
preflight_rules:

PREVIOUS FEATURE SEQUENCE:
...

KNOWN DESIGN INTENT:
bbox expectations:
critical dimensions:
feature counts:

Return only the strict tool call arguments for this one node.
```

---

### 7.7 Repair Prompt

```text
You are a local CAD IR repair agent.

You may only produce a minimal repair patch for the validation issues shown.
Do not change the design intent.
Do not change schema_version.
Do not change safety flags.
Do not change dialect/op unless the validation issue explicitly says the dialect/op is invalid.
Do not delete nodes unless the issue explicitly says the node is impossible to repair.
Do not use destructive cleanup to make validation pass.

Prefer fixing:
- enum aliases;
- missing required params when the value is implied;
- unit field names;
- small numeric values that violate obvious preflight constraints;
- wrong output names when type is known.

Give up when:
- the requested geometry cannot be represented by the selected dialects;
- a missing input requires changing feature order;
- the repair would require inventing design intent;
- multiple incompatible fixes are possible.
```

---

## 8. AutoFixer 规则边界

修改文件：

`authoring\auto_fixer.py`

必须保留审计记录：

* `rule_id`
* `path`
* `old_value`
* `new_value`
* `severity`
* `confidence`
* `fix_type`

新增规则：

1. `fix_xyz_to_xyz_mm`
2. `fix_direction_axis_to_sign_only_when_plane_known`
3. `fix_edge_selector_alias`
4. `fix_thread_class_context`
5. `fix_helix_height_pitch_turns_consistency_warning`

禁止规则：

* 不得删除 unknown field 后继续成功，除非字段在 known harmless metadata namespace。
* 不得将 unknown op 替换成“看起来相似”的 op。
* 不得将 missing input 自动设为上一 solid；这属于 assembler 职责。
* 不得改变 component ownership。

---

## 9. Build Report 与 Audit 输出规范

每个 case 输出目录必须包含：

```text
prompt.txt
route_plan.json
feature_sequence.json
node_params/
  <node_id>.json
llm_raw.json
autofix_report.json
raw_fixed.json
raw_original_validation.json
raw_fixed_validation.json
canonical.json
validation_bundle.json
semantic_postcheck.json
output.step
output.metadata.json
_build.py
_build_log.txt
```

`output.metadata.json` 必须包含：

```json
{
  "pipeline_version": "v5.1",
  "route_decision": "...",
  "selected_dialects": [],
  "schema_valid": true,
  "raw_validation_valid": true,
  "canonical_validation_valid": true,
  "kernel_valid": true,
  "runtime_postconditions_valid": true,
  "semantic_valid": true,
  "solidworks_import_valid": null,
  "autofix_count": 0,
  "repair_count": 0,
  "degraded_ops": [],
  "semantic_issues": [],
  "bbox_mm": {"x": 0, "y": 0, "z": 0},
  "volume_mm3": 0
}
```

最终 `AUDIT_REPORT.md` 必须用以下状态分类：

* `PASS_FULL`
* `PASS_DEGRADED`
* `FAIL_SCHEMA`
* `FAIL_ASSEMBLY`
* `FAIL_VALIDATION`
* `FAIL_PREFLIGHT`
* `FAIL_RUNTIME`
* `FAIL_SEMANTIC`
* `FAIL_IMPORT`

不要把 semantic fail 标记为 success。

---

## 10. Regression Test 套件

### 10.1 必须新增的测试目录

```text
integrations\engineering_tools\tests\generative_cad\
  authoring\
    test_strict_schema_pipeline.py
    test_raw_assembler_typed_wiring.py
    test_prompt_builders.py
  dialects\
    loft_sweep\
      test_helix_sweep_geometry.py
      test_sweep_path_3d.py
    shell_housing\
      test_shell_housing_integration.py
    composition\
      test_composition_governance.py
  runtime\
    test_semantic_postcheck.py
  regression\
    test_demo_outputs_v5.py
```

### 10.2 Regression runner

新增：

`demo_output_v5\run_regression_v5_1.py`

必须运行：

```bash
python demo_output_v5\run_test_model.py
python demo_output_v5\run_stress20.py
```

如果这两个脚本已存在，则保留并包装；如果不存在，则 Claude Code 需要在本地根据现有 runner 风格创建 wrapper。

### 10.3 关键 case 验收

#### `t2_spring`

必须：

* runtime success；
* semantic success；
* bbox z 接近 prompt 高度；
* volume 不小于理论值 55%；
* helix turns 被正确体现在 centerline 或 bbox/volume 中。

#### `Long Helix Spring`

必须：

* 不再体积 2.2%；
* 如果 OCCT sweep 崩溃，则 fallback 或 fail runtime；
* 不允许输出短单圈 solid 并标记 success。

#### `Dense Rib Plate`

必须：

* leaf features 使用 `add_rib`，不是 composition boolean；
* 若 LLM 仍输出 boolean_union，feature sequence validation 或 composition governance 必须拒绝；
* 如果系统能确定是 rib，则 repair 可建议重规划，但不得 silent fix 成成功。

#### `Shelled Housing`

必须：

* shell node 消费 base solid；
* shell 输出继续作为后续 cut/boss/rib 输入；
* 不再因 input=0 runtime fail。

#### `Large Thin Shell`

必须：

* shell thickness preflight 能拒绝不合理厚度；
* add_boss 不得 input=0；
* 如果 wiring 缺失，assembly fail，而不是 preflight 才发现。

#### `Multi-Pipe System`

必须：

* OCCT sweep crash 被捕获；
* 尝试 fallback；
* fallback 成功则 `PASS_DEGRADED`；
* fallback 失败则 `FAIL_RUNTIME`；
* 不得标记普通 success。

---

## 11. Claude Code 实施顺序

严格按此顺序实施，不要并行大改：

### Step 1：建立 failing tests

先新增测试，确认当前代码失败：

```bash
cd E:\auto_detection_process\integrations\engineering_tools
python -m pytest tests\generative_cad\authoring\test_strict_schema_pipeline.py -v
python -m pytest tests\generative_cad\authoring\test_raw_assembler_typed_wiring.py -v
python -m pytest tests\generative_cad\dialects\loft_sweep\test_helix_sweep_geometry.py -v
```

### Step 2：接入 strict schema

只改 `pipeline.py` 和 `prompt_builders.py`。跑 authoring schema tests。

### Step 3：重构 raw assembler

只改 `raw_assembler.py`。跑 typed wiring tests。确保所有 assembly fail 都是 structured failure。

### Step 4：修 helix_sweep

只改 `loft_sweep/handlers.py` 和必要 preflight。跑 helix tests。

### Step 5：加 semantic postcheck

新增 runtime semantic files，接入 build pipeline。跑 semantic tests。

### Step 6：修 composition governance

改 composition validation 与 prompt。跑 composition tests。

### Step 7：修 shell integration

改 shell dialect/preflight，确认 typed wiring 已覆盖。跑 shell tests。

### Step 8：修 3D sweep fallback

改 loft_sweep helper。跑 sweep tests。

### Step 9：重跑本地 test_model/stress20

```bash
cd E:\auto_detection_process
python demo_output_v5\run_test_model.py
python demo_output_v5\run_stress20.py
```

生成新的：

```text
demo_output_v5\test_model_output\AUDIT_REPORT_V5_1.md
demo_output_v5\stress20_output\AUDIT_REPORT_V5_1.md
```

---

## 12. Definition of Done

本工程完成必须满足：

1. `authoring/pipeline.py` 不再出现生产调用 `tool_schema={}`。
2. `raw_assembler.py` 不再使用 `last_solid` 作为唯一接线机制。
3. `_build_inputs()` 不再 missing input 时返回空列表。
4. `create_sweep_path → sweep_profile` 自动接 curve。
5. `boolean_union` 二输入正确，三输入以上自动 pairwise expansion。
6. `shell_body` 自动消费上一 solid 并输出新 solid。
7. `helix_sweep` 使用 `turns` 和 `height_mm`。
8. 弹簧类 case 不再以严重错误体积通过。
9. `semantic_postcheck.json` 出现在每个成功构建 case 目录。
10. `PASS_FULL` 与 `PASS_DEGRADED` 被明确区分。
11. `FAIL_SEMANTIC` 不得被计入 success。
12. 旧 primitive 链路未被修改。
13. 无新增 part-specific dialect/op。
14. 所有新增 prompt builder 有测试。
15. 所有新增 validation 规则有测试。
16. 所有新增 runtime fallback 有日志和 metadata。

---

## 13. 最小代码骨架参考

### 13.1 `prompt_builders.py`

```python
from __future__ import annotations

import json
from typing import Any

ROUTE_SYSTEM_PROMPT = """..."""

FEATURE_SEQUENCE_SYSTEM_PROMPT = """..."""

NODE_PARAMS_SYSTEM_PROMPT = """..."""

REPAIR_SYSTEM_PROMPT = """..."""

def compact_json(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def build_route_user_prompt(user_request: str, dialect_summary: str) -> str:
    return f"""USER REQUEST:
{user_request}

AVAILABLE DIALECTS:
{dialect_summary}

Return only the strict tool call arguments.
"""

def build_feature_sequence_user_prompt(
    user_request: str,
    route_plan: Any,
    ctx: Any,
    operation_summary: str,
) -> str:
    return f"""USER REQUEST:
{user_request}

ROUTE PLAN:
{compact_json(route_plan)}

AUTHORING CONTEXT:
{compact_json(ctx)}

ALLOWED OPERATIONS:
{operation_summary}

Return only the strict tool call arguments.
"""

def build_node_params_user_prompt(
    user_request: str,
    route_plan: Any,
    feature_sequence: Any,
    node_plan: Any,
    op_contract: str,
    design_intent: Any,
) -> str:
    return f"""USER REQUEST:
{user_request}

ROUTE PLAN:
{compact_json(route_plan)}

CURRENT NODE:
{compact_json(node_plan)}

OPERATION CONTRACT:
{op_contract}

FEATURE SEQUENCE:
{compact_json(feature_sequence)}

KNOWN DESIGN INTENT:
{compact_json(design_intent)}

Return only the strict tool call arguments for this one node.
"""

def build_repair_user_prompt(
    current_doc: dict,
    validation_issues: list[dict],
    repairable_paths: list[str],
    forbidden_paths: list[str],
) -> str:
    return f"""VALIDATION ISSUES:
{compact_json(validation_issues)}

REPAIRABLE PATHS:
{compact_json(repairable_paths)}

FORBIDDEN PATHS:
{compact_json(forbidden_paths)}

CURRENT DOCUMENT:
{compact_json(current_doc)}

Return only the strict repair patch tool arguments.
"""
```

### 13.2 `AssemblyError`

```python
class AssemblyError(ValueError):
    """Fail-closed error raised by RawGcadDocument assembly."""
```

### 13.3 `ValueRef`

```python
@dataclass(frozen=True)
class ValueRef:
    node_id: str
    output_name: str
    value_type: str
    component_id: str
    dialect: str
    op: str

    def as_input(self) -> dict[str, str]:
        return {"node": self.node_id, "output": self.output_name}
```

### 13.4 `SemanticPostcheckReport`

```python
class SemanticPostcheckReport(BaseModel):
    semantic_valid: bool
    measured: MeasuredGeometry
    issues: list[SemanticIssue] = Field(default_factory=list)
```

---

## 14. 不允许的实现捷径

Claude Code 不得采用以下“看似能过测试”的捷径：

1. 不得在 helix_sweep 中简单把 volume 伪造进 metadata。
2. 不得用 scale 放大错误弹簧来满足 bbox。
3. 不得在 validation 中删除失败 node 来通过。
4. 不得把所有 semantic checks 设成 warning。
5. 不得把 `boolean_union` 改成 variadic 而不更新 OperationSpec、validation、runtime。
6. 不得让 LLM 输出 input refs 来绕过 assembler typed wiring。
7. 不得修改测试期望以适配错误几何。
8. 不得把 runtime exception 吞掉后输出空 STEP。
9. 不得以 SolidWorks import 成功替代几何语义正确性。
10. 不得把 primitive 链路混入 generative path 来掩盖 dialect 能力不足。

---

## 15. 最终交付物

Claude Code 完成后必须提交：

1. 源码 patch。
2. 新增/更新测试。
3. 新版 `AUDIT_REPORT_V5_1.md`。
4. 新版 `semantic_postcheck.json` 示例。
5. 新版 `output.metadata.json` 示例。
6. 一份 `MIGRATION_NOTES_V5_1.md`，说明：

   * strict schema 接入；
   * typed wiring 变更；
   * helix 修复；
   * semantic status 新字段；
   * 旧测试结果为什么会从 success 变成 semantic fail；
   * 对外 API 是否兼容。

---

## 16. 优先级总结

第一优先级：

* strict schema 接入；
* raw assembler typed wiring；
* helix_sweep turns/height 修复；
* semantic postcheck。

第二优先级：

* composition governance；
* shell integration；
* 3D sweep fallback；
* prompt builders。

第三优先级：

* capability matrix；
* richer design intent extraction；
* better SolidWorks/NX-style feature semantics；
* long-term dialect expansion。

完成第一优先级前，不要投入大量时间继续调 LLM prompt。因为当前主要错误来自 compiler 边界断裂，而不是模型单独能力不足。
