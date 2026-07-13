# SeekFlow Text-to-CAD + FEA 全链路修复与改进总结

## 概述

本次工作从 2026-07-13 开始，对 SeekFlow Engineering Tools 的 Text-to-CAD 系统进行了深度修复和架构升级。涵盖 FEA 仿真正确性、草图圆角语义化、专业知识 Prompt 系统和修复循环四个主要方向，共 **13 次提交**，**30+ 文件**，**~3500 行新增/修改代码**。

---

## 一、FEA 仿真正确性修复 (4 次提交)

### 问题发现

深度审查 `ansys/apdl_templates.py` 中涡轮盘 ANSYS APDL 模板，发现 **4 个 P0 级严重错误**：

### 修复清单

| # | 问题 | 修复 | 影响 |
|---|------|------|------|
| 1 | `KEYOPT,1,1,1` (三角形) + `KEYOPT,1,3,0` (平面应力) → 轴对称分析从未正确运行，环向应力全为零 | `KEYOPT,1,3,1` (轴对称)，移除错误注释 | 环向应力从全0变为 -1185~3216 MPa |
| 2 | `OMEGA,,,OMEGA` (绕Z轴) → 离心力方向错误 | `OMEGA,,OMEGA,` (绕Y轴，轴对称模型的对称轴) | 离心力方向正确 |
| 3 | `BFUNIF,TEMP,T_AVG` 均匀温度 → 150°C径向温差的热应力完全被忽略 | 逐节点 `BF,NID,TEMP,T(R)` 径向温度梯度 | 热应力从0→生效 |
| 4 | `MP,EX,1,E_BORE` 单一均匀模量，`E_RIM` 定义但未使用 | `MPTEMP,1,T_BORE,T_RIM` + `MPDATA,EX,1,1,E_BORE,E_RIM` | 温度相关模量生效 |

### 关联修复 (P1-P2)

- 几何参数从 bbox 动态推导（不再硬编码 12 点剖面）
- 线程安全锁传入后台 FEA 线程
- StressHeatmap 边界从数据动态计算
- 3D 应力渲染坐标修复（`geometry.translate()` → `mesh.position`）
- Schema 对齐（`tools.py` 与 `template_registry.py` 中 rpm min 统一为 100）

### 文件

```
integrations/engineering_tools/src/seekflow_engineering_tools/ansys/apdl_templates.py
integrations/engineering_tools/src/seekflow_engineering_tools/ansys/template_registry.py
integrations/engineering_tools/src/seekflow_engineering_tools/ansys/tools.py
app/text-to-cad/server/fea_pipeline.py
app/text-to-cad/server/main.py
app/text-to-cad/src/components/StressHeatmap.tsx
app/text-to-cad/src/components/Viewport3D.tsx
```

---

## 二、草图圆角语义化修复 (3 次提交)

### 问题发现

对照 `docs/圆角以及榫槽prompt修复.md` 深度审查 `generative_cad/dialects/sketch_profile/` 模块。

### 修复清单

| # | 问题 | 修复 |
|---|------|------|
| 1 | `handle_fillet_sketch` 静默吞掉 required 圆角失败 → 伪成功模型 | `required=True` 时 `raise RuntimeError`；仅 `required=False` 且 `degradation_policy=warn` 时允许退化 |
| 2 | `handle_close_profile` `except: pass` 后无条件 `closed=True` → 假闭合 | 调用 `wire.IsClosed()` 验证；未闭合→抛错或警告 |
| 3 | `handle_add_polyline` 首次调用 `acc.extend(acc_points[1:])` → 丢失首点 | `if not acc: acc.extend(acc_points)` 保留全部点 |
| 4 | `handle_add_arc_segment` 圆心仅用于算半径，`radiusArc` 不用指定圆心 | 验证 `|Ps-C| ≈ |Pe-C|`，不等距→`ValueError` |

### 文件

```
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_profile/handlers.py
```

---

## 三、语义化草图 API (Phase 2-3，3 次提交)

### 新增模块

| 文件 | 功能 |
|------|------|
| `sketch_profile/profile_graph.py` | `ProfileVertex` / `ProfileEdge` / `ProfileWire` / `ProfileGraph` 语义拓扑模型。`from_polyline()` 从点集构建图，`find_corner_vertex()` 通过相邻边 ID 定位角点，`interior_angle_rad()` 计算内角 |
| `sketch_profile/fillet_solver.py` | 圆角可行性预检：`check_fillet_feasibility()` 计算每条共享边的 `trim_length = R/tan(θ/2)`，验证 `∑trim < edge_length`，返回 `FILLET_SHARED_EDGE_TOO_SHORT` 结构化错误 + `suggested_max_radius_mm` |
| `sketch_profile/postconditions.py` | 后置验证体系：`check_wire_count`、`check_closed`、`check_no_zero_length_edge`、`check_fillet_arc_count`、`check_fillet_radius`、`check_arc_center` |

### 接口升级

| 接口 | 变更 |
|------|------|
| `fillet_sketch@1.0.0` | 标记 **deprecated**。`at_vertex_index` 禁用于新 L2 输出 |
| `fillet_sketch@2.0.0` | **新增**。`corner_id` + `between_segments` 替代顶点索引。每目标独立 `radius_mm`。`required` 与 `expected_convexity`。可行性预检 + OCC fillet2D + 后置验证。phase=`edge_treatment` |
| `add_arc_segment` | 圆心等距校验。`required=False` 时不等距仅发警告而非阻断裂 |

### Prompt 脱耦

- 从 `prompts.py` 删除 **120+ 行**硬编码榫槽模板（24点/W_lobe/R=1.5/固定索引/60槽/250半径/80拉伸）
- 替换为 `fillet_sketch@2.0.0` 语义圆角指导 + `between_segments` 示例

### 文件

```
generative_cad/dialects/sketch_profile/profile_graph.py       [新增]
generative_cad/dialects/sketch_profile/fillet_solver.py       [新增]
generative_cad/dialects/sketch_profile/postconditions.py      [新增]
generative_cad/dialects/sketch_profile/params.py              [修改]
generative_cad/dialects/sketch_profile/handlers.py            [修改]
generative_cad/dialects/sketch_profile/dialect.py             [修改]
generative_cad/skills/prompts.py                              [修改]
```

---

## 四、Knowledge Pack 专业知识系统 (2 次提交)

### 新增模块

| 文件 | 功能 |
|------|------|
| `knowledge/schemas.py` | `KnowledgePackManifest` / `KnowledgeRule` / `KnowledgePack` / `KnowledgeSource` / `KnowledgeDependency` 版本化模型 |
| `knowledge/registry.py` | YAML 文件系统发现。`discover()` 扫描 `packs/` 目录。`get(skill_id, version)` 检索。`validate_selections()` 检查依赖、冲突、deprecated 状态 |
| `knowledge/resolver.py` | `KnowledgeResolver.resolve()` 加载并校验已选包。`compile_l1_summary()` 输出紧凑摘要给 L1 路由。`compile_l2_knowledge()` 按优先级编译完整知识（关键章节永不截断） |

### KT787 Knowledge Pack

`knowledge/packs/turbomachinery/fir_tree_groove_kt787_figure_2_4/`：

| 文件 | 内容 |
|------|------|
| `manifest.yaml` | skill_id, version, trigger_terms, required_dialects, 适用/不适用条件, source_documents |
| `topology.yaml` | 5 条硬规则：中心线对称、线+弧构造、禁止全角统一圆角、R1~R4 独立、镜像不重复 |
| `parameters.yaml` | 6 条硬规则：MM_N/MM_A/M_R1~R2/M_W1~W3/M_A1~A3/M_B1~B4/LM_WW 语义、禁止硬编码固定值 |
| `construction.yaml` | 构造策略：一侧建模→显式圆弧→镜像→闭合→拉伸→阵列→布尔 |
| `self_checks.yaml` | 5 条自检规则：禁止24点模板、禁止统一半径、区分工作面/非工作面、禁止硬编码参数 |
| `known_conflicts.yaml` | "2对齿 vs 三齿梯形" 结构冲突记录 |

### 管道集成

- `main.py`: L1 路由加载 Knowledge Pack 摘要 → LLM 选择 → L2 注入已编译知识
- `orchestrator.py`: `build_level1_routing_prompt()` 接受 `knowledge_summaries`；`build_level2_authoring_prompt()` 接受 `knowledge_prompt`
- `forceRoute` 路径也通过 trigger_terms 匹配自动选择知识包
- 删除自动补 `skill_version="1.0"`（版本必须是路由决策的一部分）

### 测试验证

Knowledge Pack 加载后，LLM 生成的 GCAD 文档质量显著提升：

| 指标 | 无 Knowledge Pack | 有 Knowledge Pack |
|------|------------------|-------------------|
| fillet 接口 | `at_vertex_index` (V1, 匿名索引) | `between_segments` (V2, 语义边 ID) |
| 圆角语义 | `[1,2,3,...20]` 无意义索引 | `M_B1~M_B4` 工程圆弧类别 |
| 半径策略 | 统一 R=1.5mm | 独立半径 (2.0/1.5/2.5/1.5mm) |
| 圆弧构造 | 尖角折线+后处理 fillet | `add_arc_segment` 显式构造 |
| 镜像 | LLM 手写左右两套坐标 | `mirror_profile` 操作 |

### 文件

```
generative_cad/knowledge/__init__.py                         [新增]
generative_cad/knowledge/schemas.py                          [新增]
generative_cad/knowledge/registry.py                         [新增]
generative_cad/knowledge/resolver.py                         [新增]
generative_cad/knowledge/packs/turbomachinery/.../manifest.yaml    [新增]
generative_cad/knowledge/packs/turbomachinery/.../topology.yaml    [新增]
generative_cad/knowledge/packs/turbomachinery/.../parameters.yaml  [新增]
generative_cad/knowledge/packs/turbomachinery/.../construction.yaml [新增]
generative_cad/knowledge/packs/turbomachinery/.../self_checks.yaml  [新增]
generative_cad/knowledge/packs/turbomachinery/.../known_conflicts.yaml [新增]
generative_cad/skills/orchestrator.py                        [修改]
app/text-to-cad/server/main.py                               [修改]
```

---

## 五、三级修复循环 (2 次提交)

### 管道架构

```
用户 Prompt
  → L1 路由 (加载 Knowledge Pack 摘要)
  → L2 Author (LLM 生成 RawGcadDocument)
  → Validation (14 阶段)
      ├─ 通过 → Runtime
      └─ 失败 → Auto-fixer (30 条规则)
          └─ 仍失败 → Repair loop (LLM修复, 最多5轮)
              ├─ 每轮: auto-fixer → LLM emit_repair_patch → governor
              ├─ ValueError → 跳过本轮(不终止)
              └─ 耗尽 → L2 retry (重新生成 RawGcadDocument)
  → Runtime (CadQuery/OCCT)
      ├─ 成功 → STEP + STL
      └─ OCC 失败 → Runtime repair (LLM修复参数, 最多3轮)
          ├─ 每轮: LLM → apply_patch → re-validate → re-run
          └─ 耗尽 → fail-closed
```

### 关键修复

| 机制 | 说明 |
|------|------|
| Governor | `can_repair_v2()` 检测：raw hash 重复、error sig 重复两次、patch hash 重复、validation 倒退 |
| Auto-fixer per-round | 每轮 repair 前重跑 auto-fixer（修复 root_node、missing refs 等） |
| L2 retry | repair 耗尽后重新调用 DeepSeek 生成新 GCAD（利用 LLM 输出随机性） |
| Runtime repair | OCC 错误（BRep_API、No pending wires、fillet2D failed）反馈给 LLM 修复参数 |

### Auto-fixer 增强

| 新增规则 | 说明 |
|---------|------|
| `fix_fillet_zero_radius` | LLM 设 `radius_mm=0` → 改为 1.0mm |
| `fix_unknown_ops` severity `destructive`→`safe_alias` | 默认策略现在移除 LLM 虚构的 op 节点 |
| `fix_unknown_ops` op_version check | 不再将 `2.0.0` 降级为 `1.0.0`；检查版本在 dialect 中是否注册 |
| `_fix_chamfer_fillet_optional` V2 保护 | `targets` 含 `M_B` 的 fir-tree 圆角保持 `required=True` |

### 文件

```
app/text-to-cad/server/main.py                               [修改]
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/auto_fixer.py [修改]
```

---

## 六、提交历史

| Hash | 说明 |
|------|------|
| `04b996f` | feat: validation repair + L2 retry + runtime repair 三级修复循环 |
| `8e5a5cf` | fix: auto-fixer op_version不再将2.0.0降级 + unknown_ops提升为safe_alias |
| `cb7935f` | fix: fillet_sketch@2.0.0 不被auto-fixer降级 + forceRoute注入Knowledge Pack |
| `ef50d8b` | feat: Knowledge Pack 专业知识系统 + Prompt 脱耦 |
| `86b9474` | feat: ProfileGraph语义拓扑 + fillet_sketch@2.0.0 + 知识脱耦 |
| `3026f66` | fix: sketch_profile handlers 四项修复 (Phase 1 止血) |
| `7d18aab` | chore: 更新generative_cad修改 + 涡轮盘分析文档 |
| `9a8c38b` | fix: FEA仿真正确性修复 + 3D应力渲染坐标修复 |
| `8db6fce` | feat: FEA集成 + 3D应力场可视化 |
| `74e482f` | fix: 涡轮盘枞树槽多项修复 |

---

## 七、当前状态与后续规划

### 已完成

- ✅ FEA 轴对称分析正确运行（环向应力、热梯度、温度相关模量）
- ✅ 3D 应力着色（坐标修正）
- ✅ 草图 handler 四项 foundational 修复
- ✅ `ProfileGraph` 语义拓扑 + `fillet_sketch@2.0.0`
- ✅ 圆角可行性预检 (`FILLET_SHARED_EDGE_TOO_SHORT`)
- ✅ `add_arc_segment` 圆心验证
- ✅ Knowledge Pack 系统（Registry/Resolver/Compiler + KT787 首个知识包）
- ✅ 120+ 行硬编码榫槽模板从 `prompts.py` 删除
- ✅ 硬编码建模约束从 `main.py` 删除
- ✅ 三级修复循环（validation repair + L2 retry + runtime repair）

### 待规划

- P3: L2A/L2B/L2C 分阶段工程建模管线
- P4: Knowledge-driven Repair 审计追踪
- P5: 其他专业知识包扩展（燕尾槽/齿轮/叶片/密封篦齿）
- 枞树槽 3D 扇区 FEA 模型
- 前端 `send` 按钮 React onChange 兼容性
