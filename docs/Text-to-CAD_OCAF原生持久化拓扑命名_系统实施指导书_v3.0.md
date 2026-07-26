# Text-to-CAD OCAF 原生持久化拓扑命名系统实施指导书 v3.0

> 文档用途：交付代码 Agent，作为实现、测试、审查和验收的唯一执行规范。  
> 适用仓库：`WYZAAACCC/text2cad_improve`，`main` 分支。  
> 形成依据：现有 Text-to-CAD / G-CAD 运行链、OCAF/TNaming 相关代码、`Text-to-CAD_OCAF原生持久化拓扑命名_修复与改进实施指导书_v2.0.md`、`OCAF_完整诊断测试报告_v3.0.md` 及已完成的 OCP 7.8.1.1 实验。  
> 执行原则：代码 Agent 开工前必须记录实际基线 SHA；本文不允许以“README 中描述”替代源码与自动测试证据。

---

## 0. 执行摘要

本系统的目标不是给几何面、边生成一个看似稳定的编号，也不是使用面积、质心或面数组下标猜测“这大概还是原来的面”。目标是构建真正的 OCAF/TNaming 原生拓扑身份系统：

```text
自然语言 / G-CAD 语义操作
        ↓
确定性 OCCT Builder 单次执行
        ↓
捕获真实 old/new TopoDS_Shape 演化历史
        ↓
写入稳定 TDF_Label 上的 TNaming_NamedShape / TNaming_Naming
        ↓
BinXCAF/XBF 原生持久化
        ↓
进程退出、重新 Retrieve
        ↓
下一 Revision 写入 Generated / Modify / Delete
        ↓
TNaming_Selector.Solve
        ↓
恢复唯一 FACE / EDGE / SET
        ↓
CAE 载荷、约束、网格控制继续绑定到同一工程语义区域
```

现有诊断已经证明：

1. BinXCAF、`TDataStd_*`、`TNaming_NamedShape` 和 `TNaming_Naming` 的底层原生持久化可用；
2. 无需重写 BinMNaming/BinMDataStd 驱动，也不应先升级 OCP；
3. 过去的失败主要来自 UTF-8 路径构造错误、同进程 `AlreadyRetrieved`、XCAF 保留 Tag 冲突及部分 OCP 输出参数包装缺陷；
4. 当前真正阻塞系统的不是 XBF，而是应用层：真实 old/new Shape 被丢弃、TNaming Writer 语义错误、标签身份不稳定、Selection 仍以几何指纹为权威、Revision 生命周期没有形成事务闭环。

因此，本实施不再继续验证“XBF 能不能保存整数”。从第一阶段起，所有工作围绕以下最终门禁展开：

```text
Select → Save → 进程退出 → Retrieve →
Rebuild → Generated/Modify/Delete → Solve →
精确恢复预期 FACE/EDGE/SET
```

---

## 1. Agent 开工规则

### 1.1 固定基线

Agent 第一个提交前必须执行：

```bash
git checkout main
git pull --ff-only
BASE_SHA=$(git rev-parse HEAD)
echo "$BASE_SHA" > docs/ocaf_implementation_base_sha.txt
git status --short
```

若工作树非干净状态，不得自动覆盖用户修改。应在实施状态文件中列出冲突文件，再停止修改相关文件。

### 1.2 实施状态文件

新增并持续更新：

```text
docs/OCAF_原生拓扑命名_implementation_status.md
```

每个阶段必须记录：

- 基线 SHA 与当前 SHA；
- 修改文件；
- 已完成验收项；
- 实际执行的测试命令；
- 测试输出摘要与证据文件路径；
- 未完成项、阻塞项和降级项；
- 是否允许进入下一阶段。

严禁只写“功能已实现”而没有测试证据。

### 1.3 PR/提交边界

按本文阶段拆分提交。不要一次性重写全部系统。

建议顺序：

1. PR-0：冻结诊断与建立回归基线；
2. PR-1：兼容层、固定 Schema、Document 生命周期；
3. PR-2：Live History 数据模型与捕获会话；
4. PR-3：Boolean History + 正确 TNaming Writer；
5. PR-4：原生 Selection/Solve 服务；
6. PR-5：Extrude/Revolve/Fillet/Chamfer/Clean 覆盖；
7. PR-6：G-CAD Pipeline 单 Revision 事务集成；
8. PR-7：CAE Binding 与 fail-closed preflight；
9. PR-8：压力测试、性能、可选版本升级。

任何阶段失败，必须保留上一阶段可运行状态。

### 1.4 禁止事项

实现过程中禁止：

- 使用 `Faces()[i]`、`Edges()[i]` 作为持久身份；
- 使用 Python `hash()` 生成持久 Tag；
- 在 `doc.Main()` 下调用无约束 `NewChild()`；
- 使用面积、质心、法向、最近邻作为权威身份；
- 将 `FindAttribute()` 返回对象视为一定拥有真实 Label；
- 调用已知危险的 `TDF_Tool.Label_s()`；
- 在正式读取链中使用未检查状态的 `app.Open(..., doc)`；
- 在异常路径使用 `except Exception: pass`；
- 在同一 TNaming Label 上混写不同 Evolution 类型；
- 在几何、OCAF 或 CAE gate 失败后仍发布新 XBF；
- 为“先跑起来”静默切换到指纹匹配并返回成功；
- 在核心重构 PR 中同时升级 CadQuery/OCP/OCCT。

---

## 2. 已确认的底层事实与调用约束

### 2.1 UTF-8 路径

所有传给 OCCT 的 Python 字符串必须通过统一 UTF-8 构造：

```python
from pathlib import Path
from OCP.TCollection import TCollection_ExtendedString


def ext_utf8(value: str | Path) -> TCollection_ExtendedString:
    return TCollection_ExtendedString(str(value), True)
```

第二个参数不可省略。以下入口全部使用该函数：

- `SaveAs` 完整路径；
- `Retrieve` 的 folder；
- `Retrieve` 的 filename；
- OCAF 中可能包含中文的 Name、AsciiString 或描述文本；
- XmlXCAF 路径；
- 临时验证文件路径。

同时保留 ASCII staging workspace 作为部署兜底，但不能将“禁止中文路径”作为架构方案。

### 2.2 文档读取

生产读取采用返回文档对象的 `Retrieve()`：

```python
doc = app.Retrieve(
    ext_utf8(path.parent),
    ext_utf8(path.name),
    True,
)
```

读取后必须检查 Application 的 Retrieve 状态及文档非空状态。不得继续沿用：

```python
doc = TDocStd_Document(...)
app.InitDocument(doc)
app.Open(path, doc)
```

原因包括：

- `Open` 使用输出 Handle；
- 同 Session 可能返回 `AlreadyRetrieved`；
- 当前代码忽略状态；
- 容易把预初始化空文档当成读取结果。

### 2.3 Attribute 访问

当前 OCP 绑定中，`TDF_Label.FindAttribute()` 可能通过 `Restore()` 复制到壳对象，不能依赖其 `Label()`。实现安全访问层：

1. 普通属性：使用 `TDF_AttributeIterator` 枚举真实挂接属性；
2. Selection：使用 `TNaming_Selector(native_label).NamedShape()` 获取真实 NamedShape；
3. Label 反查：使用持久 Tag Path，自顶向下 `FindChild(tag, False)`；
4. `TDF_Tool.Entry_s()` 只用于日志输出；
5. 禁止 `TDF_Tool.Label_s()`。

### 2.4 进程边界

持久化验收必须在独立进程中完成：

```text
Writer Process → Save temp XBF → Exit
Verifier Process → Retrieve temp XBF → Validate → Exit
Publisher → os.replace(temp, official)
```

不得以同一 Python 进程中的对象仍可访问作为持久化成功证据。

---

## 3. 当前代码问题清单

### 3.1 `ocaf/document.py`

当前问题：

- 文档被描述为“一次 pipeline revision 一个文档”，与 lineage 模型相反；
- `doc.Main().NewChild()` 实际撞入 XCAF `Shapes` 等保留标签；
- `get_or_create_component_label()` 实际始终创建新标签；
- `save()` 注释称原子保存，实际直接覆盖正式目标；
- 路径构造未启用 UTF-8；
- fsync 异常被吞掉；
- `open()` 使用不安全 `Open`，忽略状态；
- 重开后把 `doc.Main()` 错当 DesignRoot；
- `_written_node_ids` 仅是会话内集合，不能形成持久身份。

处置：完整重写，不在旧类上继续打补丁。

### 3.2 `ocaf/models.py`

当前 `EvolutionRelation` 明确不存 live old/new Shape，只保存 evidence 和数量。这与 TNaming 的必要输入直接矛盾。

处置：拆分 Live Model 和 Audit Model。Writer 只接受 Live Model；JSON 元数据只接受 Audit Projection。

### 3.3 `ocaf/writer.py`

当前错误包括：

```text
DELETED  → Delete(batch.result_shape)
GENERATED → Generated(batch.result_shape)
MODIFIED → Generated(batch.result_shape)
```

并且：

- 特征和 relation label 全部 `NewChild()`；
- Result 写入异常被吞掉；
- 每个 batch 自己开启事务；
- 没有 memory self-check；
- 没有 Selection Solve；
- 没有稳定的 relation identity。

处置：重写为无事务、纯写入的 `TopologyNamingWriter`；事务由 Revision Session 统一管理。

### 3.4 `ocaf/selectors.py`

当前把几何指纹当作面级持久身份，并以 face index 创建选择。这一模块不能继续名为 `FaceSelector`，也不能作为 CAE 绑定权威。

处置：

- 新增原生 `PersistentSelectionService`；
- 将现有模块重命名为 `heuristic_candidates.py`；
- 只用于诊断、旧数据迁移和人工修复候选；
- 任何 heuristic 结果都不得自动升级为 `UNIQUE` 权威结果。

### 3.5 `capture_session.py` 与 tracked ops

`CaptureSession` 声称替代全局缓存，实际仍从 `boolean.py::_staged_batches` 拉取 token。该桥接会产生泄漏、跨任务污染和顺序不确定性。

`boolean.py`、`extrude.py`、`revolve.py`、`fillet.py` 已经获得真实 Generated/Modified 列表，却立即丢弃具体 Shape，只记录数量。Fillet 仍以 edge index 作为输入身份。

处置：

- `TrackedShapeResult` 直接返回 Live Batch；
- 删除全局 `_staged_batches`、`capture_token` 和 `get_staged_batch()`；
- CaptureSession 接管批次有序集合；
- 捕获 FACE 与 EDGE 的真实 Handle；
- Fillet 输入改为持久 Selection Resolution，而不是下标。

### 3.6 `runtime/context.py` 与 `pipeline/run.py`

RuntimeContext 已存在若干拓扑字段，但没有完整 OCAF lineage、revision、capture、selection 和 publish lifecycle。

Pipeline 当前在组件执行、空间审计、runtime postconditions、STEP export、geometry postcheck 之后生成 metadata。OCAF 必须作为同一 Revision 的硬门禁接入，不能独立旁路保存。

---

## 4. 目标架构

### 4.1 权威层级

系统中的权威顺序固定为：

```text
1. 规范 G-CAD 业务 ID 与操作语义
2. 实际 OCCT Builder 的 old/new Shape history
3. 稳定 TDF_Label 与 TNaming 原生属性
4. Selection Policy + Semantic Contract
5. 几何 evidence / fingerprint（仅审计和候选）
6. STEP 中的实体顺序（永不作为身份）
```

任何下层不得覆盖上层。

### 4.2 一个 lineage 一个 OCAF 文档

一个设计 lineage 对应一个持续演化的 XBF：

```text
design_lineage_id
  ├── revision 1
  ├── revision 2
  ├── revision 3
  └── ...
```

Revision 不新建另一套无关联的标签树。相同 component、feature、selection、CAE binding 必须更新原有稳定 Label。

### 4.3 OCAF 固定标签 Schema

DesignRoot 使用固定 Tag 100，远离 XCAF 1～10 系统工具区：

```text
0:1 Main / XCAF Document Tool
├── 1..10                 XCAF reserved tools
└── 100                   Text2CAD DesignRoot
    ├── 1 Metadata
    ├── 2 Components
    ├── 3 Selections
    ├── 4 Assembly
    ├── 5 CAEBindings
    ├── 6 Revisions
    └── 7 StableIdIndex
```

Component：

```text
Components/<component-tag>
├── 1 Metadata
├── 2 Features
├── 3 CurrentBody
└── 4 Audit
```

Feature：

```text
Features/<feature-tag>
├── 1 Metadata
├── 2 CurrentResult          # stable result label
├── 3 EvolutionRelations
├── 4 ConstructionRoles
└── 5 RevisionAudit
```

Selection：

```text
Selections/<selection-tag>
├── 1 NativeNaming           # TNaming_Selector 独占
├── 2 Metadata
├── 3 SemanticContract
└── 4 Audit
```

`NativeNaming` Label 必须独占。不得同时在该 Label 写业务 Name、Integer、JSON 字符串等，因为 Selector 可能重建或清理命名属性。

### 4.4 Stable ID → Tag

禁止使用 Python hash。实现持久分配器：

```python
@dataclass(frozen=True)
class TagPath:
    tags: tuple[int, ...]
```

索引项至少包含：

- `object_kind`；
- `object_id`；
- `tag_path`；
- `created_revision`；
- `retired_revision`；
- `schema_version`。

分配规则：

- 对象首次出现时，从对应容器的持久单调计数器分配 Tag；
- 已删除 Tag 永不复用；
- 相同 object ID 必须解析到同一路径；
- object ID 冲突或重复种类不一致时 fail-closed；
- JSON index 只是镜像，OCAF 内索引为权威。

建议组件/特征对象动态 Tag 从 1000 开始，避免与固定结构子 Tag 混淆。

---

## 5. 核心数据模型

### 5.1 Live 与 Audit 严格分离

新增或重写 `ocaf/models.py`：

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvolutionKind(str, Enum):
    PRIMITIVE = "primitive"
    GENERATED = "generated"
    MODIFIED = "modified"
    DELETED = "deleted"


class TopologyEntityKind(str, Enum):
    SOLID = "solid"
    SHELL = "shell"
    FACE = "face"
    WIRE = "wire"
    EDGE = "edge"
    VERTEX = "vertex"


class ProofClass(str, Enum):
    EXACT_KERNEL_HISTORY = "exact_kernel_history"
    EXACT_CONSTRUCTION = "exact_construction"
    PARTIAL_POSTPROCESS = "partial_postprocess"
    EXTERNAL_IMPORT = "external_import"
    HEURISTIC_CANDIDATE = "heuristic_candidate"
    FAILED = "failed"


@dataclass(frozen=True)
class LiveEvolutionRelation:
    relation_id: str
    operation_id: str
    kind: EvolutionKind
    entity_kind: TopologyEntityKind
    source_key: str
    old_shape: Any | None
    new_shapes: tuple[Any, ...]
    proof: ProofClass
    diagnostics: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.kind is EvolutionKind.PRIMITIVE:
            assert self.old_shape is None
            assert len(self.new_shapes) >= 1
        elif self.kind in (EvolutionKind.GENERATED, EvolutionKind.MODIFIED):
            assert self.old_shape is not None
            assert len(self.new_shapes) >= 1
        elif self.kind is EvolutionKind.DELETED:
            assert self.old_shape is not None
            assert len(self.new_shapes) == 0


@dataclass
class LiveEvolutionBatch:
    scope: "TopologyCaptureScope"
    builder_kind: str
    result_shape: Any
    context_shape: Any
    relations: list[LiveEvolutionRelation] = field(default_factory=list)
    construction_roles: dict[str, Any] = field(default_factory=dict)
    history_complete: bool = True
    missing_phases: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvolutionRelationAudit:
    relation_id: str
    operation_id: str
    kind: str
    entity_kind: str
    source_key: str
    proof: str
    old_evidence: dict | None
    new_evidence: tuple[dict, ...]
    diagnostics: tuple[str, ...]
```

约束：

- Live Shape 不跨进程、不进入 JSON；
- Audit 不参与 TNaming 写入；
- Writer 参数类型只能是 `LiveEvolutionBatch`；
- 对非法关系立即报错，不做猜测修复。

### 5.2 `TrackedShapeResult`

改为：

```python
@dataclass(frozen=True)
class TrackedShapeResult:
    result: Any
    batch: LiveEvolutionBatch
    diagnostics: tuple[str, ...] = ()
```

删除：

- `capture_token`；
- 全局 staging；
- token → batch 查询。

### 5.3 Selection 模型

```python
class SelectionCardinality(str, Enum):
    EXACT_ONE = "exact_one"
    SET_ALLOWED = "set_allowed"


class SelectionResolutionStatus(str, Enum):
    UNIQUE = "unique"
    SET = "set"
    DELETED = "deleted"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    INVALID_SEMANTICS = "invalid_semantics"


@dataclass(frozen=True)
class SelectionPolicy:
    entity_kind: TopologyEntityKind
    cardinality: SelectionCardinality = SelectionCardinality.EXACT_ONE
    allow_deleted: bool = False
    required_for_cae: bool = False


@dataclass(frozen=True)
class SemanticContract:
    surface_type: str | None = None
    curve_type: str | None = None
    expected_axis: tuple[float, float, float] | None = None
    expected_normal: tuple[float, float, float] | None = None
    radius_range: tuple[float, float] | None = None
    zone_id: str | None = None
    orientation: str | None = None
    connectivity_role: str | None = None
```

Semantic Contract 只能用于后验验证，不能取代 TNaming 身份演化。

---

## 6. 兼容层实施

扩展 `ocaf/compat.py`，所有 OCP 边界调用集中在此文件。建议接口：

```python
def get_xcaf_application(): ...
def define_binxcaf_format(app) -> None: ...
def ext_utf8(value: str | Path): ...
def new_xcaf_document(app): ...
def retrieve_xcaf_document(app, path: Path): ...
def iter_attributes(label): ...
def find_real_attribute_by_type(label, expected_type_name: str): ...
def entry_of(label) -> str: ...
def resolve_tag_path(main_label, path: TagPath, create: bool): ...
def save_status_ok(status) -> bool: ...
def retrieve_status_ok(app) -> bool: ...
def shape_is_null(shape) -> bool: ...
```

`find_real_attribute_by_type()` 必须通过 Iterator 返回真实属性对象，不使用 `FindAttribute` 壳：

```python
def find_real_attribute_by_type(label, expected_type_name: str):
    from OCP.TDF import TDF_AttributeIterator

    it = TDF_AttributeIterator(label)
    while it.More():
        attr = it.Value()
        if attr.DynamicType().Name() == expected_type_name:
            return attr
        it.Next()
    return None
```

动态类型转换若 OCP 需要 DownCast，应在此层集中处理并附 smoke test。

---

## 7. Document 与 Revision 生命周期

### 7.1 类拆分

不要继续使用“一类包办所有事情”的 `OcafDocumentSession`。拆为：

```text
OcafRepository         # create/retrieve/save/publish/lock
OcafSchema             # fixed tag tree and schema version
StableLabelIndex       # business ID ↔ TagPath
RevisionTransaction    # one revision, one OCAF command
OcafVerifier           # memory + subprocess validation
```

### 7.2 RevisionTransaction

一个 Revision 只允许一次顶层 OCAF transaction：

```python
with revision_transaction(document, revision_id) as tx:
    # 1. 构建所有几何
    # 2. 写 feature result/history
    # 3. 更新/创建 selections
    # 4. Solve required selections
    # 5. semantic validation
    # 6. CAE preflight
    # 7. tx.commit()
```

Writer 不得内部调用 `NewCommand/CommitCommand`。

异常时：

- `AbortCommand()`；
- 删除临时文件；
- 上一正式 XBF 保持不变；
- Revision 状态写为 `FAILED`，但不得伪造成功 revision。

### 7.3 单写者锁

同一 lineage 同时只允许一个 Writer：

- 使用 lineage 目录下锁文件或 OS 文件锁；
- 锁中写 PID、host、start time、base revision；
- 提交前验证当前正式 revision 未变化；
- 冲突时 fail-closed，不自动覆盖。

### 7.4 原子保存

正式流程：

```text
official.xbf
    ↑ 仅在全部验证成功后 os.replace
.tmp.<revision>.<uuid>.xbf
```

步骤：

1. `SaveAs(doc, temp)`；
2. 检查 Store Status；
3. fsync temp；
4. 启动独立 verifier subprocess；
5. verifier `Retrieve`；
6. 检查 Schema、StableIndex、Revision、所有 required Selection；
7. verifier 成功退出；
8. `os.replace(temp, official)`；
9. fsync 目录；
10. 写发布审计记录。

`enforce` 模式下，任何 fsync、verify、replace 异常都视为失败。

---

## 8. History 捕获规范

### 8.1 单次 Builder 执行

每个 tracked operation 必须满足：

- 实际几何 Builder 只执行一次；
- 几何结果与 capture-off 路径完全一致；
- History 从该实际 Builder 直接读取；
- 不允许为了取 History 再跑一次“影子 Builder”。

### 8.2 Boolean

重写 `_export_bopalgo_history()`：

```python
for source_key, old_shape in stable_sources:
    generated = tuple(history.Generated(old_shape))
    modified = tuple(history.Modified(old_shape))
    removed = history.IsRemoved(old_shape)

    if generated:
        relations.append(LiveEvolutionRelation(
            kind=EvolutionKind.GENERATED,
            old_shape=old_shape,
            new_shapes=generated,
            ...,
        ))

    if modified:
        relations.append(LiveEvolutionRelation(
            kind=EvolutionKind.MODIFIED,
            old_shape=old_shape,
            new_shapes=modified,
            ...,
        ))

    if removed:
        relations.append(LiveEvolutionRelation(
            kind=EvolutionKind.DELETED,
            old_shape=old_shape,
            new_shapes=(),
            ...,
        ))
```

必须覆盖 FACE 和 EDGE。仅在 source shape 已有稳定 source key 时，关系才可进入权威 graph。

旧代码使用 `target_face_0`、`tool_face_3` 等数组下标作为 source role，不得继续作为持久 source key。对于尚无稳定 provenance 的输入，可记录为 audit-only，并在 strict mode 阻止依赖它的 required selection。

### 8.3 Extrude/Revolve

使用 Builder 的：

- `Generated(old)`；
- `Modified(old)`；
- `FirstShape()`；
- `LastShape()`。

同时建立确定性 construction roles，例如：

```text
profile.edge:<stable-profile-edge-id> → lateral face(s)
profile.face → body
cap:start
cap:end
```

`FirstShape`、`LastShape` 的角色语义必须经过操作类型测试，不能仅因为 API 名称就假定其永远是顶/底面。

### 8.4 Primitive 参数变化

新旧 revision 的 primitive builder 通常没有直接提供“旧 Builder 到新 Builder”的跨 revision history。此时只有满足严格数学角色保证的 construction role 才可写：

```text
EXACT_CONSTRUCTION:
old cap:start → new cap:start
old cap:end   → new cap:end
old side:<profile-role> → new side:<same-profile-role>
```

若角色不能唯一构造，不得基于面积/质心自动写 `Modify`。应返回 unresolved 或要求人工确认。

### 8.5 Fillet/Chamfer

输入必须是已经 Solve 的持久 EDGE Selection：

```python
resolved_edges = selection_service.require_edges(selection_ids)
tracked_fillet(body, resolved_edges, radius, ...)
```

接口不得再接受 `list[int]` 作为生产路径。可保留 index 参数仅用于测试工具，并明确标为 non-persistent。

捕获：

- selected edge → Generated fillet face；
- adjacent face → Modified face；
- removed edge/face（若 builder/history 可提供）；
- 结果不完整时将 proof 降为 `PARTIAL_POSTPROCESS`。

### 8.6 Clean / UnifySameDomain

任何可能合并、拆分或删除拓扑的 postprocess 都必须有独立 tracked phase。

如果当前 OCP API 无法取得准确 history：

- `off` 模式可保持旧行为；
- `audit` 模式标记 `history_complete=False`；
- `enforce` 模式下，若后续存在 required selection，禁止执行无历史 clean；
- 不允许通过 fingerprint 静默补全。

### 8.7 Pattern

Pattern 实例必须拥有稳定 instance ID：

```text
pattern_id / instance_id / source_feature_id / source_role
```

禁止使用当前角度排序、空间最近邻或面枚举顺序作为实例身份。

---

## 9. TNaming Writer 规范

### 9.1 一 Label 一 Evolution 类型

对每个 `LiveEvolutionRelation` 获取稳定 relation label，并严格调用：

```python
if rel.kind is EvolutionKind.PRIMITIVE:
    for new_shape in rel.new_shapes:
        builder.Generated(new_shape)

elif rel.kind is EvolutionKind.GENERATED:
    for new_shape in rel.new_shapes:
        builder.Generated(rel.old_shape, new_shape)

elif rel.kind is EvolutionKind.MODIFIED:
    for new_shape in rel.new_shapes:
        builder.Modify(rel.old_shape, new_shape)

elif rel.kind is EvolutionKind.DELETED:
    builder.Delete(rel.old_shape)
```

一个 old → 多个 new 应在同一 relation label 上写多个同类 pair，不为每个 new 创建无稳定身份的新随机 Label。

### 9.2 Feature CurrentResult

每个 Feature 的 CurrentResult 使用稳定 Label。它代表当前 revision 的 feature 结果，而不是替代详细 evolution graph。

写入策略需要 smoke test 后固化。若同 Label 重写 NamedShape 需要清理旧状态，应由专用函数实现并测试，不得直接堆叠多种 Evolution。

### 9.3 内存自检

写完每个 batch 后，在 commit 前至少验证：

- 所有 relation contract 合法；
- relation label 存在；
- NamedShape Attribute 可通过 Iterator 找到；
- NamedShape 有非空 Label；
- CurrentResult 非空且 ShapeType 符合预期；
- relation 数量与 live batch 一致；
- 未发生异常吞噬。

### 9.4 Audit Projection

Writer 完成后生成 audit JSON：

- relation ID；
- Label entry；
- evolution kind；
- old/new entity kind；
- old/new shape evidence；
- proof class；
- source operation；
- revision ID；
- diagnostics。

Audit 只能解释原生历史，不能作为恢复身份的主数据源。

---

## 10. 原生 Selection/Solve 服务

新增：

```text
ocaf/selection_service.py
ocaf/selection_models.py
ocaf/semantic_validation.py
```

### 10.1 创建 Selection

```python
class PersistentSelectionService:
    def create_selection(
        self,
        selection_id: str,
        selected_shape,
        context_shape,
        policy: SelectionPolicy,
        semantic_contract: SemanticContract,
    ) -> None:
        native_label = self.index.require_selection_native_label(selection_id)
        selector = TNaming_Selector(native_label)
        ok = selector.Select(selected_shape, context_shape)
        if not ok:
            raise SelectionCreateError(selection_id)
        # metadata 写入 sibling labels
```

创建时禁止输入 face index/edge index。UI 或调用层若只有 index，必须立即解析成当前 `TopoDS_Shape`，并把 index 标为非持久审计信息。

### 10.2 Solve

下一 Revision 在所有 feature histories 写完后统一：

```python
selector = TNaming_Selector(native_label)
solved = selector.Solve(valid_labels)
named_shape = selector.NamedShape()
current = TNaming_Tool.CurrentShape_s(named_shape)
```

实际 OCP 签名以 smoke test 为准，封装在 compat 层。

不得在历史尚未完整写入时逐 feature 提前 Solve。

### 10.3 Resolution 分类

根据 CurrentShape、实体数量、Policy 和 Semantic Contract 输出：

- `UNIQUE`：唯一且语义合法；
- `SET`：允许集合，集合成员全部合法；
- `DELETED`：目标已删除，且 Policy 允许；
- `AMBIGUOUS`：多个候选但 Policy 要求唯一；
- `UNRESOLVED`：无法解析；
- `INVALID_SEMANTICS`：TNaming 解出形状，但不满足业务语义。

required CAE selection 只有 `UNIQUE` 或明确允许的 `SET` 可通过。

### 10.4 几何指纹的角色

旧 `FaceSelector` 改名为 `HeuristicCandidateFinder`，返回：

```text
candidate list + score + evidence
```

它只能用于：

- 诊断为什么 Native Solve 失败；
- 迁移没有原生历史的旧模型；
- 提供人工确认候选；
- 测试 oracle。

它不能：

- 自动重绑 required selection；
- 将低距离候选宣称为唯一身份；
- 绕过 CAE gate；
- 写入 `EXACT_KERNEL_HISTORY` proof。

---

## 11. G-CAD Pipeline 集成

### 11.1 模式

新增配置：

```text
topology_mode = off | audit | enforce
```

- `off`：不捕获、不写 OCAF；几何输出必须与改造前字节/拓扑回归一致；
- `audit`：捕获并写审计，失败转为明确 warning，不允许 CAE 使用未验证选择；
- `enforce`：任何必需 history、selection、save、verify 失败，整个 pipeline 失败。

### 11.2 RuntimeContext 新字段

```python
topology_mode: str
design_lineage_id: str
base_revision_id: str | None
revision_id: str
ocaf_repository: Any | None
revision_transaction: Any | None
capture_session: Any | None
selection_service: Any | None
topology_audit: list[dict]
required_selection_ids: set[str]
```

### 11.3 执行顺序

推荐 Pipeline 次序：

```text
validate/canonicalize
→ compiler middle-end
→ acquire lineage lock / Retrieve base XBF
→ begin one OCAF Revision transaction
→ run components with tracked ops
→ write feature results and histories
→ composition / placements
→ geometry spatial audit
→ runtime postconditions
→ geometry health gate
→ solve all selections
→ semantic validation
→ CAE binding preflight
→ export STEP to temp
→ STEP postcheck
→ commit OCAF command
→ Save XBF to temp
→ independent verifier
→ publish STEP + metadata + XBF atomically/as a manifest set
```

注意：不能先正式发布 STEP，再发现 OCAF/CAE selection 失败。三个 artifact 应形成同一 revision manifest：

```json
{
  "revision_id": "...",
  "step_sha256": "...",
  "xbf_sha256": "...",
  "metadata_sha256": "...",
  "canonical_graph_hash": "...",
  "base_revision_id": "..."
}
```

### 11.4 Artifact 发布一致性

优先采用 revision 目录：

```text
lineage/
├── current.json
└── revisions/
    └── <revision_id>/
        ├── model.step
        ├── model.xbf
        ├── metadata.json
        └── manifest.json
```

所有文件在临时 revision 目录完成后，原子更新 `current.json` 指针。这样比同时替换多个正式文件更可靠。

---

## 12. CAE Binding

### 12.1 数据模型

```python
@dataclass(frozen=True)
class CaeBinding:
    binding_id: str
    selection_id: str
    analysis_role: str
    required: bool
    allowed_entity_kinds: tuple[TopologyEntityKind, ...]
    cardinality: SelectionCardinality
```

ANSYS/其他 CAE 层只接受 `selection_id`，不得接受：

- face index；
- edge index；
- 固定半径位置；
- 包围盒比例；
- 最近邻面。

### 12.2 Preflight

求解前输出结构化报告：

```text
binding_id
selection_id
resolution_status
resolved_entity_count
entity_kind
semantic_contract_result
revision_id
native_label_entry
proof_class
```

required binding 任一非合格即停止 FEA。禁止“找不到中心孔面就挑最靠内圆柱面”。

### 12.3 STEP/CAE 映射边界

OCAF 中的 Shape Handle 与导入 ANSYS 后的实体不是同一内存对象。后续需要独立的“导出/导入映射层”。在该层完成前：

- 可用 OCAF Selection 生成区域几何集合、独立 Named Selection 文件或 APDL 可重建区域；
- 不得声称仅凭 XBF Label 就自动绑定了 ANSYS 内部面号；
- CAE mapping proof 应单独记录。

---

## 13. 分阶段实施与验收

## PR-0：冻结诊断与回归基线

修改：

- 新建 `tests/topology/ocaf/smoke/`；
- 固化最新诊断中已经通过的 UTF-8、Tag 100、BinXCAF、NamedShape/Naming 跨进程测试；
- 保存环境版本、测试脚本和原始输出。

验收：

- ASCII、中文路径均通过；
- subprocess Retrieve 可恢复 Tag 100；
- NamedShape/Naming Attribute 存在；
- capture-off 几何回归建立基线。

## PR-1：Compat、Schema、Document Core

修改：

- 扩展 `compat.py`；
- 新建 `schema.py`、`label_index.py`、`repository.py`；
- 重写或废弃旧 `document.py`。

验收：

- DesignRoot 固定 100；
- 重开路径完全一致；
- ID→Tag 稳定跨进程；
- 中文路径；
- temp save + verifier + publish；
- 失败不覆盖上一 XBF；
- 不再调用 `Main().NewChild()`、`Open()`、`Label_s()`。

## PR-2：Live History 与 CaptureSession

修改：

- 重写 `models.py`；
- 重写 `capture_session.py`；
- 删除全局 staging/token。

验收：

- Live relation contract 单元测试；
- batch 顺序稳定；
- 多 pipeline 并发不串数据；
- clear 后无泄漏；
- Audit projection 不含 Shape Handle。

## PR-3：Boolean + Writer

修改：

- `tracked_ops/boolean.py`；
- `writer.py`；
- 增加真实 relation label schema。

验收：

- CUT/FUSE/COMMON 几何与 capture-off 一致；
- old/new Shape 实际进入 relation；
- Generated/Modify/Delete 原生属性写法正确；
- 1→N、Delete 测试；
- Writer 不开启内部 transaction；
- 任何异常 fail-closed。

## PR-4：Selection/Solve

修改：

- 新增原生 Selection Service；
- 旧 selector 降级为 heuristic candidate；
- 加 Semantic Contract。

验收：

- 创建时精确选择 FACE；
- 跨进程 Retrieve；
- Solve 后仍为预期 FACE，而不是 whole COMPOUND；
- UNIQUE/SET/DELETED/AMBIGUOUS/UNRESOLVED 分类正确；
- required selection 不允许 heuristic 自动兜底。

## PR-5：操作覆盖

修改：

- extrude、revolve、fillet；
- 新增 chamfer、clean/unify tracked phase；
- pattern stable instance identity。

验收：

- cap/side construction roles；
- fillet 输入为 persistent EDGE selection；
- Fillet 参数变化、Chamfer、Unify；
- 无 history postprocess 在 enforce 下被拒绝。

## PR-6：Pipeline Integration

修改：

- RuntimeContext；
- runtime operation handlers；
- `pipeline/run.py`；
- artifact manifest。

验收：

- topology_mode=off 几何行为不变；
- audit 有完整报告；
- enforce 中 OCAF/selection 失败导致 pipeline 失败；
- STEP、XBF、metadata 属于同一 revision；
- base revision 冲突被拒绝。

## PR-7：CAE Binding

修改：

- selection→CAE binding schema；
- preflight；
- ANSYS 入口只接受通过 preflight 的区域。

验收：

- required selection 丢失时 ANSYS 不启动；
- 跨 revision 载荷/约束仍指向正确语义区域；
- 解析集合数量和类型符合策略。

## PR-8：加固与可选升级

内容：

- 性能基准；
- 大型涡轮盘周期槽；
- 文件损坏与断电模拟；
- 并发锁；
- 可选 OCP 新版本矩阵。

升级 OCP 前必须让当前版本全部核心测试通过，并保留双版本回归。

---

## 14. 必须通过的测试矩阵

### T0：基础原生持久化

- Primitive NamedShape 跨进程；
- Selection Naming 跨进程；
- UTF-8 路径；
- Tag 100。

### T1：单 Revision 精确 Selection

使用不对称几何，选择一个唯一顶面：

- 保存；
- 进程退出；
- Retrieve；
- Solve；
- 断言 `ShapeType == FACE`；
- 面积、质心、法向仅作为测试 oracle；
- 禁止通过 face index 获取结果。

### T2：三进程跨 Revision

```text
Process A: Rev1 create + select + save
Process B: Retrieve Rev1 + rebuild Rev2 + Modify + Solve + save
Process C: Retrieve Rev2 + verify exact selection
```

### T3：1→N Split

旧面在 cut 后分裂多个面：

- policy EXACT_ONE → AMBIGUOUS；
- policy SET_ALLOWED → SET；
- 不得随意挑一个。

### T4：Delete

被选面确实删除：

- allow_deleted=False → pipeline failure；
- allow_deleted=True → DELETED；
- 不得匹配到相似新面。

### T5：N→1 / UnifySameDomain

多个旧面合并时：

- 关系历史和 selection 结果符合策略；
- clean 没有历史时 enforce 拒绝。

### T6：Extrude/Revolve construction roles

- start/end cap；
- profile edge lateral face；
- 参数改变后 role identity 稳定。

### T7：周期性相似面

涡轮盘/阵列使用多个几何近乎相同面：

- 原生 identity 不依赖最近邻；
- instance ID 稳定；
- 打乱面枚举顺序不影响结果。

### T8：Fillet/Chamfer EDGE

- selection 精确恢复 EDGE；
- fillet 生成面和 adjacent modified face 正确；
- 半径变化仍可 Solve；
- 删除或合并有明确状态。

### T9：保存失败与回滚

- transaction 异常；
- temp SaveAs 失败；
- verifier 失败；
- `os.replace` 失败；
- 上一 revision 保持可读。

### T10：路径和文件系统

- ASCII；
- 中文；
- 空格；
- 长路径；
- 无权限目录；
- 损坏 XBF；
- 同 Session 与 subprocess 行为。

### T11：CAE Gate

- 所有 required binding 成功才允许 solver；
- unresolved/ambiguous/deleted/invalid semantic 均阻止；
- 报告可审计。

### T12：完整 Text-to-CAD E2E

至少选择一个受控模型和一个涡轮盘模型：

```text
自然语言/G-CAD
→ Rev1 geometry
→ 原生 selection
→ XBF
→ 参数变更 Rev2
→ history
→ solve
→ CAE preflight
→ 输出一致 manifest
```

---

## 15. 测试断言规范

每个持久化测试必须同时断言：

- Store/Retrieve 状态；
- 文件存在及最小大小；
- Schema version；
- DesignRoot entry；
- stable object ID → TagPath；
- Attribute 动态类型；
- NamedShape Label 非空；
- CurrentShape 非空；
- ShapeType；
- 选择基数；
- semantic contract；
- revision ID 与 manifest；
- subprocess return code。

面积、质心、法向等只能作为测试 oracle 和诊断 evidence，不得成为系统身份算法。

---

## 16. 可观测性与错误模型

新增结构化错误类型：

```text
OcafPathEncodingError
OcafStoreError
OcafRetrieveError
OcafSchemaError
StableLabelConflictError
HistoryCaptureError
HistoryIncompleteError
NamingWriteError
SelectionCreateError
SelectionSolveError
SelectionAmbiguousError
SelectionDeletedError
SelectionSemanticError
CaeBindingPreflightError
RevisionConflictError
AtomicPublishError
```

错误记录至少包含：

- lineage/revision/base revision；
- component/node/operation；
- label entry；
- selection/relation ID；
- proof class；
- OCP status；
- stage；
- repairability；
- evidence path。

不要在用户消息中输出原生对象地址或不可复现的 Python repr 作为唯一证据。

---

## 17. 性能与内存要求

- Live Shape Handle 只存在于单个 Revision worker；
- Commit/Abort 后 CaptureSession 必须 clear；
- 不允许全局 batch registry；
- 大型周期模型按 operation batch 写入，不对每个面执行全局 O(n²) 指纹匹配；
- StableLabelIndex 应缓存当前进程映射，但以 OCAF 内容为权威；
- verifier 进程设置超时；
- 对 XBF 大小、保存时间、Retrieve 时间、Solve 时间建立基准。

性能优化不得牺牲 fail-closed 语义。

---

## 18. 旧数据迁移

对于历史版本只有 STEP/JSON 指纹、没有正确 TNaming history 的模型：

- 标记 proof 为 `EXTERNAL_IMPORT` 或 `HEURISTIC_CANDIDATE`；
- 允许 Candidate Finder 提供候选；
- 必须人工确认或重新建立 Selection；
- 一旦确认，在新的 lineage/revision 中创建原生 Selection；
- 不得伪造历史 Generated/Modify 关系；
- 旧 selection 未确认前不得用于 required CAE binding。

---

## 19. Definition of Done

只有同时满足以下条件，才可宣布“原生持久化拓扑命名系统完成”：

1. 正式代码不再使用已确认错误 API/模式；
2. 一个 lineage 可连续保存至少三个 revision；
3. T0～T12 全部通过；
4. FACE 和 EDGE 均有跨 revision 用例；
5. split、delete、fillet、unify、周期相似面均有明确结果；
6. required CAE binding 完全 fail-closed；
7. 中文路径和独立进程验证通过；
8. save/publish 失败不破坏上一 revision；
9. capture-off 几何回归无变化；
10. 没有 face/edge index 权威身份；
11. 没有自动 fingerprint 身份兜底；
12. 实施状态文件附完整测试证据。

仅通过 `Integer`、`NamedShape` 保存测试，不等于完成。仅能恢复 whole COMPOUND，不等于 Selection 成功。仅能在同一进程访问 Shape，不等于持久化成功。

---

## 20. Agent 最终交付物

代码 Agent 完成后应提交：

```text
1. 所有实现代码
2. 单元、集成、subprocess、E2E 测试
3. docs/OCAF_原生拓扑命名_implementation_status.md
4. docs/OCAF_Label_Schema_v1.md
5. docs/OCAF_Selection_and_CAE_Binding_Contract_v1.md
6. 测试证据目录及原始输出
7. capture-off 几何回归报告
8. 性能基准报告
9. 已知限制与后续任务
```

最后一次 Agent 回复必须逐条对应 Definition of Done，标注：

- PASS；
- FAIL；
- NOT IMPLEMENTED；
- BLOCKED。

不得用自然语言总评掩盖未通过项。

---

## 21. 推荐的第一轮具体修改清单

代码 Agent 第一轮只做 PR-0 和 PR-1，不要立即改 tracked ops：

```text
修改：
- generative_cad/topology/ocaf/compat.py
- generative_cad/topology/ocaf/document.py（重写或兼容废弃）

新增：
- generative_cad/topology/ocaf/schema.py
- generative_cad/topology/ocaf/label_index.py
- generative_cad/topology/ocaf/repository.py
- generative_cad/topology/ocaf/errors.py
- tests/topology/ocaf/smoke/
- tests/topology/ocaf/test_utf8_path.py
- tests/topology/ocaf/test_fixed_schema.py
- tests/topology/ocaf/test_atomic_publish.py
- tests/topology/ocaf/test_subprocess_retrieve.py
```

第一轮必须先证明：

```text
创建固定 Tag 100
→ 写入 Name/Integer/NamedShape/Naming
→ 中文临时路径 SaveAs
→ 进程退出
→ Retrieve
→ 固定 TagPath 找回所有内容
→ verifier 通过
→ 原子发布
```

第一轮未通过，不得进入 Live History 重构。

---

## 22. 最终技术路线定性

本系统应采用：

> **OCAF/XBF 作为持久设计与拓扑身份主文档，TNaming Builder History 作为身份演化权威，稳定业务 ID 与稳定 Label 作为工程对象锚点，Semantic Contract 作为后验约束，几何指纹仅作为诊断候选；由单 Revision 事务和独立进程原子验证保证发布一致性。**

无需建立另一套替代 OCAF 的 JSON 拓扑数据库，也无需重写 BinMNaming 驱动。真正的实现重点是：让 Text-to-CAD 的每次确定性 Builder 执行产生可证明的真实 topology history，并将其写入跨 Revision 不变的 Label 结构。

这条路线完成后，系统才具备从“生成三维模型”升级为“能够持续修改、保持边界条件与工程语义身份的 CAD/CAE 设计系统”的基础。
