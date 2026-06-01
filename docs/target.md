
---

# 1. 顶级系统的第一原则

## 1.1 LLM 永远不是 CAD kernel

LLM 只能是：

```text
受约束 CAD Grammar 的源码作者
```

它不能是：

```text
CadQuery 程序员
SolidWorks COM 作者
NXOpen 作者
APDL 作者
STEP exporter 控制者
验证裁判
安全策略决定者
```

这点是你的方向里最正确、最有价值的一点。你的原始架构基线已经明确：目标不是让 LLM 直接写任意 CadQuery / SolidWorks / NX / APDL 代码，也不是把 Primitive 改成 LLM 生成，而是在确定性 Primitive 和完全自由代码生成之间，建立独立的 `LLM-Skill-Base / Generative CAD-IR Path`。

顶级框架必须坚持：

```text
LLM 输出 Raw G-CAD source；
系统负责 parse、validate、canonicalize、execute、inspect、prove、gate。
```

一旦系统允许 LLM 控制路径、文件、导出、subprocess、CAD API、runtime 参数、安全标志、验证结果，这个系统就不再是编译器，而是危险脚本执行器。

---

## 1.2 Primitive 路线和 Generative 路线必须长期隔离

Primitive 是高确定性内核；Generative CAD 是低信任 reference geometry 路径。

这两者可以在 artifact 层合流，但不能在编译器前半段混合。你的架构文档已经明确要求：新链路不能污染 Primitive registry / primitive compiler / geometry_primitives；合流点只能是 STEP + metadata，而不是 CADPartSpec、primitive_compiler、PRIMITIVE_COMPILERS 或 geometry_primitives。

顶级系统必须有这条铁律：

```text
Primitive path:
  deterministic CADPartSpec / Primitive / Kernel

Generative path:
  Raw G-CAD → Canonical G-CAD → Dialect Runtime → STEP + Metadata Proof

Merge point:
  canonical STEP artifact + metadata only
```

如果未来有人想把 `axisymmetric_base` 塞进 `PRIMITIVE_COMPILERS`，或者让 generative graph 伪装成 `axisymmetric_turbine_disk primitive`，必须被 CI 和 code review 自动拒绝。

---

# 2. 护城河来自哪里

真正的护城河不来自“能不能生成一个好看的 STEP”。那很容易被 demo 追平。

护城河来自以下几件事。

## 2.1 稳定 Core IR

顶级系统必须有一个小而稳定的 Core IR。Core IR 只表达：

```text
document
dialects
components
nodes
inputs / outputs
params
phase
constraints
safety
```

Core IR 不理解：

```text
countersink
rim slot
rib thickness
loft twist
gear tooth
cooling passage
bolt boss
```

这些只能存在于：

```text
node.params
```

并由：

```text
OperationSpec.params_model
```

验证。

这就是“编译器健康”的核心：新增功能不改核心编译器。你的记忆文档里也明确规定，新增 op 参数只改 params_model 和 handler，不改 Core IR / validator；未知 dialect/op 必须 fail-closed，不允许模糊匹配或 silent fallback。

如果未来每加一个 CAD 能力都要改 `RawGcadDocument`、`CanonicalGcadDocument`、`validation/typecheck.py`、`pipeline/run.py`，那这个编译器是不健康的。

---

## 2.2 Dialect Contract 是护城河

`Base` 不能是零件模板，必须是 CAD Grammar Dialect。这个抽象很关键。

正确护城河不是：

```text
turbine_disk_base
flange_base
bracket_base
```

而是：

```text
axisymmetric
sketch_extrude
loft_sweep
shell_housing
composition
```

前者会退化成 Primitive 的低配版本；后者才是可复用建模语法。

每个 Dialect 必须有：

```text
manifest
contract
phase_order
OperationSpec 列表
params schema
input/output types
effects
postconditions
semantic constraints
unsupported cases
contract_hash
```

`contract_hash` 必须进入 Canonical IR、metadata、artifact proof。否则你无法证明某个 STEP 是基于哪个版本的建模语法生成的。

真正强的系统应该做到：

```text
新增 op：
  只新增 OperationSpec + ParamsModel + Handler + Tests

新增 op 参数：
  只改 ParamsModel + Handler + Tests

新增 dialect：
  只注册 Dialect + Contract + Tests

核心 compiler：
  不动
```

这是长期可扩展性的核心。

---

## 2.3 Metadata Proof 是护城河

普通系统输出：

```text
output.step
```

顶级系统输出：

```text
output.step
output.metadata.json
artifact proof
validation proof
contract proof
runtime proof
import gate result
```

metadata 不是说明书，而是 **编译证明**。

它必须证明：

```text
这个 STEP 来自哪个 Raw graph；
Raw graph 的 hash 是什么；
Canonical graph 的 hash 是什么；
用了哪些 dialect；
每个 dialect 的 contract_hash 是什么；
每个 node 的 op_version 是什么；
哪个 runner 执行；
哪个 GeometryRuntime 导出；
validation stages 是否全部通过；
runtime postconditions 是否通过；
STEP inspection 是否通过；
safety flags 是否显式存在且为 true；
是否经过 repair；
repair patch hash 是什么；
artifact hash 是否匹配；
native rebuild 是否禁止；
是否需要 import gate。
```

你的文档中也明确要求 metadata 包含 source_route、trust_level、schema_version、selected dialects、op versions、feature/canonical graph hash、base contract hash、runner_version、geometry_runtime、repair_attempts、validation stages、warnings、degraded_features、safety flags、source_ir_path、step_path，且缺失或不匹配必须 fail。

没有 metadata proof 的 STEP，在这个系统里应该被视为不可信 artifact。

---

## 2.4 Import Gate 是护城河

顶级系统不能让“生成了 STEP”自动等于“可以进入 SolidWorks / NX”。

必须有状态机：

```text
created_unverified
  ↓
validated_reference_step
  ↓
native_import_eligible
```

其中：

```text
builder 只能生成 validated_reference_step
import gate 才能生成 native_import_eligible
```

`native_rebuild_allowed` 对 generative artifact 必须永远是 false。

原因很简单：Generative CAD 的几何可以作为 reference geometry，但不能被误认为 deterministic native model。尤其在 turbomachinery / aerospace / stress-sensitive part 里，这个边界必须非常硬。

---

# 3. 编译器健康度标准

如果我作为最终架构审查人，我会用下面这些条件判断它是否健康。

## 3.1 单入口原则

Raw JSON 只能有一个入口：

```text
parse_raw_gcad_document()
```

禁止：

```text
RawGcadDocument.model_validate(user_dict)
BaseDialect.run(raw_dict)
handler(raw_node)
```

顶级系统必须做到：

```text
User / LLM dict
  → parse_raw_gcad_document
  → RawGcadDocument
  → validation pipeline
  → CanonicalGcadDocument
```

任何绕开 parse 层的入口都是漏洞。

---

## 3.2 Canonical-only 原则

BaseDialect、runner、GeometryRuntime 不应该看到 RawGcadDocument。

它们只能看到：

```text
CanonicalGcadDocument
CanonicalNode
typed params
resolved op_version
resolved contract_hash
typed inputs / outputs
```

原因是 Raw IR 是不可信源码，Canonical IR 才是编译器批准后的中间表示。

如果任何 runtime handler 还能读取 raw dict、llm hints、未验证 params，这个系统就不够干净。

---

## 3.3 No fallback 原则

顶级编译器不能“猜”。

禁止：

```text
unknown op → try closest op
unknown dialect → fallback to axisymmetric
missing output → assume body
missing safety → default true
missing metadata stage → assume ok
missing handle type → infer solid
```

允许：

```text
unknown op → fail
unknown dialect → fail
missing safety → fail
missing metadata stage → fail
type mismatch → fail
```

CAD 是工程系统，不是聊天补全系统。模糊匹配会让 debug、audit、repair 全部失效。

---

## 3.4 Versioned ABI 原则

所有重要边界都必须版本化：

```text
Raw schema_version
Canonical canonical_version
Dialect version
Operation op_version
Metadata metadata_version
Artifact artifact_schema_version
Runner runner_version
GeometryRuntime runtime_version
Prompt prompt_version
RepairPatch patch_version
```

没有版本，就没有兼容性。

强系统必须有：

```text
supported_versions
deprecated_versions
migration adapters
compatibility tests
rejection policy
```

而不是“大家记得别改字段”。

---

## 3.5 Frozen Registry 原则

Registry 不能是全局可变字典。

顶级系统必须是：

```text
build_default_registry()
  → register built-in dialects
  → freeze()
```

生产路径只读 frozen registry。测试可以构造 local registry。

禁止：

```text
import-time populate mutable registry
runtime register dialect in production
tests mutate global registry
```

否则 contract hash、validation、CI 隔离都会变脆。

---

# 4. CAD 几何层的顶级要求

CAD 和普通 AST 编译不一样。几何是“恶意的”：布尔失败、拓扑漂移、边丢失、壳不闭合、单位错、OCC 容差问题都会发生。

顶级系统必须把几何当成不可信输出，而不是 handler 返回了 solid 就算成功。

## 4.1 Geometry Preflight

在实际建模前必须检查：

```text
尺寸正数
半径 / 厚度 / 深度合理
孔阵列落在材料区域内
槽深不超过壁厚
profile 闭合
profile 不自交
loft section 数量足够
boolean operands 有效
expected body count 合理
bbox 合理
单位明确为 mm
```

这不是 optional。Geometry preflight 是防止 CAD kernel 被坏参数打爆的第一道门。

---

## 4.2 Runtime Postconditions

每个 operation 不只要“执行成功”，还要证明 postcondition。

例如：

```text
revolve_profile:
  output solid exists
  closed solid true
  body_count == 1

cut_center_bore:
  output solid exists
  bore diameter applied
  body_count still expected

boolean_union:
  result exists
  body_count expected
  no null solid

shell_body:
  shell thickness positive
  closed/open policy explicit
```

OperationSpec 里的 `postconditions` 不能只是文档，应该变成 runtime check 或至少 metadata proof 中的 structured result。

---

## 4.3 GeometryRuntime 不能泄漏 CAD backend

Dialect handler 可以内部使用 CadQuery 对象，但跨 dialect 边界只能传 typed handle。

系统边界应该是：

```text
RuntimeObjectStore:
  handle_id → object
  handle_id → value_type

Dialect:
  receives handle_id
  asks context resolve object
  returns OperationResult

Composition:
  only sees typed handles

GeometryRuntime:
  export / inspect / bbox / body_count / closed_solid
```

禁止跨 dialect 传裸 CadQuery object。否则未来 Build123dRuntime / OCCRuntime / NXRuntime 都会被堵死。

---

# 5. Prompt 必须被当成 ABI

你的系统里 prompt 不是“文案”，而是 LLM source compiler 的前端协议。

顶级系统必须把 prompt 版本化、测试化、从 contract 生成化。

## 5.1 Level-1 Prompt 要求

Level-1 只做 routing，不生成 graph。

它输出：

```text
route_decision
part_intent
selected_dialects
selected_domain_skills
unsupported_capabilities
safety_notes
```

它必须明确：

```text
不能 invent dialect
不能 invent op
不能输出 CAD code
不能输出 file path
不能输出 subprocess
能力不足必须 unsupported
制造级 / 认证级 / 适航级请求必须拒绝或走确定性高可信 primitive
```

---

## 5.2 Level-2 Prompt 要求

Level-2 只做 RawGcadDocument authoring。

它必须明确：

```text
JSON only
RawGcadDocument only
所有 required top-level fields 显式存在
constraints 显式存在
safety 显式存在
每个 safety flag 显式 true
不依赖 defaults
只使用 selected dialect contracts
只使用 contract 中存在的 op/op_version/phase/params
不写 CadQuery / NXOpen / APDL / shell / path
trust_level 不超过 reference_geometry
```

如果 prompt 没说“不要依赖 defaults”，LLM 就会输出省略字段，增加 repair loop 压力。

---

## 5.3 Repair Prompt 要求

Repair loop 必须比 authoring 更严格。

只允许局部 patch：

```text
/nodes/<node_id>/params/<field>
```

谨慎允许：

```text
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/components/<component_id>/root_node
```

禁止：

```text
/safety
/constraints/require_*
/selected_dialects
/nodes/<node_id>/dialect
/nodes/<node_id>/op
/nodes/<node_id>/op_version
/components/<component_id>/owner_dialect
```

你的记忆文档明确写了 repair loop 只能局部 patch，不能改安全标志，不能弱化 validation，不能发明 base/op，重复 graph/error/stage 要停止；v1.0 release-blocker 也要求 repair prompt path 使用 `/nodes/<node_id>/params/<field>` 这种有效占位。

一个顶级系统必须把 prompt path 也纳入测试：

```text
prompt 中不能出现 /nodes//
prompt 中不能出现 /components//
prompt 中必须出现 /nodes/<node_id>/params/<field>
```

---

# 6. 测试体系要求

顶级系统的测试不是“测试能跑通一个 golden graph”。必须覆盖编译器不变量。

## 6.1 行为测试优先

禁止 release blocker 只用：

```python
assert "some string" in inspect.getsource(...)
```

必须用行为测试：

```text
输入坏 graph → pipeline fail
输入缺 safety → parse fail
输入 unknown op → registry fail
输入 type mismatch → typecheck fail
handler 返回错误 handle → runtime fail
metadata hash mismatch → import gate fail
```

源码字符串测试可以辅助防回归，但不能作为唯一证明。

---

## 6.2 必须有 mutation tests

你要主动破坏输入，确认系统 fail-closed：

```text
remove safety
set safety false
remove constraints
unknown dialect
unknown op
wrong op_version
wrong phase
cycle graph
missing input
output type mismatch
handler returns extra output
handler returns missing output
handler returns wrong handle type
metadata missing stage
metadata stage false
contract_hash mismatch
step_hash mismatch
artifact step_import_allowed true before gate
repair patch modifies safety
repair patch modifies op_version
```

没有 mutation tests 的系统，不知道自己是否真的 fail-closed。

---

## 6.3 必须有 golden corpus

建立：

```text
golden_axisymmetric_minimal
golden_axisymmetric_with_holes
golden_sketch_extrude_plate
golden_composition_two_components
golden_repair_success
golden_repair_give_up
```

每个 golden fixture 固定：

```text
raw hash
canonical hash
metadata schema
artifact schema
expected warnings
expected validation stages
expected STEP existence
```

Golden corpus 是你的“编译器回归测试集”。

---

## 6.4 必须有 contract evolution tests

护城河来自扩展不改核心，所以必须测试：

```text
新增 op 参数只改 ParamsModel + Handler；
Core IR 不变；
Core Validator 不变；
metadata 记录新 op_version；
旧 op_version 仍能 validate；
未知 op_version fail。
```

这类测试比多加几个 demo 零件更重要。

---

# 7. 代码质量要求

## 7.1 模块边界必须硬

推荐边界：

```text
ir/
  raw.py
  parse.py
  canonical.py
  hashing.py

validation/
  pipeline.py
  structure.py
  registry.py
  params.py
  graph.py
  typecheck.py
  phase.py
  safety.py
  canonicalize.py

dialects/
  base.py
  operation.py
  results.py
  executor.py
  registry_core.py
  default_registry.py
  axisymmetric/
  sketch_extrude/
  composition/

runtime/
  context.py
  object_store.py
  handles.py
  geometry_runtime.py
  cadquery_runtime.py
  postconditions.py

pipeline/
  run.py
  metadata_v3.py
  artifact_models.py
  artifact.py
  import_artifact.py

repair/
  patch.py
  governor.py

skills/
  prompts.py
  orchestrator.py
```

禁止循环依赖。特别是：

```text
ir 不依赖 dialects
dialects 不依赖 pipeline
runtime 不依赖 skills
validation 可依赖 dialect registry，但不能依赖 runner
pipeline 组合所有层
```

如果底层模块 import 高层模块，架构就开始腐烂。

---

## 7.2 不允许宽泛异常吞噬

禁止：

```python
try:
    ...
except Exception:
    return ok
```

允许：

```python
except ValidationError as exc:
    return fail(stage="params", code="params_schema_error", ...)
except GeometryRuntimeError as exc:
    return fail(stage="runtime", code="geometry_runtime_error", ...)
```

所有 error 必须结构化：

```text
stage
code
message
path
node_id
component_id
severity
```

错误码是 repair loop 的 ABI，不能随意改。

---

## 7.3 不允许 silent degradation

optional node 可以 degrade，但必须满足：

```text
required = false
degradation_policy = may_skip_with_warning
metadata.degraded_features 记录
validation stage 不伪装 ok
warning 进入 metadata
```

如果 required node 失败，必须 fail。

---

## 7.4 Legacy 必须隔离

可以保留 legacy，但 production import graph 不能碰它。

要求：

```text
legacy modules 默认 raise ImportError
只有 SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1 才可 import
production code scan 禁止 generative_cad.legacy / old base / old runner
compat adapter 必须显式命名
```

Legacy 最大的危险不是它会被执行，而是它会误导未来的 Claude Code 或新开发者。

---

# 8. 安全与声明边界

顶级系统必须内置声明边界，而不是靠 README 提醒。

Generative output 永远只能是：

```text
reference_geometry
concept_geometry
```

不能声明：

```text
manufacturing-ready
production-ready
certified
airworthy
installable
structurally validated
fatigue validated
life prediction
```

如果用户要求这些，routing stage 必须：

```text
unsupported
或转 deterministic validated primitive path
```

尤其 turbomachinery / aerospace / pressure vessel / medical / automotive safety part，必须默认 conservative。

---

# 9. 发布门槛

我会设三个等级。

## 9.1 Experimental

允许：

```text
生成 STEP
metadata 存在
basic validation
manual inspection
```

不允许：

```text
native import by default
用户误认为可制造
自动 repair 进入最终 artifact
```

## 9.2 Release Candidate

必须满足：

```text
Raw parse fail-closed
ValidationBundle 完整
Canonical IR stable hash
OperationResult runtime proof
GeometryRuntime abstraction
MetadataProofV3
CanonicalStepArtifact
ImportGate
behavior tests
golden corpus
repair governor
legacy isolation
```

## 9.3 Production Reference Geometry

必须满足：

```text
CI 全绿
mutation tests 全绿
contract evolution tests 全绿
metadata/artifact hash proof
import gate v3-only
no legacy production imports
no prompt path invalid placeholders
performance bounds
workspace path sandboxing
no subprocess from LLM
security review
```

即使达到 Production Reference Geometry，也仍然不能宣称 manufacturing-ready / certified / airworthy。

---

# 10. 护城河最终定义

这套系统的护城河不是“模型更聪明”，而是：

```text
1. 稳定 Core IR
2. Contract-driven Dialects
3. OperationSpec + ParamsModel
4. Typed Runtime Handles
5. GeometryRuntime backend abstraction
6. MetadataProofV3
7. Artifact state machine
8. ImportGate
9. Repair governor
10. Golden corpus + mutation tests
11. Prompt as versioned ABI
12. Primitive path isolation
```

别人可以很快做一个：

```text
prompt → CadQuery script → STEP
```

但很难快速做出：

```text
LLM source
  → parse proof
  → validation proof
  → canonical graph proof
  → contract hash proof
  → operation runtime proof
  → geometry proof
  → artifact hash proof
  → import gate proof
```

这才是你的护城河。

---

# 11. 我对你当前路线的最终要求

如果要称得上顶级，我会给这套框架提出以下硬要求：

```text
第一，LLM 永远不能越过 Raw G-CAD source 边界。

第二，Core IR 永远保持小而稳定，不为具体零件膨胀。

第三，Dialect 必须是建模语法，不是零件模板。

第四，所有 op 必须 OperationSpec 化、version 化、params schema 化。

第五，所有 runtime output 必须 OperationResult 化、typed handle 化。

第六，GeometryRuntime 必须是唯一 CAD backend 边界。

第七，metadata 必须是 proof，不是日志。

第八，artifact 必须有状态机，import gate 是唯一准入权威。

第九，repair loop 必须局部、可审计、可停止，不能改 safety / contract / op。

第十，测试必须证明 fail-closed，而不是证明 happy path 能跑。

第十一，Primitive path 必须保持神圣不可污染。

第十二，所有 prompt 必须版本化、测试化、最好从 contract 生成。

第十三，任何 fallback、guess、silent default、fuzzy match 都是架构腐蚀。

第十四，任何新增能力如果需要改核心编译器，就说明抽象失败。

第十五，任何 STEP 如果没有 metadata proof，就不是可信 artifact。
```

---

# 12. 一句话总结

顶级、有护城河、编译器健康强大的 SeekFlow Generative CAD 系统，应该是：

```text
一个把 LLM 当作受约束源码作者、
把 G-CAD Core IR 当作源语言、
把 Dialect Contract 当作标准库 ABI、
把 OperationSpec 当作类型化指令集、
把 GeometryRuntime 当作后端、
把 MetadataProof 当作编译证明、
把 ImportGate 当作安全边界的 CAD 编译器。
```

只要你坚持这个方向，它就不是普通 text-to-CAD，而是一个真正可演进、可审计、可防御、可扩展的 **LLM-driven CAD compiler platform**。
