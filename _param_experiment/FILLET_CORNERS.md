# 榫槽圆角 — LLM 指定"角 + 半径"方案（保证不漏）

> 日期：2026-08-03
> 需求：LLM 指定"要圆角的点 + 两条边 + 半径"，程序在草图中圆角，且**不漏任何一个该圆的角**。

---

## 一、核心机制（保证不漏）

```
① 程序生成【必须圆角的角清单】（基于几何/角色规则）→ 每个角 = 顶点 + 两条邻边
② LLM 为清单中【每一个角】指定 radius_mm（设计决策）
③ 程序验证覆盖：LLM 是否覆盖全部角？漏了 → 反馈补齐
④ 程序按顶点（及两条邻边）执行圆角
```

**"不漏"的关键**：必须圆角的角由程序从几何规则推导（而非 LLM 自由决定），LLM 只需为每个角填半径。程序验证 `required ⊆ provided`，缺一个都反馈。

---

## 二、必须圆角的角清单（几何规则）

| 角 key | 角色 | 含义 | 圆角类型 |
|--------|------|------|---------|
| `neck@0` | neck | 齿0外斜面起点（口部楔形角） | 齿根圆角 |
| `tip_flank_top@i` | tip_flank_top | 齿i 齿顶外斜面端（凸角） | 齿顶圆角 |
| `tip_platform_end@i` | tip_platform_end | 齿i 齿顶平台端（凸角） | 齿顶圆角 |
| `neck@i` | neck | 齿间/最后颈部（凹角） | 齿根圆角 |
| `bottom_flare@-1` | bottom_flare | 槽底外扩角（凹角） | 底部圆角 |
| `root@-1` | root | 根部（凹角） | 底部圆角 |

数量：2齿 = 12 角、3齿 = 16 角、4齿 = 20 角（= 4×齿数 + 4，含 connector 与 bottom_platform）

每个角含：`{role, tooth_index, key, vertex(点坐标), edge_a, edge_b(两条邻边)}`

---

## 三、LLM 指定格式（tool schema）

```json
{
  "fillets": [
    {"role": "tip_flank_top", "tooth_index": 0, "radius_mm": 0.8},
    {"role": "neck", "tooth_index": 1, "radius_mm": 0.5},
    {"role": "bottom_flare", "tooth_index": -1, "radius_mm": 0.6},
    ...
  ]
}
```

- `role`：tip_flank_top / tip_platform_end / neck / bottom_flare / root
- `tooth_index`：tip 用齿号(0..n-1)；neck 用颈部号(0..n)；bottom 用 -1
- **LLM 用 role+tooth 定位"点"**，程序解析出顶点坐标和两条邻边（edge_a/edge_b）——即用户要求的"点 + 两条边"

**为什么用 role+tooth 而非裸坐标**：LLM 做几何坐标不可靠（已证明），role+tooth 是语义定位，LLM 100% 可靠。

---

## 四、验证覆盖（`verify_coverage`）

```python
ok, missing, extra, dup = verify_coverage(corners, llm_fillets)
# ok=False 时，missing 列出漏掉的角 → 反馈 LLM 补齐
```

实测：2齿/3齿 LLM 全覆盖 **PASS**（9/9、12/12，无遗漏、无多余、无重复）。

---

## 五、执行圆角（`execute_fillets`）

按 LLM 指定的 `(role, tooth_index) → 顶点坐标`，用**位置匹配**（fillet 后 wire 变化，按最近距离找当前顶点）+ **半径约束**（超限减半）执行 `fillet2D`。

实测：2齿 26→50 边、3齿 34→66 边，全部成功（含下侧镜像 + connector/bottom_platform）。

---

## 六、完整流程产物

```
角清单(list_required_corners) → LLM 指定(llm_schema+prompt) → 验证(verify_coverage) → 执行(execute_fillets)
```

- `fillet_corners.py`：角清单 / schema / 验证 / 执行
- `fillet_llm_test.py`：LLM 全覆盖测试
- `output/fillet_corners_demo.png`：圆角演示图

---

## 六b、碰撞安全（关键 — 圆角半径过大导致碰撞）

**根因（用户经验）**：齿间两个相邻角（如 `neck@1` 和 `connector@1`）共享 2mm 连接线；若两个角都用大半径，圆角在共享边上**碰撞** → `fillet2D` 失败 → 旧实现静默跳过 → "很多地方没有圆角"。

**约束（`compute_safe_radius`）**：
1. **邻边约束**：半径 ≤ `min(邻边)/2`
   - 多数角安全半径 ≤ 1.0；`root` ≤ 0.9（邻边 1.80）
2. **相邻碰撞约束**：相邻两角半径之和 ≤ 共享边长
   - 齿顶两端（`tip_flank_top`+`tip_platform_end`）共享 2.00mm 平台 → 和 ≤ 2.00
   - 齿根两端（`neck`+`connector`）共享 2.00mm 连接线 → 和 ≤ 2.00

**验证**：请求 tip=1.2/1.5/2.0 均被 clamp 到 ≤1.0；12 个角全部圆角成功（26→50 边，无静默失败）。

---

## 七、与 sketch_profile 方言集成的建议

把 `handle_fillet_sketch` 的 `at_vertex_index`（裸索引）升级为**角清单驱动**：
1. 生成器输出轮廓点并标注 `construction_role`
2. `at_vertex_index` 参数改为接受 `[{role, tooth_index, radius_mm}]`（或兼容旧索引）
3. handler 内：解析角色 → 顶点+邻边 → 位置匹配 fillet
4. 验证覆盖，漏角反馈
