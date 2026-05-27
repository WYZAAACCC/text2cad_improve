

# SeekFlow Engineering 工业级 Text-to-CAD 最终实施文档 vFinal

## 0. 总目标

把当前 `integrations/engineering_tools` 从“LLM 调用 CAD 工具”升级为：

```text
自然语言
→ CAD-IR
→ Recipe / Primitive 规范化
→ Capability 路由
→ Mechanical Geometry Primitive Kernel
→ Backend Adapter
→ STEP / native CAD 文件
→ Geometry Inspection
→ Mechanical Validation
→ Repair Diagnostics
→ 可回归测试 / demo_full_chain 验收
```

最终目标不是让大模型直接写 SolidWorks COM、NXOpen、CadQuery 曲线代码或 APDL，而是让大模型只负责：

```text
理解意图
抽取参数
选择 recipe / primitive
输出结构化 CAD-IR
```

所有复杂几何必须由确定性代码生成。

---

# 1. 最终内核选择

## 1.1 底层几何内核

最终采用：

```text
OpenCascade BREP
```

当前通过：

```text
CadQuery
```

调用 OpenCascade。

CadQuery 官方定位是用 Python 脚本生成参数化 3D CAD 模型，并输出 STEP、AMF、3MF、STL 等高质量 CAD 格式，这正适合作为当前系统的 canonical geometry backend。([cadquery.readthedocs.io][1])

## 1.2 齿轮专用内核

齿轮 primitive 使用：

```text
CQ_Gears
```

CQ_Gears 是基于 CadQuery 的 involute profile gear generator，支持 Spur、Helical、Herringbone、Ring、Planetary、Bevel、Rack 等齿轮类型；其 README 给出的最小用法就是 `SpurGear(...)` 后通过 `cq.Workplane("XY").gear(spur_gear)` 构建实体。([GitHub][2])

注意：CQ_Gears README 也明确写了该项目 “Work in progress / Might be unstable”，并说明需要较新的 CadQuery 环境。([GitHub][2])
因此不能把 CQ_Gears 原样暴露给 LLM，而必须包一层 adapter、参数校验、metadata sidecar、fallback warning 和 regression tests。

## 1.3 build123d 的定位

build123d 也是基于 Open Cascade 的 Python 参数化 BREP 建模框架，可用于 3D 打印、CNC、激光切割等制造场景，并可导出到 FreeCAD、SolidWorks 等工具。([build123d.readthedocs.io][3])

最终策略：

```text
P0/P1：CadQuery + CQ_Gears 作为主线
P2：build123d 作为第二建模前端 / fallback / 对照验证内核
```

不要在第一阶段同时让 CadQuery 和 build123d 都成为主线，否则复杂度过高。

---

# 2. 当前仓库核心问题

当前 `recipes/mechanical.py` 中的 `spur_gear` 描述仍是：

```text
Spur gear — star-polygon body with centre bore.
```

它只包含：

```text
module_mm
teeth
face_width_mm
bore_dia_mm
```

这说明当前 `spur_gear` 本质是视觉近似齿轮，不是标准渐开线齿轮。([GitHub][4])

同时，`natural_language/tools.py` 中的 `engineering_build_cad_model` 已能选择 backend，但 SolidWorks 和 NX 分支仍返回“不能直接驱动 SolidWorks COM / NX bridge，请使用具体工具”的错误路径，这会打断统一自然语言建模主链。([GitHub][5])

因此这次最终实现必须解决两个核心问题：

```text
1. 把 spur_gear 从 legacy visual recipe 升级为 deterministic primitive。
2. 让 engineering_build_cad_model 成为所有 backend 的统一入口。
```

---

# 3. 最终架构

## 3.1 总体架构

```text
User Natural Language
        ↓
LLM Semantic Parser
        ↓
CAD-IR v0.2
        ↓
Normalizer
  - recipe normalization
  - primitive normalization
  - deprecated recipe rewrite
        ↓
Capability Router
        ↓
Build Planner
        ↓
Mechanical Geometry Primitive Kernel
  - CadQuery generic primitives
  - CQ_Gears gear primitives
  - future build123d primitives
        ↓
Backend Adapter
  - cadquery backend
  - solidworks step import / native save
  - nx step import / native save
        ↓
Output
  - STEP
  - metadata.json
  - optional SLDPRT / PRT
        ↓
Inspection
        ↓
Mechanical Validation
        ↓
EngineeringActionResult
        ↓
Repair Diagnostics
```

## 3.2 设计原则

Claude Code 必须遵守以下原则：

```text
1. LLM 不生成复杂几何代码。
2. LLM 不推导渐开线、螺纹、弹簧、凸轮、齿根过渡曲线。
3. LLM 只输出 CAD-IR。
4. 齿轮、螺纹、弹簧、轴承、花键、凸轮等必须是 primitive。
5. primitive 由 deterministic geometry kernel 生成。
6. CadQuery/CQ_Gears 生成 canonical STEP。
7. SolidWorks/NX 对复杂 primitive 只导入 STEP 并保存 native。
8. 所有输出必须有 metadata sidecar。
9. 所有模型必须经过 inspection + validation。
10. 不能因为 STEP 文件存在就认为模型正确。
```

---

# 4. 必须新增的目录结构

在：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/
```

新增：

```text
geometry_primitives/
  __init__.py
  base.py
  registry.py
  graph.py

  gears/
    __init__.py
    models.py
    standards.py
    validator.py
    cq_gears_adapter.py
    cadquery_fallback.py
    metadata.py

  shafts/
    __init__.py
    models.py
    cadquery_adapter.py
    validator.py

  threads/
    __init__.py
    models.py
    iso_metric.py
    cadquery_adapter.py
    validator.py

  springs/
    __init__.py
    models.py
    cadquery_adapter.py
    validator.py

standards/
  __init__.py
  units.py
  tolerances.py
  gears_iso.py
  fits.py

mechanical_validation/
  __init__.py
  common.py
  gear_validation.py
  topology_validation.py

benchmark/
  __init__.py
  cases.py
  runner.py
  report.py
```

修改已有目录：

```text
ir/
  primitive.py       # 新增
  cad.py            # 接入 PrimitiveFeature

cadquery_backend/
  primitive_compiler.py   # 新增
  compiler.py             # 接入 primitive compiler
  builder.py              # 输出 metadata sidecar

natural_language/
  normalizer.py           # 新增或强化
  backend_builders.py     # 统一 SW/NX/CQ build

recipes/
  mechanical.py           # spur_gear legacy 化
  registry.py             # recipe → primitive rewrite 支持

capabilities/
  registry.py             # stable_primitives / primitive_strategy

inspection/
  validation.py           # 支持 gear-specific validation issue

repair/
  diagnostics.py          # 接入 primitive failures
```

---

# 5. CAD-IR v0.2：新增 PrimitiveFeature

## 5.1 新增 `ir/primitive.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrimitiveFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["primitive"] = "primitive"
    primitive_name: str
    parameters: dict[str, Any]
    placement: dict[str, Any] = Field(default_factory=dict)
    operation: Literal["new_body", "add", "cut"] = "new_body"

    @model_validator(mode="after")
    def validate_name(self):
        if not self.primitive_name:
            raise ValueError("primitive_name is required")
        return self
```

## 5.2 修改 `ir/cad.py`

在现有 feature union 中加入：

```python
from seekflow_engineering_tools.ir.primitive import PrimitiveFeature
```

然后：

```python
CADFeature = Annotated[
    ExtrudeFeature
    | HoleFeature
    | CircularPatternHolesFeature
    | FilletFeature
    | ChamferFeature
    | RecipeFeature
    | PrimitiveFeature,
    Field(discriminator="type"),
]
```

如果当前代码没有 discriminated union，就按现有写法加入 `PrimitiveFeature`，但必须保证 Pydantic 能正确解析：

```json
{
  "type": "primitive",
  "primitive_name": "involute_spur_gear",
  "parameters": {}
}
```

## 5.3 扩展 ValidationSpec

`CADPartSpec.validation` 需要支持机械验证字段：

```python
expected_tooth_count: int | None = None
expected_pitch_diameter_mm: float | None = None
expected_outer_diameter_mm: float | None = None
expected_root_diameter_mm: float | None = None
expected_base_diameter_mm: float | None = None
expected_bore_diameter_mm: float | None = None
expected_face_width_mm: float | None = None
expected_kernel: str | None = None
```

---

# 6. Primitive Registry

## 6.1 `geometry_primitives/base.py`

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class PrimitiveParameter(BaseModel):
    name: str
    type: Literal["float", "int", "str", "bool"]
    unit: str | None = None
    required: bool = True
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    description: str = ""


class PrimitiveDefinition(BaseModel):
    name: str
    category: str
    description: str
    parameters: list[PrimitiveParameter]
    supported_kernels: list[str]
    supported_backends: list[str]
    standards: list[str] = Field(default_factory=list)
    validation_defaults: dict[str, Any] = Field(default_factory=dict)
```

## 6.2 `geometry_primitives/registry.py`

```python
from __future__ import annotations

from typing import Any
from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition
from seekflow_engineering_tools.geometry_primitives.gears.models import GEAR_PRIMITIVES

PRIMITIVE_REGISTRY: dict[str, PrimitiveDefinition] = {}

for primitive in GEAR_PRIMITIVES:
    PRIMITIVE_REGISTRY[primitive.name] = primitive


def list_primitive_names() -> list[str]:
    return sorted(PRIMITIVE_REGISTRY)


def get_primitive(name: str) -> PrimitiveDefinition | None:
    return PRIMITIVE_REGISTRY.get(name)


def normalize_primitive_parameters(
    primitive_name: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    definition = get_primitive(primitive_name)
    if definition is None:
        raise ValueError(f"Unknown primitive: {primitive_name}")

    schema = {p.name: p for p in definition.parameters}
    unknown = set(parameters) - set(schema)
    if unknown:
        raise ValueError(
            f"Unknown parameters for primitive '{primitive_name}': {sorted(unknown)}"
        )

    normalized: dict[str, Any] = {}

    for name, p in schema.items():
        if name in parameters:
            raw = parameters[name]
        elif p.default is not None:
            raw = p.default
        elif p.required:
            raise ValueError(
                f"Missing required parameter '{name}' for primitive '{primitive_name}'"
            )
        else:
            continue

        if p.type == "float":
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be float, got bool")
            value = float(raw)
        elif p.type == "int":
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be int, got bool")
            value = int(raw)
        elif p.type == "str":
            value = str(raw)
        elif p.type == "bool":
            if not isinstance(raw, bool):
                raise ValueError(f"{name} must be bool")
            value = raw
        else:
            raise ValueError(f"Unsupported primitive parameter type: {p.type}")

        if p.min_value is not None and value < p.min_value:
            raise ValueError(f"{name}={value} below min {p.min_value}")
        if p.max_value is not None and value > p.max_value:
            raise ValueError(f"{name}={value} above max {p.max_value}")

        normalized[name] = value

    if primitive_name == "involute_spur_gear":
        from seekflow_engineering_tools.geometry_primitives.gears.validator import (
            validate_involute_spur_gear_parameters,
        )
        validate_involute_spur_gear_parameters(normalized)

    return normalized


def backend_supports_primitive(backend: str, primitive_name: str) -> bool:
    definition = get_primitive(primitive_name)
    if definition is None:
        return False
    return backend in definition.supported_backends
```

---

# 7. 齿轮 primitive：`involute_spur_gear`

## 7.1 `geometry_primitives/gears/models.py`

```python
from seekflow_engineering_tools.geometry_primitives.base import (
    PrimitiveDefinition,
    PrimitiveParameter,
)


GEAR_PRIMITIVES = [
    PrimitiveDefinition(
        name="involute_spur_gear",
        category="gear",
        description=(
            "Engineering-grade involute spur gear generated by deterministic "
            "mechanical geometry kernel. Use this for real spur gears."
        ),
        standards=["ISO_53_like", "DIN_867_like"],
        supported_kernels=["cq_gears", "cadquery_visual_fallback"],
        supported_backends=["cadquery", "solidworks2025", "nx12"],
        parameters=[
            PrimitiveParameter(
                name="module_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.05,
                description="Gear module in millimeters.",
            ),
            PrimitiveParameter(
                name="teeth",
                type="int",
                required=True,
                min_value=6,
                description="Number of teeth.",
            ),
            PrimitiveParameter(
                name="pressure_angle_deg",
                type="float",
                unit="deg",
                required=False,
                default=20.0,
                min_value=14.5,
                max_value=30.0,
            ),
            PrimitiveParameter(
                name="face_width_mm",
                type="float",
                unit="mm",
                required=True,
                min_value=0.1,
            ),
            PrimitiveParameter(
                name="bore_dia_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
            ),
            PrimitiveParameter(
                name="addendum_coefficient",
                type="float",
                required=False,
                default=1.0,
                min_value=0.5,
                max_value=1.5,
            ),
            PrimitiveParameter(
                name="clearance_coefficient",
                type="float",
                required=False,
                default=0.25,
                min_value=0.05,
                max_value=0.6,
            ),
            PrimitiveParameter(
                name="profile_shift_coefficient",
                type="float",
                required=False,
                default=0.0,
                min_value=-1.0,
                max_value=1.0,
            ),
            PrimitiveParameter(
                name="backlash_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
            ),
            PrimitiveParameter(
                name="root_fillet_radius_mm",
                type="float",
                unit="mm",
                required=False,
                default=0.0,
                min_value=0.0,
            ),
            PrimitiveParameter(
                name="quality_grade",
                type="str",
                required=False,
                default="industrial_brep",
            ),
        ],
        validation_defaults={
            "expected_body_count": 1,
            "tolerance_mm": 0.05,
        },
    )
]
```

---

# 8. 齿轮标准尺寸计算

## 8.1 `geometry_primitives/gears/standards.py`

```python
from __future__ import annotations

import math


def spur_gear_reference_dimensions(params: dict) -> dict:
    m = float(params["module_mm"])
    z = int(params["teeth"])
    alpha = math.radians(float(params.get("pressure_angle_deg", 20.0)))
    ha = float(params.get("addendum_coefficient", 1.0))
    c = float(params.get("clearance_coefficient", 0.25))
    x = float(params.get("profile_shift_coefficient", 0.0))
    backlash = float(params.get("backlash_mm", 0.0))

    pitch_d = m * z
    base_d = pitch_d * math.cos(alpha)

    outer_d = m * (z + 2.0 * (ha + x))
    root_d = pitch_d - 2.0 * m * (ha + c - x)

    circular_pitch = math.pi * m
    tooth_thickness_pitch = circular_pitch / 2.0 - backlash

    return {
        "module_mm": m,
        "teeth": z,
        "pressure_angle_deg": math.degrees(alpha),
        "pitch_diameter_mm": pitch_d,
        "base_diameter_mm": base_d,
        "outer_diameter_mm": outer_d,
        "root_diameter_mm": root_d,
        "circular_pitch_mm": circular_pitch,
        "tooth_thickness_pitch_mm": tooth_thickness_pitch,
    }
```

---

# 9. 齿轮参数校验

## 9.1 `geometry_primitives/gears/validator.py`

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)


def validate_involute_spur_gear_parameters(params: dict) -> None:
    module = float(params["module_mm"])
    teeth = int(params["teeth"])
    face_width = float(params["face_width_mm"])
    bore = float(params.get("bore_dia_mm", 0.0))

    if module <= 0:
        raise ValueError("module_mm must be > 0")
    if teeth < 6:
        raise ValueError("teeth must be >= 6")
    if face_width <= 0:
        raise ValueError("face_width_mm must be > 0")

    dims = spur_gear_reference_dimensions(params)

    if dims["root_diameter_mm"] <= 0:
        raise ValueError(
            f"Computed root_diameter_mm <= 0: {dims['root_diameter_mm']}"
        )

    if not (
        dims["root_diameter_mm"]
        < dims["pitch_diameter_mm"]
        < dims["outer_diameter_mm"]
    ):
        raise ValueError(
            "Require root_diameter_mm < pitch_diameter_mm < outer_diameter_mm"
        )

    if dims["base_diameter_mm"] > dims["outer_diameter_mm"]:
        raise ValueError("base_diameter_mm must be <= outer_diameter_mm")

    if bore > 0 and bore >= dims["root_diameter_mm"] * 0.85:
        raise ValueError(
            "bore_dia_mm too large relative to root_diameter_mm; "
            "risk of destroying tooth root"
        )

    backlash = float(params.get("backlash_mm", 0.0))
    if backlash >= dims["circular_pitch_mm"] * 0.25:
        raise ValueError("backlash_mm is too large relative to circular pitch")
```

---

# 10. CQ_Gears adapter

## 10.1 `geometry_primitives/gears/cq_gears_adapter.py`

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.gears.validator import (
    validate_involute_spur_gear_parameters,
)
from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)


def cq_gears_available() -> bool:
    try:
        import cq_gears  # noqa: F401
        return True
    except Exception:
        return False


def build_involute_spur_gear_cq_gears(params: dict):
    """
    Build engineering-grade involute spur gear using CQ_Gears.

    This is the preferred deterministic kernel for involute spur gears.
    Do not let LLM generate custom involute curves.
    """
    validate_involute_spur_gear_parameters(params)

    import cadquery as cq
    from cq_gears import SpurGear

    gear = SpurGear(
        module=float(params["module_mm"]),
        teeth_number=int(params["teeth"]),
        width=float(params["face_width_mm"]),
        bore_d=float(params.get("bore_dia_mm", 0.0)),
        pressure_angle=float(params.get("pressure_angle_deg", 20.0)),
    )

    wp = cq.Workplane("XY").gear(gear)

    metadata = {
        "primitive": "involute_spur_gear",
        "kernel": "cq_gears",
        "is_standard_involute": True,
        "parameters": params,
        "reference_dimensions": spur_gear_reference_dimensions(params),
    }

    return wp, metadata
```

---

# 11. CadQuery fallback：只能作为视觉 fallback

## 11.1 `geometry_primitives/gears/cadquery_fallback.py`

```python
from __future__ import annotations

import math

from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)
from seekflow_engineering_tools.geometry_primitives.gears.validator import (
    validate_involute_spur_gear_parameters,
)


def build_visual_spur_gear_fallback(params: dict):
    """
    Visual fallback only.

    This is not certified industrial involute geometry.
    It exists so tests and demos can still run without cq_gears.
    The result must carry warnings and metadata marking it as approximate.
    """
    validate_involute_spur_gear_parameters(params)

    import cadquery as cq

    dims = spur_gear_reference_dimensions(params)

    z = int(params["teeth"])
    width = float(params["face_width_mm"])
    bore = float(params.get("bore_dia_mm", 0.0))

    root_r = dims["root_diameter_mm"] / 2.0
    outer_r = dims["outer_diameter_mm"] / 2.0

    body = cq.Workplane("XY").circle(root_r).extrude(width)

    tooth_angle = 360.0 / z
    tooth_width_angle = tooth_angle * 0.45

    for i in range(z):
        a = math.radians(i * tooth_angle)
        da = math.radians(tooth_width_angle / 2.0)

        points = [
            (root_r * math.cos(a - da), root_r * math.sin(a - da)),
            (
                outer_r * math.cos(a - da * 0.55),
                outer_r * math.sin(a - da * 0.55),
            ),
            (
                outer_r * math.cos(a + da * 0.55),
                outer_r * math.sin(a + da * 0.55),
            ),
            (root_r * math.cos(a + da), root_r * math.sin(a + da)),
        ]

        tooth = cq.Workplane("XY").polyline(points).close().extrude(width)
        body = body.union(tooth)

    if bore > 0:
        body = body.faces(">Z").workplane().hole(bore)

    metadata = {
        "primitive": "involute_spur_gear",
        "kernel": "cadquery_visual_fallback",
        "is_standard_involute": False,
        "warnings": [
            "cq_gears is not available; generated approximate visual fallback gear.",
            "This fallback is not certified involute geometry.",
        ],
        "parameters": params,
        "reference_dimensions": dims,
    }

    return body, metadata
```

---

# 12. Primitive metadata sidecar

## 12.1 `geometry_primitives/gears/metadata.py`

```python
from __future__ import annotations

import json
from pathlib import Path


def write_primitive_metadata(
    step_path: Path,
    metadata: dict,
    validation: dict | None = None,
) -> Path:
    metadata_path = step_path.with_suffix(".metadata.json")

    payload = {
        **metadata,
        "step_file": str(step_path),
        "validation": validation or {},
    }

    metadata_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return metadata_path
```

每个 primitive 输出都必须带 metadata。

---

# 13. CadQuery primitive compiler

## 13.1 新增 `cadquery_backend/primitive_compiler.py`

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.registry import (
    normalize_primitive_parameters,
)


def compile_primitive_to_cadquery_script(feature) -> list[str]:
    primitive_name = feature.primitive_name
    params = normalize_primitive_parameters(
        primitive_name,
        feature.parameters,
    )

    if primitive_name == "involute_spur_gear":
        return [
            "from seekflow_engineering_tools.geometry_primitives.gears.cq_gears_adapter import (",
            "    cq_gears_available,",
            "    build_involute_spur_gear_cq_gears,",
            ")",
            "from seekflow_engineering_tools.geometry_primitives.gears.cadquery_fallback import (",
            "    build_visual_spur_gear_fallback,",
            ")",
            f"gear_params = {repr(params)}",
            "if cq_gears_available():",
            "    result, PRIMITIVE_METADATA = build_involute_spur_gear_cq_gears(gear_params)",
            "else:",
            "    result, PRIMITIVE_METADATA = build_visual_spur_gear_fallback(gear_params)",
            "    BUILD_WARNINGS.extend(PRIMITIVE_METADATA.get('warnings', []))",
        ]

    raise ValueError(f"Unsupported primitive for CadQuery: {primitive_name}")
```

## 13.2 修改 `cadquery_backend/compiler.py`

脚本头必须包含：

```python
lines = [
    "import json",
    "import cadquery as cq",
    "from cadquery import exporters",
    "BUILD_WARNINGS = []",
    "PRIMITIVE_METADATA = {}",
    "result = None",
]
```

feature loop 里加入：

```python
elif feature.type == "primitive":
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        compile_primitive_to_cadquery_script,
    )
    lines.extend(compile_primitive_to_cadquery_script(feature))
```

脚本尾部加入：

```python
lines.extend([
    f'exporters.export(result, r"{out_step}")',
    f'with open(r"{metadata_path}", "w", encoding="utf-8") as f:',
    "    json.dump({",
    "        'primitive_metadata': PRIMITIVE_METADATA,",
    "        'build_warnings': BUILD_WARNINGS,",
    "    }, f, indent=2, ensure_ascii=False)",
    "print('BUILD_WARNINGS=' + repr(BUILD_WARNINGS))",
])
```

`compile_cad_ir_to_cadquery_script` 函数必须接受：

```python
metadata_path: str | None = None
```

如果未传，则用：

```python
metadata_path = str(Path(out_step).with_suffix(".metadata.json"))
```

---

# 14. CadQuery builder 修改

## 14.1 `cadquery_backend/builder.py`

必须确保：

```text
1. 脚本写在 workspace 内。
2. STEP 写在 workspace 内。
3. metadata.json 写在 workspace 内。
4. stdout/stderr 进入 result。
5. validation report 写回 metadata。
6. fallback gear 不能静默成功，必须 warning。
```

核心伪代码：

```python
def build_cadquery_from_cad_ir(...):
    step_path = ensure_inside_workspace(config.workspace_root, out_step)
    ensure_extension(step_path, {".step", ".stp"})

    metadata_path = step_path.with_suffix(".metadata.json")
    metadata_path = ensure_inside_workspace(config.workspace_root, metadata_path)

    script_path = step_path.with_suffix(".cadquery_build.py")
    script_path = ensure_inside_workspace(config.workspace_root, script_path)
    ensure_extension(script_path, {".py"})

    script = compile_cad_ir_to_cadquery_script(
        spec=spec,
        out_step=str(step_path),
        metadata_path=str(metadata_path),
    )

    script_path.write_text(script, encoding="utf-8")

    proc = subprocess.run(...)

    assert_file_created(step_path, "STEP")
    assert_file_created(metadata_path, "metadata JSON")

    inspection = inspect_step_with_cadquery(step_path)
    validation = validate_inspection_against_spec(...)
    mechanical_validation = validate_mechanical_primitives(...)

    update_metadata_with_validation(metadata_path, validation, mechanical_validation)

    ok = validation.ok and mechanical_validation["ok"]

    return EngineeringActionResult(...)
```

---

# 15. Mechanical validation：齿轮专用验证

## 15.1 `mechanical_validation/gear_validation.py`

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)


def validate_involute_spur_gear_result(
    params: dict,
    inspection: dict,
    metadata: dict,
    tolerance_mm: float = 0.1,
) -> dict:
    dims = spur_gear_reference_dimensions(params)
    issues: list[dict] = []

    bbox = inspection.get("bbox_mm")
    if bbox is None:
        issues.append(
            {
                "code": "gear_bbox_missing",
                "severity": "error",
                "message": "Cannot validate gear without bbox_mm.",
            }
        )
    else:
        expected_outer = dims["outer_diameter_mm"]
        expected_width = float(params["face_width_mm"])

        if abs(bbox[0] - expected_outer) > tolerance_mm:
            issues.append(
                {
                    "code": "gear_outer_diameter_x_mismatch",
                    "severity": "error",
                    "expected": expected_outer,
                    "actual": bbox[0],
                }
            )

        if abs(bbox[1] - expected_outer) > tolerance_mm:
            issues.append(
                {
                    "code": "gear_outer_diameter_y_mismatch",
                    "severity": "error",
                    "expected": expected_outer,
                    "actual": bbox[1],
                }
            )

        if abs(bbox[2] - expected_width) > tolerance_mm:
            issues.append(
                {
                    "code": "gear_face_width_mismatch",
                    "severity": "error",
                    "expected": expected_width,
                    "actual": bbox[2],
                }
            )

    primitive_meta = metadata.get("primitive_metadata", metadata)
    kernel = primitive_meta.get("kernel")

    if kernel == "cadquery_visual_fallback":
        issues.append(
            {
                "code": "gear_visual_fallback_used",
                "severity": "warning",
                "message": "Generated approximate fallback gear; not certified involute.",
            }
        )

    if primitive_meta.get("primitive") != "involute_spur_gear":
        issues.append(
            {
                "code": "gear_metadata_missing",
                "severity": "error",
                "message": "Missing involute_spur_gear primitive metadata.",
            }
        )

    ref = primitive_meta.get("reference_dimensions") or {}
    if ref:
        for key in [
            "pitch_diameter_mm",
            "base_diameter_mm",
            "outer_diameter_mm",
            "root_diameter_mm",
        ]:
            if key not in ref:
                issues.append(
                    {
                        "code": f"gear_reference_{key}_missing",
                        "severity": "error",
                    }
                )

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "issues": issues,
        "reference_dimensions": dims,
        "kernel": kernel,
    }
```

## 15.2 `mechanical_validation/common.py`

```python
from __future__ import annotations

import json
from pathlib import Path


def load_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def validate_mechanical_primitives(spec, step_path: Path, inspection: dict) -> dict:
    results = []

    metadata_path = step_path.with_suffix(".metadata.json")
    metadata = load_metadata(metadata_path)

    for feature in spec.features:
        if feature.type == "primitive" and feature.primitive_name == "involute_spur_gear":
            from seekflow_engineering_tools.geometry_primitives.registry import (
                normalize_primitive_parameters,
            )
            from seekflow_engineering_tools.mechanical_validation.gear_validation import (
                validate_involute_spur_gear_result,
            )

            params = normalize_primitive_parameters(
                feature.primitive_name,
                feature.parameters,
            )

            result = validate_involute_spur_gear_result(
                params=params,
                inspection=inspection,
                metadata=metadata,
                tolerance_mm=getattr(spec.validation, "tolerance_mm", 0.1),
            )
            results.append(result)

    return {
        "ok": not any(not r["ok"] for r in results),
        "results": results,
    }
```

---

# 16. Legacy spur_gear 迁移策略

当前 `spur_gear` recipe 是 star-polygon visual gear。([GitHub][4])
必须保留兼容，但不能再作为工程级齿轮。

## 16.1 修改 `recipes/mechanical.py`

把旧 recipe 改为：

```python
RecipeDefinition(
    name="spur_gear_visual_legacy",
    category="legacy_visual",
    description=(
        "Legacy visual star-polygon gear. Not a standard involute gear. "
        "Use primitive involute_spur_gear for engineering-grade gears."
    ),
    ...
)
```

保留 `spur_gear` 作为 deprecated alias：

```python
RecipeDefinition(
    name="spur_gear",
    category="deprecated",
    description=(
        "Deprecated alias. Engineering-grade spur gears must be rewritten "
        "to primitive involute_spur_gear."
    ),
    ...
)
```

## 16.2 新增 normalizer

`natural_language/normalizer.py`：

```python
from __future__ import annotations

from seekflow_engineering_tools.ir.primitive import PrimitiveFeature


def rewrite_deprecated_recipes_to_primitives(spec):
    new_features = []

    for feature in spec.features:
        if feature.type == "recipe" and feature.recipe_name == "spur_gear":
            p = feature.parameters
            new_features.append(
                PrimitiveFeature(
                    id=feature.id,
                    type="primitive",
                    primitive_name="involute_spur_gear",
                    parameters={
                        "module_mm": p["module_mm"],
                        "teeth": p["teeth"],
                        "pressure_angle_deg": p.get("pressure_angle_deg", 20.0),
                        "face_width_mm": p["face_width_mm"],
                        "bore_dia_mm": p.get("bore_dia_mm", 0.0),
                    },
                    placement=getattr(feature, "placement", {}),
                    operation="new_body",
                )
            )
        else:
            new_features.append(feature)

    spec.features = new_features
    return spec
```

`engineering_validate_cad_ir` 必须调用：

```python
spec = rewrite_deprecated_recipes_to_primitives(spec)
```

并在 warnings 中加入：

```text
Recipe spur_gear was rewritten to primitive involute_spur_gear.
```

---

# 17. Capability Registry 修改

## 17.1 增加 primitive support

在 `capabilities/registry.py` 中加入：

```python
BACKEND_CAPABILITIES = {
    "cadquery": {
        "stable_recipes": [...],
        "stable_primitives": ["involute_spur_gear"],
        "primitive_strategy": {
            "involute_spur_gear": "native_cadquery_primitive",
        },
    },
    "solidworks2025": {
        "stable_recipes": ["box", "flanged_hub"],
        "stable_primitives": ["involute_spur_gear"],
        "primitive_strategy": {
            "involute_spur_gear": "cadquery_step_import",
        },
    },
    "nx12": {
        "stable_recipes": ["box", "block_with_hole", "l_bracket", "stepped_block"],
        "stable_primitives": ["involute_spur_gear"],
        "primitive_strategy": {
            "involute_spur_gear": "cadquery_step_import",
        },
    },
}
```

## 17.2 支持检查

```python
def backend_supports_feature(backend: str, feature) -> bool:
    caps = BACKEND_CAPABILITIES.get(backend, {})

    if feature.type == "recipe":
        return feature.recipe_name in caps.get("stable_recipes", [])

    if feature.type == "primitive":
        return feature.primitive_name in caps.get("stable_primitives", [])

    return backend == "cadquery"
```

`choose_backend` 必须基于 `backend_supports_feature`，不能只看 recipe。

---

# 18. SolidWorks / NX 策略

## 18.1 不在 SolidWorks/NX 生成齿轮

工程级齿轮必须：

```text
CAD-IR primitive
→ CadQuery + CQ_Gears
→ canonical STEP
→ SolidWorks/NX import
→ save native
```

不要再让 SolidWorks VBS 或 NXOpen 生成渐开线曲线。

## 18.2 SolidWorks 新增 import

新增：

```python
solidworks_import_step_as_part(step_path: str, out_sldprt: str) -> dict
```

内部：

```text
Open STEP
SaveAs SLDPRT
检查 SLDPRT 文件存在且非空
```

## 18.3 NX 新增 import job

新增 NX job action：

```text
import_step_as_prt
```

params：

```json
{
  "step_path": ".../gear.step",
  "out_prt": ".../gear.prt"
}
```

`engineering_build_cad_model` 如果 backend 是 `solidworks2025` 或 `nx12` 且 feature 是 primitive：

```text
1. 先调用 CadQuery primitive build 生成 STEP。
2. 再调用 SolidWorks/NX import 保存 native。
3. result.files_created 包含 STEP、metadata.json、native file。
4. warnings 中说明 native file was created by STEP import.
```

---

# 19. Natural Language 规则

## 19.1 用户输入到 primitive

如果用户出现以下词：

```text
gear
spur gear
involute gear
渐开线齿轮
直齿轮
模数
压力角
齿数
```

必须输出：

```json
{
  "type": "primitive",
  "primitive_name": "involute_spur_gear"
}
```

禁止输出：

```json
{
  "type": "recipe",
  "recipe_name": "spur_gear"
}
```

除非用户明确说：

```text
视觉近似齿轮
demo gear
star-like gear
```

才允许 `spur_gear_visual_legacy`。

## 19.2 示例 CAD-IR

```json
{
  "name": "precision_spur_gear_24t",
  "units": "mm",
  "target_backend": ["cadquery"],
  "features": [
    {
      "id": "gear",
      "type": "primitive",
      "primitive_name": "involute_spur_gear",
      "parameters": {
        "module_mm": 2.0,
        "teeth": 24,
        "pressure_angle_deg": 20.0,
        "face_width_mm": 12.0,
        "bore_dia_mm": 8.0,
        "addendum_coefficient": 1.0,
        "clearance_coefficient": 0.25,
        "profile_shift_coefficient": 0.0,
        "backlash_mm": 0.0
      }
    }
  ],
  "validation": {
    "expected_bbox_mm": [52.0, 52.0, 12.0],
    "expected_body_count": 1,
    "expected_tooth_count": 24,
    "expected_pitch_diameter_mm": 48.0,
    "expected_outer_diameter_mm": 52.0,
    "expected_face_width_mm": 12.0,
    "expected_bore_diameter_mm": 8.0,
    "tolerance_mm": 0.1
  }
}
```

---

# 20. `demo_full_chain.py` 最终验收脚本

`demo_full_chain.py` 必须成为 CI 可用验收脚本。

## 20.1 必须支持命令

```bash
python demo_full_chain.py --case box --backend cadquery
python demo_full_chain.py --case flanged_hub --backend cadquery
python demo_full_chain.py --case involute_spur_gear --backend cadquery
python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
```

## 20.2 报告格式

```json
{
  "overall_ok": true,
  "case": "involute_spur_gear",
  "backend": "cadquery",
  "stages": {
    "validate_cad_ir": {"ok": true},
    "normalize_primitives": {"ok": true},
    "choose_backend": {"ok": true},
    "build": {"ok": true},
    "inspect": {"ok": true},
    "mechanical_validate": {"ok": true}
  },
  "files_created": [
    "models/involute_spur_gear.step",
    "models/involute_spur_gear.metadata.json"
  ],
  "metrics": {
    "kernel_used": "cq_gears",
    "reference_dimensions": {
      "pitch_diameter_mm": 48.0,
      "base_diameter_mm": 45.105,
      "outer_diameter_mm": 52.0,
      "root_diameter_mm": 43.0
    }
  }
}
```

## 20.3 失败必须非零退出

```python
if not report["overall_ok"]:
    sys.exit(1)
```

---

# 21. `pyproject.toml` 修改

新增 optional dependencies：

```toml
[project.optional-dependencies]
cadquery = [
  "cadquery>=2.5",
]

gears = [
  "numpy>=1.24",
  "cq-gears @ git+https://github.com/meadiode/cq_gears.git@main",
]

build123d = [
  "build123d>=0.10",
]

industrial = [
  "cadquery>=2.5",
  "numpy>=1.24",
  "cq-gears @ git+https://github.com/meadiode/cq_gears.git@main",
]
```

CQ_Gears README 中推荐通过 `pip install git+https://github.com/meadiode/cq_gears.git@main` 安装，并说明依赖 numpy。([GitHub][2])

---

# 22. Tests：必须新增

新增：

```text
tests/test_geometry_primitives_registry.py
tests/test_involute_spur_gear_parameters.py
tests/test_involute_spur_gear_dimensions.py
tests/test_involute_spur_gear_cadquery_build.py
tests/test_gear_metadata_sidecar.py
tests/test_gear_validation.py
tests/test_demo_full_chain_gear.py
tests/test_no_legacy_gear_for_engineering.py
tests/test_primitive_feature_schema.py
tests/test_capability_registry_primitives.py
```

## 22.1 primitive registry 测试

```python
from seekflow_engineering_tools.geometry_primitives.registry import (
    list_primitive_names,
    get_primitive,
)


def test_involute_spur_gear_registered():
    assert "involute_spur_gear" in list_primitive_names()
    definition = get_primitive("involute_spur_gear")
    assert definition is not None
    assert "cadquery" in definition.supported_backends
```

## 22.2 参数校验测试

```python
import pytest

from seekflow_engineering_tools.geometry_primitives.registry import (
    normalize_primitive_parameters,
)


def test_involute_spur_gear_defaults():
    p = normalize_primitive_parameters(
        "involute_spur_gear",
        {
            "module_mm": 2,
            "teeth": 24,
            "face_width_mm": 12,
            "bore_dia_mm": 8,
        },
    )

    assert p["pressure_angle_deg"] == 20.0
    assert p["addendum_coefficient"] == 1.0
    assert p["clearance_coefficient"] == 0.25
    assert p["profile_shift_coefficient"] == 0.0


def test_involute_spur_gear_rejects_large_bore():
    with pytest.raises(ValueError):
        normalize_primitive_parameters(
            "involute_spur_gear",
            {
                "module_mm": 1.0,
                "teeth": 12,
                "face_width_mm": 5.0,
                "bore_dia_mm": 50.0,
            },
        )
```

## 22.3 尺寸公式测试

```python
from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)


def test_spur_gear_reference_dimensions():
    dims = spur_gear_reference_dimensions(
        {
            "module_mm": 2.0,
            "teeth": 24,
            "pressure_angle_deg": 20.0,
            "addendum_coefficient": 1.0,
            "clearance_coefficient": 0.25,
            "profile_shift_coefficient": 0.0,
            "backlash_mm": 0.0,
        }
    )

    assert abs(dims["pitch_diameter_mm"] - 48.0) < 1e-9
    assert abs(dims["outer_diameter_mm"] - 52.0) < 1e-9
    assert dims["root_diameter_mm"] < dims["pitch_diameter_mm"]
    assert dims["base_diameter_mm"] < dims["pitch_diameter_mm"]
```

## 22.4 CadQuery build 测试

```python
import pytest


def test_involute_spur_gear_builds_step(tmp_path):
    pytest.importorskip("cadquery")

    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.cadquery_backend.builder import (
        build_cadquery_from_cad_ir,
    )

    spec = CADPartSpec.model_validate(
        {
            "name": "gear_24t",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [
                {
                    "id": "gear",
                    "type": "primitive",
                    "primitive_name": "involute_spur_gear",
                    "parameters": {
                        "module_mm": 2,
                        "teeth": 24,
                        "pressure_angle_deg": 20,
                        "face_width_mm": 12,
                        "bore_dia_mm": 8,
                    },
                }
            ],
            "validation": {
                "expected_bbox_mm": [52, 52, 12],
                "expected_body_count": 1,
                "expected_outer_diameter_mm": 52,
                "expected_pitch_diameter_mm": 48,
                "expected_face_width_mm": 12,
                "tolerance_mm": 0.2,
            },
        }
    )

    result = build_cadquery_from_cad_ir(
        spec=spec,
        config=EngineeringToolsConfig(workspace_root=tmp_path),
        out_step="models/gear_24t.step",
        inspect=True,
    )

    assert result["ok"] is True, result
    assert (tmp_path / "models" / "gear_24t.step").exists()
    assert (tmp_path / "models" / "gear_24t.metadata.json").exists()
```

## 22.5 legacy gear 测试

```python
def test_spur_gear_recipe_rewritten_to_primitive():
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.natural_language.normalizer import (
        rewrite_deprecated_recipes_to_primitives,
    )

    spec = CADPartSpec.model_validate(
        {
            "name": "legacy_gear",
            "units": "mm",
            "features": [
                {
                    "id": "gear",
                    "type": "recipe",
                    "recipe_name": "spur_gear",
                    "parameters": {
                        "module_mm": 2,
                        "teeth": 24,
                        "face_width_mm": 12,
                        "bore_dia_mm": 8,
                    },
                }
            ],
        }
    )

    normalized = rewrite_deprecated_recipes_to_primitives(spec)
    assert normalized.features[0].type == "primitive"
    assert normalized.features[0].primitive_name == "involute_spur_gear"
```

---

# 23. `.claude/skills` 必须新增

新增：

```text
.claude/skills/industrial-text-to-cad/SKILL.md
.claude/skills/geometry-primitives/SKILL.md
.claude/skills/involute-gears/SKILL.md
.claude/skills/cadquery-cq-gears/SKILL.md
.claude/skills/solidworks-step-import/SKILL.md
.claude/skills/nx-step-import/SKILL.md
```

## 23.1 `industrial-text-to-cad/SKILL.md`

```markdown
---
name: industrial-text-to-cad
description: Use when implementing natural-language-to-CAD logic in this repository.
---

# Mandatory architecture

Never generate backend CAD API code directly from natural language.

Required chain:

Natural language
→ CAD-IR
→ recipe / primitive normalization
→ capability routing
→ deterministic geometry kernel
→ backend adapter
→ file verification
→ inspection
→ validation
→ EngineeringActionResult.

Complex mechanical objects must be primitives:
- involute_spur_gear
- iso_metric_thread
- shaft_with_keyway
- spline_shaft
- spring
- bearing_placeholder
- cam_profile

Never let LLM derive involute curves, thread helices, spring sweeps, or bearing geometry from scratch.
```

## 23.2 `involute-gears/SKILL.md`

```markdown
---
name: involute-gears
description: Use when implementing gear generation or gear validation.
---

# Mandatory rules

Do not use star-polygon gears for engineering work.

Use primitive:
- involute_spur_gear

Required parameters:
- module_mm
- teeth
- pressure_angle_deg default 20
- face_width_mm
- bore_dia_mm
- addendum_coefficient default 1.0
- clearance_coefficient default 0.25
- profile_shift_coefficient default 0.0
- backlash_mm default 0.0

Preferred kernel:
1. CQ_Gears adapter
2. CadQuery visual fallback only with warning

Validation must check:
- pitch diameter
- base diameter
- outer diameter
- root diameter
- face width
- metadata sidecar
- kernel used
```

## 23.3 `cadquery-cq-gears/SKILL.md`

```markdown
---
name: cadquery-cq-gears
description: Use when implementing CadQuery and CQ_Gears based geometry kernels.
---

# Mandatory rules

CadQuery is the canonical OpenCascade-based geometry backend.

CQ_Gears is the preferred deterministic gear kernel.

Never expose CQ_Gears raw calls to LLM. Always call through:
seekflow_engineering_tools.geometry_primitives.gears.cq_gears_adapter

If CQ_Gears is unavailable, visual fallback is allowed only when:
- metadata says kernel = cadquery_visual_fallback
- warnings say not certified involute geometry
- validation report includes fallback warning
```

---

# 24. 最终验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools
pytest
```

必须运行：

```bash
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json
```

必须生成：

```text
models/involute_spur_gear.step
models/involute_spur_gear.metadata.json
reports/gear.json
```

`reports/gear.json` 必须包含：

```json
{
  "overall_ok": true,
  "metrics": {
    "kernel_used": "cq_gears",
    "reference_dimensions": {
      "pitch_diameter_mm": 48.0,
      "outer_diameter_mm": 52.0
    }
  }
}
```

如果 CQ_Gears 未安装，允许 fallback，但必须：

```json
{
  "kernel_used": "cadquery_visual_fallback",
  "warnings": [
    "not certified involute geometry"
  ]
}
```

且工业级测试可以用 marker 区分：

```bash
pytest -m "not requires_cq_gears"
pytest -m requires_cq_gears
```

---

# 25. Claude Code 强制执行提示

下面这段建议原样交给 Claude Code：

```markdown
请把 integrations/engineering_tools 升级为工业级 Text-to-CAD 系统。最终内核策略是：

- OpenCascade BREP 为底层几何内核；
- CadQuery 为当前主建模入口；
- CQ_Gears 为齿轮专用 deterministic primitive kernel；
- SolidWorks/NX 不生成复杂齿形，只导入 canonical STEP 并保存 native；
- build123d 作为未来第二前端，不作为本轮主线。

必须实现：

1. 新增 geometry_primitives 包：
   - base.py
   - registry.py
   - graph.py
   - gears/models.py
   - gears/standards.py
   - gears/validator.py
   - gears/cq_gears_adapter.py
   - gears/cadquery_fallback.py
   - gears/metadata.py

2. 新增 ir/primitive.py，并把 PrimitiveFeature 加入 CADPartSpec feature union。

3. 新增 primitive involute_spur_gear，参数包括：
   - module_mm
   - teeth
   - pressure_angle_deg default 20
   - face_width_mm
   - bore_dia_mm default 0
   - addendum_coefficient default 1.0
   - clearance_coefficient default 0.25
   - profile_shift_coefficient default 0.0
   - backlash_mm default 0.0
   - root_fillet_radius_mm default 0.0
   - quality_grade default industrial_brep

4. CQ_Gears adapter：
   - 优先使用 cq_gears.SpurGear。
   - 通过 cq.Workplane("XY").gear(spur_gear) 生成实体。
   - 不允许 LLM 生成 involute 曲线。
   - 若 CQ_Gears 不可用，使用 cadquery_visual_fallback，但必须写 warning 和 metadata。

5. 修改 cadquery_backend/compiler.py：
   - 支持 feature.type == "primitive"。
   - primitive involute_spur_gear 必须调用 deterministic adapter。
   - 输出 STEP 和 metadata.json。

6. 修改 cadquery_backend/builder.py：
   - 读取 metadata.json。
   - 运行 inspection。
   - 运行 mechanical_validation。
   - validation 结果写回 metadata。
   - files_created 包含 step 和 metadata。
   - fallback gear 不得静默成功，warnings 必须暴露。

7. 修改 recipes/mechanical.py：
   - 当前 spur_gear 改为 legacy visual 或 deprecated alias。
   - 工程级齿轮必须使用 primitive involute_spur_gear。

8. 修改 natural_language/normalizer.py：
   - 所有 spur_gear recipe 自动 rewrite 成 primitive involute_spur_gear。
   - 自然语言中出现齿轮、渐开线、模数、压力角时必须输出 primitive。

9. 修改 capability registry：
   - 增加 stable_primitives。
   - cadquery 支持 involute_spur_gear native primitive。
   - solidworks2025/nx12 支持 involute_spur_gear 的策略是 cadquery_step_import。

10. 新增 mechanical_validation：
    - gear_validation.py
    - common.py
    检查 pitch/base/outer/root diameter、face width、metadata、kernel used。

11. 修改 demo_full_chain.py：
    - 支持 --case involute_spur_gear
    - 支持 --backend cadquery
    - 支持 --json-report
    - 失败时退出码非 0
    - 报告必须包含 kernel_used 和 reference_dimensions。

12. 修改 pyproject.toml：
    - optional dependency gears
    - optional dependency industrial
    - 使用 cq-gears @ git+https://github.com/meadiode/cq_gears.git@main

13. 新增 tests：
    - test_geometry_primitives_registry.py
    - test_involute_spur_gear_parameters.py
    - test_involute_spur_gear_dimensions.py
    - test_involute_spur_gear_cadquery_build.py
    - test_gear_metadata_sidecar.py
    - test_gear_validation.py
    - test_demo_full_chain_gear.py
    - test_no_legacy_gear_for_engineering.py
    - test_primitive_feature_schema.py
    - test_capability_registry_primitives.py

14. 新增 .claude/skills：
    - industrial-text-to-cad
    - geometry-primitives
    - involute-gears
    - cadquery-cq-gears
    - solidworks-step-import
    - nx-step-import

验收：

cd integrations/engineering_tools
pytest

python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json

必须生成：
- models/involute_spur_gear.step
- models/involute_spur_gear.metadata.json
- reports/gear.json

禁止：
- 用 star-polygon spur_gear 作为工程级齿轮。
- 让 LLM 生成 involute 曲线数学。
- fallback 时不写 warning。
- 只有 bbox/body_count 就认为齿轮正确。
- SolidWorks/NX 重新写一套齿轮几何。
```

---

# 26. 最终判断

最终系统应明确分层：

```text
LLM：语义理解与参数抽取
CAD-IR：设计意图表达
Primitive Registry：标准机械对象声明
Mechanical Geometry Primitive Kernel：确定性几何生成
CadQuery / CQ_Gears：OpenCascade BREP 实现入口
SolidWorks / NX：STEP 导入与 native 保存
Validation：几何、机械标准、metadata、traceability
```

齿轮问题不是“大模型不够强”，而是“系统不该让大模型现场生成齿形”。
最终要用：

```text
involute_spur_gear primitive
→ CQ_Gears
→ CadQuery / OpenCascade
→ STEP
→ metadata
→ validation
→ optional SolidWorks/NX import
```

这样才能保证同一组参数生成同一套标准几何，并让 Text-to-CAD 从“能画出来”升级为“可验证、可复现、可导入工业 CAD 流程”。

[1]: https://cadquery.readthedocs.io/?utm_source=chatgpt.com "CadQuery Documentation — CadQuery Documentation"
[2]: https://github.com/meadiode/cq_gears "GitHub - meadiode/cq_gears: CadQuery based involute gear parametric modelling · GitHub"
[3]: https://build123d.readthedocs.io/?utm_source=chatgpt.com "About — build123d 0.10.1.dev402+g41c58ed4f documentation"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/recipes/mechanical.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
