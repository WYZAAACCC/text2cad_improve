

---

# SeekFlow Generative CAD Compiler 架构重构工程文档

## 0. 最终结论

当前仓库已经有 `generative_cad` 包，但它还不是传统编译器级架构。当前实现更接近：

```text
GenerativeCADSpec
→ feature_graph.nodes
→ 单 base runner
→ CadQuery
→ STEP + metadata
```

真正应该升级为：

```text
RawGcadDocument
→ Core IR structure validation
→ registry resolution
→ operation params validation
→ typed graph validation
→ phase/order validation
→ CanonicalGcadDocument
→ component partition
→ BaseDialect lowering
→ CompositionDialect lowering
→ GeometryRuntime
→ STEP + generative metadata
→ CanonicalStepArtifact
→ existing inspection / validation
```

这个方向与已收敛文档一致：新链路不应是 `LLM → base → CadQuery`，而应是 `LLM → 固定 G-CAD Core IR → dialect validation → typed graph → dialect runners → composition → Geometry Runtime → STEP + metadata`。

当前代码的主要差距是：

1. `ir.py` 仍是 `FeatureGraphNode(base_id, op, phase, params, depends_on)`，没有 `components / inputs / outputs / op_version / canonical IR`。([GitHub][1])
2. `base.py` 的 `OperationDefinition` 只有 `op / phase / params_model / description`，缺少 `op_version / input_types / output_types / effects / postconditions / handler`。([GitHub][2])
3. `runner.py` 明确是 v0 单 base graph，会拒绝混合 base graph。([GitHub][3])
4. `builder.py` 生成的 harness 会打印 `result.metadata_path`，但 `GenerativeRunResult` 没有这个字段，这是实际成功路径 bug。([GitHub][3])
5. `axisymmetric` 和 `sketch_extrude` runner 内部仍是大 `if/elif` 修改同一个局部 `body`，还没有 typed value / object store / component result。([GitHub][4])
6. `graph_validation.py` 已经有 base/op/params/DAG/phase/semantic validation 雏形，但还没有真正 typecheck、component ownership、canonicalization、op version、cross-dialect 规则。([GitHub][5])
7. `metadata.py` 已经有 sidecar validator，但还不够强，缺 canonical graph hash、op versions、runtime version、contract hash 一致性等 provenance 校验。([GitHub][6])

因此，本次重构目标不是“修补当前 feature graph”，而是把它升级为**真正的 G-CAD compiler pipeline**。

---

# 1. 编译器级设计原则

## 1.1 借鉴原则

MLIR 的 dialect 用于扩展 attributes、operations、types，并支持多抽象层编译；LLVM IR 是 SSA-based、type-safe，并作为编译策略各阶段的通用表示。SeekFlow 不需要完整复制 MLIR/LLVM，但必须吸收三个原则：**固定 Core IR、可扩展 Dialect、分阶段 lowering**。([MLIR][7])

CadQuery 可以作为 v0 的几何 runtime，因为它是 Python 参数化 CAD 库，并支持输出 STEP 等高质量 CAD 格式。([cadquery.readthedocs.io][8])

## 1.2 本系统的核心定义

```text
Primitive
  = 确定性工程零件内核。
  = 拓扑固定、参数明确、可强校验。
  = 继续留在现有 primitive path。

BaseDialect
  = CAD grammar dialect。
  = 描述一种建模范式，不描述某个零件。
  = 例如 axisymmetric、sketch_extrude、composition。

OperationSpec
  = 某个 dialect 下的一个可验证 operation。
  = 包含 op_version、输入类型、输出类型、参数 schema、effects、handler。

G-CAD Core IR
  = LLM 输出与 dialect runner 之间唯一合法边界。
  = raw dict 不能进入 runner。
  = 只有 CanonicalGcadDocument 可以进入 runner。

GeometryRuntime
  = 对 CadQuery / future OCC / build123d 的隔离层。
  = dialect handler 不应散落调用复杂 CadQuery API。

RuntimeValue / Handle
  = 跨 dialect 的唯一数据交换形式。
  = base 之间不共享内部 CadQuery object。
```

## 1.3 绝对禁止事项

Claude Code 必须遵守：

```text
1. 不修改现有 deterministic primitive path 语义。
2. 不把 generative base 加进 PRIMITIVE_COMPILERS。
3. 不让 LLM raw JSON 进入任何 base runner。
4. 不让 base 之间直接调用。
5. 不允许 composition dialect 解释 sketch/profile 或创建复杂几何。
6. 不动态生成大型 CadQuery 脚本。
7. 不把新增参数写进 core validator。
8. 不使用 fuzzy matching 纠正未知 op/dialect。
9. 不 silent fallback。
10. 不允许 generative trust_level 超过 reference_geometry。
11. 不声明 manufacturing-ready / certified / airworthy / installable。
12. 不破坏现有 CADPartSpec / primitive / cadquery_backend 主链路。
```

这与已有架构记忆中的硬约束一致：LLM raw JSON 必须经过 `RawGcadDocument -> CanonicalGcadDocument`，base-specific 字段只能放进 `node.params`，多 base 只能通过 composition dialect 组合，输出必须是 canonical STEP artifact + metadata。

---

# 2. 当前代码应如何演进

## 2.1 不建议直接删除现有 generative_cad

当前代码有可用资产：

```text
generative_cad/ir.py
generative_cad/base.py
generative_cad/registry.py
generative_cad/graph_validation.py
generative_cad/preflight.py
generative_cad/runner.py
generative_cad/builder.py
generative_cad/metadata.py
generative_cad/validation.py
generative_cad/artifact.py
generative_cad/tools.py
generative_cad/bases/axisymmetric/*
generative_cad/bases/sketch_extrude/*
```

应采用**兼容式重构**：

```text
保留外部 tool 名称：
  generative_cad_list_bases
  generative_cad_get_base_contract
  generative_cad_validate_ir
  generative_cad_build_from_ir

内部升级为：
  RawGcadDocument
  CanonicalGcadDocument
  DialectRegistry
  OperationSpec
  RuntimeObjectStore
  CompositionDialect
```

## 2.2 迁移策略

### 阶段 A：先修 bug + 建新 core，不大破坏

1. 修复 `GenerativeRunResult.metadata_path` bug。
2. 新增 `generative_cad/core/*` 或直接按下面目录重组。
3. 保留旧 `GenerativeCADSpec` 作为 compatibility model。
4. 新 builder 优先接受 `RawGcadDocument`；旧 spec 可以通过 adapter 转换为单 component canonical graph。

### 阶段 B：axisymmetric / sketch_extrude 迁移到 BaseDialect

1. 保留原 params models。
2. 原 `_op_*` 函数迁移为 operation handler。
3. 不再由 runner `if/elif` dispatch。
4. 改为 `OperationSpec.handler(ctx, node, inputs, typed_params)`。

### 阶段 C：实现 composition dialect

1. 支持跨 component 的 placement / pattern / boolean。
2. 支持 `solid` / `solid_array` / `frame` typed values。
3. 生成 final solid handle。

### 阶段 D：metadata / artifact / tests 强化

1. 写 canonical graph hash。
2. 写 op version list。
3. 写 contract hash。
4. 写 runtime version。
5. 返回 CanonicalStepArtifact。

---

# 3. 推荐最终目录结构

在现有 `src/seekflow_engineering_tools/generative_cad/` 下重构为：

```text
generative_cad/
  __init__.py

  ir/
    __init__.py
    raw.py
    canonical.py
    values.py
    safety.py
    errors.py
    hashing.py

  dialects/
    __init__.py
    base.py
    registry.py
    operation.py

    axisymmetric/
      __init__.py
      dialect.py
      params.py
      handlers.py
      preflight.py
      contract.py
      manifest.py

    sketch_extrude/
      __init__.py
      dialect.py
      params.py
      handlers.py
      preflight.py
      contract.py
      manifest.py

    composition/
      __init__.py
      dialect.py
      params.py
      handlers.py
      contract.py
      manifest.py

  validation/
    __init__.py
    pipeline.py
    structure.py
    registry.py
    params.py
    graph.py
    typecheck.py
    phase.py
    ownership.py
    safety.py
    canonicalize.py
    reports.py

  runtime/
    __init__.py
    context.py
    handles.py
    object_store.py
    geometry_runtime.py
    cadquery_runtime.py
    results.py

  pipeline/
    __init__.py
    build.py
    run.py
    metadata.py
    artifact.py
    repair.py

  compatibility/
    __init__.py
    legacy_spec_adapter.py

  tools.py
```

不要放进：

```text
cadquery_backend/primitive_compiler.py
geometry_primitives/
ir/cad.py
```

如果必须兼容旧 `generative_cad/*.py` 文件，可以让旧文件 re-export 新实现。例如：

```python
# generative_cad/runner.py
from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core_from_files
```

---

# 4. G-CAD Core IR 最终规格

## 4.1 RawGcadDocument

文件：`generative_cad/ir/raw.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

LengthUnit = Literal["mm"]
TrustLevel = Literal["concept_geometry", "reference_geometry"]
DegradationPolicy = Literal["fail", "may_skip_with_warning"]

class RawSelectedDialect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dialect: str
    version: str

class RawComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    owner_dialect: str
    kind_hint: str | None = None
    root_node: str | None = None

class RawValueRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: str | None = None
    component: str | None = None
    output: str

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.node) == bool(self.component):
            raise ValueError("ValueRef must specify exactly one of node or component")
        return self

class RawValueDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str

class RawNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    component: str
    dialect: str
    op: str
    op_version: str | None = None
    phase: str
    inputs: list[RawValueRef] = Field(default_factory=list)
    outputs: list[RawValueDecl] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    degradation_policy: DegradationPolicy = "fail"

    @model_validator(mode="after")
    def validate_required_policy(self):
        if self.required and self.degradation_policy != "fail":
            raise ValueError("required nodes must use degradation_policy='fail'")
        return self

class RawConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_step_file: bool = True
    require_metadata_sidecar: bool = True
    require_closed_solid: bool = True
    expected_body_count: int = Field(default=1, ge=1)
    expected_bbox_mm: list[float] | None = None
    bbox_tolerance_mm: float = Field(default=1.0, gt=0)
    max_runtime_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def fail_closed_flags(self):
        if not self.require_step_file:
            raise ValueError("require_step_file cannot be false")
        if not self.require_metadata_sidecar:
            raise ValueError("require_metadata_sidecar cannot be false")
        if not self.require_closed_solid:
            raise ValueError("require_closed_solid cannot be false")
        if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
            raise ValueError("expected_bbox_mm must be [x, y, z]")
        return self

class RawSafety(BaseModel):
    model_config = ConfigDict(extra="forbid")
    non_flight_reference_only: bool = True
    not_airworthy: bool = True
    not_certified: bool = True
    not_for_manufacturing: bool = True
    not_for_installation: bool = True
    no_structural_validation: bool = True
    no_life_prediction: bool = True

    @model_validator(mode="after")
    def all_true(self):
        for key, value in self.model_dump().items():
            if value is not True:
                raise ValueError(f"safety flag {key} must be true")
        return self

class RawGcadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["g_cad_core_v0.2"] = "g_cad_core_v0.2"
    document_id: str
    part_name: str
    units: LengthUnit = "mm"
    trust_level: TrustLevel = "reference_geometry"

    selected_dialects: list[RawSelectedDialect]
    components: list[RawComponent]
    nodes: list[RawNode]

    constraints: RawConstraints = Field(default_factory=RawConstraints)
    safety: RawSafety = Field(default_factory=RawSafety)

    llm_validation_hints: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_basic(self):
        if not self.document_id.strip():
            raise ValueError("document_id must be non-empty")
        if not self.part_name.strip():
            raise ValueError("part_name must be non-empty")
        if not self.selected_dialects:
            raise ValueError("selected_dialects must not be empty")
        if not self.components:
            raise ValueError("components must not be empty")
        if not self.nodes:
            raise ValueError("nodes must not be empty")
        return self
```

## 4.2 CanonicalGcadDocument

文件：`generative_cad/ir/canonical.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.ir.raw import RawConstraints, RawSafety

ValueType = Literal[
    "solid",
    "solid_array",
    "frame",
    "plane",
    "point",
    "curve",
    "profile",
    "face_set",
    "edge_set",
    "component_ref",
]

class CanonicalSelectedDialect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dialect: str
    version: str
    contract_hash: str

class CanonicalComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    owner_dialect: str
    kind_hint: str | None = None
    root_node: str
    output_aliases: dict[str, str] = Field(default_factory=dict)

class CanonicalValueRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producer_node: str | None = None
    producer_component: str | None = None
    output: str
    resolved_type: ValueType

class CanonicalValueDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: ValueType
    value_id: str

class CanonicalNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    component: str
    dialect: str
    op: str
    op_version: str
    phase: str

    inputs: list[CanonicalValueRef] = Field(default_factory=list)
    outputs: list[CanonicalValueDecl] = Field(default_factory=list)

    params: dict[str, Any] = Field(default_factory=dict)
    typed_params: Any

    required: bool = True
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"

    operation_effects: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)

class CanonicalGcadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["g_cad_core_v0.2"] = "g_cad_core_v0.2"
    canonical_version: Literal["canonical_gcad_v0.2"] = "canonical_gcad_v0.2"

    document_id: str
    part_name: str
    units: Literal["mm"] = "mm"
    trust_level: Literal["concept_geometry", "reference_geometry"] = "reference_geometry"

    selected_dialects: list[CanonicalSelectedDialect]
    components: list[CanonicalComponent]
    nodes: list[CanonicalNode]

    constraints: RawConstraints
    safety: RawSafety

    canonical_graph_hash: str
    raw_graph_hash: str | None = None
```

---

# 5. Runtime Type System

## 5.1 Handles

文件：`generative_cad/runtime/handles.py`

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class RuntimeHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    component_id: str | None = None
    producer_node: str | None = None

class SolidHandle(RuntimeHandle):
    type: Literal["solid"] = "solid"
    bbox_mm: tuple[float, float, float] | None = None
    volume_mm3: float | None = None

class SolidArrayHandle(RuntimeHandle):
    type: Literal["solid_array"] = "solid_array"
    solid_ids: list[str] = Field(default_factory=list)

class FrameHandle(RuntimeHandle):
    type: Literal["frame"] = "frame"
    origin_mm: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    z_axis: tuple[float, float, float]

class PlaneHandle(RuntimeHandle):
    type: Literal["plane"] = "plane"
    origin_mm: tuple[float, float, float]
    normal: tuple[float, float, float]

class PointHandle(RuntimeHandle):
    type: Literal["point"] = "point"
    xyz_mm: tuple[float, float, float]

class CurveHandle(RuntimeHandle):
    type: Literal["curve"] = "curve"

class ProfileHandle(RuntimeHandle):
    type: Literal["profile"] = "profile"

RuntimeValue = (
    SolidHandle
    | SolidArrayHandle
    | FrameHandle
    | PlaneHandle
    | PointHandle
    | CurveHandle
    | ProfileHandle
)
```

## 5.2 ObjectStore

文件：`generative_cad/runtime/object_store.py`

```python
from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.handles import (
    RuntimeHandle,
    SolidHandle,
    SolidArrayHandle,
    FrameHandle,
)

class RuntimeObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self._handles: dict[str, RuntimeHandle] = {}

    def put(self, handle: RuntimeHandle, obj: Any) -> RuntimeHandle:
        if handle.id in self._objects:
            raise ValueError(f"duplicate runtime handle id: {handle.id}")
        self._handles[handle.id] = handle
        self._objects[handle.id] = obj
        return handle

    def get(self, handle_or_id: RuntimeHandle | str) -> Any:
        hid = handle_or_id.id if isinstance(handle_or_id, RuntimeHandle) else handle_or_id
        if hid not in self._objects:
            raise KeyError(f"runtime object not found: {hid}")
        return self._objects[hid]

    def get_handle(self, handle_id: str) -> RuntimeHandle:
        if handle_id not in self._handles:
            raise KeyError(f"runtime handle not found: {handle_id}")
        return self._handles[handle_id]

    def put_solid(self, handle: SolidHandle, obj: Any) -> SolidHandle:
        self.put(handle, obj)
        return handle

    def put_frame(self, handle: FrameHandle, obj: Any | None = None) -> FrameHandle:
        self.put(handle, obj)
        return handle

    def put_solid_array(self, handle: SolidArrayHandle, obj: list[Any]) -> SolidArrayHandle:
        self.put(handle, obj)
        return handle
```

## 5.3 RuntimeContext

文件：`generative_cad/runtime/context.py`

```python
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.object_store import RuntimeObjectStore

@dataclass
class RuntimeContext:
    out_step: Path
    metadata_path: Path
    workspace_root: Path
    object_store: RuntimeObjectStore = field(default_factory=RuntimeObjectStore)

    node_outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    component_outputs: dict[str, dict[str, str]] = field(default_factory=dict)

    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)

    geometry_runtime_name: str = "cadquery"
    runner_version: str = "0.2.0"

    def bind_node_output(self, node_id: str, output_name: str, handle_id: str) -> None:
        self.node_outputs.setdefault(node_id, {})[output_name] = handle_id

    def resolve_node_output(self, node_id: str, output_name: str) -> str:
        try:
            return self.node_outputs[node_id][output_name]
        except KeyError as exc:
            raise KeyError(f"missing node output {node_id}.{output_name}") from exc

    def bind_component_output(self, component_id: str, output_name: str, handle_id: str) -> None:
        self.component_outputs.setdefault(component_id, {})[output_name] = handle_id

    def resolve_component_output(self, component_id: str, output_name: str) -> str:
        try:
            return self.component_outputs[component_id][output_name]
        except KeyError as exc:
            raise KeyError(f"missing component output {component_id}.{output_name}") from exc
```

---

# 6. OperationSpec 与 BaseDialect

## 6.1 OperationSpec

文件：`generative_cad/dialects/operation.py`

```python
from __future__ import annotations

from typing import Any, Callable, Literal
from pydantic import BaseModel, ConfigDict

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode, ValueType
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext

Effect = Literal[
    "creates_solid",
    "modifies_solid",
    "cuts_material",
    "adds_material",
    "creates_frame",
    "places_component",
    "patterns_component",
    "boolean_union",
    "boolean_cut",
    "boolean_intersect",
    "exports_artifact",
]

OperationHandler = Callable[[CanonicalNode, RuntimeContext], dict[str, str]]

class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    dialect: str
    op: str
    op_version: str
    phase: str

    input_types: list[ValueType]
    output_types: list[ValueType]

    params_model: type[BaseModel]
    effects: list[Effect]

    required_context: list[str] = []
    postconditions: list[str] = []

    handler: OperationHandler

    def validate_params(self, raw_params: dict[str, Any]) -> BaseModel:
        return self.params_model.model_validate(raw_params)
```

## 6.2 BaseDialect

文件：`generative_cad/dialects/base.py`

```python
from __future__ import annotations

from typing import Protocol, Any

from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport

class BaseDialect(Protocol):
    dialect_id: str
    version: str
    phase_order: tuple[str, ...]

    def manifest(self) -> dict[str, Any]: ...
    def contract(self) -> dict[str, Any]: ...
    def op_specs(self) -> dict[tuple[str, str], OperationSpec]: ...

    def default_op_version(self, op: str) -> str: ...

    def get_op_spec(self, op: str, op_version: str | None = None) -> OperationSpec: ...

    def validate_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
    ) -> ValidationReport: ...

    def preflight_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
    ) -> ValidationReport: ...

    def run_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
        ctx: RuntimeContext,
    ) -> dict[str, str]: ...
```

## 6.3 Registry

文件：`generative_cad/dialects/registry.py`

```python
from __future__ import annotations

import json
import hashlib
from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.base import BaseDialect

DIALECT_REGISTRY: dict[str, BaseDialect] = {}

FORBIDDEN_PART_TOKENS = {
    "turbine_disk",
    "flange",
    "bracket",
    "gearbox",
    "bearing",
}

def contract_hash(contract: dict[str, Any]) -> str:
    data = json.dumps(contract, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()

def register_dialect(dialect: BaseDialect) -> None:
    did = dialect.dialect_id
    if did in DIALECT_REGISTRY:
        raise ValueError(f"duplicate dialect_id: {did}")
    if not did:
        raise ValueError("dialect_id must be non-empty")
    for token in FORBIDDEN_PART_TOKENS:
        if token in did:
            raise ValueError(
                f"dialect_id {did!r} appears to name a part, not a CAD grammar dialect"
            )
    DIALECT_REGISTRY[did] = dialect

def get_dialect(dialect_id: str) -> BaseDialect | None:
    return DIALECT_REGISTRY.get(dialect_id)

def require_dialect(dialect_id: str) -> BaseDialect:
    dialect = DIALECT_REGISTRY.get(dialect_id)
    if dialect is None:
        raise KeyError(f"unknown dialect: {dialect_id!r}")
    return dialect

def list_dialects() -> list[str]:
    return sorted(DIALECT_REGISTRY)

def export_dialect_catalog() -> dict[str, Any]:
    return {
        "catalog_version": "0.2.0",
        "dialects": [
            DIALECT_REGISTRY[k].manifest()
            for k in sorted(DIALECT_REGISTRY)
        ],
    }

def populate_registry() -> None:
    from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.dialect import AXISYMMETRIC_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude.dialect import SKETCH_EXTRUDE_DIALECT
    from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import COMPOSITION_DIALECT

    register_dialect(AXISYMMETRIC_DIALECT)
    register_dialect(SKETCH_EXTRUDE_DIALECT)
    register_dialect(COMPOSITION_DIALECT)

populate_registry()
```

---

# 7. Validation Pipeline

## 7.1 ValidationReport

文件：`generative_cad/validation/reports.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["error", "warning"]

class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    severity: Severity = "error"
    stage: str
    node_id: str | None = None
    component_id: str | None = None
    path: str | None = None
    expected: Any | None = None
    actual: Any | None = None

class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    stage: str
    issues: list[ValidationIssue] = Field(default_factory=list)

    @classmethod
    def ok_report(cls, stage: str) -> "ValidationReport":
        return cls(ok=True, stage=stage, issues=[])

    @classmethod
    def fail(cls, stage: str, code: str, message: str, **kwargs) -> "ValidationReport":
        return cls(
            ok=False,
            stage=stage,
            issues=[
                ValidationIssue(
                    stage=stage,
                    code=code,
                    message=message,
                    **kwargs,
                )
            ],
        )
```

## 7.2 Pipeline 顺序

文件：`generative_cad/validation/pipeline.py`

```python
def validate_and_canonicalize(raw: dict | RawGcadDocument) -> tuple[CanonicalGcadDocument | None, ValidationReport]:
    """
    Full fail-closed validator.

    Stages:
    1. structure
    2. registry
    3. operation params
    4. component ownership
    5. graph DAG
    6. typecheck
    7. phase order
    8. safety
    9. dialect semantic validation
    10. canonicalization
    """
```

必须执行：

```text
1. RawGcadDocument.model_validate
2. selected_dialects exist
3. dialect versions match registry
4. component ids unique
5. node ids unique
6. component owner_dialect exists
7. node dialect exists
8. node op exists
9. fill default op_version if missing
10. validate params by OperationSpec.params_model
11. validate node.outputs against OperationSpec.output_types
12. validate node.inputs against producer outputs
13. forbid cross-component internal node refs except composition
14. enforce component ownership
15. enforce DAG
16. enforce phase order
17. enforce safety true
18. run dialect.validate_component
19. generate CanonicalGcadDocument
20. compute canonical_graph_hash
```

## 7.3 Component ownership rules

文件：`generative_cad/validation/ownership.py`

```text
Rule 1:
  Every component has exactly one owner_dialect.

Rule 2:
  If component.id != "__assembly__":
    every node in that component must use component.owner_dialect.

Rule 3:
  The "__assembly__" component must have owner_dialect = "composition".

Rule 4:
  Cross-component node-to-node input is forbidden unless node.dialect == "composition".

Rule 5:
  Non-composition dialect cannot consume component outputs from another dialect.

Rule 6:
  Composition dialect cannot access dialect-internal intermediate values.
  It can only consume component public outputs or explicitly declared node outputs.
```

## 7.4 Typecheck rules

文件：`generative_cad/validation/typecheck.py`

```text
1. Every RawValueRef must resolve to an existing node output or component output.
2. Every producer output has exactly one declared ValueType.
3. Consumer OperationSpec.input_types must match actual resolved types.
4. OperationSpec.output_types must match node.outputs in count and type.
5. solid_array can only be consumed by composition ops that declare solid_array.
6. frame cannot be consumed as solid.
7. Unknown value type fails closed.
8. Missing output name fails closed.
```

## 7.5 Graph rules

```text
1. Node ids unique.
2. Output names unique per node.
3. Graph must be DAG.
4. Topological order must be computed from actual inputs, not depends_on length.
5. Phase order is checked only after topo sort.
6. A later phase may depend on earlier phase.
7. An earlier phase may not depend on later phase.
8. Same phase dependencies are allowed only if DAG order is clear.
```

当前代码已经有 DAG 和 phase 验证雏形，但它还基于 `depends_on`，不是 typed input graph。([GitHub][5])

---

# 8. Runner / Lowering Pipeline

## 8.1 RunResult

文件：`generative_cad/runtime/results.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class GcadRunResult:
    ok: bool
    step_path: Path | None = None
    metadata_path: Path | None = None
    artifact: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
```

## 8.2 Fixed runner

文件：`generative_cad/pipeline/run.py`

```python
from __future__ import annotations

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult
from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata
from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact

def run_gcad_core_from_files(
    input_json: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    try:
        raw = json.loads(Path(input_json).read_text(encoding="utf-8"))
    except Exception as exc:
        return GcadRunResult(ok=False, error=f"failed to load input JSON: {exc}")

    return run_gcad_core(raw, out_step=out_step, metadata_path=metadata_path)

def run_gcad_core(
    raw: dict,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    canonical, report = validate_and_canonicalize(raw)
    if canonical is None or not report.ok:
        return GcadRunResult(
            ok=False,
            error="validation failed: " + "; ".join(i.message for i in report.issues),
        )

    out_step = Path(out_step)
    metadata_path = Path(metadata_path)
    ctx = RuntimeContext(
        out_step=out_step,
        metadata_path=metadata_path,
        workspace_root=out_step.parent,
    )

    try:
        _run_components(canonical, ctx)
        final_handle_id = _run_composition_or_select_final(canonical, ctx)
        _export_final_solid(final_handle_id, ctx)

        metadata = build_generative_metadata(canonical=canonical, ctx=ctx)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        artifact = build_canonical_step_artifact(
            canonical=canonical,
            step_path=out_step,
            metadata_path=metadata_path,
            ctx=ctx,
        )

        return GcadRunResult(
            ok=True,
            step_path=out_step,
            metadata_path=metadata_path,
            artifact=artifact,
            metadata=metadata,
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )

    except Exception as exc:
        return GcadRunResult(
            ok=False,
            error=str(exc),
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )
```

## 8.3 Component execution

```python
def _run_components(canonical, ctx):
    components = [c for c in canonical.components if c.id != "__assembly__"]

    for component in _topo_sort_components(canonical, components):
        dialect = require_dialect(component.owner_dialect)
        nodes = _nodes_for_component(canonical, component.id)
        component_outputs = dialect.run_component(component, nodes, ctx)

        for name, handle_id in component_outputs.items():
            ctx.bind_component_output(component.id, name, handle_id)

def _run_composition_or_select_final(canonical, ctx) -> str:
    assembly = next((c for c in canonical.components if c.id == "__assembly__"), None)

    if assembly is not None:
        dialect = require_dialect("composition")
        nodes = _nodes_for_component(canonical, "__assembly__")
        outputs = dialect.run_component(assembly, nodes, ctx)
        if "body" not in outputs:
            raise RuntimeError("composition did not produce final body")
        return outputs["body"]

    if len(ctx.component_outputs) != 1:
        raise RuntimeError(
            "multiple components require __assembly__ composition component"
        )

    only_component_outputs = next(iter(ctx.component_outputs.values()))
    if "body" not in only_component_outputs:
        raise RuntimeError("single component did not expose body output")
    return only_component_outputs["body"]
```

## 8.4 Export

```python
def _export_final_solid(handle_id: str, ctx: RuntimeContext) -> None:
    obj = ctx.object_store.get(handle_id)

    import cadquery as cq
    cq.exporters.export(obj, str(ctx.out_step))
```

---

# 9. Dialect 实现规范

## 9.1 AxisymmetricDialect

### 文件

```text
dialects/axisymmetric/
  dialect.py
  params.py
  handlers.py
  preflight.py
  contract.py
  manifest.py
```

### OperationSpec 示例

```python
# dialects/axisymmetric/dialect.py

class AxisymmetricDialect:
    dialect_id = "axisymmetric"
    version = "0.2.0"
    phase_order = (
        "base_solid",
        "primary_cut",
        "annular_detail",
        "pattern_cut",
        "rim_detail",
        "edge_treatment",
        "cleanup",
    )

    def op_specs(self):
        return {
            ("revolve_profile", "1.0.0"): OperationSpec(
                dialect="axisymmetric",
                op="revolve_profile",
                op_version="1.0.0",
                phase="base_solid",
                input_types=[],
                output_types=["solid", "frame"],
                params_model=RevolveProfileParams,
                effects=["creates_solid", "creates_frame"],
                postconditions=["valid_solid", "positive_volume"],
                handler=handle_revolve_profile,
            ),
            ("cut_center_bore", "1.0.0"): OperationSpec(
                dialect="axisymmetric",
                op="cut_center_bore",
                op_version="1.0.0",
                phase="primary_cut",
                input_types=["solid"],
                output_types=["solid"],
                params_model=CutCenterBoreParams,
                effects=["cuts_material", "modifies_solid"],
                postconditions=["valid_solid"],
                handler=handle_cut_center_bore,
            ),
            ("cut_circular_hole_pattern", "1.0.0"): OperationSpec(
                dialect="axisymmetric",
                op="cut_circular_hole_pattern",
                op_version="1.0.0",
                phase="pattern_cut",
                input_types=["solid"],
                output_types=["solid"],
                params_model=CutCircularHolePatternParams,
                effects=["cuts_material", "modifies_solid"],
                postconditions=["valid_solid"],
                handler=handle_cut_circular_hole_pattern,
            ),
        }
```

### Handler 规则

handler 签名固定：

```python
def handle_revolve_profile(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    ...
```

返回值固定为：

```python
{
  "body": "solid:main_disk:n_body:body",
  "outer_frame": "frame:main_disk:n_body:outer_frame"
}
```

不允许返回 CadQuery object。CadQuery object 必须放入 object store。

## 9.2 SketchExtrudeDialect

迁移现有 `sketch_extrude/models.py` 到 `params.py`。当前 params model 已经有 `extra="forbid"` 和基本 field validation，可以复用。([GitHub][9])

MVP operations：

```text
extrude_rectangle
cut_rectangular_pocket
cut_hole
cut_hole_pattern_linear
add_rectangular_boss
add_rib
apply_safe_fillet
apply_safe_chamfer
```

每个 op 必须声明：

```text
op_version = "1.0.0"
input_types
output_types
effects
handler
```

## 9.3 CompositionDialect

### MVP operations

```text
composition.translate_solid
composition.rotate_solid
composition.place_component
composition.circular_pattern_component
composition.linear_pattern_component
composition.boolean_union
composition.boolean_cut
```

### 参数模型

文件：`dialects/composition/params.py`

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class TranslateSolidParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vector_mm: tuple[float, float, float]

class RotateSolidParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis_origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis_dir: tuple[float, float, float]
    angle_deg: float

class CircularPatternComponentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=1, le=360)
    radius_mm: float = Field(ge=0)
    axis: Literal["Z"] = "Z"
    start_angle_deg: float = 0.0

class BooleanUnionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clean_after: bool = True

class BooleanCutParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clean_after: bool = True
```

### Composition 限制

composition handler 只能做：

```text
transform
copy
array / pattern
boolean union
boolean cut
```

不能做：

```text
sketch
profile
loft
sweep
hole semantics
LLM calls
raw Python eval
```

这是防止 composition 变成万能后门。

---

# 10. Metadata 规范

当前 metadata validator 只要求 `generative_metadata / metadata_version / source_route / trust_level / base_stack / feature_graph_hash / safety / validation`，这是不够的。([GitHub][6])

## 10.1 新 metadata schema

文件：`generative_cad/pipeline/metadata.py`

```json
{
  "generative_metadata": {
    "metadata_version": "generative_metadata_v2",
    "source_route": "llm_skill_base",
    "schema_version": "g_cad_core_v0.2",
    "canonical_version": "canonical_gcad_v0.2",
    "trust_level": "reference_geometry",
    "part_name": "example",

    "selected_dialects": [
      {
        "dialect": "axisymmetric",
        "version": "0.2.0",
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

    "raw_graph_hash": "sha256:...",
    "canonical_graph_hash": "sha256:...",
    "runner_version": "0.2.0",
    "geometry_runtime": "cadquery",

    "operation_metrics": [],
    "degraded_features": [],
    "repair_attempts": 0,
    "warnings": [],

    "safety": {
      "non_flight_reference_only": true,
      "not_airworthy": true,
      "not_certified": true,
      "not_for_manufacturing": true,
      "not_for_installation": true,
      "no_structural_validation": true,
      "no_life_prediction": true
    }
  },
  "build_warnings": [],
  "validation": {
    "core_validation": {},
    "geometry_preflight": {},
    "inspection_validation": {}
  }
}
```

## 10.2 Metadata validator 必须检查

```text
1. metadata_version == generative_metadata_v2
2. source_route == llm_skill_base
3. trust_level in concept_geometry/reference_geometry
4. trust_level != certified/manufacturing
5. selected_dialects non-empty
6. every dialect has contract_hash
7. every node has op_version record
8. canonical_graph_hash starts with sha256:
9. runner_version exists
10. geometry_runtime exists
11. safety flags all true
12. build_warnings list exists
13. validation dict exists
14. if canonical document provided, recompute canonical hash and compare
15. if dialect registry available, recompute contract hash and compare
```

---

# 11. Builder 规范

当前 `builder.py` 已经有较好的 fail-closed 流程：spec validation、graph validation、preflight、subprocess、STEP exists、metadata exists、metadata validation、inspection、contract validation。([GitHub][10])

要升级为：

```text
1. Accept raw dict or RawGcadDocument.
2. validate_and_canonicalize before writing graph.
3. write canonical JSON, not raw spec.
4. harness only calls run_gcad_core_from_files.
5. subprocess timeout from canonical.constraints.max_runtime_seconds.
6. fail if step missing.
7. fail if metadata missing.
8. fail if metadata invalid.
9. inspect STEP.
10. validate against canonical.constraints.
11. return CanonicalStepArtifact in metrics["artifact"].
```

## 11.1 Harness 生成

必须修复 metadata_path bug：

```python
def _generate_harness_script(input_json: Path, out_step: Path, metadata_path: Path) -> str:
    return f'''
"""Fixed G-CAD runner harness — auto-generated, contains no LLM CAD code."""
import sys
from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core_from_files

result = run_gcad_core_from_files(
    input_json=r"{input_json.as_posix()}",
    out_step=r"{out_step.as_posix()}",
    metadata_path=r"{metadata_path.as_posix()}",
)

if not result.ok:
    print(f"BUILD FAILED: {{result.error}}", file=sys.stderr)
    sys.exit(1)

print(f"STEP exported: {{result.step_path}}")
print(f"Metadata written: {{result.metadata_path}}")

for w in result.warnings:
    print(f"CQ_WARNING: {{w}}")
'''
```

---

# 12. Tool 层升级

当前工具已有：

```text
generative_cad_list_bases
generative_cad_get_base_contract
generative_cad_validate_ir
generative_cad_build_from_ir
```

这些名称可以保留，但内部改成 dialect：

```text
generative_cad_list_dialects
generative_cad_get_dialect_contract
```

为了兼容可以保留旧工具名，message 中说明 base 已升级为 dialect。

## 12.1 validate tool

`generative_cad_validate_ir(spec: dict)` 必须返回：

```json
{
  "ok": true,
  "metrics": {
    "validation": {
      "ok": true,
      "stage": "canonicalization",
      "issues": []
    },
    "canonical_graph_hash": "sha256:...",
    "canonical_preview": {
      "components": 2,
      "nodes": 5,
      "dialects": ["axisymmetric", "sketch_extrude", "composition"]
    }
  }
}
```

## 12.2 build tool

`generative_cad_build_from_ir` 必须只接受：

```text
RawGcadDocument-compatible dict
```

如果收到 legacy `GenerativeCADSpec`：

```text
可以 adapter 转换；
但返回 warning：legacy GenerativeCADSpec was adapted to g_cad_core_v0.2
```

---

# 13. Repair Governor

当前文档已明确 repair loop 不能无限循环。

MVP 实现文件：`generative_cad/pipeline/repair.py`

```python
class RepairGovernor:
    max_attempts: int = 3

    seen_graph_hashes: set[str]
    seen_error_hashes: set[str]
    last_stage_rank: int
    last_error_count: int

    def allow_attempt(self, graph_hash: str, error_hash: str, stage: str, error_count: int) -> bool:
        ...
```

规则：

```text
1. repair 只能输出 JSON patch。
2. patch 只能修改 /nodes/*/params/*
3. patch 不能修改 schema_version。
4. patch 不能修改 safety。
5. patch 不能修改 constraints 中的 fail-closed flags。
6. patch 不能新增 dialect。
7. patch 不能新增 unknown op。
8. patch 不能修改 operation contract。
9. same graph hash repeated -> stop。
10. same error signature repeated -> stop。
11. validation stage 不前进 -> stop。
12. error count 不下降 -> stop。
13. max_attempts reached -> stop。
```

---

# 14. 测试矩阵

必须新增目录：

```text
tests/generative_cad/
```

## 14.1 P0 tests

```text
test_import_generative_cad_modules
test_registry_has_axisymmetric_sketch_extrude_composition
test_harness_result_has_metadata_path
test_unknown_dialect_fails_closed
test_unknown_op_fails_closed
test_safety_false_fails
test_constraints_false_fails
```

## 14.2 Core IR tests

```text
test_raw_gcad_document_minimal_valid
test_duplicate_component_id_fails
test_duplicate_node_id_fails
test_missing_component_fails
test_node_unknown_component_fails
test_selected_dialect_missing_fails
test_node_dialect_not_selected_fails
test_default_op_version_inserted_in_canonical
test_canonical_graph_hash_stable
test_canonical_graph_hash_changes_on_param_change
```

## 14.3 Type system tests

```text
test_input_ref_missing_node_fails
test_input_ref_missing_output_fails
test_input_type_mismatch_fails
test_output_type_count_mismatch_fails
test_frame_cannot_be_used_as_solid
test_solid_array_consumed_only_by_composition
```

## 14.4 Ownership / composition tests

```text
test_component_owner_dialect_enforced
test_cross_component_node_ref_forbidden_for_non_composition
test_cross_base_requires_composition_dialect
test_composition_can_consume_component_outputs
test_multiple_components_without_assembly_fails
test_single_component_without_assembly_allowed
```

## 14.5 Operation extension tests

```text
test_extended_param_validated_by_op_spec_only
test_old_op_version_still_uses_old_params_model
test_new_op_version_does_not_modify_core_validator
```

## 14.6 Runner tests

```text
test_axisymmetric_minimal_revolve_exports_step
test_sketch_extrude_minimal_box_exports_step
test_axisymmetric_plus_sketch_extrude_with_composition_exports_step
test_optional_node_degrades_with_warning
test_required_node_failure_fails_build
test_metadata_v2_written
test_metadata_contract_hash_matches_registry
```

## 14.7 Golden fixture corpus

```text
tests/fixtures/generative_cad/
  axisymmetric_minimal.json
  sketch_extrude_minimal.json
  composed_disk_with_lugs.json
  invalid_unknown_op.json
  invalid_type_mismatch.json
  invalid_cross_base_direct_ref.json
  invalid_safety_false.json
```

---

# 15. 高质量 LLM 输出 Prompt 规范

这个 prompt 是给“上游 LLM 生成 G-CAD Core IR”用的，不是给 Claude Code 的。

```text
You are generating SeekFlow G-CAD Core IR v0.2.

You must output ONLY valid JSON.
Do not output Markdown.
Do not output Python.
Do not output CadQuery.
Do not invent dialects or operations.
Do not omit safety flags.
Do not set any safety flag to false.
Do not claim manufacturing-ready, certified, airworthy, installable, or structurally validated geometry.

Available dialects:
{DIALECT_CATALOG}

User request:
{USER_REQUEST}

Task:
1. Select the smallest set of dialects needed.
2. Use components for independently generated solids.
3. Use composition only for placement, pattern, and boolean operations across components.
4. Every node must declare component, dialect, op, phase, inputs, outputs, params, required, degradation_policy.
5. Put all operation-specific parameters inside node.params.
6. Do not add fields outside the G-CAD Core IR envelope.
7. Use units = "mm".
8. Use trust_level = "reference_geometry".
9. Include constraints requiring STEP, metadata sidecar, closed solid, and expected body count.
10. Include all safety flags as true.

Output schema:
{
  "schema_version": "g_cad_core_v0.2",
  "document_id": "...",
  "part_name": "...",
  "units": "mm",
  "trust_level": "reference_geometry",
  "selected_dialects": [
    {"dialect": "...", "version": "..."}
  ],
  "components": [
    {"id": "...", "owner_dialect": "...", "kind_hint": "...", "root_node": "..."}
  ],
  "nodes": [
    {
      "id": "...",
      "component": "...",
      "dialect": "...",
      "op": "...",
      "op_version": null,
      "phase": "...",
      "inputs": [],
      "outputs": [{"name": "body", "type": "solid"}],
      "params": {},
      "required": true,
      "degradation_policy": "fail"
    }
  ],
  "constraints": {
    "require_step_file": true,
    "require_metadata_sidecar": true,
    "require_closed_solid": true,
    "expected_body_count": 1,
    "max_runtime_seconds": 120
  },
  "safety": {
    "non_flight_reference_only": true,
    "not_airworthy": true,
    "not_certified": true,
    "not_for_manufacturing": true,
    "not_for_installation": true,
    "no_structural_validation": true,
    "no_life_prediction": true
  }
}
```

---

# 16. 给 Claude Code 的最终实施 Prompt

下面这段可以直接复制给 Claude Code。

```text
You are working in the GitHub repository WYZAAACCC/seekflow-engineering, under integrations/engineering_tools.

Goal:
Upgrade the existing seekflow_engineering_tools.generative_cad implementation from the current single-base FeatureGraph runner into a compiler-style G-CAD Core IR v0.2 pipeline.

This is a safety-critical architecture refactor. Implement exactly as specified. Do not improvise by merging this into primitive CADPartSpec or PRIMITIVE_COMPILERS.

Current known facts:
- generative_cad/ir.py currently defines GenerativeCADSpec with selected_bases and feature_graph.nodes using base_id/op/phase/params/depends_on.
- generative_cad/base.py currently defines OperationDefinition without op_version, input_types, output_types, effects, or handler.
- generative_cad/runner.py currently supports only one base per graph and returns GenerativeRunResult without metadata_path.
- generative_cad/builder.py prints result.metadata_path in the harness, which is currently a bug.
- axisymmetric and sketch_extrude runners currently dispatch operations with if/elif and mutate one local body.
- graph_validation.py currently validates unknown base/op, params schema, DAG, phase, and base semantics, but does not implement typed inputs/outputs, component ownership, op_version, or canonicalization.

Hard constraints:
1. Do not modify deterministic primitive path semantics.
2. Do not modify cadquery_backend/primitive_compiler.py except import-safe tests if needed.
3. Do not add generative bases to PRIMITIVE_COMPILERS.
4. Do not add generative feature types to ir/cad.py.
5. Do not pass raw LLM JSON to any dialect runner.
6. All input must pass RawGcadDocument -> CanonicalGcadDocument validation.
7. Core IR envelope is fixed: schema_version, document_id, part_name, units, trust_level, selected_dialects, components, nodes, constraints, safety.
8. Base-specific fields are allowed only inside node.params.
9. node.params must be validated by OperationSpec.params_model.
10. Every dialect must implement BaseDialect.
11. Every operation must declare OperationSpec.
12. Every OperationSpec must include dialect, op, op_version, phase, input_types, output_types, params_model, effects, postconditions, handler.
13. Multiple dialects can only be composed through composition dialect.
14. Dialects must not call each other directly.
15. Cross-dialect values must be typed handles stored in RuntimeObjectStore.
16. Adding a new op parameter must not require modifying core validator.
17. Unknown dialect/op must fail closed.
18. No fuzzy matching.
19. No silent fallback.
20. The runner must use a fixed harness and must not dynamically generate large CadQuery scripts.
21. Output must be STEP + generative metadata + CanonicalStepArtifact.
22. Trust level must not exceed reference_geometry.

Implementation tasks:

Task 0: Fix current bug
- Add metadata_path to GenerativeRunResult or replace harness print with the known metadata_path.
- Prefer adding metadata_path to result.

Task 1: Add new package structure
Create:
generative_cad/ir/raw.py
generative_cad/ir/canonical.py
generative_cad/ir/values.py
generative_cad/ir/safety.py
generative_cad/ir/hashing.py
generative_cad/dialects/base.py
generative_cad/dialects/operation.py
generative_cad/dialects/registry.py
generative_cad/runtime/handles.py
generative_cad/runtime/object_store.py
generative_cad/runtime/context.py
generative_cad/runtime/results.py
generative_cad/validation/reports.py
generative_cad/validation/pipeline.py
generative_cad/validation/structure.py
generative_cad/validation/registry.py
generative_cad/validation/params.py
generative_cad/validation/typecheck.py
generative_cad/validation/graph.py
generative_cad/validation/phase.py
generative_cad/validation/ownership.py
generative_cad/validation/safety.py
generative_cad/validation/canonicalize.py
generative_cad/pipeline/run.py
generative_cad/pipeline/build.py
generative_cad/pipeline/metadata.py
generative_cad/pipeline/artifact.py

Task 2: Implement RawGcadDocument
- schema_version = "g_cad_core_v0.2"
- required envelope fields:
  document_id, part_name, units, trust_level, selected_dialects, components, nodes, constraints, safety.
- Node fields:
  id, component, dialect, op, op_version optional, phase, inputs, outputs, params, required, degradation_policy.
- Forbid extra fields everywhere.
- Fail if safety flags are false.
- Fail if require_step_file, require_metadata_sidecar, or require_closed_solid are false.

Task 3: Implement CanonicalGcadDocument
- Include resolved dialects with contract_hash.
- Include canonical nodes with op_version filled.
- Include typed_params produced by OperationSpec.params_model.
- Include resolved input types and output value ids.
- Include canonical_graph_hash.
- Hash must be stable with json.dumps(sort_keys=True, default=str).

Task 4: Implement OperationSpec and BaseDialect
- OperationSpec must include handler callable.
- BaseDialect must expose manifest, contract, op_specs, default_op_version, get_op_spec, validate_component, preflight_component, run_component.

Task 5: Implement typed runtime handles
- SolidHandle, SolidArrayHandle, FrameHandle, PlaneHandle, PointHandle, CurveHandle, ProfileHandle.
- Implement RuntimeObjectStore.
- RuntimeContext binds node outputs and component outputs by handle id.

Task 6: Implement validation pipeline
Stages:
1. structure
2. registry
3. params
4. ownership
5. graph
6. typecheck
7. phase
8. safety
9. dialect_semantics
10. canonicalize

Each failure must return a ValidationReport with code, message, stage, severity, and optional node_id/component_id/path.

Task 7: Migrate axisymmetric
- Move current params models from bases/axisymmetric/models.py to dialects/axisymmetric/params.py or re-export them.
- Convert current _op_* functions into handlers.
- Use OperationSpec for each op.
- Handler must read input handles from RuntimeContext and store output handles in RuntimeObjectStore.
- Handler must return output name -> handle id mapping.
- No if/elif dispatch in run_component.

Task 8: Migrate sketch_extrude
- Same as axisymmetric.
- No if/elif dispatch in run_component.

Task 9: Add composition dialect
MVP ops:
- translate_solid
- rotate_solid
- circular_pattern_component
- linear_pattern_component
- boolean_union
- boolean_cut

Composition can only transform, pattern, and boolean existing typed handles.
It must not create sketch/profile geometry.

Task 10: Implement runner
- run_gcad_core_from_files(input_json, out_step, metadata_path)
- run_gcad_core(raw, out_step, metadata_path)
- Validate raw -> canonical.
- Run non-assembly components by owner dialect.
- Run __assembly__ component by composition dialect if present.
- If one component and no assembly, use that component body as final.
- If multiple components and no assembly, fail.
- Export final solid to STEP with CadQuery.
- Write metadata v2.
- Return GcadRunResult including step_path and metadata_path.

Task 11: Implement builder
- Keep public function build_generative_cad_model.
- Accept dict.
- Validate and canonicalize before writing file.
- Write canonical JSON to .generative_cad_graphs.
- Generate fixed harness.
- Execute subprocess.
- Assert STEP exists.
- Assert metadata exists.
- Validate metadata.
- Inspect STEP with existing inspect_step_with_cadquery.
- Validate inspection against canonical.constraints.
- Return EngineeringActionResult with metrics including CanonicalStepArtifact.

Task 12: Metadata v2
- Write generative_metadata_v2.
- Include selected_dialects, contract_hashes, op_versions, raw_graph_hash, canonical_graph_hash, runner_version, geometry_runtime, operation_metrics, degraded_features, warnings, safety.
- Validator must recompute hashes when possible.

Task 13: Compatibility
- Preserve old tool names.
- Existing generative_cad_validate_ir and generative_cad_build_from_ir should use new RawGcadDocument.
- Optionally provide a legacy adapter from GenerativeCADSpec to RawGcadDocument for old fixtures, but do not let old model bypass new validator.

Task 14: Tests
Add tests/generative_cad with:
- import smoke
- registry includes axisymmetric, sketch_extrude, composition
- metadata_path bug fixed
- unknown dialect fails
- unknown op fails
- safety false fails
- duplicate node fails
- missing input ref fails
- input type mismatch fails
- component owner dialect enforced
- cross-base direct reference forbidden
- cross-base composition allowed
- single component build exports STEP
- composed multi component build exports STEP
- metadata v2 validates
- canonical graph hash stable
- op parameter extension does not modify core validator

Acceptance:
- Existing non-generative tests still pass.
- New generative tests pass.
- No LLM-generated CadQuery code is executed.
- No modification to primitive compiler behavior.
- Multi-dialect composed fixture builds a STEP and metadata.
```

---

# 17. 最小可验收示例 IR

```json
{
  "schema_version": "g_cad_core_v0.2",
  "document_id": "demo_plate_001",
  "part_name": "demo_plate",
  "units": "mm",
  "trust_level": "reference_geometry",
  "selected_dialects": [
    {"dialect": "sketch_extrude", "version": "0.2.0"}
  ],
  "components": [
    {
      "id": "plate",
      "owner_dialect": "sketch_extrude",
      "kind_hint": "rectangular_plate",
      "root_node": "n_base"
    }
  ],
  "nodes": [
    {
      "id": "n_base",
      "component": "plate",
      "dialect": "sketch_extrude",
      "op": "extrude_rectangle",
      "op_version": "1.0.0",
      "phase": "base_solid",
      "inputs": [],
      "outputs": [
        {"name": "body", "type": "solid"}
      ],
      "params": {
        "width_mm": 120,
        "height_mm": 80,
        "depth_mm": 12,
        "plane": "XY",
        "centered": true,
        "direction": "+"
      },
      "required": true,
      "degradation_policy": "fail"
    },
    {
      "id": "n_holes",
      "component": "plate",
      "dialect": "sketch_extrude",
      "op": "cut_hole_pattern_linear",
      "op_version": "1.0.0",
      "phase": "hole_pattern",
      "inputs": [
        {"node": "n_base", "output": "body"}
      ],
      "outputs": [
        {"name": "body", "type": "solid"}
      ],
      "params": {
        "hole_dia_mm": 8,
        "count_x": 2,
        "count_y": 2,
        "spacing_x_mm": 80,
        "spacing_y_mm": 40,
        "axis": "Z",
        "through_all": true
      },
      "required": true,
      "degradation_policy": "fail"
    }
  ],
  "constraints": {
    "require_step_file": true,
    "require_metadata_sidecar": true,
    "require_closed_solid": true,
    "expected_body_count": 1,
    "max_runtime_seconds": 120
  },
  "safety": {
    "non_flight_reference_only": true,
    "not_airworthy": true,
    "not_certified": true,
    "not_for_manufacturing": true,
    "not_for_installation": true,
    "no_structural_validation": true,
    "no_life_prediction": true
  }
}
```

---

# 18. 最终判断

这套最终架构才真正满足你要的标准：

```text
添加 base 不改总编译器；
添加 op 不改总编译器；
添加参数不改 Core IR；
LLM 错误不会进入 runner；
多 base 不互相调用；
跨 base 只通过 typed handles；
composition 只做链接层；
STEP + metadata 是唯一合流点；
所有失败 fail-closed；
旧 primitive 主链路不被污染。
```

当前实现已经有正确雏形，但必须完成这次 v0.2 编译器化重构，才能接近“传统编译器级稳定、兼容、添加内容不会崩”的目标。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/base.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runner.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/axisymmetric/runner.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/graph_validation.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/metadata.py "raw.githubusercontent.com"
[7]: https://mlir.llvm.org/docs/DefiningDialects/ "Defining Dialects - MLIR"
[8]: https://cadquery.readthedocs.io/en/latest/ "CadQuery Documentation — CadQuery Documentation"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/sketch_extrude/models.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "raw.githubusercontent.com"
