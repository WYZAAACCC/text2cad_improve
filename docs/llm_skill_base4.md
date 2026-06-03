

这份文档的目标是：**在不破坏 primitive 确定性链路的前提下，继续加固 generative G-CAD v0.2 编译器链路，并吸收 CSG 报告中可用的底层工程修复。**

---

# 1. 正确目标：双链路并存，不是统一 CSG 单链路

## 1.1 必须保留的双链路

正确架构是：

```text
Route A：Deterministic CAD-IR / Primitive Path

用户自然语言 / CAD-IR
  ↓
CADPartSpec
  ↓
Recipe / Primitive / CAD feature
  ↓
cadquery_backend/compiler.py
  ↓
primitive_compiler.py / deterministic geometry kernels
  ↓
STEP + primitive metadata
  ↓
inspection + mechanical validation


Route B：Generative G-CAD Core IR Path

LLM structured output
  ↓
RawGcadDocument
  ↓
validate_and_canonicalize
  ↓
CanonicalGcadDocument
  ↓
DialectRegistry / OperationSpec / typed graph
  ↓
axisymmetric / sketch_extrude / composition dialect runners
  ↓
RuntimeObjectStore + typed handles
  ↓
STEP + generative_metadata_v2
  ↓
inspection validation + canonical STEP artifact
```

仓库当前的 `registry.py` 同时注册 CadQuery tools、natural language tools 和 generative CAD tools，这符合“双链路并存”的入口结构；primitive 构建仍在 `cadquery_backend/builder.py` 中执行 metadata sidecar、fallback policy、inspection、mechanical validation 等 fail-closed 逻辑。([GitHub][2])

## 1.2 两条链路的合流点

只能在以下层合流：

```text
STEP file
metadata sidecar
inspection result
artifact record
optional downstream STEP import
```

不能在这些层之前合流：

```text
CADPartSpec 不能包含 G-CAD nodes；
RawGcadDocument 不能包含 PrimitiveFeature；
PRIMITIVE_COMPILERS 不能注册 generative dialect；
generative dialect 不能调用 deterministic primitive kernel；
primitive metadata 和 generative_metadata_v2 不能合并；
mechanical validation 不能被 generative path 伪装通过。
```

早期架构记忆文档也明确要求：新链路不能进入 `CADPartSpec`、`primitive_compiler.py`、`PRIMITIVE_COMPILERS`、`geometry_primitives`，合流点只能是 `canonical STEP artifact + metadata`。



# 3. 当前代码基线

下面是基于当前仓库代码的基线判断。

## 3.1 已经做对的部分

`generative_cad/tools.py` 当前已经使用 dialect registry、`RawGcadDocument`、`validate_and_canonicalize()` 和 `build_generative_cad_model()`；同时保留旧工具名 `generative_cad_list_bases`、`generative_cad_get_base_contract`、`generative_cad_validate_ir`、`generative_cad_build_from_ir`。([GitHub][1])

`generative_cad/builder.py` 当前已经先把 raw spec 转成 `RawGcadDocument`，再调用 `validate_and_canonicalize()`，写出 canonical graph，并生成固定 harness；harness 已经调用 `run_canonical_gcad_from_files()`，不再把 canonical JSON 当 raw 重新校验。([GitHub][3])

`pipeline/run.py` 已经拆出：

```text
run_gcad_core_from_files / run_gcad_core      # raw 输入
run_canonical_gcad_from_files / run_canonical_gcad  # canonical 输入
```

这是正确边界。([GitHub][4])

`CanonicalNode.typed_params` 当前已经是 `dict[str, Any]`，这符合 JSON-safe canonical IR 的要求。([GitHub][5])

`typecheck.py` 当前已经真实比较 producer output type 与 consumer expected input type；`registry.py` 也已开始 fail-closed 检查 dialect version mismatch；`composition` pattern op 已调整为 `solid → solid`。([GitHub][6])

## 3.2 仍需修复的部分

`structure.py` 目前只检查 component id、node id、node.component 是否存在，没有在 structure stage 校验 `component.root_node` 存在、归属和 `body: solid` 输出。([GitHub][7])

`canonicalize.py` 目前已经要求 root_node，并且不再使用 implicit solid fallback；但 root_node 相关错误应该前移到 structure stage，而不是留到 canonicalize stage。([GitHub][8])

`phase.py` 目前只检查 `node.phase == op_spec.phase`，还没有检查同 component / 同 dialect 的 producer phase rank 是否小于等于 consumer phase rank。([GitHub][9])

`composition/handlers.py` 当前仍有本地 `_resolve_input()` 和 `_resolve_all_inputs()`，并且 `_resolve_input()` 在无法解析输入时 fallback 到 `ctx.resolve_node_output(node.id, "body")`；这违反“所有 handler 统一使用 runtime.resolve”的规则。([GitHub][10])

`composition.dialect.py` 当前 `boolean_union` 的 OperationSpec 是固定两个 `solid` 输入，但 `handle_boolean_union()` 允许一到多个输入；要么改成严格二元 union，要么正式引入 variadic OperationSpec。v0.2 建议保持二元 union，多个 union 用 graph 链式表达。([GitHub][10])

`pipeline/metadata.py` 当前已比较 canonical hash 和 contract hash，但还没有完整比对 `schema_version`、`canonical_version`、`trust_level`、`safety`、`op_versions`、`selected_dialects` 全量列表。([GitHub][11])

`pipeline/artifact.py` 当前仍返回空 `graph_path`、`runner_script_path: None`、空 `inspection`、空 `validation`。虽然 `builder.py` 在 metrics 中重建了较完整 artifact，但直接调用 `run_canonical_gcad()` 时返回的 artifact 仍不完整。([GitHub][12])

---

# 4. 目标架构的不可变约束

Claude Code 必须遵守：

```text
1. 不修改 deterministic primitive path 的语义；
2. 不把 generative dialect 注册到 PRIMITIVE_COMPILERS；
3. 不把 G-CAD nodes 放进 CADPartSpec；
4. 不把 PrimitiveFeature 放进 RawGcadDocument；
5. 不让 primitive compiler 导入 generative_cad.dialects；
6. 不让 generative dialect handler 调用 primitive_compiler 或 geometry_primitives deterministic kernels；
7. 不让 generative path 声明 mechanical_validation 等价通过；
8. 不把 CSGTree 作为两条链路共同 IR；
9. 不重写 primitive compiler / builder 为 CSG backend；
10. 不简化 registry.py 为两个裸函数映射；
11. 不动态生成大型 CadQuery 脚本；
12. 不允许 unresolved type fallback 为 solid；
13. 不允许 handler fallback 到当前 node output；
14. 不允许 metadata 只做格式校验；
15. 不允许 artifact 是空壳。
```

---

# 5. P0 实施任务

## P0-1：把 root_node 校验前移到 structure stage

### 当前问题

`structure.py` 没有校验 `component.root_node`。这会让 root_node 错误直到 canonicalize 才出现，错误阶段不稳定。([GitHub][7])

### 修改文件

```text
src/seekflow_engineering_tools/generative_cad/validation/structure.py
```

### 目标行为

structure stage 必须校验：

```text
1. every component.root_node must be explicit and non-empty；
2. root_node must exist；
3. root_node must belong to that component；
4. root_node must declare outputs；
5. root_node must output body: solid in v0.2；
6. __assembly__.root_node must output body: solid。
```

### 实现规格

在 `validate_structure(raw)` 中加入：

```python
node_map = {n.id: n for n in raw.nodes}

for comp in raw.components:
    root_id = (comp.root_node or "").strip()
    if not root_id:
        issues.append(
            ValidationReport.fail(
                "structure",
                "missing_component_root_node",
                f"component {comp.id!r} must explicitly declare root_node",
                component_id=comp.id,
            ).issues[0]
        )
        continue

    root = node_map.get(root_id)
    if root is None:
        issues.append(
            ValidationReport.fail(
                "structure",
                "root_node_not_found",
                f"component {comp.id!r} root_node {root_id!r} does not exist",
                component_id=comp.id,
                node_id=root_id,
            ).issues[0]
        )
        continue

    if root.component != comp.id:
        issues.append(
            ValidationReport.fail(
                "structure",
                "root_node_wrong_component",
                f"component {comp.id!r} root_node {root_id!r} belongs to {root.component!r}",
                component_id=comp.id,
                node_id=root_id,
            ).issues[0]
        )
        continue

    if not root.outputs:
        issues.append(
            ValidationReport.fail(
                "structure",
                "root_node_no_outputs",
                f"component {comp.id!r} root_node {root_id!r} has no outputs",
                component_id=comp.id,
                node_id=root_id,
            ).issues[0]
        )
        continue

    has_body_solid = any(o.name == "body" and o.type == "solid" for o in root.outputs)
    if not has_body_solid:
        issues.append(
            ValidationReport.fail(
                "structure",
                "root_node_missing_body_solid",
                f"component {comp.id!r} root_node {root_id!r} must output body: solid in v0.2",
                component_id=comp.id,
                node_id=root_id,
            ).issues[0]
        )
```

### 测试

```text
test_missing_root_node_fails_in_structure_stage
test_root_node_not_found_fails_in_structure_stage
test_root_node_wrong_component_fails_in_structure_stage
test_root_node_without_body_solid_fails_in_structure_stage
```

---

## P0-2：补 phase dependency order 检查

### 当前问题

`phase.py` 只检查 `node.phase == op_spec.phase`，没有检查依赖边的 phase 顺序。([GitHub][9])

### 修改文件

```text
src/seekflow_engineering_tools/generative_cad/validation/phase.py
```

### 目标行为

同 component / 同 dialect 内：

```text
producer_phase_rank <= consumer_phase_rank
```

反向依赖必须 fail：

```text
edge_treatment → primary_cut
```

### 实现规格

在 `validate_phase(raw)` 中新增：

```python
node_map = {n.id: n for n in raw.nodes}

for node in raw.nodes:
    try:
        dialect = require_dialect(node.dialect)
    except KeyError:
        continue

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
                    (
                        f"node {node.id!r} phase {node.phase!r} depends on later "
                        f"phase {producer.phase!r} from node {producer.id!r}"
                    ),
                    node_id=node.id,
                    expected=f"producer phase rank <= {cr}",
                    actual=f"producer phase rank {pr}",
                ).issues[0]
            )
```

### 测试

```text
test_phase_reverse_dependency_fails
test_same_phase_dependency_allowed
test_forward_phase_dependency_allowed
```

---

## P0-3：composition handlers 必须统一使用 runtime.resolve

### 当前问题

`composition/handlers.py` 仍然有 `_resolve_input()`，并且 fallback 到 `ctx.resolve_node_output(node.id, "body")`。这是之前反复强调要禁止的模式。([GitHub][10])

### 修改文件

```text
src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py
```

### 目标行为

删除本地：

```python
_resolve_input
_resolve_all_inputs
```

统一使用：

```python
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_handle_id,
    resolve_input_object,
    resolve_all_input_objects,
)
```

### 具体改法

```python
def handle_translate_solid(node, ctx):
    body = resolve_input_object(node, ctx, 0)
    vector = node.typed_params.get("vector_mm", node.params.get("vector_mm", (0, 0, 0)))
    result = body.translate(vector)
    return {"body": _store_solid(node, ctx, result)}
```

```python
def handle_boolean_union(node, ctx):
    solids = resolve_all_input_objects(node, ctx)
    if len(solids) != 2:
        raise ValueError("boolean_union v0.2 requires exactly two input solids")
    result = solids[0].union(solids[1])
    return {"body": _store_solid(node, ctx, result)}
```

```python
def handle_boolean_cut(node, ctx):
    solids = resolve_all_input_objects(node, ctx)
    if len(solids) != 2:
        raise ValueError("boolean_cut v0.2 requires exactly two input solids")
    result = solids[0].cut(solids[1])
    return {"body": _store_solid(node, ctx, result)}
```

### 注意

`body.translate(vector)` 是否是你们当前 CadQuery object 的稳定 API，需要用 mock + optional real-CadQuery 测试确认。CSG 报告里关于 CadQuery API 的提醒可以吸收为测试，而不是因此引入统一 CSG backend。

### 测试

```text
test_no_composition_handler_uses_current_node_output_fallback
test_composition_handlers_use_runtime_resolve
test_boolean_union_requires_exactly_two_inputs_in_v02
test_boolean_cut_requires_exactly_two_inputs_in_v02
```

---

## P0-4：让 composition boolean_union 语义与 OperationSpec 一致

### 当前问题

`composition.dialect.py` 中 `boolean_union` 的 `input_types=["solid", "solid"]`，但 handler 接受任意数量输入，且只要求非空。([GitHub][10])

### 决策

v0.2 不引入 variadic op。`boolean_union` 是**二元 op**。

多个 union 必须由 graph 表达为：

```text
n_union_1 = union(a, b)
n_union_2 = union(n_union_1, c)
n_union_3 = union(n_union_2, d)
```

### 修改

保持 OperationSpec 不变：

```python
input_types=["solid", "solid"]
output_types=["solid"]
```

修改 handler，严格要求两个输入。

### 测试

```text
test_boolean_union_three_inputs_fails_typecheck_or_runtime
test_chained_binary_union_allowed
```

---

## P0-5：metadata v2 provenance 必须强校验

### 当前问题

`metadata.py` 已经检查 metadata_version、source_route、trust_level、selected_dialects、canonical_graph_hash、runner_version、geometry_runtime、safety 等，并且在 canonical provided 时比较 canonical graph hash 和 contract hash；但还没有完整比较 `schema_version`、`canonical_version`、`trust_level`、`safety`、`op_versions`、`selected_dialects` 全量内容。([GitHub][11])

### 修改文件

```text
src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py
```

### 目标行为

当传入 `canonical` 时，必须严格比较：

```text
gm.schema_version == canonical.schema_version
gm.canonical_version == canonical.canonical_version
gm.trust_level == canonical.trust_level
gm.safety == canonical.safety.model_dump()
gm.raw_graph_hash == canonical.raw_graph_hash
gm.canonical_graph_hash == canonical.canonical_graph_hash
gm.op_versions == canonical.nodes 的 op version 列表
gm.selected_dialects == canonical.selected_dialects 的 dialect/version/contract_hash 列表
```

### 实现规格

加入：

```python
if canonical is not None:
    if gm.get("schema_version") != canonical.schema_version:
        issues.append({"code": "schema_version_mismatch", "message": "metadata schema_version != canonical.schema_version"})

    if gm.get("canonical_version") != canonical.canonical_version:
        issues.append({"code": "canonical_version_mismatch", "message": "metadata canonical_version != canonical.canonical_version"})

    if gm.get("trust_level") != canonical.trust_level:
        issues.append({"code": "trust_level_mismatch", "message": "metadata trust_level != canonical.trust_level"})

    if gm.get("safety") != canonical.safety.model_dump():
        issues.append({"code": "safety_mismatch", "message": "metadata safety flags != canonical safety flags"})

    expected_ops = [
        {
            "node_id": n.id,
            "dialect": n.dialect,
            "op": n.op,
            "op_version": n.op_version,
        }
        for n in canonical.nodes
    ]
    if gm.get("op_versions") != expected_ops:
        issues.append({"code": "op_versions_mismatch", "message": "metadata op_versions != canonical node op_versions"})

    expected_dialects = [
        {
            "dialect": d.dialect,
            "version": d.version,
            "contract_hash": d.contract_hash,
        }
        for d in canonical.selected_dialects
    ]
    if gm.get("selected_dialects") != expected_dialects:
        issues.append({"code": "selected_dialects_mismatch", "message": "metadata selected_dialects != canonical selected_dialects"})
```

### 测试

```text
test_metadata_rejects_schema_version_drift
test_metadata_rejects_canonical_version_drift
test_metadata_rejects_trust_level_drift
test_metadata_rejects_safety_drift
test_metadata_rejects_op_versions_drift
test_metadata_rejects_selected_dialects_drift
test_metadata_rejects_contract_hash_drift
```

---

## P0-6：artifact builder 不能返回空壳

### 当前问题

`pipeline/artifact.py` 当前返回：

```text
graph_path = ""
runner_script_path = None
inspection = {}
validation = {}
```

这是不完整 artifact。([GitHub][12])

### 修改文件

```text
src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py
src/seekflow_engineering_tools/generative_cad/builder.py
```

### 目标设计

`build_canonical_step_artifact()` 应支持可选参数：

```python
def build_canonical_step_artifact(
    canonical,
    step_path: Path,
    metadata_path: Path,
    ctx,
    graph_path: Path | None = None,
    runner_script_path: Path | None = None,
    inspection: dict | None = None,
    validation: dict | None = None,
) -> dict:
    ...
```

返回：

```python
{
    "artifact_type": "canonical_step_artifact",
    "source_route": "llm_skill_base",
    "part_name": canonical.part_name,
    "step_path": str(step_path),
    "metadata_path": str(metadata_path),
    "graph_path": str(graph_path) if graph_path else None,
    "runner_script_path": str(runner_script_path) if runner_script_path else None,
    "units": canonical.units,
    "trust_level": canonical.trust_level,
    "native_rebuild_allowed": False,
    "step_import_allowed": True,
    "inspection": inspection or {},
    "validation": validation or {
        "core_validation": {},
        "geometry_preflight": {},
        "inspection_validation": {},
    },
}
```

`builder.py` 当前已经在 `metrics["artifact"]` 中重建 artifact；继续保留这个行为，但改为调用 `build_canonical_step_artifact()`，避免 builder 和 pipeline 两处 artifact schema 漂移。([GitHub][3])

### 测试

```text
test_artifact_builder_accepts_graph_and_script_paths
test_build_metrics_include_complete_artifact
test_run_direct_artifact_uses_none_for_graph_and_script_paths
test_artifact_contains_inspection_after_builder_inspection
```

---

# 6. P1 实施任务

## P1-1：增强 dual-route isolation tests

新增测试文件：

```text
tests/text_to_cad/test_dual_route_isolation.py
```

### 必测项

```text
1. primitive_compiler.py 不导入 generative_cad；
2. generative_cad/dialects 不导入 primitive_compiler；
3. PRIMITIVE_COMPILERS 不包含 axisymmetric / sketch_extrude / composition；
4. DIALECT_REGISTRY 不包含 involute_spur_gear / axisymmetric_turbine_disk；
5. CADPartSpec reject G-CAD envelope fields；
6. RawGcadDocument reject CADPartSpec features；
7. engineering_build_cad_model 不调用 generative_cad_build_from_ir；
8. generative_cad_build_from_ir 不调用 engineering_build_cad_model；
9. primitive metadata schema 与 generative_metadata_v2 distinct；
10. mechanical_validation 只存在 primitive path，generative path 不声明机械验证通过。
```

当前 primitive compiler 明确注册 `involute_spur_gear` 和 `axisymmetric_turbine_disk`，并通过 `PRIMITIVE_COMPILERS` 分发；这条链路应作为隔离测试的保护对象。([GitHub][13])

---

## P1-2：吸收 pyproject.toml，但 CadQuery 用 optional extra

新增：

```text
integrations/engineering_tools/pyproject.toml
```

建议：

```toml
[build-system]
requires = ["hatchling>=1.21.0"]
build-backend = "hatchling.build"

[project]
name = "seekflow-engineering-tools"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6.0,<3.0.0"
]

[project.optional-dependencies]
cad = [
    "cadquery>=2.4.0"
]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0"
]

[tool.hatch.build.targets.wheel]
packages = ["src/seekflow_engineering_tools"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "requires_cadquery: tests requiring a real cadquery installation"
]
```

不要把 CadQuery 作为基础必需依赖，否则纯 validator / schema / tool registry 测试会被 CAD 环境绑死。

---

## P1-3：引入 cadquery helper，但不要 CSG backend

新增：

```text
src/seekflow_engineering_tools/generative_cad/runtime/cadquery_helpers.py
```

用于封装常见 API：

```python
from __future__ import annotations

def translate_body(body, vector_mm):
    return body.translate(tuple(vector_mm))

def rotate_body(body, origin_mm, axis_dir, angle_deg):
    return body.rotate(tuple(origin_mm), tuple(axis_dir), float(angle_deg))

def boolean_union(a, b):
    return a.union(b)

def boolean_cut(a, b):
    return a.cut(b)
```

注意：这些 helper 只服务 generative runtime，不替代 primitive deterministic kernels。CadQuery API 正确性来自单元测试与 optional real-CadQuery integration test，不来自统一 CSG codegen。

---

## P1-4：错误类型可以引入，但只在边界层使用

新增：

```text
src/seekflow_engineering_tools/errors.py
```

可定义：

```python
class SeekflowError(Exception): ...
class IRValidationError(SeekflowError): ...
class GcadValidationError(SeekflowError): ...
class RuntimeResolutionError(SeekflowError): ...
class DialectExecutionError(SeekflowError): ...
class MetadataValidationError(SeekflowError): ...
class ArtifactError(SeekflowError): ...
```

但不要像 CSG 报告那样要求“所有模块禁止抛 ValueError/TypeError”。内部局部函数可以抛标准异常，builder/tool 边界统一包装为 `EngineeringActionResult` 或 `ValidationReport`。

---

# 7. P2 质量任务

## P2-1：测试中 mock CadQuery

从 CSG 报告吸收 mock CadQuery 思想。

建议：

```text
tests/conftest.py
```

提供：

```python
@pytest.fixture
def mock_cadquery(monkeypatch):
    ...
```

用于 unit tests。真实 STEP 测试放到：

```python
@pytest.mark.requires_cadquery
```

---

## P2-2：CadQuery API 回归测试

不要用它驱动架构重写，只做 regression tests：

```text
test_composition_translate_uses_expected_cadquery_api
test_composition_rotate_uses_expected_cadquery_api
test_boolean_union_uses_union
test_boolean_cut_uses_cut
test_export_step_uses_cq_exporters
```

---

## P2-3：旧 generative legacy 模块标记 deprecated

如果仍存在：

```text
generative_cad/runner.py
generative_cad/base.py
generative_cad/registry.py
generative_cad/graph_validation.py
generative_cad/metadata.py
```

需要确认它们不是 public path。可以加 deprecation warning，但不要影响当前 v0.2 pipeline。

---

# 8. Claude Code 最终执行 Prompt

下面这段可以直接交给 Claude Code。

```text
You are working in WYZAAACCC/seekflow-engineering under integrations/engineering_tools.

Important:
Do NOT implement the uploaded CSGTree unification proposal as-is.
That proposal contains useful low-level bugfix ideas, but its core architecture is wrong for this project.

The correct architecture is dual-route:

Route A: Deterministic CAD-IR / Primitive Path.
- Uses CADPartSpec, PrimitiveFeature, cadquery_backend/compiler.py, cadquery_backend/primitive_compiler.py, cadquery_backend/builder.py, geometry_primitives, mechanical_validation.
- Used for high-certainty, high-precision, engineering-semantic CAD.
- Must remain independent and must not be replaced by CSGTree or generative G-CAD.

Route B: Generative G-CAD Core IR Path.
- Uses RawGcadDocument, CanonicalGcadDocument, dialect registry, OperationSpec, validation pipeline, RuntimeObjectStore, composition dialect, generative_metadata_v2.
- Used for free-form reference/concept geometry.
- Must remain separate from primitive path.
- Must not claim manufacturing-ready, certified, airworthy, installable, or mechanically validated geometry.

Reject from the CSG proposal:
1. Do not introduce CSGTree as a shared IR for primitive and generative.
2. Do not rewrite primitive compiler/builder to use CSG frontend/backend.
3. Do not replace G-CAD dialect graph with BOX/CYLINDER/SPHERE stack machine.
4. Do not return mechanical_validation: valid=True from generative path.
5. Do not simplify registry.py to a two-function dict.
6. Do not delete geometry_primitives.
7. Do not merge primitive metadata and generative metadata.

Allowed to absorb from the CSG proposal:
1. Add pyproject.toml, but put cadquery in optional extra.
2. Use Pydantic v2 and discriminated unions where applicable.
3. Add positive dimension validation where applicable.
4. Add empty features / empty graph fail-closed checks.
5. Add CadQuery API helper tests.
6. Mock cadquery in unit tests.
7. Add better error classes at module boundaries.
8. Add STEP file existence/non-empty checks where missing.

Current code facts:
- generative_cad/tools.py already uses RawGcadDocument, validate_and_canonicalize, dialect registry, and build_generative_cad_model.
- generative_cad/builder.py already writes canonical JSON and harness calls run_canonical_gcad_from_files.
- generative_cad/pipeline/run.py already has raw and canonical entrypoints.
- CanonicalNode.typed_params is dict[str, Any].
- typecheck compares producer output type with consumer expected input type.
- composition pattern ops are solid -> solid.
Remaining tasks are targeted hardening tasks, not a rewrite.

Tasks:

P0-1. Move root_node validation into structure stage.
File: generative_cad/validation/structure.py
Rules:
- every component.root_node must be explicit and non-empty;
- root_node must exist;
- root_node must belong to that component;
- root_node must have outputs;
- root_node must output body: solid in v0.2;
- __assembly__.root_node must output body: solid.
Add tests for all failure modes.

P0-2. Add dependency phase order validation.
File: generative_cad/validation/phase.py
Keep existing node.phase == op_spec.phase check.
Additionally, for same-component same-dialect node-to-node dependencies:
producer_phase_rank <= consumer_phase_rank.
Add tests for reverse phase failure, same phase allowed, forward phase allowed.

P0-3. Refactor composition handlers to use runtime.resolve only.
File: generative_cad/dialects/composition/handlers.py
Delete local _resolve_input and _resolve_all_inputs.
Use:
- resolve_input_object
- resolve_all_input_objects
from generative_cad/runtime/resolve.py.
Remove any ctx.resolve_node_output(node.id, "body") fallback.
Add grep/inspect test preventing this fallback.

P0-4. Make composition boolean ops strictly binary in v0.2.
File: generative_cad/dialects/composition/handlers.py
OperationSpec already uses input_types=["solid", "solid"].
Handler must require exactly two input solids.
For multiple inputs, graph must chain binary union/cut.
Add tests.

P0-5. Strengthen metadata v2 provenance validation.
File: generative_cad/pipeline/metadata.py
When canonical is provided, compare:
- schema_version
- canonical_version
- trust_level
- safety
- raw_graph_hash
- canonical_graph_hash
- op_versions
- selected_dialects including version and contract_hash
Add mutation tests for each mismatch.

P0-6. Fix artifact builder so artifact is not an empty shell.
File: generative_cad/pipeline/artifact.py
Allow graph_path, runner_script_path, inspection, validation optional args.
Return None for unavailable direct-run paths, not empty string.
Update builder.py to use artifact builder for metrics["artifact"].
Add tests.

P1-1. Add dual-route isolation tests.
Tests must prove:
- primitive_compiler does not import generative_cad;
- generative dialects do not import primitive_compiler or geometry_primitives deterministic kernels;
- PRIMITIVE_COMPILERS contains only primitives, not dialects;
- DIALECT_REGISTRY contains only dialects, not primitives;
- CADPartSpec rejects G-CAD envelope fields;
- RawGcadDocument rejects CADPartSpec features;
- engineering_build_cad_model does not call generative_cad_build_from_ir;
- generative_cad_build_from_ir does not call engineering_build_cad_model;
- primitive metadata and generative_metadata_v2 are distinct;
- mechanical_validation remains primitive-only.

P1-2. Add pyproject.toml.
CadQuery must be optional extra, not mandatory base dependency.
Add pytest marker requires_cadquery.

P1-3. Add generative_cad/runtime/cadquery_helpers.py if useful.
This may wrap translate/rotate/union/cut/export operations.
Do not use it to replace primitive deterministic kernels.

P1-4. Add boundary error classes if useful.
Do not ban all built-in ValueError/KeyError internally.
Only normalize errors at builder/tool boundaries.

P2. Add CadQuery API mock tests.
Unit tests should mock cadquery.
Real STEP tests should be marked requires_cadquery.

Acceptance criteria:
- All existing primitive/CAD-IR tests pass.
- All generative v0.2 tests pass.
- No CSGTree shared IR is introduced.
- Primitive path remains deterministic and independent.
- Generative path remains dialect/Core IR based.
- Both routes only converge at STEP + metadata + inspection/artifact.
- No generative mechanical_validation success claim.
- Metadata v2 detects graph/op/safety/dialect drift.
- Artifact metrics are complete.
```

---

# 9. 最终验收标准

完成后应满足：

```text
1. Primitive path 保持原有 deterministic kernel、metadata sidecar、mechanical validation；
2. Generative path 保持 RawGcadDocument → CanonicalGcadDocument → dialect runner；
3. 没有 CSGTree shared IR；
4. 没有 stack-machine G-CAD 替代 dialect graph；
5. root_node 错误在 structure stage fail；
6. phase reverse dependency fail；
7. composition handlers 统一使用 runtime.resolve；
8. composition boolean ops 与 OperationSpec 一致；
9. metadata v2 可以检测 provenance drift；
10. artifact 不再是空壳；
11. 单元测试 mock CadQuery；
12. 真实 CadQuery 测试可选；
13. 双链路隔离测试阻止未来架构滑坡。
```

最核心的一句话要写进项目文档：

```text
SeekFlow text_to_cad is a dual-route CAD system:
deterministic CAD-IR / Primitive path for high-certainty engineering models,
and Generative G-CAD Core IR path for controlled free-form reference geometry.
The two routes are isolated before artifact generation and converge only at STEP + metadata + inspection.
```

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/tools.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/registry.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/typecheck.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/structure.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/phase.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
