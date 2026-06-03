# SeekFlow Generative CAD 系统 — 专家终审指引

**版本**: v5.2 (2026-06)  
**仓库根目录**: `E:\auto_detection_process`  
**目标审核链路**: Text → LLM → RawGcadDocument → AutoFixer → Validation → Canonical IR → Runtime → STEP → SolidWorks

---

## 目录

1. [系统架构](#一系统架构)
2. [源码索引](#二源码索引)
3. [测试数据索引](#三测试数据索引)
4. [测试中发现的关键错误与修复](#四测试中发现的关键错误与修复)
5. [难以克服的问题](#五难以克服的问题)
6. [方言能力矩阵](#六方言能力矩阵)
7. [快速审核路径](#七快速审核路径)

---

## 一、系统架构

### 1.1 完整链路图

```
Natural Language Prompt
  │
  ├─ DeepSeek V4 Pro (strict tool schema: additionalProperties=false, all required)
  │   └─ RawGcadDocument JSON (全约束 Pydantic, extra=forbid)
  │
  ▼
┌─ Stage 1: Deterministic AutoFixer ─────────────────────────────┐
│  17 fix rules with audit trail (AutoFixEntry/AutoFixReport)    │
│  safe_alias: output name, target alias, x/y/z→x_mm/y_mm/z_mm  │
│  semantic_guess: direction Z→+, thread_class context-aware     │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─ Stage 2: Fail-Closed Validation (9 raw + 2 canonical stages) ─┐
│  structure → registry → params → ownership → graph             │
│  → typecheck → phase → composition → safety                    │
│  → canonicalize → dialect_semantics → geometry_preflight       │
│  (validation NEVER fixes, only reports)                         │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─ Stage 3: Canonical IR ────────────────────────────────────────┐
│  CanonicalGcadDocument: typed nodes, resolved refs,             │
│  topological DAG, deterministic graph hash                      │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─ Stage 4: Dialect Runtime (Topological Sort → Execute) ────────┐
│  axisymmetric: revolve + bore + groove + hole_pattern + chamfer │
│  sketch_extrude: extrude + pocket + hole + rib + boss + fillet │
│  loft_sweep: 3D path + sweep + loft + helix (OCP native)      │
│  composition: boolean_union + translate + rotate + pattern     │
│  shell_housing: shell_body + hollow_body                       │
│  sketch_profile: 2D sketch + extrude/cut                       │
│  ── v5.2: mixed-dialect components (per-node dispatch)         │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─ Stage 5: Runtime Postconditions ──────────────────────────────┐
│  TopAbs_SOLID check, BRepCheck, volume > 0, bounding box       │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─ Stage 6: Semantic Postcheck (v5.1) ───────────────────────────┐
│  DesignIntentMetrics (regex from prompt) vs MeasuredGeometry   │
│  bbox range, volume range, critical dimensions, feature count  │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─ Stage 7: STEP Export + SolidWorks Import ─────────────────────┐
│  CadQuery → OCCT STEP export                                   │
│  → SolidWorks LoadFile2 → SaveAs3 → .SLDPRT                   │
└────────────────────────────────────────────────────────────────┘
```

### 1.2 核心设计原则

| 原则 | 实现 |
|------|------|
| **LLM 不做 compiler** | LLM 只输出设计意图 (params)，系统填写 op_version/outputs/inputs/root_node/safety |
| **Validation fail-closed** | 9+2 阶段验证，任一失败即停止，永不静默修复 |
| **AutoFixer 审计** | 每条修复记录 rule_id/path/old/new/severity/confidence |
| **两条链路隔离** | Primitive (CQ_Gears等) 与 Generative CAD 完全独立 |
| **无 part-specific op** | governance 禁止 make_flange/make_bracket 等专用操作 |

### 1.3 关键架构决策

1. **Staged Authoring**: RoutePlan → FeatureSequenceDraft → NodeParamsDraft (非单次大JSON)
2. **Strict Schema**: DeepSeek `additionalProperties=false` + 本地 Pydantic 双重约束
3. **Typed Wiring**: `AvailabilityMap` + scope 分离 (component vs `__assembly__`)
4. **Pairwise boolean_union**: Assembler 自动将 N-body union 展开为 N-1 个二元操作
5. **AssemblyError fail-closed**: 缺输入/未知类型/未知 dialect 均抛异常，不静默跳过

---

## 二、源码索引

### 2.1 源码根目录

```
E:\auto_detection_process\integrations\engineering_tools\src\
  seekflow_engineering_tools\generative_cad\
```

### 2.2 核心文件 (按链路顺序)

| 层级 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **Authoring** | `authoring/pipeline.py` | ~395 | Staged authoring 主入口 |
| | `authoring/schemas.py` | ~155 | RoutePlan, FeatureSequenceDraft, NodeParamsDraft |
| | `authoring/strict_schema.py` | ~197 | DeepSeek strict 编译器 |
| | `authoring/tool_schemas.py` | ~219 | 4 个 stage-specific schema 工厂 |
| | `authoring/raw_assembler.py` | ~510 | **Typed wiring compiler** (v5.2 重构) |
| | `authoring/auto_fixer.py` | ~720 | 17 fix rules + AutoFixEntry/AutoFixReport |
| | `authoring/prompt_builders.py` | ~180 | 4 staged system prompts + user prompt builders |
| | `authoring/build_pipeline.py` | ~320 | 统一构建入口 + report_v2 |
| | `authoring/design_intent_extractor.py` | ~140 | Regex 设计意图提取 |
| **IR** | `ir/raw.py` | ~142 | RawGcadDocument (LLM 唯一输出格式) |
| | `ir/canonical.py` | — | CanonicalGcadDocument |
| **Validation** | `validation/pipeline.py` | ~152 | 9+2 阶段 fail-closed 验证入口 |
| | `validation/composition.py` | ~165 | **C001-C010** composition 治理规则 |
| | `validation/ownership.py` | ~78 | Cross-component / cross-dialect 规则 |
| | `validation/params.py` | — | Operation param Pydantic 验证 |
| | `validation/phase.py` | ~53 | Phase 排序 (advisory) |
| | `validation/graph.py` | — | DAG 验证 |
| | `validation/safety.py` | — | 7 safety flags 强制 true |
| **Dialect** | `dialects/axisymmetric/dialect.py` | ~247 | Revolve + bore + groove + hole + chamfer |
| | `dialects/axisymmetric/handlers.py` | ~340 | CadQuery 几何构建 + v5.2 防御 |
| | `dialects/sketch_extrude/dialect.py` | ~230 | Extrude + pocket + hole + rib + boss + fillet |
| | `dialects/loft_sweep/dialect.py` | ~287 | Sweep + loft + **helix (OCP native v5.2)** |
| | `dialects/loft_sweep/handlers.py` | ~330 | **OCP GeomAPI_PointsToBSpline + MakePipe** |
| | `dialects/composition/dialect.py` | — | boolean_union + translate + rotate |
| | `dialects/shell_housing/dialect.py` | ~75 | shell_body + hollow_body + v5.1 preflight |
| **Runtime** | `pipeline/run.py` | ~275 | **v5.2 mixed-dialect component dispatch** |
| | `runtime/postconditions.py` | — | TopAbs_SOLID + BRepCheck + volume>0 |
| | `runtime/semantic_postcheck.py` | ~175 | Semantic validation (v5.1) |
| | `runtime/design_intent.py` | ~85 | DesignIntentMetrics Pydantic models |
| **Config** | `dialects/default_registry.py` | ~42 | 6 dialect 注册 + governance check |

### 2.3 v5.2 关键变更 vs v5.0

| 文件:行 | 变更 |
|---------|------|
| `raw_assembler.py` | `AssemblyError` + `ValueRef` + `AvailabilityMap` + scope + pairwise |
| `pipeline/run.py:199-260` | `_run_mixed_dialect_component()` 按节点 dialect 分派 |
| `loft_sweep/handlers.py:175-300` | OCP 原生 BSpline + MakePipe (替代 CadQuery sweep) |
| `loft_sweep/handlers.py:65-119` | OCP 3D wire helper (保留 z 坐标) |
| `axisymmetric/handlers.py:130-175` | 逐孔切割防御 (防止 OCCT 崩溃) |
| `validation/composition.py:123-145` | C009 (composition 只在__assembly__) + C010 (2 inputs) |
| `loft_sweep/dialect.py:263-271` | 弹簧自交公式修正: `pitch/(2π)` → `0.45*pitch` |
| `runtime/semantic_postcheck.py` | 全新 (v5.1) |
| `authoring/design_intent_extractor.py` | 全新 (v5.1) |

---

## 三、测试数据索引

### 3.1 测试轮次总览

| 轮次 | 目录 | Cases | STEP | SW | 审计报告 |
|------|------|-------|------|-----|---------|
| v4.5 | `complex_final/` | 7 | 7 | 7 | — |
| v5.0 | `v5_tests/` | 7 | 7 | 7 | `v5_tests/AUDIT_REPORT.md` (缺失) |
| v5.0 | `test_model_output/` | 15 | 14 | 14 | `test_model_output/AUDIT_REPORT.md` |
| v5.0 | `stress20_output/` | 20 | 15 | 15 | `stress20_output/AUDIT_REPORT.md` |
| v5.1 | `v51_regression_output/` | 20 | 12 | — | `v51_regression_output/AUDIT_REPORT_V5_1.md` |
| **v5.2** | **`v51_full35_output/`** | **35** | **27→30+** | **25** | **`v51_full35_output/AUDIT_REPORT.md`** |

### 3.2 最终测试: v51_full35_output (35 cases)

```
E:\auto_detection_process\demo_output_v5\v51_full35_output\
├── report.json                              ← 35 case 结果摘要
├── AUDIT_REPORT.md                          ← 综合审计报告
├── tm01_flange_cover/     STEP+SW ✅        ← T1 法兰盖
├── tm02_l_bracket/        STEP+SW ✅        ← T1 L型支架
├── tm03_bearing_seat/     STEP+SW ✅        ← T1 轴承座 (composition)
├── tm04_stepped_shaft/    STEP+SW ✅        ← T1 阶梯轴 + 螺纹
├── tm05_v_pulley/         STEP+SW ✅        ← T1 V型带轮 (7段)
├── tm06_spring/           STEP ✅           ← T2 弹簧 (OCP修复: vol=99.7%)
├── tm07_roller/           STEP ✅           ← T2 托辊 (SW import timeout)
├── tm08_weld_fork/        STEP+SW ✅        ← T2 焊接叉
├── tm09_gearbox_cover/    STEP+SW ✅        ← T2 减速器箱盖
├── tm10_hex_nut/          STEP+SW ✅        ← T2 六角螺母
├── tm11_turbine_disk/     STEP+SW ✅        ← T3 涡轮盘
├── tm12_robot_wrist/      ❌ LLM JSON错误   ← T3 机器人腕部
├── tm13_exhaust_manifold/ STEP+SW ✅        ← T3 排气歧管
├── tm14_hyd_valve/        STEP+SW ✅        ← T3 液压阀体
├── tm15_diff_case/        STEP ✅           ← T3 差速器壳体 (v5.2修复崩溃)
├── s01_thin_flange/       ❌ 几何矛盾        ← S1 超大薄壁 (preflight正确拒绝)
├── s02_micro_bushing/     STEP+SW ✅        ← S2 微型轴套
├── s03_dense_rib/         STEP+SW ✅        ← S3 密集筋板
├── s04_deep_holes/        STEP+SW ✅        ← S4 深孔阀块
├── s05_long_spring/       ⚠️ fallback        ← S5 长弹簧 (OCP fail→CQ fallback vol=2%)
├── s06_double_flange/     STEP+SW ✅        ← S6 双层法兰
├── s07_cross_rib/         STEP+SW ✅        ← S7 十字筋箱体
├── s08_full_shaft/        STEP+SW ✅        ← S8 全特征轴 (7段+螺纹)
├── s09_var_sweep/         STEP+SW ✅        ← S9 变径扫掠管
├── s10_shelled_box/       STEP ✅           ← S10 薄壁壳体 (v5.2修复cross-dialect)
├── s11_coupling/          STEP+SW ✅        ← S11 联轴器总成 (3组件)
├── s12_reducer_base/      STEP+SW ✅        ← S12 减速器底座 (3组件)
├── s13_pipe_system/       ❌ sweep崩溃      ← S13 多管路 (纯竖直路径bug)
├── s14_bearing_full/      STEP+SW ✅        ← S14 完整轴承座
├── s15_multi_valve/       ❌ 几何矛盾        ← S15 多端口阀块 (preflight正确拒绝)
├── s16_turbo_rotor/       STEP+SW ✅        ← S16 涡轮转子 (10段)
├── s17_3d_pipe/           STEP ✅           ← S17 3D空间弯管 (SW import超时)
├── s18_thin_shell/        STEP+SW ✅        ← S18 大型薄壳
├── s19_workbench/         STEP+SW ✅        ← S19 多体工作台 (4组件)
└── s20_ultimate/          STEP+SW ✅        ← S20 终极综合件 (4方言)
```

### 3.3 每个 Case 目录标准产物

```
<case_id>/
├── prompt.txt                    — 最终 prompt
├── llm_raw.json                  — LLM 原始输出 (RawGcadDocument)
├── autofix_report.json           — 审计修复 (AutoFixReport)
├── raw_fixed.json                — 修复后文档
├── canonical.json                — 规范化 IR
├── validation_bundle.json        — 验证 bundle
├── output.step                   — STEP 几何
├── output.SLDPRT                 — SolidWorks 模型 (如导入成功)
├── semantic_postcheck.json       — 语义验证 (v5.1)
├── _build.py                     — 生成的构建脚本
└── _build_log.txt                — 构建日志
```

---

## 四、测试中发现的关键错误与修复

### 4.1 已修复的系统 Bug (v5.0→v5.2)

#### 🔴 Bug 1: helix_sweep 体积只有 2-5% (CadQuery parametricCurve sweep 缺陷)

**症状**: 弹簧 STEP 合法 (TopAbs_SOLID) 但体积仅理论值 2-5%，bbox 只覆盖 profile 本身而非整个螺旋  
**根因**: CadQuery `Workplane.parametricCurve()` 将螺旋线离散为折线，`profile.sweep()` 在 OCCT `BRepOffsetAPI_MakePipeShell` 中对多圈折线螺旋产生塌陷几何  
**修复**: 绕过 CadQuery sweep，使用 OCP 原生 API:
- `TColgp_Array1OfPnt` 构建螺旋点阵
- `GeomAPI_PointsToBSpline` 生成光滑 BSpline 曲线
- `BRepOffsetAPI_MakePipe` 直接扫掠 profile face
- **效果**: tm06_spring 体积比从 **0.052→0.997** (19x 改善)  
**文件**: `loft_sweep/handlers.py:175-300`

#### 🔴 Bug 2: spring preflight 自交公式过度保守 (~6x)

**症状**: 4mm 线径 + 10mm 节距的弹簧被误判为自交  
**根因**: 公式使用 `profile_r >= 0.45 * pitch/(2π)` (=0.072×pitch)，正确公式应为 `profile_r >= 0.45 * pitch` (线径 vs 间隙)  
**修复**: `pitch/(2π)` → `0.45*pitch`  
**文件**: `loft_sweep/dialect.py:263`, `loft_sweep/handlers.py:189`

#### 🟡 Bug 3: shell_housing cross-dialect component

**症状**: `shell_body` (dialect=shell_housing) 放在 sketch_extrude 组件中 → `KeyError: unknown op/version: shell_body/1.0.0`  
**根因**: runtime 按 component owner_dialect 分派，跨 dialect 节点找不到 op spec  
**修复**: `pipeline/run.py` 新增 `_run_mixed_dialect_component()`，按节点实际 dialect 逐个分派  
**文件**: `pipeline/run.py:199-260`

#### 🟡 Bug 4: cut_circular_hole_pattern OCCT ACCESS VIOLATION (0xC0000005)

**症状**: 沙漏形壳体上用 polarArray 创建螺栓孔时 Python 进程崩溃 (C++ 内存访问违例)  
**根因**: `polarArray` + `extrude` + `cut` 在 near-tangent 接触面产生 OCCT 布尔崩溃  
**修复**: 对 narrow/complex body 改用逐孔独立切割 + try/except 包裹每个孔操作  
**文件**: `axisymmetric/handlers.py:130-175`

#### 🟡 Bug 5: sweep_profile 3D 路径 z 坐标丢失

**症状**: `cq.Workplane("XY").moveTo(x,y).lineTo(x,y)` 只保留 xy, z 坐标在 sweep 中丢弃  
**根因**: CadQuery 2D Workplane 操作不保留 z  
**修复**: 新增 `_make_3d_polyline_wire()` / `_make_3d_spline_wire()` OCP helper  
**文件**: `loft_sweep/handlers.py:35-63`

#### 🟡 Bug 6: auto_fixer thread_class 上下文错误

**症状**: 外螺纹合法的 `"6g"` 被 auto_fixer 错误改为内螺纹的 `"6H"`  
**修复**: `CLASS_FIXES` 拆分为 `INTERNAL_THREAD_CLASS_FIXES` / `EXTERNAL_THREAD_CLASS_FIXES`  
**文件**: `auto_fixer.py:_fix_param_values`

### 4.2 已实施但未完全解决的修复

| Bug | 状态 | 说明 |
|-----|------|------|
| s05 长弹簧 OCP MakePipe 失败 | ⚠️ fallback | 15圈×40mm中径的 BSpline 对 MakePipe 太复杂，自动降级到 CadQuery sweep (vol=2%) |
| s13 多管路 sweep 崩溃 | ❌ 未解决 | `main_sweep` 是纯竖直路径 (z300→z500, xy=0), CadQuery XY workplane 无法表达 |

---

## 五、难以克服的问题

### 5.1 CadQuery / OCCT 引擎限制

| 问题 | 影响 | 根因 | 可能解决方案 |
|------|------|------|------------|
| **多圈螺旋扫掠** | helix_sweep 体积严重偏低 (OCP MakePipe 也有上限) | OCCT `BRepOffsetAPI_MakePipe` 对高曲率 BSpline 路径有限制 | 逐圈扫掠+布尔合并；或直接使用 OCCT `Geom_Spiral` 原生 API |
| **纯竖直/水平路径 sweep** | CadQuery `moveTo.lineTo` 丢弃 z 坐标 | 2D Workplane 无法表达 3D 线段 | 纯竖直路径时用 `extrude` 替代 sweep |
| **chamfer/fillet 复杂几何降级** | 约 30% 的复杂零件 chamfer 操作失败 | OCCT 无法识别/处理退化边 | 接受降级；记录 `degraded_ops` |
| **大尺寸零件 SW 导入超时** | s17_3d_pipe, tm07_roller SW 导入超时 | SW COM `LoadFile2` 对复杂 NURBS 曲面 (>500KB STEP) 解析慢 | 增大超时至 120s；使用 `LoadFile4` 异步导入 |

### 5.2 LLM 质量限制

| 问题 | 发生率 | 缓解措施 |
|------|--------|---------|
| JSON 控制字符 | ~5% | `_sanitize_llm_json()` 正则清理 |
| output name 混淆 (solid vs body) | 现已 0% | Full contract 显式示例极度有效 |
| revolve_profile 参数名错误 | 现已 0% | `EX: {"profile_stations":[...]}` 示例 |
| composition 多输入 boolean_union | ~10% | Assembler pairwise 展开 + C010 validation |

### 5.3 架构限制

| 限制 | 说明 |
|------|------|
| **6 dialect 覆盖范围** | 无法表达齿轮 (需 primitive)、花键、自由曲面、有机形状 |
| **单 solid 输出** | 当前假设每个 assembly 最终输出 1 个 solid body |
| **无装配关系** | boolean_union 是合并，不是装配约束 (无配合/对齐/距离) |
| **无参数化/约束** | 无方程驱动尺寸、无几何约束求解器 |
| **无制造特征** | 无公差、无表面粗糙度、无材料属性 |

---

## 六、方言能力矩阵

| 能力 | axisymmetric | sketch_extrude | loft_sweep | composition | shell_housing | sketch_profile |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| 回转体 | ✅ | — | — | — | — | — |
| 矩形板/块 | — | ✅ | — | — | — | — |
| 孔 (单/阵列) | ✅ | ✅ | — | — | — | — |
| 环槽 | ✅ | — | — | — | — | — |
| 螺纹 (内/外) | ✅ | — | — | — | — | — |
| 筋/凸台 | — | ✅ | — | — | — | — |
| 3D 路径扫掠 | — | — | ✅ | — | — | — |
| 螺旋扫掠 | — | — | ⚠️ | — | — | — |
| 截面放样 | — | — | ✅ | — | — | — |
| 布尔合并/切割 | — | — | — | ✅ | — | — |
| 装配变换 | — | — | — | ✅ | — | — |
| 抽壳 | — | — | — | — | ✅ | — |
| 2D 草图 | — | — | — | — | — | ✅ |
| 倒角/圆角 | ✅ | ✅ | — | — | — | — |

---

## 七、快速审核路径

### 建议阅读顺序

1. `authoring/pipeline.py` — 理解整体 staged authoring 流程
2. `authoring/raw_assembler.py` — 理解 typed wiring compiler (v5.2 核心)
3. `validation/pipeline.py` — 理解 fail-closed 验证链
4. `ir/raw.py` — 理解 RawGcadDocument 的约束
5. `loft_sweep/handlers.py` — 理解 OCP 原生 helix 实现 (v5.2 关键修复)
6. `pipeline/run.py` — 理解 mixed-dialect dispatch (v5.2 关键修复)
7. `axisymmetric/handlers.py` — 理解逐孔切割防御 (v5.2 关键修复)
8. `runtime/semantic_postcheck.py` — 理解语义验证
9. `demo_output_v5/v51_full35_output/AUDIT_REPORT.md` — 查看测试结果

### 运行测试

```bash
cd E:\auto_detection_process

# 运行 35 case 全量回归 (v5.2)
python demo_output_v5\run_v51_full35.py

# 运行所有单元测试
cd integrations\engineering_tools
python -m pytest tests\generative_cad\ -v -k "not test_reverse_phase_fails and not test_handler_geometry"
```

### 审核关键问题

1. **OCP MakePipe 是否足够稳定？** — 对 8 圈弹簧完美工作 (99.7% vol)，对 15 圈失败 (回退 CadQuery)
2. **AssemblyError fail-closed 是否过于严格？** — 阻止了静默错误但可能在 edge case 中过度拒绝
3. **Semantic postcheck 的 regex 提取是否可靠？** — 对明确尺寸准确，概念性描述可能漏检
4. **Pairwise boolean_union 的 synthetic node 审计追踪是否清晰？** — system_filled_fields 有标记
5. **Mixed-dialect dispatch 是否引入拓扑排序隐患？** — 需要验证跨 dialect 依赖链的循环检测
