# SeekFlow Generative CAD-IR / LLM-Skill-Base 架构完整记忆文档

## 0. 文档用途

这是一份用于开启新对话的完整上下文文档。新对话读取本文档后，应当能够完整理解：

1. 我现在到底想做什么；
2. 现有 SeekFlow Engineering Tools 的主链路是什么；
3. 为什么不能破坏现有 Primitive / CAD-IR 主链路；
4. 新增的 LLM-Skill-Base / Generative CAD-IR 链路是什么；
5. Base 到底是什么，不是什么；
6. Skill 机制是什么，尤其是“二级 Skill 机制”是什么；
7. LLM 到底负责什么，不负责什么；
8. 多 Base 组合如何解决；
9. 参数扩展如何避免修改总编译器；
10. LLM 输出如何通过固定结构校验层和 Base 编译隔离；
11. 如何避免最终退化成 Primitive 或完全自由生成；
12. 后续继续讨论和实施时必须遵守哪些硬约束。

本文档应被视为后续讨论的架构基线。

---

# 1. 我现在到底要做什么

我正在做 text-to-CAD 工作，当前系统已经有一条比较成熟的主链路：

```text
用户自然语言
  ↓
NL → CAD-IR
  ↓
CADPartSpec
  ↓
Recipe / Primitive / 基础 CAD feature
  ↓
CadQuery / SolidWorks / NX / ANSYS
  ↓
STEP / 原生格式 / metadata
  ↓
inspection / validation / mechanical validation
```

当前主链路适合高确定性的工程建模，例如齿轮、涡轮盘等。它依赖 CAD-IR、Primitive、确定性内核、metadata sidecar、fail-closed 和后端验证。

但是我还想探索 LLM 本身在 text-to-CAD 中的边界：
LLM 是否可以在受控约束下，生成非完全模板化、非完全 Primitive 的自由形状和复杂零件。

我的目标不是让 LLM 直接写任意 CadQuery / SolidWorks / NX / APDL 代码。
我的目标也不是把现有 Primitive 改成 LLM 生成。

我的目标是新增一条独立链路：

```text
LLM-Skill-Base / Generative CAD-IR Path
```

这条链路位于：

```text
完全确定性的 Primitive
和
完全自由的 LLM 代码生成
之间
```

它的定位是：

```text
LLM 写受控 CAD Grammar；
Base / Dialect 解释并执行 Grammar；
系统做结构校验、语义校验、几何预检、STEP 导出和 metadata；
最终只在 STEP + metadata 验证通过后并入现有主链路后半段。
```

一句话总结：

```text
我想构建一条受控自由建模链路：
既保留 LLM 的建模自由度，
又不破坏现有 Primitive 主链路的确定性和安全性。
```

---

# 2. 现有主链路必须保持不变

现有系统的核心原则必须保留：

1. CAD-IR 是现有主链路的前端接口；
2. Primitive 是确定性工程语义单元；
3. Primitive 必须由 deterministic kernel 构建；
4. LLM 不应直接生成 SolidWorks COM / NXOpen / APDL 几何代码；
5. 所有异常路径 fail-closed；
6. Primitive 输出必须有 metadata sidecar；
7. turbomachinery 输出必须是 non-flight reference only；
8. 不允许声明 airworthy / certified / manufacturing-ready / production-ready / installable；
9. SolidWorks / NX 对复杂几何只 import canonical STEP；
10. 新链路不能污染现有 Primitive registry / primitive compiler / geometry_primitives。

因此新链路在 v0 中不应修改：

```text
cadquery_backend/primitive_compiler.py
geometry_primitives/
PRIMITIVE_COMPILERS
CADPartSpec 的现有语义
```

新链路也不应该把自己伪装成：

```text
primitive
recipe
axisymmetric_turbine_disk
```

它应该有独立的 Generative CAD-IR，然后在 STEP artifact 层并入主链路。

---

# 3. 新链路的最终形态

最终收敛出的架构不是：

```text
LLM → base → CadQuery
```

而是：

```text
LLM Raw Output
  ↓
G-CAD Core IR 固定结构校验层
  ↓
Canonical G-CAD Core IR
  ↓
Base Dialect / OperationSpec 校验与执行
  ↓
Geometry Runtime
  ↓
STEP + generative metadata
  ↓
canonical STEP artifact
  ↓
现有主链路后半段 inspection / validation / optional SW-NX import
```

核心思想：

```text
LLM 不直接写 CAD 代码；
LLM 不直接调用 Base；
LLM 只输出结构化 Feature Graph；
Feature Graph 必须先通过固定 Core IR 校验；
Base 不是零件模板，而是 CAD Grammar Dialect；
每个 Base 实现统一接口；
每个 operation 通过 OperationSpec 声明；
多 Base 不互相调用，只通过统一 RuntimeValue 和 Composition Dialect 组合；
最终输出是 STEP artifact，不是 Primitive。
```

---

# 4. Base 到底是什么

Base 不是某个零件模板。
Base 不是 Primitive 的新名字。
Base 不是“涡轮盘模板”“法兰模板”“支架模板”。

Base 的正确定义是：

```text
Base = 一类 CAD 建模范式的可执行 Grammar / Dialect。
```

它描述的是一种建模方式，而不是一个具体零件。

错误设计：

```text
turbine_disk_base
bracket_base
flange_base
gearbox_base
bearing_seat_base
```

这些会退化成 Primitive。

正确设计：

```text
axisymmetric_base
sketch_extrude_base
loft_sweep_base
shell_housing_base
pipe_manifold_base
sheet_metal_base
composition_base
```

这些代表建模语法。

## 4.1 axisymmetric_base

用于旋转体和轴对称零件，例如：

```text
涡轮盘
法兰
轮毂
轴套
环
端盖
皮带轮
转子盘
旋转接头
```

典型 operation：

```text
revolve_profile
cut_center_bore
cut_annular_groove
cut_circular_hole_pattern
cut_rim_slot_pattern
apply_chamfer
apply_fillet
```

## 4.2 sketch_extrude_base

用于由草图拉伸、切削、打孔形成的棱柱类零件，例如：

```text
支架
安装板
连接块
夹具块
机加工板件
耳板
加强筋结构
```

典型 operation：

```text
create_sketch
extrude_sketch
cut_pocket
cut_hole
add_boss
add_rib
linear_pattern
mirror_feature
```

## 4.3 loft_sweep_base

用于截面变化、路径扫掠、曲面过渡零件，例如：

```text
叶片
导流片
喷管
弯管
异形通道
渐变截面件
空气动力外形
```

典型 operation：

```text
create_section
place_section
loft_sections
sweep_profile
twist_sections
scale_sections
trim_surface
```

## 4.4 shell_housing_base

用于壳体、机匣、泵壳等，例如：

```text
齿轮箱壳体
泵壳
电机壳
阀体外壳
端盖壳体
罩壳
```

典型 operation：

```text
create_base_volume
shell_body
add_mounting_pad
add_boss
add_rib
cut_port
cut_hole_pattern
fillet_edges
```

## 4.5 composition_base / composition dialect

用于多 Base 组合，不直接创建复杂几何，只负责：

```text
place_component
align_frame
linear_pattern_component
circular_pattern_component
boolean_union
boolean_cut
boolean_intersect
merge_solids
```

它是跨 Base 组合层，不是万能建模后门。

---

# 5. Primitive、Base、Skill、LLM 的区别

## 5.1 Primitive

Primitive 是确定性零件内核。

特征：

```text
面向具体零件
拓扑基本固定
参数表稳定
验证规则强
可走高可信链路
适合工业级确定建模
```

示例：

```text
involute_spur_gear
axisymmetric_turbine_disk
future_standard_flange
future_shaft_with_keyway
```

## 5.2 Base

Base 是 CAD Grammar / Dialect。

特征：

```text
面向建模范式
不是具体零件
feature graph 可变
operation 数量可变
profile / sketch / path 可变
信任等级低于 Primitive
默认 reference geometry
```

示例：

```text
axisymmetric_base
sketch_extrude_base
loft_sweep_base
shell_housing_base
```

## 5.3 Skill

Skill 是 LLM 使用 Base 的指导材料，不是执行器。

Skill 告诉 LLM：

```text
某个领域通常怎么建模；
什么时候选哪个 Base；
哪些结构常见；
哪些结构禁止；
如何输出合法 Feature Graph；
安全边界是什么。
```

Skill 不写 CAD 代码。
Skill 不替代 Base Contract。
Skill 不包含 runner 源码。
Skill 不直接生成 STEP。

## 5.4 LLM

LLM 是“受约束 CAD Grammar 作者”。

LLM 负责：

```text
理解用户意图；
选择合适的 Base / Dialect；
根据 Skill 和 Contract 输出 Feature Graph；
给出建模步骤、feature 组合、参数、profile、孔阵列、布局；
在 repair loop 中输出局部 patch。
```

LLM 不负责：

```text
写完整 CadQuery 脚本；
调用 cq.exporters.export；
控制文件路径；
调用 subprocess；
写 SolidWorks COM；
写 NXOpen；
写 APDL；
决定验证是否通过；
关闭 safety；
发明不存在的 Base / op；
直接进入 Base runner。
```

---

# 6. 二级 Skill 机制是什么

为了避免上下文过长、Base 过多、LLM 混淆，Skill 机制需要分成两级。

不是把所有 Base 的全部内容塞进一个巨大 Skill。
而是：

```text
一级 Skill：领域路由与建模策略 Skill
二级 Skill：选中 Base / Dialect 的使用 Skill
```

也可以叫：

```text
Level-1 Domain Skill
Level-2 Dialect Usage Skill
```

---

## 6.1 一级 Skill：Domain Routing Skill

一级 Skill 是领域级别的建模指导。
它在 LLM 选择 Base 之前使用。

它解决的问题：

```text
这个零件大概属于什么领域？
它的主导几何是什么？
应该优先选择哪个 Base？
是否需要多个 Base？
是否有安全限制？
是否应该走 Primitive 而不是 Generative Path？
是否当前能力不支持，应 fail-closed？
```

一级 Skill 的内容包括：

```text
领域常见零件类型
零件到 Base 的选择规则
Primitive 优先规则
禁用声明
安全要求
输出 trust_level
典型建模策略
能力不足时如何报告 unsupported
```

例如 turbomachinery 一级 Skill：

```text
旋转盘、轮毂、法兰、环类 → axisymmetric_base
叶片、导流片、喷管、弯管 → loft_sweep_base
机匣、泵壳、壳体 → shell_housing_base
组合件 → component graph + composition dialect
如果用户要求适航、认证、制造级，必须拒绝或转高可信 primitive
所有 turbomachinery generative 输出只能是 non-flight reference geometry
```

一级 Skill 的输出不是完整 Feature Graph，而是：

```json
{
  "part_intent": {
    "object_type": "turbine_disk",
    "dominant_geometry": "rotational_axisymmetric_body_with_patterned_features"
  },
  "selected_dialects": [
    {
      "dialect": "axisymmetric",
      "reason": "main body is rotational and can be built by revolve_profile"
    }
  ],
  "selected_domain_skills": [
    {
      "skill_id": "turbomachinery_reference_skill"
    }
  ],
  "unsupported_capabilities": [],
  "route_decision": "generative_cad_ir"
}
```

---

## 6.2 二级 Skill：Dialect Usage Skill

二级 Skill 是在 Base / Dialect 选中之后加载的。

它不是领域泛化指导，而是告诉 LLM：

```text
当前选中的 Dialect 有哪些 op；
每个 op 的用途是什么；
Feature Graph 应该怎么组织；
phase 顺序是什么；
典型输入输出是什么；
什么组合是合法的；
常见错误是什么；
应该如何输出 Core IR 节点。
```

二级 Skill 必须由 Base Manifest / Base Contract 生成或严格同步，不能手写后长期漂移。

例如 axisymmetric dialect 的二级 Skill 包含：

```text
可用 op:
  revolve_profile
  cut_center_bore
  cut_annular_groove
  cut_circular_hole_pattern
  cut_rim_slot_pattern

phase_order:
  base_solid
  primary_cut
  annular_detail
  pattern_cut
  rim_detail
  edge_treatment
  cleanup

约束:
  revolve_profile 必须产生 root solid
  cut 类 op 必须输入 solid 并输出 solid
  circular hole pattern 的 pcd 必须落在材料区域内
  rim slot depth 不能超过 rim radial thickness
```

二级 Skill 的作用是让 LLM 输出合法的 G-CAD Core IR nodes。

---

## 6.3 为什么需要二级 Skill

如果只给 LLM 一个巨大 Skill，会出现：

```text
上下文太长；
Base 一多就混乱；
LLM 混用不同 Base 的 op；
Base 更新后 Skill 漂移；
参数 schema 和实际 runner 不一致；
错误难追踪。
```

二级 Skill 机制解决这个问题：

```text
先用一级 Skill 选择 Base；
再按需加载选中 Base 的二级 Skill / Contract；
最后让 LLM 输出 Feature Graph。
```

流程：

```text
用户需求
  ↓
Base Catalog + 一级 Domain Skill
  ↓
LLM 输出 Base Selection Plan
  ↓
系统加载选中 Base 的 Contract / 二级 Skill
  ↓
LLM 输出 G-CAD Core IR Feature Graph
  ↓
Core Validator 校验
  ↓
Base Dialect 执行
```

---

## 6.4 Skill、Manifest、Contract 的区别

需要严格区分：

### Base Manifest

给 LLM 做初步选择用，内容短：

```text
base_id / dialect_id
summary
typical_parts
main_ops
unsupported_cases
```

### Base Contract

给 validator 和二级 Skill 使用，内容严格：

```text
op specs
op params schema
input types
output types
phase
effects
constraints
version
```

### 一级 Skill

给 LLM 领域路由用：

```text
领域知识
Base 选择策略
Primitive 优先策略
安全边界
unsupported 判断
```

### 二级 Skill

给 LLM 生成合法 Feature Graph 用：

```text
选中 Base 的 op 使用说明
phase 顺序
节点组织方式
输入输出示例
少量 few-shot
常见错误
```

### Runner 源码

只给系统用，不给 LLM。

---

# 7. LLM 最终输出什么

LLM 最终输出的不是 CadQuery 代码，而是：

```text
G-CAD Core IR / Feature Graph
```

它描述：

```text
有哪些 component；
每个 component 属于哪个 owner_dialect；
有哪些 nodes；
每个 node 调用哪个 dialect.op；
节点输入输出是什么；
参数是什么；
依赖关系是什么；
phase 是什么；
哪些 feature required；
degradation_policy 是什么；
constraints 和 safety 是什么。
```

示例结构：

```json
{
  "schema_version": "g_cad_core_v0.1",
  "document_id": "part_001",
  "units": "mm",
  "trust_level": "reference_geometry",
  "selected_dialects": [
    {
      "dialect": "axisymmetric",
      "version": "0.1.0"
    }
  ],
  "components": [
    {
      "id": "main_disk",
      "owner_dialect": "axisymmetric",
      "kind_hint": "rotational_body",
      "root_node": "n_body"
    }
  ],
  "nodes": [
    {
      "id": "n_body",
      "component": "main_disk",
      "dialect": "axisymmetric",
      "op": "revolve_profile",
      "phase": "base_solid",
      "inputs": [],
      "outputs": [
        {
          "name": "body",
          "type": "solid"
        }
      ],
      "params": {
        "axis": "Z",
        "profile_stations": [
          {
            "r_mm": 40,
            "z_front_mm": -36,
            "z_rear_mm": 36
          },
          {
            "r_mm": 90,
            "z_front_mm": -36,
            "z_rear_mm": 36
          },
          {
            "r_mm": 260,
            "z_front_mm": -34,
            "z_rear_mm": 34
          }
        ]
      },
      "required": true,
      "degradation_policy": "fail"
    },
    {
      "id": "n_holes",
      "component": "main_disk",
      "dialect": "axisymmetric",
      "op": "cut_circular_hole_pattern",
      "phase": "pattern_cut",
      "inputs": [
        {
          "node": "n_body",
          "output": "body"
        }
      ],
      "outputs": [
        {
          "name": "body",
          "type": "solid"
        }
      ],
      "params": {
        "count": 12,
        "pcd_mm": 300,
        "hole_dia_mm": 28,
        "axis": "Z",
        "through_all": true
      },
      "required": true,
      "degradation_policy": "fail"
    }
  ],
  "constraints": {
    "require_closed_solid": true,
    "expected_body_count": 1,
    "require_step_file": true,
    "require_metadata_sidecar": true
  },
  "safety": {
    "not_for_manufacturing": true,
    "not_certified": true,
    "no_structural_validation": true
  }
}
```

---

# 8. 固定结构校验层

LLM 输出不能直接进入 Base。
LLM Raw JSON 必须经过固定结构校验层。

该层叫：

```text
G-CAD Core IR Validator
```

它负责：

```text
RawGcadDocument → CanonicalGcadDocument
```

校验内容：

```text
schema_version 合法；
units 合法；
trust_level 合法；
selected_dialects 存在且合法；
components id 唯一；
每个 component 有 owner_dialect；
owner_dialect 必须在 selected_dialects 中；
nodes id 唯一；
node dialect 存在；
node op 存在；
node dialect 必须在 selected_dialects 中；
node component 存在；
component 内节点必须属于 owner_dialect；
composition 节点只能位于 composition component；
inputs 引用存在；
outputs 类型合法；
input/output 类型匹配；
graph 无环；
phase 顺序合法；
params 由 OperationSpec.params_model 校验；
safety 不能缺失或被关闭；
constraints 不能放宽系统最低要求。
```

只有通过后才能生成 CanonicalGcadDocument。

后续所有模块只接受 CanonicalGcadDocument。

---

# 9. BaseDialect 和 OperationSpec

所有 Base 必须实现统一接口：

```python
class BaseDialect:
    dialect_id: str
    version: str

    def manifest(self): ...
    def contract(self): ...
    def op_specs(self): ...

    def validate_component(self, component, nodes, ctx): ...
    def preflight_component(self, component, nodes, ctx): ...
    def run_component(self, component, nodes, ctx): ...
```

所有 operation 必须声明 OperationSpec：

```python
class OperationSpec:
    dialect: str
    op: str
    op_version: str
    phase: str
    input_types: list
    output_types: list
    params_model: BaseModel
    effects: list
    postconditions: list
```

新增 operation 时，只需新增：

```text
OperationSpec
ParamsModel
Handler
Tests
```

不改总编译器。

---

# 10. 多 Base 组合方案

多 Base 不能互相调用。
多 Base 也不需要互相理解。
它们共同兼容统一 Core IR 和 RuntimeValue。

规则：

```text
每个 component 有且只有一个 owner_dialect；
component 内节点只由 owner_dialect 处理；
跨 component / 跨 dialect 操作只能由 composition dialect 处理；
Base 之间只通过 typed handles 传递结果；
Base 不能访问其他 Base 的内部状态。
```

RuntimeValue 类型包括：

```text
SolidHandle
FrameHandle
CurveHandle
ProfileHandle
PlaneHandle
PointHandle
SolidArrayHandle
ComponentHandle
```

各 Base 内部可以用 CadQuery 对象，但跨 Base 边界只能传 Handle。

Composition dialect 支持：

```text
place_component
align_frame
linear_pattern_component
circular_pattern_component
boolean_union
boolean_cut
boolean_intersect
merge_solids
```

它不支持创建复杂新几何，不支持任意代码。

---

# 11. 参数扩展机制

参数扩展不能要求修改 Core IR 或总编译器。

原则：

```text
Core IR 不知道具体参数；
Core IR 只知道 node.params 是 dict；
具体参数由 OperationSpec.params_model 校验；
扩展参数只改对应 op 的 params_model 和 handler；
总编译器不改。
```

必须使用 op_version。

例如：

```text
axisymmetric.cut_circular_hole_pattern@1.0.0
axisymmetric.cut_circular_hole_pattern@2.0.0
```

Canonical IR 必须记录实际 op_version。
metadata 也必须记录 op_version。

---

# 12. Runner 与 GeometryRuntime

不要动态生成大量 CadQuery Python 代码。

应使用固定 runner harness：

```python
from seekflow_engineering_tools.generative_cad.runner import run_gcad_core

run_gcad_core(
    input_json="input.gcad.json",
    out_step="output.step",
    metadata_path="output.metadata.json"
)
```

runner 内部：

```text
读取 CanonicalGcadDocument
按 component 分组
找到 owner_dialect
调用 dialect.run_component
得到 typed handles
调用 composition dialect 组合
GeometryRuntime 导出 STEP
写 metadata
```

GeometryRuntime 是底层 CAD API 包装层。

v0 可以只有：

```text
CadQueryRuntime
```

未来可以支持：

```text
Build123dRuntime
OCCRuntime
```

---

# 13. Verification / Validation 分层

必须有多层验证：

```text
1. Structure validation
2. Registry validation
3. Operation params validation
4. Graph validation
5. Type validation
6. Phase validation
7. Safety validation
8. Dialect semantic validation
9. Geometry preflight
10. Runtime postcondition
11. STEP inspection
12. Metadata validation
```

错误必须分层返回：

```json
{
  "stage": "typecheck",
  "node_id": "n_holes",
  "code": "input_type_mismatch",
  "message": "Expected solid input but got frame.",
  "path": "/nodes/3/inputs/0"
}
```

这样便于定位 LLM 错误、结构错误、Base 错误、几何错误或 STEP 错误。

---

# 14. Repair Loop

Repair loop 必须受控。

规则：

```text
只允许局部 patch；
不能重写整个 graph；
不能修改 safety；
不能放宽 validation contract；
不能发明 base/op；
不能修改 base contract；
不能修改 op schema；
必须记录 graph hash、error signature、repair patch hash；
重复 graph 停止；
重复 error 停止；
validation stage 不前进停止；
超过 max_attempts 停止。
```

repair 输出示例：

```json
{
  "repair_patch": {
    "target_node": "rim_slots",
    "changes": [
      {
        "path": "/params/slot_depth_mm",
        "from": 32,
        "to": 22
      }
    ],
    "reason": "slot depth exceeded available rim thickness"
  }
}
```

---

# 15. Metadata

新链路必须输出 generative metadata。

至少包含：

```text
metadata_version
source_route
trust_level
schema_version
selected_dialects
dialect versions
op versions
feature_graph_hash
canonical_graph_hash
base_contract_hash
runner_version
geometry_runtime
repair_attempts
validation stages
warnings
degraded_features
safety flags
source_ir_path
step_path
```

metadata 缺失必须 fail。
safety 缺失必须 fail。
contract hash 不匹配必须 fail。

---

# 16. 与现有主链路的合流点

新链路不能进入：

```text
CADPartSpec
primitive_compiler.py
PRIMITIVE_COMPILERS
geometry_primitives
```

新链路输出：

```text
canonical STEP artifact + generative metadata
```

主链路后半段处理：

```text
inspect STEP
validate artifact
validate metadata
optional SolidWorks / NX STEP import
```

合流点是：

```text
STEP + metadata
```

不是：

```text
primitive compiler
```

---

# 17. 如何避免走回 Primitive 老路

必须有治理规则。

## 17.1 Base 不能以零件命名

禁止：

```text
turbine_disk_base
flange_base
bracket_base
gearbox_base
```

允许：

```text
axisymmetric_base
sketch_extrude_base
loft_sweep_base
shell_housing_base
```

## 17.2 Base op 必须是几何语法

好的 op：

```text
revolve_profile
extrude_sketch
cut_hole_pattern
loft_sections
sweep_profile
shell_body
boolean_union
```

坏的 op：

```text
make_turbine_disk
make_standard_flange
make_bracket
make_gearbox
```

## 17.3 稳定模式可以晋升 Primitive

如果某个 G-CAD graph 模式稳定、常用、需要高正确性，则可以人工审查并晋升为 deterministic primitive。

例如：

```text
axisymmetric_base + hub/web/rim + rim_slots
```

长期稳定后可以成为：

```text
axisymmetric_turbine_disk primitive
```

但 base 仍保留通用 revolve / cut / pattern 能力。

---

# 18. MVP 实施范围

不要一开始做任意零件。

MVP 阶段：

```text
Core IR
Core Validator
Dialect Registry
OperationSpec
RawGcadDocument → CanonicalGcadDocument
axisymmetric dialect
CadQueryRuntime
STEP export
generative metadata
STEP inspection
```

MVP axisymmetric ops：

```text
revolve_profile
cut_center_bore
cut_annular_groove
cut_circular_hole_pattern
```

第二阶段：

```text
sketch_extrude dialect
extrude_sketch
cut_hole
cut_pocket
add_boss
```

第三阶段：

```text
composition dialect
place_component
circular_pattern_component
boolean_union
boolean_cut
```

第四阶段：

```text
参数扩展示范：
给 cut_circular_hole_pattern 增加 countersink 参数；
验证只改 op schema 和 handler，不改 Core IR / Core Validator / Pipeline。
```

---

# 19. 推荐代码结构

新增：

```text
src/seekflow_engineering_tools/generative_cad/
  __init__.py

  ir/
    raw.py
    core.py
    canonical.py
    values.py
    safety.py

  dialects/
    base.py
    registry.py

    axisymmetric/
      dialect.py
      ops.py
      params.py
      runner.py
      preflight.py

    sketch_extrude/
      dialect.py
      ops.py
      params.py
      runner.py
      preflight.py

    composition/
      dialect.py
      ops.py
      params.py
      runner.py

  validation/
    structure.py
    registry.py
    graph.py
    typecheck.py
    phase.py
    safety.py
    canonicalize.py

  runtime/
    context.py
    values.py
    object_store.py
    geometry_runtime.py
    cadquery_runtime.py

  pipeline/
    validate.py
    run.py
    build.py
    artifact.py
    metadata.py

  repair/
    governor.py
    patch.py
    hashes.py

  tools.py
```

不改：

```text
cadquery_backend/primitive_compiler.py
geometry_primitives/
PRIMITIVE_COMPILERS
```

---

# 20. 关键测试

必须测试：

```text
unknown dialect fail
unknown op fail
node id duplicate fail
input reference missing fail
graph cycle fail
phase order fail
input/output type mismatch fail
node.params schema fail
safety missing fail
safety false fail
component owner dialect enforced
cross-base internal reference forbidden
cross-base composition only via composition dialect
adding op parameter does not modify core validator
canonical graph hash stable
repair loop stops on repeated graph hash
repair loop stops on repeated error signature
metadata missing fail
STEP missing fail
golden axisymmetric graph exports valid STEP
```

尤其重要：

```text
test_extended_param_is_validated_by_op_spec_only
test_cross_base_requires_composition_dialect
```

---

# 21. 必须写给 Claude Code 的硬约束

实施时必须明确：

```text
Do not modify existing deterministic primitive path semantics.
Do not modify cadquery_backend/primitive_compiler.py.
Do not add generative feature types to ir/cad.py in v0.
Do not add generative bases to primitive registries or primitive capabilities.
LLM raw JSON must never be passed directly to any base dialect.
All LLM output must pass RawGcadDocument -> CanonicalGcadDocument validation.
Core IR envelope is fixed.
Base-specific fields are allowed only inside node.params.
node.params must be validated by OperationSpec.params_model.
Every base must implement BaseDialect.
Every operation must declare OperationSpec.
Multiple bases are composed only via composition dialect.
Base dialects must not call each other directly.
Cross-dialect runtime values must be typed handles.
Adding a new op parameter must not require modifying core compiler or core validator.
Unknown dialect/op must fail closed.
No fuzzy matching.
No silent fallback.
The runner must use a fixed harness.
Do not dynamically generate large CadQuery scripts.
Output is canonical STEP artifact with metadata, not primitive.
Trust level of generative output must not exceed reference_geometry.
```

---

# 22. 当前仍需继续讨论的问题

后续可以继续深入：

```text
G-CAD Core IR 最终 schema 是否需要再精简；
ValueType 最小集合如何定义；
OperationSpec 是否支持 polymorphic input；
Composition dialect 的 MVP op 范围；
axisymmetric dialect 的第一批 op 参数如何设计；
sketch_extrude dialect 是否作为第二个 Base；
GeometryRuntime 的接口粒度；
RuntimeObjectStore 如何保存 CadQuery 对象；
Geometry preflight 做到什么程度；
二级 Skill 如何从 Base Contract 自动生成；
Base Manifest / Contract 如何供 LLM 检索；
如何写 prompt 让 LLM 先选 dialect 再输出 Core IR；
如何构建 graph fixture corpus；
如何做 mutation tests；
如何把 generative metadata 和现有 metadata sidecar 兼容；
是否新增 engineering_build_generative_cad_model 工具；
是否在 capabilities registry 增加 non-primitive generative capabilities。
```

---

# 23. 最重要的最终总结

我想要做的东西不是：

```text
LLM 直接写 CAD 代码
```

也不是：

```text
每个零件一个 base
```

也不是：

```text
把 Primitive 改成 LLM 生成
```

而是：

```text
构建一条独立的、受控的 Generative CAD-IR 链路。
```

这条链路的本质是：

```text
LLM 根据一级 Skill 选择合适的 CAD Grammar Dialect；
系统加载对应的二级 Skill / Base Contract；
LLM 输出固定结构的 G-CAD Core IR Feature Graph；
Core Validator 把 Raw 输出转成 Canonical IR；
BaseDialect 根据 OperationSpec 校验并执行；
多 Base 通过 Composition Dialect 和 typed RuntimeValue 组合；
GeometryRuntime 生成 STEP；
metadata 记录完整 provenance；
最终只以 canonical STEP artifact 形式并入现有主链路后半段。
```

最终架构一句话：

```text
Primitive 是确定性零件内核；
Base 是可扩展 CAD Grammar Dialect；
Skill 是 LLM 使用 Base 的分层指导机制；
G-CAD Core IR 是 LLM 与 Base 的隔离层；
Composition Dialect 是多 Base 组合的唯一通道；
RuntimeValue 是跨 Base 兼容的类型系统；
STEP + metadata 是与现有主链路的唯一合流点。
```

后续讨论应始终围绕这个架构展开，不要回到“LLM 直接写代码”或“每个零件一个 base”的方案。
