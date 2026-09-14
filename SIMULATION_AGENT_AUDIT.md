# 自动仿真 Agent 系统审计

> 审计日期：2026-09-11
> 代码基线：`606ab55` + 工作区在途改动
> 审计范围：`_structural_experiment/`（结构）、`integrations/cfd/`（CFD）、`_cfd_experiment/local/fluent_worker.py`
> 审计方式：通读实现代码，不从文档推断。所有结论附 `file:line`。

---

## 0. 结论

**选面链路是正确的**——两个选面器都通过 agent 调 tool 做真实检索，无预置面清单，反模板声明成立。

**但仿真设置链路有严重缺陷**——CFD 侧 spec 里声明的物理设置**根本没有传进求解器**。

| 环节 | 判定 |
|---|---|
| 选面（tool 检索） | ✅ 成立 |
| 几何事实供给 | ⚠️ 可用，但法向朝向未修正、`edge_count` 恒为假值 |
| 面 → 网格映射 | ⚠️ 可用，但重叠静默丢力、零节点崩溃 |
| 结构求解设置 | ✅ 中性物化器，物理量强制来自 case |
| **CFD 求解设置** | 🔴 **未传进求解器** |
| 仿真代码生成 | ✅ 两边都是中性生成，无硬编码模板 |

最高危的一条是 CFD 的物理设置未落地，且**现有测试无法发现**——唯一成功的真实算例（D01）用的材料恰好等于 Fluent 默认材料。

---

## 1. 选面链路（结论：成立）

### 1.1 两个独立选面器

**A. `_structural_experiment/agent_solid_face_intent.py`**（OCC 直连）

工具集（`:40-72`）：`list_features` / `list_solids` / `query_solid_faces` / `inspect_solid_faces` / `submit_selection` / `needs_input`

`query_solid_faces`（`:103-154`）支持通用几何过滤：面类型、面积、柱坐标 r/θ/z、三个柱坐标法向分量。**无任何预置面清单**。

**B. `_structural_experiment/face_evolution/agent_evolution_face_intent.py`**（持久角色）

工具集（`:50-59`）：`get_summary` / `search_final_faces` / `search_selection_candidates` / `search_face_roles` / `roles_for_face` / `trace_role` / `submit_selection` / `needs_input`

分页检索 SQLite 角色索引 + 血缘追踪，明确禁止拉全量角色列表。

### 1.2 但 agent 自主性小于文档表述

在选面器 B 中，**对称配对由 harness 确定性构造**（`_selection_candidates` `:132-238`），LLM 的决策被压缩为：从闭合候选清单里挑"径向法向为负"的那一组。

且"负径向 = 工作齿面"这一物理约定**写死在 prompt 中**（`:566-568`），不是 agent 发现的。

这与 CAD 侧"参数化规则可见、答案不可见"的哲学一致，可以接受，但 `_structural_experiment/README.md` 中「Agent 自主输出承力面角色集合及选择理由」的表述需要下调。

---

## 2. CFD 侧发现

### 🔴 CFD-1 — spec 的物理设置根本没有进 Fluent

**证据**：`fluent_worker.py` 中所有 Fluent TUI 斜杠命令的**全集**只有 10 条：

```
/define/boundary-conditions/set/pressure-outlet
/define/boundary-conditions/set/velocity-inlet
/define/boundary-conditions/zone-type
/exit
/mesh/check
/mesh/quality
/mesh/repair-improve/improve-quality
/report/fluxes/mass-flow
/report/surface-integrals/area-weighted-avg
/solve/initialize/initialize-flow
/solve/iterate
```

**没有 `/define/materials`、没有 `/define/models`、没有 `/define/operating-conditions`、没有 `/solve/set`。**

在 worker 中搜索 `material_spec` / `spatial_order` / `relaxation` / `inflation_layers` / `length_unit`——**五个字段一次都没有出现**（不是"读了没用"，是从未引用）。

三个 fixture 都声明了会被忽略的量：

```json
"spatial_order": 2,        // 被忽略 → Fluent 默认一阶迎风
"relaxation": 0.5,         // 被忽略
"material_spec": air 1.225 kg/m3, constant_density   // 被忽略
```

> **更正（2026-09-11 修复时发现）**：本审计初稿称 turbulence / heat_transfer /
> compressible / rotation「全部静默忽略」，**这是错的**。`_check_implemented`
> （`fluent_worker.py:186-206`）早已把这几项 fail-closed 掉——非 steady、非
> laminar、非 isothermal、可压、有转速的 spec 一律抛 `capability_gap`。
> 真正未被 gate 的只有下面这几项：
>
> | 字段 | D01 声明 | 是否被应用 | 修复前是否 gate |
> |---|---|---|---|
> | `solver_control.spatial_order` | 2 | 否 | ❌ |
> | `solver_control.algorithm` | simple | 否 | ❌ |
> | `solver_control.relaxation` | 0.5 | 否 | ❌ |
> | `material_spec[0]` | air 1.225 / 1.7894e-5 | 否 | ❌（恰好等于 Fluent 默认，所以看不出） |
> | `physics_spec.gravity_m_s2` | [0,0,0] | 否 | ❌ |
> | `physics_spec.rotation_model` | none | 否 | ❌（只 gate 了 `rotation_rad_s`） |
> | `mesh_strategy.inflation_layers` | 0 | 不适用 | ❌ |
> | `physics_spec.reference_pressure_pa` | 101325 | 仅后处理使用 | ❌（恰好等于 Fluent 默认） |

**为什么现有测试发现不了**：D01 用的材料是 `air @ 1.225 kg/m³ / 1.7894e-5 Pa·s`——**正好等于 Fluent 自带默认材料**。所以"材料被应用"与"材料被忽略"跑出来完全一致。换成水会静默按空气算。

**没有任何门能发现**：`check_domain` / `check_mesh` / `check_results` 都不比对求解器侧的材料/模型状态。

**定位**：`_cfd_experiment/local/fluent_worker.py` 的 `_boundary_journal_lines`（当时唯一写 TUI 配置处）

> **重要更正（2026-09-11 实测后）**：本审计初稿称「Fluent 默认一阶迎风」——**这是错的**。
> 实测 TUI 提示符为 `Convective discretization scheme for Momentum (0 1 2 4 6) [1]`，
> 默认值是 **1**，而 Fluent 的动量默认格式是**二阶迎风**。因此 D01 的
> `spatial_order: 2` 实际上**被默认值满足了**，这一项并无偏差。
> 真正存在偏差的是 `relaxation`（spec 0.5，Fluent 默认按方程取值）与 `algorithm`。
> 教训：审计里关于「默认值是多少」的断言必须实测，不能凭印象。

**连带**：`_parse_area_average` 把 `reference_pressure_pa` 加上去并声称单位是 absolute Pa，但工作压力仍是 Fluent 默认值。

### 🔴 CFD-2 — `reduce_relaxation` 是空操作

`agents.py:237-238` 只改 `solver_control.relaxation`，而 worker 从不消费该字段（见 CFD-1）。因此 solver 阶段的"修复"重跑与失败那次**逐字节相同**——失败闭环对发散/停滞注定无效。

`integrations/cfd/README.md:215` 声称该动作"不改变物理模型/收敛标准/迭代预算"，spec 层面成立，但语义实际落空。

### 🔴 CFD-3 — 不检测 Fluent TUI 错误

`_run_process`（`:87-106`）只看退出码；`_read_log`（`:125-136`）只返回文本，**无任何调用者扫描 `Error:`**。

Fluent 批处理模式下 TUI 命令失败**仍返回 0 并继续**。因此错误的边界条件、读 case 失败都可能静默通过 `physics.configure`（`:1061-1068` 只检查 case 文件存在），只在最终数值上体现。

### 🟠 CFD-4 — `length_unit` 从未被使用

`_scale_mm_to_m`（`:229-251`）被**无条件**应用（实体 `:516`、selection BREP 面 `:354`），而 `GeometryRef.length_unit` 允许 `"m"`（`models.py:52`）。声明 `"m"` 时实体被缩小 1000 倍，内含检查（`:531-540`）仍通过，`volume_m3` 无交叉校验。

（现状：三个 fixture 均未设 `length_unit`，走默认值，所以未触发。）

### 🟠 CFD-5 — `inflation_layers` / `first_layer_m` / `growth_rate` 静默丢弃

worker 中零出现，`_check_implemented`（`:172-178`）只 gate `method == "tetra"`，**不报 `capability_gap`**。调用方无法知道自己声明的边界层被忽略。

### 🟠 CFD-6 — 残差列映射假设依赖 dict 顺序

前 4 列硬编码 continuity/x/y/z（`:1237-1242`），额外列名取自 `list(criteria.residuals)[4:]`（`:1229`、`:1243-1244`）。而 schema 只要求这 4 个 key **存在**、不要求排在前（`models.py:256-265`）。

残差 dict 顺序不同 → 数值被静默贴错标签，且收敛门会拿错数字判定。

### 🟠 CFD-7 — 两个门被硬编码零值架空

- `courant = 0.0`（`:1274`）恒过 `courant_ok`（`evidence.py:245`）
- `mass_source_kg_s` / `mass_storage_kg_s = 0.0`（`:1272-1273`）使质量守恒退化为"边界通量和 = 0"（`evidence.py:182-184`）

对稳态不可压是合理近似，但 `Sample` 专门留了这些字段（`evidence.py:65-66`），属未校验假设。

### 🟠 CFD-8 — 结果验收默认很弱

只有 `temperature <= 0` 和可选的 `expected_range` 会产生 warning（`evidence.py:337-343`）。作者不写 `expected_range` 时，物理上荒谬的数值也能得到 `status=success` 且 `requires_manual_review=False`（`orchestrator.py:621`）。

唯一的专家复核 warning 只在接入 experts 时存在（`:454-493`），而默认未接。

### 🟠 CFD-9 — 负体积检测是全日志子串匹配

`"negative" in text.lower()`（`:791`）→ 既可能误报也可能漏报。同时 `negative_volume_cells` **硬编码 0**（`:786`、`:982`），使 `check_mesh` 的该判据（`evidence.py:166`）在真实数据上永不触发。

### 🟠 CFD-10 — 收敛判定只用 3 样本窗口

`window`（默认 3，`models.py:251`）内的残差/质量/监视量达标即 `converged`（`evidence.py:226-265`），**无最小迭代数要求，也无"残差整体下降"要求**。`diverged` 检测同样只在窗口内（`:266-272`）。

### 🟡 CFD-11 — `origin_m` 只平移外域 box

`:542-550` 平移 box，但内含/间隙检查（`:521-540`）仍用未平移的 bounds → `origin_m != 0` 时间隙与 margin 判定错误。

### 🟡 CFD-12 — mesh `entity_ids` 跨进程未复核

`mesh.generate` 重建模型后重新派生 tag，却把上一个进程的 `boundary_map` 原样上报（`:973-989`，payload 来自 `:344-350`）。zone 按 physical group **名字**建立所以求解不受影响，但审计链里的 `gmsh-face:N` 可能不是实际被网格化的那些。`check_mesh` 只断言与拷贝来的 map 相等（`evidence.py:153`）。

### 🟡 CFD-13 — Windows supervisor 泄漏父进程环境变量

`process.py:87` 用 `os.environ.copy()`，与模块 docstring（`:4`）、Linux 路径的最小环境（`:247-252`）及对应测试（`tests/test_agents_process.py:105-121`，仅 Linux 生效）矛盾。**本仓库工作流里的 `DEEPSEEK_API_KEY` 会进入 Fluent 进程。**

### 🟡 CFD-14 — 输出预算与哈希策略

默认输出预算 `1e8` 字节（`models.py:289`）对真实三维 Fluent 算例偏小。且 `manifest()` 每次 checkpoint **全量递归哈希整个 job 目录**（`storage.py:144-157`，由 `orchestrator.py:101-105` 每次阶段切换调用）→ 大算例会在整轮跑完后以**不可恢复**的 `output_budget` 失败，且是 O(job size) 重复哈希。

### 🟡 CFD-15 — 可诊断性

非 `CFDError` 异常只记 `str(exc)`（`orchestrator.py:574-582`，无 traceback），包括 worker 输出导致的 pydantic `ValidationError`。`call()` 里对非 CFDError 也把 `diagnostic` 记为 None（`:182-184`）。

### 🟡 CFD-16 — 超时与返回值检查

`_run_process` 不传 `subprocess.run(timeout=...)`（`:91-97`），卡死只能靠外层 supervisor 整任务剩余时间 kill。`gmsh.write` / `gmsh.model.mesh.generate` 返回值未检查（`:895`、`:899`）。

### ⚪ CFD-17 — 前缀歧义

`zone-type <name>`（`:1003`）用 Fluent TUI 的唯一前缀匹配，而 `Name` 正则允许 `wall` 与 `wall_2` 并存 → 前缀歧义。

---

## 3. 结构侧发现

### 🔴 STRUCT-P1 — 确定性校验可被绕过

`agent_solid_face_intent.py:429-448` 第一阶段收到 `submit_selection` 时**只查下标越界**，不调用 `_validate_selected_faces`。该校验（平面性 / 径向符号一致 / 对称配对）只在第二阶段使用（`:536`）。

配合 `:466-471` 的 `if selection_ready: break`，**这三项校验可能完全不执行**。且第一阶段提交**不受任何候选集约束**——模型可提交实体上任意面索引。

对比：选面器 B 的 `submit_selection` 强制走 `_validate_selection`（`:397`）且限定在闭合候选表内。**B 是对的，A 有漏洞。**

测试覆盖：`_structural_experiment/tests/` 仅 5 个用例，该路径**零覆盖**。

### 🔴 STRUCT-P2 — 法向从未做朝向修正（系统性）

`role_facts.py:98-113` 用 `surface.D1(u,v)` 叉乘得法向，**从不调用 `face.Orientation()` 做 `TopAbs_REVERSED` 修正**。全目录 `grep Orientation` 无任何结果。

该法向喂给三处：

1. `query_solid_faces` 的法向过滤
2. `_validate_selected_faces` / `_validate_selection` 的"径向符号必须一致"
3. **SQLite 索引本身**（`build_canonical_faces.py:86-87` 直接存 `face_facts` 的 `normal_cylindrical`）

**后果**：`D1` 叉乘的符号取决于曲面参数化方向，与面的实际朝外方向无关。"负径向 = 工作齿面"依赖一个符号未定义的量。

D19 能通过是因为同一次布尔操作产出的面参数化恰好一致；**换模型或换操作不保证**。

另：法向取在 UV 中点的参数值（`:93-94`），对平面精确；对圆柱/圆锥/样条面只是中点法向，不代表整个面。

### 🟠 STRUCT-P3 — `edge_count` 恒为 0

`role_facts.py:125` `edge_count = 0`，从未计算，`:136` 原样返回。

`docs/自动结构仿真-Agent实施方案.md` 的 W1 明确把"边数"列为交付的几何事实——**未实现**，agent 收到恒定假值。

### 🟠 STRUCT-P4 — 重叠节点被静默覆盖

`map_solid_faces.py:107` 统计 `overlap_node_count` 但**不拒绝**。而 `structural_apdl.py:122` 是 `vectors[node_id] = vector`——**后写覆盖，不是累加**。

若一个节点同属两个面：两个面的面积都计入 `total_area`（都分到力），但该节点只拿到后一个面的力 → **力丢失且无任何告警**。

D19 恰好零重叠所以未暴露——README 的"零重叠"是**观测值，不是保证**。

### 🟠 STRUCT-P5 — 面映射到 0 节点直接崩溃

`structural_apdl.py:106-107`：`node_force = face_force / len(node_ids)`。

某选中面在网格上无匹配节点 → `ZeroDivisionError`，报错信息完全不知所云。

### 🟡 STRUCT-P6 — `weighted_center_mm` 恒为 `[0,0,0]`

`agent_structural_intent.py:61` 初始化后从未赋值，`:85` 返回。**喂给 agent 的几何事实是假的。**

### 🟡 STRUCT-P7 — 温度场只支持两种解析模型

`structural_apdl.py:62` 的 `node_profile_file` 分支直接 `raise`。README 所称 "an Agent-specified nodal temperature field" 名不副实——实际只有 `isothermal` 与 `radial_power_law`。

### 🟡 STRUCT-P8 — 载荷方向是纯径向，非齿面法向

`structural_apdl.py:118-121`：方向 = 节点到轴的径向单位向量。

真实的榫槽承力沿齿面法向（含摩擦）。**合力因此正确**（对称齿面切向分量抵消，且 `:137-141` 显式缩放使合力精确等于目标值），但**局部齿面应力分布不真实**——报告中的"选面最大应力 142.055 MPa"受此影响。

README 只声明了"不是接触非线性分析"，未点明方向简化。

### 🟡 STRUCT-P9 — `resultant_relative_error` 是自证指标

`structural_apdl.py:137-141` 显式缩放全部节点力使合力精确等于 `total_force`。因此 1.13e-14 验证的是缩放算术，**不是载荷分配的正确性**。作为验证证据偏弱。

### 🟡 STRUCT-P10 — `run_structural.py` 成功判定不完整

metrics 只在 `nodal_stress_3d.csv` 存在时计算（`:131`），但退出码只看 `run["has_error"]`（`:162`）。**求解器返回 0 但未产出 CSV 会记 `metrics: null` 并退出 0。**

---

## 4. 做得好的部分

避免误判，以下设计是扎实的：

**CFD 侧**
- `apply_repair`（`agents.py:231-241`）**白名单式硬编码**：只有到 `global_size_m` / `size_m` / `relaxation` 的写入代码，根本无法改物理模型/几何/BC/阈值/预算。加 `SimulationSpec.model_validate` 二次把关
- `expert_confirmed` 被**无条件强制置回 `false`**（`agents.py:159`），且有独立门（`orchestrator.py:217-222`）
- `allowed_repairs` 默认 `[]`（`models.py:304-306`）——fail-closed
- `confined()` 路径逃逸防护（`storage.py:28-37`，含 `..` / `\` / `:` / 绝对路径）
- `in_flight` 崩溃后拒绝盲目重试（`orchestrator.py:210-216`）
- `resume` 校验 spec_hash + 后端能力（`:62-69`）
- events.jsonl 哈希链（`storage.py:116-142`）
- **选面转移真拒绝多候选/零候选**，全仓 `grep nearest|fallback|closest` 无实现——**没有最近面回退**
- `mesh_independence.verified=False` 硬编码，不吹牛（`orchestrator.py:622-625`）

**结构侧**
- `_validate_against_case`（`agent_structural_intent.py:109-183`）：每个物理量与 case 文件逐项比对（`abs_tol` 1e-9 / 1e-12）——**agent 无法编造数值**
- `_expected_status`（`:186-192`）**双向强制**：case 不全时必须 `needs_input`，case 完整时禁止 `needs_input`
- `created_at_utc` 由 harness 覆写（`:264`）
- `render_apdl`（`structural_apdl.py:255`）是**真正中性的物化器**，无 D19/榫槽模板
- `run_structural.py` 的 `needs_input` / `ready_for_confirmation` 门控到位，`scientific_status` 标注正确
- `_clean_ansys_outputs` **先删旧产物**，防陈旧 CSV 被误当新结果
- 单位系统一致（mm-N-t-s：密度 t/mm³、应力 MPa）

---

## 5. 修复计划（依赖 + 重要性排序）

依赖关系：

```
F1 法向朝向修正（数据地基）
   └─> 下游一切法向判据；需重建索引与复验 D19

F2 选面器 A 校验绕过（逻辑门）
   └─> 与 F1 同属选面正确性，F1 先行使 F2 的门作用于正确数据

F3 映射层：重叠节点 + 零节点（同一函数的两个问题，一次改完）

F4 几何事实补齐（edge_count / weighted_center）——无依赖、零风险

C1 CFD 物理设置落地（最高危）
   └─> C2 relaxation 修复才有意义

C2 CFD TUI 错误检测
C3 CFD 能力缺口上报（inflation 等）
```

### 批次 1 — 无依赖、零风险、可本地验证
- **F4** `edge_count` 补齐、`weighted_center_mm` 修正
- **F3** 重叠节点改为累加 + 零节点显式报错
- **F2** 第一阶段 `submit_selection` 强制走 `_validate_selected_faces`

### 批次 2 — 数据地基（需复验）
- **F1** `face_facts` 增加 `TopAbs_REVERSED` 朝向修正；重建 D19 索引；复验 8 个持久角色仍解出同一组面

### 批次 3 — CFD（最高危，但本地无 Fluent 许可，只能做静态验证）
- **C1** worker 增加 material / models / operating-conditions / solve-set 的 TUI 配置；缺少实现时抛 `capability_gap` 而非静默忽略
- **C2** 扫描 Fluent 日志中的 `Error:`，失败即抛
- **C3** `inflation_layers` 等未实现字段上报 `capability_gap`

### 批次 4 — 收敛与验收强度
- **CFD-6** 残差列按名字映射而非位置
- **CFD-7** 移除硬编码零值门或显式标注为未校验假设
- **CFD-8** 结果验收增加必填的物理合理性区间
- **CFD-9** 负体积改为解析 Fluent 实际输出
- **STRUCT-P8/P9** 载荷方向与自证指标的文档化/改进

---

## 6. 修复记录

### 批次 1（2026-09-11 完成）

| 编号 | 修复 | 位置 |
|---|---|---|
| **F4a** | `edge_count` 由恒为 0 改为用 `TopExp.MapShapes_s` + `TopTools_IndexedMapOfShape` 真实计数（去重接缝边） | `role_facts.py` `face_facts` |
| **F4b** | `weighted_center_mm` 由恒为 `[0,0,0]` 改为面积加权质心；无质心数据时返回 `null` 而非假值。源头 `map_solid_faces.py` 增加 `centroid_mm` | `agent_structural_intent.py:_load_face_summary` |
| **F3a** | 选中面映射到 0 节点时抛明确错误，不再 `ZeroDivisionError` | `structural_apdl.py:_build_force_rows` |
| **F3b** | 共享节点由后写覆盖改为**累加**，不再静默丢力 | 同上 |
| **F2** | 选面器 A 第一阶段 `submit_selection` 强制走 `_validate_selected_faces`，并补齐 `selection_validation` / `identity_status` 字段 | `agent_solid_face_intent.py` |
| **F1** | `face_facts` 增加 `TopAbs_REVERSED` 朝向修正 | `role_facts.py:face_facts` |

**F1 是本次最有价值的修复**，且被新测试直接复现证实。修复前一个居中盒子的六个面中，
位于负坐标的三个面（`Orientation() == TopAbs_REVERSED`）报告的都是**朝内**法向：

```text
idx  orientation        normal_xyz
0    TopAbs_REVERSED    [1.0, 0.0, -0.0]   ← 位于 x=-5，法向却指向 +X
1    TopAbs_FORWARD     [1.0, 0.0, -0.0]   ← 位于 x=+5，正确
```

叉乘法向完全不看 `face.Orientation()`。这意味着修复前 SQLite 索引里约一半面的
`normal_cylindrical` 符号是错的，而「负径向 = 工作齿面」这一 prompt 约定正建立在其上。
D19 之所以仍能选出物理合理的面，是因为同一次布尔操作产出的面参数化恰好一致，
使**成对检查**在整体符号翻转下仍自洽——但这不保证换模型后依然成立。

**⚠️ 后续动作**：F1 改变了法向语义，`_structural_experiment/work/D19_face_evolution_v1.sqlite`
等既有索引与选择结果需要用新代码**重建并复验**，不能直接复用。

**测试**：`_structural_experiment` 由 5 个用例增至 14 个（新增朝向回归、零节点、
重叠累加、加权质心、校验接受/拒绝路径）。全部通过。

### 批次 2（2026-09-11 完成）

| 编号 | 修复 | 位置 |
|---|---|---|
| **C1** | 新增 `_check_spec_physics_applied`，对 worker 不会应用的 spec 字段一律抛 `capability_gap`：`spatial_order`、`algorithm`、`reference_pressure_pa`、`rotation_model`、`gravity_m_s2`、`inflation_layers`、非默认 `material_spec` | `fluent_worker.py` |
| **C1b** | 未应用但无法 gate 的字段（`relaxation`、`reference_temperature_k`）在 `physics.configure` 响应中显式列出 `unapplied_spec_fields` 披露 | 同上 |
| **C2** | 新增 `_fail_on_fluent_errors`，在所有 `_run_fluent` 调用后扫描日志中的 `Error` / `*** ERROR` 并抛错 | 同上 |
| **C3** | `inflation_layers` 的能力缺口上报已并入 C1 | 同上 |

**⚠️ 行为变更**：`_cfd_experiment/dev/specs/` 下的 D01/D05 fixture 声明了
`spatial_order: 2`，修复后会**立即被拒绝**。这是刻意为之——它们此前跑的是
一阶迎风，而 spec 声称二阶。需要先由有 Fluent 许可的人在 worker 中实现
离散格式/松弛/材料的 TUI 配置，再把这些 spec 重新启用。

**C1 的设计**：Fluent 默认值以命名常量显式声明
（`FLUENT_DEFAULT_SPATIAL_ORDER` 等），并在注释中标注「须对照真实 Fluent 核验」。
这不能保证常量本身正确，但把它从**不可见的假设**变成了**可评审的常量**——
比静默分歧好得多。

### 批次 4（2026-09-11 完成）：能力声明回到架构层

批次 3 把能力做出来了，但判定依据还在 worker 源码的常量里，且失败点在
`physics.configure`（域和网格都跑完才拒）。批次 4 把它移到正确的位置：

**`Capabilities` 新增字段**（`backends.py`）：

```python
spatial_orders: list[int]                       # 支持的离散阶数
pv_coupling_schemes: list[str]                  # 支持的耦合算法
under_relaxation: bool                          # 是否应用 solver_control.relaxation
materials: list[str]                            # 可配置的材料名；"*" 匹配任意
operating_pressure: bool
gravity: bool
inflation: bool
```

`Capabilities.check()` 增加对应比较，失败在 **preflight**（`orchestrator.py:223`）——
秒级、在建域划网格之前。默认值全部是 fail-closed 的：没声明 = 不支持。

**`fluent_local_config.json` 如实声明**：

```json
"spatial_orders": [1, 2],
"pv_coupling_schemes": ["simple", "simplec", "piso", "coupled"],
"under_relaxation": true,
"materials": ["air"],
"operating_pressure": true,
"gravity": true,
"inflation": false
```

`materials: ["air"]` 是诚实的：worker 只能配置 case 里**已存在**的材料，而新导入的
case 只有 `air`。要用别的材料必须先 `/define/materials/data-base copy`，那条路径未实现。

**验证**：

| 检查 | 结果 |
|---|---|
| worker 能力声明加载 | ✅ |
| D01 spec 通过 preflight | ✅（spatial_order=2 / simple / 0.5 / air 均已在声明内） |
| Mock spec 通过 preflight | ✅ |
| 非 `air` 材料 | ✅ 在 **preflight** 被拒 |
| `inflation_layers` | ✅ 在 **preflight** 被拒 |
| Mock 端到端 | ✅ 退出码 0 |

**分工现在清楚了**：
`Capabilities` 声明**能不能设**（由部署配置决定）→ preflight 拦截；
worker 的 journal 生成器负责**怎么设**；
`_fail_on_fluent_errors` 兜住**设失败了**（版本漂移、向导错位）。
三层各司其职，不再有静默分歧的缝隙。

**仍为缺口**（均已 fail-closed，不会静默）：
旋转参考系、边界层网格、温度相关属性表、`air` 以外的材料（需 data-base copy）。

---

### 批次 3（2026-09-11 完成）：CFD 参数真正写入 Fluent

**关键发现**：本机装有 Fluent 18.1（`D:/ANSYS181/...`），可以用 **TUI help 机制直接问 Fluent**，
不必猜测语法。进入菜单后依次发送 `?` → `help` 即可列出该菜单全部命令（顶层有效；
`/solve/set` 的 help 会让 Fluent 18.1 段错误，只能逐命令试探）。

**逐条实测确认的语法**（全部在 `tiny_fluent_native.msh` 上真实执行）：

| 设置 | 命令 | 形式 | 实测证据 |
|---|---|---|---|
| 工作压力 | `/define/operating-conditions/operating-pressure <Pa>` | 单参数 | 回显无错误 |
| 重力 | `/define/operating-conditions/gravity` | 4 个向导答案 | `enable gravitational forces? [no]` |
| 能量方程 | `/define/models/energy` | 5 个向导答案 | `Enable energy model? [no]` |
| 材料密度+粘度 | `/define/materials/change-create` | **15 个位置参数** | 见下方向导序列 |
| 动量离散 | `/solve/set/discretization-scheme/mom <n>` | 单参数 | 提示符 `(0 1 2 4 6) [1]` |
| 松弛因子 | `/solve/set/under-relaxation/<方程> <值>` | 单参数 | 回显无错误 |
| 耦合算法 | `/solve/set/p-v-coupling` | 1 个编号 | 提示符 `[20]` |

材料向导的真实序列（一次运行的回显完整暴露）：

```
/define/materials/change-create
<材料名> / yes / yes / constant / <密度> / no / no / yes / constant / <粘度> / no / no / no / yes
```

**回读验证手段**：`(rpgetvar 'mom/scheme)` 可直接读出数值——默认 1、设为 0 读回 0、设为 1 读回 1。

**实现**（`fluent_worker.py`）：

- 新增 `_material_journal_lines` / `_operating_conditions_journal_lines` /
  `_model_journal_lines` / `_solver_setting_journal_lines` / `_readback_journal_lines`
- 全部接进 `_physics_configure`，配置后追加回读表达式，再写 case
- 每条序列上方**逐字引用 Fluent 打印的原始提示文本**，便于版本升级时定位
- `_check_spec_physics_applied` 相应收缩：只保留仍未实现的 `rotation_model` 与 `inflation_layers`
- 温度相关属性表 / 热导率 / 比热仍抛 `capability_gap`（需要 piecewise-linear 编辑器，未验证）

**扩展 `_fail_on_fluent_errors`**（这是向导式命令能否安全使用的前提）。
实测发现 Fluent 有**四种**非 `Error` 开头的失败信号，初版扫描器全部漏掉：

```
invalid command [x]                  ← 向导错位
Please answer y[es] or n[o].         ← 向导答案类型不符
The requested scheme is unavailable  ← 枚举值非法
Invalid choice.                      ← 编号越界
```

外加 `*** ERROR ***`（大写，初版的 `Error` 匹配不到）。现已全部覆盖并验证 6/6。

**端到端验证**：用 D01 真实 spec 生成完整 journal 并在 Fluent 上执行——
工作压力 101325、材料 air 1.225/1.7894e-05、耦合 20 全部写入，
`(rpgetvar 'mom/scheme)` 回读为 1，`case-configured.cas.gz` 正常生成，无任何错误标记。

**测试状态**：`integrations/cfd/tests` 47 passed / 6 skipped / 1 failed。
该 failure（`test_local_worker_rpc_without_solver`）是**既有环境问题**：
测试 spawn 的是 `integrations/cfd/examples/ansys_worker.py`（本次未改动），
用系统 `D:\anaconda\python.exe` 运行，而 `seekflow-cfd` 未为该解释器安装
（`pip show seekflow-cfd` 为空）。直接运行该文件即可复现同样的
`ModuleNotFoundError`，与本次修复无关。

---

## 7. 复现命令

```bash
cd e:/text_to_cad_improve/auto_detection_process

# CFD 侧：确认 TUI 命令全集（应只有 10 条）
grep -n '"/' _cfd_experiment/local/fluent_worker.py | grep -o '"/[a-z/-]*' | sort -u

# CFD 侧：确认物理字段从未被引用（应无输出）
grep -n "material_spec\|spatial_order\|relaxation\|inflation_layers\|length_unit" \
    _cfd_experiment/local/fluent_worker.py

# 结构侧：确认无朝向修正（应无输出）
grep -rn "Orientation\|TopAbs_REVERSED\|TopAbs_FORWARD" _structural_experiment/*.py

# 结构侧测试
.conda/python.exe -m pytest _structural_experiment/tests -q
.conda/python.exe -m pytest _structural_experiment/face_evolution/tests -q

# CFD 测试（Mock，不需要许可）
.conda/python.exe -m pytest integrations/cfd/tests -q
```
