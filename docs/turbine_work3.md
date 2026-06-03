# SeekFlow Engineering：`axisymmetric_turbine_disk` 涡轮盘 Primitive v0.3 深度修复与落地实施文档

## 0. 任务总目标

当前仓库已经实现了 `axisymmetric_turbine_disk` 的 v0.2 版本，能够生成带 hub sleeve、annular details、coverplate holes、rim slots 的涡轮盘参考几何。但用户最新 SolidWorks 截图显示，外缘“涡轮叶片卡槽”仍然有明显问题：

```text
1. 外缘 slot 主要表现为外圆柱侧壁上的竖向槽；
2. slot 没有真正贯穿 rim 的前后端面；
3. 从俯视图看，外缘顶面仍然像连续圆环；
4. slot 没有形成真实涡轮盘外缘的 blade-root slot / disk post 效果；
5. 视觉上仍然偏“厚法兰盘 + 外圆刻槽”，不是“涡轮转子盘参考件”。
```

本轮目标是把当前 primitive 升级为：

```text
primitive_name = "axisymmetric_turbine_disk"
kernel = "cadquery_turbine_disk_reference_v3"
geometry_family = "axisymmetric_base_with_axial_through_rim_slots"
```

核心修复：

```text
将当前侧壁槽 side-groove 逻辑升级为 axial-through rim slot 逻辑。

也就是说，外缘 blade-root slot cutter 必须：
1. 沿 Z 方向贯穿 rim 的前端面和后端面；
2. 径向外侧必须超出 outer_radius，使 slot 在外圆开口；
3. 径向内侧切入 rim，但不能切穿 web；
4. 在俯视/轴向视图中打断外缘圆环；
5. slot 与 slot 之间保留下来的实体形成 disk posts；
6. metadata、validator、mechanical validation、demo、tests 都必须显式验证这一点。
```

本轮不是做真实航空发动机可制造涡轮盘，而是做：

```text
non-flight reference geometry only
not airworthy
not certified
not manufacturing-ready
not installable
```

---

## 1. 当前代码问题诊断

### 1.1 当前几何 kernel 的根本问题

当前 `axisymmetric_turbine_disk.py` 的 v0.2 kernel 里，rim slot cutter 大致是：

```python
axial = rim_width_mm - 2.0 * rim_slot_axial_margin_mm
cutter = box(depth, width, axial)
```

然后绕 Z 阵列：

```python
for i in range(count):
    rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
    result = result.cut(rotated)
```

这个逻辑会造成：

```text
1. 如果 axial 小于 rim_width，slot 前后端面都会留边；
2. 从俯视图看，rim front face 仍然是连续圆环；
3. 从背面看，rim back face 也可能是连续圆环；
4. 侧视图能看到竖槽，但这只是 side groove；
5. 这不是 blade-root slot 的视觉语义。
```

因此，本轮必须明确区分两类 slot：

```text
side_groove:
  只在外圆柱侧壁上刻槽；
  不贯穿前后端面；
  视觉上类似散热槽/滚花槽；
  不是本轮默认目标。

axial_through:
  沿 Z 方向贯穿 rim 前后端面；
  外径方向超出 outer_radius；
  径向内侧切入 rim；
  从俯视图看能打断外缘圆环；
  slot 之间形成 disk posts；
  这是本轮默认目标。
```

### 1.2 当前代码同步问题

当前 v0.2 代码存在“部分模块升级、部分模块没跟上”的风险：

```text
1. axisymmetric_turbine_disk.py 中 KERNEL_NAME 是 v2；
2. rim slot cutter 没有 orientation 概念；
3. metadata 没有 slot_generation.z_min/z_max 与 opens_front_face/back_face 的强校验；
4. mechanical validation 允许 v0/v2，但没有 v3 axial-through slot 语义；
5. demo 生成模型虽然有 slot，但测试可能只验证 slot_count，不验证 slot 是否贯穿；
6. SolidWorks 截图已经证明：只验证 slot_count 不足以保证几何正确。
```

本轮必须把以下层级全部同步：

```text
models.py
validator.py
axisymmetric_turbine_disk.py
metadata.py
turbomachinery_validation.py
primitive_compiler.py
demo_full_chain.py
tests
```

---

## 2. 不可违背的安全与架构约束

Claude Code 必须遵守以下硬约束：

```text
1. 不允许声称模型 flight-ready。
2. 不允许声称模型 airworthy。
3. 不允许声称模型 certified。
4. 不允许声称模型 manufacturing-ready。
5. 不允许声称模型 installable。
6. 不允许做真实航空发动机涡轮盘强度设计。
7. 不允许做真实 fir-tree 承载槽设计。
8. 不允许做真实叶片连接接触应力分析。
9. 不允许做离心载荷、疲劳寿命、爆盘裕度、热应力、材料适配判断。
10. 不允许生成制造图纸或加工参数。
11. 不允许让 LLM 直接生成任意 CAD 脚本。
12. primitive compiler 只能调用 deterministic kernel。
13. SolidWorks / NX 只能 import canonical STEP，不能重建 native feature tree。
14. 所有失败路径必须 fail-closed。
15. 不得破坏 `involute_spur_gear`。
16. 不得破坏已有 recipe cases。
17. 不得改变 primitive_name，仍为 `axisymmetric_turbine_disk`。
```

所有 metadata / warnings / skill contract 中都必须保留：

```text
non-flight reference geometry only
not airworthy
not certified
not manufacturing-ready
not for installation
rim slots are visual/reference geometry only
not certified blade attachment geometry
```

---

## 3. 本轮版本定义

保持：

```python
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
```

升级：

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v3"
GEOMETRY_FAMILY = "axisymmetric_base_with_axial_through_rim_slots"
```

metadata 中必须写：

```json
{
  "kernel": "cadquery_turbine_disk_reference_v3",
  "geometry_family": "axisymmetric_base_with_axial_through_rim_slots",
  "slot_generation": {
    "version": "rim_slot_v3",
    "orientation": "axial_through",
    "opens_front_face": true,
    "opens_back_face": true,
    "opens_outer_diameter": true
  }
}
```

---

## 4. 文件修改清单

必须修改：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
integrations/engineering_tools/demo_full_chain.py
```

必须新增或更新测试：

```text
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_parameters.py
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_compiler.py
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_metadata.py
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_mechanical_validation.py
integrations/engineering_tools/tests/test_turbine_disk_visual_features.py
integrations/engineering_tools/tests/test_demo_full_chain_turbine_disk.py
```

---

# 5. Phase 1：修正 Primitive 参数 schema

## 5.1 修改文件

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
```

## 5.2 必须新增/确认参数

当前 v0.2 已经加入一批参数，但 v0.3 必须确保以下参数全部在 `PrimitiveDefinition.parameters` 中注册，否则 CAD-IR normalize 会拒绝 demo 参数。

### 5.2.1 Rim slot 参数

必须包含：

```text
rim_slot_count
rim_slot_style
rim_slot_orientation
rim_slot_depth_mm
rim_slot_width_mm
rim_slot_neck_width_mm
rim_slot_lobe_width_mm
rim_slot_lobe_depth_mm
rim_slot_axial_margin_mm
rim_slot_through_clearance_mm
rim_slot_outer_clearance_mm
rim_slot_root_fillet_mm
rim_slot_tip_chamfer_mm
```

推荐定义：

```python
PrimitiveParameter(
    name="rim_slot_count",
    type="int",
    required=False,
    default=60,
    min_value=0,
),
PrimitiveParameter(
    name="rim_slot_style",
    type="str",
    required=False,
    default="fir_tree_like",
),
PrimitiveParameter(
    name="rim_slot_orientation",
    type="str",
    required=False,
    default="axial_through",
),
PrimitiveParameter(
    name="rim_slot_depth_mm",
    type="float",
    unit="mm",
    required=False,
    default=38.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_width_mm",
    type="float",
    unit="mm",
    required=False,
    default=7.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_neck_width_mm",
    type="float",
    unit="mm",
    required=False,
    default=4.5,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_lobe_width_mm",
    type="float",
    unit="mm",
    required=False,
    default=8.5,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_lobe_depth_mm",
    type="float",
    unit="mm",
    required=False,
    default=7.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_axial_margin_mm",
    type="float",
    unit="mm",
    required=False,
    default=0.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_through_clearance_mm",
    type="float",
    unit="mm",
    required=False,
    default=2.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_outer_clearance_mm",
    type="float",
    unit="mm",
    required=False,
    default=4.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_root_fillet_mm",
    type="float",
    unit="mm",
    required=False,
    default=0.0,
    min_value=0.0,
),
PrimitiveParameter(
    name="rim_slot_tip_chamfer_mm",
    type="float",
    unit="mm",
    required=False,
    default=0.0,
    min_value=0.0,
),
```

### 5.2.2 Hub sleeve 参数

必须包含：

```text
front_hub_sleeve_outer_dia_mm
front_hub_sleeve_inner_dia_mm
front_hub_sleeve_height_mm
front_hub_sleeve_wall_mm
front_hub_sleeve_chamfer_mm

rear_hub_sleeve_outer_dia_mm
rear_hub_sleeve_inner_dia_mm
rear_hub_sleeve_height_mm
rear_hub_sleeve_chamfer_mm
```

注意：当前代码中 `_add_rear_hub_sleeve()` 读取 `rear_hub_sleeve_chamfer_mm`，所以 `models.py` 必须注册它。若暂时不需要 rear chamfer，也必须给默认值 0.0，避免 unknown/missing 参数不一致。

### 5.2.3 Annular details 参数

必须包含：

```text
enable_annular_details

inner_hub_step_outer_dia_mm
inner_hub_step_height_mm

mid_web_recess_inner_dia_mm
mid_web_recess_outer_dia_mm
mid_web_recess_depth_mm

outer_rim_recess_inner_dia_mm
outer_rim_recess_outer_dia_mm
outer_rim_recess_depth_mm

seal_land_count
seal_land_height_mm
seal_land_width_mm
seal_land_start_dia_mm
seal_land_pitch_mm
```

### 5.2.4 Coverplate / balance 参数

必须包含：

```text
coverplate_bolt_count
coverplate_bolt_pcd_mm
coverplate_bolt_dia_mm
coverplate_bolt_axis

balance_hole_count
balance_hole_pcd_mm
balance_hole_dia_mm
balance_hole_axis
```

当前 kernel 读取 `coverplate_bolt_axis` 与 `balance_hole_axis`，因此 schema 必须注册它们。

## 5.3 supported_kernels

更新为：

```python
supported_kernels=[
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
    "cadquery_turbine_disk_reference_v3",
]
```

或者只保留 v3：

```python
supported_kernels=[
    "cadquery_turbine_disk_reference_v3",
]
```

为了不破坏旧测试，推荐暂时保留三者，但 demo 和新测试必须期望 v3。

---

# 6. Phase 2：升级参数 validator

## 6.1 修改文件

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
```

## 6.2 新增允许值

```python
ALLOWED_RIM_SLOT_STYLES = {
    "none",
    "rectangular",
    "dovetail",
    "fir_tree_like",
}

ALLOWED_RIM_SLOT_ORIENTATIONS = {
    "axial_through",
    "side_groove",
}
```

## 6.3 升级 `_validate_rim_slots`

必须实现以下逻辑：

```python
def _validate_rim_slots(errors: list[str], params: dict) -> None:
    style = str(params.get("rim_slot_style", "none"))
    orientation = str(params.get("rim_slot_orientation", "axial_through"))
    count = int(params.get("rim_slot_count", 0))

    if style not in ALLOWED_RIM_SLOT_STYLES:
        errors.append(
            f"rim_slot_style must be one of {sorted(ALLOWED_RIM_SLOT_STYLES)}, got {style!r}"
        )
        return

    if orientation not in ALLOWED_RIM_SLOT_ORIENTATIONS:
        errors.append(
            f"rim_slot_orientation must be one of {sorted(ALLOWED_RIM_SLOT_ORIENTATIONS)}, got {orientation!r}"
        )
        return

    if style == "none":
        if count != 0:
            errors.append("rim_slot_count must be 0 when rim_slot_style='none'")
        return

    if count < 12:
        errors.append("rim_slot_count must be >= 12 when rim slots are enabled")

    outer_d = float(params["outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])
    rim_width = float(params["rim_width_mm"])

    r_outer = outer_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    rim_radial = r_outer - r_rim_inner

    depth = float(params.get("rim_slot_depth_mm", 0.0))
    width = float(params.get("rim_slot_width_mm", 0.0))
    axial_margin = float(params.get("rim_slot_axial_margin_mm", 0.0))
    through_clearance = float(params.get("rim_slot_through_clearance_mm", 0.0))
    outer_clearance = float(params.get("rim_slot_outer_clearance_mm", 0.0))

    if depth <= 0:
        errors.append("rim_slot_depth_mm must be > 0 when rim slots are enabled")

    if width <= 0:
        errors.append("rim_slot_width_mm must be > 0 when rim slots are enabled")

    if rim_radial <= 0:
        errors.append("rim radial thickness must be > 0")
        return

    if depth >= rim_radial * 0.85:
        errors.append(
            "rim_slot_depth_mm is too large; it would cut into the web instead of staying in the rim"
        )

    pitch = 2.0 * math.pi * r_outer / max(count, 1)
    if pitch <= width * 1.25:
        errors.append(
            "rim_slot_width_mm is too large for rim_slot_count; rim slots would overlap"
        )

    if through_clearance < 0:
        errors.append("rim_slot_through_clearance_mm must be >= 0")

    if outer_clearance < 0:
        errors.append("rim_slot_outer_clearance_mm must be >= 0")

    if orientation == "axial_through":
        if axial_margin != 0:
            errors.append(
                "rim_slot_axial_margin_mm must be 0 for axial_through rim slots; "
                "otherwise slots will not open through front/back rim faces"
            )

        slot_cut_height = rim_width + 2.0 * through_clearance
        if slot_cut_height <= rim_width:
            errors.append(
                "axial_through rim slots must cut beyond both rim faces; "
                "increase rim_slot_through_clearance_mm"
            )

    if orientation == "side_groove":
        slot_axial = rim_width - 2.0 * axial_margin
        if slot_axial <= 0:
            errors.append(
                "rim_slot_axial_margin_mm leaves no axial thickness for side_groove slots"
            )

    if style == "fir_tree_like":
        neck_w = float(params.get("rim_slot_neck_width_mm", 0.0))
        lobe_w = float(params.get("rim_slot_lobe_width_mm", 0.0))
        lobe_depth = float(params.get("rim_slot_lobe_depth_mm", 0.0))

        if neck_w <= 0:
            errors.append("rim_slot_neck_width_mm must be > 0 for fir_tree_like slots")
        if lobe_w <= 0:
            errors.append("rim_slot_lobe_width_mm must be > 0 for fir_tree_like slots")
        if lobe_depth <= 0:
            errors.append("rim_slot_lobe_depth_mm must be > 0 for fir_tree_like slots")

        if neck_w >= lobe_w:
            errors.append(
                "rim_slot_neck_width_mm must be smaller than rim_slot_lobe_width_mm "
                "for fir_tree_like visual geometry"
            )
```

## 6.4 关键 validator 设计原则

本轮最重要的 validator 约束是：

```text
当 rim_slot_orientation == "axial_through" 时：
rim_slot_axial_margin_mm 必须等于 0。
```

原因：

```text
只要保留 axial margin，slot cutter 就会在 rim 前后端面留下未切透的材料，
SolidWorks 俯视图就会继续看到连续外缘圆环。
```

---

# 7. Phase 3：重写 v3 几何 kernel

## 7.1 修改文件

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
```

## 7.2 顶部常量

改为：

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v3"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
GEOMETRY_FAMILY = "axisymmetric_base_with_axial_through_rim_slots"
```

## 7.3 文件结构要求

必须将文件拆成清晰函数，不要继续压缩成难维护的一行格式。

推荐结构：

```python
from __future__ import annotations

from typing import Any

KERNEL_NAME = "cadquery_turbine_disk_reference_v3"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
GEOMETRY_FAMILY = "axisymmetric_base_with_axial_through_rim_slots"


def _get_float(params: dict, key: str, default: float = 0.0) -> float:
    return float(params.get(key, default))


def _get_int(params: dict, key: str, default: int = 0) -> int:
    return int(params.get(key, default))


def _get_str(params: dict, key: str, default: str = "") -> str:
    return str(params.get(key, default))


def _get_bool(params: dict, key: str, default: bool = False) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _build_base_body(cq, params: dict):
    ...


def _add_front_hub_sleeve(cq, result, params: dict, axial_zones: dict):
    ...


def _add_rear_hub_sleeve(cq, result, params: dict, axial_zones: dict):
    ...


def _add_annular_details(cq, result, params: dict, axial_zones: dict):
    ...


def _cut_hole_ring(result, *, count: int, pcd_mm: float, hole_dia_mm: float, axis: str):
    ...


def _cut_legacy_hole_rings(result, params: dict):
    ...


def _cut_coverplate_bolt_ring(result, params: dict):
    ...


def _cut_balance_hole_ring(result, params: dict):
    ...


def _rectangular_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    ...


def _dovetail_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    ...


def _fir_tree_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    ...


def _make_axial_through_slot_cutter(cq, params: dict, *, rim_z_min: float, rim_z_max: float):
    ...


def _make_side_groove_slot_cutter(cq, params: dict, *, rim_z_min: float, rim_z_max: float):
    ...


def _cut_rim_slots(cq, result, params: dict, axial_zones: dict):
    ...


def _expected_bbox_mm(params: dict) -> list[float]:
    ...


def _reference_dimensions(params: dict, slot_metadata: dict) -> dict[str, Any]:
    ...


def _build_metadata(params: dict, profile_points: list[tuple[float, float]], axial_zones: dict, slot_metadata: dict) -> dict[str, Any]:
    ...


def build_axisymmetric_turbine_disk_cadquery(params: dict):
    import cadquery as cq

    result, profile_points, axial_zones = _build_base_body(cq, params)
    result = _add_front_hub_sleeve(cq, result, params, axial_zones)
    result = _add_rear_hub_sleeve(cq, result, params, axial_zones)
    result = _add_annular_details(cq, result, params, axial_zones)
    result = _cut_legacy_hole_rings(result, params)
    result = _cut_coverplate_bolt_ring(result, params)
    result = _cut_balance_hole_ring(result, params)
    result, slot_metadata = _cut_rim_slots(cq, result, params, axial_zones)

    metadata = _build_metadata(params, profile_points, axial_zones, slot_metadata)
    return result, metadata
```

---

# 8. Phase 4：base body 必须返回 rim Z 范围

当前 `_build_base_body()` 只返回 `result, profile_points`。v3 必须返回 `axial_zones`，因为 slot cutter 需要知道 rim 实际前后边界。

实现：

```python
def _build_base_body(cq, params: dict):
    outer_d = _get_float(params, "outer_dia_mm")
    bore_d = _get_float(params, "bore_dia_mm")
    hub_d = _get_float(params, "hub_outer_dia_mm")
    web_d = _get_float(params, "web_outer_dia_mm")
    rim_inner_d = _get_float(params, "rim_inner_dia_mm")

    hub_w = _get_float(params, "hub_width_mm")
    web_w = _get_float(params, "web_width_mm")
    rim_w = _get_float(params, "rim_width_mm")

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    t_hub = hub_w / 2.0
    t_web = web_w / 2.0
    t_rim = rim_w / 2.0

    profile_points = [
        (r_bore, -t_hub),
        (r_hub, -t_hub),
        (r_hub, -t_web),
        (r_web, -t_web),
        (r_rim_inner, -t_rim),
        (r_outer, -t_rim),
        (r_outer, t_rim),
        (r_rim_inner, t_rim),
        (r_web, t_web),
        (r_hub, t_web),
        (r_hub, t_hub),
        (r_bore, t_hub),
    ]

    result = (
        cq.Workplane("XZ")
        .polyline(profile_points)
        .close()
        .revolve()
    )

    axial_zones = {
        "hub_z_min_mm": -t_hub,
        "hub_z_max_mm": t_hub,
        "web_z_min_mm": -t_web,
        "web_z_max_mm": t_web,
        "rim_z_min_mm": -t_rim,
        "rim_z_max_mm": t_rim,
        "base_z_min_mm": -max(t_hub, t_web, t_rim),
        "base_z_max_mm": max(t_hub, t_web, t_rim),
    }

    return result, profile_points, axial_zones
```

后续所有 rim slot cutter 必须使用：

```python
rim_z_min = axial_zones["rim_z_min_mm"]
rim_z_max = axial_zones["rim_z_max_mm"]
```

不要再猜测。

---

# 9. Phase 5：正确实现 axial-through rim slot cutter

## 9.1 本轮最核心修复

不要再用：

```python
axial = rim_width_mm - 2.0 * rim_slot_axial_margin_mm
```

作为默认 slot cutter 高度。

对于 `axial_through`，必须使用：

```python
z_min = rim_z_min - rim_slot_through_clearance_mm
z_max = rim_z_max + rim_slot_through_clearance_mm
height = z_max - z_min
```

并且 cutter 的 XY profile 必须：

```text
1. 最大 x > outer_radius；
2. 最小 x = outer_radius - rim_slot_depth_mm；
3. y 方向体现 slot 宽度；
4. fir_tree_like 需要 mouth / neck / lobe / root pocket 多段变化；
5. 然后沿 Z extrude height；
6. 再 translate 到 z_min；
7. 再 rotate 阵列切削。
```

## 9.2 Rectangular slot profile

```python
def _rectangular_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    width = _get_float(params, "rim_slot_width_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    x_outer = r_outer + outer_clearance
    x_inner = r_outer - depth

    return [
        (x_outer, -width / 2.0),
        (x_inner, -width / 2.0),
        (x_inner, width / 2.0),
        (x_outer, width / 2.0),
    ]
```

## 9.3 Dovetail slot profile

```python
def _dovetail_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    mouth_w = _get_float(params, "rim_slot_width_mm")
    lobe_w = _get_float(params, "rim_slot_lobe_width_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    x_outer = r_outer + outer_clearance
    x_mid = r_outer - depth * 0.40
    x_inner = r_outer - depth

    return [
        (x_outer, -mouth_w / 2.0),
        (x_mid, -mouth_w / 2.0),
        (x_inner, -lobe_w / 2.0),
        (x_inner, lobe_w / 2.0),
        (x_mid, mouth_w / 2.0),
        (x_outer, mouth_w / 2.0),
    ]
```

## 9.4 Fir-tree-like slot profile

这是视觉真实感关键。不能只用多个 box 粗糙 union，建议用 XY polygon。

```python
def _fir_tree_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    mouth_w = _get_float(params, "rim_slot_width_mm")
    neck_w = _get_float(params, "rim_slot_neck_width_mm")
    lobe_w = _get_float(params, "rim_slot_lobe_width_mm")

    x0 = r_outer + outer_clearance
    x1 = r_outer - depth * 0.16
    x2 = r_outer - depth * 0.32
    x3 = r_outer - depth * 0.48
    x4 = r_outer - depth * 0.64
    x5 = r_outer - depth * 0.82
    x6 = r_outer - depth

    root_w = neck_w * 1.15
    inner_lobe_w = lobe_w * 0.85

    return [
        (x0, -mouth_w / 2.0),
        (x1, -mouth_w / 2.0),
        (x2, -neck_w / 2.0),
        (x3, -lobe_w / 2.0),
        (x4, -neck_w / 2.0),
        (x5, -inner_lobe_w / 2.0),
        (x6, -root_w / 2.0),
        (x6, root_w / 2.0),
        (x5, inner_lobe_w / 2.0),
        (x4, neck_w / 2.0),
        (x3, lobe_w / 2.0),
        (x2, neck_w / 2.0),
        (x1, mouth_w / 2.0),
        (x0, mouth_w / 2.0),
    ]
```

注意：这只是 visual/reference fir-tree-like profile，不是可制造/可承载真实 fir-tree。

## 9.5 Axial-through cutter

```python
def _make_axial_through_slot_cutter(
    cq,
    params: dict,
    *,
    rim_z_min: float,
    rim_z_max: float,
):
    style = _get_str(params, "rim_slot_style", "none")
    through_clearance = _get_float(params, "rim_slot_through_clearance_mm", 2.0)

    z_min = rim_z_min - through_clearance
    z_max = rim_z_max + through_clearance
    height = z_max - z_min

    if style == "rectangular":
        profile = _rectangular_slot_profile_xy(params)
    elif style == "dovetail":
        profile = _dovetail_slot_profile_xy(params)
    elif style == "fir_tree_like":
        profile = _fir_tree_slot_profile_xy(params)
    else:
        raise ValueError(f"Unsupported axial-through rim_slot_style: {style!r}")

    cutter = (
        cq.Workplane("XY")
        .polyline(profile)
        .close()
        .extrude(height)
        .translate((0.0, 0.0, z_min))
    )

    cutter_metadata = {
        "profile_points_xy": [[float(x), float(y)] for x, y in profile],
        "z_min_mm": float(z_min),
        "z_max_mm": float(z_max),
        "height_mm": float(height),
        "max_x_mm": float(max(x for x, _ in profile)),
        "min_x_mm": float(min(x for x, _ in profile)),
    }

    return cutter, cutter_metadata
```

## 9.6 Side-groove cutter 只作兼容

```python
def _make_side_groove_slot_cutter(
    cq,
    params: dict,
    *,
    rim_z_min: float,
    rim_z_max: float,
):
    style = _get_str(params, "rim_slot_style", "none")
    axial_margin = _get_float(params, "rim_slot_axial_margin_mm", 0.0)

    z_min = rim_z_min + axial_margin
    z_max = rim_z_max - axial_margin
    height = z_max - z_min

    if height <= 0:
        raise ValueError("side_groove rim slot has non-positive cutter height")

    if style == "rectangular":
        profile = _rectangular_slot_profile_xy(params)
    elif style in {"dovetail", "fir_tree_like"}:
        profile = _fir_tree_slot_profile_xy(params)
    else:
        raise ValueError(f"Unsupported side-groove rim_slot_style: {style!r}")

    cutter = (
        cq.Workplane("XY")
        .polyline(profile)
        .close()
        .extrude(height)
        .translate((0.0, 0.0, z_min))
    )

    cutter_metadata = {
        "profile_points_xy": [[float(x), float(y)] for x, y in profile],
        "z_min_mm": float(z_min),
        "z_max_mm": float(z_max),
        "height_mm": float(height),
        "max_x_mm": float(max(x for x, _ in profile)),
        "min_x_mm": float(min(x for x, _ in profile)),
    }

    return cutter, cutter_metadata
```

## 9.7 `_cut_rim_slots()` 必须返回 metadata

```python
def _cut_rim_slots(cq, result, params: dict, axial_zones: dict):
    count = _get_int(params, "rim_slot_count", 0)
    style = _get_str(params, "rim_slot_style", "none")
    orientation = _get_str(params, "rim_slot_orientation", "axial_through")

    if count <= 0 or style == "none":
        return result, {
            "enabled": False,
            "slot_count": 0,
            "slot_style": style,
            "orientation": orientation,
            "profile_points_xy": [],
            "z_min_mm": None,
            "z_max_mm": None,
            "opens_front_face": False,
            "opens_back_face": False,
            "opens_outer_diameter": False,
            "reference_only": True,
        }

    rim_z_min = float(axial_zones["rim_z_min_mm"])
    rim_z_max = float(axial_zones["rim_z_max_mm"])

    if orientation == "axial_through":
        cutter, cutter_md = _make_axial_through_slot_cutter(
            cq,
            params,
            rim_z_min=rim_z_min,
            rim_z_max=rim_z_max,
        )
        opens_front = True
        opens_back = True
        opens_outer = True

    elif orientation == "side_groove":
        cutter, cutter_md = _make_side_groove_slot_cutter(
            cq,
            params,
            rim_z_min=rim_z_min,
            rim_z_max=rim_z_max,
        )
        opens_front = False
        opens_back = False
        opens_outer = True

    else:
        raise ValueError(f"Unsupported rim_slot_orientation: {orientation!r}")

    # Fail-closed: do not catch exceptions here.
    for i in range(count):
        angle = 360.0 * i / count
        rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
        result = result.cut(rotated)

    slot_metadata = {
        "enabled": True,
        "slot_count": int(count),
        "slot_style": style,
        "orientation": orientation,
        "profile_points_xy": cutter_md["profile_points_xy"],
        "z_min_mm": cutter_md["z_min_mm"],
        "z_max_mm": cutter_md["z_max_mm"],
        "height_mm": cutter_md["height_mm"],
        "max_x_mm": cutter_md["max_x_mm"],
        "min_x_mm": cutter_md["min_x_mm"],
        "rim_z_min_mm": rim_z_min,
        "rim_z_max_mm": rim_z_max,
        "opens_front_face": opens_front,
        "opens_back_face": opens_back,
        "opens_outer_diameter": opens_outer,
        "reference_only": True,
    }

    return result, slot_metadata
```

重要要求：

```text
1. 不允许 try/except 吞掉 slot cut 失败。
2. 不允许 cut 失败后继续输出无 slot 模型。
3. rim slot 是本 primitive 的核心特征，失败必须让 build fail。
```

---

# 10. Phase 6：Hub sleeve 与 annular details 的修复建议

## 10.1 当前 hub sleeve 方向风险

当前 front hub sleeve 的实现类似：

```python
sleeve = cq.Workplane("XY").circle(...).circle(...).extrude(front_height).translate((0,0,base_front_z))
```

这通常会让 sleeve 从 `base_front_z` 向 +Z 方向生长。这个行为可以保留，但 metadata 必须记录：

```python
front_sleeve_z_min_mm = base_front_z
front_sleeve_z_max_mm = base_front_z + front_height
```

rear sleeve 则必须记录：

```python
rear_sleeve_z_min_mm = base_rear_z - rear_height
rear_sleeve_z_max_mm = base_rear_z
```

## 10.2 Annular details 不应影响 rim slot

annular details 不应该覆盖外缘 slot。建议：

```text
1. outer_rim_recess_outer_dia_mm 必须小于 outer_dia_mm - 2 * rim_slot_depth_mm * 0.1；
2. seal lands 不要生成在 rim slot 区域；
3. annular raised rings 不要超出 front sleeve 的高度；
4. 先做 annular details，再 cut rim slots。
```

当前顺序应保持：

```text
base body
→ sleeve
→ annular details
→ holes
→ rim slots
```

这样 rim slots 最后切削，能够把前面生成的 rim 细节也切开。

---

# 11. Phase 7：Reference dimensions 与 expected bbox

## 11.1 `_expected_bbox_mm()`

实现：

```python
def _expected_bbox_mm(params: dict) -> list[float]:
    outer_d = _get_float(params, "outer_dia_mm")
    axial_w = _get_float(params, "axial_width_mm")
    front_h = _get_float(params, "front_hub_sleeve_height_mm", 0.0)
    rear_h = _get_float(params, "rear_hub_sleeve_height_mm", 0.0)

    return [
        outer_d,
        outer_d,
        axial_w + front_h + rear_h,
    ]
```

说明：

```text
rim slot 是 subtractive cut，不应增加 bbox；
slot cutter 虽然超出 outer radius，但切削结果外径仍应接近 outer_dia_mm。
```

## 11.2 `_reference_dimensions()`

更新：

```python
def _reference_dimensions(params: dict, slot_metadata: dict) -> dict[str, Any]:
    total_hole_count = (
        1
        + _get_int(params, "bolt_hole_count", 0)
        + _get_int(params, "lightening_hole_count", 0)
        + _get_int(params, "cooling_hole_count", 0)
        + _get_int(params, "coverplate_bolt_count", 0)
        + _get_int(params, "balance_hole_count", 0)
    )

    rim_slot_count = _get_int(params, "rim_slot_count", 0)

    return {
        "outer_dia_mm": _get_float(params, "outer_dia_mm"),
        "bore_dia_mm": _get_float(params, "bore_dia_mm"),
        "axial_width_mm": _get_float(params, "axial_width_mm"),
        "hub_outer_dia_mm": _get_float(params, "hub_outer_dia_mm"),
        "web_outer_dia_mm": _get_float(params, "web_outer_dia_mm"),
        "rim_inner_dia_mm": _get_float(params, "rim_inner_dia_mm"),
        "hub_width_mm": _get_float(params, "hub_width_mm"),
        "web_width_mm": _get_float(params, "web_width_mm"),
        "rim_width_mm": _get_float(params, "rim_width_mm"),

        "front_hub_sleeve_height_mm": _get_float(params, "front_hub_sleeve_height_mm", 0.0),
        "rear_hub_sleeve_height_mm": _get_float(params, "rear_hub_sleeve_height_mm", 0.0),

        "rim_slot_count": rim_slot_count,
        "rim_slot_style": _get_str(params, "rim_slot_style", "none"),
        "rim_slot_orientation": _get_str(params, "rim_slot_orientation", "axial_through"),
        "rim_slot_depth_mm": _get_float(params, "rim_slot_depth_mm", 0.0),
        "rim_slot_width_mm": _get_float(params, "rim_slot_width_mm", 0.0),

        "rim_slot_opens_front_face": bool(slot_metadata.get("opens_front_face")),
        "rim_slot_opens_back_face": bool(slot_metadata.get("opens_back_face")),
        "rim_slot_opens_outer_diameter": bool(slot_metadata.get("opens_outer_diameter")),

        "rim_slot_z_min_mm": slot_metadata.get("z_min_mm"),
        "rim_slot_z_max_mm": slot_metadata.get("z_max_mm"),
        "rim_slot_profile_max_x_mm": slot_metadata.get("max_x_mm"),
        "rim_slot_profile_min_x_mm": slot_metadata.get("min_x_mm"),

        "bolt_hole_count": _get_int(params, "bolt_hole_count", 0),
        "lightening_hole_count": _get_int(params, "lightening_hole_count", 0),
        "cooling_hole_count": _get_int(params, "cooling_hole_count", 0),
        "coverplate_bolt_count": _get_int(params, "coverplate_bolt_count", 0),
        "balance_hole_count": _get_int(params, "balance_hole_count", 0),

        "expected_through_hole_count": total_hole_count,
        "expected_periodic_slot_count": rim_slot_count,
        "visual_feature_count": total_hole_count + rim_slot_count,
        "expected_bbox_mm": _expected_bbox_mm(params),
    }
```

---

# 12. Phase 8：Metadata v3 结构

## 12.1 `_build_metadata()`

metadata 必须包含：

```python
def _build_metadata(
    params: dict,
    profile_points: list[tuple[float, float]],
    axial_zones: dict,
    slot_metadata: dict,
) -> dict[str, Any]:
    ref_dims = _reference_dimensions(params, slot_metadata)

    warnings = [
        "axisymmetric_turbine_disk is non-flight reference geometry only.",
        "Not airworthy, not certified, not manufacturing-ready, not for installation.",
        "Rim slots are visual/reference fir-tree-like features only.",
        "Rim slots are not certified blade attachment geometry.",
        "No contact stress, centrifugal load path, fatigue life, burst margin, or thermal validation is performed.",
        "No real material, life, rotational speed, or safety assessment is performed.",
    ]

    return {
        "primitive": PRIMITIVE_NAME,
        "metadata_version": "primitive_metadata_v1",
        "kernel": KERNEL_NAME,
        "geometry_family": GEOMETRY_FAMILY,
        "parameters": dict(params),
        "reference_dimensions": ref_dims,
        "warnings": warnings,

        "radial_zones": {
            "bore_radius_mm": _get_float(params, "bore_dia_mm") / 2.0,
            "hub_outer_radius_mm": _get_float(params, "hub_outer_dia_mm") / 2.0,
            "web_outer_radius_mm": _get_float(params, "web_outer_dia_mm") / 2.0,
            "rim_inner_radius_mm": _get_float(params, "rim_inner_dia_mm") / 2.0,
            "outer_radius_mm": _get_float(params, "outer_dia_mm") / 2.0,
        },

        "axial_zones": dict(axial_zones),

        "profile_points": [
            [float(r), float(z)]
            for r, z in profile_points
        ],

        "hole_patterns": _hole_patterns_metadata(params),

        "slot_generation": {
            "version": "rim_slot_v3",
            "orientation": slot_metadata.get("orientation"),
            "opens_front_face": slot_metadata.get("opens_front_face") is True,
            "opens_back_face": slot_metadata.get("opens_back_face") is True,
            "opens_outer_diameter": slot_metadata.get("opens_outer_diameter") is True,
            "z_min_mm": slot_metadata.get("z_min_mm"),
            "z_max_mm": slot_metadata.get("z_max_mm"),
            "rim_z_min_mm": slot_metadata.get("rim_z_min_mm"),
            "rim_z_max_mm": slot_metadata.get("rim_z_max_mm"),
            "through_clearance_mm": _get_float(params, "rim_slot_through_clearance_mm", 0.0),
            "outer_clearance_mm": _get_float(params, "rim_slot_outer_clearance_mm", 0.0),
        },

        "rim_features": {
            "slot_count": _get_int(params, "rim_slot_count", 0),
            "slot_style": _get_str(params, "rim_slot_style", "none"),
            "slot_orientation": _get_str(params, "rim_slot_orientation", "axial_through"),
            "slot_depth_mm": _get_float(params, "rim_slot_depth_mm", 0.0),
            "slot_width_mm": _get_float(params, "rim_slot_width_mm", 0.0),
            "slot_profile_points_xy": slot_metadata.get("profile_points_xy", []),
            "reference_only": True,
        },

        "visual_fidelity": {
            "target": "reference_turbine_rotor_disk",
            "contains_cyclic_rim_slots": _get_int(params, "rim_slot_count", 0) > 0,
            "contains_axial_through_rim_slots": (
                _get_int(params, "rim_slot_count", 0) > 0
                and _get_str(params, "rim_slot_orientation", "axial_through") == "axial_through"
            ),
            "contains_hub_sleeve": (
                _get_float(params, "front_hub_sleeve_height_mm", 0.0) > 0
                or _get_float(params, "rear_hub_sleeve_height_mm", 0.0) > 0
            ),
            "contains_annular_details": _get_bool(params, "enable_annular_details", False),
            "contains_coverplate_interface": _get_int(params, "coverplate_bolt_count", 0) > 0,
            "contains_real_blade_attachment": False,
        },

        "hub_sleeve": {
            "front_enabled": _get_float(params, "front_hub_sleeve_height_mm", 0.0) > 0,
            "rear_enabled": _get_float(params, "rear_hub_sleeve_height_mm", 0.0) > 0,
            "front_outer_dia_mm": _get_float(params, "front_hub_sleeve_outer_dia_mm", 0.0),
            "front_inner_dia_mm": _get_float(params, "front_hub_sleeve_inner_dia_mm", 0.0),
            "front_height_mm": _get_float(params, "front_hub_sleeve_height_mm", 0.0),
            "rear_outer_dia_mm": _get_float(params, "rear_hub_sleeve_outer_dia_mm", 0.0),
            "rear_inner_dia_mm": _get_float(params, "rear_hub_sleeve_inner_dia_mm", 0.0),
            "rear_height_mm": _get_float(params, "rear_hub_sleeve_height_mm", 0.0),
        },

        "annular_details": {
            "enabled": _get_bool(params, "enable_annular_details", False),
            "inner_hub_step": _get_float(params, "inner_hub_step_height_mm", 0.0) > 0,
            "mid_web_recess": _get_float(params, "mid_web_recess_depth_mm", 0.0) > 0,
            "outer_rim_recess": _get_float(params, "outer_rim_recess_depth_mm", 0.0) > 0,
            "seal_lands": _get_int(params, "seal_land_count", 0),
        },

        "safety": {
            "non_flight_reference_only": True,
            "not_for_manufacturing": True,
            "not_airworthy": True,
            "not_certified": True,
            "not_for_installation": True,
            "no_structural_validation": True,
            "no_life_prediction": True,
            "no_rotordynamic_validation": True,
        },
    }
```

---

# 13. Phase 9：Metadata validator 更新

## 13.1 修改文件

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
```

## 13.2 Required keys

```python
REQUIRED_TURBINE_METADATA_KEYS = [
    "geometry_family",
    "radial_zones",
    "axial_zones",
    "profile_points",
    "hole_patterns",
    "slot_generation",
    "rim_features",
    "visual_fidelity",
    "hub_sleeve",
    "annular_details",
    "safety",
]
```

## 13.3 检查 geometry family

```python
if metadata.get("geometry_family") != "axisymmetric_base_with_axial_through_rim_slots":
    errors.append(
        "metadata.geometry_family must be 'axisymmetric_base_with_axial_through_rim_slots'"
    )
```

## 13.4 检查 slot_generation

```python
slot = metadata.get("slot_generation")
if not isinstance(slot, dict):
    errors.append("metadata.slot_generation must be a dict")
else:
    if slot.get("version") != "rim_slot_v3":
        errors.append("slot_generation.version must be 'rim_slot_v3'")

    orientation = slot.get("orientation")
    if orientation == "axial_through":
        if slot.get("opens_front_face") is not True:
            errors.append("axial_through rim slots must open the front face")
        if slot.get("opens_back_face") is not True:
            errors.append("axial_through rim slots must open the back face")
        if slot.get("opens_outer_diameter") is not True:
            errors.append("axial_through rim slots must open the outer diameter")

        z_min = slot.get("z_min_mm")
        z_max = slot.get("z_max_mm")
        rim_z_min = slot.get("rim_z_min_mm")
        rim_z_max = slot.get("rim_z_max_mm")

        if z_min is None or rim_z_min is None or not (float(z_min) < float(rim_z_min)):
            errors.append("axial_through slot z_min_mm must be less than rim_z_min_mm")

        if z_max is None or rim_z_max is None or not (float(z_max) > float(rim_z_max)):
            errors.append("axial_through slot z_max_mm must be greater than rim_z_max_mm")
```

## 13.5 检查 rim_features

```python
rim = metadata.get("rim_features")
if not isinstance(rim, dict):
    errors.append("metadata.rim_features must be a dict")
else:
    if rim.get("reference_only") is not True:
        errors.append("rim_features.reference_only must be True")

    if rim.get("slot_orientation") == "axial_through":
        pts = rim.get("slot_profile_points_xy")
        if not isinstance(pts, list) or len(pts) < 4:
            errors.append("axial_through rim slots must record slot_profile_points_xy")
```

## 13.6 检查 visual_fidelity

```python
visual = metadata.get("visual_fidelity")
if not isinstance(visual, dict):
    errors.append("metadata.visual_fidelity must be a dict")
else:
    if visual.get("contains_real_blade_attachment") is not False:
        errors.append("visual_fidelity.contains_real_blade_attachment must be False")

    if visual.get("contains_cyclic_rim_slots") is True:
        if visual.get("contains_axial_through_rim_slots") is not True:
            errors.append(
                "visual_fidelity.contains_axial_through_rim_slots must be True when cyclic rim slots are enabled"
            )
```

## 13.7 检查 safety

```python
safety = metadata.get("safety")
if not isinstance(safety, dict):
    errors.append("metadata.safety must be a dict")
else:
    required_true_flags = [
        "non_flight_reference_only",
        "not_for_manufacturing",
        "not_airworthy",
        "not_certified",
        "not_for_installation",
        "no_structural_validation",
        "no_life_prediction",
    ]

    for key in required_true_flags:
        if safety.get(key) is not True:
            errors.append(f"safety.{key} must be True")
```

---

# 14. Phase 10：Mechanical validation 更新

## 14.1 修改文件

```text
src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
```

## 14.2 常量

```python
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
KERNEL_NAME = "cadquery_turbine_disk_reference_v3"

ALLOWED_KERNELS = {
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
    "cadquery_turbine_disk_reference_v3",
}
```

注意：

```text
为了旧用例兼容，可以允许 v0/v2；
但 demo 和新 tests 必须通过 expected_kernel 强制 v3。
```

## 14.3 `_expected_reference_dimensions()`

必须包含：

```python
def _expected_bbox_mm(params: dict) -> list[float]:
    return [
        float(params["outer_dia_mm"]),
        float(params["outer_dia_mm"]),
        (
            float(params["axial_width_mm"])
            + float(params.get("front_hub_sleeve_height_mm", 0.0))
            + float(params.get("rear_hub_sleeve_height_mm", 0.0))
        ),
    ]
```

并在 `_expected_reference_dimensions()` 中加入：

```python
"rim_slot_count": int(params.get("rim_slot_count", 0)),
"rim_slot_style": str(params.get("rim_slot_style", "none")),
"rim_slot_orientation": str(params.get("rim_slot_orientation", "axial_through")),
"rim_slot_depth_mm": float(params.get("rim_slot_depth_mm", 0.0)),
"rim_slot_width_mm": float(params.get("rim_slot_width_mm", 0.0)),
"front_hub_sleeve_height_mm": float(params.get("front_hub_sleeve_height_mm", 0.0)),
"rear_hub_sleeve_height_mm": float(params.get("rear_hub_sleeve_height_mm", 0.0)),
"expected_periodic_slot_count": int(params.get("rim_slot_count", 0)),
"expected_bbox_mm": _expected_bbox_mm(params),
```

## 14.4 Kernel 检查

保留：

```python
if kernel not in ALLOWED_KERNELS:
    error
```

但 expected kernel 必须强制：

```python
expected_kernel = expected.get("expected_kernel")
if expected_kernel and kernel != expected_kernel:
    issues.append(
        _issue(
            "turbine_disk_expected_kernel_mismatch",
            "Expected kernel mismatch.",
            expected=expected_kernel,
            actual=kernel,
        )
    )
```

demo 必须传：

```python
"expected_kernel": "cadquery_turbine_disk_reference_v3"
```

## 14.5 Geometry family 检查

```python
expected_family = "axisymmetric_base_with_axial_through_rim_slots"
gf = metadata.get("geometry_family")
if kernel == "cadquery_turbine_disk_reference_v3" and gf != expected_family:
    issues.append(
        _issue(
            "turbine_disk_geometry_family_mismatch",
            "Metadata geometry_family mismatch for v3 turbine disk.",
            expected=expected_family,
            actual=gf,
        )
    )
```

## 14.6 Slot 贯穿语义检查

```python
rim_slot_count = int(params.get("rim_slot_count", 0))
rim_slot_orientation = str(params.get("rim_slot_orientation", "axial_through"))

if rim_slot_count > 0:
    slot_gen = metadata.get("slot_generation") or {}
    rim = metadata.get("rim_features") or {}
    visual = metadata.get("visual_fidelity") or {}

    if slot_gen.get("version") != "rim_slot_v3":
        issues.append(
            _issue(
                "turbine_disk_slot_generation_version_mismatch",
                "slot_generation.version must be rim_slot_v3.",
                expected="rim_slot_v3",
                actual=slot_gen.get("version"),
            )
        )

    if slot_gen.get("orientation") != rim_slot_orientation:
        issues.append(
            _issue(
                "turbine_disk_slot_orientation_mismatch",
                "slot_generation.orientation does not match CAD-IR parameter.",
                expected=rim_slot_orientation,
                actual=slot_gen.get("orientation"),
            )
        )

    if rim_slot_orientation == "axial_through":
        for key in ["opens_front_face", "opens_back_face", "opens_outer_diameter"]:
            if slot_gen.get(key) is not True:
                issues.append(
                    _issue(
                        f"turbine_disk_slot_{key}_missing",
                        f"axial_through rim slots require slot_generation.{key}=True.",
                        expected=True,
                        actual=slot_gen.get(key),
                    )
                )

        z_min = slot_gen.get("z_min_mm")
        z_max = slot_gen.get("z_max_mm")
        rim_z_min = slot_gen.get("rim_z_min_mm")
        rim_z_max = slot_gen.get("rim_z_max_mm")

        if z_min is None or rim_z_min is None or not (float(z_min) < float(rim_z_min)):
            issues.append(
                _issue(
                    "turbine_disk_slot_z_min_not_through",
                    "axial_through slot z_min_mm must be less than rim_z_min_mm.",
                    expected="z_min_mm < rim_z_min_mm",
                    actual={"z_min_mm": z_min, "rim_z_min_mm": rim_z_min},
                )
            )

        if z_max is None or rim_z_max is None or not (float(z_max) > float(rim_z_max)):
            issues.append(
                _issue(
                    "turbine_disk_slot_z_max_not_through",
                    "axial_through slot z_max_mm must be greater than rim_z_max_mm.",
                    expected="z_max_mm > rim_z_max_mm",
                    actual={"z_max_mm": z_max, "rim_z_max_mm": rim_z_max},
                )
            )

    if int(rim.get("slot_count", -1)) != rim_slot_count:
        issues.append(
            _issue(
                "turbine_disk_rim_slot_count_mismatch",
                "rim_features.slot_count does not match CAD-IR params.",
                expected=rim_slot_count,
                actual=rim.get("slot_count"),
            )
        )

    if rim.get("slot_style") != params.get("rim_slot_style"):
        issues.append(
            _issue(
                "turbine_disk_rim_slot_style_mismatch",
                "rim_features.slot_style does not match CAD-IR params.",
                expected=params.get("rim_slot_style"),
                actual=rim.get("slot_style"),
            )
        )

    if visual.get("contains_axial_through_rim_slots") is not True:
        issues.append(
            _issue(
                "turbine_disk_visual_axial_through_slots_missing",
                "visual_fidelity.contains_axial_through_rim_slots must be True.",
                expected=True,
                actual=visual.get("contains_axial_through_rim_slots"),
            )
        )

    if visual.get("contains_real_blade_attachment") is not False:
        issues.append(
            _issue(
                "turbine_disk_real_blade_attachment_flag_invalid",
                "visual_fidelity.contains_real_blade_attachment must be False.",
                expected=False,
                actual=visual.get("contains_real_blade_attachment"),
            )
        )
```

## 14.7 BBox 检查必须用 expected_bbox_mm

替换旧的 Z 检查：

```python
expected_z = axial_width + front_height + rear_height
```

为统一使用：

```python
expected_bbox = ref["expected_bbox_mm"]

if abs(float(bbox[0]) - expected_bbox[0]) > tolerance_mm:
    error

if abs(float(bbox[1]) - expected_bbox[1]) > tolerance_mm:
    error

if abs(float(bbox[2]) - expected_bbox[2]) > tolerance_mm:
    error
```

这样 demo、metadata、mechanical validation 使用同一口径。

## 14.8 Safety flags

必须新增检查：

```python
required_safety_flags = [
    "non_flight_reference_only",
    "not_for_manufacturing",
    "not_airworthy",
    "not_certified",
    "not_for_installation",
    "no_structural_validation",
    "no_life_prediction",
]

for key in required_safety_flags:
    if safety.get(key) is not True:
        issue
```

---

# 15. Phase 11：Primitive compiler 检查

## 15.1 修改文件

```text
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

当前 compiler 的方向是正确的：只调用 `build_axisymmetric_turbine_disk_cadquery()`，不要把 slot cutter 逻辑内联进 compiler。

必须保持：

```python
result, PRIMITIVE_METADATA["axisymmetric_turbine_disk"] = (
    build_axisymmetric_turbine_disk_cadquery(_params)
)
```

## 15.2 新增测试要求

`test_axisymmetric_turbine_disk_compiler.py` 必须验证：

```text
1. "axisymmetric_turbine_disk" 在 compiler registry 中；
2. 编译脚本包含 build_axisymmetric_turbine_disk_cadquery；
3. 编译脚本不包含 _make_axial_through_slot_cutter；
4. 编译脚本不包含 Workplane("XY").polyline；
5. 编译脚本不包含 result.cut(rotated)；
6. compiler 仍然只是 deterministic kernel dispatcher。
```

---

# 16. Phase 12：Demo 更新

## 16.1 修改文件

```text
demo_full_chain.py
```

## 16.2 参数必须加入 v3 字段

`run_case_axisymmetric_turbine_disk()` 中必须包含：

```python
"rim_slot_orientation": "axial_through",
"rim_slot_axial_margin_mm": 0.0,
"rim_slot_through_clearance_mm": 2.0,
"rim_slot_outer_clearance_mm": 4.0,
```

推荐 demo 参数：

```python
params = {
    "outer_dia_mm": 520.0,
    "bore_dia_mm": 86.0,
    "axial_width_mm": 62.0,

    "hub_outer_dia_mm": 210.0,
    "web_outer_dia_mm": 360.0,
    "rim_inner_dia_mm": 420.0,

    "hub_width_mm": 62.0,
    "web_width_mm": 30.0,
    "rim_width_mm": 58.0,

    "hub_fillet_radius_mm": 1.5,
    "web_fillet_radius_mm": 1.0,
    "rim_fillet_radius_mm": 1.0,
    "edge_chamfer_mm": 0.5,

    "bolt_hole_count": 0,
    "bolt_pcd_mm": 0.0,
    "bolt_hole_dia_mm": 0.0,
    "bolt_hole_axis": "Z",

    "lightening_hole_count": 10,
    "lightening_hole_pcd_mm": 310.0,
    "lightening_hole_dia_mm": 20.0,
    "lightening_hole_axis": "Z",

    "cooling_hole_count": 36,
    "cooling_hole_pcd_mm": 455.0,
    "cooling_hole_dia_mm": 4.0,
    "cooling_hole_axis": "Z",

    "rim_slot_count": 60,
    "rim_slot_style": "fir_tree_like",
    "rim_slot_orientation": "axial_through",
    "rim_slot_depth_mm": 38.0,
    "rim_slot_width_mm": 7.0,
    "rim_slot_neck_width_mm": 4.5,
    "rim_slot_lobe_width_mm": 8.5,
    "rim_slot_lobe_depth_mm": 7.0,
    "rim_slot_axial_margin_mm": 0.0,
    "rim_slot_through_clearance_mm": 2.0,
    "rim_slot_outer_clearance_mm": 4.0,
    "rim_slot_root_fillet_mm": 0.0,
    "rim_slot_tip_chamfer_mm": 0.0,

    "front_hub_sleeve_outer_dia_mm": 155.0,
    "front_hub_sleeve_inner_dia_mm": 86.0,
    "front_hub_sleeve_height_mm": 58.0,
    "front_hub_sleeve_wall_mm": 8.0,
    "front_hub_sleeve_chamfer_mm": 1.5,

    "rear_hub_sleeve_outer_dia_mm": 0.0,
    "rear_hub_sleeve_inner_dia_mm": 0.0,
    "rear_hub_sleeve_height_mm": 0.0,
    "rear_hub_sleeve_chamfer_mm": 0.0,

    "enable_annular_details": True,

    "inner_hub_step_outer_dia_mm": 190.0,
    "inner_hub_step_height_mm": 8.0,

    "mid_web_recess_inner_dia_mm": 225.0,
    "mid_web_recess_outer_dia_mm": 365.0,
    "mid_web_recess_depth_mm": 3.0,

    "outer_rim_recess_inner_dia_mm": 395.0,
    "outer_rim_recess_outer_dia_mm": 485.0,
    "outer_rim_recess_depth_mm": 2.0,

    "seal_land_count": 2,
    "seal_land_height_mm": 2.0,
    "seal_land_width_mm": 3.0,
    "seal_land_start_dia_mm": 160.0,
    "seal_land_pitch_mm": 8.0,

    "coverplate_bolt_count": 18,
    "coverplate_bolt_pcd_mm": 175.0,
    "coverplate_bolt_dia_mm": 4.0,
    "coverplate_bolt_axis": "Z",

    "balance_hole_count": 0,
    "balance_hole_pcd_mm": 0.0,
    "balance_hole_dia_mm": 0.0,
    "balance_hole_axis": "Z",

    "quality_grade": "engineering_reference",
    "non_flight_reference_only": True,
}
```

## 16.3 expected validation

必须改为：

```python
expected_bbox_mm = [
    520.0,
    520.0,
    62.0 + 58.0 + 0.0,
]
```

并且：

```python
"primitive_validation": {
    "primitive1": {
        "expected_kernel": "cadquery_turbine_disk_reference_v3",
        "expected_periodic_slot_count": 60,
        "expected_slot_orientation": "axial_through",
    }
}
```

## 16.4 Required metrics

`TURBINE_DISK_REQUIRED_METRICS` 必须包含：

```text
kernel_used
reference_dimensions.outer_dia_mm
reference_dimensions.bore_dia_mm
reference_dimensions.axial_width_mm
reference_dimensions.rim_slot_count
reference_dimensions.rim_slot_style
reference_dimensions.rim_slot_orientation
reference_dimensions.rim_slot_opens_front_face
reference_dimensions.rim_slot_opens_back_face
reference_dimensions.rim_slot_opens_outer_diameter
reference_dimensions.expected_periodic_slot_count
reference_dimensions.expected_bbox_mm
reference_dimensions.rim_slot_z_min_mm
reference_dimensions.rim_slot_z_max_mm
reference_dimensions.rim_slot_profile_max_x_mm
reference_dimensions.rim_slot_profile_min_x_mm
```

---

# 17. Phase 13：测试计划

## 17.1 参数测试

文件：

```text
tests/test_axisymmetric_turbine_disk_parameters.py
```

新增：

```python
def test_axial_through_rim_slots_happy_path_normalizes():
    ...

def test_axial_through_rejects_axial_margin():
    ...

def test_rim_slot_orientation_invalid_fails():
    ...

def test_rim_slot_style_none_requires_zero_count():
    ...

def test_rim_slot_depth_too_large_fails():
    ...

def test_rim_slot_width_overlap_fails():
    ...

def test_fir_tree_like_requires_neck_lobe_params():
    ...

def test_fir_tree_like_requires_neck_narrower_than_lobe():
    ...

def test_negative_slot_outer_clearance_fails():
    ...

def test_negative_slot_through_clearance_fails():
    ...
```

关键测试：

```python
def test_axial_through_rejects_axial_margin():
    params = valid_turbine_disk_params()
    params["rim_slot_orientation"] = "axial_through"
    params["rim_slot_axial_margin_mm"] = 4.0

    with pytest.raises(ValueError):
        normalize_primitive_parameters("axisymmetric_turbine_disk", params)
```

## 17.2 Kernel visual feature tests

文件：

```text
tests/test_turbine_disk_visual_features.py
```

新增：

```python
def test_axial_through_slot_metadata_z_range_exceeds_rim_z_range():
    result, md = build_axisymmetric_turbine_disk_cadquery(valid_params)
    slot = md["slot_generation"]

    assert slot["orientation"] == "axial_through"
    assert slot["z_min_mm"] < slot["rim_z_min_mm"]
    assert slot["z_max_mm"] > slot["rim_z_max_mm"]

def test_axial_through_slot_profile_extends_beyond_outer_radius():
    result, md = build_axisymmetric_turbine_disk_cadquery(valid_params)
    outer_radius = valid_params["outer_dia_mm"] / 2.0
    max_x = md["reference_dimensions"]["rim_slot_profile_max_x_mm"]

    assert max_x > outer_radius

def test_axial_through_slot_declares_front_back_outer_openings():
    result, md = build_axisymmetric_turbine_disk_cadquery(valid_params)
    slot = md["slot_generation"]

    assert slot["opens_front_face"] is True
    assert slot["opens_back_face"] is True
    assert slot["opens_outer_diameter"] is True

def test_v3_metadata_contains_visual_reference_flags():
    result, md = build_axisymmetric_turbine_disk_cadquery(valid_params)
    visual = md["visual_fidelity"]

    assert visual["contains_axial_through_rim_slots"] is True
    assert visual["contains_real_blade_attachment"] is False
```

可选 CadQuery bbox 测试：

```python
def test_v3_bbox_includes_front_sleeve():
    result, md = build_axisymmetric_turbine_disk_cadquery(valid_params)
    bbox = result.val().BoundingBox()

    expected = md["reference_dimensions"]["expected_bbox_mm"]
    assert abs((bbox.xmax - bbox.xmin) - expected[0]) < 1.0
    assert abs((bbox.ymax - bbox.ymin) - expected[1]) < 1.0
    assert abs((bbox.zmax - bbox.zmin) - expected[2]) < 1.0
```

## 17.3 Metadata tests

文件：

```text
tests/test_axisymmetric_turbine_disk_metadata.py
```

新增：

```python
def test_v3_metadata_requires_geometry_family():
    ...

def test_v3_metadata_requires_slot_generation():
    ...

def test_v3_metadata_rejects_missing_front_opening():
    ...

def test_v3_metadata_rejects_missing_back_opening():
    ...

def test_v3_metadata_rejects_missing_outer_opening():
    ...

def test_v3_metadata_rejects_real_blade_attachment_true():
    ...

def test_v3_metadata_requires_safety_not_for_installation():
    ...

def test_v3_metadata_requires_no_structural_validation():
    ...
```

## 17.4 Mechanical validation tests

文件：

```text
tests/test_axisymmetric_turbine_disk_mechanical_validation.py
```

新增：

```python
def test_v3_mechanical_validation_happy_path():
    ...

def test_v3_mechanical_validation_requires_expected_kernel():
    ...

def test_v3_mechanical_validation_rejects_slot_not_front_open():
    ...

def test_v3_mechanical_validation_rejects_slot_not_back_open():
    ...

def test_v3_mechanical_validation_rejects_slot_not_outer_open():
    ...

def test_v3_mechanical_validation_rejects_wrong_slot_count():
    ...

def test_v3_mechanical_validation_rejects_wrong_bbox_z():
    ...

def test_v3_mechanical_validation_rejects_real_blade_attachment_true():
    ...

def test_v3_mechanical_validation_requires_not_for_installation():
    ...
```

## 17.5 Compiler tests

文件：

```text
tests/test_axisymmetric_turbine_disk_compiler.py
```

新增：

```python
def test_turbine_disk_compiler_dispatches_to_kernel_only():
    feature = PrimitiveFeature(
        id="primitive1",
        type="primitive",
        primitive_name="axisymmetric_turbine_disk",
        parameters=valid_params(),
    )

    script = "\n".join(compile_primitive_to_cadquery_script(feature))

    assert "build_axisymmetric_turbine_disk_cadquery" in script
    assert "_make_axial_through_slot_cutter" not in script
    assert "Workplane(\"XY\").polyline" not in script
    assert "result.cut(rotated)" not in script
```

## 17.6 Demo test

文件：

```text
tests/test_demo_full_chain_turbine_disk.py
```

新增/更新：

```python
def test_demo_turbine_disk_requires_v3_kernel():
    ...

def test_demo_turbine_disk_required_metrics_include_slot_openings():
    ...

def test_demo_turbine_disk_reference_dimensions_not_gear_filtered():
    ...
```

---

# 18. Phase 14：工程验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools
python -m pytest tests -q
```

重点运行：

```bash
python -m pytest tests/test_axisymmetric_turbine_disk_parameters.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_compiler.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_metadata.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_mechanical_validation.py -q
python -m pytest tests/test_turbine_disk_visual_features.py -q
python -m pytest tests/test_demo_full_chain_turbine_disk.py -q
```

Demo：

```bash
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
```

可选：

```bash
python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case axisymmetric_turbine_disk --backend nx12 --allow-step-import
```

---

# 19. SolidWorks 视觉验收标准

生成的模型必须满足：

```text
1. 从俯视图看，外缘圆环被 slot 打断；
2. 从前端面看，rim slot 开口清晰可见；
3. 从后端面看，rim slot 开口清晰可见；
4. 从侧视图看，不再只是外圆柱侧壁竖槽；
5. slot 与 slot 之间形成 disk posts；
6. 外缘具备 blade-root slot 的参考视觉语义；
7. 中心 hub sleeve 仍然存在；
8. annular details 仍然存在；
9. coverplate small holes 仍然存在；
10. 整体不再像普通厚法兰盘。
```

不要求：

```text
1. 真实 fir-tree 接触面；
2. 真实叶根榫槽角度；
3. 真实制造圆角；
4. 真实装配间隙；
5. 真实材料/强度/寿命。
```

---

# 20. Definition of Done

本轮只有满足以下全部条件才算完成：

```text
1. primitive_name 仍为 axisymmetric_turbine_disk。
2. KERNEL_NAME 为 cadquery_turbine_disk_reference_v3。
3. geometry_family 为 axisymmetric_base_with_axial_through_rim_slots。
4. models.py 注册所有 v3 参数。
5. validator 接受 axial_through happy path。
6. validator 拒绝 axial_through + rim_slot_axial_margin_mm > 0。
7. validator 拒绝 slot depth 过大。
8. validator 拒绝 slot overlap。
9. _build_base_body 返回 axial_zones。
10. _cut_rim_slots 使用 rim_z_min/rim_z_max。
11. axial_through cutter z_min < rim_z_min。
12. axial_through cutter z_max > rim_z_max。
13. axial_through cutter profile max_x > outer_radius。
14. rim slot cut 失败时 build fail，不得吞异常。
15. metadata.slot_generation.version = rim_slot_v3。
16. metadata.slot_generation.opens_front_face = True。
17. metadata.slot_generation.opens_back_face = True。
18. metadata.slot_generation.opens_outer_diameter = True。
19. metadata.rim_features.slot_profile_points_xy 非空。
20. metadata.visual_fidelity.contains_axial_through_rim_slots = True。
21. metadata.visual_fidelity.contains_real_blade_attachment = False。
22. metadata.safety.not_for_installation = True。
23. metadata.safety.no_structural_validation = True。
24. metadata.safety.no_life_prediction = True。
25. mechanical validation 使用 expected_bbox_mm。
26. mechanical validation 强制 demo expected_kernel = v3。
27. demo_full_chain axisymmetric_turbine_disk overall_ok=True。
28. demo metrics 包含 rim_slot_opens_front_face/back_face/outer_diameter。
29. SolidWorks 俯视图外缘圆环被 slot 打断。
30. SolidWorks 前后端面均可见 slot 开口。
31. 现有 involute_spur_gear 测试不被破坏。
32. 现有 recipe cases 不被破坏。
33. 所有新增测试通过。
```

---

# 21. 可直接交给 Claude Code 的最终 Prompt

```text
你现在在 seekflow-engineering 仓库中工作，重点目录：

integrations/engineering_tools/

用户最新反馈：当前 axisymmetric_turbine_disk 生成的涡轮盘外缘“叶片卡槽”仍然有问题。SolidWorks 截图显示，卡槽像刻在外圆柱侧壁上的竖向槽，没有贯穿 rim 的前后端面；俯视图中外缘仍然是连续圆环，不像真实涡轮盘的 blade-root slot / fir-tree-like slot。请深度修复 primitive，让外缘 slot 真正成为 axial-through rim slots。

最高约束：
1. primitive_name 必须保持 axisymmetric_turbine_disk。
2. KERNEL_NAME 升级为 cadquery_turbine_disk_reference_v3。
3. GEOMETRY_FAMILY 使用 axisymmetric_base_with_axial_through_rim_slots。
4. 不允许声称 flight-ready / airworthy / certified / manufacturing-ready / installable。
5. 不允许做真实航空发动机强度、寿命、转速、材料、适航设计。
6. 不允许把 fir_tree_like slot 声称为真实叶片连接结构。
7. rim slots 必须声明为 visual/reference geometry only。
8. primitive_compiler 只调用 deterministic kernel，不内联几何。
9. SolidWorks / NX 只能 import canonical STEP。
10. 所有失败必须 fail-closed。
11. 不得破坏 involute_spur_gear。
12. 不得破坏现有 recipe cases。

你必须修改：
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
- src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
- src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
- demo_full_chain.py

你必须新增/更新测试：
- tests/test_axisymmetric_turbine_disk_parameters.py
- tests/test_axisymmetric_turbine_disk_compiler.py
- tests/test_axisymmetric_turbine_disk_metadata.py
- tests/test_axisymmetric_turbine_disk_mechanical_validation.py
- tests/test_turbine_disk_visual_features.py
- tests/test_demo_full_chain_turbine_disk.py

核心修复目标：
当前 side-groove 行为必须升级为 axial-through 行为。对于 rim_slot_orientation="axial_through"：
1. rim_slot_axial_margin_mm 必须为 0；
2. cutter z_min 必须小于 rim_z_min；
3. cutter z_max 必须大于 rim_z_max；
4. cutter profile max_x 必须大于 outer_radius；
5. cutter inner x 必须等于 outer_radius - rim_slot_depth_mm；
6. cutter 必须沿 Z 贯穿整个 rim；
7. cut 后 slot 必须打开 front face；
8. cut 后 slot 必须打开 back face；
9. cut 后 slot 必须打开 outer diameter；
10. metadata 和 mechanical validation 必须验证上述语义。

第一步：models.py
确保 AXISYMMETRIC_TURBINE_DISK.parameters 注册以下 v3 参数：
rim_slot_count
rim_slot_style
rim_slot_orientation
rim_slot_depth_mm
rim_slot_width_mm
rim_slot_neck_width_mm
rim_slot_lobe_width_mm
rim_slot_lobe_depth_mm
rim_slot_axial_margin_mm
rim_slot_through_clearance_mm
rim_slot_outer_clearance_mm
rim_slot_root_fillet_mm
rim_slot_tip_chamfer_mm
front_hub_sleeve_outer_dia_mm
front_hub_sleeve_inner_dia_mm
front_hub_sleeve_height_mm
front_hub_sleeve_wall_mm
front_hub_sleeve_chamfer_mm
rear_hub_sleeve_outer_dia_mm
rear_hub_sleeve_inner_dia_mm
rear_hub_sleeve_height_mm
rear_hub_sleeve_chamfer_mm
enable_annular_details
inner_hub_step_outer_dia_mm
inner_hub_step_height_mm
mid_web_recess_inner_dia_mm
mid_web_recess_outer_dia_mm
mid_web_recess_depth_mm
outer_rim_recess_inner_dia_mm
outer_rim_recess_outer_dia_mm
outer_rim_recess_depth_mm
seal_land_count
seal_land_height_mm
seal_land_width_mm
seal_land_start_dia_mm
seal_land_pitch_mm
coverplate_bolt_count
coverplate_bolt_pcd_mm
coverplate_bolt_dia_mm
coverplate_bolt_axis
balance_hole_count
balance_hole_pcd_mm
balance_hole_dia_mm
balance_hole_axis

默认：
rim_slot_count = 60
rim_slot_style = "fir_tree_like"
rim_slot_orientation = "axial_through"
rim_slot_axial_margin_mm = 0.0
rim_slot_through_clearance_mm = 2.0
rim_slot_outer_clearance_mm = 4.0

supported_kernels 必须包含 cadquery_turbine_disk_reference_v3。

第二步：validator.py
新增：
ALLOWED_RIM_SLOT_ORIENTATIONS = {"axial_through", "side_groove"}

升级 _validate_rim_slots：
- rim_slot_style 合法；
- rim_slot_orientation 合法；
- style == "none" 时 count 必须 0；
- style != "none" 时 count >= 12；
- depth > 0；
- width > 0；
- depth < 0.85 * rim radial thickness；
- pitch > 1.25 * width；
- through_clearance >= 0；
- outer_clearance >= 0；
- axial_through 时 rim_slot_axial_margin_mm 必须等于 0；
- axial_through 时 rim_width + 2 * through_clearance 必须大于 rim_width；
- fir_tree_like 时 neck_width、lobe_width、lobe_depth 必须 > 0；
- fir_tree_like 时 neck_width < lobe_width。

第三步：axisymmetric_turbine_disk.py
重写为清晰函数结构。
设置：
KERNEL_NAME = "cadquery_turbine_disk_reference_v3"
GEOMETRY_FAMILY = "axisymmetric_base_with_axial_through_rim_slots"

_build_base_body 必须返回：
result, profile_points, axial_zones

axial_zones 至少包含：
rim_z_min_mm
rim_z_max_mm
hub_z_min_mm
hub_z_max_mm
web_z_min_mm
web_z_max_mm
base_z_min_mm
base_z_max_mm

新增 XY slot profiles：
_rectangular_slot_profile_xy
_dovetail_slot_profile_xy
_fir_tree_slot_profile_xy

fir_tree_like profile 必须用 polygon 表达 mouth / neck / lobe / root pocket，不要只用一个 box。

_make_axial_through_slot_cutter：
- 使用 rim_z_min/rim_z_max；
- z_min = rim_z_min - rim_slot_through_clearance_mm；
- z_max = rim_z_max + rim_slot_through_clearance_mm；
- height = z_max - z_min；
- profile max_x = outer_radius + rim_slot_outer_clearance_mm；
- profile min_x = outer_radius - rim_slot_depth_mm；
- cq.Workplane("XY").polyline(profile).close().extrude(height).translate((0,0,z_min))；
- 返回 cutter 和 cutter_metadata。

_cut_rim_slots：
- style none 或 count 0 时返回 enabled False metadata；
- orientation axial_through 时使用 _make_axial_through_slot_cutter；
- orientation side_groove 时只作兼容；
- 每个 slot rotate 后 result = result.cut(rotated)；
- 不允许 catch cut 异常后继续；
- 返回 result, slot_metadata；
- slot_metadata 必须包含 opens_front_face、opens_back_face、opens_outer_diameter、z_min/z_max、rim_z_min/rim_z_max、profile_points_xy、max_x/min_x。

第四步：metadata
_build_metadata 必须写入：
kernel = cadquery_turbine_disk_reference_v3
geometry_family = axisymmetric_base_with_axial_through_rim_slots
axial_zones
slot_generation
rim_features
visual_fidelity
safety

slot_generation 必须包含：
version = rim_slot_v3
orientation
opens_front_face
opens_back_face
opens_outer_diameter
z_min_mm
z_max_mm
rim_z_min_mm
rim_z_max_mm
through_clearance_mm
outer_clearance_mm

rim_features 必须包含：
slot_count
slot_style
slot_orientation
slot_depth_mm
slot_width_mm
slot_profile_points_xy
reference_only = True

visual_fidelity 必须包含：
contains_cyclic_rim_slots
contains_axial_through_rim_slots
contains_real_blade_attachment = False

safety 必须包含：
non_flight_reference_only = True
not_for_manufacturing = True
not_airworthy = True
not_certified = True
not_for_installation = True
no_structural_validation = True
no_life_prediction = True

warnings 必须包含：
non-flight reference geometry only
not airworthy
not certified
not manufacturing-ready
not for installation
rim slots are visual/reference fir-tree-like features only
not certified blade attachment geometry
no contact stress / centrifugal load / fatigue life / burst margin / thermal validation

第五步：metadata.py
validate_axisymmetric_turbine_disk_metadata 必须检查：
- geometry_family 正确；
- slot_generation 存在；
- slot_generation.version == rim_slot_v3；
- axial_through 时 opens_front_face/back_face/outer_diameter 全 True；
- axial_through 时 z_min < rim_z_min；
- axial_through 时 z_max > rim_z_max；
- rim_features.reference_only is True；
- rim_features.slot_profile_points_xy 非空；
- visual_fidelity.contains_real_blade_attachment is False；
- contains_cyclic_rim_slots=True 时 contains_axial_through_rim_slots=True；
- safety.not_for_installation=True；
- safety.no_structural_validation=True；
- safety.no_life_prediction=True。

第六步：turbomachinery_validation.py
新增/更新：
KERNEL_NAME = cadquery_turbine_disk_reference_v3
ALLOWED_KERNELS 包含 v0/v2/v3，但 demo expected_kernel 必须强制 v3。

_expected_reference_dimensions 必须包含：
rim_slot_count
rim_slot_style
rim_slot_orientation
rim_slot_depth_mm
rim_slot_width_mm
rim_slot_opens_front_face
rim_slot_opens_back_face
rim_slot_opens_outer_diameter
rim_slot_z_min_mm
rim_slot_z_max_mm
rim_slot_profile_max_x_mm
rim_slot_profile_min_x_mm
expected_periodic_slot_count
expected_bbox_mm

bbox 检查必须使用 expected_bbox_mm，不要只拿 axial_width_mm 检查 Z。

mechanical validation 必须检查：
- expected_kernel mismatch fail；
- geometry_family mismatch fail；
- slot_generation.version != rim_slot_v3 fail；
- axial_through 时 opens_front_face/back_face/outer_diameter 任一不是 True fail；
- z_min >= rim_z_min fail；
- z_max <= rim_z_max fail；
- rim_features.slot_count mismatch fail；
- rim_features.slot_style mismatch fail；
- visual_fidelity.contains_axial_through_rim_slots 不是 True fail；
- visual_fidelity.contains_real_blade_attachment 不是 False fail；
- safety.not_for_installation / no_structural_validation / no_life_prediction 缺失 fail。

第七步：primitive_compiler.py
保持 compiler 只调用 build_axisymmetric_turbine_disk_cadquery。
不要把 _make_axial_through_slot_cutter 或 CadQuery polyline/cut 细节写进 compiler。

第八步：demo_full_chain.py
run_case_axisymmetric_turbine_disk 中加入：
rim_slot_orientation = "axial_through"
rim_slot_axial_margin_mm = 0.0
rim_slot_through_clearance_mm = 2.0
rim_slot_outer_clearance_mm = 4.0
rear_hub_sleeve_chamfer_mm = 0.0
coverplate_bolt_axis = "Z"
balance_hole_axis = "Z"

primitive_validation 中 expected_kernel 改为：
cadquery_turbine_disk_reference_v3

required metrics 加入：
reference_dimensions.rim_slot_orientation
reference_dimensions.rim_slot_opens_front_face
reference_dimensions.rim_slot_opens_back_face
reference_dimensions.rim_slot_opens_outer_diameter
reference_dimensions.expected_periodic_slot_count
reference_dimensions.expected_bbox_mm
reference_dimensions.rim_slot_z_min_mm
reference_dimensions.rim_slot_z_max_mm
reference_dimensions.rim_slot_profile_max_x_mm
reference_dimensions.rim_slot_profile_min_x_mm

第九步：测试
新增/更新以下测试：
1. axial_through happy path normalize 成功；
2. axial_through + rim_slot_axial_margin_mm > 0 必须 fail；
3. slot depth 太大 fail；
4. slot overlap fail；
5. fir_tree_like neck/lobe 参数非法 fail；
6. metadata.slot_generation.version == rim_slot_v3；
7. metadata slot z_min < rim_z_min；
8. metadata slot z_max > rim_z_max；
9. metadata profile max_x > outer_radius；
10. metadata opens_front_face/back_face/outer_diameter 全 True；
11. mechanical validation expected_kernel 强制 v3；
12. mechanical validation 对 slot opening flag 缺失 fail；
13. mechanical validation 对 contains_real_blade_attachment=True fail；
14. compiler 只 dispatch 到 kernel，不内联几何；
15. demo required metrics 包含 slot opening 与 bbox 字段。

运行：
cd integrations/engineering_tools
python -m pytest tests -q
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery

完成后输出：
1. 修改文件清单；
2. 新增/变更参数清单；
3. kernel v3 说明；
4. slot cutter 贯穿逻辑说明；
5. metadata v3 字段说明；
6. 测试结果；
7. demo 结果；
8. 如果 SolidWorks 俯视图仍看不到外缘圆环被 slot 打断，必须说明原因，不得声称完成。
```
