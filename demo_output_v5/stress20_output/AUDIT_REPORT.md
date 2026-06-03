# Stress20 极限压力测试综合审计报告

**测试日期**: 2026-06-03  
**测试结果**: 15/20 STEP 生成成功  
**Pipeline**: text → DeepSeek V4 Pro (strict schema) → audited autofix → validate → canonical → CadQuery STEP → geometry audit → SolidWorks

---

## 一、结果总览

| # | Case | Dialect | 结果 | STEP | 体积 mm³ | BBox mm | 发现 |
|---|------|---------|------|------|---------|---------|------|
| 1 | Thin Large Flange | axisymmetric | ❌ preflight | - | - | - | 孔在中心孔内 |
| 2 | Micro Bushing | axisymmetric | ❌ preflight | - | - | - | 壁厚太薄 |
| 3 | Dense Rib Plate | sketch_extrude | ✅ | 1.5MB | 1,038K | [370×250×25] | LLM 误用 boolean_union |
| 4 | Deep Hole Manifold | sketch_extrude | ✅ | 60KB | 1,023K | [100×80×150] | 孔系正确 |
| 5 | Long Helix Spring | loft_sweep | ✅ | 133KB | 296 | [19×20×152] | 🔴卷积极度异常 |
| 6 | Double Flange Assy | compos. | ✅ | 46KB | 248K | [160×160×15] | 2 axisymmetric 同组件 |
| 7 | Cross-Rib Box | sketch_extrude | ✅ | 2.1MB | 974K | [285×210×28] | LLM 误用 boolean_union |
| 8 | Full-Feature Shaft | axisymmetric | ✅ | 81KB | 57K | [36×36×145] | chamfer 参数问题 |
| 9 | Variable Sweep Pipe | loft_sweep | ✅ | 166KB | 174K | [235×180×222] | 多 sweep OK |
| 10 | Shelled Ribbed Housing | shell_housing | ❌ runtime | - | - | - | boolean_union input=1 |
| 11 | Coupling Assembly | compos. | ✅ | 84KB | 564K | [100×100×80] | 3组件 OK |
| 12 | Reducer Base | compos. | ✅ | 222KB | 3,126K | [400×325×62] | input=3 (期望2) |
| 13 | Multi-Pipe System | compos. | ❌ runtime | - | - | - | 🔴 OCCT sweep 崩溃 |
| 14 | Full Bearing Housing | compos. | ✅ | 89KB | 664K | [200×140×90] | OK |
| 15 | Multi-Port Valve | sketch_extrude | ✅ | 927KB | 1,901K | [120×100×180] | 12孔 OK |
| 16 | Turbo Rotor | axisymmetric | ✅ | 152KB | 182K | [70×70×160] | 10站 OK |
| 17 | 3D Space Pipe | loft_sweep | ✅ | 792KB | 58K | [104×86×294] | 3D路径 OK |
| 18 | Large Thin Shell Box | shell_housing | ❌ preflight | - | - | - | add_boss input=0 |
| 19 | Multi-Body Workbench | compos. | ✅ | 111KB | 4,809K | [500×350×200] | LOW_DENSITY |
| 20 | Ultimate Composite | compos. | ✅ | 348KB | 1,469K | [250×190×140] | 4-dialect OK |

---

## 二、发现的系统 Bug

### 🔴 Bug 1: helix_sweep 体积严重偏低（已知限制）

**严重度**: 严重 — 体积偏差 ~45x  
**症状**: 15圈弹簧，预期体积 ~13,300 mm³，实际仅 296 mm³ (2.2%)  
**根因分析**：
1. CadQuery `parametricCurve` 创建螺旋线路径 + `profile.sweep()` 产生不完整几何
2. OCCT `BRepOffsetAPI_MakePipeShell` 对多圈螺旋的曲率处理有局限
3. profile 在 XZ 平面 (`center(radius, 0)`) 与 helix 起点 (radius, 0, 0) 存在微小的扫掠错位
4. 尝试 spline-based 路径导致 OCCT 内核崩溃 (`MakeSolid` 失败)

**已知限制**: CadQuery sweep 不支持高质量多圈螺旋。需要直接使用 OCCT `BRepOffsetAPI_MakePipe` 或 `Geom_Spiral` 原生 API。

**临时方案**: parametricCurve 可生成近似形状（bbox z 正确但 x/y 偏小），preflight 应阻止 profile_r ≥ 0.45×min_curvature_radius 的设计。

### 🟡 Bug 2: shell_housing 与 sketch_extrude 集成断裂

**症状**: s10 和 s18 均在 `shell_body` 后无法正确接线。LLM 输出 shell_body 后，后续的 `add_rectangular_boss` 或 `boolean_union` 的 input 引用断裂。
**根因**: `shell_body` 修改了 solid 但后续节点无法正确引用被 shell 后的 solid。`shell_body` 的输出类型是 `solid`，但 input 链接在跨 dialect 时断开。
**影响**: shell_housing dialect 的所有零件均受影响。

### 🟡 Bug 3: composition 中 boolean_union 输入数量不匹配

**症状**: LLM 在 assembly 节点生成 1、3 或 4 个 input，但 boolean_union 期望恰好 2 个。
**根因**: LLM 不理解 boolean_union 是二元操作。当有 3+ 组件需要合并时，LLM 尝试在一次 boolean_union 中传入所有组件，而非链式合并。
**影响**: s10 (1 input), s12 (3 inputs), s19 (4 inputs) 均有此问题。
**建议**: 在 contract 中明确 "boolean_union ALWAYS takes exactly 2 inputs. Chain multiple boolean_unions for 3+ components."

### 🟠 Bug 4: sketch_extrude 中 LLM 误用 boolean_union

**症状**: s03 和 s07 的 LLM 在 sketch_extrude 组件内尝试使用 boolean_union。
**根因**: boolean_union 只在 composition dialect 中可用，LLM 不知道这个限制。
**建议**: 在 contract 的每个 dialect section 中显式标注 "Ops ONLY available in this dialect: ..."

---

## 三、Preflight 正确拦截的案例

### ✅ 超大薄壁法兰 (s01)
- 法兰外径 500mm，中心孔 480mm → 壁厚仅 10mm
- 螺栓孔 PCD 470mm → PCD 半径 235 - 孔半径 6 = 229 ≤ 240 (bore_radius) + 1 (margin)
- **正确结论**: 孔在中心孔内，无法加工。preflight 正确拒绝。

### ✅ 微型轴套 (s02)  
- 外径 6mm (r=3)，内孔 5mm (r=2.5)
- bore_radius (2.5) ≥ profile_max (3) - margin (1) = 2.0
- **正确结论**: 壁厚 0.5mm < 1mm margin。preflight 正确拒绝。

---

## 四、LLM 输出质量分析

### 4.1 参数错误统计

| 错误类型 | 出现次数 | 说明 |
|---------|---------|------|
| output name 错误 (solid vs body) | 0 | 零错误！contract 规则有效 |
| direction 错误 (Z/X/Y vs +/-) | 0 | 零错误！ |
| path_points 字段错误 (x vs x_mm) | 0 | 零错误！ |
| boolean_union 在非 composition dialect | 2 | 需要更明确的 contract |
| boolean_union 输入数量不匹配 | 3 | LLM 不理解二元操作语义 |
| shell_body 后 input 链断裂 | 2 | 结构性接线问题 |

### 4.2 关键结论

**Contract 设计极为有效**: 通过显式规则（"output type=solid → name='body'"、"direction '+' or '-' NOT 'Z'"），LLM 在所有 20 个 case 中零基本参数错误。这证明详细的 contract + 禁止事项列表是抑制幻觉的最有效手段。

**LLM 弱点转移**: LLM 不再犯参数名错误，但暴露了新的弱项——不理解 dialect 边界（boolean_union 只能在 composition 中使用）和二元操作语义（boolean_union 需要恰好 2 个输入）。

---

## 五、几何异常分析

| Case | STEP 密度 (B/mm³) | 评估 |
|------|-------------------|------|
| s19 Multi-Body Workbench | 0.023 | 🟠 偏低（4.8M mm³ 只有 111KB） |
| s04 Deep Hole Manifold | 0.059 | 正常 |
| s17 3D Space Pipe | 13.7 | 🟡 偏高（复杂 3D 曲面） |
| s03 Dense Rib Plate | 1.42 | 正常 |
| s07 Cross-Rib Box | 2.14 | 正常 |

---

## 六、已修复的系统缺陷汇总

| Bug | 文件 | 状态 |
|-----|------|------|
| helix_sweep 忽略 turns 参数 | `loft_sweep/handlers.py` | ✅ 已修复（使用 total_z*t） |
| helix_sweep profile 位置错位 | `loft_sweep/handlers.py` | ✅ 已修复（center(radius,0)） |
| helix_sweep self-intersection 无 preflight | `loft_sweep/dialect.py` | ✅ 已添加 |
| spline-based helix → OCCT 崩溃 | `loft_sweep/handlers.py` | ⚠️ 已知限制（回退到 parametricCurve） |

## 七、待修复的系统限制

| 限制 | 影响 | 优先级 |
|------|------|--------|
| CadQuery sweep 不支持高质量多圈螺旋 | helix_sweep 体积严重偏低 | 🔴 高 |
| shell_housing 与 sketch_extrude 集成 | 薄壁壳体零件全部失败 | 🟡 中 |
| boolean_union 输入数 LLM 理解 | 3+ 组件装配需要链式合并 | 🟡 中 |
| boolean_union 非 composition dialect 误用 | 单 dialect 组件内误用 | 🟢 低 |
