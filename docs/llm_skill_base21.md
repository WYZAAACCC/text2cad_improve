# SeekFlow Generative CAD 非 Primitive 链路工程整改文档 V1.0

## 面向 Claude Code 的实现规格书

## 0. 文档定位

本文档目标不是继续做问题复述，而是把我们前面讨论出的结论整理成一套**可落地、可编码、可测试、可分阶段合并**的工程实施方案。

当前系统的正确方向是明确的：LLM 不应直接充当 CAD 编译器，而应只负责抽取意图、组件、约束、语义特征；代码侧负责确定性接线、约束求解、几何执行、校验、修复和导出。开发者文档也把这一原则列为核心设计原则，并描述了 Stage 0 空间前端、分阶段 LLM 生成、raw assembler、auto fixer、validation、Canonical IR、runtime dialect 和 STEP/SolidWorks 输出的分层架构。

但现有 v6.2 仍然有几个结构性断点：

1. **孔特征 IR 语义不足**：孔只用 `axis + position_mm + through_all` 描述，无法可靠表达目标面、局部坐标系、孔作用域、基准角度、先后阶段。
2. **几何 handler 与 op contract 不一致**：例如 `cut_hole_pattern_linear` 参数允许 X/Y/Z，但实现仍固定在 XY 平面打 Z 向孔；普通 `cut_hole` 虽支持 X/Y/Z，但对二维 `position_mm` 的解释仍存在歧义。([GitHub][1])
3. **assembler 仍有“最后一个 solid 即 root”的隐式策略**：这能提高成功率，但会隐藏“孔/槽/阵列特征没有成为最终组件输出”的问题。raw assembler 代码说明其目标是系统侧确定性填充 wiring，并把组件最后一个 solid 提升为 root。([GitHub][2])
4. **空间前端与 runtime placement 没完全闭环**：Stage 0 默认关闭，且 composition 的 `handle_place_component` 当前只读取 `position_mm`，没有优先消费 `ctx.spatial_placements`。([GitHub][3])
5. **几何内核高级能力不足**：loft 仍使用 CadQuery `.loft()` 封装处理多截面放样，对圆→矩形→圆这类异拓扑截面不稳定；开发者文档中 g8/g23 也明确归因为 loft/OCCT 限制。([GitHub][4]) 
6. **布尔降级策略会改变几何**：composition 中的 tolerance-expanded fuse 实际采用 `b.translate((margin, margin, margin))` 后再 fuse，这不是“容差扩展”，而是改变零件位置。([GitHub][5])
7. **成功标准过低**：STEP 文件能导出不等于模型正确。文档中已经列出 `MULTI_SOLID`、负体积、空 solid 等异常几何。

因此，本次整改目标应定义为：

> 把 SeekFlow Generative CAD 从“LLM 生成能跑通的 BRep 脚本”升级为“语义约束驱动、确定性接线、几何可验证、失败可定位、修复可控的 CAD compiler”。

---

# 1. 总体目标架构

## 1.1 目标流水线

```text
User Natural Language
    ↓
Stage 0: Mechanical Object + Spatial Intent Frontend
    ↓
Semantic CAD Plan
    ├─ ComponentGraph
    ├─ FeatureIntentGraph
    ├─ SpatialConstraintGraph
    ├─ Manufacturing/ToleranceProfile
    └─ ClarificationQuestions
    ↓
Deterministic CAD Compiler
    ├─ Feature DAG Wiring
    ├─ Semantic Anchor Resolution
    ├─ Hole / Face / Datum Resolution
    ├─ Spatial Placement Resolution
    └─ Geometry Feasibility Preflight
    ↓
Canonical IR v2
    ↓
Runtime Dialect Execution
    ├─ Robust Hole Engine
    ├─ Native Loft/Sweep Engine
    ├─ Safe Boolean Engine
    ├─ Shape Healing
    └─ Geometry Postcondition Gate
    ↓
STEP + metadata + spatial_contract + validation_report
    ↓
Optional SolidWorks/NX Import Validation
```

## 1.2 核心原则

### 原则 A：LLM 不允许写 concrete node wiring

LLM 可以表达：

```json
{
  "feature_role": "bolt_circle_on_top_flange",
  "after_feature": "center_bore",
  "target_component": "flange_top"
}
```

LLM 不允许表达：

```json
{
  "inputs": [{"node": "ft_cut_hole_ref", "output": "body"}]
}
```

原因：g14 这类错误已经证明，让 LLM 自由写 node ref 会产生不存在引用、错误顺序和错误 root。

---

### 原则 B：所有孔必须绑定目标面 / 基准 / 局部坐标系

禁止再让新 prompt 生成这种不完整孔：

```json
{
  "axis": "Y",
  "position_mm": [50, 30]
}
```

必须生成：

```json
{
  "target_face": "front",
  "center_uv_mm": [50, 30],
  "normal_axis": "+Y",
  "origin_mode": "face_center",
  "through_mode": "through_all"
}
```

---

### 原则 C：几何 handler 不能 silent degrade 必需特征

现有多个 handler 在异常时返回原实体，这会造成“模型看起来成功，但孔/槽/布尔没做上”。例如 `handle_cut_hole` 和 `handle_cut_hole_pattern_linear` 失败后会 `_degrade` 并保留原 body。([GitHub][1])

整改后：

```text
required=True 的几何特征失败 → hard fail
required=False 的装饰性特征失败 → degrade allowed
布尔 union 丢失实体 → hard fail
孔/槽/中心孔失败 → hard fail
fillet/chamfer 失败 → 可 degrade
```

---

### 原则 D：几何导出必须通过 postcondition

最终成功条件必须改为：

```python
success = (
    canonical_valid
    and runtime_executed
    and geometry_postcheck_ok
    and step_export_ok
    and optional_sw_import_ok
)
```

而不是只看 STEP 文件存在。

---

# 2. 分阶段实施路线

## Phase 0：建立安全网，不改变生成能力

目标：先加测试和 gate，防止继续产出错误模型。

必须完成：

1. Geometry postcondition gate。
2. root terminal validator。
3. unresolved node ref hard fail。
4. degraded required feature hard fail。
5. hole semantic audit。
6. regression fixtures：g3、g8、g14、g17、g19、g22、g23、g24、g25、g26。

---

## Phase 1：孔系统重构

目标：解决你看到的“孔位置不对、顺序不对、打到不该打地方”的核心问题。

必须完成：

1. 新增 HolePlacementV2。
2. 新增 cut_hole_v2 / drill_hole_3d / hole_pattern_linear_v2 / hole_pattern_circular_v2。
3. 旧 cut_hole 只允许兼容旧 case，不再作为 prompt 首选。
4. 线性孔阵列真正支持 X/Y/Z 和目标面。
5. 圆周孔阵列支持 start angle、datum、target face。
6. 增加 cut_scope / feature_stage。

---

## Phase 2：空间前端闭环

目标：让 Stage 0 真的影响几何装配。

必须完成：

1. `ctx.spatial_placements` 被 `handle_place_component` 使用。
2. 多组件默认启用 deterministic spatial frontend。
3. 未解析 placement 不允许 identity fallback。
4. GeometrySpatialAudit 审计 world bbox，而不是 local bbox。

---

## Phase 3：几何内核增强

目标：解决 loft、sweep、boolean、薄壁、密集孔、复杂装配的稳定性。

必须完成：

1. native loft：统一采样异拓扑截面。
2. batch boolean cut：密集孔一次切，不逐孔切。
3. fuzzy fuse 替代 translate fuse。
4. thin wall preflight + tolerance profile。
5. shape healing + BRepCheck。
6. large STEP / SolidWorks import timeout 与诊断。

---

## Phase 4：Prompt 与人-LLM-代码分工重构

目标：让 LLM 输出更稳定，但不把确定性责任交给 LLM。

必须完成：

1. route prompt：先判断单体/装配/是否需要空间前端。
2. object graph prompt：抽取组件、面、孔、基准、空间关系。
3. feature sequence prompt：只写语义特征，不写 node wiring。
4. node params prompt：强制使用 v2 params。
5. repair prompt：只允许在 solver 给出的可行域内修改。
6. clarification prompt：只问会改变几何拓扑/孔基准/装配关系的问题。

---

# 3. 具体代码改造方案

## 3.1 新增语义几何基础模型

### 新文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/geometry_semantics.py
```

### 目标

统一定义 face、axis、datum、coordinate frame、feature scope、tolerance profile。

### 建议代码

```python
from __future__ import annotations

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class Axis3(str, Enum):
    POS_X = "+X"
    NEG_X = "-X"
    POS_Y = "+Y"
    NEG_Y = "-Y"
    POS_Z = "+Z"
    NEG_Z = "-Z"


class CanonicalFace(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    CUSTOM = "custom"


class OriginMode(str, Enum):
    FACE_CENTER = "face_center"
    PART_CENTER = "part_center"
    LOWER_LEFT = "lower_left"
    DATUM = "datum"


class ThroughMode(str, Enum):
    THROUGH_ALL = "through_all"
    BLIND = "blind"
    TO_NEXT = "to_next"
    UP_TO_FACE = "up_to_face"


class FeatureScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_component: str | None = None
    target_stage: str | None = None
    include_features: list[str] = Field(default_factory=list)
    exclude_features: list[str] = Field(default_factory=list)
    required: bool = True


class HolePlacementV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_face: CanonicalFace
    center_uv_mm: tuple[float, float]
    normal_axis: Axis3
    origin_mode: OriginMode = OriginMode.FACE_CENTER

    through_mode: ThroughMode = ThroughMode.THROUGH_ALL
    depth_mm: float | None = Field(default=None, gt=0)

    start_offset_mm: float = 0.0
    scope: FeatureScope = Field(default_factory=FeatureScope)

    @model_validator(mode="after")
    def check_depth(self):
        if self.through_mode == ThroughMode.BLIND and self.depth_mm is None:
            raise ValueError("blind hole requires depth_mm")
        return self


class CircularPatternPlacementV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_face: CanonicalFace
    center_uv_mm: tuple[float, float] = (0.0, 0.0)
    normal_axis: Axis3
    pcd_mm: float = Field(gt=0)
    count: int = Field(ge=1, le=512)
    start_angle_deg: float = 0.0
    angular_span_deg: float = 360.0
    datum_axis: Literal["U", "V"] = "U"
    origin_mode: OriginMode = OriginMode.FACE_CENTER
```

---

## 3.2 重构 sketch_extrude 参数模型

### 修改文件

```text
bases/sketch_extrude/models.py
```

当前 `CutHoleParams` 允许 `position_mm` 长度 2 或 3，`axis` 为 X/Y/Z；这正是孔语义混乱的来源之一。([GitHub][6])

### 新增模型

```python
from seekflow_engineering_tools.generative_cad.ir.geometry_semantics import (
    HolePlacementV2,
    CircularPatternPlacementV2,
    CanonicalFace,
    Axis3,
    OriginMode,
    ThroughMode,
    FeatureScope,
)


class CutHoleV2Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(gt=0)
    placement: HolePlacementV2


class DrillHole3DParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(gt=0)
    origin_mm: tuple[float, float, float]
    direction: tuple[float, float, float]
    through_mode: ThroughMode = ThroughMode.THROUGH_ALL
    depth_mm: float | None = Field(default=None, gt=0)
    counterbore_dia_mm: float | None = Field(default=None, gt=0)
    counterbore_depth_mm: float | None = Field(default=None, gt=0)
    countersink_angle_deg: float | None = Field(default=None, gt=0, le=179)
    scope: FeatureScope = Field(default_factory=FeatureScope)

    @model_validator(mode="after")
    def validate_direction_and_depth(self):
        x, y, z = self.direction
        if abs(x) + abs(y) + abs(z) < 1e-9:
            raise ValueError("direction vector cannot be zero")
        if self.through_mode == ThroughMode.BLIND and self.depth_mm is None:
            raise ValueError("blind drill_hole_3d requires depth_mm")
        return self


class CutHolePatternLinearV2Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hole_dia_mm: float = Field(gt=0)
    count_u: int = Field(ge=1, le=512)
    count_v: int = Field(ge=1, le=512)
    spacing_u_mm: float = Field(gt=0)
    spacing_v_mm: float = Field(gt=0)
    placement: HolePlacementV2


class CutCircularHolePatternV2Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hole_dia_mm: float = Field(gt=0)
    placement: CircularPatternPlacementV2
    through_mode: ThroughMode = ThroughMode.THROUGH_ALL
    depth_mm: float | None = Field(default=None, gt=0)
    scope: FeatureScope = Field(default_factory=FeatureScope)
```

### 旧模型处理

保留旧 `CutHoleParams`，但标记为 legacy：

```python
class CutHoleParams(BaseModel):
    """
    LEGACY ONLY.
    New LLM prompts must not emit this op except for backward compatibility.
    Use cut_hole_v2 instead.
    """
```

---

## 3.3 注册新 op

### 修改文件

```text
dialects/sketch_extrude/dialect.py
```

新增：

```python
OperationSpec(
    op="cut_hole_v2",
    op_version=1,
    input_types=["solid"],
    output_types=["solid"],
    params_model=CutHoleV2Params,
    required_default=True,
)

OperationSpec(
    op="drill_hole_3d",
    op_version=1,
    input_types=["solid"],
    output_types=["solid"],
    params_model=DrillHole3DParams,
    required_default=True,
)

OperationSpec(
    op="cut_hole_pattern_linear_v2",
    op_version=1,
    input_types=["solid"],
    output_types=["solid"],
    params_model=CutHolePatternLinearV2Params,
    required_default=True,
)

OperationSpec(
    op="cut_circular_hole_pattern_v2",
    op_version=1,
    input_types=["solid"],
    output_types=["solid"],
    params_model=CutCircularHolePatternV2Params,
    required_default=True,
)
```

同时在 prompt context 中隐藏旧 `cut_hole_pattern_linear`，或标记为 deprecated。

---

## 3.4 实现孔坐标解析器

### 新文件

```text
dialects/geometry_utils/hole_placement.py
```

### 目标

把 `target_face + center_uv + origin_mode` 转换成真实 3D 点和方向。

### 建议代码

```python
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from seekflow_engineering_tools.generative_cad.ir.geometry_semantics import (
    CanonicalFace,
    Axis3,
    OriginMode,
)


@dataclass(frozen=True)
class ResolvedHolePlacement:
    center_xyz: tuple[float, float, float]
    direction_xyz: tuple[float, float, float]
    plane: str
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]


def _unit(v):
    n = sqrt(sum(x * x for x in v))
    if n <= 1e-12:
        raise ValueError("zero vector")
    return tuple(x / n for x in v)


def resolve_face_hole_placement(placement, bbox) -> ResolvedHolePlacement:
    u, v = placement.center_uv_mm
    face = placement.target_face
    origin = placement.origin_mode

    if face == CanonicalFace.TOP:
        face_center = ((bbox.xmin + bbox.xmax) / 2, (bbox.ymin + bbox.ymax) / 2, bbox.zmax)
        direction = (0, 0, -1)
        plane = "XY"
        u_axis = (1, 0, 0)
        v_axis = (0, 1, 0)

    elif face == CanonicalFace.BOTTOM:
        face_center = ((bbox.xmin + bbox.xmax) / 2, (bbox.ymin + bbox.ymax) / 2, bbox.zmin)
        direction = (0, 0, 1)
        plane = "XY"
        u_axis = (1, 0, 0)
        v_axis = (0, 1, 0)

    elif face == CanonicalFace.FRONT:
        face_center = ((bbox.xmin + bbox.xmax) / 2, bbox.ymin, (bbox.zmin + bbox.zmax) / 2)
        direction = (0, 1, 0)
        plane = "XZ"
        u_axis = (1, 0, 0)
        v_axis = (0, 0, 1)

    elif face == CanonicalFace.BACK:
        face_center = ((bbox.xmin + bbox.xmax) / 2, bbox.ymax, (bbox.zmin + bbox.zmax) / 2)
        direction = (0, -1, 0)
        plane = "XZ"
        u_axis = (1, 0, 0)
        v_axis = (0, 0, 1)

    elif face == CanonicalFace.RIGHT:
        face_center = (bbox.xmax, (bbox.ymin + bbox.ymax) / 2, (bbox.zmin + bbox.zmax) / 2)
        direction = (-1, 0, 0)
        plane = "YZ"
        u_axis = (0, 1, 0)
        v_axis = (0, 0, 1)

    elif face == CanonicalFace.LEFT:
        face_center = (bbox.xmin, (bbox.ymin + bbox.ymax) / 2, (bbox.zmin + bbox.zmax) / 2)
        direction = (1, 0, 0)
        plane = "YZ"
        u_axis = (0, 1, 0)
        v_axis = (0, 0, 1)

    else:
        raise ValueError("custom face requires explicit datum plane; not supported in v1")

    if origin != OriginMode.FACE_CENTER:
        raise ValueError(f"origin_mode={origin} not implemented in first patch")

    cx = face_center[0] + u * u_axis[0] + v * v_axis[0]
    cy = face_center[1] + u * u_axis[1] + v * v_axis[1]
    cz = face_center[2] + u * u_axis[2] + v * v_axis[2]

    return ResolvedHolePlacement(
        center_xyz=(cx, cy, cz),
        direction_xyz=_unit(direction),
        plane=plane,
        u_axis=u_axis,
        v_axis=v_axis,
    )
```

### Claude Code 约束

第一版只实现 `origin_mode=face_center`。不要半成品支持 `datum`，避免引入错误解释。后续扩展 datum 时必须新增 datum registry。

---

## 3.5 实现 OCP 任意方向圆柱 cutter

### 新文件

```text
dialects/geometry_utils/ocp_cylinder.py
```

### 目标

生成沿任意方向的圆柱 cutter，用于 `drill_hole_3d` 和 `cut_hole_v2`。

### 建议代码

```python
from __future__ import annotations

import math
import cadquery as cq
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder


def make_cylinder_cutter(
    center_xyz: tuple[float, float, float],
    direction_xyz: tuple[float, float, float],
    radius_mm: float,
    length_mm: float,
):
    if radius_mm <= 0:
        raise ValueError("radius_mm must be positive")
    if length_mm <= 0:
        raise ValueError("length_mm must be positive")

    dx, dy, dz = direction_xyz
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n <= 1e-12:
        raise ValueError("direction vector cannot be zero")

    dx, dy, dz = dx / n, dy / n, dz / n

    # start behind the face so through-all cut is robust
    half = length_mm / 2.0
    sx = center_xyz[0] - dx * half
    sy = center_xyz[1] - dy * half
    sz = center_xyz[2] - dz * half

    ax = gp_Ax2(gp_Pnt(sx, sy, sz), gp_Dir(dx, dy, dz))
    shape = BRepPrimAPI_MakeCylinder(ax, radius_mm, length_mm).Shape()
    return cq.Workplane(obj=shape)
```

---

## 3.6 实现 `handle_cut_hole_v2`

### 修改文件

```text
dialects/sketch_extrude/handlers.py
```

### 新增 handler

```python
def handle_cut_hole_v2(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p.get("diameter_mm", 0))
    if dia <= 0:
        raise ValueError("cut_hole_v2 requires positive diameter_mm")

    placement = p.get("placement")
    if placement is None:
        raise ValueError("cut_hole_v2 requires placement")

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.hole_placement import (
        resolve_face_hole_placement,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_cylinder import (
        make_cylinder_cutter,
    )

    bb = body.val().BoundingBox()
    resolved = resolve_face_hole_placement(placement, bb)

    through_mode = placement.get("through_mode", "through_all") if isinstance(placement, dict) else placement.through_mode
    depth_mm = placement.get("depth_mm") if isinstance(placement, dict) else placement.depth_mm

    if str(through_mode).endswith("BLIND") or through_mode == "blind":
        length = float(depth_mm)
    else:
        length = max(bb.xlen, bb.ylen, bb.zlen) + 20.0

    cutter = make_cylinder_cutter(
        center_xyz=resolved.center_xyz,
        direction_xyz=resolved.direction_xyz,
        radius_mm=dia / 2.0,
        length_mm=length,
    )

    try:
        result = body.cut(cutter)
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(f"required cut_hole_v2 failed on {node.id}: {exc}") from exc
        return {"body": _degrade(node, ctx, body, "cut_hole_v2")}

    return {"body": _store_solid(node, ctx, result)}
```

### 关键约束

必需孔失败不能 silent skip。

---

## 3.7 修复旧 `cut_hole` 的兼容语义

现有 `cut_hole` 对 `axis=Y` 且 `position_mm` 长度为 2 时，会把 z 默认为 bbox 中面。这是兼容性友好，但语义不严谨。([GitHub][1])

整改策略：

```text
legacy cut_hole:
- axis=Z + len(position_mm)=2：允许
- axis=X/Y + len(position_mm)=2：warning + hard fail in strict mode
- axis=X/Y + len(position_mm)=3：允许旧行为
```

实现：

```python
strict = getattr(ctx, "strict_geometry_semantics", True)

if axis in ("X", "Y") and len(pos) < 3 and strict:
    raise ValueError(
        f"legacy cut_hole axis={axis} requires 3D position_mm in strict mode. "
        "Use cut_hole_v2 with target_face + center_uv_mm."
    )
```

---

## 3.8 实现 `cut_hole_pattern_linear_v2`

### 关键行为

线性阵列必须在目标 face 的 u/v 平面上展开，而不是固定 XY。

```python
def iter_linear_pattern_centers(base_center_uv, count_u, count_v, spacing_u, spacing_v):
    cu, cv = base_center_uv
    for iu in range(count_u):
        for iv in range(count_v):
            u = cu + (iu - (count_u - 1) / 2.0) * spacing_u
            v = cv + (iv - (count_v - 1) / 2.0) * spacing_v
            yield u, v
```

handler 逻辑：

```python
def handle_cut_hole_pattern_linear_v2(node, ctx):
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p["hole_dia_mm"])
    count_u = int(p["count_u"])
    count_v = int(p["count_v"])
    spacing_u = float(p["spacing_u_mm"])
    spacing_v = float(p["spacing_v_mm"])
    placement = p["placement"]

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.hole_placement import (
        resolve_face_hole_placement,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_cylinder import (
        make_cylinder_cutter,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.boolean_batch import (
        batch_cut,
    )

    bb = body.val().BoundingBox()
    cutters = []

    base_uv = placement["center_uv_mm"] if isinstance(placement, dict) else placement.center_uv_mm

    for u, v in iter_linear_pattern_centers(base_uv, count_u, count_v, spacing_u, spacing_v):
        placement_i = copy.deepcopy(placement)
        if isinstance(placement_i, dict):
            placement_i["center_uv_mm"] = [u, v]
        else:
            placement_i.center_uv_mm = (u, v)

        resolved = resolve_face_hole_placement(placement_i, bb)
        length = max(bb.xlen, bb.ylen, bb.zlen) + 20.0
        cutters.append(
            make_cylinder_cutter(
                resolved.center_xyz,
                resolved.direction_xyz,
                dia / 2.0,
                length,
            )
        )

    result = batch_cut(body, cutters)
    return {"body": _store_solid(node, ctx, result)}
```

---

# 4. 几何内核修复与增强

## 4.1 替换错误的 boolean “平移容差融合”

### 当前问题

composition handler 的第三层 fallback 不是 fuzzy tolerance，而是把实体 B 平移一个 margin 后 fuse。这样会改变装配真实位置。([GitHub][5])

### 修改文件

```text
dialects/composition/handlers.py
dialects/geometry_utils/boolean_safe.py
```

### 新策略

```text
Attempt 1: CadQuery union
Attempt 2: OCP BRepAlgoAPI_Fuse with fuzzy value
Attempt 3: ShapeFix_Shape + fuzzy fuse
Attempt 4: If solids are only touching and assembly_multi_body_allowed=True, return compound
Otherwise: hard fail
```

### 代码骨架

```python
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.ShapeFix import ShapeFix_Shape
import cadquery as cq


def heal_shape(shape):
    fixer = ShapeFix_Shape(shape)
    fixer.Perform()
    return fixer.Shape()


def fuzzy_fuse_shapes(a_shape, b_shape, fuzzy_mm):
    fuse = BRepAlgoAPI_Fuse(a_shape, b_shape)
    fuse.SetFuzzyValue(fuzzy_mm)
    fuse.Build()
    if not fuse.IsDone():
        raise RuntimeError("BRepAlgoAPI_Fuse failed")
    return fuse.Shape()


def boolean_union_safe(a, b, tolerance, allow_compound=False):
    try:
        result = a.union(b)
        if _is_single_valid_solid(result):
            return result
    except Exception:
        pass

    for fuzzy in [tolerance.linear_mm, tolerance.linear_mm * 5, tolerance.linear_mm * 10]:
        try:
            shape = fuzzy_fuse_shapes(a.val().wrapped, b.val().wrapped, fuzzy)
            wp = cq.Workplane(obj=shape)
            if _is_valid_boolean_result(wp):
                return wp
        except Exception:
            pass

    try:
        ah = heal_shape(a.val().wrapped)
        bh = heal_shape(b.val().wrapped)
        shape = fuzzy_fuse_shapes(ah, bh, tolerance.linear_mm * 10)
        wp = cq.Workplane(obj=shape)
        if _is_valid_boolean_result(wp):
            return wp
    except Exception:
        pass

    if allow_compound:
        return make_compound_workplane([a, b])

    raise RuntimeError("boolean_union_safe failed without moving geometry")
```

### 严禁

不要再做：

```python
b.translate((margin, margin, margin))
```

---

## 4.2 native loft 重写

### 当前问题

`handle_loft_sections` 使用 CadQuery `.add(wires).toPending().loft()`，文档和测试都显示 g8/g23 在多截面变径处失败。([GitHub][4]) 

### 新文件

```text
dialects/geometry_utils/ocp_loft.py
```

### 设计原则

1. 所有截面都重采样为相同点数。
2. circle / ellipse / rectangle 统一转成 polygon wire。
3. 确保 wire 闭合、方向一致。
4. 使用 OCP `BRepOffsetAPI_ThruSections`。
5. 失败时按相邻截面分段 loft。
6. loft 后必须体积 > 0、solid count = 1。

### 代码骨架

```python
import math
import cadquery as cq
from OCP.gp import gp_Pnt
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections


def sample_section(sec: dict, n: int = 64):
    pos = sec.get("position", {})
    x0 = float(pos.get("x_mm", 0))
    y0 = float(pos.get("y_mm", 0))
    z0 = float(pos.get("z_mm", 0))
    shape = sec.get("shape", "circle")

    pts = []

    if shape == "circle":
        r = float(sec["radius_mm"])
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.append((x0 + r * math.cos(a), y0 + r * math.sin(a), z0))

    elif shape == "ellipse":
        rx = float(sec["width_mm"]) / 2
        ry = float(sec["height_mm"]) / 2
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.append((x0 + rx * math.cos(a), y0 + ry * math.sin(a), z0))

    elif shape == "rectangle":
        w = float(sec["width_mm"])
        h = float(sec["height_mm"])
        pts = sample_rectangle_perimeter(x0, y0, z0, w, h, n)

    else:
        raise ValueError(f"unsupported loft section shape: {shape}")

    return pts


def make_closed_wire(points):
    wb = BRepBuilderAPI_MakeWire()
    pts = list(points) + [points[0]]
    for a, b in zip(pts, pts[1:]):
        edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge()
        wb.Add(edge)
    wire = wb.Wire()
    return wire


def native_loft_sections(sections: list[dict], ruled=False, sample_n=64):
    api = BRepOffsetAPI_ThruSections(True, ruled, 1e-6)
    api.CheckCompatibility(True)

    for sec in sections:
        pts = sample_section(sec, sample_n)
        api.AddWire(make_closed_wire(pts))

    api.Build()

    if not api.IsDone():
        raise RuntimeError("native loft failed")

    wp = cq.Workplane(obj=api.Shape())
    if wp.val().Volume() <= 0:
        raise RuntimeError("native loft produced non-positive volume")

    return wp
```

### 修改 handler

```python
def handle_loft_sections(node, ctx):
    sections = node.params.get("sections", [])
    if len(sections) < 2:
        raise ValueError("Need at least 2 sections for loft")

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_loft import (
        native_loft_sections,
    )

    try:
        solid = native_loft_sections(
            sections,
            ruled=bool(node.params.get("ruled", False)),
            sample_n=int(node.params.get("sample_n", 64)),
        )
    except Exception as exc:
        raise RuntimeError(f"loft_sections failed on '{node.id}': {exc}") from exc

    return {"body": _store_solid(node, ctx, solid)}
```

---

## 4.3 批量孔布尔 cut

密集孔逐个 cut 会越来越慢，也更容易失败。开发者文档已经指出 300 孔虽然成功，但当前没有性能监控或上限保护。

### 新文件

```text
dialects/geometry_utils/boolean_batch.py
```

### 代码骨架

```python
import cadquery as cq
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder


def make_compound(shapes):
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for s in shapes:
        builder.Add(compound, s.val().wrapped)
    return cq.Workplane(obj=compound)


def batch_cut(target, cutters):
    if not cutters:
        return target

    compound = make_compound(cutters)

    try:
        result = target.cut(compound)
    except Exception as exc:
        raise RuntimeError(f"batch_cut failed for {len(cutters)} cutters: {exc}") from exc

    if result.val().Volume() <= 0:
        raise RuntimeError("batch_cut produced non-positive volume")

    return result
```

---

# 5. Validation / Audit / AutoFix 架构改造

## 5.1 新增 root terminal validator

### 新文件

```text
validation/root_terminal.py
```

### 目的

防止 g14 这类问题：组件 root 指向 base，后面的孔、阵列、槽没有成为最终输出。

### 代码骨架

```python
def validate_root_terminal(raw_doc):
    issues = []

    for comp in raw_doc.get("components", []):
        cid = comp["id"]
        if cid == "__assembly__":
            continue

        nodes = [n for n in raw_doc["nodes"] if n["component"] == cid]
        solid_nodes = [
            n["id"] for n in nodes
            if any(o.get("type") == "solid" for o in n.get("outputs", []))
        ]

        consumed = {
            inp["node"]
            for n in nodes
            for inp in n.get("inputs", [])
            if "node" in inp
        }

        terminal_solids = [nid for nid in solid_nodes if nid not in consumed]
        root = comp.get("root_node")

        if root not in terminal_solids:
            issues.append({
                "code": "ROOT_NOT_TERMINAL_SOLID",
                "component": cid,
                "root_node": root,
                "terminal_candidates": terminal_solids,
                "severity": "error",
            })

    return issues
```

---

## 5.2 新增 hole semantic validator

### 新文件

```text
validation/hole_semantics.py
```

### 检查项

1. legacy `cut_hole` 的 `axis=X/Y` 不允许二维位置。
2. v2 孔必须有 target_face。
3. 孔中心必须落在目标 face bbox 范围内。
4. 孔不能与中心孔、边界、筋发生禁止冲突。
5. 圆周孔阵列必须有 `start_angle_deg` 默认可用，但多圈/避筋场景必须声明 datum。
6. required 孔不允许 degrade。

### 代码骨架

```python
def validate_hole_semantics(canonical_doc):
    issues = []

    for node in canonical_doc.nodes:
        if node.op == "cut_hole":
            axis = node.params.get("axis", "Z")
            pos = node.params.get("position_mm", [])
            if axis in ("X", "Y") and len(pos) < 3:
                issues.append({
                    "code": "LEGACY_SIDE_HOLE_REQUIRES_3D_POSITION",
                    "node_id": node.id,
                    "severity": "error",
                    "message": "Use cut_hole_v2 with target_face and center_uv_mm.",
                })

        if node.op in ("cut_hole_v2", "cut_hole_pattern_linear_v2"):
            placement = node.params.get("placement")
            if not placement:
                issues.append({
                    "code": "MISSING_HOLE_PLACEMENT",
                    "node_id": node.id,
                    "severity": "error",
                })

    return issues
```

---

## 5.3 新增 runtime geometry postcondition gate

### 新文件

```text
runtime/geometry_postcheck.py
```

### 目标

导出前后均检查。

```python
@dataclass
class GeometryPostcheckResult:
    ok: bool
    volume_mm3: float | None
    n_solids: int | None
    bbox: dict | None
    closed: bool | None
    errors: list[str]
    warnings: list[str]
```

### 强制失败条件

```text
volume <= 0
bbox void
n_solids == 0
n_solids > expected 且不是 allow_multi_body
required feature degraded
boolean_union lost body
hole count mismatch
```

### 插入点

```text
pipeline/run.py
    after _run_composition_or_select_final()
    before _export_final_solid()
    after STEP export inspection
```

---

## 5.4 AutoFix 风险策略升级

当前 auto_fixer 已有风险分类，默认允许 syntactic/context-safe，阻止 semantic guess/destructive。([GitHub][7])

需要新增三类 fix：

### A. SAFE_STRUCTURE_FIX

可以自动做：

```text
root_node 指向唯一 terminal solid
删除孤立未引用的 optional 装饰节点
补齐 op_version
旧 alias 映射
```

### B. SAFE_SEMANTIC_NORMALIZATION

可以自动做：

```text
legacy axis=Z cut_hole + position len=2 → cut_hole_v2 target_face=top
legacy circular hole pattern → v2 with target_face=top, start_angle=0
```

### C. BLOCKED_SEMANTIC_GUESS

禁止自动做：

```text
axis=Y + position len=2 → 猜 front/back 和 z
top/bottom 盲孔深度 → 猜 depth
孔是否避开筋 → 猜 cut_scope
未知 component placement → 猜原点
```

---

# 6. 空间前端与装配修复

## 6.1 修复 `handle_place_component`

### 当前问题

`handle_place_component` 只读取 `node.params["position_mm"]`，没有使用 resolver 计算出的 `ctx.spatial_placements`。([GitHub][5])

### 修改

```python
def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)

    target_component_id = (
        node.params.get("target_component_id")
        or node.params.get("component_id")
        or getattr(node, "target_component_id", None)
    )

    pos = None

    if target_component_id and getattr(ctx, "spatial_placements", None):
        placement = ctx.spatial_placements.get(target_component_id)
        if placement is not None:
            pos = tuple(placement.translation_mm)

    if pos is None:
        pos = node.params.get("position_mm", (0, 0, 0))

    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise ValueError(f"place_component requires 3D position, got {pos}")

    try:
        placed = body.translate(tuple(float(v) for v in pos))
    except Exception as exc:
        raise RuntimeError(f"place_component failed on {node.id}: {exc}") from exc

    if hasattr(ctx, "placed_component_bboxes") and target_component_id:
        ctx.placed_component_bboxes[target_component_id] = placed.val().BoundingBox()

    return {"body": _store_solid(node, ctx, placed)}
```

---

## 6.2 多组件默认启用 deterministic spatial frontend

现有 authoring pipeline 的 `enable_spatial_frontend` 默认是 False。([GitHub][3])

### 改造原则

```text
单组件：跳过 spatial frontend
多组件：先 deterministic archetype
archetype 不足：LLM spatial frontend
仍不足：clarification
```

---

# 7. Prompt 系统重构

下面是可直接交给 Claude Code 放入 prompt 文件的高质量 prompt 规格。

## 7.1 System Prompt：总分工

```text
You are not a CAD compiler. You are a mechanical design intent extractor.

You must never invent concrete graph wiring, node input references, output references, or root nodes.
The code compiler will create graph wiring deterministically.

Your job is to extract:
1. components
2. feature intents
3. spatial relations
4. faces, axes, datums, and local coordinate frames
5. hole placements and feature scopes
6. manufacturing/tolerance assumptions
7. missing information that must be clarified

You must prefer semantic anchors over numeric guesses.
For any hole, slot, pocket, boss, rib, flange, shaft, bearing, bracket, or shell feature, always specify the target face or datum.

Never emit legacy hole parameters such as:
- axis + position_mm only
- through_all without target_face
- side hole with 2D position

Use v2 geometry parameters:
- target_face
- center_uv_mm
- normal_axis
- origin_mode
- through_mode
- feature_scope

If a required dimension, face, side, axis, or feature scope is ambiguous and changes the topology, ask a clarification question instead of guessing.
```

---

## 7.2 Object Graph Prompt

```text
Extract a MechanicalObjectGraph.

Return components and their semantic roles.
For each component, include:
- component_id
- role
- approximate shape class
- local coordinate convention
- important faces
- important axes
- mating interfaces
- holes/slots/pockets/bosses/ribs/flanges attached to it
- whether it is a leaf solid or an assembly-level component

Rules:
1. Do not generate CAD node IDs.
2. Do not generate graph input references.
3. Do not decide operation order unless required by design intent.
4. If a hole is mentioned, identify target face and whether it is through, blind, counterbored, countersunk, threaded, or unknown.
5. If the user says top/bottom/front/back/left/right, preserve that face identity explicitly.
6. If multiple components are stacked, coaxial, symmetric, bolted, inserted, or touching, emit spatial relations.
```

---

## 7.3 Feature Sequence Prompt

```text
Plan semantic features, not low-level graph wiring.

For each feature, emit:
- feature_id
- target_component
- operation_family
- semantic_role
- required
- after_feature_role if semantically necessary
- target_face or datum
- feature_scope
- parameters that are explicitly known
- parameters that are inferred with low risk
- parameters that require clarification

Do not emit:
- node inputs
- output names
- root_node
- concrete object references
- synthetic references like "ft_cut_hole_ref"

Hole rules:
1. Use cut_hole_v2 for face-normal holes.
2. Use drill_hole_3d only for arbitrary angled holes.
3. Use cut_hole_pattern_linear_v2 for rectangular arrays on a face.
4. Use cut_circular_hole_pattern_v2 for bolt circles.
5. Every hole must have target_face and center_uv_mm.
6. Every circular pattern must have pcd_mm, count, start_angle_deg, and datum_axis.
7. Never represent top and bottom holes as identical through_all Z holes unless the intent is one shared through hole.
```

---

## 7.4 Node Params Prompt

```text
Fill parameters only for the provided operation and feature intent.

Do not add inputs.
Do not add outputs.
Do not change node_id, op, dialect, or version.
Do not use deprecated legacy hole schemas.

When generating hole parameters:
- target_face must be one of top, bottom, front, back, left, right
- center_uv_mm is measured in the local face coordinate system
- origin_mode defaults to face_center
- normal_axis must point from the entry face into the part
- through_mode must be through_all, blind, to_next, or up_to_face
- blind holes require depth_mm
- feature_scope.required is true for functional holes

If side hole coordinates are ambiguous, do not guess. Mark parameter as missing and request clarification through the question planner.
```

---

## 7.5 Repair Prompt

```text
You are repairing a CAD semantic IR under strict constraints.

You must only modify fields listed as editable.
You must stay inside the feasible intervals provided by the geometric solver.
You must not invent node references.
You must not change locked user dimensions.
You must not remove required functional features.
You must not convert a failed required feature into optional.

If the error is geometric infeasibility:
- prefer reducing hole diameter only if the hole is not user-locked
- prefer increasing outer diameter only if outer diameter is not user-locked
- prefer moving PCD only within pcd_min and pcd_max
- if no feasible repair exists, give_up with a clear reason

If the error is missing target_face or feature_scope:
- do not guess front/back/left/right
- request clarification unless unambiguous from the user text
```

---

# 8. Claude Code 实施顺序

## Commit 1：Postcondition 与 required degrade hard fail

修改：

```text
runtime/geometry_postcheck.py
pipeline/run.py
validation/root_terminal.py
validation/hole_semantics.py
tests/generative_cad/validation/
```

验收：

```text
g22/g26/g30 类异常不能再算 success
root 指向 base 但后续有孔阵列时必须报错
required cut_hole 失败必须 fail
fillet/chamfer 失败仍可 degrade
```

---

## Commit 2：HolePlacementV2 数据模型与 op 注册

修改：

```text
ir/geometry_semantics.py
bases/sketch_extrude/models.py
dialects/sketch_extrude/dialect.py
authoring/context_builder.py
authoring/tool_schemas.py
```

验收：

```text
tool schema 中出现 cut_hole_v2
legacy cut_hole 标记 deprecated
LLM schema 不再鼓励 axis+position_mm
```

---

## Commit 3：孔 handler v2 与 batch cut

修改：

```text
dialects/geometry_utils/hole_placement.py
dialects/geometry_utils/ocp_cylinder.py
dialects/geometry_utils/boolean_batch.py
dialects/sketch_extrude/handlers.py
```

验收：

```text
top face hole 正确
front face side hole 正确
right face side hole 正确
linear pattern on front face 正确
required hole failure hard fail
```

---

## Commit 4：Assembler 禁止 LLM concrete wiring

修改：

```text
authoring/schemas.py
authoring/raw_assembler.py
authoring/pipeline.py
validation/reference_integrity.py
tests/generative_cad/authoring/
```

验收：

```text
LLM raw 中出现 inputs → schema fail
assembler 根据 semantic dependency 接线
g14 类 missing ref 不再进入 runtime
component root 自动指向 terminal solid
```

---

## Commit 5：空间 placement 闭环

修改：

```text
dialects/composition/handlers.py
runtime/context.py
runtime/spatial_audit.py
runtime/constraint_resolver.py
authoring/build_pipeline.py
authoring/pipeline.py
```

验收：

```text
多组件默认启用 deterministic spatial frontend
ctx.spatial_placements 被 place_component 使用
未解析多组件 placement hard fail
spatial audit 使用 world bbox
```

---

## Commit 6：Native loft 与 safe boolean

修改：

```text
dialects/geometry_utils/ocp_loft.py
dialects/geometry_utils/boolean_safe.py
dialects/loft_sweep/handlers.py
dialects/composition/handlers.py
```

验收：

```text
circle→rectangle→circle loft 成功
g8/g23 重测通过或给出明确 preflight fail
boolean 不允许 translate body 后假 fuse
thin-wall failure 有明确报告
```

---

## Commit 7：Prompt 全面替换

修改：

```text
authoring/spatial/prompts.py
authoring/tool_schemas.py
authoring/context_builder.py
docs/prompts/
```

验收：

```text
prompt 中明确禁止 concrete node refs
prompt 中强制 target_face / center_uv / normal_axis
repair prompt 使用 solver feasible intervals
clarification prompt 只问拓扑关键问题
```

---

# 9. 回归测试清单

## 必测 case

```text
g3_hyd_manifold
- 验证侧孔 face/axis/height 正确

g8_var_duct
- 验证 native loft 支持圆→矩形→圆

g14_vacuum_chamber
- 验证 missing node ref 被 schema/assembler 阻止
- 验证 flange root 指向最终孔阵列后实体

g17_cross_block
- 验证 top/bottom/front/back/left/right 面语义不被 through_all 抹掉

g19_precision_base
- 验证 cut_scope，减重孔不会误切后续 rib，除非 scope 明确要求

g22_heat_sink
- 验证 multi-solid 不再误判成功

g23_pipe_reducer
- 验证 loft + flange assembly

g24_micro_bushing
- 验证 tolerance profile 可配置

g25_large_ring
- 验证孔-中心孔冲突 solver 给出可行区间

g26_extreme_shaft
- 验证负体积 hard fail
```

---

# 10. 最终验收标准

项目不应再以“STEP 文件生成了”为成功标准，而应满足：

```text
Authoring:
- LLM 不输出 concrete wiring
- 所有孔使用 v2 semantic schema
- 多组件产生 spatial contract

Validation:
- no missing refs
- no root bypass
- no ambiguous side hole
- no invalid hole-face relation
- no required feature degraded

Runtime:
- all required features applied
- spatial placements applied
- boolean does not move geometry
- loft/sweep volume positive
- final solid count matches expectation
- bbox valid
- volume positive

Output:
- STEP export ok
- STEP inspection ok
- optional SolidWorks import ok
- metadata records warnings/degraded features/postcheck
```

---

# 11. 关键结论

这套整改的核心不是“把 prompt 写得更凶一点”，而是把系统从：

```text
LLM 猜一个 CAD 操作序列 → 代码尽量跑通
```

改成：

```text
LLM 抽取机械语义 → 代码确定性编译 → 几何内核执行 → 后验审计 → 可控修复
```

你看到的孔位错误、打孔顺序错误、孔打到不该打的地方，本质上都是同一个问题：**当前 IR 没有保存足够的机械语义，代码又允许 LLM 的不完整语义直接落到几何执行层。**

Claude Code 实施时应优先修 P0：孔语义、root/接线、geometry postcheck、required hard fail。只有这些完成后，再修 native loft、safe boolean、spatial frontend 和 prompt 系统，整个非 primitive 链路才会从“能生成一些模型”变成“能稳定生成正确机械模型”。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/handlers.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/raw_assembler.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/pipeline.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/loft_sweep/handlers.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/sketch_extrude/models.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/auto_fixer.py "raw.githubusercontent.com"
