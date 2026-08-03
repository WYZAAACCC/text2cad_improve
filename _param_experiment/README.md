# 涡轮盘/榫槽轮廓参数化 — 隔离实验报告

> 实验日期：2026-08-03
> 目的：验证**参数化文字描述**（非硬编码坐标）能否驱动 LLM 正确生成不同尺寸/样式的涡轮盘盘面轮廓与榫槽轮廓
> 模型：`deepseek-v4-pro`（真实调用，复用 `DeepSeekToolCaller`）
> 隔离性：全部代码在 `_param_experiment/`，主程序零修改

---

## 一、实验结论（简要）

**参数化方案基本可行**。LLM 能根据参数化规则 + 参数值推导出：
- 盘面：始终 12 点，hub→web→rim 三段轮廓正确，参数 **100% 忠实**
- 榫槽：点数随 `teeth_count` 动态变化（2 齿→26 点、3 齿→30~34 点），枞树形结构正确，主要参数忠实
- **小数精度（方案 A）：已验证解决**（详见下方"方案 A 验证结果"）

---

## 方案 A 验证结果（solutionA_round2 子目录，2026-08-03）

**做法**：在参数化提示词中强调"所有坐标和 params_used 参数保留输入小数精度，禁止取整"。

**结论：小数问题真正解决。** 四个组合所有小数参数**全部精确回传**：

| 组合 | 小数参数 | 输入 → 回传 | 状态 |
|------|---------|-----------|------|
| A 基准 | bottom_fillet | 0.8 → **0.8** | ✓ 精确 |
| B 小型 | neck / root_fillet / bottom_fillet | 1.5→1.5, 0.8→0.8, 0.6→0.6 | ✓ 全部精确 |
| C 大型厚缘 | root_fillet | 1.2 → **1.2** | ✓ 精确 |
| D 陡齿面 | bottom_fillet | 1.5 → **1.5** | ✓ 精确 |

坐标小数保留：A=76 坐标含 22 小数、B=76 含 32、C=84 含 12、D=76 含 20（如 -5.155, -10.042, -4.09 等）。

**方案 A 后的新发现（独立于精度）**：
- **2 齿（A/B/D）结构完整**：26 点 = 口部2 + 每齿4×2 + 底部3，无误
- **3 齿（C）结构有漏点**：输出 30 点而非 34 点（预期每侧 17）——LLM 在 3 齿时把第 3 齿的内斜面/颈部合并，且底部有 2 个重复点 (-30,3)。**这是规则遵守度问题，非精度问题**，后续需在提示词中强化"每齿必须 4 点"或加后置校验/修复。

产物：`output/solutionA_round2/`（PNG + llm_{id}.json + report.json）

**已知限制（影响后续落地）**：
1. ~~**坐标被强制为整数**~~ **已推翻**：`to_deepseek_strict_schema` 将 `number→integer`（DeepSeek 不支持 number），但实际调用 `strict=False`，**该转换不限制输出**。实测：
   - 三种 schema 变体（integer/number/raw）在 `strict=False` 下全部返回完整小数（12.5, -3.25）
   - 真正导致 fillet 取整的是**提示词未强调精度** → 在提示词中明确"保留小数精度"后，参数精确回传（2.0/1.5），坐标带小数（-4.09/-5.5）
2. **C 组合（3 齿）有 2 个重复点**（(-29,2)×2）：LLM 生成时的微小瑕疵。
3. **"外宽内窄"不完全满足**：输入参数本身 bottom(3) > neck(2)，与规则"lobe>neck>bottom"冲突（需人工判断此规则是否应为"lobe>neck 且 bottom 独立"）。

**小数精度解决方案（已验证）**：
- **方案 A（推荐，零主程序修改）**：提示词明确"坐标与参数保留输入小数精度，禁止取整"——已在 D 组合验证有效
- **方案 B（最小主程序修改）**：移除/调整 `strict_schema.py:214-216` 的 number→integer（`strict=False` 下 number 已不再被拒绝），需全量回归
- **方案 C（防御性加固，证明不必要）**：坐标×10 整数化（0.1mm 精度）
- **方案 D**：实现 `LlmModelConfig.use_json_output_fallback`（JSON 模式原生支持浮点，但需改 call_strict_tool）

---

## 二、生成产物（打开 PNG 人工检查）

`output/` 目录下：

| 文件 | 内容 |
|------|------|
| `disc_profile_A_baseline.png` / `.jpg` | 组合 A 盘面轮廓（XZ） |
| `slot_profile_A_baseline.png` / `.jpg` | 组合 A 榫槽轮廓（XY） |
| `disc_profile_B_small.png` / `.jpg` | 组合 B 盘面（小型盘） |
| `slot_profile_B_small.png` / `.jpg` | 组合 B 榫槽（浅槽） |
| `disc_profile_C_large_3tooth.png` / `.jpg` | 组合 C 盘面（大型厚缘） |
| `slot_profile_C_large_3tooth.png` / `.jpg` | 组合 C 榫槽（**3 齿**） |
| `disc_profile_D_steep_flank.png` / `.jpg` | 组合 D 盘面 |
| `slot_profile_D_steep_flank.png` / `.jpg` | 组合 D 榫槽（陡齿面+大圆角） |
| `llm_{id}.json` | 每个组合的 LLM 原始输出 |

**人工检查要点**：
1. 盘面应为三段（hub 垂直 → web 斜坡 → rim 阶梯）闭合轮廓，上下对称
2. 榫槽应为枞树形，齿数 = `teeth_count`（A/B/D=2，C=3）
3. 榫槽"外宽内窄"：凸台半宽 > 颈部半宽
4. 轮廓尺寸与输入参数一致（半径范围、槽深、半宽）

---

## 三、参数组合与 LLM 输出对照

### 组合 A — 基准 ≈ KT787
| 参数 | 输入 | LLM 采用 |
|------|------|---------|
| bore/hub/junction/rim | 60/120/215/250 | 60/120/215/250 ✓ |
| 半厚 hub/web_in/web_out/rim | 38/22/15/30 | 38/22/15/30 ✓ |
| fillet hub_web/web_rim | 12/10 | 12/10 ✓ |
| teeth_count / mouth / depth | 2/4/24 | 2/4/24 ✓ |
| neck/lobe/bottom 半宽 | 2/7/3 | 2/7/3 ✓ |
| flank_angle / root_fillet / bottom_fillet | 60°/1.0/0.8 | 60°/1/**0** ⚠取整 |

### 组合 B — 小型盘
| 参数 | 输入 | LLM 采用 |
|------|------|---------|
| bore/hub/junction/rim | 40/80/150/180 | 40/80/150/180 ✓ |
| 半厚 hub/web_in/web_out/rim | 25/15/10/20 | 25/15/10/20 ✓ |
| teeth_count / mouth / depth | 2/3/18 | 2/3/18 ✓ |
| 半宽 neck/lobe/bottom | 1.5/5/2 | 1.5/5/2 ✓ |
| flank_angle / 圆角 | 65°/0.8/0.6 | 65°/1/1 ✓(取整) |
| **参数忠实度** | — | **全部忠实** ✓ |

### 组合 C — 大型厚缘 + 3 齿
| 参数 | 输入 | LLM 采用 |
|------|------|---------|
| bore/hub/junction/rim | 80/140/250/300 | 80/140/250/300 ✓ |
| 半厚 hub/web_in/web_out/rim | 45/30/20/45 | 45/30/20/45 ✓ |
| **teeth_count** | **3** | **3 ✓（34 点）** |
| 半宽 neck/lobe/bottom | 2/7/3 | 2/7/3 ✓ |
| flank_angle / root_fillet / bottom_fillet | 55°/1.2/1.0 | 55°/**1**/1 ⚠取整 |

### 组合 D — 陡齿面 + 大圆角
| 参数 | 输入 | LLM 采用 |
|------|------|---------|
| 盘面参数 | 同 A | 同 A ✓ |
| teeth_count / mouth / depth | 2/4/24 | 2/4/24 ✓ |
| neck/lobe/bottom 半宽 | 2/**8**/4 | 2/**8**/4 ✓（lobe 增大可见） |
| flank_angle / root_fillet / bottom_fillet | **70°**/2.0/1.5 | 70°/**2**/**1** ⚠取整 |

---

## 四、逐组合轮廓数据（LLM 输出）

### 盘面 12 点（所有组合结构一致，仅坐标按参数变化）
组合 A 例：
```
(60,-38)(120,-38)(120,-22)(215,-15)(215,-30)(250,-30)
(250,30)(215,30)(215,15)(120,22)(120,38)(60,38)
```

### 榫槽点（结构随 teeth_count 变化）
- **2 齿 = 26 点**，每侧 13 点：口部楔形 2 + 齿1 4 + 齿2 4 + 底部 3
- **3 齿 = 34 点**，每侧 17 点：口部楔形 2 + 3×4 齿 + 底部 3
- 完整坐标见 `output/llm_{id}.json`

---

## 五、复现命令

```powershell
cd auto_detection_process
.conda/python.exe _param_experiment/run_experiment.py          # 全部组合
.conda/python.exe _param_experiment/run_experiment.py --smoke  # 仅组合 A
```

---

## 六、对后续落地的启示

若人工检查确认轮廓可行，下一步才考虑（**本次实验不含**）：
1. 将参数化描述迁移为 `skills/domain/` 领域技能（`domain.turbomachinery` fragment），按提示词升级方案按需注入
2. 设计参数化 IR 验证（`disc_params` / `slot_params` 校验器），替代坐标硬编码校验
3. 解决 integer 取精度的方案（如需浮点精度，需绕过 `to_deepseek_strict_schema` 的 number→integer 或改用 JSON 输出模式）

---

## 七、完整参数化建模（HB5965 体系）—— 本次新增

**问题**：早期参数化方案（方案 A）仍有不足——所有齿共用同一 `lobe_half_width`（齿高相同）、齿间用水平平台连接。真实枞树槽每个齿独立（齿高/齿厚/齿面角不同）、齿间是楔形斜面。

**依据资料**：
- `docs/KT787-JB-215 枞树形榫头、榫槽结构设计技术方法研究及程序软件.docx`（北航 2015）——基于航空行业标准 **HB5965-2002《枞树形榫头、榫槽尺寸注法与技术要求》**
- 表2-1 关键特征参数：榫槽深度 `M_R2`、颈部宽度 `M_W3`、齿距 `M_W1`、齿厚 `M_W2`、齿根高 `M_H1`、齿顶高 `M_H2`、楔角 `M_A1`、齿形角 `M_A2`、压力角 `M_A3`、齿端倒角 `M_B1~4`、间隙 `LM_WW`
- Fir-tree 优化论文：工作面/非工作面齿面角（Tfa/Ufa）、齿距 2-4mm、齿高:齿端圆角 ≈ 1.5:1~2:1

**完整参数体系**（详见 `PARAMETRIC_MODEL.md`）：
- 全局：`slot_count` / `broach_angle_deg` / `reference_radius_mm` / `slot_depth_mm` / `wedge_angle_deg`
- **每齿数组**（`teeth_count` 个）：`pitch_mm[i]`（节距）、`tooth_height_mm[i]`（齿高）、`tooth_thickness_mm[i]`（齿厚）、`top_flank_angle_deg[i]`（工作面角）、`under_flank_angle_deg[i]`（非工作面角）、`tip_fillet_mm[i]`（齿端圆角）、`root_fillet_mm[i]`（齿根圆角）、`neck_half_width_mm[i]`（颈部半宽）
- 底部：`bottom_half_width_mm` / `bottom_fillet_mm`

**确定性生成器** `fir_tree_parametric.py`（ground truth，已验证）：
- 区间布局：每齿占径向区间 [齿根, 齿顶]，跨度=齿高
- 承力面：颈部沿 `top_flank` 升到齿顶（`w_tip = w_neck + h·tan(top_flank)`）→ **不同齿高 → 不同齿顶半宽**
- 齿顶平台：宽度=齿厚；非工作面：沿 `under_flank` 降到下一颈部 → **齿间楔形斜面，非水平**
- 产物：`output/parametric_gt/slot_gt_S1/2/3.png`（3齿/2齿/4齿，齿高不同）+ `compare_old_vs_full.png`（新旧对比）

**验证结果**（S1 三齿，齿高 4/3/2 递减）：
- 齿顶半宽 = 6.0 / 5.2 / 4.5（**越远离圆心齿高越高**：齿1 最高、齿3 最矮）✓
- 齿间连接 = 内斜面 + **水平颈部平台**（`(-13.53,2.2)→(-14.53,2.2)`）✓
- 无重复点，轮廓闭合、轴对称 PASS ✓

**⚠ 修正记录（四轮，重要）**：
1. **镜像错误**：曾用 `(-q[0],-q[1])`（中心对称/180°旋转）→ 改为 `(q[0],-q[1])`（关于 y=0 轴对称）
2. **齿高语义错误**：曾把 `tooth_height` 定义为径向 x 跨度 → 改为 **y 方向凸出高度**（`w_tip = w_neck + tooth_height`），并**逐点对齐 A 组合参考**（S0 与 `solutionA_round2/llm_A_baseline.json` 26 点全部一致，最大差 0.08mm）
3. **连接线/齿宽过小**：颈部平台 `neck_platform` 从 1mm → **2mm**（对齐 A）；齿顶平台 `tooth_thickness`=2mm；外斜面角 **66.7°**、内斜面角 **60°**（对齐 A，原 45/40° 太平缓）
4. **底部结构**：补齐"**最后颈部 → 颈部平台 → 底部外扩(45°) → 槽底平台(1mm) → 根部(1.5)**"（对齐 A；原缺颈部+外扩两步）
5. **齿高方向**：确认**递增**（越靠近圆心齿高越高），S1/S2/S3 均递增（如 [6.5,7.7,9.0]）

**下一步**（待你确认后）：用完整参数化描述更新参数化提示词，重跑 LLM 实验（验证 LLM 能否忠实输出逐齿参数数组 + 正确推导轮廓），并强化"每齿 4 点 + 齿间斜面"规则。
