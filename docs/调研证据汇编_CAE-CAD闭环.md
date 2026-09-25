# 调研证据汇编：CAE→CAD 闭环、反馈机制与创新点定位

> 日期：2026-09-15
> 方法：四轮定向检索 + 逐篇核实。**WebFetch 在本环境对所有域名被阻断**，可用通道是 Bash `curl` 直连 `arxiv.org`（`/abs/` 与 `/html/` 均 200），通过 `citation_title` / `citation_abstract` 元标签逐字核实。
> 用途：写论文 related work 与 motivation 时的引证底稿。**所有数字与引语在正式引用前请再核一次原文。**

---

> ## ⚠ 更正声明 · 2026-09-15 · 本文档第 0 节的 L4 行与第 11 节已被证伪，请勿引用
>
> **L4「梯度 / adjoint / 特征灵敏度 —— 无人」是错的。** 该方向在古典优化界已成熟：
>
> | 文献 | 贡献 |
> |---|---|
> | Choi & Chang, *Finite Elements in Analysis and Design* 15(4):317–341, **1994** | design velocity field 计算；明确要求 velocity field 与 CAD 模型上定义的参数自然关联 |
> | Hardee, Chang, Tu, Choi, Grindeanu, Yu, *Advances in Engineering Software* 30(3):185–199, **1999** | **Pro/ENGINEER 参数化 CAD 的参数作为设计变量** → design velocity → 对 stress/displacement 的形状设计灵敏度 |
> | Robinson, Armstrong, Chua, Othmer, Grahs, *CADAPS* 9(2):253–268, **2012** | canonical：`adjoint surface sensitivity × parametric design velocity = ∂J/∂(CAD 特征参数)` |
> | Robinson, Armstrong & Chua, *SMO* 46(3):415–424, **2012** | 用 adjoint 灵敏度图预测添加**四种特征类型**各自收益，**选收益最大者**——离散的「改哪个特征」决策 |
> | Agarwal, Robinson, Armstrong, Kapellos, *SMO* 59(5):1639–1654, **2019** | 自动精化参数化、向 feature tree 添加新 CAD 特征 |
> | **Verstraete, Müller & Müller, ASME Turbo Expo 2017, GT2017-65005** | **最强反例**：以 max von Mises（p-norm 光滑）为目标，对 CAD 特征参数求伴随梯度；结论表述为「extend the back plate near the radial center」——**从结构应力场直接得到具名特征修改决策，且是涡轮** |
>
> **LLM/agent 侧也已有人做**：
> - **FRAME**（OpenReview `2TdYc5V4jU`）：VLM 读 FEA 云图 → 识别应力集中 → **提出具名几何修改（如 increase fillet radius）** → 生成脚本更新 CSG → 重算。注意：**仅 OpenReview 预印本，无 venue/DOI/arXiv**。
> - **商用**：Synera AutoRib（主应力图 → 参数化 rib 网络，2024/25）、Ansys RBF Morph BGM（von Mises 直接驱动表面 morphing，ε̇ = k(σ−σ_ref)）、Dassault 3DEXPERIENCE（`IF max stress > yield THEN strengthen` 规则驱动参数）。
> - **更早的祖先**：Mattheck CAO（1990，Mises 应力 → 虚拟温度场 → 表层生长 → 节点坐标更新，迭代至表面等应力）；Michell 1904 主应力轨迹 → 加筋布局。
>
> **仍可能成立的窄缝**（中等置信度，需系统检索确认）：在**任意未见过的 B-rep** 上、**不依赖工程师预先指定候选集**、**不需要 per-part adjoint / design-velocity 工程化**的前提下，把应力场区域**自动归因到该模型自身特征树中的具名特征**。经典方法每条都要逐零件构建 design velocity + adjoint solver；agent 方法（FRAME / IterSIMP-σ）自认 hotspot 定位精度不足、feature 词汇是固定小集合。
>
> **第 11 节的「没有任何工作把物理 adjoint 场直接送进 LLM」**（在 LLM 的 context 里）**这一窄命题未被推翻**，但它的新颖性弱——属于「两个成熟事物的组合」。
>
> **请勿引用的来源**：专利 US2019/0073438 被某检索摘要描述为「高应力则加厚 rib」，但 Justia 的摘要明确说该专利**不含 "high stress" 字样**，**很可能是检索摘要的幻觉**。
>
> **检索局限**：arXiv API（`export.arxiv.org`）在本环境被阻断，只能逐条 `arxiv.org/abs/ID` 取元标签，**无法做系统性全库检索，存在漏检风险**。

---

> ## → 当前结论见 **《开放问题登记表》**（`docs/开放问题登记表.md`）
>
> 本文档是**证据底稿**（"别人做到哪了"）。后续核验发现：**这里的"空白"判断多数是假空白**——"L4 完全无人"只在 LLM 语料里空，古典优化界 1994 年起就做完了；多处"未解决问题"其实已有人做（见登记表 §2/§3）。
>
> 登记表改为**反向方法**：不自己猜空白，而是收集**别人写在论文里的开放问题**（可引用的正面陈述），再逐条核验是否已解决。结果：8 条仍开放、6 条部分占位、5 条引语过时、**11 条伪造或归属错误**。
>
> **本汇编中最需警惕的几条**：
> - **CADReasoner 的"退化为盲搜"实为 IterCAD 的话，且那句话正是在批评 CADReasoner**（误归属机制：scite.ai 展示引用方句子）
> - **"Hephaestus-CCX" 这个名字在 arXiv 2605.17448 摘要页 grep 零命中**，真实标题是 *Self-Improving CAD Generation Agents with Finite Element Analysis as Feedback*
> - **ACM CSUR 的"四项 unanswered"是伪造**（论文真、清单假）
> - **ProEvolve / SLUMP / JSS 都不是 CAD 工作**（分别是电商基准、ML 代码 faithfulness、UML↔SQL 共演化）
> - **CAWM 是粒子物理、Corral 是化学/材料**，都不是 CAE benchmark

---

## 0. 一句话结论

**这个方向不拥挤，拥挤的是错的那一层。**

把反馈信号按**语义分辨率**排开，密度分布是这样的：

| 层级 | 反馈形态 | 谁在做 | 状态 |
|---|---|---|---|
| **L4** | **梯度 / adjoint / 特征灵敏度** | **无人**（SIMP 内层算了但不外送） | **空白，且两侧接口现成** |
| **L3** | 全场 → **定位到参数化特征** | IterSIMP-σ 尝试并**失败**（p = 0.382）；LLM-IDA **承认退回人工** | **空白，且已有两篇承认** |
| L2 | 全场 → 网格单元 / 区域 | 经典形状优化、SIMP hotspot、feature-mapping | 已解决（经典领域地盘） |
| L1 | 全场 → **标量** | 几乎所有 LLM-CAE 工作 | **拥挤** |
| L0 | 布尔（跑通 / 报错） | CAD-Judge、TraceCAD、Embodied CAD、多数 CFD agent | **拥挤** |

---

## 1. 两句可直接做开篇的原文引语（已逐字核实）

### 1.1 IterSIMP-σ §7.1 —— 承认没做经典方法会做的事

> "This is a deliberate architectural choice, not an equivalence claim, and it has concrete consequences. **The SIMP density update receives no gradient information about the stress field: sensitivities ∂σ_vm/∂ρ_e are never computed**, and the optimality-criteria update drives densities toward compliance reduction without direct knowledge of where stress concentrations are forming. **In classical stress-constrained formulations—P-norm penalty, augmented Lagrangian, or q-p-relaxation—the stress constraint enters the Lagrangian directly, and adjoint analysis provides element-wise stress sensitivity to guide the density update.**"

出处：arXiv:2605.19110

**用途**：证明「梯度信息本可得到、但从未被指向决策层」是作者自己承认的架构选择。

### 1.2 LLM-IDA —— 承认读不到载荷点坐标

> "It is important to note that to simulate diverse industrial design scenarios, the input is **not a 3D modeling code, but a completed 3D model**. This implies that **the LLM-IDA cannot read the coordinates of the load and constraint points. Therefore, a manual step is required** to select the load points based on LLM-IDA simulation suggestions... **If future research enables the identification and selection of the simulation load and constraint points**, LLM-IDA can achieve full-process automation in complex scenarios."

出处：*Engineering*, DOI 10.1016/j.eng.2026.04.009（17 页全文，HEP 镜像 https://jf2.hep.com.cn/4ac8ae6778e442adbc6f8f928da473d0.pdf ）

**用途**：**这是持久命名问题被承认、但未被立项的书面证据**，出自最接近的竞争者正文。是「身份」这条线的最佳引证。

### 1.3 补充：IterSIMP-σ §7.3 —— 承认网格掩盖应力集中

> "The benchmark problems in this study use relatively coarse meshes (1,600–8,000 elements)... **At coarse resolution, stress concentrations are partially smoothed by the mesh itself, potentially understating the difficulty of the stress constraint.**"

其 §7.5 自陈的下一步不是调 prompt，而是："comparison against a stress-aware inner solver such as P-norm, K–S, or augmented Lagrangian stress optimization, followed by separately calibrated fixed-volume 3D reruns and **mesh-refinement checks**."

---

## 2. 已把 CAE 结果回改几何的十项工作

| 工作 | 出处 | 机制 | 反馈信号 | 改什么 | 关键数字 |
|---|---|---|---|---|---|
| **COSMO-Agent** | arXiv:2604.05547（**注意：与 2605.20190 同标题同摘要，是一篇**） | RL 环境，LLM 编排 CadQuery + CAE solver + 结果提取器 | 标量三元组 (max disp, max vM, cost) | 参数化几何 | **74.5% FSR**；消融去掉 RL → **26.0%**；25 类 / ~20k 任务；~6.7 tool calls/实例 |
| **Physics-in-the-Loop** | arXiv:2605.19717（cs.CV；IJCAI-ECAI 2026 AI4Tech） | LangGraph 四 agent（Planner/CAD Engineer/Geometry Reviewer/Structural Reviewer） | VLM 渲染图 + 连通性 + FEA 标量 + 编译/网格报错 | CadQuery 代码 | **FEA 开：安全系数达标 59.0% vs 关：22.2%（p=0.0008）**；28.7 ± **36.9** s |
| **Hephaestus-CCX**（Self-Improving CAD with FEA as Feedback） | arXiv:2605.17448 | CadQuery 程序 + **typed requirement checker**，CalculiX + gmsh | **typed failures**：stress/displacement/modal/buckling/contact/clearance | 程序 + selector metadata | **400 次首轮尝试零严格通过**；11 轮后 38.8% → **60.5%**，9/50 严格通过；**68 min/件、总计 359,525 s**；~7× 算力 |
| **Embodied CAD** | arXiv:2606.31252（南京大学） | L0–L4 技能库 + GRPO | ⚠️ **几何执行奖励，非物理**：`R = w_f·R_format + w_p·R_policy + w_e·R_exec` | skill 序列 | 18,335 candidate group，**skip-update 率 68.3%**；exact policy 93.1% → 93.2% |
| **LLM-IDA** | *Engineering*（非 arXiv） | L0/L1/L2 三层 + PyAnsys + NSGA-II | 代理预测 + Pareto | 参数化原型 | FEA **5200 → 200 次（−96.15%）**，16536 → 636 s，HV 0.832 → 0.809（DevHV 2.76%） |
| **MDO Agent** | arXiv:2511.17511 | Designer/Modeler/**Verifier**/Optimizer 四 agent | FEA 标量 + 报错 | CadQuery 代码 + 参数 | **BC 施加自动化率 50%/70%**，网格与求解器设置 100% |
| **IPMSM FEA-AI** | arXiv:2606.09037 | 三 agent，DOE 规划 + **ANOVA 失败归因** + 不确定性驱动切换 | 目标值 + 预测不确定度 | 参数化电磁几何 | 同 150 次 FEA 配额：iron loss **−44%** / HV **+22.5%**；省时 **52–55%**；**AI-only 收敛到假最优，一半 Pareto 设计不可行** |
| **TurboAgent** | arXiv:2604.06747 | cDDPM 叶型 + transformer 代理 + LLM 元提示 + GA/PSO | 代理预测（R²>0.98） | 叶型 NURBS 参数 | 95% CFD 成功；η **+1.61%**、π **+3.02%**；全环 ~30 min；**CFD 只做末端验证** |
| **Jadhav & Barati Farimani** | arXiv:2404.17525 / *J. Eng. Design* 2026 | LLM + FEM，ReAct + ranked history | max stress + mass 标量 | 节点坐标 + 图拓扑 + 截面 ID | **≤25 次 FEM** vs NSGA-II **50k–100k 次** |
| **Luo et al.** | arXiv:2608.07978 | 双节点：硬修复约束 + 生成候选择优 | 违规项列表 + 4 维分数 + 规范条文 | 截面参数 | Layer 1 引擎精度：10 个回归算例，OpenSeesPy 误差 <1%，与独立 ANSYS APDL 容差 2–3% |

**另**：DesAgent（ASME *JMD* 148(5) 051706，**closed access，未见全文**）据搜索摘要为四 agent + ROSMs 降阶小模型，−21.2% 材料 / 232 s / 12,044 tokens——**中等置信度，引用前须取原文**。

---

## 3. 所有人绕开实体身份的共同手法

**一句话概括**：**让参数向量承载身份，而不是让具名面承载身份。** 几何永远由参数化代码重新生成，所以拓扑命名问题在受限案例集里不暴露。**一旦几何改动跨越参数化模板边界（换拓扑、加特征、载荷路径重排），四种策略全部失效。**

| 绕过策略 | 代表 | 致命弱点 |
|---|---|---|
| 语义方位谓词 | FeaGPT：「left edge」→ surface patch → Gmsh physical group → `*NSET` | 设计域空间布局必须固定 |
| 坐标包围盒谓词 | Physics-in-the-Loop：`spatial_selectors: {x_min, x_max, ...}` | **载荷会落到虚空里**。其 §9.3 自陈：「Rarely it happens that **the area where loads or fixed supports are applied is not filled with material.**」并专门设 Geometry Reviewer 检查「力和约束是否被材料连起来」 |
| 外部状态机 resolver | Embodied CAD：operation family + 构造状态/计数器/对称规则 | **每换一个领域就要新写 resolver** |
| 人工兜底 | MDO Agent：`ask_for_human_help()` | BC 施加自动化率仅 50%/70% |

### 第三方诊断（几乎是替你写的 motivation）

**CADReasoner**：
> 这些空间偏差「**fail to localize errors or attribute them to specific 2D sketch dimensions or topological entities**」，频繁导致多轮迭代「**degenerate into an unguided blind search**」。

### 文献里没有对照物

**没有任何一篇 LLM-CAE 工作把「几何变化后重新建立载荷/约束绑定」当作指标来评测。** Physics-in-the-Loop 报的 4.2× 复杂度、FeaGPT 的 element count CV，都不是身份度量。

---

## 4. 闭环在哪里断：五类硬证据

1. **首轮几乎全军覆没，收益靠堆算力。** Hephaestus-CCX：400 次首轮尝试零严格通过；拉到 60.5% 的代价是 68 min/件、总计 359,525 s。作者原话：「**expanded reasoning effort does not improve performance monotonically**」。

2. **迭代收益按幂律枯竭。** Frontier-Eng（arXiv:2604.12290）：改善频率按 t⁻¹（R²=0.84）、改善幅度按 k⁻¹ 衰减，**中位数每任务只有 7 次改善**，「50–100 迭代后边际收益趋零」。等预算下 depth 完胜 width（n=1 得 1.00，n=16 只 0.91）；**重启会重置累积上下文**。

3. **迭代越多越不稳定。** Physics-in-the-Loop §9.2 原文：
   > "with more iterations, the results tend to become more unstable. Future work could focus on **detecting stopping criteria when a CAD design becomes unrecoverable**."
   单次迭代耗时 28.7 ± **36.9** s——**方差大于均值**（对照：拓扑优化 18.6 ± 1.2 s）。

4. **失败模式振荡而非收敛。** The Observability Gap（arXiv:2603.26942，CHI 2026）：output-only 反馈下 **0% 全场景成功率**；机制是「**correcting one visible symptom repeatedly introduced a complementary failure, preventing convergence**」，形式化为 *feedback paradox*。

5. **奖励信号本身没有区分度。** Embodied CAD：18,335 个 candidate group 中 **skip-update 率 68.3%**，因为「候选都可解析可执行但组内奖励相同」。其结论可直引：「**solver feedback is necessary but not sufficient**」。

---

## 5. 验证与反馈可信度的现状

### 5.1 已有的物理验证子领域（2026 成型）

| 工作 | 出处 | 做什么 | 关键数字 |
|---|---|---|---|
| **PDE-Grounded Intent Verification** | arXiv:2605.09360 | 从 MOOSE 生成文件确定性反推 PDE，与意图契约 `P = (T,B,I,C,S,Ω)` 比对；IFS 分数；PDE-Refine 回灌 | **220 例中 39–40% 能跑但解错物理**；87.5% 不完美输出含 IFS 可检出的结构性错误 |
| **PHACT** | — | propose-certify，确定性检查器单独发证 | 80 个对抗测试**零误发证** |
| **PA-SciML** | arXiv:2607.07379 | 搜索前固定评分器，对预测场施加可机器校验的物理要求 | 抓到误差指标漏掉的因果性违规 |
| **PhysVEC / PhysLang** | arXiv / ICLR 2026 | 守恒律、对称性、渐近极限；PhysLang 明确为**证伪**而设计 | 语言被当作弱上下文先验而非因果约束 |
| **AI CFD Scientist** | arXiv:2605.06607 | **VL physics-verification gate**：渲染流场图给 VLM 检查 | **planted-failure 消融：检出 solver 层漏掉的 14/16 个静默失效** |
| **Verifiable abstention** | arXiv:2608.18836 | executor–supervisor 双 agent，返回 **accept / reject / abstain** | 「abstention 是一等结果，永不被转换成被迫的猜测」；「LLM auditor 可以追加 rejection，但**永不推翻失败了的 hard check**」 |
| **Admissibility ladder** | arXiv:2607.07196 | 作为 test oracle 的仿真器必须先被认证 | 反直觉：**视觉保真度最高的模型在闭环 verdict 上排名更低** |

### 5.2 判决词汇表的先行规范

- **Eval-Verdict Vocabulary（V1–V10）**：**V4 — tool 的返回值是 `reported` 不是 `verified`，reported→verified 需要一次独立读取**；V7 — 未验证 watcher 的「无消息」是 inconclusive，永不是「什么都没发生」；默认安全态是 `inconclusive`。
- **CUF / Veridict**：PASS / FAIL / INCONCLUSIVE，by construction fail-closed——「**no evidence is never a pass**」。
- **Hudson & Hudson**：**Epistemic Closure Score 98–100%**——模型结构性偏向给出结论而非保留不确定性。
- **Observer Zero**：LLM 科学家**能察觉世界变了，却无法得出「它变了」的结论**。

### 5.3 空白

> **没有任何工作把网格收敛 / 离散化检查作为 accept/reject 门放进 agent 环。**

- ShapeBench（arXiv:2605.20763，Stanford，103 个 ASO 任务）有 two-stage Diagnostic Suite，**诊断** surrogate exploitation（逐字证据：DrivAerStar 的 20 个参数里 **13 个在所有方法的收敛最优解上都被推到边界**，「indicating that this convergence pattern is a **landscape property of the surrogate**」；另一任务 C_D,int ≈ 0.003–0.004「physically implausible for a lifting configuration」），但**不把诊断结果作为门**。
- **检索确认：没有一篇用「同一网格」或「网格收敛性研究」作为改进验证的协议。零命中。**
- 唯一认真处理求解器可信度的是 Luo et al.（arXiv:2608.07978）——但只做到**引擎精度层**，且是**一次性**的，不在迭代里。

### 5.4 假象是被记录在案的

**Hephaestus-CCX 的九例 pass-flip 归因分析**中，四类修复里有**两类是假象**：
- **「mesh-sensitive geometry simplification」**——把加载路径简化、网格变好，**被记为设计改善**（RoboMaster launcher、FIA rollcage）
- **「checker-contract repairs」**——物理本来就对，只是 metric alias / mass field / **selector binding** 缺失导致失败

**Verifier 可信度阶梯（arXiv:2608.05179）**：Tier III（数值仿真与守恒律）「**hard to fake without actually solving the problem**」；Tier V（学习型 verifier / 代理奖励）会撞上 **reliability cliff**；「**a surrogate's own confidence certifies nothing about the specific instance**」。另有报告指出**同模型 verifier 反而让任务成功率回退 8.4 个百分点**。

---

## 6. 信用归因：三个层级，全是空的

| 归因层级 | 代表工作 | 机制 |
|---|---|---|
| **agent 的某一步** | `causal-agent-replay`、`Trajectory_Causal_Attribution` | 把 run 当 SCM，对 step 做 `do(·)` 干预后前向重跑；`P(fail\|kept) − P(fail\|ablated)`；**Point-of-Commitment** |
| **agent 组件 / 角色** | Agents that Matter、ShapleyFlow（ACL 2026）、Shadow `bisect` | Shapley / 移除法；Shadow 用**全因子 + Plackett-Burman 设计矩阵 + LASSO + pairwise interaction + 95% bootstrap CI + Meinshausen-Bühlmann 稳定性选择** |
| **文字假设** | SAGE（arXiv:2606.31478） | 多假设失败归因 + 确定性路由；metric-bearing recovery 42% → 92% |

> **没有一篇在「命名物理实体 × 跨 revision」这一层做归因。**

**可借用的形式化**：Shadow `bisect` 的设计矩阵法（把 config 轴换成 CAD 参数轴）；`causal-agent-replay` 的干预代数（把「重采样 step」换成「重采样几何改动」）。

**为什么值得做**：Frontier-Eng 的双重幂律说明盲试有上限。当「多迭代几次」不再有用时，唯一能给出下一步方向的就是「上一次是哪一处起效」。

---

## 7. 预算：数据很硬，但全在评估层

| 工作 | 省了多少 | 代价 |
|---|---|---|
| LLM-IDA | FEA **5200 → 200 次（−96.15%）**，16536 → 636 s | HV 0.832 → 0.809（DevHV 2.76%） |
| IPMSM | 同 150 次配额：iron loss −44% / HV +22.5%；省时 52–55% | **AI-only 收敛到假最优，一半 Pareto 设计不可行** |
| Jadhav | ≤25 次 FEM vs NSGA-II 50k–100k | 浮点精度是 token 生成死穴 |

**两个必须打赢的反向对照**：
- *When Is an LLM Worth It for HPO?*（arXiv:2606.21641）：budget-matched 下给经典搜索同样 warm-start，**LLM 提议不带来任何 sample efficiency 优势**——TPE/GP-BO 约 12 次评估后追平，40 次反超。
- **SimulCost**（arXiv:2603.20253，ICML）：LLM agent 比传统 scanning **慢 1.5–2.5×**。

**空白**：这些全部作用在**评估层**（少跑几次仿真），**没有一个作用在反馈解释层**（用更少仿真得到**足以定位到某个特征**的反馈）。

---

## 8. 一个被反复验证的负面事实

**What Do CAE Simulation Agents Really Need Beyond a Generic Harness?**（arXiv:2609.03718，2026-09）在信息量与修复预算固定的条件下：

- 单 agent harness **打平或超过**多 agent 专用系统（FoamBench **96.4% vs 88.2%**）
- execution-feedback repair 把 **71.8% → 96.4%**
- **"scripted reflection adds nothing"**
- 唯一还有增益的输入是 **solver tutorials**（80.9% → 96.4%）
- 其结论：领域主要缺口是**评价**——多数基准只检查代码能不能跑，**不检查物理正确性**

**解读**：「再加一个 agent / 再让 LLM 反思一轮」这条路线收益已枯竭——**瓶颈不在推理编排，在反馈信息本身的语义分辨率**。这与 Observability Gap 的 feedback paradox、Frontier-Eng 的幂律衰减、Hephaestus-CCX 的 400 次零通过是同一现象的四个侧面。

---

## 9. 两个理论挑战（必须正面回应）

### 9.1 Verification Horizon（arXiv:2606.26300，Qwen Team）

> **没有任何固定 reward function 能在策略能力增长时保持有效——验证必须与生成器共同演化。**

三条性质不可兼得：scalability / faithfulness / robustness。实测：test verifier 把 hacked resolved rate 从 28.57% 压到 0.56%。

**冲击**：「agent 自己声明判据 + harness 校验」若判据静态，会被 agent 追上并钻空子。
**回应方向**：判据由 agent 声明、天然可版本化，把「判据演化」做成设计要求；并用**不依赖判据内容**的独立检验。

### 9.2 IPT — 同构扰动检验（arXiv:2604.15149，DFKI/TU Darmstadt）

只检查 **extensional correctness** 的验证器**会主动诱导**模型放弃规则学习、转而枚举实例级标签。

- shortcut 率：GPT-5-nano **36.8%**、GPT-5-mini-high **8.4%**、GPT-4o 与 Ministral **0%**
- **随任务复杂度与推理算力上升而上升**（算力越多越会钻空子）
- 对照训练证明因果：**extensional 诱导 shortcut，isomorphic 消除 shortcut**
- 机制：把对象常量改名（`train0` → `mytrain42`）而保持关系结构；真正的规则归纳在同构变换下不变，shortcut 会崩

**机会**：**没有人定义过「物理设计的同构变换」**。涡轮盘的候选集：60 重周期扇区旋转、榫槽特征重编号、单位制切换、网格节点重排、载荷工况置换。
**判据**：extensional 通过率与 isomorphic 存活率之差 = shortcut 率。

---

## 10. 综述覆盖：这个 gap 尚未被正式立项

- **ACM CSUR 58(9):225**（arXiv v1）第 7 节 "Future Directions" **只有四条**：Interior/Home Design、Specific Data Format Generation、Building Compliance Checking in AEC、Fashion AI。**仿真反馈闭环完全不在其列。**
- **没有任何一篇 LLM-CAD/CAE 综述提到 persistent / topological naming**（`2505.08137` → 0 命中；`2512.23719` → 0；`2606.31252` → 0）。命名问题是**另一条更老的、非 LLM 的**文献线（中文经典：荆树旭/何发智/刘华俊，《计算机辅助设计与图形学学报》2007, 19(5):545-552）。
- **reward hacking of simulation rewards**：CAD-CAE 领域**只有 COSMO-Agent 一篇点名**。
- ⚠️ **surrogate error compounding**：**找不到任何工程设计综述把它作为命名现象提出**——**标注为未证实，不要当作已被综述覆盖。**
- Zeman et al.（*AEI* 75:104807, 2026，PRISMA 58 篇）结论：LLM 应视为「**capable copilots embedded within orchestrated CAD/CAE environments**」，**不是 autonomous designers**。
- MDPI *Electronics* 15(15):3485（PRISMA 252 篇）：**84.5% 研究仍处研究阶段，仅 0.8% 有可操作工业证据**。

---

## 11. 经典 CAD 灵敏度路线（从未与 LLM 接上）

**这是 L4 空白的另一半——两侧都成熟。**

- **Feature-mapping optimization**（Shannon, Robinson et al., Queen's University Belfast, 2023；*SMO* DOI 10.1007/s00158-023-03650-5）：mapping functions 与商用 CAD 的拉伸/扫掠特征模板参数化对应，**解析可微**，直接给出每个特征几何参数的灵敏度。
- **Parametric Design Velocities**（Robinson 组, NOED 2016）：把 **adjoint 表面灵敏度**与「CAD 参数变化引起的边界法向移动」链接，得到**目标函数对 CAD 参数的梯度**。
- 商用：**Ansys RBF Morph Structures** 支持「automatic shape sculpting driven by FEA solution results」。
- **Chun et al., *JCDE* 2026**：design feature recognition + 包围盒过滤 + 点距离评估做 CAD↔CAE 面映射，**100% BC 分配准确率、人工输入 −97.06%**。（DOI 10.1093/jcde/qwaf137）

**已核实**：**没有任何工作把物理 adjoint 场直接送进 LLM**。逐篇核验覆盖：SIMPr 2603.25099、IterSIMP-σ 2605.19110、AutoSiMP 2603.27000、TO-Master 2607.01812、SGA 2405.09783、Metasurface 2604.01480、Zero-shot rib design 2609.10643、AirfoilAgent、Luo 2608.07978、Gandarela 2604.27962。另全文 grep：`2603.25099` → "adjoint" **0 次**；`2606.31252` → adjoint 0、gradient 0。

现有工作严格分两类：
- **LLM 编排梯度求解器**（TO-Master、SGA、Metasurface）：梯度在求解器内部闭环，**不回传 LLM**
- **LLM 只看原始场/标量**（SIMPr 6 个标量；IterSIMP-σ 渲染图）：**只给 primal field，不给 derivative field**
- **数值融合（无 LLM 决策）**（Zero-shot rib，2609.10643）：FE sensitivity 与生成梯度逐迭代数值组合，**决策者不是 LLM**

**讽刺之处**：SIMP 内层**必须**算 adjoint 才能更新密度，所以梯度就在那里、是免费的，只是**从未被指向 LLM**。

---

## 12. 引用陷阱（必读）

1. **COSMO-Agent 在 arXiv 上有两个 ID**：`2604.05547` 与 `2605.20190`，同标题同摘要（均 2026-04-01，已核实 `citation_title` 与摘要完全一致）。**是一篇工作，不是两篇。**
2. **TurboAgent 无 arXiv HTML 版**（`/html/2604.06747v1` → 404，ar5iv 未收录）；`pdf/2604.06747`（不带 v1）与 `export.arxiv.org` 镜像**下载被截断、PDF 损坏**。完整全文只有 `https://arxiv.org/pdf/2604.06747v1`。
3. **arXiv 2605.17607 已改名**：旧 "Controlled Agentic Planning & Reasoning for Mechanism Synthesis" → 现 *Symbolic Intermediaries as a Linguistic-Numerical Interface for LLM-Driven Geometric Reasoning*（v3）。按旧标题检索找不到。
4. **Embodied CAD 的 "solver" 是 CAD 几何内核（FreeCAD），不是物理/FEM 求解器**——全文无载荷、无应力、无力学求解。其 GRPO 奖励是几何执行奖励。**写成 "physics-verified reward" 会误判该方向拥挤程度。**
5. **DesAgent 是 ASME *JMD* 148(5) 051706，closed access，非 arXiv**。其数字（−21.2% / 232 s / 12,044 tokens）**仅搜索摘要级证据，中等置信度**。
6. **LLM-IDA 不是 arXiv 论文**，是 *Engineering* Gold OA（DOI 10.1016/j.eng.2026.04.009），ScienceDirect 反爬，用 HEP 镜像。
7. **本调研中出现的 `arxiv-org.ezproxy.*` 是机构代理镜像，不是稳定引用源**——正式稿换回 `arxiv.org` 规范链接。
8. **DesignBench 未能核实**：仅有 ASME IDETC session gallery 一个来源，无 arXiv 版、无全文。**请勿直接引用。**

---

## 13. 与本系统的对应关系

| 文献空白 | 本系统的对应物 | 现有证据 |
|---|---|---|
| L4 梯度/特征灵敏度不进 LLM | 把 σ 对命名特征参数的灵敏度接入 agent | 待建（E7） |
| 无网格收敛/离散化 accept 门 | 常应力分片试验 + 错 `LKEY` 正对照 + 近零载荷对照 | A/B/C：位移 3.22314/3.22315/3.25317 mm；vM 1553.78/1482.90/6775.03 MPa；峰值 r 212.29/60/60；SF 0.623172/0.674354/0.147601 |
| 无「命名实体 × 跨 revision」归因 | 溯源锚定 role key + 面演化索引 | D19 rev-000002：**8/8 复解**，面积变化 0.795–1.648%，质心移动 0.130 mm，法向点积 ≥0.99995 |
| 无物理同构不变性检验 | 60 重旋转 / 特征重编号 / 单位切换 / 网格重排 | 待建（E5） |
| 三态 verdict 已有先行规范 | `confirmed_wrong` / `suspect` / `unverified`，**刻意无 `verified`** | `tools/checks.py:classify`；「两个测量吻合不是验证」 |
| 记忆无法区分验证过的教训与侥幸 | `unverified` 永不进入经验库 | 待建 |
| 身份被承认但未被立项 | 载荷/约束绑定准确率作为指标 | 文献**无对照物** |

**「no current memory store separates a validated lesson from a lucky one」**（arXiv:2608.05179）——这句话是三态判决词汇表的存在理由。

---

## 14. 检索方法与局限

- **WebFetch 在本环境对所有域名被阻断**；可用通道为 Bash `curl` 直连 `arxiv.org`。常见代理（r.jina.ai / allorigins / corsproxy）同样不通。
- 四轮检索覆盖的查询变体包括：COMSOL agent / COMSOL-MCP / agentic COMSOL / OpenFOAMGPT / Foam-Agent / ChatCFD / ALL-FEM / FeaGPT / AutoFEA / MCP-SIM / Abaqus MCP / PyAnsys / Code_Aster / AI CFD Scientist / COSMO-Agent / Physics-in-the-Loop / Embodied CAD / CADSmith / RA-CAD / FEA-as-feedback / TO-Master / TopOptAgents / AutoSiMP / adjoint LLM agent / credit assignment / agent memory / reward hacking / verification gap / PCMM VVUQ 等。
- **部分 arXiv ID 为 2026 年 3–9 月的新预印本，可能尚未同行评审**；各工作自报的基准互不相同（如 MetaOpenFOAM 自报 85% 而 Foam-Agent 用同批题只得 55.5%），**跨工作比较需谨慎**。
- 若干开源项目（mph-agent、comsol-codex-mcp、rf-agent）只有 GitHub README，**无正式发表**。
