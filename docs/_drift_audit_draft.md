# 架构文档与真实代码差异审计 — 汇总草稿（工作中）

> 对照：`docs/架构文档与具体规范.md`（2026-06-07 版本，声称 132 文件）
> 真实代码：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/`（276 个 .py）
> 审计日期：2026-08-03

---

## 0. 全局规模差异

| 维度 | 文档 | 真实 | 结论 |
|------|------|------|------|
| .py 文件数 | 132 | **276** | 严重过期 |
| 文档未提的子目录 | — | prompt_system/(5)、repair_kernel/(7)、validation_kernel/(8)、topology/(25)、extensions/(3)、skills/domain/(2 md) | 遗漏 6 个模块 |
| 测试文件 | 未提 | **198 个 test 文件** | 含 topology/ocaf 30、text_to_cad_real 9 |

---

## 1. Agent A — 入口层 + LLM 层 + skills + prompt_system ✅

### 1.1 tools.py 工具数
- 文档："9 个 SeekFlow Agent 工具"
- 真实：`@tool` 装饰 **10 个**，但实际注册 **8 个**（tools.py L495-504）
- 已装饰未注册：`generative_cad_build_with_autofix`(L184)、`generative_cad_full_authoring`(L251)
- 实际 8 个工具：list_dialects / list_bases(legacy) / get_dialect_contract / get_base_contract(legacy) / validate_ir / build_from_ir / import_artifact_to_solidworks / import_artifact_to_nx

### 1.2 §5.1 full_authoring 调用链错误
- 文档说 `generative_cad_full_authoring() → build_generative_cad_model()`
- 真实：full_authoring(L283) 调 `authoring/build_pipeline.py:generate_validate_build_step()`，**不经过** build_generative_cad_model()

### 1.3 builder.py 签名 ✅ 一致
- `build_generative_cad_model(spec, config, out_step, inspect, strict_inspection, graph_out, script_out)` 返回 dict
- 内部：parse → validate_and_canonicalize_with_bundle → run_canonical_gcad

### 1.4 call_strict_tool() 签名 ✅ 一致（异常 message 不同）
- 签名、8 个 error code 全部一致
- 但 8 条异常 message 文案不同（如 "DEEPSEEK_API_KEY not set" → "DEEPSEEK_API_KEY environment variable is not set"）

### 1.5 环境变量
- DEEPSEEK_API_KEY 读取位置 35 → **32**
- SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS 覆盖 "8 个" → 实为 **10 个**文件（artifact.py 不受控）
- SEEKFLOW_GCAD_ENABLE_MIDDLE_END 一致

### 1.6 skills/domain/ 新增（文档未提）
- 2 个 .md：generic_mechanical.md、turbomachinery_reference.md
- 接入：orchestrator.list_domain_skills() / load_domain_skill() / build_level1_routing_prompt() 返回 "domain_skills" 键
- DialectSelectionPlan 新增 selected_domain_skills 字段
- **注意**：生产路径当前未把 domain 注入实际 messages

### 1.7 prompt_system/（文档未提，活跃）
- 5 文件：models.py / registry.py / compiler.py / fragments_legacy.py / __init__.py
- 用途：统一 prompt 编排 + 追踪（PromptFragment / PromptRegistry / PromptCompiler / PromptTrace）
- 对应设计文档：`docs/提示词系统升级.md`
- **被 server main.py 活跃调用**（compile_level1/compile_level2，落盘 prompt_trace JSON）
- 包装 skills/orchestrator（body_ref 零复制引用 skills/prompts.py 常量）

### 1.8 活跃 prompt 路径
- 生产：server main.py → PromptCompiler.compile_level1/2 → skills/orchestrator.build_level1_routing_prompt/build_level2_authoring_prompt
- 分阶段管线：full_authoring → authoring/pipeline.py（用 prompt_builders.py）
- prompt_system 的 select()/compile_generic() 分层路径：**未使用**（dormant）
- `compile_level2_tool_schema()` / `build_level2_tool_from_compiler()`：**无生产调用者**
- 活跃 tool schema 路径：`build_level2_tool()`（仍含硬编码中文 OP_DESCRIPTIONS）
- `build_repair_prompt_v2()`：无生产调用者（修复已迁 repair_kernel）

### 1.9 顶层文件废弃分类
- 11 个重导出文件（base/runner/validation/preflight/prompts/registry/repair_governor/graph_validation/metadata/ir/artifact），全部废弃
- 10 个受 SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS 门控，**artifact.py 不受控**
- 文档说 "8 个" → 错误

### 1.10 L1/L2 规则数
- 文档："L1: 11 安全规则; L2: 33 输出规则"
- 真实：L1 **12 条**、L2 **35+ 条**

### 1.11 strict_schema 深挖
- §11.3 全部正确；额外细节：空对象注入占位属性 `{_: string}`(L133-141)、`x-local-validation` 标记(L219-224)

---

## 2. Agent C — validation 层 + validation_kernel + 编译器中间端 ✅

### 2.1 validation 层已 v0.7 重构（最大发现）
- 文档描述基于旧 `validation/pipeline.py` 实现
- 真实：`validation_kernel/`（8 文件）是**新校验引擎**，`validation/pipeline.py` 是**薄兼容 wrapper**（docstring 明确 "Deprecated compatibility path"，L19-31 委托 `run_validation()`）
- 权威 stage 顺序迁移到 `validation_kernel/stages.py`：
  - `RAW_STAGE_ORDER` = 11 阶段：structure → root_terminal → registry → params → ownership → graph → typecheck → phase → composition → hole_semantics → safety（与文档 §4.2 顺序一致）
  - `CANONICAL_STAGE_ORDER` = 2：dialect_semantics → geometry_preflight
  - `FULL_STAGE_ORDER` = 14（11 RAW + canonicalize + 2 CANONICAL）
- **文档内部矛盾**：§2.1 说 "16 个 RAW"（错），§4.2 说 11（对）
- Core 规则实际注册 **10 RAW + 2 CANONICAL**（legacy_adapter.py:40-56）
- **hole_semantics 已迁出** → `extensions/features/hole/__init__.py` 以 EXTENSION 规则注册（rule_id="feature.hole.semantics"），selector=HOLE_OPERATIONS；文档把它列为第 10 个 RAW 阶段，stage 顺序仍在但激活条件变了

### 2.2 Fact Rules = 8 条 ✅
- fact_rules.py:600-609 的 FACT_RULES 与文档 §6.4 表格完全一致
- 文档 §4.1 说 "9 规则" 是错的（§2.1 说 8 对）
- FactPropagationPass / PlannerPass 仍存在且活跃；build_compiler_module(canonical) 注册并运行两者

### 2.3 常量核对
- middle_end_enabled()：SEEKFLOW_GCAD_ENABLE_MIDDLE_END 默认 "1" ✅
- FAIL_ON_MIDDLE_END_ERROR=True / MIN_WALL_MARGIN_MM=1.0 / MAX_DIM_EXPR_RECURSION=16 ✅
- risk_model.py：HOLE_PATTERN_BATCH_THRESHOLD=8 / LARGE=120 / MANY_DESTRUCTIVE=32 ✅
- 额外：MAX_PATTERN_INSTANCES=360（risk_model.py:25）文档未提，且**全库无强制引用**（定义但未强制）

### 2.4 §13.2 边界情况核对
- 300+ 孔 segfault：限制依然成立，无缓解（MAX_PATTERN_INSTANCES 定义了但未强制）
- Helix >8 turns：MAX_TURNS_ONE_SHOT=8 / MAX_TURNS_PER_SEG=3 ✅
- 零值 chamfer/fillet：_fix_chamfer_zero_distance ✅
- 3+ solids pairwise union ✅

### 2.5 其他
- validate_and_canonicalize_with_bundle() 签名返回 3 元组 ✅（保留 2 元组版本）
- §16.6 指南过时：校验顺序修改位置已从 pipeline.py 迁到 validation_kernel/stages.py
- FactPropagationPass 是纯 Kahn（无 DFS 降级，文档 §13.3 描述不准确）
- repair_kernel/orchestrator.py:191 直连 run_validation；:364 是 apply_repair_patch_v2 的现行调用方
- validation_kernel 对应设计文档：`docs/text2cad_validation_autofix_refactor_guide_v1.md`，5 阶段重构计划

---

## 3. Agent D — dialects + runtime + pipeline ✅

### 3.1 方言 op 数量
- axisymmetric=8、sketch_extrude=11、loft_sweep=4、shell_housing=2、composition=7 ✅ 全部一致
- **sketch_profile 文档写 9 → 真实 11**（多 `revolve_profile`、`fillet_sketch`，dialect.py:80-159）

### 3.2 run_canonical_gcad() 13 → 14 步（最大差异）
- 文档 13 步全部保留且顺序不变
- **新增第 10 步：OCAF 拓扑写入**（run.py:541-570）→ `_run_ocaf_write_and_save()`（run.py:125-228）：begin_write → TopologyNamingWriter → label_index.save_to_ocaf → commit → save_temp → CAE preflight → 子进程 verify → publish .xbf
- 按 ctx.topology_mode（off/audit/enforce）决定失败是否致命
- **整个 topology/ocaf 子系统（27 文件）在文档 §3.1 中不存在**

### 3.3 run_canonical_gcad 签名 7 → 9 参
- 新增 `ocaf_path: Path|None = None`（已废弃）、`topology: Any = None`（TopologyRunConfig）
- run.py:296-319 有 ocaf_path→TopologyRunConfig 向后兼容转换

### 3.4 GcadRunResult 9 → 10 字段
- 新增 `runtime_report: Any`（results.py:22，Stage B 结构化诊断）

### 3.5 RuntimeContext 新增大量字段（文档缺失）
- 新增：workspace_root、geometry_runtime/tolerance/cache、runner_version、spatial_audit_report、planning_report、component_state
- **新增 v6.4/v6.5 拓扑字段**：enable_topology_capture、capture_session、topology_mode、design_lineage_id、revision_id、ocaf_repository、selection_service、topology_audit、required_selection_ids（context.py:56-68）

### 3.6 runtime 新文件（文档未提）
- `runtime/diagnostics.py`：Stage B 结构化诊断（RuntimeIssue/RuntimeReport，依据 repair_loop.md §5.2）
- `runtime/errors.py`：GcadRuntimeError(RuntimeError)，已统一 executor/recovery/run.py 的异常类型

### 3.7 其他差异
- **semantic_postcheck 无调用点**：文档 §5.2/§7.2 说后处理含 semantic_postcheck，但 grep 只有定义（semantic_postcheck.py:63），run.py 只调 validate_runtime_postconditions + validate_final_geometry
- 方言子目录文件数多数 +1（含 __init__.py）；axisymmetric 另有新增 thread_params.py
- geometry_utils 实际 9（8 内容 + __init__），文档计数口径自相矛盾
- BaseDialect 8 方法 ✅；execute_operation 返回 ExecutedNode ✅（仅关键字参数 + GcadRuntimeError）
- RuntimeHandle 9 子类 ✅；governance 21+17 禁令 ✅；冻结注册表 ✅

---

## 4. Agent B — authoring + spatial + IR ✅

### 4.1 一致项
- authoring/pipeline 8 阶段结构 ✅；generate_gcad_from_user_request() 签名 ✅
- RawSafety 7 个标志 ✅；RawConstraints 字段（require_step_file/require_metadata_sidecar/require_closed_solid/expected_body_count/expected_bbox_mm/bbox_tolerance_mm/max_runtime_seconds）
- DimExpr 10 种 op ✅（expr.py:25-36）
- CanonicalGcadDocument 额外字段 ✅；repair_agent 3 轮 ✅（build_pipeline 默认 max_repair_attempts=2）
- assemble_raw_gcad_document 签名 ✅（含 document_id/units）
- auto_fixer 规则实际 **31 条**（文档"20+"保守但不矛盾）；允许类别 {SYNTACTIC_ALIAS, SCHEMA_DEFAULT, CONTEXT_SAFE} ✅

### 4.2 重要错误（需优先修正）
1. **schema_version 值**：文档说 "0.2.0" exact match → 真实是 **`"g_cad_core_v0.2"`**（raw.py:115、raw_assembler.py:233、canonical.py:72）。"0.2.0" 实际是方言版本（selected_dialects[].version）。文档把 schema_version 与方言版本混淆
2. **MIN_PRIORITY_THRESHOLD**：文档 0.15 → 真实 **0.05**（question_planner.py:23）
3. **RefPath 白名单**：文档 17 → 真实 **18**（去掉 notes，补 center_bore_radius_mm、extra；expr.py:42-61）
4. **SpatialModeType**：文档 2 模式（guided/precision）→ 真实 **5**（+auto_conservative/auto_mechanical/auto_complex_verified；schemas.py:29-32）
5. **bearing_on_base**：文档说注入 "supports" → 真实注入 "above"+"coaxial"（bearing_on_base.py:39,52）；flanged_connection 额外注入 attached_to

### 4.3 数量类修正
- spatial 文件 18 → **17**（11 顶层 + archetypes 6）
- spatial schemas ~30 → **26** 个 Pydantic class（schemas.py:76-544）
- authoring 13 → **14** 文件；failure code 30 → **29**（failure_taxonomy.py:15-61）
- prompt_builders 4+4 → **5+5**（含 RUNTIME_REPAIR_SYSTEM_PROMPT + build_runtime_repair_user_prompt）

### 4.4 其他
- 单组件跳过空间前端：**代码未实现**（仅注释声称，pipeline.py:62；实际容错在 answer_normalizer.py:40 / integration.py:36）
- constraint_graph 7 种映射 ✅（文档标题写 6 但列 7 条，代码是 7）
- solver 3 项检查、validators V001-V008、SpatialSessionState 字段 ✅

---

## 5. Agent E — repair + topology/ocaf + legacy ✅

### 5.1 repair_kernel/（文档未提，生产活跃）
- Issue-driven 修复引擎：validate → propose → 原子应用 → revalidate → QualityVector 严格验收
- 复用 repair/ 的 RepairPatchV2、RepairStateV2、hash 原语
- 文件：classifier.py（可修复性分类）/ config.py（RepairLoopConfig）/ engine.py（repair_documents）/ models.py（QualityVector）/ orchestrator.py（run_generation_loop，validation+runtime 双环）/ providers.py（5 个 provider：Sanitize/SchemaDefault/DialectAlias/OpVersion/LegacyAutoFix）
- **生产入口**：app/text-to-cad/server/main.py:413-434 调用 run_generation_loop
- authoring/pipeline.py:423-558 借用 repair_kernel.models（QualityVector）做质量门禁

### 5.2 RepairPatchV2 是活的；authoring/repair_agent.py 是死的（文档错误）
- 文档 §4.2 描述 repair_agent.py 为活跃 "LLM 修复循环" → **错误**
- repair_agent.py:repair_with_llm 全仓无调用者（死代码，用整文档直接重写）
- RepairPatchV2/apply_repair_patch_v2 活跃调用方：authoring/pipeline.py:525,548（Stage 7b）+ repair_kernel/orchestrator.py:276,364,524
- §18 item 4 答案：RepairPatchV2 已确认活跃，但文档指错了对象

### 5.3 §18 不确定问题的答案
- item 3：spatial/session_state.py **不存在**（SpatialSessionState 定义在 spatial/schemas.py 内）
- item 4：RepairPatchV2 活跃（见 5.2）
- item 5：compatibility/legacy_spec_adapter.py **死代码**（仅 builder.py:50,70 报错字符串提及，无 import）

### 5.4 bases/ 未全废（文档 [已废弃] 标记过度）
- dialects/axisymmetric/contract.py、manifest.py、params.py ← bases/axisymmetric/ 对应文件（活跃重导出）
- sketch_extrude 同理
- 仅 bases/*/runner.py 死（唯一 import 者是 legacy/registry_v01.py，其自身也死）

### 5.5 legacy/ 近死代码 ✅
- 11 个顶层 shim 重导出 + legacy/ 内部互导；无生产模块 import
- 有隔离测试强制：test_gcad_v05~v10_legacy_isolation.py、test_no_production_legacy_imports.py
- 文档 §3.1 说 legacy/ 是 "v0.1 遗留代码（测试兼容）" → 与事实一致且更彻底

### 5.6 base_packages/ 确为 4 个包 ✅
- axisymmetric/sketch_extrude/composition/sketch_profile；loft_sweep/shell_housing 无 base package
- 瑕疵：BasePackageId 枚举只有 3 个，漏 SKETCH_PROFILE（base_packages/models.py:15-19）

### 5.7 topology/ocaf/（最大缺失子系统）
- 25 文件、~5500 行：models(521)/compat(341)/schema(299)/label_index(482)/document(380)/repository(323)/revision_store(166)/writer(323)/selection_service(542)/cae_preflight(144)/verify_worker(204)/solve_worker(154)/heuristic_candidates(199)/errors(116)/tracked_ops/(8 个 ops)
- **已接线**：pipeline/run.py:125-228 _run_ocaf_write_and_save()，run_canonical_gcad 在 topology mode ≠ off 时调用
- 方言 handler 走 tracked_ops：sketch_extrude/handlers.py、sketch_profile/handlers.py、composition/handlers.py
- 测试：tests/generative_cad/topology/ocaf/ 26 测试文件 + 4 smoke，~212 测试函数
- docs/ 下有 17 份 OCAF 配套文档（OCAF_* 系列 + Text-to-CAD_OCAF*指导书 v1.0~v6.0）
- 实施状态：PR-0~PR-3 完成，PR-4（Selection/Solve）为下一步（注意：这是 07-25 状态，后续 v5/v6 已推进）

### 5.8 目录文件数修正（Agent E 口径）
- ir/ 文档 11 → 实际 10（不含 __init__ 则 9）
- base_packages/ 7 → 11；bases/ 10 → 12；repair/ 3 → 4；compatibility/ 1 → 2

---

## 6. 汇总：所有差异点一览

（略——见各节。修正时主文档逐个落地。）
