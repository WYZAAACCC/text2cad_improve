
---

# SeekFlow Generative CAD-IR 架构校正与升级计划书

## 0. 最高优先级原则

本次修改**不是**要把 Generative CAD 做成另一个 Primitive 系统。Primitive 已经存在，且规划文档明确要求新链路不能污染 `cadquery_backend/primitive_compiler.py`、`geometry_primitives/`、`PRIMITIVE_COMPILERS` 或 `CADPartSpec` 既有语义；新链路只能以 **canonical STEP artifact + generative metadata** 合流到主链路后半段。

当前代码已经有正确的强编译器骨架：`RawGcadDocument` 是 LLM 唯一可输出格式，且 Pydantic model 大量使用 `extra="forbid"`；顶层要求 `schema_version="g_cad_core_v0.2"`、`selected_dialects`、`components`、`nodes`、`constraints`、`safety` 等字段，安全字段要求显式为 true，约束字段也要求 fail-closed。([GitHub][1]) 当前 builder 也已经拒绝 legacy `GenerativeCADSpec v0.1`，先 parse，再 `validate_and_canonicalize_with_bundle`，再写 canonical graph 和 validation seed。([GitHub][2]) 这些都必须保留。

但当前架构需要校正：**Dialect Compiler 变强是好事；危险在于部分 dialect op 已经开始像 feature primitive 列表，二级 Skill 和 BasePackage 作为 LLM authoring interface 还没有成为一等公民。**

---

# 1. 本次改造的最终目标

## 1.1 要做成什么

目标架构应固定为：

```text
User Request
  ↓
Level-1 Domain Routing Skill
  ↓
Dialect / BasePackage Selection Plan
  ↓
Load selected BasePackage:
    - Manifest
    - Machine Contract
    - Generated Level-2 Usage Skill
    - Few-shot Graph Fixtures
    - Anti-examples
  ↓
LLM outputs RawGcadDocument
  ↓
Raw parse + Core validation
  ↓
CanonicalGcadDocument
  ↓
Dialect Compiler:
    - OperationSpec params validation
    - graph / ownership / type / phase validation
    - dialect semantic validation
    - geometry preflight
  ↓
Fixed Runtime Harness
  ↓
STEP + generative metadata
  ↓
inspection / artifact validation / import gate
```

这与规划文档一致：LLM 只做“受约束 CAD Grammar 作者”，负责选择 Base/Dialect、输出 Feature Graph、在 repair loop 中输出局部 patch；不负责写 CadQuery、控制文件路径、调用 subprocess、关闭 safety、发明 op、进入 runner。

## 1.2 明确不要做什么

禁止把 Generative CAD 做成：

```text
make_bracket
make_flange
make_turbine_disk
make_mounting_plate
make_gearbox_housing
```

这类 op 是 primitive 伪装。规划文档明确说 Base 不是零件模板，而是一类 CAD 建模范式的 Grammar / Dialect；错误设计是 `turbine_disk_base`、`bracket_base`、`flange_base`，正确方向是 `axisymmetric_base`、`sketch_extrude_base`、`loft_sweep_base`、`shell_housing_base`、`composition_base`。

## 1.3 核心设计口径

请 Claude Code 将术语统一成四层：

```text
Primitive
  已有 deterministic part kernel。
  面向具体零件族，高确定性，不属于本次 generative path。

BasePackage
  LLM-facing authoring package。
  包含 manifest、generated level-2 usage skill、examples、anti-examples、fixtures。
  它不是 runner，不直接生成 CAD。

Dialect
  Compiler/runtime-facing ABI。
  包含 contract、OperationSpec、params_model、semantic validation、preflight、handler。

Runtime
  Geometry execution backend。
  例如 CadQueryRuntime / future OCCRuntime / Build123dRuntime。
```

这能保留“多个 base，一个 base 是一类内容”的产品形态，同时避免 Base 退化成 primitive。

---

# 2. 当前代码审阅结论

## 2.1 已经做对的部分，必须保留

当前目录已经有 `bases`、`dialects`、`ir`、`pipeline`、`repair`、`runtime`、`skills`、`validation` 等模块。([GitHub][3]) `dialects/default_registry.py` 注册了 `axisymmetric`、`sketch_extrude`、`composition` 三个默认 dialect，并 freeze registry。([GitHub][4]) 这与规划文档的 MVP / 第二阶段 / 第三阶段基本一致。

`RawGcadDocument` 的强 schema 方向正确：`RawNode` 只允许 `dialect/op/op_version/phase/inputs/outputs/params` 等固定字段，`RawConstraints` 要求 STEP、metadata、closed solid 显式为 true，`RawSafety` 要求所有 safety flag 显式为 true。([GitHub][1])

`OperationSpec` 方向也正确：它已经定义了 `dialect`、`op`、`op_version`、`phase`、`input_types`、`output_types`、`params_model`、`effects`、`postconditions`、`handler`，这是 Dialect Compiler 的核心 ABI。([GitHub][5])

builder 的 artifact gate 也正确：它检查 canonical graph hash、metadata validation proof、artifact state、`native_rebuild_allowed=False`、`step_import_allowed=False`、`requires_import_gate=True` 等状态一致性。([GitHub][2]) 固定 harness 也明确是 “auto-generated, no LLM CAD code”，并调用 `run_canonical_gcad_from_files`。([GitHub][2])

## 2.2 当前最大偏差

### 偏差 A：`BasePackage` 缺位，`bases/` 与 `dialects/` 概念并存但没有清晰分工

当前 `generative_cad` 目录同时存在 `bases` 和 `dialects`。([GitHub][3]) 同时根部 `base.py` 只是 legacy v0.1 base protocol 的 backward-compat re-export，并提示新代码应使用 `generative_cad.dialects.base`。([GitHub][6])

这说明执行层已经迁移到 `dialects`，但 LLM-facing 的 Base 形态没有被重新定义。结果是：你朋友原规划里的“多个 base 模板”心智模型会消失，而代码里又残留旧 `bases`，造成双架构错觉。

### 偏差 B：二级 Skill 还只是 prompt 参数，不是一等构件

`build_level2_authoring_prompt()` 当前会收集 selected dialect 的 `contract()`，但 `usage_skills` 只是可选入参，默认 `{}`。([GitHub][7]) 这与规划文档中“二级 Skill 必须由 Base Manifest / Base Contract 生成或严格同步，不能手写后长期漂移”的要求不够一致。

更严重的是，`build_level2_tool()` 里存在大量手写 `OP_DESCRIPTIONS` 和 schema description 注入，例如 `revolve_profile`、`cut_center_bore`、`extrude_rectangle`、`cut_hole` 等说明直接硬编码在 orchestrator 中。([GitHub][7]) 这会导致：

```text
contract 更新了，但 OP_DESCRIPTIONS 没更新；
params_model 更新了，但 usage skill 没同步；
dialect 增加 op，但 LLM authoring 层没自动学习；
orchestrator 变成所有 dialect 的 prompt monolith。
```

这正是二级 Skill 机制要避免的问题。

### 偏差 C：`sketch_extrude` 目前偏 feature primitive，而不是完整 sketch grammar

当前 `sketch_extrude` 的 op 列表是：

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

并且 semantic validation 要求 exactly one `base_solid`，且 base_solid 必须是 `extrude_rectangle`。([GitHub][8]) 这作为 MVP 可以接受，但长期会偏向“矩形板件 primitive 库”，泛化能力不足。

真正的 `sketch_extrude` grammar 应该逐步走向：

```text
create_sketch
add_line
add_arc
add_circle
add_slot
add_polyline
add_constraint
close_profile
extrude_profile
cut_profile
pattern_feature
mirror_feature
```

也就是让 LLM 组合 sketch grammar，而不是只能调用固定矩形特征。

### 偏差 D：Level-2 tool schema 有硬编码版本风险

`build_level2_tool()` 里对 node variant 写死 `"op_version": {"const": "1.0.0"}`，而不是使用 `spec.op_version`。([GitHub][7]) Level-1 / selected_dialects schema 也有 `"version": ["0.2.0"]` 这类硬编码。([GitHub][7]) 这会直接破坏规划文档中的 op_version 扩展目标：新增参数或升级 op 时，应只改对应 op 的 params_model 和 handler，不改 Core IR / Core Validator / Pipeline。

### 偏差 E：builder 仍通过 subprocess 跑固定 harness

这不是安全事故，因为 harness 是固定代码，不是 LLM 代码；但目前 builder 是直接 `subprocess.run([sys.executable, script_path], ...)`。([GitHub][2]) 后续建议统一接入项目已有 sandbox / runner abstraction，至少要预留 `ExecutionBackend` 接口。这个优先级低于 BasePackage / 二级 Skill，但要列入路线图。

---

# 3. Claude Code 执行总原则

Claude Code 修改时必须遵守：

```text
1. 不修改 deterministic primitive 主链路语义。
2. 不修改 cadquery_backend/primitive_compiler.py。
3. 不把 generative dialect 注册进 primitive registry。
4. 不新增 make_xxx_part / make_flange / make_bracket 这类零件 op。
5. 不让 LLM 输出 CadQuery / SolidWorks / NX / APDL 代码。
6. 不允许 RawGcadDocument 绕过 validator 直接进入 dialect runner。
7. 所有 dialect-specific 参数仍只能放在 node.params。
8. node.params 只能由 OperationSpec.params_model 解释和校验。
9. 多 dialect 组合只能通过 composition dialect。
10. 新增 op 参数不得修改 Core IR、Core Validator、Pipeline。
11. 所有 unknown dialect/op/version 必须 fail closed。
12. 不做 fuzzy matching，不做 silent fallback。
13. generative output trust_level 不得高于 reference_geometry。
14. 任何 artifact 只能是 canonical STEP + metadata，不是 primitive。
```

---

# 4. 目标目录结构

将当前结构校正为：

```text
src/seekflow_engineering_tools/generative_cad/
  base_packages/
    __init__.py
    registry.py
    models.py
    generator.py
    validators.py

    axisymmetric/
      __init__.py
      package.py
      examples/
        simple_washer.raw.json
        flange_with_bolt_pattern.raw.json
        stepped_hub.raw.json
      anti_examples/
        make_turbine_disk_bad.json
        direct_cadquery_bad.md
      fixtures/
        golden_manifest.json
        golden_level2_usage.md

    sketch_extrude/
      __init__.py
      package.py
      examples/
        base_plate.raw.json
        bracket_reference.raw.json
      anti_examples/
      fixtures/

    composition/
      __init__.py
      package.py
      examples/
        two_component_union.raw.json
      anti_examples/
      fixtures/

  dialects/
    axisymmetric/
    sketch_extrude/
    composition/
    sketch_profile/       # later phase
    loft_sweep/           # later phase
    shell_housing/         # later phase

  skills/
    domain/
      generic_mechanical.md
      turbomachinery_reference.md
    orchestrator.py
    prompts.py
    schemas.py
    level2_usage.py        # new: generated usage-skill builder
    authoring_context.py   # new: compact context packer

  validation/
  runtime/
  pipeline/
  repair/
  benchmarks/             # optional or tests-side
```

重点：`base_packages/` 是 LLM-facing；`dialects/` 是 compiler/runtime-facing。

---

# 5. Phase 1：建立 BasePackage 一等构件

## 5.1 新增 `base_packages/models.py`

实现以下 Pydantic models：

```python
class BasePackageId(str, Enum):
    AXISYMMETRIC = "axisymmetric"
    SKETCH_EXTRUDE = "sketch_extrude"
    COMPOSITION = "composition"

class BasePackageManifest(BaseModel):
    package_id: str
    dialect_id: str
    dialect_version: str
    title: str
    summary: str
    modeling_paradigm: str
    typical_geometry: list[str]
    typical_parts: list[str]
    main_ops: list[str]
    unsupported_cases: list[str]
    safety_notes: list[str]
    primitive_preferred_when: list[str]
    composition_notes: list[str] = Field(default_factory=list)

class BasePackageExample(BaseModel):
    example_id: str
    title: str
    user_request: str
    raw_document: dict
    expected_dialects: list[str]
    expected_validation_stages: list[str]
    notes: list[str] = Field(default_factory=list)

class BasePackage(BaseModel):
    manifest: BasePackageManifest
    level2_usage_markdown: str
    examples: list[BasePackageExample]
    anti_examples: list[dict] = Field(default_factory=list)
    contract_hash: str
```

要求：

```text
BasePackage 不导入 CadQuery。
BasePackage 不执行 geometry。
BasePackage 不包含 runner 源码。
BasePackage 可以读取 dialect.contract() 和 op_specs()。
BasePackage 的 contract_hash 必须来自 dialect contract stable hash。
```

## 5.2 新增 `base_packages/registry.py`

实现：

```python
class BasePackageRegistry:
    def register(package: BasePackage) -> None
    def get(package_id: str) -> BasePackage | None
    def require(package_id: str) -> BasePackage
    def list() -> list[str]
    def export_manifest_catalog() -> dict
    def freeze() -> None
```

并提供：

```python
@lru_cache(maxsize=1)
def default_base_package_registry() -> BasePackageRegistry:
    ...
```

注册 `axisymmetric`、`sketch_extrude`、`composition` 三个 package。

验收标准：

```text
tests/generative_cad/test_base_package_registry.py
  - test_default_base_packages_registered
  - test_base_package_id_matches_dialect_id
  - test_base_package_contract_hash_stable
  - test_base_package_does_not_import_runtime_or_cadquery
```

---

# 6. Phase 2：二级 Skill 自动生成

## 6.1 新增 `skills/level2_usage.py`

实现：

```python
def generate_level2_usage_skill(
    *,
    dialect,
    package_manifest: BasePackageManifest,
    include_examples: bool = True,
    max_examples: int = 3,
) -> str:
    ...
```

生成 markdown，必须包含以下 sections：

```text
# Dialect Usage Skill: <dialect_id>

## Purpose
说明该 dialect 的建模范式，不是具体零件模板。

## When to use
来自 BasePackageManifest.typical_geometry / typical_parts。

## When not to use
来自 unsupported_cases / primitive_preferred_when。

## Core graph pattern
说明 component / nodes / root_node / inputs / outputs 组织方式。

## Phase order
来自 dialect.phase_order。

## Operations
逐个从 OperationSpec 生成：
- op
- op_version
- phase
- input_types
- output_types
- effects
- postconditions
- params schema 摘要
- common mistakes
- geometry notes

## Valid graph skeletons
由 examples 自动抽取。

## Anti-patterns
- make_part style op
- direct CAD code
- unknown op
- cross-dialect direct call
- safety false
- missing metadata constraints

## Repair hints
说明局部 patch 策略。
```

关键要求：

```text
不要在 orchestrator.py 里手写 OP_DESCRIPTIONS。
不要把 schema description 散落在 build_level2_tool 里。
描述信息来源顺序：
  1. OperationSpec metadata / params_model Field(description=...)
  2. dialect contract
  3. package manifest
  4. curated usage notes
```

## 6.2 扩展 `OperationSpec`

当前 `OperationSpec` 已经有核心 ABI 字段。([GitHub][5]) 为了生成高质量 Level-2 Skill，请增加可选字段：

```python
class OperationSpec(BaseModel):
    ...
    summary: str | None = None
    usage_notes: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)
    anti_examples: list[dict] = Field(default_factory=list)
    llm_param_hints: dict[str, str] = Field(default_factory=dict)
```

要求：

```text
新增字段不能影响 validation semantics。
新增字段只用于 prompt / skill generation / docs。
existing tests must still pass。
```

## 6.3 修改 `skills/orchestrator.py`

### 当前问题

`build_level2_authoring_prompt()` 现在直接返回 `usage_skills or {}`，没有默认自动生成。([GitHub][7])

### 目标改法

修改为：

```python
def build_level2_authoring_prompt(...):
    ...
    if usage_skills is None:
        usage_skills = {}
        for sd in selection_plan.selected_dialects:
            pkg = BASE_PACKAGE_REGISTRY.get(sd.dialect)
            dialect = DIALECT_REGISTRY.get(sd.dialect)
            if pkg and dialect:
                usage_skills[sd.dialect] = generate_level2_usage_skill(
                    dialect=dialect,
                    package_manifest=pkg.manifest,
                    include_examples=True,
                )
```

如果找不到 package：

```text
fail closed in strict mode；
or return explicit diagnostic in non-strict developer mode。
```

### 新增参数

```python
strict_usage_skill: bool = True
```

默认 true。

验收标准：

```text
test_level2_prompt_auto_loads_usage_skill
test_level2_prompt_fails_when_selected_dialect_has_no_base_package
test_level2_usage_skill_mentions_phase_order
test_level2_usage_skill_mentions_params_model_fields
test_level2_usage_skill_contains_no_runner_source
```

---

# 7. Phase 3：把 `build_level2_tool()` 从手写 prompt monolith 改成 schema compiler

## 7.1 当前问题

`build_level2_tool()` 里有硬编码中文 `OP_DESCRIPTIONS`，并写死 `"op_version": {"const": "1.0.0"}`。([GitHub][7]) 这会使 op_version 扩展机制失效，也让 orchestrator 变成 dialect 知识垃圾桶。

## 7.2 目标设计

新增：

```text
skills/tool_schema_compiler.py
```

实现：

```python
def compile_level2_tool_schema(
    *,
    selected_dialects: list[str] | None = None,
    registry: DialectRegistry,
    base_package_registry: BasePackageRegistry,
) -> dict:
    ...
```

规则：

```text
1. 从 RawGcadDocument.model_json_schema() 开始。
2. selected_dialects enum 来自 registry.list()。
3. dialect version enum 来自 dialect.version，不写死 "0.2.0"。
4. node anyOf variants 来自 OperationSpec。
5. node.op_version const 必须是 spec.op_version，不写死 "1.0.0"。
6. params schema 来自 spec.params_model.model_json_schema()。
7. description 来自 spec.summary / usage_notes / params_model field descriptions。
8. outputs prefixItems 来自 spec.output_types 和 optional output name policy。
9. 不在 compiler 中写具体 op 的中文说明。
```

## 7.3 替换 orchestrator 逻辑

`build_level2_tool()` 应变为薄包装：

```python
def build_level2_tool(contracts: dict[str, dict] | None = None) -> dict:
    schema = compile_level2_tool_schema(...)
    return {
        "type": "function",
        "function": {
            "name": "generate_raw_gcad_document",
            "description": "...",
            "parameters": schema,
        },
    }
```

验收测试：

```text
test_level2_tool_uses_spec_op_version
test_level2_tool_no_hardcoded_op_descriptions
test_level2_tool_schema_updates_when_new_op_registered
test_level2_tool_schema_uses_params_model_schema
test_level2_tool_rejects_unknown_op_by_schema
```

---

# 8. Phase 4：治理 `bases/` 与 `dialects/` 双源头

## 8.1 目标

不要让 `bases/` 和 `dialects/` 都像执行层。执行层只能是 `dialects/`。

## 8.2 二选一

### 推荐方案：把旧 `bases/` 迁移为 legacy

```text
generative_cad/bases/
  → generative_cad/legacy/bases_v01/
```

并在旧 import 处保留兼容 re-export，但默认禁用。

### 或者：重定义 `bases/` 为 package alias

如果不想改路径太多，可以让：

```text
generative_cad/bases/
```

只 re-export：

```text
generative_cad/base_packages/
```

并明确：

```python
"""LLM-facing BasePackage definitions.

This package does not execute geometry.
Runtime execution lives in generative_cad.dialects.
"""
```

## 8.3 禁止

```text
禁止在 bases/ 里放 handler。
禁止在 bases/ 里导入 CadQuery。
禁止在 bases/ 里执行 geometry。
禁止 bases/ 调用 dialect.run_component。
```

验收测试：

```text
test_bases_package_has_no_cadquery_import
test_bases_package_has_no_runtime_handlers
test_dialects_are_only_execution_surface
test_legacy_base_import_requires_compat_flag_if_applicable
```

---

# 9. Phase 5：防止 Dialect 退化成 Primitive

## 9.1 新增 governance validator

新增：

```text
dialects/governance.py
```

实现：

```python
FORBIDDEN_PART_TOKENS = {
    "bracket", "flange", "turbine_disk", "gearbox",
    "bearing_seat", "mounting_plate", "shaft_with_keyway",
    "impeller", "pump_housing",
}

FORBIDDEN_OP_PREFIXES = {
    "make_", "create_standard_", "generate_part_", "build_part_",
}

def validate_dialect_governance(dialect) -> ValidationReport:
    ...
```

检查：

```text
dialect_id 不应包含具体零件 token。
op 名不能是 make_xxx concrete part。
manifest title/summary 不能声称 manufacturing-ready。
OperationSpec.summary 不能引导为具体零件模板。
```

注意：`axisymmetric` 可以在 `typical_parts` 中出现 flange / hub / disk，因为这是 LLM routing info；但 `dialect_id` / `op` 不能是具体零件。

## 9.2 在 registry 注册时执行

`DialectRegistry.register()` 或 `build_default_registry()` 后执行治理检查。默认 fail closed。

验收测试：

```text
test_reject_part_named_dialect
test_reject_make_part_operation
test_allow_typical_parts_in_manifest
test_allow_axisymmetric_revolve_profile
```

---

# 10. Phase 6：提升 `sketch_extrude` 泛化能力

## 10.1 当前状态

当前 `sketch_extrude` 强制 `base_solid` 为 `extrude_rectangle`。([GitHub][8]) 这适合早期板件，但泛化不够。

## 10.2 不要立刻破坏现有 op

保留现有 op 作为 v0.2 compatibility：

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

但新增一个真正 grammar 层：

```text
sketch_profile dialect
```

或在 `sketch_extrude` 中新增 v0.3 ops。

推荐新增独立 `sketch_profile` dialect，避免一次性破坏旧 tests。

## 10.3 新增 `sketch_profile` dialect

路径：

```text
dialects/sketch_profile/
  __init__.py
  dialect.py
  params.py
  handlers.py
  manifest.py
  contract.py
  preflight.py
```

MVP op：

```text
create_2d_sketch
add_line_segment
add_arc_segment
add_circle
add_slot
add_polyline
close_profile
extrude_profile
cut_profile
```

### ValueType 扩展

如果当前 `ValueType` 已支持 `profile`、`curve`、`plane` 等，则复用；如果不够，最小新增：

```text
sketch
profile
feature_ref
```

但注意：Core IR 只知道 ValueType，不知道具体 sketch 参数。

### 示例 graph

```json
{
  "component": "base_plate",
  "dialect": "sketch_profile",
  "nodes": [
    {
      "op": "create_2d_sketch",
      "outputs": [{"name": "sketch", "type": "sketch"}]
    },
    {
      "op": "add_polyline",
      "inputs": [{"node": "n_sketch", "output": "sketch"}],
      "outputs": [{"name": "profile", "type": "profile"}]
    },
    {
      "op": "extrude_profile",
      "inputs": [{"node": "n_profile", "output": "profile"}],
      "outputs": [{"name": "body", "type": "solid"}]
    }
  ]
}
```

## 10.4 修改 Level-1 routing

`generic_mechanical` domain skill 应优先：

```text
简单矩形板件 → sketch_extrude
任意草图轮廓 / 非矩形板件 / L bracket / profile-driven part → sketch_profile
旋转体 → axisymmetric
多组件组合 → composition
```

## 10.5 验收测试

```text
test_sketch_profile_can_create_non_rectangular_plate
test_sketch_profile_extrude_profile_outputs_solid
test_sketch_profile_unknown_constraint_fails_closed
test_sketch_profile_does_not_add_part_specific_ops
test_sketch_profile_level2_skill_generated_from_contract
```

---

# 11. Phase 7：Axisymmetric 保持 grammar，不要变成 turbine_disk primitive

## 11.1 当前状态

`axisymmetric` 的 grammar 方向相对健康，因为 `revolve_profile` 是真正泛化 op；`cut_center_bore`、`cut_annular_groove`、`cut_circular_hole_pattern` 也仍是通用旋转体特征。

## 11.2 改进方向

新增泛化 op，而不是零件 op：

```text
define_radial_zone
cut_radial_slot_pattern
cut_axial_slot_pattern
add_annular_boss
apply_edge_treatment_by_selector
create_reference_frame
```

禁止：

```text
make_turbine_disk
make_flange
make_pulley
make_rotor
```

## 11.3 Level-2 Skill 示例要多样化

BasePackage examples 不要只放 turbine disk，应包含：

```text
washer
flange-like reference geometry
stepped hub
pulley-like reference geometry
rotating spacer
ring with bolt circle
```

这样 LLM 会学到 axisymmetric 是 grammar，而不是 turbine_disk template。

验收测试：

```text
test_axisymmetric_examples_cover_multiple_part_intents
test_axisymmetric_usage_skill_never_says_make_turbine_disk
test_axisymmetric_op_names_are_generic
```

---

# 12. Phase 8：Composition 边界收紧

## 12.1 当前状态

`composition` 已经作为多 dialect 组合层存在，规划文档也要求多 Base 不能互相调用，只能通过 composition dialect 和 typed RuntimeValue 组合。

## 12.2 需要强化的规则

composition 只允许：

```text
place_component
align_frame
linear_pattern_component
circular_pattern_component
boolean_union
boolean_cut
boolean_intersect
merge_solids
translate_solid
rotate_solid
```

禁止：

```text
composition.create_sketch
composition.cut_hole
composition.add_rib
composition.make_assembly_part
composition.freeform_cad_op
```

## 12.3 新增 validation

```text
validation/composition.py
```

增强：

```text
1. composition component id 必须是 "__assembly__" 或显式 assembly kind。
2. composition op 不能创建复杂 primitive geometry。
3. composition op 输入必须来自 component output handle 或 previous composition node。
4. 非 composition dialect 不得直接引用其他 dialect 的 internal node，除非通过 component output。
5. composition boolean 输入数量必须匹配 OperationSpec。
```

验收测试：

```text
test_cross_dialect_internal_node_reference_rejected
test_cross_dialect_component_output_allowed_via_composition
test_composition_cannot_create_new_sketch_geometry
test_composition_boolean_requires_component_outputs
```

---

# 13. Phase 9：Repair Loop 产品化

## 13.1 当前状态

`build_repair_prompt_v2()` 已经存在，返回 `RepairPatchV2` schema，并把 raw document、validation issues、repair state 交给 LLM。([GitHub][7]) 这只是 prompt builder，还不是完整闭环。

## 13.2 目标

实现：

```text
repair/governor.py
repair/patch.py
repair/session.py
repair/hashes.py
```

Repair loop 必须严格遵守规划：

```text
只允许局部 patch；
不能重写整个 graph；
不能修改 safety；
不能放宽 validation contract；
不能发明 base/op；
不能修改 op schema；
记录 graph hash、error signature、repair patch hash；
重复 graph 停止；
重复 error 停止；
validation stage 不前进停止；
超过 max_attempts 停止。
```

这些规则来自规划文档，应视为硬约束。

## 13.3 实现接口

```python
class RepairSessionState(BaseModel):
    attempt: int
    max_attempts: int
    seen_graph_hashes: set[str]
    seen_error_signatures: set[str]
    last_stage_reached: str | None
    patches: list[AppliedRepairPatch]
    stopped_reason: str | None = None

def apply_repair_patch(raw: dict, patch: RepairPatchV2) -> dict:
    ...

def run_repair_iteration(raw, validation_report, state, llm_patch_provider):
    ...
```

## 13.4 Patch 限制

只允许 JSON Pointer 路径：

```text
/nodes/<idx>/params/...
/nodes/<idx>/inputs/...
/nodes/<idx>/outputs/...
/nodes/<idx>/phase
/components/<idx>/root_node
/constraints/expected_bbox_mm
/constraints/bbox_tolerance_mm
```

禁止路径：

```text
/safety/*
/schema_version
/trust_level
/selected_dialects
/components/<idx>/owner_dialect
/nodes/<idx>/dialect
/nodes/<idx>/op
/nodes/<idx>/op_version
```

除非 repair 类型是系统内部 migration，不允许 LLM 修改。

验收测试：

```text
test_repair_rejects_safety_change
test_repair_rejects_unknown_op_change
test_repair_rejects_selected_dialects_change
test_repair_stops_on_repeated_graph_hash
test_repair_stops_on_repeated_error_signature
test_repair_stops_when_stage_not_advancing
test_repair_allows_param_patch
```

---

# 14. Phase 10：Metadata 与 BasePackage provenance

## 14.1 当前 metadata 要补充

规划要求 metadata 至少包含：

```text
metadata_version
source_route
trust_level
schema_version
selected_dialects
dialect versions
op versions
feature_graph_hash
canonical_graph_hash
base_contract_hash
runner_version
geometry_runtime
repair_attempts
validation stages
warnings
degraded_features
safety flags
source_ir_path
step_path
```



当前 builder 已经做了 artifact/metadata hash 和 state consistency checks。([GitHub][2]) 需要新增 BasePackage provenance：

```text
base_package_ids
base_package_versions
base_package_manifest_hashes
level2_usage_skill_hashes
examples_used
anti_examples_used
tool_schema_hash
```

## 14.2 目标

`generative_metadata` 中新增：

```json
{
  "authoring_context": {
    "level1_domain_skills": ["generic_mechanical"],
    "base_packages": [
      {
        "package_id": "axisymmetric",
        "dialect_id": "axisymmetric",
        "manifest_hash": "...",
        "level2_usage_skill_hash": "...",
        "contract_hash": "..."
      }
    ],
    "tool_schema_hash": "...",
    "prompt_context_hash": "..."
  }
}
```

验收测试：

```text
test_metadata_contains_base_package_provenance
test_metadata_contains_level2_usage_skill_hash
test_metadata_contains_tool_schema_hash
test_metadata_fails_on_contract_hash_mismatch
```

---

# 15. Phase 11：Benchmark / Fixture Corpus

## 15.1 新增测试数据目录

```text
tests/fixtures/generative_cad/base_packages/
  axisymmetric/
    washer.json
    flange_reference.json
    stepped_hub.json
    pulley_reference.json
  sketch_extrude/
    simple_base_plate.json
    bracket_reference.json
  sketch_profile/
    l_bracket_profile.json
    triangular_plate.json
  composition/
    plate_plus_boss_union.json
```

## 15.2 每个 fixture 包含

```json
{
  "id": "axisymmetric_washer_001",
  "user_request": "Create a simple reference washer...",
  "route_expected": "generative_cad_ir",
  "selected_dialects_expected": ["axisymmetric"],
  "raw_document": {},
  "expected_metrics": {
    "body_count": 1,
    "bbox_range_mm": {
      "x": [79, 81],
      "y": [79, 81],
      "z": [9, 11]
    }
  },
  "semantic_checks": [
    {"kind": "has_center_bore"},
    {"kind": "has_closed_solid"}
  ]
}
```

## 15.3 Metrics

新增 benchmark runner：

```text
tests/generative_cad/test_generative_cad_benchmark_fixtures.py
```

指标：

```text
parse_success
core_validation_success
canonicalize_success
geometry_preflight_success
runtime_success
step_exists
metadata_exists
inspection_success
semantic_acceptance_success
```

不要要求所有 fixture 都实际跑 CadQuery，如果 CI 环境缺少 CAD 依赖，可分成：

```text
unit fixtures：只测 parse / validate / canonicalize
runtime fixtures：有 cadquery 时跑 STEP
```

验收测试：

```text
test_all_fixture_raw_documents_parse
test_all_fixture_raw_documents_canonicalize
test_fixture_contract_hash_matches_current_dialect
test_fixture_no_part_specific_op_names
```

---

# 16. Phase 12：Prompt / Skill 质量治理

## 16.1 Level-1 Skill

当前 Level-1 已经会加载 domain skill，并附带 primitive catalog 和 dialect catalog，让 LLM 在 deterministic primitive、generative_cad_ir、unsupported 之间路由。([GitHub][7]) 这个方向保留。

但要增强：

```text
1. 如果 primitive 精确匹配且用户需要高可信工程零件，优先 primitive。
2. 如果用户要泛化 reference geometry，走 generative_cad_ir。
3. 如果用户要求 certified / airworthy / manufacturing-ready，必须 unsupported 或降级说明。
4. 如果请求是复杂自由曲面但缺少 loft_sweep/shell_housing 能力，必须 unsupported，不要硬塞 axisymmetric/sketch_extrude。
```

## 16.2 Level-2 Skill

每个 BasePackage 必须有自动生成的 Level-2 skill，并允许人工补充：

```text
manual_notes.md
```

但最终 skill 应由：

```text
generated_from_contract.md + manual_notes.md + examples_summary.md
```

合成，且写入 hash。

## 16.3 Anti-examples

每个 BasePackage 至少 3 个 anti-example：

```text
1. 发明不存在 op。
2. 使用 make_xxx concrete part op。
3. 直接输出 CadQuery code。
4. 关闭 safety。
5. 跨 dialect 直接引用内部 node。
```

验收测试：

```text
test_each_base_package_has_minimum_examples
test_each_base_package_has_anti_examples
test_level2_skill_mentions_forbidden_patterns
test_level2_skill_does_not_include_runner_source
```

---

# 17. Phase 13：Execution Backend 抽象

这个优先级低于 BasePackage / 二级 Skill，但建议做接口预留。

## 17.1 当前状态

builder 使用 fixed harness，但通过 `subprocess.run` 直接执行。([GitHub][2])

## 17.2 目标接口

```python
class ExecutionBackend(Protocol):
    def run_python_harness(
        self,
        script_path: Path,
        cwd: Path,
        timeout_seconds: int,
    ) -> ExecutionResult: ...

class LocalSubprocessBackend:
    ...

class ProcessSandboxBackend:
    ...

class ContainerSandboxBackend:
    ...
```

builder 默认使用 `LocalSubprocessBackend`，但保留 config 注入点。

验收测试：

```text
test_builder_uses_execution_backend_abstraction
test_execution_backend_timeout_fail_closed
test_execution_backend_captures_stdout_stderr_tail
```

---

# 18. Phase 14：文档与 ADR

新增：

```text
docs/generative_cad/ADR-001-basepackage-vs-dialect-vs-primitive.md
docs/generative_cad/ADR-002-level2-skill-generation.md
docs/generative_cad/ADR-003-dialect-governance-no-primitive-regression.md
docs/generative_cad/README.md
```

## ADR-001 必须写清楚

```text
Primitive = deterministic part kernel。
BasePackage = LLM-facing authoring package。
Dialect = compiler/runtime ABI。
Skill = LLM guidance, not executor。
Contract = machine validation interface。
Runtime = geometry backend。
```

## ADR-002 必须写清楚

```text
二级 Skill 从 BasePackage + Dialect Contract + OperationSpec 生成。
禁止手写长期漂移的 op schema 描述。
manual notes 只能补充建模策略，不能覆盖 params_model。
```

## ADR-003 必须写清楚

```text
Dialect Compiler 更强，不等于 primitive。
禁止 part-named dialect。
禁止 make_part op。
稳定 graph pattern 可以人工晋升 Primitive，但不能反向污染 Dialect。
```

---

# 19. 建议提交顺序

请 Claude Code 按以下 PR/commit 顺序执行，避免大爆炸重构。

## Commit 1：BasePackage models + registry

文件：

```text
generative_cad/base_packages/models.py
generative_cad/base_packages/registry.py
generative_cad/base_packages/__init__.py
```

测试：

```text
test_base_package_registry.py
```

## Commit 2：为现有三个 dialect 建 BasePackage

文件：

```text
base_packages/axisymmetric/package.py
base_packages/sketch_extrude/package.py
base_packages/composition/package.py
```

测试：

```text
test_base_packages_existing_dialects.py
```

## Commit 3：Level-2 usage skill generator

文件：

```text
skills/level2_usage.py
skills/authoring_context.py
```

测试：

```text
test_level2_usage_generation.py
```

## Commit 4：orchestrator 自动加载 Level-2 usage skill

文件：

```text
skills/orchestrator.py
```

测试：

```text
test_skills_orchestrator_level2.py
```

## Commit 5：tool schema compiler 替换 hard-coded OP_DESCRIPTIONS

文件：

```text
skills/tool_schema_compiler.py
skills/orchestrator.py
```

测试：

```text
test_level2_tool_schema_compiler.py
```

## Commit 6：Dialect governance

文件：

```text
dialects/governance.py
dialects/registry_core.py 或 default_registry.py
```

测试：

```text
test_dialect_governance.py
```

## Commit 7：Base/Dialect legacy cleanup

文件：

```text
generative_cad/bases/*
generative_cad/legacy/*
generative_cad/base.py
```

测试：

```text
test_no_legacy_base_ambiguity.py
```

## Commit 8：Metadata provenance

文件：

```text
pipeline/metadata_v3.py
pipeline/artifact.py
builder.py
```

测试：

```text
test_generative_metadata_base_package_provenance.py
```

## Commit 9：Repair loop hardening

文件：

```text
repair/session.py
repair/governor.py
repair/patch.py
repair/hashes.py
```

测试：

```text
test_repair_loop_governance.py
```

## Commit 10：Benchmark fixtures

文件：

```text
tests/fixtures/generative_cad/base_packages/*
tests/generative_cad/test_generative_cad_fixtures.py
```

## Commit 11：可选 sketch_profile dialect

这一 commit 可以单独做，不要和治理重构混在一起。

---

# 20. 最终验收清单

完成后必须满足：

```text
[ ] deterministic primitive tests 全部仍通过。
[ ] generative builder 仍拒绝 legacy v0.1 feature_graph spec。
[ ] RawGcadDocument 仍 fail-closed。
[ ] safety false 仍 fail。
[ ] constraints 放松仍 fail。
[ ] unknown dialect/op/version 仍 fail。
[ ] selected dialect 必须有 BasePackage。
[ ] Level-2 usage skill 默认自动生成。
[ ] Level-2 skill 不包含 runner 源码。
[ ] build_level2_tool 不再手写 OP_DESCRIPTIONS。
[ ] build_level2_tool 的 op_version 来自 OperationSpec。
[ ] Dialect op 不能是 make_xxx concrete part。
[ ] sketch_extrude 现有 fixture 不破坏。
[ ] 新增 fixture 能证明 generative path 的泛化，而不是 primitive 伪装。
[ ] metadata 包含 BasePackage / Level-2 Skill / tool schema provenance。
[ ] repair loop 只能局部 patch，不能改 safety / op / dialect。
[ ] composition 是唯一跨 dialect 组合路径。
```

---

# 21. 给 Claude Code 的简短任务提示

可以把下面这段直接放到 Claude Code：

```text
You are modifying SeekFlow generative_cad. The goal is NOT to turn the Dialect Compiler into another primitive system. The deterministic primitive path already exists and must not be touched.

Keep and strengthen the Dialect Compiler architecture, but restore the intended LLM-facing BasePackage / two-level Skill design.

Implement BasePackage as an LLM authoring package, not an executor:
- manifest
- generated level-2 usage skill
- examples
- anti-examples
- contract hash
- no CadQuery import
- no runtime handlers

Dialect remains the compiler/runtime ABI:
- contract
- OperationSpec
- params_model
- semantic validation
- geometry preflight
- run_component

Refactor skills/orchestrator.py so Level-2 authoring automatically loads generated usage skills from selected BasePackages. Move hard-coded operation descriptions out of build_level2_tool into OperationSpec metadata / generated Level-2 usage skills. Create a tool_schema_compiler that builds per-op JSON schemas from OperationSpec, using spec.op_version and dialect.version, not hard-coded "1.0.0" or "0.2.0".

Add governance so dialects and ops cannot become concrete part primitives:
- reject part-named dialects
- reject make_xxx concrete part ops
- allow typical_parts only in manifest routing text
- keep graph grammar generic

Do not modify:
- cadquery_backend/primitive_compiler.py
- geometry_primitives/
- primitive registries
- CADPartSpec semantics

All RawGcadDocument output must still pass parse -> validation -> canonicalization before any runtime execution. Output remains canonical STEP + generative metadata only.

Add tests for BasePackage registry, Level-2 skill generation, tool schema compiler, no primitive regression, metadata provenance, repair patch restrictions, and fixture validation.
```

---

最终判断：**当前强 Dialect Compiler 是正确方向，不要削弱；要补的是 LLM-facing BasePackage、自动生成二级 Skill、泛化 grammar op、治理规则和 benchmark/repair 闭环。** 这样它才有相对 Primitive 的价值：Primitive 提供确定性，Generative CAD-IR 提供受控泛化。

[1]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[2]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/builder.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[3]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad at main · WYZAAACCC/seekflow-engineering · GitHub"
[4]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/default_registry.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/default_registry.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[5]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[6]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/base.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/base.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[7]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/orchestrator.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/orchestrator.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[8]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/dialect.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/dialect.py at main · WYZAAACCC/seekflow-engineering · GitHub"
