# 面向航空发动机涡轮盘的证据闭环自动仿真与结构修复

**An Evidence-Closed Framework for Automated Simulation and Structural Repair of Aero-Engine Turbine Disks**

**中文初稿 v2｜目标期刊：Chinese Journal of Aeronautics（CJA）｜2026-09-25**

> 说明：本稿是第二版中文论文初稿，不是最终投稿稿。所有已写数字均来自当前内部实验产物；尚未完成或证据不足的实验均明确标记为“待补”，不填充推测数字。D19、D27 为 verified reference，其他多族实验中的 reference 不能统一称为 ground truth。

---

## 摘要

航空发动机涡轮盘的 CAD–FEA 设计迭代不仅要求自动完成建模与求解，还要求把应力结果可靠地转化为经过验证的结构修复。现有 LLM/CAE agent 已能生成求解输入、调用有限元软件、规划网格并读取结果，但其评价通常停留在流程完成率、脚本可执行性或单次应力变化，尚未充分闭合从仿真结果到真实设计修改之间的证据链。该链条包含三个关键断层：自然语言反馈可能无法映射到正确工程特征；CAD 文档参数变化不等于最终 STEP 实体发生变化；预测中的应力方向变化也不一定超过重网格噪声或不存在副作用。

本文面向航空发动机涡轮盘，提出一种证据闭环的自动仿真与结构修复框架。主贡献不是增加一个通用 CAE agent，而是把自动仿真的终点从“得到结果”推进到“可核验的设计修复”：反馈必须绑定真实应力证据和设计特征，修改必须进入最终实体，预测必须在下一轮独立求解中接受确认、判伪或噪声底判定。围绕该主贡献，设置三个从属支撑点：特征级 CAD 参数依赖图与联合修复、求解前真实实体效果门，以及可判伪反馈—修复协议与工程经验记忆。

在当前内部实验基准中，选面流程在 11 个设计族、51 次运行上达到 51/51 精确匹配，错误接受为 0，95% Wilson 置信区间为 [0.930, 1.000]；特征依赖图覆盖 32 个设计族中的镜像、圆角、阵列、轮廓和特征包关系。D27 实体效果门确认 60→63 mm 修改使目标区域最小半径由 59.856454 mm 变为 62.818937 mm，并引起 5346 个边界单元变化。闭环预测结果为 confirmed 2、refuted 4、unmoved 1；其中 D27 成对实验的峰值变化为 −1.2228%，低于 3.8119% 的网格噪声底，因此被保守判为 unmoved；D19 两次开孔降压预测被真实求解判伪，并出现载荷面应力升高副作用。结果表明，所提框架的价值不在于保证每次设计修改都成功，而在于能够拒绝不可信修改、保留反例，并把真实物理结果转化为可积累的工程经验。

**关键词：** 航空发动机涡轮盘；CAD–FEA 闭环；智能体；自动仿真；反馈与修复；可判伪性；工程经验学习

---

## 1. 引言

### 1.1 工程背景

涡轮盘是航空发动机中承受离心载荷、气动载荷和热载荷的关键转动部件。其结构设计必须在质量、轮缘承载能力、轮毂孔径、盘体截面、孔阵列和局部圆角之间取得平衡。有限元分析是涡轮盘设计与校核的核心工具，但一次有意义的 CAD–FEA 迭代并不只是“生成模型并求解”。工程师需要回答一系列相互耦合的问题：峰值应力位于哪个真实几何区域；该峰值由膜应力、弯曲应力、应力集中、热梯度还是模型理想化边缘引起；哪些参数可以在不破坏其他设计意图的前提下修改；修改后的最终实体是否真的改变；下一轮求解的变化是否超过网格重划分带来的误差。

在传统工作流中，这些问题主要由工程师依据经验和多轮试算回答。随着参数化 CAD、APDL 脚本和自动后处理的发展，流程中的部分步骤可以被自动化，但“从结果到设计修复”的语义链条仍然依赖大量人工判断。大型语言模型和工具调用智能体的出现，使自动生成求解脚本、选择载荷面、规划网格、读取应力场和生成自然语言解释成为可能，因此自然引出新的问题：能否把仿真结果进一步转化为经过验证的设计修复，而不是停留在可读的仿真报告？

### 1.2 现有自动仿真工作的进展与不足

现有 LLM/CAE/FEA 研究已经覆盖了多种自动化能力。一类工作关注自然语言到有限元代码或输入文件的生成，例如 AutoFEA 和 ALL-FEM；另一类工作把 LLM 放入工具调用循环，通过 MCP、Abaqus/ANSYS/OpenFOAM 等接口完成建模、求解和可视化；还有研究专门处理网格自适应、CFD 仿真自动化、代码审查或多智能体协作。对于航空发动机涡轮盘这一工程对象，已有文献则主要集中在拓扑优化、孔形/孔径优化、轮缘形状优化、疲劳与蠕变可靠性优化以及代理模型优化。

这些工作共同说明：**“LLM 能够自动生成和运行仿真”本身已经不足以构成新的主要贡献。** 本文因此不把 agent 数量、工具数量、脚本生成能力或某个单次峰值下降作为主创新，而是关注生成之后更困难、更容易被审稿人追问的证据闭环问题。

### 1.3 三个关键缺口

本文把现有自动仿真到设计修复之间的缺口概括为三类。

第一，**参数/特征语义缺口。** 反馈可能知道“轮毂附近应力高”，但不知道哪个可编辑参数控制该特征，也可能只修改一个镜像参数而遗漏其镜像实例、圆角族或孔阵列。区域级或文本级建议不能直接等同于可执行的特征级修复。

第二，**文档/实体缺口。** 智能体修改 JSON、脚本或参数表，并不保证最终 STEP 实体目标区域发生变化。参数名存在、写入成功和几何构建成功是三个不同层次的事件。如果系统只检查文档字段，可能把没有真正改变零件的修复送入有限元求解，并污染后续经验记录。

第三，**预测/物理解释缺口。** 仿真反馈常以自然语言提出“增大孔径可降低应力”之类的机制假设，但该假设是否成立必须在下一轮真实求解中验证。若只看数值是否下降，重网格噪声、载荷面伪峰或局部副作用都可能被误认为成功。现有系统对预测的判伪、噪声底和副作用记录仍不充分。

### 1.4 本文方法概述

针对上述缺口，本文提出面向航空发动机涡轮盘的证据驱动自动仿真—反馈—修复闭环。系统从一个参数化 CAD 文档和已有 FEA 结果出发，依次完成以下证据链：

`应力场证据 → 机制与位置 → 可编辑特征/参数 → 文档补丁 → 最终 STEP 实体变化 → 独立再求解 → 预测判定 → 工程经验规则`

> 证据层 1：应力场证据 → 机制与位置
>
> 证据层 2：真实工程特征 → 可编辑参数组
>
> 证据层 3：文档补丁 → 最终 STEP 实体变化
>
> 证据层 4：独立再求解 → 预测判定与副作用
>
> 证据层 5：confirmed / refuted → 工程经验规则

本文的主贡献是：

> **提出并验证一种面向涡轮盘应力场修复的“特征—实体—物理”证据闭环框架，把传统“读取结果并修改参数”的弱反馈提升为可追溯、可执行、可判伪、可积累工程经验的 CAD–FEA 修复过程。**

围绕主贡献，设置三个必要支撑机制，而不是三个并列主创新。

1. **特征级 CAD 参数依赖图与联合修复。** 建立镜像点、圆角族、阵列实例、轮廓和特征包之间的关系，使反馈能够落到真实可编辑特征，并保持参数之间的几何一致性。

2. **求解前最终实体效果门。** 基于最终 STEP 的边界单元，在目标半径、轴向和方位角窗口内比较局部表面积、边界、单元数和径向边界。若目标区域未变化，则在求解前 fail-closed。

3. **可判伪反馈—修复协议与工程经验记忆。** 反馈必须包含机制、位置、证据、修改动作和预测；下一轮求解依据噪声底和副作用给出 confirmed、partial、refuted 或 unmoved；只有带真实观测的规则才能进入经验库。

非全局 Z 轴支持、自动选面和多样本 benchmark 都是该闭环的工程基础或评价手段，不作为并列创新点。

### 1.5 本文贡献与贡献边界

本文只设置一个主贡献，三个支撑点均服务于该主贡献。

**主贡献 C0：证据闭环的自动仿真与结构修复框架。** 本文将涡轮盘的反馈—修复过程统一为一条可核验证据链：`应力场证据 → 机制与位置 → 可编辑特征/参数 → 文档补丁 → 最终 STEP 实体变化 → 独立再求解 → 预测判定 → 工程经验规则`。该框架把已有自动仿真工作通常终止的“结果生成与解释”推进到“真实设计修改及其物理验证”。

围绕 C0，设置三个从属支撑点：

1. **支撑点 C1：特征级 CAD 参数依赖图与联合修复。** 将区域级反馈转化为对镜像点、圆角族、阵列实例、轮廓和特征包的可执行修改，避免改错、漏改或破坏参数一致性。
2. **支撑点 C2：求解前真实实体效果门。** 区分文档编辑与最终 STEP 实体变化；目标区域没有真实变化时，在 ANSYS 求解前 fail-closed。
3. **支撑点 C3：可判伪反馈—修复协议与工程经验记忆。** 将反馈表示为机制、位置、证据、修改动作和预测，并在下一轮求解中依据噪声底和副作用判定 confirmed、partial、refuted 或 unmoved。

本文不把多智能体数量、脚本生成、自动选面、非全局 Z 轴支持、单一案例峰值下降或 benchmark 数量分别包装为并列创新点。它们分别属于 C1 的定位基础、C2 的几何前提、C3 的评价条件，或主贡献的实验验证。本文也不声称当前系统已经是通用自动结构优化器；现有贡献是可信闭环机制及其可核验证据，而不是对所有涡轮盘设计空间的成熟优化能力。

---

## 2. 相关工作与定位

### 2.1 涡轮盘结构设计优化

涡轮盘结构优化研究通常以降低最大应力、满足寿命/可靠性约束或减重为目标。已有工作覆盖拓扑优化、双腹板轮盘形状优化、椭圆通风孔位置与形状优化、非圆通风孔代理模型优化、疲劳可靠性优化以及蠕变—疲劳可靠性分析。这些研究提供了丰富的结构设计知识和数值优化方法，但多数假设输入模型、参数化和目标函数已经确定，重点在优化算法或结构方案本身。

本文与这些工作的区别在于：本文不以替代结构优化算法为目标，而是研究当已有求解结果进入反馈—修复流程后，设计变量、工程特征和物理效果如何被可靠地闭合。换言之，传统优化关注“如何搜索设计空间”，本文关注“在结构设计空间中，如何确认一次反馈是否真的能够成为可执行且可验证的修复”。

### 2.2 LLM 和智能体驱动的 CAE/FEA

随着 LLM 发展，CAE/FEA 自动化已经出现多类代表性工作。一部分工作从自然语言生成有限元输入或代码，并通过执行错误进行修复；一部分工作使用 MCP 或 API 把仿真软件接入 agent harness；另一部分工作加入网格自适应、结果审查、可视化或角色分工。它们在任务完成率、脚本成功率、网格成功率和工作流自动化方面取得了明显进展。

然而，这些工作的评价重点通常是“能否运行”“代码是否可执行”“网格是否成功”或“结果是否可读”。从工程可信度看，还必须继续追问：反馈是否绑定真实几何；修改是否进入最终实体；预测是否被物理解释支持；变化是否超过网格噪声；副作用是否被记录；错误规则是否被保留并跨族检验。本文把这些问题统一放在主贡献中，而不是把 agent 数量或工具丰富度当作创新指标。

### 2.3 反思、经验学习与知识复用

Reflexion、Self-Refine、CRITIC 等工作说明，LLM 可以通过语言反馈、工具评价或自我批评改善后续行为；ExpeL 等方法进一步尝试从经验中抽取可复用知识。工程设计中长期存在案例推理和设计知识复用研究。这些工作为本文的经验学习提供了思想基础，但普通文本 memory 与工程经验规则之间存在重要差异：工程规则必须绑定物理机制、参数路径、方向、量纲、噪声底、副作用和适用设计族。否则，一条在轮缘上成立的规则可能被错误迁移到轮毂，造成负面设计后果。

本文因此把工程经验规则定义为带真实求解观测的结构化对象，而不是自然语言偏好或对话摘要。

### 2.4 研究定位

表 1 给出本文与代表性工作的定位比较。表格不评价各工作优劣，只说明本文选择的研究问题。

| 维度 | 典型生成/脚本工作 | 典型 agentic CAE 工作 | 传统涡轮盘优化 | 本文 |
|---|---|---|---|---|
| 主要目标 | 生成可运行输入 | 自动完成仿真流程 | 搜索最优设计 | 闭合反馈—修复证据链 |
| 特征级修复 | 较少 | 视实现而定 | 参数已给定 | 显式建模 |
| 文档—实体区分 | 少 | 少 | 通常由 CAD 内核保证 | 求解前门控 |
| 预测可判伪 | 少 | 少 | 目标函数直接评价 | 独立再求解判定 |
| 噪声底/副作用 | 少 | 少 | 优化实验可统计 | 作为规则证据 |
| 工程经验积累 | 文本 memory 为主 | 多为会话记忆 | 设计知识/案例推理 | 物理结构化规则 |

由表 1 可见，本文的核心定位不是新增一个更复杂的 agent，而是补上自动仿真结果到真实设计修复之间的证据链。

---

## 3. 问题定义

### 3.1 参数化 CAD 与实体

设参数化 CAD 文档为 `D(p)`，其中 `p` 为可编辑参数向量。最终实体由 CAD 构建过程生成：

`S(p) = Build(D(p))`

文档存在性与实体存在性不能混同。对于某次修复，定义目标窗口 `Ω_target`，其中可以包含半径、轴向位置、方位角和特征类型约束。实体效果门检查 `S(p)` 与 `S(p')` 在 `Ω_target` 内是否存在可测量变化。

### 3.2 仿真与应力场

给定实体、边界条件 `B` 和网格 `Mesh`，有限元求解产生应力场：

`σ = Solve(S(p), B, Mesh)`

应力场应至少包含节点位置、等效应力、径向/环向/轴向分量、温度和位移。应力场还必须带有可信度信息，包括载荷审计、网格质量、求解状态和是否为载荷面/约束面/理想化边缘。

### 3.3 反馈对象

本文将反馈定义为结构化对象：

`f = (m, x, e, a, y)`

其中：

- `m`：机制，例如 hoop-driven、radial-driven、stress concentration、thermal gradient、section overload、load application 或 idealisation edge；
- `x`：位置，包括几何面、特征 ID、半径、轴向位置和置信度；
- `e`：证据，包括节点 ID、应力分量、梯度、温度、载荷路径和验证结果；
- `a`：修改动作，包括参数/参数组、方向、范围和操作约束；
- `y`：预测，包括测量指标、方向和预期相对变化。

自然语言解释可以附加在对象上，但不能替代结构化字段。

### 3.4 修复与判定

修复算子为：

`p' = Apply(f, D)`

修复必须满足以下约束：

- 参数路径必须来自文档白名单；
- 相关镜像、阵列和特征包必须联合更新；
- 参数变化必须满足操作级几何约束；
- 不得直接改写 master 文档；
- 必须生成可重放补丁和历史 revision。

下一轮求解后，根据真实结果 `Δσ` 与预测 `y` 及噪声底 `η` 进行判定。判定不是简单的“峰值下降”，而是一个带证据状态的多值结果。

### 3.5 闭环目标

本文的闭环目标不是替代通用数值优化器，而是提高一次反馈—修复过程的可核验性。可将目标形式化描述为：在满足错误接受率、不可写参数修改和未变化实体进入求解等约束下，最大化 grounded repair 比例和有效物理解释比例。该定义强调工程责任边界：系统可以拒绝修复，也可以用负结果更新知识，但不能把不确定结果包装成成功优化。

---

## 4. 方法

### 4.1 总体架构

系统包含仿真侧、反馈侧和修复侧三个部分。生成部分只作为背景：本文假设已经有参数化 CAD 文档或由前序生成系统得到的设计表示。仿真侧负责面选择、载荷审计、网格规划、求解和应力场结构化；反馈侧负责机制诊断、区域排序、参数可达性和预测构造；修复侧负责参数白名单、依赖图联合修改、补丁生成和实体效果门。三者共用同一 revision 记录和证据格式。

系统采用 Flash 模型执行 agent 判断和工具调用。模型能力之外，关键可信步骤由确定性代码执行，包括证据重读、参数白名单、镜像一致性、实体窗口比较、噪声底计算和结果判定。这种设计使论文讨论的重点从“模型是否会调用工具”转向“harness 如何约束工具结果”。

#### 算法 1：证据闭环修复

1. 输入应力场 `σ`、当前 CAD 文档 `D(p)`、特征图 `G` 和工程规则库。
2. 识别可信高风险区域，排除载荷面、约束面、理想化边缘和 suspect 区域。
3. 生成结构化 finding：`mechanism + location + evidence + change + prediction`。
4. 重读 evidence，验证数值、节点、几何位置和参数可达性。
5. 将 finding 映射到参数依赖组，生成 document patch，但不改写 master。
6. 构建最终 STEP，执行目标窗口实体效果门；目标未变化则 fail-closed。
7. 对修改后的 revision 独立求解，计算相对变化和网格噪声底。
8. 结合主指标方向、变化量、副作用和实体门控给出多值判定。
9. 将真实观测写入规则库，更新 seed、candidate、trusted 或 refuted 状态。
10. 保留 revision、证据、补丁、判定和失败原因，供下一轮反馈复用。

### 4.2 坐标系归一化与仿真一致性

应力结果、网格映射和 APDL 后处理必须使用一致坐标系。系统读取参数文件声明的轴向方向，并生成 frame 描述，包括轴向单位向量、旋转中心、单位和径向区间。profile 阶段、Gmsh 网格阶段和求解阶段共享同一 frame。

非全局 Z 轴当前作为方法完整性的一部分进行说明，而不是独立创新。已完成的测试包括声明轴向读取和 30° 倾斜配置下 profile/frame 对称测量恢复，测量半径范围 r = 60–250 mm、z = −38–38 mm。当前限制是：`rotate_solid` 只旋转 STEP，未同步 OCAF topology，导致 STEP/XBF 不一致，因而实体效果门 fail-closed；倾斜轴的 solver-level ANSYS 验证仍待补充。该限制说明系统不会在上游坐标系不可信时继续求解。

### 4.3 面向测量的仿真 agent

仿真 agent 的核心职责不是写出一段脚本，而是形成一个可审计的仿真对象。其工具包括：

- 读取几何指纹和可编辑参数；
- 识别候选加载面、约束面和监测面；
- 读取面和节点的拓扑/几何一致性；
- 生成网格方案并记录质量指标；
- 执行载荷审计和求解；
- 将结果场转换为结构化统计。

输出至少包含选面 ID、匹配得分、几何距离、载荷分布机制、应用载荷合力、目标载荷误差、网格节点数、质量和后处理状态。如果载荷面识别或网格映射不满足条件，系统应拒绝进入反馈阶段。

### 4.4 特征级 CAD 参数依赖图

设特征图 `G = (N, E)`。节点 `N` 包括几何特征、可编辑参数和求解角色；边 `E` 表示参数关系或工程约束。本文重点使用以下关系：

1. `mirror_vertex_pair`：镜像点或镜像实例，修改一侧必须同步另一侧；
2. `fillet_family`：圆角族，避免只修改一个局部圆角而破坏相邻过渡；
3. `pattern_instances`：孔阵列/周期实例，确保同一阵列中的实例按设计意图共同变化；
4. `profile_contour`：轮廓控制点/截面，避免修改使轮廓出现非设计意图的折点；
5. `feature_bundle`：需要联合修改的多参数特征包。

修复动作 `a` 不直接作用于单个参数，而作用于图上的可执行组：

`group(a) = {p_i | relation(p_i, p_j) ∧ p_j ∈ a}`

修复时必须验证组内一致性和操作级约束。例如，镜像点必须保持数值一致或相对关系一致；圆角不能超过相邻边长度；阵列参数变化必须保持周期结构；轮廓变化不能导致自交或退化。

该图的作用不是让系统“更灵活”，而是让反馈必须在真实工程特征的语义范围内执行，避免产生参数记录改变但设计实体没有按预期变化的假修复。

### 4.5 反馈 agent

反馈 agent 的输入是结构化应力场、几何特征、求解角色和参数能力表。处理过程如下：

1. 对全局峰值、区域峰值和关键截面进行排序；
2. 排除载荷面、约束面、理想化边缘和求解可信度不足的区域；
3. 比较等效应力与径向/环向/轴向分量，判断主导机制；
4. 检查空间衰减、温度梯度、载荷路径和局部梯度，区分结构过载与伪峰；
5. 将位置绑定到真实几何面或特征；
6. 在参数图中查找可控参数组；
7. 生成修改动作和带方向、量级的预测。

反馈验证器要求自然语言中出现的应力数值能够在原始结果场中重读。若反馈引用不存在的节点、量级错误、位置与几何不匹配，或修改参数不在白名单中，则反馈被拒绝或降级为诊断结论，不进入修复。

### 4.6 修复 agent

修复 agent 接收结构化 finding，执行以下步骤：

1. 验证 finding 是否包含明确的几何变化；
2. 查找参数路径和所属依赖组；
3. 检查参数是否可写、单位是否明确、变化是否在操作约束内；
4. 联合应用镜像、阵列、圆角或特征包修改；
5. 生成文档补丁，但不改变 master；
6. 记录 revision、旧值、新值、原因和预测；
7. 交实体效果门检查。

若 finding 只要求“测量某个物理量”而没有给出几何变化，修复 agent 必须拒绝修改，而不是擅自发明参数。若反馈中的参数名在当前文档中不存在，应返回结构化失败原因，供后续经验学习使用。

### 4.7 求解前最终实体效果门

实体效果门从最终 STEP 读取边界三角单元，将单元中心按半径、轴向和方位角分箱，并与目标窗口 `Ω_target` 关联。比较量包括：

- 单元数和面数；
- 局部表面积；
- 最小/最大半径；
- 轴向边界；
- 目标窗口外全局体积和表面积；
- 目标区域变化单元数。

当目标窗口未发生变化时，系统返回 `target_changed = false` 并在 ANSYS 求解前 fail-closed。当目标窗口发生变化但全局变化异常时，系统记录可疑标记，不允许其自动进入高置信经验库。该门控将“改对了文档”提升为“改对了最终零件”。

### 4.8 可判伪预测与噪声底

同一模型在重网格或重复求解时，最大应力会因网格变化而产生非物理波动。本文用噪声底 `η` 表示这种波动：

`η = max_j | metric_j - metric_ref | / |metric_ref|`

对下一轮结果 `metric_after`，计算相对变化：

`Δ_rel = (metric_after - metric_before) / |metric_before|`

判定规则如下：

- 方向与预测一致且 `|Δ_rel| > η`：`confirmed`；
- 方向一致但变化不足，或关键副作用超过阈值：`partial`；
- 方向相反，或关键实体/证据条件失败：`refuted`；
- `|Δ_rel| ≤ η`：`unmoved`。

其中 `partial` 是建议增加的中间状态。即使主指标方向正确，只要载荷面应力、最小安全系数或其他关键指标出现显著副作用，也不能简单标记为成功。

### 4.9 工程经验记忆

经验条目定义为：

`r = (mechanism, feature, parameter/group, direction, metric, expected_direction, observations, noise_floor, side_effects, families, status)`

状态转移为：

`seed → candidate → trusted` 或 `seed → candidate → refuted`

其中：

- `seed`：由工程先验或历史知识初始化，但没有真实求解观测；
- `candidate`：至少有一次真实闭环观测；
- `trusted`：满足重复性、样本数和副作用约束，并至少在两个设计族中得到支持；
- `refuted`：真实求解方向相反，或实体/证据条件不成立。

规则库不允许把没有真实观测的 seed 当作可信知识，也不允许删除 refuted 规则。相反，refuted 规则是下一次反馈的高价值约束，用于阻止系统重复采用已被实验推翻的机制假设。

---

## 5. 实验设置

### 5.1 数据集与模型族

当前数据包括 D01–D32 参数化涡轮盘设计族，以及若干具有真实求解记录的 revision。D19 与 D27 作为 verified reference，用于完整闭环、成对实验和实体效果检查。D15–D18、D23–D26、D29 等族在选面基准中提供 measured candidate fallback，不能统一称为外部 ground truth。

本文实验以内部设计族为主，原因是当前目标是验证闭环协议，而不是声称已经完成跨工业型号泛化。正式投稿前仍需增加独立 verified 家族和外部模型。

### 5.2 仿真与 agent 配置

所有仿真、反馈和修复 agent 使用 Flash 模型。求解器为 ANSYS APDL 工作流，后处理输出节点坐标、应力分量、温度和位移。agent 负责判断、工具选择和自然语言解释；确定性 harness 负责：

- 参数白名单和路径校验；
- 证据数值重读；
- 镜像/阵列一致性检查；
- 最终 STEP 实体变化检查；
- revision 管理和 master 保护；
- 噪声底计算和多值判定。

这一分工意味着论文的主要变量是闭环协议，而不是模型规模。

### 5.3 对照与消融

为判断主贡献是否来自证据闭环，而不是来自更强的模型或更多工具调用，设计以下对照：

1. one-shot LLM：只根据初始结果生成一次修改建议；
2. execution-only repair：有求解和执行反馈，但没有特征图和实体门控；
3. no feature graph：允许直接写参数，不检查镜像、阵列和联合关系；
4. no solid-effect gate：只检查文档补丁，不检查最终 STEP；
5. no prediction：反馈只给诊断，不记录方向性预测；
6. no noise floor：任何方向变化都算成功；
7. full framework：本文提出的完整闭环；
8. 传统数值优化基线（可选）：Kriging 或 Bayesian optimization。

当前部分消融尚未完成，正文中以“待补”标记，不能使用推测结果。

### 5.4 评价指标

评价指标分为五组。

**选面与几何定位：** exact selection accuracy、wrong accepted rate、submission rate、Wilcoxon/Wilson 置信区间。

**特征修复：** dependency coverage、parameter group count、document patch correctness、grounded patch rate、master change rate。

**实体门控：** target changed rate、changed cell count、局部面积/半径变化、误拦截率。

**反馈可靠性：** evidence reread rate、mechanism hit rate、invalid parameter count、finding acceptance rate。

**物理验证与经验：** confirmed/partial/refuted/unmoved 分布、噪声底、副作用比例、trusted/refuted rule 数、跨族转移率。

---

## 6. 结果与讨论

### 6.1 选面与证据基础

表 2 给出内部选面基准。当前合计 11 个设计族、51 次运行，51 次 exact，错误接受为 0，submission rate 为 100%，95% Wilson 置信区间为 [0.930, 1.000]。其中 D27 有 25 次运行，D19 有 3 次运行，其余为 measured fallback 族。

| 指标 | 数值 |
|---|---:|
| 设计族数 | 11 |
| 运行数 | 51 |
| exact selection | 51/51 |
| wrong accepted | 0/51 |
| submission rate | 100% |
| 95% Wilson CI | [0.930, 1.000] |

该结果说明当前 harness 能在内部设计族上形成稳定的面选择和证据基础，但 51 次运行并不等于工业级泛化证明。正式论文应增加独立 verified 模型，并报告每族样本数。

### 6.2 特征依赖图覆盖

表 3 给出 32 个设计族的依赖覆盖。

| 关系类型 | 覆盖 | 缺失 |
|---|---:|---|
| mirror_vertex_pair | 32/32 | 无 |
| fillet_family | 32/32 | 无 |
| pattern_instances | 28/32 | D01–D04 |
| profile_contour | 32/32 | 无 |
| feature_bundle | 32/32 | 无 |

所有设计族的参数组数量中位数为 19，范围为 15–35。镜像、圆角、轮廓和特征包关系在全族出现；阵列关系只在存在阵列的 28 个族中出现，D01–D04 没有相应结构。

该结果支持 C1 的可实现性，但依赖图覆盖不等于所有参数关系都已被结构求解验证。下一步应统计每个关系类型在真实修复中的正确率，而不仅是覆盖存在性。

### 6.3 求解前实体效果

D27 将轮毂内孔参数由 60 mm 修改为 63 mm。实体效果门在最终 STEP 上得到：

| 指标 | 修改前 | 修改后 |
|---|---:|---:|
| 目标窗口最小半径 / mm | 59.856454 | 62.818937 |
| 目标窗口局部面积 / mm² | 199259.710061 | 198374.882306 |
| 变化单元数 | — | 5346 |
| target_changed | — | true |

这一结果说明，反馈—修复过程能够在求解前确认目标区域确实发生变化。对于论文主线，这比“agent 声称已修改参数”更有工程价值。

### 6.4 真实闭环中的预测判定

表 4 汇总当前预测结果。

| 判定 | 数量 |
|---|---:|
| confirmed | 2 |
| refuted | 4 |
| unmoved | 1 |
| 合计 | 7 |

D27 成对实验是一次保守判定的重要案例。修改前后最大 von Mises 应力为 1709.359 MPa 与 1688.457 MPa，相对变化为 −1.2228%；同模型重网格估算的噪声底为 3.8119%。由于变化小于噪声底，系统判定为 `unmoved`，而不是报告为“下降 1.22% 的成功修复”。

D19 展示了更直接的反证。两轮修复分别把内孔参数由 60 mm 改为 63 mm 和 66 mm，最大 von Mises 应力为 1149.708、1150.936 和 1152.771 MPa。两次反馈都预测最大应力下降，但真实结果均判为 `refuted`；同时检测到载荷面应力分别升高 6.09% 和 5.06%。这说明“开孔可以降低峰值”的工程直觉在该载荷路径下并不成立。

如果系统只优化 `max_von_mises_mpa`，它可能继续沿错误方向修改，并把副作用隐藏起来。证据闭环的作用正是在这里拒绝错误机制。

### 6.5 反馈与修复可靠性

表 5 给出反馈和修复协议的当前统计。

| 阶段 | 指标 | 结果 |
|---|---|---:|
| feedback | 接受运行 | 7/7 |
| feedback | evidence reread | 58/58 |
| feedback | mechanism hit | 9/11 |
| feedback | mechanism 95% CI | [0.523, 0.949] |
| revise | grounded patch | 3/3 |
| revise | document patch correctness | 10/11 |
| revise | master changed | 0 |

需要明确：7/7 反馈接受率集中在 D27，不能据此声称跨族泛化。它证明协议在已验证模型上能够稳定运行；跨族可靠性仍需单独实验。

### 6.6 工程经验学习

当前经验库状态为 seed 64、candidate 4、refuted 1、trusted 0。已有 8 条规则出现在多个设计族中，1 条 refuted rule 带真实观测样本。现阶段最重要的结论不是“trusted 规则库已经建成”，而是规则可以被真实结果推动进入 candidate，也可以被真实反例标记为 refuted。

这符合工程经验学习的保守原则：没有足够观测的规则不能被称为可信；被真实求解推翻的规则不能删除，而应保留为禁止重复犯错的约束。

### 6.7 非全局 Z 轴与 fail-closed

坐标系归一化测试表明，系统能够读取参数文件声明的轴向，并在 30° 倾斜配置下恢复 profile/frame 对称测量，半径范围为 60–250 mm，z 范围为 −38–38 mm。然而，实体旋转只更新了 STEP，没有同步 OCAF topology，导致 STEP/XBF 不一致，实体门控返回 `load_surface_not_materialised` 并 fail-closed。倾斜轴的 ANSYS solver-level 验证尚未完成。

因此，本文把非全局 Z 轴写成方法完整性边界，而不是可单独宣传的创新点。它说明系统在上下游表示不一致时不会继续求解，也说明后续需要实现 rigid transform 与 topology 的统一。

### 6.8 消融结果

正式投稿必须加入以下消融。当前初稿只保留实验矩阵，不写未经运行的数字。

| 配置 | 选面 | 特征修复 | 实体门控 | 预测判定 | 经验更新 |
|---|---|---|---|---|---|
| Full | ✓ | ✓ | ✓ | ✓ | ✓ |
| w/o feature graph | ✓ | 退化 | ✓ | ✓ | ✓ |
| w/o solid gate | ✓ | ✓ | 关闭 | ✓ | ✓ |
| w/o prediction | ✓ | ✓ | ✓ | 关闭 | 退化 |
| w/o noise floor | ✓ | ✓ | ✓ | 过报 | 过报 |
| execution-only | ✓ | 无结构化修复 | 无 | 无 | 无 |

待补实验应以相同模型、相同种子和同一噪声底估计流程进行，避免把模型调用差异误认为机制贡献。

---

## 7. 讨论

### 7.1 为什么负结果应当保留

D19 的反证和 D27 的 unmoved 表明，自动修复系统的可信度不在于每次都能降低应力，而在于能够识别“方向不对”和“变化低于噪声”。工程经验的价值不仅来自成功案例，也来自失败案例。一个只记录成功修改的系统很可能在后续设计族中重复使用错误机制。

### 7.2 为什么工程经验不是普通文本 memory

普通 LLM memory 可以记住“内孔增大通常降压”，但涡轮盘中的实际结果取决于轮缘载荷、截面刚度、温度场和载荷路径。因此经验条目必须包含机制、几何特征、参数路径、方向、量纲、噪声底、副作用和适用族。只有达到真实观测门槛后，规则才可以晋升。

### 7.3 对 CJA 读者和涡轮盘设计的价值

对航空发动机结构设计而言，本文的价值不是替代工程师做最终设计决策，而是把自动仿真结果转化为可审计的设计候选。工程师可以检查：

- 峰值是结构机制还是理想化伪峰；
- agent 是否选错了面或参数；
- 修改是否进入最终实体；
- 下一轮结果是否超过噪声；
- 是否存在载荷面等副作用；
- 经验规则是否有真实样本和跨族支持。

这比要求工程师阅读完整对话记录或重新检查自动生成脚本更容易形成工程责任链。

### 7.4 主贡献的支持边界

当前证据支持以下结论：

- C1 的依赖关系可以在 32 个设计族上稳定抽取，但覆盖存在性还不等于所有特征修复都经过真实求解验证；
- C2 已能在 D27 的最终 STEP 上识别真实实体变化，并支持 fail-closed；
- C3 已能在 D19/D27 上产生真实 confirmed、refuted 和 unmoved 结果，并保留反例与副作用；
- 体系层面已经形成“证据重读—参数修复—实体门控—独立求解—规则更新”的可运行闭环。

当前证据尚不能支持以下结论：

- 系统已经能在所有涡轮盘设计族上自动优化应力；
- trusted 规则库已经成熟；
- 非全局 Z 轴已完成所有求解器级一致性验证；
- 51/51 选面准确率可以解释为工业范围泛化准确率。

因此，本文的贡献应表述为“证据闭环框架及其可核验案例”，而不是“已经完成的通用结构优化器”。

---

## 8. 局限与后续工作

第一，当前完整闭环仍主要集中在 D19/D27 等少数 verified reference，跨设计族的完整两轮闭环数量不足。正式投稿前应扩展到更多 verified 家族，并按族报告样本数、种子和置信区间。

第二，非全局 Z 轴尚未完成 topology、STEP 和 XBF 的统一变换，倾斜轴 solver-level 验证缺失。当前 fail-closed 是可接受的安全行为，但论文必须如实写出限制。

第三，trusted 规则仍为 0，现有经验结果主要是 seed/candidate/refuted。需要增加至少两条 trusted、两条 refuted 和两条跨族转移规则，才能支撑“工程经验学习系统”的成熟度。

第四，消融实验尚未完成。特别是没有特征图、没有实体门控、没有预测和没有噪声底的对照，是判断主贡献是否成立的必要证据。

第五，选面基准中部分参考来自 deterministic measured oracle，不能与真实外部 ground truth 混称。正式论文应区分 verified reference、synthetic oracle 和 expert-validated case，并增加工程专家盲评。

第六，本文的 agent 使用 Flash 模型，优势主要来自 harness 和证据协议，而不是模型规模。后续可以检验其他模型是否能在相同约束下复现，但这不应替代工程评价。

---

## 9. 结论

本文围绕航空发动机涡轮盘，提出一个证据驱动的自动仿真—反馈—修复闭环。与现有主要关注脚本生成、工具调用或单次求解的 LLM/CAE 工作不同，本文把主贡献放在从仿真结果到真实设计修复的证据链上：反馈必须绑定机制、位置和参数；修复必须通过最终实体效果门；预测必须在下一轮独立求解中依据噪声底和副作用进行判定；真实反例必须进入工程经验记忆。

本文设置三个必要支撑点：特征级参数依赖图保证修复落到真实工程特征；求解前 STEP 实体门控保证文档修改与实体变化分离；可判伪反馈协议和经验记忆保证系统能够确认、判伪或拒绝不可信修复。当前内部实验已经显示，选面、特征覆盖、实体验证和反馈重读具备可运行基础，同时 D19/D27 的负结果和 unmoved 结果说明系统能够保留反例，而不是只报告成功。

本文不把当前系统描述为已经成熟的通用自动优化器。下一阶段的关键工作是用更多 verified 设计族、完整消融和跨族规则证明主贡献的泛化能力。就现有证据而言，最重要的结论是：**工程自动化的可信度不只取决于 agent 能否生成答案，更取决于系统能否证明一个答案真的改变了零件、真的改变了物理响应，并在被推翻时留下可复用的工程经验。**

---

## 符号与缩写

| 符号/缩写 | 含义 |
|---|---|
| CAD | Computer-Aided Design |
| FEA | Finite Element Analysis |
| STEP | Standard for the Exchange of Product Data |
| APDL | ANSYS Parametric Design Language |
| `D(p)` | 参数化 CAD 文档 |
| `S(p)` | 最终实体 |
| `σ` | 应力场 |
| `f` | 结构化反馈对象 |
| `p'` | 修复后的参数向量 |
| `η` | 网格/求解噪声底 |
| `confirmed` | 预测方向正确且变化超过噪声底 |
| `partial` | 主指标方向正确但存在显著副作用或变化不足 |
| `refuted` | 预测方向相反或关键证据/实体条件失败 |
| `unmoved` | 变化低于噪声底，不能据此外推 |

---

## 附录 A：投稿前最小补充实验清单

1. 在 D19/D27 之外增加至少 2 个 verified 设计族，完成两轮真实闭环。
2. 对每个闭环同时记录：选面、特征组、文档补丁、实体变化、独立求解、噪声底、副作用和预测判定。
3. 完成 full、w/o feature graph、w/o solid gate、w/o prediction、w/o noise floor、execution-only 六组消融。
4. 形成至少 2 条 trusted、2 条 refuted、2 条跨族 transfer 规则。
5. 给出每族样本数和 95% 置信区间，明确 verified/reference/oracle 类型。
6. 完成倾斜轴 topology/STEP/XBF 一致性或明确写入 limitation。
7. 增加一次工程师盲评，评价反馈可读性、修复合理性和错误拒绝是否合理。
8. 对 D19 的载荷面副作用和 D27 的噪声底案例制作独立小图，避免只放在正文数字中。

---

## 附录 B：当前不能写的结论

- 不能写“系统已经能够稳定自动优化任意涡轮盘应力”。
- 不能写“trusted 工程规则库已经形成”。
- 不能写“非全局 Z 轴已完整支持”。
- 不能写“51/51 代表工业级泛化准确率”。
- 不能写“所有设计族都使用外部 ground truth”。
- 不能写“所有预测失败都是模型错误”，其中部分可能是噪声、网格或载荷路径问题。
- 不能省略副作用、反例和 fail-closed 结果。

---

**初稿结束**

---

## 附录 C：审稿人质疑与回应框架

### C.1 与已有 LLM CAE/FEA agent 有何不同？

已有工作主要证明模型可以生成并运行仿真；本文处理的是生成之后更难被验证的一段链路：将应力反馈绑定到真实工程特征，确认文档参数修改是否真的改变最终 STEP 实体，并在下一轮真实求解中用噪声底和副作用判定预测。创新点是证据闭环，不是 agent 数量或工具数量。

### C.2 为什么负结果也可以作为贡献？

D19 的两轮开孔降压预测均被真实求解推翻，并伴随载荷面应力升高；D27 的变化低于重网格噪声底。若没有证据闭环，这些结果可能被误报为优化成功。保留 refuted 和 unmoved 说明系统能够识别错误机制，并把反例转化为后续规则约束。

### C.3 工程经验学习与普通 memory 有何区别？

普通 memory 保存语言经验；本文的规则保存机制、特征、参数组、方向、量纲、噪声底、副作用和适用设计族。没有真实求解观测的规则只能停留在 seed，被真实实验推翻的规则必须保留为 refuted，而不是删除。

### C.4 非全局 Z 轴是否影响主贡献？

非全局 Z 轴是几何一致性前提，不是本文主创新。当前 frame 归一化已贯通 profile、Gmsh、mapping、APDL 和 postprocess；倾斜实体的 topology/STEP/XBF 一致性与 solver-level 验证仍需补充。系统在表示不一致时 fail-closed，而不是给出不可信修复。

### C.5 51/51 是否说明选面已经泛化？

不能。51/51 来自内部冻结基准，其中 D19/D27 为 verified reference，其他族包含 measured fallback。该结果支持内部可重复性，不替代工业级泛化；正式投稿需要报告每族样本数、verified/oracle 类型和置信区间。

## 参考文献（候选，正式投稿前需全文核验）

[1] CFD-copilot: Leveraging domain-adapted large language model and model context protocol to enhance simulation automation. Chinese Journal of Aeronautics, 2026. DOI: 10.1016/j.cja.2026.104321.

[2] AbaqusAgent: A Multi-AI-agent Framework Enabling End-to-end Finite Element Analysis for Solid Mechanics Problems. arXiv:2606.00138, 2026.

[3] ALL-FEM: Agentic Large Language Models Fine-tuned for Finite Element Methods. Computer Methods in Applied Mechanics and Engineering, 2026. DOI: 10.1016/j.cma.2026.118985.

[4] AutoFEA: Enhancing AI Copilot by Integrating Finite Element Analysis Using Large Language Models with Graph Neural Networks. AAAI 2025. DOI: 10.1609/aaai.v39i22.34582.

[5] PAMF: An LLM-driven framework for automated mesh generation in mechanical simulation and CAE workflows. Journal of Mechanical Science and Technology, 2026. DOI: 10.1007/s12206-026-0334-6.

[6] MechAgents: Large language model multi-agent collaborations can solve mechanics problems, generate new data, and integrate knowledge. Extreme Mechanics Letters, 2024. DOI: 10.1016/j.eml.2024.102131.

[7] Large Language Model Agent as a Mechanical Designer. Journal of Engineering Design, 2026 / arXiv:2404.17525. DOI: 10.1080/09544828.2026.2624356.

[8] Large language model-empowered next-generation computer-aided engineering. Computer Methods in Applied Mechanics and Engineering, 2025. DOI: 10.1016/j.cma.2025.118591.

[9] What Do CAE Simulation Agents Really Need Beyond a Generic Harness? arXiv:2609.03718, 2026.

[10] OpenFOAMGPT: A retrieval-augmented large language model (LLM) agent for OpenFOAM-based computational fluid dynamics. Physics of Fluids, 2025. DOI: 10.1063/5.0257555.

[11] A rapidly structured aircraft concept design method based on generative artificial intelligence. Chinese Journal of Aeronautics, 2025. DOI: 10.1016/j.cja.2025.103629.

[12] Topology optimization of turbine disk considering maximum stress prediction and constraints. Chinese Journal of Aeronautics, 2023. DOI: 10.1016/j.cja.2023.03.019.

[13] Optimal location and shape definition of elliptical ventilation openings on aero engine turbine rotors with stress concentration effect. Chinese Journal of Aeronautics, 2021. DOI: 10.1016/j.cja.2021.05.003.

[14] Surrogate-based optimization with improved support vector regression for non-circular vent hole on aero-engine turbine disk. Aerospace Science and Technology, 2019. DOI: 10.1016/j.ast.2019.105332.

[15] Topology and shape optimization of twin-web turbine disk. Structural and Multidisciplinary Optimization, 2022. DOI: 10.1007/s00158-021-03147-z.

[16] A unified fatigue reliability-based design optimization framework for aircraft turbine disk. International Journal of Fatigue, 2021. DOI: 10.1016/j.ijfatigue.2021.106422.

[17] A data-driven roadmap for creep-fatigue reliability assessment and its implementation in low-pressure turbine disk at elevated temperatures. Reliability Engineering & System Safety, 2022. DOI: 10.1016/j.ress.2022.108523.

[18] ExpeL: LLM Agents Are Experiential Learners. AAAI 2024. DOI: 10.1609/aaai.v38i17.29936.

[19] Reflexion: Language Agents with Verbal Reinforcement Learning. arXiv:2303.11366, 2023.

[20] Self-Refine: Iterative Refinement with Self-Feedback. arXiv:2303.17651, 2023.

[21] CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing. arXiv:2305.11738, 2023.

[22] A study in applying case-based reasoning to engineering design: Mechanical bearing design. Artificial Intelligence for Engineering Design, Analysis and Manufacturing, 2003. DOI: 10.1017/s0890060403173064.

[23] An engineering design knowledge reuse methodology using process modelling. Research in Engineering Design, 2007. DOI: 10.1007/s00163-007-0028-8.

[24] Multidisciplinary Design Optimization of Turbine Disks Based on ANSYS Workbench Platforms. Procedia Engineering, 2015. DOI: 10.1016/j.proeng.2014.12.659.

[25] An LLM-guided structural optimization method for aero-engine lubrication hydrocyclones. Separation and Purification Technology, 2026. DOI: 10.1016/j.seppur.2026.137096.

> 证据边界：上述文献仅作为初稿定位和引用起点。正式 Related Work 写作前需获取全文，逐篇核验其方法、数据集、评价指标和结论，避免仅依据标题或摘要推断算法细节。

