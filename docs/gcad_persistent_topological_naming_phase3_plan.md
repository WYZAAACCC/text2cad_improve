# Phase 3 实施规划：History-aware Boolean + Hole Semantic Naming + Split/Merge

> **前置条件：Phase 1+2 已交付 (56 tests, 0 failures)**
> **OCP 环境确认：BRepAlgoAPI_Fuse/Cut + BRepTools_History + Generated/Modified/IsDeleted 全部可用**
> **策略：构建 history-aware boolean wrapper + hole 语义命名，修改 cut_hole handler 返回 TopologyDelta**

---

## 0. 环境事实 (已验证)

```
OCP.BRepAlgoAPI_Fuse:     Generated(), Modified(), IsDeleted(), History() = ALL AVAILABLE
OCP.BRepAlgoAPI_Cut:      Generated(), Modified(), IsDeleted(), History() = ALL AVAILABLE
OCP.BRepTools_History:    Full API available (AddGenerated, AddModified, Generated, Modified, Remove, Merge...)
OCP.BRepAlgoAPI_BuilderAlgo: HasHistory(), History(), SetToFillHistory() = AVAILABLE
CadQuery 2.7.0:           Available
```

**关键发现**：调用 `SetToFillHistory(True)` 后，boolean maker 会填充完整的历史记录。

---

## 1. Phase 3 范围

### 核心目标

1. **History-aware boolean wrappers** — `history_aware_boolean_fuse()` / `history_aware_boolean_cut()` 使用 OCP BRepAlgoAPI + BRepTools_History
2. **Hole semantic naming** — `name_hole_faces()` 命名 tool body 面 → hole 语义 (hole_wall / entry_rim / exit_rim)
3. **Split/Merge handling** — TopologyRegistry 的 split/merge 方法已存在 (Phase 1)，Phase 3 填充实际数据
4. **修改 handle_cut_hole** — 首个 handler 返回带有 topology_delta 的 OperationResult (v2_result 模式)
5. **Split/Merge delta 构建** — 从 boolean history 构建包含 SPLIT/MERGE 关系的 TopologyDelta

### 不对 boolean_union/boolean_cut handler 做大改

原因：这些 handler 有复杂的三层降级逻辑 (CadQuery → OCP Fuse → Fuzzy Fuse)。添加 topology 应该在最后一层成功时捕获。保持最小改动原则。

---

## 2. 文件变更清单

### 新增文件 (2 个)

| 文件 | 职责 |
|---|---|
| `topology/history_wrappers.py` 扩展 | +2 函数：`history_aware_boolean_fuse()`, `history_aware_boolean_cut()` |
| `topology/semantic_naming.py` 扩展 | +2 函数：`name_hole_faces()`, `name_hole_tool_faces()` |

### 修改文件 (4 个)

| 文件 | 修改 |
|---|---|
| `topology/models.py` | TopologyDelta 增加 `split_entities` / `merged_entities` 辅助字段 (可选) |
| `dialects/sketch_extrude/handlers.py` | `handle_cut_hole` 改用 v2_result + topology_delta |
| `dialects/composition/handlers.py` | `handle_boolean_cut` 末尾插入 topology capture (最小改动) |
| `dialects/executor.py` | 无需修改 — _apply_topology_delta_if_present 已存在 |

### 新增测试 (1 个)

| 文件 | 内容 |
|---|---|
| `test_topology_phase3.py` | Boolean history + hole naming + split/merge + handler integration |

---

## 3. 详细设计

### 3.1 `history_aware_boolean_fuse()`

```python
def history_aware_boolean_fuse(
    arg_shape, tool_shape,
    *,
    input_arg_faces: list[Any] | None = None,
    input_tool_faces: list[Any] | None = None,
    tolerance: float | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT boolean fuse with full history capture.
    
    Steps:
    1. Create BRepAlgoAPI_Fuse(arg, tool)
    2. Call SetToFillHistory(True) BEFORE Build()
    3. Build()
    4. For each input_arg_face: query Modified() → modified argument faces
    5. For each input_tool_face: query Modified() → modified tool faces  
    6. Query Generated() for intersection faces
    7. Return HistoryAwareShapeResult with KernelHistorySnapshot
    """
```

### 3.2 `history_aware_boolean_cut()`

```python
def history_aware_boolean_cut(
    target_shape, tool_shape,
    *,
    input_target_faces: list[Any] | None = None,
    input_tool_faces: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT boolean cut with full history capture.
    
    Key mapping for hole operations:
      tool lateral face → Generated(intersection) → hole wall
      tool cap edges → Generated(intersection) → entry/exit rim
      target face at intersection → Modified
      tool body faces → IsDeleted = True
    """
```

### 3.3 `name_hole_faces()`

```python
def name_hole_faces(
    tool_solid,           # cutter cylinder BEFORE the cut
    result_solid,         # result solid AFTER the cut
    *,
    document_id, component_id, producer_node_id,
    is_through_hole: bool = True,
) -> TopologyDelta:
    """Name faces of a hole by mapping tool body faces to hole semantics.
    
    Method:
    1. Classify tool faces: lateral (CYLINDER) / cap_start (PLANE, Z-) / cap_end (PLANE, Z+)
    2. Map to hole semantics:
       - tool/lateral → hole_wall (the cylindrical hole wall in result)
       - tool/cap_start → entry_rim (circular edge at hole entry)
       - tool/cap_end → exit_rim (circular edge at hole exit, only if through)
    3. Record tool faces as DELETED (consumed by cut)
    4. Record modified target faces (the face the hole was cut into)
    
    For blind holes: exit_rim is marked as zero_or_one (may be absent).
    """
```

### 3.4 TopologyDelta split/merge 增强

TopologyDelta 已有 `relations: list[TopologyRelation]`，其中 `TopologyRelation.relation` 支持 `"split"` 和 `"merged"`。Phase 3 填充这些：

- **Split**：一个旧的 target face 被 hole 分割成多个面 → `relation="split"`, `source_ids=[old_face_id]`, `result_entity_keys=[new_face_1_id, new_face_2_id]`
- **Merged**：boolean union 后多个面合并为一个 → `relation="merged"`, `source_ids=[old_a, old_b]`, `result_entity_keys=[new_face_id]`
- **Deleted**：tool body faces → `relation="deleted"`, `source_ids=[tool_lateral_id, ...]`

### 3.5 handle_cut_hole 修改 (最小改动)

```python
# BEFORE (current):
def handle_cut_hole(node, ctx) -> dict[str, str]:
    ...
    result = body.cut(cutter)
    return {"body": _store_solid(node, ctx, result)}

# AFTER (Phase 3):
def handle_cut_hole(node, ctx) -> dict[str, str]:  # or OperationResult for v2
    ...
    # Build topology delta BEFORE cut
    tool_delta = name_cylinder_faces(cutter, ...)
    
    # Execute cut with history capture
    history_result = history_aware_boolean_cut(
        body.val().wrapped, cutter.val().wrapped,
        input_tool_faces=cutter.faces().vals(),
    )
    
    result = body.cut(cutter)
    
    # Build hole topology delta AFTER cut
    hole_delta = name_hole_faces(
        cutter, result,
        document_id=canonical.document_id,
        component_id=node.component,
        producer_node_id=node.id,
    )
    
    return {
        "body": _store_solid(node, ctx, result),
        "_topology_delta": hole_delta,  # or return OperationResult
    }
```

**但是**：handle_cut_hole 当前返回 `dict[str, str]` (v1_dict)。要让它返回 TopologyDelta，需要改为返回 `OperationResult` (v2_result)。这需要确保 executor 正确处理。

实际上，executor 已经支持 v2_result。让我利用这一点。

---

## 4. 实施顺序

```
Phase 3.1: history_wrappers.py 扩展 — history_aware_boolean_fuse/cut
Phase 3.2: semantic_naming.py 扩展 — name_hole_faces
Phase 3.3: sketch_extrude/handlers.py — handle_cut_hole 改为 v2_result + topology_delta
Phase 3.4: composition/handlers.py — handle_boolean_cut 末尾加 topology capture
Phase 3.5: 运行全部测试确保零回归
Phase 3.6: 写入 Phase 3 测试 (boolean history + hole naming + split/merge)
```

---

## 5. 验收标准

- [ ] `history_aware_boolean_fuse()` 返回包含 generated/modified/deleted 的 history snapshot
- [ ] `history_aware_boolean_cut()` 正确记录 tool face deletion + target face modification
- [ ] `name_hole_faces()` 生成包含 hole_wall / entry_rim / exit_rim 的 TopologyDelta
- [ ] `handle_cut_hole` 返回带有 topology_delta 的 OperationResult
- [ ] 所有 Phase 1+2 测试继续通过
- [ ] Phase 3 新增 15+ 测试通过 (含真实 CadQuery boolean)
