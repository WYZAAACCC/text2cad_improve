# Text2CAD 持久化拓扑命名 V3 修复与改进实施指导书

**适用仓库：** `WYZAAACCC/text2cad_improve`  
**重点目录：** `integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/`  
**基准案例：** `app/text-to-cad/server/output/v3_final_20260721_045319/`  
**执行对象：** 代码 Agent  
**文档定位：** 工程修复规范、实施顺序、测试要求和最终验收标准

---

## 0. 给代码 Agent 的最高优先级指令

本任务不是修改报告，不是增加几个字段，也不是把 Sidecar 的 schema 名称改成 V3。

本任务的目标是：

> 让同一个工程拓扑实体在建模时序中拥有可持续继承的稳定身份；每一次创建、刚体变换、阵列、布尔修改、分裂、合并、删除，都必须基于真实的 OCCT 源实体—结果实体关系更新身份和谱系，而不是在每个阶段重新遍历最终 B-Rep 并重新命名。

### 0.1 禁止事项

必须禁止以下做法：

1. 禁止通过面数组序号、`runtime_index`、`Face17`、`side_face_3` 等运行时枚举值生成长期身份。
2. 禁止通过 `mod_i % len(prev_pids)`、`pop(0)`、列表顺序或 producer 排序猜测旧 PID。
3. 禁止把全部新实体统一挂到 `ancestor_pids[:1]`。
4. 禁止在拓扑传播异常时使用 `except Exception: pass` 静默吞错。
5. 禁止将“Registry 中有实体”“有多个 producer”“存在 generation>0”作为持久命名正确的充分证据。
6. 禁止在操作完成后根据最终 Registry 反向伪造 Timeline。
7. 禁止同时对同一操作执行 history-aware 注册和全量 semantic naming 注册（当前 Revolve 和 Boolean 代码正是这样做的——见 §1.3、§1.4）。
8. 禁止把 `gcad_topology_v3` 文件外壳当成 V3 身份已实现的证明。
9. 禁止保留 V2 writer 作为生产路径。
10. 禁止只修测试脚本或验证报告，不修生产 Handler。
11. 禁止在无法建立精确关系时伪造 `exact`、`modified`、`ancestor` 或 `descendant`。
12. 禁止让 CAE 消费 `ambiguous`、`unresolved`、过期 locator 或弱证明实体。

### 0.2 必须遵守的执行原则

1. 几何操作先成功并写入 ObjectStore，拓扑事务才能提交。
2. 每个拓扑相关操作必须产生一份真实、不可变的操作事件。
3. 所有最终子形状必须被覆盖且只被覆盖一次。
4. 所有输入子形状必须被明确分类。
5. 无法证明时必须 fail-closed，或显式降级为 `UNRESOLVED/AMBIGUOUS`。
6. 对涡轮盘严格测试，任何 unresolved 或 ambiguous 都应导致测试失败。
7. 保持 V1/V2 reader 仅用于迁移；生产 writer 只能写 V3。
8. 不改变现有涡轮盘几何设计意图，除非为获取正确 OCCT history 必须替换几何调用方式。
9. 每一个阶段都必须有单元测试和集成测试，不能最后一次性补测试。
10. 最终提交必须包含代码、测试、迁移说明、生成物和新旧结果差异报告。

---

# 1. 当前问题基线

当前代码已经存在以下基础设施：

- `TopologyIdentityDescriptorV3`
- `TopologyEntityRecord`
- `TopologyRelation`
- `TopologyDelta`
- `TopologyRegistry`
- `TopologyTransaction`
- `ShapeBindingService`
- OCCT history wrapper
- Registry lineage 字段
- Sidecar 和 strict resolution 框架

但是当前生产链仍存在以下关键缺陷。

## 1.1 V3 数据模型未贯通 Handler

`models.py` 已明确说明 V3 字段目前主要是数据模型定义，尚未完整接入 Handler。当前记录可能缺少：

- `identity_descriptor`
- `lifecycle`
- `binding_state`
- `proof_class`
- `owner_body_revision_id`
- 可靠的 `current_locator`

修复后，任何以 `gct3_` 开头的记录都必须完整携带 V3 descriptor，不能只保留不可逆 hash。

## 1.2 Revolve/Extrude 仍存在 V2 writer

`sketch_profile/handlers.py` 中仍调用 `make_persistent_id_v2()`。

修复后：

- 生产代码不得调用 `make_persistent_id_v2()`；
- `document_id` 和 `producer_node_id` 不得作为长期身份核心；
- 必须使用：
  - `document_lineage_id`
  - `component_stable_id`
  - `feature_stable_id`
  - `semantic_path`
  - `source_entity_keys`
  - `branch_key`

## 1.3 Revolve 存在重复注册路径

当前 `sketch_profile/handlers.py` 的 revolve 处理有两条独立的生产路径：

1. **history-aware 路径**（L234-238）：在 `hr is not None` 分支中调用
   `_try_produce_revolve_profile_topology(history_result=hr)`，后者在 history 可用时
   使用 `make_persistent_id_v2()` + `ShapeBindingService.locate_subshape()` 创建 entity records
   并注册到 transaction。

2. **guaranteed semantic naming 路径**（L266-291）：**无论 history 路径是否成功执行**，
   始终在 `object_store.put_solid()` 之后调用 `name_revolve_faces()` +
   `build_entity_records_from_delta()` 并单独启动一个 transaction。代码注释明确标注为
   "V3: guaranteed topology registration via semantic naming"。

这会导致：
- 同一个 revolve 结果有两套拓扑名称（history-aware 产生 `revolved.from/edge_N`，semantic 产生 `revolve/lateral_N`）
- 两次独立的 transaction 提交
- 真实 OCCT history 与事后语义枚举竞争
- 异常仅写 `ctx.topology_warnings`，权威来源不明确

## 1.4 Boolean 的旧 PID 映射是猜测

`composition/handlers.py` 的 `_try_produce_boolean_topology()` 中存在以下代码：

```python
# L449：对 modified faces 按列表轮询猜测哪个 PID 被修改
pid = prev_pids[pn][mod_i % len(prev_pids[pn])]

# L466：对 deleted entities 通过 pop(0) 消耗列表来猜测删除
pid = prev_pids[pn].pop(0)

# L549：所有新实体统一挂到第一个 ancestor
rec.ancestor_ids = ancestor_pids[:1]
```

此外 L479 的 `except Exception: pass` 静默吞掉整个 history 更新路径的所有异常。

必须删除以上逻辑及所有等价实现。
旧 PID 必须由真实 source `TopoDS_Shape` 的绑定表解析，不能由列表位置猜测。

## 1.5 Place 与 Pattern 没有身份传播

当前 `composition/handlers.py` 中以下 Handler **完全不产生拓扑事件**（无 `topology_transaction`、
无 `topology_events.append`、无 registry 更新）：

- `handle_translate_solid` (L54)
- `handle_rotate_solid` (L82)
- `handle_place_component` (L108)
- `handle_circular_pattern_component` (L179)
- `handle_linear_pattern_component` (L219)

当前 Registry 的 producer 字段主要只来自：
- revolve (sketch_profile)
- extrude (sketch_profile)
- final boolean (composition)

修复后至少应有操作事件覆盖：revolve / extrude / place / circular pattern / boolean cut。

## 1.6 当前 Timeline 事件格式简陋，缺乏结构化信息

当前 Handler 中通过 `ctx.topology_events.append({...})` 在运行时记录事件（而非事后统计），
但事件格式仅为简单 dict（如 `{"event": "...", "node_id": ..., "face_count": ...}`），
缺少关键的结构化字段。

当前事件字典不包含：
- Registry hash before/after
- Body revision before/after
- 真正的 relation 数量统计
- history provider 版本
- created/modified/unchanged/split/merged/deleted 分类计数
- ambiguous/unresolved 计数
- source/result 覆盖率

另外，`verify_timeline_deep.py` 等验证脚本通过事后遍历 Registry 的 `_entities` 进行
Timeline 分析（按 `producer_node_id` 分组、对比 before/after 快照），这在验证上是
有价值的，但不能替代 Handler 内部产生的结构化事件。

修复后，每个 topology transaction 成功提交时必须产生一个完整的 `TopologyTimelineEvent`
结构化记录（见 §4.6），包含上述全部字段。

## 1.7 当前涡轮盘谱系是人为星形图

当前结果表现为：
- 3015 个实体都有一个祖先
- 只有一个实体拥有 3015 个后代

这不是有效的逐面谱系。根因在 `composition/handlers.py:549`：
```python
rec.ancestor_ids = ancestor_pids[:1]
```
这行代码把所有新创建实体统一链接到第一个已有 PID，形成以该 PID 为中心的星形结构，
而不是基于真实 OCCT 面关系的 DAG。

---

# 2. 目标状态与系统不变量

以下不变量必须写成代码断言和测试。

## I-01：稳定身份与运行时状态解耦

Persistent ID 不得依赖：

- 运行时面序号；
- Python `id()`；
- 内存地址；
- ObjectStore 临时 handle；
- `producer_node_id`；
- document revision；
- STEP 内实体枚举顺序。

## I-02：生命周期、绑定状态、证明强度相互独立

必须分别维护：

```text
lifecycle:
    ACTIVE / SUPERSEDED / DELETED

binding_state:
    BOUND / STALE / AMBIGUOUS / UNRESOLVED / UNBOUND

proof_class:
    EXACT_GENERATED_HISTORY
    EXACT_MODIFIED_HISTORY
    DETERMINISTIC_CONSTRUCTION
    VERIFIED_REBIND_UNIQUE
    FINGERPRINT_CANDIDATE
    AMBIGUOUS_SET
    NONE
```

不得再用一个 `status` 或 `resolution_method` 混合表示三类状态。

## I-03：Active Exact 必须具有当前绑定

满足以下任一情况必须报错：

```text
ACTIVE + UNBOUND
ACTIVE + 无 locator
ACTIVE + locator body revision 过期
ACTIVE + locator 无法解析
EXACT proof + 不能绑定实际 OCP subshape
```

## I-04：每个拓扑相关操作必须有权威 Delta/Event

以下操作必须提供拓扑事件：

- primitive/revolve/extrude
- translate/rotate/place
- linear/circular pattern
- boolean union/cut/intersection
- fillet/chamfer/shell
- loft/sweep
- 导入/重绑定

## I-05：每个关系的 source PID 必须真实存在

`modified/deleted/split/merged/unchanged` 关系中的 source PID：

- 必须已在 Registry 中；
- 必须能绑定到该操作的输入 B-Rep；
- 不允许使用 history wrapper 内部字符串充当 PID；
- 不允许临时创建一个同名 source record 使验证通过。

## I-06：谱系只能由真实关系生成

- 一对一修改：通常保留同一 PID。
- 一对多分裂：旧 PID superseded，子实体获得新 PID。
- 多对一合并：源 PID superseded，结果获得新 PID。
- 删除：旧 PID deleted。
- 未变化/刚体变换：保留 PID。
- 新生成：使用稳定 source keys 和 branch key 创建新 PID。

## I-07：语义和指纹只能作为有限回退

语义分类和指纹匹配不得自动升级为 `EXACT_*`。

严格涡轮盘测试中：

- Boolean 必须依赖 OCCT history 或同等级确定性构造证据；
- 如果 history 无法覆盖全部结果，测试失败；
- 不得通过 `name_boolean_faces()` 对最终面全量重新命名后宣称持久。

## I-08：Timeline 必须是运行时不可变事件流

每个事件在事务提交时生成，禁止运行结束后根据 Registry 反推。

## I-09：相同设计重建必须稳定

同一设计、同一稳定特征身份、同一算法版本：

- PID 集合相同；
- descriptor 相同；
- 逻辑实体映射相同；
- 仅 locator、body revision、artifact digest 可以变化。

## I-10：CAE 必须 fail-closed

CAE load/constraint/contact 只能使用满足策略要求的实体：

- lifecycle active；
- binding bound；
- locator 当前有效；
- proof strength 达标；
- cardinality 正确；
- 无 ambiguous/unresolved。

---

# 3. 建议的目标架构

不要新建一套与现有系统平行的拓扑系统。应以现有 V3 类为基础补齐链路。

```text
Canonical Node
    │
    ├── stable design identity
    │     document_lineage_id
    │     component_stable_id
    │     feature_stable_id
    │
    ├── input body handles
    │
    ▼
OperationInputTopologySnapshot
    │
    ├── source TopoDS subshape
    ├── source PersistentTopoId
    ├── source locator
    ├── owner body revision
    └── input occurrence/branch
    │
    ▼
OCCT operation + history provider
    │
    ▼
KernelHistoryGraph
    │
    ├── Generated
    ├── Modified
    ├── Deleted
    ├── unchanged occurrence
    └── reverse result-to-source edges
    │
    ▼
IdentityTransferPolicy
    │
    ├── unchanged / relocated
    ├── modified_same_identity
    ├── generated_new_identity
    ├── generated_from_tool
    ├── split
    ├── merge/repartition
    ├── consumed/deleted
    └── ambiguous/unresolved
    │
    ▼
V3 records + locators + lineage
    │
    ▼
TopologyTransaction
    │
    ├── validate coverage
    ├── validate bindings
    ├── validate DAG
    ├── commit Registry
    └── append TimelineEvent
```

---

# 4. 必须新增或完善的核心对象

命名可以按现有项目风格调整，但职责不得缺失。

## 4.1 DesignIdentityContext

`design_identity.py` 中已存在 `DesignIdentity`（含 `design_id` / `revision_id` / `run_id` /
`identity_source`）。需新增一个运行时包装器，放置于 topology 或 runtime context 中：

```python
class DesignIdentityContext(BaseModel):
    document_lineage_id: str
    document_revision_id: str
    component_stable_ids: dict[str, str]
    feature_stable_ids: dict[str, str]
    identity_algorithm_version: str = "3.1.0"
    design_identity: DesignIdentity | None = None  # 复用已有模型
```

要求：

- `document_revision_id` 不进入 PID。
- `producer_node_id` 仅用于 provenance。
- 如果 Canonical IR 缺少 `feature_stable_id`，严格模式禁止执行。
- 临时兼容模式可以回退到 node ID，但必须标记 `ephemeral_identity=true`，且不能通过 V3 严格验收。

## 4.2 BoundTopologyOccurrence

```python
class BoundTopologyOccurrence(BaseModel):
    persistent_id: str
    entity_type: str
    input_slot: str
    owner_body_handle_id: str
    owner_body_revision_id: str
    locator: RuntimeTopoLocator
    occurrence_key: str
    component_stable_id: str
    branch_key: str | None
```

实际 `TopoDS_Shape` 可保存在运行时 dataclass，不需要 Pydantic 序列化。

## 4.3 OperationInputTopologySnapshot

```python
class OperationInputTopologySnapshot:
    operation_execution_id: str
    node_id: str
    inputs: dict[str, list[BoundTopologyOccurrence]]
    shape_to_pid: exact in-memory lookup
    pid_to_shape: exact in-memory lookup
    registry_hash_before: str
```

该对象必须在调用几何内核之前构建。

## 4.4 KernelHistoryEdge（完善已有模型）

`kernel_identity.py` 中已存在 `KernelHistoryEdge`，当前字段为：
- `source_pid: str`
- `result_occurrence_key: str`
- `kernel_relation: KernelRelation` (SAME / MODIFIED / GENERATED / REMOVED)

需要新增以下字段使其能携带完整的操作上下文：

```python
class KernelHistoryEdge(BaseModel):
    source_pid: str
    source_occurrence_key: str          # 新增：本次操作的 source occurrence
    result_occurrence_key: str
    relation: KernelRelation            # 已有，重命名为 kernel_relation 亦可
    input_role: Literal["target", "tool", "seed", "other"]  # 新增
    provider: str                       # 新增
    provider_version: str               # 新增
    evidence: dict                      # 新增
```

## 4.5 IdentityDecision（完善已有模型）

`kernel_identity.py` 中已存在 `IdentityDecision`，当前字段为：
- `source_pids: list[str]`
- `result_keys: list[str]`（occurrence key，非最终 PID）
- `identity_relation: IdentityRelation`（11 种值：UNCHANGED ~ DELETED）
- `policy_id: str`
- `provenance_edges: list[KernelHistoryEdge]`
- `primary_identity_source: str | None`
- `orientation_before/after`, `location_before/after`, `occurrence_change`

需要补充以下字段和枚举值：

```python
class IdentityDecision(BaseModel):
    identity_relation: Literal[
        "unchanged",
        "relocated",
        "reoriented",
        "modified_same_identity",
        "generated_new_identity",
        "generated_from_tool",
        "split",
        "merge",
        "repartition",
        "consumed",
        "deleted",
        "ambiguous",       # 新增枚举值
        "unresolved",      # 新增枚举值
    ]
    source_pids: list[str]
    result_occurrence_keys: list[str]
    result_pids: list[str]              # 新增：最终分配的 PID（区别于 occurrence key）
    provenance_edges: list[KernelHistoryEdge]
    policy_id: str
    proof_class: ProofClass             # 新增
```

`TopologyRegistry.apply_identity_decisions()` 已有完整实现（`registry.py:147-291`），
目前未被任何 Handler 调用。应把它改造为 V3 主入口，不再继续维护 `apply_delta` 与
手工字段修改两条互相竞争的路径。

## 4.6 TopologyTimelineEvent

```python
class TopologyTimelineEvent(BaseModel):
    sequence: int
    operation_execution_id: str
    node_id: str
    op: str
    component_id: str
    timestamp_utc: str

    registry_hash_before: str
    registry_hash_after: str

    input_body_revisions: dict[str, str]
    output_body_revisions: dict[str, str]

    history_provider: str
    history_provider_version: str
    policy_id: str

    counts: dict[str, int]
    source_coverage: dict
    result_coverage: dict

    created_pids: list[str]
    preserved_pids: list[str]
    modified_pids: list[str]
    superseded_pids: list[str]
    deleted_pids: list[str]
    ambiguous_pids: list[str]
    unresolved_occurrences: list[str]

    warnings: list[dict]
```

事件只允许在事务成功提交后追加。

---

# 5. 文件级修改指导

## 5.1 `topology/ids.py`

### 必须修改

1. 保留 V1/V2 parse reader。
2. 所有生产 writer 统一使用 `make_persistent_id_v3()`。
3. 增加稳定 branch key 构造辅助函数。
4. 禁止 semantic path 中的 ordinal/runtime index。
5. 将当前”Phase 4+ 才拒绝 ordinal token”改为严格模式立即拒绝。
   当前代码 `ids.py:283` 注释：
   `”NOTE: Ordinal index rejection (face_3, lateral_2) is deferred to Phase 4+”`
6. 增加 PID descriptor 一致性验证：

```python
assert descriptor.to_key() == record.persistent_id
```

### Branch key 规则

Branch key 应基于稳定操作语义，而不是最终面序号。

示例：

```text
pattern occurrence:
    occurrence:000000
    occurrence:000001

split branch:
    split:<stable geometric branch token>

generated from source:
    source:<source PID digest>/role:<semantic token>
```

对于阵列，建议以稳定 occurrence ordinal 为主。阵列数量变化时，已存在 ordinal 身份保留；几何位置变化通过 generation/body revision 表示。

---

## 5.2 `topology/models.py`

### 必须修改

1. 对 `gct3_` 记录强制要求：
   - `identity_descriptor != None`
   - `lifecycle != None`
   - `binding_state != None`
   - `proof_class != None`
   - active 记录有 owner body revision 和 locator。
2. 将 deprecated 字段保留为读取兼容，不再作为生产逻辑权威。
3. 增加 V3 交叉验证：
   - descriptor key 等于 PID；
   - active exact 必须 bound；
   - deleted/superseded 不得保留 current locator；
   - `ancestor_ids`/`descendant_ids` 不得包含自身；
   - exact proof 必须包含 kernel/construct evidence。
4. `TopologyRelation` 不应把 kernel 临时 key 放入 `source_ids`。
5. 增加或完善 KernelHistoryEdge、IdentityDecision、TimelineEvent。

---

## 5.3 `topology/shape_binding.py`

### 必须新增

1. `build_operation_input_snapshot(...)`
2. `bind_registry_entities_to_input_body(...)`
3. `find_pid_for_exact_source_shape(...)`
4. `refresh_result_locators(...)`
5. `verify_all_active_bindings(...)`

### 映射要求

操作前：

```text
input body IndexedMap position
+ exact TopoDS_Shape identity in current operation
+ Registry locator
→ old PID
```

必须验证：

- locator owner body handle 正确；
- owner body revision 正确；
- IndexedMap 位置有效；
- 实际实体类型匹配；
- 一个输入 occurrence 不得映射多个不等价 PID；
- 一个 active PID 不得无故映射到多个输入 occurrence。

### 注意

IndexedMap position 只能用作当前 body revision 的 locator，不能进入 Persistent ID。

---

## 5.4 `topology/history_wrappers.py`

### 必须修改

History wrapper 不应仅返回不可追溯字符串 key。

必须返回：

- 原始 source `TopoDS_Shape` 或可反向找到 source shape 的 occurrence；
- 原始 result `TopoDS_Shape`；
- Generated/Modified/Deleted；
- 操作输入角色 target/tool；
- provider/version；
- operation result shape。

推荐先将所有 source/result face 放入本次操作的 occurrence map：

```text
src:target:face:<map-position>
src:tool:face:<map-position>
res:face:<map-position>
```

这些 occurrence key 仅用于本次操作，不是 Persistent ID。

### Boolean 结果必须包含反向索引

```text
result occurrence → source history edges
```

这是判断 split、merge、generated-from-tool 的必要条件。

---

## 5.5 `topology/registry.py`

### 必须修改

1. `apply_identity_decisions()`（`registry.py:147-291`）已有完整实现但从未被 Handler 调用。
   应使其成为 V3 主要入口。当前实现的问题：创建新 record 时不填充 V3 字段
   （`identity_descriptor`、`lifecycle`、`binding_state`、`proof_class` 均为 None），
   且 `owner_body_handle_id` 设为空字符串。
2. 不允许直接从 Handler 访问和修改 `reg._entities`。
3. 增加正式 API：
   - preserve/relocate entity
   - modify same identity
   - create generated entity
   - split
   - merge
   - consume occurrence
   - delete
   - rebind
4. 维护所有索引的一致性：
   - body index
   - node event index
   - alias index
   - shape index
5. 更新 PID 的 owner body 时，必须从旧 body index 移除并加入新 body index。
6. `modified_same_identity`：
   - PID 不变；
   - generation + 1；
   - locator、owner body handle、revision 更新；
   - lifecycle active；
   - binding bound；
   - proof exact modified history。
7. `relocated`：
   - PID 不变；
   - generation 不变；
   - owner body revision 和 locator 更新；
   - evidence 记录 transform；
   - proof deterministic construction。
8. `split`：
   - source superseded；
   - source locator 清空；
   - children 新 PID；
   - 双向 lineage 完整。
9. `merge`：
   - 所有 sources superseded；
   - result 新 PID；
   - 多祖先；
   - 双向 lineage 完整。
10. `deleted`：
    - lifecycle deleted；
    - binding unbound；
    - locator 清空。
11. `consumed` 与 `deleted` 必须区分：
    - 可复用 seed/tool component 本体不应因被用作布尔刀具而全局删除；
    - 阵列 occurrence 可以在 assembly branch 中 consumed；
    - 原始 seed body identity 可以继续 active。
12. 禁止未知 source 自动忽略。
13. 增强 `validate_integrity()`：
    - DAG 无环；
    - 双向边一致；
    - active binding 有效；
    - descriptor/PID 一致；
    - 不存在 fake star lineage；
    - source/result coverage 合法；
    - 同一 final occurrence 只能绑定一个 active PID。

---

## 5.6 `topology/transaction.py`

### 必须修改

事务提交顺序：

```text
1. Geometry 已进入 ObjectStore
2. 校验 result body handles
3. 校验 body revisions
4. 应用 identity decisions
5. 刷新 result locators
6. 校验 source coverage
7. 校验 result coverage
8. 校验 Registry integrity
9. 原子提交 Registry
10. 追加 TimelineEvent
```

`validate_geometry_bindings()`（`transaction.py:130`）已实现但 `commit()` 方法（`transaction.py:98`）
不调用它——只调用 `validate_integrity()`。不能只是存在但不调用。

严格模式下：

- 任意覆盖缺口；
- 任意 stale locator；
- 任意 exact proof 无绑定；
- 任意 lineage 不一致；

都必须 rollback。

---

## 5.7 `topology/semantic_naming.py`

### 必须修改

1. `_make_compact_id()`（`semantic_naming.py:298-331`）已调用 `make_persistent_id_v3()` 产生
   `(key, descriptor)` 元组，但 `_make_compact_key()`（`semantic_naming.py:334-352`）丢弃了
   descriptor 只返回 key。因此所有通过 `_make_compact_key()` 生成的记录都没有 descriptor。
2. `build_entity_records_from_delta()`（`semantic_naming.py:213-269`）不设置 `identity_descriptor`、
   `lifecycle`、`binding_state`、`proof_class` —— 这些 V3 字段在 records 中全为 None。
3. `feature_uid` 在严格模式必须提供。
4. 去除以下长期身份角色：
   - `fallback/{i}`
   - `face_{i}`
   - `side_face_{i}`
   - `lateral_{i}`
   - 任何依赖运行时枚举的 token。
5. fallback 记录：
   - proof 必须是 `FINGERPRINT_CANDIDATE`、`AMBIGUOUS_SET` 或 `NONE`；
   - 不得被 CAE exact 消费；
   - 涡轮盘严格测试中直接失败。
6. `name_boolean_faces()` 不得作为完整 Boolean 的权威命名路径。
7. 原始 Primitive 可以使用确定性构造语义命名，但需要稳定 sketch element ID、profile edge ID 或 operation source key。
8. `build_entity_records_from_delta()` 不得为 `modified/deleted` 的 source key 临时创建新 record。

---

## 5.8 `dialects/sketch_profile/handlers.py`

### Revolve

1. 删除 V2 writer。
2. 删除重复的 history-aware + guaranteed semantic 双注册。
3. 在调用 `BRepPrimAPI_MakeRevol` 前，对 profile edges 建立稳定 edge identity。
4. 使用 `Generated(profile edge)` 建立结果面：
   - source_entity_keys 为稳定 profile edge PID；
   - semantic path 来自 sketch element semantic role；
   - 多结果时使用稳定 branch key。
5. 对 cap/start/end 使用 operation semantics。
6. 所有结果面建立 locator、revision、proof。
7. 同一操作仅提交一次事务。

### Extrude

当前 `sketch_profile/handlers.py:_try_produce_extrude_profile_topology()` (L296-326) 仅使用
semantic naming（`name_extrude_faces()` + `build_entity_records_from_delta()`），
未使用 `history_aware_extrude` wrapper。

需要修改：
1. 必须真正使用 history-aware extrude wrapper（`history_wrappers.py:240`）。
2. 侧面身份来自稳定 sketch edge identity（通过 `extract_sketch_element_ids()`）。
3. cap 身份来自稳定 profile region/operation semantics。
4. 禁止 `side_face_N`（当前 `name_extrude_faces` 使用 `extrude/side_face_{side_count}`）。
5. 禁止 V2 writer。
6. 同一操作仅提交一次事务。

### Sketch 元素

需要保证 Canonical sketch 节点具有稳定 `element_id/feature_uid`：

- line
- arc
- circle
- polyline segment
- fillet result

如 polyline 当前只有一个节点，必须为每一条 segment 生成稳定 element ID，不能只依赖 wire edge 枚举。

---

## 5.9 `dialects/composition/handlers.py`

这是修复重点。

### 5.9.1 Place/Translate/Rotate

刚体变换通常不改变拓扑身份。

处理流程：

```text
capture source snapshot
execute transform
store result body
build result maps
对每个 source PID：
    根据确定性 transform 找到对应 result subshape
    保持 PID
    generation 不变
    更新 owner body handle/revision/locator
    relation = relocated/reoriented
commit
```

如果 CadQuery transform 重建 shape，仍需要通过确定性一一对应或 OCCT copy/transform history建立映射。

### 5.9.2 Circular/Linear Pattern

当前“复制后不断 union”会过早丢失实例身份。

建议优先方案：

#### 方案 A：保留工具实例集合

Pattern 输出不立即合并为一个无身份的整体，而是保存：

```text
PatternHandle
    seed body
    occurrence bodies
    occurrence branch keys
    occurrence topology map
```

Boolean 可以：

- 逐实例切割并捕获每次 history；
- 或使用支持完整 history 的批量 BOP。

#### 方案 B：如必须 Fuse Pattern

每次 fuse 都必须：

- capture source snapshot；
- 捕获 fuse history；
- 更新身份；
- 不能完成 60 次 union 后才统一命名。

### Pattern PID

每个实例的拓扑 PID 应由：

```text
document_lineage_id
component_stable_id
pattern_feature_stable_id
source_entity_keys=(seed PID,)
branch_key=occurrence:<stable ordinal>
semantic_path=seed entity semantic path
```

构成。

当 count 60→61：

- occurrence 0..59 的 PID 保持；
- occurrence 60 新建；
- 如果位置改变，原 PID generation 增加或记录 relocated；
- 不允许全部换 PID。

### 5.9.3 Boolean Cut/Union

必须完全删除当前按列表猜 PID 和统一祖先的代码。

正确流程见第 6 章。

---

## 5.10 `topology/persistence.py`

### 必须修改

当前 `persistence.py` 已部分支持 V3：
- `write_topology_sidecar()` 接受 `design_identity` 参数，提取 `document_lineage_id`、
  `identity_source`、`design_id`
- 调用 `canonicalize_sidecar()` 进行确定性排序和完整性哈希
- 但 `export_snapshot()` 显式剥离 `current_locator`（runtime-only），且 entity records
  中 V3 字段（`identity_descriptor`、`lifecycle`、`binding_state`、`proof_class`）因为
  Handler 不填充而全部为 None/null

需要修改：

1. V3 sidecar 中，每个 `gct3_` record 必须有 descriptor。
2. schema 版本应反映真实能力：
   - legacy/mixed 不得标记 strict V3。
3. 保存：
   - document lineage；
   - document revision；
   - identity algorithm version；
   - registry hash；
   - body revisions；
   - timeline artifact hash；
   - entity descriptor；
   - lifecycle/binding/proof；
   - lineage；
   - evidence。
4. runtime locator 是否持久化要明确：
   - 可保存用于同一 artifact 的重绑定；
   - 不能作为跨 rebuild 身份。
5. 加载后必须验证 descriptor→PID。
6. 如果缺 descriptor：
   - 标记 legacy；
   - strict V3 加载失败。
7. Sidecar hash 只证明文件完整性，报告不得把它解释为身份正确性。

---

## 5.11 Runtime Context / Pipeline

必须提供：

- `DesignIdentityContext`
- `TopologyTimelineRecorder`
- strict topology mode
- operation execution ID
- body revision service
- topology coverage report

生产 Pipeline 不得在最终阶段后处理伪造节点时间线。

---

# 6. Boolean 身份传播算法

以下算法是本任务最核心的实现要求。

## 6.1 操作前快照

对 target 和 tool 分别构建：

```python
target_snapshot = capture_topology(
    body_handle=target_handle,
    input_role="target",
    registry=registry,
    binding_service=binding_service,
)

tool_snapshot = capture_topology(
    body_handle=tool_handle,
    input_role="tool",
    registry=registry,
    binding_service=binding_service,
)
```

必须获得：

```text
exact source TopoDS_Face
↔ source PID
↔ source locator
↔ input role
↔ body revision
```

如果 active face 无法绑定，严格模式下 Boolean 不得执行。

## 6.2 执行同一个有 history 的 OCCT Builder

不得先使用 CadQuery `target.cut(tool)` 生成结果，再另外运行一次 OCCT cut 只为了 history。

几何结果和 history 必须来自同一个 Builder 实例，否则 history 与实际保存结果可能不一致。

建议流程：

```python
builder = BRepAlgoAPI_Cut(target_shape, tool_shape)
builder.SetFuzzyValue(...)
builder.Build()

result_shape = builder.Shape()
history = read_history_from_same_builder(builder, source_snapshot)
```

如 CadQuery wrapper 无法暴露同一 builder，应直接在 `boolean_safe`/history wrapper 中返回：

- result shape；
- builder；
- history graph；
- diagnostics。

## 6.3 为每个 source 建立 history edge

对每个 target/tool source occurrence：

```text
modified = builder.Modified(source_shape)
generated = builder.Generated(source_shape)
deleted = builder.IsDeleted(source_shape)
```

所有返回 shape 必须映射到 result body occurrence。

## 6.4 识别 unchanged

有些未受影响面不会出现在 Modified/Generated 中。

必须在结果中通过同一操作上下文中的 exact shape identity 或可靠的 OCCT sameness 检查确认 pass-through：

```text
source occurrence → result occurrence
relation = unchanged
```

仅使用几何指纹不能判定 exact unchanged。

## 6.5 反向聚合结果来源

构建：

```text
result occurrence
    ← zero/one/multiple target sources
    ← zero/one/multiple tool sources
```

然后分类。

## 6.6 身份决策规则

### A. Unchanged/Relocated

条件：

- 一个旧 PID 对应一个结果 occurrence；
- 无拓扑结构变化；
- 仅位置、方向或 owner revision 改变。

行为：

- PID 不变；
- generation 不变；
- locator/revision 更新；
- proof deterministic 或 exact pass-through。

### B. Modified Same Identity

条件：

- 一个 source PID；
- 一个 result occurrence；
- history 明确 Modified；
- 没有分裂或合并。

行为：

- PID 不变；
- generation + 1；
- 更新 locator/revision；
- proof `EXACT_MODIFIED_HISTORY`。

### C. Split

条件：

- 一个 source PID 对应多个 result occurrences。

行为：

- source superseded；
- 每个 child 新 V3 PID；
- `source_entity_keys=(source PID,)`；
- 每个 child 有稳定 branch key；
- 双向 lineage。

### D. Merge/Repartition

条件：

- 一个 result occurrence 有多个 source PID。

行为：

- 所有 source superseded；
- result 新 V3 PID；
- `source_entity_keys=sorted(source PIDs)`；
- result 多祖先；
- 双向 lineage。

### E. Generated From Tool

切槽壁面通常由刀具侧面或边界生成。

行为：

- result 新 V3 PID；
- source keys 指向具体 pattern occurrence 的 tool PID；
- semantic path 继承工具语义，例如 slot/lobe/flank/root；
- branch key 包含阵列 occurrence；
- 不得统一挂到盘体第一个面。

### F. Generated New Identity

由相交、封口等产生且没有单一可继承 source identity。

行为：

- 使用完整 source set 和 operation feature stable ID 创建新 PID；
- proof exact generated history；
- 记录所有 provenance edges。

### G. Deleted/Consumed

必须区分：

- target 面实际消失：deleted/superseded；
- pattern tool occurrence 被消费：assembly occurrence consumed；
- 可复用 seed tool component 不应全局 deleted。

### H. Ambiguous/Unresolved

如果一个结果 occurrence 无法唯一分类：

- 不创建虚假的 exact PID；
- 记录 unresolved；
- 严格涡轮盘测试 rollback 并失败。

---

# 7. 覆盖率与完整性检查

每个严格操作必须计算两类覆盖率。

## 7.1 Source Coverage

每个输入 occurrence 必须进入且只进入合理分类：

```text
unchanged
modified
split
merge/repartition
deleted
consumed
```

要求：

```text
unclassified input occurrences = 0
illegal multiple classifications = 0
```

## 7.2 Result Coverage

每个最终 result face 必须拥有且只拥有一个 active identity：

```text
unbound result faces = 0
duplicate-bound result faces = 0
ambiguous result faces = 0
```

## 7.3 Lineage Integrity

要求：

- DAG 无环；
- ancestor/descendant 双向一致；
- 无 dangling PID；
- source 和 result 关系与 history edge 一致；
- 不允许一个无证据祖先拥有几乎所有结果；
- split/merge cardinality 与实际 history 一致。

---

# 8. Timeline 正确实现

## 8.1 捕获时机

Timeline Event 必须在每个 topology transaction 成功提交时产生。

不得在流水线结束后做：

```text
for node in nodes:
    按 producer 查询 Registry
    猜 before/after
```

## 8.2 涡轮盘预期 Timeline

至少应看到：

```text
n_revolve_disc:
    created > 0
    provider = occt_make_shape
    delta = true

n_extrude_cutter:
    created > 0
    provider = occt_make_shape
    delta = true

n_place_disc:
    relocated/preserved > 0
    provider = deterministic_transform
    delta = true

n_pattern_cutters:
    created occurrences > 0
    provider = deterministic_pattern
    delta = true

n_bool_cut_all:
    modified/generated/deleted/consumed > 0
    provider = occt_boolean_history
    delta = true
```

`entities_before` 必须是真实提交前 Registry 数量，不能在 Boolean 前就等于最终数量。

---

# 9. 报告与产物要求

新的测试输出目录至少应包含：

```text
canonical.json
raw_fixed.json
result.step
topology_sidecar.json
topology_registry.json
topology_timeline.json
topology_coverage_report.json
topology_lineage_report.json
pid_stability_report.json
rebuild_comparison_report.json
e2e_verification_report.json
```

## 9.1 `e2e_verification_report.json`

必须包含硬指标：

```json
{
  "strict_v3": true,
  "v3_pid_count": 0,
  "v3_descriptor_count": 0,
  "legacy_pid_count": 0,
  "active_bound_count": 0,
  "active_unbound_count": 0,
  "exact_proof_count": 0,
  "ambiguous_count": 0,
  "unresolved_count": 0,
  "ops_with_topology_events": [],
  "source_coverage": {},
  "result_coverage": {},
  "same_rebuild_pid_set_equal": false,
  "same_rebuild_descriptor_set_equal": false,
  "node_rename_pid_set_equal": false,
  "lineage_integrity_ok": false,
  "all_passed": false
}
```

### `all_passed` 必须满足

```text
v3_pid_count == total V3 records
v3_descriptor_count == v3_pid_count
legacy_pid_count == 0
active_unbound_count == 0
ambiguous_count == 0
unresolved_count == 0
所有要求的操作有真实 topology event
source coverage = 100%
result coverage = 100%
same rebuild PID set equality = true
node rename PID set equality = true
lineage integrity = true
```

任何一项失败，`all_passed=false`。

---

# 10. 测试矩阵

## 10.1 单元测试

### ID 稳定性

1. node rename 不改变 PID。
2. document revision 改变不改变 PID。
3. document lineage 改变必须改变 PID。
4. component stable ID 改变必须改变 PID。
5. feature stable ID 改变必须改变 PID。
6. source entity keys 改变必须改变 generated PID。
7. branch key 改变必须改变 split/pattern PID。
8. runtime index 不得进入 semantic path。
9. descriptor 重新计算必须等于 PID。

### Registry

1. modified same identity 保留 PID且 generation+1。
2. relocated 保留 PID且 generation 不变。
3. split 正确 supersede source。
4. merge 正确 supersede multiple sources。
5. deleted 清空 locator。
6. active unbound 被拒绝。
7. lineage 双向不一致被拒绝。
8. lineage 环被拒绝。
9. stale body revision 被 strict resolve 拒绝。

### Binding

1. exact source face 能找到旧 PID。
2. 不同 face 不得映射到同一 PID。
3. stale locator 不能 exact resolve。
4. result locator 能绑定到最终真实 OCP face。
5. ObjectStore 缺失时 transaction 失败。

### History

1. 一对一 modified。
2. 一对多 split。
3. 多对一 merge。
4. generated from target edge。
5. generated from tool face。
6. deleted。
7. unchanged pass-through。
8. reverse result source 聚合。

## 10.2 集成测试

### T1：相同涡轮盘连续重建两次

要求：

- PID 集合完全相同；
- descriptor 集合完全相同；
- 每个逻辑面身份相同；
- locator/body revision 可以不同；
- active final faces 全部 bound。

### T2：仅修改 node ID

只修改：

```text
n_revolve_disc → renamed_revolve_node
```

保持 feature stable ID 不变。

要求 PID 100% 不变。

### T3：插入无几何影响节点

在 DAG 中插入 no-op/audit 节点。

要求 PID 100% 不变。

### T4：Place 参数改变

盘体仅平移。

要求：

- PID 全部不变；
- generation 不变；
- locator 和 body revision 更新；
- Timeline 标记 relocated。

### T5：Pattern 60→61

要求：

- occurrence 0..59 PID 保持；
- occurrence 60 新建；
- 已有 occurrence 位置变化时记录 relocated/modified；
- 不得全量重新命名。

### T6：槽深改变

要求：

- 不受影响的盘体端面、中心孔面 PID 保持；
- 槽壁相关面正确 modified/split/generated；
- 删除关系准确；
- 无 fake ancestor。

### T7：局部轮毂厚度改变

要求：

- 榫槽相关无关面 PID 保持；
- 受影响的轮毂/过渡面正确变化；
- 最终结果无 ambiguous/unresolved。

### T8：输入顺序变化

在不改变设计语义的前提下改变独立节点排列。

要求 PID 不受拓扑枚举顺序影响。

### T9：失败注入

让 history wrapper 缺少一个 source/result 映射。

要求：

- transaction rollback；
- strict test 失败；
- 不得 fallback 后仍 all_passed。

### T10：CAE 门禁

构造：

- deleted PID；
- stale PID；
- ambiguous PID；
- fingerprint-only PID。

要求 CAE preflight 全部拒绝。

---

# 11. 涡轮盘最终验收标准

代码 Agent 完成后，必须使用同一涡轮盘重新生成新目录。

## 11.1 必须通过

1. `v3_descriptors == v3_pid_count`。
2. `legacy_pid_count == 0`。
3. 不再出现生产路径 `make_persistent_id_v2()`。
4. `ops_with_topology_events` 至少包含：
   - `n_revolve_disc`
   - `n_extrude_cutter`
   - `n_place_disc`
   - `n_pattern_cutters`
   - `n_bool_cut_all`
5. 每个相关节点 `delta=true`。
6. 每个相关节点 `provider != none`。
7. Boolean 前 Registry 计数是真实前值，不是最终值。
8. final result face coverage 100%。
9. source coverage 100%。
10. active unbound = 0。
11. ambiguous = 0。
12. unresolved = 0。
13. lineage DAG 无环且双向一致。
14. 不再出现“一个祖先拥有全部最终面”的无证据星形图。
15. 两次完全相同重建 PID 集合相同。
16. node rename 后 PID 集合相同。
17. Sidecar 中 descriptor 可完整恢复 PID。
18. CAE 能通过 stable topology set 解析到实际最终 OCP faces。
19. 任何失败都会使 `all_passed=false`。
20. 测试报告不能引用旧输出目录。

## 11.2 不可作为通过依据

以下指标即使为真，也不能单独说明修复成功：

- Registry 有实体；
- Sidecar 有实体；
- 多个 producer；
- generation 中存在 1；
- STEP 成功输出；
- 两次 Pipeline 均成功；
- Sidecar hash 正确；
- ancestor 数量大于 0。

---

# 12. 分阶段实施顺序

## Phase 0：建立失败基线

先保留当前输出作为 `legacy_broken_baseline`，编写能稳定复现以下失败的测试：

- `v3_descriptors=0`
- Boolean 猜测 PID
- fake star lineage
- Place/Pattern 无事件
- Timeline before/after 错误
- node rename PID 改变
- 相同重建未比较 PID

未建立失败测试前，不开始大规模改动。

## Phase 1：身份上下文和 V3 Record

完成：

- DesignIdentityContext；
- feature stable ID；
- descriptor 必填；
- V2 writer 禁止；
- strict model validators。

## Phase 2：Primitive/Revolve/Extrude

先让最初实体具有正确 V3 身份和绑定。

退出条件：

- revolve/extrude 的所有结果面有 V3 descriptor；
- 无 ordinal identity；
- 无重复注册。

## Phase 3：Place/Transform

实现 PID 保留、locator/revision 更新和 Timeline。

## Phase 4：Pattern

实现 seed→occurrence 身份传播。

优先保持 pattern occurrences 独立，避免过早 union。

## Phase 5：Boolean

实现：

- source snapshot；
- same-builder history；
- result reverse edges；
- identity transfer policy；
- exact source PID mapping；
- coverage；
- strict rollback。

这一阶段完成前，不得宣称 V3 持久命名完成。

## Phase 6：Persistence/Timeline/Reports

修复 Sidecar 和真实 Timeline，增加 rebuild comparison。

## Phase 7：CAE Gate

使用新 V3 strict resolution 更新 NamedTopologySet 和 CAE preflight。

## Phase 8：回归和性能

在正确性全部通过后评估性能。

不得为提高速度重新引入最终全量重命名。

---

# 13. 推荐的提交拆分

建议代码 Agent 不要提交一个巨型补丁。

```text
Commit 1:
    Add failing regression tests for current turbine topology defects

Commit 2:
    Enforce V3 identity context and descriptor invariants

Commit 3:
    Add operation input topology snapshot and exact binding map

Commit 4:
    Migrate revolve/extrude to single authoritative V3 path

Commit 5:
    Implement transform/place identity preservation

Commit 6:
    Implement stable pattern occurrence identity

Commit 7:
    Replace boolean guessed mapping with same-builder OCCT history transfer

Commit 8:
    Strengthen registry transactions, lineage and coverage validation

Commit 9:
    Implement runtime timeline and strict sidecar/reporting

Commit 10:
    Add turbine rebuild, rename, parameter-change and CAE gate tests
```

---

# 14. 代码审查清单

提交前逐项检查：

- [ ] 搜索不到生产代码调用 `make_persistent_id_v2()`。
- [ ] 搜索不到 `mod_i % len(prev_pids)`。
- [ ] 搜索不到 topology 相关 `pop(0)` 猜 PID。
- [ ] 搜索不到 `ancestor_pids[:1]` 批量挂接。
- [ ] 搜索不到 topology 关键路径 `except Exception: pass`。
- [ ] Handler 不直接修改 `reg._entities`。
- [ ] Revolve 不再双重注册。
- [ ] Boolean 结果和 history 来自同一 builder。
- [ ] `identity_descriptor` 不再丢失。
- [ ] feature stable ID 不依赖 node ID。
- [ ] runtime index 不进入 PID。
- [ ] Place 有真实事件。
- [ ] Pattern 有 occurrence 身份。
- [ ] Boolean 有 source/result 100% coverage。
- [ ] Timeline 是提交时生成。
- [ ] strict report 任何一项失败都会 `all_passed=false`。
- [ ] 两次重建比较 PID 和 descriptor，而不只是比较 Pipeline 成功。
- [ ] CAE strict resolve 能绑定真实 OCP shape。
- [ ] 所有新增模型有单元测试。
- [ ] 所有迁移行为有兼容性说明。

---

# 15. 最终交付要求

代码 Agent 完成后必须返回：

1. 修改文件清单。
2. 每个文件的修改目的。
3. 删除的错误逻辑清单。
4. 新增数据模型和接口说明。
5. V1/V2 兼容策略。
6. 完整测试命令。
7. 单元测试结果。
8. 涡轮盘集成测试结果。
9. 两次重建 PID 对比报告。
10. node rename 对比报告。
11. pattern 60→61 对比报告。
12. 局部尺寸变化对比报告。
13. 新输出目录。
14. 新 `topology_timeline.json`。
15. 新 `topology_lineage_report.json`。
16. 新 `topology_coverage_report.json`。
17. 新 `e2e_verification_report.json`。
18. 未解决问题和风险，不得隐瞒。

---

# 16. 最终判定原则

本任务完成的唯一标准不是“最终每个面都有名字”，而是：

> 每一个名称都能说明它从哪里来、经过了什么操作、是否保留身份、是否被修改、是否分裂或合并、当前绑定到哪个真实 B-Rep 子形状，以及这些结论由什么内核历史或确定性构造证据支持。

如果最终结果仍然主要依靠：

```text
遍历最终 faces
→ 按表面类型和序号命名
→ 批量补 ancestor
```

则任务仍然失败。

正确结果必须是：

```text
稳定设计身份
→ 操作前真实源面绑定
→ 同一次 OCCT 操作的真实 history
→ 身份转移决策
→ 原子 Registry 更新
→ 实时 Timeline
→ Sidecar 证据
→ 跨重建验证
→ CAE 严格解析
```

---

## 附：代码 Agent 可直接使用的任务摘要

请深度修改 `text2cad_improve` 的持久化拓扑命名生产链。不要只修改验证报告。首先添加能复现当前缺陷的失败测试；然后将 V3 identity descriptor、lifecycle、binding state、proof class 和 body revision 真正接入 revolve、extrude、place、pattern、boolean。删除 Boolean 中基于 PID 列表轮询、`pop(0)` 和 `ancestor_pids[:1]` 的猜测映射。操作前必须用 ShapeBindingService 建立真实 `TopoDS_Shape ↔ old PID` 快照；几何结果和 OCCT history 必须来自同一个 builder；通过 Generated/Modified/IsDeleted 和结果反向来源图执行 unchanged、modified、split、merge、generated、consumed、deleted 的身份转移。Place 保留 PID 并更新绑定；Pattern 为每个 occurrence 建立稳定 branch identity；Boolean 对 source/result 实体实现 100% 覆盖。拓扑事务失败必须 rollback，关键异常不得吞掉。Timeline 必须在每个事务提交时实时写入，不能事后反推。Sidecar 中每个 gct3 PID 必须保存完整 descriptor。最后使用涡轮盘完成相同重建、node rename、插入无关节点、pattern 60→61、槽深变化、轮毂厚度变化和 CAE gate 测试。严格验收要求 legacy PID=0、active unbound=0、ambiguous=0、unresolved=0、source/result coverage=100%、两次重建 PID 集合完全一致，任何一项失败都必须使 all_passed=false。
