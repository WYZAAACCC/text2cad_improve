# Text2CAD / G-CAD 完整持久拓扑命名修复与改进实施指导

**适用仓库：** `WYZAAACCC/text2cad_improve`  
**实施基线：** `main@6bf3000b9fb2e3eea0933da959b5288d43604018`  
**核心拓扑实现提交：** `2849b9f1f5fe2412b9c5474279a080231e288809`  
**目标读者：** 代码 Agent、CAD Runtime 开发者、OCCT/OCP 集成开发者、CAE 集成开发者  
**目标：** 将当前的 `BRep semantic registry prototype` 改造为真正的 `history-backed persistent topology`，并最终达到 `CAE-safe topology resolution`

---

# 0. 文档目标与不可妥协原则

当前代码已经具备较完整的拓扑领域模型和模块结构，但仍缺少最关键的工程闭环：

```text
PersistentTopoId
    → 当前构建结果中的实际 TopoDS 子形状
    → 经过 OCCT Generated / Modified / IsDeleted 跨操作传播
    → 经参数重建、缓存、进程重启后重新绑定
    → 被下游 CAD/CAE 消费者安全使用
```

本次改造必须遵循以下优先级：

```text
实际子形状绑定正确性
> 内核历史证据
> Fail-Closed
> 状态事务一致性
> 设计语义稳定性
> 可审计与可重放
> 性能
> 兼容旧索引 API
```

严禁采用以下“伪持久命名”方式：

```text
Face/Edge 当前枚举序号
对序号增加语义前缀，如 side_face_2
给当前 Face 临时附加随机 UUID
只比较质心最近距离
只比较面积或 surface type
持久化 selector 字符串并永久重放
在歧义时选择第一个候选
Registry 中有记录就返回 exact
```

正确原则是：

> 一个 PersistentTopoId 必须能够解释：该实体由哪个设计节点产生、从哪些输入实体演化而来、当前绑定到哪个实际内核子形状、绑定证据是什么，以及在 split、merge、delete 或 ambiguity 后应如何解析。

---

# 1. 当前代码应保留与应重构的部分

## 1.1 建议保留的架构

以下现有模块方向正确，应在原结构上升级，不必推翻：

```text
topology/ids.py
topology/models.py
topology/registry.py
topology/contracts.py
topology/history_wrappers.py
topology/semantic_naming.py
topology/fingerprint.py
topology/matcher.py
topology/persistence.py
topology/validation.py
topology/policies.py
topology/cae_bridge.py
topology/cad_adapters.py
```

以下已有接线也应保留：

```text
RuntimeContext.topology_registry
OperationResult.topology_delta
OperationSpec.topology_contract
FaceHandle / EdgeHandle 的 persistent_topology_id
Topology sidecar 概念
NamedTopologySet 概念
消费者最低质量策略
```

## 1.2 必须重构的核心行为

当前以下行为不能继续保留：

1. `TopologyRegistry.resolve()` 在没有 `current_locator` 时返回 `exact`。
2. history wrapper 将 `Generated/Modified` 结果转换为局部 `[0, 1, ...]`。
3. Handler 直接修改 Registry，绕过 Executor 事务。
4. Handler 使用高层 CadQuery 构建后，再按最终 face ordinal 命名。
5. `side_face_0`、`lateral_2` 等序号型角色被作为稳定语义。
6. split 后源实体仍 active 且解析为 exact。
7. merge 后源实体没有进入 superseded 状态。
8. sidecar restore 后 active record 没有重新绑定即可视为 resolved。
9. CAE bridge 只统计 Registry record，而不返回实际 Face。
10. Cache 只按 node ID 取得旧 key，且不包含上游几何内容 hash。

---

# 2. 最终目标架构

```text
Raw G-CAD IR
    |
    | PersistentTopoRef / semantic query
    v
Canonical G-CAD IR
    |
    | 解析设计级身份、Operation Topology Contract
    v
History-aware Operation Handler
    |
    | actual input TopoDS subshapes
    | actual OCCT builder
    | Generated / Modified / IsDeleted
    v
Staged Geometry Result + TopologyDelta
    |
    v
Unified Executor Transaction
    |
    +-- validate output ABI
    +-- stage ObjectStore objects
    +-- build result indexed maps
    +-- bind actual subshape locators
    +-- validate TopologyContract
    +-- apply TopologyDelta
    +-- validate Registry integrity
    |
    v
Atomic Commit
    |
    +-- ObjectStore
    +-- TopologyRegistry
    +-- operation cache
    +-- audit events
    |
    v
PersistentTopoId → actual TopoDS subshape
    |
    +-- downstream CAD feature
    +-- topology sidecar
    +-- Repair invariants
    +-- CAE NamedTopologySet
```

---

# 3. 统一身份模型：必须区分四种“身份”

## 3.1 设计身份

由 G-CAD 文档与 feature graph 决定：

```text
document_id
component_id
lineage_root_node_id
producer_node_id
entity_type
semantic_role
branch_token
```

它构成 `PersistentTopoId`。

设计身份不包含本次运行的 Face/Edge index。

## 3.2 内核运行时身份

表示当前一次构建中的实际 OCCT 子形状：

```text
TopoDS_Shape
owner body
entity type
IndexedMap position
orientation
location
OCCT hash
```

它构成 `RuntimeTopoLocator`，只在当前 runtime session 中有效。

## 3.3 演化身份

表示 operation 前后关系：

```text
primitive
generated
modified
deleted
split
merged
selected
unchanged
```

它构成 `TopologyDelta` 与 lineage graph。

## 3.4 持久化证据

保存：

- 设计身份；
- 语义；
- 谱系；
- fingerprint；
- operation contract/version；
- resolution evidence；
- sidecar hash。

不保存不可跨进程复用的实际 TopoDS 对象或 runtime locator。

---

# 4. PersistentTopoId v2

## 4.1 修复 document identity

禁止使用：

```python
document_id = node.component
```

RuntimeContext 必须携带真实：

```python
document_id: str
canonical_graph_hash: str
```

所有 handler 从 `ctx.document_id` 读取。

## 4.2 权威序列化不能截断

当前 `to_compact()` 截断 document ID，且冒号分隔字段未转义。应升级为 v2。

建议：

```python
class PersistentTopoIdV2(BaseModel):
    scheme: Literal["gcad_topo_v2"] = "gcad_topo_v2"
    document_id: str
    component_id: str
    lineage_root_node_id: str
    producer_node_id: str
    entity_type: TopologyEntityType
    semantic_role: str
    branch_token: str | None = None

    def canonical_payload(self) -> dict:
        return self.model_dump(mode="json")

    def stable_hash(self) -> str:
        payload = canonical_json(self.canonical_payload())
        return "gct2_" + base64url(sha256(payload))[:43]
```

权威 key 使用完整稳定 hash：

```text
gct2_<base64url sha256>
```

完整结构化字段保存在 record/sidecar。

可读 alias 仅用于 UI：

```text
component.disk/feature.center_bore/face.hole_wall
```

## 4.3 强制验证

所有字段必须：

- 非空；
- 限制长度；
- 禁止控制字符；
- semantic role 采用定义好的 grammar；
- branch token 不能包含裸 runtime index；
- 不允许 `Face7`、`Edge12`、`side_face_3` 作为 required persistent role。

推荐 role grammar：

```text
body
cap.start
cap.end
side.from.<source-id>
wall.from.<source-id>
rim.entry
rim.exit
fillet.from.<edge-id>
modified.from.<face-id>
intersection.from.<arg-id>.<tool-id>
instance.<instance-key>.<role>
```

---

# 5. 新增 RuntimeTopoLocator 与 Shape Binding

## 5.1 数据模型

```python
class RuntimeTopoLocator(BaseModel):
    owner_body_handle_id: str
    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]

    indexed_map_position: int
    occt_shape_hash: int
    orientation: str
    location_hash: int

    # 构建该 locator 时的 owner shape 内容标识
    owner_shape_content_hash: str

    # 调试字段，绝不作为持久身份
    runtime_enumeration_index: int | None = None
```

## 5.2 IndexedMap 构建

使用 OCCT：

```python
TopTools_IndexedMapOfShape
TopExp.MapShapes(owner_shape, TopAbs_FACE, face_map)
TopExp.MapShapes(owner_shape, TopAbs_EDGE, edge_map)
```

不得只使用：

```python
shape.Faces()
shape.Edges()
```

返回列表的位置作为唯一 locator。

原因是 indexed map 提供同一个结果 shape 内的统一映射空间，且可以用 `FindIndex(actual_subshape)` 将 history 返回的真实子形状定位到结果 body。

## 5.3 Runtime Shape Binding 服务

新增：

```text
topology/shape_binding.py
```

核心接口：

```python
class ShapeBindingService:
    def build_body_maps(
        self,
        owner_body_handle_id: str,
        owner_shape: Any,
    ) -> BodyTopologyMaps: ...

    def locate_subshape(
        self,
        owner_body_handle_id: str,
        owner_shape: Any,
        subshape: Any,
        entity_type: str,
    ) -> RuntimeTopoLocator: ...

    def resolve_locator(
        self,
        locator: RuntimeTopoLocator,
        object_store: ObjectStore,
    ) -> Any | None: ...

    def verify_locator(
        self,
        locator: RuntimeTopoLocator,
        expected_fingerprint: dict | None,
        object_store: ObjectStore,
    ) -> LocatorVerification: ...
```

## 5.4 exact 的强制语义

`TopologyRegistry.resolve()` 必须接受 ObjectStore/BindingService。

只有满足以下条件才返回 exact：

```text
record.status == active
record.current_locator != None
owner body 存在
owner content hash 匹配
locator 能取得唯一 actual subshape
entity type 匹配
必要 fingerprint 验证通过
```

否则：

```text
TOPOLOGY_LOCATOR_MISSING
TOPOLOGY_OWNER_NOT_FOUND
TOPOLOGY_OWNER_HASH_MISMATCH
TOPOLOGY_LOCATOR_INVALID
TOPOLOGY_TYPE_MISMATCH
```

并返回 unresolved/type_mismatch。

---

# 6. TopologyEntityRecord 状态机重构

## 6.1 建议字段

```python
class TopologyEntityRecordV2(BaseModel):
    persistent_id: str
    persistent_id_payload: PersistentTopoIdV2

    entity_type: TopologyEntityType
    component_id: str
    producer_node_id: str
    owner_body_handle_id: str

    semantic_role: str
    generation: int

    status: Literal[
        "active",
        "deleted",
        "superseded",
        "ambiguous",
        "unresolved",
    ]

    resolution_method: Literal[
        "primitive_semantic",
        "kernel_generated",
        "kernel_modified",
        "kernel_selected",
        "deterministic_semantic",
        "fingerprint_unique",
        "set_expansion",
        "unresolved",
    ]

    current_locator: RuntimeTopoLocator | None
    fingerprint: TopologyFingerprint | None

    ancestor_ids: list[str]
    descendant_ids: list[str]

    topology_contract_hash: str
    operation_execution_hash: str
    confidence: float
    evidence: list[TopologyEvidence]
```

## 6.2 状态转换

### Primitive

```text
new record = active
locator = actual primitive subshape
method = primitive_semantic
```

### 1→1 Modified

```text
source record 保持同一 PersistentTopoId
generation += 1
locator 更新到 result subshape
method = kernel_modified
status = active
```

不要创建无必要的新 ID。

### 1→N Split

```text
source.status = superseded
source.current_locator = None
source.descendant_ids = branch IDs

每个 branch:
    active
    ancestor_ids = [source]
    locator = actual branch shape
```

`resolve(source)`：

```text
status = set
resolved_entity_ids = descendants
```

是否允许消费者接受 set，由 consumer policy 决定。

### N→1 Merge

```text
all sources.status = superseded
all sources.current_locator = None
all sources.descendant_ids += [target]

target:
    active
    ancestor_ids = all source IDs
    locator = actual merged shape
```

默认 `resolve(source)` 返回：

```text
status = set 或 superseded
```

高风险消费者不得自动将多个旧面合并为一个新面，除非 policy 显式允许。

### Delete

```text
source.status = deleted
source.current_locator = None
```

禁止使用 matcher 把 deleted entity 自动匹配到“相似”实体。

### Ambiguous

```text
status = ambiguous
current_locator = None
descendant_ids/candidates = candidate IDs
```

绝不选择第一个候选。

---

# 7. TopologyDelta v2：保存真实 Shape Key，而不是局部序号

## 7.1 当前问题

以下格式没有意义：

```python
generated["edge_0"] = [0]
modified["face_1"] = [0, 1]
```

这里的 `[0]` 是每次 OCCT list 的局部位置。

## 7.2 新模型

Handler 内部可以使用运行时结构：

```python
@dataclass
class RuntimeTopologyRelation:
    relation: RelationType

    source_persistent_ids: list[str]
    source_shapes: list[Any]

    result_shapes: list[Any]

    semantic_role: str | None
    evidence: dict
```

在返回 Pydantic `TopologyDeltaV2` 前，由 ShapeBindingService 将实际 result shape 转换成 `RuntimeTopoLocator`：

```python
class TopologyResultEntity(BaseModel):
    persistent_id: str
    entity_type: TopologyEntityType
    semantic_role: str
    locator: RuntimeTopoLocator
    fingerprint: dict | None = None


class TopologyRelationV2(BaseModel):
    relation: RelationType
    source_ids: list[str]
    result_entities: list[TopologyResultEntity]
    evidence: dict


class TopologyDeltaV2(BaseModel):
    node_id: str
    component_id: str
    result_body_handle_ids: list[str]
    relations: list[TopologyRelationV2]
    history_provider: HistoryProvider
    history_provider_version: str
    topology_contract_hash: str
```

## 7.3 Evidence 必须记录

```text
builder class
OCCT version
input source IDs
source shape runtime keys
Generated/Modified/IsDeleted 查询结果
result shape locator
semantic role rule
fallback 是否使用
```

---

# 8. Handler 与 Executor：禁止 Side Channel，改为原子事务

## 8.1 Handler 规则

Handler 不得：

```python
ctx.topology_registry.register_entity(...)
ctx.topology_registry.apply_delta(...)
ctx.object_store._objects[...] = ...
```

Handler 只能：

1. 解析输入；
2. 运行 geometry builder；
3. 生成 staged objects；
4. 构造 OperationResult；
5. 返回 TopologyDelta。

## 8.2 OperationResult 扩展

```python
class StagedRuntimeObject(BaseModel):
    handle: RuntimeHandle
    value_type: str
    runtime_object_token: str


class OperationResultV3(BaseModel):
    ok: bool
    outputs: list[OperationOutput]
    topology_delta: TopologyDeltaV2 | None

    warnings: list[str]
    metrics: list[OperationMetric]
    postcondition_results: list[dict]
```

实际 Python runtime object 可通过事务对象持有，不放进 Pydantic JSON。

## 8.3 新增 RuntimeTransaction

```python
class RuntimeTransaction:
    staged_objects: dict[str, StoredRuntimeValue]
    staged_registry: TopologyRegistry
    staged_events: list[dict]

    def stage_object(...)
    def stage_topology_delta(...)
    def validate(...)
    def commit(...)
    def rollback(...)
```

最简单可行实现：

```text
ObjectStore 提供 snapshot/copy-on-write
TopologyRegistry 提供 clone()
Handler 操作 staged state
验证成功后替换 ctx 当前 state
```

后续再优化为增量 undo log。

## 8.4 Executor 正确顺序

```text
1. 计算完整 cache key
2. 尝试恢复完整 CachedOperationExecution
3. 若未命中：
   3.1 创建 transaction
   3.2 handler 运行
   3.3 验证 OperationResult ABI
   3.4 stage geometry objects
   3.5 对结果 body 建立 indexed maps
   3.6 验证 topology delta locator
   3.7 验证 TopologyContract
   3.8 应用 delta 到 staged registry
   3.9 validate registry integrity
   3.10 geometry health
   3.11 topology postconditions
   3.12 原子 commit
   3.13 写 cache
4. bind node outputs
```

Topology contract required 时，以下情况必须直接失败：

```text
delta 缺失
history capability 不满足
required role 缺失
cardinality 不满足
locator 缺失
Registry integrity 不通过
```

不再只追加 warning。

---

# 9. History Wrapper 必须真正进入主路径

## 9.1 统一 Adapter

```python
class KernelHistoryAdapter:
    def generated_shapes(self, source_shape: Any) -> list[Any]
    def modified_shapes(self, source_shape: Any) -> list[Any]
    def is_deleted(self, source_shape: Any) -> bool
```

删除或废弃返回 `list[int]` 的接口。

所有 broad `except Exception: return []/None` 改为：

```python
raise KernelHistoryError(
    code=...,
    builder=...,
    source_id=...,
    exception_type=...,
)
```

只有 capability unavailable 可以明确降级。

## 9.2 Capability 不等于 import 成功

当前 probe 只验证类可 import，不足以声明 full。

能力等级应通过 runtime self-test：

```text
创建最小 profile
执行 builder
查询 Generated
证明结果可以定位到 result indexed map
```

Manifest：

```json
{
  "extrude": {
    "level": "full",
    "verified": true,
    "builder": "BRepPrimAPI_MakePrism",
    "occt_version": "...",
    "self_test_hash": "..."
  }
}
```

## 9.3 Contract 声明必须与实际 provider 对齐

若 handler 仍依赖 semantic enumeration：

```text
history_capability = deterministic_semantic
```

不能声明：

```text
full_kernel_history
```

只有真实使用 builder history 并绑定 actual result shape 后，才能声明 full。

---

# 10. 各 Operation 的具体实现要求

---

## 10.1 Sketch：先稳定二维源实体

### 数据模型

每个 sketch element 必须由 Raw IR 显式提供稳定 ID：

```python
class SketchPoint:
    element_id: str
    ...

class SketchLine:
    element_id: str
    start_point_id: str
    end_point_id: str

class SketchArc:
    element_id: str
    start_point_id: str
    end_point_id: str
    center_point_id: str
    direction: Literal["cw", "ccw"]

class SketchCircle:
    element_id: str
    center_point_id: str
    radius_mm: float
```

禁止运行时自动用数组位置生成权威 `e0/e1`。

### Wire 顺序

闭合轮廓可以有 traversal order，但元素身份不随：

- 起点改变；
- 数组重排；
- wire 方向反转；

而变化。

### OCP edge binding

建立：

```text
sketch element ID → actual TopoDS_Edge
```

作为 extrude/revolve history 的输入。

---

## 10.2 Primitive

Primitive 可以使用确定性语义，但仍必须绑定 actual shape。

### Box

基于构造局部坐标：

```text
face.x_min
face.x_max
face.y_min
face.y_max
face.z_min
face.z_max
```

使用法向与局部坐标投影验证，不能依赖 face enumeration。

### Cylinder/Cone

使用 operation axis：

```text
cap.start
cap.end
lateral
```

不得用全局 `center.z` 正负。

### Sphere

```text
outer_surface
```

### 验收

每个语义 record：

- 有 locator；
- 能取得 actual Face；
- surface type 正确；
- 参数变化后 PersistentTopoId 不变。

---

## 10.3 Extrude

### 必须使用

```text
BRepPrimAPI_MakePrism
```

### 输入映射

```text
sketch edge PersistentTopoId → actual input TopoDS_Edge
profile face/wire ID → actual input shape
```

### 历史传播

对每条 sketch edge：

```python
generated_faces = maker.Generated(input_edge)
```

为每个 actual generated face 创建：

```text
extrude/side.from/<sketch-edge-id>
```

若一条 edge 生成多个 face：

```text
split branch token
```

根据局部几何、connected component 或 deterministic branch discriminator 产生。

### Cap

使用 builder FirstShape/LastShape 或 input profile 的 modified/generated history。

语义：

```text
cap.start
cap.end
```

按 extrusion vector 定义，不用全局正负。

### 双向 extrude

```text
cap.negative
cap.positive
```

依据 operation direction；源中面/连接面另行定义。

---

## 10.4 Revolve

### 必须使用

```text
BRepPrimAPI_MakeRevol
```

### 命名

```text
revolved.from/<sketch-edge-id>
cap.start
cap.end
seam.from/<source-id>
```

### 360° 特殊处理

使用角度容差：

```text
abs(angle - 2π) <= angular_tolerance
```

完整旋转没有普通 start/end cap。

### 轴上元素

落在轴上的 profile edge/point 可能退化或删除，必须显式记录 deleted/degenerate。

---

## 10.5 Boolean Fuse/Cut/Common

### 必须使用

```text
BRepAlgoAPI_Fuse
BRepAlgoAPI_Cut
BRepAlgoAPI_Common
SetToFillHistory(True)
```

### 输入

从 Registry 获取每个输入 body 的 active face/edge records，并解析到 actual TopoDS 子形状。

### 每个输入实体

查询：

```text
Modified
Generated
IsDeleted
```

### 关系

- 一个 input face 对应一个 result face：modified；
- 对应多个 result faces：split；
- 多个输入对应同一个 result face：merge；
- 无结果且 IsDeleted：deleted；
- 未变且 result 中可找到同一个 partner：unchanged。

### Generated intersection

新交界面/边语义必须包含来源：

```text
intersection.from.<arg-face-id>.<tool-face-id>
```

若来源无法唯一证明，标记 unresolved/ambiguous，不按 ordinal 命名。

---

## 10.6 Hole

Hole 不应独立猜测结果面，应作为 boolean cut 的语义特化。

### Tool 语义

Cutter primitive：

```text
tool.lateral
tool.cap.start
tool.cap.end
```

### Cut history

```text
tool.lateral
→ result hole wall face(s)

target entry face
→ modified face with inner wire

intersection edge
→ entry rim / exit rim
```

### Entry/Exit

按 hole axis 与 host intersection 参数定义：

```text
axis parameter t_min = entry
t_max = exit
```

不能使用全局 Z。

### Blind/Through

- blind：exit rim 为 zero_or_one；
- through：根据真实交点可能为 one_or_more；
- 多层实体/阶梯孔不能强制 exactly_one wall。

Contract 应细分 hole 类型。

---

## 10.7 Fillet

### 输入选择

必须使用 `PersistentTopoRef` 解析 actual edge。

禁止生产路径使用 raw edge index。

### Builder

```text
BRepFilletAPI_MakeFillet
```

### 历史

对 selected edge 与相邻 faces 查询：

```text
Generated/Modified/IsDeleted
```

语义：

```text
fillet.face.from/<selected-edge-id>
modified.from/<adjacent-face-id>
```

selected edge 通常：

```text
deleted 或 superseded
```

### 不可使用

```text
所有 CYLINDER/SPHERE/TORUS 都视为 fillet face
```

因为输入实体可能已有这些曲面。

---

## 10.8 Chamfer

同 Fillet，使用真实 chamfer builder history。

禁止：

```text
area < 100
```

等尺度相关魔数分类。

语义：

```text
chamfer.face.from/<selected-edge-id>
modified.from/<adjacent-face-id>
```

---

## 10.9 Shell

### 输入

Removed faces 必须是 persistent face refs。

### Builder history

使用 thick solid builder 的 history，记录：

```text
removed source faces → deleted
remaining source faces → offset/modified faces
new side walls → generated
```

### 质量

如果当前 OCP wrapper 无法提供可靠 history：

```text
history_capability = partial_kernel_history
```

对于 CAE/必需后续引用，默认不允许依赖 best-effort shell topology。

---

## 10.10 Loft / Sweep

此类 operation 具有天然 correspondence 难题。

### 源身份

必须基于：

```text
section ID
section sketch edge ID
path ID
profile ID
```

### 不允许强行一一映射

如果 section 拓扑不同，例如：

```text
四边形 → 五边形
```

侧面不存在自然一一对应。

此时正确结果是：

```text
split / merge / ambiguous / set
```

而不是 `lateral_0...`。

### 第一版范围

只对：

- 相同拓扑；
- 相同 element correspondence；
- 无分支 path；

承诺 deterministic persistence。

其他情况明确降级。

---

## 10.11 Pattern / Mirror

每个实例必须有稳定 instance key：

```text
instance.angle_000
instance.angle_006
```

或者：

```text
instance.row_2.col_4
```

不能以最终 body/face ordinal 标识。

Pattern 中的子实体 ID：

```text
pattern-node/instance.<key>/<source-persistent-id>
```

---

# 11. PersistentTopoRef 进入 Raw/Canonical IR

## 11.1 Raw IR

```python
class RawPersistentTopoRef(BaseModel):
    component_id: str
    producer_node_id: str | None

    semantic_query: str
    entity_type: Literal["face", "edge", "vertex"]

    cardinality: Literal[
        "exactly_one",
        "zero_or_one",
        "one_or_more",
        "zero_or_more",
    ]

    resolution_policy: Literal[
        "exact_only",
        "allow_deterministic_semantic",
        "allow_set_expansion",
        "allow_fingerprint_unique",
    ] = "exact_only"
```

LLM 输出 semantic query，不输出内部 stable hash。

## 11.2 Canonical IR

Canonicalizer 将 query 解析为：

```python
class CanonicalPersistentTopoRef(BaseModel):
    persistent_ids: list[str]
    entity_type: str
    cardinality: str
    resolution_policy: str
    producer_contract_hash: str
```

如果构建前无法确定具体 ID，可保留受 contract 约束的 symbolic ref：

```python
class DeferredPersistentTopoRef:
    producer_node_id
    role_pattern
    expected_type
    cardinality
```

在 producer node 完成后解析。

## 11.3 Legacy selector 迁移

旧 selector/index：

```text
runtime_index_only
```

仅允许：

- 调试；
- 非持久、一次性选择；
- 明确标记 unsafe。

禁止用于：

- CAE；
- 装配；
- required downstream feature；
- sidecar persistent reference。

---

# 12. Matcher 与 Fingerprint 的正确实现

Kernel history 是主证据，matcher 仅 fallback。

## 12.1 候选硬约束

候选必须满足：

```text
same document
same component
same entity type
compatible producer/operation
allowed lineage relation
compatible surface/curve type
compatible owner body
```

任何硬约束不满足直接淘汰。

## 12.2 Face Fingerprint

```python
class FaceFingerprintV2:
    surface_type
    area_normalized
    centroid_local
    bbox_local
    axis_or_normal
    plane_offset
    radius
    cone_angle
    major_radius
    minor_radius
    wire_count
    edge_count
    adjacent_face_ids
    adjacent_surface_types
    edge_curve_type_multiset
    convexity_signature
    provenance_anchor
```

使用 operation/local body coordinate frame，减少整体平移和旋转干扰。

## 12.3 Edge Fingerprint

```python
class EdgeFingerprintV2:
    curve_type
    length_normalized
    centroid_local
    bbox_local
    axis_or_direction
    radius
    endpoint_valences
    adjacent_face_ids
    adjacent_surface_types
    provenance_anchor
```

## 12.4 容差量纲

- length：`tol`
- area：`tol²` 或相对面积容差
- volume：`tol³`
- angle：独立 angular tolerance
- centroid/bbox：相对 body diagonal 归一化

禁止用线性 tolerance 直接量化面积。

## 12.5 匹配算法

对于多个目标与候选：

1. 建立 cost matrix；
2. 使用 Hungarian/min-cost bipartite assignment；
3. 应用最大允许 cost；
4. 计算 best/second margin；
5. 若 margin 不足则 ambiguous；
6. 若多个等价对称候选无语义 instance key，保持 ambiguous。

## 12.6 置信度

不得把 confidence 当作覆盖歧义的手段。

高置信但 margin 很小仍是 ambiguous。

---

# 13. OperationCache 完整改造

## 13.1 立即修复现有 get bug

```python
def get(self, node, execution_inputs):
    current_key = self.key(node, execution_inputs)
    stored_key = self._node_keys.get(node.id)

    if stored_key != current_key:
        return None

    return self._store.get(current_key)
```

## 13.2 Cache Key

```text
CanonicalNode content hash
input geometry content hashes
input persistent topology fragment hash
operation topology contract hash
runtime version
CadQuery version
OCP/OCCT version
topology algorithm version
tolerance policy version
```

## 13.3 输入几何 hash

每个 output handle 绑定：

```text
geometry_content_hash
```

可以来自：

- canonical BREP serialization hash；
- Shape serialization；
- 稳定几何摘要。

不能只用 handle ID。

## 13.4 Cache Entry

```python
class CachedOperationExecution:
    key: str

    operation_result: dict
    object_payloads: dict
    topology_delta: dict
    topology_registry_fragment: dict

    output_geometry_hashes: dict
    input_geometry_hashes: dict

    runtime_versions: dict
    contract_hash: str
```

## 13.5 Cache Hit

命中时必须原子恢复：

```text
ObjectStore objects
TopologyRegistry fragment
node outputs
geometry health evidence
```

如果对象不能恢复，cache miss，而不是只返回旧 Handle ID。

---

# 14. Sidecar 与跨进程 Rebind

## 14.1 Sidecar 写出时机

只有以下全部成功后才写：

```text
geometry build
topology contract validation
registry integrity
artifact validation
```

## 14.2 Sidecar 内容

```json
{
  "schema": "gcad_topology_v2",
  "document_id": "...",
  "canonical_graph_hash": "...",
  "registry_hash": "...",

  "versions": {
    "topology_algorithm": "...",
    "fingerprint_schema": "...",
    "matcher": "...",
    "runtime": "...",
    "cadquery": "...",
    "occt": "..."
  },

  "entities": [],
  "lineage": [],
  "contracts": [],
  "named_sets": [],
  "unresolved": [],
  "ambiguous": []
}
```

不持久化 RuntimeTopoLocator 为跨进程可用 locator；可以持久化仅用于诊断的旧 locator，但 restore 后必须清空解析状态。

## 14.3 Sidecar 读取

必须验证：

```text
文件 SHA-256
schema
registry hash
document_id
canonical graph hash
所有 contract hash
版本兼容性
```

当前 reader 必须补充 registry hash 重算。

## 14.4 Rebind 流程

```text
read sidecar
→ records 状态设为 unresolved_pending_rebind
→ rebuild geometry
→ 每个 operation 用 kernel history 恢复
→ 仍缺失的 entity 使用受限 matcher
→ validate required references
→ active/exact 或 ambiguous/unresolved
```

不能：

```text
read sidecar → restore active → exact
```

---

# 15. Validation 管线升级

## 15.1 静态阶段

新增或强化：

```text
topology_contract_presence
topology_contract_capability
topology_role_schema
persistent_topo_ref_structure
persistent_topo_ref_producer
persistent_topo_ref_type
persistent_topo_ref_cardinality
consumer_resolution_policy
legacy_index_prohibition
```

## 15.2 Runtime 阶段

```text
topology_delta_presence
topology_delta_contract
topology_locator_binding
topology_lineage_integrity
topology_resolution_quality
topology_named_set_integrity
```

## 15.3 Artifact 阶段

```text
topology_sidecar_exists
sidecar file hash
registry hash
document/graph hash
version compatibility
artifact build ID consistency
```

## 15.4 Severity

以下必须 error/fatal：

- topology-critical operation 无 delta；
- required role 缺失；
- required entity 无 locator；
- CAE ref ambiguous/deleted/unresolved；
- split/merge lineage 不一致；
- sidecar hash 不匹配；
- contract 宣称 full history，但 provider 不是 kernel history；
- legacy face index 被 high-risk consumer 使用。

不再以 Phase 注释为由保持 warning-only。

---

# 16. Repair Loop 集成

## 16.1 新增结构化错误

```text
TOPOLOGY_CONTRACT_MISSING
TOPOLOGY_HISTORY_CAPABILITY_MISMATCH
TOPOLOGY_DELTA_MISSING
TOPOLOGY_ROLE_MISSING
TOPOLOGY_CARDINALITY_MISMATCH
TOPOLOGY_LOCATOR_MISSING
TOPOLOGY_LOCATOR_INVALID
TOPOLOGY_REF_DELETED
TOPOLOGY_REF_AMBIGUOUS
TOPOLOGY_REF_UNRESOLVED
TOPOLOGY_SPLIT_NOT_ALLOWED
TOPOLOGY_MERGE_NOT_ALLOWED
TOPOLOGY_CACHE_FRAGMENT_MISMATCH
TOPOLOGY_SIDECAR_HASH_MISMATCH
```

## 16.2 Repair Agent 上下文

必须提供：

- 原始用户意图；
- 当前 Raw IR；
- 当前 PersistentTopoRef；
- producer node；
- topology contract；
- Registry record；
- lineage；
- actual resolution status；
- candidates；
- history evidence；
- matcher scores；
- operation geometry error；
- allowed Raw IR patch paths。

## 16.3 Repair Agent 禁止修改

```text
PersistentTopoId
TopologyRegistry
TopologyDelta
RuntimeTopoLocator
fingerprint
sidecar
resolution status
history evidence
```

Repair Agent 只能修改：

- semantic query；
- producer node 引用；
- 合法 cardinality；
- 与 topology failure 有直接因果关系的 operation 参数；
- 可证明错误的 feature graph reference。

## 16.4 Repair Progress

ProgressScore 增加：

```text
protected_topology_ids_preserved
required_topology_refs_resolved
ambiguous_count
deleted_required_count
registry_integrity_ok
cae_named_sets_safe
```

候选如果：

- required ID 消失；
- ambiguity 增加；
- CAE set 漂移；
- resolution quality 下降；

必须回滚。

---

# 17. CAE Bridge 改造

## 17.1 输出必须是实际 Shape Binding

当前 `resolve_named_set_to_faces()` 应改为：

```python
class CaeResolvedEntity(BaseModel):
    persistent_id: str
    face_handle_id: str
    owner_body_handle_id: str
    resolution_method: str
    confidence: float


class CaeResolvedSet(BaseModel):
    ...
    resolved_entities: list[CaeResolvedEntity]
    worst_resolution_quality: str
```

## 17.2 强制检查

对每个 ID：

```text
status exact
actual TopoDS_Face 存在
entity type face
owner body 正确
locator 验证通过
resolution quality 达标
```

集合质量取：

```text
minimum/worst quality
```

而不是 best。

## 17.3 Mesh/ANSYS 证明

CAE exporter 必须：

1. 将 actual Face 转换为 mesher selection；
2. 创建 Named Selection；
3. 保存 persistent IDs；
4. 导出后验证 face/entity 数量；
5. 在 result metadata 中保存作用域 hash。

如果 mesh 转换后选择为空，阻止 solve。

---

# 18. SolidWorks / NX / STEP Adapter

## 18.1 STEP/XCAF

第一阶段：

- sidecar 仍为权威；
- STEP 仅为几何交付物；
- 可尝试写 XCAF labels/AP242 properties；
- 导入后必须重新验证，不能相信名称必然保留。

## 18.2 SolidWorks

需要真实闭环：

```text
G-CAD PersistentTopoId
→ 导入 STEP
→ 找到候选 native face
→ 写 persistent reference / attribute
→ save
→ close
→ reopen
→ read attribute
→ verify geometry
```

禁止以字符串模糊相似度作为安全身份。

## 18.3 NX

同样要求 NXOpen journal 实际写入和回读 user attribute/identifier。

---

# 19. Registry Integrity 完整检查

`validate_integrity()` 必须升级为全图检查：

```text
Persistent ID 唯一
Alias 在 scope 内唯一或显式集合
Active record 必须有有效 locator
Deleted/superseded record 不得有 active locator
owner body 存在
entity type 匹配
locator 不越界
owner content hash 匹配
同一互斥 actual shape 不被多个 exclusive ID 占用
ancestor/descendant 双向一致
所有引用 ID 存在
完整 DAG cycle detection
split source 为 superseded
merge sources 为 superseded
branch tokens 唯一
contract hash 存在
resolution_method 与 relation 匹配
```

不要只沿第一个 ancestor 检查 cycle。

---

# 20. 测试计划：必须证明实际 B-Rep 身份

## 20.1 测试环境

CI 固定：

```text
Python
CadQuery
OCP
OCCT
topology algorithm version
```

History 测试不得以：

```text
异常则 return
OCP 不可用也 pass
```

方式跳过。

若 OCP 不可用，专门 job 标记 skipped；生产 topology job 必须安装并强制运行。

## 20.2 通用断言

每个 persistent entity 必须断言：

```text
record exists
status correct
locator exists when active
actual subshape exists
type correct
semantic geometry correct
rebuild 后 ID 相同
rebuild 后 locator 可不同
```

## 20.3 Extrude

- depth ±1%、±10%；
- profile 尺寸变化；
- profile element 顺序改变；
- 插入不相关 feature；
- side.from(edge_ID) 指向真实 generated face；
- cap.start/end 依据 operation direction；
- cache off/cold/warm 一致。

## 20.4 Revolve

- 角度变化；
- 360° 临界；
- profile 尺寸变化；
- axis 方向变化；
- seam/cap 状态正确。

## 20.5 Boolean

覆盖：

```text
1→1 modified
1→N split
N→1 merge
delete
no intersection
tangent
coincident
shape simplification
```

直接比较 `Generated/Modified/IsDeleted` 和 actual result shape。

## 20.6 Hole

- arbitrary axis；
- 平移/旋转 host；
- blind/through；
- 多层穿透；
- entry/exit rim；
- hole wall 实际 surface/axis/radius；
- pattern instance key。

## 20.7 Fillet/Chamfer

- 输入已有 cylinder/torus；
- 多 edge；
- 不同 radius；
- selected edge deleted；
- generated face 与 source edge history；
- 半径接近极限；
- required failure Fail-Closed。

## 20.8 Shell/Loft/Sweep

- 可证明 topology；
- 不可证明 correspondence 时 ambiguous；
- 不得按 ordinal 强行 exact。

## 20.9 Symmetry

构造：

- 完全相同双孔；
- 环形阵列；
- 对称槽；
- 等面积同类型面。

没有 instance semantic key 时必须 ambiguous。

## 20.10 Sidecar Restart

```text
build A
write sidecar
new RuntimeContext
read sidecar
确认全部 unresolved_pending_rebind
rebuild
rebind
validate exact/ambiguous
```

## 20.11 Cache

```text
cache disabled
cold cache
warm cache
上游参数变化后的 warm cache
contract version change
OCCT version change
topology algorithm version change
```

比较：

```text
geometry hash
Registry hash
sidecar hash
resolution results
```

## 20.12 Repair

- repair 参数后 protected IDs 保持；
- ambiguity 增加时 reject；
- runtime topology failure 修复后完整 validation/rebuild；
- Repair Agent 尝试修改 stable ID 时拒绝。

## 20.13 CAE

```text
Persistent ID
→ actual Face
→ mesh named selection
→ node/element count
→ 几何区域验证
```

deleted/ambiguous/unresolved 必须阻止求解。

---

# 21. 推荐 PR 拆分与实施顺序

## PR 1：Identity 与 Locator 基础修复

- PersistentTopoId v2；
- 真实 document ID；
- RuntimeTopoLocator；
- ShapeBindingService；
- Registry exact 规则；
- Legacy/Persistent Handle 分离。

**验收：** primitive active record 必须能解析 actual face。

## PR 2：Registry 状态机与事务

- split/merge/delete；
- full integrity validation；
- RuntimeTransaction；
- 禁止 handler side-channel；
- Executor 原子提交。

**验收：** 人工 delta 的完整状态机测试。

## PR 3：Cache P0 修复

- get key 比较；
- input geometry hash；
- topology fragment hash；
- cache entry/restore。

**验收：** 上游参数变化不返回旧结果。

## PR 4：Sketch Stable IDs + Extrude

- Sketch element IDs；
- BRepPrimAPI_MakePrism 接线；
- actual history；
- side.from(edge_ID)。

**验收：** 参数扰动/feature insertion 后 actual face 解析正确。

## PR 5：Revolve

- MakeRevol；
- cap/seam；
- local coordinate semantics。

## PR 6：Boolean + Hole

- BRepAlgoAPI history；
- split/merge/delete；
- hole wall/rims。

## PR 7：Fillet + Chamfer

- persistent edge input；
- builder history；
- selected edge lifecycle。

## PR 8：Shell/Loft/Sweep/Pattern

- 明确 capability 范围；
- 不可证明时 ambiguous/fail。

## PR 9：IR + Validation

- Raw/Canonical PersistentTopoRef；
- contract/runtime/artifact stages；
- legacy index policy。

## PR 10：Sidecar/Rebind

- v2 schema；
- hash 验证；
- restore/rebind。

## PR 11：Repair Loop

- topology issues；
- protected invariants；
- progress/rollback。

## PR 12：CAE

- actual Face resolution；
- mesher/ANSYS named selection；
- worst quality gate。

## PR 13：商业 CAD Adapter

- STEP/XCAF；
- SolidWorks；
- NX；
- import/reopen verification。

---

# 22. 每个 PR 的通用工程要求

1. 不得增加 broad exception swallowing。
2. 所有内核错误转成结构化 RuntimeIssue。
3. 每个 feature 必须有 capability/version。
4. 每个新增 persistent role 必须有 contract 与测试。
5. 每个 active entity 必须有实际 locator。
6. 不允许用 ordinal 填补无法证明的身份。
7. 不允许低质量 fallback 通过 CAE gate。
8. 所有 topology state 修改必须事务化。
9. Cache 和 sidecar 必须包含命名算法版本。
10. 文档声明必须与实际 capability 一致。

---

# 23. Definition of Done

系统只有同时满足以下要求，才可声明：

```text
persistent_topology_naming = history_backed
```

- PersistentTopoId 不含 runtime index；
- document identity 全局正确；
- active record 总有可验证 locator；
- Registry 能返回 actual subshape；
- extrude/revolve/boolean/hole/fillet 等主 operation 使用真实 OCCT history；
- split、merge、delete、ambiguity 正确；
- handler 不直接修改 Registry；
- ObjectStore 与 Registry 原子提交；
- cache 对上游几何与 topology 内容敏感；
- sidecar 可校验、可重建、可 rebind；
- Raw/Canonical IR 使用 PersistentTopoRef；
- legacy index 不可用于高风险消费者；
- topology validation Fail-Closed；
- Repair Loop 保护拓扑不变量；
- CAE NamedTopologySet 解析为 actual Face；
- 参数扰动、feature insertion、cache、restart 测试全部通过。

系统只有进一步满足以下要求，才可声明：

```text
cae_topology_safe = true
```

- 所有载荷/约束/接触集合均为 actual Face；
- 每个成员达到 exact kernel history 或批准的 deterministic semantic；
- 集合采用 worst quality gate；
- mesh/export named selection 回读验证成功；
- ambiguity/deleted/unresolved 一律阻止求解；
- ANSYS 结果报告保存 topology scope proof。

---

# 24. 给代码 Agent 的最终执行指令

不要先继续扩展更多 topology 模型或 CAD adapter。

第一优先事项是完成以下垂直切片：

```text
稳定 Sketch Edge ID
→ History-aware Extrude
→ Generated(actual edge) 得到 actual side face
→ RuntimeTopoLocator
→ Registry exact resolve actual face
→ sidecar
→ 参数变化后 rebind
→ 下游 fillet/CAE 使用同一 PersistentTopoId
```

只有这条垂直链完全通过，才扩展到 Boolean、Hole、Fillet、Shell、Loft 和商业 CAD。

任何时候，如果系统只能“推测”而不能证明某个 PersistentTopoId 对应哪个实际子形状，正确结果必须是：

```text
ambiguous
或
unresolved
```

而不是：

```text
exact
```

最终原则：

> 持久拓扑命名的完成标准，不是 Registry 中有多少 stable ID，而是每个被消费的 stable ID 都能以明确证据解析到当前实际 B-Rep 子形状；无法证明时，系统会安全停止。
