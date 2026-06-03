我看完当前可访问的 `main` 代码和你这张局部图后，结论很明确：**这些奇怪的线和卡槽突出部附近的小三角洞，大概率不是 SolidWorks 显示问题，而是 Boolean cutter 本身的拓扑质量很差导致的。**当前公开代码里 `axisymmetric_turbine_disk.py` 仍是 `cadquery_turbine_disk_reference_v2`，`fir_tree_like` 卡槽是由多个 box cutter union 拼出来，再旋转阵列切削；这会把 box 的内部拼接边、共面边、细小重叠边一起传递到被切后的实体上，所以 SolidWorks 里会出现大量额外边线、碎面、三角形 sliver face，严重时就会像你图里那样在突出部附近出现小三角孔。([GitHub][1])

真实 fir-tree / fir-tree blade root 并不是这种“多个矩形盒子堆出来的台阶槽”。公开资料对 fir-tree 的描述是 multilobed feature；相关专利也提到 fir-tree 型叶根轮廓通常由位于中心线两侧的对称曲面/轮廓组成。也就是说，你要的是**左右镜像、连续、多级、每级成对的 socket profile**，不是现在这种不连续 box union cutter。([ScienceDirect][2])

下面这份可以直接交给 Claude Code。它重点解决三件事：**奇怪线、三角洞、卡槽不像真实卡榫**。

---

# 给 Claude Code 的修复文档：`axisymmetric_turbine_disk` 榫槽拓扑清洁版 v0.6

## 1. 当前问题复盘

用户最新截图显示，涡轮盘外缘 fir-tree-like 卡槽附近出现：

```text
1. 大量奇怪的细线；
2. 卡槽台阶/突出部附近出现三角形小洞；
3. 单个卡槽轮廓不干净；
4. 卡槽形状仍然不像真实 fir-tree / dovetail socket；
5. 卡槽两侧不够对称；
6. 多级卡槽没有形成连续、成对、干净的齿形；
7. 外缘局部出现像碎面、裂缝、三角 sliver face 的形态。
```

这不是单纯参数问题，而是当前 cutter 构造方式的问题。

当前代码中的关键错误是：

```python
pieces = []
pieces.append(_make_box(...))  # mouth
pieces.append(_make_box(...))  # neck
pieces.append(_make_box(...))  # first lobe
pieces.append(_make_box(...))  # second pocket
pieces.append(_make_box(...))  # root pocket

cutter = pieces[0]
for piece in pieces[1:]:
    cutter = cutter.union(piece)
```

这种 `多个 box union -> 再 cut` 的做法会带来典型问题：

```text
1. 每个 box 都有自己的面和边；
2. union 后内部 seam 可能没有完全消失；
3. 多个 box 之间存在共面、共边、近重叠；
4. cutter 与圆柱外壁/前后端面相交时会产生很薄的 sliver face；
5. 旋转阵列 cut 后，这些小问题被复制 60 次；
6. SolidWorks 导入 STEP 后显示出大量额外分割边；
7. 在 lobe/neck 交界处容易出现三角形碎孔。
```

因此本轮必须彻底禁止：

```text
用多个 box union 作为 fir_tree_like 主 cutter。
```

---

## 2. 本轮修复目标

保持 primitive 名称不变：

```text
primitive_name = "axisymmetric_turbine_disk"
```

升级 kernel：

```text
KERNEL_NAME = "cadquery_turbine_disk_reference_v6"
```

升级 geometry family：

```text
GEOMETRY_FAMILY = "axisymmetric_base_with_clean_symmetric_fir_tree_slots"
```

核心目标：

```text
1. 使用单一闭合 polygon profile 生成 fir-tree socket cutter；
2. profile 必须左右镜像对称；
3. profile 必须由连续 station 生成；
4. 不允许多个 box union 拼接 fir-tree；
5. 不允许 profile 自交；
6. 不允许重复点、零长度边、极短边；
7. 不允许相邻 slots overlap；
8. cutter 必须沿 Z 方向贯穿 rim；
9. cutter 必须略微超出 outer_radius；
10. cut 后必须调用 clean；
11. metadata 必须记录 profile 拓扑质量；
12. mechanical validation 必须验证 profile 不是 box-union 拼接伪 fir-tree。
```

---

## 3. 安全与边界约束

继续保持：

```text
1. non-flight reference geometry only；
2. not airworthy；
3. not certified；
4. not manufacturing-ready；
5. not for installation；
6. no structural validation；
7. no life prediction；
8. no rotordynamic validation；
9. fir-tree-like slots are visual/reference geometry only；
10. not certified blade attachment geometry。
```

不得声称：

```text
flight-ready
airworthy
certified
manufacturing-ready
production-ready
installable
真实叶根连接
真实承载榫槽
真实适航结构
```

---

## 4. 需要修改的文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
integrations/engineering_tools/demo_full_chain.py
```

新增/更新测试：

```text
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_parameters.py
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_compiler.py
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_metadata.py
integrations/engineering_tools/tests/test_axisymmetric_turbine_disk_mechanical_validation.py
integrations/engineering_tools/tests/test_turbine_disk_visual_features.py
integrations/engineering_tools/tests/test_demo_full_chain_turbine_disk.py
```

---

# 5. `models.py` 参数升级

在 `AXISYMMETRIC_TURBINE_DISK.parameters` 中新增或确认以下参数。

## 5.1 v6 新参数

```text
rim_slot_generation_method
rim_slot_profile_kind
rim_slot_profile_symmetry
rim_slot_topology_mode

rim_slot_stage_count
rim_slot_stage_pitch_mm
rim_slot_stage_neck_width_mm
rim_slot_stage_lobe_width_mm
rim_slot_stage_lobe_height_mm
rim_slot_stage_width_growth

rim_slot_mouth_width_mm
rim_slot_throat_width_mm
rim_slot_root_width_mm

rim_slot_min_segment_length_mm
rim_slot_corner_relief_mm
rim_slot_profile_clean_tolerance_mm

rim_slot_expose_lobes_on_od
rim_slot_require_multiple_stages
rim_slot_reject_self_intersection
rim_slot_reject_duplicate_points
```

## 5.2 默认值

```python
rim_slot_generation_method = "single_clean_polygon"
rim_slot_profile_kind = "symmetric_multistage_fir_tree"
rim_slot_profile_symmetry = "mirror_y"
rim_slot_topology_mode = "clean_socket_cut"

rim_slot_stage_count = 3
rim_slot_stage_pitch_mm = 7.0
rim_slot_stage_neck_width_mm = 4.6
rim_slot_stage_lobe_width_mm = 9.0
rim_slot_stage_lobe_height_mm = 2.0
rim_slot_stage_width_growth = 0.06

rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.6
rim_slot_root_width_mm = 5.4

rim_slot_min_segment_length_mm = 0.35
rim_slot_corner_relief_mm = 0.25
rim_slot_profile_clean_tolerance_mm = 1e-6

rim_slot_expose_lobes_on_od = False
rim_slot_require_multiple_stages = True
rim_slot_reject_self_intersection = True
rim_slot_reject_duplicate_points = True
```

## 5.3 Kernel 注册

把 supported kernels 更新为：

```python
supported_kernels=[
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
    "cadquery_turbine_disk_reference_v6",
]
```

如果已有 v3/v4/v5，也可以保留，但 demo 必须强制 v6。

---

# 6. `validator.py` 必须新增的约束

新增允许值：

```python
ALLOWED_RIM_SLOT_GENERATION_METHODS = {
    "single_clean_polygon",
}

ALLOWED_RIM_SLOT_PROFILE_KINDS = {
    "symmetric_multistage_fir_tree",
    "symmetric_dovetail",
    "rectangular",
}

ALLOWED_RIM_SLOT_PROFILE_SYMMETRIES = {
    "mirror_y",
}

ALLOWED_RIM_SLOT_TOPOLOGY_MODES = {
    "clean_socket_cut",
}
```

在 `_validate_rim_slots()` 中加入强约束：

```python
generation_method = str(params.get("rim_slot_generation_method", "single_clean_polygon"))
profile_kind = str(params.get("rim_slot_profile_kind", "symmetric_multistage_fir_tree"))
profile_symmetry = str(params.get("rim_slot_profile_symmetry", "mirror_y"))
topology_mode = str(params.get("rim_slot_topology_mode", "clean_socket_cut"))

if generation_method != "single_clean_polygon":
    errors.append(
        "rim_slot_generation_method must be 'single_clean_polygon'; "
        "box-union fir-tree cutters are forbidden because they create sliver faces."
    )

if profile_symmetry != "mirror_y":
    errors.append("rim_slot_profile_symmetry must be 'mirror_y'.")

if topology_mode != "clean_socket_cut":
    errors.append("rim_slot_topology_mode must be 'clean_socket_cut'.")
```

继续检查：

```text
1. rim_slot_stage_count >= 2；
2. demo 推荐 >= 3；
3. mouth_width < lobe_width；
4. throat_width < lobe_width；
5. root_width <= lobe_width；
6. stage_neck_width < stage_lobe_width；
7. stage_count * stage_pitch < rim_slot_depth_mm * 0.85；
8. circumferential pitch > max_lobe_width * 1.35；
9. rim_slot_expose_lobes_on_od is False；
10. rim_slot_axial_margin_mm == 0 for axial_through；
11. rim_slot_through_clearance_mm > 0；
12. rim_slot_min_segment_length_mm > 0；
13. rim_slot_corner_relief_mm >= 0；
14. rim_slot_reject_self_intersection is True；
15. rim_slot_reject_duplicate_points is True。
```

关键错误提示必须明确：

```text
Box-union fir-tree cutters are forbidden.
Use a single clean mirror-symmetric polygon profile.
```

---

# 7. `axisymmetric_turbine_disk.py` 核心重写

设置：

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v6"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
GEOMETRY_FAMILY = "axisymmetric_base_with_clean_symmetric_fir_tree_slots"
```

## 7.1 必须删除或停用的旧逻辑

禁止继续使用：

```python
def _make_fir_tree_like_slot_cutter(...):
    pieces = []
    pieces.append(_make_box(...))
    ...
    cutter = pieces[0]
    for piece in pieces[1:]:
        cutter = cutter.union(piece)
```

可以保留 `_make_box()` 给 rectangular 简单槽使用，但：

```text
fir_tree_like 绝对不能走 box union。
```

## 7.2 新的 profile 生成逻辑

### 7.2.1 station 数据结构

使用 station 表示 profile：

```python
# (x, width, name)
stations = [
    (x0, width0, "outer_clearance_mouth"),
    (x1, width1, "outer_radius_mouth"),
    ...
]
```

其中：

```text
x 是径向坐标；
width 是该 station 的完整切向宽度；
左侧边界 y = -width/2；
右侧边界 y = +width/2。
```

### 7.2.2 station 生成

实现：

```python
def _fir_tree_stage_stations(params: dict) -> list[tuple[float, float, str]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    stage_count = _get_int(params, "rim_slot_stage_count", 3)
    stage_growth = _get_float(params, "rim_slot_stage_width_growth", 0.06)

    mouth_w = _get_float(params, "rim_slot_mouth_width_mm", _get_float(params, "rim_slot_width_mm", 5.2))
    throat_w = _get_float(params, "rim_slot_throat_width_mm", _get_float(params, "rim_slot_neck_width_mm", 4.6))
    root_w = _get_float(params, "rim_slot_root_width_mm", throat_w)
    neck_w = _get_float(params, "rim_slot_stage_neck_width_mm", throat_w)
    lobe_w0 = _get_float(params, "rim_slot_stage_lobe_width_mm", _get_float(params, "rim_slot_lobe_width_mm", 9.0))

    x_outer_clear = r_outer + outer_clearance
    x_outer = r_outer
    x_mouth_end = r_outer - depth * 0.10
    x_initial_throat = r_outer - depth * 0.20
    x_root = r_outer - depth

    stations: list[tuple[float, float, str]] = [
        (x_outer_clear, mouth_w, "outer_clearance_mouth"),
        (x_outer, mouth_w, "outer_radius_mouth"),
        (x_mouth_end, mouth_w, "mouth_end"),
        (x_initial_throat, throat_w, "initial_throat"),
    ]

    usable_start = x_initial_throat
    usable_end = x_root
    usable_depth = usable_start - usable_end

    for i in range(stage_count):
        center_t = (i + 1) / (stage_count + 1)

        neck_in_t = max(0.0, center_t - 0.12 / (stage_count + 1))
        lobe_t = center_t
        neck_out_t = min(1.0, center_t + 0.12 / (stage_count + 1))

        lobe_w = lobe_w0 * (1.0 + stage_growth * i)

        stations.append(
            (usable_start - usable_depth * neck_in_t, neck_w, f"stage_{i + 1}_neck_in")
        )
        stations.append(
            (usable_start - usable_depth * lobe_t, lobe_w, f"stage_{i + 1}_lobe")
        )
        stations.append(
            (usable_start - usable_depth * neck_out_t, neck_w, f"stage_{i + 1}_neck_out")
        )

    stations.append((x_root, root_w, "root"))

    return _normalize_and_validate_stations(stations, params)
```

## 7.3 station 清理与验证

实现：

```python
def _normalize_and_validate_stations(
    stations: list[tuple[float, float, str]],
    params: dict,
) -> list[tuple[float, float, str]]:
    min_seg = _get_float(params, "rim_slot_min_segment_length_mm", 0.35)

    clean: list[tuple[float, float, str]] = []

    for x, width, name in stations:
        x = float(x)
        width = float(width)

        if width <= 0:
            raise ValueError(f"Invalid slot station width at {name}: {width}")

        if clean:
            prev_x = clean[-1][0]
            if x >= prev_x:
                raise ValueError(
                    f"Slot station x must strictly decrease from OD inward. "
                    f"Station {name} has x={x}, previous x={prev_x}."
                )

            if abs(prev_x - x) < min_seg:
                raise ValueError(
                    f"Slot station segment too short near {name}: "
                    f"{abs(prev_x - x)} < {min_seg}"
                )

        clean.append((x, width, name))

    return clean
```

这一步非常重要，用于避免：

```text
1. 重复点；
2. 零长度边；
3. 极短边；
4. profile 自交；
5. 小三角碎面。
```

## 7.4 生成镜像 polygon

```python
def _symmetric_slot_profile_from_stations(
    stations: list[tuple[float, float, str]]
) -> list[tuple[float, float]]:
    left = [
        (float(x), -float(width) / 2.0)
        for x, width, _name in stations
    ]

    right = [
        (float(x), float(width) / 2.0)
        for x, width, _name in reversed(stations)
    ]

    return left + right
```

## 7.5 profile 验证

实现：

```python
def _assert_profile_mirror_y(profile: list[tuple[float, float]], tol: float = 1e-6) -> None:
    if len(profile) < 6:
        raise ValueError("Slot profile must have at least 6 points")

    if len(profile) % 2 != 0:
        raise ValueError("Mirror-symmetric slot profile must have even number of points")

    n = len(profile) // 2
    left = profile[:n]
    right = list(reversed(profile[n:]))

    for (xl, yl), (xr, yr) in zip(left, right):
        if abs(xl - xr) > tol:
            raise ValueError(f"Slot profile x mismatch: {xl} vs {xr}")
        if abs(yl + yr) > tol:
            raise ValueError(f"Slot profile y is not mirrored: {yl} vs {yr}")
```

再实现：

```python
def _assert_no_duplicate_or_short_edges(
    profile: list[tuple[float, float]],
    min_seg: float,
) -> None:
    closed = profile + [profile[0]]

    for i in range(len(closed) - 1):
        x1, y1 = closed[i]
        x2, y2 = closed[i + 1]

        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

        if length < min_seg:
            raise ValueError(
                f"Slot profile edge {i} is too short: {length} < {min_seg}"
            )
```

## 7.6 计算 polygon 面积，防止退化

```python
def _polygon_area(profile: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(profile)

    for i in range(n):
        x1, y1 = profile[i]
        x2, y2 = profile[(i + 1) % n]
        area += x1 * y2 - x2 * y1

    return abs(area) * 0.5
```

在生成 cutter 前检查：

```python
area = _polygon_area(profile)
if area <= 1e-6:
    raise ValueError("Slot profile polygon area is zero or degenerate")
```

## 7.7 fir-tree profile 主函数

```python
def _fir_tree_clean_symmetric_profile_xy(
    params: dict,
) -> tuple[list[tuple[float, float]], list[dict]]:
    stations = _fir_tree_stage_stations(params)
    profile = _symmetric_slot_profile_from_stations(stations)

    _assert_profile_mirror_y(profile)

    min_seg = _get_float(params, "rim_slot_min_segment_length_mm", 0.35)
    _assert_no_duplicate_or_short_edges(profile, min_seg)

    area = _polygon_area(profile)
    if area <= 1e-6:
        raise ValueError("Slot profile polygon area is zero")

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

---

# 8. Axial-through cutter v6

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
        raise ValueError("Axial-through slot cutter height must be positive")

    if style == "fir_tree_like":
        profile, station_metadata = _fir_tree_clean_symmetric_profile_xy(params)
        profile_generation_method = "single_clean_polygon"
    elif style == "dovetail":
        profile, station_metadata = _dovetail_clean_profile_xy(params)
        profile_generation_method = "single_clean_polygon"
    elif style == "rectangular":
        profile, station_metadata = _rectangular_clean_profile_xy(params)
        profile_generation_method = "single_clean_polygon"
    else:
        raise ValueError(f"Unsupported rim_slot_style: {style!r}")

    outer_radius = _get_float(params, "outer_dia_mm") / 2.0
    max_x = max(x for x, _ in profile)
    min_x = min(x for x, _ in profile)
    max_abs_y = max(abs(y) for _, y in profile)
    area = _polygon_area(profile)

    if max_x <= outer_radius:
        raise ValueError("Slot profile must extend beyond outer_radius")

    if min_x >= outer_radius:
        raise ValueError("Slot profile must cut inward from outer_radius")

    cutter = (
        cq.Workplane("XY")
        .polyline(profile)
        .close()
        .extrude(height)
        .translate((0.0, 0.0, z_min))
    )

    return cutter, {
        "profile_generation_method": profile_generation_method,
        "profile_points_xy": [[float(x), float(y)] for x, y in profile],
        "stage_stations": station_metadata,
        "profile_symmetry": "mirror_y",
        "is_mirror_symmetric": True,
        "profile_area_mm2": float(area),
        "profile_point_count": len(profile),
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

# 9. Cut 后清理

`_cut_rim_slots()` 中，每次 cut 后建议 clean：

```python
for i in range(count):
    angle = 360.0 * i / count
    rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
    result = result.cut(rotated)
    result = result.clean()
```

如果 `.clean()` 在当前 CadQuery 版本不可用，可以：

```python
try:
    result = result.clean()
except AttributeError:
    pass
```

但 Boolean cut 本身失败不能吞：

```python
# 不允许：
try:
    result = result.cut(rotated)
except Exception:
    pass
```

必须 fail-closed。

---

# 10. Metadata v6

metadata 必须新增：

```python
"slot_generation": {
    "version": "rim_slot_v6_clean_symmetric_polygon",
    "profile_generation_method": "single_clean_polygon",
    "box_union_forbidden": True,
    "box_union_used": False,
    "profile_symmetry": "mirror_y",
    "is_mirror_symmetric": True,
    "profile_point_count": ...,
    "profile_area_mm2": ...,
    "stage_count": ...,
    "stage_stations": ...,
    "opens_front_face": True,
    "opens_back_face": True,
    "opens_outer_diameter": True,
    "z_min_mm": ...,
    "z_max_mm": ...,
    "rim_z_min_mm": ...,
    "rim_z_max_mm": ...,
    "profile_max_x_mm": ...,
    "profile_min_x_mm": ...,
    "outer_radius_mm": ...,
}
```

`rim_features` 必须包含：

```python
"rim_features": {
    "slot_count": ...,
    "slot_style": ...,
    "slot_orientation": ...,
    "stage_count": ...,
    "mouth_width_mm": ...,
    "throat_width_mm": ...,
    "stage_neck_width_mm": ...,
    "stage_lobe_width_mm": ...,
    "root_width_mm": ...,
    "slot_profile_points_xy": ...,
    "stage_stations": ...,
    "reference_only": True,
}
```

`visual_fidelity` 必须包含：

```python
"contains_clean_symmetric_fir_tree_slots": True,
"contains_box_union_fir_tree_slots": False,
"contains_real_blade_attachment": False,
```

`safety` 继续包含：

```python
"not_for_installation": True,
"no_structural_validation": True,
"no_life_prediction": True,
"no_rotordynamic_validation": True,
```

warnings 必须包含：

```text
Fir-tree-like slots are generated from a single clean mirror-symmetric polygon profile.
Box-union fir-tree cutters are forbidden because they create sliver faces and visual artifacts.
The slot geometry is visual/reference only and not a certified blade attachment.
```

---

# 11. Metadata validator v6

在 `metadata.py` 中检查：

```text
1. kernel == cadquery_turbine_disk_reference_v6；
2. geometry_family == axisymmetric_base_with_clean_symmetric_fir_tree_slots；
3. slot_generation.version == rim_slot_v6_clean_symmetric_polygon；
4. profile_generation_method == single_clean_polygon；
5. box_union_forbidden is True；
6. box_union_used is False；
7. is_mirror_symmetric is True；
8. profile_point_count >= 8；
9. profile_area_mm2 > 0；
10. stage_count >= 2；
11. stage_stations 非空；
12. opens_front_face/back_face/outer_diameter 全 True；
13. z_min < rim_z_min；
14. z_max > rim_z_max；
15. profile_max_x > outer_radius；
16. profile_min_x < outer_radius；
17. contains_clean_symmetric_fir_tree_slots is True；
18. contains_box_union_fir_tree_slots is False；
19. contains_real_blade_attachment is False；
20. safety.not_for_installation is True；
21. safety.no_structural_validation is True；
22. safety.no_life_prediction is True。
```

---

# 12. Mechanical validation v6

`ALLOWED_KERNELS` 加入：

```python
"cadquery_turbine_disk_reference_v6"
```

demo expected kernel 必须是：

```python
"cadquery_turbine_disk_reference_v6"
```

必须新增检查：

```text
1. expected_kernel mismatch fail；
2. slot_generation.profile_generation_method != single_clean_polygon fail；
3. slot_generation.box_union_used is not False fail；
4. slot_generation.is_mirror_symmetric is not True fail；
5. profile_area_mm2 <= 0 fail；
6. stage_count < 2 fail；
7. contains_clean_symmetric_fir_tree_slots is not True fail；
8. contains_box_union_fir_tree_slots is not False fail；
9. contains_real_blade_attachment is not False fail；
10. mouth_width >= stage_lobe_width fail；
11. throat_width >= stage_lobe_width fail；
12. z_min >= rim_z_min fail；
13. z_max <= rim_z_max fail。
```

---

# 13. `demo_full_chain.py` 更新

`run_case_axisymmetric_turbine_disk()` 中加入：

```python
"rim_slot_generation_method": "single_clean_polygon",
"rim_slot_profile_kind": "symmetric_multistage_fir_tree",
"rim_slot_profile_symmetry": "mirror_y",
"rim_slot_topology_mode": "clean_socket_cut",

"rim_slot_stage_count": 3,
"rim_slot_stage_pitch_mm": 7.0,
"rim_slot_stage_neck_width_mm": 4.6,
"rim_slot_stage_lobe_width_mm": 9.0,
"rim_slot_stage_lobe_height_mm": 2.0,
"rim_slot_stage_width_growth": 0.06,

"rim_slot_mouth_width_mm": 5.2,
"rim_slot_throat_width_mm": 4.6,
"rim_slot_root_width_mm": 5.4,

"rim_slot_min_segment_length_mm": 0.35,
"rim_slot_corner_relief_mm": 0.25,
"rim_slot_profile_clean_tolerance_mm": 1e-6,

"rim_slot_expose_lobes_on_od": False,
"rim_slot_require_multiple_stages": True,
"rim_slot_reject_self_intersection": True,
"rim_slot_reject_duplicate_points": True,
```

primitive validation：

```python
"expected_kernel": "cadquery_turbine_disk_reference_v6",
"expected_slot_generation_method": "single_clean_polygon",
"expected_profile_symmetry": "mirror_y",
"expected_box_union_used": False,
"expected_fir_tree_stage_count": 3,
```

required metrics 加入：

```text
reference_dimensions.rim_slot_generation_method
reference_dimensions.rim_slot_profile_symmetry
reference_dimensions.rim_slot_is_mirror_symmetric
reference_dimensions.rim_slot_profile_area_mm2
reference_dimensions.rim_slot_profile_point_count
reference_dimensions.rim_slot_stage_count
reference_dimensions.rim_slot_box_union_used
reference_dimensions.expected_fir_tree_stage_count
```

---

# 14. Primitive compiler 保持 dispatcher

`primitive_compiler.py` 不要内联任何几何细节。

必须仍然只出现：

```python
build_axisymmetric_turbine_disk_cadquery(_params)
```

测试中必须确保 compiler script 不包含：

```text
_fir_tree_stage_stations
_symmetric_slot_profile_from_stations
_fir_tree_clean_symmetric_profile_xy
Workplane("XY").polyline
result.cut(rotated)
_make_box
```

---

# 15. 测试要求

## 15.1 参数测试

新增：

```text
1. generation_method != single_clean_polygon fail；
2. profile_symmetry != mirror_y fail；
3. box_union 相关参数非法 fail；
4. stage_count < 2 fail；
5. stage_lobe_width <= stage_neck_width fail；
6. mouth_width >= stage_lobe_width fail；
7. throat_width >= stage_lobe_width fail；
8. min_segment_length <= 0 fail；
9. slot pitch too small fail；
10. axial_through + axial_margin > 0 fail。
```

## 15.2 Kernel profile 测试

必须直接测试 profile helper：

```python
def test_v6_profile_is_mirror_symmetric():
    profile, stations = _fir_tree_clean_symmetric_profile_xy(valid_v6_params())
    _assert_profile_mirror_y(profile)

def test_v6_profile_has_no_short_edges():
    profile, _ = _fir_tree_clean_symmetric_profile_xy(valid_v6_params())
    _assert_no_duplicate_or_short_edges(profile, 0.35)

def test_v6_profile_area_positive():
    profile, _ = _fir_tree_clean_symmetric_profile_xy(valid_v6_params())
    assert _polygon_area(profile) > 0

def test_v6_profile_uses_single_polygon_not_box_union():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v6_params())
    slot = md["slot_generation"]
    assert slot["profile_generation_method"] == "single_clean_polygon"
    assert slot["box_union_used"] is False
```

## 15.3 Metadata 测试

新增：

```text
1. slot_generation.version == rim_slot_v6_clean_symmetric_polygon；
2. profile_generation_method == single_clean_polygon；
3. box_union_used=True fail；
4. is_mirror_symmetric=False fail；
5. profile_area_mm2 <= 0 fail；
6. contains_box_union_fir_tree_slots=True fail；
7. contains_clean_symmetric_fir_tree_slots 缺失 fail。
```

## 15.4 Mechanical validation 测试

新增：

```text
1. v6 happy path ok；
2. expected_kernel mismatch fail；
3. box_union_used=True fail；
4. profile_generation_method != single_clean_polygon fail；
5. profile_area <= 0 fail；
6. profile symmetry false fail；
7. contains_real_blade_attachment=True fail。
```

---

# 16. 验收命令

```bash
cd integrations/engineering_tools
python -m pytest tests -q
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
```

重点：

```bash
python -m pytest tests/test_turbine_disk_visual_features.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_mechanical_validation.py -q
python -m pytest tests/test_demo_full_chain_turbine_disk.py -q
```

---

# 17. SolidWorks 视觉验收标准

修复后必须满足：

```text
1. 不再出现大量奇怪长线；
2. 卡槽突出部附近不再出现三角小洞；
3. 单个卡槽左右对称；
4. 单个卡槽有清晰多级成对 lobe；
5. 外口窄，内部逐级变宽；
6. 相邻槽之间 disk posts 清晰；
7. 前后端面可见完整对称 fir-tree-like socket；
8. 外圆侧壁不再是 box union 造成的碎裂台阶；
9. 整体仍然只是 reference geometry，不声称真实制造/适航。
```

---

# 18. 可直接交给 Claude Code 的最终 Prompt

```text
你现在在 seekflow-engineering 仓库中工作，重点目录是 integrations/engineering_tools。

用户最新反馈：涡轮盘外缘卡槽附近出现奇怪的线和三角形小洞，卡槽形态也不像真实 fir-tree / dovetail slot。最新截图显示，卡槽突出部附近存在大量碎线、三角 sliver face、局部小孔。这说明当前 fir_tree_like cutter 的拓扑不干净。请修复 axisymmetric_turbine_disk 的 fir-tree slot kernel。

最高约束：
1. primitive_name 保持 axisymmetric_turbine_disk。
2. KERNEL_NAME 升级为 cadquery_turbine_disk_reference_v6。
3. GEOMETRY_FAMILY 使用 axisymmetric_base_with_clean_symmetric_fir_tree_slots。
4. 不允许声称 flight-ready / airworthy / certified / manufacturing-ready / installable。
5. fir-tree-like slots 只能是 visual/reference geometry。
6. primitive_compiler 只调用 deterministic kernel。
7. SolidWorks/NX 只能 import canonical STEP。
8. 所有失败必须 fail-closed。
9. 不得破坏 involute_spur_gear 和已有 recipe cases。

核心问题：
当前 fir_tree_like slot 由多个 box union 生成，导致 Boolean cut 后产生 seam edges、sliver faces、三角小洞和奇怪长线。必须禁止 box-union fir-tree cutter。

必须实现：
1. 使用单一闭合 polygon profile 生成 fir-tree socket；
2. profile 必须 mirror_y 对称；
3. profile 必须由 station list 生成；
4. station 的 x 必须从 outer_radius 向内严格递减；
5. profile 不允许重复点、零长度边、极短边；
6. profile 面积必须 > 0；
7. cutter 沿 Z 方向贯穿 rim；
8. cut 后可调用 clean；
9. metadata 记录 profile_generation_method=single_clean_polygon；
10. metadata 记录 box_union_used=False；
11. mechanical validation 强制拒绝 box_union_used=True。

修改文件：
- models.py
- validator.py
- axisymmetric_turbine_disk.py
- metadata.py
- turbomachinery_validation.py
- primitive_compiler.py
- demo_full_chain.py

新增参数：
rim_slot_generation_method = "single_clean_polygon"
rim_slot_profile_kind = "symmetric_multistage_fir_tree"
rim_slot_profile_symmetry = "mirror_y"
rim_slot_topology_mode = "clean_socket_cut"
rim_slot_stage_count = 3
rim_slot_stage_pitch_mm = 7.0
rim_slot_stage_neck_width_mm = 4.6
rim_slot_stage_lobe_width_mm = 9.0
rim_slot_stage_lobe_height_mm = 2.0
rim_slot_stage_width_growth = 0.06
rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.6
rim_slot_root_width_mm = 5.4
rim_slot_min_segment_length_mm = 0.35
rim_slot_corner_relief_mm = 0.25
rim_slot_profile_clean_tolerance_mm = 1e-6
rim_slot_expose_lobes_on_od = False
rim_slot_require_multiple_stages = True
rim_slot_reject_self_intersection = True
rim_slot_reject_duplicate_points = True

axisymmetric_turbine_disk.py 中：
- 删除/停用多个 box union 的 fir_tree_like 主实现；
- 实现 _fir_tree_stage_stations；
- 实现 _normalize_and_validate_stations；
- 实现 _symmetric_slot_profile_from_stations；
- 实现 _assert_profile_mirror_y；
- 实现 _assert_no_duplicate_or_short_edges；
- 实现 _polygon_area；
- 实现 _fir_tree_clean_symmetric_profile_xy；
- _make_axial_through_slot_cutter 使用 cq.Workplane("XY").polyline(profile).close().extrude(height)；
- 每个 slot cut 后 result.clean()；
- cut 异常不得吞掉。

metadata 必须包含：
kernel = cadquery_turbine_disk_reference_v6
geometry_family = axisymmetric_base_with_clean_symmetric_fir_tree_slots
slot_generation.version = rim_slot_v6_clean_symmetric_polygon
slot_generation.profile_generation_method = single_clean_polygon
slot_generation.box_union_forbidden = True
slot_generation.box_union_used = False
slot_generation.is_mirror_symmetric = True
slot_generation.profile_area_mm2 > 0
visual_fidelity.contains_clean_symmetric_fir_tree_slots = True
visual_fidelity.contains_box_union_fir_tree_slots = False
visual_fidelity.contains_real_blade_attachment = False

mechanical validation 必须拒绝：
- box_union_used=True；
- profile_generation_method != single_clean_polygon；
- is_mirror_symmetric != True；
- profile_area_mm2 <= 0；
- stage_count < 2；
- contains_box_union_fir_tree_slots=True；
- contains_real_blade_attachment=True。

demo_full_chain.py：
expected_kernel 改为 cadquery_turbine_disk_reference_v6。
required metrics 加入 profile_generation_method、box_union_used、profile_area、stage_count、mirror symmetry 等字段。

测试：
必须新增/更新：
1. profile mirror symmetry；
2. no duplicate/short edges；
3. polygon area positive；
4. box_union_used False；
5. compiler 不内联几何；
6. metadata validator 拒绝 box_union；
7. mechanical validation 拒绝 box_union；
8. demo expected_kernel=v6。

运行：
cd integrations/engineering_tools
python -m pytest tests -q
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery

完成后输出：
1. 修改文件清单；
2. v6 参数清单；
3. 为什么奇怪线和三角洞会消失的解释；
4. 测试结果；
5. demo 结果；
6. 如果 SolidWorks 里仍有三角孔或奇怪碎线，不得声称完成，必须说明原因。
```

---

最关键的一句话：**不要再让 `fir_tree_like` 走多个 box union。**现在的碎线和三角洞几乎就是这种构造方式的典型后果。必须改成“单一、干净、镜像对称、无短边的闭合 polygon profile”，再做一次轴向贯穿 extrude cutter。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py "raw.githubusercontent.com"
[2]: https://www.sciencedirect.com/topics/engineering/fir-tree-root?utm_source=chatgpt.com "Fir Tree Root - an overview"
