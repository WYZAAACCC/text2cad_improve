
# SeekFlow Engineering：`axisymmetric_turbine_disk` 对称多级 Fir-tree 卡榫/榫槽 v0.5 修复实施文档

## 0. 当前问题判断

用户最新对比图显示，当前 `axisymmetric_turbine_disk` 的外缘卡榫/榫槽仍然不正确。

真实参考图中的槽形特征是：

```text
1. 每个槽是一个轴向贯穿的 blade-root socket；
2. 槽截面基本关于中心线对称；
3. 两侧壁都有多个连续卡槽 / 齿肩 / undercut；
4. 不是单侧锯齿；
5. 不是几个 box 随便叠出来的不规则多边形；
6. 外口相对较窄，内部逐级展开；
7. 多级卡槽沿径向排列，形成典型 fir-tree-like profile；
8. 相邻槽之间保留完整 disk post。
```

当前生成结果的问题是：

```text
1. 槽形明显不对称；
2. 一侧边界比较平，另一侧出现不规则折线；
3. 没有左右成对的多级卡槽；
4. 没有清晰的 stage-1 / stage-2 / stage-3 多级榫槽；
5. 像由多个矩形/盒子 Boolean 拼出来的破碎轮廓；
6. 不像真实 fir-tree / dovetail blade-root socket。
```

本轮目标：

```text
将当前 fir_tree_like slot 从“box 拼接槽”升级为
“参数化、左右镜像对称、多级 fir-tree socket polygon”。

primitive_name 保持：
axisymmetric_turbine_disk

kernel 升级为：
cadquery_turbine_disk_reference_v5

geometry_family 升级为：
axisymmetric_base_with_symmetric_multistage_fir_tree_slots
```

---

## 1. 最高约束

Claude Code 必须遵守：

```text
1. 不允许声称 flight-ready。
2. 不允许声称 airworthy。
3. 不允许声称 certified。
4. 不允许声称 manufacturing-ready。
5. 不允许声称 installable。
6. 不允许做真实航空发动机强度、寿命、材料、转速、适航设计。
7. 不允许把 fir_tree_like slot 声称为真实认证叶根连接结构。
8. 所有 fir-tree-like slots 都只能声明为 visual/reference geometry。
9. primitive_compiler 只允许调用 deterministic kernel，不能内联 CadQuery 几何。
10. SolidWorks / NX 只能 import canonical STEP。
11. 所有失败路径必须 fail-closed。
12. 不得破坏 involute_spur_gear。
13. 不得破坏现有 recipe cases。
14. primitive_name 不得改，仍为 axisymmetric_turbine_disk。
```

所有 metadata / warnings / safety 字段中必须保留：

```text
non-flight reference geometry only
not airworthy
not certified
not manufacturing-ready
not for installation
fir-tree-like slots are visual/reference geometry only
not certified blade attachment geometry
no contact stress / centrifugal load / fatigue life / burst margin validation
```

---

# 2. 根因分析

## 2.1 当前错误实现

当前 `axisymmetric_turbine_disk.py` 中的 `fir_tree_like` cutter 逻辑本质上是：

```text
1. mouth box；
2. neck box；
3. lobe box；
4. inner pocket box；
5. root pocket box；
6. 将多个 box union；
7. 旋转阵列后 cut。
```

这种实现的问题是：

```text
1. box 的边界不是一个连续的对称槽截面；
2. union 后的轮廓容易出现不规则折线；
3. 左右两侧不一定严格镜像；
4. lobe 和 neck 的几何语义不清晰；
5. 不容易保证“每一级卡槽成对出现”；
6. 不容易写 validation 测试证明它是对称多级卡槽；
7. 最终 SolidWorks 里看起来像乱切出来的锯齿块。
```

因此，v0.5 必须废弃“多个 box union 作为 fir-tree 主实现”的方式。

## 2.2 正确实现方向

v0.5 必须改成：

```text
1. 先生成一个二维 XY slot profile；
2. 该 profile 关于 y=0 完全镜像对称；
3. profile 沿 x 方向从 outer_radius 向内展开；
4. x 是径向，+x 指向外圆；
5. y 是切向宽度；
6. z 是轴向；
7. profile 生成后沿 Z extrude，形成贯穿 rim 的 cutter；
8. cutter 绕 Z 轴按 rim_slot_count 阵列；
9. 每个 cutter 去 cut rim；
10. metadata 记录完整 profile、stage count、symmetry check。
```

核心概念：

```text
真实感来自“对称多级截面”，不是来自更多随机折线。
```

---

# 3. v0.5 参数设计

## 3.1 保留旧参数

不要删除已有参数，避免破坏旧 CAD-IR：

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
rim_slot_socket_mode
rim_slot_expose_lobes_on_od
```

## 3.2 新增 v0.5 参数

在：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
```

中新增以下参数：

```text
rim_slot_stage_count
rim_slot_stage_pitch_mm
rim_slot_stage_neck_width_mm
rim_slot_stage_lobe_width_mm
rim_slot_stage_lobe_height_mm
rim_slot_stage_width_growth
rim_slot_stage_depth_distribution

rim_slot_mouth_width_mm
rim_slot_throat_width_mm
rim_slot_root_width_mm

rim_slot_profile_symmetry
rim_slot_require_multiple_stages
```

推荐默认：

```text
rim_slot_stage_count = 3
rim_slot_stage_pitch_mm = 7.0
rim_slot_stage_neck_width_mm = 4.6
rim_slot_stage_lobe_width_mm = 8.8
rim_slot_stage_lobe_height_mm = 2.1
rim_slot_stage_width_growth = 0.08
rim_slot_stage_depth_distribution = "uniform"

rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.6
rim_slot_root_width_mm = 5.4

rim_slot_profile_symmetry = "mirror_y"
rim_slot_require_multiple_stages = True
```

允许值：

```text
rim_slot_profile_symmetry:
  mirror_y

rim_slot_stage_depth_distribution:
  uniform
  progressive
```

v0.5 demo 必须使用：

```text
rim_slot_style = "fir_tree_like"
rim_slot_orientation = "axial_through"
rim_slot_socket_mode = "internal_lobes"
rim_slot_expose_lobes_on_od = False
rim_slot_profile_symmetry = "mirror_y"
rim_slot_require_multiple_stages = True
rim_slot_stage_count = 3
```

---

# 4. Validator v0.5 修改

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
```

## 4.1 新增允许值

```python
ALLOWED_RIM_SLOT_PROFILE_SYMMETRIES = {
    "mirror_y",
}

ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS = {
    "uniform",
    "progressive",
}
```

## 4.2 `_validate_rim_slots()` 新增检查

在已有 rim slot 检查基础上，新增：

```python
stage_count = int(params.get("rim_slot_stage_count", 0))
stage_pitch = float(params.get("rim_slot_stage_pitch_mm", 0.0))
stage_neck_w = float(params.get("rim_slot_stage_neck_width_mm", 0.0))
stage_lobe_w = float(params.get("rim_slot_stage_lobe_width_mm", 0.0))
stage_lobe_h = float(params.get("rim_slot_stage_lobe_height_mm", 0.0))
stage_growth = float(params.get("rim_slot_stage_width_growth", 0.0))
stage_distribution = str(params.get("rim_slot_stage_depth_distribution", "uniform"))

profile_symmetry = str(params.get("rim_slot_profile_symmetry", "mirror_y"))
require_multiple = bool(params.get("rim_slot_require_multiple_stages", True))
```

必须检查：

```text
1. profile_symmetry == "mirror_y"；
2. stage_distribution in {"uniform", "progressive"}；
3. fir_tree_like 时 stage_count >= 2；
4. v0.5 demo 建议 stage_count >= 3；
5. require_multiple_stages=True 时 stage_count >= 2；
6. stage_pitch > 0；
7. stage_neck_width > 0；
8. stage_lobe_width > 0；
9. stage_lobe_width > stage_neck_width；
10. stage_lobe_height > 0；
11. stage_growth >= 0；
12. mouth_width < stage_lobe_width；
13. throat_width <= mouth_width；
14. root_width <= stage_lobe_width；
15. rim_slot_expose_lobes_on_od is False；
16. stage_count * stage_pitch 不得超过 rim_slot_depth_mm * 0.85；
17. slot pitch around circumference > max_stage_lobe_width * 1.25。
```

推荐代码：

```python
if style == "fir_tree_like":
    if profile_symmetry != "mirror_y":
        errors.append("rim_slot_profile_symmetry must be 'mirror_y' for fir_tree_like slots")

    if stage_distribution not in ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS:
        errors.append(
            f"rim_slot_stage_depth_distribution must be one of "
            f"{sorted(ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS)}"
        )

    if require_multiple and stage_count < 2:
        errors.append(
            "rim_slot_require_multiple_stages=True requires rim_slot_stage_count >= 2"
        )

    if stage_count < 2:
        errors.append("fir_tree_like rim slots require at least 2 symmetric stages")

    if stage_pitch <= 0:
        errors.append("rim_slot_stage_pitch_mm must be > 0")

    if stage_neck_w <= 0:
        errors.append("rim_slot_stage_neck_width_mm must be > 0")

    if stage_lobe_w <= 0:
        errors.append("rim_slot_stage_lobe_width_mm must be > 0")

    if stage_lobe_w <= stage_neck_w:
        errors.append(
            "rim_slot_stage_lobe_width_mm must be greater than rim_slot_stage_neck_width_mm"
        )

    if stage_lobe_h <= 0:
        errors.append("rim_slot_stage_lobe_height_mm must be > 0")

    if stage_growth < 0:
        errors.append("rim_slot_stage_width_growth must be >= 0")

    if stage_count * stage_pitch >= depth * 0.85:
        errors.append(
            "rim_slot_stage_count * rim_slot_stage_pitch_mm is too large for rim_slot_depth_mm"
        )

    max_lobe_w = stage_lobe_w * (1.0 + stage_growth * max(stage_count - 1, 0))
    pitch = 2.0 * math.pi * r_outer / max(count, 1)
    if pitch <= max_lobe_w * 1.25:
        errors.append(
            "rim slot stage lobe width is too large for rim_slot_count; adjacent fir-tree sockets would overlap"
        )
```

## 4.3 强制对称语义

validator 必须明确：

```text
fir_tree_like 不允许 asymmetric profile。
```

如果未来参数里加入 asymmetric mode，也不能作为 demo 默认。本轮只允许：

```text
rim_slot_profile_symmetry = "mirror_y"
```

---

# 5. Kernel v0.5：生成对称多级 profile

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
```

## 5.1 常量

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v5"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
GEOMETRY_FAMILY = "axisymmetric_base_with_symmetric_multistage_fir_tree_slots"
```

## 5.2 禁止项

必须删除或停止使用以下作为 `fir_tree_like` 主实现：

```text
_make_fir_tree_like_slot_cutter
多个 box pieces union 的 cutter
```

可以保留 rectangular/dovetail 简单实现，但：

```text
fir_tree_like 必须使用 polygon profile。
```

## 5.3 新增 helper：宽度读取

```python
def _slot_widths(params: dict) -> dict[str, float]:
    mouth = _get_float(
        params,
        "rim_slot_mouth_width_mm",
        _get_float(params, "rim_slot_width_mm", 0.0),
    )
    throat = _get_float(
        params,
        "rim_slot_throat_width_mm",
        _get_float(params, "rim_slot_neck_width_mm", 0.0),
    )
    root = _get_float(params, "rim_slot_root_width_mm", throat)
    stage_neck = _get_float(params, "rim_slot_stage_neck_width_mm", throat)
    stage_lobe = _get_float(
        params,
        "rim_slot_stage_lobe_width_mm",
        _get_float(params, "rim_slot_lobe_width_mm", 0.0),
    )

    return {
        "mouth": mouth,
        "throat": throat,
        "root": root,
        "stage_neck": stage_neck,
        "stage_lobe": stage_lobe,
    }
```

## 5.4 新增 helper：构造 stage stations

使用“station list”生成对称 profile。

station 定义：

```text
每个 station 是：
(x, width)

x：径向位置；
width：该位置处槽总宽度；
最终左边界 y = -width/2，右边界 y = +width/2。
```

实现：

```python
def _fir_tree_stage_stations(params: dict) -> list[tuple[float, float, str]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    widths = _slot_widths(params)

    stage_count = _get_int(params, "rim_slot_stage_count", 3)
    stage_pitch = _get_float(params, "rim_slot_stage_pitch_mm", 7.0)
    stage_growth = _get_float(params, "rim_slot_stage_width_growth", 0.08)

    mouth_w = widths["mouth"]
    throat_w = widths["throat"]
    root_w = widths["root"]
    stage_neck_w = widths["stage_neck"]
    base_lobe_w = widths["stage_lobe"]

    x_outer = r_outer + outer_clearance
    x_mouth_end = r_outer - depth * 0.12
    x_throat = r_outer - depth * 0.22

    stations: list[tuple[float, float, str]] = [
        (x_outer, mouth_w, "outer_clearance_mouth"),
        (r_outer, mouth_w, "outer_radius_mouth"),
        (x_mouth_end, mouth_w, "mouth_end"),
        (x_throat, throat_w, "initial_throat"),
    ]

    # Allocate stages between x_throat and root.
    available_depth = depth * 0.70
    start_x = x_throat
    for i in range(stage_count):
        lobe_w = base_lobe_w * (1.0 + stage_growth * i)

        neck_x = start_x - stage_pitch * (i + 0.25)
        lobe_x = start_x - stage_pitch * (i + 0.55)
        exit_neck_x = start_x - stage_pitch * (i + 0.85)

        stations.append((neck_x, stage_neck_w, f"stage_{i + 1}_neck_in"))
        stations.append((lobe_x, lobe_w, f"stage_{i + 1}_lobe"))
        stations.append((exit_neck_x, stage_neck_w, f"stage_{i + 1}_neck_out"))

    x_root = r_outer - depth
    stations.append((x_root, root_w, "root"))

    # Enforce monotonic decreasing x and clamp root if needed.
    stations_sorted = []
    last_x = float("inf")
    for x, w, name in stations:
        if x >= last_x:
            x = last_x - 0.1
        if x < x_root:
            x = x_root
        stations_sorted.append((x, w, name))
        last_x = x

    return stations_sorted
```

注意：如果 Claude Code 认为上面的 station 逻辑可能产生重复 x，可以改成更明确的分段比例法。

更稳的比例法如下：

```python
def _fir_tree_stage_stations(params: dict) -> list[tuple[float, float, str]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    widths = _slot_widths(params)

    stage_count = _get_int(params, "rim_slot_stage_count", 3)
    stage_growth = _get_float(params, "rim_slot_stage_width_growth", 0.08)

    x0 = r_outer + outer_clearance
    x1 = r_outer
    x2 = r_outer - depth * 0.12
    x3 = r_outer - depth * 0.22
    x_root = r_outer - depth

    stations = [
        (x0, widths["mouth"], "outer_clearance_mouth"),
        (x1, widths["mouth"], "outer_radius_mouth"),
        (x2, widths["mouth"], "mouth_end"),
        (x3, widths["throat"], "initial_throat"),
    ]

    usable_start = x3
    usable_end = x_root
    usable_depth = usable_start - usable_end

    for i in range(stage_count):
        base_t = (i + 1) / (stage_count + 1)

        neck_in_t = base_t - 0.10 / (stage_count + 1)
        lobe_t = base_t
        neck_out_t = base_t + 0.10 / (stage_count + 1)

        lobe_w = widths["stage_lobe"] * (1.0 + stage_growth * i)

        stations.append(
            (usable_start - usable_depth * neck_in_t, widths["stage_neck"], f"stage_{i + 1}_neck_in")
        )
        stations.append(
            (usable_start - usable_depth * lobe_t, lobe_w, f"stage_{i + 1}_lobe")
        )
        stations.append(
            (usable_start - usable_depth * neck_out_t, widths["stage_neck"], f"stage_{i + 1}_neck_out")
        )

    stations.append((x_root, widths["root"], "root"))

    return stations
```

推荐使用第二个比例法，更稳定。

## 5.5 根据 stations 生成镜像 polygon

```python
def _symmetric_slot_profile_from_stations(
    stations: list[tuple[float, float, str]]
) -> list[tuple[float, float]]:
    # Left side: y negative, from outer to inner.
    left = [
        (float(x), -float(width) / 2.0)
        for x, width, _name in stations
    ]

    # Right side: y positive, from inner back to outer.
    right = [
        (float(x), float(width) / 2.0)
        for x, width, _name in reversed(stations)
    ]

    return left + right
```

这一步是保证左右对称的关键。

## 5.6 v0.5 fir-tree profile

```python
def _fir_tree_symmetric_multistage_profile_xy(params: dict) -> tuple[list[tuple[float, float]], list[dict]]:
    stations = _fir_tree_stage_stations(params)
    profile = _symmetric_slot_profile_from_stations(stations)

    station_metadata = [
        {
            "x_mm": float(x),
            "width_mm": float(width),
            "half_width_mm": float(width) / 2.0,
            "name": name,
        }
        for x, width, name in stations
    ]

    return profile, station_metadata
```

## 5.7 Symmetry assertion

新增：

```python
def _assert_profile_mirror_y(profile: list[tuple[float, float]], tol: float = 1e-6) -> None:
    if len(profile) % 2 != 0:
        raise ValueError("Symmetric slot profile must have an even number of points")

    n = len(profile) // 2
    left = profile[:n]
    right = list(reversed(profile[n:]))

    if len(left) != len(right):
        raise ValueError("Symmetric slot profile left/right point count mismatch")

    for (xl, yl), (xr, yr) in zip(left, right):
        if abs(xl - xr) > tol:
            raise ValueError(
                f"Slot profile is not mirror-symmetric in x: left x={xl}, right x={xr}"
            )
        if abs(yl + yr) > tol:
            raise ValueError(
                f"Slot profile is not mirror-symmetric in y: left y={yl}, right y={yr}"
            )
```

`_make_axial_through_slot_cutter()` 必须调用它：

```python
profile, station_metadata = _fir_tree_symmetric_multistage_profile_xy(params)
_assert_profile_mirror_y(profile)
```

## 5.8 Axial-through cutter

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

    if height <= 0:
        raise ValueError("axial-through slot cutter has non-positive height")

    if style == "rectangular":
        profile = _rectangular_socket_profile_xy(params)
        station_metadata = []
    elif style == "dovetail":
        profile = _dovetail_socket_profile_xy(params)
        station_metadata = []
    elif style == "fir_tree_like":
        profile, station_metadata = _fir_tree_symmetric_multistage_profile_xy(params)
        _assert_profile_mirror_y(profile)
    else:
        raise ValueError(f"Unsupported rim_slot_style: {style!r}")

    cutter = (
        cq.Workplane("XY")
        .polyline(profile)
        .close()
        .extrude(height)
        .translate((0.0, 0.0, z_min))
    )

    outer_radius = _get_float(params, "outer_dia_mm") / 2.0
    max_x = max(x for x, _ in profile)
    min_x = min(x for x, _ in profile)
    max_abs_y = max(abs(y) for _, y in profile)

    if max_x <= outer_radius:
        raise ValueError("slot cutter profile must extend beyond outer_radius")

    if min_x >= outer_radius:
        raise ValueError("slot cutter profile must cut inward from outer_radius")

    return cutter, {
        "profile_points_xy": [[float(x), float(y)] for x, y in profile],
        "stage_stations": station_metadata,
        "profile_symmetry": "mirror_y",
        "is_mirror_symmetric": True,
        "stage_count": _get_int(params, "rim_slot_stage_count", 0),
        "z_min_mm": float(z_min),
        "z_max_mm": float(z_max),
        "height_mm": float(height),
        "max_x_mm": float(max_x),
        "min_x_mm": float(min_x),
        "outer_radius_mm": float(outer_radius),
        "max_abs_y_mm": float(max_abs_y),
    }
```

---

# 6. `_cut_rim_slots()` v0.5

```python
def _cut_rim_slots(cq, result, params: dict, axial_zones: dict):
    count = _get_int(params, "rim_slot_count", 0)
    style = _get_str(params, "rim_slot_style", "none")
    orientation = _get_str(params, "rim_slot_orientation", "axial_through")
    socket_mode = _get_str(params, "rim_slot_socket_mode", "internal_lobes")

    if count <= 0 or style == "none":
        return result, {
            "enabled": False,
            "slot_count": 0,
            "slot_style": style,
            "slot_orientation": orientation,
            "socket_mode": socket_mode,
            "profile_points_xy": [],
            "stage_stations": [],
            "profile_symmetry": "mirror_y",
            "is_mirror_symmetric": True,
            "stage_count": 0,
            "opens_front_face": False,
            "opens_back_face": False,
            "opens_outer_diameter": False,
            "exposes_lobes_on_od": False,
            "reference_only": True,
        }

    if orientation != "axial_through":
        raise ValueError(
            "v0.5 turbine disk fir-tree slots require rim_slot_orientation='axial_through'"
        )

    if style == "fir_tree_like" and socket_mode != "internal_lobes":
        raise ValueError(
            "v0.5 fir_tree_like slots require rim_slot_socket_mode='internal_lobes'"
        )

    rim_z_min = float(axial_zones["rim_z_min_mm"])
    rim_z_max = float(axial_zones["rim_z_max_mm"])

    cutter, cutter_md = _make_axial_through_slot_cutter(
        cq,
        params,
        rim_z_min=rim_z_min,
        rim_z_max=rim_z_max,
    )

    for i in range(count):
        angle = 360.0 * i / count
        rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
        result = result.cut(rotated)

    slot_metadata = {
        "enabled": True,
        "slot_count": int(count),
        "slot_style": style,
        "slot_orientation": orientation,
        "socket_mode": socket_mode,

        "profile_points_xy": cutter_md["profile_points_xy"],
        "stage_stations": cutter_md["stage_stations"],
        "profile_symmetry": cutter_md["profile_symmetry"],
        "is_mirror_symmetric": cutter_md["is_mirror_symmetric"],
        "stage_count": cutter_md["stage_count"],

        "z_min_mm": cutter_md["z_min_mm"],
        "z_max_mm": cutter_md["z_max_mm"],
        "height_mm": cutter_md["height_mm"],
        "max_x_mm": cutter_md["max_x_mm"],
        "min_x_mm": cutter_md["min_x_mm"],
        "outer_radius_mm": cutter_md["outer_radius_mm"],
        "max_abs_y_mm": cutter_md["max_abs_y_mm"],

        "rim_z_min_mm": rim_z_min,
        "rim_z_max_mm": rim_z_max,

        "opens_front_face": True,
        "opens_back_face": True,
        "opens_outer_diameter": True,

        "exposes_lobes_on_od": False,
        "reference_only": True,
    }

    return result, slot_metadata
```

注意：

```text
1. 不允许 catch Boolean cut 异常后继续；
2. 如果 cut 失败，build 必须 fail；
3. slot 是核心 feature，不能静默退化。
```

---

# 7. Metadata v0.5

## 7.1 metadata 主字段

`_build_metadata()` 必须写：

```python
"kernel": "cadquery_turbine_disk_reference_v5",
"geometry_family": "axisymmetric_base_with_symmetric_multistage_fir_tree_slots",
```

## 7.2 slot_generation

```python
"slot_generation": {
    "version": "rim_slot_v5_symmetric_multistage",
    "orientation": slot_metadata["slot_orientation"],
    "socket_mode": slot_metadata["socket_mode"],

    "profile_symmetry": slot_metadata["profile_symmetry"],
    "is_mirror_symmetric": slot_metadata["is_mirror_symmetric"],
    "stage_count": slot_metadata["stage_count"],
    "stage_stations": slot_metadata["stage_stations"],

    "opens_front_face": True,
    "opens_back_face": True,
    "opens_outer_diameter": True,

    "exposes_lobes_on_od": False,

    "z_min_mm": slot_metadata["z_min_mm"],
    "z_max_mm": slot_metadata["z_max_mm"],
    "rim_z_min_mm": slot_metadata["rim_z_min_mm"],
    "rim_z_max_mm": slot_metadata["rim_z_max_mm"],

    "profile_max_x_mm": slot_metadata["max_x_mm"],
    "profile_min_x_mm": slot_metadata["min_x_mm"],
    "outer_radius_mm": slot_metadata["outer_radius_mm"],
    "profile_max_abs_y_mm": slot_metadata["max_abs_y_mm"],
}
```

## 7.3 rim_features

```python
"rim_features": {
    "slot_count": _get_int(params, "rim_slot_count", 0),
    "slot_style": _get_str(params, "rim_slot_style", "none"),
    "slot_orientation": _get_str(params, "rim_slot_orientation", "axial_through"),
    "socket_mode": _get_str(params, "rim_slot_socket_mode", "internal_lobes"),

    "stage_count": _get_int(params, "rim_slot_stage_count", 0),
    "mouth_width_mm": _get_float(params, "rim_slot_mouth_width_mm", _get_float(params, "rim_slot_width_mm", 0.0)),
    "throat_width_mm": _get_float(params, "rim_slot_throat_width_mm", _get_float(params, "rim_slot_neck_width_mm", 0.0)),
    "stage_neck_width_mm": _get_float(params, "rim_slot_stage_neck_width_mm", 0.0),
    "stage_lobe_width_mm": _get_float(params, "rim_slot_stage_lobe_width_mm", _get_float(params, "rim_slot_lobe_width_mm", 0.0)),
    "root_width_mm": _get_float(params, "rim_slot_root_width_mm", 0.0),

    "slot_profile_points_xy": slot_metadata["profile_points_xy"],
    "stage_stations": slot_metadata["stage_stations"],

    "reference_only": True,
}
```

## 7.4 visual_fidelity

```python
"visual_fidelity": {
    "target": "reference_turbine_rotor_disk",
    "contains_cyclic_rim_slots": _get_int(params, "rim_slot_count", 0) > 0,
    "contains_axial_through_rim_slots": True,
    "contains_symmetric_fir_tree_slots": True,
    "contains_multistage_sidewall_grooves": True,
    "contains_internal_lobe_socket_slots": True,
    "contains_real_blade_attachment": False,
    "contains_hub_sleeve": ...,
    "contains_annular_details": ...,
    "contains_coverplate_interface": ...,
}
```

## 7.5 safety

```python
"safety": {
    "non_flight_reference_only": True,
    "not_for_manufacturing": True,
    "not_airworthy": True,
    "not_certified": True,
    "not_for_installation": True,
    "no_structural_validation": True,
    "no_life_prediction": True,
    "no_rotordynamic_validation": True,
}
```

---

# 8. Reference dimensions v0.5

`_reference_dimensions()` 必须新增：

```python
"rim_slot_stage_count": _get_int(params, "rim_slot_stage_count", 0),
"rim_slot_profile_symmetry": _get_str(params, "rim_slot_profile_symmetry", "mirror_y"),
"rim_slot_is_mirror_symmetric": slot_metadata["is_mirror_symmetric"],

"rim_slot_mouth_width_mm": ...,
"rim_slot_throat_width_mm": ...,
"rim_slot_stage_neck_width_mm": ...,
"rim_slot_stage_lobe_width_mm": ...,
"rim_slot_root_width_mm": ...,

"rim_slot_exposes_lobes_on_od": False,
"rim_slot_profile_max_x_mm": slot_metadata["max_x_mm"],
"rim_slot_profile_min_x_mm": slot_metadata["min_x_mm"],
"rim_slot_profile_max_abs_y_mm": slot_metadata["max_abs_y_mm"],

"expected_periodic_slot_count": rim_slot_count,
"expected_fir_tree_stage_count": rim_slot_stage_count,
```

---

# 9. Metadata validator v0.5

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
```

必须检查：

```text
1. geometry_family == axisymmetric_base_with_symmetric_multistage_fir_tree_slots；
2. slot_generation.version == rim_slot_v5_symmetric_multistage；
3. slot_generation.profile_symmetry == mirror_y；
4. slot_generation.is_mirror_symmetric is True；
5. slot_generation.stage_count >= 2；
6. slot_generation.stage_stations 是 list 且长度 >= stage_count * 3；
7. opens_front_face/back_face/outer_diameter 全 True；
8. exposes_lobes_on_od is False；
9. z_min < rim_z_min；
10. z_max > rim_z_max；
11. profile_max_x > outer_radius；
12. profile_min_x < outer_radius；
13. rim_features.reference_only is True；
14. rim_features.slot_profile_points_xy 非空；
15. visual_fidelity.contains_symmetric_fir_tree_slots is True；
16. visual_fidelity.contains_multistage_sidewall_grooves is True；
17. visual_fidelity.contains_real_blade_attachment is False；
18. safety.not_for_installation is True；
19. safety.no_structural_validation is True；
20. safety.no_life_prediction is True。
```

核心代码示例：

```python
slot = metadata.get("slot_generation") or {}

if slot.get("version") != "rim_slot_v5_symmetric_multistage":
    errors.append("slot_generation.version must be rim_slot_v5_symmetric_multistage")

if slot.get("profile_symmetry") != "mirror_y":
    errors.append("slot_generation.profile_symmetry must be mirror_y")

if slot.get("is_mirror_symmetric") is not True:
    errors.append("slot_generation.is_mirror_symmetric must be True")

if int(slot.get("stage_count", 0)) < 2:
    errors.append("slot_generation.stage_count must be >= 2")

if slot.get("exposes_lobes_on_od") is not False:
    errors.append("slot_generation.exposes_lobes_on_od must be False")
```

---

# 10. Mechanical validation v0.5

修改：

```text
src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
```

## 10.1 常量

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v5"

ALLOWED_KERNELS = {
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
    "cadquery_turbine_disk_reference_v3",
    "cadquery_turbine_disk_reference_v4",
    "cadquery_turbine_disk_reference_v5",
}
```

demo expected kernel 必须是 v5。

## 10.2 新增 mechanical checks

必须检查：

```text
1. expected_kernel mismatch fail；
2. geometry_family mismatch fail；
3. slot_generation.version != rim_slot_v5_symmetric_multistage fail；
4. profile_symmetry != mirror_y fail；
5. is_mirror_symmetric is not True fail；
6. stage_count < 2 fail；
7. stage_count mismatch fail；
8. exposes_lobes_on_od is not False fail；
9. opens_front/back/outer 任一不是 True fail；
10. z_min >= rim_z_min fail；
11. z_max <= rim_z_max fail；
12. profile_max_x <= outer_radius fail；
13. profile_min_x >= outer_radius fail；
14. mouth_width >= stage_lobe_width fail；
15. throat_width >= stage_lobe_width fail；
16. visual_fidelity.contains_symmetric_fir_tree_slots is not True fail；
17. visual_fidelity.contains_multistage_sidewall_grooves is not True fail；
18. visual_fidelity.contains_real_blade_attachment is not False fail；
19. safety.not_for_installation / no_structural_validation / no_life_prediction 缺失 fail。
```

---

# 11. Primitive compiler

修改：

```text
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

保持 dispatcher 模式。编译脚本只允许出现：

```python
build_axisymmetric_turbine_disk_cadquery(_params)
```

禁止 compiler script 中出现：

```text
_fir_tree_symmetric_multistage_profile_xy
_fir_tree_stage_stations
_symmetric_slot_profile_from_stations
Workplane("XY").polyline
result.cut(rotated)
```

新增测试必须检查这些字符串不存在。

---

# 12. Demo 更新

修改：

```text
demo_full_chain.py
```

参数必须加入：

```python
"rim_slot_style": "fir_tree_like",
"rim_slot_orientation": "axial_through",
"rim_slot_socket_mode": "internal_lobes",
"rim_slot_expose_lobes_on_od": False,

"rim_slot_stage_count": 3,
"rim_slot_stage_pitch_mm": 7.0,
"rim_slot_stage_neck_width_mm": 4.6,
"rim_slot_stage_lobe_width_mm": 9.0,
"rim_slot_stage_lobe_height_mm": 2.1,
"rim_slot_stage_width_growth": 0.08,
"rim_slot_stage_depth_distribution": "uniform",

"rim_slot_mouth_width_mm": 5.2,
"rim_slot_throat_width_mm": 4.6,
"rim_slot_root_width_mm": 5.4,

"rim_slot_profile_symmetry": "mirror_y",
"rim_slot_require_multiple_stages": True,
```

primitive validation：

```python
"primitive_validation": {
    "primitive1": {
        "expected_kernel": "cadquery_turbine_disk_reference_v5",
        "expected_periodic_slot_count": 60,
        "expected_slot_orientation": "axial_through",
        "expected_slot_socket_mode": "internal_lobes",
        "expected_fir_tree_stage_count": 3,
        "expected_profile_symmetry": "mirror_y",
        "expected_lobes_exposed_on_od": False,
    }
}
```

required metrics 增加：

```text
reference_dimensions.rim_slot_stage_count
reference_dimensions.rim_slot_profile_symmetry
reference_dimensions.rim_slot_is_mirror_symmetric
reference_dimensions.rim_slot_mouth_width_mm
reference_dimensions.rim_slot_throat_width_mm
reference_dimensions.rim_slot_stage_neck_width_mm
reference_dimensions.rim_slot_stage_lobe_width_mm
reference_dimensions.rim_slot_root_width_mm
reference_dimensions.rim_slot_exposes_lobes_on_od
reference_dimensions.expected_fir_tree_stage_count
```

---

# 13. 测试计划

## 13.1 参数测试

文件：

```text
tests/test_axisymmetric_turbine_disk_parameters.py
```

新增：

```text
1. v5 fir_tree_like mirror_y multistage happy path；
2. rim_slot_stage_count < 2 fail；
3. rim_slot_profile_symmetry != mirror_y fail；
4. rim_slot_expose_lobes_on_od=True fail；
5. mouth_width >= stage_lobe_width fail；
6. throat_width >= stage_lobe_width fail；
7. stage_lobe_width <= stage_neck_width fail；
8. stage_count * stage_pitch 太大 fail；
9. slot pitch <= max_lobe_width * 1.25 fail；
10. axial_through + axial_margin > 0 fail。
```

## 13.2 Kernel visual tests

文件：

```text
tests/test_turbine_disk_visual_features.py
```

新增：

```python
def test_v5_profile_is_mirror_symmetric():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v5_params())
    slot = md["slot_generation"]

    assert slot["profile_symmetry"] == "mirror_y"
    assert slot["is_mirror_symmetric"] is True


def test_v5_profile_has_multiple_stages():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v5_params())
    slot = md["slot_generation"]

    assert slot["stage_count"] >= 3
    assert len(slot["stage_stations"]) >= slot["stage_count"] * 3


def test_v5_profile_has_narrow_mouth_and_wider_lobes():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v5_params())
    rim = md["rim_features"]

    assert rim["mouth_width_mm"] < rim["stage_lobe_width_mm"]
    assert rim["throat_width_mm"] < rim["stage_lobe_width_mm"]


def test_v5_does_not_expose_lobes_on_od():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v5_params())
    slot = md["slot_generation"]

    assert slot["exposes_lobes_on_od"] is False
```

## 13.3 Metadata tests

新增：

```text
1. slot_generation.version == rim_slot_v5_symmetric_multistage；
2. is_mirror_symmetric=False fail；
3. stage_count < 2 fail；
4. exposes_lobes_on_od=True fail；
5. contains_symmetric_fir_tree_slots 缺失 fail；
6. contains_multistage_sidewall_grooves 缺失 fail。
```

## 13.4 Mechanical validation tests

新增：

```text
1. v5 happy path ok；
2. expected_kernel mismatch fail；
3. profile symmetry mismatch fail；
4. stage_count mismatch fail；
5. exposes_lobes_on_od=True fail；
6. mouth_width >= lobe_width fail；
7. contains_real_blade_attachment=True fail。
```

## 13.5 Compiler tests

新增：

```text
1. compiler 只调用 build_axisymmetric_turbine_disk_cadquery；
2. compiler 不包含 profile generator 内部函数；
3. compiler 不包含 Workplane("XY").polyline；
4. compiler 不包含 result.cut(rotated)。
```

---

# 14. 验收命令

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

---

# 15. SolidWorks 视觉验收标准

生成结果必须满足：

```text
1. 单个榫槽左右对称；
2. 单个榫槽有至少 2 级卡槽，demo 至少 3 级；
3. 两侧壁均有对应卡槽，不是单边锯齿；
4. 外圆入口窄；
5. 内部 lobe 比入口宽；
6. 前后端面可见对称多级 fir-tree-like 截面；
7. 外圆侧壁不再是不规则横向台阶块；
8. 相邻榫槽之间形成稳定 disk posts；
9. 不再像 box union 拼出来的破碎多边形；
10. metadata 与 mechanical validation 全部通过。
```

---

# 16. Definition of Done

只有满足以下全部条件才算完成：

```text
1. KERNEL_NAME = cadquery_turbine_disk_reference_v5。
2. GEOMETRY_FAMILY = axisymmetric_base_with_symmetric_multistage_fir_tree_slots。
3. models.py 注册 v5 参数。
4. validator 要求 mirror_y。
5. validator 要求 stage_count >= 2。
6. validator 要求 mouth_width < lobe_width。
7. validator 要求 throat_width < lobe_width。
8. validator 拒绝 expose_lobes_on_od=True。
9. fir_tree_like 使用 symmetric polygon profile。
10. 不再用多个 box union 作为 fir_tree_like 主实现。
11. profile 左右镜像对称。
12. profile 有多个 stage stations。
13. metadata.slot_generation.version = rim_slot_v5_symmetric_multistage。
14. metadata.slot_generation.is_mirror_symmetric=True。
15. metadata.slot_generation.stage_count >= 2。
16. metadata.slot_generation.exposes_lobes_on_od=False。
17. visual_fidelity.contains_symmetric_fir_tree_slots=True。
18. visual_fidelity.contains_multistage_sidewall_grooves=True。
19. visual_fidelity.contains_real_blade_attachment=False。
20. mechanical validation 强制 demo expected_kernel=v5。
21. demo overall_ok=True。
22. compiler 仍只 dispatch deterministic kernel。
23. SolidWorks 中单个卡榫/榫槽左右对称。
24. SolidWorks 中每个榫槽有多个对称卡槽。
25. 现有 gear primitive 不被破坏。
26. 现有 recipe cases 不被破坏。
27. 所有新增测试通过。
```

---

# 17. 可直接交给 Claude Code 的最终 Prompt

```text
你现在在 seekflow-engineering 仓库中工作，重点目录：

integrations/engineering_tools/

用户最新反馈：axisymmetric_turbine_disk 的卡榫/榫槽仍然不对。真实卡榫图中，每个榫槽有多个卡槽，而且左右对称；当前生成结果明显不对称，也没有多个成对卡槽，看起来像 box cutter 拼出的不规则单侧锯齿。请将 fir_tree_like rim slot 修复为“左右镜像对称、多级 fir-tree socket profile”。

最高约束：
1. primitive_name 保持 axisymmetric_turbine_disk。
2. KERNEL_NAME 升级为 cadquery_turbine_disk_reference_v5。
3. GEOMETRY_FAMILY 使用 axisymmetric_base_with_symmetric_multistage_fir_tree_slots。
4. 不允许声称 flight-ready / airworthy / certified / manufacturing-ready / installable。
5. 不允许做真实航空发动机强度、寿命、材料、转速、适航设计。
6. fir_tree_like slot 只能是 visual/reference geometry。
7. primitive_compiler 只调用 deterministic kernel，不内联几何。
8. SolidWorks / NX 只能 import canonical STEP。
9. 所有失败必须 fail-closed。
10. 不得破坏 involute_spur_gear 和 recipe cases。

必须修改：
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
- src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
- src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
- src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
- demo_full_chain.py

新增/更新测试：
- tests/test_axisymmetric_turbine_disk_parameters.py
- tests/test_axisymmetric_turbine_disk_compiler.py
- tests/test_axisymmetric_turbine_disk_metadata.py
- tests/test_axisymmetric_turbine_disk_mechanical_validation.py
- tests/test_turbine_disk_visual_features.py
- tests/test_demo_full_chain_turbine_disk.py

第一步：models.py
新增参数：
rim_slot_stage_count
rim_slot_stage_pitch_mm
rim_slot_stage_neck_width_mm
rim_slot_stage_lobe_width_mm
rim_slot_stage_lobe_height_mm
rim_slot_stage_width_growth
rim_slot_stage_depth_distribution
rim_slot_mouth_width_mm
rim_slot_throat_width_mm
rim_slot_root_width_mm
rim_slot_profile_symmetry
rim_slot_require_multiple_stages

默认：
rim_slot_stage_count = 3
rim_slot_stage_pitch_mm = 7.0
rim_slot_stage_neck_width_mm = 4.6
rim_slot_stage_lobe_width_mm = 9.0
rim_slot_stage_lobe_height_mm = 2.1
rim_slot_stage_width_growth = 0.08
rim_slot_stage_depth_distribution = "uniform"
rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.6
rim_slot_root_width_mm = 5.4
rim_slot_profile_symmetry = "mirror_y"
rim_slot_require_multiple_stages = True
rim_slot_expose_lobes_on_od = False

supported_kernels 加入 cadquery_turbine_disk_reference_v5。

第二步：validator.py
新增：
ALLOWED_RIM_SLOT_PROFILE_SYMMETRIES = {"mirror_y"}
ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS = {"uniform", "progressive"}

_validate_rim_slots 必须检查：
- profile_symmetry == "mirror_y"；
- stage_distribution 合法；
- fir_tree_like 时 stage_count >= 2；
- require_multiple_stages=True 时 stage_count >= 2；
- stage_pitch > 0；
- stage_neck_width > 0；
- stage_lobe_width > stage_neck_width；
- stage_lobe_height > 0；
- stage_growth >= 0；
- mouth_width < stage_lobe_width；
- throat_width < stage_lobe_width；
- root_width <= stage_lobe_width；
- rim_slot_expose_lobes_on_od is False；
- stage_count * stage_pitch < rim_slot_depth_mm * 0.85；
- circumferential pitch > max_stage_lobe_width * 1.25；
- axial_through + axial_margin == 0。

第三步：axisymmetric_turbine_disk.py
设置：
KERNEL_NAME = "cadquery_turbine_disk_reference_v5"
GEOMETRY_FAMILY = "axisymmetric_base_with_symmetric_multistage_fir_tree_slots"

禁止继续用多个 box union 作为 fir_tree_like 主实现。

实现：
_slot_widths(params)
_fir_tree_stage_stations(params)
_symmetric_slot_profile_from_stations(stations)
_fir_tree_symmetric_multistage_profile_xy(params)
_assert_profile_mirror_y(profile)
_make_axial_through_slot_cutter(...)

核心要求：
- stations 是 (x, width, name)；
- profile 左侧使用 y=-width/2；
- profile 右侧使用 y=+width/2，并反向镜像；
- _assert_profile_mirror_y 必须验证左右点数、x 相等、y 相反；
- stage_count 至少 2，demo 3；
- profile 外口 mouth 窄；
- 内部 lobe 宽；
- 每一级 lobe 左右成对；
- profile max_x > outer_radius；
- profile min_x < outer_radius；
- cutter z_min < rim_z_min；
- cutter z_max > rim_z_max；
- cut 失败不能吞异常。

第四步：metadata
metadata 必须包含：
kernel = cadquery_turbine_disk_reference_v5
geometry_family = axisymmetric_base_with_symmetric_multistage_fir_tree_slots

slot_generation:
version = rim_slot_v5_symmetric_multistage
profile_symmetry = mirror_y
is_mirror_symmetric = True
stage_count
stage_stations
opens_front_face = True
opens_back_face = True
opens_outer_diameter = True
exposes_lobes_on_od = False

rim_features:
stage_count
mouth_width_mm
throat_width_mm
stage_neck_width_mm
stage_lobe_width_mm
root_width_mm
slot_profile_points_xy
stage_stations
reference_only = True

visual_fidelity:
contains_symmetric_fir_tree_slots = True
contains_multistage_sidewall_grooves = True
contains_real_blade_attachment = False

safety:
not_for_installation = True
no_structural_validation = True
no_life_prediction = True

第五步：metadata.py
validate_axisymmetric_turbine_disk_metadata 必须检查：
- geometry_family 正确；
- slot_generation.version == rim_slot_v5_symmetric_multistage；
- profile_symmetry == mirror_y；
- is_mirror_symmetric is True；
- stage_count >= 2；
- stage_stations 长度合理；
- exposes_lobes_on_od is False；
- opens_front/back/outer 全 True；
- profile_max_x > outer_radius；
- profile_min_x < outer_radius；
- contains_symmetric_fir_tree_slots=True；
- contains_multistage_sidewall_grooves=True；
- contains_real_blade_attachment=False；
- safety flags 全 True。

第六步：turbomachinery_validation.py
KERNEL_NAME = cadquery_turbine_disk_reference_v5。
ALLOWED_KERNELS 加入 v5。
demo expected_kernel 必须强制 v5。

mechanical validation 必须检查：
- expected_kernel mismatch fail；
- profile_symmetry != mirror_y fail；
- is_mirror_symmetric is not True fail；
- stage_count < 2 fail；
- exposes_lobes_on_od=True fail；
- mouth_width >= stage_lobe_width fail；
- throat_width >= stage_lobe_width fail；
- contains_symmetric_fir_tree_slots 不是 True fail；
- contains_multistage_sidewall_grooves 不是 True fail；
- contains_real_blade_attachment 不是 False fail。

第七步：demo_full_chain.py
加入参数：
rim_slot_stage_count = 3
rim_slot_stage_pitch_mm = 7.0
rim_slot_stage_neck_width_mm = 4.6
rim_slot_stage_lobe_width_mm = 9.0
rim_slot_stage_lobe_height_mm = 2.1
rim_slot_stage_width_growth = 0.08
rim_slot_stage_depth_distribution = "uniform"
rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.6
rim_slot_root_width_mm = 5.4
rim_slot_profile_symmetry = "mirror_y"
rim_slot_require_multiple_stages = True
rim_slot_expose_lobes_on_od = False

primitive_validation.expected_kernel = cadquery_turbine_disk_reference_v5。

required_metrics 加入：
reference_dimensions.rim_slot_stage_count
reference_dimensions.rim_slot_profile_symmetry
reference_dimensions.rim_slot_is_mirror_symmetric
reference_dimensions.rim_slot_mouth_width_mm
reference_dimensions.rim_slot_throat_width_mm
reference_dimensions.rim_slot_stage_neck_width_mm
reference_dimensions.rim_slot_stage_lobe_width_mm
reference_dimensions.rim_slot_root_width_mm
reference_dimensions.rim_slot_exposes_lobes_on_od
reference_dimensions.expected_fir_tree_stage_count

第八步：primitive_compiler.py
保持 dispatcher。compiler 脚本不能包含：
_fir_tree_symmetric_multistage_profile_xy
_fir_tree_stage_stations
_symmetric_slot_profile_from_stations
Workplane("XY").polyline
result.cut(rotated)

第九步：测试
新增/更新：
1. v5 happy path；
2. stage_count < 2 fail；
3. profile_symmetry != mirror_y fail；
4. expose_lobes_on_od=True fail；
5. mouth_width >= lobe_width fail；
6. throat_width >= lobe_width fail；
7. profile mirror symmetry test；
8. stage_count >= 3 in demo；
9. contains_symmetric_fir_tree_slots=True；
10. contains_multistage_sidewall_grooves=True；
11. contains_real_blade_attachment=False；
12. compiler only dispatches to kernel；
13. demo expected_kernel=v5。

运行：
cd integrations/engineering_tools
python -m pytest tests -q
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery

完成后输出：
1. 修改文件清单；
2. v5 参数清单；
3. symmetric multistage fir-tree profile 说明；
4. metadata v5 字段说明；
5. 测试结果；
6. demo 结果；
7. 如果 SolidWorks 中单个卡榫仍不对称或没有多个卡槽，不得声称完成，必须说明原因。
```
