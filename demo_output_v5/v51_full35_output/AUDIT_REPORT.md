# v5.1 全量35 Case 回归审计报告

**测试**: 2026-06-03 | **结果**: 27/35 STEP 构建成功 (77%)  
**Pipeline**: Text → LLM (strict schema + full contract) → audited autofix → validate → canonical → STEP → semantic postcheck

---

## 一、结果概览

| 分类 | 数量 | 占比 |
|------|------|------|
| ✅ STEP 构建成功 + Semantic 通过 | 27 | 77% |
| ❌ Preflight 正确拒绝 (几何矛盾) | 2 | 6% |
| ❌ CadQuery 限制 (helix 体积) | 2 | 6% |
| ❌ 结构性缺陷 (shell/sweep/LLM) | 4 | 11% |

## 二、失败详细分析

### 🔴 CadQuery 限制 (2 cases)

| Case | 错误 | 详情 |
|------|------|------|
| tm06_spring | volume ratio=0.052 | helix_sweep 体积只有理论值 5.2%, v5.1 fail-closed 正确阻止 |
| s05_long_spring | volume ratio=0.020 | helix_sweep 体积只有理论值 2%, v5.1 fail-closed 正确阻止 |

**根因**: CadQuery `parametricCurve` + `sweep` 对多圈螺旋产生严重偏小的几何。OCCT `MakePipeShell` 无法正确处理螺旋路径扫掠。需要直接使用 OCCT `Geom_Spiral` API 或 `BRepOffsetAPI_MakePipe` 原生接口。

### 🟡 几何矛盾 (2 cases)

| Case | 错误 |
|------|------|
| s01_thin_flange | 螺栓孔 PCD 470mm 在中心孔 480mm 内 |
| s15_multi_valve | 孔位置超出 base 范围 |

**根因**: Prompt 中存在矛盾几何约束。Preflight 正确拒绝。

### 🟡 LLM 错误 (1 case)

| Case | 错误 |
|------|------|
| tm12_robot_wrist | LLM 输出含非法控制字符, JSON 解析失败 |

### 🟡 结构性缺陷 (3 cases)

| Case | 错误 | 类型 |
|------|------|------|
| s10_shelled_box | `shell_body` 在 sketch_extrude component 中 | 🔴 cross-dialect component |
| s13_pipe_system | OCCT `BRep_API: command not done` sweep | 🟡 sweep 崩溃 |
| tm15_diff_case | chamfer 操作失败 | 🟡 边缘特征降级 |

**s10 根因**: `shell_body` 属于 `shell_housing` dialect, 但 LLM 将其放在 `sketch_extrude` 组件中。运行时用 `sketch_extrude` 查询 `shell_body` op spec 失败。需要系统侧将 shell_housing 节点分离到独立组件, 或在 runtime 中按节点 dialect 分派。

**s13 根因**: 主汇流管用 2 点路径 + radius=30mm 做直线扫掠, OCCT `BRepOffsetAPI_MakePipeShell` 内部失败。可能原因: 前序 boolean_union 产生了不良 solid 被 sweep 消费。

## 三、v5.0→v5.1 对比

| Case | v5.0 | v5.1 | 变化原因 |
|------|------|------|---------|
| tm06_spring | ✅ PASS (vol=103, 2%) | ❌ FAIL | 新增 volume verification fail-closed |
| s05_long_spring | ✅ PASS (vol=296, 2%) | ❌ FAIL | 同上 |
| tm10_hex_nut | ❌ param名错误 | ✅ PASS | 全量 contract = 显式示例 |
| tm11_turbine_disk | ❌ param名错误 | ✅ PASS | 同上 |
| tm12_robot_wrist | ❌ param名错误 | ❌ LLM错误 | prompt修正了参数名但LLM输出损坏 |
| tm15_diff_case | ✅ PASS | ❌ BUILD_FAIL | chamfer 在新 assembler 下失败 |
| s02_micro_bushing | ❌ 壁厚太薄 | ✅ PASS | preflight正确性未变, LLM调整了参数 |

## 四、修复的 Bug

| Bug | 文件 | 修复 |
|-----|------|------|
| 🔴 弹簧 preflight 公式过度保守 (~6x) | `loft_sweep/dialect.py:265` | `pitch/(2π)→0.45*pitch` |
| 🔴 Handler 曲率警告公式相同错误 | `loft_sweep/handlers.py` | 同上修复 |
| 🟡 紧凑 contract 缺显式示例 | runner | 使用完整 contract builder |

## 五、系统健康度评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 基础几何 (axisymmetric) | ⭐⭐⭐⭐⭐ | 15/16 case 通过 |
| 板件 (sketch_extrude) | ⭐⭐⭐⭐⭐ | 10/10 case 通过 |
| 装配 (composition) | ⭐⭐⭐⭐ | 6/8 case 通过 |
| 扫掠 (loft_sweep sweep) | ⭐⭐⭐⭐ | 4/5 case 通过 |
| 螺旋 (loft_sweep helix) | ⭐⭐ | 0/2 standalone 通过 (CadQuery 限制) |
| 抽壳 (shell_housing) | ⭐⭐ | 1/2 通过 (cross-dialect issue) |
| LLM 参数准确性 | ⭐⭐⭐⭐⭐ | 0 参数名错误 (full contract 有效) |
| Semantic postcheck | ⭐⭐⭐⭐⭐ | 27/27 成功 case 全部通过 |

## 六、顶层建议

1. **helix_sweep 终极修复**: 放弃 CadQuery sweep, 使用 OCCT `Geom_Spiral` + `BRepOffsetAPI_MakePipe` 直接构建
2. **cross-dialect component**: 系统应将 mixed-dialect 节点的 component 自动分离或 runtime 按节点 dialect 分派
3. **sweep fallback**: 对 OCCT 崩溃的 sweep 提供 fallback (polyline+fillet 近似)
