# 论文 MCP 质量检查层 — 作用分析与可实现性

> 日期：2026-08-03
> 依据：`docs/论文正文0726-V3.docx`（主文）、`docs/论文正文0726-V3-补充材料.docx`、`docs/论文正文0725-V1-第1章及数据集规划.pdf`
> 基准数据：`app/text-to-cad/server/output/b572661c219c4952/`（HPT_Disk_KT787_JB_210，最新涡轮盘建模记录）

---

## 一、论文 MCP 体系（DiskCAD-MCP）的作用

论文将 MCP（Model Context Protocol）定位为 **CAD 模型生成后的独立工程质量检查层**（外层闭环），区别于"中间表示-CAD执行"的内层纠错。核心价值（论文 §1.2.3、§MCP）：

1. **统一工具接口**：尺寸测量、特征计数、实体健康、几何裕度、STEP 回读、可视化等专业算法以统一名称+说明+schema 注册，LLM 按描述发现并调用（不临时生成检查代码）。
2. **区分"程序可执行"与"工程模型正确"**：CAD 内核无报错 ≠ 关键尺寸/特征数量/剩余材料/再生能力满足要求。
3. **结果反馈纠错闭环**：质量检查未过 → 转 Repair Ticket → corrector 修复 → 重新检查，直至"结构化表达合法、CAD 实体有效、关键设计要求满足且质量检查通过"。
4. **可扩展性**：新增工具训练后注册即可被调用（论文：新工具正确调用率 85%，无需改客户端）。

**论文量化效果**：MCP 在 348 个首轮有效实体上额外发现 17 个 CAD 执行状态未暴露的问题（7 关键尺寸偏差、4 特征数量错误、3 边界裕度违规、3 STEP 回读不一致）；工程质量漏检率由 5.8% 降至 1.0%。多工具流程完成率 91.7%、工具选择 F1 95.6%、结果准确率 98.1%。

## 二、论文 MCP 工具清单

### 通用工具（补充材料表 S6）
| 类别 | 功能 |
|------|------|
| 实体检查 | 封闭性、退化边、无效曲面 |
| 尺寸测量 | 外径/内径/厚度/孔径/槽宽/槽深 |
| 榫槽检查 | 齿数/齿面角/槽深/圆角/周向节距 |
| 几何约束 | 孔槽边界裕度、相邻特征最小距离 |
| 参数再生 | 单/多参数修改后模型再生 |
| STEP 检查 | 导出、重导入、几何一致性 |
| 可视化 | 标准视图、剖视图、局部放大 |
| 质量报告 | 汇总检查结果及错误证据 |

### 榫槽专项工具（数据集 §8.4）
`measure_fir_tree_slot_profile` / `count_fir_tree_slots` / `check_slot_pitch_and_ligament` / `check_slot_depth_and_rim_thickness` / `inspect_slot_root_fillet` / `validate_slot_pattern_periodicity` / `compare_slot_profile_to_requirement` / `validate_slot_step_roundtrip`

## 三、现有系统能力映射（可实现性）

| 论文 MCP 工具 | 现有代码基础 | 差距 | 可实现性 |
|---|---|---|---|
| 实体检查 | `cadquery_inspect_step`（STEP 导入+bbox/体积/实体数）、`ModelInspection`（body/face/edge/孔估计）、`geometry_postcheck`（closed/valid） | 退化边/无效曲面需 OCP 深度分析 | ✅ **高**（已 60%，补退化检查） |
| 尺寸测量 | `BoundingBox` 给整体尺寸；Disk-G-CAD 轮廓点确定性可得 | 无专项测量工具 | ✅ **高**（确定性从 IR 推导 + STEP 验证） |
| 榫槽检查 | `_param_experiment` 轮廓分析（齿数/齿面角/圆角/碰撞）已成熟 | 未接入生产检查链路 | ✅ **中高**（确定性几何可算） |
| 几何约束 | 无；但公式明确（pitch-width≥2c、depth+lig≤rim） | 需实现检查器 | ✅ **高**（确定性公式） |
| 参数再生 | Compiler/runner 存在（`cadquery_build_from_cad_ir`） | 需验证 Compiler 对参数修改的重建稳定性 | ⚠️ **中**（依赖 Compiler，需测试） |
| STEP 回读 | `inspect_step_with_cadquery`（STEP 导入已工作）✓ | 体积/尺寸一致性比较需实现 | ✅ **高** |
| 可视化 | 无标准视图 | 需实现（OCP/matplotlib 渲染） | ✅ **高** |
| 质量报告 | `validation_report.json`、`autofix_report.json` 已有部分 | 需整合为统一质量门 | ✅ **高** |
| **MCP 协议层** | `DeepSeekToolCaller.call_strict_tool` + `tools.py`（8 工具注册） | 无标准 MCP 服务器 | ✅ **高**（现有 tool calling 可模拟，或实现 MCP SDK） |

**总体结论：MCP 质量检查层可实现。** 现有系统已具备实体检查、STEP 回读、质量报告的基础（`cadquery_inspect_step` + `ModelInspection` + `geometry_postcheck`），核心缺口是：①榫槽专项测量工具（确定性可算，已有 `_param_experiment` 轮廓分析可迁移）；②尺寸专项测量；③参数再生（依赖 Compiler）；④可视化；⑤MCP 服务器协议封装。

## 四、原型验证（基准：b572661c219c4952）

`_param_experiment/mcp_prototype.py` 实现 9 个论文 MCP 工具，对真实建模产物（`output.step` + `raw_fixed.json`）运行：

```
[输入基准] 盘面外径=500mm  榫槽=60个/2齿  (KT787_JB_210)
[PASS] check_solid_validity          : body=1, faces=3015, edges=9025, V=8799358.5mm³, closed, valid, bbox=[500,500,76]
[MEAS] measure_disc_dimensions       : 外径500 / 中心孔120 / 轴厚76 / hub半厚38 / rim半厚30 / web半厚15
[MEAS] count_fir_tree_slots          : 60个, 分布半径250, 节距26.18mm
[MEAS] measure_fir_tree_slot_profile : 齿数2 / 槽深24 / 喉部半宽4 / 齿面角78.7° / 齿根圆角1.0
[PASS] check_slot_pitch_and_ligament : pitch26.18 - width14 ≥ 2×6.09  ✔
[PASS] check_slot_depth_and_rim      : depth24 + lig11 ≤ rim35  ✔
[PASS] validate_slot_pattern_periodicity: 周期, 60槽, 相邻不重叠  ✔
[PASS] validate_slot_step_roundtrip  : STEP 回读 V=8799358.5 (一致)  ✔
[质量报告] 工程验收通过（5 检查 PASS，无失败）
```

**关键验证点**：
1. **STEP 回读**：`output.step`（15MB，60 槽布尔切除后）能通过 `cq.importers.importStep` 导入并重新测体积（8799358.512 mm³），与 metadata 中 `geometry_postcheck` 记录的完全一致 → 论文"STEP 导出-回读"工具可直接构造。
2. **榫槽专项**：齿数 2、槽深 24、节距 26.18、剩余材料 6.09 —— 全部从 Disk-G-CAD（`raw_fixed.json`）确定性测量，无需 LLM 参与。
3. **几何约束**：论文的 `width+2×ligament≤pitch`、`depth+lig≤rim` 公式在真实参数上通过。
4. **metadata 佐证**：现有系统 `inspection_validation` 阶段为 `missing_inspection_validation_report`（ok:false）——正是论文 MCP 外层质量门的空缺，原型补上了这一环。

## 五、结论与差距清单

**可实现性：高。** 论文 MCP 质量检查层可在现有系统上构造，且现有 inspection 基础设施（ModelInspection / STEP 导入 / geometry_postcheck）覆盖了约一半工具。

**主要差距（按优先级）**：
1. **榫槽专项测量工具集**（齿数/齿面角/节距/剩余材料/圆角）——迁移 `_param_experiment` 轮廓分析
2. **尺寸专项测量**（外径/孔径/厚度从 B-rep 截面验证）
3. **参数再生工具**——验证并接入 Compiler 的局部重建
4. **MCP 服务器封装**（工具注册表 + schema + LLM 发现调用）——可用现有 tool calling 模拟，或实现标准 MCP SDK
5. **可视化**（标准视图/剖视图）
6. **质量报告统一门**（汇总所有工具 + 错误证据 → Repair Ticket 反馈 corrector）

## 六、产物

- `mcp_prototype.py`：9 个 MCP 工具原型（MCP 风格注册：name/description/schema/handler）
- 基准数据：`output/b572661c219c4952/`（STEP + Disk-G-CAD + 验证记录）
