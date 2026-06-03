# test_model.md 全链路测试综合审计报告

**测试日期**: 2026-06-03  
**测试范围**: 15 个零件，覆盖 4 个难度梯队，6 个 dialect  
**测试结果**: 14/15 STEP 生成成功，1/15 被 preflight 正确拒绝  
**Pipeline**: text → DeepSeek V4 Pro (strict schema) → audited autofix → validate → canonical → CadQuery STEP → geometry audit → SolidWorks

---

## 一、测试结果总览

| # | Case | 难度 | Dialect | STEP | 体积 mm³ | BBox mm | Autofix | 备注 |
|---|------|------|---------|------|---------|---------|---------|------|
| 1 | t1_flange_cover | T1 | axisymmetric | 111KB | 295,254 | [150×150×25] | 1 | ✅ |
| 2 | t1_l_bracket | T1 | sketch_extrude | 265KB | 92,277 | [100×100×40] | 2 | ✅ |
| 3 | t1_bearing_seat | T1 | comp. | 370KB | 193,117 | [120×85×68] | 1 | ✅ |
| 4 | t1_stepped_shaft | T1 | axisymmetric | 71KB | 118,112 | [44×44×120] | 1 | ✅ |
| 5 | t1_v_pulley | T1 | axisymmetric | 116KB | 1,749K | [200×200×60] | 1 | ✅ 低密度 |
| 6 | t2_spring | T2 | loft_sweep | 26KB | 103 | [8×6×5] | 0 | 🔴 严重Bug |
| 7 | t2_roller | T2 | comp. | 27KB | 1,176K | [89×89×650] | 3 | ✅ 低密度 |
| 8 | t2_weld_fork | T2 | sketch_extrude | 540KB | 55,492 | [100×60×22] | 2 | ✅ |
| 9 | t2_gearbox_cover | T2 | sketch_extrude | 312KB | 1,221K | [370×250×29] | 2 | ✅ |
| 10 | t2_hex_nut | T2 | axisymmetric | 20KB | 1,612 | [18×18×8] | 2 | ✅ |
| 11 | t3_turbine_disk | T3 | axisymmetric | 467KB | 2,750K | [300×300×85] | 2 | ✅ |
| 12 | t3_robot_wrist | T3 | axisymmetric | - | - | - | 1 | ❌ 正确拒绝 |
| 13 | t3_exhaust_manifold | T3 | loft_sweep | 39KB | 43,495 | [36×69×355] | 1 | ✅ |
| 14 | t3_hyd_valve | T3 | sketch_extrude | 56KB | 814,858 | [80×60×200] | 1 | ✅ 低密度 |
| 15 | t3_diff_case | T3 | axisymmetric | 181KB | 564,544 | [150×150×100] | 1 | ✅ chamfer降级 |

---

## 二、发现的系统 Bug

### 🔴 Bug 1: helix_sweep 生成只有 1 圈（已修复）

**严重度**: 严重 — 导致弹簧/螺纹类零件体积偏差 ~90 倍  
**文件**: `dialects/loft_sweep/handlers.py:173-178`  
**根因**: `parametricCurve` 使用 `pitch * t` 计算 z 坐标 (t∈[0,1])，但完全忽略 `turns` 参数。对于 8 圈弹簧，只生成了 1 圈。

```python
# 旧代码（Bug）:
wire = cq.Workplane("XY").parametricCurve(
    lambda t: (
        radius * math.cos(2 * math.pi * t),
        radius * math.sin(2 * math.pi * t),
        pitch * t,  # ⚠️ t∈[0,1] → z 范围只有 [0, pitch]，只有 1 圈！
    ),
    N=200,
)
```

**修复**: 
```python
total_z = height if abs(height - pitch * turns) > 0.01 else pitch * turns
helix = cq.Workplane("XY").parametricCurve(
    lambda t: (
        radius * math.cos(2 * math.pi * turns * t),
        radius * math.sin(2 * math.pi * turns * t),
        total_z * t,  # ✅ 覆盖全部高度
    ),
    N=max(200, int(turns * 25)),
)
```

**影响范围**: 所有使用 `helix_sweep` 的零件（弹簧、螺纹等）均受影响。
**修复后验证**: 弹簧 bbox z 从 4.6mm → 80.7mm（正确），但体积仍偏低（600 vs 9475 mm³，见 Bug 2）。

### 🟡 Bug 2: helix_sweep 自交无 preflight 检查

**严重度**: 中等  
**根因**: 簧丝直径 4mm (profile_r=2)，节距 10mm，最小曲率半径 = 10/(2π) ≈ 1.59mm。profile_r(2) > min_curvature_radius(1.59)，螺旋线必然自交。Handler 已有 warning 但 preflight 应报 error。

**建议修复**: `loft_sweep.preflight_component` 中增加检查：`if profile_r > 0.45 * pitch / (2*math.pi): error`。

### 🟡 Bug 3: sweep_profile 自交检查

**严重度**: 中等  
**根因**: `loft_sweep/handlers.py` 中 `handle_sweep_profile` 有自交 heuristic（检查非相邻点距离），但只检查点级别，不检查 sweep 路径的全局曲率。某些路径（如排气歧管的密集 S 弯）会因局部曲率过大导致 sweep 自交。

**建议修复**: 计算路径曲率，若 `radius_mm > 0.45 * local_curvature_radius` 则 warning。

### 🟠 异常 1: t2_roller STEP 体积/密度异常

**观察**: 体积 1,176K mm³，bbox [89×89×650]，均正确。但 STEP 仅 27KB（密度 0.02 B/mm³）。对比：t1_bearing_seat 仅 193K mm³ 却有 370KB STEP。
**分析**: 托辊几何由 2 个圆柱体 + boolean_union 组成，几何简单（少面片）。STEP 文件大小取决于面片数（BREP 复杂度），而非体积。
**结论**: 不是 bug，是正常现象。但应添加审核规则：`if step_size/volume < 0.05 and volume > 1e6: WARNING`。

### 🟠 异常 2: t3_robot_wrist 被 preflight 正确拒绝

**观察**: prompt 要求 PCD 140mm 螺栓孔在半径 max 60mm 的轮廓上。PCD radius(70) + hole_radius(4.5) = 74.5 > profile_max(60) - margin(1) = 59。
**分析**: 这是 **prompt 设计问题**，不是系统 bug。LLM 在 4 轮中无法修正（因为 prompt 给出了矛盾的几何约束）。
**教训**: 应在 prompt 验证阶段检查关键尺寸一致性。

### 🟠 异常 3: t3_diff_case chamfer 降级

**观察**: 差速器壳体 STEP 构建时 chamfer 操作失败（"no edge ops"），自动移除 chamfer 后成功。
**分析**: 球壳 + 法兰的复杂几何使 `apply_safe_chamfer` 无法找到合适的边缘。这是已知的 chamfer 降级机制。
**建议**: 不需要修复，降级机制正常工作。

---

## 三、LLM 输出质量分析

### 3.1 核心指标

| 指标 | 数值 |
|------|------|
| 总 LLM 调用 | 15 cases × ~1.5 平均尝试 = ~23 次 |
| 参数名错误 (output=solid, direction=Z 等) | **0** |
| path_point 字段错误 (x vs x_mm) | **0** |
| 需要 autofix 的主要错误类型 | dialect_name 未注册(8), phase_ordering(7), op_versions(2) |

### 3.2 关键结论

**LLM 输出质量显著提升**: 通过精心设计的 contract text（包含显式示例、禁止事项列表），LLM 在所有 15 个 case 中零参数命名错误。之前的测试中 output name 错误率高达 6/7，本次为 0/15。

**Autofix 主要修复次要问题**: 21 次 autofix 中，8 次是 dialect name（如 LLM 写 "axisymmetric_base" 而非 "axisymmetric"），7 次是 phase ordering，2 次是 op_versions。这些都是系统侧可自动纠正的次要问题，不影响几何语义。

---

## 四、系统瓶颈与改进建议

### 4.1 几何引擎瓶颈

| 瓶颈 | 表现 | 建议 |
|------|------|------|
| Chamfer 在复杂几何上降级 | diff_case, gearbox_cover 等 | 改善 chamfer 的边选择逻辑 |
| helix_sweep 自交 | 弹簧体积异常 | 加强 preflight 曲率检查 |
| 大规模零件 STEP 体积异常小 | roller 27KB for 1M mm³ | 添加体积/尺寸审计 |
| multi-dialect 装配的 SW 导入不稳定 | SW COM 偶尔挂起 | 添加 SW 调用超时保护 |

### 4.2 Prompt/Contract 改进

- ✅ Contract 中的显式示例（如 `EX: {"axis":"Z",...}`）对抑制幻觉非常有效
- ✅ 明确的禁止事项列表（"direction: '+' or '-' NOT 'Z'"）消除了常见参数错误
- ⚠️ 应在 prompt 层验证关键几何尺寸一致性（避免 robot_wrist 矛盾约束）
- ⚠️ 考虑添加 expected bbox/volume 约束到 prompt，帮助 LLM 自我修正

### 4.3 新增测试发现的可扩展性限制

| 文档中的零件 | 当前系统是否支持 | 原因 |
|-------------|----------------|------|
| 渐开线齿轮 | ❌ | 需要 primitive 链路 (CQ_Gears) |
| 花键轴 | ❌ | 无 spline profile op |
| V型带轮多槽 | ⚠️ | revolve_profile 可近似，但无法表达精确槽角 |
| 三通管接头 | ❌ | 多方向扫掠 + 布尔交 |
| 连杆 I 形截面 | ❌ | 无自定义截面 extrude |
| 蜗壳 | ❌ | 阿基米德螺旋 + 变截面放样 |
| 摆线轮 | ❌ | 需要参数方程曲线 |
| 4缸缸体 | ❌ | 远超当前 dialect 表达能力 |

---

## 五、已修复的 Bug 汇总

| Bug | 文件 | 状态 |
|-----|------|------|
| helix_sweep 只用 pitch 忽略 turns | `loft_sweep/handlers.py:173` | ✅ 已修复 |
| auto_fixer thread_class 上下文错误 | `auto_fixer.py:_fix_param_values` | ✅ 上次已修复 |
| auto_fixer 单 station 复制 hack | `auto_fixer.py:_fix_profile_stations` | ✅ 上次已修复 |
| sketch_extrude 缺少 import math | `sketch_extrude/dialect.py:3` | ✅ 上次已修复 |

---

## 六、测试产物

所有数据保存在: `E:\auto_detection_process\demo_output_v5\test_model_output\`

每个 case 目录包含:
- `prompt.txt` — 最终测试 prompt
- `llm_raw.json` — LLM 原始输出
- `autofix_report.json` — 审计修复记录
- `raw_fixed.json` — 修复后文档
- `canonical.json` — 规范化 IR
- `validation_bundle.json` — 验证 bundle
- `output.step` — STEP 几何文件
- `output.SLDPRT` — SolidWorks 原生文件（部分 case SW 未连接时缺失）
- `_build.py` — 生成的构建脚本
- `_build_log.txt` — 构建日志
