# SeekFlow Engineering：`axisymmetric_turbine_disk` 卡榫/榫槽 v0.4 精准修复实施文档

## 0. 当前问题说明

用户最新 SolidWorks 局部截图显示，`axisymmetric_turbine_disk` 外缘卡榫/榫槽做得不对。

当前视觉问题：

```text
1. 外圆侧壁上出现一排横向、不规则、台阶状的锯齿槽；
2. 槽形像是被多个 box cutter 拼出来的碎块；
3. 外径入口处暴露了过多 fir-tree/lobe 形状；
4. 卡槽没有形成真实涡轮盘常见的“窄入口 + 内部扩大榫槽腔”；
5. 从侧壁看像装饰性刻槽，不像 blade-root slot；
6. 真实 fir-tree / dovetail 槽的主要截面轮廓应该在前后端面可见，而不是全部暴露在外圆柱面；
7. 当前 cutter 语义更接近“在外圆侧面挖几个台阶”，不是“沿轴向贯穿 rim 的叶根槽 socket”。
```

本轮目标不是继续增加更多细节，而是**修正榫槽几何语义**。

最终目标：

```text
primitive_name = "axisymmetric_turbine_disk"
kernel = "cadquery_turbine_disk_reference_v4"
geometry_family = "axisymmetric_base_with_axial_fir_tree_socket_slots"
```

核心修复：

```text
将当前“box 组合式侧壁锯齿槽”改为“轴向贯穿的 blade-root socket”。

正确的 slot 应满足：

1. 沿 Z 方向贯穿 rim 前后端面；
2. 外圆入口是窄喉口，不应把所有 lobe 全暴露在外圆侧壁；
3. fir-tree / dovetail 的多级轮廓应作为槽腔截面，主要在前端面和后端面可见；
4. slot 的径向方向从 outer_radius 向内切入；
5. slot 的切向方向控制喉口宽度、颈部宽度、lobe 宽度；
6. slot 与 slot 之间保留 rim posts；
7. metadata 和 mechanical validation 必须验证 socket 语义，而不仅仅验证 slot_count。
```

---

## 1. 硬性安全与架构约束

Claude Code 必须遵守：

```text
1. 不允许声称 flight-ready。
2. 不允许声称 airworthy。
3. 不允许声称 certified。
4. 不允许声称 manufacturing-ready。
5. 不允许声称 installable。
6. 不允许做真实航空发动机强度、寿命、转速、材料、适航设计。
7. 不允许把 fir_tree_like slot 声称为真实叶片连接结构。
8. rim slots 只能声明为 visual/reference geometry。
9. primitive compiler 只能调用 deterministic kernel，不允许内联几何。
10. SolidWorks / NX 只能 import canonical STEP。
11. 所有失败必须 fail-closed。
12. 不得破坏 `involute_spur_gear`。
13. 不得破坏现有 recipe cases。
14. 不得修改 primitive_name，仍为 `axisymmetric_turbine_disk`。
```

所有 metadata / warnings / skill contract 中继续保留：

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

# 2. 当前几何错误的根因

当前 v2 slot cutter 的根本问题是：

```text
1. 使用多个 box union 拼出 fir_tree_like；
2. 这些 box 在径向不同位置具有不同切向宽度；
3. 组合体直接从外圆往里切；
4. 因此从外圆侧壁能看到一堆横向台阶/lobe；
5. 这会把 fir-tree 的内部 lobe 形状暴露到外圆柱侧壁；
6. 结果就是截图里那种“侧壁锯齿槽”。
```

真实 reference slot 的语义应该是：

```text
outer OD side:
  只看到窄入口、轴向长槽、基本直而干净；

front/back face:
  看到 fir-tree / dovetail 的完整截面轮廓；

inside rim:
  多级 lobe 腔体在 rim 内部展开；

disk posts:
  相邻 slot 之间保留实体。
```

因此，v4 不能继续使用“多个 box 拼成槽”的方式作为主实现。

必须改为：

```text
用一个明确的 XY 截面 polygon 表达 blade-root socket，
再沿 Z 方向 extrude 贯穿 rim。
```

---

# 3. v4 几何概念定义

## 3.1 局部 slot 坐标

在 +X 方向生成单个 slot cutter，然后绕 Z 轴阵列。

局部坐标定义：

```text
X 方向：径向，+X 指向外圆；
Y 方向：切向宽度；
Z 方向：轴向，贯穿 rim 前后端面。
```

单个 slot cutter 是一个 prism：

```text
XY 平面：slot 截面轮廓；
Z 方向：贯穿 extrusion。
```

## 3.2 正确 socket 截面

对 `fir_tree_like`，截面不应该是“外侧很宽、内侧乱变”的锯齿，而应该是：

```text
outer mouth:
  窄入口，宽度 mouth_width；

throat / neck:
  比 mouth 略窄或相近，形成入口颈部；

first lobe chamber:
  在径向更内侧变宽；

second neck:
  再收窄；

second lobe chamber:
  再变宽；

root pocket:
  最内侧稍收或圆化。
```

也就是说：

```text
外圆处窄，内部变宽，再收缩，再变宽。
```

不能把 lobe 直接暴露在 outer_radius 外侧。

---

# 4. 参数表 v4 修改

## 4.1 保留已有参数

保留 v0.2/v0.3 中已有参数，不要删除已有 CAD-IR 字段。

## 4.2 新增/确认 slot 参数

在：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
```

确保注册以下参数：

```text
rim_slot_count
rim_slot_style
rim_slot_orientation

rim_slot_depth_mm
rim_slot_mouth_width_mm
rim_slot_throat_width_mm
rim_slot_lobe_width_mm
rim_slot_lobe_depth_mm
rim_slot_root_width_mm

rim_slot_width_mm
rim_slot_neck_width_mm

rim_slot_axial_margin_mm
rim_slot_through_clearance_mm
rim_slot_outer_clearance_mm

rim_slot_root_fillet_mm
rim_slot_tip_chamfer_mm

rim_slot_socket_mode
rim_slot_expose_lobes_on_od
```

说明：

```text
rim_slot_width_mm:
  兼容旧参数，可作为 mouth_width 默认来源。

rim_slot_neck_width_mm:
  兼容旧参数，可作为 throat_width 默认来源。

rim_slot_mouth_width_mm:
  新推荐参数，控制外圆入口宽度。

rim_slot_throat_width_mm:
  新推荐参数，控制颈部宽度。

rim_slot_lobe_width_mm:
  控制内部腔体最大宽度。

rim_slot_root_width_mm:
  控制最内端 root pocket 宽度。

rim_slot_socket_mode:
  默认为 "internal_lobes"。

rim_slot_expose_lobes_on_od:
  必须默认为 False。
```

推荐默认：

```text
rim_slot_count = 60
rim_slot_style = "fir_tree_like"
rim_slot_orientation = "axial_through"

rim_slot_depth_mm = 38.0

rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.5
rim_slot_lobe_width_mm = 9.0
rim_slot_lobe_depth_mm = 7.0
rim_slot_root_width_mm = 5.5

rim_slot_width_mm = 5.2
rim_slot_neck_width_mm = 4.5

rim_slot_axial_margin_mm = 0.0
rim_slot_through_clearance_mm = 2.0
rim_slot_outer_clearance_mm = 4.0

rim_slot_root_fillet_mm = 0.0
rim_slot_tip_chamfer_mm = 0.0

rim_slot_socket_mode = "internal_lobes"
rim_slot_expose_lobes_on_od = False
```

允许值：

```text
rim_slot_style:
  none
  rectangular
  dovetail
  fir_tree_like

rim_slot_orientation:
  axial_through
  side_groove

rim_slot_socket_mode:
  simple_open_slot
  internal_lobes
```

v4 demo 必须使用：

```text
rim_slot_style = "fir_tree_like"
rim_slot_orientation = "axial_through"
rim_slot_socket_mode = "internal_lobes"
rim_slot_expose_lobes_on_od = False
```

---

# 5. Validator v4 修改

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
```

## 5.1 新增允许值

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

ALLOWED_RIM_SLOT_SOCKET_MODES = {
    "simple_open_slot",
    "internal_lobes",
}
```

## 5.2 新增 bool 严格约束

`rim_slot_expose_lobes_on_od` 必须是 bool。

如果 primitive normalizer 已有严格 bool parser，直接使用 normalize 后结果即可。

v4 demo 必须：

```python
rim_slot_expose_lobes_on_od is False
```

## 5.3 `_validate_rim_slots()` 必须检查

核心逻辑：

```python
def _validate_rim_slots(errors: list[str], params: dict) -> None:
    style = str(params.get("rim_slot_style", "none"))
    orientation = str(params.get("rim_slot_orientation", "axial_through"))
    socket_mode = str(params.get("rim_slot_socket_mode", "internal_lobes"))
    count = int(params.get("rim_slot_count", 0))

    if style not in ALLOWED_RIM_SLOT_STYLES:
        errors.append(...)
        return

    if orientation not in ALLOWED_RIM_SLOT_ORIENTATIONS:
        errors.append(...)
        return

    if socket_mode not in ALLOWED_RIM_SLOT_SOCKET_MODES:
        errors.append(...)
        return

    if style == "none":
        if count != 0:
            errors.append("rim_slot_count must be 0 when rim_slot_style='none'")
        return

    if count < 12:
        errors.append("rim_slot_count must be >= 12 when rim slots are enabled")
```

尺寸检查：

```python
outer_d = float(params["outer_dia_mm"])
rim_inner_d = float(params["rim_inner_dia_mm"])
rim_width = float(params["rim_width_mm"])

r_outer = outer_d / 2.0
r_rim_inner = rim_inner_d / 2.0
rim_radial = r_outer - r_rim_inner

depth = float(params.get("rim_slot_depth_mm", 0.0))

mouth_w = float(
    params.get(
        "rim_slot_mouth_width_mm",
        params.get("rim_slot_width_mm", 0.0),
    )
)
throat_w = float(
    params.get(
        "rim_slot_throat_width_mm",
        params.get("rim_slot_neck_width_mm", 0.0),
    )
)
lobe_w = float(params.get("rim_slot_lobe_width_mm", 0.0))
root_w = float(params.get("rim_slot_root_width_mm", throat_w))
lobe_depth = float(params.get("rim_slot_lobe_depth_mm", 0.0))

through_clearance = float(params.get("rim_slot_through_clearance_mm", 0.0))
outer_clearance = float(params.get("rim_slot_outer_clearance_mm", 0.0))
axial_margin = float(params.get("rim_slot_axial_margin_mm", 0.0))
```

必须检查：

```text
1. depth > 0；
2. depth < 0.85 * rim_radial；
3. mouth_w > 0；
4. throat_w > 0；
5. lobe_w > 0 for fir_tree_like/internal_lobes；
6. root_w > 0；
7. lobe_depth > 0 for fir_tree_like；
8. throat_w <= mouth_w；
9. mouth_w < lobe_w；
10. throat_w < lobe_w；
11. root_w <= lobe_w；
12. outer_clearance >= 0；
13. through_clearance >= 0；
14. axial_through 时 axial_margin == 0；
15. axial_through 时 through_clearance > 0；
16. slot pitch > lobe_w * 1.25；
17. rim_slot_expose_lobes_on_od must be False for fir_tree_like/internal_lobes。
```

推荐实现：

```python
pitch = 2.0 * math.pi * r_outer / max(count, 1)

if pitch <= lobe_w * 1.25:
    errors.append(
        "rim slot lobe width is too large for rim_slot_count; adjacent internal lobes would overlap"
    )

if orientation == "axial_through":
    if axial_margin != 0:
        errors.append(
            "rim_slot_axial_margin_mm must be 0 for axial_through rim slots"
        )
    if through_clearance <= 0:
        errors.append(
            "rim_slot_through_clearance_mm must be > 0 for axial_through rim slots"
        )

if style == "fir_tree_like" and socket_mode == "internal_lobes":
    expose = params.get("rim_slot_expose_lobes_on_od", False)
    if expose is not False:
        errors.append(
            "rim_slot_expose_lobes_on_od must be False for v4 fir_tree_like internal_lobes; "
            "the OD entrance must remain a narrow mouth"
        )

    if mouth_w >= lobe_w:
        errors.append(
            "rim_slot_mouth_width_mm must be smaller than rim_slot_lobe_width_mm"
        )
    if throat_w >= lobe_w:
        errors.append(
            "rim_slot_throat_width_mm must be smaller than rim_slot_lobe_width_mm"
        )
```

---

# 6. Kernel v4 重写重点

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
```

## 6.1 常量

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v4"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"
GEOMETRY_FAMILY = "axisymmetric_base_with_axial_fir_tree_socket_slots"
```

## 6.2 保留整体流程

主流程仍然是：

```text
1. build base body；
2. add front/rear hub sleeve；
3. add annular details；
4. cut hole rings；
5. cut coverplate/balance holes；
6. 最后 cut rim slots；
7. build metadata。
```

注意：

```text
rim slots 必须最后 cut。
```

因为它需要切开 rim 上已有的所有外缘细节。

---

# 7. 正确的 fir-tree socket cutter

## 7.1 禁止继续使用多个 box union 作为 fir-tree 主实现

当前问题很大概率来自 box union：

```text
mouth box
neck box
lobe box
root pocket box
```

这种实现会把各个 box 的边界直接暴露在外圆侧壁上，形成用户截图里的“横向台阶块”。

v4 必须使用：

```text
单个闭合 polygon profile
+ Z direction extrusion
```

## 7.2 新 helper：宽度参数读取

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
    lobe = _get_float(params, "rim_slot_lobe_width_mm", 0.0)
    root = _get_float(params, "rim_slot_root_width_mm", throat)

    return {
        "mouth": mouth,
        "throat": throat,
        "lobe": lobe,
        "root": root,
    }
```

## 7.3 Fir-tree internal-lobes profile

关键原则：

```text
x_outer 到 x_mouth_end：
  保持窄 mouth，不暴露 lobe；

x_mouth_end 往内：
  才开始展开 fir-tree lobe；

因此从外圆侧壁看是窄槽；
从前后端面看是完整 fir-tree socket。
```

实现：

```python
def _fir_tree_internal_socket_profile_xy(params: dict) -> list[tuple[float, float]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    widths = _slot_widths(params)
    mouth_w = widths["mouth"]
    throat_w = widths["throat"]
    lobe_w = widths["lobe"]
    root_w = widths["root"]

    x0 = r_outer + outer_clearance
    x1 = r_outer - depth * 0.14   # OD mouth segment end
    x2 = r_outer - depth * 0.26   # first throat
    x3 = r_outer - depth * 0.42   # first lobe
    x4 = r_outer - depth * 0.58   # second throat
    x5 = r_outer - depth * 0.76   # second lobe
    x6 = r_outer - depth          # root pocket

    return [
        (x0, -mouth_w / 2.0),
        (x1, -mouth_w / 2.0),

        (x2, -throat_w / 2.0),
        (x3, -lobe_w / 2.0),
        (x4, -throat_w / 2.0),
        (x5, -lobe_w * 0.90 / 2.0),
        (x6, -root_w / 2.0),

        (x6, root_w / 2.0),
        (x5, lobe_w * 0.90 / 2.0),
        (x4, throat_w / 2.0),
        (x3, lobe_w / 2.0),
        (x2, throat_w / 2.0),

        (x1, mouth_w / 2.0),
        (x0, mouth_w / 2.0),
    ]
```

这个 profile 的关键点：

```text
1. x0 到 x1 都是 mouth_w；
2. 外圆入口不暴露 lobe_w；
3. lobe_w 只在内部 x3/x5 位置出现；
4. 前后端面能看到 fir-tree-like 内部轮廓；
5. 外圆侧面只看到窄入口。
```

## 7.4 Dovetail profile

```python
def _dovetail_socket_profile_xy(params: dict) -> list[tuple[float, float]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)

    widths = _slot_widths(params)
    mouth_w = widths["mouth"]
    throat_w = widths["throat"]
    lobe_w = widths["lobe"]

    x0 = r_outer + outer_clearance
    x1 = r_outer - depth * 0.20
    x2 = r_outer - depth * 0.55
    x3 = r_outer - depth

    return [
        (x0, -mouth_w / 2.0),
        (x1, -mouth_w / 2.0),
        (x2, -throat_w / 2.0),
        (x3, -lobe_w / 2.0),
        (x3, lobe_w / 2.0),
        (x2, throat_w / 2.0),
        (x1, mouth_w / 2.0),
        (x0, mouth_w / 2.0),
    ]
```

## 7.5 Rectangular profile

```python
def _rectangular_socket_profile_xy(params: dict) -> list[tuple[float, float]]:
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    outer_clearance = _get_float(params, "rim_slot_outer_clearance_mm", 4.0)
    width = _slot_widths(params)["mouth"]

    x0 = r_outer + outer_clearance
    x1 = r_outer - depth

    return [
        (x0, -width / 2.0),
        (x1, -width / 2.0),
        (x1, width / 2.0),
        (x0, width / 2.0),
    ]
```

---

# 8. Axial-through cutter v4

## 8.1 必须基于 rim_z_min / rim_z_max

`_build_base_body()` 必须返回：

```python
axial_zones = {
    "rim_z_min_mm": -t_rim,
    "rim_z_max_mm": t_rim,
    "hub_z_min_mm": -t_hub,
    "hub_z_max_mm": t_hub,
    "web_z_min_mm": -t_web,
    "web_z_max_mm": t_web,
}
```

## 8.2 cutter 实现

```python
def _select_slot_profile_xy(params: dict) -> list[tuple[float, float]]:
    style = _get_str(params, "rim_slot_style", "none")
    socket_mode = _get_str(params, "rim_slot_socket_mode", "internal_lobes")

    if style == "rectangular":
        return _rectangular_socket_profile_xy(params)

    if style == "dovetail":
        return _dovetail_socket_profile_xy(params)

    if style == "fir_tree_like":
        if socket_mode != "internal_lobes":
            return _rectangular_socket_profile_xy(params)
        return _fir_tree_internal_socket_profile_xy(params)

    raise ValueError(f"Unsupported rim_slot_style: {style!r}")
```

```python
def _make_axial_through_slot_cutter(
    cq,
    params: dict,
    *,
    rim_z_min: float,
    rim_z_max: float,
):
    through_clearance = _get_float(params, "rim_slot_through_clearance_mm", 2.0)

    z_min = rim_z_min - through_clearance
    z_max = rim_z_max + through_clearance
    height = z_max - z_min

    if height <= 0:
        raise ValueError("axial-through slot cutter has non-positive height")

    profile = _select_slot_profile_xy(params)

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

    if max_x <= outer_radius:
        raise ValueError(
            "slot cutter profile must extend beyond outer_radius to open the outer diameter"
        )

    if min_x >= outer_radius:
        raise ValueError(
            "slot cutter profile must cut inward from outer_radius into the rim"
        )

    return cutter, {
        "profile_points_xy": [[float(x), float(y)] for x, y in profile],
        "z_min_mm": float(z_min),
        "z_max_mm": float(z_max),
        "height_mm": float(height),
        "max_x_mm": float(max_x),
        "min_x_mm": float(min_x),
        "outer_radius_mm": float(outer_radius),
    }
```

---

# 9. Cut rim slots v4

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
            "opens_front_face": False,
            "opens_back_face": False,
            "opens_outer_diameter": False,
            "exposes_lobes_on_od": False,
            "reference_only": True,
        }

    rim_z_min = float(axial_zones["rim_z_min_mm"])
    rim_z_max = float(axial_zones["rim_z_max_mm"])

    if orientation != "axial_through":
        raise ValueError(
            "v4 turbine disk demo only supports rim_slot_orientation='axial_through'; "
            "side_groove is retained only for future compatibility"
        )

    cutter, cutter_md = _make_axial_through_slot_cutter(
        cq,
        params,
        rim_z_min=rim_z_min,
        rim_z_max=rim_z_max,
    )

    # Fail closed: do not catch exceptions.
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
        "z_min_mm": cutter_md["z_min_mm"],
        "z_max_mm": cutter_md["z_max_mm"],
        "height_mm": cutter_md["height_mm"],
        "max_x_mm": cutter_md["max_x_mm"],
        "min_x_mm": cutter_md["min_x_mm"],
        "outer_radius_mm": cutter_md["outer_radius_mm"],

        "rim_z_min_mm": rim_z_min,
        "rim_z_max_mm": rim_z_max,

        "opens_front_face": True,
        "opens_back_face": True,
        "opens_outer_diameter": True,

        "exposes_lobes_on_od": bool(
            params.get("rim_slot_expose_lobes_on_od", False)
        ),

        "reference_only": True,
    }

    return result, slot_metadata
```

重点：

```text
1. v4 demo 不再允许 side_groove；
2. side_groove 如果保留，也不应作为默认路径；
3. slot cut 异常不允许吞掉；
4. slot_metadata 必须记录“外圆不暴露 lobe”的语义。
```

---

# 10. Metadata v4

## 10.1 reference_dimensions

`_reference_dimensions(params, slot_metadata)` 必须包含：

```python
{
    "rim_slot_count": ...,
    "rim_slot_style": ...,
    "rim_slot_orientation": ...,
    "rim_slot_socket_mode": ...,

    "rim_slot_mouth_width_mm": ...,
    "rim_slot_throat_width_mm": ...,
    "rim_slot_lobe_width_mm": ...,
    "rim_slot_root_width_mm": ...,

    "rim_slot_opens_front_face": True,
    "rim_slot_opens_back_face": True,
    "rim_slot_opens_outer_diameter": True,

    "rim_slot_exposes_lobes_on_od": False,

    "rim_slot_z_min_mm": ...,
    "rim_slot_z_max_mm": ...,
    "rim_slot_profile_max_x_mm": ...,
    "rim_slot_profile_min_x_mm": ...,
    "rim_slot_outer_radius_mm": ...,

    "expected_periodic_slot_count": rim_slot_count,
    "expected_bbox_mm": ...,
}
```

## 10.2 metadata 主结构

```python
metadata = {
    "primitive": PRIMITIVE_NAME,
    "metadata_version": "primitive_metadata_v1",
    "kernel": KERNEL_NAME,
    "geometry_family": GEOMETRY_FAMILY,
    "parameters": dict(params),
    "reference_dimensions": ref_dims,
    "warnings": warnings,

    "slot_generation": {
        "version": "rim_slot_v4_socket",
        "orientation": slot_metadata["slot_orientation"],
        "socket_mode": slot_metadata["socket_mode"],
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
    },

    "rim_features": {
        "slot_count": ...,
        "slot_style": ...,
        "slot_orientation": ...,
        "socket_mode": ...,
        "mouth_width_mm": ...,
        "throat_width_mm": ...,
        "lobe_width_mm": ...,
        "root_width_mm": ...,
        "slot_profile_points_xy": ...,
        "reference_only": True,
    },

    "visual_fidelity": {
        "target": "reference_turbine_rotor_disk",
        "contains_cyclic_rim_slots": True,
        "contains_axial_through_rim_slots": True,
        "contains_internal_lobe_socket_slots": True,
        "contains_hub_sleeve": ...,
        "contains_annular_details": ...,
        "contains_coverplate_interface": ...,
        "contains_real_blade_attachment": False,
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

Warnings 必须包含：

```text
axisymmetric_turbine_disk is non-flight reference geometry only.
Not airworthy, not certified, not manufacturing-ready, not for installation.
Fir-tree-like rim slots are visual/reference socket features only.
Rim slots are not certified blade attachment geometry.
No contact stress, centrifugal load path, fatigue life, burst margin, or thermal validation is performed.
Internal lobe socket geometry is only a visual approximation.
```

---

# 11. Metadata validator v4

修改：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
```

必须检查：

```text
1. geometry_family == axisymmetric_base_with_axial_fir_tree_socket_slots；
2. slot_generation.version == rim_slot_v4_socket；
3. slot_generation.orientation == axial_through；
4. slot_generation.socket_mode == internal_lobes；
5. opens_front_face is True；
6. opens_back_face is True；
7. opens_outer_diameter is True；
8. exposes_lobes_on_od is False；
9. z_min_mm < rim_z_min_mm；
10. z_max_mm > rim_z_max_mm；
11. profile_max_x_mm > outer_radius_mm；
12. profile_min_x_mm < outer_radius_mm；
13. rim_features.reference_only is True；
14. rim_features.slot_profile_points_xy 非空；
15. visual_fidelity.contains_internal_lobe_socket_slots is True；
16. visual_fidelity.contains_real_blade_attachment is False；
17. safety.not_for_installation is True；
18. safety.no_structural_validation is True；
19. safety.no_life_prediction is True。
```

示例：

```python
slot = metadata.get("slot_generation") or {}

if slot.get("version") != "rim_slot_v4_socket":
    errors.append("slot_generation.version must be rim_slot_v4_socket")

if slot.get("orientation") != "axial_through":
    errors.append("v4 rim slots must use axial_through orientation")

if slot.get("socket_mode") != "internal_lobes":
    errors.append("v4 fir-tree-like slots must use internal_lobes socket_mode")

if slot.get("exposes_lobes_on_od") is not False:
    errors.append("v4 socket slots must not expose lobes on outer diameter")

if not (float(slot.get("profile_max_x_mm", 0)) > float(slot.get("outer_radius_mm", 0))):
    errors.append("slot profile must extend beyond outer radius")

if not (float(slot.get("profile_min_x_mm", 0)) < float(slot.get("outer_radius_mm", 0))):
    errors.append("slot profile must cut inward from outer radius")
```

---

# 12. Mechanical validation v4

修改：

```text
src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
```

## 12.1 常量

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v4"

ALLOWED_KERNELS = {
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
    "cadquery_turbine_disk_reference_v3",
    "cadquery_turbine_disk_reference_v4",
}
```

demo expected kernel 必须为 v4。

## 12.2 必须新增检查

```text
1. expected_kernel mismatch fail；
2. geometry_family mismatch fail；
3. slot_generation.version != rim_slot_v4_socket fail；
4. slot_generation.orientation != axial_through fail；
5. slot_generation.socket_mode != internal_lobes fail；
6. exposes_lobes_on_od is not False fail；
7. opens_front_face/back_face/outer_diameter 任一不是 True fail；
8. z_min >= rim_z_min fail；
9. z_max <= rim_z_max fail；
10. profile_max_x <= outer_radius fail；
11. profile_min_x >= outer_radius fail；
12. rim_features.slot_count mismatch fail；
13. rim_features.slot_style mismatch fail；
14. visual_fidelity.contains_internal_lobe_socket_slots is not True fail；
15. visual_fidelity.contains_real_blade_attachment is not False fail；
16. safety.not_for_installation / no_structural_validation / no_life_prediction 缺失 fail。
```

## 12.3 reference_dimensions 也必须检查

必须包含：

```text
rim_slot_socket_mode
rim_slot_exposes_lobes_on_od
rim_slot_mouth_width_mm
rim_slot_throat_width_mm
rim_slot_lobe_width_mm
rim_slot_root_width_mm
```

---

# 13. Demo 更新

修改：

```text
demo_full_chain.py
```

`run_case_axisymmetric_turbine_disk()` 参数更新：

```python
"rim_slot_count": 60,
"rim_slot_style": "fir_tree_like",
"rim_slot_orientation": "axial_through",
"rim_slot_socket_mode": "internal_lobes",
"rim_slot_expose_lobes_on_od": False,

"rim_slot_depth_mm": 38.0,
"rim_slot_mouth_width_mm": 5.2,
"rim_slot_throat_width_mm": 4.5,
"rim_slot_lobe_width_mm": 9.0,
"rim_slot_lobe_depth_mm": 7.0,
"rim_slot_root_width_mm": 5.5,

"rim_slot_width_mm": 5.2,
"rim_slot_neck_width_mm": 4.5,

"rim_slot_axial_margin_mm": 0.0,
"rim_slot_through_clearance_mm": 2.0,
"rim_slot_outer_clearance_mm": 4.0,
```

primitive validation：

```python
"primitive_validation": {
    "primitive1": {
        "expected_kernel": "cadquery_turbine_disk_reference_v4",
        "expected_periodic_slot_count": 60,
        "expected_slot_orientation": "axial_through",
        "expected_slot_socket_mode": "internal_lobes",
        "expected_lobes_exposed_on_od": False,
    }
}
```

required metrics 增加：

```text
reference_dimensions.rim_slot_socket_mode
reference_dimensions.rim_slot_exposes_lobes_on_od
reference_dimensions.rim_slot_mouth_width_mm
reference_dimensions.rim_slot_throat_width_mm
reference_dimensions.rim_slot_lobe_width_mm
reference_dimensions.rim_slot_root_width_mm
reference_dimensions.rim_slot_opens_front_face
reference_dimensions.rim_slot_opens_back_face
reference_dimensions.rim_slot_opens_outer_diameter
reference_dimensions.rim_slot_profile_max_x_mm
reference_dimensions.rim_slot_profile_min_x_mm
```

---

# 14. Primitive compiler 要求

修改：

```text
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

保持 dispatcher 模式。

必须保证编译后的 script 只包含：

```python
from seekflow_engineering_tools.geometry_primitives.turbomachinery.axisymmetric_turbine_disk import (
    build_axisymmetric_turbine_disk_cadquery,
)

result, PRIMITIVE_METADATA["axisymmetric_turbine_disk"] = (
    build_axisymmetric_turbine_disk_cadquery(_params)
)
```

禁止 compiler 中出现：

```text
_fir_tree_internal_socket_profile_xy
_make_axial_through_slot_cutter
Workplane("XY").polyline
result.cut(rotated)
```

---

# 15. 测试计划

## 15.1 参数测试

文件：

```text
tests/test_axisymmetric_turbine_disk_parameters.py
```

新增测试：

```text
1. v4 fir_tree_like internal_lobes happy path normalize 成功；
2. rim_slot_expose_lobes_on_od=True 必须 fail；
3. mouth_width >= lobe_width 必须 fail；
4. throat_width >= lobe_width 必须 fail；
5. axial_through + axial_margin > 0 必须 fail；
6. through_clearance <= 0 必须 fail；
7. slot depth 过大 fail；
8. slot count 太小 fail；
9. lobe width 与 pitch overlap fail；
10. socket_mode 非法 fail。
```

## 15.2 Kernel visual tests

文件：

```text
tests/test_turbine_disk_visual_features.py
```

新增：

```python
def test_v4_slot_profile_has_narrow_od_mouth_and_internal_lobes():
    params = valid_v4_params()
    _, md = build_axisymmetric_turbine_disk_cadquery(params)

    pts = md["rim_features"]["slot_profile_points_xy"]
    slot = md["slot_generation"]

    assert slot["version"] == "rim_slot_v4_socket"
    assert slot["exposes_lobes_on_od"] is False
    assert slot["profile_max_x_mm"] > slot["outer_radius_mm"]
    assert slot["profile_min_x_mm"] < slot["outer_radius_mm"]

    mouth_w = md["rim_features"]["mouth_width_mm"]
    lobe_w = md["rim_features"]["lobe_width_mm"]

    assert mouth_w < lobe_w
```

新增：

```python
def test_v4_slot_z_range_through_rim():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v4_params())
    slot = md["slot_generation"]

    assert slot["z_min_mm"] < slot["rim_z_min_mm"]
    assert slot["z_max_mm"] > slot["rim_z_max_mm"]
    assert slot["opens_front_face"] is True
    assert slot["opens_back_face"] is True
```

新增：

```python
def test_v4_visual_flags_are_reference_only():
    _, md = build_axisymmetric_turbine_disk_cadquery(valid_v4_params())

    assert md["visual_fidelity"]["contains_internal_lobe_socket_slots"] is True
    assert md["visual_fidelity"]["contains_real_blade_attachment"] is False
    assert md["safety"]["not_for_installation"] is True
    assert md["safety"]["no_structural_validation"] is True
```

## 15.3 Metadata tests

文件：

```text
tests/test_axisymmetric_turbine_disk_metadata.py
```

新增：

```text
1. geometry_family v4 正确；
2. slot_generation.version 必须为 rim_slot_v4_socket；
3. exposes_lobes_on_od=True fail；
4. profile_max_x <= outer_radius fail；
5. profile_min_x >= outer_radius fail；
6. contains_internal_lobe_socket_slots 缺失 fail；
7. contains_real_blade_attachment=True fail。
```

## 15.4 Mechanical validation tests

文件：

```text
tests/test_axisymmetric_turbine_disk_mechanical_validation.py
```

新增：

```text
1. v4 happy path ok；
2. expected_kernel v4 mismatch fail；
3. socket_mode mismatch fail；
4. exposes_lobes_on_od=True fail；
5. mouth_width >= lobe_width fail；
6. front/back opening flag missing fail；
7. profile_max_x <= outer_radius fail；
8. profile_min_x >= outer_radius fail；
9. real_blade_attachment=True fail。
```

## 15.5 Compiler tests

文件：

```text
tests/test_axisymmetric_turbine_disk_compiler.py
```

新增：

```text
1. compiler dispatches to build_axisymmetric_turbine_disk_cadquery；
2. compiler script 不包含 _make_axial_through_slot_cutter；
3. compiler script 不包含 _fir_tree_internal_socket_profile_xy；
4. compiler script 不包含 Workplane("XY").polyline；
5. compiler script 不包含 result.cut(rotated)。
```

---

# 16. 验收命令

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

# 17. SolidWorks 视觉验收标准

生成模型必须满足：

```text
1. 外圆侧壁不再出现大片横向锯齿台阶；
2. 外圆入口为窄槽口；
3. fir-tree / dovetail 的内部 lobe 不直接暴露在外圆侧壁；
4. 前端面能看到完整 slot socket 截面；
5. 后端面能看到完整 slot socket 截面；
6. slot 沿 Z 方向贯穿 rim；
7. 相邻 slots 之间形成清晰 disk posts；
8. 整体不再像“厚法兰盘 + 外圆刻花”；
9. 仍然保留 hub sleeve、annular details、coverplate holes；
10. metadata 与 mechanical validation 全部通过。
```

---

# 18. Definition of Done

只有满足以下全部条件才算完成：

```text
1. KERNEL_NAME = cadquery_turbine_disk_reference_v4。
2. GEOMETRY_FAMILY = axisymmetric_base_with_axial_fir_tree_socket_slots。
3. models.py 注册所有 v4 slot 参数。
4. validator 拒绝 expose_lobes_on_od=True。
5. validator 要求 mouth_width < lobe_width。
6. validator 要求 throat_width < lobe_width。
7. validator 要求 axial_through + axial_margin == 0。
8. fir_tree_like 使用单一 polygon socket profile，不再使用多个 box union 作为主实现。
9. slot profile 外圆段保持窄 mouth。
10. lobe 只在内部展开。
11. cutter z_min < rim_z_min。
12. cutter z_max > rim_z_max。
13. profile max_x > outer_radius。
14. profile min_x < outer_radius。
15. metadata.slot_generation.version = rim_slot_v4_socket。
16. metadata.slot_generation.exposes_lobes_on_od = False。
17. metadata.rim_features.socket_mode = internal_lobes。
18. visual_fidelity.contains_internal_lobe_socket_slots = True。
19. visual_fidelity.contains_real_blade_attachment = False。
20. safety.not_for_installation = True。
21. safety.no_structural_validation = True。
22. mechanical validation 强制 demo expected_kernel = v4。
23. demo overall_ok=True。
24. compiler 仍只 dispatch deterministic kernel。
25. SolidWorks 局部外圆不再是横向锯齿台阶槽。
26. 现有 gear primitive 不被破坏。
27. 现有 recipe cases 不被破坏。
28. 所有新增测试通过。
```

---

# 19. 可直接交给 Claude Code 的最终 Prompt

```text
你现在在 seekflow-engineering 仓库中工作，重点目录：

integrations/engineering_tools/

用户最新反馈：axisymmetric_turbine_disk 的外缘卡榫/榫槽做得不对。最新 SolidWorks 局部截图显示，外圆侧壁出现一排横向台阶状、锯齿状的槽，像多个 box cutter 拼出来的侧壁刻槽；真实涡轮盘的 fir-tree/dovetail blade-root slot 不应该这样。正确的 reference geometry 应该是：外圆入口是窄喉口，内部 lobe/socket 在 rim 内部展开，fir-tree-like 截面主要在前后端面可见，并沿 Z 方向贯穿 rim。

最高约束：
1. primitive_name 保持 axisymmetric_turbine_disk。
2. KERNEL_NAME 升级为 cadquery_turbine_disk_reference_v4。
3. GEOMETRY_FAMILY 使用 axisymmetric_base_with_axial_fir_tree_socket_slots。
4. 不允许声称 flight-ready / airworthy / certified / manufacturing-ready / installable。
5. 不允许做真实航空发动机强度、寿命、转速、材料、适航设计。
6. fir_tree_like slot 只能是 visual/reference geometry。
7. 不允许把 slot 声称为 certified blade attachment。
8. primitive_compiler 只调用 deterministic kernel，不内联几何。
9. SolidWorks / NX 只能 import canonical STEP。
10. 所有失败必须 fail-closed。
11. 不得破坏 involute_spur_gear 和已有 recipe cases。

你必须修改：
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
新增/确认参数：
rim_slot_mouth_width_mm
rim_slot_throat_width_mm
rim_slot_root_width_mm
rim_slot_socket_mode
rim_slot_expose_lobes_on_od

默认：
rim_slot_style = "fir_tree_like"
rim_slot_orientation = "axial_through"
rim_slot_socket_mode = "internal_lobes"
rim_slot_expose_lobes_on_od = False
rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.5
rim_slot_lobe_width_mm = 9.0
rim_slot_root_width_mm = 5.5
rim_slot_depth_mm = 38.0
rim_slot_axial_margin_mm = 0.0
rim_slot_through_clearance_mm = 2.0
rim_slot_outer_clearance_mm = 4.0

supported_kernels 加入 cadquery_turbine_disk_reference_v4。

第二步：validator.py
新增：
ALLOWED_RIM_SLOT_SOCKET_MODES = {"simple_open_slot", "internal_lobes"}

_validate_rim_slots 必须检查：
- socket_mode 合法；
- fir_tree_like/internal_lobes 时 rim_slot_expose_lobes_on_od 必须 False；
- mouth_width > 0；
- throat_width > 0；
- lobe_width > 0；
- root_width > 0；
- mouth_width < lobe_width；
- throat_width < lobe_width；
- root_width <= lobe_width；
- axial_through 时 axial_margin == 0；
- axial_through 时 through_clearance > 0；
- slot pitch > lobe_width * 1.25；
- depth < 0.85 * rim radial thickness。

第三步：axisymmetric_turbine_disk.py
设置：
KERNEL_NAME = "cadquery_turbine_disk_reference_v4"
GEOMETRY_FAMILY = "axisymmetric_base_with_axial_fir_tree_socket_slots"

禁止继续用多个 box union 作为 fir_tree_like 主实现。

实现 polygon profile：
_fir_tree_internal_socket_profile_xy(params)

该 profile 必须满足：
- x0 = outer_radius + outer_clearance；
- x1 仍使用 mouth_width；
- lobe_width 只在内部 x3/x5 处出现；
- 外圆入口不暴露 lobe；
- mouth_width < lobe_width；
- profile max_x > outer_radius；
- profile min_x < outer_radius。

实现：
_make_axial_through_slot_cutter(cq, params, rim_z_min, rim_z_max)

要求：
- z_min = rim_z_min - through_clearance；
- z_max = rim_z_max + through_clearance；
- height = z_max - z_min；
- cq.Workplane("XY").polyline(profile).close().extrude(height).translate((0,0,z_min))；
- 返回 cutter_metadata，包括 profile_points_xy、z_min、z_max、max_x、min_x、outer_radius。

_cut_rim_slots：
- v4 demo 只支持 axial_through；
- 每个 slot rotate 后 result = result.cut(rotated)；
- 不允许 catch 异常后继续；
- 返回 slot_metadata；
- slot_metadata.exposes_lobes_on_od 必须 False。

第四步：metadata
metadata 必须包含：
kernel = cadquery_turbine_disk_reference_v4
geometry_family = axisymmetric_base_with_axial_fir_tree_socket_slots

slot_generation:
version = rim_slot_v4_socket
orientation = axial_through
socket_mode = internal_lobes
opens_front_face = True
opens_back_face = True
opens_outer_diameter = True
exposes_lobes_on_od = False
z_min_mm
z_max_mm
rim_z_min_mm
rim_z_max_mm
profile_max_x_mm
profile_min_x_mm
outer_radius_mm

rim_features:
slot_count
slot_style
slot_orientation
socket_mode
mouth_width_mm
throat_width_mm
lobe_width_mm
root_width_mm
slot_profile_points_xy
reference_only = True

visual_fidelity:
contains_internal_lobe_socket_slots = True
contains_real_blade_attachment = False

safety:
not_for_installation = True
no_structural_validation = True
no_life_prediction = True

第五步：metadata.py
validate_axisymmetric_turbine_disk_metadata 必须检查：
- geometry_family 正确；
- slot_generation.version == rim_slot_v4_socket；
- orientation == axial_through；
- socket_mode == internal_lobes；
- opens_front_face/back_face/outer_diameter 全 True；
- exposes_lobes_on_od is False；
- z_min < rim_z_min；
- z_max > rim_z_max；
- profile_max_x > outer_radius；
- profile_min_x < outer_radius；
- rim_features.reference_only is True；
- slot_profile_points_xy 非空；
- contains_internal_lobe_socket_slots is True；
- contains_real_blade_attachment is False；
- safety.not_for_installation / no_structural_validation / no_life_prediction 全 True。

第六步：turbomachinery_validation.py
KERNEL_NAME 升级为 cadquery_turbine_disk_reference_v4。
ALLOWED_KERNELS 包含 v0/v2/v3/v4，但 demo expected_kernel 必须强制 v4。

mechanical validation 必须检查：
- expected_kernel mismatch fail；
- geometry_family mismatch fail；
- slot_generation.version != rim_slot_v4_socket fail；
- socket_mode != internal_lobes fail；
- exposes_lobes_on_od is not False fail；
- opens_front/back/outer 任一不是 True fail；
- z_min >= rim_z_min fail；
- z_max <= rim_z_max fail；
- profile_max_x <= outer_radius fail；
- profile_min_x >= outer_radius fail；
- visual_fidelity.contains_internal_lobe_socket_slots 不是 True fail；
- visual_fidelity.contains_real_blade_attachment 不是 False fail；
- safety.not_for_installation / no_structural_validation / no_life_prediction 缺失 fail。

第七步：demo_full_chain.py
参数加入：
rim_slot_socket_mode = "internal_lobes"
rim_slot_expose_lobes_on_od = False
rim_slot_mouth_width_mm = 5.2
rim_slot_throat_width_mm = 4.5
rim_slot_lobe_width_mm = 9.0
rim_slot_root_width_mm = 5.5

primitive_validation.expected_kernel 改为 cadquery_turbine_disk_reference_v4。

required metrics 加入：
reference_dimensions.rim_slot_socket_mode
reference_dimensions.rim_slot_exposes_lobes_on_od
reference_dimensions.rim_slot_mouth_width_mm
reference_dimensions.rim_slot_throat_width_mm
reference_dimensions.rim_slot_lobe_width_mm
reference_dimensions.rim_slot_root_width_mm
reference_dimensions.rim_slot_profile_max_x_mm
reference_dimensions.rim_slot_profile_min_x_mm

第八步：primitive_compiler.py
保持 dispatcher。编译脚本不能出现：
_fir_tree_internal_socket_profile_xy
_make_axial_through_slot_cutter
Workplane("XY").polyline
result.cut(rotated)

第九步：测试
必须新增/更新：
1. v4 fir_tree_like internal_lobes happy path；
2. expose_lobes_on_od=True fail；
3. mouth_width >= lobe_width fail；
4. throat_width >= lobe_width fail；
5. axial_through + axial_margin > 0 fail；
6. slot profile max_x > outer_radius；
7. slot profile min_x < outer_radius；
8. z_min < rim_z_min；
9. z_max > rim_z_max；
10. slot_generation.version == rim_slot_v4_socket；
11. contains_internal_lobe_socket_slots=True；
12. contains_real_blade_attachment=False；
13. compiler only dispatches to kernel；
14. demo expected_kernel=v4。

运行：
cd integrations/engineering_tools
python -m pytest tests -q
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery

完成后输出：
1. 修改文件清单；
2. v4 参数清单；
3. fir-tree socket profile 说明；
4. metadata v4 字段说明；
5. 测试结果；
6. demo 结果；
7. 如果 SolidWorks 外圆侧壁仍出现横向台阶锯齿槽，不得声称完成，必须说明原因。
```
