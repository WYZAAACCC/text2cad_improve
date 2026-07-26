# Text-to-CAD OCAF 原生持久化拓扑命名系统
# 专家复核与最终正确化实施指导书 v6.0

> 编制日期：2026-07-26  
> 适用仓库：`WYZAAACCC/text2cad_improve`，当前 `main` 分支  
> 参考进度文档：`docs/OCAF_系统完整审查文档_专家评估版_v1.md`  
> 执行对象：代码 Agent  
> 文档性质：下一阶段唯一实施基线、根因复核报告、分阶段验收规范  
> 最终目标：实现真正基于 OCCT OCAF/TNaming 的原生、跨进程、跨 Revision、FACE/EDGE 精确可解析、可安全供 CAE 使用的持久化拓扑命名系统

---

# 0. 执行摘要

当前系统已经完成了大量有效工作，尤其包括：

- BinXCAF/XBF 原生持久化；
- UTF-8 路径与固定 Tag 100；
- `Retrieve()` 安全读取；
- `TDF_AttributeIterator + attr.Get()` 安全属性访问；
- StableLabelIndex v2 的主要结构；
- Live/Audit History 分离；
- 真实 `TopoDS_Shape` 的内存态捕获；
- `Generated/Modify/Delete` Writer API；
- Selection Policy、Semantic Contract；
- Solve/Verify 子进程骨架；
- CAE preflight 骨架；
- 多种 tracked operation 的初步支持。

但专家评估文档中有一个会直接影响后续路线的核心误判：

> **现有实验尚未证明“OCCT/OCP 7.8.1.1 无法实现 FACE 级 UNIQUE Solve”，也没有证明必须升级到 7.9+ 才能完成原生拓扑命名。**

目前 Face 级测试失败的更直接原因是：

1. Rev1、Rev2、Rev3 的 Box 是相互独立重建的几何；
2. 测试人为调用 `Modify(old_body, new_body)`，并没有来自同一个 OCCT 建模算法的精确 history；
3. 测试中的 `LiveEvolutionRelation` 声明 `entity_kind=FACE`，但实际 `old_shape/new_shapes` 是整个 SOLID；
4. CurrentResult 只登记了整个 body；
5. 面级 relation history 被放在 CurrentResult Label 的兄弟树，而 OCCT Selector 源码明确会检查 Context Result Label 下登记的子拓扑 NamedShape；
6. attempted “6× face Modify” 如果依赖 `Faces()` 数组位置匹配，就是伪造 history，Access Violation 不能据此证明 TNaming 本身不支持面级演化；
7. 现有 T2 接受 `AMBIGUOUS`，因此没有达到拓扑命名系统的核心验收目标。

OCCT 官方文档明确要求三部分同步：

```text
建模算法的真实 History
+ 将结果及必要子拓扑历史登记到 OCAF
+ Selection / Solve
```

仅登记整体 body 的 Modify，Selector 没有足够信息从六个新面中识别原来的某一个面。当前得到 Compound(6 faces) 是信息不足的自然结果，不是“FACE 级 TNaming 永久不可用”的证明。

因此，下一阶段的正确路线不是直接升级 OCP，而是：

```text
修正 TNaming Label 组织与 T2 基准
→ 建立语义明确、history 真实的 FACE/EDGE fixture
→ 运行 C++/Python × OCCT 7.8/7.9 版本矩阵
→ 再决定是否升级
→ 完成稳定 Relation、Revision、Artifact Bundle
→ 接入 Solve Worker 与 CAE Gate
→ 完成真实 G-CAD E2E
```

---

# 1. 审查结论与当前成熟度

## 1.1 当前状态定性

建议将当前状态从：

```text
Engineering Beta
```

调整为：

```text
OCAF Native Topology Naming — Engineering Alpha+
```

理由不是基础工作不足，而是最核心的产品承诺仍未被证明：

```text
跨 Revision 的某一个具体 FACE/EDGE
能够通过 OCAF 原生 history
在独立进程中唯一恢复
且可作为 CAE required binding
```

## 1.2 分层成熟度

| 能力层 | 当前判断 | 成熟度 |
|---|---|---:|
| OCAF/XBF 基础持久化 | 已验证 | 95% |
| UTF-8 / Tag 100 / Retrieve | 基本完成 | 95% |
| 安全 Attribute 读取 | 基本完成 | 90% |
| StableLabelIndex：component/feature/selection | 已有有效实现 | 80% |
| StableLabelIndex：relation/revision/CAE | 仍有 placeholder 与路径错误 | 35% |
| Live History 模型 | 主体正确 | 80% |
| TNaming Writer API 映射 | 调用类型正确，树结构与身份仍错误 | 60% |
| 单 Revision Selection | 可创建、可持久化 | 70% |
| 跨 Revision body Modify | 可运行但证明力有限 | 50% |
| 跨 Revision FACE/EDGE UNIQUE | 尚未证明 | 15% |
| Tracked operation history | 部分算法正确，Pattern 等仍有错误 | 55% |
| Pipeline topology 接线 | 有正式入口，但事务并非完整原子 | 50% |
| Solve Worker / Verify Worker | 有骨架，正式路径未完全采用 | 55% |
| CAE Gate | 有模块，证据与绑定模型不完整 | 35% |
| Immutable Revision Artifact | 基本未完成 | 20% |
| 系统整体 | 模块较丰富，主链未闭环 | 约 48% |

---

# 2. 对专家评估文档的复核

## 2.1 可以确认的成果

以下成果应保留，不需要推翻：

1. `attr.Get()` 实例方法可用于当前 OCP；
2. `read_ascii_string/read_integer` 使用真实 Attribute Iterator 的方向正确；
3. StableObjectKey 已从单字符串升级为复合身份；
4. StableLabelIndex 可以保存和恢复 component/feature/selection 的基础记录；
5. `LiveEvolutionRelation.validate()` 已改用异常；
6. Pipeline 已将 OCAF 写入移到 STEP 和 geometry postcheck 后；
7. Verify Worker 与 Solve Worker 已建立；
8. Policy/Contract 已能跨进程读取；
9. Writer 已具备 initial `Generated()` 与 later `Modify()` 分支；
10. CAE entity kind 检查已不再完全空置；
11. Pattern 已尝试使用带 History 的 Boolean Fuse；
12. 198 项测试说明局部模块具备一定稳定性。

## 2.2 必须修改的结论

### 结论 A：“Face 级 UNIQUE 被 OCP 7.8.1.1 永久阻塞”

当前证据不足，不能成立。

应改为：

> 当前 T2 的 history 粒度、Label 组织和旧/新面对应关系不足，尚不能判断 Face UNIQUE 失败来自 OCCT 算法、OCP 绑定还是应用层建模历史不完整。

### 结论 B：“升级到 OCCT 7.9+ 将解决 Face UNIQUE”

当前没有证据支持。

OCCT 7.9.3 的 `TNaming_Selector` 核心逻辑仍然要求：

- Context NamedShape；
- Result Label 下的子拓扑 NamedShape；
- 正确 Naming Structure；
- 更新后调用 Solve。

7.9 并不会自动从一个整体 SOLID Modify 猜出六个面中的目标面。

升级只能通过版本矩阵验证，不能作为应用层 history 缺失的替代方案。

### 结论 C：“True T2 已完成”

不成立。

当前测试虽然调用了 `Modify`，但存在：

- `entity_kind=FACE` 与实际 SOLID 不一致；
- 独立重建 Box 之间没有 kernel history；
- 接受 `AMBIGUOUS`；
- 没有断言精确 FACE；
- 没有验证 Relation Label 稳定；
- 没有通过正式 Pipeline/Revision Bundle。

建议将该测试重命名为：

```text
test_body_level_modify_persistence_smoke.py
```

不得再称为 True T2。

### 结论 D：“所有正式 XBF 操作已子进程隔离”

与源码不完全一致。

当前 Pipeline CAE preflight 直接实例化 `PersistentSelectionService` 并在主进程调用 `solve()`。Solve Worker 虽存在，但没有成为正式 Pipeline 的唯一 Solve 入口。

### 结论 E：“Pattern Fuse History 完整”

当前实现有方向性错误：

```python
fused = fuser.Shape()
for face in Faces(fused):
    fhist.Modified(face)
```

History 查询必须以算法输入 shape/subshape 为 key，而不是最终输出 face。当前循环是在用 result face 查询 input→output history，通常不会得到正确映射。

### 结论 F：“Relation Identity 基础设施已就绪”

仅部分成立。

`allocate_relation()` 当前使用 dummy component Tag：

```text
DesignRoot / Components / 1000 / Features / relation_tag
```

它并不知道真实 component/feature TagPath，可能造成不同 feature 的 relation path 冲突。

Writer 默认仍回退：

```text
1001 + relation list index
```

因此 Relation 身份尚未稳定。

---

# 3. 最关键的根因：TNaming 数据结构组织不符合 Selector 预期

## 3.1 当前 Label Schema

当前 Feature 结构：

```text
Feature
├── 1 Metadata
├── 2 CurrentResult          ← body NamedShape
├── 3 EvolutionRelations     ← face/edge history
├── 4 ConstructionRoles
└── 5 RevisionAudit
```

`CurrentResult` 与 `EvolutionRelations` 是兄弟。

## 3.2 OCCT Selector 的关键行为

OCCT `TNaming_Selector` 源码在处理 Context 时，会：

1. 找到 Context 对应的 `TNaming_NamedShape`；
2. 从该 NamedShape 所在 Label 向下检查子 NamedShape；
3. 利用这些已登记的子拓扑历史构造和再生 naming rule。

源代码注释直接写明：

```text
sub-shapes registered in DF and put under result label
```

因此更合理的 Feature Native Naming 树应为：

```text
Feature
├── 1 Metadata
├── 2 ResultRoot                 ← Context / CurrentResult NamedShape
│   ├── 1000 role:top
│   ├── 1001 role:bottom
│   ├── 1002 role:x_min
│   ├── 1003 role:x_max
│   ├── 1004 operation relation A
│   ├── 1005 operation relation B
│   └── ...
├── 3 BusinessRelationMetadata   ← 不放 TNaming_NamedShape
├── 4 ConstructionRoleMetadata
└── 5 Audit
```

或者：

```text
Feature / ResultRoot / NativeHistory / <stable relation labels>
```

但要先用最小 C++ fixture 验证多一层容器是否会被 Selector 递归使用。OCCT 7.8 的部分代码只检查 Result Label 的直接子标签，因此首个正确性实现应优先将 NamedShape relation 放在 ResultRoot 的直接子标签。

## 3.3 Native Label 与 Metadata 必须分离

一个 Native Relation 应使用两个 Label：

```text
ResultRoot / <relation_tag>          ← 只放 TNaming_NamedShape
BusinessRelations / <relation_tag>  ← relation_id、source_ref、audit JSON
```

不要在同一个 Label 上同时承载：

- TNaming evolution；
- JSON metadata；
-业务 Name；
- Selection policy。

这样可以减少 `TNaming_Builder` 重建 Attribute 时对业务数据的干扰。

## 3.4 一个 1→N Relation 应使用一个 Builder

OCCT 官方说明：

> 同一 Builder 可以写入多个具有相同 Evolution 的 old/new pair，最终形成一个 NamedShape。

当前 Writer 为每个 `new_shape` 创建不同子 Label：

```text
relation / child1
relation / child2
relation / child3
```

建议改为：

```python
label = native_relation_label
builder = TNaming_Builder(label)
for new_shape in rel.new_shapes:
    builder.Generated(rel.old_shape, new_shape)
```

或：

```python
builder.Modify(old_shape, new_shape)
```

这样一个逻辑 relation 本身就是 SET，不依赖 kernel 返回顺序。

只有当业务语义明确区分各分支时，才为分支建立额外 Selection，而不是把 `sub_idx` 变成持久身份。

---

# 4. 正确的 FACE UNIQUE 基准实验

这是下一阶段第一优先级。在它完成前，不得升级库、不得继续宣称库限制。

## 4.1 为什么不能继续使用普通 CadQuery Box + Faces() index

`cq.Workplane(...).box()` 每次独立构造一个新 BRep。

旧 Box 与新 Box 之间没有一个共同的 OCCT 算法对象提供：

```text
Modified(old_face)
Generated(old_face)
IsRemoved(old_face)
```

按 `Faces()[i]` 将旧面与新面配对属于应用层猜测，不是 exact kernel history。

## 4.2 建议 Fixture：BRepPrimAPI_MakeBox 语义面

`BRepPrimAPI_MakeBox` 提供稳定的语义 API：

```text
TopFace
BottomFace
LeftFace
RightFace
FrontFace
BackFace
```

首个验证 Fixture 可利用这些构造角色建立明确 old→new 对应，而不是枚举索引。

### Rev1

```text
ResultRoot:
  Generated(box1)

ResultRoot/top_role:
  Generated(top1)

ResultRoot/bottom_role:
  Generated(bottom1)

... 其他角色

Selection:
  Select(top1, box1)
```

### Rev2

```text
ResultRoot:
  Modify(box1, box2)

相同 top_role Label:
  Modify(top1, top2)

相同 bottom_role Label:
  Modify(bottom1, bottom2)

... 其他角色

Selector.Solve(valid_labels)
```

### Rev3

重复 Rev2。

## 4.3 强制断言

必须全部成立：

```text
Solve == True
status == UNIQUE
resolved_count == 1
ShapeType == FACE
area == expected_top_area
centroid.z == expected_height
normal == expected_top_normal
selection TagPath unchanged
top_role TagPath unchanged
ResultRoot TagPath unchanged
无 heuristic fallback
```

不得接受 `AMBIGUOUS`。

## 4.4 该 Fixture 的证明边界

这个 Fixture 证明的是：

> 当应用程序提供正确、稳定、语义明确的 face-level evolution 时，TNaming 能否跨 Revision 唯一恢复。

它不证明任意几何操作都自动具备 history。后续 Boolean、Fillet、Pattern 必须使用各自算法真实 history。

---

# 5. C++/Python × 版本矩阵

完成正确 Fixture 后，再隔离 OCCT 与 OCP。

## 5.1 四象限

| Writer / Solver | Reader / Verification | 目的 |
|---|---|---|
| C++ 7.8.1 | C++ 7.8.1 | OCCT 基线 |
| Python OCP 7.8.1.1 | C++ 7.8.1 | Python 写入正确性 |
| C++ 7.8.1 | Python OCP 7.8.1.1 | Python 读取/Solve 绑定 |
| Python 7.8.1.1 | Python 7.8.1.1 | 产品路径 |

然后对：

```text
OCP 7.8.1.2
OCP 7.9.3.1.1
```

运行同一 fixture。

## 5.2 判定规则

### C++ 7.8 成功、Python 7.8 失败

结论：

```text
OCP 绑定或 Python 生命周期问题
```

处理：

- 私有 OCP safe wrapper；
- 小型 C++ sidecar；
- 不必重构 OCAF 数据模型。

### C++ 7.8 失败、C++ 7.9 成功

结论：

```text
OCCT 版本缺陷
```

此时升级有充分依据。

### 7.8、7.9 都失败

结论：

```text
Fixture 或 Label/history 组织仍错误
```

不得继续声称版本阻塞。

### 7.8、7.9 都成功

结论：

```text
当前主系统集成问题
```

## 5.3 禁止事项

- 不得只在 Python 7.9 上偶然成功就认定根因解决；
- 不得使用不同的几何 Fixture 比较版本；
- 不得改变 Label Schema 后还称为单变量版本实验；
- 不得以 `HashCode()` 是否可用判断 TNaming 是否可用。

---

# 6. StableLabelIndex v3

## 6.1 当前确定问题

### relation/revision/cae_binding placeholder

通用 `allocate()` 对以下类型返回：

```python
TagPath((DYNAMIC_TAG_START,))
```

这是不可投入生产的 placeholder。

### `allocate_relation()` 使用 dummy component

当前 relation path 并不包含真实 Feature TagPath。

### Feature Namespace 使用 component Tag

```text
component:1000
```

虽能工作，但不利于：

- Schema migration；
- Lineage 合并；
- Debug；
- 多文档复制。

建议使用：

```text
component:<semantic_component_id>
```

并把 component TagPath 作为值，不作为 namespace 语义。

### Session open 后 revision_number 重置为 1

必须从 lineage metadata 恢复。

### Index 保存的 entry label 使用顺序位置

保存 Index JSON entry 的 OCAF child Tag 仍取决于 `_by_key` 插入顺序。虽然 JSON 中包含稳定 key，但：

- 顺序变化会重写不同 child；
- 旧条目可能残留；
- diff 不稳定。

建议给 Index Entry 本身建立独立不可变 entry ID，或在保存前清理并完全重写 Entries subtree。

## 6.2 新接口

```python
allocate_component(lineage_id, component_id)
allocate_feature(component_key, feature_id)
allocate_selection(lineage_id, selection_id)
allocate_relation(feature_key, relation_key)
allocate_revision(lineage_id, revision_id)
allocate_cae_binding(lineage_id, binding_id)
```

所有方法必须接收真实父 `TagPath`，不得在内部猜 dummy path。

## 6.3 RelationKey

```python
@dataclass(frozen=True)
class SourceEntityRef:
    component_id: str
    feature_id: str
    role_id: str | None
    selection_id: str | None
    entity_kind: TopologyEntityKind

@dataclass(frozen=True)
class RelationKey:
    feature_id: str
    source: SourceEntityRef
    evolution_kind: EvolutionKind
    relation_role: str
```

禁止使用：

```text
face_3
edge_7
relation list index
instance_2_face_5
```

作为跨 Revision ID。

## 6.4 Gate

必须增加：

1. relation 在不同枚举顺序下 TagPath 不变；
2. 两个 Feature 中相同 relation_id 不冲突；
3. revision Tag 不重用；
4. CAE Binding Tag 可跨进程恢复；
5. open 后 revision_number 与 HEAD 一致；
6. placeholder path 在生产代码中为 0 处。

---

# 7. Revision 与 Artifact Bundle

## 7.1 当前问题

当前 Pipeline 仍以：

```text
一个 evolving design.xbf
+ 单独 out_step
+ 单独 metadata
```

工作。

即使 OCAF gate 失败，STEP 可能已经写到正式路径。

当前 `publish()` 使用：

```python
shutil.copy2(temp, official)
```

并在 OCAF Session 关闭前调用，正是 Windows 文件锁问题的重要来源。

## 7.2 正确模型

```text
lineage/
├── HEAD.json
└── revisions/
    ├── rev-000001/
    │   ├── design.xbf
    │   ├── model.step
    │   ├── metadata.json
    │   ├── topology_manifest.json
    │   ├── selection_resolution.json
    │   └── cae_preflight.json
    └── rev-000002/
```

## 7.3 正确发布顺序

```text
1. 在 staging 目录构建 STEP
2. Geometry/STEP postcheck
3. 打开上一 XBF 或创建新文档
4. begin transaction
5. 写 result/history/index/revision
6. commit transaction
7. 保存 staging XBF
8. 关闭 OCAF Session
9. Solve Worker 打开 staging XBF，Solve 并保存 solved XBF
10. Verify Worker 验证 solved XBF
11. CAE preflight 使用 Worker 输出
12. 写全部 JSON 和 hash
13. 将 staging revision 目录改名为正式新目录
14. 原子替换 HEAD.json
```

关键变化：

> 必须先关闭 OCAF 文档，再尝试 `os.replace()`。

这比把 Windows 文件锁归类为“永久阻塞”更合理。

## 7.4 乐观并发

```python
if requested_parent_revision_id != current_head_revision_id:
    raise RevisionConflictError
```

## 7.5 失败注入

至少注入：

- STEP postcheck；
- writer relation；
- index；
- commit；
- SaveAs；
- session close；
- Solve Worker；
- Verify Worker；
- CAE Gate；
- manifest；
- HEAD update。

所有失败必须证明：

```text
上一 HEAD 不变
上一 Revision 目录不变
没有部分正式 STEP/XBF
```

---

# 8. Pipeline 必须修复的具体问题

## 8.1 previous_result 没有进入正式 Pipeline Writer

Pipeline 当前：

```python
for batch in capture_session:
    writer.write_batch(batch)
```

没有：

```python
previous_result = session.get_current_result_shape(feature_label)
writer.write_batch(batch, previous_result=previous_result)
```

所以 `write_feature_result(..., previous_result)` 虽已实现，正式主链没有使用。

## 8.2 required_selection_ids 没有形成正式 Solve Stage

`TopologyRunConfig` 中应区分：

```text
required_selection_ids
required_cae_binding_ids
```

两者不能混用。

## 8.3 CAE Binding 被临时伪造成 selection_id

当前 Pipeline 根据 binding ID 构造：

```python
CaeBinding(binding_id=bid, selection_id=bid, analysis_role="load")
```

这不是实际 CAE Binding 数据。

必须从：

```text
Tag 100/5 CAEBindings
```

或 Canonical IR 中读取完整 binding：

- selection_id；
- allowed entity kinds；
- cardinality；
- analysis role；
- required；
- proof/history policy。

## 8.4 Pipeline 仍在主进程 Solve

正式 Pipeline 必须调用 Solve Worker，不得直接调用：

```python
PersistentSelectionService.solve()
```

## 8.5 valid_labels 范围过宽

`collect_tnaming_labels(design_root)` 会收集整个文档中的全部 TNaming Label，可能包括：

- 旧 Revision；
- 无关组件；
- Selection 自身；
- sibling feature；
- 已退休 relation。

必须建立：

```text
SelectionDependencyScope
```

每个 Selection 持久化：

- context feature key；
- context result root TagPath；
- 允许的 history label set；
-创建 revision；
- source role/relation IDs。

Solve 时只传该依赖闭包。

---

# 9. Selection Service v4

## 9.1 不得在 Solve 时 ensure_selection

当前 Solve 使用 `ensure_selection()`。

错误的 selection_id 会创建新空 Label，而不是报告不存在。

改为：

```python
entry = label_index.get_existing(...)
if entry is None:
    return INVALID_SELECTION_ID
```

## 9.2 Null Shape 检查

OCP 常返回 Null `TopoDS_Shape` 对象，不一定是 Python `None`。

必须统一：

```python
shape is None or shape.IsNull()
```

NamedShape 也应检查 `IsNull()`。

## 9.3 Policy/Contract fail-closed

当前 JSON 解析失败返回 None。

必须返回：

```text
INVALID_POLICY
INVALID_CONTRACT
```

required CAE Selection 不得使用默认值继续。

## 9.4 先 explode，再验证 semantics

当前代码先对 Compound 执行 Semantic Contract，再拆分实体。

正确顺序：

```text
CurrentShape
→ explode target entity kind
→ deduplicate
→ 对每个真实 FACE/EDGE 验证 semantics
→ classify cardinality
```

## 9.5 Semantic Contract 不得 fail-open

当前行为：

```text
surface type 获取失败 → 不报错
normal 获取失败 → 不报错
zone_id → pass
```

必须引入：

```text
VALIDATION_UNAVAILABLE
```

如果 contract 声明某项，但系统无法验证，该项不得视为通过。

## 9.6 Delete 前置判定

不要直接对已知删除目标调用 Solve。

持久化 Selection Dependency，检查其 source relation/current shape：

- evolution == DELETE；
- CurrentShape IsNull；
- source role retired。

然后返回：

```text
DELETED
```

未知情况才进入 Worker。

## 9.7 Solve Worker 输出

当前 Worker 只返回：

- status；
- count。

必须增加：

```json
{
  "selection_id": "...",
  "status": "unique",
  "entity_kind": "face",
  "resolved_count": 1,
  "entities": [
    {
      "shape_type": "FACE",
      "area": 600.0,
      "centroid": [0, 0, 15],
      "surface_type": "Plane",
      "normal": [0, 0, 1],
      "brep_path": "...",
      "source_label_entries": []
    }
  ],
  "native_exit_code": 0,
  "native_crash": false
}
```

Worker 应：

1. 显式 close session；
2. flush stdout；
3. 必要时 `os._exit(code)`，避免解释器析构崩溃；
4. 不通过 `parents[5]` 推测源码路径，使用已安装 package 或显式环境变量。

---

# 10. Tracked Operations 正确性

## 10.1 Pattern 当前 Fuse History 查询错误

错误结构：

```python
fused = fuser.Shape()
for face in Faces(fused):
    fuser.History().Modified(face)
```

正确结构：

```python
previous_fused = fused
tool = s

fuser.AddArgument(previous_fused)
fuser.AddTool(tool)
fuser.Perform()
new_fused = fuser.Shape()

for input_face in Faces(previous_fused):
    query history(input_face)

for input_face in Faces(tool):
    query history(input_face)

fused = new_fused
```

必须对每一步：

- `HasErrors()`；
- `IsDone()` 或等价状态；
- `History()`；
- `Modified(input)`；
- `Generated(input)`；
- `IsRemoved(input)`。

## 10.2 需要 History Composition

顺序 Fuse 后，最初 source face 的最终 descendants 可能经历多个阶段：

```text
source
→ transformed
→ fuse step 1
→ fuse step 2
→ final result
```

不能只保存每一阶段零散 relation，再假设 Selector 自动知道最终关联。

需要新增：

```python
HistoryGraph
HistoryComposer
```

将各阶段 exact history 组合为：

```text
original semantic source → final output entity set
```

同时保留 phase-level audit。

## 10.3 Primitive / Extrude / Revolve

应优先使用构造语义：

- start cap；
- end cap；
- profile edge generated side；
- axis；
- seam；
- inner/outer cylindrical face。

这些角色比 face index 更适合跨参数 Revision。

## 10.4 Boolean

必须使用同一个 Boolean Builder 的：

```text
Modified(old)
Generated(old)
IsRemoved(old)
```

不得在 clean/unify 后丢失 history。

如果后处理改变拓扑却没有 history：

```text
history_complete=False
```

enforce required CAE 不得通过。

## 10.5 Fillet/Chamfer EDGE

输入 EDGE 必须来自：

- 已持久化 Selection；
- 稳定 construction role；
- 上游 exact history。

不得从当前 `Edges()[i]` 创建跨 Revision identity。

---

# 11. Relation Writer v3

## 11.1 新 Label Schema

建议：

```text
Feature
├── Metadata
├── ResultRoot                       ← body context NamedShape
│   ├── <relation_tag_1>             ← TNaming_NamedShape only
│   ├── <relation_tag_2>
│   └── ...
├── RelationMetadata
│   ├── <relation_tag_1>             ← JSON / proof / source ref
│   └── ...
├── RoleMetadata
└── Audit
```

## 11.2 移除 position fallback

生产模式禁止：

```python
1001 + rel_idx
```

仅可在旧文档只读 migration 工具中保留。

## 11.3 关系写法

### PRIMITIVE

```python
builder.Generated(new_shape)
```

### GENERATED 1→N

同一 Label、同一 Builder：

```python
for new in new_shapes:
    builder.Generated(old, new)
```

### MODIFIED 1→N

同一 Label：

```python
for new in new_shapes:
    builder.Modify(old, new)
```

### DELETED

```python
builder.Delete(old)
```

## 11.4 Shape Kind 校验

`LiveEvolutionRelation.validate()` 必须验证：

```text
entity_kind == old_shape.ShapeType()
entity_kind == each new_shape.ShapeType()
```

必要时允许显式 type migration，但必须单独声明：

```python
allow_type_migration=True
```

当前 T2 中 FACE relation 传 SOLID 应直接失败。

---

# 12. CAE Gate v2

## 12.1 当前问题

- Pipeline 临时构造 Binding；
- history complete gate 未接入；
- proof 信息没有进入 SelectionResolution；
- allowed kinds 检查遇到 `actual_kind=None` 时可能未阻止；
- preflight 在主进程 Solve；
- 没有完整 JSON artifact；
- 没有证明 solver 永远不能绕过 gate。

## 12.2 Required Gate 条件

全部满足才通过：

```text
status == UNIQUE
或显式允许 SET

entity_kind ∈ allowed_entity_kinds
cardinality 满足
SemanticContract 全部可验证且通过
proof == EXACT_KERNEL_HISTORY 或受控 SEMANTIC_ROLE_HISTORY
history_complete == True
native_crash == False
heuristic_used == False
revision_id == current HEAD
manifest hashes 一致
```

## 12.3 两类合法 Proof

建议区分：

```text
EXACT_KERNEL_HISTORY
EXACT_CONSTRUCTION_ROLE
```

例如 BRepPrimAPI_MakeBox 的 TopFace 角色映射不是 Boolean history，但它是 builder 提供的明确构造语义，不是几何指纹。

禁止将其标成 heuristic。

## 12.4 Solver Adapter

Solver 启动接口必须强制接收：

```python
ValidatedCaeBindingBundle
```

不能让调用者直接传 face index 或任意 BREP 绕过 preflight。

---

# 13. 库升级策略

## 13.1 不立即全量升级

升级 OCP 会同时影响：

- CadQuery compatibility；
- Boolean history；
- STEP；
- Fillet；
- ABI；
- Windows DLL；
- 现有基线。

## 13.2 先建版本矩阵环境

```text
env-7811
env-7812
env-7931
```

同一测试数据、同一 Schema、同一 fixture。

## 13.3 升级门槛

只有满足以下之一才升级：

1. C++ 7.8 fixture 失败、C++ 7.9 fixture 成功；
2. OCP 7.8 binding 崩溃、OCP 7.9 同一调用成功；
3. 官方 changelog/commit 明确修复当前 TNaming case；
4. 完整 CadQuery/G-CAD 回归通过。

## 13.4 当前源码比较结论

OCCT 7.8.1 与 7.9.3 的 Selector 核心机制仍相同：

- Result Context；
- Result Label 下的子 NamedShape；
- Naming rule；
- Solve。

因此不能假设升级会自动补齐缺失的 subshape history。

---

# 14. 下一阶段 PR 规划

## PR-1：正确 TNaming 基准与 Schema v3

修改：

```text
schema.py
writer.py
models.py
tests/test_tnaming_semantic_box_cpp/*
tests/test_tnaming_semantic_box_python.py
```

任务：

- ResultRoot 子历史 Schema；
- semantic MakeBox roles；
- relation shape kind validation；
- UNIQUE Face T2；
- C++/Python fixture。

Gate：

```text
Python OCP 7.8.1.1 下先完成正确 fixture；
若失败，输出 C++ 对照结果，不得直接归因版本。
```

## PR-2：StableLabelIndex v3

修改：

```text
label_index.py
document.py
schema.py
```

任务：

- 去除 placeholder；
- 父 TagPath 参数化；
- relation/revision/CAE 全持久化；
- revision number 恢复；
- relation order perturbation；
- stale entry 清理/重写策略。

## PR-3：HistoryGraph 与 tracked ops

新增：

```text
history_graph.py
history_composer.py
source_entity_ref.py
```

修复：

- Pattern；
- Boolean postprocess；
- Fillet/Chamfer；
- Unify；
- construction roles。

Gate：

- 每个 operation 提供 input→final output exact history；
- `history_complete` 可证明。

## PR-4：Selection Service v4

任务：

- read-only lookup；
- Null guards；
- explode before semantics；
- fail-closed contract；
- dependency scope；
- Delete preclassification；
- Worker enhanced output。

## PR-5：Revision Bundle

新增：

```text
revision_store.py
artifact_bundle.py
head_store.py
verify_worker.py
solve_worker.py
```

任务：

- immutable revision dir；
- parent conflict；
- close-before-replace；
- HEAD atomic；
- failure injection。

## PR-6：Pipeline Native Topology Stage

任务：

- previous_result 自动注入；
- required selection stage；
- persisted CAE Binding；
- worker solve；
- preflight；
- bundle publish；
- no direct official STEP before gate。

## PR-7：CAE Gate 与 Solver Adapter

任务：

- proof/history/evidence；
- binding artifact；
- solver cannot bypass；
- actual dry-run solver。

## PR-8：T0～T12 与版本矩阵

包括：

- Face；
- Edge；
- Split；
- Merge；
- Delete；
- Pattern；
- Construction roles；
- corrupted XBF；
- Unicode；
- G-CAD 3 Revision E2E。

---

# 15. 新 T0～T12 Gate

| ID | 场景 | 通过标准 |
|---|---|---|
| T0 | XBF/TNaming 基础 | 保持 |
| T1 | 单 Revision FACE | UNIQUE + 精确语义 |
| T2 | 三进程 semantic face Modify | 三 Rev 均 UNIQUE |
| T3 | Boolean 1→N | 顺序扰动后关系稳定 |
| T4 | Delete | 前置 DELETED，不崩溃 |
| T5 | N→1 Unify | merged FACE 唯一 |
| T6 | Construction roles | role Label 跨参数不变 |
| T7 | Pattern | instance role 到 final fuse 完整 |
| T8 | Fillet/Chamfer EDGE | EDGE 唯一恢复 |
| T9 | Artifact rollback | HEAD/old revision 不变 |
| T10 | Unicode | 全链路 |
| T11 | CAE | required 失败 solver=0 |
| T12 | Text→CAD→3 Rev→CAE | 完整 Bundle |

---

# 16. 代码 Agent 禁止事项

1. 不得把独立重建几何之间的 face index 配对标为 exact history；
2. 不得继续把 body Modify 的 Compound 结果解释为 OCP Face 限制；
3. 不得在没有 C++ 对照时宣称 OCCT 缺陷；
4. 不得默认升级 OCP；
5. 不得保留 production relation position fallback；
6. 不得在 relation path 使用 dummy component；
7. 不得在 Solve 时 ensure 不存在的 Selection；
8. 不得在主 Pipeline 直接执行危险 Solve；
9. 不得用输出 face 查询 Boolean input history；
10. 不得先写正式 STEP，再在 OCAF enforce 失败后保留它；
11. 不得将 `copy2` 描述成原子发布；
12. 不得吞掉 required metadata parse error；
13. 不得在无法验证 contract 时视为通过；
14. 不得把模块测试等同完整 E2E；
15. 不得把 skipped/ignored 计入 passed；
16. 不得让 Audit fingerprint 反向建立身份；
17. 不得使用 `TopoDS_Shape.HashCode` 作为必要条件；
18. 不得让 CAE solver 接受未验证 Selection；
19. 不得对 official XBF 原地修改；
20. 不得在 `history_complete=False` 时通过 required gate。

---

# 17. 每个 PR 的交付要求

代码 Agent 每个 PR 必须提交：

```text
Git SHA
修改文件
删除文件
公开 API 变化
OCAF Label Schema 变化
数据迁移影响
测试命令
Passed / Failed / Skipped / Ignored
C++ fixture 结果
Python fixture 结果
版本矩阵结果
failure injection 结果
未解决问题
Gate 是否通过
```

---

# 18. 最终 Definition of Done

只有全部满足，才能声明：

```text
Correct Native Persistent Topology Naming
```

1. 正确语义 FACE fixture 在至少一个受支持 OCP 版本下三进程 UNIQUE；
2. 证明该结果来自 OCAF/TNaming，不是 fingerprint；
3. ResultRoot 与 subshape history 结构符合 Selector 机制；
4. Relation Label 100% 使用 Stable RelationKey；
5. Stable Index 无 placeholder；
6. revision/relation/CAE binding 均跨进程恢复；
7. Pipeline 自动读取 previous result；
8. 所有 required Selection 由 Worker Solve；
9. Delete 不导致主进程崩溃；
10. Pattern 使用 input history 并完成 history composition；
11. Boolean/Fillet/Unify history_complete 可证明；
12. Semantic Contract fail-closed；
13. FACE 与 EDGE 均有语义验证；
14. Immutable Revision Bundle；
15. HEAD 与 optimistic concurrency；
16. close-before-atomic-publish；
17. XBF/STEP/metadata hash 一致；
18. CAE solver 无法绕过 gate；
19. T0～T12 全通过；
20. 版本矩阵和 CI Manifest 可复现。

---

# 19. 最终专家结论

当前系统已经拥有足够扎实的基础，不应推倒重来。

真正需要推翻的是两个认识：

```text
“整体 body Modify 就足以追踪任意 face”
“当前失败说明 7.8.1 永远不支持 face UNIQUE”
```

原生拓扑命名的本质不是让 OCCT 猜测几何，而是：

```text
用建模语义和算法 history
把每个重要拓扑实体的演化明确登记进 OCAF
再让 Selector 基于这些原生证据重建 Selection
```

下一阶段的最高优先级是构建一个完全正确的 FACE 级语义基准，并据此重新判断库版本。只要该基准打通，后续 Stable Relation、Revision Bundle、CAE Gate 都可以沿同一原则扩展；若该基准在 C++ 7.8 中失败、7.9 中成功，才有充分理由升级。

因此，交给代码 Agent 的第一条指令应是：

> **停止把 AMBIGUOUS 当作 T2 通过；停止以独立 Box 的 body Modify 判断 TNaming 能力。先重构 ResultRoot 子历史树，使用 BRepPrimAPI_MakeBox 语义面建立三 Revision UNIQUE fixture，并执行 C++/Python × 7.8/7.9 对照。**
