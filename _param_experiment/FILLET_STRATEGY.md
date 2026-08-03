# 榫槽 fillet_sketch 圆角策略 — 角色语义驱动，保证圆角始终正确

> 日期：2026-08-03
> 目的：在改进后的参数化榫槽（5点/齿结构）上，保证 fillet_sketch 圆角始终正确。

---

## 一、问题背景

旧 prompt 的 fillet_sketch 用**裸顶点索引**（`at_vertex_index=[3,7,11,...]`）绑定旧 3点/齿结构。改进后的参数化榫槽是 **5点/齿结构**（外斜面起点/顶/齿顶平台端/内斜面端/连接线端），裸索引约 50% 错位 → 倒角作用到错误顶点。

**根本解决**：用**角色语义**（construction_role）代替裸索引——每个轮廓点标注"它是榫槽的哪个特征部位"，fillet 规则按角色匹配，与齿数/点数完全解耦。

---

## 二、角色定义（construction_role）

| 角色 | 含义 | 需要圆角 |
|------|------|---------|
| `mouth` | 口部上缘 | 否 |
| `neck` | 齿根/颈部（外斜面起点、内斜面端） | **是（neck_fillet）** |
| `tip_flank_top` | 齿顶外斜面端 | **是（tip_fillet）** |
| `tip_platform_end` | 齿顶平台端 | **是（tip_fillet）** |
| `connector` | 齿间连接线端 | 否（*后续演进为圆角，以 fillet_corners.py 为准*） |
| `bottom_flare` | 槽底外扩角 | **是（bottom_fillet）** |
| `bottom_platform` | 槽底平台端 | 否（*后续演进为圆角，以 fillet_corners.py 为准*） |
| `root` | 根部 | **是（bottom_fillet）** |

### 角色→索引（上侧，齿数 n，上侧点数 = 5+4n）
```
[0] mouth
[1] neck                    # 齿0外斜面起点
对每齿 i（独占 4 点）:
  [2+4i] tip_flank_top
  [3+4i] tip_platform_end
  [4+4i] neck               # 内斜面端
  [5+4i] connector          # 连接线端
底部:
  [5+4n] bottom_flare
  [6+4n] bottom_platform
  [7+4n] root
```
下侧为精确镜像。

### 圆角规则（按角色）
```
tip_fillet   → role ∈ {tip_flank_top, tip_platform_end}   # 齿顶两端
neck_fillet  → role == 'neck'                             # 齿根/颈部
bottom_fillet→ role ∈ {bottom_flare, root}                # 底部
```

---

## 三、三种保证机制（关键）

### 1. 角色驱动选顶点（`fillet_strategy.py: compute_fillet_targets`）
按角色过滤 → 得到需要圆角的顶点索引。齿数变化时自动适配。

### 2. 位置匹配（fillet 后 wire 变化）
`fillet2D` 会把 1 个尖角替换为 2 个圆弧端点 → **wire 顶点数/顺序变化**。裸索引必然错位。
**解决**：缓存原始顶点位置 `(x,y)`，每次圆角在**当前 wire** 上按欧氏距离找最近顶点。

### 3. 半径约束（≤ 相邻最短边/2）
`fillet2D` 若半径大于相邻边的一半会失败（`BRep_API: command not done`）。
**解决**：半径超限时自动减半重试（`r → r/2`）。

### 4. 分半径批量
不同圆角类（tip/neck/bottom）半径不同 → 分 3 次 `fillet2D`（每次一类、同类全部顶点一次调用）。

---

## 四、验证结果（2/3/4 齿）

| 齿数 | 圆角顶点数 | 原始边→圆角后边 | 状态 |
|------|-----------|----------------|------|
| 2 | tip8 + neck6 + bottom4 | 26 → 44 | PASS |
| 3 | tip12 + neck8 + bottom4 | 34 → 58 | PASS |
| 4 | tip16 + neck10 + bottom4 | 42 → 72 | PASS |

演示图：`output/fillet_role_demo.png`（3齿原始 vs 圆角对比）

---

## 五、集成到 sketch_profile 方言

`handle_fillet_sketch` 的现有实现已支持：
- 列表形式 `at_vertex_index=[...]`（同一半径一次 `fillet2D`）
- 单顶点累积（缓存原始 wire + 位置匹配）

**建议改造**（保证正确性）：
1. 给轮廓点标注 `construction_role`（生成器输出时）
2. `at_vertex_index` 参数改名为/兼容 `fillet_roles`（如 `["tip_flank_top","tip_platform_end"]`）
3. handler 内按角色匹配顶点，用位置匹配 + 半径约束应用

这样**无论 LLM 输出哪种点数结构**（5点/齿或 3点/齿），只要角色标注正确，圆角就正确。

---

## 六、产物

- `fillet_strategy.py`：`annotate_roles()` / `compute_fillet_targets()` / `full_indices()` / `apply_fillet_plan()`
- `output/fillet_role_demo.png`：圆角演示图
- 稳健应用逻辑（位置匹配+半径约束）见本实验验证脚本
