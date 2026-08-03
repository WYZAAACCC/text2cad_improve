# 涡轮盘盘面 + 枞树形榫槽 — 完整参数化建模方案

> 依据：`docs/KT787-JB-215 枞树形榫头、榫槽结构设计技术方法研究及程序软件.docx`（北航 2015）
> 行业标准：**HB5965-2002《枞树形榫头、榫槽尺寸注法与技术要求》**
> 补充：Fir-tree root 优化设计论文（工作面/非工作面齿面角 Tfa/Ufa、齿距、齿端圆角等）

---

## 一、当前参数化方案的不足（需修正）

| 不足 | 当前方案 | 真实设计要求 |
|------|---------|-------------|
| 不同齿齿高相同 | 单一 `lobe_half_width_mm` 所有齿共用 | 每个齿有独立的齿根高 `M_H1` + 齿顶高 `M_H2`、齿距 `M_W1`（HB5965） |
| 齿间水平连接 | `neck` 用水平平台连接 | 齿间是**楔形斜面**（楔角 `M_A1` 20~40°，承力面斜置） |
| 齿端平顶 | 凸台顶部是水平段 | 齿端是**圆弧**（齿端倒角 `M_B1~M_B4`，半圆形齿） |
| 单一齿面角 | 一个 `flank_angle_deg` | **工作面角 ≠ 非工作面角**（Tfa/Ufa，齿形角 `M_A2` + 压力角 `M_A3`） |
| 齿位均匀 | 按 `slot_depth` 均匀布齿 | 齿距 `M_W1` 逐齿可变，基准面 `M_R1` 定位首个齿 |

---

## 二、完整参数体系（HB5965 体系 + 补充）

### 2.1 全局参数（涡轮盘级）

| 参数 | 含义 | 来源 |
|------|------|------|
| `slot_count` | 涡轮盘周向榫槽数（= 叶片数） | `MM_N` |
| `broach_angle_deg` | 榫槽拉削角（中心平面与子午面夹角） | `MM_A` |
| `reference_radius_mm` | 基准面径向位置（第一齿节线距轴线） | `M_R1` |
| `slot_depth_mm` | 槽总深（颈部→槽底） | `M_R2` |
| `mouth_half_width_mm` | 槽口半宽 | — |
| `mouth_wedge_ratio` | 口部楔形（入口斜面跨度占比） | — |
| `wedge_angle_deg` | 节线间楔角（控制齿间斜面整体倾角） | `M_A1` |

### 2.2 每齿参数（数组，长度 = `teeth_count`）

| 参数 | 含义 | 来源 |
|------|------|------|
| `pitch_mm[i]` | 第 i 齿节线距基准面的径向距离 | `M_W1` |
| `tooth_thickness_mm[i]` | 第 i 齿节线处齿厚 | `M_W2` |
| `tooth_height_mm[i]` | 第 i 齿齿高（齿根→齿顶径向跨度） | `M_H1+M_H2` |
| `top_flank_angle_deg[i]` | 第 i 齿**工作面**齿面角（承力面，较陡） | `Tfa` / `M_A2` |
| `under_flank_angle_deg[i]` | 第 i 齿**非工作面**齿面角（背侧） | `Ufa` / `M_A3` |
| `tip_fillet_mm[i]` | 第 i 齿**齿端圆角**（半圆齿） | `M_B1..4` |
| `root_fillet_mm[i]` | 第 i 齿**齿根圆角** | trough radius |
| `neck_half_width_mm[i]` | 第 i 齿颈部半宽（齿间凹处） | `M_W3/2` |

### 2.3 底部参数

| 参数 | 含义 | 来源 |
|------|------|------|
| `bottom_half_width_mm` | 槽底半宽 | — |
| `bottom_fillet_mm` | 槽底圆角 | — |

### 2.4 齿高/圆角工程约束（论文资料）

- 齿高 : 齿端圆角半径 ≈ **1.5:1 ~ 2:1**（齿越高，圆角越大）
- 楔角 20~40°；齿面角典型 60°±1°（齿面间夹角）
- 齿距典型 2~4 mm；齿端圆角 0.2~1.0 mm
- 齿数一般 **2~6 对**

---

## 三、轮廓生成规则（每侧，从槽口向中心）

```
设齿 i 节线径向位置 x_pitch[i]（由 reference_radius + 累计 pitch 决定）
  齿根（颈部）在 x_root[i] = x_pitch[i] + 齿根高分量（靠外）
  齿顶在 x_tip[i] = x_pitch[i] - 齿顶高分量（靠内）
  齿高 h[i] = tooth_height_mm[i]

轮廓点（一侧，y≥0，从 x=0 向内）：
  1. 口部上缘: (0, mouth_half_width)
  2. 口部楔形: (x_mouth, neck_half_width[0])          # 入口斜面
  对每个齿 i（外→内）：
  3. 外斜面(承力面): (x_root[i], neck_half_width[i]) → (x_tip[i], w_tip[i])
        w_tip[i] = neck_half_width[i] + h[i]·tan(top_flank_angle[i])
  4. 齿顶平台: (x_tip[i] - tooth_thickness[i], w_tip[i])   # 水平
  5. 内斜面(非承力面): (齿顶末端) → (x_next, neck_half_width[i+1])
        dx = (w_tip[i] - neck_half_width[i+1]) / tan(under_flank_angle[i])
  6. **颈部水平平台**: (x_next, neck_half_width[i+1]) → (x_next - neck_platform, neck_half_width[i+1])
        # ← 齿间连接线：内斜面 → 水平颈部平台 → 下一齿外斜面（重要修正）
  （最后一个齿）→ 槽底:
  7. 槽底: (x_bottom, bottom_half_width) → 槽底平台 → 根部收窄
下侧为关于 y=0 中心线的**轴对称镜像**（x 不变，仅 y 取负；切勿用中心对称(-x,-y)）。
```

**关键改进**：
- 每个齿的 `h[i]`、`tooth_thickness[i]`、`top/under_flank_angle[i]` 独立 → **不同齿齿高/齿厚/齿面角可变**
- **齿高递减**：`tooth_height[i]` 应从外到内递减（越远离圆心齿高越高；槽口处齿最高、槽底处齿最矮）
- 齿间由**内斜面 + 水平颈部平台**连接（非直接 V 形）→ **连接线正确**
- 齿端/齿根用 `tip_fillet`/`root_fillet` 圆弧过渡 → **半圆形齿端**
- 口部楔形、槽底圆角完善全轮廓

---

## 四、参数组合示例（供验证）

### 组合 S1：三齿，齿高递减（真实盘）
```
teeth_count=3, slot_depth≈24, mouth_half_width=4
tooth_height:    [4, 3, 2]            # 齿高递减：越远离圆心越高（修正）
tooth_thickness: [2, 2, 2]            # 各齿齿厚
top_flank:       [45, 45, 45]         # 外斜面(承力面)与径向夹角
under_flank:     [40, 40, 40]         # 内斜面(非承力面)与径向夹角
neck_half_width: [2, 2.2, 2.5, 3]     # 各颈部半宽 + 槽底颈部
neck_platform:   1.0                  # 齿间颈部水平平台
tip_fillet:      [0.8, 0.7, 0.6]
root_fillet:     [0.5, 0.5, 0.5]
```

### 组合 S2：两齿，陡工作面角 + 大圆角（KT787 半圆齿风格）
```
teeth_count=2, top_flank=[50,50], under_flank=[35,35]
tooth_height=[4,3]                    # 齿高递减
tooth_thickness=[2,2]
tip_fillet=[1.5,1.0], neck_half_width=[2,2.5,3], neck_platform=1.0
```

### 组合 S3：四齿，对称齿面角，齿高递减
```
teeth_count=4, top_flank=[45]*4, under_flank=[45]*4
tooth_height=[3, 2.5, 2, 1.5]         # 齿高递减
neck_half_width=[1.5,1.8,2.0,2.2,2.5], neck_platform=0.8
```

---

## 五、与盘面参数化的衔接

盘面参数化（已通过方案 A 验证）保持，增加 `reference_radius_mm` 与盘面 `rim_radius` 关联：
```
榫槽基准面位置 reference_radius_mm ≈ rim_radius_mm（榫槽开在轮缘）
```

---

## 六、后续验证路径

1. **确定性生成器**：写 `fir_tree_parametric.py` 从参数直接计算轮廓点（ground truth），绘制不同组合对比图，验证几何正确性（含斜面连接、齿高差异、圆角）
2. **LLM 实验（方案 A+完整参数）**：用完整参数化描述替换当前简化描述，验证 LLM 能否忠实输出逐齿参数并正确推导轮廓
3. **规则遵守强化**：提示词明确"每齿必须 4 点 + 齿间斜面"，或加后置校验/自动补点（解决 3 齿漏点问题）
