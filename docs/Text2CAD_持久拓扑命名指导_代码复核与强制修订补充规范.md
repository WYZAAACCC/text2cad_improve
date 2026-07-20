# Text2CAD 持久拓扑命名修复指导文档——代码复核与强制修订补充规范

**适用仓库：** `WYZAAACCC/text2cad_improve`  
**对应原文：** `Text2CAD_持久拓扑命名修复与改进实施指导.md`  
**文档优先级：** 本补充规范高于原指导文档。两者冲突时，以本文件为准。  
**复核目标：** 判断原方案是否真的能够建立可信的时间序列 lineage，并补齐仍可能产生“伪持久拓扑”的漏洞。

---

# 0. 最终复核结论

原指导文档的核心架构是正确的，尤其是以下四点：

1. 将持久身份与当前 B-Rep Locator 分离；
2. 让 OCCT History 接收真实 Persistent ID，而不是 `face_17` 等临时编号；
3. 通过 unchanged、modified、split、merge、generated、consumed 等事件建立时间序列 lineage；
4. 将 sidecar、跨进程 rebind 和 CAE 强解析纳入同一信任链。

这些改造能够解决当前涡轮盘主链路中的根本问题。

但是，原文还不能直接作为最终实现规范。若代码 Agent 只按原文逐字实现，仍有可能得到以下错误结果：

- 每次 authoring 生成新的 `document_id`，导致全部 PID 变化；
- Pattern 副本共享同一 TShape，仅靠面索引区分；
- 对称阵列中的子面按几何排序重新编号；
- `IsSame` 成功但 face orientation 已改变，CAE 法向错误；
- Wire/Shell 被误认为可直接由 `BRepTools_History` 跟踪；
- `ShapeBindingService` 把 OCCT `HashCode` 当作几何内容哈希；
- locator 验证抛异常后被 `except: pass` 放行；
- fallback matcher 只有一个候选就返回 `exact`；
- `primitive_semantic` 被质量策略判为高质量，使最终重新枚举的面通过 CAE gate；
- ObjectStore 已经写入结果，但 Registry 事务失败，产生半提交；
- 命中 OperationCache 时只恢复几何，不恢复 topology event；
- STEP/SolidWorks/NX 只达到80%或模糊名称匹配就被判为成功；
- 60槽改61槽时，没有定义实例身份究竟按序号、角度还是特征 UUID 保持。

因此，本次复核结论是：

> **原文解决了正确的问题，但还缺少“稳定设计身份、操作特定 History 适配器、实例复制语义、强绑定信任、缓存与跨后端一致性”五个闭环。完成本补充规范后，才可以认为方案真正覆盖涡轮盘时间序列 lineage。**

---

# 1. 必须保留的原方案

以下原方案不需要推翻，应继续执行。

## 1.1 Identity、Occurrence、Event 三层分离

继续采用：

```text
TopologyIdentity
    ↓ current_occurrence_id
TopologyOccurrence
    ↓ created/updated by
TopologyEvent
```

含义：

- Identity：设计实体是谁；
- Occurrence：某次 body revision 中对应哪个 TopoDS 子形状；
- Event：一次操作如何把输入实体演化为输出实体。

运行时 Locator、面积、质心、B-Rep 索引、OCP 对象地址不得进入 Identity。

## 1.2 一对一目标实体修改默认保留 PID

默认规则仍为：

```text
target entity A --modified--> target entity B
PID(B) = PID(A)
```

但本规则必须受 `IdentityTransferPolicy` 约束，不能对 tool、construction entity 或语义发生根本变化的实体机械套用。

## 1.3 Split、Merge、Repartition 形成显式 lineage

继续采用：

- one-to-many：split；
- many-to-one：merge；
- many-to-many：repartition；
- source 进入 superseded；
- result 创建新 identity；
- 双向 ancestor/descendant 完整记录。

## 1.4 Final body 必须达到完整覆盖

最终面覆盖仍要求100%，但验收公式应修订为：

```text
TopExp face indexed-map extent(final_body_revision)
==
active bound face occurrence count(owner_body_revision=final_revision)
==
distinct locator count(final_revision, entity_type=face)
```

不能使用 Registry 全局 active count，因为 Registry 还包含历史实体、工具实体、边和实体体。

---

# 2. 原文必须修正的十三个关键问题

# 2.1 设计身份来源没有闭环

## 当前代码问题

`assemble_raw_gcad_document()` 在调用方未传 `document_id` 时，会创建：

```python
document_id = f"gcad-{uuid.uuid4().hex[:12]}"
```

因此同一自然语言重新 authoring，会得到新的 document ID。当前 V2 PID 又把 document ID 放入哈希，全部实体必然换 ID。

## 强制修订

新增三个不同概念：

```text
design_id
revision_id
run_id
```

- `design_id`：同一个设计永久稳定；
- `revision_id`：一次受控设计修改；
- `run_id`：一次执行。

规则：

1. `design_id` 必须由项目清单、数据库或用户保存的设计记录提供；
2. authoring assembler 不得默认生成“可用于持久拓扑”的随机 design ID；
3. 若无稳定 design ID，只能运行 `ephemeral_topology` 模式；
4. `run_id` 和 `revision_id` 不得进入 PID；
5. `document_id` 可保留兼容，但不得继续同时承担 design/run 两种身份。

推荐：

```python
class DesignIdentity(BaseModel):
    design_id: str
    revision_id: str
    run_id: str
    identity_source: Literal[
        "persisted_project_manifest",
        "caller_supplied",
        "ephemeral_generated",
    ]
```

只有前两种来源可宣称 strong persistence。

---

# 2.2 稳定 Node ID 不能只写成要求，必须实现 reconciliation

原文提出“Node ID 必须稳定”，但没有规定如何实现。

新增：

```python
class FeatureIdentity:
    feature_uid: str
    display_node_id: str
    operation_kind: str
    component_uid: str
```

Persistent ID 使用 `feature_uid`，而不是可变的 display node ID。

实现 `FeatureIdentityReconciler`：

1. 同一 canonical IR 重跑：直接复用 feature_uid；
2. repair patch：patch 必须保留未删除节点的 feature_uid；
3. 参数修改：feature_uid 不变；
4. 插入前序特征：已有 feature_uid 不变；
5. LLM 全量重写：
   - 先按 component、operation、graph neighborhood、explicit feature key 对齐；
   - 唯一匹配才复用；
   - 多候选标记 ambiguous；
   - 不允许靠列表位置匹配；
6. 无法对齐时，创建新 feature_uid，并生成 feature-level lineage。

没有 FeatureIdentityReconciler，V3 PID 仍会因节点改名而整体 churn。

---

# 2.3 OCCT History 的权威追踪范围必须收窄

`BRepTools_History` 的直接支持对象应限制为：

```text
vertex
edge
face
solid
```

Wire 和 Shell 不应被当作同等级 kernel-history identity。

强制规则：

- Face/Edge/Vertex/Solid：允许 kernel-authoritative lineage；
- Wire：由 ordered edge-use aggregate 派生；
- Shell：由 oriented face-use aggregate 派生；
- Compound/Compsolid：由子实体集合与装配结构派生；
- derived aggregate 的身份必须记录组成成员和顺序规则；
- 不得调用 `Generated(wire)` 或 `Modified(shell)` 后把空列表解释为 unchanged。

新增：

```python
KernelTrackedEntityType = Literal["vertex", "edge", "face", "solid"]
DerivedAggregateType = Literal["wire", "shell", "compound", "compsolid"]
```

---

# 2.4 通用 History Normalizer 不足以覆盖所有操作

原文的二部图归一化是正确中间层，但在它之前必须增加“操作特定适配器”。

新增接口：

```python
class OperationHistoryAdapter(Protocol):
    def execute(...) -> KernelOperationResult: ...
    def extract_source_history(...) -> KernelHistoryGraph: ...
    def derive_operation_semantics(...) -> list[SemanticAnchor]: ...
```

至少实现：

```text
PrismHistoryAdapter
RevolveHistoryAdapter
TransformCopyHistoryAdapter
BooleanHistoryAdapter
FilletHistoryAdapter
ChamferHistoryAdapter
ThickSolidHistoryAdapter
LoftHistoryAdapter
SweepHistoryAdapter
```

## Prism

不能只依赖通用 `Generated()`：

- profile edge → lateral face：`Generated(edge)`；
- profile basis/start：`FirstShape()`/`FirstShape(subshape)`；
- end cap：`LastShape()`/`LastShape(subshape)`；
- Copy 参数必须记录；
- profile 为 wire/face 时应显式解释 cap 与 region 关系。

## Revolve

- profile edge → revolved face：`Generated(edge)`；
- partial revolve 起止面：`FirstShape`、`LastShape`；
- full 360° 不应虚构 start/end cap；
- 退化边必须读取 `Degenerated()` 并记录。

Generic normalizer 只能处理已经正确提取的 source-result graph，不能替代 builder-specific semantics。

---

# 2.5 `IsSame` 不能单独代表“完全 unchanged”

OCCT 语义：

- `IsPartner`：同 TShape，Location 和 Orientation 可不同；
- `IsSame`：同 TShape、同 Location，Orientation 可不同；
- `IsEqual`：TShape、Location、Orientation 全部相同。

修订分类：

```text
IsEqual             -> occurrence_unchanged
IsSame but !IsEqual -> identity_unchanged + reoriented occurrence
IsPartner only      -> same underlying topology, relocated occurrence
```

新增事件属性：

```python
orientation_before
orientation_after
location_before
location_after
occurrence_change: Literal[
    "none",
    "reoriented",
    "relocated",
    "reoriented_and_relocated",
]
```

对于 CAE face normal、接触主从面等高风险用途，orientation 必须验证，不能只用 IsSame。

---

# 2.6 Pattern 的复制语义必须明确

原文只写“使用 BRepBuilderAPI_Transform”，仍然不够。

对直接等距旋转，若：

```python
copyGeom=False
```

OCCT 可能只给原 Shape 设置新 Location，多个实例共享底层 TShape。

必须选择一种明确策略。

## 推荐策略：Instance Identity + Occurrence Location

```text
template topology identity
    ↓ generated instance
instance topology identity
    ↓ occurrence with unique location
```

每个实例由：

```text
pattern_feature_uid
instance_uid
template_source_pid
```

定义身份。

`instance_uid` 不得仅由结果几何排序生成。

可使用：

```text
instance_uid = stable UUID stored in canonical IR
```

IR 示例：

```json
{
  "pattern_feature_uid": "pattern_slots",
  "instance_identity_policy": "ordinal",
  "instances": [
    {"instance_uid": "slot_000", "ordinal": 0},
    {"instance_uid": "slot_001", "ordinal": 1}
  ]
}
```

## Transform copy 模式

- 需要完全独立拓扑副本：`copyGeom=True`，或先 `BRepBuilderAPI_Copy`；
- 允许共享几何但独立 occurrence：可用 location-only transform，但 PID 必须依赖 instance_uid，不能依赖 TShape；
- 事件必须记录：
  - copy mode；
  - transform matrix；
  - source PID；
  - instance UID；
  - result locator。

---

# 2.7 Pattern 身份政策必须可配置

原文假设 60→61 后 `slot_000...slot_059` 必须保持，但等角阵列中增加数量会使绝大多数实例角度变化。

必须定义：

```python
PatternIdentityPolicy = Literal[
    "ordinal",
    "angular_anchor",
    "explicit_instance_uid",
]
```

### ordinal

第 i 个实例身份保持，即使角度因 count 改变而移动。

### angular_anchor

身份跟随绝对角度；count 改变后只有角度仍匹配的实例保持。

### explicit_instance_uid

上层设计系统显式管理每个实例 UID，最可靠。

涡轮盘推荐：

```text
explicit_instance_uid
```

若当前 IR 只支持 count/start_angle，首期可使用 ordinal，但必须在 metadata 中声明该政策。

对完全对称且无显式实例 UID 的外部导入几何，不得仅按角度排序后宣称每个个体 identity exact；只能返回一个 symmetric equivalence set，或 ambiguous。

---

# 2.8 多工具 Boolean 应优先使用真正的 multi-tool API

原文建议“Compound 后一次 Cut”，这只能作为经过验证的兼容路径，不能作为首选规范。

优先顺序应为：

1. `BOPAlgo_BOP` 或支持 arguments/tools 的 Boolean builder；
2. `SetArguments(targets)`；
3. `SetTools(instance_tools)`；
4. `SetOperation(CUT)`；
5. `SetNonDestructive(True)`；
6. `SetToFillHistory(True)`；
7. `Perform()`；
8. 检查 `HasErrors()`、`HasWarnings()`、`HasHistory()`；
9. 对每个独立 tool instance 的 tracked face 查询 History。

只有在当前 OCP 绑定无法调用 multi-tool API 时，才尝试 Compound，并必须通过测试证明：

- 每个 child tool face 的 history 可单独查询；
- 没有因 Compound 包装丢失 instance provenance；
- 最终覆盖率100%。

另外必须记录：

```text
boolean algorithm
non_destructive flag
fuzzy tolerance
glue mode
simplify result flag
OCCT version
builder warnings/errors
```

若调用 `SimplifyResult()`，必须使用包含 simplifier history 的最终 History；否则关闭 simplify。

---

# 2.9 Kernel relation 与 Identity decision 必须分层

一条 OCCT `Modified` 边不等于“保留 PID”。

新增两个层次：

```python
class KernelHistoryEdge:
    source_pid: str
    result_occurrence_key: str
    kernel_relation: Literal[
        "same", "modified", "generated", "removed"
    ]

class IdentityDecision:
    source_pids: list[str]
    result_keys: list[str]
    identity_relation: Literal[
        "unchanged",
        "modified_same_identity",
        "generated_new_identity",
        "generated_from_tool",
        "split",
        "merge",
        "repartition",
        "consumed",
        "deleted",
    ]
    policy_id: str
```

`IdentityTransferPolicy` 至少考虑：

- source role：target/tool/profile/construction；
- source component 与 result component；
- entity dimension/type；
- operation kind；
- semantic role continuity；
- source/result cardinality；
- whether orientation-only/location-only；
- consumer safety class。

例如：

```text
tool face --kernel modified--> final slot wall
```

domain decision 仍应是：

```text
generated_from_tool
```

并创建新的 final disk PID。

同一个结果可能同时受到 target 和 tool 的 provenance 影响，因此 occurrence 应允许：

```python
provenance_edges: list[KernelHistoryEdge]
primary_identity_source: str | None
```

不能假设每个结果只有一个祖先。

---

# 2.10 当前 ShapeBindingService 不能直接作为 strong binding

当前实现存在四个必须修正的问题。

## A. “内容哈希”并不是真正内容哈希

当前 `_compute_shape_content_hash()` 使用 Shape `HashCode`，异常时返回 `"unknown"`。它不能作为跨进程、跨重建的稳定几何内容证明。

修订：

- runtime stale detection 优先使用 `body_revision_id`；
- 若需要 artifact hash，使用规范化 BREP/STEP bytes 的 SHA-256，或明确版本化的 topology+geometry digest；
- 禁止把 Python `id()`、OCCT HashCode 或 `"unknown"` 当作强证明；
- hash 方法和 OCCT 版本必须写入 metadata。

## B. Locator 目前只真正构建 face/edge map

模型声明 solid/shell/wire/vertex，但 `ShapeBindingService` 实际只映射 face 和 edge。

首期 strong scope 应明确为：

```text
face + edge
```

随后分别实现 vertex/solid。Wire/Shell 按 aggregate 处理。

## C. Fingerprint verification 仍是 stub

`verify_locator(..., expected_fingerprint)` 当前没有真正比较 fingerprint。

在完成前：

```text
expected_fingerprint provided but not verified
```

必须返回不可信，而不是 valid=True。

## D. 解析异常不能放行

当前 `registry.resolve()` 对 content hash 和 locator verification 的异常使用 `except Exception: pass`。

修订为：

```text
verification exception -> unresolved
```

并带错误码：

```text
topology_binding_verification_failed
```

生产、CAE、跨后端导出不得降级放行。

---

# 2.11 信任等级不能只靠 `resolution_method` 字符串排序

当前质量表把：

```text
primitive_semantic
```

排在 deterministic semantic 之上，而当前最终重新枚举的 Boolean 面又可能被登记成 primitive semantic。这会使错误面通过 CAE load/constraint 的最低质量门。

改为证书式信任：

```python
class TopologyTrustCertificate:
    identity_provider: str
    history_provider: str
    binding_verified: bool
    coverage_verified: bool
    orientation_verified: bool
    event_chain_verified: bool
    provider_capability_verified: bool
    ambiguity_count: int
    unresolved_count: int
    trust_level: Literal[
        "strong_kernel_history",
        "operation_semantic_exact",
        "fingerprint_unique",
        "set_only",
        "ambiguous",
        "unresolved",
    ]
```

规则：

1. `resolution_method` 只能是证据字段，不直接决定 trust；
2. `strong_kernel_history` 要求真实 Kernel History、强绑定和100%覆盖；
3. primitive birth face 可以是 `operation_semantic_exact`；
4. primitive semantic 不得自动证明后续 Boolean 结果；
5. 整个 lineage 的 trust 取最弱边；
6. CAE gate 必须使用 `resolve_bound()` 并验证 trust certificate；
7. contact 默认只接受 strong kernel history；
8. load/constraint 是否允许 operation semantic exact，由用户安全政策显式配置。

---

# 2.12 Matcher 当前仍是占位实现，禁止返回 strong exact

当前 matcher：

- 几何成本全部为0；
- 单候选直接返回 exact；
- 多候选通常 ambiguous。

强制修订：

```text
matcher_algorithm_state = placeholder
```

时不得产生：

```text
exact
fingerprint_unique
```

单候选也不够，因为候选过滤本身可能错误。

真正 matcher 至少需要：

- 实际 fingerprint 计算；
- provenance constraints；
- component/type/feature/lineage constraints；
- adjacency；
- geometry；
- location；
- assignment-level one-to-one约束；
- best/second margin；
- absolute maximum cost；
- symmetric equivalence detection。

推荐返回：

```text
matched_unique
ambiguous_equivalence_class
unresolved
```

只有通过全局或分桶的双射校验，才可生成 fingerprint_unique。

---

# 2.13 ObjectStore、Node Binding、Cache 必须纳入拓扑事务

当前 `TopologyTransaction` 只克隆和提交 Registry。Handler 先把几何写进 ObjectStore，再应用 topology delta。一旦 topology 失败，就会留下永久几何 handle。

同时，OperationCache 的 topology fragment 目前是 `None`。命中缓存时可能只恢复几何，不重放 topology。

新增：

```python
class BuildCommitBundle:
    staged_objects
    staged_node_bindings
    staged_component_bindings
    staged_registry
    staged_occurrences
    staged_events
    staged_cache_entry
```

提交流程：

```text
execute geometry outside permanent store
→ build output body revision
→ extract and validate history
→ validate coverage
→ stage object
→ stage occurrences
→ stage registry/event
→ validate full bundle
→ atomic publish
```

ObjectStore 至少增加：

```text
begin_stage
put_staged
commit_stage
rollback_stage
```

或者使用不可变对象仓库 + 原子发布 handle map。

## Cache

Cache entry 必须包含：

```python
geometry_result
output_body_revision
topology_identity_fragment
topology_occurrence_fragment
topology_event_fragment
trust_certificate
algorithm/version/tolerance key
```

Cache hit 必须：

- 验证输入 body revision；
-恢复 topology fragment；
-生成 `cache_replay` event；
-重新绑定 occurrence；
-验证 final coverage。

不能只返回 shape。

---

# 3. 对 Sidecar V3 的进一步修订

原文提出 Sidecar V3 是正确的，但必须补充以下规则。

## 3.1 Canonical serialization

哈希不能仅依赖：

```python
json.dumps(..., sort_keys=True)
```

因为 list 顺序、float 表示和不同实现可能变化。

采用明确规范：

- RFC 8785 JCS，或项目自定义 canonical JSON；
- entities 按 PID 排序；
- occurrences 按 `(run_id, sequence_no, persistent_id)` 排序；
- relations 按 canonical tuple 排序；
- lineage edges 去重并排序；
- float 使用明确量化；
-禁止 NaN/Infinity；
-每个 schema version 固定 canonicalizer version。

## 3.2 更新所有消费者

当前写入器输出 v2，但以下模块仍存在 v1 假设：

- topology validation；
- CAD adapter；
-部分测试。

升级 sidecar 时必须同步更新：

```text
persistence.py
validation.py
cad_adapters.py
metadata proof
SolidWorks adapter
NX adapter
tests
```

不能只修改 writer。

## 3.3 旧版本迁移

v1/v2 记录通常缺少 birth descriptor，无法无损推导 V3 PID。

迁移策略：

```text
read legacy
→ trust_level=legacy_unverified
→ rebuild with V3
→ create legacy_pid_to_v3_pid migration map
→ do not claim same identity without evidence
```

---

# 4. 跨后端部分必须同步收紧

原指导文档主要聚焦 G-CAD 内部，但最终若交给 SolidWorks、NX、STEP/CAE，弱映射仍会破坏身份。

当前适配器中的危险行为包括：

- SolidWorks 按名称部分词匹配；
- 80% match rate 即可 `ok=True`；
- STEP 实际尚未嵌入 face identity；
-无 sidecar 仍可能 warning-only；
-NX 命令依赖 semantic role 找 face。

强制修订：

## STEP

首期：

- STEP 与 sidecar 作为不可分割 artifact bundle；
-记录 STEP SHA-256；
-导入后做全量 geometry/topology reconciliation；
-高风险消费者缺 sidecar直接失败。

后续：

- 使用 AP242/XCAF；
-对子形状写入稳定属性或名称；
-导入后验证属性与 sidecar。

## SolidWorks/NX

- 禁止 fuzzy name 匹配作为 strong proof；
-必须写入并读取实体属性；
-属性写入前必须通过 strong binding；
-必需 Named Set 匹配率必须100%；
-全模型允许统计 match rate，但不能替代关键集合完整性；
-任何 low-confidence face 不得用于 CAE load/contact。

---

# 5. 修订后的涡轮盘主流程

# 5.1 回转盘体

输入：

```text
stable profile segment UID
```

输出：

```text
profile segment UID
→ kernel Generated
→ disk face identity
```

对于 cap/start/end，使用 Revolve adapter 的 FirstShape/LastShape 语义。

# 5.2 Cutter extrusion

```text
stable cutter profile edge UID
→ Prism Generated(edge)
→ template cutter side face PID
```

cap 用 FirstShape/LastShape，不按最终面类型编号。

# 5.3 Pattern

每个实例：

```text
pattern feature UID
+ explicit instance UID
+ template PID
→ construction instance PID
```

记录 transform、copy mode、orientation 和 location。

# 5.4 Multi-tool cut

一次提交60个独立 tool instances。

对 target 与每个 tool tracked face 查询 History，构建 kernel graph。

# 5.5 Identity decision

示例：

```text
disk hub face -> IsEqual -> unchanged, same PID
disk rim face -> 1:N Modified -> split, child PIDs
tool slot_017 pressure face -> result face -> generated_from_tool
tool instances -> consumed
```

# 5.6 Final gate

```text
all final faces have one occurrence
all occurrences have one active PID
no duplicate locator
all input tracked faces classified
all result faces covered
no ambiguity
no unresolved
orientation checked
event chain valid
trust = strong_kernel_history
```

---

# 6. 修订后的测试矩阵

原文测试继续保留，并增加以下强制测试。

## 6.1 Identity source

- 未提供 stable design_id 时，不得输出 strong persistence；
-相同 persisted design_id 重建，PID稳定；
-随机 run_id 变化不影响 PID；
-feature display name 改变不影响 feature_uid。

## 6.2 OCCT equality semantics

- IsEqual；
- IsSame但orientation反转；
- IsPartner但location不同；
-不同TShape但几何相同。

分别验证 identity 与 occurrence 状态。

## 6.3 Transform copy

- `copyGeom=False` location-only；
- `copyGeom=True` deep copy；
-同 TShape、不同 location 的多个 pattern instances；
-每个 instance PID/occurrence 唯一。

## 6.4 Symmetry

- 60个完全相同槽；
-候选排序被随机打乱；
-不得依赖 kernel list order；
-无 instance UID 时返回 equivalence set/ambiguous；
-有 instance UID 时全部稳定。

## 6.5 Operation-specific history

- Prism FirstShape/LastShape；
-360° Revolve 无 cap；
-partial Revolve 有起止面；
-degenerated edges；
-Fillet/Chamfer modified adjacent faces；
-Shell offset/removed faces；
-Boolean target/tool 多源 provenance。

## 6.6 Binding

- owner body revision变化；
-locator index变化；
-orientation变化；
-content hash verifier异常；
-fingerprint verifier未实现；
-所有异常都应 fail closed。

## 6.7 Transaction

故障注入点：

- geometry后、history前；
-history后、registry前；
-registry后、event前；
-cache写入前；
-node binding前。

所有情况下永久 ObjectStore、Registry、EventStore、node output 必须保持原状态。

## 6.8 Cache

- cache miss 正常创建 event；
-cache hit 恢复 identity/occurrence/event；
-输入 revision 变化导致失效；
-tolerance/OCCT/algorithm version变化导致失效；
-不得出现只有 geometry 没有 topology。

## 6.9 Boolean strategy

- multi-tool BOP；
-compound fallback；
-fuzzy tolerance；
-SimplifyResult 开/关；
-non-destructive 开/关；
-每种策略都验证 coverage 和 history。

## 6.10 Pattern edit policy

分别测试：

- ordinal 60→61；
-angular_anchor 60→61；
-explicit_instance_uid 60→61。

不得对三种政策使用同一预期。

## 6.11 Sidecar

- canonical ordering随机打乱，hash不变；
-篡改 relation/event，hash失败；
-v2读取后 legacy_unverified；
-v3 restore后 unbound；
-rebuild+rebind后 strong；
-不同 OCCT 版本不要求无条件 PID set完全一致，应产生 compatibility report。

## 6.12 Cross-backend

- fuzzy name match不得 strong pass；
-required Named Set 必须100%；
-缺少属性失败；
-属性存在但绑定到错误面失败；
-sidecar与STEP hash不一致失败。

---

# 7. 修订后的验收口径

## 7.1 可以证明的范围

完成本规范后，可以可信证明：

1. 在固定 design identity、canonical feature identity、OCCT版本、算法策略和容差下，同一构建链路的实体时间序列 lineage；
2. 相同 IR 独立进程重建的 PID 和 lineage 稳定；
3. 受控参数编辑下，不受影响实体保持、修改实体继承、分裂合并显式演化；
4. 涡轮盘阵列实例到最终槽面的 provenance；
5. CAE Named Set 强绑定到当前 final body face。

## 7.2 不能承诺的绝对范围

不得宣称：

- 任意自然语言重新生成都能自动保持全部 feature UID；
-任意 OCCT版本切换都保证相同 B-Rep 分区；
-完全对称且无设计锚点的实体可被唯一识别；
-任意大参数变化后所有 split child PID都保持；
-仅靠 fingerprint 能解决通用 persistent naming problem。

正确行为是：

```text
无法证明唯一性
→ ambiguous/unresolved
→ fail closed
```

而不是强行生成“稳定”名称。

---

# 8. 修订后的实施优先级

## PR-0：失败测试

先加入：

- random document_id churn；
- empty-source modified；
- unchanged未处理；
- matcher placeholder single candidate exact；
- CAE weak resolve；
- shape hash unknown仍放行；
- pattern shared TShape；
- transaction半提交；
-cache只恢复geometry；
-sidecar v1/v2消费者不一致。

这些测试必须先失败。

## PR-1：稳定设计与特征身份

- DesignIdentity；
- FeatureIdentity；
- FeatureIdentityReconciler；
- V3 PID；
- legacy migration map。

## PR-2：Identity/Occurrence/Event 与 Registry

- relation validators；
-kernel edge与identity decision分层；
-unchanged/reoriented/relocated；
-occurrence store；
-event store；
-strong resolve；
-trust certificate。

## PR-3：Binding 与事务

-真实 body revision；
-strong locator verification；
-移除异常放行；
-atomic BuildCommitBundle；
-topology-aware cache。

## PR-4：Prism/Revolve

- stable profile element UID；
-operation-specific adapters；
-FirstShape/LastShape；
-degenerated handling。

## PR-5：Pattern

- explicit instance UID；
-transform copy policy；
-shared TShape tests；
-symmetric equivalence policy。

## PR-6：Multi-tool Boolean

- BOPAlgo/BRepAlgoAPI multi-tool；
-target/tool provenance；
-split/merge/repartition；
-builder report；
-coverage gate。

## PR-7：Sidecar V3 与跨进程 Rebind

- canonical serialization；
-event hash chain；
-restore unbound；
-rebuild reconcile；
-version compatibility report。

## PR-8：CAE 与跨后端

- CAE strong resolve；
-STEP artifact bundle；
-SW/NX attribute mapping；
-required sets 100% gate。

## PR-9：涡轮盘验收

运行：

- identical rebuild；
-thickness edit；
-profile edit；
-count policy edits；
-feature insertion；
-cache replay；
-new process rebind；
-cross-backend proof。

---

# 9. 给代码 Agent 的最终强制指令

代码 Agent 不得：

1. 仅修改 semantic role 字符串；
2. 将最终面排序后编号；
3. 将 OCCT HashCode 当作内容哈希；
4. 将单候选 matcher 判为 exact；
5. 在验证异常时 `except: pass`；
6. 将 `primitive_semantic` 自动视为 strong；
7. 使用弱 `registry.resolve()` 通过 CAE；
8. 只事务化 Registry；
9. 命中 cache 时只恢复几何；
10. 对 wire/shell 直接声称 kernel history exact；
11. 使用 transform 默认参数而不记录 copy semantics；
12. 对称阵列无实例 UID仍强行唯一命名；
13. 将 Compound Cut 未经证明地视为完整 per-instance history；
14. 以80%跨后端匹配率作为关键工程面成功；
15. 在 design_id 不稳定时宣称跨重建持久性。

代码 Agent 必须输出：

```text
implementation_diff.md
topology_contract_coverage.json
history_provider_matrix.json
identity_policy_matrix.json
binding_verification_report.json
cache_topology_replay_report.json
turbine_timeline_report.json
turbine_rebuild_diff.json
turbine_rebind_report.json
```

---

# 10. 最终判断

加入本补充规范后，原指导文档的方案才形成完整闭环：

```text
稳定设计/特征身份
→ 稳定 primitive birth identity
→ 真实 operation-specific OCCT history
→ kernel relation graph
→ identity transfer policy
→ occurrence与orientation/location绑定
→ 原子 Registry/ObjectStore/Event/Cache提交
→ Sidecar V3
→ 跨进程强rebind
→ CAE与跨后端严格gate
```

这套方案能够真正修复当前涡轮盘测试中的“每阶段重新命名”问题，并建立可信时间序列 lineage。

但其可信性来自：

```text
能够证明就保持或派生身份
不能证明就 ambiguous/unresolved 并阻断
```

而不是承诺任何情况下都能为每个面强行找到唯一旧身份。
