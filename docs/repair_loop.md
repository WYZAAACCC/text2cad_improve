# Text2CAD / G-CAD Repair Loop 实现指导文档

## 0. 文档目的

本文用于指导代码 Agent 在 `WYZAAACCC/text2cad_improve` 中实现一套安全、可控、可审计的 Repair Loop。

目标流程：

```text
LLM Authoring
  → Raw G-CAD IR
  → Validation
      → Deterministic AutoFix
      → Validation Repair Agent
      → Re-validation
  → Canonicalization
  → Runtime
      → Runtime Repair Agent
      → 回到完整 Validation / Canonicalization / Runtime
  → Artifact / Failure
```

Repair Loop 应满足：

* 默认开启；
* 可以整体关闭；
* validation repair 与 runtime repair 可以分别关闭；
* AutoFix 可以单独关闭；
* 有全局和分阶段尝试次数上限；
* 修复必须是局部、事务式、可回滚的；
* 不允许通过弱化安全条件或跳过必要特征来“修复成功”；
* 不允许错误放大、设计意图漂移和无限循环；
* runtime 修复后必须重新经过完整 validation 和 canonicalization；
* 所有尝试必须可审计、可重放。

Repair Loop 的目标不是让所有输入最终通过，而是：

> 在错误能够被局部、可证明且安全地修复时自动修复；否则携带完整证据停止。

---

# 1. 当前代码现状

仓库已经具备 Repair Loop 的若干基础构件：

* `authoring/pipeline.py` 已包含 validation、AutoFix 和 LLM patch repair 的初步串联；
* `auto_fixer.py` 已强调确定性、幂等性和设计意图保持；
* `repair/patch.py` 已定义局部 Patch 与深拷贝应用机制；
* `repair/governor.py` 已包含尝试次数、重复错误、重复补丁和阶段进度等治理概念；
* validation 已提供 `ValidationIssue`、`ValidationReport` 和 `ValidationBundle`；
* runtime 已收集 geometry health、operation metrics、postcondition、inspection 等结构化信息。

但是，现有机制还不能直接扩展成可靠的 validation/runtime 双 Repair Loop。必须先解决下面的状态一致性问题。

## 1.1 AutoFix 文档与诊断报告可能错位

现有流程可能：

1. 对 `fixed_doc` 重新 validation；
2. 把新的 validation report 保存为当前 report；
3. 但后续 LLM repair 仍基于原始 Raw 文档生成 Patch。

这样 Repair Agent 看到的是“修复后文档的错误”，实际修改的却是“修复前文档”。

必须保证下面三个对象始终绑定在同一个不可拆分的状态快照中：

```text
current_raw_document
current_validation_report
current_validation_bundle
```

不得将一个文档与另一个文档产生的诊断混用。

## 1.2 LLM 修复后的 Raw 文档没有稳定回写

LLM repair 成功后，修复后的文档必须：

```text
成为唯一 current_raw_document
→ 写回 raw_assembly.raw_document
→ 被上层 build pipeline 使用
→ 被保存到证据链
```

不能只更新 canonical document 或 validation bundle，而让上层重新取得旧 Raw IR。现有 authoring 与 build pipeline 的责任重叠，使这个问题更容易发生。

## 1.3 RepairState 可能记录补丁前状态

每次 Patch 应用并重新验证后，RepairState 必须记录候选结果：

* 候选文档 hash；
* 候选错误签名；
* 候选失败阶段；
* 当前 Patch hash；
* 候选进度评分；
* 候选是否被接受。

不得继续记录 Patch 前的 raw hash、错误签名或 stage rank。

## 1.4 内外两层重复编排

`generate_gcad_from_user_request` 与 `generate_validate_build_step` 当前都有 validation、AutoFix 或 repair 责任。双层编排会导致：

* `allow_autofix=False` 不能在所有层一致生效；
* 尝试次数被重复计算；
* 修复结果在层间丢失；
* 同一文档被重复验证；
* 最终错误报告难以解释；
* repair budget 无法统一。

最终必须只有一个 Repair Loop 编排权威。

## 1.5 早期 validation 失败缺少完整 repair hints

validation 管线包括 structure、registry、params、ownership、graph、typecheck、phase、composition、hole semantics、safety、dialect semantics 和 geometry preflight 等阶段，但 repair hints 的生成需要覆盖所有失败出口，不能只在较后的 canonical 阶段形成。

## 1.6 Runtime 诊断被过度压平

Runtime 当前实际上掌握：

* failing node；
* operation；
* geometry health；
* body count；
* closed/valid B-Rep 状态；
* bbox、volume；
* operation metrics；
* runtime postconditions；
* final geometry postcheck；
* inspection report。

但 `GcadRunResult` 的主要错误接口仍是 `error: str | None`，多个失败出口把结构化证据转换成字符串，最外层异常捕获还会将 traceback 尾部拼接到字符串中。

Runtime Repair Loop 实施前，必须先建立结构化 RuntimeReport。

---

# 2. 总体设计原则

## 2.1 单一状态所有者

新增：

```text
generative_cad/repair/orchestrator.py
```

其中的 `RepairOrchestrator` 是完整流程中唯一有权替换 `current_raw_document` 的组件。

其他组件保持纯粹：

### Validator

* 输入 Raw 文档；
* 返回 validation report、bundle、canonical document；
* 不调用 LLM；
* 不自行重试；
* 不隐式修改输入。

### AutoFix

* 输入文档和结构化错误；
* 返回候选文档和完整修改报告；
* 不决定候选是否被采用。

### Runtime

* 输入已经验证的 Canonical IR；
* 返回 artifact 或结构化 RuntimeReport；
* 不调用 Repair Agent；
* 不自行修改 IR。

### Repair Agent

* 输入受控 RepairRequest；
* 只返回局部 Patch；
* 不直接写文件；
* 不直接执行 CAD；
* 不直接修改 Canonical IR。

### RepairOrchestrator

负责：

* 当前 Raw IR；
* 尝试次数；
* AutoFix；
* Agent 调用；
* Patch 应用；
* validation/runtime 重试；
* 进度比较；
* 回滚；
* 停止条件；
* 审计记录。

## 2.2 Repair Agent 只能修改 Raw IR

Repair Agent 不允许直接修改：

* Canonical IR；
* CadQuery runtime object；
* STEP；
* metadata；
* runtime context；
* validation report；
* geometry health report。

即使错误发生在 runtime，Repair Agent 也必须输出针对 Raw IR 的 Patch。

Runtime repair 后必须执行：

```text
Patched Raw IR
  → Pydantic Parse
  → Raw Validation
  → Canonicalization
  → Canonical Validation
  → Runtime
```

禁止使用旧 Canonical IR 直接重试 runtime。

原因是 Runtime Patch 可能改变：

* 参数；
* 引用；
* body ownership；
* 输入输出类型；
* geometry preflight；
* canonical hash；
* dialect postconditions。

旧 Canonical IR 已经失效。

## 2.3 Deterministic AutoFix 优先

固定顺序：

```text
初始 Validation
  → Deterministic AutoFix
  → 再 Validation
  → Validation Repair Agent
```

只有 AutoFix 无法使文档通过，且错误被分类为 repairable，才调用 LLM。

AutoFix 与 LLM repair 必须分别计数和记录。

## 2.4 Fail-Closed

以下情况必须停止，禁止让 Agent 猜测：

* 基础设施或环境错误；
* dialect handler 实现缺陷；
* operation contract 自相矛盾；
* 缺少必要上下文；
* 修复需要改变核心设计意图；
* 需要新增未知节点；
* 需要切换 dialect 或 operation；
* 尝试次数耗尽；
* 候选状态没有进步；
* 错误严重性增加；
* Agent 返回 `give_up`；
* 安全约束会被削弱。

---

# 3. 推荐状态机

```text
AUTHOR_RAW
    |
    v
VALIDATE_RAW
    |
    +-- success -------------------------------+
    |                                         |
    v                                         v
AUTO_FIX                                   CANONICALIZE
    |                                         |
    v                                         v
VALIDATE_AUTOFIXED                       VALIDATE_CANONICAL
    |                                         |
    +-- success -------------------------------+
    |
    +-- repair disabled --------------------> FAIL
    |
    +-- non-repairable ---------------------> FAIL
    |
    v
VALIDATION_REPAIR_AGENT
    |
    v
APPLY_PATCH_TRANSACTIONALLY
    |
    v
VALIDATE_RAW  <-------------------------------+
                                                  |
                                                  v
                                                RUNTIME
                                                  |
                         +------------------------+-----------------+
                         |                                          |
                      success                                runtime failure
                         |                                          |
                         v                                          v
                      ARTIFACT                        CLASSIFY_RUNTIME_FAILURE
                                                                    |
                              +-------------------------------------+----------+
                              |                                                |
                       non-repairable                                     repairable
                              |                                                |
                              v                                                v
                            FAIL                                  RUNTIME_REPAIR_AGENT
                                                                               |
                                                                               v
                                                                   APPLY_RAW_PATCH
                                                                               |
                                                                               v
                                                                     VALIDATE_RAW
```

Runtime repair 后回到完整 validation 是强制约束。

---

# 4. 配置模型

建议新增：

```python
class RepairLoopConfig(BaseModel):
    enabled: bool = True

    validation_repair_enabled: bool = True
    runtime_repair_enabled: bool = True
    deterministic_autofix_enabled: bool = True

    max_total_llm_attempts: int = 4
    max_validation_llm_attempts: int = 3
    max_runtime_llm_attempts: int = 2

    max_changes_per_patch: int = 4
    max_same_error_occurrences: int = 2
    max_no_progress_attempts: int = 1

    allow_wiring_repair: bool = False
    allow_optional_degradation_change: bool = False
    allow_structural_repair: bool = False

    require_strict_progress: bool = True
    rollback_on_regression: bool = True

    max_relative_numeric_change: float = 0.25
    max_absolute_patch_bytes: int = 16_384
```

## 4.1 开关语义

### `enabled=False`

* 禁止所有 LLM repair；
* 是否允许 AutoFix 由 `deterministic_autofix_enabled` 单独决定；
* 不调用任何 Repair Agent。

### `enabled=True`，但无 repair caller

* 可以继续 deterministic AutoFix；
* 不调用 LLM；
* 最终状态明确标记为：

```text
repair_unavailable
```

不得在报告中声称 LLM repair 已启用。

### 推荐 CLI 参数

```text
--no-repair
--no-validation-repair
--no-runtime-repair
--no-autofix
--max-repair-attempts N
--max-runtime-repair-attempts N
```

所有入口必须使用同一个 `RepairLoopConfig`，不能由不同 pipeline 分别维护默认值。

---

# 5. 统一诊断模型

## 5.1 RepairIssue

建议将 validation 和 runtime 错误统一转换成：

```python
class RepairIssue(BaseModel):
    source: Literal["validation", "runtime"]
    stage: str
    code: str
    severity: Literal["info", "warning", "error", "fatal"]

    message: str

    node_id: str | None = None
    component_id: str | None = None
    dialect: str | None = None
    operation: str | None = None
    operation_version: str | None = None

    path: str | None = None
    expected: Any | None = None
    actual: Any | None = None

    exception_type: str | None = None
    cause_chain: list[str] = []

    repairability: Literal[
        "repairable",
        "conditionally_repairable",
        "non_repairable",
        "unknown",
    ]

    suggested_paths: list[str] = []
    evidence: dict[str, Any] = {}
```

现有 `ValidationIssue` 已经包含 code、message、severity、stage、node ID、component ID、path、expected 和 actual，可通过转换函数接入统一模型。

## 5.2 RuntimeReport

扩展 `GcadRunResult`：

```python
class RuntimeReport(BaseModel):
    ok: bool
    failed_stage: str | None = None
    issues: list[RepairIssue] = []

    failing_node_id: str | None = None
    failing_component_id: str | None = None
    failing_operation: str | None = None

    geometry_health: list[dict[str, Any]] = []
    operation_metrics: list[dict[str, Any]] = []
    runtime_postconditions: list[dict[str, Any]] = []

    geometry_postcheck: dict[str, Any] | None = None
    inspection_report: dict[str, Any] | None = None

    sanitized_traceback: list[str] = []
```

```python
class GcadRunResult(BaseModel):
    ok: bool
    ...
    runtime_report: RuntimeReport | None = None

    # 兼容旧调用者，只保留短摘要
    error: str | None = None
```

## 5.3 Typed Runtime Exception

新增：

```python
class GcadRuntimeError(RuntimeError):
    def __init__(
        self,
        issue: RepairIssue,
        *,
        node_snapshot: dict | None = None,
        input_snapshot: dict | None = None,
        geometry_health: dict | None = None,
    ):
        ...
```

`dialects/executor.py`、`runtime/recovery.py` 和 handler 应优先抛出 typed exception。

例如：

```python
raise GcadRuntimeError(
    RepairIssue(
        source="runtime",
        stage="operation_execution",
        code="FILLET_RADIUS_TOO_LARGE",
        severity="error",
        node_id=node.id,
        component_id=node.component_id,
        dialect=node.dialect,
        operation=node.operation,
        operation_version=node.operation_version,
        path=f"/nodes/{node_index}/params/radius",
        expected={"maximum_estimated_radius": max_radius},
        actual={"radius": params.radius},
        repairability="repairable",
        suggested_paths=[
            f"/nodes/{node_index}/params/radius",
        ],
        message="Fillet operation failed because the requested radius "
                "is larger than the local edge geometry permits.",
    ),
    node_snapshot=node.model_dump(mode="json"),
    geometry_health=health.model_dump(mode="json"),
)
```

最外层只负责归一化，不应把全部证据压缩为一个字符串。

---

# 6. Runtime 错误可修复性分类

Runtime Repair Agent 不应接收所有 runtime 错误。

## 6.1 通常可修复

只有错误能够明确关联到 Raw IR 参数时，才允许进入 runtime repair：

* fillet 半径超过局部几何允许值；
* chamfer 距离过大；
* shell thickness 导致壳化失败；
* hole 直径、深度或位置导致布尔失败；
* boolean tool 与 target 不相交；
* loft profile 数量、顺序或尺度导致退化；
* sweep path 与 profile 关系不合法；
* 某个节点产生非闭合或零体积几何；
* operation 后置条件因局部参数错误而失败；
* 某个必要特征的输入几何明确为空。

## 6.2 条件可修复

需要更严格策略：

* 输入引用连接错误；
* component root 指向错误；
* body count 与预期不符；
* optional feature 导致最终实体不健康；
* 某一布尔操作使用了错误但类型兼容的 body。

这些默认不开启 wiring repair。

只有同时满足以下条件才允许：

1. validator 或 runtime 能给出唯一候选；
2. 修改路径明确；
3. 不需要新增或删除节点；
4. 不改变 operation/dialect；
5. 重新 validation 能完整检查修改。

## 6.3 不可通过 IR Repair 解决

以下错误不得发送给 LLM 修改设计：

* CadQuery/OpenCASCADE 未安装；
* 软件版本不兼容；
* 文件权限或磁盘错误；
* 路径不存在；
* OOM；
* 进程崩溃；
* 系统级超时；
* STEP exporter 不可用；
* handler 中的 `AttributeError`、`NameError` 等实现错误；
* operation registry 与 handler 实现不一致；
* dialect contract hash 不一致；
* metadata writer 代码错误；
* artifact hash 代码错误；
* 安全策略拒绝；
* 未知 dialect 或 operation；
* 无法证明错误与 Raw IR 参数之间存在因果关系。

此类错误应返回：

```text
infrastructure_failure
implementation_failure
contract_failure
security_failure
```

而不是消耗 repair budget。

---

# 7. Repair Agent 上下文包

信息不足是 Repair Agent 乱修的主要原因。

建议新增：

```python
class RepairRequestEnvelope(BaseModel):
    phase: Literal["validation", "runtime"]

    attempt_index: int
    max_attempts: int

    original_user_request: str

    current_raw_document: dict
    current_raw_hash: str

    route_plan: dict | None
    feature_sequence: dict | None

    issues: list[RepairIssue]
    primary_issue: RepairIssue
    related_issues: list[RepairIssue]

    failing_node: dict | None
    graph_neighborhood: dict
    component_snapshot: dict | None

    operation_contracts: list[dict]
    dialect_contracts: list[dict]
    raw_ir_schema_excerpt: dict
    patch_schema: dict

    allowed_paths: list[str]
    forbidden_paths: list[str]
    immutable_invariants: dict

    validation_report: dict | None
    validation_bundle: dict | None
    autofix_report: dict | None
    runtime_report: dict | None

    prior_attempts: list[dict]
    repair_hints: list[dict]
```

## 7.1 每次 Repair 必须提供

至少包括：

1. 原始用户请求；
2. 当前完整 Raw IR；
3. 当前文档 hash；
4. 完整结构化错误；
5. primary issue；
6. 相关联的其他 issue；
7. 报错节点完整内容；
8. 该节点 operation 的精确参数 schema；
9. 输入输出端口类型；
10. dialect 和 operation 版本；
11. 一跳上游和下游节点；
12. expected 与 actual；
13. 允许修改的精确路径；
14. 禁止修改的路径；
15. AutoFix 做过什么；
16. AutoFix 后错误如何变化；
17. 之前每个 Patch；
18. 每个 Patch 的验证结果；
19. 不可改变的设计意图；
20. 精确 RepairPatch schema。

现有主 Repair Prompt 主要接收当前文档、validation issues 和可选路径限制；实际调用中缺乏完整 operation contract、AutoFix diff、repair history、图邻域和明确的局部契约，因此需要由新的 Context Builder 扩充。

## 7.2 Runtime Repair 额外提供

* failing operation 的输入 handle 摘要；
* 输入几何 bbox；
* volume；
* body count；
* closed；
* valid B-Rep；
* operation 前后 geometry health；
* operation metrics；
* runtime postconditions；
* geometry postcheck；
* inspection report；
* 已清洗的异常类型；
* cause chain；
* 相关参数的约束范围；
* 上一个成功节点的健康摘要；
* 失败是否可稳定复现。

## 7.3 不要无脑倾倒全部上下文

上下文策略应为：

> 完整局部契约 + 有界全局背景。

具体要求：

* 提供完整 Raw IR；
* 提供全局安全与不可变约束；
* 只提供报错节点和相关节点的完整 operation contract；
* 只提供一跳邻域或必要的最短依赖路径；
* traceback 只保留清洗后的末端；
* 移除 secrets；
* 移除环境变量；
* 对用户目录和绝对路径脱敏；
* 设置最大上下文体积；
* 保存被裁剪字段列表。

---

# 8. Repair Agent 输出协议

不要让生产 Repair Agent 重新生成完整 `RawGcadDocument`。

仓库中已有完整文档式 LLM repair 路径，但完整重写容易引入无关修改和设计漂移。生产 Repair Loop 应统一采用局部 Patch。

建议升级为：

```python
class RepairChangeV3(BaseModel):
    op: Literal["replace", "add"]

    path: str

    old_value: Any
    new_value: Any

    issue_codes: list[str]

    reason: str
    expected_effect: str

    confidence: float


class RepairPatchV3(BaseModel):
    base_document_hash: str

    target_node_id: str | None = None
    target_component_id: str | None = None

    changes: list[RepairChangeV3] = []

    give_up: bool = False
    give_up_reason: str | None = None
```

## 8.1 强制规则

* `replace` 必须提供精确 `old_value`；
* `base_document_hash` 必须匹配当前状态；
* path 必须来自服务端生成的 allowed path 集合；
* `target_node_id` 必须与 path 指向节点一致；
* 一次 Patch 不超过 `max_changes_per_patch`；
* Patch 总大小不得超过配置上限；
* 默认禁止 `remove`；
* 禁止新增节点；
* 禁止删除节点；
* 禁止改变 operation；
* 禁止改变 dialect；
* 禁止改变 operation version；
* 禁止修改 schema version；
* 禁止修改 selected dialects；
* 禁止修改 safety；
* 默认禁止修改 required；
* 默认禁止修改 degradation policy；
* 默认禁止整体替换 inputs；
* 默认禁止整体替换 outputs。

输入引用修复必须使用精确子路径，例如：

```text
/nodes/3/inputs/profile/source_node_id
```

不能替换整个 `/nodes/3/inputs` 对象。

现有 Patch 机制允许的部分路径仍然过宽，例如完整 inputs/outputs，以及 `required`、`degradation_policy`；同时当前错误签名主要按错误 code 聚合，无法充分区分节点、路径和 expected/actual。两者都需要收紧。

## 8.2 动态 Tool Schema

不要将 `new_value` 长期保持为 `Any`。

应根据 failing operation 的 `OperationSpec` 动态生成 Tool Schema：

* path 使用 enum 或 const；
* 每个 path 的 `new_value` 使用对应参数 schema；
* 引用字段只允许合法 node/output；
* 数值字段保留 min/max；
* 枚举字段只允许 contract 中的值；
* 布尔字段严格为 boolean；
* 不允许额外字段。

如果当前错误只允许修改：

```text
/nodes/4/params/radius
```

Repair Agent 的工具 schema 中就不应出现其他 path。

---

# 9. Patch 必须事务式应用

建议固定过程：

```text
1. 校验 base_document_hash
2. 校验 Patch 字节大小
3. 校验 change 数量
4. 校验每个 path 的权限
5. 校验 target_node 与 path 一致
6. 校验 old_value
7. 在 deep copy 上应用全部 change
8. 生成 structural diff
9. 检查 immutable projection hash
10. 检查 design-intent budget
11. Pydantic parse
12. 完整 validation
13. 计算 progress
14. 只有进步才 commit
15. 否则整体 rollback
```

任意一步失败，整个 Patch 不得部分生效。

需要返回：

```python
class PatchApplyReport(BaseModel):
    ok: bool

    base_hash: str
    candidate_hash: str | None

    applied_changes: list[dict]
    rejected_changes: list[dict]

    protected_projection_unchanged: bool

    parse_ok: bool
    validation_ok: bool | None

    rejection_code: str | None
    rejection_reason: str | None
```

---

# 10. 防止设计意图漂移

## 10.1 Protected Projection

从初始 Raw IR 生成不可变投影：

```text
schema_version
units
selected_dialects
dialect versions
component identity
node identity
node dialect
node operation
node operation version
node ownership
required safety declarations
用户明确指定的关键尺寸
```

保存：

```text
protected_projection_hash
```

每次 Patch 后重新计算。默认必须完全一致。

## 10.2 用户明确尺寸

将用户请求中明确给出的尺寸和约束单独保存：

```python
class UserSpecifiedConstraint(BaseModel):
    semantic_name: str
    value: Any
    tolerance: Any | None
    source_span: str | None
    protected: bool = True
```

例如用户明确要求：

```text
中心孔直径 20 mm
```

Repair Agent 不应因为布尔失败直接改成 25 mm。

如果必须改变用户明确尺寸才能构建，应：

* `give_up`；
* 或返回“需要用户澄清”；
* 不得擅自修改。

## 10.3 数值修改预算

普通尺寸默认要求：

* 相对变化不超过 25%；
* 不改变正负号；
* 不从毫米级跳到完全不同数量级；
* 不改变单位；
* validator 给出合法范围时，可以使用明确范围；
* 修改必须与当前 issue 有直接关系。

可定义：

```python
relative_delta = abs(new - old) / max(abs(old), epsilon)
```

若超过阈值且无明确 expected range，则拒绝。

## 10.4 禁止通过降级掩盖失败

Repair Agent 不得将：

```text
required = true
```

改成：

```text
required = false
```

也不得把：

```text
degradation_policy = fail
```

改成跳过，以此让流程表面成功。

只有满足以下条件时，才可由确定性策略考虑降级：

* 特征明确标记为装饰性；
* 不影响主体拓扑；
* 不影响用户核心需求；
* 配置显式允许；
* 最终报告明确记录 degraded feature。

---

# 11. 进度判断与回滚

现有 stage rank 无法直接覆盖 runtime repair，因为 runtime Patch 后返回 validation 是预期行为，不应被视为阶段倒退。

需要以一次完整 Repair Cycle 的最终状态进行比较。

## 11.1 ProgressScore

```python
class ProgressScore(BaseModel):
    raw_parse_ok: bool

    validation_stage_rank: int
    validation_error_count: int
    validation_fatal_count: int

    canonical_created: bool
    canonical_validation_ok: bool

    runtime_reached: bool
    runtime_stage_rank: int
    runtime_error_count: int
    runtime_fatal_count: int

    geometry_health_score: float | None

    artifact_created: bool
```

## 11.2 比较优先级

按以下顺序判断候选是否改善：

1. 是否解析成功；
2. 是否通过更多 validation 阶段；
3. fatal 数量是否减少；
4. error 数量是否减少；
5. 是否成功 canonicalize；
6. 是否进入 runtime；
7. runtime 是否推进到更晚阶段；
8. runtime fatal/error 是否减少；
9. geometry health 是否提高；
10. 是否生成最终 artifact。

## 11.3 候选采用规则

候选只有同时满足以下条件才可提交：

* Raw IR 解析成功；
* protected invariants 未改变；
* 没有新增更高严重级别错误；
* ProgressScore 严格改善，或者失败点推进到更晚阶段；
* 没有超过数值修改预算；
* 没有出现已访问过的文档 fingerprint。

否则：

```text
rollback to best-known Raw IR
```

不能因为 Agent 输出了合法 JSON 就自动采用。

## 11.4 Best-known 状态

RepairSessionState 应保存：

```python
current_raw
best_raw

current_snapshot
best_snapshot

accepted_attempts
rejected_attempts
```

当候选退化时：

* 当前状态不变；
* 候选进入 rejected audit；
* attempt budget 仍然消耗；
* 后续 Agent 看到该失败尝试及拒绝原因。

## 11.5 更强的错误签名

错误签名至少包含：

```text
source
stage
code
node_id
component_id
path
normalized expected
normalized actual
exception_type
```

排序后稳定 hash。

不能只使用唯一错误 code，因为：

```text
PARAM_OUT_OF_RANGE at node_a /radius
```

和：

```text
PARAM_OUT_OF_RANGE at node_b /depth
```

不是同一个错误状态。

---

# 12. 循环停止条件

满足任一条件立即停止：

* 达到全局 LLM 尝试上限；
* 达到 validation 尝试上限；
* 达到 runtime 尝试上限；
* 同一错误签名重复达到阈值；
* 同一 Raw 文档 hash 再次出现；
* 同一 Patch hash 再次出现；
* 连续无进展；
* 错误严重性增加；
* fatal issue 数量增加；
* 违反 protected projection；
* 超过数值修改预算；
* Patch 应用失败；
* Agent 返回 `give_up`；
* 错误为 non-repairable；
* token budget 耗尽；
* 时间预算耗尽；
* 成本预算耗尽。

建议停止结果：

```python
class RepairStopDecision(BaseModel):
    should_stop: bool
    code: str
    reason: str

    phase: Literal["validation", "runtime"]

    attempts_total: int
    attempts_in_phase: int

    best_raw_hash: str
    last_raw_hash: str

    repeated_error_signature: str | None
    repeated_patch_hash: str | None
```

---

# 13. Validation Repair Agent 与 Runtime Repair Agent 分离

应当使用两个 Agent 角色，而不是一个万能 Repair Agent。

## 13.1 ValidationRepairAgent

主要理解：

* Raw schema；
* graph；
* ownership；
* type system；
* phase；
* operation params；
* dialect semantics；
* geometry preflight；
* canonicalization 前置条件。

默认允许修改：

* failing node 的 params；
* validator 明确允许的精确输入引用；
* validator 明确允许的 component root；
  -非语义性的 validation hint。

## 13.2 RuntimeRepairAgent

主要理解：

* 实际 B-Rep 构建错误；
* CadQuery/OpenCASCADE 操作失败；
* boolean、fillet、chamfer、shell、loft、sweep 几何约束；
* geometry health；
* operation inputs/outputs；
* runtime postconditions；
* final geometry postcheck。

默认只允许修改：

* 与 failing operation 直接相关的参数；
* 少量由证据明确关联的上游参数。

默认不允许 graph wiring repair。

两个 Agent 可以共享同一个底层 LLM caller，但必须使用：

* 不同 system prompt；
* 不同 context builder；
* 不同 path policy；
* 不同 repairability classifier；
* 不同 metrics。

---

# 14. Prompt 规范

## 14.1 System Prompt

建议固定核心内容：

```text
你是受约束的 G-CAD IR Repair Agent。

你只能输出 RepairPatchV3。
你不得重新生成完整 RawGcadDocument。
你不得重新设计零件。
你不得修改任何禁止字段。
你不得修改与当前错误无关的节点。
你不得通过降低 required、安全性或 geometry postcondition 使流程通过。

每个修改必须：
1. 指向 allowed_paths 中的精确路径；
2. 使用当前文档中的精确 old_value；
3. 引用所解决的 issue code；
4. 说明修改与错误之间的直接因果关系；
5. 描述预期修复效果。

优先使用最少修改。

如果：
- 信息不足；
- 错误不是 IR 参数问题；
- 修复需要改变用户核心设计意图；
- 无法在允许路径内安全修复；
则必须返回 give_up=true。
```

## 14.2 User Prompt 固定章节

1. Repair objective；
2. Repair phase；
3. attempt index；
4. 原始用户意图；
5. primary issue；
6. related issues；
7. failing node；
8. local graph；
9. operation contract；
10. dialect contract；
11. expected 与 actual；
12. AutoFix 修改及结果；
13. runtime evidence；
14. previous attempts；
15. allowed paths；
16. forbidden paths；
17. immutable invariants；
18. 当前完整 Raw IR；
19. RepairPatchV3 schema。

Agent 不应只看到：

```text
Fillet failed, please fix.
```

而应看到：

```json
{
  "code": "FILLET_RADIUS_TOO_LARGE",
  "node_id": "edge_fillet_1",
  "path": "/nodes/6/params/radius",
  "expected": {
    "estimated_maximum": 1.8
  },
  "actual": {
    "radius": 4.0
  },
  "geometry_health": {
    "input_closed": true,
    "input_valid_brep": true,
    "input_body_count": 1
  },
  "allowed_paths": [
    "/nodes/6/params/radius"
  ],
  "parameter_schema": {
    "type": "number",
    "exclusiveMinimum": 0
  }
}
```

---

# 15. 推荐代码结构

## 15.1 新增文件

```text
generative_cad/repair/config.py
generative_cad/repair/models.py
generative_cad/repair/orchestrator.py
generative_cad/repair/context_builder.py
generative_cad/repair/classifier.py
generative_cad/repair/progress.py

generative_cad/runtime/diagnostics.py
generative_cad/runtime/errors.py
```

## 15.2 修改文件

```text
authoring/pipeline.py
authoring/build_pipeline.py
authoring/prompt_builders.py
authoring/tool_schemas.py

repair/patch.py
repair/governor.py
repair/hashes.py

validation/pipeline.py
validation/models.py
validation/repair_hints.py

runtime/results.py
runtime/recovery.py
runtime/context.py

dialects/executor.py
pipeline/run.py

authoring/failures.py
authoring/metrics.py
```

## 15.3 职责调整

### `authoring/pipeline.py`

建议只负责：

```text
用户请求
→ Route
→ Feature Sequence
→ Node Params
→ Raw IR Assembly
```

不要继续拥有独立 Repair Loop。

如果为了兼容必须保留原接口，应立即委托统一 Orchestrator，不能保留另一套 repair 状态机。

### `authoring/build_pipeline.py`

作为产品级入口：

```text
Authoring
→ RepairOrchestrator
→ Artifact
```

不再自行重复 validation 或 AutoFix。

### `validation/pipeline.py`

* 保持纯验证；
* 每个失败出口都形成完整 `ValidationBundle`；
* 所有阶段都生成 typed repair hints；
* 不调用 Agent；
* 不做循环。

### `pipeline/run.py`

* 保持纯 runtime；
* 返回结构化 RuntimeReport；
* 不调用 Agent；
* 不循环；
* 不修改 Raw IR。

### `repair/orchestrator.py`

统一负责：

* validation loop；
* runtime loop；
* global budget；
* state；
* rollback；
* audit；
* metrics。

---

# 16. 核心伪代码

```python
def generate_validate_build_step(
    *,
    user_request: str,
    authoring_caller,
    validation_repair_caller=None,
    runtime_repair_caller=None,
    repair_config: RepairLoopConfig | None = None,
    ...
):
    config = repair_config or RepairLoopConfig()

    initial_raw = author_raw_document(
        user_request=user_request,
        caller=authoring_caller,
    )

    state = RepairSessionState.from_initial(
        user_request=user_request,
        raw_document=initial_raw,
        config=config,
    )

    while True:
        validation = validate_document(state.current_raw)

        state.observe_validation(validation)

        if not validation.ok:
            if config.deterministic_autofix_enabled:
                fixed = auto_fix(
                    document=state.current_raw,
                    validation_report=validation.report,
                    validation_bundle=validation.bundle,
                )

                fixed_validation = validate_document(fixed.document)

                candidate = RepairCandidate(
                    raw_document=fixed.document,
                    validation=fixed_validation,
                    source="deterministic_autofix",
                    autofix_report=fixed.report,
                )

                if state.should_accept(candidate):
                    state.commit(candidate)
                    validation = fixed_validation
                else:
                    state.reject(candidate)

            if not validation.ok:
                decision = state.governor.decide_validation_repair(
                    validation=validation,
                )

                if not decision.allow:
                    return build_failure_result(
                        state=state,
                        stop_decision=decision,
                    )

                if validation_repair_caller is None:
                    return build_failure_result(
                        state=state,
                        stop_code="repair_unavailable",
                    )

                request = context_builder.for_validation(
                    state=state,
                    validation=validation,
                )

                patch = validation_repair_agent.call(
                    caller=validation_repair_caller,
                    request=request,
                )

                if patch.give_up:
                    return build_failure_result(
                        state=state,
                        stop_code="agent_give_up",
                        stop_reason=patch.give_up_reason,
                    )

                apply_result = patch_applier.apply_transactionally(
                    document=state.current_raw,
                    patch=patch,
                    policy=validation_patch_policy,
                )

                if not apply_result.ok:
                    state.record_rejected_patch(
                        patch=patch,
                        apply_result=apply_result,
                    )
                    continue

                candidate_validation = validate_document(
                    apply_result.document,
                )

                candidate = RepairCandidate(
                    raw_document=apply_result.document,
                    validation=candidate_validation,
                    source="validation_llm_repair",
                    patch=patch,
                    apply_report=apply_result.report,
                )

                if not state.should_accept(candidate):
                    state.reject(candidate)
                    continue

                state.commit(candidate)
                continue

        canonical = validation.canonical_document

        runtime = run_canonical_gcad(
            canonical_document=canonical,
            ...
        )

        state.observe_runtime(runtime)

        if runtime.ok:
            return build_success_result(
                state=state,
                runtime=runtime,
            )

        decision = state.governor.decide_runtime_repair(
            runtime_report=runtime.runtime_report,
        )

        if not decision.allow:
            return build_failure_result(
                state=state,
                stop_decision=decision,
            )

        if runtime_repair_caller is None:
            return build_failure_result(
                state=state,
                stop_code="runtime_repair_unavailable",
            )

        request = context_builder.for_runtime(
            state=state,
            canonical_document=canonical,
            runtime_report=runtime.runtime_report,
        )

        patch = runtime_repair_agent.call(
            caller=runtime_repair_caller,
            request=request,
        )

        if patch.give_up:
            return build_failure_result(
                state=state,
                stop_code="runtime_agent_give_up",
                stop_reason=patch.give_up_reason,
            )

        apply_result = patch_applier.apply_transactionally(
            document=state.current_raw,
            patch=patch,
            policy=runtime_patch_policy,
        )

        if not apply_result.ok:
            state.record_rejected_patch(
                patch=patch,
                apply_result=apply_result,
            )
            continue

        # 必须重新进行完整 validation，不能直接重跑 runtime。
        candidate_validation = validate_document(
            apply_result.document,
        )

        candidate = RepairCandidate(
            raw_document=apply_result.document,
            validation=candidate_validation,
            source="runtime_llm_repair",
            patch=patch,
            apply_report=apply_result.report,
        )

        if not state.should_accept(candidate):
            state.reject(candidate)
            continue

        state.commit(candidate)

        # 返回 while 顶部，再次完成：
        # validation → canonicalization → runtime
```

实际实现可以缓存本轮已经得到的 validation 结果，避免重复计算，但不能改变上述语义边界。

---

# 17. 审计与可重现性

每次 Repair 尝试保存：

```text
repair/
  validation/
    attempt_01/
      request.json
      prompt.txt
      response.json
      patch.json
      apply_report.json
      candidate_raw.json
      validation_report.json
      validation_bundle.json
      progress.json

  runtime/
    attempt_01/
      request.json
      prompt.txt
      response.json
      patch.json
      apply_report.json
      candidate_raw.json
      runtime_report.json
      validation_after_patch.json
      progress.json
```

最终生成：

```text
repair_summary.json
```

至少包含：

* RepairLoopConfig；
* repair 是否有效启用；
* AutoFix 次数；
* validation LLM 次数；
* runtime LLM 次数；
* 每次 raw hash；
* 每次 error signature；
* 每次 Patch hash；
* accepted/rejected；
* 拒绝原因；
* stop reason；
* best-known document hash；
* 最终成功阶段；
* LLM token；
* LLM cost；
* latency；
* 脱敏状态。

---

# 18. Metrics

当前单一 `repair_attempts` 指标不够。建议拆分：

```python
class RepairMetrics(BaseModel):
    autofix_attempts: int = 0
    autofix_accepted: int = 0

    validation_llm_attempts: int = 0
    validation_llm_accepted: int = 0
    validation_llm_rejected: int = 0

    runtime_llm_attempts: int = 0
    runtime_llm_accepted: int = 0
    runtime_llm_rejected: int = 0

    repeated_error_stops: int = 0
    repeated_patch_stops: int = 0
    no_progress_stops: int = 0
    regression_rollbacks: int = 0
    non_repairable_stops: int = 0
    give_up_stops: int = 0

    total_tokens: int = 0
    total_cost: float = 0.0
    total_latency_ms: int = 0
```

仓库当前 authoring metrics 对 repair 的表达较粗，应在新 orchestrator 中统一升级。

---

# 19. 必须新增的测试

## 19.1 配置和控制流

1. 默认 Repair Loop 开启；
2. `enabled=False` 时绝不调用 Agent；
3. 无 caller 时只执行 AutoFix；
4. 无 caller 时返回 `repair_unavailable`；
5. `deterministic_autofix_enabled=False` 在所有入口一致生效；
6. validation/runtime 开关可以独立关闭；
7. 全局预算覆盖两个 Agent。

## 19.2 状态一致性

8. AutoFix 后 report 与 fixed document 始终匹配；
9. LLM 修复后写回 `raw_assembly.raw_document`；
10. build pipeline 使用修复后的 Raw IR；
11. RepairState 记录候选 hash；
12. RepairState 记录候选错误签名；
13. validation bundle 与文档 hash 一一对应；
14. 内外层不会重复 repair。

## 19.3 Patch 安全

15. stale `base_document_hash` 被拒绝；
16. `old_value` 不匹配时整体回滚；
17. 禁止字段不能修改；
18. operation/dialect/version 不能修改；
19. required/degradation 不能被用于掩盖错误；
20. change 数量受限；
21. Patch 字节大小受限；
22. target node 与 path 不一致时拒绝；
23. protected projection 改变时拒绝；
24. 数值变化超预算时拒绝；
25. Patch 不能部分应用。

## 19.4 循环治理

26. 相同 error signature 达到阈值即停止；
27. 相同 Raw hash 重复即停止；
28. 相同 Patch hash 重复即停止；
29. 连续无进展时停止；
30. fatal 数量上升时回滚；
31. 错误严重性增加时回滚；
32. Agent `give_up` 时停止；
33. validation phase 上限有效；
34. runtime phase 上限有效；
35. global 上限有效；
36. rejected Patch 同样消耗预算。

## 19.5 Runtime repair

37. fillet 参数错误可以进入 Runtime Repair；
38. boolean 不相交可以在证据充分时进入 Repair；
39. runtime Patch 后完整重跑 validation；
40. runtime Patch 引入 validation 错误时不能进入 runtime；
41. runtime Patch 后旧 Canonical IR 不得复用；
42. 基础设施错误不得调用 Agent；
43. handler 代码错误不得修改 IR；
44. geometry health 进入 Runtime Repair 请求；
45. operation metrics 进入 Runtime Repair 请求；
46. runtime repair 成功后生成 artifact；
47. runtime→validation 的回跳不被错误判断为 stage regression。

## 19.6 审计

48. 每次尝试产生完整审计文件；
49. accepted 与 rejected 都被记录；
50. prompt 中 secrets 被脱敏；
51. prompt 中用户绝对路径被脱敏；
52. 相同输入的 deterministic AutoFix 产生相同 hash；
53. Repair Summary 能完整解释停止原因。

仓库已经有 Patch、Governor 和部分 Repair Loop 治理测试，但需要补充上述端到端编排、runtime repair、状态回写和回滚测试。

---

# 20. 推荐实施顺序

## Phase 0：修复现有状态错误

必须首先完成：

* 统一 `current_raw_document`；
* 修复 fixed_doc/report 错位；
* 修复 repaired Raw IR 不回写；
* 修复 RepairState 使用旧 hash/error signature；
* 去除内外层重复编排；
* 统一 AutoFix 开关；
* 确保每个 validation bundle 带对应 raw hash。

Phase 0 未完成前，不应直接实现 runtime repair。

## Phase 1：可靠的 Validation Repair Loop

实施：

* `RepairLoopConfig`；
* `RepairSessionState`；
* `RepairRequestEnvelope`；
* `RepairPatchV3`；
* protected projection；
* transaction patch；
* progress comparison；
* rollback；
* 所有 validation 阶段 repair hints；
* 端到端测试。

## Phase 2：结构化 Runtime Diagnostics

实施：

* `RuntimeReport`；
* `RepairIssue`；
* typed runtime exception；
* executor 结构化错误；
* geometry health 归一化；
* postcheck 归一化；
* inspection 归一化；
* runtime repairability classifier；
* 保留旧 `error: str` 兼容摘要。

## Phase 3：Runtime Repair Loop

实施：

* 独立 RuntimeRepairAgent；
* runtime context builder；
* 更严格的 runtime patch policy；
* runtime Patch 后完整 validation；
* 与 validation loop 共享 global governor；
* runtime 端到端测试。

## Phase 4：工程强化

实施：

* 动态 Patch Tool Schema；
* token/time/cost budget；
* audit artifacts；
* replay 工具；
* telemetry；
* benchmark corpus；
* 错误分类统计；
* Repair 成功率与回归分析。

---

# 21. Definition of Done

只有同时满足以下条件，Repair Loop 才算完成：

* 只有一个 Orchestrator 管理 repair 状态；
* 默认开启；
* 可以明确关闭；
* AutoFix、validation repair、runtime repair 可分别控制；
* validation 和 runtime 均返回结构化错误；
* Repair Agent 获得充分且聚焦的上下文；
* Agent 只能输出受限局部 Patch；
* Patch 事务式应用；
* stale Patch 会被拒绝；
* 核心设计意图不可改变；
* 安全约束不可削弱；
* required feature 不可被偷偷降级；
* runtime Patch 必须重新经过完整 validation/canonicalization；
* 全局及分阶段次数上限有效；
* 重复、无进展和错误放大能够停止；
* 候选退化时自动回滚；
* 基础设施与代码缺陷不会被交给 Agent 修改 IR；
* 修复后的 Raw IR 能稳定传递到最终 build；
* 每次尝试可审计、可重放；
* 关键路径有端到端测试。

---

# 22. 给代码 Agent 的最终约束

实现优先级必须是：

```text
状态一致性
> Fail-Closed
> 设计意图保持
> 可审计性
> 最小补丁
> 自动修复成功率
```

不要为了提高自动通过率而放宽：

* required feature；
* safety declaration；
* geometry validity；
* closed solid 要求；
* runtime postcondition；
* inspection validation；
* artifact consistency。

最终原则：

> Repair Agent 不是新的设计 Agent，也不是重新生成 Agent。它是一个只能在证据充分、修改范围明确、影响可验证的情况下，提交最小事务式补丁的受限编译修复器。
