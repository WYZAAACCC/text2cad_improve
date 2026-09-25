# CJA 论文框架与大纲（主贡献聚焦版）

**建议中文题目：** 面向航空发动机涡轮盘的证据驱动自动仿真—反馈—修复闭环

**建议英文题目：** An Evidence-Grounded Simulation–Feedback–Repair Closed Loop for Aero-Engine Turbine Disks

**目标期刊：** Chinese Journal of Aeronautics（CJA）

**版本：** 中文初版框架，v1，2026-09-20

> 写作原则：只设置一个主贡献，下设三个必要支撑点。选面、非全局 Z 轴、benchmark、负结果和工程经验学习都不单独抢占“创新点”，而是分别为这三个支撑点提供能力、证据或验证。

---

## 0. 一句话定位

本文不把“用 LLM/Agent 自动调用 CAE 软件”作为主要创新，因为该方向已被 CFD-copilot、ALL-FEM、AutoFEA、AbaqusAgent、PAMF 等工作覆盖。本文把一个更容易被审稿人追问、也更有航空发动机工程价值的问题作为主线：

**当仿真结果指出一个高应力区域后，系统如何确认应该修改哪个真实设计特征、确认修改是否进入最终实体、执行可执行的参数修复，并用下一轮独立求解判断这次反馈究竟是正确、错误还是低于网格噪声？**

因此，论文的主贡献是：

> **面向涡轮盘应力场修复的“特征—实体—物理”证据闭环框架。** 该框架把传统“读结果并改参数”的弱闭环，提升为从工程特征定位、CAD 实体变化验证、参数化修复到可判伪预测和经验规则积累的证据闭环。

论文不追求把 D27 或某一个模型“优化到更低峰值”作为唯一卖点，而是证明闭环中的每一步都能被独立核验；负面结果也被保留为系统可信度的一部分。

---

## 1. 贡献结构：一个主贡献 + 三个支撑贡献

### 主贡献 C0：证据驱动的 CAD–FEA 反馈修复闭环

将涡轮盘结构仿真的反馈—修复过程统一建模为如下证据链：

`应力场证据 → 机制与位置 → 可编辑特征/参数 → 文档补丁 → 最终 STEP 实体变化 → 独立再求解 → 预测判定 → 经验规则`

框架强调三件事：

1. 反馈必须绑定真实应力证据和设计特征，不能只生成自然语言建议；
2. 修复必须落到实际可写的 CAD 参数，并验证最终实体确实发生变化；
3. 反馈中的预测必须在下一轮求解中被确认、部分确认、判伪或因低于噪声而未移动。

**与已有工作的边界：** 已有工作已经覆盖 LLM 生成 FEA/APDL、工具调用、网格自适应和流程自动化。本文的创新不是“再做一个多智能体系统”，而是把自动仿真的终点从“得到结果”推进到“可核验的设计修复闭环”。

### 支撑贡献 C1：特征级 CAD 参数依赖图与联合修复

面向涡轮盘的真实建模特征，建立可编辑参数之间的关系图，避免系统在参数级别上进行孤立、错误的最小修改。

重点关系包括：

- 镜像点/镜像顶点：`mirror_vertex_pair`
- 圆角族：`fillet_family`
- 孔阵列/周期实例：`pattern_instances`
- 轮廓线/截面：`profile_contour`
- 联合特征包：`feature_bundle`

C1 解决的问题是：**仿真反馈即使找对了区域，也可能改错特征、漏改镜像实例，或破坏参数之间的几何一致性。** 它使“区域级建议”能够转化为“特征级修复”。

当前证据：32 个设计族上统计依赖关系覆盖；镜像、圆角、轮廓和特征包达到 32/32，阵列类关系在存在阵列的 28 个设计族中覆盖，参数组中位数为 19，范围 15–35。该部分应作为方法支撑，不再被写成一个独立的主创新点。

### 支撑贡献 C2：求解前最终实体效果门

区分三类经常被混为一谈的事件：

1. 智能体认为自己修改了参数；
2. CAD 文档 JSON/参数记录发生变化；
3. 最终生成的 STEP 实体目标区域确实发生变化。

C2 在 ANSYS 求解之前，对最终 STEP 的边界三角单元进行半径、轴向和方位角聚合，检查目标窗口内的单元数、局部表面积、径向边界和法向/边界变化。如果目标区域没有变化，则 fail-closed，不进入求解阶段。

当前证据：D27 将孔径/内孔参数从 60 mm 修改为 63 mm 后，目标区域最小半径由 59.856454 mm 变为 62.818937 mm，局部表面积由 199259.710061 mm² 变为 198374.882306 mm²，目标区域变化单元数为 5346，`target_changed = true`。这说明门控能够区分文档编辑和真实实体效果。

C2 的工程意义是：**不让一个没有真正改变零件的“修复”进入昂贵的有限元求解，也不让这种修复污染经验学习库。**

### 支撑贡献 C3：可判伪反馈—修复协议与工程经验记忆

反馈智能体输出结构化对象：

`finding = (mechanism, location, evidence, change, prediction)`

其中：

- `mechanism` 表示应力机制，例如 hoop-driven、radial-driven、stress concentration；
- `location` 绑定真实几何/网格区域；
- `evidence` 必须能在原始结果场中重新读取；
- `change` 必须指向文档中真实存在的可编辑参数或参数组；
- `prediction` 给出指标、方向和相对变化量。

修复后，下一轮使用独立求解结果进行判定：

- `confirmed`：方向正确，变化量超过噪声底；
- `partial`：主指标方向正确，但伴随显著副作用或变化量不足；
- `refuted`：方向相反、关键证据不成立，或目标实体未发生必要变化；
- `unmoved`：变化小于重新网格化噪声底，不能据此宣称成功。

经验记忆的规则不是普通文本记忆，而是带工程语义的经验条目：

`rule = (mechanism, feature, parameter/group, direction, expected metric, evidence count, side effects, transferability)`

规则状态为 `seed → candidate → trusted / refuted`。只有真实 FEA 观测达到晋升门槛，规则才能进入 trusted；被真实实验推翻的规则必须保留为 refuted，而不是被删除。

当前证据：7/7 反馈运行被接受，58/58 条证据可重读，机制命中率为 9/11；修复侧已有 3/3 个 grounded patch；闭环预测结果为 confirmed 2、refuted 4、unmoved 1。D19 中两次“开孔降压”预测均被真实结果判伪，并出现载荷面应力升高副作用；D27 中 60→66 mm 的成对实验只得到 −1.22% 峰值变化，而网格噪声底为 3.81%，因此被保守判为 unmoved。

C3 的重点不是“反馈总是正确”，而是：**系统能够知道自己何时错、错在什么机制、下一次应当如何修正规则。**

---

## 2. 不应再单独包装成创新的内容

以下内容可以写进论文，但不能与主贡献并列：

- Agent 数量、工具数量或“多智能体”架构本身；
- LLM 自动生成 ANSYS APDL/输入文件；
- 自动选面本身；
- 非全局 Z 轴支持本身；
- 使用 Kriging、代理模型或 Bayesian optimization；
- 单个 D27/D19 案例中的峰值下降；
- 让 Flash 模型执行工具调用；
- 把所有实验都说成 ground truth。

这些内容应分别服务于：C1 的特征定位、C2 的几何门控、C3 的物理验证与经验学习。

---

## 3. 论文主叙事

### 3.1 问题起点

涡轮盘设计中，应力峰值通常同时受轮缘载荷、轮盘截面、孔径、孔阵列、圆角、轮毂/轮缘厚度和温度场影响。工程迭代不是简单“降低一个数字”，而是要回答：

- 峰值是结构过载、应力集中、热梯度还是模型理想化边缘的伪峰？
- 应该修改哪个特征，而不是改哪个看起来相关的参数？
- 参数修改后最终实体是否真的发生了变化？
- 下一轮求解出现的方向变化是否足以超过重网格噪声？
- 这次结果应该变成一条可复用规则，还是一条反例？

### 3.2 现有工作的缺口

现有 LLM/CAE 工作主要解决：

- 自然语言到 FEA 输入/代码的生成；
- 软件 API/MCP 工具调用；
- 网格/求解流程自动化；
- 基于执行反馈的脚本修复；
- 单轮或短轮次的仿真迭代。

它们尚未充分解决：

- 从“高应力位置”到“真实 CAD 特征/参数”的可追溯映射；
- 文档参数变化与最终实体变化的分离；
- 反馈预测的可判伪性和噪声边界；
- 负结果的结构化保留；
- 跨设计族的工程经验规则迁移。

### 3.3 本文主张

本文主张：**可信的自动修复不等于自动修改更多，而是每一步都能给出证据、反例和边界。**

主结论应写成：

> 在涡轮盘参数化 CAD–FEA 场景中，证据驱动的闭环修复能够把仿真结果转化为可检查、可执行、可判伪的设计修改；在部分案例中，真实求解会推翻看似合理的工程直觉，而这种推翻正是经验学习系统识别错误规则、避免重复犯错的必要信号。

---

## 4. 详细论文大纲

### Abstract

1. 涡轮流盘迭代式 CAD–FEA 的工程成本与可信性需求。
2. 现有 LLM/CAE agent 已能生成和运行仿真，但缺少从结果到真实特征修复的证据闭环。
3. 提出 evidence-grounded simulation–feedback–repair framework。
4. 三个关键机制：feature dependency graph、pre-solve solid-effect gate、falsifiable feedback and experience memory。
5. 给出内部基准和代表案例的定量结果。
6. 强调负结果、噪声底和 fail-closed 对工程可信度的意义。
7. 给出局限：设计族、独立验证和跨族规则仍需扩展。

建议摘要必须出现的数字：

- 选面基准：51/51 exact，0 wrong accepted，95% Wilson CI [0.930, 1.000]；
- 特征图：32 个设计族，参数组中位数 19；
- 实体门控：D27 target changed，changed cells 5346；
- 反馈/修复：58/58 evidence，3/3 grounded patch；
- 预测：confirmed 2、refuted 4、unmoved 1；
- 至少一条真实 refuted rule。

### 1. Introduction

**1.1 工程背景**：涡轮盘设计中的应力控制、疲劳/蠕变可靠性和 CAD–FEA 迭代成本。

**1.2 自动化现状**：LLM/agent 已经能完成 FEA 脚本生成、工具调用、网格规划和结果读取。

**1.3 关键缺口**：`document edit ≠ solid change`，`stress reduction suggestion ≠ verified physical effect`，`text memory ≠ engineering rule`。

**1.4 本文框架**：用一条证据链连接结果、特征、实体、求解和经验。

**1.5 贡献**：主贡献 C0；支撑 C1–C3。

**1.6 结构安排**。

### 2. Related Work and Positioning

**2.1 涡轮盘结构优化**：拓扑、形状、孔径/孔形、轮缘厚度、疲劳/蠕变可靠性优化。

**2.2 LLM/agentic CAE/FEA**：CFD-copilot、ALL-FEM、AutoFEA、AbaqusAgent、PAMF、OpenFOAMGPT 等。

**2.3 反馈、反思与经验学习**：Reflexion、Self-Refine、CRITIC、ExpeL、case-based reasoning。

**2.4 定位表**：比较“生成能力、执行能力、特征修复、实体验证、可判伪性、经验迁移”六个维度。

结论：本文不竞争“能否自动做仿真”，而竞争“反馈是否可信、修复是否真实、经验是否可积累”。

### 3. Problem Formulation

定义：

- 参数化 CAD 文档 `D(p)`；
- 最终实体 `S(p) = Build(D(p))`；
- 有限元映射 `M(S, B, Mesh)`；
- 应力场 `σ = Solve(S, B, Mesh)`；
- 反馈 `f = (mechanism, location, evidence, change, prediction)`；
- 补丁 `p' = Apply(f, D)`；
- 实体变化门 `G(S, S', target window)`；
- 物理判定 `V(Δσ, prediction, η_noise)`。

优化目标不是替代通用优化器，而是最大化可核验修复率：

`maximize P(grounded repair, solid change, physical verdict)`，并约束错误接受率、副作用和不可写参数修改为零。

### 4. Methodology

**4.1 Overall architecture**

输入：已生成的参数化涡轮盘 CAD、工况、网格计划和求解结果。

输出：经过证据验证的 revision、预测判定和经验规则。

**4.2 Frame normalization and solver consistency**

声明轴向、旋转中心和单位；保证 profile、Gmsh、mesh mapping、APDL 和 postprocess 使用同一坐标系。

非全局 Z 轴在这里作为方法完整性，不作为独立贡献。当前必须明确写出：partially implemented；30° tilted profile/frame 测量可恢复，但旋转实体拓扑与 STEP/XBF 一致性仍 fail-closed，solver-level validation 待补。

**4.3 Measurement-driven simulation agent**

职责：选择真实承载面、读取载荷/约束、生成网格方案、运行求解、汇总应力场。

输出必须带：面 ID、几何指纹、载荷审计、网格指标、求解状态和可信度。

**4.4 Feature dependency graph**

节点：几何特征、可编辑参数、求解角色（载荷面、约束面、监测面）。

边：

- mirror：镜像参数和实例；
- fillet：圆角族及其邻接边；
- pattern：孔阵列/周期实例；
- profile：轮廓控制点与截面；
- bundle：需要联合修改的参数集合。

修复只能在图约束内进行，避免孤立改变一个参数而破坏设计意图。

**4.5 Feedback agent**

过程：

1. 对峰值和区域进行排序；
2. 排除载荷面、约束面、理想化边缘和低可信区域；
3. 根据梯度、方向分量、空间衰减和温度场判断 mechanism；
4. 绑定真实网格节点、几何面和参数能力；
5. 生成可判伪预测。

**4.6 Revise agent**

过程：

1. 读取结构化 finding；
2. 只允许写白名单中的参数路径；
3. 合并镜像/阵列/特征包修改；
4. 执行操作级约束检查；
5. 生成稳定补丁和 revision 记录；
6. 不改变 master 文档。

**4.7 Pre-solve solid-effect gate**

从最终 STEP 生成边界三角单元，按 `(r, z, θ)` 聚合；比较目标窗口内：

- 单元数量和面数量；
- 局部表面积；
- 最小/最大半径；
- 轴向边界；
- 目标窗口外的全局变化，用于识别副作用。

目标窗口未变化时禁止求解；目标窗口变化但全局异常时记录为可疑修复。

**4.8 Falsifiable prediction scoring and experience memory**

噪声底由同模型重网格/重复求解基线估计：

`η = max_i |Δmetric_i| / |metric_ref|`

判定逻辑：

- 方向正确且 `|Δ| > η`：confirmed；
- 方向正确但变化不足或存在显著副作用：partial；
- 方向相反或关键实体/证据条件失败：refuted；
- `|Δ| ≤ η`：unmoved。

经验规则只在真实求解存在时更新观测；规则晋升必须满足样本数、跨族或重复性条件。

### 5. Experimental Setup

**5.1 数据与模型**

- D01–D32 参数化涡轮盘设计族；
- D19、D27 作为 verified reference；
- 其余多族结果必须标注为 deterministic measured oracle / provisional；
- ANSYS APDL 求解与结构化后处理。

**5.2 Agent 与 harness**

- 所有仿真、反馈和修复 agent 使用 Flash 模型；
- 模型仅负责判断和工具调用；证据重读、参数白名单、实体门控和判定器由确定性代码执行；
- 这样可以把“语言模型能力”与“可信工程约束”分离。

**5.3 Baselines**

- 一次性 LLM 生成/修复；
- 仅执行反馈、无特征图；
- 有特征图但无 pre-solve solid gate；
- 无预测的反馈；
- 无噪声底的结果比较；
- 传统 Kriging/Bayesian optimization 作为数值基线（若实验规模允许）。

**5.4 Metrics**

- face selection exact accuracy、wrong acceptance；
- feature graph coverage、parameter group count；
- document patch correctness、grounded patch rate；
- target changed rate；
- evidence reread rate、mechanism hit rate；
- confirmed/partial/refuted/unmoved；
- side effects、fail-closed rate；
- trusted/refuted rule count、跨族转移率。

### 6. Results

**6.1 Face selection and grounding**

内部基准：11 个设计族、51 次运行，51/51 exact，0 wrong accepted，submission 100%，95% Wilson CI [0.930, 1.000]。

必须同时写：D19/D27 为 verified reference，其他族为 measured oracle，不能宣称全部为外部 ground truth。

**6.2 Feature dependency coverage**

32 个设计族：

- mirror_vertex_pair：32/32；
- fillet_family：32/32；
- pattern_instances：28/32（缺失族为 D01–D04）；
- profile_contour：32/32；
- feature_bundle：32/32；
- 参数组中位数 19，范围 15–35。

解释：覆盖率和参数组数量说明“特征级联合修复”在数据集上具有可实现性，但不等于所有关系都被求解器独立验证。

**6.3 Pre-solve solid-effect verification**

D27：60 → 63 mm。

- 最小半径 59.856454 → 62.818937 mm；
- 局部面积 199259.710061 → 198374.882306 mm²；
- changed cells 5346；
- target_changed = true。

结论：文档参数变化能够通过最终 STEP 被独立确认。

**6.4 Closed-loop repair cases**

D27 成对实验：60 → 66 mm，峰值 1709.359 → 1688.457 MPa，相对变化 −1.2228%；噪声底 3.8119%；判定 unmoved。

D19：60 → 63 → 66 mm，峰值 1149.708 → 1150.936 → 1152.771 MPa；两次预测均为下降，但均被 refuted；载荷面应力分别出现 +6.09% 和 +5.06% 的副作用。

结论：真实求解可以推翻看似合理的“开孔降压”直觉，说明反馈系统必须具备反证和副作用检查。

**6.5 Feedback and revise reliability**

- 反馈接受率 7/7；
- 证据重读 58/58；
- 机制命中 9/11，95% CI [0.523, 0.949]；
- 修复 grounded patch 3/3；
- document patch correctness 10/11；
- master changed 0。

解释：不把 7/7 当作泛化结论；它说明协议可以在 verified D27 上稳定运行。

**6.6 Prediction outcomes and experience learning**

- confirmed 2；
- refuted 4；
- unmoved 1；
- seed 64、candidate 4、refuted 1、trusted 0；
- 跨多族出现的规则 8 条；
- refuted rule 1 条带真实观测。

结论：当前最重要的结果不是“规则库已经成熟”，而是证明了经验规则可以被真实求解证实或推翻，并且系统不会把未超过噪声底的变化误报为成功。

**6.7 Frame and non-global-Z ablation**

当前只能写成：

- 已能读取声明轴向并归一化 profile/frame；
- 30° tilt 下对称测量可恢复；
- rotate_solid 只旋转 STEP、未同步 OCAF topology，导致 STEP/XBF 不一致；
- 设计效果门 fail-closed；
- solver-level tilted ANSYS 验证尚未完成。

因此非全局 Z 轴是“可信系统覆盖边界”的案例，不是论文完成度的卖点。

**6.8 Ablation study**

正文必须预留以下消融表：

- full loop；
- w/o feature graph；
- w/o solid-effect gate；
- w/o prediction；
- w/o noise floor；
- execution-only repair。

当前若实验不足，明确标记为待补，不用推测数字。

### 7. Discussion

**7.1 为什么“负结果”是贡献**

D19 的反证和 D27 的 unmoved 说明：一个只看峰值是否下降的系统会把噪声或副作用误认为优化成功；证据闭环的价值在于拒绝不可信结论。

**7.2 为什么工程经验必须带物理边界**

普通文本 memory 记住的是“建议”；工程规则必须记住机制、参数、量纲、方向、噪声底、副作用和适用族。否则规则会被错误迁移到不同载荷路径。

**7.3 对涡轮盘设计的工程意义**

系统不是替代工程师，而是把工程师的审查对象从“整段聊天记录/脚本”变成“证据、特征、补丁、实体变化和预测判定”，降低错误接受和重复试验成本。

### 8. Limitations and Future Work

- 更多 verified 设计族和更多独立种子；
- 真实倾斜轴模型的求解器级验证；
- STEP/XBF/OCAF topology 统一变换；
- 至少 2 条 trusted、2 条 refuted、2 条跨族转移规则；
- 更强的工程先验和物理不变量；
- 噪声底的更严格重复实验设计；
- 与 Kriging/Bayesian optimization 的公平比较；
- 工程专家盲评。

### 9. Conclusion

回到一个主贡献：证据驱动的涡轮盘 CAD–FEA 反馈修复闭环。三个支撑点只服务于此：特征图保证改对地方，实体门控保证真的改了零件，可判伪协议与经验记忆保证系统知道自己是否真的有效。

---

## 5. 图表安排

| 编号 | 内容 | 目的 | 是否已有数据 |
|---|---|---|---|
| Fig. 1 | CAD–FEA evidence loop overview | 展示主贡献 | 可绘制 |
| Fig. 2 | Feature dependency graph example | 支撑 C1 | 已有 |
| Fig. 3 | Pre-solve solid-effect gate | 支撑 C2 | 已有 D27 数据 |
| Fig. 4 | Feedback–repair–verdict protocol | 支撑 C3 | 已有 |
| Fig. 5 | Benchmark and ablation matrix | 说明实验设计 | 部分 |
| Fig. 6 | D19/D27 closed-loop trajectories | 展示真实与反证 | 已有 |
| Fig. 7 | Rule lifecycle and transfer | 展示经验学习 | 需补 |
| Table 1 | Related-work positioning | 说明差异 | 可写 |
| Table 2 | Agent/tool responsibilities | 说明 harness | 可写 |
| Table 3 | Selection benchmark | 定量结果 | 已有 |
| Table 4 | Feature dependency coverage | 支撑 C1 | 已有 |
| Table 5 | Solid-effect examples | 支撑 C2 | 已有 |
| Table 6 | Prediction outcomes | 支撑 C3 | 已有 |
| Table 7 | Ablation study | 投稿必需 | 待补 |

---

## 6. 投稿前的证据优先级

| 优先级 | 任务 | 直接支撑 |
|---|---|---|
| P0 | 增加 D19/D27 之外至少 2–4 个 verified 家族的完整两轮闭环 | 主贡献 |
| P0 | 完成 no feature graph / no solid gate / no prediction / no noise floor 消融 | 支撑 C1–C3 |
| P0 | 至少 2 条 trusted、2 条 refuted、2 条跨族规则 | 支撑 C3 |
| P1 | 倾斜轴 solver-level 验证或明确将非全局 Z 写成 limitation | 方法边界 |
| P1 | 与一次性 LLM、execution-only repair、经典优化基线比较 | 审稿可信度 |
| P1 | 工程专家盲评反馈可读性和修复合理性 | CJA 工程价值 |
| P2 | 更完整的置信区间、种子数和统计检验 | 论文严谨性 |

---

## 7. 一句话审稿回应

**审稿人问：这跟已有 LLM 自动 FEA 有何不同？**

答：已有工作主要证明“模型能生成并运行仿真”；本文处理的是生成之后更困难的一段链路：将应力反馈绑定到真实工程特征，验证文档修改是否真正改变最终 STEP 实体，并在下一轮真实求解中用噪声底和副作用判定预测。核心贡献不是 agent 数量，而是一个可判伪、可反证、可积累工程经验的 CAD–FEA 修复闭环。
