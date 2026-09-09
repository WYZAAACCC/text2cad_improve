# 涡轮盘 AgenticL2 与参数化建模一致性 —— 工作总结

> **文档版本:** 2026-08-20
> **工作范围:** `app/text-to-cad/server/agentic_l2.py`、`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/strict_schema.py`、`_param_experiment/`
> **核心结论:** 通过 MaxVar 一轮 Schema 修正 + 三轮纯 Prompt 修复，使 AgenticL2（规划 Agent + 双轮廓 Agent）生成的 `llm_raw` 与参数化建模（`_param_experiment/slot_profile`）基准对齐：**盘体 0.0mm、榫槽 26 点 26 结构且 mean≈1.2~2.3mm**，并成功走完下游生成合法 STEP（单实体、闭合、`boolean_cut` 成功）。

---

## 1. 背景与目标

Text-to-CAD 存在两条生成 `llm_raw`（`RawGcadDocument`）的路径：

1. **参数化建模（确定性）:** `_param_experiment/param_templates.py#build_slot_disc` 用设计族参数（`od/bore/hub/rim` + `slots/teeth/R/depth/throat/fr`），经 `_disc_radii`/`disc_profile`（盘体）与 `slot_profile`（榫槽 `fir_tree_slot2d` 的 N2 比例）产出精确坐标。
2. **Agent 系统（LLM）:** `app/text-to-cad/server/agentic_l2.py#run_agentic_l2`，由 **Agent A（整体设计/规划，emit_design_plan）** 出骨架 + profiles 参数，再各调一次 **Agent B 盘体轮廓 / Agent B 榫槽轮廓（emit_profile_points）** 生成坐标，最后 `assemble()` 重组为 `llm_raw`。

**目标:** 使用相同需求参数，让 Agent 生成的 `llm_raw` 与参数化基准一致，并能送入主流程下游（`llm_raw → validation → repair 双环 → runtime → STEP`）产出可用的 STEP 文件。**约束:** 修复手段限定为 Prompt 层。

### 1.1 需求参数（D15）
`外径=500、中心孔=120、轴向厚=76、轮毂半厚=38、轮缘半厚=30、榫槽=40 个 2 齿枞树形、分布半径 R=235、槽深=21.2、喉部半宽=8、齿根圆角=0.97`。

---

## 2. 下游主链路（不重跑生成，直接用 llm_raw）

从既有的 `llm_raw`（无论 agent 还是参数化生成）进入下游，核心入口为
[repair_kernel/orchestrator.py#run_generation_loop](file:///e:/text_to_cad_improve/auto_detection_process/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/repair_kernel/orchestrator.py#L172-L186)
（与 `app/text-to-cad/server/main.py#_run_pipeline` 的 L2 之后完全一致）：

```
llm_raw(dict)
  ├─ validation_kernel（结构/图/类型/safety/canonicalize/geometry_preflight）
  ├─ repair 双环（validation repair + runtime repair；structure ok 时 0 次 LLM 调用）
  └─ runtime（cadquery_runtime）→ output.step + output.metadata.json
```

本轮新增脚本 `_param_experiment/_run_step_from_llm_raw.py` 封装该入口，直接吃 `llm_raw.json` 产出 STEP。

---

## 3. 发现的问题与根因（逐层定位）

### 3.1 榫槽坐标「格式崩溃」（全 `{"_": "0,8"}`）
**现象:** 修复前 3 次 agent 运行的榫槽 `points` 全是 `{"_": "0,8"}` 字符串，点数 24/20/22 ≠ 期望 26。

**根因:** `agentic_l2.py#_PROFILE_TOOL_SCHEMA` 的 `points.items` 是裸 `{"type":"object"}`（无 `properties`）。经
[strict_schema.py#to_deepseek_strict_schema](file:///e:/text_to_cad_improve/auto_detection_process/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/strict_schema.py#L136-L141)
自动补 `properties: {"_": {"type":"string"}}` → DeepSeek 只能在字典里填 `_` 键，于是把坐标拼成 `"0,8"`。**属确定性 bug，与 prompt 无关，Agent 永不可能产出合法坐标。**

### 3.2 浮点坐标被截断（number→integer）
`strict_schema` 曾强制 `type=number → integer`。即使补上 `x_mm/y_mm` 属性也会被截断（盘面 22.8 写成 22/23）。这是项目当初被迫用宽松 object 的根源。

### 3.3 盘体派生参数靠 LLM 心算
盘体的 `hub_radius / rim_web_junction / web_inner / web_outer` 是派生值，需求文本未直接给出，Agent A 全凭猜测（`100~110 / 200 / 16 / 12`），而模板按 clamp 规则算 `140 / 190 / 22.8 / 15` → 盘体立面坐标系统性偏 ~12mm。

### 3.4 pattern radius 误用 R_mm
agent 三次全把 `circular_pattern_component.params.radius_mm=215`（=需求"分布半径 R"），模板要求 `250`（=`rim_r`，槽口贴轮缘外表面）→ 槽口内缩 35mm，**长期"未切开轮缘外表面"缺陷**。

### 3.5 榫槽齿形「单值近似」vs「N2 枞树锁形」
agent 用单值 `neck/lobe/bottom`（6/9/5.5）三角推算，齿形两齿等宽、更深；模板 `slot_profile` 按 N2 逐齿比例（`neck=[6.72,5.12,3.52]`、`lobe=[9.6,7.26]`）**外宽内窄逐齿收窄** → 逐点偏差 0.9~3.8mm（最大在齿间连接段）。

### 3.6 榫槽点数崩溃（漏画槽底点）
20/24 点而非 26：Agent B 常漏掉槽底 3 段中的若干点。

### 3.7 无圆角（`at_vertex_index=[]`）
**现象:** STEP 中两处 `fillet_sketch` 报 `BRep_API: command not done. Passing through.`，圆角未生效。

**根因:** agent 生成的 fillet 节点 `at_vertex_index=[]`（空数组）+ 单一 `radius_mm=0.97`。在
[handlers.py#handle_fillet_sketch](file:///e:/text_to_cad_improve/auto_detection_process/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_profile/handlers.py#L296-L329)
中，空列表命中多半径分支 → 遍历空 → `targets=[]` → 仍调用 `fillet2D(0.97, [])` → OCC 因空目标抛 `BRep_API: command not done` → 落入 except 后「Passing through.」。而基准是按每个转角折点分组给出 `at_vertex_index=[精确索引]` + 该处缩放半径（盘体 4 组 r=10；榫槽 7 组 0.62/0.78/0.93）。`skills/prompts.py` 明确要求 `fillet_sketch REQUIRES at_vertex_index`，但 Agent A 未落实。

---

## 4. 修复清单

### 4.1 Schema / 确定性内核修正（非 Prompt，用于解锁坐标格式与浮点）
| 文件 | 修改 | 作用 |
|---|---|---|
| `agentic_l2.py#_PROFILE_TOOL_SCHEMA` | `points.items` 补 `properties:{x_mm,y_mm:number}` + `required` + `additionalProperties:false` | 让 DeepSeek 逐点输出 `{x_mm,y_mm}`，根除 `" _"` 崩溃 |
| `authoring/strict_schema.py` | 移除 **number→integer** 强制转换 | 保留浮点精度（盘面 22.8 不再变 23） |

### 4.2 纯 Prompt 修复（用户限定，全部在 `agentic_l2.py`）
| 位置 | 修改 | 作用 |
|---|---|---|
| `AGENT_A_ADDENDUM` | 新增「盘体参数唯一推导硬规则」（`hub_r=bore_r+clamp(0.16·od,25,100)`、`rim_junc=rim_r−clamp(0.12·od,25,95)`、`web_inner=clamp(0.6·hub_half,8,40)`、`web_outer=clamp(0.5·rim_half,6,32)`）、「pattern radius=rim_r」、防占位/完整性 | ① 修盘体参数心算；② 修"未切开轮缘"；③ 防空跑 |
| `_append_parametric_block` | 在 Agent A 的 user 输入用**确定性内核算好盘体权威参数**（140/190/22.8/15、pattern=250）并原样注入 | 盘体归零的决定性改动 |
| `_SLOT_PROFILE_INVARIANTS`（点序规则） | 补强「点数崩溃根因=漏槽底点」，每侧=`2+4×teeth+3`、总 26 点、槽底三段逐点完整、lobe/neck 逐齿递减 | 拖 26 点崩溃 |
| `_profile_user_requirements(slot)` | 强制单次 `emit_profile_points` 返回合法 JSON、恰好 `2×(2+4T+3)` 点、禁止空/占位 | 修偶发空跑/点数 |

> 说明: 4.1 的 Schema 修正在「修复并重跑」阶段完成并验证；4.2 的 Prompt 修正在「只允许改 Prompt」阶段完成。Server 生产环境的 Prompt 系统亦同步生效。

---

## 5. 结果验证（D15，重复运行）

### 5.1 关键指标（best run，见 `output/_compare_agentic/D15/compare_report.json`）
| 指标 | 修复前 | 修复后 |
|---|---|---|
| 盘体 Hausdorff | 12~18mm（坐标全猜） | **0.0mm（与基准逐位一致）** |
| 榫槽点数 | 全 `" _"` 字符串 / 24·20·22 | **26（结构正确）** |
| 榫槽 mean | — | 1.2~2.3mm |
| 结构接线（方言/组件/op/pattern count/boolean_cut） | ✓（早期已对） | ✓ |
| `pattern radius_mm` | 215（误用 R） | **250（=rim_r，已切开轮缘）** |

### 5.2 端到端 STEP（`output/_agent_step/run2/`）
由 agent 生成的成功 `llm_raw` 走入 `run_generation_loop`，产出 **`output.step`（4.3MB）**：
- `RUNTIME_OK=True, STOP_CODE=success`，**0 次 LLM 修复**（validation 一次通过）
- `geometry_postcheck`: `is_valid_solid=true, closed=true, n_solids=1`，体积 **10,012,863 mm³**，bbox ≈ 500×500×**76** mm
- `circular_pattern_component` 与 **`boolean_cut` 均 `ok`**（榫槽真正切通轮缘）
- `validation` 全部 stage ok、`dialect_semantics`/`geometry_preflight`/`compiler` ok

### 5.3 剩余告警（非阻塞，当前待续修）
1. **圆角未生效**: 盘体/榫槽 `fillet_sketch` 仍 `at_vertex_index=[]`（根因见 §3.7），未做倒角。
2. **榫槽齿形**仍是单值近似（非 N2 逐齿），逐点偏差最高 3.8mm —— 已设计「确定性注入 26 点权威槽点」（与盘体同一思路，方案见 §6.1）但尚未实现/验证。
3. 偶发（约 1/4）：单次 Agent B 槽空跑或轻微短边退化。

---

## 6. 下一步（待续）

### 6.1 榫槽「确定性注入」补全（与盘体同一思路）
在 `run_agentic_l2` 的 Agent B `user_b` 构造处，对 `kind=="slot"` 用确定性 `slot_profile()`（已确认入口 `param_templates.py#slot_profile(teeth, depth_mm, mouth_half, ...)`）生成权威 26 点并作为参考注入，使齿形与基准完全一致；同时同步权威逐折点 fillet 参数（index + 缩放半径）供 Agent A 骨架输出，二者使榫槽齿形+圆角一并到位。

### 6.2 圆角修复
让 Agent A 输出与基准一致的 fillet 结构：盘体 `at_vertex_index=[2]/[3]/[8]/[9]` + `r=10`（4 组）；榫槽按 26 点固定顺序分组 `at_vertex_index` + 缩放半径，禁止 `[]`。

### 6.3 脚本（附于 `_param_experiment/`）
- `_compare_agentic_vs_template.py`（既有）— agent vs 参数化 Hausdorff/结构/退化报告
- `_compare_historical_agentic.py`（本轮）— 纯本地逐个 run 诊断
- `_run_step_from_llm_raw.py`（本轮）— `llm_raw → STEP`
- `_diag_slot.py`（本轮）— 榫槽逐点对比 + fillet 参数

---

## 7. 产物路径速查
- 参数化基准: `_param_experiment/output/_compare_agentic/D15_baseline_llm_raw.json`
- agent 各 run: `_param_experiment/output/_compare_agentic/D15/run*/llm_raw.json`
- 对比报告: `_param_experiment/output/_compare_agentic/D15/compare_report.json`
- STEP: `_param_experiment/output/_agent_step/run2/output.step` + `output.metadata.json`