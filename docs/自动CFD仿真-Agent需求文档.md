# Agent 驱动的自动 CFD 仿真：需求文档

> 文档状态：待专家评审  
> 编制日期：2026-09-09  
> 交付对象：负责“生成后自动 CFD 仿真”的实现专家  
> 本文不承诺具体的 CFD 物理方案已定稿，而是把“应做什么、凭什么能做、如何验收、哪些决策必须由专家/领域人员确认”写清楚。

---

## 1. 项目背景与现状

当前系统已基本完成“自然语言 → 涡轮盘参数化 CAD 模型”的生成侧闭环：

1. 多智能体把自然语言需求转换为结构化 CAD 建模规范，包含 FDG 与操作节点；
2. CAD 建模规范经校验、规范化、编译后由确定性 CAD 执行引擎生成 B-rep/STEP；
3. MCP 工程验证工具对实体、关键尺寸、榫槽、STEP 回读等进行质量检查；
4. 生成过程具有完整 trace、修复日志、record_id、时间戳和几何报告，支持实验级复现；
5. 已完成持久化拓扑命名（OCAF/TNaming + tracked ops + face/edge role + PersistentSelectionService），使跨 revision 的“同一功能面/边”可以稳定引用。

下一步目标：在同一个“工程智能体”体系内，把上述 CAD 输出自动推进到 CFD 仿真，形成：

```text
自然语言需求
  → CAD 模型（已有）
  → 拓扑身份抽取（已有基础）
  → CFD 问题解释
  → 计算域/网格/物理/边界条件/求解/收敛/后处理（待实现）
  → 可审计仿真报告
```

## 2. 目标

实现一个 Agent 驱动的自动 CFD 仿真系统，满足：

1. **自动完成典型流场/热流仿真工作流**，在专家确认任务语义后无需人工编写网格、求解或后处理脚本；
2. **Agent 负责意图与决策**，通用工具负责确定性执行；系统不得依赖隐藏的“零件专用 CFD 模板”替代建模决策；
3. **拓扑命名成为 CAD 与 CFD 的稳定桥**：仿真中的面/边/域归属不使用几何索引或启发式猜面；
4. **每一轮仿真可追溯**：保存 CAD revision、仿真 spec、网格参数、工具调用、求解器日志、收敛证据与结果指标；
5. **不回归现有 CAD 主流程**，自动 CFD 模块应与生成、修复、实验数据收集保持独立目录与独立配置。

## 3. 范围界定

### 3.1 输入

一次自动 CFD 任务至少包含：

- 一个由当前系统生成的涡轮盘/相关几何结果；
- 与该结果对应的持久化拓扑命名文件（若该 CAD revision 已开启拓扑捕获）；
- 自然语言仿真需求；
- 可选的显式仿真参数，例如：
  - 流体域类型；
  - 工质与温度/压力；
  - 转速或质量流量；
  - 壁面条件；
  - 计算域扇区；
  - 精度/算力约束。

### 3.2 输出

- 可执行的 CFD 项目目录；
- 网格与网格质量报告；
- 求解设置与求解器日志；
- 收敛/发散判定报告；
- 关键结果指标（如压降、温升、流量分配、壁面温度、热流、压力场峰值等）；
- 面向用户的图形/JSON 结果摘要；
- 带 record_id 的仿真记录，字段结构与现有实验记录一致；
- 若判定不可行、能力不足或硬约束冲突，应给出结构化拒绝原因，而不是修改输入参数硬跑。

### 3.3 初始建议场景

“自动 CFD”必须先落在有界、可验证的场景上。建议首批覆盖以下任一类：

1. 旋转盘/盘腔流动或共轭传热简化模型；
2. 涡轮盘榫槽/冷却孔/环槽周围冷却流道模型；
3. 简化的盘腔转子-静子间隙流动；
4. 由专家定义的轴对称/周期性外部流动验证算例。

> 待专家确认：最终首期 CFD 物理场景、商用/开源求解器选择与算力预算。

## 4. 核心架构要求

### 4.1 总体分层

```text
User / API
  └─ CFD Orchestrator Agent
       ├─ Geometry & Topology Agent
       ├─ Domain & Mesh Agent
       ├─ Physics & Boundary Agent
       ├─ Solver & Monitor Agent
       └─ Verification & Report Agent

Deterministic Tool Layer
  ├─ topology query tools
  ├─ geometry/domain/mesh tools
  ├─ physics/BC/setup tools
  ├─ solver run/monitor tools
  └─ verification/post-processing tools
```

设计原则：

- **Agent 不直接编写任意后端脚本**，只输出结构化意图/计划/参数；
- 确定性工具层拥有唯一的几何、网格、求解、后处理执行权限；
- 工具应是通用能力，而不是“盘体专用”或“榫槽专用”黑盒；
- 多智能体之间的信息通过规范化的“仿真中间表示”传递；
- 失败时产生结构化诊断，进入修复闭环，修复不能伪造收敛或结果。

### 4.2 仿真中间表示

建议定义类似 CAD 建模规范的声明式 `CFD Simulation Spec`：

```text
SimulationSpec
├─ geometry_ref          # CAD artifact + topology naming file + revision hash
├─ domain_strategy       # full/sector/extract/outer domain
├─ mesh_strategy         # method, size fields, inflation, periodic mapping
├─ physics_spec          # steady/unsteady, turbulence model, heat transfer, species...
├─ material_spec
├─ boundary_specs[]      # each references topology role or named surface
├─ solver_control        # scheme, discretization, relaxation, limits, iterations
├─ convergence_criteria
├─ result_requests
└─ traceability          # agent plan, tool calls, timestamps
```

该 spec 必须可序列化、可哈希、可版本化，并作为求解前后的唯一事实来源。

## 5. 持久化拓扑命名与 CFD 桥接

### 5.1 现状可复用

- OCAF/TNaming 持久化；
- tracked ops 已覆盖 revolve、extrude、fillet、chamfer、boolean、pattern、unify、mirror 等；
- face/edge role 与稳定 label index；
- PersistentSelectionService；
- CAE proof gate / preflight 已存在雏形。

### 5.2 CFD 需要的拓扑能力

CFD 专家必须在实现前明确以下拓扑接口：

1. 从 CAD revision 中导出“功能面命名 → 当前 B-rep face id”的稳定映射；
2. 对扇区切割后新生成的面，能与原面/原始边界自动分类（周期面、对称面、壁面）；
3. 当参数变化导致面分裂/合并/删除时，CFD 边界条件能自动映射到正确的新 face；
4. 面选择结果应进入 `mesh_report` 和 solver 的 BC label，而不是依赖 CAD 内核导出的临时索引；
5. 当拓扑解析为 AMBIGUOUS/UNRESOLVED 时，应停止自动求解并结构化报告，不得静默选择最近面。

### 5.3 建议接口示例

```text
list_topology_roles(cad_artifact)
resolve_role_to_faces(cad_artifact, role_key)
export_topology_face_map(cad_artifact) -> JSON
check_role_binding_stable(revision_a, revision_b, role_key)
```

专家应把这些能力以 MCP tool 形式暴露，供 Geometry & Topology Agent 调用。

## 6. Agent 功能需求

### 6.1 CFD Orchestrator

- 解析仿真需求并生成完整任务计划；
- 判断是否缺少硬参数、是否存在硬约束冲突；
- 调用子 Agent；
- 管理 Agent/工具调用预算；
- 汇总结果并决定继续、修复、给用户询问建议或终止。

### 6.2 Geometry & Topology Agent

- 导入 STEP/B-rep 与拓扑命名文件；
- 查询功能面/边；
- 构建/切割流体域或扇区；
- 确认拓扑绑定与网格边界来源；
- 在 CAD 参数变化后，负责把既有 BC 映射到新 revision。

### 6.3 Domain & Mesh Agent

- 选择计算域范围；
- 定义远场/入口/出口/对称面；
- 选择网格工具与尺寸场；
- 对复杂圆角/榫槽/冷却孔施加局部加密；
- 校验网格单元质量、周期节点匹配、最小体积与负体积；
- 不得在网格不合格时进入求解。

### 6.4 Physics & Boundary Agent

- 从自然语言中提取流体/热模型；
- 选择工质、材料、温度相关属性；
- 解释壁面/入口/出口/周期/对称条件；
- 生成可校验的物理模型清单；
- 对不确定或互斥条件进行结构化拒绝。

### 6.5 Solver & Monitor Agent

- 提交求解；
- 监控残差、质量守恒、热流守恒、库朗数/时间步；
- 判定收敛、发散或卡死；
- 在算力预算内决定继续或终止；
- 返回求解器日志摘要和结构化诊断。

### 6.6 Verification & Report Agent

- 检查网格无关性/守恒/边界量；
- 检查结果量级合理性；
- 生成结果摘要、图表数据和完整仿真记录；
- 对任何“看起来成功但物理上可疑”的结果标出人工复核建议。

## 7. 确定性工具层需求

### 7.1 工具注册与通用性

工具应像 CAD 系统中“草图、拉伸、阵列、布尔”一样是**通用算子**，例如：

| 类别 | 工具示例 |
| --- | --- |
| 几何 | import STEP/B-rep、query faces、cut domain、extract fluid、merge/split bodies |
| 拓扑 | list roles、resolve role→face、export face map、compare revisions |
| 网格 | build surface mesh、build volume mesh、inflation、periodic coupling、quality report |
| 物理 | create material、create fluid、create turbulence model、add boundary condition |
| 求解 | initialize、run steady/unsteady、get residuals、write case/data、stop |
| 后处理 | extract surface field、compute mass/energy balance、export CSV/JSON/plot |

这些工具不得被 Agent 当作“照抄盘体专用流程”的黑盒；Agent 必须基于任务描述自行选择与组合。

### 7.2 工具调用记录

每次工具调用应记录：

- tool name / version / input hash / output hash；
- 调用者 Agent；
- 开始/结束时间与耗时；
- 返回状态与结构化错误；
- 与 CFD Spec 的节点映射。

## 8. 自动修复与安全约束

### 8.1 内环修复

- 拓扑面解析失败 → 仅修复选择/依赖，不改几何；
- 网格质量失败 → 调整局部尺寸/方法，不静默跳过坏单元；
- 求解发散 → 调整数值控制/网格/物理模型，不允许通过“隐藏残差”标成功；
- 多次修复仍失败 → 明确 give_up 并保留证据。

### 8.2 硬约束与不可行处理

- 几何上不存在入口/出口/流体域时，应结构化拒绝；
- 拓扑角色解析为歧义时，不得猜测；
- 材料/物理模型超出当前后端支持时，应返回“能力不足”；
- 任何 Agent 都不能修改用户硬约束来换取可运行结果。

### 8.3 算力与外部进程边界

- 必须有任务级求解超时、迭代上限、内存/CPU 配额；
- 必须有文件/命令白名单和输出边界；
- 求解器运行必须放在独立 job 目录；
- 支持断点续跑与任务重放。

## 9. 数据记录与可审计性

自动 CFD 的每条记录应具备与现有实验数据相同的完整性要求：

```json
{
  "record_id": "...",
  "schema_version": "cfd_sim_v1",
  "collected_at": "...",
  "cad_revision_id": "...",
  "simulation_spec_hash": "...",
  "agent_trace": [],
  "tool_calls": [],
  "mesh_report": {},
  "solver_log_summary": {},
  "metrics": {},
  "status": "success | failed | rejected | timeout | capability_gap",
  "error_stage": null,
  "error_message": null
}
```

建议放在独立目录，例如：

```text
_cfd_experiment/
  output/
    jobs/
    records.json
    manifest.json
    report.md
```

## 10. 与现有系统的隔离要求

- 自动 CFD 实现应新建独立模块，不修改现有 CAD 生成主流程；
- 可以复用：
  - `agentic_l2.py` 的 Agent/工具调用协议；
  - 校验、自动修复与 repair 循环模式；
  - MCP 工具注册和调用记录；
  - OCAF/TNaming 拓扑接口；
  - `fea3d/` 中已实现的 Gmsh 扇区/周期网格和 ANSYS 运行经验；
  - `integrations/engineering_tools/src/seekflow_engineering_tools/ansys` 的 runner/解析器模式。
- 不应复用或修改已有 CAD 生成模板作为 CFD 计算核心；
- 若需要调用现有 FEA3D 作为对照算例，应通过独立 Adapter 调用。

## 11. 首期验收标准

建议专家按以下顺序交付并逐项验收：

1. **仿真 Spec 与 schema 测试**：能表达首期 CFD 任务并往返序列化；
2. **拓扑→CFD 边界桥 POC**：对一个含孔/榫槽/环槽的生成模型，自动导出功能面映射，并在一次参数扰动后保持正确；
3. **Mock 求解器流水线**：不消耗求解器许可即可验证整个 Agent/工具/记录流程；
4. **真实求解器单点通过**：在人工确认的算例上完成“域构造→网格→求解→收敛→后处理”；
5. **批量稳定性**：在不同设计族/难度上连续运行，给出成功率、失败分类和平均耗时；
6. **回归不破坏**：现有 CAD 主实验相关测试全部通过。

建议量化指标：

- 拓扑 BC 绑定错误率：0；
- 对合法任务，结构化 spec 可执行率：≥ 目标值，由专家与用户确认；
- 网格质量门通过后再进入求解：100%；
- 求解状态判定可追溯：100%；
- 同一 CAD revision + 同一 spec 重跑结果的确定性/近似一致性：在数值噪声范围内；
- 失败任务必须归入 structured rejection / timeout / capability gap，不允许无原因静默失败。

## 12. 建议实施工作包

| 阶段 | 内容 | 验收物 |
| --- | --- | --- |
| WP0 | 项目范围评审：选定首期 CFD 物理场景、求解器、算力与模型 | 范围决策记录 |
| WP1 | 定义 SimulationSpec、schema、任务和 mock registry | schema 测试、单元测试 |
| WP2 | Topology/Geometry Agent + 拓扑面导出与映射工具 | POC 用例 |
| WP3 | Domain/Mesh Agent + Gmsh/ANSYS 网格工具与质量门 | 网格报告 |
| WP4 | Physics/BC/Solver Agent + Fluent/CFX/OpenFOAM Adapter | 单点真实算例 |
| WP5 | Verification/Report Agent + 收敛与守恒检查 | 仿真记录/报告 |
| WP6 | 端到端批量实验与断点/重试/预算控制 | 实验报告 |

## 13. 专家实现前必须确认的问题

1. 首期 CFD 场景是外流、盘腔、冷却流道还是共轭传热？
2. 使用 ANSYS Fluent、CFX，还是 OpenFOAM/PyFluent 等作为目标后端？
3. 几何精度/网格规模/单任务求解预算的上限？
4. 是否需要调用真实商业许可；许可证是 Mechanical Enterprise 还是包含 Fluent/CFX？
5. 哪些输入参数必须人工确认，哪些允许 Agent 自动推断？
6. 是否采用扇区/周期域；周期边界由拓扑命名还是几何对称自动判定？
7. 与现有“参数扰动再生”的关系：CAD 参数修改后，仿真是否需要自动重跑？
8. 是否要求与论文中的主实验/辅助实验共用同一套 record schema 和统计口径？

## 14. 参考文件与代码入口

- CAD Agent 生成主流程：`app/text-to-cad/server/agentic_l2.py`
- MCP 工具/适配器模式：`integrations/engineering_tools/src/seekflow_engineering_tools`
- 持久化拓扑命名：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/ocaf/`
- 现有 FEA3D 原型：`app/text-to-cad/server/fea3d/`
- FEA3D 实现指导：`docs/涡轮盘三维有限元实现指导.md`
- ANSYS 工具封装：`integrations/engineering_tools/src/seekflow_engineering_tools/ansys/`

