
---

# SeekFlow 双链路 CAD 架构修复工程文档

## 0. 总目标

本次重构目标不是“用 G-CAD 替代 primitive”，而是把 SeekFlow CAD 系统固定成**双链路架构**：

```text
Route A：Deterministic CAD-IR / Primitive Path
  用于高确定性、高精度、工程语义明确、可机械验证的模型。

Route B：Generative G-CAD Core IR Path
  用于自由度更高、拓扑更开放、概念几何 / 参考几何的模型。
```

两条链路并存，互不污染。

当前仓库中 deterministic primitive 链路已经存在：`primitive_compiler.py` 明确写着 primitive route to deterministic geometry kernels，不能走 LLM-generated code，并通过 `PRIMITIVE_COMPILERS` registry 分发。([GitHub][2])
传统 CAD-IR 构建工具 `cadquery_build_from_cad_ir` 仍然接收 `CADPartSpec`，然后进入 `build_cadquery_from_cad_ir()`。([GitHub][3])
自然语言主构建工具 `engineering_build_cad_model` 也仍然以 `CADPartSpec` 为核心，包含 recipe rewrite、primitive parameter normalization、backend choice、primitive canonical STEP import 等逻辑。([GitHub][4])

Generative 链路也已新增：`generative_cad/tools.py` 暴露 `generative_cad_validate_ir` 和 `generative_cad_build_from_ir`，并使用 `RawGcadDocument`、`validate_and_canonicalize()` 和 dialect registry。([GitHub][5])

因此，正确修复方向是：

```text
保留 deterministic primitive path；
保留 generative G-CAD path；
不要让二者互相调用；
不要让二者共享 IR / registry / metadata schema；
只允许二者在 STEP artifact + metadata + inspection 层合流。
```

---

# 1. 当前代码事实与风险判断

## 1.1 Primitive 链路必须保留

当前 deterministic path 由这些模块构成：

```text
ir/cad.py
cadquery_backend/compiler.py
cadquery_backend/primitive_compiler.py
cadquery_backend/builder.py
natural_language/tools.py
geometry_primitives/*
mechanical_validation/*
```

`CADPartSpec` 定义在 `ir/cad.py`，包含 extrude、hole、circular_pattern_holes、fillet、chamfer、recipe、primitive 等 feature 类型。([GitHub][6])
`compile_cad_ir_to_cadquery_script()` 通过 `CADPartSpec.features` 中的 feature type 分发，primitive feature 会调用 `compile_primitive_to_cadquery_script()`。([GitHub][7])
`build_cadquery_from_cad_ir()` 对 primitive path 执行 STEP 输出、metadata sidecar 检查、fallback policy、inspection validation 和 mechanical validation。([GitHub][8])

这个链路的定位是：**高确定性、高精度、工程语义明确、可验证**。

它不能被 generative dialect 替代，也不能让 generative graph 混入 `CADPartSpec.features`。

---

## 1.2 Generative 链路必须独立

当前 generative path 由这些模块构成：

```text
generative_cad/ir/raw.py
generative_cad/ir/canonical.py
generative_cad/dialects/*
generative_cad/validation/*
generative_cad/runtime/*
generative_cad/pipeline/*
generative_cad/builder.py
generative_cad/tools.py
```

`RawGcadDocument` 已经明确是 LLM 唯一允许输出的 generative IR，且使用固定 envelope：`schema_version / document_id / part_name / units / trust_level / selected_dialects / components / nodes / constraints / safety`。([GitHub][9])
`generative_cad/tools.py` 已经把 public generative tools 接到 `RawGcadDocument`、`validate_and_canonicalize()` 和 dialect registry。([GitHub][5])

这个链路的定位是：**自由度更高、拓扑更开放、非制造、非认证、参考几何**。

它不能进入 `PRIMITIVE_COMPILERS`，也不能伪装成 deterministic primitive。

---

## 1.3 当前 generative 代码仍有确定性 bug

虽然 public generative 工具已经切到 v0.2，但当前实现仍有几个关键错误：

1. `builder.py` 先把 raw 输入 canonicalize，然后把 canonical JSON 写入 graph 文件；但 harness 调用的仍是 `run_gcad_core_from_files()`，而该函数会把文件内容再次当 raw 输入送进 `validate_and_canonicalize()`，这会造成 raw/canonical 接线错误。([GitHub][10])
2. `canonicalize.py` 在 input type 无法解析时默认 fallback 为 `"solid"`，这是 typed compiler 中不可接受的行为。([GitHub][11])
3. `registry.py` 文件注释说检查 version match，但实际没有比较 `selected_dialects.version` 与 registered dialect version。([GitHub][12])
4. `composition.dialect.py` 的 in-degree 统计把已经完成的 component input 也当作未满足依赖，会导致 composition graph 不调度。([GitHub][13])
5. `composition` 的 pattern op 声明 `solid_array`，但当前 handler 设计并未形成完整 `SolidArrayHandle` 语义，存在 spec/runtime 不一致风险。([GitHub][13])
6. `axisymmetric.handlers.py` 中 `handle_cut_center_bore()` 会在有输入时先解析当前 node 自己尚未产生的 `"body"` 输出，这是确定性 bug。([GitHub][14])

这些问题必须修，但修复范围应局限在 generative 链路内，不能影响 deterministic primitive 链路。

---

# 2. 双链路顶层架构

## 2.1 两条链路

```text
┌──────────────────────────────────────────────────────────────┐
│                    SeekFlow CAD System                       │
└──────────────────────────────────────────────────────────────┘

Route A：Deterministic CAD-IR / Primitive Path
───────────────────────────────────────────────────────────────
User / NL normalized CAD request
  ↓
CADPartSpec
  ↓
engineering_validate_cad_ir
  ↓
engineering_build_cad_model / cadquery_build_from_cad_ir
  ↓
compile_cad_ir_to_cadquery_script
  ↓
primitive_compiler / deterministic geometry kernels
  ↓
STEP + primitive_metadata
  ↓
inspection + mechanical_validation
  ↓
validated deterministic artifact


Route B：Generative G-CAD Path
───────────────────────────────────────────────────────────────
User / LLM free-form modeling request
  ↓
RawGcadDocument
  ↓
generative_cad_validate_ir
  ↓
validate_and_canonicalize
  ↓
CanonicalGcadDocument
  ↓
generative_cad_build_from_ir
  ↓
dialect runners + runtime object store
  ↓
composition dialect
  ↓
STEP + generative_metadata_v2
  ↓
inspection validation
  ↓
reference geometry artifact
```

## 2.2 二者的合流点

两条链路只允许在这里合流：

```text
STEP file
metadata sidecar
inspection result
artifact record
optional SW/NX canonical STEP import
```

禁止在这些层之前混合：

```text
CADPartSpec 不能包含 G-CAD nodes；
RawGcadDocument 不能包含 PrimitiveFeature；
Primitive compiler 不能调用 generative dialect；
Generative dialect 不能调用 deterministic primitive kernel；
Primitive metadata 和 generative metadata 不能共用 schema；
Primitive mechanical validation 不能被 generative path 自动声明通过。
```

---

# 3. 路由原则

## 3.1 什么时候走 Primitive

必须走 primitive / deterministic path 的情况：

```text
1. 用户要求高精度、高确定性、工程可验证。
2. 用户明确要齿轮、标准渐开线齿轮、涡轮盘等已有 primitive。
3. 用户要求 mechanical validation、标准参数、工业级 BREP。
4. 用户要求 SolidWorks / NX native import 且已有 canonical STEP primitive strategy。
5. 用户要求可复现、可验算、可追踪的工程语义。
6. 用户要求 manufacturing-ready / certified / airworthy 时，系统不能承诺；但若是能建模，也只能走 deterministic path 并保留安全限制。
```

现有 primitive compiler 已有 `involute_spur_gear` 和 `axisymmetric_turbine_disk` 注册，这类模型应继续走 deterministic primitive。([GitHub][2])

## 3.2 什么时候走 Generative G-CAD

可以走 generative path 的情况：

```text
1. 用户需要自由形状探索。
2. 用户描述的是“类似某类结构”的非标准形体。
3. 拓扑不适合现有 primitive。
4. 用户只需要概念几何 / reference geometry。
5. 用户需要组合多个建模范式，例如旋转体 + 拉伸耳板 + boolean union。
6. 用户接受 not_for_manufacturing / no_structural_validation。
```

Generative raw IR 已经包含 `trust_level` 和强制 safety flags，适合表达 reference geometry。([GitHub][9])

## 3.3 路由不能靠自动吞并

不能做：

```text
如果 primitive 不支持，就自动转 generative；
如果 generative validator 失败，就自动转 primitive；
如果 CAD-IR schema 失败，就塞进 G-CAD；
如果 G-CAD dialect 不支持，就写成 primitive；
```

必须显式路由。

建议新增一个只读路由建议工具或模块：

```text
seekflow_engineering_tools.routing.cad_route
```

它只输出建议，不执行构建：

```json
{
  "recommended_route": "primitive" | "generative" | "reject",
  "confidence": 0.0,
  "reasons": [],
  "required_tool": "engineering_build_cad_model" | "generative_cad_build_from_ir",
  "safety_notes": []
}
```

该模块不能调用 builder，不能修改 spec，不能 fallback。

---

# 4. 必须保持的硬隔离边界

## 4.1 IR 隔离

```text
CADPartSpec 只属于 deterministic path。
RawGcadDocument 只属于 generative path。
CanonicalGcadDocument 只属于 generative path。
PrimitiveFeature 不能进入 RawGcadDocument。
GcadNode 不能进入 CADPartSpec。
```

## 4.2 Registry 隔离

```text
PRIMITIVE_COMPILERS 只注册 deterministic primitive。
DIALECT_REGISTRY 只注册 generative dialect。
geometry_primitives registry 不能导入 generative_cad。
generative_cad dialects 不能导入 geometry_primitives deterministic kernels。
```

## 4.3 Metadata 隔离

```text
Primitive path:
  .metadata.json must contain primitive_metadata
  must validate primitive_metadata_v1
  may run mechanical_validation

Generative path:
  .metadata.json must contain generative_metadata
  must validate generative_metadata_v2
  must not claim mechanical validation
  must not claim certified/manufacturing/airworthy
```

## 4.4 Tool 隔离

Primitive tools:

```text
engineering_validate_cad_ir
engineering_build_cad_model
cadquery_compile_cad_ir_to_script
cadquery_build_from_cad_ir
```

Generative tools:

```text
generative_cad_list_bases
generative_cad_get_base_contract
generative_cad_validate_ir
generative_cad_build_from_ir
```

`registry.py` 当前同时注册 cadquery tools、natural_language tools、generative_cad tools，这是对的；但每个 tool 的内部调用路径必须保持隔离。([GitHub][1])

---

# 5. 本次 Claude Code 修复范围

本次修复不是推翻双链路，而是完成以下目标：

```text
A. 保留 deterministic CAD-IR / primitive path，不改语义。
B. 修复 generative G-CAD v0.2 内部接线。
C. 增加双链路隔离测试，防止污染。
D. 建立 route policy，明确什么时候走哪条链。
E. 清理 generative 内部 legacy 死模块，但不删除 deterministic path。
```

---

# 6. P0 修复任务：Generative raw/canonical 接线

## 6.1 当前错误

`builder.py` 写出的是 canonical JSON，但 harness 调用 `run_gcad_core_from_files()`；而 `run_gcad_core_from_files()` 会把 JSON 当 raw 输入重新 validate/canonicalize。([GitHub][10])

## 6.2 正确设计

Generative pipeline 必须拆成两个入口：

```python
run_gcad_core_from_files(raw_json, out_step, metadata_path)
run_gcad_core(raw_dict, out_step, metadata_path)

run_canonical_gcad_from_files(canonical_json, out_step, metadata_path)
run_canonical_gcad(canonical, out_step, metadata_path)
```

规则：

```text
public validate/build tool 接收 raw；
builder 负责 raw → canonical；
builder 写出的 graph file 是 canonical；
harness 必须调用 run_canonical_gcad_from_files；
run_canonical_gcad_from_files 不允许再次调用 RawGcadDocument validator。
```

## 6.3 Claude Code 修改要求

修改 `generative_cad/pipeline/run.py`：

```python
def run_gcad_core_from_files(input_json, out_step, metadata_path):
    """
    Accept RawGcadDocument JSON only.
    Load raw JSON, call run_gcad_core.
    """

def run_gcad_core(raw, out_step, metadata_path):
    """
    Accept raw dict only.
    Call validate_and_canonicalize.
    Then call run_canonical_gcad.
    """

def run_canonical_gcad_from_files(canonical_json, out_step, metadata_path):
    """
    Accept CanonicalGcadDocument JSON only.
    Do not call validate_and_canonicalize.
    """

def run_canonical_gcad(canonical, out_step, metadata_path):
    """
    Run already canonicalized graph.
    Execute dialects, export STEP, write metadata, return result.
    """
```

修改 `generative_cad/builder.py` 的 harness：

```python
from seekflow_engineering_tools.generative_cad.pipeline.run import (
    run_canonical_gcad_from_files,
)

result = run_canonical_gcad_from_files(
    canonical_json=r"...",
    out_step=r"...",
    metadata_path=r"...",
)
```

---

# 7. P0 修复任务：typed_params 必须 JSON-safe

当前 `canonicalize.py` 把 `op_spec.validate_params()` 的返回对象直接放进 `typed_params`，再由 `json.dumps(..., default=str)` 写文件。([GitHub][11])

正确做法：

```python
typed_model = op_spec.validate_params(node.params)
typed_params = typed_model.model_dump()
```

并把 `CanonicalNode.typed_params` 类型固定为：

```python
typed_params: dict[str, Any]
```

禁止在 canonical IR 中存放 Pydantic object。

---

# 8. P0 修复任务：类型系统必须真实工作

## 8.1 当前漏洞

`typecheck.py` 当前没有真正对比 producer output type 与 consumer expected type。([GitHub][15])

## 8.2 正确规则

每条 input edge 必须满足：

```text
producer_output.type == consumer_operation.input_types[index]
```

如果是 component input：

```text
component.output type 来自 component.root_node 的 output declaration
```

禁止默认猜 `solid`。

## 8.3 必须新增错误码

```text
input_type_mismatch
missing_component_output_ref
missing_node_output_ref
output_type_mismatch
input_count_mismatch
output_count_mismatch
```

---

# 9. P0 修复任务：canonicalize 禁止 fallback

当前 `canonicalize.py` 在解析 input type 时有：

```python
resolved_type: ValueType = "solid"
```

这必须删除。([GitHub][11])

正确行为：

```text
producer node 不存在 → fail
producer output 不存在 → fail
component output 不存在 → fail
type 无法解析 → fail
```

Canonical IR 是 verified IR，不能猜类型。

---

# 10. P0 修复任务：dialect version 必须严格匹配

当前 `validation/registry.py` 没有实际比较 selected dialect version。([GitHub][12])

必须实现：

```python
if sd.version != dialect.version:
    fail("dialect_version_mismatch")
```

不要做自动升级：

```text
0.1.0 → 0.2.0
```

如需兼容，必须走显式 migration，不允许 validator 静默接受。

---

# 11. P0 修复任务：component root_node 必须严格

`RawComponent.root_node` 当前允许为 None。([GitHub][9])
但为了编译器稳定，进入 canonical 前必须要求：

```text
1. root_node 必须存在。
2. root_node 必须属于该 component。
3. root_node 必须声明 outputs。
4. 非 assembly component 的 root_node 应输出 body: solid。
5. __assembly__ 的 root_node 必须输出 body: solid。
```

`canonicalize.py` 里“没有 root_node 就取第一个 node”的行为必须删除。([GitHub][11])

---

# 12. P0 修复任务：composition DAG

当前 `composition.run_component()` 的 in-degree 把已完成 component input 也算进去。([GitHub][13])

修复：

```python
in_degree = {
    n.id: sum(
        1
        for i in n.inputs
        if i.producer_node and i.producer_node in node_map
    )
    for n in nodes
}
```

component input 是 external ready value，不参与 assembly 内部拓扑排序。

执行后必须检查：

```python
if len(sorted_nodes) != len(nodes):
    raise RuntimeError("composition DAG did not schedule all nodes")
```

---

# 13. P0 修复任务：composition pattern 类型一致

当前 `circular_pattern_component` / `linear_pattern_component` 声明 `solid_array`，但当前 v0.2 没有完整 solid_array runtime。([GitHub][13])

v0.2 应简化为：

```text
pattern input: solid
pattern output: solid
语义：复制若干 solid 并 union 成一个 solid
```

修改 OperationSpec：

```python
input_types=["solid"]
output_types=["solid"]
effects=["patterns_component", "boolean_union"]
postconditions=["valid_solid"]
```

后续 v0.3 再引入真正的 `SolidArrayHandle`。

---

# 14. P0 修复任务：统一 runtime input resolver

当前 axisymmetric handler 内部各自解析 input，已经出现 `handle_cut_center_bore()` 读取当前 node 尚未产生输出的问题。([GitHub][14])

新增：

```text
generative_cad/runtime/resolve.py
```

实现：

```python
def resolve_input_handle_id(node, ctx, index=0) -> str:
    inp = node.inputs[index]
    if inp.producer_node:
        return ctx.resolve_node_output(inp.producer_node, inp.output)
    if inp.producer_component:
        return ctx.resolve_component_output(inp.producer_component, inp.output)
    raise ValueError(...)

def resolve_input_object(node, ctx, index=0):
    return ctx.object_store.get(resolve_input_handle_id(node, ctx, index))
```

所有 dialect handler 必须使用这个 resolver。

禁止在 handler 中出现：

```python
ctx.resolve_node_output(node.id, "body")
```

除非有非常明确的后置读取场景。一般 op handler 不应读取当前 node 自己的输出。

---

# 15. P0 修复任务：degradation policy 统一处理

当前 `handle_apply_safe_chamfer()` 会捕获异常并 `pass`，这会让 required op 失败被静默吞掉。([GitHub][14])

正确机制：

```text
handler 不吞异常；
dialect.run_component 统一 catch；
如果 node.required 或 degradation_policy == fail → raise；
否则记录 ctx.warnings 和 ctx.degraded_features；
metadata 中记录 degraded node。
```

---

# 16. P1 修复任务：metadata / artifact

## 16.1 Generative metadata v2 必须强校验

`builder.py` 当前调用 `validate_generative_metadata_v2(metadata)`，没有传入 canonical 做 provenance 校验。([GitHub][10])

应改成：

```python
validate_generative_metadata_v2(
    metadata,
    canonical=canonical,
    registry_check=True,
)
```

必须检查：

```text
canonical_graph_hash 一致
raw_graph_hash 一致
selected_dialects 一致
contract_hash 一致
op_versions 一致
safety flags 一致
trust_level 一致
```

## 16.2 Artifact 必须进入 metrics

`pipeline/run.py` 当前返回 `GcadRunResult` 时没有构建 artifact。([GitHub][16])

应构建：

```python
artifact = build_canonical_step_artifact(...)
```

并放入：

```python
GcadRunResult.artifact
metrics["artifact"]
```

---

# 17. P1 修复任务：builder metrics 不得覆盖 validation

`builder.py` 当前先把 core validation 放入 `metrics["validation"]`，后面 inspection 又覆盖 `metrics["validation"]`。([GitHub][10])

改为：

```python
metrics = {
    "core_validation": report.model_dump(),
    "metadata_validation": meta_validation,
    "inspection": insp_result,
    "inspection_validation": inspection_validation,
}
```

---

# 18. Legacy 清理原则

这里必须非常精确：**只清理 generative 内部 legacy v0 模块，不清理 deterministic primitive 链路。**

可以迁移或标记 deprecated：

```text
generative_cad/runner.py
generative_cad/base.py
generative_cad/registry.py
generative_cad/graph_validation.py
generative_cad/metadata.py
```

不能动：

```text
ir/cad.py
ir/primitive.py
cadquery_backend/compiler.py
cadquery_backend/primitive_compiler.py
cadquery_backend/builder.py
geometry_primitives/*
mechanical_validation/*
natural_language/tools.py
```

如果保留旧 generative module，必须加 warning：

```python
warnings.warn(
    "generative_cad.runner is legacy v0; use generative_cad.pipeline.run",
    DeprecationWarning,
)
```

并新增测试保证 public generative tools 不导入旧 runner。

---

# 19. 双链路测试矩阵

## 19.1 Primitive 链路保护测试

必须新增：

```text
test_primitive_path_still_uses_cadpartspec
test_primitive_path_does_not_import_generative_cad_dialects
test_primitive_compiler_registry_unchanged
test_axisymmetric_turbine_disk_primitive_still_builds_or_compiles
test_involute_spur_gear_primitive_still_builds_or_compiles
test_engineering_build_cad_model_still_routes_primitives_to_deterministic_path
test_primitive_metadata_schema_is_not_generative_metadata_v2
test_mechanical_validation_not_removed_from_primitive_path
```

## 19.2 Generative 链路测试

```text
test_generative_tool_accepts_raw_gcad_document
test_generative_builder_writes_canonical_and_harness_reads_canonical
test_run_canonical_gcad_from_files_does_not_validate_as_raw
test_typecheck_rejects_frame_as_solid
test_canonicalize_no_default_solid_fallback
test_dialect_version_mismatch_fails
test_missing_root_node_fails
test_composition_external_component_inputs_ready
test_composition_schedules_all_nodes
test_axisymmetric_revolve_then_center_bore_builds
test_composition_pattern_outputs_solid_in_v02
test_optional_degradation_records_warning
test_required_failure_fails_closed
test_generative_metadata_v2_provenance_validation
```

## 19.3 隔离测试

```text
test_generative_registry_does_not_register_primitives
test_primitive_registry_does_not_register_dialects
test_cadpartspec_rejects_gcad_fields
test_raw_gcad_document_rejects_cadpartspec_features
test_generative_tools_do_not_call_engineering_build_cad_model
test_engineering_build_cad_model_does_not_call_generative_build_from_ir
test_step_inspection_shared_but_metadata_schemas_distinct
```

---

# 20. 给 Claude Code 的最终 Prompt

下面这段可以直接交给 Claude Code。

```text
You are working in WYZAAACCC/seekflow-engineering under integrations/engineering_tools.

Important correction:
The project must keep TWO independent CAD generation routes.

Route A: Deterministic CAD-IR / Primitive path.
- Used for high-certainty, high-precision, engineering-semantic models.
- Uses CADPartSpec, PrimitiveFeature, cadquery_backend/compiler.py, cadquery_backend/primitive_compiler.py, cadquery_backend/builder.py, geometry_primitives, mechanical_validation.
- This path must remain intact and must not be replaced by generative CAD.

Route B: Generative G-CAD Core IR path.
- Used for free-form, higher-degree-of-freedom, reference geometry.
- Uses RawGcadDocument, CanonicalGcadDocument, dialects, validation pipeline, runtime object store, pipeline.run, generative metadata v2.
- This path must remain separate from primitive.

Your job:
Fix the current generative G-CAD v0.2 implementation while preserving the deterministic primitive path. Do not make generative the only CAD path. Do not route primitives through generative. Do not route generative graphs through primitive.

Hard constraints:
1. Do not modify deterministic primitive path semantics.
2. Do not remove CADPartSpec.
3. Do not remove PrimitiveFeature.
4. Do not modify PRIMITIVE_COMPILERS except adding tests that confirm it remains separate.
5. Do not import generative_cad dialects from primitive_compiler.
6. Do not import primitive_compiler or geometry_primitives deterministic kernels from generative dialect handlers.
7. Do not let CADPartSpec contain G-CAD nodes.
8. Do not let RawGcadDocument contain PrimitiveFeature.
9. Primitive metadata and generative metadata must remain separate schemas.
10. Primitive mechanical validation must remain in the primitive path.
11. Generative path must not claim manufacturing-ready, certified, airworthy, installable, or structurally validated geometry.
12. Public CAD-IR tools must continue using engineering_validate_cad_ir and engineering_build_cad_model.
13. Public generative tools must use generative_cad_validate_ir and generative_cad_build_from_ir.
14. Both routes may share STEP inspection utilities, but not IR, registries, or metadata schemas.

Current known issues to fix:
A. generative_cad/builder.py writes CanonicalGcadDocument JSON, but its harness calls run_gcad_core_from_files, which re-validates that canonical JSON as RawGcadDocument. Split raw and canonical runner entrypoints.
B. CanonicalNode.typed_params is not JSON-safe if it stores Pydantic objects. Store typed_params as dict.
C. typecheck does not truly compare producer output type with consumer OperationSpec.input_types.
D. canonicalize falls back unresolved input types to "solid"; remove this.
E. registry validation does not enforce selected dialect version match.
F. component.root_node must be explicit and valid. Do not choose first node as root.
G. composition run_component counts external component inputs in in_degree; external component inputs are already ready values.
H. composition pattern ops declare solid_array but handlers are not complete solid_array runtime. In v0.2, make pattern input/output solid unless implementing SolidArray end-to-end.
I. axisymmetric handle_cut_center_bore resolves the current node output before it exists. Add a shared runtime input resolver and use it everywhere.
J. handler-level silent degradation must be removed. Degradation policy is handled by dialect.run_component.
K. metadata v2 validation must compare against canonical and registry contract hash.
L. builder metrics must not overwrite core validation with inspection validation.
M. artifact must be produced and included in generative build metrics.
N. Legacy generative v0 modules may be deprecated or moved, but deterministic primitive modules must not be touched.

Implementation tasks:

1. Implement raw/canonical runner split in generative_cad/pipeline/run.py:
   - run_gcad_core_from_files(raw_json, out_step, metadata_path)
   - run_gcad_core(raw_dict, out_step, metadata_path)
   - run_canonical_gcad_from_files(canonical_json, out_step, metadata_path)
   - run_canonical_gcad(canonical, out_step, metadata_path)
   Builder harness must call run_canonical_gcad_from_files.

2. Make CanonicalNode.typed_params JSON-safe:
   - typed_params: dict[str, Any]
   - canonicalize must store op_spec.validate_params(node.params).model_dump()

3. Strengthen structure validation:
   - every component.root_node required
   - root_node exists
   - root_node belongs to component
   - root_node has outputs
   - __assembly__.root_node outputs body: solid

4. Strengthen typecheck:
   - producer node output type must equal expected input type
   - component public output type comes from component.root_node outputs
   - missing component output fails
   - no implicit solid fallback

5. Remove canonicalize fallback:
   - delete resolved_type = "solid"
   - unresolved producer/output/type is an error

6. Enforce dialect version:
   - selected_dialects.version must equal registered dialect.version
   - mismatch fails closed

7. Fix composition:
   - in_degree only counts assembly-local node-to-node dependencies
   - external component inputs are ready
   - fail if not all nodes are scheduled
   - pattern ops in v0.2 should be solid -> solid if handlers union copies into a single solid
   - do not expose solid_array until SolidArrayHandle is implemented end-to-end

8. Add runtime input resolver:
   - generative_cad/runtime/resolve.py
   - resolve_input_handle_id(node, ctx, index)
   - resolve_input_object(node, ctx, index)
   - resolve_all_input_objects(node, ctx)
   Replace all handler-local input resolution.

9. Centralize degradation policy:
   - handlers raise exceptions
   - dialect.run_component catches exceptions
   - required/fail nodes fail closed
   - optional may_skip_with_warning nodes record ctx.warnings and ctx.degraded_features

10. Strengthen metadata v2:
   - validate_generative_metadata_v2(metadata, canonical=None, registry_check=True)
   - compare canonical_graph_hash, raw_graph_hash, selected_dialects, contract_hash, op_versions, safety, trust_level
   - builder must pass canonical into metadata validator

11. Artifact:
   - pipeline.run builds CanonicalStepArtifact
   - GcadRunResult.artifact populated
   - builder metrics include artifact

12. Metrics:
   - use core_validation, metadata_validation, inspection, inspection_validation
   - do not overwrite metrics["validation"]

13. Dual-route tests:
   Add tests that prove primitive and generative paths remain separate:
   - primitive path still uses CADPartSpec
   - primitive compiler registry has primitive names and no dialects
   - dialect registry has dialect names and no primitives
   - CADPartSpec rejects G-CAD fields
   - RawGcadDocument rejects CADPartSpec features
   - engineering_build_cad_model does not call generative_cad_build_from_ir
   - generative_cad_build_from_ir does not call engineering_build_cad_model
   - primitive metadata schema and generative metadata schema are distinct
   - primitive mechanical validation remains reachable
   - shared STEP inspection is allowed

14. Generative correctness tests:
   - builder writes canonical and harness reads canonical
   - run_canonical_gcad_from_files accepts canonical JSON
   - run_gcad_core_from_files accepts raw JSON
   - typecheck rejects frame used as solid
   - canonicalize no solid fallback
   - wrong dialect version fails
   - missing root_node fails
   - composition external component inputs are ready
   - composition schedules all nodes
   - axisymmetric revolve -> center bore resolves producer input
   - pattern op output type matches handler output
   - metadata v2 validates against canonical and registry

Acceptance criteria:
- All existing primitive/CAD-IR tests still pass.
- All new dual-route isolation tests pass.
- All generative v0.2 tests pass.
- Primitive path is still the recommended path for high-determinism/high-precision primitives.
- Generative path is only for reference/concept geometry.
- No module-level dependency from deterministic primitive compiler to generative dialects.
- No module-level dependency from generative dialects to deterministic primitive kernels.
- Both routes may share STEP inspection but not IR, registry, or metadata schema.
```

---

# 21. 最终验收标准

完成后，系统必须满足：

```text
1. Primitive 和 generative 是两条并存链路。
2. Primitive path 继续用于高确定性、高精度、可机械验证模型。
3. Generative path 用于自由度高、非制造、reference geometry。
4. 二者不共享 IR。
5. 二者不共享 registry。
6. 二者不共享 metadata schema。
7. 二者不互相 fallback。
8. 二者只在 STEP + metadata + inspection 层合流。
9. Primitive mechanical validation 保留。
10. Generative safety flags 强制保留。
11. Generative 内部 v0.2 compiler invariants 修复。
12. 测试能防止未来架构滑坡。
```

最重要的一句话：

```text
不是“用 generative 替代 primitive”，而是“primitive 负责高确定性工程内核，generative 负责受控自由建模；两者并存、隔离、按需求路由”。
```

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/registry.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/tools.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/tools.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/compiler.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/registry.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/dialect.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py "raw.githubusercontent.com"
[15]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/typecheck.py "raw.githubusercontent.com"
[16]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "raw.githubusercontent.com"
