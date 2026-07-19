# Phase 4 实施规划：Fillet / Chamfer / Shell — persistent edge selection + history

> **前置条件：Phase 1-3 已交付 (67 tests, 0 failures)**
> **OCP 环境确认：BRepFilletAPI_MakeFillet/MakeChamfer + BRepOffsetAPI_MakeThickSolid 全部有 Generated/Modified/IsDeleted**
> **约束：CadQuery `body.fillet(r)` 不暴露单边历史 → Phase 4 构建 OCP 层 wrapper，暂不修改 handler**

---

## 0. 关键发现

```
OCP BRepFilletAPI_MakeFillet:  Generated(), Modified(), IsDeleted() = ALL AVAILABLE
OCP BRepFilletAPI_MakeChamfer: Generated(), Modified(), IsDeleted() = ALL AVAILABLE
OCP BRepOffsetAPI_MakeThickSolid: Generated(), Modified(), IsDeleted() = ALL AVAILABLE

CadQuery fillet:  body.fillet(r) → applies to ALL edges, no per-edge history
CadQuery chamfer: body.chamfer(d) → same limitation
CadQuery shell:   body.faces('<Z').shell(thickness) → removes selected face
```

**策略**：
- 构建 OCP 级 wrapper（捕获完整历史），但不强制 handler 使用
- 添加 fillet/chamfer/shell 语义命名函数
- handler 修改推迟到有明确的 OCP history 测试需求时
- 当前价值：补完 contracts + wrappers + naming 覆盖，为 Phase 5/6 铺路

---

## 1. Phase 4 范围

### 新增/扩展

| 文件 | 操作 | 内容 |
|---|---|---|
| `topology/history_wrappers.py` | 扩展 | `history_aware_fillet()`, `history_aware_chamfer()`, `history_aware_shell()` |
| `topology/semantic_naming.py` | 扩展 | `name_fillet_faces()`, `name_chamfer_faces()`, `name_shell_faces()` |
| `topology/contracts.py` | 扩展 | `FILLET_CONTRACT` 更新，新增 `CHAMFER_CONTRACT`, `SHELL_CONTRACT` |
| 不修改 handler | — | fillet/chamfer/shell handler 使用 CadQuery 高层 API，暂不强制 OCP history |

### 核心设计

#### `history_aware_fillet(shape, edges_with_radii)`

```python
def history_aware_fillet(
    shape,
    edges_with_radii: list[tuple[Any, float]],  # [(edge, radius), ...]
    *,
    input_faces: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCP fillet with per-edge history.
    
    For each input edge: IsDeleted() → edge consumed
    For each input face: Modified() → face changed (adjacent to filleted edge)
    Generated() → new fillet round face
    """
```

#### `history_aware_chamfer(shape, edges_with_distances)`

```python
def history_aware_chamfer(
    shape,
    edges_with_distances: list[tuple[Any, float]],  # [(edge, distance), ...]
) -> HistoryAwareShapeResult | None:
    """OCP chamfer — same pattern as fillet with different Add() API."""
```

#### `name_fillet_faces(result_solid, *, selected_edge_ids)`

```python
def name_fillet_faces(
    result_solid,
    *,
    document_id, component_id, producer_node_id,
    selected_edge_ids: list[str],  # persistent IDs of filleted edges
) -> TopologyDelta:
    """Classify fillet faces by surface type (CYLINDER/SPHERE/TORUS).
    Map old edges → deleted, new curved faces → fillet_face_from/<edge_id>.
    Adjacent planar faces → modified_adjacent_face.
    """
```

---

## 2. 实施顺序

```
4.1: history_wrappers.py — history_aware_fillet/chamfer/shell
4.2: contracts.py — 更新 FILLET_CONTRACT + 新增 CHAMFER/SHELL
4.3: semantic_naming.py — name_fillet_faces/name_chamfer_faces/name_shell_faces
4.4: 运行全部测试确保零回归
4.5: 写入 Phase 4 测试
```

## 3. 验收标准

- [ ] `history_aware_fillet()` 使用 OCP BRepFilletAPI，返回包含 generated/modified/deleted 的 snapshot
- [ ] `history_aware_chamfer()` 同上
- [ ] `name_fillet_faces()` 将新曲面分类为 fillet_face，旧边标记 deleted
- [ ] 所有 67 个已有测试零回归
- [ ] Phase 4 新增 10+ 测试通过
