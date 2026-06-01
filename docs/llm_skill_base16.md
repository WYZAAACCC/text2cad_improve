# SeekFlow Generative CAD-IR vNext 终极工程实施文档

**面向 Claude Code 的可落地架构修复规范**

我以当前 GitHub `main` 上可见源码为准重新审阅。先明确一个关键事实：**当前代码并没有真正完成上一轮目标架构的闭环**。现在确实出现了一些正确模块，例如 `ir/parse.py`、`dialects/executor.py`、`metadata_v3.py`、`artifact_models.py`，但很多模块仍是“已创建但未贯通 production path”。更严重的是，当前 `RawGcadDocument` 仍然通过 defaults / `default_factory` 自动补齐 `schema_version`、`units`、`trust_level`、`constraints` 和 `safety`，而 `validation/pipeline.py` 对 dict 输入仍直接 `RawGcadDocument.model_validate(raw)`，没有使用 `parse_raw_gcad_document()`。这意味着“缺 safety / constraints 必须 fail-closed”的最核心要求仍没有完全生效。([GitHub][1])

本文档的目标是给 Claude Code 一份**不留模糊空间**的实施蓝图，把当前系统从“正确方向的原型”推进到真正的：

```text
LLM constrained source
  → compiler front-end
  → canonical IR
  → dialect-linked executable plan
  → typed runtime execution
  → GeometryRuntime
  → STEP
  → MetadataProofV3
  → CanonicalStepArtifact
  → ImportGate
```

这正符合你的架构基线：新增链路必须是独立的受控 Generative CAD-IR，不是 LLM 直接写 CAD 代码，不是把 Primitive 改成 LLM 生成，也不是每个零件一个 base；最终合流点只能是 canonical STEP artifact + metadata，而不是 `CADPartSpec`、`primitive_compiler.py`、`PRIMITIVE_COMPILERS` 或 `geometry_primitives`。 

---

# 0. 当前代码状态的真实判断

## 0.1 当前已存在但未真正闭环的模块

当前仓库已经有一些正确方向的模块：

```text
generative_cad/ir/parse.py
generative_cad/dialects/executor.py
generative_cad/pipeline/metadata_v3.py
generative_cad/pipeline/artifact_models.py
```

但是这些模块目前没有被 production path 充分使用。`parse.py` 定义了 required top-level keys、required safety keys、required constraint keys，并能输出 path-aware parse issues；但 `validation/pipeline.py` 仍然直接 `RawGcadDocument.model_validate(raw)`。([GitHub][2])

`dialects/executor.py` 已经定义统一 executor，并要求通过 `OperationResult` 校验 output name、value type、handle 存在性和 handle type；但当前 `axisymmetric/dialect.py` 的 `run_component()` 仍直接调用 `op_spec.handler(node, ctx)` 并绑定 dict outputs，没有走 `execute_operation()`。([GitHub][3])

`metadata_v3.py` 已经声明自己是 production replacement，但 `pipeline/run.py` 仍调用 v2 的 `build_generative_metadata`，`builder.py` 仍使用 `validate_generative_metadata_v2`，`import_artifact.py` 也仍是 v2 gate。([GitHub][4])

`artifact_models.py` 已经定义 `CanonicalStepArtifact`，包括 `state`、`step_import_candidate`、`step_import_allowed`、`requires_import_gate`、`step_sha256`、`metadata_sha256` 等字段；但 `pipeline/artifact.py` 仍返回手写 dict，而且当前还把 `step_import_allowed` 设为 `True`，这与 typed artifact model 的 `Literal[False]` 完全相冲突。([GitHub][5])

## 0.2 当前仍是 release blocker 的事实

当前 `RawConstraints` 和 `RawSafety` 仍有默认值；`RawGcadDocument.constraints` 和 `RawGcadDocument.safety` 仍使用 `Field(default_factory=...)`。这会导致某些路径中缺失 safety / constraints 被 Pydantic 自动补齐，而不是 fail-closed。([GitHub][1])

当前 `run_canonical_gcad_from_files()` 没有 `validation_seed_json` 参数，仍然调用 `run_canonical_gcad(canonical, out_step=..., metadata_path=...)`；`run_canonical_gcad()` 仍允许 `validation_seed=None` 且 `require_full_validation_seed=False`，没有 seed 时只是追加 warning。([GitHub][6])

当前 `RuntimeContext` 仍然只有 `geometry_runtime_name: str = "cadquery"`，没有持有 `GeometryRuntime` 对象；`_export_final_solid()` 仍直接 `import cadquery as cq` 并调用 `cq.exporters.export(...)`。这说明 GeometryRuntime 抽象还没有真正接入当前 production runner。([GitHub][7])

当前 `RuntimeObjectStore` 没有 `get_typed()`，但 `execute_operation()` 调用了 `ctx.object_store.get_typed(...)`。这意味着只要 dialect 接入 executor，就会触发 `AttributeError`。([GitHub][3])

当前 `dialects/registry.py` 仍是 module-level `DIALECT_REGISTRY`，并在 import 时调用 `populate_registry()`；这不是 frozen registry，也不是可注入 registry。([GitHub][8])

当前 repair prompt 仍包含 `/nodes//params/`、`/nodes//inputs`、`/components//root_node` 这种无效 path，而你的 v1.0 记忆文档明确要求 repair prompt path 必须使用 `/nodes/<node_id>/params/<field>` 等有效占位。([GitHub][9]) 

---

# 1. 最高优先级目标

你需要让 Claude Code 明白：**不要继续新增“看起来正确但不接线”的模块。** 当前真正的问题不是缺概念，而是缺 production wiring。

最终必须形成这条不可绕过的 pipeline：

```text
User NL
  ↓
Level-1 Routing Skill
  ↓
DialectSelectionPlan
  ↓
Level-2 Dialect Authoring Skill
  ↓
RawGcadDocument JSON
  ↓
parse_raw_gcad_document(data)
  ↓
RawGcadDocument
  ↓
validate_and_canonicalize_with_bundle(raw)
  ↓
ValidationBundle + CanonicalGcadDocument
  ↓
run_canonical_gcad(canonical, validation_seed)
  ↓
Frozen DialectRegistry
  ↓
BaseDialect.run_component
  ↓
execute_operation
  ↓
OperationResult
  ↓
RuntimeObjectStore typed handles
  ↓
GeometryRuntime.export_step
  ↓
runtime_postconditions
  ↓
STEP inspection
  ↓
MetadataProofV3
  ↓
CanonicalStepArtifact
  ↓
ImportGate
  ↓
native_import_eligible STEP import only
```

必须禁止：

```text
Raw dict → RawGcadDocument.model_validate directly
Raw JSON → BaseDialect directly
Canonical IR without ValidationBundle → runner
runner direct CadQuery export
artifact.step_import_allowed = True before import gate
metadata v2.1 in production build/import gate
repair path /nodes//...
generative path → primitive compiler
```

---

# 2. 不变量：这些是编译器内核级硬约束

这些不变量必须作为代码和测试存在，不是注释：

```text
1. LLM Raw JSON 永远先进入 parse_raw_gcad_document。
2. RawGcadDocument.safety 和 constraints 不允许 default / default_factory。
3. Core IR 不知道 op-specific 参数。
4. node.params 只由 OperationSpec.params_model 校验。
5. Unknown dialect/op/op_version/type/phase 必须 fail-closed。
6. BaseDialect 之间不能互相调用。
7. 多 dialect 组合只能通过 composition dialect。
8. RuntimeObjectStore 只允许 typed handles 跨 dialect 传递。
9. runner 必须接收 CanonicalGcadDocument + ValidationBundle proof。
10. GeometryRuntime 是 CAD backend 的唯一导出接口。
11. Builder artifact 只能是 validated_reference_step。
12. ImportGate 是 native_import_eligible 的唯一权威。
13. Generative artifact 永远 native_rebuild_allowed=False。
14. Generative trust_level 永远不超过 reference_geometry。
15. metadata 缺失、safety 缺失、contract hash mismatch、STEP 缺失都必须 fail。
16. Primitive path 不能被 generative path 修改或污染。
```

这些约束直接来自你的架构文档：LLM 输出必须通过 Core IR 验证，node.params 由 OperationSpec 校验，多 Base 只能通过 Composition Dialect，unknown dialect/op fail-closed，不允许 silent fallback，runner 固定 harness，输出必须是 canonical STEP artifact + metadata，trust level 不超过 reference_geometry。

---

# 3. Milestone M0：禁止修改范围

Claude Code 的第一条指令必须是：

```text
Do not modify:
- cadquery_backend/primitive_compiler.py
- geometry_primitives/
- CADPartSpec semantics
- PRIMITIVE_COMPILERS
- deterministic primitive route semantics
```

允许修改：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/**
integrations/engineering_tools/tests/generative_cad/**
tool descriptions that refer to generative_cad
```

当前 `cadquery_backend/primitive_compiler.py` 仍是 deterministic primitive compiler 的路径，不应被 generative path 污染。你的文档也明确要求新链路不能进入 `CADPartSpec`、`primitive_compiler.py`、`PRIMITIVE_COMPILERS`、`geometry_primitives`，合流点仅为 STEP + metadata。

---

# 4. Milestone M1：Raw parse / explicit safety 彻底修正

## 4.1 当前问题

当前 `RawConstraints` / `RawSafety` 仍有默认值，`RawGcadDocument.constraints` / `safety` 仍有 `default_factory`。([GitHub][1])

当前 `validation/pipeline.py` 对 dict 输入仍直接：

```python
raw = RawGcadDocument.model_validate(raw)
```

而不是：

```python
parse_raw_gcad_document(raw)
```

这会绕过 `parse.py` 中对显式字段的结构化检查。([GitHub][10])

## 4.2 必须修改文件

```text
generative_cad/ir/raw.py
generative_cad/ir/parse.py
generative_cad/validation/pipeline.py
generative_cad/builder.py
generative_cad/tools.py
tests/generative_cad/test_vnext_raw_parse_behavior.py
```

## 4.3 `ir/raw.py` 的目标实现

把所有安全关键字段改为无默认值：

```python
class RawConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_step_file: bool
    require_metadata_sidecar: bool
    require_closed_solid: bool
    expected_body_count: int = Field(ge=1)
    expected_bbox_mm: list[float] | None = None
    bbox_tolerance_mm: float = Field(default=1.0, gt=0)
    max_runtime_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def fail_closed_flags(self):
        if self.require_step_file is not True:
            raise ValueError("constraints.require_step_file must be explicitly true")
        if self.require_metadata_sidecar is not True:
            raise ValueError("constraints.require_metadata_sidecar must be explicitly true")
        if self.require_closed_solid is not True:
            raise ValueError("constraints.require_closed_solid must be explicitly true")
        if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
            raise ValueError("expected_bbox_mm must be [x, y, z]")
        return self


class RawSafety(BaseModel):
    model_config = ConfigDict(extra="forbid")

    non_flight_reference_only: bool
    not_airworthy: bool
    not_certified: bool
    not_for_manufacturing: bool
    not_for_installation: bool
    no_structural_validation: bool
    no_life_prediction: bool

    @model_validator(mode="after")
    def all_true(self):
        for key, value in self.model_dump().items():
            if value is not True:
                raise ValueError(f"safety.{key} must be explicitly true")
        return self


class RawGcadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["g_cad_core_v0.2"]
    document_id: str
    part_name: str
    units: Literal["mm"]
    trust_level: Literal["concept_geometry", "reference_geometry"]
    selected_dialects: list[RawSelectedDialect]
    components: list[RawComponent]
    nodes: list[RawNode]
    constraints: RawConstraints
    safety: RawSafety
    llm_validation_hints: dict[str, Any] = Field(default_factory=dict)
```

允许保留非安全关键字段默认值，例如 `bbox_tolerance_mm` 和 `max_runtime_seconds`，但不允许 safety / core constraints / schema envelope 自动补齐。

## 4.4 `validation/pipeline.py` 必须使用 parse layer

当前 dict 输入必须改成：

```python
from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document

if isinstance(raw, dict):
    parsed = parse_raw_gcad_document(raw)
    if not parsed.ok or parsed.document is None:
        stages_run.append("structure")
        issues = [
            ValidationIssue(
                stage="structure",
                code=i.code,
                message=i.message,
                path=i.path,
                severity=i.severity,
            )
            for i in parsed.issues
        ]
        report = ValidationReport(
            ok=False,
            stage="structure",
            issues=issues,
            stages_run=list(stages_run),
        )
        bundle = ValidationBundle(
            ok=False,
            raw_stage_reports={"structure": report},
            canonicalize_report=None,
            canonical_stage_reports={},
        )
        return None, report, bundle
    raw = parsed.document
```

禁止 production path 再直接对 LLM dict 调用 `RawGcadDocument.model_validate`.

## 4.5 `builder.py` 必须使用 validation pipeline

当前 builder 对 dict 输入直接 `RawGcadDocument.model_validate(spec)`。([GitHub][11])

改为：

```python
# Do not pre-parse dict here.
# Let validate_and_canonicalize_with_bundle own the only raw parse path.
canonical, report, validation_bundle = validate_and_canonicalize_with_bundle(spec)
```

如果需要先过滤 legacy spec，则只做形状判断，不做 model_validate。

## 4.6 测试

新增：

```python
def test_missing_safety_fails_before_pydantic_defaults(): ...
def test_missing_constraints_fails_before_pydantic_defaults(): ...
def test_missing_safety_flag_fails_with_path(): ...
def test_missing_expected_body_count_fails_with_path(): ...
def test_builder_rejects_missing_safety_dict(): ...
def test_validate_and_canonicalize_uses_parse_layer(monkeypatch): ...
def test_raw_model_has_no_safety_default_factory(): ...
def test_raw_model_has_no_constraints_default_factory(): ...
```

验收命令：

```bash
pytest tests/generative_cad/test_vnext_raw_parse_behavior.py -q
pytest tests/generative_cad -q
```

---

# 5. Milestone M2：Canonical runner 必须强制 validation seed

## 5.1 当前问题

当前 `run_canonical_gcad_from_files()` 不接受 `validation_seed_json`，`run_canonical_gcad()` 的 `validation_seed` 是 optional，`require_full_validation_seed` 默认 False。([GitHub][6])

这意味着 canonical runner 仍然能无 proof 生成 STEP + metadata。

## 5.2 必须修改文件

```text
generative_cad/pipeline/run.py
generative_cad/builder.py
tests/generative_cad/test_vnext_runner_proof_behavior.py
```

## 5.3 目标接口

```python
def run_canonical_gcad_from_files(
    canonical_json: str | Path,
    validation_seed_json: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    ...
```

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
    if not validation_seed:
        return GcadRunResult(
            ok=False,
            error="run_canonical_gcad requires non-empty validation_seed",
        )
```

`validation_seed` 不允许默认为 `None`。

## 5.4 Builder harness 必须写 validation seed

builder 必须写：

```text
.generative_cad_graphs/gcad_<id>.validation.json
```

内容：

```python
validation_bundle.to_metadata_dict()
```

harness 代码必须是：

```python
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"...",
    validation_seed_json=r"...",
    out_step=r"...",
    metadata_path=r"...",
)
```

## 5.5 测试

```python
def test_run_canonical_requires_validation_seed(): ...
def test_run_canonical_from_files_requires_validation_seed_json(): ...
def test_builder_harness_passes_validation_seed_json(): ...
def test_validation_seed_is_deep_copied_not_mutated(): ...
```

---

# 6. Milestone M3：GeometryRuntime 真实接入

## 6.1 当前问题

当前 `RuntimeContext` 只有 `geometry_runtime_name` 字符串，没有 `geometry_runtime` 对象；runner export 仍直接 import CadQuery。([GitHub][7])

## 6.2 必须新增 / 修改文件

```text
generative_cad/runtime/geometry_runtime.py
generative_cad/runtime/cadquery_runtime.py
generative_cad/runtime/context.py
generative_cad/pipeline/run.py
tests/generative_cad/test_vnext_geometry_runtime_behavior.py
```

## 6.3 新增 `geometry_runtime.py`

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GeometryRuntime(Protocol):
    runtime_id: str
    runtime_version: str

    def export_step(self, solid_obj: Any, out_step: Path) -> None:
        ...

    def inspect_solid(self, solid_obj: Any) -> dict:
        ...

    def validate_closed_solid(self, solid_obj: Any) -> dict:
        ...

    def compute_bbox_mm(self, solid_obj: Any) -> list[float] | None:
        ...

    def count_bodies(self, solid_obj: Any) -> int | None:
        ...
```

## 6.4 新增 `cadquery_runtime.py`

```python
class CadQueryRuntime:
    runtime_id = "cadquery"
    runtime_version = "cadquery_runtime_v1"

    def export_step(self, solid_obj: Any, out_step: Path) -> None:
        import cadquery as cq
        cq.exporters.export(solid_obj, str(out_step))

    def inspect_solid(self, solid_obj: Any) -> dict:
        return {"ok": True, "runtime": self.runtime_id}

    def validate_closed_solid(self, solid_obj: Any) -> dict:
        return {"ok": True}

    def compute_bbox_mm(self, solid_obj: Any) -> list[float] | None:
        return None

    def count_bodies(self, solid_obj: Any) -> int | None:
        return None
```

## 6.5 修改 `RuntimeContext`

```python
@dataclass
class RuntimeContext:
    out_step: Path
    metadata_path: Path
    workspace_root: Path
    geometry_runtime: GeometryRuntime = field(default_factory=CadQueryRuntime)
    object_store: RuntimeObjectStore = field(default_factory=RuntimeObjectStore)
    ...

    @property
    def geometry_runtime_name(self) -> str:
        return self.geometry_runtime.runtime_id

    @property
    def geometry_runtime_version(self) -> str:
        return self.geometry_runtime.runtime_version
```

## 6.6 修改 runner export

当前：

```python
obj = ctx.object_store.get(handle_id)
import cadquery as cq
cq.exporters.export(obj, str(ctx.out_step))
```

改为：

```python
obj = ctx.object_store.get(handle_id)
ctx.geometry_runtime.export_step(obj, ctx.out_step)
```

## 6.7 测试

```python
def test_runtime_context_has_geometry_runtime_object(): ...
def test_runner_export_uses_geometry_runtime(monkeypatch): ...
def test_run_py_does_not_import_cadquery_for_export(): ...
def test_metadata_records_runtime_id_and_version(): ...
```

---

# 7. Milestone M4：OperationResult ABI 贯通 production execution

## 7.1 当前问题

当前 `OperationSpec.handler` 仍是 `Callable[..., dict[str, str]]`，`axisymmetric.run_component()` 仍直接调用 handler；`execute_operation()` 需要 `get_typed()`，但 `RuntimeObjectStore` 没有。([GitHub][12])

## 7.2 修改文件

```text
generative_cad/runtime/object_store.py
generative_cad/dialects/operation.py
generative_cad/dialects/executor.py
generative_cad/dialects/axisymmetric/dialect.py
generative_cad/dialects/sketch_extrude/dialect.py
generative_cad/dialects/composition/dialect.py
tests/generative_cad/test_vnext_operation_result_behavior.py
```

## 7.3 `RuntimeObjectStore.get_typed`

新增：

```python
@dataclass(frozen=True)
class StoredRuntimeObject:
    handle_id: str
    value_type: str
    handle: RuntimeHandle
    obj: Any


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

如果 `RuntimeHandle` 当前字段名不是 `value_type`，则必须在 handle model 上新增统一 property：

```python
@property
def value_type(self) -> str:
    return self.type
```

不要让 executor 猜字段名。

## 7.4 `OperationSpec` 类型升级

```python
from seekflow_engineering_tools.generative_cad.dialects.results import OperationResult

OperationHandler = Callable[
    [CanonicalNode, RuntimeContext],
    OperationResult | dict[str, str],
]
```

添加：

```python
handler_kind: Literal["v1_dict", "v2_result"] = "v1_dict"
```

新 op 必须用 `handler_kind="v2_result"`。已有 built-in dict handlers 暂时允许 v1。

## 7.5 所有 dialect 必须使用 executor

把所有 dialect 的：

```python
outputs = op_spec.handler(node, ctx)
for name, hid in outputs.items():
    ctx.bind_node_output(node.id, name, hid)
```

替换成：

```python
executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
for name, hid in executed.outputs.items():
    final_outputs[name] = hid
```

optional degradation 的 try/except 包住 `execute_operation()`。

## 7.6 测试

```python
def test_executor_rejects_missing_output_name(): ...
def test_executor_rejects_extra_output_name(): ...
def test_executor_rejects_output_type_mismatch(): ...
def test_executor_rejects_missing_handle(): ...
def test_executor_rejects_handle_type_mismatch(): ...
def test_axisymmetric_uses_execute_operation(monkeypatch): ...
def test_sketch_extrude_uses_execute_operation(monkeypatch): ...
def test_composition_uses_execute_operation(monkeypatch): ...
def test_v1_dict_adapter_allowed_for_builtin_ops(): ...
```

---

# 8. Milestone M5：Frozen DialectRegistry 接入 production

## 8.1 当前问题

当前 `dialects/registry.py` 是 global dict + import-time populate。([GitHub][8])

## 8.2 新增 / 修改文件

```text
generative_cad/dialects/registry_core.py
generative_cad/dialects/default_registry.py
generative_cad/dialects/registry.py
generative_cad/validation/*.py
generative_cad/pipeline/metadata*.py
tests/generative_cad/test_vnext_registry_freeze_behavior.py
```

## 8.3 `registry_core.py`

```python
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
                    f"dialect_id {did!r} appears to name a part, not a grammar dialect"
                )
        self._dialects[did] = dialect

    def freeze(self) -> None:
        self._frozen = True

    def require(self, dialect_id: str) -> BaseDialect:
        try:
            return self._dialects[dialect_id]
        except KeyError as exc:
            raise KeyError(f"unknown dialect: {dialect_id!r}") from exc
```

## 8.4 `default_registry.py`

```python
@lru_cache(maxsize=1)
def default_registry() -> DialectRegistry:
    registry = DialectRegistry()
    registry.register(AXISYMMETRIC_DIALECT)
    registry.register(SKETCH_EXTRUDE_DIALECT)
    registry.register(COMPOSITION_DIALECT)
    registry.freeze()
    return registry
```

## 8.5 `registry.py` 变成 wrapper

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

删除：

```text
DIALECT_REGISTRY
populate_registry()
register_dialect()
import-time populate_registry()
```

如果为了兼容必须保留 `register_dialect`，它必须直接 raise：

```python
def register_dialect(...):
    raise RuntimeError("Production registry is frozen; use test-local DialectRegistry")
```

## 8.6 Validation 支持 registry 注入

```python
def validate_and_canonicalize_with_bundle(
    raw: dict | RawGcadDocument,
    *,
    registry: DialectRegistry | None = None,
):
    registry = registry or default_registry()
```

所有 validators 接受 `registry`，不要自己 import global registry。

## 8.7 测试

```python
def test_default_registry_is_frozen(): ...
def test_frozen_registry_rejects_late_registration(): ...
def test_registry_rejects_part_named_dialect(): ...
def test_validation_uses_injected_registry(): ...
def test_no_import_time_populate_registry_side_effect(): ...
```

---

# 9. Milestone M6：MetadataProofV3 接入 production

## 9.1 当前问题

`metadata_v3.py` 已存在，但 production path 仍用 v2 metadata。([GitHub][4])

## 9.2 修改文件

```text
generative_cad/pipeline/run.py
generative_cad/builder.py
generative_cad/pipeline/import_artifact.py
generative_cad/pipeline/metadata_v3.py
generative_cad/tools.py
tests/generative_cad/test_vnext_metadata_v3_behavior.py
```

## 9.3 `run.py` 使用 v3

替换：

```python
from ...pipeline.metadata import build_generative_metadata
```

为：

```python
from ...pipeline.metadata_v3 import build_generative_metadata_v3
```

`run_canonical_gcad` 签名必须带路径：

```python
def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    validation_seed: dict,
    *,
    canonical_ir_path: str | Path,
    validation_seed_path: str | Path,
) -> GcadRunResult:
```

`run_canonical_gcad_from_files()` 传入真实路径。

## 9.4 v3 metadata 必须包含

```text
metadata_version = generative_metadata_v3
source_route = llm_skill_base
schema_version
canonical_version
trust_level
document_id
part_name
selected_dialects with contract_hash
op_versions
raw_graph_hash
canonical_graph_hash
paths.canonical_ir_path
paths.validation_seed_path
paths.step_path
paths.metadata_path
runtime.runner_version
runtime.geometry_runtime
runtime.geometry_runtime_version
artifact.step_sha256
import_policy.native_rebuild_allowed = false
import_policy.requires_import_gate = true
import_policy.step_import_candidate = true
import_policy.step_import_allowed = false
repair_attempts
warnings
degraded_features
operation_metrics
safety
validation
```

这与记忆文档中 metadata 必须记录 provenance、validation stages、safety flags、source_ir_path、step_path，并在缺失或不匹配时 fail 的要求一致。

## 9.5 Builder final validation

builder 最终必须调用：

```python
validate_generative_metadata_v3(
    metadata,
    canonical=canonical,
    registry=default_registry(),
    require_validation_ok=True,
    require_final_artifact_hash=True,
)
```

## 9.6 Import gate 使用 v3

import gate 必须拒绝 v2 metadata，除非显式 compatibility mode。

必须检查：

```text
metadata_version == generative_metadata_v3
source_route == llm_skill_base
trust_level in concept/reference
safety all true
contract_hash matches registry
artifact.step_sha256 matches STEP file
import_policy.native_rebuild_allowed is False
import_policy.requires_import_gate is True
import_policy.step_import_allowed is False
all required validation stages ok
```

## 9.7 测试

```python
def test_run_writes_metadata_v3(): ...
def test_builder_final_validation_uses_v3(): ...
def test_import_gate_rejects_v2_metadata_by_default(): ...
def test_metadata_v3_requires_runtime_version(): ...
def test_metadata_v3_requires_paths(): ...
def test_metadata_v3_step_hash_mismatch_fails(): ...
def test_metadata_v3_contract_hash_mismatch_fails(): ...
def test_metadata_v3_missing_validation_stage_fails_closed(): ...
```

---

# 10. Milestone M7：CanonicalStepArtifact typed model 接入

## 10.1 当前问题

`artifact_models.py` 有 typed model，但 `artifact.py` 返回 hand-written dict 且 `step_import_allowed=True`。([GitHub][5])

## 10.2 修改文件

```text
generative_cad/pipeline/artifact.py
generative_cad/pipeline/artifact_models.py
generative_cad/builder.py
tests/generative_cad/test_vnext_artifact_model_behavior.py
```

## 10.3 目标实现

```python
def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_canonical_step_artifact(
    canonical,
    step_path: str | Path,
    metadata_path: str | Path,
    *,
    graph_path: str | None = None,
    validation_seed_path: str | None = None,
    runner_script_path: str | None = None,
    validation: dict,
    inspection: dict,
) -> dict:
    artifact = CanonicalStepArtifact(
        artifact_type="canonical_step_artifact",
        artifact_schema_version="canonical_step_artifact_v1",
        source_route="llm_skill_base",
        state="validated_reference_step",
        part_name=canonical.part_name,
        document_id=canonical.document_id,
        step_path=str(step_path),
        metadata_path=str(metadata_path),
        graph_path=str(graph_path),
        validation_seed_path=str(validation_seed_path) if validation_seed_path else None,
        runner_script_path=str(runner_script_path) if runner_script_path else None,
        units="mm",
        trust_level=canonical.trust_level,
        schema_version=canonical.schema_version,
        canonical_version=canonical.canonical_version,
        raw_graph_hash=canonical.raw_graph_hash,
        canonical_graph_hash=canonical.canonical_graph_hash,
        selected_dialects=[d.model_dump() for d in canonical.selected_dialects],
        native_rebuild_allowed=False,
        step_import_candidate=True,
        step_import_allowed=False,
        requires_import_gate=True,
        step_sha256=_sha256_file(Path(step_path)),
        metadata_sha256=_sha256_file(Path(metadata_path)) if Path(metadata_path).exists() else None,
        inspection=inspection,
        validation=validation,
    )
    return artifact.model_dump()
```

## 10.4 Builder consistency check

builder 必须检查：

```python
artifact["state"] == "validated_reference_step"
artifact["step_import_allowed"] is False
artifact["native_rebuild_allowed"] is False
artifact["requires_import_gate"] is True
artifact["validation"] == metadata["validation"]
artifact["step_sha256"] == metadata["generative_metadata"]["artifact"]["step_sha256"]
```

## 10.5 测试

```python
def test_artifact_builder_returns_typed_model(): ...
def test_artifact_state_validated_reference_step(): ...
def test_artifact_step_import_allowed_false(): ...
def test_artifact_step_hash_matches_file(): ...
def test_builder_rejects_artifact_metadata_hash_mismatch(): ...
```

---

# 11. Milestone M8：Repair prompt 修正

## 11.1 当前问题

当前 repair prompt 使用 `/nodes//params/` 等无效 path。([GitHub][9])

## 11.2 修改文件

```text
generative_cad/skills/prompts.py
tests/generative_cad/test_gcad_v10_prompt_paths.py
tests/generative_cad/test_vnext_repair_prompt_paths.py
tests/generative_cad/test_vnext_repair_patch_behavior.py
```

## 11.3 替换 prompt

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

最终 repair prompt：

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

## 11.4 测试

```python
def test_repair_prompt_has_no_double_slash_paths(): ...
def test_repair_prompt_uses_node_id_placeholders(): ...
def test_repair_prompt_forbids_safety_modification(): ...
def test_repair_patch_rejects_double_slash_path(): ...
def test_repair_patch_accepts_node_param_path(): ...
def test_repair_patch_rejects_safety_path(): ...
def test_repair_patch_rejects_op_version_path(): ...
```

---

# 12. Milestone M9：Legacy repair barrier

## 12.1 当前问题

`repair_governor.py` 直接 re-export legacy v0.1 repair governor。([GitHub][13])

## 12.2 修改

```python
import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad.repair_governor is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.repair.governor "
        "or seekflow_engineering_tools.generative_cad.repair.patch."
    )
```

## 12.3 测试

```python
def test_legacy_repair_governor_disabled_by_default(): ...
def test_legacy_repair_governor_allowed_with_env_flag(monkeypatch): ...
```

---

# 13. Milestone M10：测试从源码字符串检查升级为行为测试

禁止把 release blocker 只写成：

```python
assert "some string" in inspect.getsource(...)
```

必须用真实行为测试。

必须新增：

```text
test_vnext_raw_parse_behavior.py
test_vnext_runner_proof_behavior.py
test_vnext_geometry_runtime_behavior.py
test_vnext_operation_result_behavior.py
test_vnext_registry_freeze_behavior.py
test_vnext_metadata_v3_behavior.py
test_vnext_artifact_model_behavior.py
test_vnext_import_gate_behavior.py
test_vnext_repair_patch_behavior.py
test_vnext_legacy_barriers.py
```

最低行为测试矩阵：

```text
Raw:
  missing safety fails
  missing constraints fails
  missing safety flag fails
  safety false fails
  constraints false fails

Runner:
  canonical runner without validation_seed fails
  from_files requires validation_seed_json
  validation_seed not mutated

Runtime:
  runner uses GeometryRuntime.export_step
  run.py does not import cadquery for export

Operation:
  output name mismatch fails
  output type mismatch fails
  missing handle fails
  handle type mismatch fails

Registry:
  default registry frozen
  unknown dialect fail
  injected registry works

Metadata:
  v3 required in production
  missing path fails
  missing runtime version fails
  step hash mismatch fails
  contract hash mismatch fails
  missing validation stage fails closed

Artifact:
  state is validated_reference_step
  step_import_allowed false
  native_rebuild_allowed false
  hash matches metadata

Import Gate:
  v2 metadata rejected by default
  v3 metadata required
  step hash mismatch rejected
  missing runtime_postconditions rejected
  success returns native_import_eligible

Repair:
  no /nodes// paths
  params patch allowed
  safety patch rejected
  op_version patch rejected

Primitive isolation:
  primitive compiler unchanged
  geometry_primitives unchanged
  PRIMITIVE_COMPILERS unchanged
```

---

# 14. Claude Code 总实施 Prompt

下面这段可以直接交给 Claude Code：

```text
You are implementing a compiler-grade hardening pass for SeekFlow generative_cad.

Primary goal:
Turn generative_cad into a robust, ABI-stable compiler pipeline:

RawGcadDocument
  -> parse_raw_gcad_document
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
1. Do not modify cadquery_backend/primitive_compiler.py.
2. Do not modify geometry_primitives/.
3. Do not modify CADPartSpec semantics.
4. Do not add generative dialects to primitive registries.
5. LLM Raw JSON must never enter BaseDialect directly.
6. Every dict input must pass parse_raw_gcad_document.
7. RawGcadDocument.safety and constraints must be explicit required fields.
8. No safety or core constraints defaults/default_factory.
9. Core IR envelope is fixed.
10. Op-specific fields are allowed only in node.params.
11. node.params must be validated only by OperationSpec.params_model.
12. Unknown dialect/op/op_version/type/phase/input/output must fail closed.
13. No fuzzy matching.
14. No silent fallback.
15. No dynamic CAD code generation.
16. No generated CadQuery scripts except the fixed runner harness.
17. No SolidWorks COM / NXOpen / APDL code generation.
18. Output remains canonical STEP + metadata proof.
19. Native rebuild is always forbidden.
20. Generative trust_level must never exceed reference_geometry.
21. Multiple dialects compose only through composition dialect.
22. Dialect handlers must not call other dialects directly.
23. Cross-dialect values must be typed runtime handles.
24. Do not hide failing tests by skipping them.
25. Update fixtures to satisfy stricter contracts; do not weaken validation.

Implement in this exact order:

M1 Raw parse:
- Remove safety/constraints defaults from RawGcadDocument.
- Ensure validation pipeline uses parse_raw_gcad_document.
- Ensure builder does not call RawGcadDocument.model_validate on raw dict.
- Add behavior tests.

M2 Runner proof:
- run_canonical_gcad requires validation_seed.
- run_canonical_gcad_from_files requires validation_seed_json.
- builder harness passes validation_seed_json.
- Add behavior tests.

M3 GeometryRuntime:
- Add GeometryRuntime and CadQueryRuntime if missing.
- RuntimeContext owns geometry_runtime object.
- run.py export uses ctx.geometry_runtime.export_step.
- Remove direct cadquery import from run.py export path.
- Add behavior tests.

M4 OperationResult:
- Add RuntimeObjectStore.get_typed.
- Make all dialect.run_component paths call execute_operation.
- Validate output names, output value types, handle existence, handle type.
- Keep v1_dict only as transitional adapter.
- Add behavior tests.

M5 Frozen Registry:
- Replace production global DIALECT_REGISTRY with default_registry wrapper.
- Remove import-time populate_registry side effect.
- Support injected registry in validation.
- Add behavior tests.

M6 MetadataProofV3:
- Make run.py build v3 metadata.
- Make builder final validation use validate_generative_metadata_v3.
- Make import_artifact.py use v3 validator.
- Reject v2 metadata in production import gate by default.
- Add behavior tests.

M7 CanonicalStepArtifact:
- Make artifact.py construct CanonicalStepArtifact model.
- Compute step_sha256 and metadata_sha256.
- Builder verifies artifact/metadata hash consistency.
- Add behavior tests.

M8 Repair prompt:
- Replace /nodes//... and /components//... with valid <node_id>/<component_id> paths.
- Fix contradictory tests.
- Add RepairPatchV2 behavior tests.

M9 Legacy barrier:
- Add production barrier to repair_governor.py.
- Ensure no production import from legacy modules.

Acceptance:
- pytest tests/generative_cad -q
- pytest tests -q
- No production import from legacy namespaces.
- Existing deterministic primitive tests still pass.
```

---

# 15. 分阶段 Claude Code Prompts

## Prompt M1：Raw parse hardening

```text
Implement M1 Raw parse hardening.

Files:
- generative_cad/ir/raw.py
- generative_cad/ir/parse.py
- generative_cad/validation/pipeline.py
- generative_cad/builder.py
- tests/generative_cad/test_vnext_raw_parse_behavior.py

Requirements:
1. RawGcadDocument.safety must be required, no default_factory.
2. RawGcadDocument.constraints must be required, no default_factory.
3. RawSafety flags must be required, no defaults.
4. RawConstraints require_step_file, require_metadata_sidecar, require_closed_solid, expected_body_count must be required.
5. validation pipeline must use parse_raw_gcad_document for dict input.
6. builder must not directly RawGcadDocument.model_validate raw dict.
7. Missing safety fails with path /safety.
8. Missing constraints fails with path /constraints.
9. Missing nested flags fail with exact paths.
10. Do not weaken validation.

Run:
pytest tests/generative_cad/test_vnext_raw_parse_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M2：Runner proof

```text
Implement M2 canonical runner proof.

Files:
- generative_cad/pipeline/run.py
- generative_cad/builder.py
- tests/generative_cad/test_vnext_runner_proof_behavior.py

Requirements:
1. run_canonical_gcad validation_seed is required.
2. run_canonical_gcad_from_files requires validation_seed_json.
3. Builder writes validation seed JSON from ValidationBundle.to_metadata_dict().
4. Harness passes validation_seed_json.
5. validation_seed must be deep-copied before runtime_postconditions insertion.
6. No production canonical runner path may run without proof.

Run:
pytest tests/generative_cad/test_vnext_runner_proof_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M3：GeometryRuntime

```text
Implement M3 GeometryRuntime wiring.

Files:
- generative_cad/runtime/geometry_runtime.py
- generative_cad/runtime/cadquery_runtime.py
- generative_cad/runtime/context.py
- generative_cad/pipeline/run.py
- tests/generative_cad/test_vnext_geometry_runtime_behavior.py

Requirements:
1. RuntimeContext owns geometry_runtime object.
2. Default runtime is CadQueryRuntime.
3. run.py export path calls ctx.geometry_runtime.export_step.
4. run.py must not import cadquery directly for export.
5. metadata records runtime id and runtime version.

Run:
pytest tests/generative_cad/test_vnext_geometry_runtime_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M4：OperationResult

```text
Implement M4 OperationResult production execution.

Files:
- generative_cad/runtime/object_store.py
- generative_cad/dialects/operation.py
- generative_cad/dialects/executor.py
- generative_cad/dialects/axisymmetric/dialect.py
- generative_cad/dialects/sketch_extrude/dialect.py
- generative_cad/dialects/composition/dialect.py
- tests/generative_cad/test_vnext_operation_result_behavior.py

Requirements:
1. Add RuntimeObjectStore.get_typed.
2. execute_operation is the only handler execution path in every dialect.
3. Runtime output names must exactly match CanonicalNode.outputs.
4. Runtime output value_type must match CanonicalNode.outputs.
5. Returned handle must exist.
6. Stored handle value_type must match declared output type.
7. v1_dict remains only as transitional adapter.
8. New ops must use handler_kind="v2_result".

Run:
pytest tests/generative_cad/test_vnext_operation_result_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M5：Frozen registry

```text
Implement M5 Frozen DialectRegistry production wiring.

Files:
- generative_cad/dialects/registry_core.py
- generative_cad/dialects/default_registry.py
- generative_cad/dialects/registry.py
- generative_cad/validation/*.py
- tests/generative_cad/test_vnext_registry_freeze_behavior.py

Requirements:
1. Production registry uses default_registry().
2. default_registry is frozen.
3. Remove import-time populate_registry side effects.
4. registry.py compatibility functions delegate to default_registry.
5. Validation supports injected registry.
6. Duplicate dialect fails.
7. Part-named dialect fails.

Run:
pytest tests/generative_cad/test_vnext_registry_freeze_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M6：MetadataProofV3

```text
Implement M6 MetadataProofV3 production integration.

Files:
- generative_cad/pipeline/run.py
- generative_cad/builder.py
- generative_cad/pipeline/import_artifact.py
- generative_cad/pipeline/metadata_v3.py
- generative_cad/tools.py
- tests/generative_cad/test_vnext_metadata_v3_behavior.py

Requirements:
1. Production run.py writes generative_metadata_v3.
2. Builder final validation uses validate_generative_metadata_v3.
3. Import gate uses validate_generative_metadata_v3.
4. v2.1 is compatibility-only.
5. v3 metadata includes paths, runtime proof, artifact step hash, import policy, safety, validation.
6. step_sha256 must match STEP file.
7. Missing validation stage fails closed.
8. require_validation_ok=True rejects any false stage.

Run:
pytest tests/generative_cad/test_vnext_metadata_v3_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M7：Artifact model

```text
Implement M7 CanonicalStepArtifact model wiring.

Files:
- generative_cad/pipeline/artifact.py
- generative_cad/pipeline/artifact_models.py
- generative_cad/builder.py
- tests/generative_cad/test_vnext_artifact_model_behavior.py

Requirements:
1. build_canonical_step_artifact constructs CanonicalStepArtifact.
2. artifact_schema_version is canonical_step_artifact_v1.
3. state is validated_reference_step.
4. step_import_allowed is false.
5. requires_import_gate is true.
6. native_rebuild_allowed is false.
7. Compute step_sha256.
8. Compute metadata_sha256 when metadata exists.
9. Builder rejects artifact/metadata hash mismatch.

Run:
pytest tests/generative_cad/test_vnext_artifact_model_behavior.py -q
pytest tests/generative_cad -q
```

## Prompt M8：Repair prompt

```text
Implement M8 repair prompt path hardening.

Files:
- generative_cad/skills/prompts.py
- tests/generative_cad/test_gcad_v10_prompt_paths.py
- tests/generative_cad/test_vnext_repair_prompt_paths.py
- tests/generative_cad/test_vnext_repair_patch_behavior.py

Requirements:
1. Remove all /nodes//... and /components//... paths.
2. Use /nodes/<node_id>/params/<field>.
3. Use /components/<component_id>/root_node.
4. Prompt forbids /safety.
5. Prompt forbids /constraints/require_*.
6. Prompt forbids dialect/op/op_version changes.
7. Fix contradictory tests.
8. Add behavior tests for RepairPatchV2.

Run:
pytest tests/generative_cad/test_gcad_v10_prompt_paths.py -q
pytest tests/generative_cad/test_vnext_repair_prompt_paths.py -q
pytest tests/generative_cad/test_vnext_repair_patch_behavior.py -q
pytest tests/generative_cad -q
```

---

# 16. 最终验收标准

全部完成后，必须满足：

```text
Raw:
  missing safety fails
  missing constraints fails
  missing nested safety flag fails
  false safety flag fails
  no defaults for safety/constraints

Runner:
  canonical runner without validation_seed fails
  from_files requires validation_seed_json
  validation_seed not mutated

Runtime:
  RuntimeContext has GeometryRuntime
  run.py does not direct import cadquery for STEP export
  metadata records runtime id/version

Operation:
  every dialect uses execute_operation
  output name mismatch fails
  output type mismatch fails
  missing handle fails
  handle type mismatch fails

Registry:
  default registry frozen
  no import-time populate side effect
  injected registry works

Metadata:
  production metadata_version == generative_metadata_v3
  paths required
  runtime version required
  step hash required
  step hash mismatch fails
  contract hash mismatch fails
  missing validation stage fails closed

Artifact:
  typed CanonicalStepArtifact used
  state == validated_reference_step
  step_import_allowed == false
  native_rebuild_allowed == false
  requires_import_gate == true

Import Gate:
  v2 metadata rejected by default
  v3 metadata required
  import_policy enforced
  step_sha256 verified
  success returns native_import_eligible

Repair:
  no /nodes// paths
  no /components// paths
  params patch allowed
  safety patch rejected
  op_version patch rejected

Legacy:
  repair_governor disabled by default
  no production import from legacy namespaces

Primitive:
  primitive compiler unchanged
  geometry_primitives unchanged
  CADPartSpec unchanged
```

---

# 17. 最终结论

你这条路线是对的，但当前代码仍停在“正确模块已出现，但 production path 未闭环”的状态。真正要做的不是继续新增 v11/v12 壳模块，而是把这几个关键点彻底贯通：

```text
1. Raw parse 成为唯一 dict → RawGcadDocument 入口。
2. Canonical runner 必须强制 validation proof。
3. GeometryRuntime 成为唯一 STEP export 后端。
4. OperationResult 成为唯一 runtime operation ABI。
5. Frozen DialectRegistry 成为 production registry。
6. MetadataProofV3 成为 production metadata。
7. CanonicalStepArtifact model 成为 production artifact。
8. ImportGate 成为 native import eligibility 的唯一权威。
9. Repair prompt 使用真实可执行 path ABI。
10. Legacy 顶层入口默认禁用。
```

这套实现完成后，你的系统才会真正从“text-to-CAD prompt 工程”变成“LLM constrained CAD compiler”。这也是这条路线最有价值、最有壁垒的地方。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/parse.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact_models.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/registry.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/repair_governor.py "raw.githubusercontent.com"
