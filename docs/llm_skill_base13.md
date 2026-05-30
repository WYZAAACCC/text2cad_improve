# SeekFlow Generative CAD-IR vNext 工程落地文档

**面向 Claude Code 的实现规范 / 架构硬化方案 / Prompt 规范 / 测试验收矩阵**

本文档的目标不是“再补几个 if 判断”，而是把 `text_to_cad` / `generative_cad` 做成一个**不脆弱、可演进、低频修改核心编译器、强兼容、强 fail-closed** 的小型 CAD 编译器架构。

我把它定义为：

```text
LLM constrained authoring
  → Raw G-CAD source
  → compiler front-end validation
  → canonical IR
  → dialect-linked executable plan
  → geometry runtime
  → STEP artifact
  → metadata proof
  → import gate
```

核心原则来自你的两份记忆文档：Generative CAD 只能作为独立链路存在，不能污染 Primitive 主链路；LLM 只能输出受控 G-CAD Core IR，不能写 CadQuery / SolidWorks COM / NXOpen / APDL 代码；最终合流点只能是 STEP + metadata。 

---

## 0. 当前代码状态的关键事实

仓库中确实已经有独立的 `generative_cad` 子系统，目录下包含 `dialects`、`ir`、`legacy`、`pipeline`、`repair`、`runtime`、`skills`、`validation` 等模块，没有把 generative path 直接塞进 deterministic primitive path。([GitHub][1])

当前 `RawGcadDocument` 明确声明自己是 LLM 唯一可输出格式，并且 Pydantic model 使用 `extra="forbid"`；但它的 `constraints` 与 `safety` 当前仍通过 `Field(default_factory=...)` 自动补齐，这会把“LLM 没输出 safety / constraints”伪装成“安全字段存在且为 true”。这是编译器级 P0 问题。([GitHub][2])

当前 validation pipeline 已经有 structure、registry、params、ownership、graph、typecheck、phase、composition、safety 等 Raw 阶段，并在 canonicalize 后执行 dialect semantics 与 geometry preflight。这个方向是正确的，应该保留并强化，而不是推倒重写。([GitHub][3])

当前 metadata v2.1 已经有 `REQUIRED_VALIDATION_STAGES`，包括 `core_validation`、`dialect_semantics`、`geometry_preflight`、`runtime_postconditions`、`inspection_validation`，并提供缺失 stage 的 fail-closed normalization。([GitHub][4]) metadata validator 也支持 `require_validation_ok=True`，可以强制所有 validation stage 为 true。([GitHub][4])

当前 runner 已区分 Raw entrypoint 和 canonical entrypoint；Raw entrypoint 会通过 validation bundle 后再运行，canonical entrypoint 目前仍允许不带 validation seed 运行并产生 runner-local metadata，代码注释也说明 builder 会后续重写 metadata。([GitHub][5]) ([GitHub][5])

当前 builder 已经做了 production builder 的关键工作：拒绝 legacy `GenerativeCADSpec v0.1`，通过 `validate_and_canonicalize_with_bundle` 获取完整 stage reports，写 canonical graph，生成固定 runner harness，运行 subprocess，检查 STEP 与 metadata，并最终把完整 validation proof 写回 metadata。([GitHub][6]) ([GitHub][6]) ([GitHub][6])

当前 `OperationSpec` 存在，但 handler 类型仍是 `Callable[..., dict[str, str]]`，过宽，不利于长期稳定 ABI、静态检查和 runtime proof。([GitHub][7]) 当前 runtime 有 `RuntimeContext` 与 `RuntimeObjectStore`，但还没有真正的 `GeometryRuntime` / `CadQueryRuntime` 抽象层；`RuntimeContext` 只是记录 `geometry_runtime_name = "cadquery"`。([GitHub][8]) ([GitHub][9])

当前 prompt 层已经有 Level-1 routing、Level-2 authoring、RepairPatchV2 prompts，并明确禁止 CAD code、路径、subprocess、CadQuery、SolidWorks COM、NXOpen、APDL，方向正确。([GitHub][10])

---

# 1. 目标架构：把 Generative CAD 做成稳定编译器，而不是脚本流水线

## 1.1 架构分层

最终架构必须分成 7 个不可混淆的层：

```text
Layer 0: Prompt / Skill layer
Layer 1: Raw Source Front-End
Layer 2: Core Compiler Validation
Layer 3: Canonical IR / Contract Linking
Layer 4: Dialect Execution
Layer 5: Geometry Runtime
Layer 6: Artifact / Metadata Proof
Layer 7: Native Import Gate
```

每一层只依赖上一层输出，不得反向调用，不得绕过。

---

## 1.2 数据流

```text
User request
  ↓
Level-1 routing prompt
  ↓
DialectSelectionPlan
  ↓
Load selected Dialect Contracts
  ↓
Level-2 authoring prompt
  ↓
RawGcadDocument JSON
  ↓
parse_raw_gcad_document()
  ↓
RawGcadDocument, with explicit required safety/constraints
  ↓
validate_and_canonicalize_with_bundle()
  ↓
CanonicalGcadDocument + ValidationBundle
  ↓
run_canonical_gcad(..., validation_seed=ValidationBundle)
  ↓
DialectRegistry → BaseDialect.run_component()
  ↓
OperationSpec → OperationHandler → OperationResult
  ↓
RuntimeContext + GeometryRuntime
  ↓
STEP file
  ↓
runtime_postconditions
  ↓
STEP inspection
  ↓
GenerativeMetadataProof
  ↓
CanonicalStepArtifact
  ↓
validate_generative_step_artifact_for_native_import()
  ↓
SW/NX import as STEP only
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
Canonical IR without validation proof → importable STEP
Generative CAD → Primitive compiler
Generative CAD → geometry_primitives
Generative CAD → CADPartSpec mutation
```

---

# 2. 设计思想：稳定 ABI，而不是频繁修改核心编译器

要避免“编译器脆弱并且频繁改核心”，必须明确 5 个 ABI。

## 2.1 Core Source ABI

`RawGcadDocument` 是源代码 ABI。它只描述：

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

Core Source ABI 不知道任何具体 op 的业务参数。

禁止为了新增 countersink、slot、rib、shell thickness、draft angle 等参数去改 Core IR。

所有 op-specific 参数必须放在：

```json
"params": {}
```

然后由：

```text
OperationSpec.params_model
```

负责校验。

---

## 2.2 Canonical IR ABI

`CanonicalGcadDocument` 是编译后的 IR ABI。它应该包含：

```text
canonical_version
canonical_graph_hash
raw_graph_hash
selected_dialects with contract_hash
nodes with resolved op_version
nodes with typed_params
nodes with typed inputs/outputs
components with resolved root_node
constraints
safety
```

Canonical IR 不应该再包含 LLM 可自由发挥的字段。

Canonical IR 是唯一允许进入 runner 的 IR。

---

## 2.3 Dialect Contract ABI

每个 dialect 必须输出稳定 contract：

```text
dialect_id
version
phase_order
manifest
operation specs
params JSON schema
input/output types
effects
postconditions
semantic constraints
unsupported cases
```

Contract hash 必须进入 Canonical IR 和 metadata。

新增 op 参数时，只允许改：

```text
dialects/<dialect>/params.py
dialects/<dialect>/ops.py
dialects/<dialect>/runner.py 或 handlers.py
tests
```

不允许改：

```text
ir/raw.py
ir/canonical.py
validation/graph.py
validation/typecheck.py
validation/phase.py
pipeline/run.py
builder.py
```

除非是在新增基础类型、基础 validation stage 或 artifact ABI。

---

## 2.4 Runtime ABI

Dialect handler 不应该直接导出 STEP，也不应该知道 final artifact policy。它只应通过 `RuntimeContext` 和 `GeometryRuntime` 处理对象。

Runtime ABI 需要支持：

```text
store/get typed handles
export_step
inspect_solid
validate_closed_solid
body_count
bbox
runtime name/version
```

CadQuery 只是当前 backend，不是架构本身。

---

## 2.5 Artifact ABI

STEP + metadata 是唯一合流点。

Artifact ABI 必须表达三种状态：

```text
created_unverified
validated_reference_step
native_import_eligible
```

不要把“已经生成 STEP”误认为“允许 SolidWorks/NX import”。

---

# 3. 必须实施的 P0 修复：Raw safety / constraints 显式必填

## 3.1 当前问题

当前代码：

```python
constraints: RawConstraints = Field(default_factory=RawConstraints)
safety: RawSafety = Field(default_factory=RawSafety)
```

这会造成：

```text
LLM 输出缺少 safety
  ↓
Pydantic 默认补出 RawSafety(all true)
  ↓
safety validator 看到 all true
  ↓
错误地通过
```

这违反：

```text
safety missing must fail
constraints missing must fail
```

---

## 3.2 正确设计

`RawGcadDocument` 的 top-level ABI 字段必须显式出现。

建议改为：

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
            raise ValueError("constraints.expected_bbox_mm must be [x, y, z]")
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

关键点：

```text
schema_version 不默认
units 不默认
trust_level 不默认
constraints 不默认
safety 不默认
required safety flags 不默认
required constraint flags 不默认
```

这是编译器前端正确行为：**源代码必须显式声明 ABI、安全边界和约束，不允许 compiler 替 LLM 补安全承诺。**

---

## 3.3 需要新增结构化 parse 层

不要直接让 Pydantic 抛出一团不可控错误。新增：

```text
generative_cad/ir/parse.py
```

接口：

```python
@dataclass(frozen=True)
class RawParseIssue:
    code: str
    message: str
    path: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class RawParseResult:
    ok: bool
    document: RawGcadDocument | None
    issues: list[RawParseIssue]


def parse_raw_gcad_document(data: dict) -> RawParseResult:
    ...
```

它先检查 required keys：

```python
REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "document_id",
    "part_name",
    "units",
    "trust_level",
    "selected_dialects",
    "components",
    "nodes",
    "constraints",
    "safety",
}
```

然后检查 nested safety keys：

```python
REQUIRED_SAFETY_KEYS = {
    "non_flight_reference_only",
    "not_airworthy",
    "not_certified",
    "not_for_manufacturing",
    "not_for_installation",
    "no_structural_validation",
    "no_life_prediction",
}
```

以及 nested constraints keys：

```python
REQUIRED_CONSTRAINT_KEYS = {
    "require_step_file",
    "require_metadata_sidecar",
    "require_closed_solid",
    "expected_body_count",
}
```

错误必须像这样：

```json
{
  "stage": "structure",
  "code": "missing_required_field",
  "message": "RawGcadDocument.safety is required and must be explicit.",
  "path": "/safety",
  "severity": "error"
}
```

---

## 3.4 测试要求

新增：

```text
tests/generative_cad/test_raw_explicit_safety_constraints.py
```

必须覆盖：

```python
def test_missing_safety_fails_structure():
    ...

def test_missing_constraints_fails_structure():
    ...

def test_missing_safety_flag_fails_structure():
    ...

def test_missing_constraint_required_flag_fails_structure():
    ...

def test_safety_false_fails_structure():
    ...

def test_constraint_require_step_false_fails_structure():
    ...

def test_valid_explicit_safety_constraints_passes():
    ...
```

验收标准：

```text
pytest tests/generative_cad/test_raw_explicit_safety_constraints.py -q
```

必须全部通过。

---

# 4. Runner 证明系统：禁止 canonical runner 无 proof 生成 importable artifact

## 4.1 当前问题

当前 Raw entrypoint 会携带 validation bundle 调用 runner，这是对的。([GitHub][5]) 但 canonical entrypoint 仍允许不带 `validation_seed` 执行，只是加 warning。([GitHub][5])

这在 builder 内部可以被 metadata 重写补救，但从编译器安全设计看，仍是一个“proof bypass surface”。

---

## 4.2 正确设计

### 4.2.1 runner 默认必须要求 validation proof

改为：

```python
def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    *,
    validation_seed: dict,
    require_full_validation_seed: bool = True,
) -> GcadRunResult:
    ...
```

`validation_seed` 不允许默认为 `None`。

保留一个私有测试入口：

```python
def _run_canonical_gcad_unverified_for_tests(...):
    ...
```

它必须位于：

```text
generative_cad/pipeline/_test_helpers.py
```

生产代码不得 import。

---

### 4.2.2 builder harness 必须传 validation seed 文件

当前 builder 生成 harness 只传：

```text
canonical_json
out_step
metadata_path
```

应新增：

```text
validation_seed_path
```

builder 写入：

```text
.generative_cad_graphs/gcad_<id>.validation.json
```

内容：

```python
validation_bundle.to_metadata_dict()
```

harness 改成：

```python
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"...",
    validation_seed_json=r"...",
    out_step=r"...",
    metadata_path=r"...",
)
```

runner 文件入口：

```python
def run_canonical_gcad_from_files(
    canonical_json: str | Path,
    validation_seed_json: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    canonical = CanonicalGcadDocument.model_validate(...)
    validation_seed = json.loads(...)
    return run_canonical_gcad(
        canonical,
        out_step=out_step,
        metadata_path=metadata_path,
        validation_seed=validation_seed,
        require_full_validation_seed=True,
    )
```

---

### 4.2.3 validation seed 不可变

继续保持当前 v0.9 的正确方向：runner 内部 deep-copy validation seed，不允许原地修改。([GitHub][5])

要求：

```python
validation = copy.deepcopy(validation_seed)
validation["runtime_postconditions"] = runtime_pc
```

禁止：

```python
validation_seed["runtime_postconditions"] = runtime_pc
```

---

## 4.3 测试要求

新增：

```text
tests/generative_cad/test_runner_requires_validation_proof.py
```

必须覆盖：

```python
def test_run_canonical_without_validation_seed_fails():
    ...

def test_run_canonical_from_files_requires_validation_seed_file():
    ...

def test_builder_harness_passes_validation_seed_file(tmp_path):
    ...

def test_validation_seed_not_mutated_by_runner():
    ...
```

验收标准：

```text
pytest tests/generative_cad/test_runner_requires_validation_proof.py -q
```

---

# 5. GeometryRuntime ABI：把 CadQuery 从 runner 中解耦

## 5.1 当前问题

当前 `RuntimeContext` 记录 `geometry_runtime_name = "cadquery"`，但没有 runtime 对象。([GitHub][8]) `RuntimeObjectStore` 保存 typed handles 与对象，这是正确基础。([GitHub][9]) 但 runner 的 STEP export 仍不应直接 import CadQuery；否则后续 Build123d/OCC runtime、mock runtime、test runtime 都会污染 runner。

---

## 5.2 新增文件

```text
src/seekflow_engineering_tools/generative_cad/runtime/geometry_runtime.py
src/seekflow_engineering_tools/generative_cad/runtime/cadquery_runtime.py
src/seekflow_engineering_tools/generative_cad/runtime/runtime_errors.py
```

---

## 5.3 `GeometryRuntime` Protocol

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from seekflow_engineering_tools.generative_cad.runtime.handles import RuntimeHandle


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

---

## 5.4 `CadQueryRuntime`

```python
class CadQueryRuntime:
    runtime_id = "cadquery"
    runtime_version = "cadquery_runtime_v1"

    def export_step(self, solid_obj: Any, out_step: Path) -> None:
        import cadquery as cq
        cq.exporters.export(solid_obj, str(out_step))

    def inspect_solid(self, solid_obj: Any) -> dict:
        # best-effort object-level inspection
        ...

    def validate_closed_solid(self, solid_obj: Any) -> dict:
        ...

    def compute_bbox_mm(self, solid_obj: Any) -> list[float] | None:
        ...

    def count_bodies(self, solid_obj: Any) -> int | None:
        ...
```

---

## 5.5 RuntimeContext 修改

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
```

---

## 5.6 runner 修改

删除 runner 内部直接 CadQuery export。

从：

```python
def _export_final_solid(handle_id: str, ctx: RuntimeContext) -> None:
    obj = ctx.object_store.get(handle_id)
    import cadquery as cq
    cq.exporters.export(obj, str(ctx.out_step))
```

改为：

```python
def _export_final_solid(handle_id: str, ctx: RuntimeContext) -> None:
    obj = ctx.object_store.get(handle_id)
    ctx.geometry_runtime.export_step(obj, ctx.out_step)
```

---

## 5.7 测试要求

新增：

```text
tests/generative_cad/test_geometry_runtime_abi.py
```

覆盖：

```python
def test_runner_uses_geometry_runtime_export_step(monkeypatch):
    ...

def test_runtime_context_defaults_to_cadquery_runtime():
    ...

def test_mock_geometry_runtime_can_export_without_cadquery_import():
    ...

def test_metadata_records_runtime_id_and_version():
    ...
```

---

# 6. Operation ABI：把 handler 从 `Callable[..., dict]` 升级为强类型 OperationResult

## 6.1 当前问题

当前 `OperationSpec.handler` 是：

```python
OperationHandler = Callable[..., dict[str, str]]
```

过宽。([GitHub][7])

这意味着 handler 可以偷偷返回任意 dict，runner 难以验证：

```text
输出是否匹配 OperationSpec.output_types
是否产生 degraded feature
是否有 warnings
是否满足 postconditions
是否记录 metrics
是否产生了正确 handle type
```

---

## 6.2 新增文件

```text
src/seekflow_engineering_tools/generative_cad/dialects/results.py
```

---

## 6.3 定义强类型结果

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OperationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    handle_id: str
    value_type: str


class OperationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    op: str
    elapsed_ms: float | None = None
    details: dict = Field(default_factory=dict)


class OperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    outputs: list[OperationOutput]
    warnings: list[str] = Field(default_factory=list)
    degraded_features: list[dict] = Field(default_factory=list)
    metrics: list[OperationMetric] = Field(default_factory=list)
    postcondition_results: list[dict] = Field(default_factory=list)
```

---

## 6.4 handler 签名

```python
from typing import Callable

OperationHandler = Callable[
    [CanonicalNode, RuntimeContext, dict[str, str]],
    OperationResult,
]
```

参数说明：

```text
CanonicalNode: 已解析 op_version、typed_params、inputs/outputs 的节点
RuntimeContext: object store + geometry runtime + warnings/metrics
dict[str, str]: input name/output ref → handle_id
OperationResult: 强类型结果
```

---

## 6.5 兼容策略

为了不一次性重构所有 dialect，做一个 adapter：

```python
def adapt_legacy_handler_result(result: dict[str, str], node: CanonicalNode) -> OperationResult:
    return OperationResult(
        ok=True,
        outputs=[
            OperationOutput(name=name, handle_id=handle_id, value_type=_declared_output_type(node, name))
            for name, handle_id in result.items()
        ],
    )
```

`OperationSpec` 可短期支持：

```python
handler_kind: Literal["v1_dict", "v2_result"] = "v2_result"
```

但 production 新 op 必须使用 v2。

---

## 6.6 测试要求

```text
tests/generative_cad/test_operation_result_abi.py
```

覆盖：

```python
def test_v2_handler_result_outputs_match_spec():
    ...

def test_handler_output_name_not_declared_fails():
    ...

def test_handler_output_type_mismatch_fails():
    ...

def test_legacy_handler_adapter_is_allowed_only_for_marked_legacy_ops():
    ...

def test_new_operation_must_use_v2_result_handler():
    ...
```

---

# 7. Registry / Contract Hash：让 dialect 扩展强兼容

## 7.1 目标

新增 dialect / op / params 不应该修改核心编译器。

Registry 必须支持：

```text
显式初始化
幂等注册
contract hash 稳定
多版本 op coexist
测试中 reset
生产中 freeze
```

---

## 7.2 新增 registry 对象

```python
class DialectRegistry:
    def __init__(self) -> None:
        self._dialects: dict[str, BaseDialect] = {}
        self._frozen = False

    def register(self, dialect: BaseDialect) -> None:
        if self._frozen:
            raise RuntimeError("DialectRegistry is frozen")
        if dialect.dialect_id in self._dialects:
            raise ValueError(f"duplicate dialect: {dialect.dialect_id}")
        self._dialects[dialect.dialect_id] = dialect

    def freeze(self) -> None:
        self._frozen = True

    def require(self, dialect_id: str) -> BaseDialect:
        ...

    def contract_hash(self, dialect_id: str) -> str:
        ...
```

默认生产 registry：

```python
def build_default_registry() -> DialectRegistry:
    registry = DialectRegistry()
    registry.register(AxisymmetricDialect())
    registry.register(SketchExtrudeDialect())
    registry.register(CompositionDialect())
    registry.freeze()
    return registry
```

---

## 7.3 contract hash 规则

hash 必须基于 canonical JSON：

```python
def canonical_contract_payload(dialect: BaseDialect) -> dict:
    return {
        "dialect_id": dialect.dialect_id,
        "version": dialect.version,
        "phase_order": list(dialect.phase_order),
        "operations": [
            canonical_operation_spec(spec)
            for spec in sorted(dialect.op_specs().values(), key=lambda s: (s.op, s.op_version))
        ],
    }
```

禁止 hash 直接依赖 Python object repr。

必须：

```text
sort keys
stable list order
exclude handler function object
include params JSON schema
include op_version
include input/output types
include phase
include effects/postconditions
```

---

## 7.4 测试要求

```text
tests/generative_cad/test_dialect_registry_contract_hash.py
```

覆盖：

```python
def test_contract_hash_stable_across_calls():
    ...

def test_contract_hash_changes_when_param_schema_changes():
    ...

def test_contract_hash_ignores_handler_object_identity():
    ...

def test_registry_rejects_duplicate_dialect():
    ...

def test_registry_freeze_rejects_late_registration():
    ...

def test_unknown_dialect_fail_closed():
    ...
```

---

# 8. Artifact 状态机：不要把 STEP created 当成 import allowed

## 8.1 当前问题

builder 最终检查 artifact 的 `step_import_allowed` 必须为 true。([GitHub][6]) 这会导致语义混乱：builder 生成并验证了 reference STEP，不代表它已经通过 native import gate。

---

## 8.2 正确状态机

定义：

```python
ArtifactState = Literal[
    "created_unverified",
    "validated_reference_step",
    "native_import_eligible",
]
```

artifact 字段：

```json
{
  "artifact_type": "canonical_step_artifact",
  "artifact_schema_version": "canonical_step_artifact_v1",
  "source_route": "llm_skill_base",
  "state": "validated_reference_step",
  "native_rebuild_allowed": false,
  "step_import_candidate": true,
  "step_import_allowed": false,
  "requires_import_gate": true
}
```

import gate 成功后返回：

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

解释：

```text
builder 可以证明 artifact 是 validated reference STEP
import gate 才能证明 artifact native import eligible
```

---

## 8.3 builder 修改

builder 不应要求：

```python
artifact["step_import_allowed"] is True
```

而应要求：

```python
artifact["state"] == "validated_reference_step"
artifact["step_import_candidate"] is True
artifact["step_import_allowed"] is False
artifact["native_rebuild_allowed"] is False
artifact["requires_import_gate"] is True
```

---

## 8.4 import gate 修改

import gate 成功路径继续检查全部 true flags，但 success 返回时才设置：

```python
gate["step_import_allowed"] = True
state = "native_import_eligible"
```

---

## 8.5 测试要求

```text
tests/generative_cad/test_artifact_state_machine.py
```

覆盖：

```python
def test_builder_outputs_validated_reference_step_not_import_allowed():
    ...

def test_import_gate_promotes_to_native_import_eligible():
    ...

def test_native_rebuild_is_never_allowed():
    ...

def test_import_gate_success_requires_all_true_flags():
    ...

def test_missing_metadata_never_import_allowed():
    ...
```

---

# 9. Metadata Proof：从 metadata 字段升级为 build proof

## 9.1 目标

metadata 不只是记录信息，而是编译证明。

必须证明：

```text
这个 STEP 来自哪个 Raw IR
Raw IR 被哪个 validation bundle 验证
Canonical IR hash 是什么
Dialect contract hash 是什么
每个 op_version 是什么
哪个 runtime 导出
runtime postconditions 如何
STEP inspection 如何
safety flags 是否全 true
是否经过 repair
是否有 degradation
是否允许 native rebuild
是否需要 import gate
```

---

## 9.2 metadata schema

建议 metadata 顶层：

```json
{
  "generative_metadata": {
    "metadata_version": "generative_metadata_v3",
    "source_route": "llm_skill_base",
    "schema_version": "g_cad_core_v0.2",
    "canonical_version": "canonical_gcad_v0.2",
    "trust_level": "reference_geometry",

    "document_id": "...",
    "part_name": "...",

    "raw_graph_hash": "sha256:...",
    "canonical_graph_hash": "sha256:...",
    "artifact_hash": "sha256:...",

    "selected_dialects": [
      {
        "dialect": "axisymmetric",
        "version": "0.1.0",
        "contract_hash": "sha256:..."
      }
    ],

    "op_versions": [
      {
        "node_id": "n_body",
        "dialect": "axisymmetric",
        "op": "revolve_profile",
        "op_version": "1.0.0"
      }
    ],

    "runner": {
      "runner_version": "gcad_runner_v1",
      "geometry_runtime": "cadquery",
      "geometry_runtime_version": "cadquery_runtime_v1"
    },

    "paths": {
      "canonical_ir_path": "...",
      "step_path": "...",
      "metadata_path": "..."
    },

    "repair": {
      "attempts": 0,
      "patch_hashes": [],
      "stopped_reason": null
    },

    "degraded_features": [],
    "warnings": [],

    "safety": {
      "non_flight_reference_only": true,
      "not_airworthy": true,
      "not_certified": true,
      "not_for_manufacturing": true,
      "not_for_installation": true,
      "no_structural_validation": true,
      "no_life_prediction": true
    },

    "native_rebuild_allowed": false,
    "requires_import_gate": true
  },

  "validation": {
    "core_validation": {...},
    "dialect_semantics": {...},
    "geometry_preflight": {...},
    "runtime_postconditions": {...},
    "inspection_validation": {...}
  },

  "build_warnings": []
}
```

---

## 9.3 Metadata validation policy

`validate_generative_metadata_v3(..., require_validation_ok=True)` 必须检查：

```text
generative_metadata exists
metadata_version is supported
source_route == llm_skill_base
trust_level <= reference_geometry
raw_graph_hash valid
canonical_graph_hash valid
artifact_hash valid if artifact exists
selected_dialects non-empty
every selected dialect has contract_hash
contract_hash matches registry
op_versions count == canonical.nodes count
safety exists
every safety flag explicitly true
native_rebuild_allowed is false
validation exists
all REQUIRED_VALIDATION_STAGES exist
if require_validation_ok: each stage.ok is true
paths do not escape workspace
```

---

# 10. Legacy 隔离：兼容不等于污染 production import graph

## 10.1 当前风险

`generative_cad` 目录同时存在 `legacy`、顶层 wrapper、`bases` 命名目录等，这容易让 Claude Code 或未来开发者 import 错路径。仓库树显示 `generative_cad` 下同时有 `bases`、`legacy`、`dialects` 等目录。([GitHub][1])

---

## 10.2 目标

保留历史兼容，但 production path 不能 import legacy。

规则：

```text
生产 builder 不接受 legacy spec
生产 validator 不接受 legacy graph
生产 prompts 不使用 base_id / selected_bases / feature_graph
legacy adapter 只能在 compatibility 或 legacy tests 中使用
```

当前 builder 已经拒绝 legacy `GenerativeCADSpec v0.1`，这个方向必须保留。([GitHub][6])

---

## 10.3 文件处理

建议：

```text
generative_cad/legacy/
  保留，但只给 legacy tests

generative_cad/compatibility/
  legacy_spec_adapter.py
  只允许显式调用

generative_cad/base.py
generative_cad/ir.py
generative_cad/validation.py
generative_cad/prompts.py
generative_cad/registry.py
generative_cad/runner.py
  若为旧 re-export，改为 deprecation barrier
```

deprecation barrier 示例：

```python
import os

if os.environ.get("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS") != "1":
    raise ImportError(
        "Legacy generative_cad import path is disabled in production. "
        "Use seekflow_engineering_tools.generative_cad.ir.raw, "
        "generative_cad.validation.pipeline, or generative_cad.pipeline.run."
    )
```

---

## 10.4 import-linter 测试

新增：

```text
tests/generative_cad/test_no_production_legacy_imports.py
```

简单实现可以扫描源码：

```python
PRODUCTION_ROOT = Path("src/seekflow_engineering_tools/generative_cad")

FORBIDDEN_IMPORTS = [
    "seekflow_engineering_tools.generative_cad.legacy",
    "seekflow_engineering_tools.generative_cad.bases",
    "from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec",
]
```

但允许：

```text
compatibility/
legacy/
tests/
```

---

# 11. Prompt 架构：Prompt 也必须像 compiler front-end 一样有 ABI

当前 prompts 已经有正确硬约束：routing prompt 禁止 invent dialect/op，禁止 CAD code；authoring prompt 要求输出 RawGcadDocument JSON；repair prompt 只允许局部 patch。([GitHub][10])

但为了配合新的 strict Raw ABI，需要升级 prompt。

---

## 11.1 Level-1 Routing Prompt vNext

用途：

```text
决定 route_decision
选择 dialects
判断 unsupported
不输出 RawGcadDocument
```

高质量 prompt：

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
4. Never invent dialects, operations, operation versions, or parameters.
5. Do not output CAD code, Python, CadQuery, SolidWorks COM, NXOpen, APDL, shell commands, imports, exports, paths, or subprocesses.
6. If more than one independent component must be combined, include the composition dialect.
7. If no registered dialect can express the request, choose unsupported.
8. If the request is better covered by an existing deterministic primitive and the user needs high determinism, choose deterministic_primitive.
9. Do not use deprecated terms: base_id, selected_bases, feature_graph, GenerativeCADSpec.
10. Output JSON only. No markdown. No comments. No prose. No trailing commas.

Required output shape:
{
  "route_decision": "generative_cad_ir | deterministic_primitive | unsupported",
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
  "safety_notes": [
    "..."
  ]
}
```

---

## 11.2 Level-2 Authoring Prompt vNext

用途：

```text
把已选 dialect contract 转成 RawGcadDocument
```

关键升级：

```text
所有 required top-level 字段必须显式输出
所有 safety flags 必须显式 true
所有 required constraints flags 必须显式 true
不允许依赖 schema defaults
```

Prompt：

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
9. Every required top-level field must be explicitly present. Do not rely on defaults.
10. The "constraints" object must be explicitly present.
11. constraints.require_step_file must be explicitly true.
12. constraints.require_metadata_sidecar must be explicitly true.
13. constraints.require_closed_solid must be explicitly true.
14. constraints.expected_body_count must be explicitly present and >= 1.
15. The "safety" object must be explicitly present.
16. Every safety flag must be explicitly true:
    - non_flight_reference_only
    - not_airworthy
    - not_certified
    - not_for_manufacturing
    - not_for_installation
    - no_structural_validation
    - no_life_prediction
17. Use only selected_dialects provided by Level-1.
18. Use only operations listed in the selected dialect contracts.
19. Every node must specify id, component, dialect, op, op_version, phase, inputs, outputs, params, required, and degradation_policy.
20. Every node phase must match its OperationSpec phase.
21. Every node input type must match OperationSpec input_types.
22. Every node output type must match OperationSpec output_types.
23. Every component must specify owner_dialect and root_node.
24. A non-assembly component may only contain nodes from its owner_dialect.
25. Cross-component composition may happen only inside "__assembly__" with owner_dialect "composition".
26. If more than one non-assembly component exists, include "__assembly__".
27. The final root node must output "body" of type "solid".
28. required=true nodes must use degradation_policy="fail".
29. Do not invent dialects, operations, operation versions, phases, output types, or parameters.
30. Do not use deprecated fields: selected_bases, base_id, feature_graph, system_validation_contract, ir_version, GenerativeCADSpec.
31. If the request cannot be expressed with the selected contracts, output:
{
  "unsupported": true,
  "reason": "...",
  "missing_capabilities": [...]
}
instead of inventing fields.
```

---

## 11.3 Repair Prompt vNext

现有 repair prompt 已经禁止修改 `/safety`、`/selected_dialects`、核心 constraints、dialect/op/op_version，并要求 path notation。([GitHub][10]) 保留并强化：

```text
You are a local G-CAD source repair patch author.

You must output RepairPatchV2 JSON only.

Hard rules:
1. Do not rewrite the whole graph.
2. Do not modify /schema_version.
3. Do not modify /selected_dialects.
4. Do not modify /safety.
5. Do not modify /constraints/require_step_file.
6. Do not modify /constraints/require_metadata_sidecar.
7. Do not modify /constraints/require_closed_solid.
8. Do not modify /nodes/<node_id>/dialect.
9. Do not modify /nodes/<node_id>/op.
10. Do not modify /nodes/<node_id>/op_version.
11. Do not modify /components/<component_id>/owner_dialect.
12. Do not invent dialects.
13. Do not invent operations.
14. Do not weaken validation.
15. Prefer only /nodes/<node_id>/params/<field>.
16. Use old_value whenever supplied.
17. If old_value does not match the current document, the patch must not apply.
18. If the same error signature repeated, output:
{
  "give_up": true,
  "reason": "..."
}
19. Output JSON only.
20. No markdown. No prose. No comments. No trailing commas.

Allowed patch paths:
- /nodes/<node_id>/params/<field>
- /nodes/<node_id>/inputs
- /nodes/<node_id>/outputs
- /nodes/<node_id>/required
- /nodes/<node_id>/degradation_policy
- /components/<component_id>/root_node

Only use structural paths when the validation error explicitly requires that exact structural repair.
```

---

# 12. Claude Code 实施总 Prompt

下面这段可以直接交给 Claude Code 作为总任务。

```text
You are implementing a compiler-grade hardening pass for SeekFlow Engineering Tools generative_cad.

Primary goal:
Make the Generative CAD path robust, fail-closed, ABI-stable, and extensible without requiring frequent changes to the core compiler.

Non-negotiable constraints:
1. Do not modify deterministic primitive semantics.
2. Do not modify cadquery_backend/primitive_compiler.py.
3. Do not modify geometry_primitives/.
4. Do not add generative feature types to CADPartSpec or deterministic primitive registries.
5. LLM Raw JSON must never enter BaseDialect directly.
6. All LLM output must pass RawGcadDocument parsing, validation, and canonicalization.
7. Core IR must not know op-specific parameters beyond node.params.
8. Operation-specific parameters must be validated only by OperationSpec.params_model.
9. Unknown dialects, operations, op versions, phases, value types, inputs, outputs, and safety states must fail closed.
10. No fuzzy matching.
11. No silent fallback.
12. No dynamic CAD code generation.
13. No generated CadQuery scripts beyond the fixed runner harness.
14. No SolidWorks COM / NXOpen / APDL code generation.
15. Output artifact remains canonical STEP + metadata only.
16. Native rebuild is always forbidden for generative artifacts.
17. Generative trust_level must never exceed reference_geometry.
18. Production code must not import generative_cad.legacy or generative_cad.bases.

Implement in this order:

Milestone P0:
- Make RawGcadDocument safety and constraints explicit required fields.
- Make all RawSafety flags explicit required booleans.
- Make core RawConstraints flags explicit required booleans.
- Add parse_raw_gcad_document with structured missing-field errors.
- Add tests for missing safety, missing constraints, missing flags, false flags.

Milestone P1:
- Require validation_seed for run_canonical_gcad by default.
- Make builder write validation_seed JSON and pass it to runner harness.
- Ensure validation_seed is deep-copied and never mutated.
- Add tests proving canonical runner cannot run production path without validation proof.

Milestone P2:
- Add GeometryRuntime protocol and CadQueryRuntime implementation.
- Put geometry_runtime object into RuntimeContext.
- Remove direct CadQuery export from pipeline/run.py.
- Add mock runtime test.

Milestone P3:
- Introduce OperationResult ABI.
- Adapt existing dict-return handlers through a legacy adapter only where explicitly marked.
- New operations must use OperationResult.
- Add output name/type matching tests.

Milestone P4:
- Introduce artifact state machine:
  created_unverified → validated_reference_step → native_import_eligible.
- Builder returns validated_reference_step, not step_import_allowed=true.
- Import gate is the only code path that returns native_import_eligible.
- Add state machine tests.

Milestone P5:
- Isolate legacy modules from production imports.
- Add tests scanning production generative_cad code for forbidden legacy imports.

Milestone P6:
- Update Level-1, Level-2, and Repair prompts to require explicit safety and constraints, and to forbid defaults.

Acceptance:
- Run all existing tests.
- Add the new tests described in this task.
- Do not weaken existing validation.
- Do not remove fail-closed behavior.
- Do not hide failing tests by skipping them.
- If a test needs updating because semantics are now stricter, update the fixture to include explicit safety/constraints instead of weakening validation.
```

---

# 13. 文件级落地计划

## 13.1 `ir/raw.py`

改动：

```text
Remove default_factory from RawGcadDocument.constraints.
Remove default_factory from RawGcadDocument.safety.
Remove defaults from RawSafety flags.
Remove defaults from required RawConstraints flags.
Consider removing defaults from schema_version, units, trust_level.
Keep optional engineering hints optional.
```

验收：

```text
dict missing safety → fail
dict missing constraints → fail
dict missing safety.non_flight_reference_only → fail
dict missing constraints.require_step_file → fail
```

---

## 13.2 新增 `ir/parse.py`

职责：

```text
pre-Pydantic missing key detection
path-aware errors
structured issues
Pydantic conversion
```

不要把 parse 层做成 validator 大杂烩。它只处理：

```text
missing field
wrong top-level shape
Pydantic schema exception mapping
```

---

## 13.3 `validation/pipeline.py`

改动：

```text
Use parse_raw_gcad_document for dict input.
If parse fails, return ValidationBundle with structure fail.
Do not call RawGcadDocument.model_validate directly in random places.
```

目标：

```text
all raw parsing has one entrance
```

---

## 13.4 `builder.py`

改动：

```text
Use parse/validation pipeline.
Write validation_seed JSON file.
Harness passes validation_seed_json.
Do not accept legacy spec.
Do not mark artifact step_import_allowed true.
Run final metadata validation require_validation_ok=True.
Return artifact state validated_reference_step.
```

---

## 13.5 `pipeline/run.py`

改动：

```text
run_gcad_core raw path still validates and passes bundle.
run_canonical_gcad requires validation_seed.
run_canonical_gcad_from_files requires validation_seed_json.
No direct CadQuery import.
Use ctx.geometry_runtime.export_step.
```

---

## 13.6 `runtime/geometry_runtime.py`

新增 Protocol。

---

## 13.7 `runtime/cadquery_runtime.py`

新增 CadQuery implementation。

---

## 13.8 `runtime/context.py`

新增：

```python
geometry_runtime: GeometryRuntime = field(default_factory=CadQueryRuntime)
```

并保留：

```python
@property
def geometry_runtime_name(self) -> str:
    return self.geometry_runtime.runtime_id
```

---

## 13.9 `dialects/operation.py`

改动：

```text
OperationHandler becomes strongly typed.
OperationSpec supports handler_kind temporarily.
validate_params unchanged.
```

---

## 13.10 `dialects/results.py`

新增 `OperationResult`、`OperationOutput`、`OperationMetric`。

---

## 13.11 `pipeline/artifact.py`

改动：

```text
artifact_schema_version
state
step_import_candidate
step_import_allowed false by default
requires_import_gate true
```

---

## 13.12 `pipeline/import_artifact.py`

改动：

```text
Only import gate can set native_import_eligible.
Success path returns state native_import_eligible.
Failure path always step_import_allowed false.
```

---

## 13.13 `skills/prompts.py`

升级 Level-1、Level-2、Repair prompts。

特别是 Level-2 必须明确：

```text
Do not rely on defaults.
constraints must be explicit.
safety must be explicit.
```

---

# 14. 测试矩阵

## 14.1 P0 Raw safety / constraints

```text
test_missing_safety_fails_structure
test_missing_constraints_fails_structure
test_missing_safety_flag_fails_structure
test_missing_constraint_flag_fails_structure
test_safety_false_fails_structure
test_constraint_false_fails_structure
test_valid_explicit_safety_constraints_passes
```

---

## 14.2 Core compiler invariants

```text
test_unknown_dialect_fails
test_unknown_op_fails
test_unknown_op_version_fails
test_duplicate_node_id_fails
test_duplicate_component_id_fails
test_missing_input_reference_fails
test_graph_cycle_fails
test_phase_order_fails
test_input_type_mismatch_fails
test_output_type_mismatch_fails
test_component_owner_dialect_enforced
test_cross_component_reference_requires_composition
test_composition_component_must_use_composition_dialect
```

---

## 14.3 Extension stability

```text
test_adding_param_to_op_requires_only_params_model_and_handler
test_core_ir_does_not_change_for_new_op_param
test_core_validator_does_not_change_for_new_op_param
test_contract_hash_changes_for_param_schema_change
test_canonical_records_actual_op_version
test_metadata_records_actual_op_version
```

---

## 14.4 Runner proof

```text
test_run_canonical_without_validation_seed_fails
test_run_canonical_from_files_without_seed_fails
test_builder_harness_passes_validation_seed
test_validation_seed_not_mutated
test_runner_metadata_contains_runtime_postconditions
```

---

## 14.5 Geometry runtime

```text
test_runner_uses_geometry_runtime_export_step
test_mock_runtime_can_export
test_cadquery_runtime_records_runtime_id
test_metadata_records_runtime_id
test_runtime_postconditions_use_runtime_api
```

---

## 14.6 Metadata / artifact

```text
test_metadata_missing_validation_stage_fails_when_require_validation_ok
test_metadata_partial_validation_normalizes_fail_closed
test_metadata_contract_hash_mismatch_fails
test_metadata_safety_missing_fails
test_metadata_safety_false_fails
test_artifact_validation_equals_metadata_validation
test_artifact_hash_matches_metadata
test_builder_outputs_validated_reference_step
test_import_gate_promotes_to_native_import_eligible
test_import_gate_missing_metadata_fails
test_import_gate_success_requires_all_true_flags
```

---

## 14.7 Legacy isolation

```text
test_production_builder_rejects_legacy_spec
test_no_production_imports_from_legacy
test_no_production_imports_from_bases
test_deprecated_top_level_imports_raise_without_env_flag
```

---

## 14.8 Prompt tests

```text
test_level2_prompt_requires_explicit_safety
test_level2_prompt_requires_explicit_constraints
test_level2_prompt_forbids_defaults
test_level2_prompt_forbids_code_paths_subprocess
test_repair_prompt_forbids_safety_modification
test_repair_prompt_uses_path_notation
test_routing_prompt_forbids_unregistered_dialects
```

---

# 15. 编译器错误模型

统一错误结构：

```json
{
  "stage": "typecheck",
  "code": "input_type_mismatch",
  "message": "Node n_holes input 0 expected solid but got frame.",
  "path": "/nodes/n_holes/inputs/0",
  "node_id": "n_holes",
  "component_id": "main_disk",
  "severity": "error"
}
```

错误规范：

```text
stage: 必须是固定枚举
code: snake_case，稳定，测试依赖 code
message: 给人读
path: 给 repair loop 用
node_id/component_id: 能有则有
severity: error/warning
```

稳定 stage 枚举：

```text
parse
structure
registry
params
ownership
graph
typecheck
phase
composition
safety
canonicalize
dialect_semantics
geometry_preflight
runtime
runtime_postconditions
step_export
inspection_validation
metadata_validation
artifact_validation
import_gate
```

不要随意改 error code。error code 是 repair loop ABI。

---

# 16. Repair Loop Governor

## 16.1 状态记录

每次 repair attempt 记录：

```json
{
  "attempt": 1,
  "input_raw_hash": "sha256:...",
  "input_canonical_hash": null,
  "error_signature": "sha256:...",
  "patch_hash": "sha256:...",
  "stage_before": "geometry_preflight",
  "stage_after": "geometry_preflight",
  "advanced": false,
  "result": "rejected_repeated_error"
}
```

---

## 16.2 停止条件

必须停止：

```text
attempts >= max_attempts
same raw graph hash repeated
same canonical graph hash repeated
same error_signature repeated
validation stage did not advance twice
patch tries to modify forbidden path
patch old_value mismatch
patch introduces unknown dialect/op/version
patch modifies safety
patch weakens constraints
```

---

## 16.3 Patch apply policy

允许：

```text
/nodes/<node_id>/params/<field>
```

谨慎允许：

```text
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/nodes/<node_id>/required
/nodes/<node_id>/degradation_policy
/components/<component_id>/root_node
```

禁止：

```text
/schema_version
/selected_dialects
/safety
/constraints/require_step_file
/constraints/require_metadata_sidecar
/constraints/require_closed_solid
/nodes/<id>/dialect
/nodes/<id>/op
/nodes/<id>/op_version
/components/<id>/owner_dialect
```

---

# 17. 兼容策略

## 17.1 兼容不是默认放松

兼容规则：

```text
Production accepts only strict RawGcadDocument.
Legacy adapter exists only under compatibility/.
Legacy adapter must be explicit.
Legacy adapter must add audit warning.
Legacy adapter output must still pass strict RawGcadDocument.
```

---

## 17.2 旧 fixture 迁移

如果旧测试 fixture 没有 safety / constraints：

```text
不要恢复默认值
不要放宽 RawGcadDocument
不要跳过测试
应该更新 fixture，显式加入 safety / constraints
```

---

## 17.3 schema version 策略

短期：

```text
仍使用 g_cad_core_v0.2
但收紧为 explicit safety/constraints
```

原因：

```text
记忆文档和 prompts 已经要求 safety/constraints 显式存在
这是 validation tightening，不是 IR shape breaking
```

长期如果新增 top-level 字段：

```text
g_cad_core_v0.3
```

---

# 18. Claude Code 分阶段执行 Prompt

## 18.1 P0 Prompt：Raw explicit safety/constraints

```text
Implement P0 strict RawGcadDocument safety/constraints hardening.

Files likely affected:
- src/seekflow_engineering_tools/generative_cad/ir/raw.py
- src/seekflow_engineering_tools/generative_cad/ir/parse.py
- src/seekflow_engineering_tools/generative_cad/validation/pipeline.py
- tests/generative_cad/test_raw_explicit_safety_constraints.py
- existing fixtures that omit safety/constraints

Rules:
1. Do not modify primitive compiler or geometry_primitives.
2. Do not restore default safety or default constraints.
3. Missing safety must fail.
4. Missing constraints must fail.
5. Missing individual safety flags must fail.
6. Missing core constraint flags must fail.
7. False safety or false core constraints must fail.
8. Valid explicit safety/constraints must pass.
9. Error paths must be usable by repair loop, e.g. /safety/not_airworthy.
10. Update tests by making fixtures explicit, not by weakening validation.

Run:
pytest tests/generative_cad/test_raw_explicit_safety_constraints.py -q
pytest tests/generative_cad -q
```

---

## 18.2 P1 Prompt：Runner validation proof

```text
Implement P1 validation proof requirement for canonical runner.

Files likely affected:
- src/seekflow_engineering_tools/generative_cad/pipeline/run.py
- src/seekflow_engineering_tools/generative_cad/builder.py
- tests/generative_cad/test_runner_requires_validation_proof.py

Rules:
1. run_canonical_gcad must require validation_seed by default.
2. run_canonical_gcad_from_files must require validation_seed_json.
3. build_generative_cad_model must write ValidationBundle.to_metadata_dict() to a validation seed JSON file.
4. The generated fixed harness must pass validation_seed_json.
5. validation_seed must be deep-copied before adding runtime_postconditions.
6. No production path may generate STEP from canonical IR without validation proof.
7. Test-only unverified runner, if needed, must live in a test helper and be clearly private.

Run:
pytest tests/generative_cad/test_runner_requires_validation_proof.py -q
pytest tests/generative_cad -q
```

---

## 18.3 P2 Prompt：GeometryRuntime

```text
Implement P2 GeometryRuntime abstraction.

Files likely affected:
- src/seekflow_engineering_tools/generative_cad/runtime/geometry_runtime.py
- src/seekflow_engineering_tools/generative_cad/runtime/cadquery_runtime.py
- src/seekflow_engineering_tools/generative_cad/runtime/context.py
- src/seekflow_engineering_tools/generative_cad/pipeline/run.py
- tests/generative_cad/test_geometry_runtime_abi.py

Rules:
1. pipeline/run.py must not directly import cadquery for STEP export.
2. RuntimeContext must own a geometry_runtime object.
3. Default runtime is CadQueryRuntime.
4. STEP export must call ctx.geometry_runtime.export_step.
5. Metadata must record runtime id/version.
6. Mock runtime must be usable in tests.

Run:
pytest tests/generative_cad/test_geometry_runtime_abi.py -q
pytest tests/generative_cad -q
```

---

## 18.4 P3 Prompt：OperationResult ABI

```text
Implement P3 OperationResult ABI.

Files likely affected:
- src/seekflow_engineering_tools/generative_cad/dialects/operation.py
- src/seekflow_engineering_tools/generative_cad/dialects/results.py
- dialect handler files
- tests/generative_cad/test_operation_result_abi.py

Rules:
1. Define OperationResult, OperationOutput, OperationMetric.
2. New handlers must return OperationResult.
3. Legacy dict-return handlers may only be adapted when explicitly marked.
4. Runner/dialect execution must validate result outputs against OperationSpec.
5. Unknown output names fail.
6. Output type mismatch fails.
7. Operation warnings/degraded_features/metrics must flow into RuntimeContext.

Run:
pytest tests/generative_cad/test_operation_result_abi.py -q
pytest tests/generative_cad -q
```

---

## 18.5 P4 Prompt：Artifact state machine

```text
Implement P4 artifact state machine.

Files likely affected:
- src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py
- src/seekflow_engineering_tools/generative_cad/pipeline/import_artifact.py
- src/seekflow_engineering_tools/generative_cad/builder.py
- tests/generative_cad/test_artifact_state_machine.py

Rules:
1. Builder artifact state must be validated_reference_step after validation passes.
2. Builder artifact step_import_allowed must be false.
3. Builder artifact step_import_candidate must be true.
4. Builder artifact requires_import_gate must be true.
5. Import gate is the only code that may return native_import_eligible.
6. Native rebuild remains false forever.
7. Import gate success requires every required gate flag true.

Run:
pytest tests/generative_cad/test_artifact_state_machine.py -q
pytest tests/generative_cad -q
```

---

## 18.6 P5 Prompt：Legacy isolation

```text
Implement P5 production legacy isolation.

Files likely affected:
- src/seekflow_engineering_tools/generative_cad/base.py
- src/seekflow_engineering_tools/generative_cad/ir.py
- src/seekflow_engineering_tools/generative_cad/validation.py
- src/seekflow_engineering_tools/generative_cad/prompts.py
- src/seekflow_engineering_tools/generative_cad/registry.py
- src/seekflow_engineering_tools/generative_cad/runner.py
- tests/generative_cad/test_no_production_legacy_imports.py

Rules:
1. Production generative_cad code must not import generative_cad.legacy.
2. Production generative_cad code must not import generative_cad.bases.
3. Legacy imports may be enabled only through SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1.
4. Builder must continue rejecting legacy GenerativeCADSpec v0.1.
5. Do not remove legacy tests; isolate them.

Run:
pytest tests/generative_cad/test_no_production_legacy_imports.py -q
pytest tests/generative_cad -q
```

---

# 19. 最终验收标准

完整实现后必须满足：

```text
1. Missing safety fails.
2. Missing constraints fails.
3. Unknown dialect/op/op_version fails.
4. Cross-component non-composition reference fails.
5. New op parameter requires no core compiler change.
6. Canonical runner cannot produce production artifact without validation proof.
7. Runner uses GeometryRuntime, not direct CadQuery export.
8. Metadata validation requires all validation stages true before import.
9. Builder artifact is validated_reference_step, not native_import_eligible.
10. Import gate alone promotes to native_import_eligible.
11. Native rebuild is always forbidden.
12. Production code has no legacy imports.
13. Prompts require explicit safety/constraints.
14. Repair cannot modify safety or weaken constraints.
15. Existing primitive path remains untouched.
```

推荐最终命令：

```bash
pytest tests/generative_cad -q
pytest tests -q
```

可选静态扫描：

```bash
python -m compileall integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad
```

---

# 20. 总结：真正正确的顶级架构

最终应收敛为：

```text
Primitive path:
  deterministic CADPartSpec / Primitive
  stable kernel
  high determinism

Generative path:
  LLM writes Raw G-CAD source only
  compiler front-end parses explicit safety/constraints
  validator links dialect contract and op specs
  canonical IR freezes op_version and contract_hash
  dialect handlers return typed OperationResult
  runtime stores typed handles
  GeometryRuntime exports STEP
  metadata stores proof
  artifact state machine prevents premature native import
  import gate is the only native import authority
```

这套架构的本质是：

```text
Core compiler 稳定；
Dialect 可扩展；
Operation 参数可演进；
Runtime 可替换；
Prompt 与 Contract 同步；
Repair 受治理；
Artifact 有证明；
Import 有门禁；
Primitive 主链路不受污染。
```

最关键的 P0 是：

```text
不要让 schema default 替 LLM 补 safety/constraints。
```

最关键的 P1 是：

```text
不要让 canonical runner 无 validation proof 生成可被误用的 artifact。
```

最关键的长期架构点是：

```text
新增能力应该扩展 dialect contract / params_model / handler / tests，
而不是修改 Core IR、Core Validator、Builder 或 Primitive Compiler。
```

这才是一个健康、强壮、兼容性强、符合编译器内核标准的 text-to-CAD Generative CAD 架构。

[1]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad at main · WYZAAACCC/seekflow-engineering · GitHub"
[2]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py "raw.githubusercontent.com"
[4]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[5]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[6]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[7]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[8]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[9]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/object_store.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/object_store.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[10]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/prompts.py at main · WYZAAACCC/seekflow-engineering · GitHub"
