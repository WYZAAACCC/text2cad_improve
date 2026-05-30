# SeekFlow Generative CAD-IR vNext 顶级工程实施文档

**面向 Claude Code 的可落地实现规范**

下面这份文档不是普通建议，而是可以直接交给 Claude Code 执行的工程蓝图。目标是把当前 `generative_cad / text_to_cad` 从“结构正确的工程原型”推进到“编译器内核级、可演进、可审计、fail-closed、低频修改核心编译器”的架构。

我重新审阅了当前仓库源码。当前代码已经修正了上一轮几个关键问题：`RawGcadDocument.safety / constraints` 已显式必填，`parse_raw_gcad_document()` 已接入 validation pipeline，canonical runner 已要求 `validation_seed_json`，artifact state 已变成 `validated_reference_step / step_import_allowed=False`，`GeometryRuntime / CadQueryRuntime` 已经落地。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py))
但仍存在“半接入 ABI”问题：`OperationResult` / `execute_operation()` 定义了但 dialect execution 仍绕过它；`Frozen DialectRegistry` 定义了但生产 registry 仍是 global import-time registry；`MetadataProofV3` 定义了但 builder / runner / import gate 仍走 v2；typed `CanonicalStepArtifact` model 定义了但 artifact builder 返回手写 dict；repair prompt 仍含 `/nodes//params/` 这种无效路径。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py))

---

# 0. 最终目标

你的方向是对的：这不是做一个“LLM 直接写 CAD 代码”的 demo，而是构建一条**独立、受控、可验证的 Generative CAD-IR 编译链路**。架构基线明确要求：LLM 不直接写 CadQuery / SolidWorks COM / NXOpen / APDL，LLM 只输出 G-CAD Core IR；系统负责 Core Validator、Canonical IR、BaseDialect / OperationSpec、GeometryRuntime、STEP、metadata proof 和 import gate；最终合流点只能是 STEP + metadata，而不是 Primitive compiler。

最终 pipeline 必须是：

```text
User request
  ↓
Level-1 Routing Skill
  ↓
DialectSelectionPlan
  ↓
Load Dialect Contracts
  ↓
Level-2 Authoring Skill
  ↓
RawGcadDocument JSON
  ↓
parse_raw_gcad_document
  ↓
RawGcadDocument
  ↓
ValidationBundle
  ↓
CanonicalGcadDocument
  ↓
LinkedExecutablePlan
  ↓
BaseDialect.run_component
  ↓
execute_operation
  ↓
OperationResult
  ↓
RuntimeObjectStore + GeometryRuntime
  ↓
STEP export
  ↓
runtime_postconditions
  ↓
STEP inspection
  ↓
MetadataProofV3
  ↓
CanonicalStepArtifact
  ↓
Import Gate
  ↓
native_import_eligible STEP import only
```

禁止路径：

```text
LLM → CadQuery code
LLM → SolidWorks COM
LLM → NXOpen
LLM → APDL
LLM → file path
LLM → subprocess
Raw JSON → BaseDialect directly
Canonical IR without validation proof → STEP artifact
Generative CAD → Primitive compiler
Generative CAD → geometry_primitives
Generative CAD → CADPartSpec mutation
```

---

# 1. 当前代码状态的精准判断

## 1.1 已经修对的部分

### Raw IR 显式 safety / constraints

当前 `RawConstraints` 的核心字段已经显式必填，`RawSafety` 七个安全 flag 也显式必填；`RawGcadDocument` 的 `schema_version`、`units`、`trust_level`、`constraints`、`safety` 都是显式字段，不再通过 default_factory 静默补齐。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py))

### parse 层已存在

`parse_raw_gcad_document()` 已经检查 required top-level keys、required safety keys、required constraints keys，并返回 structured parse issues。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/parse.py))

### runner validation proof 已收紧

`run_canonical_gcad_from_files()` 当前要求 `validation_seed_json`，`run_canonical_gcad()` 要求 non-empty validation seed，并 deep-copy seed 后添加 runtime postconditions。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py))

### builder harness 已传 validation seed

builder 当前会写 `.validation.json`，并生成固定 runner harness，将 `canonical_json`、`validation_seed_json`、`out_step`、`metadata_path` 一起传给 `run_canonical_gcad_from_files()`。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py))

### GeometryRuntime 已落地

`RuntimeContext` 当前持有 `geometry_runtime`，并通过 `geometry_runtime_name` 暴露 runtime id；runner export 已经调用 `ctx.geometry_runtime.export_step(...)`，不是直接在 runner 中调用 CadQuery exporter。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py))

---

## 1.2 当前仍然不合格的部分

### 问题 A：OperationResult ABI 未接入生产执行路径

当前 `OperationSpec.handler` 仍是 `Callable[..., dict[str, str]]`，`handler_kind` 默认仍是 `"v1_dict"`。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py))
虽然 `OperationResult` 和 `execute_operation()` 已经存在，但 axisymmetric / sketch_extrude / composition 的 `run_component()` 仍直接调用 `op_spec.handler(node, ctx)`，然后绑定 dict outputs；这意味着 runtime output name / type / handle 并没有统一验证。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py))

更严重的是：`execute_operation()` 调用 `ctx.object_store.get_typed(...)`，但当前 `RuntimeObjectStore` 只有 `get()`、`get_handle()`、`put_*()`，没有 `get_typed()`。一旦把 dialect 接到 executor，会直接 AttributeError。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/object_store.py))

### 问题 B：Frozen DialectRegistry 未进入生产路径

`registry_core.py` 和 `default_registry.py` 已经定义了 frozen registry，但生产 `dialects/registry.py` 仍是 module-level `DIALECT_REGISTRY`，并在 import 时 populate。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/registry_core.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/default_registry.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/registry.py))

这对编译器式系统不健康：registry 必须显式、可冻结、可注入、可测试隔离。

### 问题 C：MetadataProofV3 未进入生产路径

`metadata_v3.py` 已经实现 paths、runtime proof、artifact hash、import policy、validation proof 等字段，但 `pipeline/run.py` 仍然 import 并调用 `build_generative_metadata`，也就是 v2 builder；`builder.py` 和 `import_artifact.py` 也仍然使用 `validate_generative_metadata_v2`。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/import_artifact.py))

metadata 必须是 provenance proof，而不是 side note；你的记忆文档要求 metadata 至少包含 source_route、trust_level、schema_version、dialect/op versions、graph hash、contract hash、runner/runtime、repair、validation、warnings、degraded_features、safety、source_ir_path、step_path，并且缺失必须 fail。

### 问题 D：CanonicalStepArtifact model 未进入 builder

`artifact_models.py` 已定义 `CanonicalStepArtifact`，但 `artifact.py` 仍手写 dict，且不计算 `step_sha256` / `metadata_sha256`。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact_models.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py))

### 问题 E：Repair prompt path 错误

当前 repair prompt 仍包含 `/nodes//dialect`、`/nodes//params/`、`/components//root_node` 等无效 path；测试文件同时断言这些 path 存在和不存在，测试本身是矛盾的。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/tests/generative_cad/test_gcad_v10_prompt_paths.py))
记忆文档明确要求 repair path 必须使用 `/nodes/<node_id>/params/<field>` 这种有效占位。

---

# 2. 真正正确的目标架构

## 2.1 核心架构

```text
Raw authoring layer
  - Level-1 Routing Skill
  - Level-2 Dialect Usage Skill

Compiler front-end
  - parse_raw_gcad_document
  - RawGcadDocument
  - Structure validation
  - Registry validation
  - Params validation
  - Graph validation
  - Typecheck
  - Phase validation
  - Safety validation

Compiler middle-end
  - CanonicalGcadDocument
  - Contract hash linking
  - op_version resolution
  - typed params
  - typed inputs/outputs
  - phase-ordered dependency graph

Execution back-end
  - Frozen DialectRegistry
  - BaseDialect.run_component
  - execute_operation
  - OperationResult
  - RuntimeObjectStore typed handles
  - GeometryRuntime

Artifact layer
  - STEP export
  - runtime_postconditions
  - STEP inspection
  - MetadataProofV3
  - CanonicalStepArtifact
  - ImportGateResult
```

## 2.2 永久不变量

这些不变量必须作为测试存在：

```text
1. Raw JSON 必须先 parse，不能直接进入 BaseDialect。
2. Core IR 不知道 op-specific params。
3. node.params 只由 OperationSpec.params_model 校验。
4. Unknown dialect/op/op_version 必须 fail-closed。
5. BaseDialect 之间不能互相调用。
6. 多 dialect 组合只能通过 composition dialect。
7. RuntimeObjectStore 只传 typed handles，不传裸 CadQuery object 跨 dialect。
8. runner 只能接受 CanonicalGcadDocument + ValidationBundle proof。
9. Artifact 生成不等于 native import allowed。
10. Import gate 是 native import eligibility 的唯一权威。
11. Generative artifact 永远 native_rebuild_allowed=False。
12. trust_level 永远不超过 reference_geometry。
13. Primitive path 不受 generative path 污染。
```

这些不变量直接对应你上传的硬约束：不改 deterministic primitive path、不改 primitive compiler、不把 generative 加进 primitive registry、所有 LLM 输出必须通过 Raw → Canonical validation、unknown dialect/op fail-closed、runner 固定 harness、输出是 canonical STEP artifact with metadata。

---

# 3. 实施 Milestone 总览

```text
M0: 不碰 Primitive 主链路
M1: OperationResult ABI 贯通生产 execution
M2: RuntimeObjectStore typed handle API
M3: Frozen DialectRegistry 接管生产路径
M4: MetadataProofV3 接入 run / builder / import gate
M5: CanonicalStepArtifact typed model 接入 artifact builder
M6: Repair prompt path 和测试修复
M7: Prompt ABI 升级
M8: Legacy namespace 最终隔离
M9: 行为测试替代源码字符串测试
```

---

# M0. 禁止修改范围

Claude Code 必须遵守：

```text
Do not modify cadquery_backend/primitive_compiler.py.
Do not modify geometry_primitives/.
Do not modify CADPartSpec semantics.
Do not add generative dialects to PRIMITIVE_COMPILERS.
Do not add generative fields to deterministic CAD-IR.
Do not route generative outputs through primitive compiler.
```

允许修改：

```text
generative_cad/
tests/generative_cad/
tool descriptions related to generative_cad
```

---

# M1. OperationResult ABI 贯通生产 execution

## 目标

把当前：

```text
handler -> dict[str, str]
```

升级为：

```text
handler -> OperationResult
```

并让所有 dialect 必须通过统一 executor：

```text
BaseDialect.run_component
  → execute_operation(node, op_spec, ctx)
  → OperationResult validation
  → ctx.bind_node_output(...)
```

## 修改文件

```text
src/seekflow_engineering_tools/generative_cad/runtime/object_store.py
src/seekflow_engineering_tools/generative_cad/dialects/operation.py
src/seekflow_engineering_tools/generative_cad/dialects/executor.py
src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py
src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/dialect.py
src/seekflow_engineering_tools/generative_cad/dialects/composition/dialect.py
tests/generative_cad/test_vnext_operation_result_behavior.py
```

## 1.1 修改 RuntimeObjectStore

当前 executor 调 `get_typed()`，但 object store 没有该方法。必须新增：

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class StoredRuntimeObject:
    handle_id: str
    value_type: str
    handle: RuntimeHandle
    obj: Any

class RuntimeObjectStore:
    ...

    def get_typed(self, handle_id: str) -> StoredRuntimeObject:
        if handle_id not in self._handles:
            raise KeyError(f"runtime handle not found: {handle_id}")
        if handle_id not in self._objects:
            raise KeyError(f"runtime object not found: {handle_id}")
        handle = self._handles[handle_id]
        return StoredRuntimeObject(
            handle_id=handle_id,
            value_type=handle.value_type,
            handle=handle,
            obj=self._objects[handle_id],
        )
```

如果 `RuntimeHandle` 当前字段不是 `value_type`，而是 `type` / `kind`，则只允许在 `get_typed()` 内统一映射成 `value_type`。不要让 executor 猜字段名。

## 1.2 修改 OperationHandler 类型

当前：

```python
OperationHandler = Callable[..., dict[str, str]]
```

改成：

```python
from typing import Callable
from seekflow_engineering_tools.generative_cad.dialects.results import OperationResult

OperationHandler = Callable[
    [CanonicalNode, RuntimeContext],
    OperationResult | dict[str, str],
]
```

保留 transitional：

```python
handler_kind: Literal["v1_dict", "v2_result"] = "v1_dict"
```

但新增 validator：

```python
def is_legacy_handler_allowed(self) -> bool:
    return self.handler_kind == "v1_dict"
```

新 op 必须写：

```python
handler_kind="v2_result"
```

## 1.3 修改所有 dialect.run_component

把：

```python
outputs = op_spec.handler(node, ctx)
for name, hid in outputs.items():
    ctx.bind_node_output(node.id, name, hid)
    final_outputs[name] = hid
```

改成：

```python
from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
for name, hid in executed.outputs.items():
    final_outputs[name] = hid
```

保留 optional degradation 逻辑，但必须围绕 `execute_operation()`：

```python
try:
    executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
except Exception as exc:
    if not node.required and node.degradation_policy == "may_skip_with_warning":
        ctx.warnings.append(...)
        ctx.degraded_features.append(...)
        ctx.operation_metrics.append(...)
        continue
    raise
```

## 1.4 executor 必须校验

`execute_operation()` 必须校验：

```text
result.ok is true
result.outputs names == node.outputs names
result_output.value_type == node output type
handle exists
stored handle value_type == declared type
```

禁止只 bind 不校验。

## 1.5 测试

新增：

```text
tests/generative_cad/test_vnext_operation_result_behavior.py
```

必须覆盖：

```python
def test_executor_rejects_missing_output_name(): ...
def test_executor_rejects_extra_output_name(): ...
def test_executor_rejects_output_type_mismatch(): ...
def test_executor_rejects_missing_handle(): ...
def test_executor_rejects_handle_type_mismatch(): ...
def test_axisymmetric_run_component_uses_execute_operation(monkeypatch): ...
def test_sketch_extrude_run_component_uses_execute_operation(monkeypatch): ...
def test_composition_run_component_uses_execute_operation(monkeypatch): ...
def test_v1_dict_adapter_still_works_for_existing_builtin_ops(): ...
def test_v2_result_metrics_warnings_degraded_features_propagate(): ...
```

验收：

```bash
pytest tests/generative_cad/test_vnext_operation_result_behavior.py -q
pytest tests/generative_cad -q
```

---

# M2. Frozen DialectRegistry 接入生产路径

## 目标

生产 registry 必须变成：

```text
default_registry() -> frozen DialectRegistry
```

而不是 import-time global mutable `DIALECT_REGISTRY`。

## 修改文件

```text
generative_cad/dialects/registry.py
generative_cad/validation/registry.py
generative_cad/validation/params.py
generative_cad/validation/typecheck.py
generative_cad/validation/canonicalize.py
generative_cad/pipeline/metadata.py
generative_cad/pipeline/metadata_v3.py
tests/generative_cad/test_vnext_registry_freeze_behavior.py
```

## 2.1 改写 dialects/registry.py

替换为 compatibility wrapper：

```python
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

def require_dialect(dialect_id: str):
    return default_registry().require(dialect_id)

def get_dialect(dialect_id: str):
    return default_registry().get(dialect_id)

def list_dialects() -> list[str]:
    return default_registry().list_ids()

def export_dialect_catalog() -> dict:
    return default_registry().export_catalog()

def dialect_contract_hash(dialect_id: str) -> str:
    return default_registry().contract_hash(dialect_id)
```

删除：

```text
DIALECT_REGISTRY = {}
populate_registry()
register_dialect(...)
import-time populate side effect
```

## 2.2 validation pipeline 支持 registry 注入

函数签名升级：

```python
def validate_and_canonicalize_with_bundle(raw, *, registry: DialectRegistry | None = None):
    registry = registry or default_registry()
```

下游 registry / params / typecheck / canonicalize 都通过参数传入 registry，不要直接 import global `require_dialect`。

短期可以保留 wrapper，但最终 production path 应注入 registry。

## 2.3 测试

新增：

```python
def test_default_registry_is_frozen(): ...
def test_frozen_registry_rejects_late_registration(): ...
def test_registry_rejects_duplicate_dialect(): ...
def test_registry_rejects_part_named_dialect(): ...
def test_validation_uses_injected_registry(): ...
def test_no_import_time_populate_registry_side_effect(): ...
def test_contract_hash_stable(): ...
```

---

# M3. MetadataProofV3 接入生产路径

## 目标

`MetadataProofV3` 必须成为 production builder / runner / import gate 的唯一 metadata schema。v2.1 只保留 compatibility。

## 修改文件

```text
generative_cad/pipeline/run.py
generative_cad/builder.py
generative_cad/pipeline/import_artifact.py
generative_cad/tools.py
generative_cad/pipeline/metadata_v3.py
tests/generative_cad/test_vnext_metadata_v3_behavior.py
```

## 3.1 run.py 改用 v3

当前 `run.py` 用：

```python
from ...pipeline.metadata import build_generative_metadata
```

改成：

```python
from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import (
    build_generative_metadata_v3,
)
```

但 `run_canonical_gcad()` 当前没有 `canonical_ir_path` 和 `validation_seed_path` 参数。必须升级签名：

```python
def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    validation_seed: dict,
    *,
    canonical_ir_path: str | Path | None = None,
    validation_seed_path: str | Path | None = None,
    require_full_validation_seed: bool = True,
) -> GcadRunResult:
```

`run_canonical_gcad_from_files()` 调用时传入：

```python
canonical_ir_path=canonical_json
validation_seed_path=validation_seed_json
```

Raw entrypoint `run_gcad_core()` 没有文件路径时，可传：

```python
canonical_ir_path="<in_memory>"
validation_seed_path="<in_memory>"
```

但 production builder 必须传真实 path。

## 3.2 metadata v3 build 时机

runner export STEP 后才可计算真实 `step_sha256`。因此顺序必须是：

```text
_run_components
runtime_postconditions
_export_final_solid
validation = deepcopy(seed)
validation["runtime_postconditions"] = runtime_pc
metadata = build_generative_metadata_v3(... step_path=out_step ...)
write metadata
validate metadata v3 require_validation_ok=False or partial
```

注意：runner 阶段尚未有 inspection_validation，builder 会补充 inspection 后 final validation。为了避免 v3 validator 在 runner 阶段误判，`build_generative_metadata_v3` 仍可以 normalize missing inspection to `ok=False`；production builder 最终必须补全并 require_validation_ok=True。

## 3.3 builder 改用 v3

替换：

```python
validate_generative_metadata_v2(...)
```

为：

```python
validate_generative_metadata_v3(
    metadata,
    canonical=canonical,
    registry=default_registry(),
    require_validation_ok=False,
)
```

inspection 后重写 metadata 时，不要只替换 `metadata["validation"]`；必须确保：

```text
metadata.generative_metadata.paths.canonical_ir_path == graph_path
metadata.generative_metadata.paths.validation_seed_path == validation_seed_path
metadata.generative_metadata.paths.step_path == step_path
metadata.generative_metadata.paths.metadata_path == meta_path
metadata.generative_metadata.artifact.step_sha256 == actual step sha256
metadata.generative_metadata.import_policy.step_import_allowed == False
```

final validation：

```python
validate_generative_metadata_v3(
    metadata,
    canonical=canonical,
    registry=default_registry(),
    require_validation_ok=True,
    require_final_artifact_hash=True,
)
```

## 3.4 import gate 改用 v3

`import_artifact.py` 改为：

```python
from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import (
    validate_generative_metadata_v3,
)
```

gate 必须检查：

```text
metadata_version == generative_metadata_v3
source_route == llm_skill_base
trust_level <= reference_geometry
safety all true
native_rebuild_allowed false
requires_import_gate true
step_import_allowed false in metadata proof
validation all required stages ok
step_sha256 matches file
contract_hash matches registry
```

gate 成功返回：

```json
{
  "ok": true,
  "state": "native_import_eligible",
  "gate": {
    "step_import_allowed": true,
    "native_rebuild_allowed": false
  }
}
```

metadata proof 本身仍然保持 `step_import_allowed=false`，因为 metadata 描述的是 artifact policy；gate result 是准入结果。

## 3.5 tests

新增：

```python
def test_builder_writes_metadata_v3(): ...
def test_import_gate_rejects_v2_metadata_in_production(): ...
def test_metadata_v3_requires_runtime_version(): ...
def test_metadata_v3_requires_paths(): ...
def test_metadata_v3_step_hash_mismatch_fails(): ...
def test_metadata_v3_contract_hash_mismatch_fails(): ...
def test_metadata_v3_missing_validation_stage_fails_closed(): ...
def test_metadata_v3_final_require_validation_ok_rejects_false_stage(): ...
```

---

# M4. CanonicalStepArtifact typed model 接入 builder

## 目标

`artifact_models.CanonicalStepArtifact` 必须成为 artifact builder 的唯一输出结构。

## 修改文件

```text
generative_cad/pipeline/artifact.py
generative_cad/pipeline/artifact_models.py
generative_cad/builder.py
tests/generative_cad/test_vnext_artifact_model_behavior.py
```

## 4.1 artifact.py 改造

新增 hash helper：

```python
def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
```

`build_canonical_step_artifact()` 改成构造 model：

```python
from seekflow_engineering_tools.generative_cad.pipeline.artifact_models import CanonicalStepArtifact

artifact = CanonicalStepArtifact(
    artifact_type="canonical_step_artifact",
    artifact_schema_version="canonical_step_artifact_v1",
    source_route="llm_skill_base",
    state="validated_reference_step",
    part_name=canonical.part_name,
    document_id=canonical.document_id,
    step_path=str(step_path),
    metadata_path=str(metadata_path),
    graph_path=str(graph_path or ""),
    validation_seed_path=str(validation_seed_path) if validation_seed_path else None,
    runner_script_path=str(runner_script_path) if runner_script_path else None,
    units="mm",
    trust_level=canonical.trust_level,
    schema_version=canonical.schema_version,
    canonical_version=canonical.canonical_version,
    raw_graph_hash=canonical.raw_graph_hash or "",
    canonical_graph_hash=canonical.canonical_graph_hash,
    selected_dialects=[d.model_dump() for d in canonical.selected_dialects],
    native_rebuild_allowed=False,
    step_import_candidate=True,
    step_import_allowed=False,
    requires_import_gate=True,
    step_sha256=_sha256_file(step_path),
    metadata_sha256=_sha256_file(metadata_path) if metadata_path.exists() else None,
    inspection=inspection or {},
    validation=validation,
)
return artifact.model_dump()
```

## 4.2 builder consistency check

builder 必须检查：

```text
artifact["step_sha256"] == metadata["generative_metadata"]["artifact"]["step_sha256"]
artifact["validation"] == metadata["validation"]
artifact["state"] == "validated_reference_step"
artifact["step_import_allowed"] is False
artifact["native_rebuild_allowed"] is False
artifact["requires_import_gate"] is True
```

## 4.3 tests

```python
def test_artifact_builder_returns_typed_model_fields(): ...
def test_artifact_step_hash_matches_file(): ...
def test_artifact_metadata_hash_matches_file(): ...
def test_builder_rejects_artifact_metadata_step_hash_mismatch(): ...
def test_builder_artifact_state_is_validated_reference_step(): ...
```

---

# M5. Repair prompt path 修复

## 目标

repair prompt 必须使用有效 path notation。

## 修改文件

```text
generative_cad/skills/prompts.py
tests/generative_cad/test_gcad_v10_prompt_paths.py
tests/generative_cad/test_vnext_repair_prompt_paths.py
```

## 5.1 替换 prompt

把所有：

```text
/nodes//dialect
/nodes//op
/nodes//op_version
/components//owner_dialect
/nodes//params/
/nodes//inputs
/nodes//outputs
/components//root_node
```

替换为：

```text
/nodes/<node_id>/dialect
/nodes/<node_id>/op
/nodes/<node_id>/op_version
/components/<component_id>/owner_dialect
/nodes/<node_id>/params/<field>
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/components/<component_id>/root_node
```

## 5.2 最终 repair prompt

```text
You are a local G-CAD IR repair patch author.

You may only repair the provided RawGcadDocument by returning a local RepairPatchV2 JSON.

Hard rules:
1. Output JSON only.
2. Output must match RepairPatchV2 exactly.
3. Do not include markdown, prose, comments, or trailing commas.
4. Do not rewrite the entire graph.
5. Do not modify /schema_version.
6. Do not modify /selected_dialects.
7. Do not modify /safety.
8. Do not modify /constraints/require_step_file.
9. Do not modify /constraints/require_metadata_sidecar.
10. Do not modify /constraints/require_closed_solid.
11. Do not modify /nodes/<node_id>/dialect.
12. Do not modify /nodes/<node_id>/op.
13. Do not modify /nodes/<node_id>/op_version.
14. Do not modify /components/<component_id>/owner_dialect.
15. Do not invent dialects.
16. Do not invent operations.
17. Do not invent operation versions.
18. Do not weaken validation.
19. Prefer changing only /nodes/<node_id>/params/<field>.
20. You may change /nodes/<node_id>/inputs, /nodes/<node_id>/outputs, /nodes/<node_id>/required, /nodes/<node_id>/degradation_policy, or /components/<component_id>/root_node only when the validation error explicitly requires that exact structural repair.
21. Use old_value when available.
22. If old_value no longer matches, the patch must not apply.
23. If the same error signature repeated, output {"give_up": true, "reason": "..."}.
24. If repair would require changing safety, constraints, dialect, op, or op_version, output {"give_up": true, "reason": "..."}.

Allowed path examples:
- /nodes/n_holes/params/pcd_mm
- /nodes/n_slot/params/slot_depth_mm
- /nodes/n_cut/inputs
- /nodes/n_cut/outputs
- /components/main_disk/root_node
```

## 5.3 修复测试

删除矛盾断言。

正确测试：

```python
def test_repair_prompt_uses_valid_placeholder_paths():
    assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2

def test_repair_prompt_has_no_double_slash_paths():
    assert "/nodes//" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/components//" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
```

---

# M6. Prompt ABI 升级

## 6.1 Level-1 Routing Prompt

替换为：

```text
You are the routing front-end of a constrained CAD compiler.

Your only job is to decide which modelling route is safe and expressible.

You must output JSON only, matching DialectSelectionPlan.

Allowed route_decision values:
- deterministic_primitive
- generative_cad_ir
- unsupported

Hard safety rules:
1. If the user requests manufacturing-ready, production-ready, certified, airworthy, installable, structurally validated, fatigue/life prediction, or simulation truth, choose unsupported unless an explicitly deterministic validated primitive route is available.
2. Generative CAD output is reference geometry only.
3. Never select a dialect that is not listed in the Dialect Catalog.
4. Never invent dialects, operations, operation versions, phases, output types, or parameters.
5. Do not output CAD code.
6. Do not output CadQuery, SolidWorks COM, NXOpen, APDL, Python, shell commands, imports, exports, file paths, or subprocesses.
7. If more than one independent component must be combined, include the composition dialect.
8. If no registered dialect can express the request, choose unsupported.
9. If the request is better covered by an existing deterministic primitive and the user needs high determinism, choose deterministic_primitive.
10. Do not use deprecated terms: selected_bases, base_id, feature_graph, GenerativeCADSpec.
11. Output JSON only. No markdown. No comments. No prose. No trailing commas.
```

## 6.2 Level-2 Authoring Prompt

重点补强显式 safety / constraints：

```text
You are the source author for a constrained G-CAD compiler.

You must output RawGcadDocument JSON only.

Hard output rules:
1. Output JSON only.
2. The JSON must match RawGcadDocument exactly.
3. Do not include markdown, comments, prose, explanations, or trailing commas.
4. Do not include file paths.
5. Do not include Python, CadQuery, SolidWorks COM, NXOpen, APDL, shell commands, imports, exports, or subprocesses.
6. Use schema_version exactly "g_cad_core_v0.2".
7. Use units exactly "mm".
8. trust_level must be "reference_geometry" or "concept_geometry"; never higher.
9. Every required top-level field must be explicitly present.
10. Do not rely on schema defaults.
11. The constraints object must be explicitly present.
12. constraints.require_step_file must be explicitly true.
13. constraints.require_metadata_sidecar must be explicitly true.
14. constraints.require_closed_solid must be explicitly true.
15. constraints.expected_body_count must be explicitly present and >= 1.
16. The safety object must be explicitly present.
17. Every safety flag must be explicitly present and true:
    - non_flight_reference_only
    - not_airworthy
    - not_certified
    - not_for_manufacturing
    - not_for_installation
    - no_structural_validation
    - no_life_prediction
18. Use only selected_dialects provided by Level-1.
19. Use only operations listed in the selected dialect contracts.
20. Every node must specify id, component, dialect, op, op_version, phase, inputs, outputs, params, required, and degradation_policy.
21. Every node phase must match its OperationSpec phase.
22. Every node input type must match OperationSpec input_types.
23. Every node output type must match OperationSpec output_types.
24. Every component must specify id, owner_dialect, and root_node.
25. A non-assembly component may only contain nodes from its owner_dialect.
26. Cross-component composition may happen only inside "__assembly__" with owner_dialect "composition".
27. If more than one non-assembly component exists, include "__assembly__".
28. The final root node must output "body" of type "solid".
29. required=true nodes must use degradation_policy="fail".
30. Do not invent dialects, operations, operation versions, phases, output types, or parameters.
31. Do not use deprecated fields: selected_bases, base_id, feature_graph, system_validation_contract, ir_version, GenerativeCADSpec.
32. If the request cannot be expressed with the selected contracts, return to Level-1 routing as unsupported instead of inventing fields.
33. Do not claim manufacturing readiness, certification, airworthiness, installation readiness, structural validation, life prediction, or production readiness.
```

---

# M7. Legacy namespace 最终隔离

## 目标

所有 legacy top-level modules 默认禁用。

当前 `prompts.py` 已加 barrier，但 `repair_governor.py` 仍直接 re-export legacy。([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/prompts.py)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/repair_governor.py))

## 修改

给 `repair_governor.py` 加：

```python
import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.repair_governor is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.repair.governor or "
        "seekflow_engineering_tools.generative_cad.repair.patch."
    )
```

## 测试

```python
def test_legacy_repair_governor_disabled_by_default(): ...
def test_legacy_prompts_disabled_by_default(): ...
def test_legacy_import_allowed_with_env_flag(monkeypatch): ...
```

---

# M8. 测试体系升级为行为测试

当前部分测试是源码字符串检查，不能证明系统行为正确。必须新增行为测试。

## 必须新增

```text
tests/generative_cad/test_vnext_raw_parse_behavior.py
tests/generative_cad/test_vnext_operation_result_behavior.py
tests/generative_cad/test_vnext_registry_freeze_behavior.py
tests/generative_cad/test_vnext_metadata_v3_behavior.py
tests/generative_cad/test_vnext_artifact_model_behavior.py
tests/generative_cad/test_vnext_import_gate_behavior.py
tests/generative_cad/test_vnext_repair_prompt_paths.py
tests/generative_cad/test_vnext_legacy_barriers.py
```

## 行为测试要求

```python
def test_missing_safety_fails_before_model_validate(): ...
def test_missing_constraints_fails_before_model_validate(): ...
def test_run_canonical_requires_validation_seed(): ...
def test_operation_result_output_name_mismatch_fails(): ...
def test_operation_result_handle_type_mismatch_fails(): ...
def test_registry_injected_unknown_dialect_fails(): ...
def test_metadata_v3_step_hash_mismatch_fails(): ...
def test_import_gate_rejects_metadata_without_runtime_postconditions(): ...
def test_builder_artifact_not_import_allowed(): ...
def test_import_gate_promotes_to_native_import_eligible(): ...
def test_repair_patch_cannot_modify_safety(): ...
def test_repair_patch_accepts_node_param_path(): ...
```

---

# 4. Claude Code 总 Prompt

下面可以直接交给 Claude Code：

```text
You are implementing a compiler-grade vNext hardening pass for SeekFlow generative_cad.

Primary goal:
Turn generative_cad into a robust, ABI-stable compiler pipeline:
RawGcadDocument
  -> ValidationBundle
  -> CanonicalGcadDocument
  -> Frozen DialectRegistry
  -> BaseDialect.run_component
  -> execute_operation
  -> OperationResult
  -> RuntimeObjectStore typed handles
  -> GeometryRuntime
  -> STEP
  -> MetadataProofV3
  -> CanonicalStepArtifact
  -> ImportGate.

Non-negotiable constraints:
1. Do not modify deterministic primitive path semantics.
2. Do not modify cadquery_backend/primitive_compiler.py.
3. Do not modify geometry_primitives/.
4. Do not add generative fields to CADPartSpec.
5. Do not add generative dialects to primitive registries.
6. LLM Raw JSON must never enter BaseDialect directly.
7. Every dict input must pass parse_raw_gcad_document.
8. Core IR envelope is fixed.
9. Op-specific fields are allowed only inside node.params.
10. node.params must be validated only by OperationSpec.params_model.
11. Unknown dialect/op/op_version/type/phase/input/output must fail closed.
12. No fuzzy matching.
13. No silent fallback.
14. No dynamic CAD code generation.
15. No generated CadQuery scripts except the fixed runner harness.
16. No SolidWorks COM / NXOpen / APDL code generation.
17. Output remains canonical STEP + metadata proof.
18. Native rebuild is always forbidden.
19. Generative trust_level must never exceed reference_geometry.
20. Multiple dialects compose only through composition dialect.
21. Dialect handlers must not call other dialects directly.
22. Cross-dialect values must be typed runtime handles.
23. Do not hide failing tests by skipping them.
24. Update fixtures to satisfy stricter contracts; do not weaken validation.

Implement in this exact order:

M1 OperationResult ABI:
- Add RuntimeObjectStore.get_typed.
- Make all dialect.run_component paths call execute_operation.
- Validate returned output names, value types, handle existence, and handle type.
- Keep v1_dict only as transitional adapter.
- Add behavior tests.

M2 Frozen DialectRegistry:
- Make dialects/registry.py delegate to default_registry().
- Remove import-time global mutable registry and populate_registry side effects.
- Add registry injection where practical.
- Add behavior tests.

M3 MetadataProofV3:
- Make run.py build MetadataProofV3.
- Make builder.py final validation use validate_generative_metadata_v3.
- Make import_artifact.py validate v3.
- Keep v2.1 only for compatibility tests.
- Add step hash and runtime version checks.

M4 CanonicalStepArtifact:
- Make artifact.py construct CanonicalStepArtifact model.
- Compute step_sha256 and metadata_sha256.
- Builder must verify artifact and metadata hashes agree.

M5 Repair prompt:
- Replace all /nodes//... and /components//... paths with /nodes/<node_id>/... and /components/<component_id>/...
- Fix contradictory tests.
- Add behavior tests for RepairPatchV2.

M6 Prompt ABI:
- Upgrade Level-1 and Level-2 prompts.
- Level-2 must require explicit constraints and safety objects and every safety flag.

M7 Legacy barriers:
- Add deprecation barrier to repair_governor.py.
- Ensure production code cannot import legacy modules by default.

M8 Behavior tests:
- Convert release-blocker source-string checks into behavior tests.
- Do not weaken validation to pass tests.

Acceptance:
- pytest tests/generative_cad -q
- pytest tests -q
- No production import from legacy namespaces.
- Existing deterministic primitive tests still pass.
```

---

# 5. 分阶段 Claude Code Prompts

## Prompt M1：OperationResult

```text
Implement M1 OperationResult ABI wiring.

Files:
- src/seekflow_engineering_tools/generative_cad/runtime/object_store.py
- src/seekflow_engineering_tools/generative_cad/dialects/operation.py
- src/seekflow_engineering_tools/generative_cad/dialects/executor.py
- src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py
- src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/dialect.py
- src/seekflow_engineering_tools/generative_cad/dialects/composition/dialect.py
- tests/generative_cad/test_vnext_operation_result_behavior.py

Requirements:
1. Add RuntimeObjectStore.get_typed(handle_id).
2. get_typed must return handle_id, value_type, handle, obj.
3. execute_operation must be the only path for handler execution in dialect.run_component.
4. Runtime output names must exactly match CanonicalNode.outputs.
5. Runtime output value_type must match CanonicalNode.outputs.
6. Returned handle must exist.
7. Stored handle value_type must match declared output type.
8. v1_dict legacy adapter may remain only for existing ops.
9. New ops must use handler_kind="v2_result".
10. Do not modify Core IR.

Run:
pytest tests/generative_cad/test_vnext_operation_result_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M2：Frozen Registry

```text
Implement M2 Frozen DialectRegistry production wiring.

Files:
- generative_cad/dialects/registry.py
- generative_cad/dialects/default_registry.py
- generative_cad/dialects/registry_core.py
- validation modules using require_dialect/get_dialect/dialect_contract_hash
- tests/generative_cad/test_vnext_registry_freeze_behavior.py

Requirements:
1. registry.py must delegate to default_registry().
2. Remove module-level mutable DIALECT_REGISTRY from production path.
3. Remove import-time populate_registry side effect.
4. default_registry must be frozen.
5. Duplicate dialects fail.
6. Part-named dialect IDs fail.
7. Validation can use injected registry.
8. Contract hash remains stable.

Run:
pytest tests/generative_cad/test_vnext_registry_freeze_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M3：Metadata v3

```text
Implement M3 MetadataProofV3 production integration.

Files:
- generative_cad/pipeline/run.py
- generative_cad/builder.py
- generative_cad/pipeline/import_artifact.py
- generative_cad/pipeline/metadata_v3.py
- generative_cad/tools.py
- tests/generative_cad/test_vnext_metadata_v3_behavior.py

Requirements:
1. run.py must call build_generative_metadata_v3.
2. run_canonical_gcad must accept canonical_ir_path and validation_seed_path.
3. builder.py must final-validate metadata with validate_generative_metadata_v3.
4. import_artifact.py must use validate_generative_metadata_v3.
5. v2.1 is compatibility only.
6. Metadata v3 must include paths, runtime version, artifact.step_sha256, import_policy, safety, validation.
7. step_sha256 must match STEP file.
8. Missing validation stage fails closed.
9. require_validation_ok=True rejects any false stage.

Run:
pytest tests/generative_cad/test_vnext_metadata_v3_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M4：Artifact model

```text
Implement M4 CanonicalStepArtifact typed model wiring.

Files:
- generative_cad/pipeline/artifact.py
- generative_cad/pipeline/artifact_models.py
- generative_cad/builder.py
- tests/generative_cad/test_vnext_artifact_model_behavior.py

Requirements:
1. build_canonical_step_artifact must construct CanonicalStepArtifact.
2. Compute step_sha256 from STEP file.
3. Compute metadata_sha256 when metadata exists.
4. state must be validated_reference_step.
5. step_import_allowed must be false.
6. requires_import_gate must be true.
7. native_rebuild_allowed must be false.
8. Builder must reject artifact/metadata hash mismatch.

Run:
pytest tests/generative_cad/test_vnext_artifact_model_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M5：Repair prompt

```text
Implement M5 repair prompt path hardening.

Files:
- generative_cad/skills/prompts.py
- tests/generative_cad/test_gcad_v10_prompt_paths.py
- tests/generative_cad/test_vnext_repair_prompt_paths.py

Requirements:
1. Remove all /nodes//... and /components//... paths.
2. Use /nodes/<node_id>/params/<field>.
3. Use /components/<component_id>/root_node.
4. Prompt must forbid /safety.
5. Prompt must forbid /constraints/require_*.
6. Prompt must forbid dialect/op/op_version changes.
7. Fix contradictory tests.
8. Add behavior tests.

Run:
pytest tests/generative_cad/test_gcad_v10_prompt_paths.py -q
pytest tests/generative_cad/test_vnext_repair_prompt_paths.py -q
pytest tests/generative_cad -q
```

---

# 6. 最终验收矩阵

完成后必须满足：

```text
Raw / Core:
  missing safety fails
  missing constraints fails
  safety false fails
  unknown dialect fails
  unknown op fails
  unknown op_version fails
  graph cycle fails
  phase order fails
  type mismatch fails
  params schema fail
  cross-component non-composition fail

Operation runtime:
  every dialect uses execute_operation
  missing output fails
  extra output fails
  output type mismatch fails
  missing handle fails
  handle type mismatch fails
  warnings/degraded/metrics propagate

Registry:
  default registry frozen
  no import-time mutable populate
  duplicate dialect fail
  part-named dialect fail
  injected registry works

Runner:
  canonical runner requires validation_seed
  validation_seed not mutated
  fixed harness passes validation_seed_json
  GeometryRuntime export used

Metadata:
  production metadata_version == generative_metadata_v3
  paths required
  runtime version required
  step hash required
  step hash mismatch fails
  contract hash mismatch fails
  validation missing stage fails closed
  require_validation_ok rejects false stage

Artifact:
  typed CanonicalStepArtifact used
  builder state == validated_reference_step
  step_import_allowed false
  native_rebuild_allowed false
  requires_import_gate true

Import gate:
  validates v3 metadata
  rejects missing runtime_postconditions
  rejects step hash mismatch
  returns native_import_eligible only after all checks

Repair:
  prompt uses <node_id> placeholders
  no /nodes// paths
  patch cannot modify safety
  patch cannot modify require_* constraints
  patch cannot modify dialect/op/op_version
  params patch allowed

Legacy:
  repair_governor legacy import disabled by default
  prompts legacy import disabled by default
  production code has no legacy imports

Primitive:
  primitive compiler unchanged
  geometry_primitives unchanged
  CADPartSpec unchanged
```

---

# 7. 最终判断

这条路线真正正确的核心不是“多写几个 schema”，而是建立一个**LLM constrained source → compiler validation → contract-linked canonical IR → typed runtime execution → metadata proof → import gate** 的完整链路。

当前代码已经修好底层安全地基，但仍处于“组件有了，生产路径未完全贯通”的阶段。下一步不要再新增壳模块，也不要继续写 inspect.getsource 字符串测试；应该把五个半接入点彻底接通：

```text
1. OperationResult → dialect execution
2. Frozen Registry → validation / metadata / runner
3. MetadataProofV3 → run / builder / import gate
4. CanonicalStepArtifact model → artifact builder
5. valid repair paths → prompt + behavior tests
```

补齐后，你的系统会从“正确方向的工程原型”进入“真正有编译器内核气质的 Generative CAD pipeline”。这也是这条方向真正有壁垒和长期价值的地方。
