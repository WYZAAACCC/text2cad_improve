
---

# 航空发动机涡轮盘自然语言建模实现方案

## 0. 当前代码架构判断

当前系统已经有适合扩展涡轮盘的基础架构，不应该重构成新系统。现有 `CADPartSpec` 已经支持 `PrimitiveFeature`，而 `PrimitiveFeature` 的结构是通用的：`primitive_name + parameters + placement + operation`，这正好适合新增 `axisymmetric_turbine_disk` primitive，而不是新增一种专门的 `TurbineDiskFeature`。([GitHub][1])

当前 primitive registry 也是通用结构，已有 `PrimitiveDefinition` / `PrimitiveParameter`，每个 primitive 可以声明参数、支持 kernel、支持 backend、standards 和 validation defaults，所以涡轮盘应该作为新的 primitive family 注册进去，而不是绕开 registry 单独写一条链路。([GitHub][2])

当前自然语言统一入口已经是 `engineering_validate_cad_ir` 和 `engineering_build_cad_model`。validate 阶段会做 schema validation、recipe/primitive 参数 normalization、backend support 检查；build 阶段会内部再次 normalize，并根据 primitive strategy 选择 CadQuery 原生构建或 SW/NX canonical STEP import。因此涡轮盘必须接入这两个入口，不能另起一个 build tool。([GitHub][3])

当前 capability registry 已经支持 `stable_primitives` 和 `primitive_strategy`，其中 CadQuery primitive 策略是 `native_cadquery_primitive`，SolidWorks/NX primitive 策略是 `cadquery_step_import`。涡轮盘应该沿用这个策略：CadQuery/OpenCascade 生成 canonical STEP，SolidWorks/NX 只导入 STEP，不重新生成复杂涡轮盘几何。([GitHub][4])

当前 CadQuery compiler 只认识 `involute_spur_gear` primitive；这是需要扩展的核心点。新增涡轮盘时，只应扩展 primitive compiler 的 dispatch，不应该让 LLM 生成 CadQuery 代码。([GitHub][5])

当前 builder 对 primitive 已经有 metadata sidecar、inspection、mechanical validation、fallback policy 等机制；涡轮盘应该复用这套机制，并把 gear-only metadata 检查扩展成 generic primitive metadata 检查。([GitHub][6])

当前 mechanical validation common 只分发 `involute_spur_gear`，因此涡轮盘应新增 `turbine_disk_validation.py` 并在 `validate_mechanical_primitives()` 中按 primitive name 分发，而不是写在 demo 或 builder 里。([GitHub][7])

---

# 1. 总体设计原则

## 1.1 必须保持现有通用架构

本次新增能力必须仍然遵循：

```text
自然语言
  ↓
Skill / parser
  ↓
CAD-IR
  ↓
engineering_validate_cad_ir
  ↓
Primitive Registry / Capability Registry
  ↓
engineering_build_cad_model
  ↓
CadQuery deterministic primitive compiler
  ↓
STEP + metadata.json
  ↓
Inspection
  ↓
Mechanical Validation
  ↓
SolidWorks/NX 可选 import STEP
```

不能新增：

```text
turbine_disk_build_model 独立工具
turbine_disk_direct_cadquery_generator
LLM 直接生成 CadQuery 脚本
LLM 直接生成 NXOpen / SolidWorks COM
```

## 1.2 LLM 的职责边界

LLM / skill 只允许做：

```text
1. 理解用户自然语言描述；
2. 判断用户想要的是涡轮盘 primitive；
3. 抽取参数；
4. 判断缺失参数；
5. 输出 CAD-IR；
6. 根据 diagnostics 修改 CAD-IR。
```

LLM / skill 不允许做：

```text
1. 现场写 CadQuery 几何脚本；
2. 自己生成轮盘母线点；
3. 自己推导榫槽曲线；
4. 自己决定航空安全关键尺寸；
5. 自己决定真实材料、转速、寿命、安全系数；
6. 声称模型可用于真实发动机制造或适航。
```

---

# 2. 涡轮盘 primitive 定义

## 2.1 primitive 名称

固定名称：

```text
axisymmetric_turbine_disk
```

第一阶段只做**轴对称涡轮盘主体 + 中心孔 + 可选螺栓孔环 + 可选减重孔环 + 可选冷却孔环的几何骨架**。

不要第一阶段做真实榫槽、真实叶片连接、真实轮缘 fir-tree slot、真实冷却结构。

## 2.2 primitive 分类

```text
category = "turbomachinery"
```

## 2.3 支持 backend

```python
supported_backends = ["cadquery", "solidworks2025", "nx12"]
```

## 2.4 支持 kernels

```python
supported_kernels = ["cadquery_opencascade_revolve"]
```

## 2.5 strategy

在 `capabilities/registry.py` 中：

```python
"cadquery": {
    "stable_primitives": [
        "involute_spur_gear",
        "axisymmetric_turbine_disk",
    ],
    "primitive_strategy": {
        "involute_spur_gear": "native_cadquery_primitive",
        "axisymmetric_turbine_disk": "native_cadquery_primitive",
    },
}
```

SolidWorks / NX：

```python
"solidworks2025": {
    "stable_primitives": [
        "involute_spur_gear",
        "axisymmetric_turbine_disk",
    ],
    "primitive_strategy": {
        "involute_spur_gear": "cadquery_step_import",
        "axisymmetric_turbine_disk": "cadquery_step_import",
    },
}
```

```python
"nx12": {
    "stable_primitives": [
        "involute_spur_gear",
        "axisymmetric_turbine_disk",
    ],
    "primitive_strategy": {
        "involute_spur_gear": "cadquery_step_import",
        "axisymmetric_turbine_disk": "cadquery_step_import",
    },
}
```

---

# 3. 固定参数表

**Claude Code 不得自行设计参数名。必须严格使用下面参数。**

## 3.1 必填基础参数

| 参数名                |    类型 | 单位 | 必填 |  最小值 | 说明             |
| ------------------ | ----: | -- | -: | ---: | -------------- |
| `outer_dia_mm`     | float | mm |  是 |  > 0 | 涡轮盘最大外径        |
| `bore_dia_mm`      | float | mm |  是 | >= 0 | 中心孔直径，0 表示无中心孔 |
| `axial_width_mm`   | float | mm |  是 |  > 0 | 总轴向宽度          |
| `hub_outer_dia_mm` | float | mm |  是 |  > 0 | 轮毂外径           |
| `web_outer_dia_mm` | float | mm |  是 |  > 0 | 腹板外径           |
| `rim_inner_dia_mm` | float | mm |  是 |  > 0 | 轮缘内径           |
| `hub_width_mm`     | float | mm |  是 |  > 0 | 轮毂轴向宽度         |
| `web_width_mm`     | float | mm |  是 |  > 0 | 腹板轴向宽度         |
| `rim_width_mm`     | float | mm |  是 |  > 0 | 轮缘轴向宽度         |

## 3.2 可选圆角 / 倒角参数

| 参数名                    |    类型 | 单位 | 必填 | 默认值 | 说明          |
| ---------------------- | ----: | -- | -: | --: | ----------- |
| `hub_fillet_radius_mm` | float | mm |  否 | 1.0 | 轮毂过渡圆角      |
| `web_fillet_radius_mm` | float | mm |  否 | 1.0 | 腹板过渡圆角      |
| `rim_fillet_radius_mm` | float | mm |  否 | 1.0 | 轮缘过渡圆角      |
| `edge_chamfer_mm`      | float | mm |  否 | 0.0 | 外边倒角，0 表示不做 |

## 3.3 可选螺栓孔环参数

| 参数名                |    类型 | 单位    |   必填 |   默认值 | 说明          |
| ------------------ | ----: | ----- | ---: | ----: | ----------- |
| `bolt_hole_count`  |   int | count |    否 |     0 | 螺栓孔数量，0 表示无 |
| `bolt_pcd_mm`      | float | mm    | 条件必填 |   0.0 | 螺栓孔节圆直径     |
| `bolt_hole_dia_mm` | float | mm    | 条件必填 |   0.0 | 螺栓孔直径       |
| `bolt_hole_axis`   |   str | -     |    否 | `"Z"` | 第一阶段固定为 Z   |

条件必填规则：

```text
如果 bolt_hole_count > 0，则 bolt_pcd_mm > 0 且 bolt_hole_dia_mm > 0。
如果 bolt_hole_count == 0，则 bolt_pcd_mm 和 bolt_hole_dia_mm 必须为 0 或缺省。
```

## 3.4 可选减重孔环参数

| 参数名                      |    类型 | 单位    |   必填 |   默认值 | 说明          |
| ------------------------ | ----: | ----- | ---: | ----: | ----------- |
| `lightening_hole_count`  |   int | count |    否 |     0 | 减重孔数量，0 表示无 |
| `lightening_hole_pcd_mm` | float | mm    | 条件必填 |   0.0 | 减重孔节圆直径     |
| `lightening_hole_dia_mm` | float | mm    | 条件必填 |   0.0 | 减重孔直径       |
| `lightening_hole_axis`   |   str | -     |    否 | `"Z"` | 第一阶段固定为 Z   |

条件必填规则同螺栓孔。

## 3.5 可选冷却孔环参数

第一阶段只做简化直通冷却孔，不做复杂斜孔/三维气膜孔。

| 参数名                   |    类型 | 单位    |   必填 |   默认值 | 说明        |
| --------------------- | ----: | ----- | ---: | ----: | --------- |
| `cooling_hole_count`  |   int | count |    否 |     0 | 冷却孔数量     |
| `cooling_hole_pcd_mm` | float | mm    | 条件必填 |   0.0 | 冷却孔节圆直径   |
| `cooling_hole_dia_mm` | float | mm    | 条件必填 |   0.0 | 冷却孔直径     |
| `cooling_hole_axis`   |   str | -     |    否 | `"Z"` | 第一阶段固定为 Z |

第一阶段禁止：

```text
cooling_hole_angle_deg
compound_angle_deg
film_cooling_shape
diffuser_hole
elliptical_hole
```

这些留到第二阶段。

## 3.6 质量等级参数

| 参数名             |  类型 |                       默认值 | 允许值                                             |
| --------------- | --: | ------------------------: | ----------------------------------------------- |
| `quality_grade` | str | `"engineering_reference"` | `"concept_geometry"`, `"engineering_reference"` |

定义：

```text
concept_geometry:
  用于概念展示、教学、早期形状验证。

engineering_reference:
  用于工程参考几何，可进行 STEP、metadata、inspection、mechanical_validation；
  但不能声明可制造、可适航、可装机。
```

不要使用：

```text
manufacturing_ready
flight_ready
certified
airworthy
```

## 3.7 安全声明参数

增加一个布尔参数：

| 参数名                         |   类型 |    默认值 | 说明                                     |
| --------------------------- | ---: | -----: | -------------------------------------- |
| `non_flight_reference_only` | bool | `True` | 必须为 True；如果用户显式设 False，validation 必须失败 |

这是为了避免系统输出被误解为可用于真实航空发动机。

---

# 4. 固定 CAD-IR 格式

Claude Code 必须以这个格式为准。

```json
{
  "nlcad_version": "0.1",
  "name": "hpt_axisymmetric_turbine_disk_demo",
  "units": "mm",
  "target_backend": ["cadquery"],
  "parameters": {},
  "features": [
    {
      "id": "disk1",
      "type": "primitive",
      "primitive_name": "axisymmetric_turbine_disk",
      "operation": "new_body",
      "placement": {
        "origin_mm": [0.0, 0.0, 0.0],
        "axis": "Z"
      },
      "parameters": {
        "outer_dia_mm": 480.0,
        "bore_dia_mm": 80.0,
        "axial_width_mm": 60.0,

        "hub_outer_dia_mm": 150.0,
        "web_outer_dia_mm": 380.0,
        "rim_inner_dia_mm": 390.0,

        "hub_width_mm": 60.0,
        "web_width_mm": 28.0,
        "rim_width_mm": 52.0,

        "hub_fillet_radius_mm": 2.0,
        "web_fillet_radius_mm": 2.0,
        "rim_fillet_radius_mm": 2.0,
        "edge_chamfer_mm": 0.5,

        "bolt_hole_count": 36,
        "bolt_pcd_mm": 130.0,
        "bolt_hole_dia_mm": 8.0,
        "bolt_hole_axis": "Z",

        "lightening_hole_count": 24,
        "lightening_hole_pcd_mm": 260.0,
        "lightening_hole_dia_mm": 18.0,
        "lightening_hole_axis": "Z",

        "cooling_hole_count": 0,
        "cooling_hole_pcd_mm": 0.0,
        "cooling_hole_dia_mm": 0.0,
        "cooling_hole_axis": "Z",

        "quality_grade": "engineering_reference",
        "non_flight_reference_only": true
      }
    }
  ],
  "validation": {
    "expected_bbox_mm": [480.0, 480.0, 60.0],
    "expected_body_count": 1,
    "expected_hole_count": 61,
    "expected_through_hole_count": 61,
    "tolerance_mm": 0.1,
    "expected_kernel": "cadquery_opencascade_revolve",
    "primitive_validation": {
      "disk1": {
        "expected_primitive": "axisymmetric_turbine_disk",
        "expected_outer_dia_mm": 480.0,
        "expected_bore_dia_mm": 80.0,
        "expected_axial_width_mm": 60.0,
        "expected_hub_outer_dia_mm": 150.0,
        "expected_web_outer_dia_mm": 380.0,
        "expected_rim_inner_dia_mm": 390.0,
        "expected_bolt_hole_count": 36,
        "expected_lightening_hole_count": 24,
        "expected_cooling_hole_count": 0,
        "expected_quality_grade": "engineering_reference",
        "expected_non_flight_reference_only": true
      }
    }
  },
  "outputs": {
    "native": false,
    "step": true,
    "stl": false,
    "preview_png": false
  }
}
```

---

# 5. 必须修改 `ValidationSpec`

当前 `ValidationSpec` 里已经出现了 gear-specific 字段，例如 `expected_tooth_count`、`expected_pitch_diameter_mm` 等。为了保持通用性，不要继续往核心 schema 里塞大量 turbine-specific 字段。当前 `ValidationSpec` 使用 `extra="forbid"`，所以如果要支持上面的 `primitive_validation`，必须显式增加这个通用字段。([GitHub][1])

## 5.1 修改文件

```text
src/seekflow_engineering_tools/ir/cad.py
```

## 5.2 新增字段

在 `ValidationSpec` 中增加：

```python
primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

因为 `cad.py` 已经 import 了 `Any`，可以直接使用。([GitHub][1])

## 5.3 新增校验

```python
@model_validator(mode="after")
def validate_primitive_validation(self):
    if self.primitive_validation is None:
        self.primitive_validation = {}
    for feature_id, spec in self.primitive_validation.items():
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ValueError("primitive_validation keys must be non-empty feature ids")
        if not isinstance(spec, dict):
            raise ValueError(
                f"primitive_validation['{feature_id}'] must be a dict"
            )
    return self
```

如果已有 `validate_bbox`，不要覆盖它；可以新增第二个 validator，或者合并。

---

# 6. 新增 primitive 文件结构

新增目录：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/
  __init__.py
  turbine_disk/
    __init__.py
    models.py
    validator.py
    profile.py
    cadquery_adapter.py
    metadata.py
```

## 6.1 `models.py`

固定内容结构：

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.base import (
    PrimitiveDefinition,
    PrimitiveParameter,
)

TURBINE_DISK_PRIMITIVES: list[PrimitiveDefinition] = [
    PrimitiveDefinition(
        name="axisymmetric_turbine_disk",
        category="turbomachinery",
        description=(
            "Axisymmetric aero-engine turbine disk reference geometry. "
            "Deterministic hub-web-rim revolve primitive with optional "
            "bolt/lightening/cooling hole rings. Non-flight reference only."
        ),
        parameters=[
            PrimitiveParameter(
                name="outer_dia_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=1.0,
                description="Maximum outside diameter of the disk.",
            ),
            PrimitiveParameter(
                name="bore_dia_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.0,
                description="Central bore diameter; 0 means no bore cut.",
            ),
            PrimitiveParameter(
                name="axial_width_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Overall axial width of the disk.",
            ),
            PrimitiveParameter(
                name="hub_outer_dia_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Hub outside diameter.",
            ),
            PrimitiveParameter(
                name="web_outer_dia_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Web outside diameter.",
            ),
            PrimitiveParameter(
                name="rim_inner_dia_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Rim inside diameter.",
            ),
            PrimitiveParameter(
                name="hub_width_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Axial width of hub zone.",
            ),
            PrimitiveParameter(
                name="web_width_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Axial width of web zone.",
            ),
            PrimitiveParameter(
                name="rim_width_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
                description="Axial width of rim zone.",
            ),
            PrimitiveParameter(
                name="hub_fillet_radius_mm",
                type="float",
                unit="mm",
                required=False,
                default=1.0,
                min_value=0.0,
                description="Hub transition fillet radius.",
            ),
            PrimitiveParameter(
                name="web_fillet_radius_mm",
                type="float",
                unit="mm",
                required=False,
                default=1.0,
                min_value=0.0,
                description="Web transition fillet radius.",
            ),
            PrimitiveParameter(
                name="rim_fillet_radius_mm",
                type="float",
                unit="mm",
                required=False,
                default=1.0,
                min_value=0.0,
                description="Rim transition fillet radius.",
            ),
            PrimitiveParameter(
                name="edge_chamfer_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Optional external edge chamfer.",
            ),
            PrimitiveParameter(
                name="bolt_hole_count",
                type="int",
                unit="count",
                required=False,
                default=0,
                min_value=0,
                description="Number of equally spaced bolt holes.",
            ),
            PrimitiveParameter(
                name="bolt_pcd_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Bolt hole pitch circle diameter.",
            ),
            PrimitiveParameter(
                name="bolt_hole_dia_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Bolt hole diameter.",
            ),
            PrimitiveParameter(
                name="bolt_hole_axis",
                type="str",
                required=False,
                default="Z",
                description="Bolt hole axis. Phase 1 only supports Z.",
            ),
            PrimitiveParameter(
                name="lightening_hole_count",
                type="int",
                unit="count",
                required=False,
                default=0,
                min_value=0,
                description="Number of equally spaced lightening holes.",
            ),
            PrimitiveParameter(
                name="lightening_hole_pcd_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Lightening hole pitch circle diameter.",
            ),
            PrimitiveParameter(
                name="lightening_hole_dia_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Lightening hole diameter.",
            ),
            PrimitiveParameter(
                name="lightening_hole_axis",
                type="str",
                required=False,
                default="Z",
                description="Lightening hole axis. Phase 1 only supports Z.",
            ),
            PrimitiveParameter(
                name="cooling_hole_count",
                type="int",
                unit="count",
                required=False,
                default=0,
                min_value=0,
                description="Number of simplified through cooling holes.",
            ),
            PrimitiveParameter(
                name="cooling_hole_pcd_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Cooling hole pitch circle diameter.",
            ),
            PrimitiveParameter(
                name="cooling_hole_dia_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
                description="Cooling hole diameter.",
            ),
            PrimitiveParameter(
                name="cooling_hole_axis",
                type="str",
                required=False,
                default="Z",
                description="Cooling hole axis. Phase 1 only supports Z.",
            ),
            PrimitiveParameter(
                name="quality_grade",
                type="str",
                required=False,
                default="engineering_reference",
                description=(
                    "Allowed: concept_geometry, engineering_reference. "
                    "Never means manufacturing-ready or flight-ready."
                ),
            ),
            PrimitiveParameter(
                name="non_flight_reference_only",
                type="bool",
                required=False,
                default=True,
                description="Must remain true for this primitive.",
            ),
        ],
        supported_kernels=["cadquery_opencascade_revolve"],
        supported_backends=["cadquery", "solidworks2025", "nx12"],
        standards=["internal_reference_geometry_v0"],
        validation_defaults={
            "expected_body_count": 1,
            "tolerance_mm": 0.1,
            "non_flight_reference_only": True,
        },
    )
]
```

---

# 7. 参数 validator 规则

新增文件：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/turbine_disk/validator.py
```

## 7.1 固定 validation 函数名

```python
def validate_axisymmetric_turbine_disk_parameters(params: dict) -> list[str]:
    ...
```

## 7.2 固定规则

必须检查：

```text
1. quality_grade ∈ {"concept_geometry", "engineering_reference"}
2. non_flight_reference_only 必须为 True
3. bolt_hole_axis/lightening_hole_axis/cooling_hole_axis 必须为 "Z"
4. outer_dia_mm > rim_inner_dia_mm > web_outer_dia_mm > hub_outer_dia_mm > bore_dia_mm
5. axial_width_mm > 0
6. hub_width_mm <= axial_width_mm
7. web_width_mm <= axial_width_mm
8. rim_width_mm <= axial_width_mm
9. web_width_mm <= hub_width_mm
10. web_width_mm <= rim_width_mm
11. 所有 fillet/chamfer 不得超过局部最小壁厚的 1/3
12. bolt/lightening/cooling hole count > 0 时，对应 pcd 和 hole_dia 必须 > 0
13. hole count == 0 时，对应 pcd/hole_dia 必须为 0
14. 每个孔环 pcd 必须在 bore_dia_mm 与 outer_dia_mm 之间
15. bolt holes 推荐落在 hub zone：bore_dia_mm < bolt_pcd_mm < hub_outer_dia_mm
16. lightening holes 推荐落在 web zone：hub_outer_dia_mm < lightening_hole_pcd_mm < web_outer_dia_mm
17. cooling holes 推荐落在 rim/web transition zone：web_outer_dia_mm < cooling_hole_pcd_mm < outer_dia_mm
18. 孔径不得破坏内外边界：
    pcd/2 - hole_dia/2 > inner_zone_radius + min_edge_clearance
    outer_zone_radius - (pcd/2 + hole_dia/2) > min_edge_clearance
19. 同一孔环孔间桥接厚度必须满足：
    chord_spacing = 2 * ring_radius * sin(pi / count)
    chord_spacing - hole_dia >= min_bridge_mm
20. bolt/lightening/cooling 三类孔环不得互相重叠：
    abs(pcd_a - pcd_b) / 2 >= (dia_a + dia_b) / 2 + min_edge_clearance
```

## 7.3 固定阈值

```python
MIN_EDGE_CLEARANCE_MM = 2.0
MIN_BRIDGE_MM = 2.0
MAX_FILLET_FRACTION_OF_LOCAL_WALL = 1.0 / 3.0
```

## 7.4 参考实现骨架

```python
from __future__ import annotations

import math

ALLOWED_QUALITY_GRADES = {"concept_geometry", "engineering_reference"}
MIN_EDGE_CLEARANCE_MM = 2.0
MIN_BRIDGE_MM = 2.0
MAX_FILLET_FRACTION_OF_LOCAL_WALL = 1.0 / 3.0


def _f(params: dict, key: str) -> float:
    return float(params.get(key, 0.0))


def _i(params: dict, key: str) -> int:
    return int(params.get(key, 0))


def _check_hole_ring(
    *,
    errors: list[str],
    label: str,
    count: int,
    pcd: float,
    dia: float,
    allowed_inner_dia: float,
    allowed_outer_dia: float,
) -> None:
    if count < 0:
        errors.append(f"{label}_hole_count must be >= 0")
        return

    if count == 0:
        if pcd not in (0, 0.0) or dia not in (0, 0.0):
            errors.append(
                f"{label} hole pcd/dia must be 0 when {label}_hole_count == 0"
            )
        return

    if count < 3:
        errors.append(f"{label}_hole_count must be >= 3 when enabled")

    if pcd <= 0:
        errors.append(f"{label}_hole_pcd_mm must be > 0 when enabled")

    if dia <= 0:
        errors.append(f"{label}_hole_dia_mm must be > 0 when enabled")

    ring_r = pcd / 2.0
    hole_r = dia / 2.0
    inner_r = allowed_inner_dia / 2.0
    outer_r = allowed_outer_dia / 2.0

    if ring_r - hole_r <= inner_r + MIN_EDGE_CLEARANCE_MM:
        errors.append(
            f"{label} holes too close to inner boundary: "
            f"ring_r-hole_r={ring_r-hole_r:.3f}, "
            f"required>{inner_r + MIN_EDGE_CLEARANCE_MM:.3f}"
        )

    if ring_r + hole_r >= outer_r - MIN_EDGE_CLEARANCE_MM:
        errors.append(
            f"{label} holes too close to outer boundary: "
            f"ring_r+hole_r={ring_r+hole_r:.3f}, "
            f"required<{outer_r - MIN_EDGE_CLEARANCE_MM:.3f}"
        )

    if count > 0 and pcd > 0 and dia > 0:
        chord = 2.0 * ring_r * math.sin(math.pi / count)
        bridge = chord - dia
        if bridge < MIN_BRIDGE_MM:
            errors.append(
                f"{label} hole spacing too small: bridge={bridge:.3f}mm, "
                f"required>={MIN_BRIDGE_MM}mm"
            )


def validate_axisymmetric_turbine_disk_parameters(params: dict) -> list[str]:
    errors: list[str] = []

    quality = str(params.get("quality_grade", "engineering_reference"))
    if quality not in ALLOWED_QUALITY_GRADES:
        errors.append(
            f"quality_grade must be one of {sorted(ALLOWED_QUALITY_GRADES)}, got {quality!r}"
        )

    if params.get("non_flight_reference_only", True) is not True:
        errors.append("non_flight_reference_only must be True")

    for axis_key in [
        "bolt_hole_axis",
        "lightening_hole_axis",
        "cooling_hole_axis",
    ]:
        if str(params.get(axis_key, "Z")).upper() != "Z":
            errors.append(f"{axis_key} must be 'Z' in phase 1")

    outer = _f(params, "outer_dia_mm")
    bore = _f(params, "bore_dia_mm")
    hub = _f(params, "hub_outer_dia_mm")
    web = _f(params, "web_outer_dia_mm")
    rim_inner = _f(params, "rim_inner_dia_mm")
    axial = _f(params, "axial_width_mm")
    hub_w = _f(params, "hub_width_mm")
    web_w = _f(params, "web_width_mm")
    rim_w = _f(params, "rim_width_mm")

    if not (outer > rim_inner > web > hub > bore >= 0):
        errors.append(
            "Diameter order must satisfy outer_dia_mm > rim_inner_dia_mm > "
            "web_outer_dia_mm > hub_outer_dia_mm > bore_dia_mm >= 0"
        )

    if axial <= 0:
        errors.append("axial_width_mm must be > 0")

    for key in ["hub_width_mm", "web_width_mm", "rim_width_mm"]:
        if _f(params, key) <= 0:
            errors.append(f"{key} must be > 0")
        if _f(params, key) > axial:
            errors.append(f"{key} must be <= axial_width_mm")

    if web_w > hub_w:
        errors.append("web_width_mm must be <= hub_width_mm")
    if web_w > rim_w:
        errors.append("web_width_mm must be <= rim_width_mm")

    local_radial_walls = [
        (hub - bore) / 2.0,
        (web - hub) / 2.0,
        (rim_inner - web) / 2.0,
        (outer - rim_inner) / 2.0,
    ]
    min_wall = min(local_radial_walls) if local_radial_walls else 0.0
    max_fillet = min_wall * MAX_FILLET_FRACTION_OF_LOCAL_WALL

    for key in [
        "hub_fillet_radius_mm",
        "web_fillet_radius_mm",
        "rim_fillet_radius_mm",
        "edge_chamfer_mm",
    ]:
        value = _f(params, key)
        if value < 0:
            errors.append(f"{key} must be >= 0")
        if value > max_fillet:
            errors.append(
                f"{key}={value} too large for local wall; max allowed {max_fillet:.3f}"
            )

    _check_hole_ring(
        errors=errors,
        label="bolt",
        count=_i(params, "bolt_hole_count"),
        pcd=_f(params, "bolt_pcd_mm"),
        dia=_f(params, "bolt_hole_dia_mm"),
        allowed_inner_dia=bore,
        allowed_outer_dia=hub,
    )

    _check_hole_ring(
        errors=errors,
        label="lightening",
        count=_i(params, "lightening_hole_count"),
        pcd=_f(params, "lightening_hole_pcd_mm"),
        dia=_f(params, "lightening_hole_dia_mm"),
        allowed_inner_dia=hub,
        allowed_outer_dia=web,
    )

    _check_hole_ring(
        errors=errors,
        label="cooling",
        count=_i(params, "cooling_hole_count"),
        pcd=_f(params, "cooling_hole_pcd_mm"),
        dia=_f(params, "cooling_hole_dia_mm"),
        allowed_inner_dia=web,
        allowed_outer_dia=outer,
    )

    rings = [
        ("bolt", _i(params, "bolt_hole_count"), _f(params, "bolt_pcd_mm"), _f(params, "bolt_hole_dia_mm")),
        ("lightening", _i(params, "lightening_hole_count"), _f(params, "lightening_hole_pcd_mm"), _f(params, "lightening_hole_dia_mm")),
        ("cooling", _i(params, "cooling_hole_count"), _f(params, "cooling_hole_pcd_mm"), _f(params, "cooling_hole_dia_mm")),
    ]
    active = [(n, p, d) for n, c, p, d in rings if c > 0]
    for idx, (na, pa, da) in enumerate(active):
        for nb, pb, db in active[idx + 1:]:
            radial_gap = abs(pa - pb) / 2.0 - (da + db) / 2.0
            if radial_gap < MIN_EDGE_CLEARANCE_MM:
                errors.append(
                    f"{na} and {nb} hole rings overlap or are too close: "
                    f"radial_gap={radial_gap:.3f}mm"
                )

    return errors
```

---

# 8. 轴对称 profile 生成

新增文件：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/turbine_disk/profile.py
```

## 8.1 原则

涡轮盘基础体通过**确定性二维母线 profile + revolve** 生成。不要用 LLM 生成 profile 点。

坐标约定：

```text
CadQuery Workplane("XZ")
x = 半径方向 r
z = 轴向方向 z
revolve around Z axis
```

基础母线要形成一个封闭多边形，内边界从 bore radius 开始。如果 `bore_dia_mm == 0`，内半径为 0。

## 8.2 固定函数

```python
def turbine_disk_profile_points(params: dict) -> list[tuple[float, float]]:
    ...
```

## 8.3 profile 规则

定义：

```python
outer_r = outer_dia_mm / 2
bore_r = bore_dia_mm / 2
hub_r = hub_outer_dia_mm / 2
web_r = web_outer_dia_mm / 2
rim_inner_r = rim_inner_dia_mm / 2

hub_half = hub_width_mm / 2
web_half = web_width_mm / 2
rim_half = rim_width_mm / 2
```

生成一个阶梯型轴对称截面：

```text
从内孔半径 bore_r 到 hub_r，厚度 hub_width
从 hub_r 到 web_r，厚度 web_width
从 web_r 到 rim_inner_r，过渡厚度 web_width
从 rim_inner_r 到 outer_r，厚度 rim_width
```

固定点序：

```python
[
    (bore_r, -hub_half),
    (hub_r, -hub_half),
    (hub_r, -web_half),
    (web_r, -web_half),
    (rim_inner_r, -rim_half),
    (outer_r, -rim_half),
    (outer_r, rim_half),
    (rim_inner_r, rim_half),
    (web_r, web_half),
    (hub_r, web_half),
    (hub_r, hub_half),
    (bore_r, hub_half),
]
```

如果 `bore_r == 0`，仍允许从中心线 revolve，但为了避免自交，可以用：

```python
bore_r = max(bore_dia_mm / 2.0, 0.0)
```

---

# 9. CadQuery adapter

新增文件：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/turbine_disk/cadquery_adapter.py
```

## 9.1 固定函数名

```python
def build_axisymmetric_turbine_disk(params: dict):
    """
    Returns (cadquery.Workplane, metadata_dict).
    """
```

## 9.2 构建逻辑

```text
1. 调 validator；
2. 生成 profile_points；
3. Workplane("XZ").polyline(profile_points).close().revolve(360, (0,0,0), (0,0,1))；
4. 如果 bore_dia_mm > 0，profile 已经包含中心孔，不必再 cut；
5. 对 bolt hole ring 做 Z 轴通孔；
6. 对 lightening hole ring 做 Z 轴通孔；
7. 对 cooling hole ring 做 Z 轴通孔；
8. 可选 chamfer/fillet，第一阶段失败时不要吞掉，应记录 warning 或直接 raise；
9. 返回 result + metadata。
```

## 9.3 CadQuery 孔环实现

建议第一阶段使用：

```python
result = (
    result.faces(">Z")
    .workplane()
    .polarArray(pcd / 2.0, 0, 360, count)
    .hole(hole_dia)
)
```

注意：这样是从上表面沿 Z 打孔，适用于第一阶段简化直通孔。

## 9.4 metadata 格式

必须返回：

```python
metadata = {
    "primitive": "axisymmetric_turbine_disk",
    "kernel": "cadquery_opencascade_revolve",
    "is_axisymmetric_base": True,
    "is_flight_certified": False,
    "non_flight_reference_only": True,
    "parameters": {k: v for k, v in params.items()},
    "reference_dimensions": {
        "outer_dia_mm": outer_dia_mm,
        "bore_dia_mm": bore_dia_mm,
        "axial_width_mm": axial_width_mm,
        "hub_outer_dia_mm": hub_outer_dia_mm,
        "web_outer_dia_mm": web_outer_dia_mm,
        "rim_inner_dia_mm": rim_inner_dia_mm,
    },
    "radial_zones": {
        "bore_radius_mm": bore_dia_mm / 2.0,
        "hub_outer_radius_mm": hub_outer_dia_mm / 2.0,
        "web_outer_radius_mm": web_outer_dia_mm / 2.0,
        "rim_inner_radius_mm": rim_inner_dia_mm / 2.0,
        "outer_radius_mm": outer_dia_mm / 2.0,
    },
    "profile_points": [[r, z], ...],
    "hole_patterns": {
        "bolt": {
            "count": bolt_hole_count,
            "pcd_mm": bolt_pcd_mm,
            "hole_dia_mm": bolt_hole_dia_mm,
            "axis": "Z",
        },
        "lightening": {...},
        "cooling": {...},
    },
    "warnings": [
        "Reference geometry only; not flight-certified or manufacturing-ready."
    ],
}
```

---

# 10. 接入 primitive registry

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/registry.py
```

当前 registry 只导入 gear primitive，而且 `except ImportError: pass` 会静默吞掉导入错误。这里在做涡轮盘时必须顺手修掉，因为涡轮盘也要注册，不能继续靠单个 gear import。([GitHub][8])

## 10.1 推荐改法

```python
PRIMITIVE_REGISTRY: dict[str, PrimitiveDefinition] = {}
_REGISTRY_LOAD_ERRORS: list[str] = []


def _register_all(definitions: list[PrimitiveDefinition]) -> None:
    for p in definitions:
        if p.name in PRIMITIVE_REGISTRY:
            _REGISTRY_LOAD_ERRORS.append(f"Duplicate primitive registered: {p.name}")
            continue
        PRIMITIVE_REGISTRY[p.name] = p


def _populate_registry():
    PRIMITIVE_REGISTRY.clear()
    _REGISTRY_LOAD_ERRORS.clear()

    try:
        from seekflow_engineering_tools.geometry_primitives.gears.models import GEAR_PRIMITIVES
        _register_all(GEAR_PRIMITIVES)
    except ImportError as exc:
        _REGISTRY_LOAD_ERRORS.append(
            f"Failed to import gear primitives: {type(exc).__name__}: {exc}"
        )

    try:
        from seekflow_engineering_tools.geometry_primitives.turbomachinery.turbine_disk.models import (
            TURBINE_DISK_PRIMITIVES,
        )
        _register_all(TURBINE_DISK_PRIMITIVES)
    except ImportError as exc:
        _REGISTRY_LOAD_ERRORS.append(
            f"Failed to import turbine disk primitives: {type(exc).__name__}: {exc}"
        )


def _raise_if_registry_unhealthy() -> None:
    if _REGISTRY_LOAD_ERRORS:
        raise RuntimeError("; ".join(_REGISTRY_LOAD_ERRORS))


def list_primitive_names() -> list[str]:
    _raise_if_registry_unhealthy()
    return sorted(PRIMITIVE_REGISTRY.keys())


def get_primitive(name: str) -> PrimitiveDefinition | None:
    _raise_if_registry_unhealthy()
    return PRIMITIVE_REGISTRY.get(name)
```

## 10.2 normalize 中增加涡轮盘 validator

在 `normalize_primitive_parameters()` 末尾新增：

```python
if primitive_name == "axisymmetric_turbine_disk":
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.turbine_disk.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )
    disk_errors = validate_axisymmetric_turbine_disk_parameters(normalized)
    if disk_errors:
        raise ValueError(
            "Turbine disk validation failed: " + "; ".join(disk_errors)
        )
```

---

# 11. 接入 primitive compiler

修改：

```text
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

当前只 dispatch `involute_spur_gear`。需要增加 `axisymmetric_turbine_disk`。([GitHub][5])

## 11.1 修改 dispatch

```python
def compile_primitive_to_cadquery_script(feature) -> list[str]:
    name = feature.primitive_name
    if name == "involute_spur_gear":
        return _compile_involute_spur_gear(feature)
    if name == "axisymmetric_turbine_disk":
        return _compile_axisymmetric_turbine_disk(feature)
    raise PrimitiveCompileError(
        f"Unknown primitive '{name}'. "
        f"Available: involute_spur_gear, axisymmetric_turbine_disk"
    )
```

## 11.2 新增 compiler 函数

```python
def _format_python_value(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return "True" if v else "False"
    if v is None:
        return "None"
    return repr(v)


def _compile_axisymmetric_turbine_disk(feature) -> list[str]:
    params = feature.parameters
    param_lines = []
    for k, v in params.items():
        param_lines.append(f"    {k!r}: {_format_python_value(v)},")

    code = f"""
# [Primitive: axisymmetric_turbine_disk]
from seekflow_engineering_tools.geometry_primitives.turbomachinery.turbine_disk.cadquery_adapter import (
    build_axisymmetric_turbine_disk,
)

_params = {{
{chr(10).join(param_lines)}
}}

result, PRIMITIVE_METADATA["axisymmetric_turbine_disk"] = build_axisymmetric_turbine_disk(_params)

BUILD_WARNINGS.extend(
    PRIMITIVE_METADATA["axisymmetric_turbine_disk"].get("warnings", [])
)
"""
    return code.strip().split("\\n")
```

注意：不要 import metadata writer。当前 compiler 已经统一在最终 script 中写 `_meta_payload`，不要为涡轮盘单独写 metadata 文件，以保持和 gear 一致。([GitHub][9])

---

# 12. builder metadata 检查改成 generic

当前 `_assert_metadata_sidecar()` 针对 gear 写了专门检查。涡轮盘要保持通用性，所以不能再继续写大量 if gear / if turbine。应该做两层：

```text
通用 primitive metadata 必填字段；
primitive-specific metadata 可选增强检查。
```

修改：

```text
src/seekflow_engineering_tools/cadquery_backend/builder.py
```

## 12.1 通用 metadata 字段

每个 primitive metadata 必须有：

```text
primitive
kernel
parameters
reference_dimensions
warnings
```

## 12.2 修改 `_assert_metadata_sidecar`

保留 gear-specific 检查，但先做 generic 检查：

```python
for feat in spec.features:
    if feat.type != "primitive":
        continue

    primitive_name = feat.primitive_name
    primitive_meta = pm.get(primitive_name)
    if primitive_meta is None:
        raise ValueError(f"Metadata missing primitive entry for '{primitive_name}'")

    for key in ["primitive", "kernel", "parameters", "reference_dimensions"]:
        if key not in primitive_meta:
            raise ValueError(
                f"Primitive metadata for '{primitive_name}' missing '{key}'"
            )

    if primitive_meta["primitive"] != primitive_name:
        raise ValueError(
            f"Primitive metadata name mismatch: expected '{primitive_name}', "
            f"got '{primitive_meta.get('primitive')}'"
        )

    if "warnings" not in primitive_meta:
        primitive_meta["warnings"] = []

    if primitive_name == "involute_spur_gear":
        if "is_standard_involute" not in primitive_meta:
            raise ValueError("Gear metadata missing 'is_standard_involute'")

    if primitive_name == "axisymmetric_turbine_disk":
        if "is_axisymmetric_base" not in primitive_meta:
            raise ValueError("Turbine disk metadata missing 'is_axisymmetric_base'")
        if "radial_zones" not in primitive_meta:
            raise ValueError("Turbine disk metadata missing 'radial_zones'")
        if "profile_points" not in primitive_meta:
            raise ValueError("Turbine disk metadata missing 'profile_points'")
        if "hole_patterns" not in primitive_meta:
            raise ValueError("Turbine disk metadata missing 'hole_patterns'")
        if primitive_meta.get("non_flight_reference_only") is not True:
            raise ValueError(
                "Turbine disk metadata must set non_flight_reference_only=True"
            )
```

---

# 13. Mechanical validation 扩展

新增：

```text
src/seekflow_engineering_tools/mechanical_validation/turbine_disk_validation.py
```

修改：

```text
src/seekflow_engineering_tools/mechanical_validation/common.py
```

当前 `common.py` 只 dispatch gear。需要增加涡轮盘分支。([GitHub][7])

## 13.1 common.py 分发逻辑

```python
elif name == "axisymmetric_turbine_disk":
    metadata_path = Path(str(step_path)).with_suffix(".metadata.json")
    raw_metadata = load_metadata(metadata_path)
    metadata = _unwrap_primitive_metadata(raw_metadata, name)

    from seekflow_engineering_tools.mechanical_validation.turbine_disk_validation import (
        validate_axisymmetric_turbine_disk_result,
    )

    expected = {}
    if getattr(spec, "validation", None) is not None:
        expected = spec.validation.primitive_validation.get(feature.id, {})

    result = validate_axisymmetric_turbine_disk_result(
        params=feature.parameters,
        inspection=inspection,
        metadata=metadata,
        expected=expected,
        tolerance_mm=spec.validation.tolerance_mm,
    )
```

## 13.2 validation 函数固定签名

```python
def validate_axisymmetric_turbine_disk_result(
    *,
    params: dict,
    inspection: dict,
    metadata: dict | None,
    expected: dict | None = None,
    tolerance_mm: float = 0.1,
) -> dict:
    ...
```

## 13.3 必须检查

```text
1. metadata exists
2. metadata.primitive == "axisymmetric_turbine_disk"
3. metadata.kernel == "cadquery_opencascade_revolve"
4. metadata.non_flight_reference_only is True
5. metadata.is_axisymmetric_base is True
6. metadata.parameters 与 CAD-IR params 完全一致
7. reference_dimensions.outer_dia_mm 匹配 params.outer_dia_mm
8. reference_dimensions.bore_dia_mm 匹配 params.bore_dia_mm
9. reference_dimensions.axial_width_mm 匹配 params.axial_width_mm
10. radial_zones 半径顺序正确
11. profile_points 存在，且不少于 8 个点
12. hole_patterns count 与 params count 一致
13. expected_primitive 匹配
14. expected_outer_dia_mm 匹配
15. expected_bore_dia_mm 匹配
16. expected_axial_width_mm 匹配
17. expected_bolt_hole_count 匹配
18. expected_lightening_hole_count 匹配
19. expected_cooling_hole_count 匹配
20. inspection bbox 与 outer_dia / axial_width 匹配
21. inspection body_count == 1
22. inspection hole_count_estimate 若存在，应与 bore + bolt + lightening + cooling 数量一致
```

## 13.4 返回格式

必须和 gear validation 一致：

```python
return {
    "ok": len(errors) == 0,
    "primitive": "axisymmetric_turbine_disk",
    "kernel": kernel,
    "reference_dimensions": ref,
    "issues": issues,
}
```

issue 格式：

```python
{
    "code": "turbine_disk_outer_dia_mismatch",
    "message": "...",
    "expected": 480.0,
    "actual": 479.7,
    "severity": "error"
}
```

---

# 14. Natural language normalizer 扩展

当前 `normalizer.py` 只有 gear trigger words 和 deprecated gear rewrite。涡轮盘要扩展 trigger，但不要在这里做复杂解析。自然语言真正参数抽取可以由 skill 做，normalizer 只做轻量识别和 ambiguity。([GitHub][10])

修改：

```text
src/seekflow_engineering_tools/natural_language/normalizer.py
```

## 14.1 增加 trigger words

```python
PRIMITIVE_TRIGGER_WORDS["axisymmetric_turbine_disk"] = [
    "turbine disk",
    "turbine rotor disk",
    "aero engine disk",
    "gas turbine disk",
    "涡轮盘",
    "航空发动机涡轮盘",
    "发动机轮盘",
    "涡轮转子盘",
    "轮毂",
    "腹板",
    "轮缘",
    "减重孔",
    "螺栓孔环",
]
```

## 14.2 ambiguity 检查

在 `detect_ambiguities()` 中支持 primitive name：

```python
required_params["axisymmetric_turbine_disk"] = [
    "outer_dia_mm",
    "bore_dia_mm",
    "axial_width_mm",
    "hub_outer_dia_mm",
    "web_outer_dia_mm",
    "rim_inner_dia_mm",
    "hub_width_mm",
    "web_width_mm",
    "rim_width_mm",
]
```

如果用户只说“做一个涡轮盘”，应该返回缺参，不要构建。

---

# 15. Capability registry 扩展

修改：

```text
src/seekflow_engineering_tools/capabilities/registry.py
```

## 15.1 增加 primitive

如第 2.5 节。

## 15.2 增加 caveat

CadQuery：

```python
"Turbine disk primitives are deterministic reference geometries only; not flight-certified."
```

SolidWorks/NX：

```python
"Turbine disk primitives are imported via canonical STEP; SolidWorks/NX must not regenerate turbine disk geometry."
```

## 15.3 建议新增函数

当前 capability registry 只有 `backend_supports_feature`，里面直接看 `stable_primitives`。为了保持通用性，建议新增：

```python
def backend_supports_primitive(backend: str, primitive_name: str) -> bool:
    cap = CAPABILITIES.get(backend, {})
    return primitive_name in cap.get("stable_primitives", [])
```

再让 `backend_supports_feature()` 调用它。

---

# 16. 新增 Claude skill

新增：

```text
.claude/skills/turbomachinery-cad-ir/SKILL.md
```

## 16.1 固定 skill 内容

```markdown
# Turbomachinery CAD-IR Skill

This skill converts natural-language turbomachinery modelling requests into SeekFlow Engineering CAD-IR.

## Scope

Supported primitive in phase 1:

- axisymmetric_turbine_disk

This skill must output CAD-IR only. It must not generate CadQuery, SolidWorks COM, NXOpen, APDL, or any direct CAD backend code.

## Safety boundary

Aero-engine turbine disks are safety-critical rotating parts. The output of this skill is reference geometry only.

The skill must not claim:

- flight-ready
- airworthy
- certified
- manufacturing-ready
- life-approved
- burst-safe
- fatigue-safe

If the user requests a real flight engine part, respond that the system can only generate reference CAD geometry from user-provided engineering parameters and must not replace expert design, FEA, life analysis, manufacturing review, or certification.

## Primitive selection

If the request mentions turbine disk / 涡轮盘 / 轮毂 / 腹板 / 轮缘 / 螺栓孔环 / 减重孔, use primitive:

axisymmetric_turbine_disk

## Required parameters

The skill must not invent these required parameters:

- outer_dia_mm
- bore_dia_mm
- axial_width_mm
- hub_outer_dia_mm
- web_outer_dia_mm
- rim_inner_dia_mm
- hub_width_mm
- web_width_mm
- rim_width_mm

If any required parameter is missing, return a missing-parameter diagnostic instead of CAD-IR.

## Optional defaults

The skill may fill these defaults:

- hub_fillet_radius_mm = 1.0
- web_fillet_radius_mm = 1.0
- rim_fillet_radius_mm = 1.0
- edge_chamfer_mm = 0.0
- bolt_hole_count = 0
- bolt_pcd_mm = 0.0
- bolt_hole_dia_mm = 0.0
- bolt_hole_axis = "Z"
- lightening_hole_count = 0
- lightening_hole_pcd_mm = 0.0
- lightening_hole_dia_mm = 0.0
- lightening_hole_axis = "Z"
- cooling_hole_count = 0
- cooling_hole_pcd_mm = 0.0
- cooling_hole_dia_mm = 0.0
- cooling_hole_axis = "Z"
- quality_grade = "engineering_reference"
- non_flight_reference_only = true

## Output format

Output a CADPartSpec-compatible JSON object with:

- nlcad_version = "0.1"
- units = "mm"
- features[0].type = "primitive"
- features[0].primitive_name = "axisymmetric_turbine_disk"
- validation.expected_bbox_mm = [outer_dia_mm, outer_dia_mm, axial_width_mm]
- validation.expected_body_count = 1
- validation.expected_kernel = "cadquery_opencascade_revolve"
- validation.primitive_validation[feature_id] contains expected turbine disk fields.

## Forbidden behavior

Do not:
- generate CAD code
- generate profile points directly
- infer unknown required dimensions
- use manufacturing_ready / flight_ready quality grade
- set non_flight_reference_only to false
- route SolidWorks or NX to regenerate turbine disk geometry
```

---

# 17. demo_full_chain 扩展

修改：

```text
integrations/engineering_tools/demo_full_chain.py
```

当前 demo 已经是统一入口模式，但前面审查指出它仍有假成功风险。新增涡轮盘 case 时，必须先修复 `overall_ok` 聚合，不能复制旧逻辑。当前 demo 的设计目标是 CI acceptance script。([GitHub][11])

## 17.1 新增 case

CLI 支持：

```bash
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case axisymmetric_turbine_disk --backend nx12 --allow-step-import
```

## 17.2 固定 demo 参数

```python
params = {
    "outer_dia_mm": 480.0,
    "bore_dia_mm": 80.0,
    "axial_width_mm": 60.0,
    "hub_outer_dia_mm": 150.0,
    "web_outer_dia_mm": 380.0,
    "rim_inner_dia_mm": 390.0,
    "hub_width_mm": 60.0,
    "web_width_mm": 28.0,
    "rim_width_mm": 52.0,
    "hub_fillet_radius_mm": 2.0,
    "web_fillet_radius_mm": 2.0,
    "rim_fillet_radius_mm": 2.0,
    "edge_chamfer_mm": 0.5,
    "bolt_hole_count": 36,
    "bolt_pcd_mm": 130.0,
    "bolt_hole_dia_mm": 8.0,
    "bolt_hole_axis": "Z",
    "lightening_hole_count": 24,
    "lightening_hole_pcd_mm": 260.0,
    "lightening_hole_dia_mm": 18.0,
    "lightening_hole_axis": "Z",
    "cooling_hole_count": 0,
    "cooling_hole_pcd_mm": 0.0,
    "cooling_hole_dia_mm": 0.0,
    "cooling_hole_axis": "Z",
    "quality_grade": "engineering_reference",
    "non_flight_reference_only": True,
}
```

## 17.3 expected hole count

第一阶段 hole count：

```python
expected_hole_count = (
    (1 if params["bore_dia_mm"] > 0 else 0)
    + params["bolt_hole_count"]
    + params["lightening_hole_count"]
    + params["cooling_hole_count"]
)
```

即 demo 为：

```text
1 + 36 + 24 + 0 = 61
```

## 17.4 必须 stage

涡轮盘 case 必须要求：

```text
validate_cad_ir
normalize_primitives
choose_backend
build
inspect
mechanical_validate
metadata
```

任一缺失或失败，`overall_ok=False`。

---

# 18. 必须新增测试

## 18.1 primitive registry

新增：

```text
tests/test_turbine_disk_primitive_registry.py
```

必须测试：

```python
def test_turbine_disk_registered():
    assert "axisymmetric_turbine_disk" in list_primitive_names()

def test_turbine_disk_supported_backends():
    pd = get_primitive("axisymmetric_turbine_disk")
    assert "cadquery" in pd.supported_backends
    assert "solidworks2025" in pd.supported_backends
    assert "nx12" in pd.supported_backends

def test_turbine_disk_supported_kernel():
    pd = get_primitive("axisymmetric_turbine_disk")
    assert "cadquery_opencascade_revolve" in pd.supported_kernels
```

## 18.2 参数 normalization

新增：

```text
tests/test_turbine_disk_parameters.py
```

必须测试：

```text
valid params pass
default optional params filled
missing required fails
unknown parameter fails
invalid quality_grade fails
non_flight_reference_only=False fails
non-Z hole axis fails
```

## 18.3 validator

新增：

```text
tests/test_turbine_disk_validator.py
```

必须测试：

```text
invalid diameter order fails
hub_width > axial_width fails
web_width > hub_width fails
fillet too large fails
bolt count > 0 but missing pcd/dia fails
bolt pcd outside hub zone fails
lightening pcd outside web zone fails
cooling pcd outside allowed zone fails
hole spacing too small fails
hole rings overlap fails
```

## 18.4 CadQuery compiler

新增：

```text
tests/test_turbine_disk_primitive_compiler.py
```

必须测试：

```text
compile_primitive_to_cadquery_script(axisymmetric_turbine_disk)
包含 build_axisymmetric_turbine_disk
包含 PRIMITIVE_METADATA["axisymmetric_turbine_disk"]
不包含 LLM / generated profile 字样
unknown primitive still fails
```

## 18.5 metadata sidecar

新增：

```text
tests/test_turbine_disk_metadata_sidecar.py
```

必须测试：

```text
metadata missing primitive entry fails
metadata missing kernel fails
metadata missing reference_dimensions fails
metadata missing radial_zones fails
metadata missing profile_points fails
metadata non_flight_reference_only != True fails
valid metadata passes _assert_metadata_sidecar
```

## 18.6 mechanical validation

新增：

```text
tests/test_turbine_disk_mechanical_validation.py
```

必须测试：

```text
metadata missing fails
primitive mismatch fails
kernel mismatch fails
non_flight_reference_only false fails
parameter mismatch fails
outer diameter mismatch fails
bore diameter mismatch fails
axial width mismatch fails
radial zone order invalid fails
profile_points missing fails
hole pattern count mismatch fails
inspection bbox mismatch fails
body_count mismatch fails
valid result passes
```

## 18.7 natural language validate/build

新增：

```text
tests/test_engineering_validate_cad_ir_turbine_disk.py
```

必须测试：

```text
engineering_validate_cad_ir accepts valid axisymmetric_turbine_disk
normalized_spec includes defaults
missing required parameter returns ok=False
backend cadquery supported
backend solidworks2025 supported
backend nx12 supported
unknown parameter returns ok=False
```

## 18.8 demo

新增：

```text
tests/test_demo_full_chain_turbine_disk.py
```

必须测试：

```text
demo case exists
demo uses engineering_validate_cad_ir
demo uses engineering_build_cad_model
metadata missing => overall_ok False
inspection missing => overall_ok False
mechanical_validation missing => overall_ok False
kernel mismatch => overall_ok False
valid mocked build => overall_ok True
```

## 18.9 SW/NX route

新增或扩展：

```text
tests/test_turbine_disk_step_import_strategy.py
```

必须测试：

```text
SolidWorks turbine disk primitive strategy == cadquery_step_import
NX turbine disk primitive strategy == cadquery_step_import
build_solidworks_from_canonical_step used for turbine disk
build_nx_from_canonical_step used for turbine disk
SolidWorks/NX never call direct turbine disk creation
```

---

# 19. 需要修复的通用漏洞

虽然本方案重点是涡轮盘，但为了让涡轮盘真正可靠，必须同步修这几个通用问题：

## 19.1 registry 不能吞 ImportError

当前 `registry.py` 有 `except ImportError: pass`，会导致 primitive 静默消失。涡轮盘新增后风险更大，必须改成记录并 fail-closed。([GitHub][8])

## 19.2 `rewrite_deprecated_recipes_to_primitives` 不应原地修改

当前 normalizer 直接修改传入 spec。涡轮盘虽然不一定用 rewrite，但自然语言入口会经过这个函数。建议 `copy.deepcopy(spec)` 后再修改，避免调用方复用 spec 时出现副作用。([GitHub][10])

## 19.3 builder 的 metadata 检查要通用化

当前 `_assert_metadata_sidecar()` 偏 gear，要扩展成 generic primitive metadata + primitive-specific metadata。([GitHub][6])

## 19.4 demo 的 `overall_ok` 必须统一 finalize

涡轮盘 demo 不准复制旧的 build.ok 覆盖逻辑。最终成功必须由 required stages 聚合。

---

# 20. Claude Code 执行 Prompt

下面这段可以直接复制给 Claude Code。

```text
你要在当前 SeekFlow Engineering Tools 架构基础上实现自然语言驱动的航空发动机涡轮盘参考几何建模能力。禁止大幅度改架构，禁止新增独立 turbine_disk build tool，必须复用 CAD-IR、Primitive Registry、Capability Registry、engineering_validate_cad_ir、engineering_build_cad_model、CadQuery primitive compiler、metadata sidecar、inspection、mechanical_validation、SolidWorks/NX canonical STEP import 这条现有通用链路。

一、总体目标

新增 primitive：

axisymmetric_turbine_disk

它表示轴对称涡轮盘参考几何，包含 hub-web-rim 盘体、中心孔、可选螺栓孔环、可选减重孔环、可选简化冷却孔环。第一阶段不要做真实 fir-tree 榫槽、真实叶片连接、真实复杂冷却孔、真实适航/制造认证设计。

LLM / Claude skill 只输出 CAD-IR，不得生成 CAD 代码。几何必须由 deterministic primitive kernel 生成。

二、必须新增或修改文件

1. 修改：
src/seekflow_engineering_tools/ir/cad.py

在 ValidationSpec 中新增通用字段：
primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)

增加 validator，确保 primitive_validation key 是非空 feature id，value 是 dict。

不要为涡轮盘新增大量 expected_turbine_xxx 字段，保持 schema 通用。

2. 新增目录：
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/turbine_disk/

新增文件：
__init__.py
models.py
validator.py
profile.py
cadquery_adapter.py
metadata.py

3. models.py 必须注册：

TURBINE_DISK_PRIMITIVES = [
    PrimitiveDefinition(
        name="axisymmetric_turbine_disk",
        category="turbomachinery",
        ...
    )
]

参数必须严格使用以下名称，不得自行改名：

outer_dia_mm
bore_dia_mm
axial_width_mm
hub_outer_dia_mm
web_outer_dia_mm
rim_inner_dia_mm
hub_width_mm
web_width_mm
rim_width_mm
hub_fillet_radius_mm default 1.0
web_fillet_radius_mm default 1.0
rim_fillet_radius_mm default 1.0
edge_chamfer_mm default 0.0
bolt_hole_count default 0
bolt_pcd_mm default 0.0
bolt_hole_dia_mm default 0.0
bolt_hole_axis default "Z"
lightening_hole_count default 0
lightening_hole_pcd_mm default 0.0
lightening_hole_dia_mm default 0.0
lightening_hole_axis default "Z"
cooling_hole_count default 0
cooling_hole_pcd_mm default 0.0
cooling_hole_dia_mm default 0.0
cooling_hole_axis default "Z"
quality_grade default "engineering_reference"
non_flight_reference_only default True

supported_kernels = ["cadquery_opencascade_revolve"]
supported_backends = ["cadquery", "solidworks2025", "nx12"]

4. validator.py 必须实现：

validate_axisymmetric_turbine_disk_parameters(params: dict) -> list[str]

必须检查：
- quality_grade 只能是 concept_geometry 或 engineering_reference
- non_flight_reference_only 必须为 True
- bolt/lightening/cooling hole axis 必须是 "Z"
- outer_dia_mm > rim_inner_dia_mm > web_outer_dia_mm > hub_outer_dia_mm > bore_dia_mm >= 0
- axial_width_mm > 0
- hub_width_mm/web_width_mm/rim_width_mm > 0 且 <= axial_width_mm
- web_width_mm <= hub_width_mm
- web_width_mm <= rim_width_mm
- fillet/chamfer 不得超过局部最小径向壁厚的 1/3
- count > 0 时对应 pcd/dia 必须 > 0
- count == 0 时对应 pcd/dia 必须为 0
- bolt holes 位于 bore 到 hub zone 内
- lightening holes 位于 hub 到 web zone 内
- cooling holes 位于 web 到 outer zone 内
- 孔边缘与区间边界至少 2mm clearance
- 同一孔环孔间桥接厚度至少 2mm
- 各孔环之间径向间隙至少 2mm

5. profile.py 必须实现：

turbine_disk_profile_points(params: dict) -> list[tuple[float, float]]

坐标约定：
Workplane("XZ")
x = radius
z = axial coordinate
revolve around Z axis

固定 profile 点序：
(bore_r, -hub_half)
(hub_r, -hub_half)
(hub_r, -web_half)
(web_r, -web_half)
(rim_inner_r, -rim_half)
(outer_r, -rim_half)
(outer_r, rim_half)
(rim_inner_r, rim_half)
(web_r, web_half)
(hub_r, web_half)
(hub_r, hub_half)
(bore_r, hub_half)

6. cadquery_adapter.py 必须实现：

build_axisymmetric_turbine_disk(params: dict)

流程：
- 调 validate_axisymmetric_turbine_disk_parameters
- 生成 profile_points
- 使用 cadquery Workplane("XZ").polyline(profile_points).close().revolve(360, (0,0,0), (0,0,1))
- 按 Z 轴切 bolt/lightening/cooling hole rings
- 返回 result, metadata

metadata 必须包含：
primitive = "axisymmetric_turbine_disk"
kernel = "cadquery_opencascade_revolve"
is_axisymmetric_base = True
is_flight_certified = False
non_flight_reference_only = True
parameters
reference_dimensions
radial_zones
profile_points
hole_patterns
warnings

warnings 至少包含：
"Reference geometry only; not flight-certified or manufacturing-ready."

7. 修改：
src/seekflow_engineering_tools/geometry_primitives/registry.py

当前 registry 不能只注册 gear。要注册 gear + turbine disk。
禁止 except ImportError: pass。
导入失败必须记录 _REGISTRY_LOAD_ERRORS，并在 list_primitive_names/get_primitive 时 fail-closed raise RuntimeError。
normalize_primitive_parameters 中新增 axisymmetric_turbine_disk validator 调用。

8. 修改：
src/seekflow_engineering_tools/capabilities/registry.py

cadquery/solidworks2025/nx12 的 stable_primitives 增加 axisymmetric_turbine_disk。
cadquery strategy = native_cadquery_primitive。
solidworks2025/nx12 strategy = cadquery_step_import。
增加 caveats，说明 turbine disk 是 reference geometry only，SW/NX 只 import STEP。
建议新增 backend_supports_primitive，并让 backend_supports_feature 调用它。

9. 修改：
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py

compile_primitive_to_cadquery_script 增加 axisymmetric_turbine_disk 分支。
新增 _compile_axisymmetric_turbine_disk(feature)，它必须调用 build_axisymmetric_turbine_disk，写入：
PRIMITIVE_METADATA["axisymmetric_turbine_disk"]

不得生成 profile 点代码，profile 必须由 adapter deterministic function 生成。

10. 修改：
src/seekflow_engineering_tools/cadquery_backend/builder.py

_assert_metadata_sidecar 要从 gear-only 改成 generic primitive metadata 检查：
每个 primitive metadata 必须有 primitive/kernel/parameters/reference_dimensions/warnings。
如果 primitive 是 axisymmetric_turbine_disk，还必须有：
is_axisymmetric_base
radial_zones
profile_points
hole_patterns
non_flight_reference_only=True

保留 gear-specific 检查，不要破坏 gear。

11. 新增：
src/seekflow_engineering_tools/mechanical_validation/turbine_disk_validation.py

实现：
validate_axisymmetric_turbine_disk_result(
    *,
    params: dict,
    inspection: dict,
    metadata: dict | None,
    expected: dict | None = None,
    tolerance_mm: float = 0.1,
) -> dict

必须 hard-check：
- metadata exists
- metadata.primitive == axisymmetric_turbine_disk
- metadata.kernel == cadquery_opencascade_revolve
- metadata.non_flight_reference_only is True
- metadata.is_axisymmetric_base is True
- metadata.parameters 与 CAD-IR params 一致
- reference_dimensions outer/bore/axial/hub/web/rim 匹配 params
- radial_zones 顺序正确
- profile_points 存在且长度 >= 8
- hole_patterns count 与 params count 一致
- expected dict 中 expected_* 字段匹配
- inspection bbox 匹配 outer_dia_mm, outer_dia_mm, axial_width_mm
- inspection body_count == 1
- inspection hole_count_estimate 若存在，应等于 bore + bolt + lightening + cooling

返回格式：
{
  "ok": bool,
  "primitive": "axisymmetric_turbine_disk",
  "kernel": "...",
  "reference_dimensions": {...},
  "issues": [...]
}

12. 修改：
src/seekflow_engineering_tools/mechanical_validation/common.py

validate_mechanical_primitives 增加 axisymmetric_turbine_disk 分支。
从 metadata sidecar unwrap primitive metadata。
从 spec.validation.primitive_validation[feature.id] 读取 expected。
调用 validate_axisymmetric_turbine_disk_result。

13. 修改：
src/seekflow_engineering_tools/natural_language/normalizer.py

PRIMITIVE_TRIGGER_WORDS 增加 axisymmetric_turbine_disk 触发词：
turbine disk
turbine rotor disk
aero engine disk
gas turbine disk
涡轮盘
航空发动机涡轮盘
发动机轮盘
涡轮转子盘
轮毂
腹板
轮缘
减重孔
螺栓孔环

detect_ambiguities 增加 axisymmetric_turbine_disk 必填参数清单：
outer_dia_mm
bore_dia_mm
axial_width_mm
hub_outer_dia_mm
web_outer_dia_mm
rim_inner_dia_mm
hub_width_mm
web_width_mm
rim_width_mm

建议 rewrite_deprecated_recipes_to_primitives 使用 copy.deepcopy，避免原地修改输入。

14. 新增 Claude skill：
.claude/skills/turbomachinery-cad-ir/SKILL.md

内容必须说明：
- 只输出 CAD-IR
- 不生成 CAD 代码
- 不猜必填参数
- 涡轮盘是 reference geometry only
- 不声明 flight-ready/airworthy/certified/manufacturing-ready
- 必须设置 non_flight_reference_only=true
- 必填参数缺失时返回 missing parameter diagnostic

15. 修改 demo_full_chain.py

新增 case：
axisymmetric_turbine_disk

支持：
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case axisymmetric_turbine_disk --backend nx12 --allow-step-import

demo 参数固定：
outer_dia_mm=480
bore_dia_mm=80
axial_width_mm=60
hub_outer_dia_mm=150
web_outer_dia_mm=380
rim_inner_dia_mm=390
hub_width_mm=60
web_width_mm=28
rim_width_mm=52
hub_fillet_radius_mm=2
web_fillet_radius_mm=2
rim_fillet_radius_mm=2
edge_chamfer_mm=0.5
bolt_hole_count=36
bolt_pcd_mm=130
bolt_hole_dia_mm=8
bolt_hole_axis="Z"
lightening_hole_count=24
lightening_hole_pcd_mm=260
lightening_hole_dia_mm=18
lightening_hole_axis="Z"
cooling_hole_count=0
cooling_hole_pcd_mm=0
cooling_hole_dia_mm=0
cooling_hole_axis="Z"
quality_grade="engineering_reference"
non_flight_reference_only=True

validation:
expected_bbox_mm=[480,480,60]
expected_body_count=1
expected_hole_count=61
expected_through_hole_count=61
expected_kernel="cadquery_opencascade_revolve"
primitive_validation["disk1"] 包含 expected outer/bore/axial/hub/web/rim/bolt/lightening/cooling/quality/non_flight 字段。

demo 必须走 engineering_validate_cad_ir 和 engineering_build_cad_model。
必须包含 stages：
validate_cad_ir
normalize_primitives
choose_backend
build
inspect
mechanical_validate
metadata

任一 stage 缺失或 ok 不是 True，overall_ok 必须 False。
不得用 build_result.get("ok") 单独把 overall_ok 设回 True。

16. 新增测试

必须新增：
tests/test_turbine_disk_primitive_registry.py
tests/test_turbine_disk_parameters.py
tests/test_turbine_disk_validator.py
tests/test_turbine_disk_primitive_compiler.py
tests/test_turbine_disk_metadata_sidecar.py
tests/test_turbine_disk_mechanical_validation.py
tests/test_engineering_validate_cad_ir_turbine_disk.py
tests/test_demo_full_chain_turbine_disk.py
tests/test_turbine_disk_step_import_strategy.py
tests/test_turbomachinery_skill_contract.py

测试必须覆盖：
- valid disk passes
- default optional params filled
- missing required fails
- unknown parameter fails
- invalid diameter order fails
- invalid quality_grade fails
- non_flight_reference_only false fails
- non-Z hole axis fails
- hole pcd/dia missing fails
- hole outside allowed zone fails
- hole spacing too small fails
- hole rings overlap fails
- compiler calls deterministic adapter
- metadata missing fails
- metadata missing radial_zones/profile_points/hole_patterns fails
- mechanical validation parameter mismatch fails
- bbox mismatch fails
- body_count mismatch fails
- demo metadata missing fails
- demo mechanical_validation missing fails
- SW/NX strategy is cadquery_step_import
- no direct SW/NX turbine disk generation function is routed

17. 最后运行：
cd integrations/engineering_tools
python -m compileall src demo_full_chain.py
python -m pytest

如果环境有 CadQuery：
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery --json-report reports/turbine_disk_cadquery.json

成功条件：
overall_ok=true
kernel_used=cadquery_opencascade_revolve
metadata stage ok=true
inspect stage ok=true
mechanical_validate stage ok=true
STEP exists and non-empty
metadata.json exists and non-empty

如果环境没有 CadQuery，可以跳过真实 CAD build 测试，但纯逻辑、registry、validation、compiler、mechanical validation、demo mocked fail-closed 测试不能跳过。
```

---

# 21. 最终验收标准

Claude Code 完成后，必须满足：

```text
1. axisymmetric_turbine_disk 出现在 list_primitive_names()
2. engineering_validate_cad_ir 能 normalize 涡轮盘参数
3. 必填参数缺失时 ok=False
4. unknown parameter 时 ok=False
5. 非法直径顺序时 ok=False
6. non_flight_reference_only=False 时 ok=False
7. cadquery backend 策略为 native_cadquery_primitive
8. solidworks2025/nx12 策略为 cadquery_step_import
9. primitive_compiler 不生成 profile 点，只调用 deterministic adapter
10. STEP 生成后必须有 metadata sidecar
11. metadata 必须包含 radial_zones/profile_points/hole_patterns
12. mechanical_validation 必须检查 CAD-IR params 与 metadata params 一致
13. demo_full_chain turbine disk case 必须走统一入口
14. demo 缺 metadata/inspection/mechanical_validation 时必须 fail
15. SolidWorks/NX 不得重新生成涡轮盘几何，只 import canonical STEP
16. compileall 通过
17. pytest 通过
```

---

# 22. 你后续使用自然语言时的推荐输入格式

当这个能力实现后，你可以这样说：

```text
用 CadQuery 构建一个航空发动机涡轮盘参考几何：
外径 480mm，中心孔 80mm，总轴向宽度 60mm；
轮毂外径 150mm，腹板外径 380mm，轮缘内径 390mm；
轮毂宽 60mm，腹板宽 28mm，轮缘宽 52mm；
36 个螺栓孔，PCD 130mm，孔径 8mm；
24 个减重孔，PCD 260mm，孔径 18mm；
不做冷却孔；
质量等级 engineering_reference，仅作为 non-flight reference。
```

系统应该输出 CAD-IR，然后走统一 build 链路。

如果你只说：

```text
帮我做一个航空发动机涡轮盘。
```

系统必须返回缺参，而不是自己脑补参数。

---

# 23. 核心结论

你的需求应该这样实现：

```text
不是给涡轮盘写一个孤立 builder；
不是让 LLM 写 CAD；
不是把架构改成专用航空发动机系统；

而是在当前通用 primitive 架构中新增：
axisymmetric_turbine_disk primitive
+ deterministic CadQuery/OpenCascade adapter
+ generic metadata sidecar
+ turbine_disk mechanical validation
+ turbomachinery CAD-IR skill
+ demo_full_chain case
+ 完整 fail-closed tests。
```

这样既能满足你“自然语言建模涡轮盘”的目标，又不会破坏现有 SeekFlow Engineering 的通用 Text-to-CAD 架构。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/base.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/compiler.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/normalizer.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/demo_full_chain.py "raw.githubusercontent.com"
