# SeekFlow `text_to_cad` 双链路架构落地修复工程文档

## 面向 Claude Code 的高确定性实施规格

## 0. 核心原则先纠偏

本项目绝不能把 generative G-CAD 链路变成唯一 CAD 链路。正确架构是**双链路并存、强隔离、按任务选择**：

```text
Route A：Deterministic CAD-IR / Primitive Path
用途：高确定性、高精度、工程语义明确、需要机械验证的模型。
入口：CADPartSpec / PrimitiveFeature / engineering_build_cad_model / cadquery_build_from_cad_ir。
核心：primitive_compiler.py + deterministic geometry kernels。
结果：STEP / primitive metadata / inspection / mechanical validation。

Route B：Generative G-CAD Core IR Path
用途：自由度高、拓扑开放、参考几何、概念建模。
入口：RawGcadDocument / generative_cad_validate_ir / generative_cad_build_from_ir。
核心：CanonicalGcadDocument / dialect runners / composition / runtime object store。
结果：STEP / generative_metadata_v2 / inspection / reference geometry artifact。
```

当前仓库已经具备双链路入口：`registry.py` 同时注册 CadQuery、natural language 和 generative CAD tools，因此不能把 generative 改成唯一主链路；它只能作为与 primitive 并列的第二条 CAD 生成路径。`primitive_compiler.py` 仍然明确承担 deterministic primitive kernels，`generative_cad/tools.py` 则已经接入 `RawGcadDocument`、`validate_and_canonicalize()` 与 dialect registry，这说明双链路方向已经开始落地。([GitHub][1])

---

# 1. 当前代码最新状态判断

## 1.1 已经修好的部分

本轮代码相比上一轮已经明显进步：

1. `generative_cad/tools.py` 已经改为 v0.2 dialect-based generative tools，public generative 工具现在使用 `RawGcadDocument`、`validate_and_canonicalize()`、dialect registry 和 `build_generative_cad_model()`，不再直接使用旧 `GenerativeCADSpec`。([GitHub][1])

2. `builder.py` 已经把 harness 改成调用 `run_canonical_gcad_from_files()`，避免了“builder 写 canonical，但 runner 当 raw 再校验”的旧接线错误。([GitHub][2])

3. `pipeline/run.py` 已经拆分 raw entrypoints 与 canonical entrypoints：`run_gcad_core_from_files / run_gcad_core` 处理 raw，`run_canonical_gcad_from_files / run_canonical_gcad` 处理 canonical，这是正确的编译器边界。([GitHub][3])

4. `typecheck.py` 已经开始真正比较 producer output type 与 consumer expected input type，并且删除了 implicit solid fallback 的语义。([GitHub][4])

5. `registry.py` 已经开始执行 dialect version mismatch fail-closed。([GitHub][5])

6. `composition.dialect.py` 已将 pattern op 改为 `solid → solid`，并修正 assembly 内部 in-degree 只统计 composition node-to-node dependency，这是正确方向。([GitHub][6])

7. `axisymmetric.handlers.py` 已经引入 shared resolver，并且不再在 `cut_center_bore` 中读取当前 node 尚未产生的 output。([GitHub][7])

这些修改说明：**v0.2 generative compiler path 的主结构已经开始接线。**

---

## 1.2 仍然存在的关键问题

当前还不能宣称达到“传统编译器级稳定、兼容、添加内容不会崩溃”。剩余问题集中在六类：

```text
1. 双链路隔离测试不足，无法防止未来 primitive/generative 污染。
2. Generative typed IR 仍不完全可信，component input 在 canonicalize 中仍被标成 component_ref。
3. structure stage 没有提前强校验 root_node，root_node 错误被推迟到 canonicalize。
4. phase validator 只检查 node.phase == op_spec.phase，没有检查 dependency phase order。
5. sketch_extrude 和 composition handlers 仍有本地 input resolver 与 silent fallback，未统一使用 runtime.resolve。
6. metadata/artifact 仍是半贯通：metadata v2 缺少 op_versions/safety/trust_level 强比对，builder metrics 还没有正式 artifact。
```

`canonical.py` 中 `CanonicalNode.typed_params` 仍是 `Any = None`，而不是 `dict[str, Any]`；`canonicalize.py` 虽然注释写着 typed_params 已变 JSON-safe，但 canonical model 层没有类型约束。([GitHub][8])
`structure.py` 仍然只检查 component/node id 和 node component 引用，没有检查 root_node 存在、归属、输出 body。([GitHub][9])
`phase.py` 仍然只检查 node 自身 phase 是否匹配 op spec，没有检查 producer phase 是否早于 consumer phase。([GitHub][10])
`sketch_extrude/handlers.py` 仍然有本地 `_resolve_solid_input()`，并且 fallback 到 `ctx.resolve_node_output(node.id, "body")`，这与新的 shared runtime resolver 规则冲突。([GitHub][11])
`composition/handlers.py` 也仍然保留本地 `_resolve_input()`，并且在无法解析输入时 fallback 到当前 node output，同样不符合 compiler-grade runtime input resolution。([GitHub][12])
`artifact.py` 目前返回的 artifact 仍有空 `graph_path`、空 inspection 和空 validation，它不是完整合流层 artifact。([GitHub][13])

---

# 2. 本次 Claude Code 的实施总目标

本次不是重新设计架构，而是把已有代码**收敛成稳定双链路架构**：

```text
目标 A：保护 deterministic primitive path
- 不改 CADPartSpec 语义。
- 不改 PRIMITIVE_COMPILERS 语义。
- 不让 generative dialect 进入 primitive registry。
- 不让 primitive kernel 被 generative handler 调用。
- 确保高确定性模型继续走 primitive path。

目标 B：修复 generative G-CAD v0.2 内部 compiler invariants
- Raw / Canonical 边界严格。
- Typed IR 真实可信。
- Component public output 类型可解析。
- OperationSpec 与 handler 行为一致。
- Runtime input resolver 唯一化。
- Metadata provenance 可验证。
- Artifact 作为受控合流层产物。

目标 C：建立防退化测试
- Primitive 与 generative 互不污染。
- Public generative 工具只走 v0.2 pipeline。
- Public primitive 工具继续走 CADPartSpec / primitive pipeline。
```

---

# 3. 绝对硬约束

Claude Code 必须遵守以下约束，不能自行变通：

```text
1. 不允许删除、替换或弱化 deterministic primitive path。
2. 不允许让 engineering_build_cad_model 默认调用 generative_cad_build_from_ir。
3. 不允许让 generative_cad_build_from_ir 调用 engineering_build_cad_model。
4. 不允许把 G-CAD nodes 加入 CADPartSpec.features。
5. 不允许把 PrimitiveFeature 加入 RawGcadDocument.nodes。
6. 不允许把 generative dialect 注册到 PRIMITIVE_COMPILERS。
7. 不允许在 generative dialect handler 中调用 deterministic primitive kernels。
8. 不允许 generative metadata 声明 manufacturing-ready、certified、airworthy、installable、structurally validated。
9. 不允许 handler 本地 fallback 到 ctx.resolve_node_output(node.id, "body")。
10. 不允许 canonicalize 猜测 unresolved type。
11. 不允许 dialect version mismatch 静默通过。
12. 不允许 optional feature failure 被 handler 静默吞掉。
13. 不允许 metadata 只做格式校验而不做 canonical provenance 校验。
14. 不允许 artifact 只作为空壳存在。
```

---

# 4. 目录与职责边界

## 4.1 保留 deterministic path

以下模块属于 Route A，除增加隔离测试外，不要改核心语义：

```text
src/seekflow_engineering_tools/ir/cad.py
src/seekflow_engineering_tools/ir/primitive.py
src/seekflow_engineering_tools/cadquery_backend/compiler.py
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
src/seekflow_engineering_tools/cadquery_backend/builder.py
src/seekflow_engineering_tools/natural_language/tools.py
src/seekflow_engineering_tools/geometry_primitives/
src/seekflow_engineering_tools/mechanical_validation/
```

## 4.2 修复 generative path

本次主要修改：

```text
generative_cad/ir/canonical.py
generative_cad/validation/structure.py
generative_cad/validation/typecheck.py
generative_cad/validation/canonicalize.py
generative_cad/validation/phase.py
generative_cad/runtime/resolve.py
generative_cad/dialects/axisymmetric/dialect.py
generative_cad/dialects/sketch_extrude/dialect.py
generative_cad/dialects/sketch_extrude/handlers.py
generative_cad/dialects/composition/dialect.py
generative_cad/dialects/composition/handlers.py
generative_cad/pipeline/metadata.py
generative_cad/pipeline/artifact.py
generative_cad/pipeline/run.py
generative_cad/builder.py
```

---

# 5. P0 修复任务

## P0-1：`CanonicalNode.typed_params` 必须固定为 JSON-safe dict

当前 `CanonicalNode.typed_params` 仍是 `Any = None`。这不符合 compiler IR 的稳定性要求。([GitHub][8])

修改：

```python
# generative_cad/ir/canonical.py
class CanonicalNode(BaseModel):
    ...
    params: dict[str, Any] = Field(default_factory=dict)
    typed_params: dict[str, Any] = Field(default_factory=dict)
```

`canonicalize.py` 必须保证：

```python
typed_params_obj = op_spec.validate_params(node.params)
typed_params = typed_params_obj.model_dump()
```

禁止把 Pydantic object 塞进 canonical IR。

验收测试：

```text
test_canonical_typed_params_is_dict
test_canonical_json_roundtrip_preserves_typed_params
```

---

## P0-2：`canonicalize` 中 component input 的 `resolved_type` 必须是真实类型，不是 `component_ref`

当前 `canonicalize.py` 对 `inp.component is not None` 返回 `"component_ref"`。([GitHub][14])
这会让 `CanonicalValueRef.resolved_type` 失去实际 value type 语义。虽然 `typecheck.py` 已经会从 `component.root_node.outputs` 推导实际类型，但 canonical IR 仍不够“typed”。

正确规则：

```text
node input:
  resolved_type = producer node output type

component input:
  resolved_type = component.root_node 对应 output 的真实 type，例如 solid / frame / curve
```

实现 helper：

```python
def _component_public_output_type(raw: RawGcadDocument, component_id: str, output: str) -> str | None:
    comp = next((c for c in raw.components if c.id == component_id), None)
    if comp is None or not comp.root_node:
        return None

    root = next((n for n in raw.nodes if n.id == comp.root_node), None)
    if root is None:
        return None

    for out in root.outputs:
        if out.name == output:
            return out.type

    return None
```

在 `_resolve_input_type()` 中：

```python
elif inp.component is not None:
    typ = _component_public_output_type(raw, inp.component, inp.output)
    if typ is None:
        issues.append(...)
        return None
    return typ
```

验收测试：

```text
test_canonical_component_input_resolves_to_solid_not_component_ref
test_composition_component_input_type_is_solid
```

---

## P0-3：`structure.py` 必须提前验证 root_node

当前 `structure.py` 不校验 root_node。([GitHub][9])
现在 root_node 错误被推迟到 canonicalize，导致 pipeline 的错误阶段不稳定。结构性错误应在 structure stage fail。

新增规则：

```text
1. 每个 component.root_node 必须非空。
2. root_node 必须存在。
3. root_node 必须属于该 component。
4. root_node 必须有 outputs。
5. __assembly__.root_node 必须输出 body: solid。
6. 非 assembly component 的 root_node 建议必须输出 body: solid。当前 v0.2 强制要求 body: solid，除非未来引入 non-solid component。
```

实现片段：

```python
node_map = {n.id: n for n in raw.nodes}

for comp in raw.components:
    if not comp.root_node:
        issues.append(...)
        continue

    root = node_map.get(comp.root_node)
    if root is None:
        issues.append(...)
        continue

    if root.component != comp.id:
        issues.append(...)
        continue

    if not root.outputs:
        issues.append(...)
        continue

    has_body_solid = any(o.name == "body" and o.type == "solid" for o in root.outputs)
    if not has_body_solid:
        issues.append(...)
```

错误码：

```text
missing_component_root_node
root_node_not_found
root_node_wrong_component
root_node_no_outputs
root_node_missing_body_solid
```

验收测试：

```text
test_missing_root_node_fails_in_structure_stage
test_root_node_wrong_component_fails
test_root_node_without_body_solid_fails
```

---

## P0-4：`phase.py` 必须检查 dependency phase order

当前 `phase.py` 只检查 `node.phase == op_spec.phase`。([GitHub][10])
必须加入边级 phase order：

```text
同 component / 同 dialect 内：
producer_phase_rank <= consumer_phase_rank
```

实现：

```python
node_map = {n.id: n for n in raw.nodes}

for node in raw.nodes:
    dialect = require_dialect(node.dialect)
    phase_rank = {p: i for i, p in enumerate(dialect.phase_order)}

    for inp in node.inputs:
        if inp.node is None:
            continue

        producer = node_map.get(inp.node)
        if producer is None:
            continue

        if producer.component != node.component:
            continue

        if producer.dialect != node.dialect:
            continue

        pr = phase_rank.get(producer.phase)
        cr = phase_rank.get(node.phase)

        if pr is None or cr is None:
            continue

        if pr > cr:
            issues.append(
                ValidationReport.fail(
                    "phase",
                    "phase_dependency_order_violation",
                    f"node {node.id!r} phase {node.phase!r} depends on later phase "
                    f"{producer.phase!r} from node {producer.id!r}",
                    node_id=node.id,
                    expected=f"producer phase rank <= {cr}",
                    actual=f"producer phase rank {pr}",
                ).issues[0]
            )
```

验收测试：

```text
test_phase_reverse_dependency_fails
test_same_phase_dependency_allowed
test_forward_phase_dependency_allowed
```

---

## P0-5：所有 handlers 必须使用 `runtime.resolve`

`axisymmetric` 已经改得比较好，但 `sketch_extrude` 和 `composition` 仍有本地 resolver，并且 fallback 到当前 node output。([GitHub][7])

必须删除：

```python
ctx.resolve_node_output(node.id, "body")
```

从所有 handler-local resolver 中删除，改为统一使用：

```python
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_handle_id,
    resolve_input_object,
    resolve_all_input_objects,
)
```

### sketch_extrude 修改

删除：

```python
def _resolve_solid_input(node, ctx):
    if node.inputs and node.inputs[0].producer_node:
        return ctx.resolve_node_output(...)
    return ctx.resolve_node_output(node.id, "body")
```

替换：

```python
from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object

body = resolve_input_object(node, ctx, 0)
```

### composition 修改

删除本地 `_resolve_input()` 和 `_resolve_all_inputs()`，改用 shared resolver：

```python
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_handle_id,
    resolve_input_object,
    resolve_all_input_objects,
)

def handle_boolean_union(node, ctx):
    solids = resolve_all_input_objects(node, ctx)
    ...
```

验收测试：

```text
test_no_handler_uses_current_node_output_fallback
test_sketch_extrude_second_node_resolves_producer_input
test_composition_component_input_resolves_via_shared_resolver
```

---

## P0-6：`sketch_extrude` 必须统一 degradation policy

`axisymmetric.dialect.py` 和 `composition.dialect.py` 已经集中处理 optional degradation，但 `sketch_extrude.dialect.py` 仍然直接调用 handler，没有 try/except policy；同时 `sketch_extrude.handlers.py` 的 fillet/chamfer 仍在 handler 内部 `try/except pass`。([GitHub][15])

修改 `SketchExtrudeDialect.run_component()`：

```python
try:
    outputs = op_spec.handler(node, ctx)
except Exception as exc:
    if not node.required and node.degradation_policy == "may_skip_with_warning":
        ctx.warnings.append(f"Optional {node.id!r} ({node.op}) skipped: {exc}")
        ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
        ctx.operation_metrics.append({
            "node_id": node.id,
            "op": node.op,
            "status": "degraded",
            "reason": str(exc),
        })
        continue
    raise
```

修改 fillet/chamfer handlers：

```python
def handle_se_fillet(node, ctx):
    body = resolve_input_object(node, ctx, 0)
    r = float(node.typed_params.get("radius_mm", node.params.get("radius_mm", 0)))
    if r <= 0:
        raise ValueError("radius_mm must be positive")
    body = body.fillet(r)
    return {"body": _store_solid(node, ctx, body)}
```

不要在 handler 内吞掉异常。

验收测试：

```text
test_sketch_optional_fillet_failure_records_degraded_feature
test_sketch_required_fillet_failure_fails_closed
```

---

## P0-7：axisymmetric / sketch_extrude run_component 必须检查 DAG 是否完全调度

`composition` 已经加了 “if not all nodes scheduled fail”，但 `axisymmetric` 和 `sketch_extrude` 仍缺这个保护。([GitHub][6])

加入：

```python
if len(sorted_nodes) != len(nodes):
    unscheduled = [n.id for n in nodes if n not in sorted_nodes]
    raise RuntimeError(f"{self.dialect_id}: could not schedule nodes: {unscheduled}")
```

虽然 `validate_graph` 已经做 DAG 检查，但 runtime 仍应 fail-closed，防止 canonical JSON 被手工篡改后进入 runner。

验收测试：

```text
test_axisymmetric_runtime_fails_unscheduled_nodes
test_sketch_extrude_runtime_fails_unscheduled_nodes
```

---

# 6. P1 修复任务

## P1-1：metadata v2 强化 provenance 校验

当前 metadata validator 已经支持 canonical 和 contract hash 比对，但仍不完整：它没有严格比对 `schema_version / canonical_version / trust_level / safety / op_versions / selected_dialects version`。([GitHub][16])

补充：

```python
if canonical is not None:
    if gm.get("schema_version") != canonical.schema_version: ...
    if gm.get("canonical_version") != canonical.canonical_version: ...
    if gm.get("trust_level") != canonical.trust_level: ...
    if gm.get("safety") != canonical.safety.model_dump(): ...

    expected_ops = [
        {"node_id": n.id, "dialect": n.dialect, "op": n.op, "op_version": n.op_version}
        for n in canonical.nodes
    ]
    if gm.get("op_versions") != expected_ops: ...

    expected_dialects = [
        {"dialect": d.dialect, "version": d.version, "contract_hash": d.contract_hash}
        for d in canonical.selected_dialects
    ]
    if gm.get("selected_dialects") != expected_dialects: ...
```

验收测试：

```text
test_metadata_rejects_op_version_drift
test_metadata_rejects_safety_drift
test_metadata_rejects_trust_level_drift
test_metadata_rejects_selected_dialect_version_drift
```

---

## P1-2：artifact 必须成为正式合流层产物

`artifact.py` 现在返回空 `graph_path`、空 `inspection`、空 `validation`。([GitHub][13])
`pipeline/run.py` 虽然已经构建 artifact，但 builder subprocess 无法直接拿到 Python object；builder 需要在成功后重建或补全 artifact。([GitHub][3])

在 `builder.py` 中构造正式 artifact：

```python
artifact = {
    "artifact_type": "canonical_step_artifact",
    "source_route": "llm_skill_base",
    "part_name": canonical.part_name,
    "step_path": str(step_path),
    "metadata_path": str(meta_path),
    "graph_path": str(graph_path),
    "runner_script_path": str(script_path),
    "units": canonical.units,
    "trust_level": canonical.trust_level,
    "native_rebuild_allowed": False,
    "step_import_allowed": True,
    "inspection": insp_result if inspect else {},
    "validation": {
        "core_validation": report.model_dump(),
        "metadata_validation": meta_validation,
        "inspection_validation": insp_val if inspect else {},
    },
}
metrics["artifact"] = artifact
```

验收测试：

```text
test_generative_build_metrics_include_complete_artifact
test_artifact_has_graph_path_and_runner_script_path
test_artifact_contains_inspection_validation_after_inspect
```

---

## P1-3：primitive / generative 双链路隔离测试

必须新增测试，防止后续开发把两条链路混在一起：

```text
test_primitive_compiler_does_not_import_generative_cad
test_generative_dialects_do_not_import_primitive_compiler
test_primitive_registry_has_no_dialects
test_dialect_registry_has_no_primitives
test_cadpartspec_rejects_gcad_fields
test_raw_gcad_document_rejects_cadpartspec_features
test_engineering_build_cad_model_does_not_call_generative_build
test_generative_cad_build_from_ir_does_not_call_engineering_build
test_primitive_metadata_schema_distinct_from_generative_metadata_v2
```

实现方式可用 `inspect.getsource()`、import graph grep、或 pytest monkeypatch sentinel。

---

## P1-4：public tool integration tests

只测内部函数不够，必须测 public tools：

```text
test_generative_cad_validate_ir_tool_uses_v02_pipeline
test_generative_cad_build_from_ir_tool_builds_sketch_plate
test_generative_cad_build_from_ir_tool_builds_composed_model
test_engineering_build_cad_model_still_accepts_cadpartspec
test_cadquery_build_from_cad_ir_still_accepts_cadpartspec
```

---

# 7. 推荐最终测试目录

```text
tests/
  text_to_cad/
    test_dual_route_isolation.py
    test_primitive_path_regression.py
    test_generative_public_tools.py

  generative_cad/
    test_raw_canonical_boundaries.py
    test_structure_root_node.py
    test_typecheck_component_outputs.py
    test_phase_dependency_order.py
    test_runtime_resolver.py
    test_degradation_policy.py
    test_metadata_v2_provenance.py
    test_artifact_contract.py
    test_composition_runtime.py
    test_sketch_extrude_runtime.py
    test_axisymmetric_runtime.py

  fixtures/
    generative_cad/
      sketch_plate_minimal.json
      axisymmetric_bore_minimal.json
      composed_disk_lug.json
      invalid_component_input_type.json
      invalid_missing_root_node.json
      invalid_phase_reverse_dependency.json
      invalid_dialect_version.json
```

---

# 8. 实施顺序

Claude Code 必须按下面顺序做，避免越修越乱：

```text
Step 1：锁定双链路边界
- 新增 isolation tests 的骨架。
- 确认 primitive path 测试仍通过。
- 不改 primitive 语义。

Step 2：修 CanonicalNode.typed_params
- canonical.py 改 typed_params: dict[str, Any]。
- canonicalize 保证 model_dump。

Step 3：修 structure root_node
- root_node 错误提前到 structure stage。
- 删除 canonicalize root fallback 相关逻辑。

Step 4：修 component input type
- typecheck 与 canonicalize 使用同一套 component public output resolution。
- canonical resolved_type 必须是真实 type。

Step 5：修 phase dependency order
- phase.py 增加 producer/consumer phase rank 检查。

Step 6：统一 runtime resolver
- 修改 sketch_extrude handlers。
- 修改 composition handlers。
- 删除所有 current-node-output fallback。

Step 7：统一 degradation policy
- 修改 sketch_extrude.dialect.py。
- 删除 sketch_extrude handler 内 try/except pass。

Step 8：runtime DAG 防御
- axisymmetric / sketch_extrude 加 unscheduled nodes check。

Step 9：metadata provenance 强化
- 比对 schema/canonical/trust/safety/op_versions/selected_dialects。

Step 10：artifact 补全
- builder metrics 填入完整 artifact。

Step 11：补 public tool integration tests
- 验证 public generative tools 真实构建。
- 验证 primitive tools 不受影响。
```

---

# 9. 可直接交给 Claude Code 的 Prompt

下面这段可以直接复制给 Claude Code。

```text
You are working in WYZAAACCC/seekflow-engineering under integrations/engineering_tools.

Important architecture constraint:
This project has TWO CAD generation routes, both must remain first-class and isolated.

Route A: deterministic CAD-IR / Primitive path.
- Used for high-certainty, high-precision, engineering-semantic models.
- Uses CADPartSpec, PrimitiveFeature, cadquery_backend/compiler.py, cadquery_backend/primitive_compiler.py, cadquery_backend/builder.py, geometry_primitives, mechanical_validation.
- Do not replace this route with generative CAD.
- Do not route primitives through generative.

Route B: Generative G-CAD Core IR path.
- Used for free-form, high-degree-of-freedom, reference geometry.
- Uses RawGcadDocument, CanonicalGcadDocument, dialect registry, validation pipeline, runtime object store, pipeline.run, generative_metadata_v2.
- Do not route G-CAD graphs through primitive compiler.
- Do not claim manufacturing-ready/certified/airworthy/structurally validated geometry.

Current repository state:
- generative_cad/tools.py already uses RawGcadDocument, validate_and_canonicalize, dialect registry, and build_generative_cad_model.
- generative_cad/builder.py already writes canonical JSON and harness calls run_canonical_gcad_from_files.
- generative_cad/pipeline/run.py already has raw and canonical entrypoints.
- typecheck now compares producer output type with consumer expected input type.
- registry now checks dialect version mismatch.
- composition pattern ops are solid -> solid.
- axisymmetric handlers mostly use runtime.resolve.
But several compiler invariants remain incomplete.

Hard constraints:
1. Do not modify deterministic primitive semantics.
2. Do not modify PRIMITIVE_COMPILERS except tests proving isolation.
3. Do not import generative dialects from primitive compiler.
4. Do not import primitive compiler or deterministic primitive kernels from generative dialects.
5. Do not let CADPartSpec contain G-CAD nodes.
6. Do not let RawGcadDocument contain PrimitiveFeature.
7. Do not use fuzzy matching or silent fallback.
8. Do not allow unresolved input type to become solid.
9. Do not allow handlers to read ctx.resolve_node_output(node.id, "body") as fallback.
10. Do not allow handlers to silently swallow feature failure.
11. Generative output must remain reference/concept geometry only.

Tasks:

1. Make CanonicalNode.typed_params JSON-safe.
- In generative_cad/ir/canonical.py, change typed_params from Any to dict[str, Any].
- In canonicalize.py, ensure typed_params = op_spec.validate_params(node.params).model_dump().
- Add JSON roundtrip test.

2. Move root_node validation into structure stage.
- In validation/structure.py, every component.root_node must be present.
- root_node must exist, belong to that component, have outputs.
- root_node must output body: solid in v0.2.
- __assembly__.root_node must output body: solid.
- Add tests for missing/wrong root_node.

3. Fix canonicalize component input resolved_type.
- Currently component inputs may become component_ref.
- Resolve component input type through component.root_node.outputs.
- CanonicalValueRef.resolved_type for component body input must be solid, not component_ref.
- Add tests.

4. Strengthen phase validation.
- Keep node.phase == op_spec.phase.
- Additionally, for same-component same-dialect node-to-node dependency, producer phase rank must be <= consumer phase rank.
- Add tests for reverse phase dependency.

5. Use shared runtime resolver everywhere.
- generative_cad/runtime/resolve.py is the only valid input resolver.
- Replace sketch_extrude handler _resolve_solid_input with resolve_input_object.
- Replace composition handler _resolve_input and _resolve_all_inputs with resolve_input_object / resolve_all_input_objects.
- Remove all ctx.resolve_node_output(node.id, "body") fallbacks in handlers.
- Add grep/inspect test to enforce this.

6. Centralize degradation policy for sketch_extrude.
- Handlers must raise exceptions.
- SketchExtrudeDialect.run_component must catch exceptions and apply node.required/degradation_policy.
- Remove try/except pass from apply_safe_fillet and apply_safe_chamfer handlers.
- Add required/optional failure tests.

7. Runtime DAG defensive checks.
- Add unscheduled node check to AxisymmetricDialect.run_component.
- Add unscheduled node check to SketchExtrudeDialect.run_component.
- Composition already has it; keep it.

8. Strengthen metadata v2 provenance validation.
- validate_generative_metadata_v2(metadata, canonical=None, registry_check=True) must compare:
  schema_version
  canonical_version
  trust_level
  safety
  raw_graph_hash
  canonical_graph_hash
  op_versions
  selected_dialects including version and contract_hash
- Add tests that mutate metadata and confirm rejection.

9. Complete artifact in builder metrics.
- pipeline.run can return artifact, but subprocess builder cannot directly receive it.
- In builder.py, reconstruct a complete artifact dict after metadata + inspection:
  artifact_type
  source_route
  part_name
  step_path
  metadata_path
  graph_path
  runner_script_path
  units
  trust_level
  native_rebuild_allowed=false
  step_import_allowed=true
  inspection
  validation
- Put it in metrics["artifact"].
- Add tests.

10. Add dual-route isolation tests.
- Primitive compiler must not import generative_cad dialects.
- Generative dialects must not import primitive_compiler or geometry_primitives deterministic kernels.
- PRIMITIVE_COMPILERS must not contain axisymmetric/sketch_extrude/composition.
- DIALECT_REGISTRY must not contain involute_spur_gear or axisymmetric_turbine_disk.
- CADPartSpec rejects G-CAD fields.
- RawGcadDocument rejects CADPartSpec features.
- engineering_build_cad_model remains CADPartSpec/primitive route.
- generative_cad_build_from_ir remains RawGcadDocument route.
- Primitive metadata schema and generative_metadata_v2 remain distinct.

Acceptance criteria:
- All existing primitive/CAD-IR tests still pass.
- All generative v0.2 tests pass.
- Public generative_cad_validate_ir validates RawGcadDocument only.
- Public generative_cad_build_from_ir builds at least one sketch_extrude fixture and one composed fixture.
- Primitive path remains unchanged and independent.
- No handler contains ctx.resolve_node_output(node.id, "body") fallback.
- Metadata v2 provenance validator catches graph/op/safety/dialect drift.
- Artifact metrics are complete enough for downstream STEP import.
```

---

# 10. 最终验收标准

完成后，系统必须满足以下条件：

```text
1. 双链路并存：
   Primitive path 用于高确定性工程语义模型；
   Generative path 用于自由参考几何模型。

2. 双链路隔离：
   IR 隔离、registry 隔离、metadata 隔离、validation 隔离、测试隔离。

3. Generative compiler invariants：
   Raw/Canonical 边界清晰；
   typed_params JSON-safe；
   component input resolved_type 真实；
   phase dependency 合法；
   runtime resolver 唯一；
   optional degradation 统一记录；
   metadata provenance 可重算验证。

4. Artifact 合流：
   两条链路最终都能以 STEP + metadata + inspection artifact 进入后半段；
   但不得在 IR/registry/compiler 前半段混合。

5. 可扩展：
   新增 primitive 不需要碰 generative；
   新增 dialect 不需要碰 primitive；
   新增 op 参数不需要改 core validator；
   新增自由建模能力不会破坏 deterministic primitive。
```

最核心的架构语句应写入项目文档：

```text
SeekFlow text_to_cad is a dual-route CAD generation system.
Deterministic CAD-IR / Primitive path is the high-certainty engineering route.
Generative G-CAD Core IR path is the controlled free-form reference-geometry route.
The two routes are isolated before artifact generation and only converge at STEP + metadata + inspection.
```

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/tools.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/typecheck.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/registry.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/dialect.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/structure.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/phase.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/handlers.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py "raw.githubusercontent.com"
[15]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py "raw.githubusercontent.com"
[16]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py "raw.githubusercontent.com"
