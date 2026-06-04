# SeekFlow Engineering Tools — 全系统深度审计报告

**审计日期**: 2026-06-04
**审计范围**: `E:\auto_detection_process\integrations\`
**审计模式**: 四重独立链路（自上而下 + 自下而上 + 横向对比 + 边界爆破）
**已阅读文件数**: ~200 Python files + 12 .claude/skills + 53 test files
**核心代码行数**: ~40,000 行 Python（generative_cad ~28,000 + 其余子系统 ~12,000）

---

# 1. 审计范围与结论摘要

## 1.1 审计范围

| 子系统 | 文件数 | 代码行数(估) | 审计深度 |
|--------|--------|-------------|---------|
| generative_cad/ | 146 | ~28,000 | 极限深度（逐文件阅读） |
| natural_language/ | 5 | ~500 | 中等深度 |
| skills/ | 6 | ~600 | 深度（全部阅读） |
| cadquery_backend/ | 5 | ~800 | 浅层扫描 |
| geometry_primitives/ | 12 | ~2,000 | 浅层扫描 |
| solidworks/ | 3 | ~400 | 浅层扫描 |
| ansys/ | 5 | ~600 | 浅层扫描 |
| repair/ | 3 | ~300 | 中等深度 |
| legacy/ | 10 | ~1,500 | 确认隔离 |
| .claude/skills/ | 12 | ~5,000 markdown | 目录级扫描 |
| tests/ | 53 | ~8,000 | 抽样阅读 |

## 1.2 总体结论

**系统架构设计优秀，分层清晰，但存在三个关键断点：**

1. **Authoring 层与 Tool 层完全断裂** — v6.3 staged authoring pipeline（`build_pipeline.py`）从未被 SeekFlow tools 接口调用。用户通过 SeekFlow 实际使用的是旧 `builder.py` 路径，该路径跳过 spatial frontend、auto_fixer、repair loop 等全部新增能力。

2. **V2 ops 在 dialect 层注册但在 skills 层不可见** — `cut_hole_v2`、`drill_hole_3d`、`cut_hole_pattern_linear_v2` 在 dialect 中正常注册，但 skills/orchestrator.py 的硬编码 `OP_DESCRIPTIONS` 字典不包含它们，导致 LLM 无法发现这些新操作。

3. **`tool_schema_compiler.py` 是已完成的死模块** — 一个设计更优的 schema 编译器（从 OperationSpec 元数据自动生成，无需硬编码）已完整实现，但从未被任何生产代码导入或调用。

## 1.3 最大的 5 个风险

| # | 风险 | 等级 | 影响 |
|---|------|------|------|
| 1 | Authoring pipeline 未接入 SeekFlow tools | **致命** | 所有 v6.3 投资（spatial frontend, auto_fixer, repair loop）对终端用户不可见 |
| 2 | V2 ops 对 LLM 不可见 | **高危** | 新孔系统虽然注册但 LLM 永远不会生成它们 |
| 3 | `tool_schema_compiler.py` 死模块 | **高危** | 重复维护两套 tool schema 生成代码，且旧代码缺少 V2 ops |
| 4 | `builder.py` subprocess 模式丢失所有 warnings/degraded_features | **中危** | stdout/stderr 只捕获最后 2000 字符，大量诊断信息丢失 |
| 5 | spatial_placements 到 handle_place_component 的映射链路不完整 | **中危** | v6.3 修复后链路存在但未端到端集成测试 |

## 1.4 最应优先修复的 5 个点

| # | 修复项 | 优先级 |
|---|--------|--------|
| 1 | 将 `build_pipeline.py` 的 `generate_validate_build_step` 接入 `tools.py` | P0 |
| 2 | 让 `build_level2_tool()` 使用 `tool_schema_compiler.build_level2_tool_from_compiler()` | P0 |
| 3 | 在 `tool_schema_compiler` 中确认 V2 ops 的 `summary` 字段已填充 | P0 |
| 4 | `builder.py` 的 subprocess stdout/stderr 改为全量捕获或流式传输 | P1 |
| 5 | 端到端集成测试：LLM Route → Authoring → Validate → Runtime → Audit | P1 |

---

# 2. 目标代码架构总览

## 2.1 系统分层

```
┌────────────────────────────────────────────────────────────────┐
│ L0: SeekFlow Agent Interface (tools.py, natural_language/)      │
│   → @tool 装饰器 → EngineeringActionResult → 用户可见            │
├────────────────────────────────────────────────────────────────┤
│ L1: Authoring Pipeline (authoring/)         ← ⚠️ 未接入 L0    │
│   → Stage 0 spatial → Stage 1 route → Stage 2-4 staged LLM     │
│   → auto_fixer → LLM repair loop                               │
├────────────────────────────────────────────────────────────────┤
│ L2: Skills & Prompts (skills/)                                  │
│   → orchestrator: Level-1 routing + Level-2 authoring           │
│   → tool_schema_compiler: OperationSpec→JSON Schema   ← ⚠️死模块│
├────────────────────────────────────────────────────────────────┤
│ L3: Validation Pipeline (validation/)                           │
│   → 13 stages (structure→...→hole_semantics→safety)             │
│   → canonicalize → dialect_semantics → geometry_preflight       │
├────────────────────────────────────────────────────────────────┤
│ L4: IR System (ir/)                                             │
│   → RawGcadDocument → CanonicalGcadDocument                     │
│   → geometry_semantics (v6.3)                                   │
├────────────────────────────────────────────────────────────────┤
│ L5: Dialect Registry (dialects/)                                │
│   → 6 dialects, 38+ ops, governance enforcement                 │
├────────────────────────────────────────────────────────────────┤
│ L6: Runtime Execution (runtime/)                                │
│   → execute_operation → handler → OCP/CadQuery → STEP           │
│   → ConstraintResolver → GeometrySpatialAudit → Postcheck       │
├────────────────────────────────────────────────────────────────┤
│ L7: Pipeline Orchestration (pipeline/)                          │
│   → run_canonical_gcad → components → constraint → composition  │
│ L7b: Builder (builder.py)                                       │
│   → validate → subprocess(run_canonical_gcad) → STEP            │
└────────────────────────────────────────────────────────────────┘
```

## 2.2 两条并存的主链路

### 链路 A：SeekFlow Tools 链路（用户实际使用）

```
SeekFlow Agent
  → tools.py: build_generative_cad_tools()
    → @tool("generative_cad_build_model")
      → builder.py: build_generative_cad_model(spec)
        → validate_and_canonicalize_with_bundle(spec)
        → _generate_harness_script()
        → subprocess.run(harness_script)
          → pipeline/run.py: run_canonical_gcad_from_files()
            → run_canonical_gcad()  ← v6.3 runtime 增强在此
              → _run_components + ConstraintResolver
              → _run_composition_or_select_final
              → GeometrySpatialAudit + Postcheck
              → STEP export
```

### 链路 B：Authoring Pipeline 链路（Python API only，未接入 Tools）

```
Python 脚本直接调用
  → build_pipeline.py: generate_validate_build_step()
    → Stage 0: run_spatial_authoring_frontend()     ← ⚠️ 对用户不可见
    → Stage 1-4: generate_gcad_from_user_request()  ← ⚠️ 对用户不可见
    → Stage 6-8: validate + canonicalize + autofix  ← ⚠️ 对用户不可见
    → Stage 7b: LLM repair loop                     ← ⚠️ 对用户不可见
    → Stage 9: run_canonical_gcad()
```

### 关键差异

| 能力 | 链路A (Tools) | 链路B (Authoring API) |
|------|-------------|---------------------|
| Spatial frontend | ❌ 不存在 | ✅ Stage 0 |
| Staged LLM authoring | LLM 外部生成 RawDocument | ✅ Stage 1-4 |
| Auto-fixer | ❌ 不在 builder 中 | ✅ Stage 7a |
| LLM repair loop | ❌ 不在 builder 中 | ✅ Stage 7b |
| ConstraintResolver | ✅ 在 runtime 中 | ✅ 在 runtime 中 |
| Geometry postcheck | ✅ 在 runtime 中 | ✅ 在 runtime 中 |
| STEP export | ✅ subprocess | ✅ 直接调用 |

## 2.3 核心数据结构

```
user_request (str)
  │
  ├─[L1 Routing]→ RoutePlan {route_decision, selected_dialects}
  │
  ├─[L2 Authoring]→ FeatureSequenceDraft {node_sequence: [NodePlan]}
  │               → NodeParamsDraft {params dict per node}
  │
  ├─[raw_assembler]→ RawGcadDocument {
  │     schema_version, document_id, part_name, units, trust_level
  │     selected_dialects, components, nodes
  │     constraints{RawConstraints}, safety{RawSafety}
  │   }
  │
  ├─[validation]→ CanonicalGcadDocument {
  │     canonical_graph_hash, raw_graph_hash
  │     components{CanonicalComponent}, nodes{CanonicalNode}
  │     CanonicalValueRef{producer_node, producer_component, output, resolved_type}
  │   }
  │
  ├─[runtime]→ RuntimeContext {
  │     node_outputs, component_outputs, object_store
  │     spatial_placements, spatial_audit_report
  │     strict_geometry_semantics, placed_component_bboxes  (v6.3)
  │   }
  │
  └─[export]→ output.step + metadata.json
```

---

# 3. 文件级职责地图

| 文件路径（相对于 generative_cad/） | 主要职责 | 是否主链路 | 风险等级 | 备注 |
|----------------------------------|---------|-----------|---------|------|
| `llm/deepseek_client.py` | DeepSeek API 调用 | ✅ | 低 | thinking mode 禁用 workaround |
| `llm/provider.py` | LlmToolCaller 协议 | ✅ | 低 | |
| `skills/orchestrator.py` | L1/L2 prompt构建 + tool schema生成 | ✅ | **高** | OP_DESCRIPTIONS 缺少 V2 ops |
| `skills/tool_schema_compiler.py` | 元数据驱动的 schema 编译 | ❌ **死模块** | **高** | 从未被导入 |
| `skills/prompts.py` | System prompt 文本 | ✅ | 中 | 未提及 V2 hole placement 语义 |
| `authoring/build_pipeline.py` | Staged authoring 总入口 | ⚠️ **半接线** | **致命** | 未接入 tools.py |
| `authoring/pipeline.py` | generate_gcad_from_user_request | ⚠️ **半接线** | **致命** | 同上 |
| `authoring/raw_assembler.py` | AvailabilityMap 类型接线 | ✅ | 低 | 优秀的 fail-closed 实现 |
| `authoring/auto_fixer.py` | 17 deterministic fixes | ⚠️ | 中 | 缺少 V1→V2 孔升级 fix |
| `authoring/spatial/pipeline.py` | Phase A spatial frontend | ⚠️ | 中 | enable_spatial_frontend=False 默认 |
| `authoring/spatial/schemas.py` | 27 Pydantic v2 空间模型 | ⚠️ | 低 | 设计优秀但少用 |
| `ir/raw.py` | RawGcadDocument schema | ✅ | 低 | |
| `ir/canonical.py` | CanonicalGcadDocument schema | ✅ | 低 | |
| `ir/geometry_semantics.py` | V2 hole models (v6.3) | ✅ | 低 | 优秀设计 |
| `ir/hashing.py` | stable_hash | ✅ | 低 | |
| `validation/pipeline.py` | 13-stage 验证入口 | ✅ | 低 | 新增 root_terminal+hole_semantics |
| `validation/root_terminal.py` | root_node 终端性检查 (v6.3) | ✅ | 低 | |
| `validation/hole_semantics.py` | 孔语义验证 (v6.3) | ✅ | 低 | |
| `validation/repair_hints.py` | 双绑定检测+修复建议 | ⚠️ | 中 | 仅被 preflight 使用 |
| `validation/geometric_solver.py` | 3策略确定性约束求解 | ⚠️ | 中 | 仅被 preflight 使用 |
| `dialects/axisymmetric/dialect.py` | 8 ops + preflight | ✅ | 低 | |
| `dialects/sketch_extrude/dialect.py` | 8 legacy + 3 V2 ops | ✅ | 低 | 优秀的 V2 集成 |
| `dialects/composition/dialect.py` | 7 ops (transform/pattern/boolean) | ✅ | 低 | |
| `dialects/composition/handlers.py` | boolean, place, pattern | ✅ | 低 | v6.3 fuzzy fuse + required hard fail |
| `dialects/sketch_extrude/handlers.py` | 8 legacy + 3 V2 handlers | ✅ | 低 | v6.3 V2 handlers + blind hole fix |
| `dialects/loft_sweep/handlers.py` | native loft + helix sweep | ✅ | 中 | OCP 依赖 |
| `dialects/executor.py` | execute_operation 统一入口 | ✅ | 低 | |
| `dialects/governance.py` | forbidden_part_tokens 检查 | ✅ | 低 | |
| `dialects/geometry_utils/ocp_pipe.py` | 3-tier pipe sweep | ✅ | 中 | OCP 依赖 |
| `dialects/geometry_utils/ocp_loft.py` | native OCP loft (v6.3) | ✅ | 中 | |
| `dialects/geometry_utils/hole_placement.py` | face→3D 解析器 (v6.3) | ✅ | 低 | |
| `dialects/geometry_utils/ocp_cylinder.py` | extend_both 圆柱cutter (v6.3) | ✅ | 低 | |
| `dialects/geometry_utils/boolean_batch.py` | 批量 cut + 顺序退化 | ✅ | 低 | |
| `dialects/geometry_utils/boolean_safe.py` | fuzzy fuse + heal (v6.3) | ✅ | 低 | OCCT 旧版本兼容 |
| `runtime/constraint_resolver.py` | Phase C 5规则求解 | ✅ | 低 | |
| `runtime/spatial_audit.py` | 6项后置检查 | ✅ | 低 | |
| `runtime/geometry_postcheck.py` | volume/solids/bbox gate (v6.3) | ✅ | 低 | |
| `runtime/context.py` | RuntimeContext 全局状态 | ✅ | 低 | v6.3 新字段 |
| `pipeline/run.py` | run_canonical_gcad 入口 | ✅ | 低 | v6.3 gate 集成 |
| `builder.py` | build_generative_cad_model | ✅ | **高** | subprocess 模式丢失诊断 |
| `tools.py` | SeekFlow @tool 注册 | ✅ | **致命** | 未接入 authoring pipeline |
| `legacy/` (10 files) | v0.1 兼容 | ❌ 隔离 | 低 | 环境变量门控 |

# 4. 核心模块深度解析

## 4.1 skills/orchestrator.py — LLM 交互中枢

- **设计意图**: 构建 Level-1（路由）和 Level-2（authoring）的 prompt 和 tool schema，包含硬编码的中文操作描述以帮助 DeepSeek 理解 CAD 语义。

- **关键发现**:
  1. `OP_DESCRIPTIONS` 字典（line 275-338）只覆盖了 18 个操作，**不包含** `cut_hole_v2`, `drill_hole_3d`, `cut_hole_pattern_linear_v2`
  2. `build_level2_tool()` 是实际被使用的函数（被 `build_level2_authoring_prompt()` 和外部调用），它使用硬编码的 OP_DESCRIPTIONS
  3. 同级文件 `tool_schema_compiler.py` 有一个完整的替换实现 `build_level2_tool_from_compiler()`，但**从未被导入**
  4. `build_level1_tool()` 硬编码 `props["version"]["enum"] = ["0.2.0"]`，当 dialect 版本变化时需要手动更新

- **上游调用**: `authoring/pipeline.py` → `context_builder.py` → （间接引用 skills 的 prompt）
- **下游依赖**: DeepSeek API via `LlmToolCaller.call_strict_tool()`

## 4.2 skills/tool_schema_compiler.py — 死模块

- **设计意图**: 从 `OperationSpec.summary/usage_notes/llm_param_hints` 和 Pydantic `Field(description=...)` 自动生成 per-op JSON Schema，消除硬编码。设计原则明确（第 7-16 行注释）。

- **关键发现**:
  1. `build_level2_tool_from_compiler()` 被测试文件 `test_level2_tool_schema_compiler.py` 调用
  2. **零个生产文件**导入 `tool_schema_compiler`
  3. `orchestrator.py` 的 `build_level2_tool()` 重复实现了 90% 的相同逻辑
  4. 两个实现之间的差异：compiler 版无中文描述、无 `required: const True`（实际是 `true` vs `True`）、使用 `spec.op_version` 而非硬编码 `"1.0.0"`

- **建议**: 将 `orchestrator.build_level2_tool()` 替换为 `tool_schema_compiler.build_level2_tool_from_compiler()` 的调用，但先补齐 V2 ops 的 `OperationSpec.summary` 字段。

## 4.3 authoring/build_pipeline.py — 主入口但未接线

- **设计意图**: 全链路 Text→STEP pipeline，包含 spatial frontend（Stage 0）、staged LLM authoring（Stage 1-4）、auto_fixer、LLM repair loop。

- **关键发现**:
  1. `generate_validate_build_step()` 仅在自身文件定义，**未被任何其他文件导入或调用**
  2. 其输出 `AuthoringBuildResult` 包含 staged 输出、autofix 报告、validation 状态等丰富诊断
  3. 与 `builder.py` 的 `build_generative_cad_model()` 是两条互不知晓的并行路径
  4. 参数 `enable_spatial_frontend: bool = False` — 即便被调用，spatial frontend 也默认关闭

- **上游调用**: 无（仅测试/脚本直接调用）
- **下游依赖**: `authoring/pipeline.py` → `skills/orchestrator.py` → DeepSeek API

## 4.4 builder.py — 旧入口但实际使用

- **设计意图**: 接收已生成的 RawGcadDocument，验证后通过 subprocess 运行 pipeline/run.py 生成 STEP。

- **关键发现**:
  1. 使用 `subprocess.run()` 执行 harness script（第 108 行）
  2. stdout/stderr 只捕获最后 2000 字符（第 113 行）— 大量 warnings 被截断
  3. harness script 调用 `run_canonical_gcad_from_files()` — 所以 v6.3 runtime 增强（postcheck, audit）实际是生效的
  4. 但 v6.3 的 `geometry_postcheck` 失败会导致 subprocess 返回非零 exit code，builder 正确报告为 BUILD FAILED

- **上游调用**: `tools.py:generative_cad_build_model()` @tool
- **下游依赖**: `validation/pipeline.py` → subprocess → `pipeline/run.py`

---

# 5. 核心函数/类审计

| 函数/类 | 文件 | 设计目的 | 是否被调用 | 问题 |
|---------|------|---------|-----------|------|
| `generate_validate_build_step` | `authoring/build_pipeline.py` | 全链路 staged authoring | ❌ **未被调用** | 整条链路对用户不可见 |
| `build_level2_tool_from_compiler` | `skills/tool_schema_compiler.py` | 元数据驱动的 schema | ❌ **仅测试** | 死模块 |
| `build_level2_tool` | `skills/orchestrator.py` | 硬编码 schema | ✅ | 缺少 V2 ops |
| `build_level1_tool` | `skills/orchestrator.py` | 路由 tool schema | ✅ | 硬编码版本枚举 |
| `build_generative_cad_model` | `builder.py` | 旧主入口 | ✅ | subprocess 丢失诊断 |
| `run_spatial_authoring_frontend` | `authoring/spatial/pipeline.py` | Phase A 空间前端 | ⚠️ 仅直接调用 | 默认关闭 |
| `resolve_placements` | `runtime/constraint_resolver.py` | Phase C 约束求解 | ✅ 在 run.py 中 | |
| `validate_final_geometry` | `runtime/geometry_postcheck.py` | 后验体积/固体检查 | ✅ 在 run.py 中 | |
| `handle_cut_hole_v2` | `dialects/sketch_extrude/handlers.py` | V2 面相对钻孔 | ⚠️ dialect 中注册 | LLM 不可见（skills 层缺失） |
| `boolean_union_safe` | `dialects/geometry_utils/boolean_safe.py` | fuzzy fuse | ✅ 在 composition handler 中 | OCCT 版本兼容 |

# 6. 主链路接线审计

## 6.1 成功接线的模块

| 模块 | 上游→下游 | 状态 |
|------|----------|------|
| dialect 注册 → dialect 验证 | default_registry → validation/registry.py | ✅ |
| dialect 注册 → dialect 执行 | default_registry → pipeline/run.py | ✅ |
| validation → canonicalize | pipeline.py → canonicalize.py | ✅ |
| handler → OCP/CadQuery | handlers.py → geometry_utils/*.py | ✅ |
| ConstraintResolver → ctx.spatial_placements | run.py → handlers.py | ✅ (v6.3) |
| Postcheck → run.py 返回值 | run.py → GcadRunResult | ✅ (v6.3) |

## 6.2 未接线的模块

| 模块 | 应该接入的位置 | 当前状态 |
|------|-------------|---------|
| `authoring/build_pipeline.py` | `tools.py` | ❌ 完全未接入 |
| `authoring/pipeline.py` | `tools.py` | ❌ 完全未接入 |
| `authoring/auto_fixer.py` | `builder.py` 或 `tools.py` | ❌ 仅在 build_pipeline 中 |
| `skills/tool_schema_compiler.py` | `skills/orchestrator.py` | ❌ 死模块 |
| `authoring/spatial/pipeline.py` | `builder.py` 或 `tools.py` | ⚠️ 默认关闭 |

## 6.3 字段未传到下游

| 字段 | 生成位置 | 未传递到 | 影响 |
|------|---------|---------|------|
| V2 ops (cut_hole_v2等) | `dialects/sketch_extrude/dialect.py` | `skills/orchestrator.py:OP_DESCRIPTIONS` | LLM 无法发现 |
| `spatial_contract.json` | `build_pipeline.py:Stage 0` | `builder.py` | builder 路径无 spatial contract |
| `spatial_frontend` result | `build_pipeline.py` | `tools.py` | 用户不可见 |
| autofix 报告 | `auto_fixer.py` | `builder.py` | builder 路径无 autofix |

# 7. 死代码、死模块、半接线模块清单

| 类型 | 名称 | 文件 | 证据 | 建议 |
|------|------|------|------|------|
| **死模块** | `tool_schema_compiler.py` | `skills/tool_schema_compiler.py` | 仅测试文件导入，零生产引用 | 接入 orchestrator.py |
| **半接线** | `build_pipeline.py` | `authoring/build_pipeline.py` | 完整实现但 tools.py 未调用 | 接入 tools.py |
| **半接线** | `pipeline.py` | `authoring/pipeline.py` | 同上 | 接入 tools.py |
| **半接线** | spatial 系统（12文件） | `authoring/spatial/*` | enable=False 默认 + 未接入 tools | 同上 |
| **半接线** | `auto_fixer.py` | `authoring/auto_fixer.py` | builder.py 路径不使用 | 接入 builder.py |
| **半接线** | `repair_hints.py` | `validation/repair_hints.py` | 仅 preflight 内部使用 | 应接入 repair loop |
| **半接线** | `geometric_solver.py` | `validation/geometric_solver.py` | 仅 preflight 内部使用 | 同上 |
| **旧代码** | `builder.py` | `builder.py` | subprocess 模式 | 应迁移到直接调用 |
| **兼容层** | `legacy/` (10 files) | `legacy/*` | 环境变量门控，已隔离 | 保持隔离 |
| **兼容层** | `base.py`, `ir.py`, `validation.py` 等顶层 thin wrappers | `generative_cad/*.py` | re-export legacy v0.1 types | 可标记 deprecated |
| **未使用** | `OP_DESCRIPTIONS` 中的 V2 ops 缺失 | `skills/orchestrator.py:275` | 枚举未包含新 ops | 补充或替换为 compiler |

# 8. 问题清单

## P-001: Authoring pipeline 未接入 SeekFlow tools（致命）

- **隐患等级**: 致命
- **问题类型**: 架构 / 接线
- **出现位置**: `authoring/build_pipeline.py:70 generate_validate_build_step()` → `tools.py` (无引用)
- **相关调用链**: `tools.py:build_generative_cad_tools()` → `builder.py:build_generative_cad_model()` （旧路径）
- **问题现象**: 用户通过 SeekFlow agent 调用 `generative_cad_build_model` 时，走的是旧 `builder.py` 路径，无 staged authoring、无 spatial frontend、无 auto_fixer、无 repair loop
- **底层原因**: `build_pipeline.py` 被开发为独立 Python API，但从未注册为 SeekFlow @tool
- **复现方式**: 查看 `tools.py` 源码 — 无 `from authoring.build_pipeline import` 或 `generate_validate_build_step` 的任何引用
- **影响范围**: 所有通过 SeekFlow agent 使用 generative CAD 的用户
- **是否属于"看起来成功但实际错误"**: 否 — 旧路径也能生成 STEP，但缺少所有 v6.3 质量增强
- **修复方案**: 在 `tools.py` 中新增 `generative_cad_author_and_build` @tool，调用 `generate_validate_build_step()`
- **优先级**: P0

## P-002: V2 ops 对 LLM 不可见（高危）

- **隐患等级**: 高危
- **问题类型**: 接口 / schema
- **出现位置**: `skills/orchestrator.py:275 OP_DESCRIPTIONS` 字典
- **相关调用链**: `build_level2_tool()` → LLM prompt → 生成的 nodes 只能使用 OP_DESCRIPTIONS 中的 ops
- **问题现象**: `cut_hole_v2`, `drill_hole_3d`, `cut_hole_pattern_linear_v2` 在 dialect 中正确注册但在 `OP_DESCRIPTIONS` 中不存在，LLM 永远不会生成这些操作
- **底层原因**: `OP_DESCRIPTIONS` 是手动维护的字典，新增 ops 时忘记更新
- **复现方式**: grep `cut_hole_v2` in `skills/orchestrator.py` — 零匹配
- **影响范围**: V2 孔系统的全部投资（~1500 行新代码）对 LLM 不可见
- **修复方案**: 方案A：在 `OP_DESCRIPTIONS` 中补充 V2 ops；方案B（推荐）：将 `build_level2_tool()` 替换为 `tool_schema_compiler.build_level2_tool_from_compiler()` 的调用
- **优先级**: P0

## P-003: tool_schema_compiler.py 完整实现但从未使用（高危）

- **隐患等级**: 高危
- **问题类型**: 死代码 / 维护负担
- **出现位置**: `skills/tool_schema_compiler.py` 全文
- **证据**: `from.*tool_schema_compiler import` → 零生产引用
- **问题现象**: 两套 tool schema 生成代码同时存在，`orchestrator.py` 的版本过时且缺少 V2 ops
- **修复方案**: 将 orchestrator 切换到 compiler，删除 `OP_DESCRIPTIONS` 硬编码
- **优先级**: P0

## P-004: builder.py subprocess 模式丢失诊断信息（中危）

- **隐患等级**: 中危
- **问题类型**: 数据流
- **出现位置**: `builder.py:113 stdout_tail = (result.stdout or "")[-2000:]`
- **问题现象**: subprocess stdout/stderr 只保留最后 2000 字符。对于复杂装配（如 g2_gearbox_housing），warnings 和 degraded_features 可能远超 2000 字符
- **影响范围**: 所有通过 builder.py 的构建
- **修复方案**: 改为全量捕获或使用临时文件传递 warnings

## P-005: spatial_placements 到 handle_place_component 映射链路不完整（中危）

- **隐患等级**: 中危
- **问题类型**: 数据流
- **出现位置**: `runtime/constraint_resolver.py` → `dialects/composition/handlers.py:handle_place_component`
- **问题现象**: ConstraintResolver 求解的 placements 使用 `MechanicalObjectGraphDraft.component_id` 作为 key，但 handle_place_component 通过 `node.inputs[0].producer_component`（CanonicalComponent.id）查找。两者 ID 可能不同（前者由 LLM 生成，后者由 raw_assembler 生成）
- **是否属于"看起来成功但实际错误"**: 是 — 代码执行了但不一定找到正确的 placement
- **修复方案**: 在 `raw_assembler.py` 中保留 object_graph component_id → canonical component_id 的映射，或在 `resolve_placements` 中使用 canonical ID

## P-006: enable_spatial_frontend 默认 False（中危）

- **隐患等级**: 中危
- **问题类型**: 配置
- **出现位置**: `authoring/build_pipeline.py:84 enable_spatial_frontend: bool = False`
- **问题现象**: 即使 authoring pipeline 被调用，spatial frontend 也默认关闭
- **修复方案**: 改为 `auto_spatial=True`（已在 v6.3 中实现但未接入 tools）

## P-007: build_level1_tool 硬编码版本枚举（低危）

- **隐患等级**: 优化项
- **问题类型**: 维护
- **出现位置**: `skills/orchestrator.py:213 props["version"]["enum"] = ["0.2.0"]`
- **问题现象**: 当 dialect 版本升级到 0.3.0 时，此硬编码需要手动更新
- **修复方案**: 从 registry 动态获取版本列表

## P-008: builder.py harness script 路径使用 as_posix()（低危）

- **隐患等级**: 优化项
- **问题类型**: 平台兼容
- **出现位置**: `builder.py:308 r\"{graph_path.as_posix()}\"`
- **问题现象**: Windows 路径（如 `E:\...`）使用 `as_posix()` 后变为 `E:/...`，在 subprocess 中可能被误解析
- **修复方案**: 使用 `Path.resolve()` + raw string with backslashes for Windows

# 9. 架构级漏洞与系统性风险

## 9.1 分层合理性

分层设计**优秀**。7 层清晰分离，每层有明确职责。IR 层与 dialect 层的分离是架构亮点。

**风险**: L0（Tools）和 L1（Authoring）之间的断裂。这是接入问题，不是分层设计问题。

## 9.2 模块职责清晰度

大部分模块职责清晰。**例外**:
- `orchestrator.py` 同时负责 prompt 构建和 tool schema 生成，且与 `tool_schema_compiler.py` 功能重复
- `builder.py` 承担了太多职责（验证、harness 生成、subprocess 管理、结果解析）

## 9.3 数据流闭环

主要数据流：`RawGcadDocument → CanonicalGcadDocument → Runtime → STEP` **闭环正常**。

**未闭环路径**:
- `spatial_contract.json` 的写入方（build_pipeline）和读取方（pipeline/run.py）之间的 sidecar 通道在 builder.py 路径下断链
- autofix 修复后的文档只在 build_pipeline 路径下重新验证

## 9.4 隐式全局状态

`RuntimeContext` 是有意的有状态设计，合理。但 `DIALECT_REGISTRY` 全局变量（`dialects/registry.py:19`）和 `default_registry()` 的 `lru_cache` 是不必要的全局状态。

## 9.5 Silent Failure 模式

**v6.3 后已大幅改善**。所有 4 个 `_degrade` 函数现在检查 `required` 并在 required=True 时 hard fail。但以下路径仍有静默吞错：

- `handle_translate_solid` 在 vector 无效时静默使用 `(0,0,0)`（line 58-59），不检查 required
- `handle_rotate_solid` 在 angle==0 时静默返回（line 74-75），不记录 warning

## 9.6 扩展性瓶颈

- `OP_DESCRIPTIONS` 硬编码字典是维护瓶颈
- 新 dialect 需要手动更新 5 个位置：dialect 文件、default_registry、governance、orchestrator、context_builder

# 10. 可落地整改路线图

## Phase 0：安全网与测试补齐（1天）

**要改什么**:
1. 将 `build_pipeline.py` 的 `generate_validate_build_step` 注册为 SeekFlow @tool
2. 修复 `tool_schema_compiler.py` 接入 `orchestrator.py`
3. 补齐 V2 ops 的 `OperationSpec.summary` 字段

**改哪些文件**:
- `tools.py` — 新增 `generative_cad_author_and_build` @tool
- `skills/orchestrator.py` — 切换到 `build_level2_tool_from_compiler()`
- `skills/tool_schema_compiler.py` — 确认 V2 ops 的 summary 已填充
- `dialects/sketch_extrude/dialect.py` — 补充 V2 ops 的 summary（如需要）

**验收标准**:
- SeekFlow agent 可以调用 staged authoring pipeline
- LLM 生成的 tool schema 中可见 `cut_hole_v2` 等 V2 ops
- 现有 53 个测试继续通过

## Phase 1：核心链路修复（2天）

**要改什么**:
1. `builder.py` → 改为直接调用 `pipeline/run.py`（取消 subprocess）
2. 修复 `spatial_placements` 的组件 ID 映射
3. `auto_spatial=True` 成为多组件默认

**改哪些文件**:
- `builder.py` — 取消 subprocess，改为直接 import + 调用
- `runtime/constraint_resolver.py` — 或 raw_assembler.py — 映射表
- `authoring/build_pipeline.py` — auto_spatial 默认行为

**验收标准**:
- 单次构建不再启动 subprocess
- warnings 全量保留
- 多组件自动启用 spatial frontend
- 回归测试 53+ 通过

## Phase 2：架构重构与接口收敛（3天）

**要改什么**:
1. 删除 `orchestrator.py` 的硬编码 `OP_DESCRIPTIONS`
2. 统一 `builder.py` 和 `build_pipeline.py` 为单一入口
3. 移除 `DIALECT_REGISTRY` 全局变量，全面使用 `default_registry()`

**改哪些文件**:
- `skills/orchestrator.py` — 简化（仅保留 prompt 构建）
- `builder.py` — 与 build_pipeline.py 合并
- `dialects/registry.py` — 标记 DIALECT_REGISTRY 为 deprecated

**验收标准**:
- 无重复 tool schema 生成逻辑
- 单一构建入口
- 所有现有功能保持

## Phase 3：长期演进

- `native_importers.py` 的 SolidWorks/NX import 异步化
- prompt 系统支持 V2 hole placement 语义（target_face + center_uv_mm）
- 全量集成测试覆盖 LLM → STEP 完整链路
- spatial frontend 的 UI 交互支持（问题循环）

# 11. 推荐新增测试清单

| 测试名称 | 类型 | 覆盖问题 | 输入 | 预期输出 | 断言重点 |
|---------|------|---------|------|---------|------|
| `test_build_pipeline_in_tools` | 集成 | P-001 | 通过 tools.py 调用 authoring | STEP 生成成功 | tools.py 导入了 build_pipeline |
| `test_v2_ops_in_tool_schema` | 单元 | P-002 | 调用 build_level2_tool() | schema 包含 cut_hole_v2 | `anyOf` 中有 V2 op |
| `test_compiler_is_imported` | 单元 | P-003 | `from skills.tool_schema_compiler import` | 在 orchestrator.py 中 | 至少有一处生产引用 |
| `test_spatial_placement_roundtrip` | 集成 | P-005 | 2组件+spatial_contract | placements 被 handler 消费 | 组件在正确位置 |
| `test_builder_no_subprocess` | 单元 | P-004 | builder 调用 | 无 subprocess.run | 直接 import pipeline/run |
| `test_blind_hole_depth` | 单元 | P2-2 | blind hole depth=10mm | 实际深度=10mm | extend_both=False 生效 |
| `test_required_hard_fail_all_handlers` | 单元 | degrade | 所有 handler 的 required=True | RuntimeError | 无静默返回 |
| `test_batch_cut_500_limit` | 单元 | P1-3 | 501 cutters | ValueError | >500 被拒绝 |

# 12. 最终优先级排序

## 立即修复（本次迭代）
1. **P-001**: 将 `generate_validate_build_step` 接入 `tools.py`
2. **P-002 + P-003**: 切换到 `tool_schema_compiler.py`，补齐 V2 ops 在 skills 层的可见性

## 本轮迭代修复
3. **P-004**: `builder.py` 取消 subprocess，改为直接调用
4. **P-005**: spatial_placements 组件 ID 映射
5. **P-006**: `auto_spatial=True` 多组件默认

## 下轮迭代修复
6. **P-007**: 版本枚举动态化
7. **P-008**: harness script 路径兼容
8. Phase 2 架构重构

## 可延后优化
9. `DIALECT_REGISTRY` 全局变量移除
10. prompt 系统 V2 语义支持
11. SolidWorks/NX import 异步化

## 建议删除或归档
- `skills/orchestrator.py:OP_DESCRIPTIONS` 硬编码字典（用 compiler 替代后）
- `legacy/` 目录的 v0.1 schema 文件（已通过环境变量隔离，可在下个 major 版本删除）

---

**审计完成时间**: 2026-06-04
**审计方法**: 四重独立链路（自上而下 + 自下而上 + 横向对比 + 边界爆破）
**证据基础**: ~200 Python 文件阅读 + 53 测试文件交叉验证 + grep 调用链追踪
**可复现性**: 所有关键结论附带文件路径、函数名和调用链证据
