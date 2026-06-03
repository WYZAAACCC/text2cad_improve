

> 现阶段只做 STEP 是正确选择。不要现在投入 SolidWorks/NX native feature tree。当前代码中的 SW/NX 工具本身也明确是“把 validated generative STEP 导入为 SLDPRT/PRT”，并且不重建 native feature tree。这个边界应该保留。([GitHub][1])

---

# 一、总体目标

本轮修复的目标是：

> **将 Text → G-CAD staged authoring → RawGcadDocument → audited autofix → canonical IR → runtime → validated STEP 这条链路做成稳定、强约束、可复现、可评测的主链路。**

具体结果应该是：

1. LLM 不再直接生成完整 `RawGcadDocument`。
2. LLM 只生成三类小对象：`RoutePlan`、`FeatureSequenceDraft`、单节点 `NodeParamsDraft`。
3. 系统用 `raw_assembler.py` 填充所有固定字段、outputs、op versions、root node、safety、constraints。
4. 所有 LLM 调用必须使用 operation-specific strict tool schema。
5. `direction: "Z"`、`target: "all_outer_edges"`、`path_points: [{x,y,z}]` 这类错误要么被 strict schema 阻止，要么进入受审计的 autofix。
6. `industrial_flange`、`engine_mount`、`exhaust_pipe` 必须能重新生成 STEP，且报告中清楚区分 raw、autofix、canonical、runtime、artifact。
7. 不要触碰 primitive 链路，不要做 SolidWorks/NX native，不要把 `loft_sweep` 做成 part-specific primitive。

---

# 二、当前代码状态与修复依据

## 2.1 已有 staged authoring 设计，但没有完整接上 strict schema

当前 `authoring/schemas.py` 已经定义了正确的分阶段对象：`RoutePlan`、`FeatureSequenceDraft`、`NodeParamsDraft`。源码注释也明确说，LLM 不应该一次性输出巨大的 RawGcadDocument，而应该输出三个更小对象，再由系统组装。([GitHub][2])

但是 `authoring/pipeline.py` 中对 route、feature sequence、node params、repair 的 `call_strict_tool` 调用仍然传入 `tool_schema={}`。这意味着虽然接口名字叫 strict tool，但实际没有把强 schema 传给模型。([GitHub][3])

这是本轮最高优先级修复点。

---

## 2.2 strict schema 编译器已存在，但需要正确使用

`authoring/strict_schema.py` 已经提供 `to_deepseek_strict_schema` 和 `strict_schema_from_pydantic`，并且会把 object 处理成 DeepSeek strict mode 需要的形式：`additionalProperties=false`、所有字段 required、保留 enum/const。它也说明 `minItems/maxItems` 等 DeepSeek 不支持的约束会被移入本地验证提示，因此本地 Pydantic/OperationSpec validation 仍然必须保留。([GitHub][4])

所以修复策略不是“只依赖 provider strict schema”，而是：

```text
provider strict schema 阻止大部分 hallucination
+
本地 Pydantic / OperationSpec validation 作为最终裁决
```

---

## 2.3 raw assembler 已经非常接近正确答案，但 wiring 需要修复

`raw_assembler.py` 的注释明确规定：LLM 不应写 `schema_version`、`trust_level`、`safety`、`constraints`、dialect versions、op versions、outputs、linear wiring；系统会确定性填充这些字段。([GitHub][5])

但当前 `_build_inputs` 只跟踪 `last_solid`。这对 `axisymmetric` 和 `sketch_extrude` 基本够用，但对 `loft_sweep` 不够，因为 `create_sweep_path` 输出的是 `curve`，`sweep_profile` 输入需要 `curve`。当前 default registry 已注册 `loft_sweep`，而 `loft_sweep` 的 `sweep_profile` 的 `input_types=["curve"]`，所以 assembler 必须支持“按类型自动接线”，不能只接 solid。([GitHub][6])

---

## 2.4 AutoFixer 已存在，但需要变成受审计 compiler pass

`authoring/auto_fixer.py` 已经包含大量针对 LLM 常见错误的规则，例如参数名修复、`all_outer_edges → all_external_edges`、output name 修复、path point 字段名修复等。([GitHub][7])

但当前主 validation pipeline 是 fail-closed：`structure → registry → params → ownership → graph → typecheck → phase → composition → safety`，canonical 后再做 `dialect_semantics` 和 `geometry_preflight`。这个 pipeline 本身没有 autofix 阶段。([GitHub][8])

这其实是好事：**纯 validation 不应该偷偷修复。** 正确做法是新增一个显式的、带审计报告的 authoring/build wrapper：

```text
raw_original
→ validate raw_original
→ autofix with audit
→ validate raw_fixed
→ canonicalize
→ canonical validation
→ runtime
→ STEP
```

---

## 2.5 现有 demo 失败点与代码约束是对应的

`complex_final/report.json` 当前显示 `industrial_flange`、`engine_mount`、`exhaust_pipe` 失败，其中 flange 是 chamfer params invalid，engine mount 是 `extrude_rectangle` / `cut_rectangular_pocket` params invalid，exhaust pipe 是 `create_sweep_path` 15 个 validation errors。([GitHub][9])

具体 raw 问题包括：

* `engine_mount` 使用 `direction: "Z"`，而当前 sketch extrude params 中 `direction` 是 `Literal["+", "-"]`；但 `draft_angle_deg` 当前已经在模型中存在，所以不要再把 `draft_angle_deg` 当成错误。([GitHub][10])
* `industrial_flange` 使用 `target: "all_outer_edges"`，而 axisymmetric chamfer 只允许 `all_external_edges`；同时它的 `profile_stations` 只有一个，而当前 model 和 handler 都要求至少两个。([GitHub][11])
* `exhaust_pipe` 的 `path_points` 使用 `{x,y,z}`，而 `loft_sweep.params.Point3D` 定义的是 `{x_mm,y_mm,z_mm}`；runtime handler 虽然能容忍 x/y/z fallback，但 validation 在 runtime 前就会拒绝。([GitHub][12])

---

# 三、不要做的事情

Claude Code 必须遵守这些限制：

1. **不要修改 primitive 生成链路。**
2. **不要实现 SolidWorks/NX native backend。** 当前只保证 STEP。
3. **不要让 LLM 输出 CadQuery、SolidWorks COM、NXOpen、Python 脚本。** Level 1 / Level 2 prompt 本来就禁止输出 CAD 代码。([GitHub][13])
4. **不要把 flange、bracket、pipe、housing 这种具体零件做成 dialect 或 op。** 现有 governance 已经禁止 part-named dialect 和 `make_xxx` 具体零件 op，应继续遵守。([GitHub][14])
5. **不要让 `validate_and_canonicalize_with_bundle` 默认 autofix。** validation 必须保持 fail-closed；autofix 只能出现在显式 authoring/build wrapper 中。
6. **不要用静默修复。** 所有修复必须记录 path、old value、new value、rule id、confidence、severity。
7. **不要为了让 demo 过而放宽安全标记。** `reference_geometry`、not manufacturing-ready、not certified 等边界必须保留。

---

# 四、具体修复方案

## Phase 1：新增 strict tool schema 工厂

### 目标

把 `authoring/pipeline.py` 里所有 `tool_schema={}` 替换成真实 schema。

### 新增文件

建议新增：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/tool_schemas.py
```

### 需要实现的函数

```python
def build_route_plan_tool_schema(dialect_registry, primitive_catalog_summary=None) -> dict:
    ...

def build_feature_sequence_tool_schema(ctx: AuthoringContext) -> dict:
    ...

def build_node_params_tool_schema(node_plan, dialect_registry) -> dict:
    ...

def build_repair_patch_tool_schema() -> dict:
    ...
```

### 关键要求

#### 1. route schema

基于 `RoutePlan.model_json_schema()`，然后使用：

```python
strict_schema_from_pydantic(RoutePlan)
```

但要额外约束：

* `selected_dialects[*].dialect` 必须来自 `dialect_registry.list_ids()`。
* `selected_dialects[*].version` 必须来自对应 dialect.version。
* 如果 `route_decision != generative_cad_ir`，后续 pipeline 不进入 CAD IR authoring。

#### 2. feature sequence schema

基于 `FeatureSequenceDraft`，但要额外约束：

* `components[*].owner_dialect` 只能来自 route 选中的 dialect，必要时允许 `"composition"`。
* `node_sequence[*].dialect` 只能来自 route 选中的 dialect，必要时允许 `"composition"`。
* `node_sequence[*].op` 必须属于该 dialect 的 `op_specs()`。
* `node_sequence[*].phase` 必须等于 `OperationSpec.phase`。
* `node_sequence[*].op_version` 必须等于 `OperationSpec.op_version`。
* `FeatureSequenceDraft` 禁止包含 params；这一点现有 schema 已经表达，应保留。([GitHub][2])

#### 3. node params schema

这是最重要的部分。不要直接使用 `NodeParamsDraft.model_json_schema()`，因为它的 `params: dict[str, Any]` 太开放。应构造 operation-specific wrapper：

```python
{
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "node_id": {"const": node_plan.node_id},
    "dialect": {"const": node_plan.dialect},
    "op": {"const": node_plan.op},
    "op_version": {"const": resolved_op_version},
    "params": <spec.params_model.model_json_schema()>,
    "assumptions": {
      "type": "array",
      "items": {"type": "string"}
    }
  },
  "required": ["node_id", "dialect", "op", "op_version", "params", "assumptions"]
}
```

然后对整个 wrapper 调用 `to_deepseek_strict_schema()`。

注意：`minItems/maxItems` 在 provider strict schema 里可能不会被 DeepSeek 执行，所以本地仍必须调用 `spec.validate_params(np.params)`。`strict_schema.py` 代码本身也说明 unsupported keywords 会被移入本地验证提示。([GitHub][4])

---

## Phase 2：修复 `authoring/pipeline.py`

### 目标

让 staged authoring 真正成为主路径。

### 修改点 1：route 阶段

当前：

```python
tool_schema={}
```

改为：

```python
tool_schema=build_route_plan_tool_schema(
    dialect_registry=dialect_registry,
    primitive_catalog_summary=primitive_catalog_summary,
)
```

并且 messages 不要只有 user_request，应包含：

* user_request；
* dialect catalog summary；
* primitive catalog summary；
* safety route rules；
* “do not output CAD code”。

可以复用现有 prompt，但要注意 staged pipeline 的输出对象是 `RoutePlan`，不是旧的 `DialectSelectionPlan`。

### 修改点 2：feature sequence 阶段

当前：

```python
tool_schema={}
```

改为：

```python
tool_schema=build_feature_sequence_tool_schema(ctx)
```

调用后必须本地检查：

```python
validate_feature_sequence_against_context(fs, ctx, dialect_registry)
```

新增函数建议放在：

```text
authoring/validators.py
```

检查规则：

1. `components` 非空。
2. `node_sequence` 非空。
3. 每个 node 的 `component_id` 存在。
4. 每个 node 的 dialect 被 route 选中，或是 composition。
5. 每个 op 存在。
6. phase 与 OperationSpec.phase 一致。
7. op_version 与 OperationSpec 一致。
8. node_id 唯一。
9. phase 顺序不严重倒置；真正 DAG/phase 仍由后续 validation 判断。

### 修改点 3：node params 阶段

当前：

```python
tool_schema={}
```

改为：

```python
tool_schema=build_node_params_tool_schema(node_plan, dialect_registry)
```

调用后必须做强一致性检查：

```python
np = NodeParamsDraft.model_validate(tc_result.arguments)

if np.node_id != node_plan.node_id:
    fail

if np.dialect != node_plan.dialect:
    fail

if np.op != node_plan.op:
    fail

if np.op_version != resolved_op_version:
    fail

spec.validate_params(np.params)
```

这一步能阻止 `engine_mount` 中的 `direction: "Z"`。当前 params model 明确要求 sketch extrude 的 `direction` 是 `"+"` 或 `"-"`。([GitHub][15])

### 修改点 4：repair 阶段

repair caller 也不能传空 schema。应使用 `RepairPatchV2.model_json_schema()` 加 strict schema。

但建议 repair 阶段优先级低于 deterministic AutoFixer：

```text
validation failed
→ deterministic autofix
→ revalidate
→ if still failed, then LLM repair
```

---

## Phase 3：修复 `raw_assembler.py` 的类型化 wiring

### 当前问题

`raw_assembler.py` 当前设计正确，但 `_build_inputs` 只围绕上一个 solid 自动接线。对于 `loft_sweep`：

```text
create_sweep_path → outputs curve
sweep_profile → inputs curve
```

当前 assembler 无法自然接上 curve 链路。`loft_sweep` 的 operation spec 明确 `create_sweep_path` 输出 `curve`，`sweep_profile` 输入 `curve`。([GitHub][16])

### 需要修改

把当前：

```python
last_solid: dict[str, str | None]
```

改成：

```python
last_output_by_type: dict[str, dict[str, tuple[str, str]]]
```

含义：

```python
{
  component_id: {
    "solid": ("n_base", "body"),
    "curve": ("node_path", "curve"),
    "frame": ("n_revolve", "outer_frame")
  }
}
```

### 输出名映射

保留现有 `_OUTPUT_NAME_MAP`，但新增一个 helper：

```python
def _output_name_for_type(vtype: str) -> str:
    return _OUTPUT_NAME_MAP.get(vtype, vtype)
```

这已经存在，应继续使用。([GitHub][5])

### 新 `_build_inputs` 逻辑

```python
def _build_inputs(node_plan, last_output_by_type, dialect_registry):
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        return []

    spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
    inputs = []

    for required_type in spec.input_types:
        prev = last_output_by_type.get(node_plan.component_id, {}).get(required_type)
        if prev is None:
            return []
        producer_node, output_name = prev
        inputs.append({"node": producer_node, "output": output_name})

    return inputs
```

### 更新 last outputs

每个 node 的 outputs 生成后，对所有 output 更新：

```python
for o in outputs:
    last_output_by_type[node_plan.component_id][o["type"]] = (
        node_plan.node_id,
        o["name"],
    )
```

### root node

component 的 `root_node` 仍然应该是最后一个 solid-producing node。也就是说：

```python
if output type == "solid":
    last_solid[component_id] = node_id
```

可以保留 `last_solid` 只用于 root_node，但 inputs 不能只依赖 solid。

### 验收标准

`exhaust_pipe` 走 staged authoring 时，assembled raw 应自动形成：

```json
"node_path": outputs [{"name": "curve", "type": "curve"}]

"node_sweep": inputs [{"node": "node_path", "output": "curve"}]
```

而不是空 inputs。

---

## Phase 4：修复 axisymmetric 的 simple cylinder 表达

### 当前问题

`industrial_flange` 的 base blank 是一个简单圆柱，LLM 输出单个 station：

```json
{ "r_mm": 100, "z_front_mm": 0, "z_rear_mm": 25 }
```

这从 CAD 语义上是合理的：它就是一个半径 100、高度 25 的圆柱。当前 `RevolveProfileParams` 要求 `profile_stations` 至少两个，handler 也硬编码 “Need at least 2 profile stations”，preflight 还要求 radius range 有 max > min。([GitHub][17])

这不是 LLM 的错误，而是 IR 设计对简单圆柱不友好。

### 修改建议

#### 修改 1：Pydantic model

文件：

```text
bases/axisymmetric/models.py
```

把：

```python
profile_stations: list[ProfileStation] = Field(min_length=2)
```

改成：

```python
profile_stations: list[ProfileStation] = Field(min_length=1)
```

#### 修改 2：handler

文件：

```text
dialects/axisymmetric/handlers.py
```

把：

```python
if len(stations) < 2:
    raise ValueError("Need at least 2 profile stations")
```

改成：

```python
if len(stations) < 1:
    raise ValueError("Need at least 1 profile station")
```

并确保单 station 时生成封闭矩形轮廓：

```python
if len(stations) == 1:
    s = stations[0]
    r = float(s["r_mm"])
    zf = float(s.get("z_front_mm", 0))
    zr = float(s.get("z_rear_mm", 0))
    if zr <= zf:
        raise ValueError("z_rear_mm must be > z_front_mm")
    result = (
        cq.Workplane("XZ")
        .moveTo(r, zf)
        .lineTo(r, zr)
        .lineTo(0, zr)
        .lineTo(0, zf)
        .close()
        .revolve(360, (0, 0, 0), (0, 0, 1))
    )
```

多 station 逻辑可以暂时保持现有实现，但也要保留 z/r finite 检查。

#### 修改 3：preflight

文件：

```text
dialects/axisymmetric/dialect.py
```

把：

```python
if len(ps) < 2:
    error
```

改成：

```python
if len(ps) < 1:
    error
```

把：

```python
elif max_r <= 0 or min_r <= 0 or max_r <= min_r:
    error
```

改成：

```python
elif max_r <= 0 or min_r <= 0:
    error
else:
    profile_max_radius = max_r
    profile_min_radius = min_r
```

允许 `profile_max_radius == profile_min_radius`。这是简单圆柱，不是错误。

### 为什么这比 autofix 更好

不要用 AutoFixer 把一个 station 复制成两个 station。那是伪修复，而且可能制造重复点或零宽台阶。正确做法是让 IR 支持单段旋转体。

---

## Phase 5：实现 audited AutoFixer

### 目标

把已有 `auto_fix(raw_doc)` 改造成可审计 pass。

### 修改文件

```text
authoring/auto_fixer.py
```

### 新增数据结构

可以用 Pydantic 或 dataclass，建议 Pydantic，便于 JSON dump：

```python
class AutoFixEntry(BaseModel):
    rule_id: str
    path: str
    old_value: Any
    new_value: Any
    severity: Literal["safe_alias", "semantic_guess", "destructive"]
    confidence: float
    message: str

class AutoFixReport(BaseModel):
    applied: bool
    before_hash: str
    after_hash: str
    entries: list[AutoFixEntry] = []
```

### 新增函数

```python
def auto_fix_with_report(
    raw_doc: dict,
    dialect_registry=None,
) -> tuple[dict, AutoFixReport]:
    ...
```

要求：

1. 不要原地修改输入，必须 `copy.deepcopy(raw_doc)`。
2. 每条修复都要记录。
3. 修复后 hash 必须变化；如果没变化，`applied=false`。
4. 保留现有 `auto_fix(raw_doc)` 作为兼容 wrapper，但内部调用 `auto_fix_with_report(...)[0]`。

### 修复规则分级

#### safe_alias，可自动应用

这些可以自动修：

```text
all_outer_edges → all_external_edges
outer_edges → all_external_edges
solid output name → body
frame output name → outer_frame
{x,y,z} point → {x_mm,y_mm,z_mm}
hole_diameter_mm → hole_dia_mm
diameter → diameter_mm
```

这些规则已经大多存在于当前 AutoFixer 中。([GitHub][7])

#### semantic_guess，可自动应用但必须降级标记

```text
direction: "Z" → "+"
```

只允许在以下条件同时满足时修：

```text
op in {"extrude_rectangle", "cut_rectangular_pocket"}
plane == "XY"
direction == "Z"
```

否则不要修。原因：如果 plane 是 `YZ` 或 `XZ`，`Z` 到 `+/-` 的映射就不是显然的。

#### destructive，默认不要自动应用

不要默认删除未知字段。当前 sketch extrude 已经包含 `draft_angle_deg`，所以 engine_mount 中这个字段不再应被删除。([GitHub][15])

如果未来遇到未知字段，建议 report 中记录，但让 validation fail，交给 LLM repair 或人工修复。

---

## Phase 6：新增 authoring build wrapper，不污染 core validation

### 新增文件

```text
authoring/build_pipeline.py
```

或在现有 `authoring/pipeline.py` 中新增清晰函数。建议新文件，避免把原 pipeline 变得更混乱。

### 新增主函数

```python
def generate_validate_build_step(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry,
    base_package_registry,
    out_dir: Path,
    allow_autofix: bool = True,
    max_repair_attempts: int = 2,
) -> AuthoringBuildResult:
    ...
```

### 输出目录结构

每个 case 输出：

```text
out_dir/
  prompt.txt
  route_plan.json
  feature_sequence.json
  node_params/
    <node_id>.json
  raw_original.json
  raw_original_validation.json
  autofix_report.json
  raw_fixed.json
  raw_fixed_validation.json
  canonical.json
  validation_bundle.json
  runtime_report.json
  metadata.json
  output.step
  report_v2.json
```

### report_v2.json 格式

```json
{
  "case_id": "industrial_flange",
  "ok": true,
  "step_ok": true,
  "raw_original_valid": false,
  "autofix_applied": true,
  "raw_fixed_valid": true,
  "canonical_valid": true,
  "runtime_valid": true,
  "artifact_valid": true,
  "semantic_valid": null,
  "final_error": null,
  "hashes": {
    "raw_original": "...",
    "raw_fixed": "...",
    "canonical": "...",
    "step_sha256": "..."
  },
  "autofix": {
    "entries": [
      {
        "rule_id": "target_alias_all_outer_edges",
        "path": "/nodes/4/params/target",
        "old_value": "all_outer_edges",
        "new_value": "all_external_edges",
        "severity": "safe_alias",
        "confidence": 1.0
      }
    ]
  },
  "validation_stages_run": [
    "structure",
    "registry",
    "params",
    "ownership",
    "graph",
    "typecheck",
    "phase",
    "composition",
    "safety",
    "canonicalize",
    "dialect_semantics",
    "geometry_preflight"
  ]
}
```

### 注意

`run_gcad_core` 和 `validate_and_canonicalize_with_bundle` 不要默认 autofix。`run_gcad_core` 当前 raw entrypoint 是 validate + canonicalize 后进入 runtime；保持这个纯路径。([GitHub][18])

---

## Phase 7：加强 `loft_sweep` 的 validation/preflight

### 当前问题

`loft_sweep` 当前 `validate_component` 和 `preflight_component` 直接返回 ok，这意味着它没有做真实几何预检。([GitHub][16])

### 修复目标

先不要追求复杂工业管路，只做足够稳的 STEP 生成质量门。

### 修改文件

```text
dialects/loft_sweep/dialect.py
```

### validate_component 规则

至少实现：

1. 如果 component 使用 `sweep_profile`，必须有且仅有一个前置 `create_sweep_path`，或者每个 `sweep_profile` 的 input 能解析到 curve。
2. `create_sweep_path` 必须在 `sweep_profile` 之前。
3. component root node 最终必须输出 `body:solid`。
4. `sweep_profile` 必须消费 `curve`，输出 `solid`。
5. 不允许多个互不相连的 solid root。

### preflight_component 规则

至少实现：

1. `path_points` 数量 ≥ 2。
2. 每个点坐标 finite。
3. 相邻点距离 > 0.1mm。
4. 若 sweep circle，则 `radius_mm > 0`。
5. `radius_mm` 小于最短 path segment 的 0.45 倍。
6. 非相邻点过近时 warning 或 error，避免明显自交。
7. 如果 path 点中有 `{x,y,z}`，这不应该到达 canonical；若到达，报 error，因为 params validation 理应已经挡住。

### handler 注意

`loft_sweep/handlers.py` 里 `handle_sweep_profile` 目前会将 path 点转成 CadQuery vectors，并尝试用 spline sweep。它还做了一个简单的自交 heuristic。这个可以保留，但 validation 不应依赖 runtime fallback。([GitHub][19])

---

## Phase 8：增强 `sketch_extrude` 的几何预检

### 当前核心目标

确保 `engine_mount` 这种板件支架能够稳定生成 STEP，不要求真实工程强度，只要求几何合理、封闭实体、尺寸不明显越界。

### 文件

```text
dialects/sketch_extrude/dialect.py
```

### 必须检查

1. base_solid 必须唯一，且 op 是 `extrude_rectangle`。当前已有类似检查，应保留。([GitHub][20])
2. `cut_rectangular_pocket.depth_mm < base.depth_mm`。
3. hole pattern 总 span 不能超出 base plate：

   ```python
   span_x = (count_x - 1) * spacing_x_mm + hole_dia_mm
   span_y = (count_y - 1) * spacing_y_mm + hole_dia_mm
   ```

   要求：

   ```python
   span_x <= base_width_mm - 2 * margin
   span_y <= base_height_mm - 2 * margin
   ```
4. 单孔位置必须落在 base bounding rectangle 内，并保留 margin。
5. boss/rib 的 position 不要明显超出 base。
6. fillet/chamfer radius/distance 不能超过 base 最小厚度的 0.45 倍。

### 注意

不要把这些检查写成“制造合格”。它们只是 reference geometry preflight。

---

## Phase 9：新增 demo regression tests

### 测试目标

不要只测代码单元，要测三个失败 demo 的闭环。

### 建议新增目录

```text
integrations/engineering_tools/tests/generative_cad/test_complex_final_regression.py
```

### 必须测试

#### test_industrial_flange_raw_can_autofix_and_build

输入使用当前 demo 的 `industrial_flange/llm_raw.json`。

期望：

1. raw_original validation fail。
2. autofix 应至少修复 `all_outer_edges → all_external_edges`。
3. 如果执行了 Phase 4，单 station 应直接合法，不需要复制 station。
4. raw_fixed validation ok。
5. canonical ok。
6. runtime 输出 STEP。
7. STEP 文件存在且 size > 0。

#### test_engine_mount_raw_can_autofix_and_build

输入使用当前 demo 的 `engine_mount/llm_raw.json`。

期望：

1. raw_original validation fail，因为 `direction: "Z"`。
2. autofix 在 `plane == "XY"` 时修为 `"+"`。
3. `draft_angle_deg` 保留，因为当前 model 支持该字段。([GitHub][15])
4. raw_fixed validation ok。
5. runtime 输出 STEP。

#### test_exhaust_pipe_raw_can_autofix_and_build

输入使用当前 demo 的 `exhaust_pipe/llm_raw.json`。

期望：

1. raw_original validation fail，因为 `path_points` 使用 x/y/z。
2. autofix 把 x/y/z 改为 x_mm/y_mm/z_mm。
3. raw_fixed validation ok。
4. assembler typed wiring 单测要证明 `sweep_profile` 可以自动消费 `create_sweep_path` 的 curve。
5. runtime 输出 STEP。

---

# 五、最重要的验收标准

Claude Code 完成后，必须满足这些条件。

## 5.1 功能验收

1. `industrial_flange` 可输出 STEP。
2. `engine_mount` 可输出 STEP。
3. `exhaust_pipe` 可输出 STEP。
4. `bearing_housing`、`gearbox_housing`、`turbine_disk`、`hydraulic_cap` 不回退。
5. 所有输出都有 `metadata.json` 和 `report_v2.json`。
6. `report_v2.json` 中必须能看出是否发生了 autofix。

## 5.2 架构验收

1. LLM 不再直接输出完整 RawGcadDocument。
2. `authoring/pipeline.py` 不再出现 `tool_schema={}`。
3. `raw_assembler.py` 支持按 input/output type 自动 wiring，不只支持 solid。
4. `validate_and_canonicalize_with_bundle` 保持纯 validation，不默认 autofix。
5. AutoFixer 有审计报告。
6. `loft_sweep` 不再是完全空 preflight。
7. 不新增任何 part-specific dialect/op。

## 5.3 质量验收

1. 新增测试覆盖三个失败 demo。
2. 测试必须验证 raw invalid 与 fixed valid 的状态区别。
3. 测试必须验证 STEP 文件存在且非空。
4. 不允许通过修改 demo raw 文件来“修复”测试；测试应验证 pipeline 能处理这些 raw 问题。
5. 不允许通过跳过 validation 来生成 STEP。

---

# 六、给 Claude Code 的高质量执行 Prompt

下面这段可以直接复制给 Claude Code。

```text
你是一个资深 CAD 编译器与 Python 工程架构工程师。请在当前仓库 WYZAAACCC/seekflow-engineering 中修复 generative_cad 的 STEP 生成链路。只做 STEP，不做 SolidWorks/NX native feature tree。不要修改 primitive 生成链路。不要新增任何 part-specific dialect 或 make_flange/make_bracket 之类操作。

背景：
当前 generative_cad 已有 staged authoring 设计：RoutePlan、FeatureSequenceDraft、NodeParamsDraft；也已有 raw_assembler、strict_schema、validation pipeline、AutoFixer、runtime。但 authoring/pipeline.py 中 call_strict_tool 仍然传 tool_schema={}，导致 strict schema 没真正生效。raw_assembler 当前只按 last_solid 接线，不能正确支持 loft_sweep 的 curve → sweep_profile 链路。AutoFixer 有规则但没有受审计报告。axisymmetric 的 revolve_profile 目前要求至少 2 个 profile_stations，导致简单圆柱法兰 blank 的单 station 表达失败。loft_sweep 的 validate_component/preflight_component 目前基本 no-op。

任务目标：
把 Text → staged authoring → RawGcadDocument → audited autofix → canonical IR → runtime → validated STEP 做成稳定、强约束、可复现链路。修复后 demo_output_v5/complex_final 中 industrial_flange、engine_mount、exhaust_pipe 这三个失败样例应能通过 explicit autofix/build wrapper 输出 STEP；已有成功样例不能回退。

必须完成：

1. 新增 authoring/tool_schemas.py
   - 实现 build_route_plan_tool_schema(dialect_registry, primitive_catalog_summary=None)
   - 实现 build_feature_sequence_tool_schema(ctx)
   - 实现 build_node_params_tool_schema(node_plan, dialect_registry)
   - 实现 build_repair_patch_tool_schema()
   - 使用 authoring/strict_schema.py 中的 to_deepseek_strict_schema 或 strict_schema_from_pydantic。
   - node params schema 必须是 operation-specific wrapper，不允许直接使用 NodeParamsDraft 的 params: dict[str, Any] 开放 schema。
   - node params wrapper 必须 const 约束 node_id、dialect、op、op_version，并把 params 设为对应 OperationSpec.params_model 的 schema。

2. 修改 authoring/pipeline.py
   - 所有 call_strict_tool 不得再传 tool_schema={}。
   - route、feature_sequence、node_params、repair 都要传真实 schema。
   - node params 返回后必须检查 node_id/dialect/op/op_version 与当前 node_plan 完全一致。
   - 必须调用 spec.validate_params(np.params)。
   - deterministic AutoFixer 应在 raw validation 失败后、LLM repair 前尝试。
   - validate_and_canonicalize_with_bundle 本身不要改成默认 autofix。

3. 修改 authoring/raw_assembler.py
   - 当前只跟踪 last_solid。改为按 output type 跟踪 last_output_by_type。
   - _build_inputs 应根据 OperationSpec.input_types 自动选择最近的同类型输出：
     solid → body
     frame → outer_frame
     curve → curve
     profile → profile
     sketch → sketch
   - root_node 仍然选择最后一个 solid-producing node。
   - 必须支持 loft_sweep: create_sweep_path 输出 curve，sweep_profile 自动输入该 curve。
   - 不要让 LLM 决定 outputs、op_version、safety、constraints、root_node。

4. 修改 authoring/auto_fixer.py
   - 新增 AutoFixEntry 和 AutoFixReport。
   - 新增 auto_fix_with_report(raw_doc, dialect_registry=None) -> tuple[dict, AutoFixReport]。
   - 不要原地修改 raw_doc，必须 deepcopy。
   - 每条修复必须记录 rule_id、path、old_value、new_value、severity、confidence、message。
   - 保留 auto_fix(raw_doc) 兼容函数，内部调用 auto_fix_with_report 并返回 fixed_doc。
   - safe_alias 可自动修：
     all_outer_edges/outer_edges/external_edges/all_edges → all_external_edges
     output solid → body
     output frame → outer_frame
     point {x,y,z} → {x_mm,y_mm,z_mm}
     common parameter aliases such as hole_diameter_mm → hole_dia_mm
   - semantic_guess 可自动修：
     direction "Z" → "+" 仅限 op in {"extrude_rectangle","cut_rectangular_pocket"} 且 plane == "XY"。
   - 不要默认删除未知字段。当前 draft_angle_deg 在 sketch_extrude model 中合法，不能删除。

5. 修改 axisymmetric
   - bases/axisymmetric/models.py: RevolveProfileParams.profile_stations 从 min_length=2 改为 min_length=1。
   - dialects/axisymmetric/handlers.py: handle_revolve_profile 支持单 station。单 station 表示一个简单圆柱段，按 r_mm、z_front_mm、z_rear_mm 生成封闭矩形截面并 revolve。
   - dialects/axisymmetric/dialect.py: preflight_component 允许单 station；允许 profile_max_radius == profile_min_radius；只要求 radius > 0 且 z_rear_mm > z_front_mm。
   - 不要用 AutoFixer 复制 station 来伪造两个 station。

6. 修改 loft_sweep
   - dialects/loft_sweep/dialect.py 中 validate_component 不得直接 ok。
   - 至少检查 sweep_profile 必须消费 curve，输出 solid；create_sweep_path 必须先于 sweep_profile；component root node 必须输出 body solid。
   - preflight_component 至少检查：
     path_points >= 2
     坐标 finite
     相邻点距离 > 0.1mm
     circle radius_mm > 0
     radius_mm < shortest_segment_length * 0.45
     明显重复/过近非相邻点给 error 或 warning
   - 不要把 loft_sweep 改成 exhaust_pipe 专用 dialect。

7. 增强 sketch_extrude preflight
   - 保留已有 base_solid 唯一性检查。
   - 检查 pocket depth < base depth。
   - 检查 linear hole pattern span 不超过 base plate 尺寸。
   - 检查 cut_hole position 在 base rectangle 内。
   - 检查 fillet/chamfer radius/distance 不超过 base 最小厚度的 0.45。
   - 这些都是 reference geometry preflight，不要声称 manufacturing-ready。

8. 新增 authoring/build_pipeline.py 或等价清晰入口
   - 实现 generate_validate_build_step(...)
   - 输出目录必须包含：
     prompt.txt
     route_plan.json
     feature_sequence.json
     node_params/<node_id>.json
     raw_original.json
     raw_original_validation.json
     autofix_report.json
     raw_fixed.json
     raw_fixed_validation.json
     canonical.json
     validation_bundle.json
     runtime_report.json
     metadata.json
     output.step
     report_v2.json
   - report_v2.json 必须区分：
     raw_original_valid
     autofix_applied
     raw_fixed_valid
     canonical_valid
     runtime_valid
     artifact_valid
     semantic_valid，当前可为 null
   - 记录 raw/canonical/step hash。

9. 新增 regression tests
   - 使用 demo_output_v5/complex_final/industrial_flange/llm_raw.json
   - 使用 demo_output_v5/complex_final/engine_mount/llm_raw.json
   - 使用 demo_output_v5/complex_final/exhaust_pipe/llm_raw.json
   - 测试 raw_original validation fail，autofix 后 validation ok，runtime 输出非空 STEP。
   - 单独测试 raw_assembler typed wiring：create_sweep_path 的 curve 必须自动接到 sweep_profile。
   - 测试不要通过修改 demo raw 文件实现；要验证 pipeline 能处理这些历史 raw 问题。

验收：
- authoring/pipeline.py 不再出现 tool_schema={}。
- validate_and_canonicalize_with_bundle 保持 fail-closed，不默认修复。
- industrial_flange、engine_mount、exhaust_pipe 都能通过 explicit autofix/build wrapper 生成 STEP。
- 现有成功 demo 不回退。
- 不新增 SolidWorks/NX native 逻辑。
- 不新增 part-specific dialect/op。
- 所有新/改代码通过现有测试和新增 regression tests。
```

---

# 七、实现优先级建议

如果 Claude Code 一次做不完，按这个顺序完成：

1. **先修 raw_assembler typed wiring。** 这是 `loft_sweep` 能否走 staged authoring 的关键。
2. **再接 strict schemas。** 这是阻止 LLM 继续输出非法 params 的关键。
3. **再做 audited AutoFixer。** 这是处理历史 raw 和模型偶发错误的关键。
4. **再修 axisymmetric 单 station。** 这是 flange blank 的根本建模表达问题。
5. **再补 loft_sweep/sketch_extrude preflight。**
6. **最后做 report_v2 和 regression tests。**

---

# 八、我对最终架构的评价

修完之后，这条链路应该变成一个真正的“小型 CAD 编译器”：

```text
Natural Language
  ↓
RoutePlan
  ↓
FeatureSequenceDraft
  ↓
Operation-specific NodeParamsDraft
  ↓
System-side RawGcadDocument assembly
  ↓
Raw validation
  ↓
Audited deterministic autofix
  ↓
Canonical IR
  ↓
Dialect runtime
  ↓
Runtime postconditions
  ↓
STEP + metadata + report_v2
```

这比“让 LLM 写完整 JSON”稳定得多，也比“让 LLM 写 CadQuery 脚本”安全得多。当前只做 STEP 完全足够；等这条 compiler-style pipeline 稳定后，再讨论 SolidWorks/NX native feature tree 才有意义。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/tools.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/schemas.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/pipeline.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/strict_schema.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/raw_assembler.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/default_registry.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/auto_fixer.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/demo_output_v5/complex_final/report.json "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/demo_output_v5/complex_final/engine_mount/llm_raw.json "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/demo_output_v5/complex_final/industrial_flange/llm_raw.json "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/demo_output_v5/complex_final/exhaust_pipe/llm_raw.json "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/governance.py "raw.githubusercontent.com"
[15]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/sketch_extrude/models.py "raw.githubusercontent.com"
[16]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/loft_sweep/dialect.py "raw.githubusercontent.com"
[17]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/axisymmetric/models.py "raw.githubusercontent.com"
[18]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "raw.githubusercontent.com"
[19]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/loft_sweep/handlers.py "raw.githubusercontent.com"
[20]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/dialect.py "raw.githubusercontent.com"
