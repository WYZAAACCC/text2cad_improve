# SeekFlow Generative CAD v6.2 — 专家审阅指导文档

**版本**: v6.2 Engineering Baseline
**日期**: 2026-06-04
**作者身份**: CAD 编译器架构师 / 几何内核工程师 / SolidWorks & NX 首席专家
**审阅对象**: 外部专家 / 代码审核人 / 技术决策者
**代码仓库**: `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/`

---

## 0. 文档目的

本文档为外部专家提供对 SeekFlow Generative CAD v6.2 系统的**全面、深入、可审核**的技术视图。涵盖：

1. 系统架构与设计原则
2. 完整源码索引（200 个 Python 文件，精确到行数和职责）
3. 数据流与关键算法
4. 三轮测试的完整数据（v5.2→v6.1→v6.2，共 100 个 case）
5. 测试中暴露的所有问题及其根因分析
6. 当前架构的不足与建议改进方向

---

## 1. 系统架构

### 1.1 分层架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    用户自然语言输入                                │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 0 层: 空间意图解析 (v6 新增)                                  │
│  authoring/spatial/                                              │
│  MechanicalObjectGraphDraft → SpatialConstraintGraph             │
│  → Phase A Solver → Validator → Clarification Loop              │
│  核心创新: 约束延迟两阶段求解 (Phase A 符号 + Phase C 数值)        │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 1 层: 分阶段 LLM 生成 (v5.0+)                                 │
│  authoring/pipeline.py                                           │
│  RoutePlan → FeatureSequenceDraft → NodeParamsDraft × N          │
│  DeepSeek v4-pro, strict tool calling, 4 阶段分步生成             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 2 层: 系统侧组装 (v5.1+)                                      │
│  authoring/raw_assembler.py                                      │
│  AvailabilityMap + typed wiring + pairwise boolean_union 展开    │
│  Fail-closed: AssemblyError on unresolved inputs                 │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 3 层: 确定性修复 (v5.0+)                                      │
│  authoring/auto_fixer.py                                         │
│  17 个修正函数, AutoFixCategory 风险分级 (v6)                      │
│  + JSON Sanitizer (v6.1) + GeometricParameterSolver (v6.2)       │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 4 层: 验证 (9 raw + 2 canonical stages, fail-closed)          │
│  validation/pipeline.py + 16 个验证模块                           │
│  + validation/repair_hints.py (v6.1)                             │
│  + validation/geometric_solver.py (v6.2)                         │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 5 层: Canonical IR (类型解析 + 哈希)                          │
│  ir/canonical.py                                                 │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 6 层: Runtime 执行                                            │
│  pipeline/run.py                                                 │
│  _run_components → [v6] ConstraintResolver → assembly →          │
│  [v6] GeometrySpatialAudit → _export_final_solid                 │
│                                                                  │
│  6 个 Dialect 插件:                                              │
│    axisymmetric (8 ops)   sketch_extrude (8+1 ops v6.1)         │
│    loft_sweep (4 ops)     composition (7 ops)                    │
│    shell_housing (2 ops)  sketch_profile (9 ops)                │
│                                                                  │
│  几何工具层 (v6):                                                │
│    geometry_utils/ocp_wire.py     — 3D wire 构建                  │
│    geometry_utils/ocp_pipe.py     — BSpline/polyline/分段扫掠     │
│    geometry_utils/path_analysis.py — 路径形状分析 (v6.2)          │
│    geometry_utils/boolean_safe.py — fillet/chamfer 降级           │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  第 7 层: 输出                                                    │
│  STEP 文件 + metadata_v3 + spatial_contract.json                 │
│  → SolidWorks COM 导入 → SLDPRT                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 核心设计原则（6 条不变规则）

1. **LLM 不做 CAD compiler** — LLM 只抽取意图和关系, 代码负责约束求解和几何执行
2. **Fail-closed 全链路** — 任何未解决的输入/类型/约束都导致 AssemblyError 或 ValidationReport.fail
3. **验证永远不修复数据** — validation 只检测问题, 修复由 auto_fixer (确定性) 或 repair loop (LLM) 完成
4. **不破坏 primitive/generative CAD 隔离** — 两条链路完全独立
5. **不引入 part-specific operation** — dialect 是几何语法, 不是零件模板
6. **约束延迟两阶段求解 (v6)** — Phase A 符号约束 (无尺寸), Phase C 数值求解 (有尺寸)

### 1.3 v6 关键架构创新: 约束延迟两阶段求解

```
问题: Solver 需要组件尺寸 → 尺寸在后续阶段产生 → 鸡生蛋循环

方案:
  Phase A (无尺寸): relation drafts → PlacementConstraint (符号)
    约束: "$bottom_plate.Z_max + 0 = $pillar_left.Z_min"
    不计算绝对坐标

  Phase C (有尺寸): 真实 bbox 测量 → 代入符号约束 → 数值 Placement
    bottom_plate.zmax = 20mm → pillar_left.zmin = 20mm
    → composition handler 执行 placement

三阶段流水线:
  _run_components()         ← 构建 leaf components, 测量 bbox
       ↓
  ConstraintResolver        ← NEW: 符号→数值求解 (5 rules)
       ↓
  _run_composition_or_select_final()  ← 执行 placement + boolean_union
       ↓
  GeometrySpatialAudit      ← NEW: 验证空间关系 (overlap/Z-order/connectivity)
```

---

## 2. 源码索引

### 2.1 项目规模

| 指标 | 数值 |
|------|------|
| 总 Python 文件 | 200 |
| v6+ 新增文件 | **28** (17 spatial + 5 geometry_utils + 6 runtime/validation) |
| v6+ 修改文件 | **9** |
| 单元测试 | 538 (510 passed, 24 OCP-dependent skipped, 4 skipped) |

### 2.2 核心新增文件 (v6+)

| 文件 | 行数 | 职责 |
|------|------|------|
| `authoring/spatial/schemas.py` | 541 | 27 个 Pydantic v2 模型: MechanicalObjectGraphDraft, SpatialConstraintGraph, PlacementConstraint, SymbolicDimensionRef, NumericPlacement, SpatialQuestion 等 |
| `authoring/spatial/pipeline.py` | 236 | SpatialFrontend 主入口: 7-step Phase A 管线, 单组件快速路径, 多轮交互 |
| `authoring/spatial/prompts.py` | 133 | 4 个 LLM system prompt: ObjectGraph, SpatialPlan, QuestionPlanner, AnswerNormalizer |
| `authoring/spatial/tool_schemas.py` | 82 | 4 个 DeepSeek strict schema factory + const 注入 |
| `authoring/spatial/constraint_graph.py` | 146 | relation drafts → PlacementConstraint (7 种关系类型映射) |
| `authoring/spatial/solver.py` | 119 | Phase A 约束一致性: DFS 环检测, 矛盾约束检测, 实体存在性 |
| `authoring/spatial/validators.py` | 163 | V001-V008: 未放置组件, identity collapse, left/right symmetry, 连通性 |
| `authoring/spatial/question_planner.py` | 185 | 优先级公式 `impact*uncertainty/max(answer_cost,0.1)`, 默认选项生成 |
| `authoring/spatial/answer_normalizer.py` | 127 | option/custom/auto 三种模式归一化, LLM + 确定性 fallback |
| `authoring/spatial/integration.py` | 115 | placement 节点注入 FeatureSequence, SPATIAL CONTRACT 文本生成 |
| `authoring/spatial/archetypes/registry.py` | 81 | ArchetypeRegistry: matcher-based 匹配, 4 个初始 archetype |
| `authoring/spatial/archetypes/pillar_support.py` | ~100 | 立柱支撑: plates+pillars → above+symmetric_pair |
| `authoring/spatial/archetypes/axial_coupling.py` | ~80 | 轴向联轴器: hubs+spider → coaxial+face_contact |
| `authoring/spatial/archetypes/bearing_on_base.py` | ~80 | 轴承座: bearings+base → above+coaxial |
| `authoring/spatial/archetypes/flanged_connection.py` | ~80 | 法兰连接: flanges → coaxial+face_contact+attached_to |
| `runtime/constraint_resolver.py` | 312 | Phase C 数值求解: 5 rules (identity/stack/Kahn topo/align/symmetric/contact) |
| `runtime/bbox_tracker.py` | 54 | 组件 bbox 测量: object_store → CadQuery BoundingBox |
| `runtime/spatial_audit.py` | 189 | 装配后审计: overlap ratio, Z-order, connectivity, bbox, solid count |
| `validation/repair_hints.py` | 148 | Preflight-guided repair: 双约束检测 + 协调修复策略 (3 选 1) |
| `validation/geometric_solver.py` | 187 | 确定性几何约束求解: 最小改动参数调整 (ReduceHole/ReduceBore/IncreaseOuter) |
| `validation/spatial_contract.py` | 61 | spatial_contract.json sidecar 验证 |
| `dialects/geometry_utils/ocp_pipe.py` | 275 | 三级混合扫掠: BSpline → polyline → segmented, 体积验证 |
| `dialects/geometry_utils/ocp_wire.py` | 55 | OCP 原生 3D wire: polyline (BRepBuilderAPI_MakeEdge) + spline (GeomAPI_PointsToBSpline) |
| `dialects/geometry_utils/path_analysis.py` | 152 | 路径形状分析: 曲率/弯角/共线性/共面性检测, 最优方法推荐 |
| `dialects/geometry_utils/boolean_safe.py` | 79 | 安全 fillet: 渐进半径降级 (1.0→0.5→0.25→skip) |

### 2.3 关键修改文件 (v6+)

| 文件 | 行数 | v6 修改 |
|------|------|---------|
| `authoring/auto_fixer.py` | 841 | +JSON Sanitizer (v6.1), +_fix_op_versions 增强 (v6.1), +AutoFixCategory 枚举 (v6.0) |
| `dialects/axisymmetric/dialect.py` | 295 | +preflight 孔>外径检测 (v6.1), +双边界预计算 (v6.2) |
| `dialects/loft_sweep/handlers.py` | 366 | +OCP 3D pipe sweep_profile (v6.1), +分段 helix sweep (v6.2) |
| `dialects/sketch_extrude/handlers.py` | 259 | +handle_cut_hole axis=X/Y 支持 (v6.1) |
| `dialects/composition/handlers.py` | 290 | +boolean_union 三层 fallback (v6.2): union→fuse→tolerance_expanded_fuse |
| `runtime/context.py` | 64 | +spatial_placements, +spatial_audit_report, +spatial_contract_hash (v6.0) |
| `pipeline/run.py` | 386 | +ConstraintResolver 插入 (v6.0), +GeometrySpatialAudit (v6.0), +_load_spatial_contract (v6.0) |
| `authoring/build_pipeline.py` | 422 | +Stage 0 Spatial Frontend (v6.0), +10 个新参数 |
| `authoring/pipeline.py` | ~400 | +Stage 0 + spatial_frontend 字段 + enable_spatial_frontend 开关 (v6.0) |

---

## 3. 测试结果全景

### 3.1 三轮测试汇总

| 测试轮次 | 基线 | Case 数 | STEP | SW | 关键改进 |
|---------|------|---------|------|-----|---------|
| v5.2 Full35 | v5.2 | 35 | 27 (77%) | 2/27 | 基线 |
| v6.1 Full35 | v6.1 | 35 | **33 (94%)** | 33 | +6 cases (s05长弹簧/s10壳体/s13管路/s15阀体/tm06弹簧/tm15差速器) |
| v6.2 Stress30 | v6.2 | 30 | **25 (83%)** | 24 | 新功能验证 (loft/300孔/六面钻/20圈螺旋/12筋) |
| v6.1 8-Failed | v6.1 | 8 (之前失败) | 6 (75%) | 6 | s01/tm12 仍失败 (几何冲突, preflight正确拦截) |

### 3.2 各轮失败根因

**v5.2 的 8 个失败 → v6.1 修复了 6 个:**
- s05 (长弹簧) → OCP MakePipe 分段 sweep ✅
- s10 (壳体) → 混编 dialect 模板 ✅
- s13 (管路) → OCP 3D pipe 竖直段 ✅
- s15 (阀体) → _fix_op_versions 增强 ✅
- tm06 (弹簧) → OCP MakePipe 一次性 ✅
- tm15 (差速器) → preflight 增强 ✅
- s01 (薄壁法兰) → preflight 正确检测几何冲突 ❌ (prompt 问题)
- tm12 (腕部) → preflight 正确检测几何冲突 ❌ (prompt 问题)

**v6.2 Stress30 的 5 个失败:**
- g8 (变截面管) → loft_sections OCCT BRepOffsetAPI_ThruSections 失败 (OCCT 限制)
- g14 (真空腔体) → LLM 复杂装配节点引用错误 (prompt 模板不足)
- g23 (变径管) → loft + 装配 OCCT 失败 (同 g8)
- g24 (微型轴套) → 壁厚 0.25mm < preflight margin (正确拦截)
- g25 (超大环) → 1m 环 36 孔撞 center bore (正确拦截)

### 3.3 异常几何

| Case | 症状 | 根因 |
|------|------|------|
| tm07_roller | MULTI_SOLID(2) | 薄壁管+实心轴 boolean_union 失败 (grazing contact) |
| g22_heat_sink | MULTI_SOLID(2) | 3 组件散热器装配 boolean_union 失败 |
| g26_extreme_shaft | 负体积 (-34K) | 壁厚 1mm 空心轴 OCCT boolean 崩溃 |
| s05_long_spring | solids=0 (但体积正确) | CadQuery inspection artifact, SW 导入正常 |

---

## 4. 当前面临的问题 (按严重程度)

### 4.1 致命问题 — OCCT 几何内核限制

**A. Loft (放样) 不稳定**

- **位置**: `dialects/loft_sweep/handlers.py` → `handle_loft_sections` (line 120)
- **症状**: BRepOffsetAPI_ThruSections 在多截面变径 (圆→矩形→圆) 时失败。g8 (4截面), g23 (2截面+法兰装配) 均失败。
- **根因**: OCCT 7.x 的 ThruSections 对非相似截面 (不同拓扑类型) 的 G0 连续性处理有限。CadQuery 的 `.loft()` 封装未暴露 G1/G2 参数。
- **当前状态**: 代码中有 continuity 参数预留但未使用 (line 155 注释: "G1/G2 loft requires CadQuery/OCCT 7.7+")。
- **影响范围**: 3/30 Stress30 cases + 未来所有变截面放样零件。
- **建议**: (a) 升级 OCCT 版本到 7.7+; (b) 实现 OCP 原生 BRepOffsetAPI_ThruSections 替代 CadQuery 封装; (c) 对非相似截面自动拆分为多个相似截面段。

**B. 极薄壁 Boolean 崩溃**

- **位置**: `dialects/composition/handlers.py` → `handle_boolean_union` (line 152)
- **症状**: g26 壁厚 1mm 空心轴 (外径 16mm, 内径 14mm) 的 cut_center_bore 产生负体积。g22 3 组件散热器即使有 3 层 fallback (union→fuse→tolerance_expanded_fuse) 仍失败。
- **根因**: OCCT boolean operations 对 grazing/near-tangent contact 敏感。壁厚小于 tolerance 的若干倍时, 布尔运算不稳定。
- **当前状态**: tolerance_expanded_fuse (v6.2) 增加了 margin=linear_mm/2 的扩展, 但 margin 可能不够。
- **建议**: (a) preflight 增加最小壁厚检查 (当前 MARGIN=1.0mm 但未强制执行); (b) 对壁厚 < 2mm 的 boolean 操作自动使用更大的扩展 margin; (c) 在 preflight 中直接拒绝壁厚 < 2*linear_tolerance 的设计。

### 4.2 重要问题 — 系统设计层面

**C. 空间前端未与生产管线集成**

- **位置**: `authoring/build_pipeline.py` → `generate_validate_build_step`
- **症状**: Stage 0 代码已写入但 `enable_spatial_frontend=False` 为默认。当前 65 个测试 case 均未使用空间前端（无 LLM ObjectGraphDraft 提取）。
- **影响**: 多组件装配 (s11/s19/g1/g2 等) 的所有组件堆叠在原点 (identity placement), 空间语义完全错误。
- **根本障碍**: ObjectGraphDraft 的 LLM 提取需要额外 DeepSeek API 调用, 增加了延迟和不确定性。
- **建议**: (a) 先实现非 LLM 的空间前端 (纯 archetype 匹配, 不调用 LLM); (b) 然后逐步引入 LLM ObjectGraphDraft; (c) 对单组件 case 自动跳过。

**D. 大文件 SW 导入超时**

- **位置**: `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/native_importers.py`
- **症状**: 3.7MB 螺旋管 STEP 导入 SW 需要 5+ 分钟。COM 接口对超大文件不稳定。
- **建议**: 增加 SW 导入超时配置, 或对大文件使用异步导入 + 进度回调。

### 4.3 中等问题 — 功能缺失

**E. drill_hole_3d 未正式注册**

- **位置**: `dialects/sketch_extrude/dialect.py`
- **症状**: v6 文档设计了 `drill_hole_3d` 操作 (任意 3D 方向钻孔 + counterbore), 代码在 `handlers.py` 中实现了 `handle_drill_hole_3d`, 但未在 `op_specs` 中注册。
- **影响**: LLM 无法使用 drill_hole_3d, 只能使用 cut_hole (仅支持 axis=X/Y/Z 正交方向)。
- **建议**: 在 sketch_extrude dialect 中注册 drill_hole_3d, 并在 contract/prompt 中暴露。

**F. 密集孔 boolean 性能**

- **位置**: `dialects/sketch_extrude/handlers.py` → `handle_cut_hole_pattern_linear`
- **症状**: g27 (300 个 3mm 孔) 成功生成 1.3MB STEP, 但 OCCT boolean 时间随孔数线性增长。20×15 阵列已经接近实用上限。
- **当前状态**: 没有性能监控或上限保护。
- **建议**: (a) preflight 增加 max_holes 限制 (当前 DEFAULT_GEOMETRY_POLICY 未使用); (b) 对于 100+ 孔的阵列, 使用 OCCT 的 BRepAlgoAPI_Splitter 或 pattern 操作代替逐个 boolean cut。

### 4.4 轻微问题

**G. LLM 复杂装配节点引用错误**

- g14 (5 组件) 的 LLM 输出了错误的 node_id 引用 (`ft_pattern_rest` → `ft_cut_hole_ref`)。
- 当前 auto_fixer 的 `fix_cross_component_refs` 只能修复跨组件引用, 不能修复组件内引用。
- **建议**: 增加 `fix_intra_component_refs` 函数, 使用 node 的 op 类型推断正确的输入/输出引用链。

**H. preflight 对 edge case 的 MARGIN 硬编码**

- g24 (壁厚 0.25mm) 和 g25 (壁厚 5mm 但 36 孔撞 bore) 被 preflight 拒绝。
- MARGIN=1.0mm 在某些场景下过于保守 (微精密零件需要亚毫米 margin)。
- **建议**: 将 MARGIN 移到 GeometryTolerance 配置中, 允许按 case 调整。

---

## 5. 测试数据索引

### 5.1 v5.2 基线 (35 cases)

```
E:\auto_detection_process\demo_output_v5\v51_full35_output\
  27 STEP + 完整过程数据
  问题: OCP helix/Sweep/混编dialect/LLM op_version
```

### 5.2 v6.1 全量 (35 cases)

```
E:\auto_detection_process\demo_output_v5\v6_full35_output\
  33 STEP + 33 SolidWorks SLDPRT
  step_inspection.json (全部 33 case 体积/bbox/closed/solids)
```

### 5.3 v6.2 压力测试 (30 cases)

```
E:\auto_detection_process\demo_output_v5\v62_stress30_output\
  25 STEP + 24 SolidWorks SLDPRT
  STRESS30_AUDIT.md (完整审计)
  step_inspection.json (全部 25 case 几何检查)
```

### 5.4 v6.1 失败重测 (8 cases)

```
E:\auto_detection_process\demo_output_v5\v61_8failed_output\
  6 STEP + 6 SolidWorks SLDPRT
  V61_AUDIT_REPORT.md
```

### 5.5 测试脚本

```
E:\auto_detection_process\demo_output_v5\
  run_v51_full35.py       — v5.2 基线 (35 cases)
  run_v6_full35.py        — v6.1 全量 (35 cases, 使用 v6.1 修复)
  run_v62_stress30.py     — v6.2 压力测试 (30 个新 case)
  run_v61_8failed.py      — v6.1 8 个失败 case 重测
```

---

## 6. 关键算法详解

### 6.1 ConstraintResolver (5 规则数值求解)

**位置**: `runtime/constraint_resolver.py:44-76`

```
规则执行顺序 (必须严格):
  1. _resolve_identity    — 显式 (0,0,0) placement
  2. _resolve_stack       — Z 轴堆叠: lower.zmax + offset = upper.zmin
                            (Kahn 拓扑排序, O(V+E) 复杂度)
  3. _resolve_align_axis  — 同轴对齐: 横向坐标对齐到参考组件中心
  4. _resolve_symmetric   — X 轴对称: A.x = -d/2, B.x = +d/2
                            (Y, Z 自动传播自参考实体)
  5. _resolve_contact     — 接触验证: 检查 bbox 数据可用性
                            (实际距离验证在 GeometrySpatialAudit)
```

### 6.2 PathAnalysis → 扫掠方法选择

**位置**: `dialects/geometry_utils/path_analysis.py:20-150`

```
决策树:
  IF n==2 OR max_bend < 0.5°:
    → cylinder (BRepPrimAPI_MakeCylinder, 最快, 100% 体积)
  ELIF n==3 AND max_bend < 45° AND NOT tight:
    → polyline_sweep (单弯头 MakePipe, 可靠)
  ELIF min_bend_radius < 3*pipe_radius:
    → segmented (紧密弯头, 保证体积 > 95%)
  ELSE:
    → bspline_sweep (平滑 B 样条, 最高质量, 12+ faces)
  
  体积验证: ratio < 0.90 → 自动回退到下一级
```

### 6.3 GeometricParameterSolver

**位置**: `validation/geometric_solver.py:17-95`

```
约束方程:
  min_pcd = bore_dia + hole_dia + 2*MARGIN
  max_pcd = 2*outer_r - hole_dia - 2*MARGIN
  Feasible: min_pcd <= max_pcd

求解策略 (按最小改动量排序):
  Strategy A (ReduceHole): hole_dia -= gap/2     [改动量: gap/2]
  Strategy B (ReduceBore): bore_dia -= gap        [改动量: gap]
  Strategy C (IncreaseOuter): outer_r += gap/2    [改动量: gap/2, 但需修改 profile_stations]
```

---

## 7. 快速审核路径

### 7.1 建议阅读顺序 (按架构层次)

1. `authoring/spatial/schemas.py` — 所有数据模型 (27 models, 541 lines)
2. `authoring/spatial/pipeline.py` — SpatialFrontend 主入口 (236 lines)
3. `authoring/spatial/constraint_graph.py` — 关系→符号约束 (146 lines)
4. `runtime/constraint_resolver.py` — 数值求解器 (312 lines)
5. `pipeline/run.py` — 修改部分 (lines 123-178, 254-264)
6. `dialects/geometry_utils/ocp_pipe.py` — 混合扫掠 (275 lines)
7. `dialects/geometry_utils/path_analysis.py` — 路径分析 (152 lines)
8. `validation/repair_hints.py` — 修复提示 (148 lines)
9. `validation/geometric_solver.py` — 几何求解 (187 lines)
10. `dialects/axisymmetric/dialect.py` — preflight 修改 (lines 196-228)

### 7.2 运行验证

```bash
cd E:\auto_detection_process\integrations\engineering_tools

# 单元测试
python -m pytest tests/generative_cad/authoring/ tests/generative_cad/dialects/composition/ -v

# 全量回归
python -m pytest tests/generative_cad/ --ignore=tests/generative_cad/experiments -q

# v6 空间管线验证
python -c "
from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import default_archetypes
from seekflow_engineering_tools.generative_cad.authoring.spatial.constraint_graph import build_constraint_graph
from seekflow_engineering_tools.generative_cad.runtime.constraint_resolver import resolve_placements
# (完整集成测试代码见 docs/llm_skill_base20.md §附录 B)
"
```

### 7.3 审核关键问题

1. **约束延迟两阶段求解**是否正确解决了 Solver 尺寸依赖循环？Phase A 的符号约束是否充分表达所有必要的空间关系？
2. **Archetype 系统的匹配逻辑**是否合理？4 个初始 archetype 是否覆盖了常见的机械布局模式？
3. **PathAnalysis 的决策树**是否考虑了所有边界情况？tight bend 阈值 (3×radius) 是否合理？
4. **GeometricParameterSolver 的策略选择**（最小改动量）是否总是正确的？是否需要加权用户显式参数？
5. **preflight 的 MARGIN 硬编码**（1.0mm）是否应该可配置？对微精密零件的处理是否正确？

---

## 8. 附录: 文件完整索引

### 新增文件 (28 files, v6+)

```
authoring/spatial/__init__.py
authoring/spatial/schemas.py                    (541 loc)
authoring/spatial/pipeline.py                   (236 loc)
authoring/spatial/prompts.py                    (133 loc)
authoring/spatial/tool_schemas.py               (82 loc)
authoring/spatial/question_planner.py           (185 loc)
authoring/spatial/answer_normalizer.py          (127 loc)
authoring/spatial/constraint_graph.py           (146 loc)
authoring/spatial/solver.py                     (119 loc)
authoring/spatial/validators.py                 (163 loc)
authoring/spatial/integration.py                (115 loc)
authoring/spatial/archetypes/__init__.py
authoring/spatial/archetypes/registry.py        (81 loc)
authoring/spatial/archetypes/pillar_support.py
authoring/spatial/archetypes/axial_coupling.py
authoring/spatial/archetypes/bearing_on_base.py
authoring/spatial/archetypes/flanged_connection.py
runtime/constraint_resolver.py                  (312 loc)
runtime/bbox_tracker.py                         (54 loc)
runtime/spatial_audit.py                        (189 loc)
validation/repair_hints.py                      (148 loc)
validation/geometric_solver.py                  (187 loc)
validation/spatial_contract.py                  (61 loc)
dialects/geometry_utils/__init__.py
dialects/geometry_utils/ocp_wire.py             (55 loc)
dialects/geometry_utils/ocp_pipe.py             (275 loc)
dialects/geometry_utils/path_analysis.py        (152 loc)
dialects/geometry_utils/boolean_safe.py         (79 loc)
```

### 修改文件 (9 files, v6+)

```
authoring/auto_fixer.py                         (+JSON Sanitizer, +_fix_op_versions)
dialects/axisymmetric/dialect.py                (+preflight bore>outer, +双边界)
dialects/loft_sweep/handlers.py                 (+OCP 3D pipe, +分段 helix)
dialects/sketch_extrude/handlers.py             (+cut_hole axis=X/Y)
dialects/composition/handlers.py                (+boolean_union 3-layer fallback)
runtime/context.py                              (+spatial_placements 等)
pipeline/run.py                                 (+ConstraintResolver, +Audit)
authoring/build_pipeline.py                     (+Stage 0 Spatial Frontend)
authoring/pipeline.py                           (+spatial_frontend 集成)
```
