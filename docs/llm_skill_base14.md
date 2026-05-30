# SeekFlow Generative CAD-IR vNext 工程实施文档

**面向 Claude Code 的编译器级架构修复规范**

本文档基于你给出的两份架构记忆文档与我对当前 GitHub `main` 代码的再次静态审阅。未本地执行测试，因此下面对代码状态的判断是**源码级审计结论**，不是运行结果声明。

当前代码已经比上一次明显前进：`RawGcadDocument` 的 `safety` / `constraints` 已经改成显式必填，`parse_raw_gcad_document()` 已经存在并检查缺失字段，validation pipeline 已经接入 parse 层；canonical runner 现在要求 `validation_seed_json`，builder 会写 validation seed 并把它传给固定 harness；artifact builder 也已经改成 `validated_reference_step` / `step_import_allowed=False` 的状态机；`GeometryRuntime` / `CadQueryRuntime` 已经初步落地。([GitHub][1])

但现在还没有达到“顶级、健康、强壮、兼容性强、低频修改核心编译器”的状态。当前最大剩余问题是：**OperationResult ABI 只定义了，但没有真正接入 BaseDialect / OperationSpec / dialect execution；registry 仍然是 import-time global mutable registry；repair prompt 仍使用 `/nodes//params/` 这种无效占位；metadata proof 仍缺少路径、artifact hash、runtime version、import gate policy 等强证明字段；legacy production namespace 还需要彻底隔离。** ([GitHub][2])

---

## 1. 总目标

你的系统目标不是“让 LLM 写 CAD 代码”，也不是“每个零件一个 base”，更不是“把 Primitive 改成 LLM 生成”。目标是构建一条独立的受控 Generative CAD-IR 链路：LLM 输出固定结构的 G-CAD Core IR，系统做 Core Validator / BaseDialect / OperationSpec / GeometryRuntime / STEP / metadata proof，最终只通过 canonical STEP + metadata 合流到现有主链路后半段。

因此 vNext 架构必须满足：

```text
LLM Raw Output
  ↓
parse_raw_gcad_document
  ↓
RawGcadDocument
  ↓
Core validation pipeline
  ↓
CanonicalGcadDocument
  ↓
LinkedExecutablePlan
  ↓
Dialect execution via OperationSpec + OperationResult
  ↓
RuntimeObjectStore + GeometryRuntime
  ↓
STEP export
  ↓
runtime_postconditions
  ↓
STEP inspection
  ↓
MetadataProof v3
  ↓
CanonicalStepArtifact
  ↓
Import Gate
  ↓
native_import_eligible, STEP import only
```

现有 deterministic Primitive 主链路不得修改，不得污染 `cadquery_backend/primitive_compiler.py`、`geometry_primitives/`、`PRIMITIVE_COMPILERS`、`CADPartSpec` 核心语义；Primitive 仍是 deterministic kernel 路径。 当前 primitive compiler 文件也仍明确声明 Primitive route 使用 deterministic geometry kernels、never to LLM-generated code，这一点必须保持。([GitHub][3])

---

# 2. 当前代码状态复核

## 2.1 已经做对的部分

### 2.1.1 Raw IR 显式安全字段已经基本修对

当前 `RawConstraints` 的核心字段 `require_step_file`、`require_metadata_sidecar`、`require_closed_solid`、`expected_body_count` 已经没有默认补齐，并且 fail-closed validator 要求前三个 flag 显式为 true；`RawSafety` 的七个安全字段也已经没有默认值，并且要求全部为 true；`RawGcadDocument` 的 `schema_version`、`units`、`trust_level`、`constraints`、`safety` 也都改为显式字段。([GitHub][1])

### 2.1.2 parse 层已经存在并接入 validation pipeline

`ir/parse.py` 已经定义 required top-level keys、required safety keys、required constraint keys，并输出 path-aware `RawParseIssue`；validation pipeline 在 dict 输入时已经调用 `parse_raw_gcad_document()`，parse 失败会生成 structure failure，而不是直接 `RawGcadDocument.model_validate()`。([GitHub][4])

### 2.1.3 canonical runner proof bypass 已经基本修掉

`run_canonical_gcad_from_files()` 现在要求 `validation_seed_json`，并把 validation seed 传入 `run_canonical_gcad()`；`run_canonical_gcad()` 现在要求 non-empty validation seed，默认 `require_full_validation_seed=True`，并且会 deep-copy validation seed 后再添加 runtime postconditions。([GitHub][5])

### 2.1.4 builder harness 已经传 validation seed

builder 当前会写 `gcad_<id>.validation.json`，并生成固定 harness 调 `run_canonical_gcad_from_files(canonical_json, validation_seed_json, out_step, metadata_path)`，这个方向正确。([GitHub][6])

### 2.1.5 artifact state machine 已经开始正确化

`build_canonical_step_artifact()` 现在返回 `state="validated_reference_step"`、`step_import_candidate=True`、`step_import_allowed=False`、`requires_import_gate=True`、`native_rebuild_allowed=False`，这比之前“builder 直接允许 import”正确得多。([GitHub][7])

### 2.1.6 GeometryRuntime 已经初步落地

当前已经有 `GeometryRuntime` Protocol，`CadQueryRuntime` 实现了 `export_step`、`inspect_solid`、`validate_closed_solid`、`compute_bbox_mm`、`count_bodies`；`RuntimeContext` 也持有 `geometry_runtime` 对象，并通过 `geometry_runtime_name` 暴露 runtime id。([GitHub][8])

---

## 2.2 当前仍不合格的核心问题

### P0 / P1：OperationResult ABI 没有真正接入

当前 `dialects/results.py` 已经定义 `OperationResult`、`OperationOutput`、`OperationMetric` 和 legacy adapter，但 `OperationSpec.handler` 仍然是 `Callable[..., dict[str, str]]`，默认 `handler_kind="v1_dict"`；`BaseDialect.run_component()` 协议仍返回 `dict[str, str]`。([GitHub][2])

更关键的是，axisymmetric dialect 的 `run_component()` 仍然直接：

```python
outputs = op_spec.handler(node, ctx)
for name, hid in outputs.items():
    ctx.bind_node_output(node.id, name, hid)
```

没有统一把 handler result 规范化为 `OperationResult`，也没有校验 runtime output name / type / handle 是否与 `OperationSpec.output_types` 和 CanonicalNode outputs 一致。([GitHub][9])

这会导致一个 compiler ABI 漏洞：前端 typecheck 证明的是“LLM 声明的 outputs 合法”，但 runtime handler 实际返回的 outputs 仍可能漂移。最终 RuntimeObjectStore 中绑定了什么，仍过度依赖 handler 约定，而不是统一 runtime verifier。

### P1：registry 仍是 import-time global mutable registry

`dialects/registry.py` 当前仍然是 module-level `DIALECT_REGISTRY`，在 import 时执行 `populate_registry()`，没有显式 `DialectRegistry` 对象、没有 `freeze()`、没有测试隔离、没有 registry context 注入。虽然它有 duplicate dialect 检查和禁止 part-name token，这些是正确方向，但它仍不是健康的 compiler registry。([GitHub][10])

长期风险：

```text
测试间状态污染；
插件式 dialect 难以并存；
contract hash 依赖全局状态；
未来多 registry / 多版本 dialect 运行困难；
import side-effect 会让工具和 CI 行为脆弱。
```

### P1：repair prompt 仍有无效 path 占位

当前 `REPAIR_PATCH_SYSTEM_PROMPT_V2` 仍写着：

```text
/nodes//dialect
/nodes//op
/nodes//op_version
/components//owner_dialect
/nodes//params/
```

这些不是有效 JSON pointer，也不是你记忆文档要求的 `/nodes/<node_id>/params/<field>` 形式。([GitHub][11]) 你的 release-blocker 明确要求 repair prompt path 必须使用有效占位，并且 repair 只能局部 patch、不能改 safety、不能弱化 validation。

### P1：metadata proof 仍不够强

metadata v2.1 已经有 fail-closed validation normalization：缺失 required stage 会生成 `ok=False` 的 `_missing_stage`；required stages 包括 `core_validation`、`dialect_semantics`、`geometry_preflight`、`runtime_postconditions`、`inspection_validation`。([GitHub][12])

但是 `build_generative_metadata()` 当前只记录 `metadata_version`、`schema_version`、`canonical_version`、`trust_level`、`selected_dialects`、`op_versions`、`raw_graph_hash`、`canonical_graph_hash`、`runner_version`、`geometry_runtime`、metrics、degraded_features、repair_attempts、warnings、safety；它没有记录 `source_ir_path` / `canonical_ir_path` / `step_path` / `metadata_path` / `artifact_hash` / `geometry_runtime_version` / `native_rebuild_allowed=False` / `requires_import_gate=True` / artifact state。([GitHub][12])

你的记忆文档明确要求 metadata 至少包含 metadata_version、source_route、trust_level、schema_version、selected dialects、dialect versions、op versions、graph hash、contract hash、runner_version、geometry_runtime、repair_attempts、validation stages、warnings、degraded_features、safety flags、source_ir_path、step_path，且 metadata 缺失、safety 缺失、contract hash 不匹配必须 fail。

### P2：Level-2 prompt 仍不够硬

Level-2 authoring prompt 已经禁止 CAD code、路径、自然语言、过高 trust_level，并要求 constraints/safety true，但它没有明确说：

```text
constraints object 必须显式存在；
safety object 必须显式存在；
每一个 safety flag 必须逐项显式输出；
expected_body_count 必须显式输出；
禁止依赖 schema defaults；
缺字段不能靠系统补齐。
```

虽然当前 Raw schema 已经显式必填，但 prompt 也必须和 schema 对齐，降低 repair loop 与 authoring loop 的噪声。([GitHub][11])

### P2：legacy namespace 仍需要最终隔离

当前测试目录已经有多轮 legacy isolation 测试，但生产源码目录仍存在 `base.py`、`ir.py`、`registry.py`、`runner.py`、`validation.py`、`legacy/`、`bases/` 等旧路径，这些会继续诱导 Claude Code 或 LLM tool import 错路径。测试目录可见多轮 legacy isolation 和 v05-v10 测试，说明团队已经意识到问题，但 vNext 应该把它做成硬边界。([GitHub][13])

---

# 3. vNext 顶级目标架构

## 3.1 编译器分层

vNext 不应再是“pipeline 脚本 + 若干 validator”。它应明确成为一个小型编译器：

```text
Layer 0: Skill / Prompt Front-End
Layer 1: Raw Source Parse
Layer 2: Core Validation
Layer 3: Canonicalization
Layer 4: Contract Linking
Layer 5: Executable Plan
Layer 6: Dialect Runtime Execution
Layer 7: GeometryRuntime Backend
Layer 8: STEP + Metadata Proof
Layer 9: Artifact State Machine
Layer 10: Native Import Gate
```

每一层只消费上一层的输出，不允许跨层旁路。

---

## 3.2 核心数据对象

vNext 需要这些稳定 ABI：

```text
RawGcadDocument
  LLM 唯一允许输出的源码 ABI。

ValidationBundle
  Core validation proof，不是日志。

CanonicalGcadDocument
  已类型化、已 contract linked 的 IR。

LinkedExecutablePlan
  把 canonical nodes 与 OperationSpec、typed inputs、expected outputs 固定绑定。

OperationResult
  每个 handler 唯一允许返回的 runtime ABI。

RuntimeHandle / RuntimeObjectStore
  跨 dialect 的 typed runtime value 系统。

GeometryRuntime
  后端几何 API 抽象，CadQuery 只是一个 backend。

MetadataProofV3
  编译证明，不是附带说明。

CanonicalStepArtifact
  artifact 状态机对象。

ImportGateResult
  native import eligibility 的唯一权威。
```

---

# 4. vNext 实施总原则

这些原则必须写进 Claude Code prompt，并作为 CI 测试：

```text
Do not modify deterministic primitive path semantics.
Do not modify cadquery_backend/primitive_compiler.py.
Do not modify geometry_primitives/.
Do not add generative capabilities to primitive registries.
Do not add generative fields to CADPartSpec.
LLM raw JSON must never enter BaseDialect directly.
All dict input must pass parse_raw_gcad_document.
Core IR envelope is fixed.
Op-specific fields are allowed only in node.params.
node.params must be validated only by OperationSpec.params_model.
Unknown dialect/op/op_version/type/phase must fail closed.
No fuzzy matching.
No silent fallback.
No generated CadQuery scripts except fixed harness.
No SolidWorks COM / NXOpen / APDL generation.
Native rebuild is always forbidden for generative artifacts.
Generative trust_level must never exceed reference_geometry.
Multiple dialects compose only via composition dialect.
Dialect handlers must not call other dialects directly.
Cross-dialect values must be typed runtime handles.
```

这些约束与记忆文档完全一致：所有 LLM 输出必须通过 Core IR 验证，node.params 由 OperationSpec.params_model 校验，多 Base 只能通过 Composition Dialect，未知 dialect/op fail-closed，不允许 silent fallback，runner 使用固定 harness，输出是 canonical STEP artifact + metadata，trust level 不超过 reference_geometry。

---

# 5. Milestone M1：完成 OperationResult ABI 接线

这是当前最重要的剩余工程任务。

## 5.1 目标

把当前：

```text
handler -> dict[str, str]
```

升级为：

```text
handler -> OperationResult
```

并且由统一 executor 校验：

```text
output name declared
output type matches
handle exists
handle type matches
warnings/degraded/metrics/postconditions propagated
```

---

## 5.2 修改文件

```text
src/seekflow_engineering_tools/generative_cad/dialects/results.py
src/seekflow_engineering_tools/generative_cad/dialects/operation.py
src/seekflow_engineering_tools/generative_cad/dialects/executor.py      # 新增
src/seekflow_engineering_tools/generative_cad/dialects/base.py
src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py
src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/dialect.py
src/seekflow_engineering_tools/generative_cad/dialects/composition/dialect.py
src/seekflow_engineering_tools/generative_cad/runtime/object_store.py
tests/generative_cad/test_operation_result_abi.py
```

---

## 5.3 新增 `dialects/executor.py`

```python
from __future__ import annotations

from dataclasses import dataclass

from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.dialects.results import (
    OperationResult,
    adapt_legacy_handler_result,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


@dataclass(frozen=True)
class ExecutedNode:
    node_id: str
    outputs: dict[str, str]


def execute_operation(
    *,
    node: CanonicalNode,
    op_spec: OperationSpec,
    ctx: RuntimeContext,
) -> ExecutedNode:
    raw_result = op_spec.handler(node, ctx)

    if isinstance(raw_result, OperationResult):
        result = raw_result
    elif isinstance(raw_result, dict) and op_spec.handler_kind == "v1_dict":
        result = adapt_legacy_handler_result(raw_result, node)
    else:
        raise RuntimeError(
            f"Handler for {node.dialect}.{node.op}@{node.op_version} returned "
            f"unsupported result type {type(raw_result).__name__}"
        )

    validate_operation_result(node=node, op_spec=op_spec, result=result, ctx=ctx)

    for w in result.warnings:
        ctx.warnings.append(w)

    for d in result.degraded_features:
        ctx.degraded_features.append(d)

    for metric in result.metrics:
        ctx.operation_metrics.append(metric.model_dump())

    outputs: dict[str, str] = {}
    for output in result.outputs:
        ctx.bind_node_output(node.id, output.name, output.handle_id)
        outputs[output.name] = output.handle_id

    return ExecutedNode(node_id=node.id, outputs=outputs)


def validate_operation_result(
    *,
    node: CanonicalNode,
    op_spec: OperationSpec,
    result: OperationResult,
    ctx: RuntimeContext,
) -> None:
    if result.ok is not True:
        raise RuntimeError(f"Operation {node.id} returned ok=False")

    declared_by_name = {o.name: o.type for o in node.outputs}
    result_by_name = {o.name: o for o in result.outputs}

    missing = sorted(set(declared_by_name) - set(result_by_name))
    extra = sorted(set(result_by_name) - set(declared_by_name))

    if missing:
        raise RuntimeError(f"Operation {node.id} missing output(s): {missing}")
    if extra:
        raise RuntimeError(f"Operation {node.id} returned undeclared output(s): {extra}")

    expected_output_types = list(op_spec.output_types)
    actual_declared_types = [o.type for o in node.outputs]
    if actual_declared_types != expected_output_types:
        raise RuntimeError(
            f"Operation {node.id} canonical outputs {actual_declared_types} "
            f"do not match spec outputs {expected_output_types}"
        )

    for output_decl in node.outputs:
        result_output = result_by_name[output_decl.name]
        if result_output.value_type != output_decl.type:
            raise RuntimeError(
                f"Operation {node.id}.{output_decl.name} returned type "
                f"{result_output.value_type!r}, expected {output_decl.type!r}"
            )

        stored = ctx.object_store.get_typed(result_output.handle_id)
        if stored.value_type != output_decl.type:
            raise RuntimeError(
                f"Handle {result_output.handle_id!r} has type {stored.value_type!r}, "
                f"expected {output_decl.type!r}"
            )
```

---

## 5.4 `RuntimeObjectStore` 必须提供 typed getter

如果当前 object store 没有这个接口，新增：

```python
@dataclass(frozen=True)
class StoredRuntimeObject:
    handle_id: str
    value_type: str
    obj: object


class RuntimeObjectStore:
    ...

    def get_typed(self, handle_id: str) -> StoredRuntimeObject:
        ...
```

如果已有 typed handle 模型，则使用已有模型，但必须保证：

```text
handle_id 不存在 -> fail
handle value_type mismatch -> fail
```

---

## 5.5 `OperationSpec` 修改

当前 `OperationHandler = Callable[..., dict[str, str]]` 应改成：

```python
from typing import Callable, Literal

from seekflow_engineering_tools.generative_cad.dialects.results import OperationResult
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext

OperationHandler = Callable[[CanonicalNode, RuntimeContext], OperationResult | dict[str, str]]
```

临时兼容：

```python
handler_kind: Literal["v1_dict", "v2_result"] = "v1_dict"
```

但新增硬约束：

```python
@model_validator(mode="after")
def validate_handler_kind(self):
    if self.handler_kind == "v2_result":
        return self
    # v1_dict only allowed for legacy-migrating built-ins
    return self
```

新增 dialect op 时必须用：

```python
handler_kind="v2_result"
```

---

## 5.6 Dialect `run_component()` 修改

所有 dialect 的 `run_component()` 中，替换：

```python
outputs = op_spec.handler(node, ctx)
for name, hid in outputs.items():
    ctx.bind_node_output(node.id, name, hid)
```

为：

```python
from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
for name, hid in executed.outputs.items():
    final_outputs[name] = hid
```

optional degradation 仍然由外层 try/except 处理，但必须遵守：

```text
required=True -> handler failure = fail
required=False + may_skip_with_warning -> record degraded feature, continue
required=False + degradation_policy != may_skip_with_warning -> fail
```

---

## 5.7 测试

新增：

```text
tests/generative_cad/test_operation_result_abi.py
```

测试必须是行为测试，不允许只 `inspect.getsource()`。

覆盖：

```python
def test_operation_result_output_names_must_match_node_outputs():
    ...

def test_operation_result_output_type_mismatch_fails():
    ...

def test_operation_result_handle_type_mismatch_fails():
    ...

def test_operation_result_missing_handle_fails():
    ...

def test_v1_dict_adapter_allowed_for_existing_builtin_ops():
    ...

def test_v2_result_metrics_warnings_degraded_features_propagate():
    ...
```

验收：

```bash
pytest tests/generative_cad/test_operation_result_abi.py -q
pytest tests/generative_cad -q
```

---

# 6. Milestone M2：引入 Frozen DialectRegistry

## 6.1 目标

把 import-time global registry 改成显式、可冻结、可注入、可测试隔离的 registry。

当前 `DIALECT_REGISTRY` 在 import 时 populate，这对原型可以，但对 compiler-grade 系统不健康。([GitHub][10])

---

## 6.2 新增 `dialects/registry_core.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.base import BaseDialect
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash


FORBIDDEN_PART_TOKENS = {
    "turbine_disk",
    "flange",
    "bracket",
    "gearbox",
    "bearing",
}


@dataclass
class DialectRegistry:
    _dialects: dict[str, BaseDialect] = field(default_factory=dict)
    _frozen: bool = False

    def register(self, dialect: BaseDialect) -> None:
        if self._frozen:
            raise RuntimeError("DialectRegistry is frozen")
        did = dialect.dialect_id
        if not did:
            raise ValueError("dialect_id must be non-empty")
        if did in self._dialects:
            raise ValueError(f"duplicate dialect_id: {did}")
        for token in FORBIDDEN_PART_TOKENS:
            if token in did:
                raise ValueError(
                    f"dialect_id {did!r} appears to name a part, not a CAD grammar dialect"
                )
        self._dialects[did] = dialect

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, dialect_id: str) -> BaseDialect:
        try:
            return self._dialects[dialect_id]
        except KeyError as exc:
            raise KeyError(f"unknown dialect: {dialect_id!r}") from exc

    def get(self, dialect_id: str) -> BaseDialect | None:
        return self._dialects.get(dialect_id)

    def list_ids(self) -> list[str]:
        return sorted(self._dialects)

    def export_catalog(self) -> dict[str, Any]:
        return {
            "catalog_version": "0.3.0",
            "dialects": [
                self._dialects[k].manifest()
                for k in sorted(self._dialects)
            ],
        }

    def contract_hash(self, dialect_id: str) -> str:
        return contract_hash(self.require(dialect_id).contract())
```

---

## 6.3 新增 `dialects/default_registry.py`

```python
from __future__ import annotations

from functools import lru_cache

from seekflow_engineering_tools.generative_cad.dialects.registry_core import DialectRegistry


def build_default_registry() -> DialectRegistry:
    from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.dialect import SKETCH_EXTRUDE_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT

    registry = DialectRegistry()
    registry.register(AXISYMMETRIC_DIALECT)
    registry.register(SKETCH_EXTRUDE_DIALECT)
    registry.register(COMPOSITION_DIALECT)
    registry.freeze()
    return registry


@lru_cache(maxsize=1)
def default_registry() -> DialectRegistry:
    return build_default_registry()
```

---

## 6.4 保留 compatibility wrapper

当前 `dialects/registry.py` 可以保留 API，但内部委托 frozen default registry：

```python
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

def require_dialect(dialect_id: str):
    return default_registry().require(dialect_id)

def get_dialect(dialect_id: str):
    return default_registry().get(dialect_id)

def list_dialects():
    return default_registry().list_ids()

def export_dialect_catalog():
    return default_registry().export_catalog()

def dialect_contract_hash(dialect_id: str):
    return default_registry().contract_hash(dialect_id)
```

禁止再有 import-time `populate_registry()` side effect。

---

## 6.5 Validation / metadata / builder 支持 registry 注入

长期应让：

```python
validate_and_canonicalize_with_bundle(raw, registry=default_registry())
build_generative_metadata(..., registry=default_registry())
validate_generative_metadata_v3(..., registry=default_registry())
```

短期 compatibility wrapper 可以默认用 `default_registry()`。

---

## 6.6 测试

新增：

```text
tests/generative_cad/test_dialect_registry_freeze.py
```

覆盖：

```python
def test_default_registry_is_frozen():
    ...

def test_frozen_registry_rejects_late_registration():
    ...

def test_registry_rejects_part_named_dialect():
    ...

def test_contract_hash_stable():
    ...

def test_test_registry_can_be_isolated():
    ...

def test_compat_registry_wrapper_uses_default_registry():
    ...
```

---

# 7. Milestone M3：MetadataProof v3

## 7.1 目标

metadata 不应只是“记录”。metadata 是编译证明。

当前 v2.1 已经有 validation normalization 和 contract hash check，这是正确基础。([GitHub][12]) 但 vNext 必须升级为 v3，补全路径、artifact hash、runtime version、native import policy。

---

## 7.2 新增 metadata v3 schema

文件：

```text
src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py
```

Schema：

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class MetadataPathProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_ir_path: str
    validation_seed_path: str
    step_path: str
    metadata_path: str


class RuntimeProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runner_version: str
    geometry_runtime: str
    geometry_runtime_version: str


class ImportPolicyProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    native_rebuild_allowed: Literal[False]
    requires_import_gate: Literal[True]
    step_import_candidate: Literal[True]
    step_import_allowed: Literal[False]


class ArtifactHashProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_sha256: str
    metadata_schema_hash: str | None = None


class GenerativeMetadataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_version: Literal["generative_metadata_v3"]
    source_route: Literal["llm_skill_base"]
    schema_version: str
    canonical_version: str
    trust_level: Literal["concept_geometry", "reference_geometry"]

    document_id: str
    part_name: str

    selected_dialects: list[dict]
    op_versions: list[dict]

    raw_graph_hash: str
    canonical_graph_hash: str

    paths: MetadataPathProof
    runtime: RuntimeProof
    artifact: ArtifactHashProof
    import_policy: ImportPolicyProof

    repair_attempts: int = 0
    repair_patch_hashes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded_features: list[dict] = Field(default_factory=list)
    operation_metrics: list[dict] = Field(default_factory=list)

    safety: dict


class MetadataProofV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generative_metadata: GenerativeMetadataV3
    build_warnings: list[str]
    validation: dict
```

---

## 7.3 v3 builder function

```python
def build_generative_metadata_v3(
    *,
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
    validation: dict,
    canonical_ir_path: Path,
    validation_seed_path: Path,
    step_path: Path,
    metadata_path: Path,
    repair_summary: dict | None = None,
) -> dict:
    ...
```

必须计算：

```text
step_sha256
geometry_runtime_version
native_rebuild_allowed=False
requires_import_gate=True
step_import_allowed=False
```

如果 STEP 文件还没有写完，则 builder 初始 metadata 可使用：

```text
artifact.step_sha256 = "sha256:pending"
```

但最终写入 metadata 前必须替换为真实 hash。最终 metadata validator 不接受 `sha256:pending`。

---

## 7.4 v3 validation

```python
def validate_generative_metadata_v3(
    metadata: dict,
    *,
    canonical: CanonicalGcadDocument | None = None,
    registry: DialectRegistry | None = None,
    require_validation_ok: bool = False,
    require_final_artifact_hash: bool = True,
) -> dict:
    ...
```

必须检查：

```text
metadata_version == generative_metadata_v3
source_route == llm_skill_base
trust_level in concept/reference
selected_dialects non-empty
every selected dialect has contract_hash
contract_hash matches registry
op_versions count == len(canonical.nodes) if canonical provided
raw_graph_hash sha256
canonical_graph_hash sha256
runtime.runner_version exists
runtime.geometry_runtime exists
runtime.geometry_runtime_version exists
paths.step_path exists if require_final_artifact_hash
artifact.step_sha256 matches file if path exists
import_policy.native_rebuild_allowed is False
import_policy.requires_import_gate is True
import_policy.step_import_candidate is True
import_policy.step_import_allowed is False
safety exists and all required flags true
validation contains all required stages
if require_validation_ok=True every stage.ok is True
```

---

## 7.5 Compatibility

保留 v2.1 validator 一段时间，但 production builder 应使用 v3：

```text
builder -> build_generative_metadata_v3
import_gate -> validate_generative_metadata_v3
v2.1 -> only compatibility tests
```

---

## 7.6 测试

新增：

```text
tests/generative_cad/test_metadata_v3_proof.py
```

覆盖：

```python
def test_metadata_v3_requires_paths():
    ...

def test_metadata_v3_requires_runtime_version():
    ...

def test_metadata_v3_requires_native_rebuild_false():
    ...

def test_metadata_v3_requires_import_gate_true():
    ...

def test_metadata_v3_step_hash_matches_file():
    ...

def test_metadata_v3_contract_hash_mismatch_fails():
    ...

def test_metadata_v3_missing_validation_stage_fails_closed():
    ...

def test_metadata_v3_require_validation_ok_rejects_false_stage():
    ...
```

---

# 8. Milestone M4：Artifact state 与 ImportGate 闭环

## 8.1 当前状态

artifact builder 当前已经返回 `validated_reference_step`，step import 不允许；import gate 成功时返回 `state="native_import_eligible"` 并设置 `step_import_allowed=True`。([GitHub][7])

这已经接近正确，但需要统一 typed model，避免散 dict 漂移。

---

## 8.2 新增 artifact models

文件：

```text
src/seekflow_engineering_tools/generative_cad/pipeline/artifact_models.py
```

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict


ArtifactState = Literal[
    "created_unverified",
    "validated_reference_step",
    "native_import_eligible",
]


class CanonicalStepArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["canonical_step_artifact"]
    artifact_schema_version: Literal["canonical_step_artifact_v1"]

    source_route: Literal["llm_skill_base"]
    state: Literal["validated_reference_step"]

    part_name: str
    document_id: str

    step_path: str
    metadata_path: str
    graph_path: str
    validation_seed_path: str | None = None
    runner_script_path: str | None = None

    units: Literal["mm"]
    trust_level: Literal["concept_geometry", "reference_geometry"]

    schema_version: str
    canonical_version: str

    raw_graph_hash: str
    canonical_graph_hash: str
    selected_dialects: list[dict]

    native_rebuild_allowed: Literal[False]
    step_import_candidate: Literal[True]
    step_import_allowed: Literal[False]
    requires_import_gate: Literal[True]

    step_sha256: str
    metadata_sha256: str | None = None

    inspection: dict
    validation: dict
```

---

## 8.3 `build_canonical_step_artifact()` 返回 model_dump

`artifact.py` 中先构造 `CanonicalStepArtifact`，再 `.model_dump()`。

如果 `validation` 缺失，保持当前 fail-closed 默认，但 production builder 必须始终传入真实 validation。

---

## 8.4 ImportGateResult model

文件：

```text
src/seekflow_engineering_tools/generative_cad/pipeline/import_gate_models.py
```

```python
class ImportGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    state: Literal["native_import_eligible"] | None = None
    issues: list[dict]
    metadata: dict | None
    gate: dict
```

---

# 9. Milestone M5：Repair prompt 与 RepairPatch 硬化

## 9.1 必须立即修 prompt path

当前 prompt 中 `/nodes//params/` 必须改为：

```text
/nodes/<node_id>/params/<field>
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/nodes/<node_id>/required
/nodes/<node_id>/degradation_policy
/components/<component_id>/root_node
```

禁止路径：

```text
/schema_version
/selected_dialects
/safety
/constraints/require_step_file
/constraints/require_metadata_sidecar
/constraints/require_closed_solid
/nodes/<node_id>/dialect
/nodes/<node_id>/op
/nodes/<node_id>/op_version
/components/<component_id>/owner_dialect
```

---

## 9.2 最终 Repair Prompt

将 `REPAIR_PATCH_SYSTEM_PROMPT_V2` 替换为：

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

---

## 9.3 测试

```text
tests/generative_cad/test_repair_prompt_vnext_paths.py
```

覆盖：

```python
def test_repair_prompt_uses_node_id_placeholders():
    ...

def test_repair_prompt_does_not_contain_double_slash_paths():
    ...

def test_repair_prompt_forbids_safety_modification():
    ...

def test_repair_prompt_forbids_op_version_modification():
    ...
```

行为测试：

```python
def test_patch_rejects_safety_path():
    ...

def test_patch_rejects_op_path():
    ...

def test_patch_accepts_node_params_path():
    ...

def test_patch_old_value_mismatch_rejects():
    ...
```

---

# 10. Milestone M6：Prompt ABI 升级

## 10.1 Level-1 Routing Prompt vNext

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

Required output shape:
{
  "route_decision": "generative_cad_ir",
  "part_intent": {
    "object_type": "...",
    "dominant_geometry": "...",
    "engineering_domain": "..."
  },
  "selected_dialects": [
    {
      "dialect": "...",
      "version": "...",
      "reason": "..."
    }
  ],
  "selected_domain_skills": [
    {
      "skill_id": "...",
      "reason": "..."
    }
  ],
  "unsupported_capabilities": [],
  "safety_notes": []
}
```

---

## 10.2 Level-2 Authoring Prompt vNext

替换为：

```text
You are the source author for a constrained G-CAD compiler.

You must output RawGcadDocument JSON only.

You are not a CAD kernel.
You are not a CadQuery programmer.
You are not a SolidWorks automation author.
You are not an NXOpen automation author.
You are not an APDL author.
You are a constrained feature-graph author.

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

# 11. Milestone M7：Legacy production namespace 隔离

## 11.1 目标

legacy 可以保留，但必须只能被 legacy tests 或 explicit compatibility adapter 使用。

生产代码禁止 import：

```text
seekflow_engineering_tools.generative_cad.legacy
seekflow_engineering_tools.generative_cad.bases
seekflow_engineering_tools.generative_cad.ir      # 如果它是 v0.1 legacy 文件
seekflow_engineering_tools.generative_cad.base
seekflow_engineering_tools.generative_cad.runner  # legacy single-base runner
seekflow_engineering_tools.generative_cad.registry
seekflow_engineering_tools.generative_cad.validation
```

---

## 11.2 Deprecation barrier

每个 legacy top-level module 加：

```python
import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad v0.1 import path is disabled in production. "
        "Use generative_cad.ir.raw, generative_cad.validation.pipeline, "
        "generative_cad.pipeline.run, or generative_cad.dialects.* instead."
    )
```

如果某些测试仍需要 import，则在测试里显式设置 env var。

---

## 11.3 Import scan test

新增：

```text
tests/generative_cad/test_no_production_legacy_imports_vnext.py
```

扫描：

```python
PROD_ROOT = Path("integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad")
ALLOWED_DIR_PARTS = {"legacy", "compatibility"}

FORBIDDEN = [
    "generative_cad.legacy",
    "generative_cad.bases",
    "generative_cad.ir import GenerativeCADSpec",
    "generative_cad.base import",
    "generative_cad.runner import",
    "generative_cad.registry import",
    "generative_cad.validation import",
]
```

---

# 12. Milestone M8：测试体系从字符串测试升级到行为测试

当前测试目录有大量 v05-v10 hardening 测试，这是好的，但 vNext 必须避免只用 `inspect.getsource()` 检查字符串。测试目录显示目前已经累积了大量 builder/import gate/metadata/prompt/legacy isolation 测试文件，下一步应把关键 release-blocker 改成行为测试。([GitHub][13])

## 12.1 必须新增行为测试

```text
tests/generative_cad/test_vnext_raw_parse_behavior.py
tests/generative_cad/test_vnext_runner_proof_behavior.py
tests/generative_cad/test_vnext_operation_result_behavior.py
tests/generative_cad/test_vnext_metadata_v3_behavior.py
tests/generative_cad/test_vnext_artifact_import_state_behavior.py
tests/generative_cad/test_vnext_registry_freeze_behavior.py
tests/generative_cad/test_vnext_repair_patch_behavior.py
tests/generative_cad/test_vnext_legacy_import_barrier.py
```

---

## 12.2 测试清单

### Raw parse

```python
def test_missing_safety_fails_before_pydantic():
    ...

def test_missing_constraints_fails_before_pydantic():
    ...

def test_missing_each_safety_flag_fails():
    ...

def test_missing_expected_body_count_fails():
    ...

def test_valid_explicit_raw_passes():
    ...
```

### Runner proof

```python
def test_run_canonical_requires_validation_seed():
    ...

def test_run_canonical_from_files_requires_validation_seed_json():
    ...

def test_builder_harness_contains_validation_seed_json():
    ...

def test_validation_seed_not_mutated_by_runner():
    ...
```

### Operation result

```python
def test_runtime_output_must_match_declared_outputs():
    ...

def test_runtime_output_handle_type_must_match_declared_type():
    ...

def test_operation_result_metrics_propagate():
    ...
```

### Metadata v3

```python
def test_metadata_v3_requires_step_path():
    ...

def test_metadata_v3_requires_runtime_version():
    ...

def test_metadata_v3_rejects_native_rebuild_true():
    ...

def test_metadata_v3_rejects_missing_import_policy():
    ...

def test_metadata_v3_validates_step_hash():
    ...
```

### Import gate

```python
def test_builder_artifact_not_import_allowed():
    ...

def test_import_gate_promotes_to_native_import_eligible():
    ...

def test_import_gate_rejects_metadata_without_runtime_postconditions():
    ...
```

---

# 13. Claude Code 总实施 Prompt

下面这段可以直接交给 Claude Code：

```text
You are implementing a compiler-grade vNext hardening pass for SeekFlow generative_cad.

Primary goal:
Make Generative CAD a robust, ABI-stable compiler pipeline:
RawGcadDocument -> ValidationBundle -> CanonicalGcadDocument -> LinkedExecutablePlan -> OperationResult execution -> GeometryRuntime -> STEP -> MetadataProofV3 -> CanonicalStepArtifact -> ImportGate.

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

Implement in this order:

M1 OperationResult ABI:
- Add dialects/executor.py.
- Make OperationSpec handler support OperationResult.
- Keep v1_dict adapter only for existing builtin ops.
- All run_component methods must call execute_operation.
- Validate output names, output types, handle existence, and handle value_type.
- Add behavior tests.

M2 Frozen DialectRegistry:
- Add DialectRegistry class with register/freeze/require/contract_hash.
- Add build_default_registry/default_registry.
- Remove import-time populate_registry side effect.
- Keep compatibility wrapper functions.
- Add freeze and isolation tests.

M3 MetadataProofV3:
- Add metadata_v3.py.
- Include paths, runtime version, artifact hashes, import policy, safety, validation proof.
- Builder should write final v3 metadata.
- Import gate should validate v3.
- Keep v2.1 compatibility tests but production builder uses v3.

M4 Artifact typed model:
- Add CanonicalStepArtifact model.
- Builder output state must be validated_reference_step.
- step_import_allowed must be false until import gate.
- Import gate returns native_import_eligible only after all checks.

M5 Repair prompt:
- Replace /nodes//... placeholders with /nodes/<node_id>/...
- Add prompt tests and RepairPatch behavior tests.
- Repair must not modify safety, constraints, dialect, op, op_version.

M6 Prompt ABI:
- Upgrade Level-1 and Level-2 prompts.
- Level-2 must require explicit constraints and safety objects and every safety flag.

M7 Legacy isolation:
- Add deprecation barriers to legacy top-level modules.
- Production code must not import generative_cad.legacy or generative_cad.bases.
- Add import scan tests.

M8 Behavior tests:
- Add vNext behavior tests listed in the architecture document.
- Avoid source-string-only tests for release blockers.

Acceptance:
- pytest tests/generative_cad -q
- pytest tests -q
- No production import from legacy namespaces.
- Existing deterministic primitive tests still pass.
```

---

# 14. Claude Code 分阶段 Prompt

## 14.1 M1 OperationResult Prompt

```text
Implement M1 OperationResult ABI wiring.

Files:
- generative_cad/dialects/results.py
- generative_cad/dialects/operation.py
- generative_cad/dialects/executor.py
- generative_cad/dialects/base.py
- generative_cad/dialects/axisymmetric/dialect.py
- generative_cad/dialects/sketch_extrude/dialect.py
- generative_cad/dialects/composition/dialect.py
- generative_cad/runtime/object_store.py
- tests/generative_cad/test_vnext_operation_result_behavior.py

Requirements:
1. Add execute_operation(node, op_spec, ctx).
2. Normalize handler output to OperationResult.
3. Validate returned output names exactly match CanonicalNode.outputs.
4. Validate returned output value_type matches CanonicalNode.outputs.
5. Validate RuntimeObjectStore handle exists.
6. Validate stored handle value_type matches output type.
7. Propagate warnings, degraded_features, metrics.
8. Keep v1_dict adapter only for existing builtin ops.
9. New op specs should use handler_kind="v2_result".
10. Do not alter Core IR.
11. Do not weaken validation.

Run:
pytest tests/generative_cad/test_vnext_operation_result_behavior.py -q
pytest tests/generative_cad -q
```

---

## 14.2 M2 Registry Prompt

```text
Implement M2 Frozen DialectRegistry.

Files:
- generative_cad/dialects/registry_core.py
- generative_cad/dialects/default_registry.py
- generative_cad/dialects/registry.py
- validation modules that call require_dialect/get_dialect
- metadata validators that call dialect_contract_hash
- tests/generative_cad/test_vnext_registry_freeze_behavior.py

Requirements:
1. Add DialectRegistry class with register, freeze, require, get, list_ids, export_catalog, contract_hash.
2. build_default_registry registers axisymmetric, sketch_extrude, composition, then freezes.
3. default_registry is cached.
4. Remove import-time populate_registry side effects.
5. Compatibility functions in registry.py delegate to default_registry.
6. Production registry is frozen.
7. Tests can build isolated registry instances.
8. Duplicate dialect fails.
9. Part-named dialect fails.
10. Contract hash stable.

Run:
pytest tests/generative_cad/test_vnext_registry_freeze_behavior.py -q
pytest tests/generative_cad -q
```

---

## 14.3 M3 Metadata v3 Prompt

```text
Implement M3 MetadataProofV3.

Files:
- generative_cad/pipeline/metadata_v3.py
- generative_cad/pipeline/metadata.py if compatibility wrapper needed
- generative_cad/pipeline/run.py
- generative_cad/builder.py
- generative_cad/pipeline/import_artifact.py
- tests/generative_cad/test_vnext_metadata_v3_behavior.py

Requirements:
1. Add Pydantic models for MetadataProofV3.
2. Add build_generative_metadata_v3.
3. Add validate_generative_metadata_v3.
4. Metadata v3 must include paths, runtime proof, artifact hash proof, import policy, safety, dialect contract hashes, op_versions, raw/canonical graph hashes.
5. Production builder writes v3 metadata.
6. Import gate validates v3 metadata.
7. v2.1 can remain for compatibility tests.
8. Missing validation stages fail closed.
9. native_rebuild_allowed must be false.
10. requires_import_gate must be true.
11. step_import_allowed must be false in metadata proof.
12. step_sha256 must match final STEP file.

Run:
pytest tests/generative_cad/test_vnext_metadata_v3_behavior.py -q
pytest tests/generative_cad -q
```

---

## 14.4 M4 Artifact / Import Gate Prompt

```text
Implement M4 typed artifact state machine.

Files:
- generative_cad/pipeline/artifact_models.py
- generative_cad/pipeline/artifact.py
- generative_cad/pipeline/import_gate_models.py
- generative_cad/pipeline/import_artifact.py
- generative_cad/builder.py
- tests/generative_cad/test_vnext_artifact_import_state_behavior.py

Requirements:
1. Add CanonicalStepArtifact Pydantic model.
2. build_canonical_step_artifact returns model_dump.
3. Builder artifact state is validated_reference_step.
4. Builder artifact step_import_allowed is false.
5. Builder artifact requires_import_gate is true.
6. Import gate is the only path returning native_import_eligible.
7. Import gate success sets gate.step_import_allowed true.
8. Native rebuild remains false.
9. Artifact validation must equal metadata validation proof.
10. Artifact step hash must match metadata step hash.

Run:
pytest tests/generative_cad/test_vnext_artifact_import_state_behavior.py -q
pytest tests/generative_cad -q
```

---

## 14.5 M5 Repair Prompt Prompt

```text
Implement M5 repair prompt path hardening.

Files:
- generative_cad/skills/prompts.py
- generative_cad/repair/patch.py if needed
- tests/generative_cad/test_vnext_repair_patch_behavior.py
- tests/generative_cad/test_repair_prompt_vnext_paths.py

Requirements:
1. Replace all /nodes//... and /components//... placeholders.
2. Use /nodes/<node_id>/params/<field>.
3. Use /components/<component_id>/root_node.
4. Prompt must forbid /safety.
5. Prompt must forbid /constraints/require_*.
6. Prompt must forbid dialect/op/op_version changes.
7. RepairPatch implementation must enforce the same restrictions.
8. Add behavior tests for allowed and forbidden paths.

Run:
pytest tests/generative_cad/test_repair_prompt_vnext_paths.py -q
pytest tests/generative_cad/test_vnext_repair_patch_behavior.py -q
pytest tests/generative_cad -q
```

---

# 15. 最终验收矩阵

vNext 完成后必须满足：

```text
Raw parse:
  missing safety fails
  missing constraints fails
  missing safety flag fails
  missing expected_body_count fails
  valid explicit raw passes

Core validation:
  unknown dialect fails
  unknown op fails
  unknown op_version fails
  duplicate node fails
  missing input reference fails
  graph cycle fails
  type mismatch fails
  phase order fails
  cross-component non-composition fails

Operation runtime:
  handler output name mismatch fails
  handler output type mismatch fails
  handle type mismatch fails
  missing handle fails
  OperationResult metrics propagate

Runner:
  canonical runner requires validation seed
  validation seed not mutated
  fixed harness passes validation_seed_json
  GeometryRuntime export is used

Artifact:
  builder returns validated_reference_step
  builder step_import_allowed false
  import gate returns native_import_eligible
  native rebuild always false

Metadata:
  v3 requires paths
  v3 requires runtime version
  v3 requires step hash
  v3 requires import policy
  contract hash mismatch fails
  missing validation stage fails closed
  require_validation_ok rejects false stage

Repair:
  cannot modify safety
  cannot modify require_* constraints
  cannot modify dialect/op/op_version
  can modify /nodes/<node_id>/params/<field>
  old_value mismatch rejects patch

Legacy:
  production imports from legacy fail
  compatibility adapter explicit only
  primitive path unchanged
```

---

# 16. 最终架构评价与方向

当前代码已经修掉了上一轮最危险的几个 P0：Raw safety/constraints 默认补齐、parse 层未接入、canonical runner 无 proof、artifact import state 混乱、runner 直接 CadQuery export。这些已经明显改善。([GitHub][1])

现在真正阻止它成为顶级架构的是：

```text
1. OperationResult ABI 没有贯通 runtime execution。
2. Registry 仍是 import-time global mutable state。
3. Metadata proof 仍不是完整 provenance proof。
4. Repair prompt path 仍不合法。
5. Legacy namespace 仍容易误导生产 import。
6. 测试需要从字符串检查升级为行为证明。
```

最终正确形态应该是：

```text
稳定 Core IR；
显式 Raw safety；
单入口 parse；
fail-closed validation；
contract-linked canonical IR；
frozen registry；
typed OperationResult；
typed RuntimeObjectStore；
backend-neutral GeometryRuntime；
metadata proof v3；
artifact state machine；
import gate sole authority；
legacy explicit compatibility only；
Primitive 主链路零污染。
```

这才是一个健康、强壮、兼容性强、低频修改核心编译器、能承载长期 text-to-CAD 演进的架构。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/parse.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/registry.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py "raw.githubusercontent.com"
[12]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[13]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/tests/generative_cad "seekflow-engineering/integrations/engineering_tools/tests/generative_cad at main · WYZAAACCC/seekflow-engineering · GitHub"
