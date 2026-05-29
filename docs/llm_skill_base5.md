# SeekFlow Engineering Tools — Generative CAD-IR / LLM-Skill-Base v0.3 工程实现规格书

版本：v0.3 implementation spec
目标仓库：`WYZAAACCC/seekflow-engineering`
目标目录：`integrations/engineering_tools/src/seekflow_engineering_tools`
核心子系统：`generative_cad`
实现执行者：Claude Code
目标状态：把当前 v0.2 Generative CAD 雏形收敛成严格、可测试、可扩展、可导入 SolidWorks/NX 的受控 LLM-Skill-Base CAD 编译链路。

---

# 0. 总目标

本次实现的目标不是新增更多 CAD operation，也不是让 LLM 直接生成 CadQuery/SolidWorks/NX 代码。

本次实现目标是把当前已经存在但尚未完全闭合的 generative CAD 路线，升级为一条真正安全、稳定、可扩展、可交付的编译链路：

```text
User natural language
  ↓
Level-1 Domain Skill / Routing Context
  ↓
Dialect Selection Plan
  ↓
Load selected Dialect Contracts + Level-2 Usage Skills
  ↓
LLM emits RawGcadDocument JSON only
  ↓
RawGcadDocument structural validation
  ↓
Registry / params / ownership / graph / type / phase / safety validation
  ↓
Dialect semantic validation
  ↓
Geometry preflight
  ↓
CanonicalGcadDocument
  ↓
Fixed runner harness
  ↓
BaseDialect / OperationSpec execution
  ↓
Runtime postconditions
  ↓
STEP export
  ↓
Strict STEP inspection
  ↓
Generative metadata v2
  ↓
CanonicalStepArtifact
  ↓
Optional SolidWorks STEP import
  ↓
Optional NX STEP import
```

该链路必须保持与现有 Primitive / CADPartSpec 路线隔离。

最终系统必须满足：

```text
LLM never writes CAD code.
LLM never controls file paths.
LLM never calls CadQuery, SolidWorks COM, NXOpen, APDL, subprocess, imports, exporters, or validators.
LLM only emits RawGcadDocument JSON or local repair patch JSON.
RawGcadDocument never enters runtime directly.
Only CanonicalGcadDocument enters runner.
Only STEP + metadata enters SolidWorks/NX.
Generative output never becomes primitive.
Primitive route remains untouched.
```

---

# 1. 当前代码状态判断

当前仓库已经具备正确方向，但处于“v0.2 半收敛状态”。

## 1.1 已经正确的部分

当前已经存在：

```text
generative_cad/ir/raw.py
generative_cad/ir/canonical.py
generative_cad/dialects/base.py
generative_cad/dialects/operation.py
generative_cad/dialects/registry.py
generative_cad/validation/pipeline.py
generative_cad/pipeline/run.py
generative_cad/pipeline/metadata.py
generative_cad/runtime/*
generative_cad/tools.py
```

这些模块已经表达了正确的主线：

```text
RawGcadDocument
→ validate_and_canonicalize
→ CanonicalGcadDocument
→ BaseDialect / OperationSpec
→ runtime handles
→ STEP + metadata
```

必须保留这些方向。

## 1.2 必须修复的问题

当前存在以下架构缺陷：

```text
1. v0.1 legacy schema 与 v0.2 dialect schema 并存。
2. repair_governor.py 仍基于旧 GenerativeCADSpec / feature_graph / selected_bases。
3. preflight.py 仍基于旧 BASE_REGISTRY。
4. prompts.py 仍使用 base / selected_bases / GenerativeCADSpec 旧术语。
5. validation pipeline 没有调用 dialect.validate_component。
6. validation pipeline 没有调用 dialect.preflight_component。
7. 多组件没有 __assembly__ 的情况 validation 仍可通过。
8. STEP inspection unavailable 默认只是 warning，不是 strict fail。
9. metadata.validation.geometry_preflight 为空。
10. metadata.validation.inspection_validation 不是 build 前后的统一强制 contract。
11. SolidWorks/NX 只有通用 STEP import，没有 generative artifact import wrapper。
12. Skill 机制只是 markdown 与 prompt 文本，没有形成 Level-1 / Level-2 orchestration。
13. dialect contract re-export 自 legacy bases，说明旧 base 仍是 contract source。
14. composition dialect 仍主要是 solid → solid，不是真正 component_ref / frame-aware composition。
15. runner 有若干 runtime exception 应提前移动到 validation 阶段。
```

本次实现优先修复 1–12。第 13–15 作为 v0.3 的强制方向，其中 composition 的 frame-aware 完整能力可分阶段实现，但 validation 必须先闭合。

---

# 2. 不允许修改的硬边界

Claude Code 必须遵守以下硬约束。

## 2.1 不允许污染 Primitive 主链路

禁止修改以下语义：

```text
seekflow_engineering_tools/ir/cad.py
seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
seekflow_engineering_tools/geometry_primitives/
PRIMITIVE_COMPILERS
PRIMITIVE_REGISTRY
CADPartSpec feature semantics
engineering_validate_cad_ir primitive/recipe semantics
engineering_build_cad_model primitive routing semantics
```

允许新增测试来证明未污染。

## 2.2 不允许把 generative dialect 注册为 primitive

禁止：

```text
axisymmetric
sketch_extrude
composition
axisymmetric_base
sketch_extrude_base
composition_base
```

进入：

```text
PRIMITIVE_COMPILERS
PRIMITIVE_REGISTRY
CAPABILITIES["cadquery"]["stable_primitives"]
CADPartSpec.features
```

## 2.3 LLM 输出边界

LLM 只允许输出两类结构：

```text
1. DialectSelectionPlan JSON
2. RawGcadDocument JSON
3. RepairPatchV2 JSON
```

LLM 不允许输出：

```text
Python
CadQuery
SolidWorks COM
NXOpen
APDL
shell command
file path
subprocess
import/export call
validation result override
metadata override
contract override
```

## 2.4 运行边界

runtime 只允许接收：

```text
CanonicalGcadDocument
```

禁止：

```text
run_component(raw_json)
run_component(RawGcadDocument)
dialect.run_component before canonicalization
LLM raw JSON directly into handler
```

## 2.5 STEP/SW/NX 边界

SolidWorks/NX 只能接收：

```text
CanonicalStepArtifact with valid generative_metadata_v2
```

禁止：

```text
LLM generating SW feature tree
LLM generating NXOpen geometry
generative path direct native rebuild
native_rebuild_allowed = true
importing STEP without metadata validation
importing STEP with failed inspection_validation
```

---

# 3. 目标架构

## 3.1 模块总览

最终目录结构应收敛为：

```text
src/seekflow_engineering_tools/generative_cad/
  __init__.py

  ir/
    __init__.py
    raw.py
    canonical.py
    values.py
    hashing.py

  dialects/
    __init__.py
    base.py
    operation.py
    registry.py

    axisymmetric/
      __init__.py
      dialect.py
      params.py
      handlers.py
      manifest.py
      contract.py
      semantic.py
      preflight.py
      usage_skill.py

    sketch_extrude/
      __init__.py
      dialect.py
      params.py
      handlers.py
      manifest.py
      contract.py
      semantic.py
      preflight.py
      usage_skill.py

    composition/
      __init__.py
      dialect.py
      params.py
      handlers.py
      manifest.py
      contract.py
      semantic.py
      preflight.py
      usage_skill.py

  validation/
    __init__.py
    reports.py
    structure.py
    registry.py
    params.py
    ownership.py
    graph.py
    typecheck.py
    phase.py
    safety.py
    composition.py
    dialect_semantics.py
    geometry_preflight.py
    canonicalize.py
    pipeline.py

  runtime/
    __init__.py
    context.py
    handles.py
    object_store.py
    resolve.py
    results.py
    postconditions.py
    geometry_inspection.py

  pipeline/
    __init__.py
    validate.py
    run.py
    build.py
    artifact.py
    metadata.py
    import_artifact.py

  skills/
    __init__.py
    domain/
      generic_mechanical.md
      turbomachinery_reference.md
    orchestrator.py
    prompts.py
    schemas.py

  repair/
    __init__.py
    governor.py
    patch.py
    hashes.py

  tools.py

  legacy/
    __init__.py
    ir_v01.py
    base_v01.py
    registry_v01.py
    graph_validation_v01.py
    metadata_v01.py
    preflight_v01.py
    repair_governor_v01.py
```

## 3.2 迁移原则

当前根目录下旧文件：

```text
generative_cad/ir.py
generative_cad/base.py
generative_cad/registry.py
generative_cad/graph_validation.py
generative_cad/metadata.py
generative_cad/preflight.py
generative_cad/repair_governor.py
generative_cad/validation.py
```

必须迁入：

```text
generative_cad/legacy/
```

并修复所有 import。

禁止新代码 import：

```python
seekflow_engineering_tools.generative_cad.ir.GenerativeCADSpec
seekflow_engineering_tools.generative_cad.registry.BASE_REGISTRY
seekflow_engineering_tools.generative_cad.repair_governor
seekflow_engineering_tools.generative_cad.preflight
```

除非路径包含：

```text
generative_cad.legacy
```

并且仅 legacy tests 使用。

---

# 4. IR 设计要求

## 4.1 RawGcadDocument

`RawGcadDocument` 是唯一 LLM 可输出的建模文档。

保持 schema：

```python
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
llm_validation_hints: dict[str, Any]
```

必须继续使用：

```python
model_config = ConfigDict(extra="forbid")
```

所有子模型必须 `extra="forbid"`。

### 4.1.1 RawValueRef 规则

当前：

```python
class RawValueRef:
    node: str | None
    component: str | None
    output: str
```

规则保持：

```text
exactly one of node or component must be set
```

新增约束：

```text
If component is set:
  consumer node dialect must be "composition".
```

该约束应在 ownership/typecheck/composition validation 层实现，而不是 Pydantic model 内实现。

### 4.1.2 RawComponent 规则

当前：

```python
id: str
owner_dialect: str
kind_hint: str | None
root_node: str | None
```

v0.3 要求：

```text
root_node must be explicit for every non-empty component.
__assembly__ root_node must also be explicit.
```

如果当前 schema 允许 `root_node=None`，可保留以便 Raw schema parsing，但 canonicalize 必须 fail。已经有此行为，必须新增测试覆盖 `__assembly__`。

### 4.1.3 trust_level 规则

允许：

```text
concept_geometry
reference_geometry
```

禁止新增：

```text
production_ready
manufacturing_ready
certified
airworthy
installable
```

## 4.2 CanonicalGcadDocument

Canonical IR 必须继续包含：

```text
contract_hash
op_version
typed_params
operation_effects
postconditions
raw_graph_hash
canonical_graph_hash
```

新增要求：

```python
validation_summary: dict[str, Any] | None = None
```

或者在 metadata 中强制保存 validation reports。二选一即可。优先选择 metadata 保存，避免 Canonical IR 变重。

## 4.3 canonical hash

`canonical_graph_hash` 必须只基于语义稳定字段：

```text
node id
component
dialect
op
op_version
phase
inputs
outputs
params
```

不要把 warnings、metrics、runtime transient object id、file path 放入 canonical hash。

---

# 5. Validation Pipeline v0.3

## 5.1 新 pipeline 顺序

将 `validation/pipeline.py` 的 stages 改为：

```python
stages = [
    ("structure", validate_structure),
    ("registry", validate_registry),
    ("params", validate_params),
    ("ownership", validate_ownership),
    ("graph", validate_graph),
    ("typecheck", validate_typecheck),
    ("phase", validate_phase),
    ("composition", validate_composition_requirements),
    ("safety", validate_safety),
]
```

然后：

```python
canonical, c_report = canonicalize(raw)
```

然后对 canonical 执行：

```python
canonical_stages = [
    ("dialect_semantics", validate_dialect_semantics),
    ("geometry_preflight", validate_geometry_preflight),
]
```

最终返回：

```python
CanonicalGcadDocument | None
ValidationReport
```

注意：

```text
structure/registry/params/ownership/graph/typecheck/phase/composition/safety 是 Raw-level validation。
canonicalize 是 Raw → Canonical lowering。
dialect_semantics/geometry_preflight 是 Canonical-level validation。
runtime_postconditions 是 runtime-level validation，不在 validate_and_canonicalize 内执行。
```

原因：

```text
Dialect semantic validation 需要 op_version、typed_params、contract hash 等 canonical 信息。
Geometry preflight 也应基于 canonical typed params，避免 raw params 类型漂移。
```

## 5.2 ValidationReport 要求

现有 `ValidationReport` 需要支持：

```python
ok: bool
stage: str
issues: list[ValidationIssue]
```

`ValidationIssue` 必须至少包含：

```python
stage: str
code: str
message: str
severity: Literal["error", "warning"]
node_id: str | None
component_id: str | None
path: str | None
expected: str | None
actual: str | None
```

如果当前已有接近模型，不要重写整个结构；只补齐缺字段并保证 model_dump 稳定。

## 5.3 validate_composition_requirements

新增文件：

```text
generative_cad/validation/composition.py
```

实现：

```python
def validate_composition_requirements(raw: RawGcadDocument) -> ValidationReport:
    ...
```

规则：

### Rule C001：多非 assembly component 必须有 `__assembly__`

```text
If count(components where id != "__assembly__") > 1:
  require component id "__assembly__"
  require selected_dialects contains dialect "composition"
```

失败：

```text
stage: composition
code: multiple_components_require_assembly
message: multiple non-assembly components require __assembly__ composition component
```

### Rule C002：`__assembly__` 必须 owner_dialect = composition

已有 ownership 检查，但 composition validator 再做一次聚合语义检查。

失败：

```text
code: assembly_owner_must_be_composition
```

### Rule C003：`__assembly__` 必须至少有一个 node

失败：

```text
code: empty_assembly_component
```

### Rule C004：`__assembly__` root_node 必须存在

失败：

```text
code: assembly_missing_root_node
```

### Rule C005：`__assembly__` root_node 必须输出 `body: solid`

失败：

```text
code: assembly_root_must_output_body_solid
```

### Rule C006：非 assembly component root_node 必须输出 `body: solid`

失败：

```text
code: component_root_must_output_body_solid
```

说明：

```text
当前 canonicalize 只要求 root_node 有 outputs，不保证 body solid。
v0.3 必须提前检查，否则 runtime 中 _run_composition_or_select_final 才失败。
```

### Rule C007：单非 assembly component 无 assembly 允许

```text
If exactly one non-assembly component:
  __assembly__ optional.
```

### Rule C008：assembly node 必须使用 composition dialect

失败：

```text
code: assembly_node_must_use_composition
```

## 5.4 validate_dialect_semantics

新增文件：

```text
generative_cad/validation/dialect_semantics.py
```

实现：

```python
def validate_dialect_semantics(canonical: CanonicalGcadDocument) -> ValidationReport:
    issues = []
    for component in canonical.components:
        dialect = require_dialect(component.owner_dialect)
        nodes = [n for n in canonical.nodes if n.component == component.id]
        report = dialect.validate_component(component, nodes)
        merge issues
    return report
```

要求：

```text
Do not swallow dialect exceptions.
Convert exceptions into ValidationIssue with code="dialect_semantic_validator_error".
```

每个 dialect 的 `validate_component` 必须至少检查：

### axisymmetric

```text
1. exactly one base_solid root creation op is allowed.
2. root_node must be reachable from all downstream modifications or final body chain.
3. first solid-producing node in component must be revolve_profile.
4. revolve_profile must output body:solid and outer_frame:frame.
5. all cut/modification ops must consume solid and output solid.
6. no operation may consume frame as solid.
7. at least one valid_solid postcondition exists for final root chain.
```

### sketch_extrude

```text
1. exactly one base_solid creation op is allowed.
2. first solid-producing node must be extrude_rectangle.
3. pocket/hole/rib/boss ops must consume solid and output solid.
4. root_node must output body:solid.
```

### composition

```text
1. component id must be "__assembly__".
2. all nodes must use composition dialect.
3. final root_node must output body:solid.
4. boolean_cut requires exactly 2 inputs in v0.3.
5. boolean_union requires at least 2 logical inputs if it is the final assembly operation.
```

## 5.5 validate_geometry_preflight

新增文件：

```text
generative_cad/validation/geometry_preflight.py
```

实现：

```python
def validate_geometry_preflight(canonical: CanonicalGcadDocument) -> ValidationReport:
    issues = []
    policy = DEFAULT_GEOMETRY_POLICY
    check global node counts
    call dialect.preflight_component(component, nodes)
    return merged report
```

全局 policy：

```python
DEFAULT_GEOMETRY_POLICY = {
    "max_nodes": 64,
    "max_boolean_ops": 256,
    "max_profile_points": 128,
    "min_edge_length_mm": 0.25,
    "min_wall_thickness_mm": 1.0,
    "min_boolean_clearance_mm": 0.2,
    "min_hole_to_boundary_margin_mm": 1.0,
    "max_pattern_instances": 360,
}
```

全局检查：

```text
max_nodes
max_boolean_ops
max_profile_points where operation params contain profile_stations / points / sections
```

### axisymmetric preflight v0.3

实现文件：

```text
generative_cad/dialects/axisymmetric/preflight.py
```

并在 dialect.preflight_component 调用。

必须检查：

#### A001 revolve_profile stations

```text
profile_stations length >= 2
all r_mm > 0
z_rear_mm > z_front_mm
station radial values finite
station z values finite
max radius > min radius
```

#### A002 center bore sanity

对 `cut_center_bore`：

```text
diameter_mm > 0
diameter_mm < 2 * max_profile_radius
diameter_mm <= 0.90 * 2 * min_hub_radius_guess
```

如果无法确定 hub radius，则只检查小于外径。

#### A003 circular hole pattern sanity

对 `cut_circular_hole_pattern`：

```text
count >= 3
hole_dia_mm > 0
pcd_mm > 0
pcd_mm / 2 + hole_dia_mm / 2 < max_profile_radius - min_hole_to_boundary_margin_mm
pcd_mm / 2 - hole_dia_mm / 2 > center_bore_radius + min_hole_to_boundary_margin_mm if bore exists
```

#### A004 annular groove sanity

对 `cut_annular_groove`：

```text
inner_dia_mm < outer_dia_mm
outer radius < max_profile_radius
groove_width/depth positive if fields exist
```

Use actual param field names from existing params models. Do not invent field names; inspect existing Pydantic models and implement checks against real fields only.

#### A005 rim slot sanity

对 `cut_rim_slot_pattern`：

```text
count >= 3
slot depth positive
slot radius band within max radius
slot depth must not remove entire rim
```

Use existing param field names.

### sketch_extrude preflight v0.3

实现文件：

```text
generative_cad/dialects/sketch_extrude/preflight.py
```

必须检查：

```text
extrude_rectangle width_mm > 0
height_mm > 0
depth_mm > 0
cut_hole diameter smaller than local plate dimension
pocket dimensions smaller than base dimensions
boss dimensions positive
rib dimensions positive
linear hole pattern count * spacing fits within base width/height when inferable
```

### composition preflight v0.3

实现文件：

```text
generative_cad/dialects/composition/preflight.py
```

必须检查：

```text
pattern count <= max_pattern_instances
boolean op input count valid
translate/rotate vectors finite
rotation axis_dir not zero vector
```

## 5.6 Strict artifact inspection

当前 builder 对 `inspect_step_with_cadquery` 返回 error 时只 warning。v0.3 要改为 strict default。

在 `build_generative_cad_model` 增加参数：

```python
strict_inspection: bool = True
```

规则：

```text
If inspect=True and strict_inspection=True:
  inspection error must fail build.
If inspect=True and strict_inspection=False:
  inspection error may be warning.
If inspect=False:
  skip inspection, but mark metadata.validation.inspection_validation as {"ok": null, "skipped": true, ...}
```

默认：

```python
inspect=True
strict_inspection=True
```

失败 code：

```text
inspection_unavailable
inspection_body_count_mismatch
inspection_bbox_mismatch
```

---

# 6. Runtime v0.3

## 6.1 Runner 输入

保持：

```python
run_gcad_core(raw, out_step, metadata_path)
run_canonical_gcad(canonical, out_step, metadata_path)
```

但内部必须新增：

```python
from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
```

执行顺序：

```text
_run_components
_run_composition_or_select_final
validate_runtime_postconditions
_export_final_solid
build metadata
build artifact
```

## 6.2 runtime postconditions

新增文件：

```text
generative_cad/runtime/postconditions.py
```

实现：

```python
def validate_runtime_postconditions(canonical, ctx, final_handle_id) -> dict:
    ...
```

返回：

```python
{
  "ok": bool,
  "stage": "runtime_postconditions",
  "issues": [...]
}
```

检查：

```text
final_handle_id exists in object_store
handle type is solid
if require_closed_solid true:
  attempt CadQuery/OCC validity check when available
expected_body_count cannot be validated here unless inspector available after export
```

如果无法检查 closed solid：

```text
strict runtime should not fail solely because method unavailable.
Record warning "runtime_closed_solid_check_unavailable".
STEP inspection will enforce body count.
```

## 6.3 object store typed handles

当前 `RuntimeObjectStore` 已经支持 handles。v0.3 不要求完全重写，但要补齐：

```python
def has(self, handle_id: str) -> bool
def get_typed(self, handle_id: str, expected_type: str) -> Any
```

`get_typed` 必须检查：

```text
handle.type == expected_type
```

否则 raise：

```text
RuntimeTypeError or ValueError
```

所有 handler 解析 solid 时应优先使用 `get_typed`.

## 6.4 composition final selection

当前 `_run_composition_or_select_final` 在多个 component 无 assembly 时 runtime fail。v0.3 要求 validation 提前 fail，但 runtime 仍保留 defensive check。

保留：

```python
if len(non_assembly) != 1:
    raise RuntimeError("multiple components require __assembly__ composition component")
```

但新增测试必须证明 validation 已先 fail。

---

# 7. Metadata v2.1

## 7.1 metadata schema

当前 `generative_metadata_v2` 保留，但新增字段：

```python
"validation": {
  "core_validation": {...},
  "dialect_semantics": {...},
  "geometry_preflight": {...},
  "runtime_postconditions": {...},
  "inspection_validation": {...}
}
```

如果仍称 metadata_version 为 `generative_metadata_v2`，必须兼容旧 validator。

更好的做法：

```text
metadata_version: generative_metadata_v2
metadata_schema_minor: "2.1"
```

不要改成 `generative_metadata_v3`，避免大迁移。

## 7.2 build_generative_metadata 参数

修改：

```python
def build_generative_metadata(
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
    validation: dict | None = None,
    repair_summary: dict | None = None,
) -> dict:
```

默认：

```python
validation = {
  "core_validation": {},
  "dialect_semantics": {},
  "geometry_preflight": {},
  "runtime_postconditions": {},
  "inspection_validation": {},
}
```

## 7.3 validator 加强

`validate_generative_metadata_v2` 新增检查：

```text
validation must be dict
validation.core_validation exists
validation.geometry_preflight exists
validation.inspection_validation exists
source_route == llm_skill_base
native_rebuild_allowed must not appear as true
trust_level in allowed values only
all safety flags true
contract_hash starts sha256:
canonical_graph_hash starts sha256:
runner_version exists
geometry_runtime exists
```

如果 metadata 用于 SW/NX import wrapper，还必须检查：

```text
validation.inspection_validation.ok is True
validation.geometry_preflight.ok is True
validation.core_validation.ok is True or has no errors
```

---

# 8. CanonicalStepArtifact v0.3

## 8.1 Artifact schema

当前 `CanonicalStepArtifact` 保持，但建议加字段：

```python
metadata_version: str = "generative_metadata_v2"
metadata_schema_minor: str = "2.1"
source_graph_hash: str
canonical_graph_hash: str
contract_hashes: dict[str, str]
import_gate: dict
```

如果不想改 Pydantic artifact schema，可在 artifact dict metrics 中提供。

## 8.2 Artifact gate

新增文件：

```text
generative_cad/pipeline/import_artifact.py
```

实现：

```python
def validate_generative_step_artifact_for_native_import(
    step_path: str | Path,
    metadata_path: str | Path,
    *,
    require_inspection_ok: bool = True,
    require_geometry_preflight_ok: bool = True,
    registry_check: bool = True,
) -> dict:
    ...
```

返回：

```python
{
  "ok": bool,
  "issues": [...],
  "metadata": metadata,
  "gate": {
    "step_exists": bool,
    "metadata_exists": bool,
    "metadata_valid": bool,
    "safety_valid": bool,
    "contract_hash_valid": bool,
    "inspection_ok": bool,
    "geometry_preflight_ok": bool,
    "native_rebuild_allowed": False,
    "step_import_allowed": True,
  }
}
```

必须检查：

```text
STEP exists and non-empty
metadata exists and valid JSON
validate_generative_metadata_v2 ok
source_route == llm_skill_base
trust_level <= reference_geometry
all safety flags true
registry contract_hash matches
metadata validation inspection ok
metadata validation geometry_preflight ok
```

失败时绝不调用 SolidWorks/NX。

---

# 9. SolidWorks / NX Generative Import Wrappers

## 9.1 新工具

在 `generative_cad/tools.py` 增加两个工具，不要修改现有 SW/NX 通用工具语义：

```text
generative_cad_import_artifact_to_solidworks
generative_cad_import_artifact_to_nx
```

## 9.2 SolidWorks wrapper

签名：

```python
@tool(
  name="generative_cad_import_artifact_to_solidworks",
  description=(
    "Import a validated Generative CAD canonical STEP artifact into SolidWorks "
    "as native SLDPRT. Requires generative_metadata_v2 to pass strict import gate. "
    "Does not rebuild native feature tree."
  ),
)
def generative_cad_import_artifact_to_solidworks(
    step_path: str,
    metadata_path: str,
    out_sldprt: str,
) -> dict:
    ...
```

实现方式：

```python
gate = validate_generative_step_artifact_for_native_import(...)
if not gate["ok"]:
    return EngineeringActionResult(ok=False, ...)

Then call the same underlying SolidWorksClient import mechanism used by solidworks_import_step_as_part.
```

不要从工具函数直接调用另一个 decorated tool wrapper。如果 `solidworks_import_step_as_part` 逻辑没有可复用 helper，则抽取 helper：

```text
solidworks/importers.py
  import_step_as_sldprt(config, input_step, out_sldprt) -> dict
```

然后原工具和 generative wrapper 都调用 helper。

## 9.3 NX wrapper

签名：

```python
@tool(
  name="generative_cad_import_artifact_to_nx",
  description=(
    "Import a validated Generative CAD canonical STEP artifact into Siemens NX "
    "as native PRT. Requires generative_metadata_v2 to pass strict import gate. "
    "Does not rebuild native feature tree."
  ),
)
def generative_cad_import_artifact_to_nx(
    step_path: str,
    metadata_path: str,
    out_prt: str,
) -> dict:
    ...
```

同理，抽取 helper：

```text
nx/importers.py
  import_step_as_prt(config, job_root, input_step, out_prt) -> dict
```

原 `nx_import_step_as_prt` 和 generative wrapper 共用。

## 9.4 wrapper 返回 metrics

必须包含：

```python
metrics={
  "source_route": "llm_skill_base",
  "source_step": str(step_path),
  "source_metadata": str(metadata_path),
  "native_path": str(out_sldprt or out_prt),
  "strategy": "validated_generative_step_import",
  "native_rebuild_allowed": False,
  "step_import_allowed": True,
  "canonical_graph_hash": ...,
  "selected_dialects": ...,
  "import_gate": gate["gate"],
}
```

warnings 必须包含：

```text
Native file created by importing validated generative canonical STEP.
Native feature tree is not regenerated.
Generative output is reference geometry only.
Not certified, not manufacturing-ready, not installable.
```

---

# 10. Skill System v0.3

当前 `prompts.py` 使用旧 base 概念，必须迁移到 dialect 概念。

## 10.1 新目录

```text
generative_cad/skills/
  __init__.py
  orchestrator.py
  prompts.py
  schemas.py
  domain/
    generic_mechanical.md
    turbomachinery_reference.md
```

当前 markdown 中的：

```text
axisymmetric_base
sketch_extrude_base
loft_sweep_base
```

必须改为：

```text
axisymmetric
sketch_extrude
loft_sweep if registered
composition
```

## 10.2 Skill 概念

Skill 分两级：

```text
Level-1 Domain Skill:
  Used for routing. It decides primitive vs generative vs unsupported and selects dialects.

Level-2 Dialect Usage Skill:
  Used after dialect selection. It instructs LLM how to produce valid RawGcadDocument using selected contracts.
```

## 10.3 schemas.py

新增：

```python
class DialectSelectionItem(BaseModel):
    dialect: str
    version: str
    reason: str

class DomainSkillSelectionItem(BaseModel):
    skill_id: str
    skill_version: str
    reason: str

class DialectSelectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_intent: dict[str, str]
    route_decision: Literal[
        "deterministic_primitive",
        "generative_cad_ir",
        "unsupported"
    ]
    selected_dialects: list[DialectSelectionItem]
    selected_domain_skills: list[DomainSkillSelectionItem]
    unsupported_capabilities: list[str] = []
    safety_notes: list[str] = []
```

Rules:

```text
If route_decision == generative_cad_ir:
  selected_dialects must not be empty.
If multiple non-assembly components are expected:
  selected_dialects must include composition.
If route_decision == deterministic_primitive:
  selected_dialects must be empty.
If route_decision == unsupported:
  unsupported_capabilities must not be empty.
```

## 10.4 orchestrator.py

新增函数：

```python
def load_domain_skill(skill_id: str) -> str:
    ...

def build_level1_routing_prompt(
    user_request: str,
    dialect_catalog: dict,
    domain_skill_ids: list[str] | None = None,
) -> dict:
    ...
```

返回：

```python
{
  "system": LEVEL1_ROUTING_SYSTEM_PROMPT,
  "user": "...",
  "output_schema": DialectSelectionPlan.model_json_schema(),
  "catalog": dialect_catalog,
  "domain_skills": [...]
}
```

新增：

```python
def build_level2_authoring_prompt(
    user_request: str,
    selection_plan: DialectSelectionPlan,
    contracts: dict[str, dict],
    usage_skills: dict[str, str],
) -> dict:
    ...
```

返回：

```python
{
  "system": LEVEL2_AUTHORING_SYSTEM_PROMPT,
  "user": "...",
  "output_schema": RawGcadDocument.model_json_schema(),
  "selected_dialects": ...,
  "contracts": ...,
  "usage_skills": ...,
}
```

新增：

```python
def build_repair_prompt_v2(
    raw_document: dict,
    validation_report: dict,
    repair_state: dict,
) -> dict:
    ...
```

返回 repair patch schema。

## 10.5 Level-1 routing prompt

必须使用以下 prompt 文本作为基础：

```text
You are a CAD grammar routing compiler front-end.

Your job is to select the safest modelling route for a mechanical CAD request.

You must choose exactly one route_decision:
- deterministic_primitive
- generative_cad_ir
- unsupported

Rules:
1. Use deterministic_primitive only when the requested part is already covered by the existing primitive path and high determinism is required.
2. Use generative_cad_ir only when the request can be expressed by registered CAD grammar dialects.
3. Use unsupported when the request needs missing dialects, native CAD feature-tree authoring, structural validation, certification, manufacturing readiness, or arbitrary code.
4. You may only select dialects listed in the provided Dialect Catalog.
5. Do not invent dialect names.
6. Do not invent operation names.
7. Do not output CAD code.
8. Do not output CadQuery, SolidWorks COM, NXOpen, APDL, Python, shell commands, imports, exports, file paths, or subprocesses.
9. Generative turbomachinery output is non-flight reference geometry only.
10. Never claim airworthy, certified, production-ready, manufacturing-ready, installable, or structurally validated status.
11. Output JSON only, matching DialectSelectionPlan schema.
```

## 10.6 Level-2 authoring prompt

必须使用以下 prompt 文本作为基础：

```text
You are a G-CAD Core IR author.

Your job is to produce RawGcadDocument JSON only.

You are not a CAD kernel.
You are not a CadQuery programmer.
You are not a SolidWorks or NX automation script author.
You are a constrained feature-graph author.

Rules:
1. Output only JSON matching RawGcadDocument schema.
2. Use schema_version exactly "g_cad_core_v0.2".
3. Use units exactly "mm".
4. trust_level must be "reference_geometry" or "concept_geometry"; never higher.
5. Use only selected_dialects provided by the routing step.
6. Use only operations listed in the selected dialect contracts.
7. Every node must specify dialect, op, op_version, phase, inputs, outputs, params, required, degradation_policy.
8. Every operation phase must match the contract.
9. Every node output type must match the operation output_types.
10. Every node input type must match the operation input_types.
11. Every component must have owner_dialect and explicit root_node.
12. A non-assembly component may only contain nodes from its owner_dialect.
13. Cross-component composition must happen only inside "__assembly__" using the "composition" dialect.
14. If more than one non-assembly component exists, include "__assembly__" with owner_dialect "composition".
15. The final root node must output "body" of type "solid".
16. constraints.require_step_file must be true.
17. constraints.require_metadata_sidecar must be true.
18. constraints.require_closed_solid must be true.
19. All safety flags must be true.
20. Do not weaken constraints.
21. Do not include file paths.
22. Do not include code.
23. Do not include natural language outside JSON.
24. If the request cannot be expressed with the selected contracts, output a JSON error object with unsupported_capabilities instead of inventing ops.
```

## 10.7 Repair prompt v2

```text
You are a local G-CAD IR repair patch author.

You may only repair the provided RawGcadDocument by returning a local RepairPatchV2 JSON.

Rules:
1. Do not rewrite the entire graph.
2. Do not modify schema_version.
3. Do not modify selected_dialects.
4. Do not modify safety.
5. Do not modify constraints except llm_validation_hints if explicitly allowed.
6. Do not modify node.dialect.
7. Do not modify node.op.
8. Do not modify node.op_version.
9. Do not modify component.owner_dialect.
10. Do not invent dialects.
11. Do not invent operations.
12. Do not weaken validation.
13. Only modify params of target_node unless the validation error explicitly requires changing inputs, outputs, root_node, required, or degradation_policy.
14. If the same error signature repeated, output {"give_up": true, "reason": "..."}.
15. Output JSON only.
```

---

# 11. Repair v0.3

## 11.1 New package

```text
generative_cad/repair/
  __init__.py
  patch.py
  hashes.py
  governor.py
```

Migrate old root `repair_governor.py` to `legacy/repair_governor_v01.py`.

## 11.2 patch.py

Define:

```python
class RepairChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    old_value: Any | None = None
    new_value: Any
    reason: str

class RepairPatchV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_node: str | None = None
    target_component: str | None = None
    changes: list[RepairChange]
    reason: str
    give_up: bool = False
```

Allowed paths:

```text
/nodes/<node_id>/params/<field>
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/nodes/<node_id>/required
/nodes/<node_id>/degradation_policy
/components/<component_id>/root_node
/llm_validation_hints
```

Forbidden paths:

```text
/schema_version
/selected_dialects
/constraints/require_step_file
/constraints/require_metadata_sidecar
/constraints/require_closed_solid
/safety
/nodes/<node_id>/dialect
/nodes/<node_id>/op
/nodes/<node_id>/op_version
/components/<component_id>/owner_dialect
```

## 11.3 hashes.py

Implement:

```python
def raw_graph_hash(raw: RawGcadDocument | dict) -> str
def error_signature_hash(report: ValidationReport | dict) -> str
def repair_patch_hash(patch: RepairPatchV2 | dict) -> str
```

## 11.4 governor.py

Implement:

```python
class RepairStateV2(BaseModel):
    attempts: int = 0
    max_attempts: int = 3
    raw_graph_hashes: list[str] = []
    canonical_graph_hashes: list[str] = []
    error_signature_hashes: list[str] = []
    repair_patch_hashes: list[str] = []
    last_stage_rank: int = 0
```

Stage rank:

```python
STAGE_RANK = {
    "structure": 10,
    "registry": 20,
    "params": 30,
    "ownership": 40,
    "graph": 50,
    "typecheck": 60,
    "phase": 70,
    "composition": 80,
    "safety": 90,
    "canonicalize": 100,
    "dialect_semantics": 110,
    "geometry_preflight": 120,
    "runtime_postconditions": 130,
    "inspection": 140,
}
```

Repair allowed if:

```text
attempts < max_attempts
raw graph hash not repeated
error signature not repeated more than once
stage rank is progressing or params changed
patch hash not repeated
patch does not touch forbidden paths
```

---

# 12. tools.py v0.3

## 12.1 Rename descriptions to dialect

Keep old tool names for backward compatibility:

```text
generative_cad_list_bases
generative_cad_get_base_contract
```

But descriptions must say:

```text
legacy alias: base means dialect
```

Add new canonical names:

```text
generative_cad_list_dialects
generative_cad_get_dialect_contract
generative_cad_validate_ir
generative_cad_build_from_ir
generative_cad_import_artifact_to_solidworks
generative_cad_import_artifact_to_nx
```

Do not remove old tool names yet.

## 12.2 build tool parameters

Modify:

```python
def generative_cad_build_from_ir(
    spec: dict,
    out_step: str,
    inspect: bool = True,
    strict_inspection: bool = True,
) -> dict:
```

Pass through to builder.

## 12.3 capabilities

Add capabilities:

```text
cad.generative.import.solidworks
cad.generative.import.nx
```

Or reuse:

```text
cad.generative.write
cad.solidworks.write
cad.nx.write
filesystem.write
```

Prefer not to add new capability constants unless needed. If adding, update `ENGINEERING_CAPABILITIES`.

---

# 13. Tests Required

Implement all tests below. Do not skip. CadQuery-dependent tests may use `pytest.importorskip("cadquery")`.

## 13.1 Legacy isolation tests

File:

```text
tests/generative_cad/test_gcad_v03_legacy_isolation.py
```

Tests:

```python
def test_new_pipeline_does_not_import_legacy_generative_spec():
    inspect source of validation.pipeline, builder, pipeline.run
    assert "GenerativeCADSpec" not in source
    assert "BASE_REGISTRY" not in source

def test_legacy_modules_are_under_legacy_namespace():
    assert import seekflow_engineering_tools.generative_cad.legacy.ir_v01 works
```

## 13.2 Composition validation tests

File:

```text
tests/generative_cad/test_gcad_v03_composition_validation.py
```

Tests:

```python
test_multiple_components_without_assembly_fails_in_validation
test_multiple_components_without_composition_selected_fails
test_assembly_owner_must_be_composition
test_assembly_root_node_required
test_assembly_root_must_output_body_solid
test_component_root_must_output_body_solid
test_single_component_without_assembly_allowed
```

Update existing `test_multiple_components_without_assembly_fails` expectation:

Current bad behavior:

```python
assert canonical is not None
assert report.ok
```

New expected behavior:

```python
assert canonical is None
assert not report.ok
assert issue code multiple_components_require_assembly
```

## 13.3 Dialect semantics tests

File:

```text
tests/generative_cad/test_gcad_v03_dialect_semantics.py
```

Tests:

```python
test_axisymmetric_requires_revolve_profile_base_solid
test_axisymmetric_rejects_multiple_base_solid_nodes
test_sketch_extrude_requires_extrude_rectangle_base_solid
test_composition_component_must_be_assembly
test_boolean_cut_requires_two_inputs
```

## 13.4 Geometry preflight tests

File:

```text
tests/generative_cad/test_gcad_v03_geometry_preflight.py
```

Tests:

```python
test_preflight_rejects_too_many_nodes
test_axisymmetric_rejects_hole_pattern_outside_outer_radius
test_axisymmetric_rejects_center_bore_larger_than_outer_diameter
test_sketch_extrude_rejects_pocket_larger_than_base
test_composition_rejects_zero_rotation_axis
test_composition_rejects_pattern_count_over_limit
```

## 13.5 Metadata tests

File:

```text
tests/generative_cad/test_gcad_v03_metadata.py
```

Tests:

```python
test_metadata_contains_geometry_preflight_validation
test_metadata_contains_runtime_postconditions
test_metadata_validator_rejects_missing_validation
test_metadata_validator_rejects_false_safety
test_metadata_validator_rejects_contract_hash_mismatch
```

## 13.6 Strict inspection tests

File:

```text
tests/generative_cad/test_gcad_v03_strict_inspection.py
```

Tests:

```python
def test_strict_inspection_unavailable_fails(monkeypatch):
    monkeypatch inspect_step_with_cadquery to return {"error": "mock unavailable"}
    build with inspect=True strict_inspection=True
    assert not ok
    assert error contains inspection_unavailable

def test_non_strict_inspection_unavailable_warns(monkeypatch):
    build with inspect=True strict_inspection=False
    assert ok if STEP and metadata exist
    assert warning contains Inspection unavailable
```

## 13.7 SW/NX import gate tests

File:

```text
tests/generative_cad/test_gcad_v03_native_import_gate.py
```

Tests:

```python
test_import_gate_rejects_missing_metadata
test_import_gate_rejects_invalid_metadata_version
test_import_gate_rejects_false_safety
test_import_gate_rejects_failed_inspection_validation
test_import_gate_rejects_contract_hash_mismatch
test_import_gate_accepts_valid_metadata_and_step
```

These tests must not require SolidWorks or NX.

Wrapper tests should monkeypatch helper import functions:

```python
test_solidworks_wrapper_does_not_call_import_when_gate_fails
test_nx_wrapper_does_not_call_import_when_gate_fails
```

## 13.8 Skill prompt tests

File:

```text
tests/generative_cad/test_gcad_v03_skills.py
```

Tests:

```python
test_level1_prompt_uses_dialect_not_base
test_level2_prompt_forbids_cadquery_solidworks_nx_code
test_level2_prompt_requires_raw_gcad_document
test_repair_prompt_forbids_safety_and_dialect_changes
test_domain_skills_do_not_reference_axisymmetric_base
```

## 13.9 Primitive isolation regression

Keep and extend existing tests:

```python
test_primitive_compiler_registry_no_dialects
test_primitive_registry_no_dialects
test_dialect_registry_no_primitives
test_cad_part_spec_rejects_gcad_fields
```

Add:

```python
test_generative_import_tools_not_registered_as_primitive_builders
```

---

# 14. Implementation Order for Claude Code

Implement exactly in this order.

## Step 1 — Move legacy modules

1. Create `generative_cad/legacy/`.
2. Move old modules into legacy with new names.
3. Add compatibility comments.
4. Fix imports.
5. Run tests.
6. No behavior change yet.

Expected pass:

```text
existing tests still pass except tests that imported old root modules directly.
```

If existing tests import old root modules, update tests to import legacy only if they are legacy tests.

## Step 2 — Add composition validation

1. Create `validation/composition.py`.
2. Add to `validation/pipeline.py` before safety.
3. Update failing existing test expectation.
4. Add new composition tests.

This is P0.

## Step 3 — Add canonical-level dialect semantics

1. Create `validation/dialect_semantics.py`.
2. Add canonical-level validation after canonicalize.
3. Implement minimal validate_component logic in each dialect.
4. Add tests.

This is P0.

## Step 4 — Add geometry preflight v0.3

1. Create `validation/geometry_preflight.py`.
2. Create dialect preflight files.
3. Wire dialect.preflight_component.
4. Add metadata field.
5. Add tests.

This is P0.

## Step 5 — Strict inspection

1. Add `strict_inspection` arg.
2. Fail on inspection error when strict.
3. Write inspection validation into metadata.
4. Add tests.

This is P0.

## Step 6 — Metadata v2.1

1. Extend `build_generative_metadata`.
2. Extend `validate_generative_metadata_v2`.
3. Include core/dialect/preflight/runtime/inspection validation.
4. Add tests.

This is P0.

## Step 7 — Import artifact gate

1. Create `pipeline/import_artifact.py`.
2. Implement gate validation.
3. Add tests.

This is P0.

## Step 8 — SolidWorks/NX wrappers

1. Extract import helpers.
2. Add generative wrappers.
3. Register tools.
4. Add gate tests with monkeypatch.
5. Do not require SolidWorks/NX in tests.

This is P1.

## Step 9 — Skills and prompts

1. Move prompts into `skills/prompts.py`.
2. Add schemas.
3. Add orchestrator.
4. Update markdown domain skills.
5. Add tests.

This is P1.

## Step 10 — Repair v0.3

1. Create repair package.
2. Migrate governor to RawGcadDocument.
3. Add patch validation.
4. Add tests.
5. Do not automatically run repair in builder yet unless trivial.
6. Metadata repair_attempts remains 0 unless orchestrator uses repair.

This is P1.

---

# 15. Acceptance Criteria

The implementation is complete only when:

```text
1. No new code outside legacy imports GenerativeCADSpec.
2. No new code outside legacy imports BASE_REGISTRY.
3. RawGcadDocument remains the only LLM-authored modelling document.
4. validate_and_canonicalize fails multi-component graphs without __assembly__.
5. dialect semantics is part of validation report.
6. geometry preflight is part of validation report and metadata.
7. build_generative_cad_model strict inspection fails when inspection unavailable.
8. metadata validator rejects unsafe or incomplete generative metadata.
9. import gate rejects invalid or uninspected generative artifacts.
10. SolidWorks/NX generative wrappers cannot import without valid metadata.
11. Skill prompts use dialect terminology, not old base terminology.
12. repair governor v0.3 uses RawGcadDocument paths, not feature_graph paths.
13. Existing primitive route tests still pass.
14. Existing CadQuery runner tests still pass.
15. All new tests pass.
```

---

# 16. Specific Code-Level Notes

## 16.1 Do not rewrite everything

Claude Code must avoid unnecessary rewrites. The existing correct components should be extended:

Keep:

```text
ir/raw.py
ir/canonical.py
dialects/base.py
dialects/operation.py
dialects/registry.py
validation/structure.py
validation/registry.py
validation/params.py
validation/ownership.py
validation/graph.py
validation/typecheck.py
validation/phase.py
validation/safety.py
validation/canonicalize.py
runtime/context.py
runtime/object_store.py
runtime/handles.py
runtime/resolve.py
pipeline/run.py
pipeline/metadata.py
builder.py
tools.py
```

Modify surgically.

## 16.2 Report merging helper

If no helper exists, add:

```python
def merge_reports(stage: str, reports: list[ValidationReport]) -> ValidationReport:
    issues = []
    for r in reports:
        issues.extend(r.issues)
    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage=stage,
        issues=issues,
    )
```

## 16.3 Validation exception conversion

All validation stages must be fail-closed:

```python
try:
    report = validator(...)
except Exception as exc:
    return ValidationReport.fail(
        stage=stage_name,
        code=f"{stage_name}_validator_exception",
        message=str(exc),
    )
```

Do not allow validator exceptions to crash agent-facing tools.

## 16.4 Tool output

All tools must return `EngineeringActionResult(...).model_dump()`.

Do not return raw exceptions.

## 16.5 File path safety

All paths must pass:

```python
ensure_inside_workspace(config.workspace_root, path)
ensure_extension(...)
```

before read/write/import.

---

# 17. High-Quality Prompt Assets to Implement

## 17.1 `skills/prompts.py`

Implement these constants.

```python
LEVEL1_ROUTING_SYSTEM_PROMPT = """
You are a CAD grammar routing compiler front-end.

Your task is to select the safest modelling route for a mechanical CAD request.

You must choose exactly one route_decision:
- deterministic_primitive
- generative_cad_ir
- unsupported

Rules:
1. Use deterministic_primitive only when the requested part is covered by the deterministic primitive path and high determinism is required.
2. Use generative_cad_ir only when the requested geometry can be expressed by registered CAD grammar dialects.
3. Use unsupported when the request needs missing dialects, native feature-tree authoring, structural validation, certification, manufacturing readiness, arbitrary code, or unconstrained freeform modelling.
4. You may only select dialects listed in the provided Dialect Catalog.
5. Do not invent dialect names.
6. Do not invent operation names.
7. Do not output CAD code.
8. Do not output CadQuery, SolidWorks COM, NXOpen, APDL, Python, shell commands, imports, exports, file paths, or subprocesses.
9. Generative turbomachinery output is non-flight reference geometry only.
10. Never claim airworthy, certified, production-ready, manufacturing-ready, installable, or structurally validated status.
11. Output JSON only, matching DialectSelectionPlan schema.
"""
```

```python
LEVEL2_AUTHORING_SYSTEM_PROMPT = """
You are a G-CAD Core IR author.

Your task is to produce RawGcadDocument JSON only.

You are not a CAD kernel.
You are not a CadQuery programmer.
You are not a SolidWorks or NX automation script author.
You are a constrained feature-graph author.

Rules:
1. Output only JSON matching RawGcadDocument schema.
2. Use schema_version exactly "g_cad_core_v0.2".
3. Use units exactly "mm".
4. trust_level must be "reference_geometry" or "concept_geometry"; never higher.
5. Use only selected_dialects provided by the routing step.
6. Use only operations listed in the selected dialect contracts.
7. Every node must specify dialect, op, op_version, phase, inputs, outputs, params, required, degradation_policy.
8. Every operation phase must match the contract.
9. Every node output type must match the operation output_types.
10. Every node input type must match the operation input_types.
11. Every component must have owner_dialect and explicit root_node.
12. A non-assembly component may only contain nodes from its owner_dialect.
13. Cross-component composition must happen only inside "__assembly__" using the "composition" dialect.
14. If more than one non-assembly component exists, include "__assembly__" with owner_dialect "composition".
15. The final root node must output "body" of type "solid".
16. constraints.require_step_file must be true.
17. constraints.require_metadata_sidecar must be true.
18. constraints.require_closed_solid must be true.
19. All safety flags must be true.
20. Do not weaken constraints.
21. Do not include file paths.
22. Do not include code.
23. Do not include natural language outside JSON.
24. If the request cannot be expressed with the selected contracts, output a JSON object with unsupported_capabilities instead of inventing ops.
"""
```

```python
REPAIR_PATCH_SYSTEM_PROMPT_V2 = """
You are a local G-CAD IR repair patch author.

You may only repair the provided RawGcadDocument by returning a local RepairPatchV2 JSON.

Rules:
1. Do not rewrite the entire graph.
2. Do not modify schema_version.
3. Do not modify selected_dialects.
4. Do not modify safety.
5. Do not modify constraints.require_step_file.
6. Do not modify constraints.require_metadata_sidecar.
7. Do not modify constraints.require_closed_solid.
8. Do not modify node.dialect.
9. Do not modify node.op.
10. Do not modify node.op_version.
11. Do not modify component.owner_dialect.
12. Do not invent dialects.
13. Do not invent operations.
14. Do not weaken validation.
15. Only modify params of target_node unless the validation error explicitly requires changing inputs, outputs, root_node, required, or degradation_policy.
16. If the same error signature repeated, output {"give_up": true, "reason": "..."}.
17. Output JSON only.
"""
```

---

# 18. Final Architecture Statement

After this implementation, the correct architecture is:

```text
Primitive path:
  CADPartSpec
    → deterministic primitive compiler
    → CadQuery/CQ_Gears deterministic kernel
    → STEP + primitive metadata
    → optional SW/NX STEP import

Generative path:
  Level-1 Skill Routing
    → selected dialects
    → Level-2 Dialect Authoring Context
    → RawGcadDocument
    → Raw validation
    → CanonicalGcadDocument
    → dialect semantic validation
    → geometry preflight
    → fixed runner
    → BaseDialect/OperationSpec handlers
    → runtime postconditions
    → STEP inspection
    → generative metadata
    → CanonicalStepArtifact
    → optional validated SW/NX STEP import
```

These two paths meet only at:

```text
canonical STEP artifact + validated metadata
```

They do not meet at:

```text
CADPartSpec
primitive registry
primitive compiler
geometry_primitives
native SolidWorks/NX feature-tree generation
```

This is the correct v0.3 architecture.
