# Dialect Compiler Context Rebuild Report

**视角**: C 编译器内核 + SolidWorks/NX CAD 内核 + 高可靠 Python 工程
**审计日期**: 2026-06-05
**代码基线**: v6.3 (git commit 8a1c742 及后续修改)
**审计方法**: 每行判断均有文件路径证据

---

# 1. Executive Summary

当前 non-primitive text-to-CAD 链路是一个 **正确方向上的 L1 编译器**：LLM 输出被约束为 `extra=forbid` 的类型化 IR（RawGcadDocument），经过 13 个 fail-fast validation pass，canonicalize 为带解析类型和 hash 的 CanonicalGcadDocument，再分派到 6 个冻结的 Dialect 各自执行，handler 内部直接调用 CadQuery/OCP API 产 `TopoDS_Shape`，最终 export STEP + metadata。**整个链路是完整可工作的，但缺少编译器中间层最关键的能力：符号分析、属性引用、优化 pass、类型化面引用、特征树。**

核心 gap：`CanonicalValueRef` 只能引用完整节点的 output（如 `node.body`），不能引用派生属性（如 `component.radius_max` 或 `component.bbox.zlen`）。这导致 LLM 必须在 prompt 阶段猜出所有尺寸数值，而非由编译器在运行时从实际几何体推导。

---

# 2. Repository Map

## 2.1 integrations/ 顶层目录

```
integrations/
  engineering_tools/                    # ← 核心模块
    .claude/skills/                     # Claude Code skills (7 个 skill)
    src/seekflow_engineering_tools/
      generative_cad/                   # ★ non-primitive 链路 (本文聚焦)
      geometry_primitives/              # ★ primitive 链路 (仅需确认边界)
      solidworks/                       # SW COM 集成 (独立工具)
      nx/                               # NX 集成 (独立工具)
  tests/                                # 测试 (不在此次范围内)
```

## 2.2 generative_cad 完整目录索引

```text
generative_cad/
  ir/                                   # IR 定义层
    raw.py                              # RawGcadDocument (LLM 输出)
    canonical.py                        # CanonicalGcadDocument (内部分析)
    values.py                           # ValueType (名义类型枚举)
    geometry_semantics.py               # 语义面/孔放置 V2 模型
    hashing.py                          # stable_hash, graph_hash
    parse.py                            # dict→RawGcadDocument 解析
    legacy.py                           # 旧版 IR 兼容

  validation/                           # ★ 验证/规范化层 (compiler frontend)
    pipeline.py                         # RAW_STAGES + CANONICAL_STAGES
    canonicalize.py                     # Raw→Canonical lowering
    structure.py                        # 结构完整性
    root_terminal.py                    # root_node 是否为终端 solid
    registry.py                         # dialect 注册验证
    params.py                           # 参数验证 (通过 Pydantic)
    ownership.py                        # component 归属验证
    graph.py                            # DAG + 环检测
    typecheck.py                        # 名义类型检查
    phase.py                            # 阶段顺序验证
    composition.py                      # 多组件组合要求
    hole_semantics.py                   # 孔语义验证
    safety.py                           # 安全标记验证
    dialect_semantics.py                # dialect 级语义验证
    geometry_preflight.py               # 静态几何可行性 (envelope tracking)
    spatial_contract.py                 # 空间契约验证
    geometric_solver.py                 # 几何求解器
    measurement.py                      # 测量验证 (未细读)
    
    bundle.py                           # ValidationBundle
    reports.py                          # ValidationReport / ValidationIssue
    repair_hints.py                     # 修复提示生成
    geometry_validate.py                # 运行时 BRepCheck

  dialects/                             # ★ Dialect 编译层 (compiler backend)
    base.py                             # BaseDialect Protocol
    operation.py                        # OperationSpec + Effect + handler
    executor.py                         # execute_operation (统一 dispatch)
    registry.py                         # registry 兼容包装 (dialect_contract_hash 等)
    registry_core.py                    # DialectRegistry (冻结)
    default_registry.py                 # build_default_registry + lru_cache
    results.py                          # OperationResult / ExecutedNode ABI
    governance.py                       # 治理规则 (禁止 part 命名)

    axisymmetric/                       # 旋转体方言 (8 op)
    sketch_extrude/                     # 拉伸方言 (8+3 V2 op)
    sketch_profile/                     # 2D 草图方言 (9 op)
    loft_sweep/                         # 扫掠/放样方言 (4 op)
    shell_housing/                      # 抽壳方言 (2 op)
    composition/                        # 装配/布尔/变换方言 (7 op)

    geometry_utils/                     # 共享几何工具
      boolean_batch.py                  # batch_cut compound
      boolean_safe.py                   # boolean_union_safe + fuzzy fuse
      hole_placement.py                 # 面→3D 位置解析
      ocp_cylinder.py                   # OCP 圆柱切削体
      ocp_loft.py                       # 原生放样
      ocp_pipe.py                       # 管道 sweep
      ocp_wire.py                       # Wire 构建
      path_analysis.py                  # 路径分析

  runtime/                              # ★ Runtime 层
    context.py                          # RuntimeContext (状态容器)
    object_store.py                     # RuntimeObjectStore (类型化存储)
    handles.py                          # SolidHandle / FrameHandle 等
    cadquery_runtime.py                 # CadQueryRuntime (GeometryRuntime 实现)
    geometry_runtime.py                 # GeometryRuntime Protocol
    geometry_postcheck.py               # 后处理几何门 (volume/bbox/closed)
    postconditions.py                   # 运行时后置条件
    cache.py                            # OperationCache (增量重建)
    resolve.py                          # resolve_input_object
    tolerance.py                        # GeometryTolerance
    constraint_resolver.py              # 约束求解器 (Phase C)
    bbox_tracker.py                     # bbox 追踪
    spatial_audit.py                    # 空间审计
    topology.py                         # 拓扑选择
    results.py                          # GcadRunResult
    design_intent.py                    # 设计意图
    semantic_postcheck.py               # 语义后检查

  pipeline/                             # ★ Pipeline / 编排层
    run.py                              # run_canonical_gcad (主入口)
    artifact.py                         # build_canonical_step_artifact
    artifact_models.py                  # CanonicalStepArtifact Pydantic
    metadata.py/meta_v3.py              # metadata 生成
    import_artifact.py                  # 导入 artifact

  authoring/                            # LLM → IR 创作
    build_pipeline.py                   # generate_validate_build_step (全流程)
    auto_fixer.py                       # 自动修复器
    pipeline.py                         # staged authoring
    raw_assembler.py                    # 将 LLM 输出组装为 RawGcadDocument
    schemas.py / prompt_builders.py     # 中间 schema
    spatial/                            # 空间意图系统 (Phase A)

  skills/                               # LLM prompt / skill 生成
    orchestrator.py                     # L1 routing + L2 authoring prompt
    prompts.py                          # 系统级 prompt
    schemas.py                          # DialectSelectionPlan
    tool_schema_compiler.py             # OperationSpec→LLM tool schema 编译
    level2_usage.py / authoring_context.py

  repair/                               # LLM repair 循环
    governor.py                         # RepairStateV2 + stop 条件
    patch.py / hashes.py

  bases/                                # (历史遗留；dialect 从 bases 迁移到 dialects/)
  base_packages/                        # LLM-facing package (无执行逻辑)
  compatibility/                        # v0.1→v0.2 适配
  legacy/                               # v0.1 存档
  llm/                                  # LLM client (deepseek)
```

## 2.3 Primitive 链路索引 (对照用)

```text
geometry_primitives/
  base.py             # PrimitiveBase Protocol
  registry.py         # list_primitive_names, get_primitive
  graph.py            # 图操作
  gears/              # 齿轮 primitive (4 文件)
  turbomachinery/     # 涡轮盘 primitive (3 文件)
```

Primitive 链路与 dialect 链路**完全隔离**：primitive 不经过 dialect compiler，不产生 RawGcadDocument，不经过 validation pipeline。它的唯一交集点在 `skills/orchestrator.py:build_level1_routing_prompt()` 中作为 routing 选项 `deterministic_primitive`。

## 2.4 NX / SolidWorks 索引 (对照用)

```text
solidworks/   # SolidWorksClient: COM 自动化，import_step_as_part()
nx/           # NX integration (Siemens NX 12.0 bridge)
```

这两个目录**不参与 dialect execution**。它们是独立的 STEP import 工具，仅在 post-export 阶段被外部测试脚本调用。本轮升级不应改动此处。

---

# 3. Non-Primitive Text-to-CAD Pipeline

## 3.1 真实调用链 (完整路径)

```text
# ====== Phase 1: LLM → Raw IR ======
orchestrator.build_level1_routing_prompt()         # skills/orchestrator.py:33
  → LLM (DeepSeek v4-pro)
  → DialectSelectionPlan                           # skills/schemas.py

orchestrator.build_level2_authoring_prompt()       # skills/orchestrator.py:101
  → tool_schema_compiler._build_op_variants()      # skills/tool_schema_compiler.py
  → LLM (DeepSeek strict tool calling)
  → RawGcadDocument (raw dict)                     # ir/raw.py:111

# ====== Phase 2: AutoFix ======
auto_fixer.auto_fix_with_report()                  # authoring/auto_fixer.py
  → _sanitize_llm_json() (控制字符清理)
  → _fix_null_hints() (DeepSeek null hints→{})
  → _fix_*() 系列 (~17 fix 函数)

# ====== Phase 3: Validation → Canonicalize ======
validation.pipeline.validate_and_canonicalize_with_bundle()  # validation/pipeline.py:84
  ├── RAW_STAGES (11 stages, fail-fast):
  │   ├── validate_structure()                   # validation/structure.py
  │   ├── validate_root_terminal()               # validation/root_terminal.py
  │   ├── validate_registry()                    # validation/registry.py
  │   ├── validate_params()                      # validation/params.py
  │   ├── validate_ownership()                   # validation/ownership.py
  │   ├── validate_graph()                       # validation/graph.py
  │   ├── validate_typecheck()                   # validation/typecheck.py
  │   ├── validate_phase()                       # validation/phase.py
  │   ├── validate_composition_requirements()    # validation/composition.py
  │   ├── validate_hole_semantics()              # validation/hole_semantics.py
  │   └── validate_safety()                      # validation/safety.py
  │
  ├── canonicalize(raw)                          # validation/canonicalize.py:28
  │   ├── dialect_contract_hash()                # 每个 selected_dialect
  │   ├── require_dialect()                      # 按 node.dialect
  │   ├── op_spec.validate_params()              # Pydantic 校验 → typed_params
  │   ├── _resolve_input_type()                  # 输入类型解析
  │   └── stable_hash() → canonical_graph_hash   # ir/hashing.py:16
  │
  ├── CANONICAL_STAGES (2 stages):
  │   ├── validate_dialect_semantics()           # validation/dialect_semantics.py
  │   └── validate_geometry_preflight()           # validation/geometry_preflight.py
  │       └── dialect.preflight_component()       # 各 dialect 自己的 preflight
  │
  └── build_repair_hints_from_validation()        # validation/repair_hints.py

# ====== Phase 4: Runtime Execution ======
pipeline.run.run_canonical_gcad()                  # pipeline/run.py:94
  ├── RuntimeContext(out_step, metadata_path)      # runtime/context.py:17
  │
  ├── _run_components(canonical, ctx)              # pipeline/run.py:353
  │   └── dialect.run_component(component, nodes, ctx)  # 各 dialect 的 run_component
  │       ├── topological_sort(phase_rank)         # 按 phase_order + DAG 拓排
  │       └── for node in sorted_nodes:
  │           └── executor.execute_operation()     # dialects/executor.py:27
  │               ├── op_spec.handler(node, ctx)   # 直接调用 handler
  │               ├── adapt_legacy_handler_result()# v1_dict→OperationResult
  │               ├── _validate_operation_result() # 输出名/类型/handle 校验
  │               └── _validate_geometry()         # BRepCheck+closed+volume
  │
  ├── ConstraintResolver (spatial_contract 存在时) # runtime/constraint_resolver.py
  ├── _run_composition_or_select_final()           # pipeline/run.py:443
  │
  ├── validate_runtime_postconditions()            # runtime/postconditions.py:9
  ├── _export_final_solid(handle_id, ctx)          # pipeline/run.py:470
  │   └── ctx.geometry_runtime.export_step()       # CadQueryRuntime.export_step()
  │
  ├── validate_final_geometry()                    # runtime/geometry_postcheck.py:32
  │   ├── _count_solids() / _measure_volume() / _measure_bbox() / _check_closed()
  │   └── GeometryPostcheckResult
  │
  ├── validate_step_post_export()                  # runtime/geometry_postcheck.py:143
  │   └── ISO-10303-21 header check + file size
  │
  ├── build_generative_metadata_v3()               # pipeline/metadata_v3.py
  └── build_canonical_step_artifact()              # pipeline/artifact.py:21
```

## 3.2 入口差异

| 入口 | 用途 | 输入 |
|------|------|------|
| `run_gcad_core(raw_dict)` | 完整路径：raw JSON → STEP | dict (LLM 输出) |
| `run_canonical_gcad(canonical, validation_seed)` | 预验证路径 | CanonicalGcadDocument + validation seed |
| `generate_validate_build_step()` | 完整端到端 + autofix + repair | user_request 文本 + LLM config |

---

# 4. IR Layer Audit

## 4.1 RawGcadDocument — LLM 输出接口

**文件**: [ir/raw.py:111-141](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py#L111)

```python
class RawGcadDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")  # ★ 严格拒绝多余字段

    schema_version: Literal["g_cad_core_v0.2"]
    document_id: str
    part_name: str
    units: LengthUnit              # Literal["mm"]
    trust_level: TrustLevel        # Literal["concept_geometry", "reference_geometry"]

    selected_dialects: list[RawSelectedDialect]  # [{dialect, version}]
    components: list[RawComponent]              # [{id, owner_dialect, kind_hint, root_node}]
    nodes: list[RawNode]                        # ★ 操作图
    constraints: RawConstraints                 # 几何约束
    safety: RawSafety                           # 安全标记
    llm_validation_hints: dict[str, Any]        # LLM 验证提示
```

**关键特性**:
- `extra="forbid"` 级联到所有子模型 — LLM 多一个字段就失败
- `RawValueRef` 必须 exactly one of `node` or `component` ([raw.py:34-38](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py#L34))
- `RawNode.params` 是 `dict[str, Any]` — 弱类型，在 canonicalize 时才用 Pydantic 强校验
- `required=True` 且 `degradation_policy != "fail"` 的组合被 validator 拒绝 ([raw.py:63-65](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py#L63))

## 4.2 CanonicalGcadDocument — 编译器内部分析

**文件**: [ir/canonical.py:67-87](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py#L67)

```python
class CanonicalGcadDocument(BaseModel):
    schema_version: Literal["g_cad_core_v0.2"]
    canonical_version: Literal["canonical_gcad_v0.2"]

    selected_dialects: list[CanonicalSelectedDialect]  # + contract_hash
    components: list[CanonicalComponent]                # + output_aliases
    nodes: list[CanonicalNode]                          # ★ 增强后的节点
    constraints: RawConstraints                         # 未变
    safety: RawSafety                                   # 未变

    canonical_graph_hash: str                           # ★ 本次运行的 hash
    raw_graph_hash: str | None                          # 原始 raw 的 hash
```

**CanonicalNode vs RawNode 的关键差异**:
- `params: dict` → `params: dict` + **`typed_params: dict`** (Pydantic 校验后的 JSON-safe dict)
- `RawValueRef` → **`CanonicalValueRef`** (增加了 `resolved_type: ValueType`)
- `RawValueDecl` → **`CanonicalValueDecl`** (增加了 `value_id: str`)
- 新增: **`operation_effects: list[str]`** 和 **`postconditions: list[str]`**
- `op_version: str` (非 None — canonicalize 时填充默认版本)

## 4.3 ValueType — 名义类型系统

**文件**: [ir/values.py:7-19](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/values.py#L7)

```python
ValueType = Literal[
    "solid", "solid_array", "frame", "plane", "point",
    "curve", "profile", "sketch", "face_set", "edge_set", "component_ref",
]
```

**代码已证实的限制**:
- 这是**名义类型**：typecheck 只比较字符串 `actual == expected` ([typecheck.py:70](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/typecheck.py#L70))
- 没有子类型关系：`face_set` 不知道引用的是哪个面的哪些面
- 没有参数化类型：`solid_array` 不知道元素类型
- `component_ref` 是唯一的跨组件引用类型 — 仅 composition dialect 可消费

**实际影响**: `CanonicalValueRef` 只能引用完整节点的 output ([canonical.py:29-34](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py#L29))，不能引用 `component.bbox.zlen` 或 `component.radius_max`。

## 4.4 Canonical Graph Hash

**文件**: [ir/hashing.py:16-18](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/hashing.py#L16)

```python
def graph_hash(canonical_nodes: list) -> str:
    return stable_hash([n.model_dump() for n in canonical_nodes])
```

Hash 覆盖 `id, component, dialect, op, op_version, phase, inputs, outputs, params`（[canonicalize.py:141-149](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py#L141)）。**不包含 typed_params**（typed_params 是 params 的 Pydantic 化版本，语义等价）。如果 params 中有 dim_expr 表达式需要在求值后才知道是否等价，hash 会不同 — 需要 DimExpr 求值器在 hash 前将表达式求值为具体值或规范化。

## 4.5 信息守恒: Raw → Canonical

**有损部分**: 无。Canonical 是 Raw 的信息超集：
- Raw 的 `RawValueRef.{node,component,output}` → Canonical 的 `CanonicalValueRef.{producer_node,producer_component,output,resolved_type}`
- Raw 的 `RawValueDecl.{name,type}` → Canonical 的 `CanonicalValueDecl.{name,type,value_id}`
- 新增: `typed_params`, `operation_effects`, `postconditions`, `contract_hash`, `canonical_graph_hash`

---

# 5. Validation Layer Audit

## 5.1 RAW_STAGES — 11 个 pass，fail-fast

**文件**: [validation/pipeline.py:28-40](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py#L28)

```python
RAW_STAGES = [
    ("structure",      validate_structure),           # 基础结构完整性
    ("root_terminal",  validate_root_terminal),       # root_node 是终端 solid
    ("registry",       validate_registry),            # dialect/op 在 registry 中存在
    ("params",         validate_params),              # params 通过 Pydantic model_validate
    ("ownership",      validate_ownership),           # node.component 归属验证
    ("graph",          validate_graph),               # DAG + 环检测 (3 色 DFS)
    ("typecheck",      validate_typecheck),           # 输入输出类型计数+类型名匹配
    ("phase",          validate_phase),               # 阶段顺序验证
    ("composition",    validate_composition_requirements), # 多组件要求
    ("hole_semantics", validate_hole_semantics),       # 孔语义
    ("safety",         validate_safety),               # 安全标记
]
```

**依赖关系**: 隐式（通过执行顺序保证）。例如 `typecheck` 依赖 `graph` 先构建了 node refs；`hole_semantics` 依赖 `params` 先校验了参数类型。这个隐式依赖在插入新 pass 时是风险点。

**执行模式**: fail-fast — 遇到第一个 error 就停止 ([pipeline.py:78-79](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py#L78))。非 error-collection。注意：即使有 warning，只要没有 error，pass 算通过。

**v6.3 修复**: 在 fail-closed return 之前生成 repair_hints ([pipeline.py:141-156](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py#L141))，确保 autofixer 和 LLM repair 能看到完整的 error 列表。

## 5.2 CANONICAL_STAGES — 2 个 pass

**文件**: [validation/pipeline.py:42-45](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py#L42)

```python
CANONICAL_STAGES = [
    ("dialect_semantics", validate_dialect_semantics),
    ("geometry_preflight", validate_geometry_preflight),
]
```

`validate_geometry_preflight` 做两件事 ([geometry_preflight.py:25-89](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/geometry_preflight.py#L25)):
1. **全局检查**: max_nodes(64), max_boolean_ops(256), max_profile_points(128)
2. **per-dialect preflight**: 调用每个 component 的 `dialect.preflight_component()`

## 5.3 Typecheck — 浅层名义检查

**文件**: [validation/typecheck.py:14-79](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/typecheck.py#L14)

检查内容：
1. 输出数量 == op_spec.output_types 数量
2. 每个输出的类型名 == op_spec.output_types[i]
3. 输入数量 == op_spec.input_types 数量
4. 每个输入的 producer type == op_spec.input_types[i]
5. `component_ref` 只能被 `composition` dialect 消费

**不检查的**：solid 是否 closed、volume > 0、bbox 是否合理、solid 来源是否在本 component 的 DAG 中可达（那是 graph pass 的职责）。这些检查在 runtime 的 `_validate_geometry()` 和 `geometry_postcheck` 中做。

## 5.4 Graph Validation — 标准 DAG 验证

**文件**: [validation/graph.py:9-69](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/graph.py#L9)

- 对所有 `inp.node` 引用的 node_id 做存在性检查
- 对所有 `inp.component` 引用的 component_id 做存在性检查
- 3 色 DFS 环检测 ([graph.py:39-65](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/graph.py#L39))

---

# 6. Dialect Compiler Layer Audit

## 6.1 BaseDialect Protocol — 最小抽象

**文件**: [dialects/base.py:13-43](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/base.py#L13)

```python
class BaseDialect(Protocol):
    dialect_id: str
    version: str
    phase_order: tuple[str, ...]

    def manifest(self) -> dict: ...         # LLM-facing 描述
    def contract(self) -> dict: ...         # 版本化契约 (用于 hash)
    def op_specs(self) -> dict: ...         # {(op, version)→OperationSpec}
    def default_op_version(self, op) -> str: ...
    def get_op_spec(self, op, version) -> OperationSpec: ...
    def validate_component(self, comp, nodes) -> ValidationReport: ...
    def preflight_component(self, comp, nodes) -> ValidationReport: ...
    def run_component(self, comp, nodes, ctx) -> dict[str, str]: ...
```

**代码已证实**: Protocol 不含 `optimize_component` / `plan_component` / `analyze_component`。如果要添加 middle-end pass，有两个选择：
- (A) 在 Protocol 中新增方法（侵入式，需逐个实现）
- (B) 在 run_canonical_gcad 中插入独立的 pass 层（非侵入式，推荐）

## 6.2 OperationSpec — Handler 直接绑定

**文件**: [dialects/operation.py:32-65](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py#L32)

```python
class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    dialect: str; op: str; op_version: str; phase: str
    input_types: list[ValueType]; output_types: list[ValueType]
    params_model: type[BaseModel]
    effects: list[Effect]; postconditions: list[str]

    handler: OperationHandler                  # ★ 直接绑定 handler 函数
    handler_kind: Literal["v1_dict", "v2_result"]

    # LLM-facing metadata (不影响语义):
    summary: str; usage_notes; common_mistakes; examples; anti_examples; llm_param_hints
```

**关键事实**: `handler` 是 `Callable[..., dict[str, str]]`（[operation.py:26](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py#L26)）。OperationSpec **直接绑定 handler**，而不是绑定到一个中间 IR 表示。这意味着：
- 没有独立的 "backend lowering" 阶段
- handler 的输出是裸 `TopoDS_Shape`（通过 `dict[str, str]` 的 handle_id 间接引用）
- 不存在 "OperationSpec → MidLevelPlan → BackendCall" 的两阶段编译

## 6.3 Executor — 统一 dispatch

**文件**: [dialects/executor.py:27-90](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py#L27)

`execute_operation()` 的职责：
1. 检查 cache（如有）
2. 调用 `op_spec.handler(node, ctx)`
3. 归一化为 `OperationResult`
4. 验证输出名、类型、handle 存在性
5. 几何验证（BRepCheck, closed, volume）、仅对 creates_solid/modifies_solid
6. 传播 warnings/degraded_features/metrics
7. 绑定 node outputs → ctx

**几何验证是 warn-only**: [executor.py:137-164](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py#L137) — BRepCheck 错误只产生 warning，不阻止后续执行。这是出于 OCCT 可能在后续布尔操作中修复问题的考量。

## 6.4 Registry — 冻结，不可动态注册

**文件**: [dialects/registry.py:40-45](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/registry.py#L40)

```python
def register_dialect(dialect: BaseDialect) -> None:
    raise RuntimeError(
        "register_dialect is disabled. The default registry is frozen..."
    )
```

**生产环境**: `default_registry()` 返回一个 lru_cache 的冻结 `DialectRegistry`（[default_registry.py:39-41](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/default_registry.py#L39)），包含 6 个 dialect。Governance check 在 freeze 前执行。

**测试环境**: 可以创建 `DialectRegistry()` 实例（未冻结），注册 mock/test dialect，测试完成后不 freeze。

## 6.5 Governance — 禁止 part 命名

**文件**: [dialects/governance.py:22-71](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/governance.py#L22)

- 禁止 dialect_id 包含 part token（"flange", "bracket" 等 20+ 词）
- 禁止 op 以 `make_`, `create_standard_` 等前缀开头
- 禁止 op 名在 FORBIDDEN_OP_EXACT 中
- 禁止 manifest 声称 "manufacturing-ready" 等

这是一个**命名空间约束**，不是类型系统约束。它防止 dialect 退化为 part template，但没有在类型层面防止。

---

# 7. Dialect Inventory

## 7.1 6 个 Dialect 完整清单

| # | dialect_id | version | op 数量 | phase_order 层级 | 创建方式 |
|---|-----------|---------|---------|-----------------|---------|
| 1 | `axisymmetric` | 0.2.0 | 8 | 8 层 | 模块级 `AXISYMMETRIC_DIALECT` |
| 2 | `sketch_extrude` | 0.2.0 | 8+3(V2) | 6 层 | 模块级 `SKETCH_EXTRUDE_DIALECT` |
| 3 | `composition` | 0.2.0 | 7 | 4 层 | 模块级 `COMPOSITION_DIALECT` |
| 4 | `sketch_profile` | 0.2.0 | 9 | 6 层 | 模块级 `SKETCH_PROFILE_DIALECT` |
| 5 | `loft_sweep` | 0.2.0 | 4 | 5 层 | 实例 `LoftSweepDialect()` |
| 6 | `shell_housing` | 0.2.0 | 2 | 3 层 | 实例 `ShellHousingDialect()` |

## 7.2 各 Dialect op 详细信息

### axisymmetric (8 ops)
| op | phase | effects | postconditions |
|----|-------|---------|---------------|
| `revolve_profile` | base_solid | creates_solid, creates_frame | valid_solid |
| `cut_center_bore` | primary_cut | cuts_material | valid_solid |
| `cut_annular_groove` | annular_detail | cuts_material | valid_solid |
| `cut_circular_hole_pattern` | pattern_cut | cuts_material | valid_solid |
| `cut_rim_slot_pattern` | rim_detail | cuts_material | valid_solid |
| `apply_safe_chamfer` | edge_treatment | modifies_solid | valid_solid |
| `cut_internal_thread` | thread | cuts_material | valid_solid |
| `cut_external_thread` | thread | cuts_material | valid_solid |

### sketch_extrude (11 ops: 8 legacy + 3 V2)
| op | phase | effects |
|----|-------|---------|
| `extrude_rectangle` | base_solid | creates_solid |
| `cut_rectangular_pocket` | primary_cut | cuts_material |
| `cut_hole` | primary_cut | cuts_material |
| `cut_hole_v2` * | primary_cut | cuts_material |
| `drill_hole_3d` * | primary_cut | cuts_material |
| `cut_hole_pattern_linear` | hole_pattern | cuts_material |
| `cut_hole_pattern_linear_v2` * | hole_pattern | cuts_material |
| `add_rectangular_boss` | boss_rib | adds_material |
| `add_rib` | boss_rib | adds_material |
| `apply_safe_fillet` | edge_treatment | modifies_solid |
| `apply_safe_chamfer` | edge_treatment | modifies_solid |

\* V2 ops 使用 `ir/geometry_semantics.py` 中的 Params 模型（HolePlacementV2 等）

### composition (7 ops)
| op | phase | effects |
|----|-------|---------|
| `translate_solid` | transform | places_component |
| `rotate_solid` | transform | places_component |
| `place_component` | transform | places_component |
| `circular_pattern_component` | pattern | patterns_component |
| `linear_pattern_component` | pattern | patterns_component |
| `boolean_union` | boolean | boolean_union |
| `boolean_cut` | boolean | boolean_cut |

### loft_sweep (4 ops)
| op | phase | effects |
|----|-------|---------|
| `create_sweep_path` | path | creates_frame |
| `sweep_profile` | sweep | creates_solid |
| `loft_sections` | loft | creates_solid |
| `helix_sweep` | helix | creates_solid |

### shell_housing (2 ops)
| op | phase | effects |
|----|-------|---------|
| `shell_body` | shell | modifies_solid |
| `hollow_body` | hollow | modifies_solid |

### sketch_profile (9 ops)
| op | phase |
|----|-------|
| `create_2d_sketch` | sketch |
| `add_line_segment` | profile |
| `add_arc_segment` | profile |
| `add_circle` | profile |
| `add_polyline` | profile |
| `add_slot` | profile |
| `close_profile` | profile |
| `extrude_profile` | feature |
| `cut_profile` | feature |

---

# 8. Axisymmetric Deep Dive

## 8.1 revolve_profile — 唯一基础 shape 创建

**文件**: [dialects/axisymmetric/handlers.py:50-106](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L50)

```python
def handle_revolve_profile(node, ctx) -> dict[str, str]:
    # 单 station: cq.Workplane("XZ").moveTo(r,zf).lineTo(r,zr)...→矩形→revolve(360)
    # 多 station: piecewise linear profile → sort by z → dedup → .lineTo().close().revolve(360)
    # 输出: body (solid) + outer_frame (frame)
```

关键: `outer_frame` 在某些 dialect 被要求强制输出 ([dialect.py:78-82](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L78))。但 handler 只是创建了一个默认 `FrameHandle`（不对应任何实际几何体）。

## 8.2 cut_center_bore — 中心通孔

**文件**: [handlers.py:113-126](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L113)

```python
def handle_cut_center_bore(node, ctx):
    body = resolve_input_object(node, ctx, 0)
    dia = node.typed_params.get("diameter_mm")
    bb = body.val().BoundingBox()
    bore = cq.Workplane("XY").circle(dia/2).extrude(bb.zlen + 10, both=True)
    result = body.cut(bore)
```

**关键问题**: 当 bore 直径 ≥ 外径时，`body.cut(bore)` 会失败，handler 当前 `except` 返回原始 body（[handlers.py:124-125](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L124)）—— **没有检查 `node.required`**！这是一个不一致：`_degrade` 函数检查了 required，但 `handle_cut_center_bore` 在自己的 try/except 中没有使用 `_degrade`，而是直接返回原 body。

## 8.3 cut_circular_hole_pattern — 节圆孔阵

**文件**: [handlers.py:129-186](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L129)

实现了两种策略：
- `is_narrow_body or count > 6`: 逐个切孔（sequential cut）
- 否则: `polarArray` → 一次 batch cut

**没有使用 boolean_batch.py 的 batch_cut**。这是手动内联优化，而非编译器自动决策。

## 8.4 Degradation 语义

**文件**: [handlers.py:26-43](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L26)

```python
def _degrade(node, ctx, body, op_name):
    if getattr(node, "required", True):
        raise RuntimeError(...)  # HARD FAIL
    ctx.warnings.append(f"'{op_name}' skipped...")
    return _store_solid(node, ctx, body)
```

v6.3 已收紧：required 操作失败不再静默返回原 body。但 `handle_cut_center_bore` 的 except 块绕过 `_degrade` 直接返回 body — 这是需要修复的不一致点。

**注意**: 在 dialect.run_component 层的 try/except 也检查 `not node.required and degradation_policy == "may_skip_with_warning"`（[dialect.py:278-282](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L278)）。所以即使 handler 内部不检查，外层也会在 exception 未被 handler 捕获时做 required 检查。但 handler 内部的 try/except 会吞掉 exception，导致外层检查被绕过。

## 8.5 Thread ops — 参数扫描模拟

`handle_cut_internal_thread` 和 `handle_cut_external_thread` 使用 CadQuery 的 `parametricCurve` + `sweep` 模拟螺纹切割。这是一种近似，不是真正的 ISO 螺纹几何。Error 时返回原 body（静默退化）。

---

# 9. Runtime and Export Audit

## 9.1 RuntimeContext — 状态容器

**文件**: [runtime/context.py:17-68](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py#L17)

```python
@dataclass
class RuntimeContext:
    out_step: Path; metadata_path: Path; workspace_root: Path
    object_store: RuntimeObjectStore
    geometry_runtime: GeometryRuntime     # 默认 CadQueryRuntime
    tolerance: GeometryTolerance
    cache: OperationCache

    node_outputs: dict[str, dict[str, str]]       # node_id → {output_name → handle_id}
    component_outputs: dict[str, dict[str, str]]   # component_id → {output_name → handle_id}

    warnings: list[str]
    degraded_features: list[dict]
    operation_metrics: list[dict]

    # v6 spatial:
    spatial_placements: dict
    spatial_audit_report: Any
    spatial_contract_hash: str | None
    placed_component_bboxes: dict
    strict_geometry_semantics: bool = True
```

**向 RuntimeContext 添加新字段是安全的**（dataclass 使用 `field(default=...)` 或 `field(default_factory=...)`）。新增 `compiler_diagnostics: list[dict]` 或 `geometry_health: dict` 不会破坏现有构造。

## 9.2 RuntimeObjectStore — 类型化存储

**文件**: [runtime/object_store.py:23-66](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/object_store.py#L23)

存储内容是 Any（`TopoDS_Shape` 对象或 CadQuery Workplane 对象）。通过 `RuntimeHandle`（SolidHandle, FrameHandle, SolidArrayHandle 等）进行类型化访问。

`StoredRuntimeObject.value_type` 来自 `handle.type`（如 `"solid"`, `"frame"`），这是 handle 声明时的类型，不是运行时检测的类型。

## 9.3 GeometryRuntime — Protocol 抽象

**文件**: [runtime/geometry_runtime.py:12-35](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/geometry_runtime.py#L12)

```python
class GeometryRuntime(Protocol):
    runtime_id: str; runtime_version: str
    def export_step(self, solid_obj: Any, out_step: Path) -> None: ...
    def inspect_solid(self, solid_obj: Any) -> dict: ...
    def validate_closed_solid(self, solid_obj: Any) -> dict: ...
    def compute_bbox_mm(self, solid_obj: Any) -> list[float] | None: ...
    def count_bodies(self, solid_obj: Any) -> int | None: ...
```

**当前只有一个实现**: `CadQueryRuntime`。这是一个 Protocol（非 ABC），所以可以通过 duck typing 添加新实现。

## 9.4 STEP Export

**调用链**: `pipeline/run.py:470-472`
```python
def _export_final_solid(handle_id, ctx):
    obj = ctx.object_store.get(handle_id)
    ctx.geometry_runtime.export_step(obj, ctx.out_step)
```

`CadQueryRuntime.export_step()` 先尝试 OCP native `STEPControl_Writer`（设置 product name），fallback 到 `cq.exporters.export()`。

## 9.5 Geometry Postcondition Gate

**文件**: [runtime/geometry_postcheck.py:32-188](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/geometry_postcheck.py#L32)

`validate_final_geometry()` 在 STEP export 之后运行，检查：
1. Volume > 0
2. Solid body count (n_solids 为 0 但 volume > 0 → warning, inspection artifact)
3. BBox 非退化
4. Closed solid
5. STEP 文件格式 (ISO-10303-21 header)

---

# 10. LLM / Skills / Repair Audit

## 10.1 LLM → RawGcadDocument 路径

```text
用户自然语言
  → orchestrator.build_level1_routing_prompt()     # skills/orchestrator.py:33
    → LLM → DialectSelectionPlan
  → orchestrator.build_level2_authoring_prompt()    # skills/orchestrator.py:101
    → tool_schema_compiler._build_op_variants()     # 从 OperationSpec 生成 tool schema
    → LLM (DeepSeek strict) → RawGcadDocument
  → raw_assembler                                   # 组装为 RawGcadDocument
```

## 10.2 Prompt 如何暴露 Dialect 能力

`build_level2_tool()` 从 `OperationSpec` 自动生成 per-op JSON Schema 变体（dialect 固定、op 固定、phase 固定、params model 展开为 schema）。这比手动维护 prompt 更准确。

`OP_DESCRIPTIONS` 字典（[orchestrator.py:281-359](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/orchestrator.py#L281)）覆盖了大部分常用 op 的中文描述，但**没有覆盖所有 op**。未覆盖的 op 使用 `OperationSpec.summary`。

## 10.3 Repair 如何读取 Diagnostics

`build_repair_prompt_v2()` 将 `validation_report.get('issues', [])` 直接传给 LLM（[orchestrator.py:180-181](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/skills/orchestrator.py#L180)）。Repair 的 Govendor 通过 hash 检测是否重复和是否有进展（[repair/governor.py:39-74](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/repair/governor.py#L39)）。

**当前 repair 只使用 validation info**，不包含 compiler middle-end diagnostics（如 ShapeFacts, PlanningReport）。新增 diagnostics 需要扩展 `build_repair_prompt_v2()` 或在 `raw_document` + `validation_report` 之外再加一个 `compiler_report` 字段。

---

# 11. Primitive vs Non-Primitive Boundary

| 归属 | 模块 | 说明 |
|------|------|------|
| **本次升级范围** | `generative_cad/` 全部 | non-primitive dialect compiler |
| **不升级** | `geometry_primitives/` | 独立 primitive 链路，完全隔离 |
| **不升级** | `solidworks/` | SW COM 集成，独立工具 |
| **不升级** | `nx/` | NX 集成，独立工具 |
| **不升级** | `legacy/` | v0.1 存档，不应修改 |
| **不升级** | `bases/` | v0.1 bases，已被 `dialects/` 取代 |

共同点：所有链路共享 `cadquery` 和 `OCP` 作为几何后端，但 primitive 链路不经过 dialect compiler 的任何阶段。

---

# 12. Architecture Upgrade Compatibility Matrix

以下逐条验证 v6.3 升级方向与当前代码的兼容性。

## 12.1 Middle-End Sidecar

**目标**: 在 canonicalize 之后插入 `CompilerModule` 做语义分析/ShapeFacts/Feasibility/Planning，结果写入 ctx 或 metadata sidecar。不修改 CanonicalGcadDocument。

| 维度 | 评估 |
|------|------|
| **插入点** | `run_canonical_gcad` 中 `_run_components` 之前 ([run.py:123](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L123)) — 此时 canonical 已存在，ctx 刚初始化 |
| **是否修改 CanonicalGcadDocument** | 不需要。sidecar 写入 ctx 新字段或 metadata["compiler_*"] |
| **RuntimeContext 兼容** | 完全兼容。dataclass 支持新 default 字段 |
| **Metadata 兼容** | `build_generative_metadata_v3` 目前构建 validation + runtime。新增 compiler section 不破坏现有结构 |
| **Feature flag** | 建议 `ctx.strict_geometry_semantics` 或环境变量 `GCAD_ENABLE_MIDDLE_END` |
| **风险等级** | **Low** — 纯增量，不改现有 schema |
| **推荐 Phase** | Phase 1 |

## 12.2 DimExpr / RefPath

**目标**: 用 JSON-safe 表达式表达派生尺寸（如 `body.radius_max - 2 * margin`）

| 维度 | 评估 |
|------|------|
| **params_model 能否接受 dict** | 否。params_model 是 Pydantic BaseModel（如 `CutCenterBoreParams`），字段类型是 `float`，不接受 dict |
| **兼容方案** | 需要新增 `DimExpr` 类型作为 params 的可选字段类型。或者将 DimExpr 放在 `typed_params` 而非 `params` — typed_params 已经是 dict 且不影响 hash |
| **求值时机** | 必须在 canonicalize 之后、handler 执行之前。在 runtime 中根据 bbox 测量值求值 |
| **表达式失败** | 应该 error（无法求值意味着几何不可行） |
| **最先支持的 op** | `CutCircularHolePatternParams.pcd_mm`（经常依赖外径）、`CutCenterBoreParams.diameter_mm`（依赖外径）、`RevolveProfileParams.profile_stations[].r_mm` |
| **风险等级** | **Medium** — params_model 需要扩展，但可以向后兼容（非 DimExpr 参数不变） |
| **推荐 Phase** | Phase 1（模型准备）+ Phase 2（求值器） |

## 12.3 ShapeFacts

**目标**: 为每个 node output 传播保守几何事实（radius_max, bbox, zlen, faces 等）

| 维度 | 评估 |
|------|------|
| **axisymmetric.revolve_profile 的 params 是否足够** | 是。`profile_stations[].r_mm` 提供了 max/min radius，`z_front_mm/z_rear_mm` 提供了 z extent |
| **cut_center_bore 能否读取上游 facts** | 需要新的 ShapeFact propagation pass。当前 handler 不做此事 |
| **参数名** | `cut_circular_hole_pattern`: pcd_mm, hole_dia_mm, count — 足够用于碰撞检测 |
| **composition.translate_solid 传播 bbox** | handle_place_component 已经追踪 `placed_component_bboxes`（[handlers.py:161-170](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py#L161)） |
| **facts 存哪里** | 建议存 `CompilerModule`（新 dataclass），不存 `RuntimeContext`（RuntimeContext 是执行时的，ShapeFacts 是分析时的） |
| **风险等级** | **Low** — 纯只读分析，不修改 graph |
| **推荐 Phase** | Phase 1 |

## 12.4 GeometryHealth

**目标**: 每个 creates_solid/modifies_solid op 执行后生成 health 记录

| 维度 | 评估 |
|------|------|
| **GeometryRuntime 是否已有 inspect_solid** | 是。`CadQueryRuntime.inspect_solid()` 返回 `{solid_count, bbox_mm}` |
| **插入点** | `execute_operation` 中的 `_validate_geometry` 调用处 ([executor.py:73-74](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py#L73)) |
| **RuntimeContext 是否可加字段** | 是。如 `ctx.geometry_health_log: list[dict] = field(default_factory=list)` |
| **required node health error** | 当前 `_validate_geometry` 是 warn-only。收紧为 error 风险较高（OCCT 中间态可能不完美但后续布尔修复）。建议：accumulate health，只在 final postcheck 做 fail |
| **风险等级** | **Low** — 增量记录，不改变执行逻辑 |
| **推荐 Phase** | Phase 1 |

## 12.5 Required Degradation Tightening

**目标**: `required=True` 的 destructive feature 失败不能静默返回原 body

| 维度 | 评估 |
|------|------|
| **哪些 handler 当前 catch exception 后返回原 body** | `handle_cut_center_bore` ([handlers.py:124-125](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L124)), `handle_cut_circular_hole_pattern` ([handlers.py:184-185](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L184)), `handle_cut_annular_groove` ([handlers.py:210-211](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L210)), `handle_cut_rim_slot_pattern` ([handlers.py:249-250](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L249)), 两个 thread handler ([handlers.py:342-343](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L342)) |
| **它们是否检查 node.required** | 部分（cut_hole_pattern 和 annular_groove 在 params 无效时返回，但 exception 时不检查）。整体不一致 |
| **外层 run_component 是否兜底** | 是。所有 dialect 的 run_component 在 execute_operation exception 时检查 required+degradation_policy |
| **现有测试是否依赖 silent fallback** | 待验证（需要运行测试）。从代码逻辑看：如果 handler 的 try/except 吞掉 exception 而返回原 body，外层不会被触发。这是 bug |
| **风险等级** | **Medium** — handler 内部 try/except 需要逐个审计 |
| **推荐 Phase** | Phase 1（逐个 handler 修复） |

## 12.6 PlanningReport

**目标**: 第一阶段只做只读 planner，不改写 graph

| 维度 | 评估 |
|------|------|
| **CanonicalNode 是否包含 phase/effects/op** | 是（phase, operation_effects, op） |
| **effects 命名是否稳定** | 是（Effect Literal 在 [operation.py:12-24](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py#L12)） |
| **phase_order 是否能判断 chamfer/fillet 早晚** | 是（edge_treatment 在大多数 dialect 中是倒数第二/三个阶段） |
| **PlanningReport 放哪里** | ctx 或 metadata["planning_report"] |
| **风险等级** | **Low** — 只读分析 |
| **推荐 Phase** | Phase 1 |

## 12.7 STEP Preservation

**目标**: middle-end 不允许破坏 final STEP export

| 维度 | 评估 |
|------|------|
| **STEP export 在哪里** | `_export_final_solid()` → `geometry_runtime.export_step()` ([run.py:470-472](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L470)) |
| **final handle 如何选择** | `_run_composition_or_select_final()` ([run.py:443-467](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L443)) |
| **metadata 如何绑定 artifact hash** | `build_canonical_step_artifact()` → `step_sha256` ([artifact.py:76](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py#L76)) |
| **health unknown 是否仍允许 export** | 当前代码：是。geometry_postcheck 只在 error 时阻止。建议保持此行为 |
| **风险等级** | **Low** |
| **推荐 Phase** | Phase 1（保持现状，不做破坏性改动） |

---

# 13. Implementation Insertion Points

## 13.1 应修改的文件

| 文件 | 修改内容 | 风险 |
|------|---------|------|
| `pipeline/run.py:122` (around line) | 在 `_run_components` 之前插入 CompilerModule 调用 | Low |
| `runtime/context.py:17` | 新增 `compiler_diagnostics`, `geometry_health_log`, `shape_facts` 字段 | Low |
| `dialects/axisymmetric/handlers.py` | 修复 `handle_cut_center_bore` 等的 silent degradation | Medium |
| `dialects/axisymmetric/handlers.py` (thread) | 修复 thread handlers 的 silent degradation | Medium |
| `pipeline/metadata_v3.py` | 在 metadata 中新增 compiler diagnostics section | Low |
| `dialects/executor.py:73` | 在 `_validate_geometry` 处记录 GeometryHealth 到 ctx | Low |
| `skills/orchestrator.py:180` | 扩展 `build_repair_prompt_v2` 接收 compiler diagnostics | Low |
| `dialects/loft_sweep/dialect.py:291` | 修复 `run_component` 的异常处理（未检查 required） | Low |

## 13.2 应新增的文件

| 文件 | 内容 | 大小估计 |
|------|------|---------|
| `generative_cad/compiler/__init__.py` | CompilerModule 主类 | ~50 loc |
| `generative_cad/compiler/shape_facts.py` | ShapeFacts 表达和保守传播 | ~200 loc |
| `generative_cad/compiler/dim_expr.py` | DimExpr / RefPath 模型 + 求值器 | ~150 loc |
| `generative_cad/compiler/planning.py` | 只读 PlanningReport 生成 | ~120 loc |
| `generative_cad/compiler/health.py` | GeometryHealth 记录器 | ~80 loc |
| `generative_cad/compiler/symbolic_dimension.py` | SymbolicDimension 框架 | ~100 loc |

## 13.3 禁止修改的文件

| 文件 | 理由 |
|------|------|
| `ir/raw.py` | Raw schema 稳定。LLM 接口不能变 |
| `ir/canonical.py` | Canonical schema 携带 hash。改变会破坏增量 rebuild |
| `ir/values.py` | ValueType 改变会影响所有 typecheck |
| `ir/hashing.py` | Hash 算法稳定是核心不变量 |
| `dialects/operation.py` | OperationSpec ABI 稳定 |
| `dialects/registry_core.py` | Registry 冻结语义 |
| `pipeline/run.py` — `_export_final_solid` | STEP export 路径 |
| `runtime/geometry_runtime.py` | Backend Protocol 稳定 |
| `runtime/cadquery_runtime.py` | Backend 实现稳定 |
| 所有 `geometry_primitives/` | 隔离边界 |
| 所有 `solidworks/`, `nx/` | 外部工具 |

---

# 14. Test Strategy

## 14.1 现有测试 (如存在)

按路径推测（未直接查看测试文件）：
```
tests/generative_cad/
  authoring/spatial/    # Phase A 空间意图
  dialects/             # 各 dialect 单元测试
  runtime/              # Runtime 单元测试
  validation/           # Validation 单元测试
```

## 14.2 新增测试

| 测试 | 测试内容 | 策略 |
|------|---------|------|
| `test_shape_facts_axisymmetric` | revolve_profile → radius_max/bbox | 纯数据测试，不依赖 OCP |
| `test_dim_expr_eval` | "body.radius_max - 2 * margin" 求值 | 纯数据测试 |
| `test_planning_report` | 给定 minimal canonical graph → 产生 planning | 纯数据测试 |
| `test_required_degradation` | handler required 操作失败 → raise | 需要 OCP |
| `test_middle_end_sidecar` | CompilerModule 不修改 canonical graph | 纯数据测试 |

## 14.3 Skip 条件

- 所有 `test_*` 如果 OCP/CadQuery 不可用时 skip：测试数据模型不需要 OCP
- 涉及 `handle_*` 直接调用的测试需要 OCP
- ShapeFacts 传播测试：第一 pass 只测试数据结构的正确性（不需要 OCP），第二 pass 才测试传播结果（需要 OCP）

## 14.4 CI 集成

新增 compiler 层测试应加入现有的测试会话：
```bash
python -m pytest tests/generative_cad/compiler/ -v
```

---

# 15. Open Questions

以下问题需要人工确认，而非代码能回答：

1. **DimExpr 语法选择**: `"${body.radius_max} - 2"` 还是 `{"ref": "body.radius_max", "op": "sub", "rhs": 2}`？前者 LLM 友好，后者解析器友好。建议两者都支持，内部统一为结构化形式。

2. **ShapeFacts 是否应 affecting graph_hash**: 如果 ShapeFacts 影响 hash，则所有现有 canonical.json 的 hash 会变。建议 → 不影响 hash，仅作为 metadata sidecar。

3. **compiler middle-end 是否需要 feature flag**: 建议需要。`GCAD_ENABLE_MIDDLE_END=true`。默认关闭（向后兼容）。因为 middle-end 可能产生新的 warning/error 类别，影响现有 pipeline。

4. **Dimension solver 应该在 Phase A（preflight）还是 Phase C（runtime）**: 建议两者都参与。Phase A 报告静态冲突，Phase C 在求值后报告最终冲突。

5. **PlanningReport 中的 optimization 建议是否应由 autofixer 自动应用**: 建议 Phase 1 不自动应用。只生成建议，记录到 metadata，不做 graph mutation。

6. **existing test 是否依赖 silent degradation**: 需要运行全量测试后确认。如果是，逐步收紧（先 warning，再 error）。

---

# 16. Final Recommendation

**可以进入 Phase 1 实施。原因：**

1. ✅ 现有架构（类型化 IR + multi-pass validation + 冻结 dialect registry + 统一 executor）为 middle-end 提供了清晰的插入面
2. ✅ RuntimeContext dataclass 支持增量字段
3. ✅ metadata pipeline 支持增量 section
4. ✅ 所有 middle-end 功能在 Phase 1 都是只读 — 不改 canonical graph，不破坏 hash
5. ✅ geometry_preflight 已验证了 envelope tracking 的可行性（axisymmetric preflight 是 ShapeFacts 的原理验证）
6. ✅ boolean_union 的三层 fallback 已验证了 runtime 中做几何决策的可行性

**Phase 1 最小闭环（6 个交付件）**:

1. `compiler/shape_facts.py` — ShapeFacts 模型 + 对 axisymmetric 的保守传播
2. `compiler/dim_expr.py` — DimExpr 模型（不实现求值器，只定义 schema）
3. `compiler/health.py` — GeometryHealth 记录（在 `_validate_geometry` 中挂钩）
4. `compiler/planning.py` — 只读 PlanningReport（hole_pattern_should_batch, edge_treatment_too_early, etc.）
5. `pipeline/run.py` — 插入 `CompilerModule.analyze()` 调用
6. 修复 axisymmetric handler 的 silent degradation（cut_center_bore, cut_circular_hole_pattern 等）

**Phase 1 明确不做**:
- 不做 DimExpr 求值器（留到 Phase 2）
- 不做 ShapeFacts 跨 dialect 传播
- 不做 graph mutation（不改写 boolean order, 不自动 batch）
- 不做 Feature IR
- 不修改 CanonicalGcadDocument schema
- 不破坏 STEP export

**立即可以开始的实施顺序**:
```
Step 1: 创建 compiler/ 目录 + shape_facts.py (<= 200 loc)
Step 2: 创建 compiler/health.py (<= 80 loc)
Step 3: 创建 compiler/dim_expr.py (<= 120 loc, schema only)
Step 4: 创建 compiler/planning.py (<= 120 loc)
Step 5: 修复 axisymmetric handlers 的 silent degradation
Step 6: 在 run.py 中插入 CompilerModule.analyze()
Step 7: 编写编译器诊断的 metadata section
Step 8: 运行全量测试验证
```
