# NL2DiskCAD — 涡轮盘参数化模板与数据集基础设施（_param_experiment）

> 论文《面向航空发动机涡轮盘的自然语言参数化 CAD 建模》数据集生成层。
> 隔离实验目录，全部代码在 `_param_experiment/`，主程序零修改。
> 当前状态：2026-08-10（P5 环槽统一为卡环槽）。

---

## 一、系统概述

**确定性参数化模板生成 llm_raw（非 LLM）**：设计族参数 → 合法 RawGcadDocument，
经 validation / repair / runtime / **MCP 质量门**采集数据；LLM 只用于生成三种描述。

32 个设计族（D01-D32），6 类：

| 类别 | 数量 | split 分配 | 结构 |
|------|------|-----------|------|
| basic | 4 | 3 训 / 1 测 | 轮毂-腹板-轮缘盘体 |
| hole | 5 | 3 / 1 / 1 | + 周向安装孔阵列 |
| groove | 5 | 3 / 1 / 1 | + 环槽 / 减重孔 / 冷却孔 / 径向切槽 |
| slot | 8 | 5 / 1 / 2 | + 枞树形榫槽 |
| coupled | 6 | 4 / 1 / 1 | + 榫槽 + 孔阵列 + 环槽 |
| complex_rim | 4 | 2 / 0 / 2 | 厚轮缘 + 曲线过渡 + 榫槽 |

---

## 二、核心模块

| 文件 | 职责 |
|------|------|
| `design_families.py` | 32 族种子定义（类别 / split / 主体尺寸 / 特征） |
| `param_templates.py` | 确定性模板 → RawGcadDocument（盘体 / 榫槽 / 孔 / 环槽 / 切槽 / 环形腔） |
| `candidate_sampler.py` | 三区采样（feasible / boundary / infeasible）→ candidates.json |
| `sampling_constraints.py` | 几何约束（孔界 / 节距 / 槽深 / 环槽-孔间隙 / 圆角可放空间） |
| `run_batch.py` | 批量执行（断点续跑 / 失败隔离 / 并发） |
| `preview_collection.py` | 每族 1 个代表盘 preview（STEP + PNG） |
| `collect_families.py` | 全量多组合采集（8 核心产物 + params.json） |
| `mcp_tools.py` | DiskCAD-MCP 质量门（check_degenerate_geometry 等 15 工具） |

---

## 三、关键几何决策

### 盘体
- `_disc_radii(od, bore, form)`：盘体半径**唯一真源**（rim_junc 按 form 系数；
  `sampling_constraints._axisym_radii` 是须同步的副本）
- 12 点 R-Z 轮廓；conical 腹板**越朝外越薄**（rim 侧半厚 `wo_cone = 0.4×rim_half`，
  hub 侧 `web_inner` 更厚）
- complex_rim：s_curve / ellipse / power / arc_out 曲线过渡（幅度 ≤ 6mm，不深入腹板）
- web-rim fillet 按环槽取舍（见下）

### 榫槽（mon_e2b035beb218 基准复刻）
- 逐齿 neck 收窄（0.625×throat，递减 0.125×throat/齿）、lobe 逐齿衰减（0.25×throat/齿）
- 槽底：槽底肩 1.25×throat → 平底 0.875×throat（mon 槽底根半宽 3.5）
- **5 组 fillet**（rad_tip/flank/neck/root/small 按 `fr` 参数化缩放）
- 槽深 `depth ≥ 0.55×rim_radial`（深窄型，槽切透轮缘；上限 rim_radial−3）
- 槽口在轮缘外表面（pattern radius = rim_r）；`R_mm` 用于周向节距约束与论文标注

### 环槽（P5 决策：全部卡环槽）
- `groove_type` 全 **`collar`**（卡环槽）；`mid`（中段集气槽）**停用**，默认值即 collar
- 从**轮缘内壁表面**开口（r = rim_junc 向 +r 挖 gd），截面 [rim_junc, rim_junc+gd]×[z_c±gw/2]
- **grooves = 1**：单道贴下端面 web 交界（槽内缘 z = ∓wb）；**未切除的上端面保留
  web-rim 圆角**（fillet 顶点 8，r=10）
- **grooves ≥ 2**：上下端面**对称**各一道（z_cs = ±(wb+gw/2)），两侧都切除、都无圆角
- 尺寸：**gw = 10**（轴向高度与轮缘整体适配）、**gd ≈ 0.15–0.23×rim_radial**
  （径向切除厚度与轮缘真实厚度适配；coupled 族因榫槽占用轮缘取小值）
- conical 盘 collar 位置用 `wo_cone`（web 交界真实半厚，非 web_outer）

### 孔阵列
- 16 边形近似圆（孔径 4–26mm 误差 <2%）
- 孔外缘距 rim_junc **≥ 14mm**（`gap = max(gd+2, 14)`，避开 fillet 弧边界 →
  防止 0.2mm 退化小边）
- 冷却孔双排：先定外排 `cl_pcd2` 再定内排 `cl_pcd`，双排间距 ≥ hdia + ch

---

## 四、MCP 质量门

`check_degenerate_geometry`（<0.25mm 边 / <0.01mm² 面）、`check_solid_validity`、
`validate_slot_step_roundtrip` 等 15 工具。pipeline 末尾强制门禁，被拒任务跳过 STEP 导出。

---

## 五、当前验证状态

- 全库采样 **268 候选**（feasible 207 / boundary 25 / infeasible 36），参数范围核查全部通过
- 环槽族（D10–D14）与耦合族（D23–D28）preview 全部通过 MCP 门（零退化小边）
- D26 曾因孔边恰贴 fillet_clearance 边界产生 0.2mm 微边 → gap 提到 14 解决
- 环境注意：必须用 `auto_detection_process/.conda/python.exe`
  （系统 python 缺 cadquery / OCP 模块，runtime 报 ModuleNotFoundError）

---

## 六、复现命令

```powershell
cd auto_detection_process
.conda/python.exe _param_experiment/candidate_sampler.py --per-family 12   # 采样候选
.conda/python.exe _param_experiment/preview_collection.py                  # 每族 preview（STEP+PNG）
.conda/python.exe _param_experiment/collect_families.py                    # 全量多组合采集
```

产物：`output/datasets/candidates.json`、`output/collection/<族>/preview/`、
`output/preview_png/<族>.png`。

---

## 七、历史实验（2026-08-03 早期 LLM 参数化验证）

早期验证"参数化文字描述能否驱动 LLM 正确生成轮廓"。结论：**参数化方案基本可行**——
盘面 12 点结构正确、榫槽点数随 teeth 动态变化；小数精度通过"提示词强调保留小数"解决。
后转为**确定性模板**（本 README 一至六节），LLM 不再生成 llm_raw。详见
`FILLET_STRATEGY.md`、`PARAMETRIC_MODEL.md`、`SLOT_PROMPT_ITERATION.md`。
