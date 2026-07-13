# SeekFlow 草图圆角与专业知识 Prompt 系统最终修复方案

## 一、最终目标与边界

本方案合并此前两份方案，并作出一个关键调整：

> **保留第一份方案中全部通用草图、圆角、圆弧、拓扑和验证层修复；删除“枞树形榫槽专用确定性生成器”方案；将原来涉及榫槽 Prompt 的部分，替换为可持续扩展、可版本管理、可动态路由的专业知识 Prompt 系统。**

最终系统形态为：

```text
用户工程意图
    ↓
L1 工程领域与能力路由
    ↓
选择通用 CAD Dialect
+ 选择专业知识包 Knowledge Pack
    ↓
Knowledge Resolver
    ├─ 解析版本
    ├─ 加载依赖
    ├─ 检查冲突
    └─ 编译适用知识章节
    ↓
L2A 工程建模计划
    ↓
L2B LLM 使用通用 GCAD 操作自主建模
    ↓
通用草图、拓扑、圆角和几何验证
    ↓
L2C 专业知识 Critic 审查
    ↓
知识驱动的局部 Repair
    ↓
确定性 CadQuery/OCC Runtime 执行
    ↓
几何后置验证与产物证明
```

明确边界：

* **LLM 仍负责计算榫槽控制点、直线、圆弧、切点、圆心、拉伸、阵列及布尔步骤。**
* Runtime 不包含 `fir_tree_groove` 专用几何生成算法。
* 不增加 `create_registered_profile("fir_tree_groove")`。
* 不增加 `fir_tree_joint.py` 专用生成器。
* 代码只提供通用、精确、可验证的草图和圆角操作。
* 专业知识通过版本化 Prompt Knowledge Pack 不断增加。

原修复方案关于圆角错误定位、失败开放、圆角半径不可行、圆弧和闭环验证缺失等判断继续保留。

上传的 KT787 文档则作为首个枞树形榫槽知识包的专业来源。文档给出了工作面、非工作面、齿距、齿厚、压力角、齿形角、楔角、R1～R4圆弧、间隙和对称约束等专业语义。

---

# 二、目前故障的根因

现有问题不能只靠修改 Prompt 解决，也不能只靠修复 OCC 调用解决。它由四个层级叠加产生。

## 1. 专业知识层错误

当前全局 L2 Prompt 将特定榫槽建模知识硬编码为：

* 固定24点；
* 左右各12点；
* 对所有内部顶点统一倒圆；
* 固定 `R=1.5 mm`；
* 固定顶点索引；
* 固定槽数；
* 固定阵列半径；
* 固定拉伸深度。

这既不符合文档中的专业参数体系，也无法扩展到其他齿形、燕尾槽、齿轮、叶片或机匣结构。

## 2. 语义寻址层错误

`fillet_sketch` 使用：

```python
at_vertex_index
```

定位圆角目标。

但 LLM 认为的“第5个点”和 OCC 重建后的 `wire.Vertices()[5]` 没有稳定关系。以下操作都可能改变拓扑顺序：

* 轮廓闭合；
* 顺逆时针反转；
* Wire 起始点改变；
* 圆弧插入；
* Face 重建；
* Boolean 或 healing；
* 多 Wire 排序。

所以会出现：

* 不该圆角的点被选中；
* 应该圆角的点没有被选中；
* 同一份 GCAD 多次执行结果不稳定。

## 3. 几何可行性层错误

原 Prompt 给出的多个短边无法容纳两端统一的 `R=1.5 mm` 圆角。

对直线—直线圆角：

[
t=R\cot\frac{\theta}{2}
]

同一条边两端均圆角时必须满足：

[
t_{\mathrm{start}}+t_{\mathrm{end}}
<L-\varepsilon
]

旧24点示例中至少有多条边违反该条件。也就是说，某些圆角在进入 OCC 前就已经数学不可行。

## 4. Runtime 失败策略错误

当前圆角失败后保留原尖角轮廓并继续：

```text
圆角失败
→ warning
→ keeping original profile
→ 拉伸继续
→ 布尔继续
→ 整体任务可能显示完成
```

这导致“该圆角没有圆角，但系统仍声明成功”。

---

# 三、最终设计原则

## 原则一：专业知识属于 Knowledge Pack

不得继续把榫槽知识写入：

* 全局 L2 Prompt；
* Web `main.py`；
* 通用 Dialect Prompt；
* 通用 OperationSpec；
* Runtime handler。

专业知识应作为动态加载的版本化知识包。

## 原则二：LLM 决定建模意图，Runtime 精确执行

LLM负责：

* 选择结构变体；
* 确定建模坐标系；
* 计算控制点；
* 计算线段和圆弧；
* 决定哪些位置圆角；
* 决定半径；
* 输出 GCAD。

Runtime负责：

* 验证点线弧关系；
* 精确建立曲线；
* 按语义 ID 定位；
* 检查半径可行性；
* 检查相切、闭合、自交；
* 严格执行失败策略。

## 原则三：不再以拓扑数组索引表达工程语义

禁止新 L2 输出：

```json
{
  "at_vertex_index": [3, 7, 9]
}
```

改为：

```json
{
  "corner_id": "right_upper_tooth_tip",
  "between_segments": [
    "right_upper_working_flank",
    "right_upper_nonworking_flank"
  ],
  "radius_mm": 2.4
}
```

## 原则四：设计圆弧与后处理圆角必须区分

枞树形榫槽中的 R1～R4属于设计截面的一部分。

优先建模方式应为：

```text
add_line_segment
+ add_arc_segment
+ add_line_segment
```

而不是：

```text
先画任意尖角折线
→ 再对大量顶点调用 fillet
```

`fillet_sketch` 应主要承担真正的草图修饰圆角；设计轮廓中的关键圆弧应尽可能显式构造。

## 原则五：专业知识应同时参与生成、审查和修复

同一 Knowledge Pack 应被用于：

1. L1 路由；
2. L2A 建模计划；
3. L2B GCAD 生成；
4. L2C 专业审查；
5. Repair 局部修复。

不能只在生成 Prompt 中出现一次。

---

# 四、通用草图数据模型重构

## 1. 新增语义化 Profile Graph

新增文件：

```text
generative_cad/
└── dialects/
    └── sketch_profile/
        └── profile_graph.py
```

建议核心模型：

```python
class ProfileVertex(BaseModel):
    vertex_id: str
    x_mm: float
    y_mm: float
    engineering_role: str | None = None
    tags: set[str] = set()


class ProfileEdge(BaseModel):
    edge_id: str
    kind: Literal["line", "arc"]
    start_vertex_id: str
    end_vertex_id: str
    engineering_role: str | None = None
    tags: set[str] = set()


class ProfileWire(BaseModel):
    wire_id: str
    ordered_edge_ids: list[str]
    closed: bool = False


class ProfileGraph(BaseModel):
    vertices: dict[str, ProfileVertex]
    edges: dict[str, ProfileEdge]
    wires: dict[str, ProfileWire]
```

这不是榫槽专用结构，而是所有二维工程草图共用的语义拓扑层。

适用对象包括：

* 榫槽；
* 燕尾槽；
* 齿轮齿廓；
* 叶片截面；
* 焊接坡口；
* 壳体开口；
* 密封篦齿；
* 轴肩和退刀槽。

---

## 2. 扩展通用点和线操作

原来的点坐标需要增加稳定语义 ID。

示例：

```json
{
  "operation": "add_line_segment",
  "params": {
    "segment_id": "right_upper_working_flank",
    "engineering_role": "working_flank",
    "start": {
      "point_id": "right_upper_root_tangent",
      "x_mm": -8.2,
      "y_mm": 5.4
    },
    "end": {
      "point_id": "right_upper_tip_tangent",
      "x_mm": -5.1,
      "y_mm": 7.2
    }
  }
}
```

要求：

* `point_id`在当前 Profile 内唯一；
* `segment_id`唯一；
* 后续操作只能引用语义 ID；
* 坐标允许由 LLM 计算；
* Runtime 不替 LLM推导榫槽结构。

---

# 五、`fillet_sketch@2.0.0` 通用圆角接口

## 1. 参数模型

```python
class SketchFilletTarget(BaseModel):
    corner_id: str
    between_segments: tuple[str, str]
    radius_mm: float = Field(gt=0)

    expected_convexity: Literal[
        "convex",
        "concave",
        "either",
    ] = "either"

    engineering_role: str | None = None
    required: bool = True


class FilletSketchV2Params(BaseModel):
    wire_id: str
    targets: list[SketchFilletTarget] = Field(min_length=1)

    strict: bool = True
    tolerance_mm: float = Field(default=1e-5, gt=0)
```

示例：

```json
{
  "operation": "fillet_sketch",
  "operation_version": "2.0.0",
  "params": {
    "wire_id": "groove_profile",
    "targets": [
      {
        "corner_id": "right_upper_tooth_tip",
        "between_segments": [
          "right_upper_working_flank",
          "right_upper_nonworking_flank"
        ],
        "radius_mm": 2.4,
        "expected_convexity": "concave",
        "engineering_role": "M_B4",
        "required": true
      }
    ],
    "strict": true
  }
}
```

## 2. V1 迁移策略

旧版：

```text
fillet_sketch@1.0.0
```

处理策略：

* 标记 deprecated；
* 仅允许读取旧测试资产；
* 新 L2 Prompt 禁止输出；
* 一个版本周期后删除；
* Auto Fixer 不应把语义圆角降级为索引圆角。

---

# 六、圆角执行算法修复

## 1. 目标定位

不得：

```python
wire.Vertices()[idx]
```

应：

1. 根据 `wire_id`取得指定 Wire；
2. 根据两个 `segment_id`取得相邻边；
3. 检查两边是否共享唯一顶点；
4. 该共享顶点即目标角点；
5. 验证 `corner_id`与拓扑一致；
6. 验证凹凸性是否符合预期。

若两个 segment：

* 不相邻；
* 共享多个顶点；
* 属于不同 Wire；
* 已被圆弧替换；
* 找不到；

则必须返回结构化错误。

---

## 2. 圆角可行性预检

新增：

```text
sketch_profile/fillet_solver.py
```

对于直线—直线角点：

```python
trim_length = radius_mm / tan(interior_angle_rad / 2.0)
```

对每条共享边汇总两端圆角的占用长度：

```python
required_length = start_trim + end_trim

if required_length >= edge_length - tolerance:
    raise FilletInfeasibleError(...)
```

错误结构：

```json
{
  "code": "FILLET_SHARED_EDGE_TOO_SHORT",
  "wire_id": "groove_profile",
  "edge_id": "right_lower_short_flank",
  "corner_ids": [
    "right_lower_tip",
    "right_lower_root"
  ],
  "available_mm": 1.581139,
  "required_mm": 2.581139,
  "suggested_max_radius_mm": 0.918861
}
```

注意：

* Runtime 可以给出数学上可行的最大值；
* Runtime 不得自行将用户半径改成最大值；
* 应将错误交给 LLM Repair 或用户澄清。

---

## 3. 分目标构造与状态检查

不要将20个角一次性送入一个不可诊断的 `fillet2D` 构造器。

推荐方式：

```text
预检全部目标
    ↓
按拓扑相关性分组
    ↓
执行一个或一个兼容组
    ↓
检查Builder状态
    ↓
更新ProfileGraph
    ↓
继续下一组
```

若直接调用 OCP：

```python
builder.Status()
builder.NbFillet()
builder.FilletEdges()
```

必须逐项检查。

返回结果应包含：

```python
class FilletExecutionResult(BaseModel):
    corner_id: str
    requested_radius_mm: float
    actual_radius_mm: float | None

    success: bool
    status_code: str

    generated_edge_ids: list[str]
    removed_vertex_id: str | None

    tangent_to_first: bool | None
    tangent_to_second: bool | None
```

---

## 4. 圆角失败必须失败关闭

修改通用处理逻辑：

```python
try:
    result = apply_fillet(...)
except Exception as exc:
    if node.required or node.degradation_policy == "fail":
        raise RequiredOperationFailed(
            operation="fillet_sketch",
            node_id=node.node_id,
            cause=exc,
        ) from exc

    ctx.warnings.append(...)
    return original_profile
```

禁止：

```text
required=true
+ 圆角失败
+ 保留尖角
+ 任务继续成功
```

只有同时满足：

```json
{
  "required": false,
  "degradation_policy": "warn"
}
```

才允许退化。

---

# 七、显式圆弧操作修复

榫槽 R1～R4应优先通过通用 `add_arc_segment` 创建，因此该操作必须精确。

## 1. 新参数模型

```python
class AddArcSegmentV2Params(BaseModel):
    arc_id: str

    start_vertex_id: str
    end_vertex_id: str

    start: Point2D
    end: Point2D
    center: Point2D

    radius_mm: float = Field(gt=0)

    direction: Literal["cw", "ccw"]
    sweep: Literal["minor", "major"]

    engineering_role: str | None = None

    tangent_to_previous: bool = False
    tangent_to_next: bool = False

    tolerance_mm: float = 1e-5
```

## 2. 必须验证

[
\left||P_s-C|-R\right|<\varepsilon
]

[
\left||P_e-C|-R\right|<\varepsilon
]

并检查：

* 当前草图末点等于声明 start；
* start 和 end 不重合；
* 圆心不与端点重合；
* 方向与 sweep 一致；
* 圆弧不是退化弧；
* 圆弧与前后边的切向满足要求；
* 创建后的真实圆心和真实半径与输入一致。

不能继续只根据圆心算一个半径，然后调用：

```python
radiusArc(end, signed_radius)
```

而忽略声明的圆心。

---

# 八、其他草图 Runtime 必修问题

## 1. 修复 `polyline_points` 丢失首点

修改为：

```python
if not accumulated_points:
    accumulated_points.extend(new_points)
else:
    if distance(
        accumulated_points[-1],
        new_points[0],
    ) > tolerance:
        raise ProfileContinuityError(...)

    accumulated_points.extend(new_points[1:])
```

否则建立语义点映射后会出现整体偏移。

## 2. 修复 `close_profile` 假关闭

禁止捕获异常后直接：

```python
closed = True
```

应验证：

```python
wires = wp.wires().vals()

if len(wires) != 1:
    raise ProfileTopologyError(...)

wire = wires[0]

if not wire.IsClosed():
    raise ProfileNotClosedError(...)
```

还需要检查：

* 首尾间距；
* 边顺序连续；
* 无孤立边；
* 无重复边；
* 无零长度边；
* 无自交。

## 3. 禁止默认 `wires[0]`

多 Wire 情况必须显式传入 `wire_id`。

如果没有 `wire_id`：

* 单 Wire 可以自动解析；
* 多 Wire 必须报错；
* 不得根据 OCC 返回顺序选择第一个。

---

# 九、草图后置条件体系

新增：

```text
sketch_profile/postconditions.py
```

## 1. 通用 Profile Postconditions

```text
PROFILE_HAS_SINGLE_EXPECTED_WIRE
PROFILE_IS_CLOSED
PROFILE_HAS_NO_SELF_INTERSECTION
PROFILE_HAS_NO_ZERO_LENGTH_EDGE
PROFILE_HAS_NO_DUPLICATE_CONSECUTIVE_VERTEX
PROFILE_ORIENTATION_MATCHES_EXPECTATION
PROFILE_AREA_IS_POSITIVE
```

## 2. 圆角 Postconditions

```text
FILLET_TARGET_COUNT_MATCHES
FILLET_RADIUS_MATCHES
FILLET_IS_TANGENT_TO_BOTH_NEIGHBOURS
FILLET_REMOVED_EXPECTED_CORNER
FILLET_DID_NOT_MODIFY_NON_TARGET_CORNERS
FILLET_PROFILE_REMAINS_CLOSED
FILLET_PROFILE_REMAINS_NON_SELF_INTERSECTING
```

## 3. 圆弧 Postconditions

```text
ARC_CENTER_MATCHES
ARC_RADIUS_MATCHES
ARC_DIRECTION_MATCHES
ARC_SWEEP_MATCHES
ARC_ENDPOINTS_MATCH
ARC_TANGENCY_MATCHES
```

每个检查应返回结构化报告，而不是单一布尔值。

---

# 十、专业知识 Prompt 系统架构

## 1. 新目录

建议新增：

```text
generative_cad/
└── knowledge/
    ├── __init__.py
    ├── schemas.py
    ├── registry.py
    ├── resolver.py
    ├── compiler.py
    ├── conflict_checker.py
    ├── token_budget.py
    ├── source_provenance.py
    └── packs/
        ├── mechanical/
        │   ├── generic_sketching/
        │   ├── robust_fillet/
        │   ├── tangent_arc_construction/
        │   └── symmetric_profile/
        └── turbomachinery/
            ├── core/
            ├── turbine_disc/
            ├── fir_tree_joint/
            └── fir_tree_groove_kt787_figure_2_4/
```

每个知识包：

```text
manifest.yaml
overview.md
terminology.yaml
topology.yaml
parameters.yaml
construction_strategy.md
operation_mapping.yaml
geometry_rules.yaml
self_checks.yaml
conflicts.yaml
references.yaml
examples/
anti_examples/
```

---

## 2. Knowledge Pack Manifest

```python
class KnowledgePackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: str
    title: str

    engineering_domain: str
    object_types: list[str]
    feature_types: list[str]

    trigger_terms: list[str]
    negative_trigger_terms: list[str]

    required_dialects: list[str]
    optional_dialects: list[str]

    dependencies: list["KnowledgeDependency"]
    conflicts_with: list[str]

    applicable_when: list[str]
    not_applicable_when: list[str]

    source_documents: list["KnowledgeSource"]

    priority: int

    status: Literal[
        "draft",
        "reviewed",
        "validated",
        "deprecated",
    ]
```

## 3. 知识规则模型

```python
class KnowledgeRule(BaseModel):
    rule_id: str

    severity: Literal[
        "hard",
        "strong_preference",
        "heuristic",
        "informational",
    ]

    statement: str
    rationale: str

    applies_to: list[str]
    source_refs: list[str]
```

必须区分：

* 强制工程规则；
* 推荐建模策略；
* 经验规则；
* 背景知识。

不能把所有文本都作为同等级 Prompt 内容。

---

# 十一、KT787 榫槽专业知识包

建议首个具体知识包：

```text
skill_id:
turbomachinery.fir_tree_groove.kt787.figure_2_4

version:
1.0.0
```

## 1. 专业参数语义

文档知识包应包含：

| 文档符号        | 规范字段                      | 工程含义         |
| ----------- | ------------------------- | ------------ |
| `MM_N`      | `groove_count`            | 涡轮盘榫槽个数      |
| `MM_A`      | `broach_angle_deg`        | 榫槽中心面和盘子午面夹角 |
| `M_R1`      | `reference_radius_mm`     | 第一齿节线基准径向位置  |
| `M_R2`      | `groove_depth_mm`         | 槽底到颈部深度      |
| `M_W3`      | `neck_width_mm`           | 颈部两节点之间宽度    |
| `M_W1`      | `tooth_pitch_mm`          | 同侧相邻齿节点间距    |
| `M_W2`      | `tooth_thickness_mm`      | 节线上齿厚        |
| `M_H1`      | `root_height_mm`          | 齿根高度         |
| `M_H2`      | `tooth_top_height_mm`     | 齿顶相对节线高度     |
| `M_A1`      | `wedge_angle_deg`         | 两条节线夹角       |
| `M_A2`      | `tooth_form_angle_deg`    | 工作面与非工作面夹角   |
| `M_A3`      | `pressure_angle_deg`      | 工作面与节线法向夹角   |
| `M_B1～M_B4` | 四类圆弧半径                    | 不同齿端、齿根或过渡圆弧 |
| `LM_WW`     | `nonworking_clearance_mm` | 非工作面配合间隙     |

这些参数来自文档的关键参数表和拓扑图。

## 2. 知识包不得包含

禁止包含：

* 固定24个坐标点；
* 固定半宽7.5、6.5、3.5；
* 固定 `R=1.5`；
* 固定圆角顶点索引；
* 固定60槽；
* 固定250 mm阵列半径；
* 固定80 mm拉伸；
* 某一组只能生成一个尺寸的 GCAD。

知识包存储的是建模知识，不是最终几何。

---

# 十二、KT787 知识包的核心规则

## 1. 拓扑规则

```yaml
topology_rules:
  - rule_id: fir_tree.centerline_symmetry
    severity: hard
    statement: >
      榫槽左右轮廓必须关于槽中心线严格对称。
      应先生成一侧语义轮廓，再通过通用镜像操作得到另一侧。

  - rule_id: fir_tree.lines_and_tangent_arcs
    severity: hard
    statement: >
      榫槽由具有工程语义的工作面、非工作面、
      齿端圆弧、齿根圆弧和底部过渡圆弧组成，
      不是任意锯齿折线。

  - rule_id: fir_tree.no_global_fillet
    severity: hard
    statement: >
      禁止对全部内部顶点统一倒圆。
      只允许在设计规定的圆弧角色位置创建圆弧或圆角。

  - rule_id: fir_tree.distinct_arc_classes
    severity: hard
    statement: >
      M_B1、M_B2、M_B3、M_B4是不同工程圆弧类别，
      除非用户明确给出相等值，不得合并为一个公共半径。
```

## 2. 参数规则

```yaml
parameter_rules:
  - rule_id: fir_tree.pressure_angle
    severity: hard
    statement: >
      M_A3控制工作面方向，不得将其用作整个轮廓旋转角。

  - rule_id: fir_tree.tooth_form_angle
    severity: hard
    statement: >
      M_A2控制工作面与非工作面之间的齿形角。

  - rule_id: fir_tree.wedge_angle
    severity: hard
    statement: >
      M_A1控制节线关系，不得与M_A2或M_A3混用。

  - rule_id: fir_tree.nonworking_clearance
    severity: hard
    statement: >
      LM_WW仅施加于指定非工作配合面，
      禁止对整个轮廓进行全局偏置。
```

---

# 十三、处理文档中的结构冲突

文档中同时出现：

* “2对榫齿、大圆角半圆形榫齿”；
* “三齿梯形榫头连接形式”。

图2-4和图3-2又表现出特定的 R1～R4拓扑关系。

不能把这些内容混合到同一个模糊 Prompt 中。

知识包应明确记录：

```yaml
known_conflicts:
  - conflict_id: kt787.tooth_topology_variant

    interpretation_a:
      id: two_pair_large_radius
      evidence:
        - "2对榫齿"
        - "大圆角"
        - "半圆形榫齿"

    interpretation_b:
      id: three_tooth_trapezoidal
      evidence:
        - "三齿梯形榫头连接形式"

    selected_interpretation:
      id: figure_2_4_topology

    resolution_policy:
      require_clarification_when:
        - user_requests_three_tooth
        - user_requests_trapezoidal
        - user_supplies_conflicting_parameters
```

后续可分别建立：

```text
fir_tree_groove.kt787.figure_2_4
fir_tree_groove.three_tooth_trapezoidal
fir_tree_groove.two_pair_semicircular
fir_tree_groove.hb5965
```

---

# 十四、L1 知识路由修复

## 1. L1 只读取知识目录摘要

L1不需要完整专业内容，只需看到：

```json
{
  "skill_id": "turbomachinery.fir_tree_groove.kt787.figure_2_4",
  "version": "1.0.0",
  "title": "KT787 枞树形涡轮盘榫槽建模知识",
  "object_types": ["turbine_disc"],
  "feature_types": [
    "fir_tree_groove",
    "blade_attachment_slot"
  ],
  "trigger_terms": [
    "枞树形榫槽",
    "fir-tree groove",
    "turbine disc slot"
  ],
  "required_dialects": [
    "sketch_profile",
    "composition"
  ]
}
```

L1输出：

```json
{
  "selected_domain_skills": [
    {
      "skill_id": "turbomachinery.fir_tree_groove.kt787.figure_2_4",
      "skill_version": "1.0.0",
      "reason": "The request requires a fir-tree attachment groove in a turbine disc."
    }
  ]
}
```

## 2. 禁止服务器补默认版本

删除类似：

```python
if not skill.get("skill_version"):
    skill["skill_version"] = "1.0"
```

知识版本必须是路由决策的一部分。

## 3. 选择结果验证

新增：

```python
validate_knowledge_selection(
    selected_skills,
    registry,
    selected_dialects,
)
```

检查：

* ID存在；
* 版本存在；
* 状态允许使用；
* 依赖完整；
* 无冲突；
* required Dialect已选择；
* 当前对象类型适用。

---

# 十五、L2 分成三个专业阶段

## L2A：Engineering Modeling Plan

L2A只输出建模计划，不输出 GCAD。

```python
class EngineeringModelingPlan(BaseModel):
    object_type: str
    selected_variant: str

    knowledge_packs: list["KnowledgePackRef"]

    coordinate_system: "CoordinatePlan"
    resolved_parameters: list["ResolvedParameter"]
    unresolved_parameters: list["UnresolvedParameter"]

    topology_sequence: list["TopologyElement"]
    arc_roles: list["ArcRole"]

    symmetry_strategy: "SymmetryStrategy"
    construction_steps: list["ModelingStep"]

    expected_checks: list["ExpectedCheck"]
    assumptions: list["EngineeringAssumption"]
    clarification_questions: list["ClarificationQuestion"]
```

榫槽计划应明确表达：

```text
局部坐标系
→ 基准面与节线
→ 工作面
→ 非工作面
→ R1～R4圆弧
→ 一侧有序轮廓
→ 精确镜像
→ 闭合
→ 拉伸切刀
→ MM_A定向
→ MM_N阵列
→ 与盘体求差
```

## L2B：Raw GCAD Author

输入：

* 用户原始请求；
* L2A建模计划；
* Dialect Operation Contract；
* Usage Skill；
* 专业知识包；
* 正确示例；
* 反例；
* 空间约束。

LLM输出：

* 通用点；
* 通用线；
* 通用圆弧；
* 通用镜像；
* 通用拉伸；
* 通用阵列；
* 通用布尔。

不调用任何榫槽专用操作。

## L2C：Domain Critic

在 GCAD 通过基础 Schema 验证后，使用同一知识包审查。

```python
class DomainReviewReport(BaseModel):
    passed: bool

    satisfied_rule_ids: list[str]
    violated_rules: list["DomainIssue"]
    unresolved_rule_ids: list[str]

    repairable: bool
    requires_clarification: bool
```

榫槽 Critic 检查：

* 是否选定明确结构变体；
* 是否区分工作面和非工作面；
* 是否正确使用 `M_A1/M_A2/M_A3`；
* 是否存在 R1～R4角色；
* 是否错误统一圆角；
* 是否使用固定24点模板；
* 是否左右对称；
* 是否只在非工作面应用 `LM_WW`；
* `MM_N`是否控制槽数；
* `MM_A`是否控制方向；
* 是否存在未解释的硬编码尺寸。

---

# 十六、Prompt Compiler

## 1. Prompt 优先级

```text
P0 Safety and ABI
P1 GCAD Schema and Operation Contract
P2 Professional Hard Rules
P3 L2A Modeling Plan
P4 Dialect Usage Instructions
P5 Professional Construction Strategy
P6 Correct Examples
P7 Anti-examples
P8 Spatial Constraints
P9 User Request
```

冲突优先级：

```text
Safety
>
Schema / Operation Contract
>
Professional Hard Rule
>
Explicit User Dimension
>
Professional Strong Preference
>
Heuristic
>
Example
```

## 2. Token Budget

禁止：

```python
knowledge_text[:2000]
```

改为章节优先级：

```python
SECTION_PRIORITY = {
    "hard_rules": 100,
    "variant_conflicts": 98,
    "topology": 95,
    "parameter_semantics": 92,
    "operation_mapping": 88,
    "self_checks": 85,
    "anti_examples": 80,
    "construction_strategy": 75,
    "correct_examples": 60,
    "background": 20,
}
```

以下章节永远不得被截断：

* Hard Rules；
* 结构变体；
* 参数定义；
* 来源冲突；
* 自检规则；
* 适用范围。

---

# 十七、Repair 系统改造

## 1. Repair Prompt 新输入

```python
build_repair_prompt_v3(
    raw_document=...,
    validation_report=...,
    geometry_report=...,
    modeling_plan=...,
    selected_knowledge_packs=...,
    domain_review_report=...,
    repair_state=...,
)
```

## 2. 局部修复原则

Repair必须：

* 只修改违反规则的节点；
* 保留已验证的点、线、弧和参数；
* 不重新生成整个榫槽；
* 不将专业错误修成仅Schema正确；
* 不删除关键圆弧以绕过验证；
* 不擅自缩小半径；
* 半径不可行时优先修改相邻几何或要求澄清；
* 记录知识规则 ID 和变更原因。

## 3. Repair 例子

Domain Critic：

```json
{
  "rule_id": "fir_tree.no_global_fillet",
  "node_ids": ["fillet_all_corners"],
  "message": "The node applies a common radius to all interior corners."
}
```

Repair应改为：

* 删除全局圆角节点；
* 为 R1～R4各自建立显式圆弧或语义圆角目标；
* 不改变其他已通过的轮廓部分。

---

# 十八、文件级修改清单

## A. 通用草图和圆角

修改：

```text
generative_cad/dialects/sketch_profile/params.py
generative_cad/dialects/sketch_profile/handlers.py
generative_cad/dialects/sketch_profile/dialect.py
```

新增：

```text
generative_cad/dialects/sketch_profile/profile_graph.py
generative_cad/dialects/sketch_profile/fillet_solver.py
generative_cad/dialects/sketch_profile/postconditions.py
generative_cad/dialects/sketch_profile/topology_errors.py
```

任务：

1. 引入 point/edge/wire语义 ID；
2. 实现 `fillet_sketch@2.0.0`；
3. 实现 `add_arc_segment@2.0.0`；
4. 圆角可行性预检；
5. required失败关闭；
6. 实际半径验证；
7. G1相切验证；
8. 目标和非目标修改验证；
9. 修复 polyline首点；
10. 修复假关闭；
11. 禁止默认 `wires[0]`。

---

## B. 专业知识系统

新增：

```text
generative_cad/knowledge/schemas.py
generative_cad/knowledge/registry.py
generative_cad/knowledge/resolver.py
generative_cad/knowledge/compiler.py
generative_cad/knowledge/conflict_checker.py
generative_cad/knowledge/token_budget.py
generative_cad/knowledge/source_provenance.py
```

新增知识包：

```text
generative_cad/knowledge/packs/
└── turbomachinery/
    └── fir_tree_groove_kt787_figure_2_4/
```

---

## C. Prompt 与 Orchestrator

修改：

```text
generative_cad/skills/prompts.py
generative_cad/skills/schemas.py
generative_cad/skills/orchestrator.py
generative_cad/skills/authoring_context.py
```

任务：

1. 删除全局榫槽固定模板；
2. 删除固定24点；
3. 删除所有内部顶点统一圆角；
4. 删除固定参数；
5. L1加载知识目录；
6. L2实际加载已选知识包；
7. 新增 L2A；
8. 新增 L2C；
9. Repair加载专业知识；
10. Prompt统一由 Compiler生成。

---

## D. Web 服务

修改：

```text
app/text-to-cad/server/main.py
```

删除：

* `For fir-tree slot cutters...`硬编码；
* 专业知识字符串拼接；
* `skill_text[:2000]`；
* 缺失版本自动补 `"1.0"`。

改为：

```python
selection = orchestrator.route(...)
resolved_knowledge = knowledge_resolver.resolve(selection)
modeling_plan = orchestrator.create_modeling_plan(...)
prompt = prompt_compiler.compile_authoring_prompt(...)
raw_gcad = llm_author(...)
domain_report = domain_critic.review(...)
```

Web层不得知道“榫槽应该如何画”。

---

# 十九、明确删除原方案中的内容

下列原方案内容全部取消：

```text
geometry_primitives/turbomachinery/fir_tree_joint.py
sketch_profile/registered_profiles.py
create_registered_profile@1.0.0
fir_tree_groove_v2 专用几何实现
two_pair_semicircular_kt787 专用生成函数
```

同时取消以下规则：

```text
LLM只提供榫槽参数
→ 专用程序生成直线和圆弧
```

替换为：

```text
LLM读取专业知识包
→ 输出通用点线弧GCAD
→ Runtime通用验证与执行
→ Domain Critic专业审查
```

---

# 二十、实施优先级

## P0：立即止血

优先修改：

1. required圆角失败必须中止；
2. 越界索引不得静默跳过；
3. 多 Wire禁止默认取第一个；
4. `close_profile`必须真实验证；
5. `add_arc_segment`验证圆心和半径；
6. 修复 polyline首点丢失；
7. 旧24点 `R=1.5`示例必须预检失败。

这一阶段即使 Knowledge Pack尚未完成，也能阻止错误模型伪成功。

## P1：语义草图 API

完成：

* `ProfileGraph`；
* point/segment/wire ID；
* `fillet_sketch@2`；
* `add_arc_segment@2`；
* 圆角可行性预检；
* 后置验证。

## P2：Knowledge Pack 基础设施

完成：

* Registry；
* Manifest；
* Resolver；
* Conflict Checker；
* Token Budget；
* Source Provenance。

## P3：L2A/L2B/L2C

完成：

* 工程计划；
* GCAD Author；
* Domain Critic；
* 结构化报告。

## P4：Repair 与审计

完成：

* 知识驱动 Repair；
* Prompt Hash；
* Knowledge Pack ID/version/hash；
* Domain Review Report；
* 修改追踪。

## P5：扩展其他专业知识

验证系统可以在不修改全局 Prompt 和 Runtime 的情况下增加：

* 燕尾槽；
* 齿轮；
* 叶片截面；
* 篦齿封严；
* 轴承座；
* 压力容器接管；
* 焊接坡口。

---

# 二十一、验收测试

## 1. 通用圆角测试

必须通过：

1. 轮廓起点循环移动后，圆角目标不变；
2. 顺时针改为逆时针后，圆角目标不变；
3. 多 Wire未给 `wire_id` 必须失败；
4. 非目标角点不得改变；
5. 每个目标只生成一个预期圆弧；
6. 超大半径在进入 OCC 前失败；
7. 共享短边两端圆角正确计算占用长度；
8. required圆角失败导致任务失败；
9. 实际圆角半径在公差内；
10. 圆弧与两侧边 G1相切；
11. 圆角后轮廓保持闭合；
12. 圆角后无自交；
13. OCC失败不能保留尖角并声明成功。

## 2. 显式圆弧测试

1. start与当前末点不一致时失败；
2. start、end到center距离不一致时失败；
3. 真实半径与输入不一致时失败；
4. CW/CCW正确；
5. minor/major正确；
6. 声明相切但实际不相切时失败；
7. 圆弧插入后 ProfileGraph拓扑正确。

## 3. Knowledge Registry 测试

1. 新知识包无需修改Python列表即可发现；
2. 重复ID拒绝；
3. 重复版本拒绝；
4. 缺依赖拒绝；
5. 冲突包拒绝；
6. deprecated默认不选择；
7. Knowledge Pack hash稳定。

## 4. Prompt 编译测试

1. 全局 Prompt不含 fir-tree；
2. 普通法兰请求不出现榫槽知识；
3. 榫槽请求才加载 KT787包；
4. Hard Rules不会因Token预算被截断；
5. Prompt记录 Skill ID/version/hash；
6. Web层没有榫槽硬编码。

## 5. L2A 测试

榫槽请求必须识别：

* 结构变体；
* 局部坐标系；
* 中心线；
* 工作面；
* 非工作面；
* R1～R4；
* 对称策略；
* `M_A1/M_A2/M_A3`；
* `MM_A/MM_N`；
* 必要自检。

不得输出：

* 固定24点；
* 统一1.5 mm；
* 所有内部点圆角；
* 固定60槽；
* 固定80 mm拉伸。

## 6. L2B 测试

必须：

* 只使用通用注册操作；
* 输出有序点、线、圆弧；
* 使用语义 ID；
* 每类圆弧独立半径；
* 左右通过通用镜像操作建立；
* 不调用任何榫槽专用操作。

## 7. Domain Critic 测试

故意输入以下错误：

* 对全部角统一圆角；
* 工作面/非工作面颠倒；
* 未使用压力角；
* R3缺失；
* 左右不对称；
* `LM_WW`应用于整体轮廓；
* `MM_N`未控制阵列数；
* 固定24点模板。

Critic必须输出：

* 具体 `rule_id`；
* 相关节点；
* 严重程度；
* 是否可自动修复；
* 是否需要用户澄清。

## 8. 旧问题回归测试

给定旧24点和 `R=1.5`：

```text
必须返回 FILLET_SHARED_EDGE_TOO_SHORT
不得调用 OCC 后静默退化
不得导出为合格模型
```

---

# 二十二、代码 Agent 可直接执行的总任务

```text
重构 SeekFlow Generative CAD 的草图圆角系统和专业知识
Prompt 系统。

严格禁止实现任何 fir-tree groove 专用确定性几何生成器。
榫槽控制点、直线、圆弧、切点、圆心、拉伸、阵列及布尔
步骤继续由 LLM 使用通用 GCAD Dialect 生成。

第一部分：通用草图和圆角

1. 为二维草图增加稳定的 point_id、segment_id、wire_id 和
   engineering_role。

2. 实现 ProfileGraph，禁止依赖 OCC 顶点数组索引表达工程语义。

3. 实现 fillet_sketch@2.0.0：
   - 使用 wire_id；
   - 使用 between_segments；
   - 每个目标独立 radius；
   - 支持预期凹凸性；
   - required失败关闭。

4. 对圆角执行几何可行性预检，检查共享短边的两端切线长度预算。

5. 圆角后验证：
   - 数量；
   - 半径；
   - 相切性；
   - 闭合性；
   - 自交；
   - 非目标角点未变化。

6. 实现 add_arc_segment@2.0.0，严格检查：
   - start/end/center；
   - radius；
   - CW/CCW；
   - major/minor；
   - 与相邻边相切。

7. 修复：
   - polyline首点丢失；
   - close_profile假关闭；
   - 多Wire默认wires[0]；
   - 越界索引静默跳过；
   - 圆角失败后保留尖角继续执行。

第二部分：专业知识 Prompt 系统

8. 删除 prompts.py 和 Web main.py 中全部涡轮盘及枞树形
   榫槽硬编码知识，包括：
   - 固定24点；
   - 固定R=1.5；
   - 全部内部点圆角；
   - 固定索引；
   - 固定60槽；
   - 固定250半径；
   - 固定80拉伸。

9. 建立版本化 ProfessionalKnowledgePack Registry，包括：
   - applicability；
   - topology rules；
   - parameter semantics；
   - construction strategy；
   - operation guidance；
   - self checks；
   - examples；
   - anti-examples；
   - source provenance；
   - known conflicts。

10. 创建知识包：
    turbomachinery.fir_tree_groove.kt787.figure_2_4@1.0.0

11. 知识包只描述专业知识，不包含专用生成代码和固定坐标。

12. L1必须真正看到Knowledge Pack目录，并输出精确版本。
    禁止服务器自动补版本。

13. 引入：
    - L2A Engineering Modeling Plan；
    - L2B Raw GCAD Author；
    - L2C Domain Critic。

14. L2B必须根据Knowledge Pack使用通用点、线、圆弧、镜像、
    拉伸、阵列和布尔操作自主生成榫槽。

15. Domain Critic检查：
    - 工作面/非工作面；
    - R1-R4；
    - M_A1/M_A2/M_A3；
    - 对称性；
    - MM_A/MM_N；
    - LM_WW；
    - 禁止全角统一圆角；
    - 禁止固定24点模板。

16. Repair Prompt必须同时加载：
    - Modeling Plan；
    - Selected Knowledge Packs；
    - Domain Review Report；
    - 通用几何验证报告。

17. Repair只能修改违规局部节点，不得重新生成整个模型，不得
    通过删除专业特征绕过验证。

18. Prompt必须由统一PromptCompiler编译。
    Web main.py不得包含任何专业建模知识。

19. 增加完整测试：
    - semantic sketch；
    - fillet feasibility；
    - explicit arc；
    - fail-closed；
    - registry；
    - routing；
    - prompt snapshot；
    - L2A；
    - L2B；
    - critic；
    - repair；
    - old 24-point regression。
```

---

# 最终效果

修复后的系统不再是：

```text
不断扩大全局 Prompt
+ LLM手工数顶点
+ OCC随机圆角
+ 失败后保留尖角
```

也不是：

```text
每增加一个专业零件
→ 写一个专用几何生成器
```

而是：

```text
通用语义 CAD 操作
+
版本化专业知识包
+
动态知识路由
+
分阶段工程规划
+
LLM自主几何建模
+
通用几何严格验证
+
专业知识 Critic
+
知识驱动局部 Repair
```

这既能解决当前圆角错位、遗漏和静默失败问题，也能满足后续不断添加专业知识、由 LLM根据专业 Prompt完成不同工业结构建模的长期目标。
