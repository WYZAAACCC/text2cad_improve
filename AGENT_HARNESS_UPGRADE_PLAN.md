# Agent / Harness 升级路线与交接补充

> 日期：2026-09-20
> 范围：生成系统、结构自动仿真系统、反馈与修复闭环
> 目的：把“哪个阶段由谁决定、依赖什么测量、哪里可能静默降级”拆开，给后续优化提供可执行顺序。

---

## 0. 当前基线与证据

- 结构集成全量测试：`556 passed`（2026-09-20）。
- 当前工作树包含 Claude Code 留下的一批在途改动，尚未提交；本次优化没有回退这些改动。
- D27 历史选面 sweep 共 80 条有效记录：精确正确 12、错误 37、耗尽 30、传输失败 1。
- 旧错误的主要形态不是“找不到面”，而是：
  - 把径向方向相似但半径低约 70 mm 的槽面当成承力面；
  - 把同一齿上的工作齿面和非工作/过渡齿面一起选入；
  - 选中整个 18° 扇区或跨扇区重复面，导致加载面积和压力改变。
- 本轮新增的选面门在真实 D27 数据上回放：
  - 正确 24 面：通过；
  - 历史混合 72 面：拒绝；
  - 历史低半径 8 面：拒绝；
  - 拒绝原因包含测量值，不依赖固定面索引。

本轮已落地的第一批改动：

1. `facefind` 增加 `flank_surface_normal` 的载荷法向族门：
   - 先按半径寻找独立的外缘载荷带；
   - 再在外缘带内按径向法向对齐度寻找强对齐族；
   - 只有两个间隙都显著时才启用；
   - 缺失强对齐族或混入其他半径带/非工作齿面时拒绝提交。
2. `feedback` 的提交不再只做字段形状校验：
   - 每条 evidence 必须从真实结果场重读；
   - 声明值偏离测量值超过容差则拒绝；
   - 有几何修改必须有可检验 prediction；
   - `load_application` / `idealisation_edge` / `unresolved` 不得携带几何修改；
   - 文档参数名必须在该 revision 的 document 中真实存在。
3. `iterate.score_applied` 修正了仅有 `relative_change` 时的增/减方向判断。
4. `revise` 现在同时强制“修改参数一致”和“修改幅度一致”，防止把结果归因到未实际执行的 finding。

真实兼容性回放：

- run3/run4/run5 的 7 次真实 document 写回全部与 finding 提议值精确一致；
- run3–run6 的 8 条历史 finding 当前全部通过新的证据与预测门，没有被误拒。

### Flash 夜间实测结果

- 结构仿真、feedback、revise 和 CFD expert review 的默认模型已统一为 `deepseek-v4-flash`；目标范围内已无 `deepseek-v4-pro` 默认值。
- D27 选面独立 benchmark（4 路并发、Flash）：
  - 25/25 精确匹配参考 24 面；
  - wrong accepted = 0；
  - submission rate = 100%；
  - 工具调用中位数 = 6，范围 6–8。
- D19 OOD 检查（不同几何、6° 扇区、8 面参考集）：3/3 精确正确；
- D27 + D19 合计 28/28 精确正确、0 误接受。
- feedback Flash 在 run3–run6 四个真实历史 job 上回放：
  - 4/4 成功提交；
  - 调用数 14–25；
  - 所有 evidence 均重读通过；
  - 有 document 的 revision 能正确提出 document 参数或明确 no-change 诊断。
- revise Flash 在四个历史 finding 上回放：
  - 有 structured change 的 2 条全部写出精确 document patch；
  - 无 change 的 2 条最初试图擅自修改 document，新 fail-fast/归因门成功阻断，最终 `document_edits=[]`；
  - 母版隔离检查全部通过。

这一轮新增的硬门还包括：

- stored feedback 在每次 loop diagnose 前按 revision document 重新验证；失效记录不会被直接复用；
- 一轮 submission 最多一个可执行设计改动，避免多个预测共享同一结果；
- revise 必须逐条 accounting，未知 skipped、重复/重叠、遗漏 finding 都拒绝；
- no-change diagnosis 不能授权 `set_parameter`/`write_script`；
- applied finding 的写操作必须参数一致、幅度一致，且不能存在未列入 applied 的额外改动；
- 相反方向的 knowledge rule 会拆成不同 entry，不与相反观测混合。
- feedback 支持自描述 `agg:<quantity>:<reducer>:<bounds>` 统计 evidence，可由 harness 按字段重算。
- 新增论文指标聚合器 `_structural_experiment/probes/paper_metrics.py`。
- 新增 document dependency graph、最终 STEP design probe 和统计 evidence。
- frame 归一化已贯通 profile、Gmsh、face-to-node mapping、APDL 和 postprocess；非全局 Z/非原点旋转轴已支持。
- revise 记录 profile vertex 的 case-frame r/z 几何效果；写值但几何位置不变会被拒绝。
- 成对的 meridian 顶点必须一起修改；单边修改会在 revise 提交时被拒绝。
- 切向锚点改为扇区中部的实测 bore 节点，避免选中 CPCYC 从节点导致小主元失败。

真实配对实验：bore 顶点对 `60 -> 66 mm` 后，峰值从 `1709.359 MPa` 到 `1688.457 MPa`，相对变化 `-1.2228%`，而实测噪声底 `3.8119%`，因此判定为 `unmoved`，没有把噪声当成改进。

---

## 1. 生成系统：职责拆分

主链路：

`task prompt + normalized_params -> L1 route -> Agent A -> Agent B -> assemble -> validation/repair -> MCP gate -> CAD artifacts`

| 环节 | 主要实现 | 决策者 | 输入 | 输出 | 当前风险 | 升级方向 |
|---|---|---|---|---|---|---|
| L1 路由 | `app/text-to-cad/server/main.py`, `_main_experiment/pipeline.py` | LLM | 用户需求、规范化参数 | `generative_cad_ir` / primitive / unsupported | Web 与实验两条链路重复，容易漂移 | 抽一个共享 route 函数；只保留一套重试和审计 |
| Agent A | `agentic_l2.py:_call_design_with_tools` | LLM | 需求、参数、工具结果 | skeleton + profiles | 大文件、隐式上下文、双链路 | 固化输入/输出 schema；增加离线 replay 评测 |
| Agent B | `agentic_l2.py:_call_profile_with_tools` | LLM | 单个 profile 语义、参数、镜像/拓扑约束 | points | 轮廓不变式失败会重试，成本波动 | 把常用几何计算变成测量工具；记录失败分布 |
| assemble | `agentic_l2.py:assemble` | harness | skeleton + points | `RawGcadDocument` | 转换错误可能到 validation 才暴露 | 增加 assemble 前 invariant，失败点名字段 |
| validation | `validation/` | harness | document | typed issues | 22 个模块，问题码需要保持稳定 | 聚合 issue family；为 Agent 提供按影响排序的修复视图 |
| repair kernel | `repair_kernel/` | 确定性 + LLM | validation/runtime failure | new document / failure class | 严格改善是优点；runtime patch 风险高于确定性 repair | 扩大 deterministic provider 覆盖；保留严格质量向量回滚 |
| MCP gate | `_param_experiment/mcp_tools.py` | harness | generated artifacts | pass/fail + metrics | 失败后是否导出要持续保持 fail-closed | 继续禁止“未过门仍生成成功产物” |
| metrics | 评估脚本 | harness | golden（仅评估） | benchmark metrics | 生产链路不得读取 golden | 保持生成/评估隔离，增加 golden 读取审计 |

生成侧最重要的边界：生产链路可以调用通用工具和 repair，但不能读取 golden。这个边界目前已有专门审计，后续改动应继续保护。

---

## 2. 结构自动仿真系统：职责拆分

实际阶段顺序：

`preflight -> frame -> domain -> setup -> assembly -> mesh -> materialize -> solve -> postprocess -> verify -> feedback -> complete`

外层闭环：

`Loop: generate -> solve -> diagnose(feedback) -> revise -> next revision -> prediction scoring -> knowledge`

### 2.1 preflight / frame

- `preflight`：检查 API key、预算、输入完整性。
- `frame`：测量旋转轴、外径、孔半径、对称面，建立全局 case frame。
- 这些阶段不能猜测物理参数；缺输入应 fail-closed。
- 重点风险：几何量和后续柱坐标必须使用同一 frame，不能各模块各自假定全局 Z。

### 2.2 domain agent

- 文件：`agents/domain.py`
- 工具：`get_geometry`、`inspect_azimuthal_profile`、`probe_periodicity`、`test_finer_periods`、`preview_domain`、`submit_domain`。
- 决策：整件还是循环扇区；扇区角、起始角、使用的对称面。
- 硬门：提交前必须完成周期测量和 domain preview；不能同时使用不相容周期。
- 主要风险：扇区角错会让后续所有面都在错误模型里，但结果仍可求解。
- 下一步：把“扇区包含几个重复特征”作为显式测量返回，消除 `one sector's worth` 的歧义；对 fine period 做一次批量测试而不是逐阶扫。

### 2.3 setup agent

- 文件：`agents/setup.py`
- 工具：`get_part_facts`、`list_alloys`、`lookup_material`、`check_load`、`check_setup`、`submit_setup`、`needs_input`。
- 决策：旋转、温度、材料、叶片载荷、约束。
- 硬门：每个物理值必须来自参数文件或 brief；缺值只能 `needs_input`。
- 已有一致性检查：stated force vs `m r omega^2`；温度半径 vs 几何；材料温度覆盖范围。
- 主要风险：一致性残差目前报告但不阻断；当两个独立输入矛盾时，后续仍可能继续。
- 下一步：为矛盾值引入“明确选择来源”门，而不是默认任一方胜出。

### 2.4 assembly / facefind agent

- 外层：`agents/assembly.py`
- 选面：`agents/facefind.py`
- 工具：`list_features`、`list_solids`、`list_origins`、`query_faces`、`inspect_faces`、`check_criterion`、`run_analysis`、`submit_faces`。
- 决策：feature、solid、真实 TopoDS face 集、选择 criterion、选择理由。
- 已有硬门：
  - 必须给 feature/solid 和 criterion；
  - 面必须能由 pressure mapper 支持（当前要求 planar）；
  - 面必须在正在求解的扇区内；
  - 本轮新增：`flank_surface_normal` 必须通过外缘载荷带 + 强法向族门。
- 主要风险：
  - 几何相似但物理角色不同的面，模型没有叶根几何时信息不完备；
  - 历史 sweep 显示提交率仍偏低，重复探索多见；
  - 正确率只能通过成批 replay 统计，不能靠单次成功判断。
- 下一步：
  - 建立 frozen D27/D19 选面 benchmark，固定 bundle、sector、需求、模型参数；
  - 每批至少 20 次，记录 exact-set accuracy、accepted wrong rate、未提交率、调用数中位数；
  - 任何 wrong accepted 都是 P0；先保精确率，再压缩调用数；
  - 对需要叶根几何才能区分的案例显式标注 `needs_input`，不把不确定性伪装成答案。

### 2.5 mesh agent

- 文件：`agents/mesh.py`
- 工具：几何、profile、mesh measure、convergence、submit。
- 决策：网格尺寸、局部加密区域、元素预算。
- 硬门：两级收敛研究必须完成；收敛结果是后续 `noise_floors` 的来源。
- 主要风险：coarse/final 若是相同分辨率，会浪费一半成本。
- 下一步：复用 coarse/final 等价网格；记录每类 case 的节点数、求解时间和噪声底。

### 2.6 materialize / solve / postprocess

- `pipeline/materialize.py`：选中 CAD 面到网格 element face / node set。
- `pipeline/solve.py`：ANSYS 18.1 APDL batch。
- `core/postprocess_structural.py`：读回应力、位移、反力、载荷账本。
- 已有硬门：选中面必须完整映射；部分面映射时拒绝求解，避免在局部载荷错误的结果上学习。
- 重点检查：
  - 节点重叠是累加还是覆盖；
  - 零节点面必须显式报错；
  - 载荷方向、压力符号、总力/力矩守恒必须来自独立测量。

### 2.7 verify

- 文件：`agents/verify.py`
- 决策：哪些量可以引用，verdict ∈ `unverified/suspect/confirmed_wrong`。
- 证据：收敛变化、载荷方向、反力/守恒、温度双站点比较。
- 主要原则：suspect 和 confirmed_wrong 不能被 feedback 当作设计优化目标。

---

## 3. 反馈与修复系统：职责拆分

### 3.1 feedback agent

- 文件：`agents/feedback.py`
- 工具：结果上下文、rank regions、节点查询、profile、浓度、局部检查、截面、面应力、`locate_point`、document 参数、知识库、`check_finding`、`submit_feedback`。
- 输出：finding = 位置 + 机制 + evidence + 可选 change + prediction。
- 本轮新增硬门：
  - evidence 必须重读；
  - 几何 change 必须有 prediction；
  - 非几何机制不能带 change；
  - 位置型机制 propose change 时必须给 `radius_mm` 和 `z_mm`；
  - document 参数必须真实存在。
- 不强制“机制判定一致”，因为 local concentration vs section overload 是工程判断；强制的是测量事实。
- 下一步：
  - 建立 finding replay corpus，统计 evidence mismatch、missing prediction、unreachable parameter、wrong mechanism；
  - 对同一问题跨 revision 的 finding 稳定性做测试；
  - 把“为什么选这个 region”变成可比较候选集，而不是只返回排名第一。

### 3.2 prediction / knowledge

- 文件：`pipeline/iterate.py`、`tools/knowledge.py`
- 规则键当前是 `(mechanism, parameter)`。
- prediction 在下一 revision 才评分，避免自证。
- outcome：`confirmed/partial/refuted/unmoved/unmeasurable/untested`。
- 副作用会记录 safety factor、displacement 等反向变化。
- 本轮修正：relative-only change 的增/减方向。
- 仍待优化：
  - `(mechanism, parameter)` 是否足够区分 increase/decrease 的相反规则；
  - partial confirmation 的统计语义；
  - `trusted` 与 `retired_by_mechanism` 的真实运行覆盖率。

### 3.3 revise agent

- 文件：`agents/revise.py`
- 任务：把 finding 落到当前 revision 的 `document.json`，不是重新生成。
- 硬门：
  - applied finding 必须有对应写操作；
  - 写操作必须针对 finding 提出的 parameter；
  - 参数必须存在于当前 document；
  - 必须产生真实 document diff；
  - 母版隔离必须验证。
- 主要风险：feedback 的参数虽然真实但语义不同，revise 应拒绝而不是换一个参数。
- 下一步：对 change magnitude、value、relative_change 三者做精确一致性验证，并把最终 patch 写回 finding 做闭环审计。

---

## 4. 升级顺序与验收指标

### P0 已完成

- 全量结构测试基线；
- 重复 tool call 熔断；
- 选中面完整映射 gate（缺失面 fail-closed，面积覆盖下限 95%，避免扇区/半厚度理想化误报）；
- feedback 证据重读与 prediction gate；
- D27 载荷法向族选面 gate；
- knowledge direction 修正；
- revise 参数/幅度/未授权改动归因门；
- stored feedback 按当前 revision document 重验；
- 所有目标 Agent 默认 Flash。

### P1 选面正确率

当前状态：D27 25/25、D19 OOD 3/3，门槛指标在这两个冻结 case 上已达标；仍待扩展到更多设计族。

目标：

- frozen benchmark 上 `wrong accepted = 0`；
- exact-set accuracy ≥ 90%（20 次滚动窗口）；
- valid submission rate ≥ 90%；
- 中位 tool calls ≤ 20；
- 对无解案例必须输出可解释 `needs_input`。

### P2 feedback 与知识质量

目标：

- 100% finding 的 evidence 可重读；
- 0 个 geometry change 无 prediction；
- 参数不可达/不存在时 100% 在 feedback 或 revise 被拒绝；
- 预测与实测的噪声底全部有来源；
- 每条 trusted/refuted 规则都有真实 run 证据。

### P3 revise 与闭环归因

目标：

- 每个 applied finding 都有精确 document patch；
- 无变化 revision 不运行；
- 跨轮 domain/mesh/face selection 固定；
- 每次结果只归因到实际写入的 document diff。

### P4 求解器与物理真实度

目标：

- 全部选中面进入网格且载荷守恒；
- 压力方向、面积、总力、力矩均有独立检查；
- 记录载荷方向和分布假设的适用边界；
- CFD 侧继续要求 spec 物理字段 fail-closed，不允许静默忽略。

---

## 5. 接手后的第一验证命令

```powershell
cd E:\text_to_cad_improve\auto_detection_process\integrations\structural
..\..\.conda\python.exe -m pytest tests -q
..\..\.conda\python.exe -m ruff check src/seekflow_structural/agents/facefind.py src/seekflow_structural/agents/assembly.py src/seekflow_structural/agents/feedback.py src/seekflow_structural/agents/revise.py src/seekflow_structural/pipeline/iterate.py tests/test_facefind_actions.py tests/test_feedback_agent.py tests/test_revise_agent.py tests/test_iterate.py
```

全目录 `ruff check src tests` 当前仍会报告 25 个既有 lint 项（多在未改动的 domain/mesh/verify/cli/tests）；本轮没有顺手大范围格式化，改动文件的定向 ruff 已通过。

完整闭环仍按 `交接文档.md` 第 1.5 节运行，不要把 `TEMP/TMP` 指回 C 盘。

---

## 6. 2026-09-20 续作：非全局 Z、feature graph、求解前实体检查与多族实验

### 6.1 非全局 Z 完整贯通

- 新增 materialize.deck_axis_for；identity frame 为 None，非 identity 统一为 +Z。
- frame 阶段记录 ModelFacts.frame.to_z。
- mesh_sector.case_frame_transform 与 structural Normalisation 做 transform parity 测试。
- profile、Gmsh、CAD facts、mesh mapping、convergence intent、APDL、postprocess 使用同一 case frame。
- mesher 未应用 frame 时，mapping 先归一化临时 mesh；materialize 最终重写 canonical mesh.inp；postprocess 读 intent.mesh_inp。

### 6.2 Feature-level 参数依赖图 v2

dependency_graph 现在输出 operation graph、parameter_groups 和 joint_edit_groups，覆盖：

- mirror_vertex_pair：强制成对修改；
- fillet_family：同一 feature 的圆角族；
- pattern_instances：circular pattern 的 source + placement；
- profile_contour：同一闭合轮廓坐标；
- feature_bundle：一个生成 feature 的全部可编辑参数。

revise 可以在同一 finding 下多次调用 set_parameter，实现 hole pattern、fillet group、rim thickness、slot profile 的多参数联合修改；primary 和 mandatory mirror 仍必须精确写入。

32 族确定性实验：mirror/fillet/contour/feature 均 32/32；pattern 28/32（D01-D04 无 circular pattern）；parameter group 中位数 19，范围 15-35。

### 6.3 生成后、求解前真实实体效果检查

新增 pipeline/design_effect.py；build_profile 增加 triangle_cells（2 mm 径向、2 mm 轴向、10 度方位）。Loop 在 generate 后、solve 前比较全局、surface cells 和 finding target window；目标明确未变化则在 ANSYS 前停止。

D27 bore 配对真实回放（points[0]/[11] 60 -> 63 mm）：

- global r_min_mm 相对变化 +5.0%；
- target local min radius 59.856454 -> 62.818937 mm；
- target local area 199259.710061 -> 198374.882306 mm2；
- target window changed cells 5346；
- verdict target_changed = true。

legacy profile 没有 triangle_cells 时，仍走保守 global fallback 并记录限制。

### 6.4 多设计族与多 seed 选面统计

新增 11 族 Flash sweep：D15-D19、D23-D27、D29，共 23 个 seed。中途发现 D25/D26 各多选近切向面，加入 MIN_RADIAL_LOAD_ALIGNMENT = 0.20 后回放修复。

结果：新增 23/23 exact，wrong accepted 0，submission 23/23。与既有 D27 25/25、D19 3/3 合并：51/51 exact，wrong accepted 0，Wilson 95% exact accuracy [0.930, 1.0]。D15-D26、D29 的 reference 是 deterministic measured oracle；只有 D19/D27 是人工验证 reference。

### 6.5 反馈、修复与知识指标

- feedback：4/4 accepted，evidence re-read 24/24，mechanism signature 3/5（另 2 条为连续 fall-off / load-application 保守判定），2 条带可执行 change。
- revise：4/4 replay 未改母版；有 applied 的 2/2 产生 grounded node patch；no-op applied 0。
- loop：5 条 prediction observation，confirmed 2、refuted 2、unmoved 1。
- knowledge：目前只有 seed/candidate 和 5 条 observation，尚无 trusted/refuted 规则；不能把 candidate 写成泛化结论。
- 严格 path/value/magnitude patch 统计 11/13；旧 live artifact 中 1 条无 document edit、1 条 magnitude 记录不完整。

### 6.6 当前限制

- 新族 reference 是 deterministic measured oracle，不是人工 verified reference。
- feedback/revise replay 仍主要在 D27；跨族 feedback/revise 需要更多完整 solve。
- trusted/refuted 还没有足够真实样本，不能宣称跨族泛化。
- 非全局 Z 已有 transforms/mapping/deck intent 单元契约，仍需真实非 Z STEP + ANSYS solver-level 验证。


---

## 7. 2026-09-20 第二轮续作：跨族闭环与 revise 归因

D19 跨族真实闭环已跑通：bore 依次为 60、63、66 mm，峰值分别为 1149.708、1150.936、1152.771 MPa。前两次 prediction 都预测下降，实测分别 +0.1068% 和 +0.1594%，均高于 mesh noise floor，因此都被判定 refuted；load-surface stress 同时上升约 6.09% 和 5.06%。重建证据在 d19_cross_family_loop_reconstructed.json。

revise 修复了两类跨族归因问题：absolute proposed value 与 rounded relative change 不一致时，以 finding 的 absolute document value 为准；同一 finding/parameter 禁止重复覆盖；no-op 在写回前拒绝。干净 D19 rev2 replay 已精确写回 points[0]/[11] = 66。

frame 运行在 setup 之前，原来只从空的 case.physics 读取 rotation axis。现在 frame 直接读取 RunContext.params 的 rotation block。修复后 D19 30 度 tilt 的 profile/frame 对称测量恢复为 r=60..250、z=-38..38，symmetry score 为 z0=1.0、x0=0.9885、y0=1.0。

限制：composition.rotate_solid 会旋转 STEP，但 OCAF tracked history 没有对应 rotate transform，XBF 仍在原坐标；这会让 STEP/XBF frame 不一致，系统当前以 load_surface_not_materialised fail-closed。真实 tilted ANSYS 对照需要 generation topology 支持 rigid transform，或使用 STEP/XBF 同为 tilted 的外部模型。

最新 artifact：paper_metrics_v10.json、paper_tables_v5.md、d19_cross_family_loop_reconstructed.json。
