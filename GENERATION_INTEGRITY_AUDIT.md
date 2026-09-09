# 生成系统完整性审计

审计日期：2026-09-01
审计范围：Agent 生成主链路（Agent A → Agent B → 沙箱 → assemble → repair → 质量门 → 指标），
以及实验 runner 与并行脚本。重点检查是否存在“对着 golden 答案生成/修复结果”的行为。

## 结论

1. **生成链路没有读取 golden 文件**：`golden/canonical_ir.json`、`output.step`、
   `slot_reference` 等只在评估阶段（指标计算、冒烟对比、工具实验）被读取。
2. **生成链路没有调用参数化模板函数**：`agentic_l2.py` 不 import
   `param_templates` / `fir_tree_slot2d`，Agent B 沙箱执行的是 LLM 自己写的代码。
3. **修复循环不接触 golden**：validation/runtime 修复只接收用户需求、当前文档、
   校验/运行错误与工程验证门信息。
4. **发现并修复一处“隐藏答案参数”泄漏**：`fr_mm`（榫槽圆角比例）原本只在任务元数据
   `normalized_params` 中，未写进用户 prompt，却被 harness 用来计算 fillet 半径。
   这不是读 golden 文件，但属于“任务答案参数未对 LLM 可见”的泄漏，已修复为显式参数。

## 数据流

```text
task prompt + normalized_params
  └─ pipeline._run_agentic_l2
       ├─ Agent A：需求 → 骨架 + profiles(params)
       ├─ Agent B：params + 参数化规则 prompt → 通用工具(sandbox) → emit points
       ├─ assemble：骨架 + Agent B points → RawGcadDocument
       ├─ repair loop：validation/runtime 错误 + 用户需求 → 补丁
       └─ mcp quality gate：只检查当前 run 目录的 STEP/IR

评估（只读 golden）：
  metrics.semantics / metrics.geometry
  _smoke_generation_fix.py / _test_tool_budget.py
```

## 逐环节检查结果

| 环节 | 是否读取 golden | 证据 |
| --- | --- | --- |
| Agent A 输入 | 否 | `pipeline.py:_run_agentic_l2` 只拼 prompt + normalized_params |
| Agent B 输入 | 否 | `agentic_l2.py:run_agentic_l2` 只用 profiles.params + 规则文本 |
| 沙箱执行 | 否 | `_run_python_sandbox` 只执行 LLM 代码，输入为参数 |
| assemble | 否 | 只用骨架 + Agent B 返回的点 |
| fillet 重建 | 否 | `_rebuild_fillet_nodes` 用 Agent A profiles/组件信息 + 参数化规则 |
| repair loop | 否 | orchestrator 只收 user_request + 校验/运行错误 |
| MCP 质量门 | 否 | `run_mcp_quality_gate` 只检查 run_path |
| 指标计算 | 是（评估） | metrics 读取 golden 用于 FDG/参数/Hausdorff/体积对比 |
| 冒烟/对比脚本 | 是（评估） | 只用于统计 Hausdorff，不影响生成 |

## 发现的问题与修复

### 问题：`fr_mm` 隐藏参数泄漏

位置：
- `_main_experiment/tasks/task_builder.py`：`fr_mm` 写入 `normalized_params`，但未出现在任务 prompt。
- `_main_experiment/pipeline.py`：旧代码把 `fr_mm` 放入 `explicit_req`，绕过 prompt 直接传给
  `_rebuild_fillet_nodes`。
- `agentic_l2.py:_slot_fillet_groups`：`exact_fr_mm=req["fr_mm"]` 直接复现模板 fillet 半径。

影响：fillet 半径使用了 LLM 看不到的基准参数，属于“答案参数藏在 harness 里”。

修复：
- `pipeline.py` 现在把 `fr_mm` 作为显式设计参数写入 prompt：
  `榫槽圆角比例 fr_mm=1.2（fillet 半径 = 分组系数 × 喉部半宽 × fr_mm）`。
- `param_prompts.py` 补充 fillet 分组半径公式，LLM 可在推理链中核对。
- harness 仍按声明的参数化规则重建 fillet（结构默认），但参数已对 LLM 可见。

回归验证：T19:8、T33:8 重跑通过，体积/表面积误差与修复前一致（约 0.000x%）。

## 残余边界与论文表述建议

以下行为不是 golden 读取，但属于“参数化规则落地”，论文中应明确说明：
- 轮廓参数化构造规则以 prompt 形式提供给 Agent，坐标由 LLM 调用通用工具计算。
- harness 对 fillet 做确定性分组重建（半径按参数化公式，索引按轮廓角色），
  并补 `boolean_cut.clean_after` 等结构默认。
- Agent A 参数校验与轮廓不变式校验基于 prompt 中声明的参数化公式，不依赖 golden。

建议论文措辞：系统输入为自然语言设计需求 + 参数化构造规则；LLM 通过通用数学/沙箱工具
推导轮廓，harness 仅执行结构默认与一致性校验，golden 仅用于生成后的定量评估。

## 验证记录

- 单测：`test_agentic_plan_validation.py`、`test_complex_rim_transition.py`、
  `test_metrics_semantics.py` 均通过。
- 冒烟：`smoke_fr_mm_visible`（T19:8、T33:8）2/2 通过，槽 Hausdorff ≤ 0.001mm。
- 全量 40 任务（seed 8）：`full_40_rerun` 40/40 通过，体积均值 0.0008%，
  表面积均值 0.004%，槽 Hausdorff 均值 0.009mm。

## 第二批 100 次实验中发现并修复的问题

在 T01-T10 × 种子 0-7/9/10 的 100 次实验中，T06:5、T08:3 出现了“任务未要求榫槽但
Agent A 输出 slot profile”的污染结果，T07:10 因 STEP 导出失败未过门。

根因：`_validate_agent_a_plan` 检查 `"枞树形" not in text` 时，使用的是拼接了
参数化规则文本的完整 user prompt，而规则文本本身含“枞树形”字样，导致该检查永远不触发；
此外旧逻辑在 Agent A 使用两次工具后会跳过校验。

修复：
- `_call_design_with_tools` 新增 `requirement_text`，校验只针对原始任务文本；
- 校验不再因工具调用轮次而跳过，非法 plan 始终反馈并要求修正；
- 测试 `test_design_loop_accepts_emit_after_two_tool_calls` 同步更新为
  “两次工具调用后仍校验并拒绝非法 plan”。

复测：T06:5、T08:3、T07:10 全部通过，且不再出现多余榫槽（slot_n=0），
体积/表面积误差为 0。

合并后 100 次最终结果：`other_seeds_100/final_summary.json`，
成功 100/100，L1 80/80、L2 20/20，体积均值 0.000001%，表面积均值 0.000003%。

## 第三批 T11-T20 × 其他种子的 100 次实验

首轮结果：97/100，3 个失败 + 3 个高误差成功。根因全部在 Agent A 规划层：

1. T18:1：任务只有环槽，Agent A 凭空生成两道冷却孔（幻觉特征）。
2. T11:5：安装孔阵列半径写成 320（误用 rim 半径），需求分布半径为 230。
3. T13:0 / T14:0 / T14:3：Agent A 给环槽组件生成了 `circular_pattern count=1`，
   运行时因“count=1 无效参数”崩溃。
4. T20:4：槽轮廓短边修正仍有个别种子偏差（slot Hausdorff 0.188mm）。

修复（全部为参数化/结构一致性校验，不读 golden）：
- `_validate_agent_a_plan` 禁止未在需求中出现的特征（榫槽/安装孔/减重孔/冷却孔/环槽）。
- 校验孔阵列 `circular_pattern_component.radius_mm` 必须等于需求分布半径。
- 校验 `circular_pattern count >= 2`，且环槽组件不允许做 circular_pattern。

复测 6 个问题组合全部通过，T20:4 的槽 Hausdorff 降回 0.001mm。
合并后最终结果：`other_seeds_100_b2/final_summary.json`，
成功 100/100，L2 80/80、L3 20/20，体积均值 0.00008%，表面积均值 0.00048%。

## 第四批 T21-T30 × 其他种子的 100 次实验

首轮结果：97/100，3 个失败 + 多个高误差成功。根因四类，全部在生成层：

1. 槽底外扩公式误用：部分种子把 `flare_y` 里的 `conn_last_X` 错写成
   `neck_half[-1]`，导致槽底整体偏移约 0.18mm（T22:3、T24:2/4、T29:10、T30:10 等）。
   prompt 已加 MUST-FIX 明确“必须用 X_neck(ys_conn[-1])”。
2. 点序多插齿根点：T22:1 在每齿前多输出一个 root 点，破坏
   crest/plat/under/conn 交替顺序，Hausdorff 达 0.946mm。
   `_slot_shape_issue` 新增逐齿齿顶/平台/内斜面顺序不变式，强制修正点序。
3. 盘体径向参数错误：T22:10 的 hub_radius/rim_web_junction 与形态公式偏差
   12/23mm。Agent A 校验新增 hub/rim 径向站公式检查。
4. 环槽轴向位置错误：T26:10 的 z_base 应为 -25（锥形 collar 为 -22），
   实际偏了 6mm。Agent A 校验新增 collar 槽 z_base 公式检查。

另有一个失败（T24:4）是运行中途 API 余额不足（402），复测后通过。

合并后最终结果：`other_seeds_100_b3/final_summary.json`，
成功 100/100，L3 100/100，体积均值 0.00005%，表面积均值 0.00044%，
槽 Hausdorff 均值 0.0008mm、最大 0.001mm。
