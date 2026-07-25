# OCAF/TNaming 持久化拓扑命名 — 实施状态报告 v1.1

> 编制日期: 2026-07-25
> 对比基线: 《Text-to-CAD / OCAF 持久化拓扑命名落地实施指导书 v1.0》(经 v1.1 环境修正)
> 实际环境: Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · Git 678c073

---

## 1. 总体判断

**系统处于原型验证阶段 (PoC/MVP)。** 核心概念已验证，但距离指导书定义的"生产可用的持久化拓扑命名系统"存在关键差距。

代码规模: 13 个新增源文件, ~1500 行, 4 个修改文件, ~120 行增量。

---

## 2. 指导书目标 vs 实际达成

### 2.1 最终目标 (指导书 §1.1)

| 目标链环节 | 指导书要求 | 实际状态 | 差距 |
|-----------|----------|---------|------|
| Canonical IR → handler | 不改 | ✅ flag 控制, 默认不变 | — |
| handler → CadQuery/OCCT build | 一次执行 | ✅ 使用相同 OCCT Builder | — |
| result + same-builder History | 同源 | ✅ BOPAlgo_BOP+BRepPrimAPI_MakePrism/MakeRevol | 覆盖 5/8 操作 |
| staged live evolution batch | 暂存 | ✅ CaptureSession | — |
| geometry validation | 不改 | ✅ 原有逻辑不变 | — |
| OCAF/TNaming commit | 写入 | ✅ TNaming_Builder + XBF save/reopen | NamedShape 读回未验证 |
| Selector / PID / proof class | 跨 revision | ❌ **TNaming_Selector 不可用** | **致命差距** |
| CAE preflight | 失败关闭 | ❌ 未实现 | 无 FEA 桥接 |

### 2.2 成功定义 (指导书 §1.2)

| 验收标准 | 状态 | 详情 |
|---------|------|------|
| 启用 History Probe 后几何不变 | ✅ | STEP 15499 bytes 完全一致 |
| 不会为历史执行第二次 Build | ✅ | `SetToFillHistory(True)` + 一次 `Perform()` |
| OCAF 保存为 XBF, 重开后恢复 | ⚠️ | 保存/重开 OK, Label 树存在, NamedShape 读回未验证 |
| 轻微参数扰动时 Selector Solve | ⚠️ | FaceSelector 可通过 10% 扰动, 50% 失败 |
| 分裂/合并/删除/歧义 返回结构化状态 | ⚠️ | UNIQUE/UNRESOLVED 状态 OK, AMBIGUOUS 路径存在但未充分测试 |
| CAE 错误绑定率 0 | ❌ | 未连接 FEA |
| 未覆盖操作明确降级 | ⚠️ | 部分 handler 回退原路径, 但无结构化降级记录 |

---

## 3. 指导书 PR 计划 vs 实际实施

| PR | 指导书目标 | 实际交付 | 偏差 |
|----|----------|---------|------|
| PR-0 | 基线+ABI 审计 | ✅ 完成。发现基线 678c073 无 P0-04/05/06 ABI 问题 | 原基线 ed6f6603 已过时 |
| PR-1 | Capture Core | ✅ tracked_ops/boolean/extrude/revolve + fillet | CadQuery 不提供 History API, 改为 OCCT Builder 层包装 |
| PR-2 | 同源建模 History | ✅ composition/sketch_profile 接入 | sketch_extrude 推迟至 PR-7 |
| PR-3 | OCAF Writer | ✅ document.py + writer.py | Label 分配简化, 原子保存简化 |
| PR-4 | Selector/Revision | ❌ **TNaming_Selector 不可用** | 改用 FaceSelector (几何指纹) |
| PR-5 | 后处理覆盖 | ✅ tracked_fillet | Clean/Unify 无 History (OCP 已知限制) |
| PR-6 | Registry/CAE | ❌ **未实现** | Registry 源码已删除, FEA 桥接未做 |
| PR-7 | 工程化 | ⚠️ 部分 | sketch_extrude 接入, 管道集成 `ocaf_path`, 演示脚本 |

---

## 4. 关键问题详解

### 4.1 🔴 致命: TNaming_Selector 不可用

**这是当前系统与指导书设计之间最根本的差距。**

指导书设计的跨 revision 选择链路:
```
TNaming_Selector.Select(face, context) → Solve(context) → 跨 revision 找回同一面
```

**实际**: OCP 7.8.1.1 中 `TNaming_Selector.Select()` 返回 True, 但 `IsIdentified_s()` **始终返回 0**——选择从未真正持久化。OCP 的 Python 绑定未正确暴露 TNaming_Selector 需要的 NamedShape 上下文传递路径。

**当前替代**: `FaceSelector` — 几何指纹匹配 (面积 + 质心 + 曲面类型)。这本质上是**几何快照比较**, 而非**拓扑路径追踪**。

**FaceSelector 的根本局限** (实验验证):

| 场景 | TNaming_Selector (理论) | FaceSelector (实际) | 差距 |
|------|------------------------|-------------------|------|
| Box 20x20x10 → 22x22x10 (+10%) | ✅ 拓扑路径不变 | ✅ area diff=21%, dist=0.63<3.0 | 可接受 |
| Box 20x20x10 → 200x200x10 (10x) | ✅ 拓扑路径不变 | ❌ **UNRESOLVED** area diff=99x, dist=57>3.0 | **不可接受** |
| 孔 R=10→R=20 (4x area) | ✅ 孔壁仍是孔壁 | ❌ 可能失败 | 取决于阈值 |
| 面分裂 (1→2) | ✅ 返回 AMBIGUOUS | ⚠️ 可能选"最近"面 | 无拓扑信息 |

**结论**: FaceSelector 可以处理**小参数扰动**, 但无法替代真正的拓扑路径追踪。任何大幅参数变化都可能导致失败。

**可能的解决路径**:
- A. 升级 OCP/OCCT 到修复了 TNaming_Selector 的版本
- B. C++ 写 TNaming 桥接层, 绕过有问题的 Python 绑定
- C. 在 Python 层自己实现拓扑路径追踪 (基于 `TopExp_Explorer` + `TopoDS_Shape.IsSame()` + `BRepTools_History` 的 Generated/Modified 映射)

### 4.2 🟡 中: 管线集成不完整

- `enable_topology_capture = False` (默认) — 所有现有管线行为完全不变, 但也意味着**拓扑捕获永远不会发生**
- `run_canonical_gcad(ocaf_path=...)` 参数存在但需要调用者显式传入
- 6/20+ handler 函数接入, 常用操作 (`cut_hole_v2`, `drill_hole_3d`, `cut_rim_slot_pattern` 等) 未覆盖
- Tapered extrude / "both" direction extrude 回退原路径 (无 History)

### 4.3 🟡 中: OCAF NamedShape 读回未验证

- XBF 保存/重开: ✅
- Label 树存在: ✅ (8 labels)
- TNaming_Tool.NamedShape_s(label) 可读回: ❌ **未验证**
- 原因: OCP 7.8.1.1 的 `NamedShape_s` 需要 `(TopoDS_Shape, TDF_Label)` 参数, 但重开后我们拿到的是新的 TopoDS_Shape 对象, 无法与原始 shape 做精确匹配

### 4.4 🟡 中: 无 Registry 集成

- 原始 `topology/registry.py` 源码已在基线回退时删除 (仅 `__pycache__` 残留)
- 当前系统没有业务层 PID 注册表
- FaceSelectionRecord 是独立存储, 不与其他系统共享

### 4.5 🟡 中: 无 FEA/CAE 桥接

- FEA 3D 管线 (`fea3d/`) 存在但完全独立
- 拓扑指纹无法自动映射到 CAE 边界条件面 (bore 温度面、rim 温度面、对称约束面)
- 指导书要求的关键 CAE 错误绑定率 0 无法验证

---

## 5. 环境发现汇总

| 项目 | 指导书假设 | 实际 | 影响 |
|------|----------|------|------|
| CadQuery History API | `shapes.History` 类存在 | ❌ CadQuery 2.7.0 不提供 | 改为 OCCT Builder 层包装 |
| TNaming_Selector | `Select() → Solve()` 可用 | ❌ `IsIdentified_s` 恒返回 0 | 致命——Selector 链路断裂 |
| TDocStd_Document 构造 | `TDocStd_Document('BinXCAF')` | ❌ 需要 `TCollection_ExtendedString` | 已修正 |
| Clean/Unify History | `ShapeUpgrade_UnifySameDomain.History()` | ❌ OCP 7.8.1.1 无此方法 | 需 CadQuery patch |
| P0 ABI 问题 | 存在 | ❌ 基线 678c073 无 V3 代码 | 简化了实施 |

---

## 6. 当前可工作的垂直切片

```
tracked_revolve(涡轮盘剖面)
    → BRepPrimAPI_MakeRevol.Build() (一次执行)
    → builder.Generated(edge) → 4 EvolutionRelations (EXACT_KERNEL)
    → CaptureSession.stage()
    → OCAF write: TNaming_Builder.Generated(...) → 8 labels
    → XBF save: 5290 bytes
    → XBF reopen: label tree restored
    → FaceSelector.select_face(bore, face[0]) → FaceFingerprint
    → FaceSelector.solve(bore_fp, perturbed_body) → UNIQUE (R=60→65, OK)
    → FaceSelector.solve(bore_fp, extreme_body) → UNRESOLVED (R=60→100, FAIL)
```

---

## 7. 下一步建议 (按优先级)

| 优先级 | 任务 | 理由 |
|--------|------|------|
| **P0** | 解决 TNaming_Selector 不可用问题 | 这是系统与指导书之间最根本的差距。没有真正的拓扑路径追踪, 持久化命名就是几何猜测。 |
| P1 | 验证 OCAF NamedShape 读回 | 证明 XBF 不是黑盒——重开后可以正确恢复 NamedShape |
| P1 | 集成到生产管线默认启用 | 需要性能测试 + 错误隔离 + fallback 机制 |
| P2 | 补全 handler 覆盖 | cut_hole_v2, drill_hole_3d 等常用操作 |
| P2 | FEA 桥接 POC | 将拓扑指纹映射到 fea3d 边界条件 |
| P3 | Registry 重建 | 业务层 PID 管理 + CAE 门禁 |
| P3 | Revision Bridge | 跨 revision 身份连续性 |
