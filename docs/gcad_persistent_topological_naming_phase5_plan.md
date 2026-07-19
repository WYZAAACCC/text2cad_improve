# Phase 5 实施规划：Loft / Sweep + Fingerprint Computation

> **前置：Phase 1-4 + PR 7 已交付 (77 tests, 0 failures)**
> **关键发现：helix_sweep 已使用 OCP BRepOffsetAPI_MakePipe；loft_sections 已使用 native OCP ThruSections**
> **策略：最小 Phase 5 — history wrappers + naming + fingerprint 计算 + contracts**

---

## 0. 代码探查发现

### Loft/Sweep 现状

| Handler | 当前实现 | OCP 级别 | 历史 API |
|---|---|---|---|
| `handle_loft_sections` | `native_loft_sections()` (OCP) → CadQuery fallback | 部分 | ThruSections 有 IsDone()，无 Generated |
| `handle_sweep_profile` | `make_circular_pipe_along_path()` (OCP) → CadQuery fallback | 部分 | MakePipe 有 IsDone() |
| `handle_helix_sweep` | `BRepOffsetAPI_MakePipe` (OCP) 直接调用 | **完全** | MakePipe → 可直接加 adapter |
| `handle_create_sweep_path` | 纯路径数据 | N/A | N/A |

### 关键约束

- `ProfileSection` (loft 截面) 没有 stable element_id
- Path points 没有 identity
- `BRepOffsetAPI_ThruSections` 和 `BRepOffsetAPI_MakePipe` 派生自 `BRepBuilderAPI_MakeShape` → 有 `Generated()/Modified()/IsDeleted()`

### Phase 5 最小可行范围

考虑到 loft/sweep 的使用频率远低于 extrude/revolve/hole/boolean，Phase 5 应聚焦于：

1. **History wrappers** — `history_aware_loft()`, `history_aware_sweep()`
2. **Semantic naming** — `name_loft_faces()` (按截面顺序分类), `name_sweep_faces()`
3. **Fingerprint computation** — `compute_face_fingerprint()` — 从 CadQuery/OCP face 计算 FaceFingerprint
4. **Contracts** — `LOFT_CONTRACT`, `SWEEP_CONTRACT`, `HELIX_SWEEP_CONTRACT`

**不修改 handler** — loft/sweep 已有复杂降级链，修改风险高。

---

## 2. 文件变更清单

### 新增函数（扩展现有文件）

| 文件 | 新增 | 说明 |
|---|---|---|
| `topology/history_wrappers.py` | `history_aware_loft()`, `history_aware_sweep()` | OCP ThruSections/MakePipe wrapper |
| `topology/semantic_naming.py` | `name_loft_faces()`, `name_sweep_faces()` | 按截面/路径分类面 |
| `topology/fingerprint.py` | `compute_face_fingerprint()` | 从 CadQuery face 计算 FaceFingerprint |
| `topology/contracts.py` | `LOFT_CONTRACT`, `SWEEP_CONTRACT`, `HELIX_SWEEP_CONTRACT` | 预定义契约 |

### 不修改的文件

- `dialects/loft_sweep/handlers.py` — handler 不变
- `ir/` — 无 IR schema 变更

---

## 3. 核心设计

### 3.1 `compute_face_fingerprint(face) -> FaceFingerprint`

```python
def compute_face_fingerprint(face, tolerance_mm=0.01) -> FaceFingerprint:
    """从 CadQuery/OCP face 计算量化几何指纹。
    
    量化规则: 所有浮点数 round(value / tolerance) → int
    确保跨重建容差内的参数变化不改变指纹。
    
    字段:
      surface_type: "PLANE"|"CYLINDER"|"CONE"|"SPHERE"|"TORUS"|"SPLINE"
      area_q: int          # 面积 ÷ tolerance
      centroid_q: (int,int,int)
      bbox_q: (int,int,int,int,int,int)
      normal_or_axis_q: (int,int,int)|None
      plane_offset_q: int|None  # 仅 PLANE
      radius_q: int|None        # 仅 CYLINDER/SPHERE
      boundary_wire_count: int
      boundary_edge_count: int
      adjacent_face_signatures: list[str]  # Phase 5: 暂空
      convexity_signature: list[str]       # Phase 5: 暂空
      provenance_anchor: str
    """
```

### 3.2 `name_loft_faces(solid, sections, ...) -> TopologyDelta`

```python
def name_loft_faces(solid, *, document_id, component_id, producer_node_id,
                     section_count: int) -> TopologyDelta:
    """按截面顺序分类 loft 面:
    - loft/lateral_N: 相邻截面之间的过渡面 (CYLINDER/SPHERE/SPLINE)
    - loft/cap_start: 起始截面 (PLANE, 最低 Z/索引)
    - loft/cap_end: 终止截面 (PLANE, 最高 Z/索引)
    """
```

### 3.3 `name_sweep_faces(solid, ...) -> TopologyDelta`

```python
def name_sweep_faces(solid, *, document_id, component_id, producer_node_id,
                      path_point_count: int) -> TopologyDelta:
    """按路径分类 sweep 面:
    - sweep/lateral_N: 沿路径的管壁面
    - sweep/cap_start: 起始截面
    - sweep/cap_end: 终止截面
    """
```

---

## 4. 实施顺序

```
5.1: topology/fingerprint.py — compute_face_fingerprint() (实际计算)
5.2: topology/history_wrappers.py — history_aware_loft/sweep
5.3: topology/semantic_naming.py — name_loft_faces/name_sweep_faces
5.4: topology/contracts.py — LOFT/SWEEP/HELIX contracts
5.5: 运行全部测试确保零回归
5.6: 写入 Phase 5 测试
```

## 5. 验收标准

- [ ] `compute_face_fingerprint()` 对 box 的 6 个面返回正确的 surface_type + 量化几何
- [ ] `history_aware_loft()` 使用 OCP ThruSections
- [ ] `name_loft_faces()` 正确分类 lateral/cap 面
- [ ] 77 已有测试零回归
- [ ] Phase 5 新增 10+ 测试通过
