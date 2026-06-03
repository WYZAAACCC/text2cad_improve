# 工业几何引擎升级工程计划书

**审计基准**: SolidWorks/NX 首席技术专家视角  
**当前评分**: 1.8/5 → 目标 3.5/5 (概念几何→工程参考几何)  
**约束**: 不破坏现有 LLM pipeline，向后兼容，每阶段独立可测

---

## 第一阶段：几何验证与公差模型 (G + B)

**目标**: 补上工业 CAD 最基础的防线——知道输出是否有效

### 1.1 新增全局公差模型

**文件**: `generative_cad/runtime/tolerance.py` (新建)

```python
@dataclass(frozen=True)
class GeometryTolerance:
    linear_mm: float = 0.01       # 线性公差
    angular_deg: float = 0.1      # 角度公差
    min_edge_length_mm: float = 0.25
    min_wall_thickness_mm: float = 1.0
    min_boolean_clearance_mm: float = 0.2
    fuzzy_zero_mm: float = 1e-6   # 视为零的阈值
```

**修改 `RuntimeContext`** (line 20):
```python
tolerance: GeometryTolerance = field(default_factory=GeometryTolerance)
```

**影响**: 所有 handler 可通过 `ctx.tolerance` 获取统一公差。composition boolean fallback 的硬编码 `0.01` 替换为 `ctx.tolerance.linear_mm`。

### 1.2 新增运行时几何验证

**文件**: `generative_cad/validation/geometry_validate.py` (新建)

利用 OCCT 的 `BRepCheck_Analyzer` 做三件事：

```python
def validate_solid_geometry(solid, tolerance: GeometryTolerance) -> ValidationReport:
    """三步验证: 自交检测 → 最小壁厚 → 非流形检测"""
    # 1. BRepCheck_Analyzer: 自交、无效边、空壳
    # 2. 按 tolerance.min_wall_thickness_mm 检查壁厚
    # 3. 检查是否为 manifold solid (每个边恰好属于 2 个面)
```

**集成到 `executor.py`** 的 `execute_operation()`:
```python
# 在每个 creates_solid / modifies_solid 操作后自动调用
if "creates_solid" in spec.effects or "modifies_solid" in spec.effects:
    geo_report = validate_solid_geometry(result_obj, ctx.tolerance)
    if not geo_report.ok:
        ctx.warnings.extend(...)
```

**影响范围**: `executor.py` line 41 之后新增调用。不改 handler。

### 1.3 激活已声明的几何策略

当前 `geometry_preflight.py` 的 `DEFAULT_GEOMETRY_POLICY` 是**死代码**。将其中可执行的项移到运行时验证：

| 策略 | 当前状态 | 修改 |
|---|---|---|
| `min_wall_thickness_mm: 1.0` | 只声明不执行 | 移入 `geometry_validate.py` |
| `min_edge_length_mm: 0.25` | 只声明不执行 | 移入 `geometry_validate.py` |
| `max_fillet_ratio_to_local_thickness: 0.25` | 只声明不执行 | 移入 fillet handler 的 pre-check |

---

## 第二阶段：拓扑命名与面/边选择 (A)

**目标**: 让 chamfer/fillet 可以选择"哪条边"，而非只能全实体

### 2.1 新增 EdgeHandle 和 FaceHandle

**文件**: `generative_cad/runtime/handles.py` (修改)

```python
class EdgeHandle(RuntimeHandle):
    type: Literal["edge"] = "edge"
    parent_solid_id: str | None = None
    edge_index: int = 0

class FaceHandle(RuntimeHandle):
    type: Literal["face"] = "face"
    parent_solid_id: str | None = None
    face_index: int = 0
```

### 2.2 新增拓扑查询方法

**文件**: `generative_cad/runtime/topology.py` (新建)

```python
def select_edges_by_selector(solid, selector: str) -> list[EdgeHandle]:
    """selector: 'top', 'bottom', 'all_external', '>Z', '<Z', 'sharp(angle>30deg)'"""
    # 使用 CadQuery selectors: faces(">Z").edges() 等

def select_faces_by_selector(solid, selector: str) -> list[FaceHandle]:
    """selector: 'top', 'bottom', '>Z', '<Z', 'parallel(XY)'"""
```

### 2.3 升级 chamfer/fillet handler

**修改**: `axisymmetric/handlers.py` line 197, `sketch_extrude/handlers.py` line 191

```python
# 当前:
body = body.chamfer(distance)

# 升级后:
target = node.params.get("target", "all_external_edges")
if target == "all_external_edges":
    body = body.chamfer(distance)
else:
    edges = select_edges_by_selector(body, target)
    for edge in edges:
        body = body.edges(edge.edge_index).chamfer(distance)
```

**影响**: 向后兼容——`target="all_external_edges"` 行为不变。新增 `target="top_edge"` 等选项。

---

## 第三阶段：布尔运算鲁棒性 (D)

**目标**: 边接触/零体积/自交输入不会静默丢数据

### 3.1 新增布尔前检查

**文件**: `generative_cad/validation/geometry_validate.py` (追加)

```python
def pre_boolean_check(a, b, tolerance: GeometryTolerance) -> tuple[bool, str]:
    """布尔运算前检查: 包络相交? 最小间隙? 自交?"""
    bb_a = a.val().BoundingBox()
    bb_b = b.val().BoundingBox()
    if not boxes_intersect(bb_a, bb_b):
        return False, "Bounding boxes do not intersect"
    clearance = min_box_clearance(bb_a, bb_b)
    if clearance < tolerance.min_boolean_clearance_mm:
        return True, f"Near-coincident faces (clearance={clearance:.4f}mm)"
    return True, ""
```

### 3.2 升级 boolean handler

**修改**: `composition/handlers.py` `handle_boolean_union` 和 `handle_boolean_cut`

当前的三级降级 "try union → try fuse → return first solid" 改为：
```python
# 1. pre_boolean_check
# 2. try union with tolerance
# 3. try cut+tolerance
# 4. 记录详细诊断信息 (两个实体的 BBox、体积、面数)
# 5. 返回时在 ctx.degraded_features 中记录结构化数据
```

### 3.3 修改 boolean_union 的静默数据丢失

当前 `return {"body": _store_solid(node, ctx, a)}` 静默丢弃 solid B。

改为：
```python
ctx.degraded_features.append({
    "node_id": node.id, "op": "boolean_union",
    "reason": "union_failed_returning_first_solid",
    "lost_geometry": {"volume_mm3": b_vol, "bbox_mm": b_bbox},
})
ctx.warnings.append(
    f"boolean_union FAILED on '{node.id}': solid B ({b_vol:.1f}mm³) was NOT merged. "
    f"Assembly is INCOMPLETE — check clearance between components."
)
```

---

## 第四阶段：曲面连续性 (E)

**目标**: loft/sweep 可用于气动参考几何

### 4.1 升级 sweep 路径为 NURBS

**修改**: `loft_sweep/handlers.py` `handle_sweep_profile`

当前用 `lineTo` 构建折线路径。改为：
```python
pts_3d = [cq.Vector(x, y, z) for x, y, z in path_points]
path_wire = cq.Workplane("XY").spline(pts_3d)  # NURBS spline
```

### 4.2 新增 G1/G2 连续参数

**修改**: `loft_sweep/params.py` `LoftSectionsParams`

```python
class LoftSectionsParams(BaseModel):
    sections: list[ProfileSection] = Field(min_length=2)
    ruled: bool = False
    continuity: Literal["G0", "G1", "G2"] = "G0"  # 新增
    start_tangent: Point3D | None = None             # 新增
    end_tangent: Point3D | None = None               # 新增
```

### 4.3 新增 sweep 路径自交检测

**修改**: `loft_sweep/handlers.py` `handle_sweep_profile`

sweep 前检查路径是否自交，利用 OCCT `BRepCheck`:
```python
if path_self_intersects(path_wire):
    raise RuntimeError("Sweep path self-intersects — aborting")
```

### 4.4 新增最小曲率检查

**修改**: `loft_sweep/handlers.py` `handle_helix_sweep`

```python
min_radius = pitch / (2 * math.pi)  # 螺旋线最小曲率半径
if profile_radius_mm > min_radius * 0.8:
    ctx.warnings.append("Profile radius > 80% of minimum curvature radius — may self-intersect")
```

---

## 第五阶段：增量执行与缓存 (H)

**目标**: 改一个参数不重算整个图

### 5.1 新增操作缓存层

**文件**: `generative_cad/runtime/cache.py` (新建)

```python
class OperationCache:
    def key(self, node: CanonicalNode) -> str:
        """基于 node 的所有输入参数 + 输入 handle 的 hash 生成缓存键"""
        return stable_hash(node.model_dump())

    def get(self, node_key: str) -> Any | None: ...
    def put(self, node_key: str, result: Any) -> None: ...
    def invalidate(self, node_id: str) -> None: ...
```

### 5.2 集成到 execute_operation

**修改**: `executor.py` `execute_operation()`

```python
cache_key = ctx.cache.key(node)
cached = ctx.cache.get(cache_key)
if cached is not None:
    return cached  # 跳过重算

result = op_spec.handler(node, ctx)
ctx.cache.put(cache_key, result)
return result
```

### 5.3 增量失效传播

**修改**: `pipeline/run.py` `_run_components()`

当前: `for component in components: dialect.run_component(...)` — 总是从头执行

改为:
```python
# 1. 计算每个 node 的输入 hash
# 2. 找到第一个 changed node
# 3. 只从该 node 开始执行 (复用之前的结果)
# 4. 未被改变的 node 从缓存读取
```

---

## 第六阶段：测试覆盖

**目标**: handler 测试从 2/29 (7%) 提升到 20/29 (69%)

### 6.1 测试优先级

| 优先级 | Dialect | Handler | 测试内容 |
|---|---|---|---|
| P0 | axisymmetric | revolve_profile | 验证 5 种 profile 的 revolve 体积 |
| P0 | axisymmetric | cut_center_bore | 验证不同直径+位置的孔切割 |
| P0 | composition | boolean_union | 验证 edge-contact 退化行为 |
| P1 | sketch_extrude | extrude_rectangle | 验证不同 plane/centered/direction |
| P1 | sketch_extrude | add_rib | 验证 rib 生成+union 成功 |
| P1 | loft_sweep | loft_sections | 验证 2-4 截面放样 |
| P1 | loft_sweep | helix_sweep | 验证等距/变距弹簧 |
| P2 | shell_housing | shell_body | 验证简单抽壳 |
| P2 | composition | circular_pattern | 验证 count=0 不再存 None |
| P2 | composition | linear_pattern | 同上 |

### 6.2 测试模板
```python
def test_<handler>_produces_valid_geometry():
    """验证 <handler> 产生 CLOSED_SHELL + volume > 0"""
    # 1. 构造最小 valid params
    # 2. 调用 handler
    # 3. 检查 result.val().isClosed()
    # 4. 检查 result.val().Volume() > 0
    # 5. 检查 ctx.warnings 中无 critical error
```

---

## 执行顺序与依赖

```
Phase 1 (G+B): 几何验证 + 公差模型 ← 无依赖，最先做
    ↓
Phase 2 (A):   拓扑命名           ← 依赖 Phase 1 的 tolerance
    ↓
Phase 3 (D):   布尔鲁棒性         ← 依赖 Phase 1 的 pre_boolean_check
    ↓
Phase 4 (E):   曲面连续性         ← 独立模块，可与 Phase 2-3 并行
    ↓
Phase 5 (H):   增量缓存           ← 依赖所有 handler 稳定后
    ↓
Phase 6:       测试覆盖           ← 与 Phase 1-5 穿插进行
```

## 各阶段预估工作量

| 阶段 | 新增文件 | 修改文件 | 新增 LOC | 测试 |
|---|---|---|---|---|
| 1. 验证+公差 | 2 | 3 | ~300 | 6 |
| 2. 拓扑命名 | 1 | 3 | ~400 | 8 |
| 3. 布尔鲁棒 | 0 | 1 | ~150 | 4 |
| 4. 曲面连续 | 0 | 2 | ~200 | 4 |
| 5. 增量缓存 | 1 | 2 | ~300 | 4 |
| 6. 测试覆盖 | 10+ | 0 | ~2000 | 20+ |

## 验收标准

完成后必须满足：
- [ ] 所有 boolean 失败记录详细信息（非静默丢数据）
- [ ] chamfer/fillet 支持 target selector（非仅 all_external_edges）
- [ ] loft 支持 G1 连续性
- [ ] 至少有 20 个 handler 有真实几何测试
- [ ] 475 个现有测试零回归
- [ ] 改一个参数不再触发全部重算（增量缓存命中率 > 50%）
