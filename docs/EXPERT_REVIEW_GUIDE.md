# SeekFlow Generative CAD 系统 — 专家审核指引文档

**版本**: v5.x  
**审核日期**: 2026-06  
**仓库根目录**: `E:\auto_detection_process`

---

## 目录

1. [系统架构概述](#一系统架构概述)
2. [源码索引](#二源码索引)
3. [测试数据索引](#三测试数据索引)
4. [关键架构决策](#四关键架构决策)
5. [已知问题与限制](#五已知问题与限制)
6. [快速启动](#六快速启动)

---

## 一、系统架构概述

### 1.1 整体链路

```
Natural Language Text Prompt
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 1: LLM Staged Authoring       │  authoring/pipeline.py
│  RoutePlan → FeatureSequenceDraft    │  authoring/schemas.py
│  → NodeParamsDraft (per operation)   │  authoring/tool_schemas.py
│  DeepSeek V4 Pro + Strict Tool Schema│  authoring/strict_schema.py
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 2: System Assembly            │  authoring/raw_assembler.py
│  LLM drafts → RawGcadDocument JSON   │
│  (fills: op_version, outputs,        │
│   linear wiring, safety, constraints)│
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 3: Deterministic AutoFixer    │  authoring/auto_fixer.py
│  17 fix rules with audit trail       │  (AutoFixEntry / AutoFixReport)
│  (safe_alias / semantic_guess)       │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 4: Fail-Closed Validation     │  validation/pipeline.py
│  9 raw stages + canonicalize +       │  validation/*.py
│  2 canonical stages (single pass)    │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 5: Canonical IR               │  ir/canonical.py
│  CanonicalGcadDocument               │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 6: Dialect Runtime            │  dialects/<name>/dialect.py
│  Topological sort → op execution     │  dialects/<name>/handlers.py
│  → CadQuery / OCCT geometry          │  dialects/executor.py
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 7: Runtime Postconditions     │  runtime/postconditions.py
│  TopAbs_SOLID, BRepCheck, volume>0   │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 8: STEP Export                │  pipeline/run.py
│  → output.step + metadata.json       │  pipeline/artifact.py
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Stage 9: SolidWorks Import (optional)│  solidworks/com_client.py
│  STEP → LoadFile2 → SaveAs3 → SLDPRT │
└──────────────────────────────────────┘
```

### 1.2 6 个建模方言 (Dialects)

| 方言 | ID | 操作数 | 几何能力 |
|------|-----|--------|---------|
| Axisymmetric | `axisymmetric` | 8 | 回转体 + 孔 + 环槽 + 螺纹 + 倒角 |
| Sketch Extrude | `sketch_extrude` | 8 | 矩形拉伸 + 切割 + 孔 + 筋/凸台 + 圆角/倒角 |
| Composition | `composition` | 5 | boolean_union/cut, translate/rotate, pattern, place |
| Loft Sweep | `loft_sweep` | 4 | 3D 路径扫掠, 截面放样, 螺旋扫掠 |
| Shell Housing | `shell_housing` | 2 | 抽壳, 挖空 |
| Sketch Profile | `sketch_profile` | 9 | 2D 草图 + 轮廓拉伸/切割 |

### 1.3 两条并行链路

```
链路 A (非 Primitive, 本系统):
  Text → LLM(严格Schema) → RawGcadDocument → AutoFixer → Validation → Canonical → Runtime → STEP

链路 B (Primitive, 独立):
  CADPartSpec → CQ_Gears / recipe generators → STEP
  (本系统不修改、不触碰链路 B)
```

---

## 二、源码索引

### 2.1 源码根目录

```
E:\auto_detection_process\integrations\engineering_tools\src\
  seekflow_engineering_tools\generative_cad\
```

### 2.2 Authoring 层（LLM 交互 + 组装）

| 文件 | 行数 | 职责 |
|------|------|------|
| `authoring/pipeline.py` | ~395 | **主入口**: staged authoring (Route→Sequence→Params→Assemble→Validate→Repair) |
| `authoring/schemas.py` | ~155 | **Pydantic 模型**: RoutePlan, FeatureSequenceDraft, NodeParamsDraft, RawAssemblyResult |
| `authoring/strict_schema.py` | ~197 | **DeepSeek strict 编译器**: `to_deepseek_strict_schema()`, `strict_schema_from_pydantic()` |
| `authoring/tool_schemas.py` | ~219 | **4 个 schema 工厂**: route/feature_sequence/node_params/repair 的 strict tool schema |
| `authoring/raw_assembler.py` | ~266 | **系统侧组装器**: 将 LLM drafts 组装为完整 RawGcadDocument, 按 output type 自动接线 |
| `authoring/auto_fixer.py` | ~720 | **确定性修复器**: 17 fix 函数 + AutoFixEntry/AutoFixReport 审计 |
| `authoring/build_pipeline.py` | ~320 | **统一构建入口**: `generate_validate_build_step()` 含完整 report_v2 |
| `authoring/context_builder.py` | ~105 | 按 selected_dialects 构建 AuthoringContext |

### 2.3 IR 层（中间表示）

| 文件 | 职责 |
|------|------|
| `ir/raw.py` | **RawGcadDocument** — LLM 必须输出的唯一格式 (extra=forbid, 全约束) |
| `ir/canonical.py` | **CanonicalGcadDocument** — 验证后的规范化 IR |
| `ir/parse.py` | Raw dict → RawGcadDocument 解析 |
| `ir/hashing.py` | `stable_hash()` — 内容确定性 hash |

### 2.4 Validation 层（验证管线）

| 文件 | 职责 |
|------|------|
| `validation/pipeline.py` | **主验证入口**: `validate_and_canonicalize_with_bundle()` — 9+2 阶段 fail-closed |
| `validation/structure.py` | 结构完整性 (document_id, components, nodes 非空) |
| `validation/registry.py` | 注册表验证 (dialect/op 是否存在) |
| `validation/params.py` | 参数验证 (Pydantic model_validate 每个 op 的 params) |
| `validation/ownership.py` | 组件归属 (cross-component node ref 禁止非 composition) |
| `validation/graph.py` | DAG 验证 (无环, input ref 解析, root_node 存在) |
| `validation/typecheck.py` | 类型检查 (input/output type 匹配) |
| `validation/phase.py` | Phase 排序 (advisory only — 不强制) |
| `validation/composition.py` | 装配验证 (boolean_union 语义正确性) |
| `validation/safety.py` | 安全标记 (全部 7 个 flag 必须 true) |
| `validation/canonicalize.py` | Raw → Canonical 规范化 |
| `validation/dialect_semantics.py` | 方言级语义验证 |
| `validation/geometry_preflight.py` | 几何预检 |

### 2.5 Dialect 层（建模方言）

每个方言目录结构:
```
dialects/<name>/
  dialect.py       — 方言类 (op_specs, validate_component, preflight_component, run_component)
  params.py        — Operation-specific Pydantic 参数模型
  handlers.py      — CadQuery 几何构建函数 (handle_*)
  contract.py      — LLM 契约定义
  manifest.py      — 方言元数据
```

| 方言 | dialect.py 关键行 | 关键 preflight 检查 |
|------|-------------------|-------------------|
| `dialects/axisymmetric/dialect.py` | L28-247 | 站数≥1, 半径>0, z 顺序, 孔在轮廓内, PCD 干涉检测 |
| `dialects/sketch_extrude/dialect.py` | L24-222 | 唯一 base_solid, pocket depth<base, hole in rectangle, pattern span, edge treatment 0.45×thickness |
| `dialects/composition/dialect.py` | — | boolean_union input=2, translate/rotate 引用正确 |
| `dialects/loft_sweep/dialect.py` | L16-287 | sweep 消费 curve→输出 solid, path≥2点, 坐标 finite, 相邻点>0.1mm, helix 自交检测 |
| `dialects/shell_housing/dialect.py` | — | 基本检查 |
| `dialects/sketch_profile/dialect.py` | — | 基本检查 |

### 2.6 Runtime 层（几何执行）

| 文件 | 职责 |
|------|------|
| `dialects/executor.py` | `execute_operation()` — 调用 handler, 处理 output 绑定 |
| `runtime/context.py` | `RuntimeContext` — object_store, geometry_runtime, handle 管理 |
| `runtime/handles.py` | `SolidHandle`, `FrameHandle`, `RuntimeHandle` — 类型化句柄 |
| `runtime/resolve.py` | `resolve_input_object()` — input 引用解析 |
| `runtime/object_store.py` | 对象存储 (put/get solid, frame 等) |
| `runtime/postconditions.py` | `validate_runtime_postconditions()` — TopAbs_SOLID, BRepCheck, volume>0 |
| `runtime/geometry_runtime.py` | STEP 导出 |
| `runtime/tolerance.py` | `GeometryTolerance` — 容差配置 |

### 2.7 Pipeline 层（流程编排）

| 文件 | 职责 |
|------|------|
| `pipeline/run.py` | `run_gcad_core()`, `run_canonical_gcad()` — 从 raw/canonical 到 STEP 的入口 |
| `pipeline/artifact.py` | `build_canonical_step_artifact()` — artifact 构建与一致性检查 |
| `pipeline/metadata_v3.py` | 元数据生成 |

### 2.8 LLM 集成

| 文件 | 职责 |
|------|------|
| `llm/models.py` | `AuthoringLlmConfig` — router/author/repair 三角色 LLM 配置 |
| `llm/provider.py` | `LlmToolCaller` 抽象接口 |
| `skills/prompts.py` | `LEVEL2_AUTHORING_SYSTEM_PROMPT` — LLM 系统提示词 |
| `skills/schemas.py` | Tool schema 定义 |

### 2.9 SolidWorks 集成

```
solidworks/com_client.py   — SolidWorksClient (COM 自动化)
solidworks/tools.py        — 注册为 SeekFlow Tool 的 SW 操作
```

### 2.10 Base Packages（基础包）

```
bases/axisymmetric/    — axisymmetric_base 基础包
bases/sketch_extrude/  — sketch_extrude_base 基础包
```

---

## 三、测试数据索引

### 3.1 测试目录结构

```
E:\auto_detection_process\demo_output_v5\
├── complex_final\           ← 第 1 轮: 7 个基础复杂零件 (v4.5)
├── v5_tests\                ← 第 2 轮: 7 个改进链路测试 (v5.0)
├── test_model_output\       ← 第 3 轮: 15 个 test_model.md 零件
├── stress20_output\         ← 第 4 轮: 20 个极限压力测试
├── run_complex_parts.py     ← 第 1 轮 runner
├── run_v5_tests.py          ← 第 2 轮 runner
├── run_test_model.py        ← 第 3 轮 runner
└── run_stress20.py          ← 第 4 轮 runner
```

### 3.2 每轮测试详情

#### 第 1 轮: complex_final (7 cases) — v4.5 基线

| Case | Dialect | 状态 | STEP 大小 |
|------|---------|------|-----------|
| industrial_flange | axisymmetric | ✅ | 138KB SW |
| engine_mount | sketch_extrude | ✅ | 261KB SW |
| bearing_housing | composition | ✅ | 107KB SW |
| gearbox_housing | sketch_extrude | ✅ | 374KB SW |
| turbine_disk | axisymmetric | ✅ | 202KB SW |
| exhaust_pipe | loft_sweep | ✅ | 372KB SW |
| hydraulic_cap | axisymmetric | ✅ | 4.4MB SW |

每个 case 目录含: `output.SLDPRT`, `output.step`, `output.metadata.json`, `canonical.json`, `llm_raw.json`, `prompt.txt`

#### 第 2 轮: v5_tests (7 cases) — 改进后链路验证

| Case | Dialect | 状态 | 关键发现 |
|------|---------|------|---------|
| stepped_shaft | axisymmetric | ✅ (修复后) | auto_fixer thread_class 上下文 bug |
| sensor_mount_plate | sketch_extrude | ✅ | boss position warning |
| valve_body | axisymmetric | ✅ | — |
| u_bend_heat_exchanger_tube | loft_sweep | ✅ | **零 autofix** — LLM 完美输出 |
| pillow_block | composition | ✅ | — |
| gearbox_cover | sketch_extrude | ✅ | 3 轮通过 |
| shaft_sleeve | axisymmetric | ✅ | — |

#### 第 3 轮: test_model_output (15 cases) — test_model.md 全覆盖

| # | Case | T | 状态 | 体积 mm³ | BBox mm |
|---|------|---|------|---------|---------|
| 1 | t1_flange_cover | T1 | ✅ | 295K | [150×150×25] |
| 2 | t1_l_bracket | T1 | ✅ | 92K | [100×100×40] |
| 3 | t1_bearing_seat | T1 | ✅ | 193K | [120×85×68] |
| 4 | t1_stepped_shaft | T1 | ✅ | 118K | [44×44×120] |
| 5 | t1_v_pulley | T1 | ✅ | 1,749K | [200×200×60] |
| 6 | t2_spring | T2 | ✅ | 103 | [8×6×5] 🔴 |
| 7 | t2_roller | T2 | ✅ | 1,176K | [89×89×650] |
| 8 | t2_weld_fork | T2 | ✅ | 55K | [100×60×22] |
| 9 | t2_gearbox_cover | T2 | ✅ | 1,221K | [370×250×29] |
| 10 | t2_hex_nut | T2 | ✅ | 1.6K | [18×18×8] |
| 11 | t3_turbine_disk | T3 | ✅ | 2,750K | [300×300×85] |
| 12 | t3_robot_wrist | T3 | ❌ preflight | — | — |
| 13 | t3_exhaust_manifold | T3 | ✅ | 43K | [36×69×355] |
| 14 | t3_hyd_valve | T3 | ✅ | 815K | [80×60×200] |
| 15 | t3_diff_case | T3 | ✅ | 565K | [150×150×100] |

审计报告: `test_model_output/AUDIT_REPORT.md`

#### 第 4 轮: stress20_output (20 cases) — 极限压力

| # | Case | Dialect | 状态 | 关键发现 |
|---|------|---------|------|---------|
| 1 | Thin Large Flange | axisymmetric | ❌ preflight | 孔在中心孔内 (正确拒绝) |
| 2 | Micro Bushing | axisymmetric | ❌ preflight | 壁厚太薄 (正确拒绝) |
| 3 | Dense Rib Plate | sketch_extrude | ✅ | 10筋 OK, LLM 误用 boolean_union |
| 4 | Deep Hole Manifold | sketch_extrude | ✅ | 5 孔交叉 OK |
| 5 | Long Helix Spring | loft_sweep | ✅ | 🔴 体积 2.2% |
| 6 | Double Flange | composition | ✅ | 2 flange OK |
| 7 | Cross-Rib Box | sketch_extrude | ✅ | 10筋网格 OK |
| 8 | Full-Feature Shaft | axisymmetric | ✅ | 7 站 + 螺纹 + 环槽 |
| 9 | Variable Sweep Pipe | loft_sweep | ✅ | 多段 3D sweep OK |
| 10 | Shelled Housing | shell_housing | ❌ runtime | 🟡 集成断裂 |
| 11 | Coupling Assembly | composition | ✅ | 3 组件 OK |
| 12 | Reducer Base | composition | ✅ | 3 组件 3.1M mm³ |
| 13 | Multi-Pipe System | composition | ❌ runtime | 🔴 OCCT sweep 崩溃 |
| 14 | Full Bearing Housing | composition | ✅ | 复杂装配 OK |
| 15 | Multi-Port Valve | sketch_extrude | ✅ | 12 孔 OK |
| 16 | Turbo Rotor | axisymmetric | ✅ | 10 站 OK |
| 17 | 3D Space Pipe | loft_sweep | ✅ | 真 3D 路径 OK |
| 18 | Large Thin Shell | shell_housing | ❌ preflight | 🟡 add_boss input=0 |
| 19 | Multi-Body Workbench | composition | ✅ | 5M mm³ 大件 OK |
| 20 | Ultimate Composite | composition | ✅ | 4-dialect 综合 OK |

审计报告: `stress20_output/AUDIT_REPORT.md`

### 3.3 每个 Case 目录的标准产物

```
<case_id>/
├── prompt.txt                    — 最终发送给 LLM 的 prompt
├── llm_raw.json                  — LLM 原始输出 (RawGcadDocument JSON)
├── autofix_report.json           — 审计修复报告 (AutoFixReport)
├── raw_fixed.json                — 修复后的 RawGcadDocument
├── raw_original_validation.json  — 原始验证报告
├── raw_fixed_validation.json     — 修复后验证报告
├── canonical.json                — 规范化 IR
├── validation_bundle.json        — 完整验证 bundle
├── output.step                   — STEP 几何文件
├── output.SLDPRT                 — SolidWorks 原生文件
├── output.metadata.json          — 运行时元数据
├── _build.py                     — 生成的构建脚本
└── _build_log.txt                — 构建日志 (含 degraded ops 信息)
```

---

## 四、关键架构决策

### 4.1 设计原则

1. **LLM 不直接输出完整 RawGcadDocument** — 改为 RoutePlan → FeatureSequenceDraft → NodeParamsDraft 分阶段生成，系统侧组装固定字段
2. **Validation 永远 fail-closed** — `validate_and_canonicalize_with_bundle()` 不做任何修复，只报告
3. **Autofix 显式 + 审计** — 每个修复记录 rule_id / path / old_value / new_value / severity / confidence
4. **两条链路隔离** — Primitive 和 Generative CAD 路径完全独立，互不污染
5. **无 part-specific dialect/op** — governance 禁止 make_flange/make_bracket 等专用操作

### 4.2 Strict Schema 策略

```
Provider strict schema (DeepSeek additionalProperties=false, all required)
  +
本地 Pydantic / OperationSpec validation (最终裁决)
```

DeepSeek 不支持的约束 (`minItems`, `maxLength` 等) 移入 `x-local-validation` 标记，由本地验证器执行。

### 4.3 AutoFixer 分级

| 级别 | 示例 | 策略 |
|------|------|------|
| `safe_alias` | `all_outer_edges` → `all_external_edges`, `{x,y,z}` → `{x_mm,y_mm,z_mm}` | 自动修, confidence=1.0 |
| `semantic_guess` | `direction:"Z"` → `"+"` (仅 plane="XY") | 自动修但降级标记, confidence=0.9 |
| `destructive` | 删除未知字段 | 不自动修, 交给 LLM repair |

### 4.4 Raw Assembler 类型化接线

```python
last_output_by_type[component_id][output_type] = (producer_node_id, output_name)
# solid → body, frame → outer_frame, curve → curve, profile → profile, sketch → sketch
```

使 `create_sweep_path → curve` 输出自动连接 `sweep_profile → curve` 输入。

---

## 五、已知问题与限制

### 5.1 已修复

| Bug | 文件:行 | 修复内容 |
|-----|---------|---------|
| helix_sweep 忽略 turns 参数 | `loft_sweep/handlers.py:173` | 使用 `total_z * t` 替代 `pitch * t` |
| auto_fixer thread_class 上下文错误 | `auto_fixer.py:_fix_param_values` | 区分 INTERNAL/EXTERNAL thread class 修复表 |
| axisymmetric 不允许单 station | 3 处 | min_length=2→1, handler 支持单 station 矩形 revolve |
| pipeline.py tool_schema={} | `pipeline.py:155,205,234,351` | 全部替换为真实 strict schema |
| raw_assembler 只接 solid 链 | `raw_assembler.py:_build_inputs` | 改为 last_output_by_type 类型化接线 |
| loft_sweep validation 完全空 | `loft_sweep/dialect.py:59-63` | 添加 4 项 dialect_semantics + 6 项 geometry_preflight |
| sketch_extrude preflight 不完整 | `sketch_extrude/dialect.py:90-176` | 添加 pocket depth/boss pos/hole pos/edge treatment 检查 |

### 5.2 已知限制（待修复）

| 限制 | 严重度 | 影响范围 |
|------|--------|---------|
| helix_sweep 体积严重偏低 (~45x) | 🔴 高 | 所有弹簧/螺纹零件 |
| shell_housing 与 sketch_extrude 集成断裂 | 🟡 中 | 薄壁壳体零件 |
| boolean_union 输入数 LLM 不理解 | 🟡 中 | 3+ 组件装配 |
| spline-based helix → OCCT MakePipeShell 崩溃 | 🔴 高 | 多圈螺旋 |

---

## 六、快速启动

### 6.1 环境

```bash
Python:  E:\auto_detection_process\.conda\python.exe  (3.11.9)
CadQuery: 已安装 (含 OCP)
DeepSeek API Key: 环境变量 DEEPSEEK_API_KEY
SolidWorks 2025: COM 已注册 (可选)
```

### 6.2 运行测试

```bash
cd E:\auto_detection_process

# 运行第 4 轮 stress20 测试
python demo_output_v5\run_stress20.py

# 运行第 3 轮 test_model 测试
python demo_output_v5\run_test_model.py

# 运行已有 regression tests
cd integrations\engineering_tools
python -m pytest tests\generative_cad\ -v
```

### 6.3 审核关键文件建议阅读顺序

1. `authoring/pipeline.py` — 理解整体 staged authoring 流程
2. `authoring/schemas.py` — 理解 LLM 输出对象的 Pydantic 约束
3. `authoring/strict_schema.py` — 理解 DeepSeek strict mode 编译规则
4. `authoring/auto_fixer.py` — 理解确定性修复的 17 条规则
5. `validation/pipeline.py` — 理解 fail-closed 验证链
6. `ir/raw.py` — 理解 RawGcadDocument 的完整约束
7. `dialects/axisymmetric/dialect.py` — 代表性方言实现
8. `dialects/loft_sweep/handlers.py` — 几何 handler 实现（含已知 bug）
9. `pipeline/run.py` — STEP 构建入口
10. `demo_output_v5/stress20_output/AUDIT_REPORT.md` — 最新审计报告

---

## 附录 A: 各 dialect 操作完整列表

### Axisymmetric (8 ops)
`revolve_profile`, `cut_center_bore`, `cut_annular_groove`, `cut_circular_hole_pattern`, `cut_rim_slot_pattern`, `apply_safe_chamfer`, `cut_internal_thread`, `cut_external_thread`

### Sketch Extrude (8 ops)
`extrude_rectangle`, `cut_rectangular_pocket`, `cut_hole`, `cut_hole_pattern_linear`, `add_rectangular_boss`, `add_rib`, `apply_safe_fillet`, `apply_safe_chamfer`

### Composition (5 ops)
`boolean_union`, `boolean_cut`, `translate_solid`, `rotate_solid`, `place_component`, `circular_pattern_component`, `linear_pattern_component`

### Loft Sweep (4 ops)
`create_sweep_path`, `sweep_profile`, `loft_sections`, `helix_sweep`

### Shell Housing (2 ops)
`shell_body`, `hollow_body`

### Sketch Profile (9 ops)
`create_2d_sketch`, `add_line_segment`, `add_polyline`, `add_arc_segment`, `add_circle`, `close_profile`, `extrude_profile`, `cut_profile`

## 附录 B: 所有审计报告位置

| 测试轮次 | 审计报告 |
|---------|---------|
| 第 3 轮 (test_model) | `demo_output_v5/test_model_output/AUDIT_REPORT.md` |
| 第 4 轮 (stress20) | `demo_output_v5/stress20_output/AUDIT_REPORT.md` |
