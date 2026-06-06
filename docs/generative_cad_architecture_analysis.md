# generative_cad 深度架构与功能分析文档

> **文档版本:** 2026-06-06
> **分析范围:** `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/`
> **代码行数:** ~15,000+ Python (132 个 .py 文件)
> **分析方法:** 逐文件深度阅读,基于实际代码、调用链、类型定义、配置和测试行为得出结论

---

## 1. Executive Summary

`generative_cad` 包实现了 **Text-to-CAD 的两条独立链路**:

1. **非 Primitive 链路 (LLM + 编译器):** 用户输入自然语言描述 → LLM (DeepSeek v4-pro) 路由和创作 → 格式化 IR → 多层校验 → 自动修复 → 编译器中间端分析 → 方言运行时执行 → STEP 文件 → SolidWorks/NX 原生格式。这是主链路,大约 95% 的代码为其服务。

2. **Primitive 链路 (确定性):** 用户输入结构化规格 → 直接调用 `geometry_primitives` 包生成确定性几何体。此链路在 `generative_cad` 包外部,通过 `geometry_primitives` 包实现。`generative_cad` 仅通过 `tools.py` 中的 `generative_cad_list_dialects` 和 L1 路由的 primitive_catalog 参数与之交互。

**核心架构模式:** 管道/流水线 + 方言注册表 + 编译器 Pass + Fail-Closed 安全策略

**关键设计原则:**
- LLM 永远不被信任为最终权威 — 所有输出经过严格校验、规范化、自动修复和几何检查
- DeepSeek 是唯一的 LLM 提供商，通过 `strict=False` 模式适配其已知缺陷
- 所有 safety 标志必须显式为 `true` — 系统在组装和校验阶段强制执行
- 方言系统提供统一协议 (`BaseDialect`): manifest/contract/op_specs/validate/preflight/run

---

## 2. 代码范围与阅读依据

### 2.1 读取范围

```
generative_cad/
├── __init__.py              # 包文档
├── base.py                  # [已废弃] 向后兼容重导出
├── builder.py               # ★ 生产入口: build_generative_cad_model()
├── tools.py                 # ★ SeekFlow Agent 工具注册
├── runner.py                # [已废弃] 向后兼容重导出
├── validation.py            # [已废弃] 向后兼容重导出
├── preflight.py             # [已废弃] 向后兼容重导出
├── prompts.py               # [已废弃] 向后兼容重导出
├── registry.py              # [已废弃] 向后兼容重导出
├── repair_governor.py       # [已废弃] 向后兼容重导出
├── graph_validation.py      # [已废弃] 向后兼容重导出
├── metadata.py              # [已废弃] 向后兼容重导出
├── ir.py                    # [已废弃] 向后兼容重导出
├── artifact.py              # [已废弃] 向后兼容重导出
├── native_importers.py      # SolidWorks/NX STEP 导入器
├── analysis/                # ★ 编译器中间端 Phase 1: ShapeFacts
├── authoring/               # ★ 多阶段创作管线 + 空间意图系统
│   └── spatial/             # ★ v6 空间交互子系统
├── base_packages/           # ★ LLM 面向的技能包 (BasePackage)
├── bases/                   # [已废弃] v0.1 遗留基类
├── compiler/                # ★ 编译器中间端: Pass 管理
├── compatibility/           # 遗留 spec 适配器
├── dialects/                # ★ 方言注册表 + 6 种方言 + 执行器 + 几何工具
├── ir/                      # ★ 中间表示: Raw + Canonical + 表达式 + 语义
├── legacy/                  # v0.1 遗留代码 (测试兼容)
├── llm/                     # ★ DeepSeek LLM 客户端
├── pipeline/                # ★ 核心运行时: run/artifact/metadata/import_gate
├── planning/                # ★ 编译器中间端 Phase 3: 规划分析
├── repair/                  # 修复治理: governor/hashes/patch
├── runtime/                 # ★ 运行时: context/object_store/handles/resolve/cache/health/recovery + 空间约束求解
├── skills/                  # ★ L1/L2 LLM prompt 编排
└── validation/              # ★ 22 个校验阶段 + canonicalize + repair_hints
```

### 2.2 阅读依据

分析基于以下文件的完整实际代码阅读:
- 全部 132 个 `.py` 文件的类定义、函数签名、导入依赖、调用关系
- 类型定义 (Pydantic models, dataclasses, Protocols, TypedDicts)
- 配置常量 (环境变量、模块级常量)
- 测试文件引用和 git 历史中的测试结果

### 2.3 约定

文中使用以下标记:
- **★** = 核心活跃模块
- **[已废弃]** = 仅为向后兼容保留的模块
- **[确认]** = 已由实际代码确认
- **[推断]** = 基于代码结构推断
- **[不确定]** = 需要进一步验证

---

## 3. 目录与文件结构

### 3.1 完整文件清单 (132 个 .py 文件)

```
generative_cad/                              (1 文件)
  __init__.py                                # 包文档, 无重导出
  base.py, runner.py, validation.py,         # 8 个向后兼容重导出
  preflight.py, prompts.py, registry.py,
  repair_governor.py, graph_validation.py,
  metadata.py, ir.py, artifact.py
  builder.py                                 # ★ build_generative_cad_model()
  tools.py                                   # ★ 9 个 SeekFlow Agent 工具
  native_importers.py                        # SW/NX STEP 导入

ir/                                          (11 文件)
  __init__.py                                # 重导出 Raw + Canonical 模型
  raw.py                                     # ★ RawGcadDocument (LLM 输出格式)
  canonical.py                               # ★ CanonicalGcadDocument (校验后 IR)
  values.py                                  # ValueType 字面量联合
  expr.py                                    # ★ DimExpr/RefPath 表达式系统
  semantic.py                                # SemanticType/FaceSelector/PlacementExpr
  geometry_semantics.py                      # ★ HolePlacementV2 V2 几何语义
  legacy.py                                  # v0.1 遗留 IR
  parse.py                                   # RawParseResult 预 Pydantic 解析
  hashing.py                                 # stable_hash / graph_hash / contract_hash

llm/                                         (5 文件)
  __init__.py                                # 重导出
  deepseek_client.py                         # ★ DeepSeekToolCaller
  models.py                                  # LlmModelConfig / AuthoringLlmConfig
  provider.py                                # ToolCallResult / LlmToolCaller 协议
  errors.py                                  # LlmToolCallError / LlmProviderError

skills/                                      (7 文件)
  __init__.py                                # 包文档
  orchestrator.py                            # ★ L1/L2 prompt 构建 + tool 构建
  schemas.py                                 # DialectSelectionPlan / DomainSkillSelectionItem
  prompts.py                                 # L1/L2/Repair system prompts
  authoring_context.py                       # pack_authoring_context()
  level2_usage.py                            # ★ generate_level2_usage_skill()
  tool_schema_compiler.py                    # ★ compile_level2_tool_schema()

authoring/                                   (13 文件 + spatial/)
  __init__.py                                # 包文档
  pipeline.py                                # ★ generate_gcad_from_user_request() 多阶段管线
  build_pipeline.py                          # ★ generate_validate_build_step() Text→STEP
  schemas.py                                 # RoutePlan/FeatureSequenceDraft/NodeParamsDraft/RawAssemblyResult
  context_builder.py                         # build_authoring_context()
  prompt_builders.py                         # 4 个 system prompt + 4 个 user prompt builder
  raw_assembler.py                           # ★ assemble_raw_gcad_document() 系统填充
  auto_fixer.py                              # ★ 20+ 确定性修复规则
  strict_schema.py                           # ★ to_deepseek_strict_schema() DeepSeek 适配
  tool_schemas.py                            # build_*_tool_schema() 路由/序列/参数/修复
  design_intent_extractor.py                 # 正则提取设计意图指标
  failure_taxonomy.py                        # 30 个 AuthoringFailureCode
  metrics.py                                 # AuthoringRunMetrics
  repair_agent.py                            # repair_with_llm() LLM 修复循环
  spatial/                                   (18 文件, v6 空间子系统)
    __init__.py, schemas.py, prompts.py, tool_schemas.py
    pipeline.py, integration.py
    constraint_graph.py, solver.py, validators.py
    question_planner.py, answer_normalizer.py
    archetypes/ (registry.py + 4 个 archetype)

compiler/                                    (4 文件)
  __init__.py                                # 重导出 CompilerModule/CompilerPass/middle_end_enabled
  module.py                                  # ★ CompilerModule 数据容器
  pass_manager.py                            # ★ run_compiler_passes() + build_compiler_module()
  config.py                                  # middle_end_enabled() + 配置常量

analysis/                                    (6 文件)
  __init__.py                                # 重导出
  facts.py                                   # ★ ShapeFacts/FactStore/BBoxFacts/NumericFact/FaceFact
  fact_rules.py                              # ★ 9 个事实推导规则 + FACT_RULES 注册表
  fact_propagation.py                        # ★ FactPropagationPass (Compiler Pass 1)
  expr_eval.py                               # ★ evaluate_dim_expr() DimExpr 求值
  semantic_specs.py                          # OperationSemanticSpec 语义规格

planning/                                    (4 文件)
  __init__.py                                # 重导出
  planning_report.py                         # PlanningIssue/PlanningReport
  risk_model.py                              # 5 个风险阈值 + RiskCategory 目录
  planner.py                                 # ★ PlannerPass (Compiler Pass 2)

dialects/                                    (30+ 文件)
  __init__.py                                # 空
  base.py                                    # ★ BaseDialect 协议
  operation.py                               # ★ OperationSpec + Effect 字面量
  executor.py                                # ★ execute_operation() 统一执行器
  governance.py                              # 方言治理 (禁止具体零件名)
  results.py                                 # OperationResult ABI
  registry.py                                # 兼容包装器 → default_registry()
  registry_core.py                           # ★ DialectRegistry (冻结注册表)
  default_registry.py                        # ★ build_default_registry() 6 种方言
  axisymmetric/ (7 文件)                     # ★ 旋转对称方言 (8 ops)
  sketch_extrude/ (6 文件)                   # ★ 草图拉伸方言 (11 ops)
  loft_sweep/ (3 文件)                       # ★ 扫描放样方言 (4 ops)
  shell_housing/ (3 文件)                    # ★ 壳体方言 (2 ops)
  composition/ (6 文件)                      # ★ 装配方言 (7 ops)
  sketch_profile/ (3 文件)                   # ★ 草图轮廓方言 (9 ops)
  geometry_utils/ (9 文件)                   # ★ OCP 几何工具

pipeline/                                    (8 文件)
  __init__.py                                # 空
  run.py                                     # ★ run_canonical_gcad() 主编排器
  artifact.py                                # build_canonical_step_artifact()
  artifact_models.py                         # CanonicalStepArtifact
  import_artifact.py                         # ★ validate_generative_step_artifact_for_native_import()
  import_gate_models.py                      # ImportGateResult
  metadata.py                                # v2.1 metadata builder/validator
  metadata_v3.py                             # ★ v3 metadata + 子证明模型
  _test_helpers.py                           # 测试专用 (UNVERIFIED)

runtime/                                     (20 文件)
  __init__.py                                # 空
  context.py                                 # ★ RuntimeContext (中央状态持有者)
  cadquery_runtime.py                        # CadQueryRuntime (STEP 导出/检查)
  geometry_runtime.py                        # GeometryRuntime 协议
  object_store.py                            # ★ RuntimeObjectStore (类型化对象存储)
  handles.py                                 # ★ 类型化句柄 (SolidHandle/FrameHandle/...)
  resolve.py                                 # resolve_input_handle_id/object()
  results.py                                 # GcadRunResult
  cache.py                                   # OperationCache (基于 hash 的记忆化)
  tolerance.py                               # GeometryTolerance (全局精度)
  topology.py                                # select_edges/faces 拓扑选择器
  design_intent.py                           # DesignIntentMetrics (预期几何性质)
  postconditions.py                          # validate_runtime_postconditions()
  geometry_postcheck.py                      # validate_final_geometry() + STEP postcheck
  semantic_postcheck.py                      # run_semantic_postcheck()
  health.py                                  # ★ GeometryHealth + inspect_geometry_health()
  recovery.py                                # ★ handle_feature_failure() 统一降级
  bbox_tracker.py                            # measure_all_component_bboxes()
  constraint_resolver.py                     # ★ resolve_placements() 约束求解器
  spatial_audit.py                           # ★ run_geometry_spatial_audit()

validation/                                  (22 文件)
  __init__.py, reports.py                    # ValidationIssue/ValidationReport
  pipeline.py                                # ★ validate_and_canonicalize_with_bundle()
  bundle.py                                  # ValidationBundle
  canonicalize.py                            # ★ canonicalize() Raw→Canonical
  graph.py, structure.py, typecheck.py       # DAG/结构/类型校验
  params.py, ownership.py, phase.py          # 参数/所有权/阶段校验
  registry.py, safety.py                     # 注册表/安全标志校验
  dialect_semantics.py                       # ★ 每个方言的 validate_component()
  geometry_preflight.py                      # ★ 每个方言的 preflight_component()
  geometry_validate.py                       # 运行时几何体校验 (BRepCheck)
  geometric_solver.py                        # 确定性孔位约束求解
  hole_semantics.py                          # 孔语义校验
  measurement.py                             # 体积/bbox/距离/壁厚测量
  repair_hints.py                            # ★ 修复提示生成 (给 LLM 和 auto_fixer)
  root_terminal.py                           # 根节点终端检查
  spatial_contract.py                        # spatial_contract.json 校验
  composition.py                             # C001-C010 装配规则

base_packages/                               (7 文件)
  __init__.py, models.py, registry.py        # BasePackage 模型 + 注册表
  axisymmetric/package.py                    # ★ AXISYMMETRIC_BASE_PACKAGE
  sketch_extrude/package.py                  # ★ SKETCH_EXTRUDE_BASE_PACKAGE
  composition/package.py                     # ★ COMPOSITION_BASE_PACKAGE
  sketch_profile/package.py                  # ★ SKETCH_PROFILE_BASE_PACKAGE

bases/                                       [已废弃 v0.1]
  axisymmetric/ (5 文件)                     # AxisymmetricBase (CadQuery 执行器)
  sketch_extrude/ (5 文件)                   # SketchExtrudeBase (CadQuery 执行器)

compatibility/ (1 文件)
  legacy_spec_adapter.py                     # v0.1→v0.2 spec 适配

repair/ (3 文件)
  governor.py, hashes.py, patch.py           # 修复治理
```

### 3.2 文件规模估算

| 目录 | 文件数 | 估计代码行数 | 职责 |
|---|---|---|---|
| authoring/ + spatial/ | 31 | ~6,000 | 多阶段创作 + 空间意图 |
| dialects/ + geometry_utils/ | 30+ | ~5,000 | 方言系统 + OCP 几何 |
| validation/ | 22 | ~3,000 | 22 校验阶段 |
| runtime/ | 20 | ~2,500 | 运行时 + 空间求解 |
| ir/ | 11 | ~1,200 | 中间表示 |
| pipeline/ | 8 | ~1,000 | 主编排 + 元数据 |
| skills/ | 7 | ~800 | LLM prompt 编排 |
| analysis/ + compiler/ + planning/ | 14 | ~1,500 | 编译器中间端 |
| base_packages/ | 7 | ~600 | LLM 技能包 |
| llm/ | 5 | ~300 | DeepSeek 客户端 |
| **总计** | **132** | **~15,000+** | |

---

## 4. 模块地图

### 4.1 非 Primitive (LLM + 编译器) 链路架构层次

```
┌─────────────────────────────────────────────────┐
│  入口层 (Entry Layer)                            │
│  builder.py  tools.py  native_importers.py       │
├─────────────────────────────────────────────────┤
│  创作层 (Authoring Layer)                        │
│  authoring/pipeline.py  build_pipeline.py        │
│  authoring/schemas.py  raw_assembler.py          │
│  authoring/auto_fixer.py  strict_schema.py       │
│  authoring/spatial/ (v6 空间子系统)              │
├─────────────────────────────────────────────────┤
│  LLM 交互层 (LLM Interaction Layer)              │
│  llm/deepseek_client.py  skills/orchestrator.py │
│  skills/prompts.py  skills/schemas.py            │
│  skills/tool_schema_compiler.py                  │
├─────────────────────────────────────────────────┤
│  IR 层 (Intermediate Representation Layer)       │
│  ir/raw.py  ir/canonical.py  ir/expr.py          │
│  ir/semantic.py  ir/geometry_semantics.py        │
│  ir/values.py  ir/parse.py  ir/hashing.py        │
├─────────────────────────────────────────────────┤
│  校验与修复层 (Validation & Repair Layer)        │
│  validation/pipeline.py  validation/canonicalize.py │
│  16 个 RAW_STAGES 校验器  2 个 CANONICAL_STAGES    │
│  validation/repair_hints.py  geometric_solver.py  │
│  authoring/auto_fixer.py (20+ 确定性修复)         │
│  authoring/repair_agent.py (LLM 修复循环)         │
├─────────────────────────────────────────────────┤
│  编译器中间端 (Compiler Middle-End)              │
│  compiler/pass_manager.py  compiler/module.py    │
│  analysis/fact_propagation.py (Pass 1)           │
│  analysis/fact_rules.py (9 规则)                 │
│  analysis/expr_eval.py (DimExpr 求值)            │
│  planning/planner.py (Pass 2)                    │
├─────────────────────────────────────────────────┤
│  方言层 (Dialect Layer)                          │
│  dialects/base.py (协议)                         │
│  dialects/registry_core.py (注册表)              │
│  dialects/executor.py (统一执行器)               │
│  6 种方言: axisymmetric, sketch_extrude,         │
│    loft_sweep, shell_housing, composition,       │
│    sketch_profile                                │
│  geometry_utils/ (OCP 几何工具)                  │
├─────────────────────────────────────────────────┤
│  运行时层 (Runtime Layer)                        │
│  runtime/context.py  runtime/object_store.py     │
│  runtime/handles.py  runtime/cadquery_runtime.py │
│  runtime/health.py  runtime/recovery.py          │
│  runtime/constraint_resolver.py                  │
│  runtime/spatial_audit.py                        │
├─────────────────────────────────────────────────┤
│  管线层 (Pipeline Layer)                         │
│  pipeline/run.py  pipeline/artifact.py           │
│  pipeline/metadata_v3.py  pipeline/import_artifact.py │
└─────────────────────────────────────────────────┘
```

### 4.2 模块详细职责

#### 模块：入口层 (builder.py / tools.py / native_importers.py)

- **位置:** `generative_cad/builder.py`, `tools.py`, `native_importers.py`
- **核心职责:**
  - `builder.py`: 生产环境的 Text→STEP 入口 `build_generative_cad_model()`, 编排完整管线
  - `tools.py`: 构建 9 个 SeekFlow Agent 工具 (`@tool` 装饰器), 包括完整的 full_authoring 工具
  - `native_importers.py`: STEP→SolidWorks / STEP→NX 导入
- **所属层级:** API / Controller
- **主要输入:** `RawGcadDocument | dict`, `EngineeringToolsConfig`, 输出路径
- **主要输出:** `EngineeringActionResult` (builder), `ToolPolicy` 工具列表 (tools), `dict` (importers)
- **依赖的模块:** `validation.pipeline`, `pipeline.run`, `pipeline.metadata_v3`, `pipeline.artifact`, `ir.raw`, `ir.parse`, `dialects.default_registry`, `authoring.auto_fixer`, `native_importers`
- **被哪些模块调用:** CLI 入口、SeekFlow Agent 框架、测试脚本

#### 模块：LLM 交互层 (llm/ + skills/)

- **位置:** `generative_cad/llm/`, `generative_cad/skills/`
- **核心职责:**
  - `llm/deepseek_client.py`: DeepSeek API 调用, strict tool calling
  - `skills/orchestrator.py`: L1 路由/L2 创作 prompt 构建, L1/L2 tool schema 构建
  - `skills/prompts.py`: 硬编码 system prompt (L1: 11 安全规则; L2: 33 输出规则)
  - `skills/tool_schema_compiler.py`: 为每个操作生成精确的 JSON Schema variant
- **所属层级:** Infrastructure (外部 API 抽象)
- **关键类/函数:**
  - `DeepSeekToolCaller.call_strict_tool()` — 唯一的 LLM 调用入口
  - `build_level1_routing_prompt()` + `build_level2_authoring_prompt()`
  - `build_level1_tool()` + `build_level2_tool()` / `compile_level2_tool_schema()`
  - `DialectSelectionPlan` (L1 输出 Pydantic model)
- **依赖:** `openai.OpenAI` (指向 DeepSeek base URL), `authoring.strict_schema.to_deepseek_strict_schema()`
- **环境变量:** `DEEPSEEK_API_KEY` (必需)
- **关键实现细节:**
  - `strict=False` 避免 DeepSeek #1069 bug
  - `tool_choice="required"` + `thinking: {type: "disabled"}` 避免 #1376
  - 所有 Pydantic schema 通过 `to_deepseek_strict_schema()` 转换: inline $ref, number→integer, additionalProperties=false

#### 模块：IR 层 (ir/)

- **位置:** `generative_cad/ir/`
- **核心职责:** 定义 LLM 输出格式 (RawGcadDocument) 和校验后格式 (CanonicalGcadDocument)
- **关键数据结构:**
  - `RawGcadDocument` (LLM 输出, extra=forbid): schema_version, document_id, part_name, units, trust_level, selected_dialects, components, nodes, constraints, safety, llm_validation_hints
  - `CanonicalGcadDocument` (校验后): 与 Raw 相同 + canonical_version, contract_hash, canonical_graph_hash, typed_params, operation_effects, postconditions
  - `DimExpr` / `RefPath` / `DimExprOrFloat`: JSON 安全的维度表达式系统
  - `ValueType`: 字面量联合 (solid/solid_array/frame/plane/point/curve/profile/sketch/face_set/edge_set/component_ref)
  - `RawConstraints` / `RawSafety`: fail-closed 结构 (所有 require_* 必须显式 True)
- **关键校验:**
  - `RawValueRef.exactly_one_source()`: node 或 component 必须恰好一个
  - `RawNode.validate_required_policy()`: required 节点必须 degradation_policy='fail'
  - `RawSafety.all_true()`: 所有 7 个安全标志必须为 True
  - `DimExpr.validate_arg_count()`: 每个 ops 的元数检查
  - `RefPath.validate_path_segments()`: 路径段必须在白名单中 (17 个属性)

#### 模块：校验与修复层 (validation/ + authoring/auto_fixer.py + authoring/repair_agent.py)

- **位置:** `generative_cad/validation/`, `generative_cad/authoring/auto_fixer.py`, `generative_cad/authoring/repair_agent.py`
- **核心职责:** 11 阶段 RAW 校验 + 规范化 + 2 阶段 CANONICAL 校验 + 20+ 确定性修复 + LLM 修复循环
- **校验阶段 (按执行顺序):**
  1. `structure` — 组件/节点 ID 唯一性, root_node 存在性
  2. `root_terminal` — root_node 必须是终端 solid (输出不被其他节点消费)
  3. `registry` — 方言/操作在注册表中存在
  4. `params` — 每个节点的 params 通过 Pydantic 校验
  5. `ownership` — 所有权检查 (component owner_dialect, 跨组件引用规则)
  6. `graph` — DAG 无环验证 (DFS WHITE/GRAY/BLACK)
  7. `typecheck` — 输入/输出类型匹配
  8. `phase` — 阶段名匹配
  9. `composition` — 装配规则 C001-C010
  10. `hole_semantics` — 孔语义 (V1/V2 兼容)
  11. `safety` — 所有安全标志为 True
  12. `canonicalize` — Raw→Canonical 降低 (类型解析, contract_hash)
  13. `dialect_semantics` — 每个方言的 validate_component()
  14. `geometry_preflight` — 每个方言的 preflight_component() (几何可行性)
- **修复机制:**
  - `auto_fixer.py`: 20+ 确定性修复规则 (SYNTACTIC_ALIAS → SCHEMA_DEFAULT → CONTEXT_SAFE, 默认不允许 SEMANTIC_GUESS 和 DESTRUCTIVE)
  - `repair_agent.py`: 最多 3 轮 LLM 修复循环, 带 compiler diagnostics
  - `repair_hints.py`: "双重绑定" 检测 (孔同时碰到 bore 和 profile 边界)
  - `geometric_solver.py`: 确定性约束满足 (缩小孔/缩小 bore/增大外径)

#### 模块：编译器中间端 (compiler/ + analysis/ + planning/)

- **位置:** `generative_cad/compiler/`, `generative_cad/analysis/`, `generative_cad/planning/`
- **核心职责:** 在 canonicalize 和 execute 之间的只读旁路分析, 不修改 CanonicalGcadDocument
- **Compiler Pass 1 — FactPropagationPass:**
  - 拓扑排序节点 (Kahn 算法)
  - 为每个 solid-producing 节点调用 fact rule (9 个规则)
  - 解析 DimExpr (通过 FactStore 查找 RefPath)
  - 填充 FactStore (dual-index: by value_id + by node_output)
  - 发出可行性诊断 (FEASIBILITY ERROR/WARNING)
- **Compiler Pass 2 — PlannerPass:**
  - 检查 pattern 计数 vs BATCH_THRESHOLD/LARGE_THRESHOLD
  - 检查 destructible op 计数
  - 检查 edge_treatment 排序
  - 发出优化建议
- **配置门控:** `SEEKFLOW_GCAD_ENABLE_MIDDLE_END` 环境变量 (默认 "1")

#### 模块：方言层 (dialects/)

- **位置:** `generative_cad/dialects/`
- **核心职责:** 6 种建模方言的统一协议和实现
- **BaseDialect 协议方法:**
  - `manifest()` → 人类可读清单
  - `contract()` → 约束 (phase_order, allowed_ops, 硬限制)
  - `op_specs()` → dict[(dialect,op), OperationSpec]
  - `get_op_spec(op, version)` → OperationSpec
  - `validate_component(component, nodes)` → 语义校验
  - `preflight_component(component, nodes)` → 几何预检
  - `run_component(component, nodes, ctx)` → 执行
- **6 种方言:**

| 方言 | 操作数 | 阶段数 | 典型零件 |
|---|---|---|---|
| axisymmetric | 8 | 8 | 法兰、垫圈、阶梯轴、轴承座 |
| sketch_extrude | 11 | 6 | 块体、壳体、加筋板、安装座 |
| loft_sweep | 4 | 5 | 弹簧、管路、风管、异形管 |
| shell_housing | 2 | 3 | 抽壳件、空心体 |
| composition | 7 | 4 | 装配件 (union/cut/pattern/placement) |
| sketch_profile | 9 | 6 | 2D 草图→拉伸/切割 |

- **统一执行器:** `execute_operation()` 强制 OperationResult ABI (ok, outputs, warnings, degraded_features, metrics)
- **几何校验:** `_validate_geometry()` 对几何产生操作运行 BRepCheck + closed solid + volume
- **治理:** `governance.py` 禁止 21 个具体零件名 token 和 17 个具体操作名

#### 模块：运行时层 (runtime/)

- **位置:** `generative_cad/runtime/`
- **核心职责:** 类型化对象存储、句柄交换、输出解析、几何健康检查、特征失败恢复、空间约束求解
- **关键组件:**
  - `RuntimeContext`: 中央状态持有者 (object_store, outputs, warnings, degraded_features, metrics, spatial_placements, compiler_diagnostics, health_log)
  - `RuntimeObjectStore`: 类型化对象存储 (SolidHandle, FrameHandle, PlaneHandle...)
  - `RuntimeHandle` 子类: SolidHandle, SolidArrayHandle, FrameHandle, PlaneHandle, PointHandle, CurveHandle, ProfileHandle, EdgeHandle, FaceHandle
  - `handle_feature_failure()`: 统一降级决策 (required→raise, optional→warn+skip)
  - `GeometryHealth`: BRep/closed/bbox/volume 评分 (0.0-1.0)
  - `ConstraintResolver`: 符号约束→数值 placement (identity→stack→align_axis→symmetric→contact)
  - `GeometrySpatialAudit`: 装配后空间审计 (overlap, Z-order, connectivity, bbox)

#### 模块：管线层 (pipeline/)

- **位置:** `generative_cad/pipeline/`
- **核心职责:** 主编排器、元数据生成、STEP 导出、导入门控
- **主编排器:** `run_canonical_gcad()` 的 13 步执行序列:
  1. RuntimeContext 创建
  2. Compiler middle-end
  3. `_run_components()` (leaf 组件)
  4. Spatial constraint resolution (v6)
  5. `_run_composition_or_select_final()` (assembly or single)
  6. Geometry Spatial Audit (v6)
  7. Runtime postconditions 校验
  8. STEP 导出
  9. Geometry postcheck
  10. Metadata build (v3)
  11. Artifact build
  12. Artifact/metadata 一致性检查
  13. 返回 GcadRunResult
- **导入门控:** `validate_generative_step_artifact_for_native_import()` 检查 15+ 条件才允许原生格式导入

---

## 5. 模块关系清单

### 5.1 主要调用关系

```
- tools.py → builder.py
  - 调用方向: tools.py 的 full_authoring 工具调用 builder.py
  - 具体调用位置: tools.py:generative_cad_full_authoring() → build_generative_cad_model()
  - 传递的数据: user_request (str), out_dir (str), EngineeringToolsConfig
  - 返回的数据: EngineeringActionResult
  - 同步/异步: 同步

- builder.py → validation/pipeline.py → pipeline/run.py
  - 调用方向: 入口 → 校验 → 运行
  - 具体调用位置: builder.py:build_generative_cad_model() → validate_and_canonicalize_with_bundle() → run_canonical_gcad()
  - 传递的数据: RawGcadDocument → ValidationReport + CanonicalGcadDocument + ValidationBundle → GcadRunResult
  - 副作用: STEP 文件写入, metadata JSON 写入

- skills/orchestrator.py → llm/deepseek_client.py
  - 调用方向: Prompt 构建后调用 LLM
  - 具体调用位置: 测试脚本中 pattern: l1 = build_level1_routing_prompt(); caller.call_strict_tool(messages=[...], tool_schema=l1_tool)
  - 传递的数据: system prompt + user prompt → tool schema → ToolCallResult
  - 返回的数据: ToolCallResult(arguments=dict)

- skills/orchestrator.py → skills/tool_schema_compiler.py
  - 调用方向: L2 tool schema 编译
  - 具体调用位置: build_level2_tool() 内部调用 compile_level2_tool_schema()
  - 传递的数据: selected_dialects, registry, base_package_registry
  - 返回的数据: DeepSeek-strict JSON schema dict

- authoring/pipeline.py → authoring/raw_assembler.py
  - 调用方向: 创作管线最后阶段
  - 具体调用位置: generate_gcad_from_user_request() Stage 5: assemble_raw_gcad_document()
  - 传递的数据: user_request, route_plan, feature_sequence, node_params, dialect_registry
  - 返回的数据: RawAssemblyResult (含 RawGcadDocument dict + 哈希)
  - 副作用: 系统填充 schema_version, trust_level, document_id, units, constraints, safety, selected_dialects

- validation/pipeline.py → validation/canonicalize.py
  - 调用方向: RAW_STAGES 通过后 → canonicalize
  - 具体调用位置: validate_and_canonicalize_with_bundle() 中调用 canonicalize()
  - 传递的数据: RawGcadDocument
  - 返回的数据: (CanonicalGcadDocument | None, ValidationReport)
  - 关键变换: 类型解析, contract_hash 查找, graph_hash 计算

- compiler/pass_manager.py → analysis/fact_propagation.py → analysis/fact_rules.py
  - 调用方向: 编译器 Pass 管理 → Pass 1 → 事实规则
  - 具体调用位置: build_compiler_module() → FactPropagationPass.run() → get_fact_rule() → rule_*()
  - 传递的数据: CanonicalNode → typed_params (含 DimExpr dicts) → ShapeFacts
  - 返回的数据: ShapeFacts (bbox, radii, faces)

- dialects/executor.py → dialect handlers (各方言)
  - 调用方向: 统一执行器 → 方言处理器
  - 具体调用位置: execute_operation() → op_spec.handler(node, ctx)
  - 传递的数据: CanonicalNode, RuntimeContext
  - 返回的数据: OperationResult (ok, outputs, warnings, degraded_features, metrics)

- pipeline/run.py → runtime/context.py (全部运行时状态)
  - 调用方向: 主编排器创建并传递 RuntimeContext 贯穿所有阶段
  - RuntimeContext 是每个阶段的输入参数

- pipeline/run.py → runtime/constraint_resolver.py → runtime/spatial_audit.py
  - 调用方向: v6 空间管线: 加载 spatial_contract → 求解 → 审计
  - 具体调用位置: run_canonical_gcad() 中 _load_spatial_contract() → resolve_placements() → run_geometry_spatial_audit()
  - 传递的数据: spatial_contract.json → SpatialConstraintGraph → dict[component_id, NumericPlacement] → GeometrySpatialAuditReport

- authoring/auto_fixer.py → ir/raw.py (RawGcadDocument schema)
  - 调用方向: 自动修复器使用 raw schema 作为修复指引
  - 具体调用位置: auto_fix_with_report() 中 _fix_param_names 使用 PARAM_NAME_FIXES 字典
  - 传递的数据: raw dict (in/out mutation)
  - 副作用: 深拷贝后原地修改文档 dict
```

### 5.2 数据流向总结

```
用户自然语言 (str)
  │
  ▼
[L1 路由] (DeepSeek v4-pro, tool_choice=required)
  │ 输出: DialectSelectionPlan (JSON)
  ▼
[L2 创作] (DeepSeek v4-pro, 41-variant schema 通过 strict=False)
  │ 输出: RawGcadDocument dict (LLM 生成)
  ▼
[系统填充] (raw_assembler.py)
  │ 系统填入: schema_version, trust_level, safety, constraints, selected_dialects versions
  │ 系统填入: node op_version, outputs 类型, inputs 连线, phase, pairwise boolean_union 展开
  ▼
[确定性修复] (auto_fixer.py, 20+ 规则)
  │ 修复: 参数名别名、输出名、方言名、phase 名、缺失字段、多余字段、零值
  ▼
[RAW 校验] (11 阶段, fail-fast)
  │ structure → root_terminal → registry → params → ownership → graph → typecheck
  │ → phase → composition → hole_semantics → safety
  ▼
[规范化] (canonicalize.py)
  │ RawGcadDocument → CanonicalGcadDocument
  │ 类型解析, contract_hash, graph_hash, typed_params
  ▼
[CANONICAL 校验] (2 阶段)
  │ dialect_semantics → geometry_preflight
  ▼
[编译器中间端] (如果 SEEKFLOW_GCAD_ENABLE_MIDDLE_END=1)
  │ Pass 1: FactPropagationPass (拓扑排序 → fact rules → DimExpr 求解 → FactStore)
  │ Pass 2: PlannerPass (pattern 计数/排序分析 → PlanningReport)
  │ 输出: CompilerModule (diagnostics, facts, planning_report) → 存入 RuntimeContext
  ▼
[运行时组件执行] (_run_components)
  │ 非 assembly 组件: topological sort → execute_operation() → OperationResult
  │ 执行 _validate_geometry() 记录 GeometryHealth
  │ handle_feature_failure() 处理 required/optional 降级
  ▼
[空间约束求解] (v6, 如果有 spatial_contract.json)
  │ 加载 spatial_contract → measure_all_component_bboxes() → resolve_placements()
  │ → 空间审计 (overlap, connectivity, Z-order)
  ▼
[装配/终选] (_run_composition_or_select_final)
  │ 多组件: 运行 __assembly__ 组件 (composition dialect)
  │ 单组件: 选择 leaf 组件的 root_node 输出
  ▼
[STEP 导出] (CadQueryRuntime.export_step)
  │ OCCT STEPControl_Writer → .step 文件
  ▼
[后处理] (postconditions + geometry_postcheck + semantic_postcheck)
  │ 验证 final solid 存在/封闭/有体积/bbox 有效
  │ 检查语义预期 (bbox 范围, 特征计数)
  ▼
[元数据 + 工件] (metadata_v3 + artifact)
  │ 构建 GenerativeMetadataV3 (含 SHA256, runtime proof, import policy)
  │ 构建 CanonicalStepArtifact
  ▼
[原生格式导入] (可选)
  │ validate_generative_step_artifact_for_native_import() → 15+ gate checks
  │ import_step_to_solidworks() / import_step_to_nx()
  ▼
输出: .step 文件 + metadata.json + (可选 .SLDPRT / .prt)
```

---

## 6. 核心功能流程

### 6.1 功能流程：Text→STEP 完整非 Primitive 管线

#### 功能目的
将自然语言机械设计描述转换为经过校验的 STEP 文件和元数据证明。

#### 入口
- **文件:** `builder.py`
- **类/函数:** `build_generative_cad_model()`
- **触发方式:** SeekFlow Agent 工具调用或测试脚本直接调用
- **输入来源:** 用户自然语言字符串 + `EngineeringToolsConfig`

#### 流程步骤

**步骤 1: 解析输入 (parse)**
- 执行位置: `builder.py:build_generative_cad_model()` → `ir/parse.py:parse_raw_gcad_document()`
- 输入: `dict | RawGcadDocument`
- 处理逻辑: 如果输入是 dict, 通过 4-step 预 Pydantic 解析 (top-level keys → safety keys → constraint keys → Pydantic model_validate)
- 输出: `RawParseResult` (ok, document, issues)
- 副作用: 无

**步骤 2: 校验 + 规范化 (validate + canonicalize)**
- 执行位置: `validation/pipeline.py:validate_and_canonicalize_with_bundle()`
- 输入: `RawGcadDocument`
- 处理逻辑: 11 RAW_STAGES → canonicalize → 2 CANONICAL_STAGES → repair_hints
- 输出: `(CanonicalGcadDocument|None, ValidationReport, ValidationBundle)`
- 错误处理: 任何阶段失败立即短路返回

**步骤 3: 运行时执行 (runtime)**
- 执行位置: `pipeline/run.py:run_canonical_gcad()`
- 输入: `CanonicalGcadDocument`, 输出路径, `ValidationBundle`
- 处理逻辑: 13 步序列 (见上文 §4.2 管线层)
- 输出: `GcadRunResult` (ok, step_path, metadata_path, artifact, warnings, degraded_features, metrics)
- 副作用: STEP 文件写入, metadata JSON 写入

**步骤 4: 工件构建 (artifact)**
- 执行位置: `pipeline/artifact.py:build_canonical_step_artifact()`
- 输入: canonical doc, step_path, metadata_path, validation dict, inspection dict, ctx
- 输出: `CanonicalStepArtifact` dict (state="validated_reference_step")
- 副作用: SHA256 计算

**步骤 5: 原生导入 (可选)**
- 执行位置: `native_importers.py:import_step_to_solidworks()` 或 `import_step_to_nx()`
- 输入: step_path, output native path, config
- 输出: `{"ok": True/False, "files_created": [...], "diagnostics": {...}}`
- 副作用: SolidWorks/NX 进程启动, .SLDPRT/.prt 文件写入

#### 最终输出
- `output.step` — ISO-10303-21 STEP 文件
- `output.metadata.json` — GenerativeMetadataV3 (含 SHA256, runtime proof, import policy)
- `output.SLDPRT` (可选) — SolidWorks 原生零件
- `output.prt` (可选) — Siemens NX 原生零件

#### 异常路径
- L1_FAIL: LLM 路由失败 (API error, invalid JSON, no tool call)
- L2_FAIL: LLM 创作失败
- VAL_FAIL: 校验失败 (11 个 RAW 阶段中任意一个)
- RT_FAIL: 运行时失败 (几何内核崩溃, OCP segfault)
- VAL_EXC: 校验器异常
- RT_EXC: 运行时异常 (MemoryError, timeout)

---

### 6.2 功能流程：多阶段创作管线 (Staged Authoring)

#### 功能目的
将单次 LLM L2 调用拆分为 Route → FeatureSequence → NodeParams (per-node) 三阶段, 提高 LLM 输出质量。

#### 入口
- **文件:** `authoring/pipeline.py`
- **函数:** `generate_gcad_from_user_request()`
- **触发方式:** `authoring/build_pipeline.py:generate_validate_build_step()` 中调用

#### 流程步骤

**Stage 0: 空间前端 (可选, v6)**
- 如果 `enable_spatial_frontend=True` 或 `auto_spatial=True`
- 调用 `authoring/spatial/pipeline.py:run_spatial_authoring_frontend()`
- 多轮 LLM 交互: 提取对象图 → archetype 匹配 → 约束图 → Phase A 验证 → 问题 → 答案规范化

**Stage 1: 路由 (Route)**
- LLM 调用: `route_caller.call_strict_tool()` 使用 `build_route_plan_tool_schema()`
- 输出: `RoutePlan` (route_decision, selected_dialects, part_intent, etc.)
- 校验: validate_route_invariants (route_decision 一致性)

**Stage 2: 构建上下文 (Build Context)**
- `build_authoring_context()`:
  - 加载 dialect contracts (hash 校验)
  - 加载 BasePackage level2_usage_skills (markdown)
  - 计算 tool_schema_hash 和 context_hash

**Stage 3: 特征序列 (Feature Sequence)**
- LLM 调用: `feature_sequence_caller.call_strict_tool()` 使用 `build_feature_sequence_tool_schema()`
- 输出: `FeatureSequenceDraft` (components, node_sequence, assumptions)
- 校验: validate_has_nodes

**Stage 4: 节点参数 (Node Params, per-node)**
- 对每个 node, 单独调用 LLM:
  - 构建当前节点 operation 专属的精确 JSON Schema (含 params_model 的所有字段)
  - 只允许输出这一个节点的 params
- 输出: `NodeParamsDraft` (node_id, dialect, op, op_version, params, assumptions)
- 严格一致性检查: node_id/dialect/op/op_version 必须与 plan 完全一致

**Stage 5: 组装 (Assemble)**
- `assemble_raw_gcad_document()`:
  - 系统填入: schema_version, trust_level, safety (全部 true)
  - 系统填入: selected_dialects versions (从 registry)
  - 系统填入: node 的 op_version (从 OperationSpec), phase (从 dialect phase_order)
  - 系统填入: outputs 类型 (从 OperationSpec.output_types)
  - 系统填入: inputs 连线 (通过 AvailabilityMap 自动连线)
  - 展开: pairwise boolean_union (3+ solids 时自动展开)
  - cross-component refs 转为 component refs

**Stage 6: 解析 + 校验 + 规范化**
- 同 6.1 步骤 2

**Stage 7a: 确定性自动修复**
- `auto_fix_with_report()`: 20+ 规则, 仅 SYNTACTIC_ALIAS + SCHEMA_DEFAULT + CONTEXT_SAFE

**Stage 7b: LLM 修复循环 (可选)**
- 最多 3 轮: prompt (含 compiler diagnostics + DimExpr 支持提示) → DeepSeek → autofix → 重校验

---

### 6.3 功能流程：编译器中间端分析

#### 功能目的
在规范化之后、运行时执行之前, 对 canonical IR 进行只读几何分析, 产生诊断和规划报告。

#### 入口
- **文件:** `pipeline/run.py:run_canonical_gcad()`
- **调用:** `build_compiler_module(canonical)` → `run_compiler_passes(module, passes)`
- **门控:** `compiler/config.py:middle_end_enabled()` (env `SEEKFLOW_GCAD_ENABLE_MIDDLE_END`)

#### Pass 1: FactPropagationPass

1. 验证 canonical 存在
2. 创建 FactStore
3. 对每个非 assembly 组件:
   a. 拓扑排序 (Kahn 算法, DFS 降级)
   b. 对每个节点:
      - 查找 fact rule (dialect, op) → FACT_RULES 注册表
      - 如果找到: 解析 DimExpr (调用 `resolve_typed_params_dim_exprs`)
      - 调用 fact rule → ShapeFacts
      - 绑定到 FactStore (by value_id + by node_output)
      - 从 notes 提取可行性诊断 (FEASIBILITY ERROR/WARNING)
4. 对 __assembly__ 组件: 同样处理

**Fact Rules 注册表 (9 个规则):**

| 规则函数 | (dialect, op) | 推导内容 |
|---|---|---|
| rule_revolve_profile | (axisymmetric, revolve_profile) | max/min radius, bbox, zlen, faces |
| rule_cut_center_bore | (axisymmetric, cut_center_bore) | 输入传播, inner_cylindrical face, 可行性 |
| rule_cut_circular_hole_pattern | (axisymmetric, cut_circular_hole_pattern) | 输入传播, 外缘/内缘干涉检查 |
| rule_cut_annular_groove | (axisymmetric, cut_annular_groove) | 输入传播, groove outer vs body radius_max |
| rule_extrude_rectangle | (sketch_extrude, extrude_rectangle) | bbox 从 w/h/d + plane, 6 faces, traits |
| rule_translate_solid | (composition, translate_solid) | bbox 平移 |
| rule_boolean_union | (composition, boolean_union) | 保守 bbox = 各自 bbox 的并集 |
| rule_boolean_cut | (composition, boolean_cut) | 输入传播, 不相交/完全包含警告 |

#### Pass 2: PlannerPass

4 个静态检查:
1. pattern 计数 vs BATCH_THRESHOLD (8) / LARGE_THRESHOLD (120)
2. destructive op 计数 vs MANY_DESTRUCTIVE_OPS_THRESHOLD (32)
3. edge_treatment 排序 (是否在后续 destructive op 之前)
4. 发出结构化 PlanningIssue → PlanningReport

---

### 6.4 功能流程：方言运行时执行

#### 功能目的
将 canonical IR 的每个节点翻译为具体的几何操作 (CadQuery/OCCT) 并产生 solid body。

#### 入口
- **文件:** `pipeline/run.py:_run_components()` 或各 dialect 的 `run_component()`
- **核心函数:** `dialects/executor.py:execute_operation()`

#### 执行步骤 (execute_operation 的 5 步)

1. **缓存检查:** `ctx.cache.get(node)` → 命中则返回
2. **调用 handler:** `op_spec.handler(node, ctx)`
   - v1_dict: 传统 dict[str,str] 返回值 → adapt_legacy_handler_result()
   - v2_result: 直接返回 OperationResult
3. **标准化:** 确保输出是 `OperationResult` ABI
4. **校验:** `_validate_operation_result()` — ok=True, 输出名称/类型/句柄 完全匹配声明
5. **几何校验:** `_validate_geometry()` — BRepCheck + closed solid + volume → GeometryHealth
   - required + unhealthy → RuntimeError
   - optional + unhealthy → warning

#### handler 内部流程 (以 axisymmetric revolve_profile 为例)

1. 解析输入: `resolve_input_handle_id(node, ctx, 0)` → 前驱 solid handle
2. 获取前驱 solid: `ctx.object_store.get(handle_id)`
3. 读取 typed_params: `node.typed_params` (已经过 DimExpr 求解)
4. 构建几何: CadQuery/OCCT 操作
   - revolve_profile: 构建 2D 线轮廓在 RZ 平面, revolve 360°
5. 存储结果: `_store_solid(node, ctx, obj)` → SolidHandle → object_store
6. 返回: `{"body": handle_id}` 或 `{"body": handle_id, "outer_frame": frame_id}`

#### 错误处理

所有 handler 使用 `runtime/recovery.py:handle_feature_failure()`:
- `required=True` → 抛出 RuntimeError (fail-closed)
- `required=False` + `degradation_policy="may_skip_with_warning"` → 记录 warning, 返回原始 body
- 其他组合 → 抛出 RuntimeError

---

## 7. 调用链分析

### 7.1 编者注

由于调用链极为密集, 以下聚焦关键路径, 标注具体文件和行号范围 (根据代码结构推断, 非精确行号)。

### 7.2 主调用链 (Text→STEP)

```
用户文本
  │
  ├─[L1] skills/orchestrator.py:build_level1_routing_prompt()
  │       → skills/prompts.py:LEVEL1_ROUTING_SYSTEM_PROMPT (11 安全规则)
  │       → skills/orchestrator.py:build_level1_tool()
  │       → llm/deepseek_client.py:DeepSeekToolCaller.call_strict_tool()
  │       → authoring/strict_schema.py:to_deepseek_strict_schema()
  │       → openai.OpenAI.chat.completions.create(tools=[...], tool_choice="required")
  │       → 输出: ToolCallResult → DialectSelectionPlan
  │
  ├─[L2] skills/orchestrator.py:build_level2_authoring_prompt()
  │       → skills/prompts.py:LEVEL2_AUTHORING_SYSTEM_PROMPT (33 输出规则)
  │       → skills/orchestrator.py:build_level2_tool()
  │       │   → skills/tool_schema_compiler.py:compile_level2_tool_schema()
  │       │   → 为每个操作生成精确 JSON Schema variant (extra=forbid, 所有 constraints)
  │       → llm/deepseek_client.py:call_strict_tool()
  │       → 输出: RawGcadDocument dict
  │
  ├─[AUTOFIX] authoring/auto_fixer.py:auto_fix_with_report()
  │       → 20+ 修复规则顺序执行
  │       → 输出: (fixed_dict, AutoFixReport)
  │
  ├─[VALIDATE] validation/pipeline.py:validate_and_canonicalize_with_bundle()
  │       → ir/parse.py:parse_raw_gcad_document() (4-step parse)
  │       → _run_stage_collect() → 11 RAW_STAGES
  │       → validation/canonicalize.py:canonicalize()
  │       → _run_stage_collect() → 2 CANONICAL_STAGES
  │       → validation/repair_hints.py:build_repair_hints_from_validation()
  │       → 输出: (CanonicalGcadDocument, ValidationReport, ValidationBundle)
  │
  ├─[COMPILER] compiler/pass_manager.py:build_compiler_module()
  │       → 门控: compiler/config.py:middle_end_enabled()
  │       → analysis/fact_propagation.py:FactPropagationPass.run()
  │       │   → _topological_sort() (Kahn)
  │       │   → for each node: get_fact_rule() → rule_*() → resolve_typed_params_dim_exprs()
  │       → planning/planner.py:PlannerPass.run()
  │       → 输出: CompilerModule (存入 ctx.compiler_diagnostics)
  │
  ├─[RUNTIME] pipeline/run.py:_run_components()
  │       → 每个 component: dialect.run_component() 或 _run_mixed_dialect_component()
  │       → dialects/executor.py:execute_operation()
  │       │   → op_spec.handler(node, ctx)
  │       │   → _validate_operation_result()
  │       │   → _validate_geometry() (BRepCheck)
  │       → runtime/recovery.py:handle_feature_failure() (统一降级)
  │
  ├─[SPATIAL] (如果有 spatial_contract) pipeline/run.py:_load_spatial_contract()
  │       → runtime/bbox_tracker.py:measure_all_component_bboxes()
  │       → runtime/constraint_resolver.py:resolve_placements()
  │       → runtime/spatial_audit.py:run_geometry_spatial_audit()
  │
  ├─[ASSEMBLY] pipeline/run.py:_run_composition_or_select_final()
  │       → composition dialect: handle_boolean_union (3 层降级)
  │
  ├─[EXPORT] runtime/cadquery_runtime.py:export_step()
  │       → OCCT STEPControl_Writer
  │
  └─[POST] runtime/postconditions.py + geometry_postcheck.py + semantic_postcheck.py
          → pipeline/metadata_v3.py:build_generative_metadata_v3()
          → pipeline/artifact.py:build_canonical_step_artifact()
```

### 7.3 数据转换调用链

```
用户文本 (str)
  → [DeepSeek API] → arguments dict
  → [Pydantic] → DialectSelectionPlan (typed)
  → [DeepSeek API] → arguments dict
  → [Pydantic] → RawGcadDocument (typed)
  → [raw_assembler] → dict (system-filled)
  → [auto_fixer] → dict (deterministically fixed)
  → [parse] → RawGcadDocument
  → [11 RAW_STAGES] → ValidationReport (issues accumulated)
  → [canonicalize] → CanonicalGcadDocument (types resolved)
  → [2 CANONICAL_STAGES] → ValidationReport
  → [FactPropagation] → FactStore (analysis output)
  → [PlannerPass] → PlanningReport
  → [dialect.run_component] → CadQuery Workplane objects
  → [execute_operation] → OperationResult (ABI)
  → [object_store] → SolidHandle (typed)
  → [resolve_placements] → NumericPlacement dict
  → [spatial_audit] → GeometrySpatialAuditReport
  → [CadQueryRuntime] → .step file (ISO-10303-21)
  → [metadata_v3] → .metadata.json (JSON)
  → [artifact] → CanonicalStepArtifact dict
  → [SolidWorksClient] → .SLDPRT file (可选)
```

---

## 8. 数据流分析

### 8.1 主要数据流：文本 → IR → 几何体 → 文件

**数据名:** 用户请求 → Canonical IR → 运行时对象 → STEP

**来源:** 用户自然语言输入
**经过的模块:**
1. `skills/orchestrator.py` — L1 routing prompt 构建
2. `llm/deepseek_client.py` — DeepSeek API 调用 → ToolCallResult
3. `skills/schemas.py` — DialectSelectionPlan 解析
4. `skills/orchestrator.py` — L2 authoring prompt 构建 (含 dialect contracts + level2_usage)
5. `llm/deepseek_client.py` — DeepSeek API 调用 → ToolCallResult
6. `ir/parse.py` — RawGcadDocument 解析
7. `authoring/auto_fixer.py` — 确定性修复
8. `validation/pipeline.py` — 14 阶段校验
9. `validation/canonicalize.py` — Raw → Canonical 降低
10. `compiler/pass_manager.py` — 编译器 Pass
11. `dialects/executor.py` — 统一执行器
12. `runtime/health.py` — GeometryHealth 记录
13. `runtime/cadquery_runtime.py` — STEP 导出
14. `pipeline/metadata_v3.py` — metadata 生成

**转换过程:**
- `str` → `dict` (JSON parse in DeepSeek client)
- `dict` → `DialectSelectionPlan` (Pydantic)
- `DialectSelectionPlan` + `str` → `dict` (LLM L2 output)
- `dict` → `RawGcadDocument` (Pydantic)
- `dict` → `dict` (20+ autofix mutations)
- `RawGcadDocument` → `CanonicalGcadDocument` (type resolution, hash computation)
- `CanonicalNode.typed_params` → `float` (DimExpr resolution in FactPropagation)
- `CanonicalNode` → `CadQuery Workplane` (dialect handlers)
- `CadQuery Workplane` → `.step` file (OCCT export)

**是否持久化:** 是 — STEP 文件, metadata JSON, canonical JSON (可选)

**是否有副作用:** 是 — 磁盘 I/O, SolidWorks/NX 进程启动 (可选)

---

### 8.2 数据流：DimExpr 符号表达式求值

**数据名:** DimExpr dict → 具体 float

**来源:** LLM 在 params 中使用 DimExpr (如 `{"kind":"dim_expr","op":"ref","args":[{"root_kind":"component",...}],"unit":"mm"}`)

**经过的模块:**
1. `ir/expr.py` — DimExprOrFloat BeforeValidator (接受 float 或 dict)
2. `analysis/expr_eval.py` — evaluate_dim_expr() (在 FactPropagationPass 期间)
3. `analysis/facts.py` — FactStore (RefPath 查找目标)

**转换过程:**
- `DimExprOrFloat` → `DimExpr dict` (如果输入是 dict)
- `DimExpr.op="ref"` → `_resolve_ref()` → `_walk_fact_path()` → `NumericFact.value`
- `DimExpr.op="add"` → 递归求值 args → sum
- `DimExpr.op="mul"` → 递归求值 args → product
- `DimExpr.op="clamp"` → 递归求值 args[0], 限制在 args[1]..args[2]

**是否持久化:** 否 (临时, 但结果存入 FactStore)

---

## 9. 接口契约

### 9.1 DeepSeekToolCaller.call_strict_tool()

- **位置:** `llm/deepseek_client.py:23`
- **调用方:** 测试脚本、创作管线、空间管线
- **被调用方:** `openai.OpenAI.chat.completions.create()` (指向 `https://api.deepseek.com/beta`)
- **职责:** 调用 DeepSeek API 进行单次 strict tool calling, 强制恰好一个 tool call
- **输入参数:**
  - `messages: list[dict[str, Any]]` — 必填, 标准 OpenAI chat messages
  - `tool_name: str` — 必填, 期望的 tool name
  - `tool_description: str` — 必填, tool 描述
  - `tool_schema: dict[str, Any]` — 必填, Pydantic JSON Schema (将被转换为 DeepSeek strict 子集)
  - `model_config: LlmModelConfig` — 必填, model/base_url/timeout/temperature
- **返回值:**
  - 类型: `ToolCallResult`
  - 字段: `tool_name`, `arguments: dict[str, Any]`, `raw_response_id`, `model`, `provider`
- **可能抛出的异常:**
  - `LlmToolCallError("DEEPSEEK_API_KEY not set", code="provider_no_auth")`
  - `LlmToolCallError("openai package required", code="provider_missing_dependency")`
  - `LlmToolCallError("API call failed", code="provider_api_error")`
  - `LlmToolCallError("no tool call", code="provider_no_tool_call")`
  - `LlmToolCallError("multiple tool calls", code="provider_multiple_tool_calls")`
  - `LlmToolCallError("wrong tool name", code="provider_wrong_tool_name")`
  - `LlmToolCallError("invalid JSON", code="provider_invalid_json")`
  - `LlmToolCallError("arguments not object", code="provider_arguments_not_object")`
- **前置条件:** `DEEPSEEK_API_KEY` 环境变量已设置, `openai` 包已安装
- **后置条件:** 返回的 arguments 是 dict (已 JSON.parse)
- **副作用:** HTTP 请求到 `api.deepseek.com`
- **是否依赖全局状态:** 是 (`DEEPSEEK_API_KEY` 环境变量)
- **是否同步/异步:** 同步

### 9.2 方言注册表接口 (BaseDialect 协议)

- **位置:** `dialects/base.py:BaseDialect`
- **调用方:** `validation/canonicalize.py`, `validation/registry.py`, `validation/dialect_semantics.py`, `validation/geometry_preflight.py`, `pipeline/run.py`, 所有测试
- **被调用方:** 6 种方言实现 (axisymmetric, sketch_extrude, loft_sweep, shell_housing, composition, sketch_profile)
- **方法契约:**
  - `manifest() -> dict[str, Any]` — 返回人类可读清单
  - `contract() -> dict[str, Any]` — 返回 phase_order + allowed_ops
  - `op_specs() -> dict[tuple[str, str], OperationSpec]` — 所有操作的规格
  - `default_op_version(op: str) -> str` — 操作的默认版本
  - `get_op_spec(op: str, version: str | None) -> OperationSpec` — 查找特定操作
  - `validate_component(component, nodes) -> ValidationReport` — 语义校验
  - `preflight_component(component, nodes) -> ValidationReport` — 几何预检
  - `run_component(component, nodes, ctx) -> dict[str, str]` — 执行
- **特征:**
  - `dialect_id: str` — 方言唯一标识
  - `version: str` — 方言版本
  - `phase_order: tuple[str, ...]` — 阶段排序
- **前置条件:** 方言已通过 `registry.register()` 注册
- **后置条件:** run_component 执行后, outputs 绑定到 ctx

### 9.3 assemble_raw_gcad_document()

- **位置:** `authoring/raw_assembler.py:assemble_raw_gcad_document()`
- **调用方:** `authoring/pipeline.py:generate_gcad_from_user_request()` Stage 5
- **职责:** 将分阶段 LLM 输出组装为完整的 RawGcadDocument dict
- **输入参数:**
  - `user_request: str` — 原始用户请求
  - `route_plan: RoutePlan` — Stage 1 输出
  - `feature_sequence: FeatureSequenceDraft` — Stage 3 输出
  - `node_params: dict[str, NodeParamsDraft]` — Stage 4 输出
  - `dialect_registry` — 方言注册表
  - `document_id: str | None` — 可选, 默认生成 UUID
  - `units: str = "mm"` — 单位
- **返回值:**
  - 类型: `RawAssemblyResult`
  - 字段: `raw_document: dict`, `source_route_plan_hash: str`, `source_feature_sequence_hash: str`, `source_node_params_hashes: dict`, `system_filled_fields: list[str]`
- **系统填入的字段:**
  - `schema_version` → `"0.2.0"`
  - `trust_level` → `"reference_geometry"`
  - `safety` → 全部 7 个标志 = True
  - `selected_dialects[*].version` → 从 registry 获取
  - `nodes[*].op_version` → 从 OperationSpec 获取
  - `nodes[*].outputs` → 从 OperationSpec.output_types 重建
  - `nodes[*].inputs` → 通过 AvailabilityMap 自动连线
  - `nodes[*].phase` → 从 dialect phase_order 推断
  - `constraints` → require_step_file/require_metadata_sidecar/require_closed_solid = True
  - 3+ solids 的 boolean_union → 自动展开为 pairwise union
- **可能抛出的异常:** `AssemblyError(ValueError)` — 输出类型未知, 连线失败
- **前置条件:** route_plan, feature_sequence, node_params 已产出

### 9.4 validate_and_canonicalize_with_bundle()

- **位置:** `validation/pipeline.py:validate_and_canonicalize_with_bundle()`
- **调用方:** `builder.py`, `authoring/pipeline.py`, `authoring/build_pipeline.py`, 所有测试
- **职责:** 完整的校验 + 规范化管线
- **输入参数:**
  - `raw: dict | RawGcadDocument` — 必填
- **返回值:**
  - 类型: `tuple[CanonicalGcadDocument | None, ValidationReport, ValidationBundle]`
  - ValidationReport: `ok: bool`, `stage: str`, `issues: list[ValidationIssue]`
  - ValidationBundle: `ok: bool`, `raw_stage_reports: dict`, `canonicalize_report`, `canonical_stage_reports: dict`, `repair_hints: str`
- **可能抛出的异常:** 无 — 所有错误编码在 reports 中
- **前置条件:** 无 (接受 dict 或 Pydantic model)
- **后置条件:** 如果 ok=True, canonical 不为 None

### 9.5 execute_operation()

- **位置:** `dialects/executor.py:execute_operation()`
- **调用方:** 所有方言的 `run_component()`, `pipeline/run.py:_run_mixed_dialect_component()`
- **职责:** 统一操作执行, 强制 OperationResult ABI
- **输入参数:**
  - `node: CanonicalNode` — 必填, 包含 typed_params
  - `op_spec: OperationSpec` — 必填, 含 handler 函数引用
  - `ctx: RuntimeContext` — 必填
- **返回值:**
  - 类型: `ExecutedNode`
  - 字段: `node_id: str`, `outputs: dict[str, str]` (output_name → handle_id)
- **可能抛出的异常:**
  - `RuntimeError` — required 节点几何体不健康
  - `ValueError` — 输出名/类型/句柄不匹配
- **前置条件:** node 已通过 canonicalize, ctx.object_store 已初始化
- **后置条件:** 输出句柄绑定到 ctx.object_store 和 ctx.node_outputs
- **副作用:**
  - 写入 ctx.object_store
  - 写入 ctx.geometry_health_log
  - 写入 ctx.warnings, ctx.degraded_features, ctx.operation_metrics

### 9.6 run_canonical_gcad()

- **位置:** `pipeline/run.py:run_canonical_gcad()`
- **调用方:** `builder.py`, `authoring/build_pipeline.py`, 所有测试
- **职责:** 主编排器 — 从 canonical IR 到 STEP 文件
- **输入参数:**
  - `canonical: CanonicalGcadDocument` — 必填
  - `out_step: Path | str` — 必填
  - `metadata_path: Path | str` — 必填
  - `validation_seed: dict` — 必填, 非空 (fail-closed)
  - `canonical_ir_path: Path | None` — 可选
  - `validation_seed_path: Path | None` — 可选
  - `require_full_validation_seed: bool = True` — 是否要求完整的 validation bundle
- **返回值:**
  - 类型: `GcadRunResult`
  - 字段: `ok`, `step_path`, `metadata_path`, `artifact`, `metadata`, `warnings`, `degraded_features`, `operation_metrics`, `error`
- **可能抛出的异常:** 无 — 所有异常捕获并转为 `GcadRunResult(ok=False, error=str(exc))`
- **前置条件:** canonical 已通过 canonicalize, validation_seed 非空
- **后置条件:** 如果 ok=True, step_path 指向存在的 ISO-10303-21 STEP 文件
- **副作用:**
  - STEP 文件写入磁盘
  - metadata JSON 写入磁盘
  - 大量运行时状态累积在 ctx 中

---

## 10. 数据结构与输入输出规范

### 10.1 RawGcadDocument — LLM 输出的唯一格式

- **定义位置:** `ir/raw.py`
- **使用位置:** 整个校验/规范化/执行管线
- **数据来源:** LLM (DeepSeek v4-pro) L2 创作输出
- **数据去向:** `parse_raw_gcad_document()` → 11 RAW_STAGES → canonicalize
- **生命周期:** 从 LLM 输出到 canonicalize 完成
- **是否会被修改:** 是 — auto_fixer 和 raw_assembler 修改系统字段
- **是否会被缓存:** 否
- **是否会被持久化:** 是 (作为 `llm_raw.json` 或 `raw_fixed.json`)
- **字段说明:**

| 字段 | 类型 | 必填 | 含义 | 校验逻辑 |
|---|---|---|---|---|
| schema_version | str | 是 | IR schema 版本 | exact match "0.2.0" |
| document_id | str | 是 | 文档唯一 ID | 非空字符串 |
| part_name | str | 是 | 零件名 | 非空字符串 |
| units | LengthUnit | 是 | 单位 | 必须是 "mm" |
| trust_level | TrustLevel | 是 | 信任级别 | 必须是 "concept_geometry" 或 "reference_geometry" |
| selected_dialects | list[RawSelectedDialect] | 是 | 选中的方言 | 非空, dialect/version 在 registry 中存在 |
| components | list[RawComponent] | 是 | 组件列表 | 非空, id 唯一, root_node 存在 |
| nodes | list[RawNode] | 是 | 节点列表 | 非空, id 唯一, 参数通过 OperationSpec.params_model |
| constraints | RawConstraints | 是 | 约束 | require_* 字段必须全部 True |
| safety | RawSafety | 是 | 安全标志 | 7 个 boolean 必须全部 True |
| llm_validation_hints | dict | 否 | LLM 自我校验提示 | 任意 dict |

### 10.2 CanonicalGcadDocument — 校验后的 IR

- **定义位置:** `ir/canonical.py`
- **额外字段 (vs Raw):**
  - `canonical_version: str` — canonical schema 版本
  - `canonical_graph_hash: str` — canonical nodes 的 SHA256
  - `raw_graph_hash: str` — raw nodes 的 SHA256
  - `CanonicalSelectedDialect` — 含 `contract_hash`
  - `CanonicalComponent` — 含 `output_aliases`
  - `CanonicalValueRef` — 含 `resolved_type: ValueType`
  - `CanonicalValueDecl` — 含 `value_id: str`
  - `CanonicalNode` — 含 `typed_params`, `operation_effects`, `postconditions`

### 10.3 DimExpr — 符号维度表达式

- **定义位置:** `ir/expr.py`
- **支持的 op (10 种):**
  - `const` — 字面常量 (1 个数值 arg)
  - `ref` — 引用另一个几何属性 (1 个 RefPath arg)
  - `add`, `sub`, `mul`, `div` — 算术运算 (2+ 个 args)
  - `min`, `max` — 极值 (2+ 个 args)
  - `abs` — 绝对值 (1 个 arg)
  - `clamp` — 限制范围 (3 个 args: value, min, max)
- **RefPath 白名单 (17 个属性):**
  - ShapeFacts 顶级: `bbox`, `radius_min_mm`, `radius_max_mm`, `length_z_mm`, `volume_mm3`, `traits`, `faces`, `notes`
  - BBox 子级: `xlen_mm`, `ylen_mm`, `zlen_mm`, `xmin_mm`, `xmax_mm`, `ymin_mm`, `ymax_mm`, `zmin_mm`, `zmax_mm`
  - faces 和 extra 下的子键: 自由格式
- **DimExprOrFloat:** `Annotated[Union[float, dict], BeforeValidator(_validate_dim_expr_or_float)]`
  - 接受正 float (非 NaN, 非 Inf)
  - 接受 DimExpr dict → 通过 Pydantic 校验

### 10.4 RuntimeHandle — 运行时类型化句柄

- **定义位置:** `runtime/handles.py`
- **基类:** `RuntimeHandle` — `id: str`, `type: str`, `component_id: str`, `producer_node: str`
- **子类:**
  - `SolidHandle` — `type="solid"`, `bbox_mm`, `volume_mm3`
  - `SolidArrayHandle` — `type="solid_array"`, `solid_ids`
  - `FrameHandle` — `type="frame"`, `origin_mm`, `x_axis`, `y_axis`, `z_axis`
  - `PlaneHandle` — `type="plane"`, `origin_mm`, `normal`
  - `PointHandle` — `type="point"`, `xyz_mm`
  - `CurveHandle` — `type="curve"`
  - `ProfileHandle` — `type="profile"`
  - `EdgeHandle` — `type="edge"`, `parent_solid_id`, `edge_index`
  - `FaceHandle` — `type="face"`, `parent_solid_id`, `face_index`

### 10.5 ToolCallResult — LLM 调用结果

- **定义位置:** `llm/provider.py`
- **字段:**
  - `tool_name: str` — 被调用的 tool name
  - `arguments: dict[str, Any]` — LLM 生成的 JSON arguments
  - `raw_response_id: str | None` — API 响应 ID
  - `model: str` — 使用的模型名
  - `provider: str` — provider 标识 (通常 "deepseek")

### 10.6 GcadRunResult — 运行时结果

- **定义位置:** `runtime/results.py`
- **字段:**
  - `ok: bool` — 执行是否成功
  - `step_path: Path | None` — STEP 文件路径
  - `metadata_path: Path | None` — metadata JSON 路径
  - `artifact: dict | None` — CanonicalStepArtifact 序列化
  - `metadata: dict` — metadata dict
  - `warnings: list[str]` — 累積的警告
  - `degraded_features: list[dict]` — 降级特征记录
  - `operation_metrics: list[dict]` — 操作耗时等指标
  - `error: str | None` — 错误信息

### 10.7 环境变量清单

| 名称 | 读取位置 | 必需 | 默认值 | 缺失时行为 | 影响范围 |
|---|---|---|---|---|---|
| `DEEPSEEK_API_KEY` | `llm/deepseek_client.py:35` | 是 | — | 抛出 `LlmToolCallError("provider_no_auth")` | 所有 LLM 调用 |
| `SEEKFLOW_GCAD_ENABLE_MIDDLE_END` | `compiler/config.py` | 否 | `"1"` | middle_end_enabled() 返回 False | 编译器 Pass 是否执行 |
| `SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS` | 8 个 legacy 重导出文件 | 否 | — | 抛出 `ImportError` | 是否允许导入 v0.1 类型 |

---

## 11. 配置、环境变量与外部依赖

### 11.1 外部依赖

| 依赖名称 | 使用位置 | 用途 | 失败时行为 |
|---|---|---|---|
| `openai` (Python SDK) | `llm/deepseek_client.py`, `authoring/repair_agent.py` | DeepSeek API 客户端 | 抛出 `LlmToolCallError("provider_missing_dependency")` |
| `cadquery` | 所有 dialect handlers | 几何建模内核 | OCP 异常 → `handle_feature_failure()` |
| `pydantic` (v2) | 整个代码库 | 数据校验和模型定义 | 校验失败 → ValidationError → ValidationIssue |
| SolidWorks 2025 COM | `native_importers.py:import_step_to_solidworks()` | STEP→SLDPRT 导入 | 返回 `{"ok": False}` |
| Siemens NX | `native_importers.py:import_step_to_nx()` | STEP→PRT 导入 | 返回 job result dict (可能含 error) |
| OCP (OpenCascade Python) | `dialects/geometry_utils/` (所有文件) | 原生 BRep 操作 | segfault → 进程崩溃 (捕获为 RuntimeError) |

### 11.2 模块级配置常量

| 常量 | 值 | 位置 | 含义 |
|---|---|---|---|
| `MIN_WALL_MARGIN_MM` | 1.0 | `compiler/config.py` | 最小壁厚余量 |
| `MAX_DIM_EXPR_RECURSION` | 16 | `compiler/config.py`, `ir/expr.py` | DimExpr 最大递归深度 |
| `FAIL_ON_MIDDLE_END_ERROR` | True | `compiler/config.py` | 中间端 error → 管线失败 |
| `HOLE_PATTERN_BATCH_THRESHOLD` | 8 | `planning/risk_model.py` | hole pattern 批处理建议阈值 |
| `HOLE_PATTERN_LARGE_THRESHOLD` | 120 | `planning/risk_model.py` | 大型 pattern 风险阈值 |
| `MANY_DESTRUCTIVE_OPS_THRESHOLD` | 32 | `planning/risk_model.py` | 大量 destructive op 阈值 |
| `DEFAULT_QUESTION_BUDGET` | 3 | `authoring/spatial/question_planner.py` | 空间提问最大数 |
| `MIN_PRIORITY_THRESHOLD` | 0.15 | `authoring/spatial/question_planner.py` | 空间提问最小优先级 |
| `DEFAULT_GEOMETRY_POLICY` (dict) | 多个值 | `validation/geometry_preflight.py` | max_nodes=64, min_edge_length=0.25mm, ... |
| `LARGE_STEP_FILE_BYTES` | 3MB | `native_importers.py` | 大型 STEP 文件阈值 |

### 11.3 DeepSeek API 特殊配置

- `strict=False` — 避免 DeepSeek issue #1069 ($ref 严格模式 bug)
- `tool_choice="required"` — 强制 tool call (仅在 thinking 禁用时支持, #1376)
- `extra_body={"thinking": {"type": "disabled"}}` — 禁用思维模式
- `to_deepseek_strict_schema()` — 所有 Pydantic schema 的转换:
  - inline 所有 $ref → 移除 $defs
  - `number` → `integer` (DeepSeek 不支持 "number" type)
  - 所有 `additionalProperties=false` + `required` = 所有属性名
  - 移除 `minLength`, `maxLength`, `minItems`, `maxItems` 等不支持的关键字
  - 可选字段 → `anyOf [{type}, {type:"null"}]`

---

## 12. 状态、生命周期与副作用

### 12.1 有状态对象

**RuntimeContext:**
- 定义位置: `runtime/context.py`
- 初始化位置: `pipeline/run.py:run_canonical_gcad()` 创建
- 更新位置: 整个运行时执行期间 (object_store, node_outputs, warnings, degraded_features, health_log, spatial_placements)
- 生命周期: 单次 `run_canonical_gcad()` 调用
- 共享范围: 单次管线执行 (非线程安全)

**RuntimeObjectStore:**
- 定义位置: `runtime/object_store.py`
- 初始化位置: RuntimeContext 创建时
- 更新位置: `execute_operation()` 每个成功执行的操作
- 生命周期: 单次管线执行
- 共享范围: 所有方言 handler 和 runtime 工具函数

**OperationCache:**
- 定义位置: `runtime/cache.py`
- 初始化位置: RuntimeContext 创建时
- 更新位置: `execute_operation()` 缓存几何操作结果
- 生命周期: 单次管线执行
- 键: `stable_hash(node.model_dump())` — 基于完整 node 状态的 SHA256

**FactStore:**
- 定义位置: `analysis/facts.py`
- 初始化位置: `FactPropagationPass.run()` 创建
- 更新位置: 每个节点的 fact rule 结果绑定
- 生命周期: 编译器 Pass 期间 (然后存入 CompilerModule)
- 双索引: `by_value_id` + `by_node_output`

**AssumptionLedger (空间):**
- 定义位置: `authoring/spatial/schemas.py`
- 初始化位置: `run_spatial_authoring_frontend()`
- 更新位置: archetype 匹配, 用户回答规范化
- 生命周期: 空间前端多轮期间

### 12.2 副作用清单

| 副作用类型 | 发生位置 | 触发条件 | 输入 | 输出 |
|---|---|---|---|---|
| HTTP 请求 | `llm/deepseek_client.py:78` | 每次 LLM 调用 | messages + tools | API response |
| STEP 文件写入 | `runtime/cadquery_runtime.py:export_step()` | 管线成功 | CadQuery solid | .step 文件 |
| Metadata JSON 写入 | `pipeline/metadata_v3.py` | 管线成功 | Canonical doc + ctx | .metadata.json |
| Canonical JSON 写入 | `authoring/build_pipeline.py` | 测试模式 | Canonical doc | canonical.json |
| SolidWorks COM 启动 | `native_importers.py:import_step_to_solidworks()` | 可选导入 | STEP path | .SLDPRT |
| NX 批处理作业 | `native_importers.py:import_step_to_nx()` | 可选导入 | STEP path | .prt |
| 日志 (warnings.warn) | `runtime/cadquery_runtime.py` | bbox/body count 测量失败 | 几何对象 | stderr |

---

## 13. 错误处理与边界情况

### 13.1 错误处理机制

1. **Fail-Closed 校验 (Validation Layer):**
   - 所有 14 个校验阶段返回 `ValidationReport` (ok=False 时不抛异常)
   - 管线在首个失败阶段短路 (fail-fast)
   - 校验器异常被包装为 `"{stage}_validator_exception"` 代码

2. **Fail-Closed 几何体 (Geometry Validation):**
   - `_validate_geometry()` 在所有几何产生操作上运行 BRepCheck
   - `required=True` + 不健康 → `RuntimeError`
   - `required=False` + `degradation_policy="may_skip_with_warning"` → warning

3. **结构化降级 (Structured Degradation):**
   - `handle_feature_failure()` 替代所有 handler 中的 ad-hoc try/except
   - 记录到 `degraded_features` 和 `operation_metrics`

4. **布尔操作的渐进式降级:**
   - CadQuery union → OCCT fuzzy fuse (3 个 tolerance 级别) → heal+fuse → compound

5. **安全标志强制:**
   - `RawSafety.all_true()` 要求所有 7 个标志显式为 True
   - `validation/safety.py` 单独检查每个标志

6. **DimExpr 错误处理:**
   - 未解决的 ref → 返回 None (调用方决定)
   - NaN/Inf/div-by-zero → 抛出 ValueError (记录为 compiler diagnostic)
   - 递归溢出 (depth > 16) → 抛出 ValueError

### 13.2 边界情况

| 边界情况 | 处理方式 |
|---|---|
| 空输入 | `parse_raw_gcad_document()` 在步骤 1-3 检查缺失键 |
| 非法输入 (错误 JSON) | DeepSeek client 捕获 json.JSONDecodeError → LlmToolCallError |
| 缺失 `DEEPSEEK_API_KEY` | 立即抛出 `LlmToolCallError("provider_no_auth")` |
| LLM 不返回 tool call | `tool_choice="required"` 减少但无法完全消除; 最多 4 次重试 |
| 方言/操作不在注册表 | `validation/registry.py` 产生 "unknown_dialect" / "unknown_op" 错误 |
| 跨组件引用 (非 composition) | `validation/ownership.py` 拒绝 (除 composition 外的跨组件引用) |
| DAG 循环 | `validation/graph.py` DFS WHITE/GRAY/BLACK 检测 |
| OCP segfault | 进程崩溃, 由 shell script 重新启动处理 |
| 3+ solids boolean_union | `raw_assembler.py` 自动展开为 pairwise union |
| 300+ 孔 pattern | OCP 内核 segfault (已知限制, 跳过) |
| 零值 chamfer/fillet | `auto_fixer.py:_fix_chamfer_zero_distance()` 移除该节点 |
| Helix >8 turns | `loft_sweep/handlers.py` 分段 sweep (≤3 turns/段) |
| 大型 STEP (>3MB) | 跳过 SW 导入 (内存限制) |
| 无验证种子 | `run_canonical_gcad()` 在 `require_full_validation_seed=True` 时失败 |
| Mixed-dialect 组件 | `_run_mixed_dialect_component()` 通过 Kahn 拓扑排序执行 |

### 13.3 最容易出 bug 的地方

1. **DeepSeek API 兼容性** (`strict_schema.py`): DeepSeek 的 JSON Schema 支持与标准 JSON Schema 有显著偏差。`to_deepseek_strict_schema()` 包含 20+ 转换规则, 任何新 Pydantic 字段或验证器都可能需要额外适配。

2. **OCP 几何内核崩溃**: 300 孔 pattern 导致 segfault, helix >8 turns 需要特殊分段逻辑。内核崩溃无法在 Python 层面恢复。

3. **DimExpr 求解时机**: DimExpr 在 FactPropagationPass 期间求解, 而不是在运行时。如果 fact rule 覆盖不全, 某些操作在运行时遇到未求解的 DimExpr 会静默传递 dict。

4. **auto_fixer 出现循环依赖**: 20+ 修复规则顺序执行, 修改可能相互抵消 (如 `_fix_phase_ordering` 和 `_fix_phase_names`)。

5. **拓扑排序不一致**: `FactPropagationPass._topological_sort()` 和 `_run_mixed_dialect_component()` 各自实现拓扑排序, 可能产生不同顺序。

6. **线程安全**: 无 — RuntimeContext 在所有操作间共享可变状态, 假定单线程执行。

---

## 14. 架构模式与设计模式

### 14.1 管道/流水线 (Pipeline)

- **是否明确存在:** 是
- **体现位置:** `validation/pipeline.py:_run_stage_collect()` (fail-fast), `pipeline/run.py:run_canonical_gcad()` (13 步), `authoring/pipeline.py:generate_gcad_from_user_request()` (8 阶段)
- **参与模块:** validation, authoring, pipeline, compiler, runtime
- **解决的问题:** 将复杂处理拆分为有序的独立阶段, 每阶段有明确输入/输出
- **优点:** 每个阶段可独立测试, fail-fast 减少无效计算
- **风险:** 阶段顺序耦合 — 修改某阶段输出可能破坏下游

### 14.2 方言注册表 (Dialect Registry Pattern)

- **是否明确存在:** 是
- **体现位置:** `dialects/registry_core.py:DialectRegistry`, `dialects/default_registry.py:build_default_registry()`
- **参与模块:** 所有 dialect 实现, validation, pipeline
- **解决的问题:** 统一的方言发现、校验和执行调度
- **当前实现方式:** 冻结注册表 (初始化后不可变), `require_dialect()` 单点查找
- **优点:** 类型安全, 集中治理
- **扩展方式:** 在 `build_default_registry()` 中 `register()` 新方言, 实现 `BaseDialect` 协议

### 14.3 编译器 Pass 系统 (Compiler Pass)

- **是否明确存在:** 是
- **体现位置:** `compiler/pass_manager.py:CompilerPass` 协议 + `run_compiler_passes()`
- **参与模块:** compiler, analysis, planning
- **解决的问题:** 在规范化后、执行前插入只读分析, 不修改 IR
- **当前实现方式:** 顺序执行, fail-fast, 每个 Pass 读取/写入 CompilerModule
- **优点:** 可插拔, 非侵入
- **扩展方式:** 实现 `CompilerPass` 协议, 在 `build_compiler_module()` 中注册

### 14.4 Fail-Closed 安全策略

- **是否明确存在:** 是
- **体现位置:** `ir/raw.py:RawSafety.all_true()`, `ir/raw.py:RawConstraints.fail_closed_flags()`, `validation/safety.py`, `runtime/recovery.py:handle_feature_failure()`
- **解决的问题:** LLM 输出的 geometry 不能隐式信任; 任何不安全的输出必须显式拒绝
- **当前实现方式:** 所有安全字段默认 fail; 必须显式设为 True 才能通过
- **优点:** 防止 LLM 幻觉传播到制造环节
- **风险:** 可能过于严格, 拒绝合法的新用例

### 14.5 OperationResult ABI (Handler 抽象)

- **是否明确存在:** 是
- **体现位置:** `dialects/results.py:OperationResult`, `dialects/executor.py:execute_operation()`
- **解决的问题:** 统一所有方言 handler 的返回值格式
- **当前实现方式:** Typed Pydantic model (ok, outputs, warnings, degraded_features, metrics, postcondition_results)
- **优点:** 类型安全, 向后兼容 (adapt_legacy_handler_result)

### 14.6 两阶段 IR (Raw → Canonical)

- **是否明确存在:** 是
- **体现位置:** `ir/raw.py` + `ir/canonical.py`
- **解决的问题:** 分离 LLM 输出格式 (宽松, 含 LLM 错误) 和内部处理格式 (严格, 类型完全解析)
- **优点:** LLM 不直接接触 canonical IR, 所有降低都经过校验

### 14.7 工厂模式 (Factory Pattern)

- **体现位置:** `dialects/default_registry.py:build_default_registry()`, `base_packages/registry.py:default_base_package_registry()`, `authoring/spatial/archetypes/registry.py:_build_default_archetypes()`
- **实现:** 均为 `@lru_cache(maxsize=1)` 懒加载单例

### 14.8 协议/抽象基

- **体现位置:** `dialects/base.py:BaseDialect`, `runtime/geometry_runtime.py:GeometryRuntime`, `compiler/pass_manager.py:CompilerPass`, `llm/provider.py:LlmToolCaller`
- **实现:** Python `typing.Protocol` (结构化子类型)

---

## 15. 画图素材区

### 15.1 节点清单 (用于模块依赖图)

| 节点名 | 类型 | 职责 | 位置 |
|---|---|---|---|
| builder | 入口 | 生产环境 Text→STEP 入口 | `builder.py` |
| tools | 入口 | SeekFlow Agent 工具注册 | `tools.py` |
| native_importers | 外部服务 | SW/NX STEP 导入 | `native_importers.py` |
| deepseek_client | 外部服务 | DeepSeek API 客户端 | `llm/deepseek_client.py` |
| skills_orchestrator | 核心逻辑 | L1/L2 prompt + tool 构建 | `skills/orchestrator.py` |
| skills_prompts | 配置 | 硬编码 system prompts | `skills/prompts.py` |
| tool_schema_compiler | 核心逻辑 | per-op JSON Schema 编译 | `skills/tool_schema_compiler.py` |
| authoring_pipeline | 核心逻辑 | 多阶段创作管线 | `authoring/pipeline.py` |
| build_pipeline | 入口 | Text→STEP 完整管线 | `authoring/build_pipeline.py` |
| raw_assembler | 核心逻辑 | LLM 输出组装 | `authoring/raw_assembler.py` |
| auto_fixer | 核心逻辑 | 20+ 确定性修复 | `authoring/auto_fixer.py` |
| strict_schema | 工具 | DeepSeek schema 转换 | `authoring/strict_schema.py` |
| spatial_pipeline | 核心逻辑 | v6 空间前端 | `authoring/spatial/pipeline.py` |
| constraint_graph | 核心逻辑 | 符号约束图构建 | `authoring/spatial/constraint_graph.py` |
| spatial_solver | 核心逻辑 | Phase A 约束求解 | `authoring/spatial/solver.py` |
| ir_raw | 数据模型 | LLM 输出格式 | `ir/raw.py` |
| ir_canonical | 数据模型 | 校验后 IR | `ir/canonical.py` |
| ir_expr | 数据模型 | 维度表达式系统 | `ir/expr.py` |
| ir_geom_semantics | 数据模型 | V2 几何语义 | `ir/geometry_semantics.py` |
| validation_pipeline | 核心逻辑 | 14 阶段校验主控 | `validation/pipeline.py` |
| canonicalize | 核心逻辑 | Raw→Canonical 降低 | `validation/canonicalize.py` |
| repair_hints | 工具 | 修复提示生成 | `validation/repair_hints.py` |
| compiler_module | 数据模型 | 编译器数据容器 | `compiler/module.py` |
| pass_manager | 核心逻辑 | Pass 注册和执行 | `compiler/pass_manager.py` |
| fact_propagation | 核心逻辑 | Pass 1: 事实传播 | `analysis/fact_propagation.py` |
| fact_rules | 核心逻辑 | 9 个事实推导规则 | `analysis/fact_rules.py` |
| expr_eval | 工具 | DimExpr 求值 | `analysis/expr_eval.py` |
| planner | 核心逻辑 | Pass 2: 规划分析 | `planning/planner.py` |
| dialect_base | 抽象 | BaseDialect 协议 | `dialects/base.py` |
| dialect_registry | 核心逻辑 | 方言注册表 | `dialects/registry_core.py` |
| default_registry | 配置 | 6 种方言注册 | `dialects/default_registry.py` |
| executor | 核心逻辑 | 统一操作执行器 | `dialects/executor.py` |
| axisymmetric_dialect | 服务 | 旋转对称方言 (8 ops) | `dialects/axisymmetric/` |
| sketch_extrude_dialect | 服务 | 草图拉伸方言 (11 ops) | `dialects/sketch_extrude/` |
| loft_sweep_dialect | 服务 | 扫描放样方言 (4 ops) | `dialects/loft_sweep/` |
| shell_housing_dialect | 服务 | 壳体方言 (2 ops) | `dialects/shell_housing/` |
| composition_dialect | 服务 | 装配方言 (7 ops) | `dialects/composition/` |
| sketch_profile_dialect | 服务 | 草图轮廓方言 (9 ops) | `dialects/sketch_profile/` |
| geometry_utils | 工具 | OCP 原生几何工具 | `dialects/geometry_utils/` |
| pipeline_run | 核心逻辑 | 主编排器 | `pipeline/run.py` |
| metadata_v3 | 数据模型 | v3 元数据证明 | `pipeline/metadata_v3.py` |
| artifact | 数据模型 | STEP 工件 | `pipeline/artifact.py` |
| import_gate | 服务 | 导入门控 | `pipeline/import_artifact.py` |
| runtime_context | 数据模型 | 中央状态持有者 | `runtime/context.py` |
| object_store | 基础设施 | 类型化对象存储 | `runtime/object_store.py` |
| handles | 数据模型 | 运行时句柄 | `runtime/handles.py` |
| cadquery_runtime | 外部服务 | CadQuery/OCCT 后端 | `runtime/cadquery_runtime.py` |
| health | 工具 | 几何健康评分 | `runtime/health.py` |
| recovery | 工具 | 特征失败恢复 | `runtime/recovery.py` |
| constraint_resolver | 核心逻辑 | Phase C 约束求解 | `runtime/constraint_resolver.py` |
| spatial_audit | 工具 | 装配后空间审计 | `runtime/spatial_audit.py` |
| DeepSeek API | 外部服务 | LLM 推理 | `api.deepseek.com` |
| OCCT/BRep | 外部服务 | 几何内核 | OCP Python 绑定 |

### 15.2 边清单 (用于模块依赖图)

```
from → to: 关系类型, 传递内容

builder → validation_pipeline: 调用, RawGcadDocument → ValidationReport+Canonical+Bundle
builder → pipeline_run: 调用, CanonicalGcadDocument → GcadRunResult
builder → ir_parse: 调用, dict → RawParseResult
tools → builder: 调用, user_request → EngineeringActionResult
deepseek_client → strict_schema: 调用, Pydantic schema → DeepSeek-strict schema
deepseek_client → DeepSeek API: 外部请求, messages+tools → ToolCallResult

skills_orchestrator → skills_prompts: 数据读取, 系统提示文本
skills_orchestrator → tool_schema_compiler: 调用, registry → per-op schema
skills_orchestrator → dialect_registry: 数据读取, dialect_id → catalog

authoring_pipeline → skills_orchestrator: 调用, user_request → L1/L2 prompt
authoring_pipeline → raw_assembler: 调用, 分阶段输出 → raw dict
authoring_pipeline → auto_fixer: 调用, raw dict → fixed dict
authoring_pipeline → validation_pipeline: 调用, raw dict → canonical
authoring_pipeline → spatial_pipeline: 调用, user_request → SpatialFrontendResult

raw_assembler → dialect_registry: 数据读取, OperationSpec → output_types/phase

auto_fixer → ir_raw: 数据读取, schema 作为修复指引

validation_pipeline → canonicalize: 调用, RawGcadDocument → CanonicalGcadDocument
validation_pipeline → repair_hints: 调用, ValidationReport → 修复建议文本

canonicalize → dialect_registry: 数据读取, dialect_id → contract_hash + op_spec

pass_manager → fact_propagation: 注册+调用, CompilerModule → CompilerModule
pass_manager → planner: 注册+调用, CompilerModule → CompilerModule

fact_propagation → fact_rules: 调用, CanonicalNode → ShapeFacts
fact_propagation → expr_eval: 调用, typed_params + FactStore → resolved params
fact_rules → analysis_facts: 数据生成, NumericFact/BBoxFacts/FaceFact → ShapeFacts

executor → dialect handlers: 调用, CanonicalNode + RuntimeContext → OperationResult
executor → health: 调用, solid → GeometryHealth

pipeline_run → pass_manager: 调用, canonical → CompilerModule
pipeline_run → dialect_registry: 调用, component → dialect.run_component()
pipeline_run → constraint_resolver: 调用, SpatialConstraintGraph + bboxes → placements
pipeline_run → spatial_audit: 调用, placements + final_solid → audit_report
pipeline_run → cadquery_runtime: 调用, solid → .step file

dialect handlers → object_store: 写入, SolidHandle + CadQuery object
dialect handlers → recovery: 调用, 异常 → 降级/重抛
dialect handlers → geometry_utils: 调用, 路径点 → OCP wire/pipe/loft

constraint_resolver → spatial_schemas: 数据读取, PlacementConstraint → NumericPlacement
spatial_audit → spatial_schemas: 数据生成, bbox+metrics → GeometrySpatialAuditReport

metadata_v3 → runtime_context: 数据读取, warnings/degraded_features/metrics
artifact → metadata_v3: 数据读取, metadata + sha256
import_gate → metadata_v3: 数据读取, 15+ gate 检查
```

### 15.3 主要时序 (Text→STEP 完整管线)

参与者: User → DeepSeek API → SkillsOrchestrator → AutoFixer → ValidationPipeline → CompilerPassManager → DialectRegistry → Executor → CadQueryRuntime → MetadataBuilder

顺序步骤:
1. User → SkillsOrchestrator: 构建 L1 prompt (含 dialect catalog)
2. SkillsOrchestrator → DeepSeek API: 发送 L1 prompt 和 tool schema
3. DeepSeek API → SkillsOrchestrator: 返回 DialectSelectionPlan
4. SkillsOrchestrator → DeepSeek API: 发送 L2 prompt (含 contracts + usage_skills)
5. DeepSeek API → SkillsOrchestrator: 返回 RawGcadDocument dict
6. SkillsOrchestrator → AutoFixer: 确定性修复 (20+ 规则)
7. AutoFixer → ValidationPipeline: 14 阶段校验 + 规范化
8. ValidationPipeline → CompilerPassManager: FactPropagation + Planner
9. CompilerPassManager → DialectRegistry: 执行每个组件
10. DialectRegistry → Executor: execute_operation() per node
11. Executor → CadQueryRuntime: export_step()
12. CadQueryRuntime → MetadataBuilder: 构建 v3 metadata + artifact

异常分支:
- 步骤 2/4 失败 → 重试 (最多 3-4 次)
- 步骤 6 失败 → 可选 LLM 修复循环 (最多 3 轮)
- 步骤 11 失败 → handle_feature_failure() 降级

### 15.4 主要数据流

| 数据名 | 来源 | 经过模块 | 转换过程 | 最终去向 |
|---|---|---|---|---|
| 用户请求 | User | skills_orchestrator → deepseek_client → skills_schemas | string → API request → JSON → DialectSelectionPlan | L2 prompt |
| RawGcadDocument | DeepSeek API | ir_parse → auto_fixer → validation_pipeline → canonicalize | JSON dict → Pydantic → fixed dict → CanonicalGcadDocument | pipeline_run |
| typed_params | canonicalize | fact_propagation → expr_eval | DimExpr dicts → resolved floats | dialect handlers |
| Solid body | CadQuery/OCCT | object_store → executor → health | Workplane → SolidHandle → GeometryHealth | STEP export |
| STEP file | CadQueryRuntime | metadata_v3 → artifact → import_gate | OCCT export → SHA256 → CanonicalStepArtifact | native import |
| SpatialConstraintGraph | LLM (object_graph) | constraint_graph → solver → constraint_resolver → spatial_audit | relations → constraints → placements → audit metrics | metadata |

---

## 16. 扩展与修改指南

### 16.1 如果要新增一种方言

1. 创建 `dialects/<new_dialect>/` 目录
2. 实现 `dialect.py` (BaseDialect 协议):
   - `dialect_id = "new_dialect"`
   - `version = "0.1.0"`
   - `phase_order = (...)` (至少一个阶段)
   - `op_specs()` — 至少一个 OperationSpec
   - `validate_component()` / `preflight_component()` / `run_component()`
3. 创建 `params.py` — 所有 params_model (Pydantic BaseModel, extra="forbid")
4. 创建 `handlers.py` — 每个操作的处理函数 (签名: `(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]`)
5. 在 `default_registry.py:build_default_registry()` 中 `registry.register(new_dialect)`
6. 如果需要 LLM 支持, 创建 `base_packages/<new_dialect>/package.py`:
   - `BasePackageManifest` + `BasePackage` + level2_usage markdown
   - 在 `default_base_package_registry()` 中注册
7. 推荐测试:
   - 单元测试: `tests/generative_cad/dialects/<new_dialect>/test_handlers.py`
   - params 测试: `test_params.py` (Pydantic 校验)
   - 语义测试: `test_dialect.py` (validate_component + preflight_component)

### 16.2 如果要新增一种操作

1. 在目标方言的 `params.py` 中定义 `NewOpParams(BaseModel)` (extra="forbid")
2. 在目标方言的 `dialect.py:op_specs()` 中添加新的 `OperationSpec`:
   - 指定 `input_types`, `output_types`, `effects`, `phase`
3. 在目标方言的 `handlers.py` 中添加 handler 函数
4. (可选) 在 `analysis/fact_rules.py` 中添加 fact rule → `FACT_RULES` 注册表
5. (可选) 在 `skills/tool_schema_compiler.py` 的 `OP_DESCRIPTIONS` 中添加中文描述
6. (可选) 在 `authoring/auto_fixer.py` 中添加 `PARAM_NAME_FIXES` 和其他修复规则

### 16.3 如果要新增一种编译器 Pass

1. 实现 `CompilerPass` 协议:
   ```python
   class MyNewPass:
       name = "my_new_pass"
       def run(self, module: CompilerModule) -> CompilerModule:
           # 只读分析, 写入 module.diagnostics, 不修改 module.canonical
           return module
   ```
2. 在 `compiler/pass_manager.py:build_compiler_module()` 中注册:
   ```python
   passes.append(MyNewPass())
   ```

### 16.4 如果要替换底层实现

- **替换几何运行时:** 实现 `GeometryRuntime` 协议, 在 `RuntimeContext` 初始化时传入
- **替换 LLM 提供商:** 实现 `LlmToolCaller` 协议, 在创作管线初始化时传入
- **替换 STEP 导出器:** 修改 `CadQueryRuntime.export_step()` 或实现新的 `GeometryRuntime`

### 16.5 如果要增加配置项

- **环境变量:** 在对应模块中读取 `os.environ.get()`, 在 `MANUAL.md` 或本文档中记录
- **模块级常量:** 在 `compiler/config.py`、`planning/risk_model.py` 或 `validation/geometry_preflight.py` 中添加
- **命令行参数:** 修改 `authoring/build_pipeline.py:generate_validate_build_step()` 的参数签名

### 16.6 如果要修改核心处理逻辑

- 管线顺序: 修改 `pipeline/run.py:run_canonical_gcad()` 的 13 步序列
- 校验顺序: 修改 `validation/pipeline.py:RAW_STAGES` 或 `CANONICAL_STAGES` 列表
- 修复顺序: 修改 `authoring/auto_fixer.py:auto_fix_with_report()` 中的 fix 函数列表
- 安全性策略: 修改 `ir/raw.py:RawSafety.all_true()` 或 `validation/safety.py`

---

## 17. 质量评估与风险

### P0：必须尽快处理

1. **OCP 几何内核 segfault 无法恢复**
   - 证据: 300 孔 test case (v63_perforated / g27_dense_holes) 导致 OCP 崩溃, 测试脚本显式跳过
   - 影响: 复杂几何操作不可预测地崩溃, 无法在 Python 层捕获
   - 建议: 实现输入级 filter (pattern count > 100 → 分段), 添加 watchdog 进程监控
   - 涉及文件: `dialects/loft_sweep/handlers.py`, `dialects/geometry_utils/`

2. **拓扑排序实现不一致**
   - 证据: `FactPropagationPass._topological_sort()` 和 `_run_mixed_dialect_component()` 各有一套实现
   - 影响: 不同阶段可能产生不同节点顺序, 导致难以调试的不一致性
   - 建议: 抽取共享拓扑排序函数到 `runtime/topology.py` 或类似位置
   - 涉及文件: `analysis/fact_propagation.py`, `pipeline/run.py`

3. **DeepSeek API 兼容性维护成本高**
   - 证据: `strict_schema.py` 包含 20+ 专门针对 DeepSeek schema bug 的转换规则
   - 影响: DeepSeek 修复 bug 或变更 API 行为时, 这些 workaround 可能失效或冲突
   - 建议: 每个 workaround 添加 DeepSeek issue 引用和版本号, 写定期核查脚本
   - 涉及文件: `authoring/strict_schema.py`, `llm/deepseek_client.py`

### P1：重要但不紧急

4. **auto_fixer 规则顺序敏感**
   - 证据: 20+ 规则顺序执行, 修改可能相互覆盖 (如 `_fix_phase_names` 和 `_fix_phase_ordering`)
   - 影响: 添加新规则可能在现有规则之后无效或被覆盖
   - 建议: 添加规则间冲突检测, 或实现 multi-pass 策略
   - 涉及文件: `authoring/auto_fixer.py`

5. **线程安全问题**
   - 证据: `RuntimeContext` 在所有操作间共享可变状态, 无锁保护
   - 影响: 未来如果引入并发执行 (如多组件并行), 会有数据竞争
   - 建议: 文档明确标注单线程假设, 或引入 per-component 隔离
   - 涉及文件: `runtime/context.py`, `runtime/object_store.py`

6. **大函数风险**
   - 证据: `pipeline/run.py:run_canonical_gcad()` (~200 行, 13 步), `authoring/pipeline.py:generate_gcad_from_user_request()` (~200 行, 8 阶段)
   - 影响: 难以测试单个步骤, 修改风险高
   - 建议: 拆分每个步骤为独立函数

### P2：可优化

7. **测试覆盖缺口**
   - 证据: 编译器中间端有 35 个 DimExpr 测试 + 19 个 fact 测试, 但空间管线缺少集成测试
   - 影响: 空间管线修改回归风险高
   - 建议: 添加 `test_spatial_pipeline_e2e.py` 模拟 LLM mock caller

8. **废弃模块过多**
   - 证据: 13 个顶层文件和部分子目录是已废弃的 v0.1 兼容层
   - 影响: 增加代码库认知负担, 新开发者可能混淆活跃模块和废弃模块
   - 建议: 设置废弃期限, 清理后更新文档

9. **日志不足**
   - 证据: 仅在 `cadquery_runtime.py` 中使用 `warnings.warn()`, 无结构化日志
   - 影响: 生产环境调试困难
   - 建议: 引入 `logging` 模块, 在关键决策点 (校验失败，几何降级, LLM 重试) 添加结构化日志

10. **配置混乱**
    - 证据: 配置分布在环境变量 (`DEEPSEEK_API_KEY`)`, 模块级常量 (`MIN_WALL_MARGIN_MM`)`, Pydantic model 默认值, 和 `DEFAULT_GEOMETRY_POLICY` dict 中
    - 影响: 难以全局审计所有配置项
    - 建议: 集中配置管理 (如 `config.py` 统一导出)

---

## 18. 仍不确定的问题

1. **Primitive 链路调用路径:** `geometry_primitives` 包在 `generative_cad` 外部, 只通过 `tools.py` 中的 `primitive_catalog` 和 L1 路由中的 `primitive_catalog_summary` 参数引用。实际的 Primitive 执行管线在 `geometry_primitives/` 中, 未在本分析中阅读。 **[需要进一步阅读 `geometry_primitives/` 包]**

2. **SolidWorks 导入的完整状态机:** `builder.py` 中的 artifact state machine 检查包括 `step_import_candidate=True`, `step_import_allowed=False`, `requires_import_gate=True` 等字段, 但这些字段的完整生命周期和转换规则仍不完全清晰。 **[需要进一步阅读 `CanonicalStepArtifact` 状态模型测试]**

3. **空间管线 precision 模式:** `spatial_mode="precision"` 与 `session_state` 参数交互, 但完整的多轮问答会话持久化机制 (session 存储, 超时, 跨请求状态) 未完全实现。 **[需要进一步阅读 `authoring/spatial/session_state.py` 和实际的多轮测试]**

4. **修复治理 RepairPatchV2 的使用:** `repair/patch.py` 定义了 `RepairPatchV2`, `RepairStateV2`, `apply_repair_patch_v2`, 但截至分析时, 代码路径中 `repair_agent.py` 使用的是更简化的直接修复流程。 **[需要确认实际使用的修复策略]**

5. **Legacy adapters 的活跃度:** `compatibility/legacy_spec_adapter.py` 被哪些代码路径引用? 是否还有活跃调用方? **[需要全局搜索 `legacy_spec_adapter` 引用]**

6. **Object Store 的并发安全性边界:** 文档标注为单线程, 但 `@lru_cache` 在 `default_registry()` 和 `default_base_package_registry()` 的使用暗示可能有共享读取场景。 **[需要确认 deployment 中是否有多线程可能]**

---

## 19. 建议继续阅读的文件路线图

如果要深入理解特定子系统:

### 理解非 Primitive 整体流程
1. `builder.py` — 顶层入口
2. `authoring/build_pipeline.py` — Text→STEP 完整管线
3. `pipeline/run.py` — 主编排器
4. `validation/pipeline.py` — 校验管线

### 理解 LLM 交互
1. `llm/deepseek_client.py` — API 调用
2. `skills/orchestrator.py` — Prompt 构建
3. `skills/prompts.py` — 硬编码规则
4. `authoring/strict_schema.py` — 20+ DeepSeek 适配规则

### 理解 IR 设计
1. `ir/raw.py` — LLM 输出格式
2. `ir/canonical.py` — 校验后格式
3. `ir/expr.py` — 符号表达式
4. `ir/geometry_semantics.py` — V2 几何语义

### 理解校验系统
1. `validation/pipeline.py` — 14 阶段
2. `validation/canonicalize.py` — Raw→Canonical
3. `validation/graph.py` — DAG 检测
4. `validation/typecheck.py` — 类型检查
5. `authoring/auto_fixer.py` — 确定性修复

### 理解方言系统
1. `dialects/base.py` — BaseDialect 协议
2. `dialects/operation.py` — OperationSpec
3. `dialects/registry_core.py` — DialectRegistry
4. `dialects/default_registry.py` — 6 种方言注册
5. `dialects/executor.py` — 统一执行器
6. `dialects/axisymmetric/dialect.py` — 最完整的方言示例

### 理解编译器中间端
1. `compiler/pass_manager.py` — Pass 管理
2. `analysis/fact_propagation.py` — FactPropagationPass
3. `analysis/fact_rules.py` — 9 个事实规则
4. `analysis/expr_eval.py` — DimExpr 求值
5. `planning/planner.py` — PlannerPass

### 理解运行时
1. `runtime/context.py` — 状态持有者
2. `runtime/handles.py` — 类型化句柄
3. `runtime/object_store.py` — 对象存储
4. `runtime/recovery.py` — 失败恢复
5. `runtime/health.py` — 几何健康

### 理解空间子系统 (v6)
1. `authoring/spatial/schemas.py` — 全部数据模型 (~30 个 Pydantic class)
2. `authoring/spatial/pipeline.py` — 空间前端入口
3. `authoring/spatial/constraint_graph.py` — 约束图构建
4. `runtime/constraint_resolver.py` — Phase C 数值求解
5. `runtime/spatial_audit.py` — 装配后审计

---

*文档完成于 2026-06-06。基于 132 个 .py 文件的完整代码阅读。*
