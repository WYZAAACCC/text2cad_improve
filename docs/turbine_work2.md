
# SeekFlow Engineering：涡轮盘 Primitive v0.2 真实感改进实施文档

## 0. 本次任务目标

当前 `axisymmetric_turbine_disk` 已经能生成一个带中心孔、螺栓孔、减重孔、冷却孔的轴对称盘体，但从视觉和结构语义上看，它更像“平面法兰盘 / 带孔圆盘”，不像涡轮转子盘。

本次任务目标是把它升级为：

```text
axisymmetric_turbine_disk v0.2
```

或者在代码中保持 primitive name 不变：

```text
primitive_name = "axisymmetric_turbine_disk"
```

但 kernel 升级为：

```text
kernel = "cadquery_turbine_disk_reference_v2"
```

核心目标：

```text
1. 保持 SeekFlow primitive 架构不变；
2. 保持 deterministic kernel；
3. 不让 LLM 生成 CAD 代码；
4. 不做真实航空强度/寿命/适航/制造设计；
5. 明显增强涡轮盘外观真实感；
6. 增加 rim blade-root slot / fir-tree-like slot / dovetail-like slot 的参考几何；
7. 增加中心筒状 hub / shaft sleeve；
8. 增加前后端台阶、rabbet、seal land、coverplate interface；
9. 增加环形槽、台阶圆角、倒角；
10. 增加可选 split-line / coverplate bolt ring / balance holes；
11. metadata 与 validation 同步升级；
12. demo 输出必须比当前图 3 明显更像真实涡轮盘。
```

本次仍然禁止：

```text
1. 不允许声称 flight-ready；
2. 不允许声称 airworthy；
3. 不允许声称 certified；
4. 不允许声称 manufacturing-ready；
5. 不允许声称 installable；
6. 不允许做真实 fir-tree 强度设计；
7. 不允许做真实叶片连接接触分析；
8. 不允许做真实冷却流路设计；
9. 不允许做材料、转速、寿命、爆盘、低周疲劳、热应力判断；
10. 不允许输出制造图纸；
11. 不允许给真实航空发动机装机建议。
```

所有 metadata / warnings / skill contract 中都必须继续声明：

```text
non-flight reference geometry only
not airworthy
not certified
not for manufacturing
not for installation
```

---

# 1. 当前代码问题诊断

当前 `axisymmetric_turbine_disk.py` 的问题不是链路问题，而是几何特征层级不够。

当前几何大致是：

```text
1. 一个 revolve profile；
2. hub / web / rim 三段台阶；
3. 中心孔；
4. 三圈 Z 方向圆孔；
5. 没有外缘 blade-root slots；
6. 没有 rim posts；
7. 没有筒状前伸 hub / shaft sleeve；
8. 没有 seal teeth / seal land；
9. 没有 coverplate rabbet / bayonet / retaining lip；
10. 没有环形槽；
11. 没有前后端非对称台阶；
12. 没有外缘厚重 rim；
13. 没有真实涡轮盘常见的“盘齿”轮廓。
```

所以 SolidWorks 结果看起来像：

```text
普通圆盘 + 法兰孔 + 中心孔
```

而不是：

```text
带外缘叶根槽、厚 rim、中心轴颈、台阶 hub、环形密封/挡圈结构的涡轮转子盘。
```

结论：

```text
如果继续只做 axisymmetric revolve，无论参数怎么调，都不会像你给的真实图。
```

原因：

```text
真实涡轮盘最显著的视觉特征往往不是轴对称截面，而是外缘圆周周期结构：
- blade-root slots；
- fir-tree / dovetail-like slots；
- rim posts；
- cooling slots；
- retainer / coverplate features；
- seal lands；
- balance holes；
- front/back asymmetric hub sleeve。
```

因此 v0.2 必须在原有 revolve 基体之上增加：

```text
cyclic rim feature pattern
```

也就是：

```text
revolved disk body
+ polar array subtractive slots
+ optional rim post relief
+ optional coverplate / seal geometry
```

---

# 2. 设计方向：不要再做“平盘”，要做“参考涡轮转子盘”

## 2.1 新 primitive 语义

建议继续保留旧 primitive name：

```text
axisymmetric_turbine_disk
```

原因：

```text
1. 不破坏已有 CAD-IR；
2. 不破坏 demo；
3. 不破坏 tests；
4. 不破坏 capability registry；
5. 仍可把主盘体视为 axisymmetric base body。
```

但 metadata 中要明确：

```text
kernel = "cadquery_turbine_disk_reference_v2"
geometry_family = "axisymmetric_base_with_cyclic_rim_features"
```

也就是说：

```text
primitive 名字保持兼容；
实际 kernel 升级为“轴对称基体 + 周期外缘特征”。
```

如果希望语义更严格，后续可以新增：

```text
turbine_rotor_disk_reference
```

但本次不要引入新 primitive name，避免扩大改动范围。

---

# 3. v0.2 几何目标

v0.2 输出应具备以下视觉特征。

## 3.1 外缘 blade-root slot / fir-tree-like slot ring

这是最重要的改动。

真实参考图最明显的特征是外缘一圈密集的“盘齿”或“榫槽”。当前模型完全没有这一层，所以不像。

v0.2 应实现：

```text
rim_slot_count
rim_slot_depth_mm
rim_slot_width_mm
rim_slot_neck_width_mm
rim_slot_lobe_width_mm
rim_slot_lobe_depth_mm
rim_slot_axial_margin_mm
rim_slot_style
```

支持：

```text
rim_slot_style = "rectangular"
rim_slot_style = "dovetail"
rim_slot_style = "fir_tree_like"
```

v0.2 推荐默认：

```text
rim_slot_style = "fir_tree_like"
```

但必须声明：

```text
This is a visual/reference fir-tree-like slot pattern, not a certified blade attachment.
```

视觉目标：

```text
1. 外圆不再是光滑圆；
2. 外缘形成均匀 rim posts；
3. 从正面看有很多黑色/贯穿槽；
4. 从斜视图看外缘像真实 turbine disk rim；
5. slot 数量建议 48–80，默认 60；
6. slot 深度建议占 rim radial thickness 的 35%–60%；
7. slot 不得切穿 web；
8. slot 不得破坏中心盘体。
```

## 3.2 厚 rim + rim front/back lips

真实涡轮盘外缘 rim 往往比 web 更厚，且前后端有挡边、台阶、ring land。

v0.2 应增加：

```text
rim_front_lip_height_mm
rim_back_lip_height_mm
rim_lip_radial_width_mm
rim_lip_axial_width_mm
outer_rim_band_width_mm
```

视觉目标：

```text
1. 外缘看起来厚重；
2. 前端有明显 rim lip；
3. 后端可有较小 lip；
4. rim 与 web 不再只是薄平面连接。
```

## 3.3 中心筒状 hub / shaft sleeve

真实图中中心不是简单孔，而是有一个向前突出的筒状轴颈或 hub sleeve。

v0.2 应增加：

```text
front_hub_sleeve_outer_dia_mm
front_hub_sleeve_inner_dia_mm
front_hub_sleeve_height_mm
front_hub_sleeve_wall_mm
front_hub_sleeve_chamfer_mm

rear_hub_sleeve_outer_dia_mm
rear_hub_sleeve_inner_dia_mm
rear_hub_sleeve_height_mm
```

默认可以只生成 front sleeve：

```text
front_hub_sleeve_height_mm > 0
rear_hub_sleeve_height_mm = 0
```

视觉目标：

```text
1. 中心孔不再只是平盘开孔；
2. 前端有明显竖直筒；
3. 筒口有倒角；
4. 筒根部有台阶法兰；
5. hub sleeve 与盘体之间有过渡圆角/台阶。
```

## 3.4 环形台阶、沟槽、rabbet、seal land

真实图中盘面有多圈细环、台阶和槽，而当前模型盘面过于平滑。

v0.2 应增加：

```text
annular_groove_count
annular_groove_specs
seal_land_count
seal_land_specs
rabbet_count
rabbet_specs
```

为了参数不要过度复杂，v0.2 可先固定 3 组典型环形特征：

```text
inner_hub_step
mid_web_recess
outer_rim_recess
```

参数：

```text
inner_hub_step_outer_dia_mm
inner_hub_step_height_mm

mid_web_recess_inner_dia_mm
mid_web_recess_outer_dia_mm
mid_web_recess_depth_mm

outer_rim_recess_inner_dia_mm
outer_rim_recess_outer_dia_mm
outer_rim_recess_depth_mm
```

视觉目标：

```text
1. 盘面不再是一个大平面；
2. 中心到外缘有清晰分层；
3. hub → web → rim 有台阶过渡；
4. 图像上能看到真实加工件那种 concentric rings。
```

## 3.5 Coverplate / retainer bolt ring

真实盘上经常有小螺钉、小孔、挡圈或 coverplate interface。当前 demo 有三圈孔，但分布比较像普通法兰。

v0.2 应区分孔的语义：

```text
coverplate_bolt_count
coverplate_bolt_pcd_mm
coverplate_bolt_dia_mm

balance_hole_count
balance_hole_pcd_mm
balance_hole_dia_mm

inspection_hole_count
inspection_hole_pcd_mm
inspection_hole_dia_mm
```

建议：

```text
coverplate_bolt_count = 18 或 24
balance_hole_count = 8 或 12
inspection_hole_count = 0 或 6
```

视觉目标：

```text
1. 小孔更多，靠近 hub 或 mid web；
2. 大孔数量较少，位于中间 web；
3. 外缘小冷却孔或 balance holes 更密。
```

## 3.6 可选 cooling slot / scallop

除了圆孔，还应支持外缘附近的径向细槽：

```text
rim_cooling_slot_count
rim_cooling_slot_width_mm
rim_cooling_slot_depth_mm
rim_cooling_slot_style
```

v0.2 可以先实现简单 rectangular radial slot：

```text
rim_cooling_slot_style = "rectangular"
```

它不是实际冷却流道，只是 reference visual feature。

---

# 4. 参数表升级

当前参数表保留，但新增 v0.2 参数。

## 4.1 保留旧参数

必须保留：

```text
outer_dia_mm
bore_dia_mm
axial_width_mm

hub_outer_dia_mm
web_outer_dia_mm
rim_inner_dia_mm

hub_width_mm
web_width_mm
rim_width_mm

hub_fillet_radius_mm
web_fillet_radius_mm
rim_fillet_radius_mm
edge_chamfer_mm

bolt_hole_count
bolt_pcd_mm
bolt_hole_dia_mm
bolt_hole_axis

lightening_hole_count
lightening_hole_pcd_mm
lightening_hole_dia_mm
lightening_hole_axis

cooling_hole_count
cooling_hole_pcd_mm
cooling_hole_dia_mm
cooling_hole_axis

quality_grade
non_flight_reference_only
```

## 4.2 新增外缘 slot 参数

新增：

```text
rim_slot_count
rim_slot_style
rim_slot_depth_mm
rim_slot_width_mm
rim_slot_neck_width_mm
rim_slot_lobe_width_mm
rim_slot_lobe_depth_mm
rim_slot_axial_margin_mm
rim_slot_root_fillet_mm
rim_slot_tip_chamfer_mm
```

默认：

```text
rim_slot_count = 60
rim_slot_style = "fir_tree_like"
rim_slot_depth_mm = 35.0
rim_slot_width_mm = 7.0
rim_slot_neck_width_mm = 4.5
rim_slot_lobe_width_mm = 8.5
rim_slot_lobe_depth_mm = 7.0
rim_slot_axial_margin_mm = 4.0
rim_slot_root_fillet_mm = 0.5
rim_slot_tip_chamfer_mm = 0.3
```

允许：

```text
rim_slot_style in {"none", "rectangular", "dovetail", "fir_tree_like"}
```

如果：

```text
rim_slot_style = "none"
```

则：

```text
rim_slot_count = 0
```

## 4.3 新增中心 hub sleeve 参数

新增：

```text
front_hub_sleeve_outer_dia_mm
front_hub_sleeve_inner_dia_mm
front_hub_sleeve_height_mm
front_hub_sleeve_wall_mm
front_hub_sleeve_chamfer_mm

rear_hub_sleeve_outer_dia_mm
rear_hub_sleeve_inner_dia_mm
rear_hub_sleeve_height_mm
```

默认：

```text
front_hub_sleeve_outer_dia_mm = 150.0
front_hub_sleeve_inner_dia_mm = 80.0
front_hub_sleeve_height_mm = 55.0
front_hub_sleeve_wall_mm = 8.0
front_hub_sleeve_chamfer_mm = 2.0

rear_hub_sleeve_outer_dia_mm = 0.0
rear_hub_sleeve_inner_dia_mm = 0.0
rear_hub_sleeve_height_mm = 0.0
```

## 4.4 新增环形台阶/槽参数

新增：

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

默认：

```text
enable_annular_details = True

inner_hub_step_outer_dia_mm = 180.0
inner_hub_step_height_mm = 8.0

mid_web_recess_inner_dia_mm = 220.0
mid_web_recess_outer_dia_mm = 360.0
mid_web_recess_depth_mm = 3.0

outer_rim_recess_inner_dia_mm = 390.0
outer_rim_recess_outer_dia_mm = 450.0
outer_rim_recess_depth_mm = 2.0

seal_land_count = 2
seal_land_height_mm = 2.0
seal_land_width_mm = 3.0
seal_land_start_dia_mm = 155.0
seal_land_pitch_mm = 8.0
```

## 4.5 新增 coverplate / balance hole 参数

新增：

```text
coverplate_bolt_count
coverplate_bolt_pcd_mm
coverplate_bolt_dia_mm

balance_hole_count
balance_hole_pcd_mm
balance_hole_dia_mm
```

默认：

```text
coverplate_bolt_count = 18
coverplate_bolt_pcd_mm = 170.0
coverplate_bolt_dia_mm = 4.0

balance_hole_count = 10
balance_hole_pcd_mm = 310.0
balance_hole_dia_mm = 18.0
```

---

# 5. 文件修改清单

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
integrations/engineering_tools/tests/test_demo_full_chain_turbine_disk.py
integrations/engineering_tools/tests/test_turbine_disk_visual_features.py
```

---

# 6. 代码风格要求

当前一些文件在 raw view 中呈现为单行压缩格式，维护性很差。Claude Code 必须把本次涉及文件重新格式化为正常 Python 风格。

要求：

```text
1. 每个 import 独立成行；
2. 每个函数正常换行；
3. 每个 dict/list 不要压缩成一行；
4. 通过 ruff/black 风格；
5. 不要把复杂几何逻辑写在 primitive_compiler.py；
6. primitive_compiler.py 只负责调用 kernel；
7. kernel 文件负责几何；
8. validator.py 负责参数约束；
9. metadata.py 负责 metadata 结构检查；
10. mechanical_validation 负责结果验证。
```

---

# 7. v0.2 几何实现方案

## 7.1 总体建模流程

新的 kernel 应按以下顺序建模：

```text
1. normalize / read params；
2. build revolved base body；
3. add front hub sleeve；
4. add optional rear hub sleeve；
5. add annular raised steps；
6. cut annular recesses；
7. cut old hole rings；
8. cut coverplate bolt ring；
9. cut balance hole ring；
10. cut rim blade-root slots；
11. optionally cut rim cooling slots；
12. apply conservative chamfers；
13. build metadata；
14. return result, metadata。
```

不要一开始就 fillet 全部边。复杂 boolean 后全局 fillet 很容易失败。v0.2 可以只做：

```text
small chamfer on visible outer sleeve lip
small chamfer on outer rim edge
optional slot tip chamfer
```

如果 chamfer 失败，必须抛异常或写入 error，不要 silently pass。

---

## 7.2 Base revolve profile 改进

当前 profile 太简单，建议改成更有层次的 profile。

仍然用 XZ 截面：

```text
X = radius
Z = axial coordinate
```

新的 profile 应该体现：

```text
1. thick hub；
2. thin web；
3. thick rim；
4. asymmetric front/rear face；
5. rim lip；
6. hub root shoulder。
```

建议 helper：

```python
def _build_base_profile(params: dict) -> list[tuple[float, float]]:
    ...
```

示意 profile：

```python
profile_points = [
    (r_bore, -t_hub),
    (r_hub_inner_shoulder, -t_hub),
    (r_hub_inner_shoulder, -t_hub + hub_back_step),
    (r_hub, -t_web),
    (r_web, -t_web),
    (r_rim_inner, -t_rim),
    (r_outer, -t_rim),
    (r_outer, t_rim),
    (r_rim_inner, t_rim),
    (r_web, t_web),
    (r_hub, t_web),
    (r_hub_inner_shoulder, t_hub - hub_front_step),
    (r_hub_inner_shoulder, t_hub),
    (r_bore, t_hub),
]
```

必须保证：

```text
bbox X ≈ outer_dia_mm
bbox Y ≈ outer_dia_mm
bbox Z ≈ axial_width_mm + front_hub_sleeve_height_mm + rear_hub_sleeve_height_mm
```

因此 v0.2 的 expected bbox 需要更新。

---

## 7.3 Hub sleeve 实现

新增 helper：

```python
def _add_front_hub_sleeve(result, params):
    ...
```

实现思路：

```text
1. 在 front face 上创建圆筒；
2. outer diameter = front_hub_sleeve_outer_dia_mm；
3. inner diameter = front_hub_sleeve_inner_dia_mm；
4. height = front_hub_sleeve_height_mm；
5. 与盘体 fuse；
6. 中心孔贯通。
```

CadQuery 推荐：

```python
sleeve = (
    cq.Workplane("XY")
    .circle(front_outer / 2.0)
    .circle(front_inner / 2.0)
    .extrude(front_height)
    .translate((0, 0, base_front_z))
)
result = result.union(sleeve)
```

注意：

```text
base_front_z = axial_width_mm / 2
```

如果当前坐标方向相反，测试要以 bbox 和视觉为准调整。

再给 sleeve 口部增加可选 chamfer：

```python
if front_hub_sleeve_chamfer_mm > 0:
    result = result.edges(">Z").chamfer(front_hub_sleeve_chamfer_mm)
```

如果 `edges(">Z")` 过宽导致错误，改为不做 chamfer，但要在 metadata warnings 中写：

```text
front hub sleeve chamfer skipped by v0.2 kernel
```

不要因为 chamfer 失败导致基础模型不可用，除非测试明确要求 fail-closed。

---

## 7.4 Annular recess / raised ring 实现

建议实现两个 helper：

```python
def _add_annular_raised_ring(result, inner_dia, outer_dia, height, z_face):
    ...

def _cut_annular_recess(result, inner_dia, outer_dia, depth, z_face):
    ...
```

### Raised ring

用于：

```text
inner_hub_step
seal_land
rim lip
```

实现：

```python
ring = (
    cq.Workplane("XY")
    .circle(outer_dia / 2.0)
    .circle(inner_dia / 2.0)
    .extrude(height)
    .translate((0, 0, z_face))
)
result = result.union(ring)
```

### Recess

用于：

```text
mid_web_recess
outer_rim_recess
```

实现：

```python
result = (
    result.faces(">Z")
    .workplane(centerOption="CenterOfBoundBox")
    .circle(outer_dia / 2.0)
    .circle(inner_dia / 2.0)
    .cutBlind(-depth)
)
```

或者更稳：

```python
cutter = (
    cq.Workplane("XY")
    .circle(outer_dia / 2.0)
    .circle(inner_dia / 2.0)
    .extrude(depth * 1.2)
    .translate((0, 0, z_face - depth))
)
result = result.cut(cutter)
```

v0.2 推荐用 cutter solids，避免 face selector 不稳定。

---

# 8. Rim slot / fir-tree-like slot 实现重点

## 8.1 不能再只做圆孔

外缘 slot 是本轮最关键。

新增 helper：

```python
def _cut_rim_slots(result, params):
    ...
```

## 8.2 简化几何策略

真实 fir-tree 是复杂多 lobes 曲线。v0.2 不做真实承载形状，只做 reference visual approximation。

可实现三种 style：

```text
rectangular:
  简单径向矩形槽；

dovetail:
  外窄内宽或外宽内窄梯形槽；

fir_tree_like:
  由 neck + two lobes + root pocket 组合而成的多段槽。
```

推荐先实现：

```text
rectangular
fir_tree_like
```

`dovetail` 可映射到 simplified trapezoid。

## 8.3 CadQuery 方案 A：切单个 slot cutter，然后 polar array cut

对每个 slot，构造一个局部 cutter solid：

```text
slot 位于 +X 方向；
slot 从 r_outer 向内切入 rim_slot_depth_mm；
slot 在切向方向有宽度；
slot 轴向贯穿 rim_width_mm - 2 * rim_slot_axial_margin_mm。
```

因为 CadQuery 直接构造复杂局部坐标 polyline 再旋转阵列比较麻烦，建议使用矩形 box cutter 近似：

```python
def _make_rectangular_rim_slot_cutter(params):
    slot_depth = params["rim_slot_depth_mm"]
    slot_width = params["rim_slot_width_mm"]
    slot_axial = params["rim_width_mm"] - 2 * params["rim_slot_axial_margin_mm"]

    r_outer = params["outer_dia_mm"] / 2
    center_x = r_outer - slot_depth / 2

    cutter = (
        cq.Workplane("XY")
        .box(slot_depth, slot_width, slot_axial, centered=True)
        .translate((center_x, 0, 0))
    )
    return cutter
```

然后：

```python
for i in range(count):
    angle = 360.0 * i / count
    rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
    result = result.cut(rotated)
```

这个方式稳定、可读、可测试。

## 8.4 Fir-tree-like cutter 方案

用多个 box 叠加成一个 cutter：

```text
1. outer mouth cutter；
2. neck cutter；
3. lobe cutter 1；
4. lobe cutter 2；
5. root pocket cutter。
```

在 +X 方向创建：

```python
def _make_fir_tree_like_slot_cutter(params):
    r_outer = outer_dia / 2
    depth = rim_slot_depth_mm
    axial = rim_width_mm - 2 * rim_slot_axial_margin_mm

    neck_w = rim_slot_neck_width_mm
    lobe_w = rim_slot_lobe_width_mm
    lobe_depth = rim_slot_lobe_depth_mm
    mouth_w = rim_slot_width_mm

    cutters = []

    # mouth near outer radius
    cutters.append(box(depth * 0.25, mouth_w, axial, center_x=r_outer - depth * 0.125))

    # narrow neck
    cutters.append(box(depth * 0.45, neck_w, axial, center_x=r_outer - depth * 0.45))

    # first lobe
    cutters.append(box(lobe_depth, lobe_w, axial, center_x=r_outer - depth * 0.55))

    # second inner pocket
    cutters.append(box(lobe_depth, lobe_w * 0.9, axial, center_x=r_outer - depth * 0.82))

    # root pocket
    cutters.append(box(depth * 0.18, neck_w * 1.2, axial, center_x=r_outer - depth * 0.94))

    cutter = cutters[0]
    for c in cutters[1:]:
        cutter = cutter.union(c)

    return cutter
```

为了避免 sharp corners，可选对 cutter 做小 fillet，但 fillet 失败风险高，先不做。

这种形状不是承载用真实 fir-tree，但视觉上会形成“外缘多段槽 + 盘齿”的效果，比纯圆盘明显更真实。

## 8.5 Slot validation

validator 必须新增：

```text
rim_slot_count >= 0
rim_slot_style in allowed set
if style == "none": rim_slot_count == 0
if rim_slot_count > 0:
    rim_slot_count >= 12
    rim_slot_depth_mm > 0
    rim_slot_width_mm > 0
    rim_slot_depth_mm < outer_radius - rim_inner_radius
    rim_slot_depth_mm <= 0.75 * rim radial thickness
    slot tangential pitch > rim_slot_width_mm * 1.2
    axial slot width < rim_width_mm
    rim_slot_axial_margin_mm >= 0
```

计算：

```python
r_outer = outer_dia_mm / 2
r_rim_inner = rim_inner_dia_mm / 2
rim_radial_thickness = r_outer - r_rim_inner
slot_pitch = 2 * math.pi * r_outer / rim_slot_count
```

约束：

```python
if rim_slot_depth_mm >= rim_radial_thickness * 0.8:
    errors.append("rim_slot_depth_mm too large; would cut through rim into web")

if slot_pitch <= rim_slot_width_mm * 1.2:
    errors.append("rim_slot_width_mm too large for rim_slot_count")
```

---

# 9. 更新 metadata

metadata 必须新增 v0.2 字段。

## 9.1 reference_dimensions 扩展

新增：

```text
rim_slot_count
rim_slot_style
rim_slot_depth_mm
rim_slot_width_mm
front_hub_sleeve_outer_dia_mm
front_hub_sleeve_inner_dia_mm
front_hub_sleeve_height_mm
coverplate_bolt_count
balance_hole_count
visual_feature_count
expected_periodic_slot_count
```

其中：

```text
expected_periodic_slot_count = rim_slot_count
visual_feature_count = rim_slot_count + coverplate_bolt_count + balance_hole_count + old hole counts
```

## 9.2 新增 metadata 结构

metadata 新增：

```json
{
  "geometry_family": "axisymmetric_base_with_cyclic_rim_features",
  "visual_fidelity": {
    "target": "reference_turbine_rotor_disk",
    "contains_cyclic_rim_slots": true,
    "contains_hub_sleeve": true,
    "contains_annular_details": true,
    "contains_coverplate_interface": true,
    "contains_real_blade_attachment": false
  },
  "rim_features": {
    "slot_count": 60,
    "slot_style": "fir_tree_like",
    "slot_depth_mm": 35.0,
    "slot_width_mm": 7.0,
    "reference_only": true
  },
  "hub_sleeve": {
    "front_enabled": true,
    "rear_enabled": false,
    "front_outer_dia_mm": 150.0,
    "front_inner_dia_mm": 80.0,
    "front_height_mm": 55.0
  },
  "annular_details": {
    "enabled": true,
    "mid_web_recess": true,
    "outer_rim_recess": true,
    "seal_lands": 2
  }
}
```

warnings 必须新增：

```text
Rim slots are visual/reference fir-tree-like features only.
They are not certified blade attachment geometry.
No contact stress, centrifugal load path, fatigue life, or burst margin is validated.
```

---

# 10. 更新 mechanical validation

`validate_axisymmetric_turbine_disk_result()` 必须新增检查。

## 10.1 必须检查 metadata

新增检查：

```text
metadata.kernel == "cadquery_turbine_disk_reference_v2"
metadata.geometry_family == "axisymmetric_base_with_cyclic_rim_features"
metadata.visual_fidelity.contains_cyclic_rim_slots is True when rim_slot_count > 0
metadata.visual_fidelity.contains_real_blade_attachment is False
metadata.rim_features.slot_count == params.rim_slot_count
metadata.hub_sleeve.front_height_mm == params.front_hub_sleeve_height_mm
metadata.safety flags all True
```

## 10.2 必须检查 reference dimensions

新增：

```text
reference_dimensions.rim_slot_count == params.rim_slot_count
reference_dimensions.front_hub_sleeve_height_mm == params.front_hub_sleeve_height_mm
reference_dimensions.expected_periodic_slot_count == params.rim_slot_count
```

## 10.3 bbox 更新

因为 front sleeve 会增加 Z 高度，expected bbox 不能再是：

```text
[outer_dia, outer_dia, axial_width]
```

而应是：

```text
[
  outer_dia_mm,
  outer_dia_mm,
  axial_width_mm + front_hub_sleeve_height_mm + rear_hub_sleeve_height_mm
]
```

但注意：

```text
如果 rim slots 是 subtractive，不改变 outer_dia；
如果 annular raised rings 在 Z 方向增加高度，也要计入 bbox。
```

建议 metadata 中写：

```text
expected_bbox_mm
```

由 kernel 根据参数计算，demo 直接引用同样计算公式，避免手写错。

---

# 11. 更新 demo case

当前 demo 参数太像平盘。必须改为“真实感”参数。

建议 demo 参数：

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
    "rim_slot_depth_mm": 38.0,
    "rim_slot_width_mm": 7.0,
    "rim_slot_neck_width_mm": 4.5,
    "rim_slot_lobe_width_mm": 8.5,
    "rim_slot_lobe_depth_mm": 7.0,
    "rim_slot_axial_margin_mm": 5.0,
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

    "balance_hole_count": 0,
    "balance_hole_pcd_mm": 0.0,
    "balance_hole_dia_mm": 0.0,

    "quality_grade": "engineering_reference",
    "non_flight_reference_only": True,
}
```

注意：

```text
不要同时保留太多大孔，否则视觉会像法兰。
真实感 demo 应减少“法兰大孔”，增加 rim slot + sleeve + annular details。
```

---

# 12. 新增 visual acceptance tests

新增：

```text
tests/test_turbine_disk_visual_features.py
```

不需要做图像识别，但要测试 metadata 和几何语义。

必须测试：

```python
def test_turbine_disk_v2_has_rim_slots_in_metadata():
    ...

def test_turbine_disk_v2_has_hub_sleeve_in_metadata():
    ...

def test_turbine_disk_v2_expected_bbox_includes_front_sleeve():
    ...

def test_turbine_disk_v2_rejects_slot_depth_that_cuts_into_web():
    ...

def test_turbine_disk_v2_rejects_too_many_wide_slots():
    ...

def test_turbine_disk_v2_visual_fidelity_flags_reference_only():
    ...
```

如果测试环境有 CadQuery，则增加：

```python
def test_turbine_disk_v2_builds_cadquery_shape():
    ...

def test_turbine_disk_v2_bbox_is_reasonable():
    ...
```

---

# 13. 具体代码改造建议

## 13.1 `models.py`

在 `AXISYMMETRIC_TURBINE_DISK.parameters` 中追加新增参数。

新增参数时必须使用现有 `PrimitiveParameter` 格式。

示例：

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
    name="rim_slot_depth_mm",
    type="float",
    unit="mm",
    required=False,
    default=35.0,
    min_value=0.0,
),
```

将 supported kernel 改为包含新旧两个：

```python
supported_kernels=[
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
]
```

或者直接改为：

```python
supported_kernels=["cadquery_turbine_disk_reference_v2"]
```

但如果已有测试强依赖旧 kernel，优先保留两者，并让新 metadata 使用 v2 kernel。

---

## 13.2 `validator.py`

新增：

```python
ALLOWED_RIM_SLOT_STYLES = {
    "none",
    "rectangular",
    "dovetail",
    "fir_tree_like",
}
```

新增函数：

```python
def _validate_rim_slots(errors: list[str], params: dict) -> None:
    ...
```

新增函数：

```python
def _validate_hub_sleeve(errors: list[str], params: dict) -> None:
    ...
```

新增函数：

```python
def _validate_annular_details(errors: list[str], params: dict) -> None:
    ...
```

在 `validate_axisymmetric_turbine_disk_parameters()` 末尾调用。

---

## 13.3 `axisymmetric_turbine_disk.py`

必须拆分函数，不要继续写一个长函数。

建议结构：

```python
KERNEL_NAME = "cadquery_turbine_disk_reference_v2"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"

def _get_float(params, key): ...
def _get_int(params, key): ...
def _get_bool(params, key): ...

def _build_base_body(cq, params):
    ...

def _add_front_hub_sleeve(cq, result, params):
    ...

def _add_rear_hub_sleeve(cq, result, params):
    ...

def _add_annular_details(cq, result, params):
    ...

def _cut_hole_ring(result, *, count, pcd_mm, hole_dia_mm, axis, z_face="front"):
    ...

def _make_rectangular_rim_slot_cutter(cq, params):
    ...

def _make_fir_tree_like_slot_cutter(cq, params):
    ...

def _cut_rim_slots(cq, result, params):
    ...

def _reference_dimensions(params):
    ...

def _metadata(params, profile_points, warnings):
    ...

def build_axisymmetric_turbine_disk_cadquery(params):
    import cadquery as cq

    result, profile_points = _build_base_body(cq, params)
    result = _add_front_hub_sleeve(cq, result, params)
    result = _add_rear_hub_sleeve(cq, result, params)
    result = _add_annular_details(cq, result, params)
    result = _cut_legacy_hole_rings(result, params)
    result = _cut_coverplate_bolt_ring(result, params)
    result = _cut_balance_hole_ring(result, params)
    result = _cut_rim_slots(cq, result, params)

    metadata = _metadata(params, profile_points, warnings)

    return result, metadata
```

---

# 14. Geometry implementation sketch

下面是 Claude Code 可参考的关键实现片段。请根据仓库实际 CadQuery 版本修正 API。

```python
def _make_box(cq, length_x: float, width_y: float, height_z: float, center: tuple[float, float, float]):
    return (
        cq.Workplane("XY")
        .box(length_x, width_y, height_z, centered=True)
        .translate(center)
    )


def _make_rectangular_rim_slot_cutter(cq, params: dict):
    r_outer = float(params["outer_dia_mm"]) / 2.0
    depth = float(params["rim_slot_depth_mm"])
    width = float(params["rim_slot_width_mm"])
    axial = float(params["rim_width_mm"]) - 2.0 * float(params["rim_slot_axial_margin_mm"])

    center_x = r_outer - depth / 2.0

    return _make_box(
        cq,
        length_x=depth * 1.1,
        width_y=width,
        height_z=axial,
        center=(center_x, 0.0, 0.0),
    )


def _make_fir_tree_like_slot_cutter(cq, params: dict):
    r_outer = float(params["outer_dia_mm"]) / 2.0
    depth = float(params["rim_slot_depth_mm"])
    mouth_w = float(params["rim_slot_width_mm"])
    neck_w = float(params["rim_slot_neck_width_mm"])
    lobe_w = float(params["rim_slot_lobe_width_mm"])
    lobe_depth = float(params["rim_slot_lobe_depth_mm"])
    axial = float(params["rim_width_mm"]) - 2.0 * float(params["rim_slot_axial_margin_mm"])

    pieces = []

    pieces.append(
        _make_box(
            cq,
            length_x=depth * 0.25,
            width_y=mouth_w,
            height_z=axial,
            center=(r_outer - depth * 0.125, 0.0, 0.0),
        )
    )

    pieces.append(
        _make_box(
            cq,
            length_x=depth * 0.45,
            width_y=neck_w,
            height_z=axial,
            center=(r_outer - depth * 0.42, 0.0, 0.0),
        )
    )

    pieces.append(
        _make_box(
            cq,
            length_x=lobe_depth,
            width_y=lobe_w,
            height_z=axial,
            center=(r_outer - depth * 0.58, 0.0, 0.0),
        )
    )

    pieces.append(
        _make_box(
            cq,
            length_x=lobe_depth,
            width_y=lobe_w * 0.9,
            height_z=axial,
            center=(r_outer - depth * 0.78, 0.0, 0.0),
        )
    )

    pieces.append(
        _make_box(
            cq,
            length_x=depth * 0.18,
            width_y=neck_w * 1.15,
            height_z=axial,
            center=(r_outer - depth * 0.93, 0.0, 0.0),
        )
    )

    cutter = pieces[0]
    for piece in pieces[1:]:
        cutter = cutter.union(piece)

    return cutter


def _cut_rim_slots(cq, result, params: dict):
    count = int(params.get("rim_slot_count", 0))
    style = str(params.get("rim_slot_style", "none"))

    if count <= 0 or style == "none":
        return result

    if style == "rectangular":
        cutter = _make_rectangular_rim_slot_cutter(cq, params)
    elif style in {"dovetail", "fir_tree_like"}:
        cutter = _make_fir_tree_like_slot_cutter(cq, params)
    else:
        raise ValueError(f"Unsupported rim_slot_style: {style!r}")

    for i in range(count):
        angle = 360.0 * i / count
        rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
        result = result.cut(rotated)

    return result
```

注意：

```text
1. 这个 fir_tree_like 是 visual approximation；
2. 不是真实承载槽；
3. 不用于装配叶片；
4. 不用于制造；
5. metadata 必须明确说明。
```

---

# 15. Validator 新增逻辑示例

```python
def _validate_rim_slots(errors: list[str], params: dict) -> None:
    style = str(params.get("rim_slot_style", "none"))
    count = int(params.get("rim_slot_count", 0))

    allowed = {"none", "rectangular", "dovetail", "fir_tree_like"}
    if style not in allowed:
        errors.append(f"rim_slot_style must be one of {sorted(allowed)}, got {style!r}")
        return

    if style == "none":
        if count != 0:
            errors.append("rim_slot_count must be 0 when rim_slot_style='none'")
        return

    outer_d = float(params["outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])
    rim_width = float(params["rim_width_mm"])

    r_outer = outer_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    rim_radial = r_outer - r_rim_inner

    depth = float(params.get("rim_slot_depth_mm", 0.0))
    width = float(params.get("rim_slot_width_mm", 0.0))
    axial_margin = float(params.get("rim_slot_axial_margin_mm", 0.0))

    if count < 12:
        errors.append("rim_slot_count must be >= 12 when rim_slot_style is not 'none'")

    if depth <= 0:
        errors.append("rim_slot_depth_mm must be > 0 when rim slots are enabled")

    if width <= 0:
        errors.append("rim_slot_width_mm must be > 0 when rim slots are enabled")

    if depth >= rim_radial * 0.8:
        errors.append(
            "rim_slot_depth_mm is too large; it would cut too deeply into the rim/web region"
        )

    pitch = 2.0 * math.pi * r_outer / max(count, 1)
    if pitch <= width * 1.2:
        errors.append(
            "rim_slot_width_mm is too large for rim_slot_count; slots would overlap"
        )

    if axial_margin < 0:
        errors.append("rim_slot_axial_margin_mm must be >= 0")

    slot_axial = rim_width - 2.0 * axial_margin
    if slot_axial <= 0:
        errors.append("rim_slot_axial_margin_mm leaves no axial thickness for rim slots")

    for key in [
        "rim_slot_neck_width_mm",
        "rim_slot_lobe_width_mm",
        "rim_slot_lobe_depth_mm",
    ]:
        value = float(params.get(key, 0.0))
        if style == "fir_tree_like" and value <= 0:
            errors.append(f"{key} must be > 0 for fir_tree_like rim slots")
```

---

# 16. 更新 metadata validation

`validate_axisymmetric_turbine_disk_metadata()` 应新增：

```python
def validate_axisymmetric_turbine_disk_metadata(metadata: dict) -> list[str]:
    errors = []

    if metadata.get("geometry_family") != "axisymmetric_base_with_cyclic_rim_features":
        errors.append("metadata.geometry_family must be axisymmetric_base_with_cyclic_rim_features")

    visual = metadata.get("visual_fidelity")
    if not isinstance(visual, dict):
        errors.append("metadata.visual_fidelity must be a dict")
    else:
        if visual.get("contains_real_blade_attachment") is not False:
            errors.append("visual_fidelity.contains_real_blade_attachment must be False")

    rim = metadata.get("rim_features")
    if not isinstance(rim, dict):
        errors.append("metadata.rim_features must be a dict")
    else:
        if "slot_count" not in rim:
            errors.append("rim_features.slot_count missing")
        if "slot_style" not in rim:
            errors.append("rim_features.slot_style missing")
        if rim.get("reference_only") is not True:
            errors.append("rim_features.reference_only must be True")

    sleeve = metadata.get("hub_sleeve")
    if not isinstance(sleeve, dict):
        errors.append("metadata.hub_sleeve must be a dict")

    # Keep existing safety checks
    ...

    return errors
```

---

# 17. 更新 mechanical validation

`validate_axisymmetric_turbine_disk_result()` 中新增：

```python
expected_kernel = "cadquery_turbine_disk_reference_v2"
```

但为了兼容旧测试，可暂时允许：

```python
allowed_kernels = {
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
}
```

不过 demo v0.2 必须期望：

```text
cadquery_turbine_disk_reference_v2
```

新增检查：

```python
if int(params.get("rim_slot_count", 0)) > 0:
    rim_features = metadata.get("rim_features") or {}
    if int(rim_features.get("slot_count", -1)) != int(params["rim_slot_count"]):
        issues.append(...)

    visual = metadata.get("visual_fidelity") or {}
    if visual.get("contains_cyclic_rim_slots") is not True:
        issues.append(...)

    if visual.get("contains_real_blade_attachment") is not False:
        issues.append(...)
```

bbox 计算：

```python
expected_z = (
    float(params["axial_width_mm"])
    + float(params.get("front_hub_sleeve_height_mm", 0.0))
    + float(params.get("rear_hub_sleeve_height_mm", 0.0))
)
```

允许 tolerance：

```text
1.0 mm
```

不要为了通过测试把 tolerance 调到很大。

---

# 18. Demo 验收标准

运行：

```bash
cd integrations/engineering_tools
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
```

输出必须：

```text
overall_ok = True
metadata stage ok
mechanical_validate stage ok
kernel_used = cadquery_turbine_disk_reference_v2
reference_dimensions.rim_slot_count exists
reference_dimensions.front_hub_sleeve_height_mm exists
```

生成图形从视觉上应满足：

```text
1. 外缘有密集周期槽；
2. 中心有前伸筒状 hub sleeve；
3. 盘面有环形台阶/凹槽；
4. 外缘 rim 更厚；
5. 不是纯平盘；
6. 不是普通法兰；
7. 比原图 3 更接近用户给的真实图 1/图 2。
```

---

# 19. 测试清单

必须运行：

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
python -m pytest tests/test_demo_full_chain_turbine_disk.py -q
python -m pytest tests/test_turbine_disk_visual_features.py -q
```

新增 visual feature tests 必须覆盖：

```text
1. rim_slot_count > 0 时 metadata.rim_features 存在；
2. rim_slot_style="fir_tree_like" 时 validator 要求 neck/lobe 参数；
3. slot depth 太大时 validation fail；
4. slot width 与 count 导致重叠时 validation fail；
5. front_hub_sleeve_height_mm > 0 时 expected bbox Z 增大；
6. visual_fidelity.contains_real_blade_attachment 必须 False；
7. warnings 必须包含 non-flight reference geometry only；
8. demo expected kernel 为 cadquery_turbine_disk_reference_v2。
```

---

# 20. Claude Code 执行 Prompt

请按下面 prompt 执行：

```text
你现在在 seekflow-engineering 仓库中，重点目录：

integrations/engineering_tools/

当前 axisymmetric_turbine_disk 已经能生成一个基本圆盘，但视觉上不像真实涡轮盘。用户给出的真实参考图有明显外缘盘齿/叶根槽、中心前伸筒状 hub、环形台阶、seal land / rabbet / coverplate 接口，而当前 SolidWorks 结果像普通平面法兰盘。

你的任务是把 axisymmetric_turbine_disk 升级到 v0.2，使它成为“更接近真实涡轮转子盘外观的非飞行参考几何 primitive”。

最高约束：
1. 不允许声称 flight-ready / airworthy / certified / manufacturing-ready / installable。
2. 不允许做真实航空发动机设计。
3. 不允许做真实强度、寿命、转速、适航、材料验证。
4. 不允许把 fir-tree-like slot 声称为真实叶片连接。
5. 不允许让 LLM 生成任意 CAD 代码。
6. primitive_compiler 只调用 deterministic kernel。
7. SolidWorks/NX 仍只能 import canonical STEP。
8. 所有 metadata / warnings / safety 必须声明 non-flight reference geometry only。
9. 不要破坏现有 gear primitive 和 recipe cases。
10. 不要重命名 primitive_name，仍保持 axisymmetric_turbine_disk。

实施目标：
- 保留 primitive_name = "axisymmetric_turbine_disk"
- 将 kernel 升级为 "cadquery_turbine_disk_reference_v2"
- 在现有轴对称基体上增加 cyclic rim slots
- 增加 front hub sleeve
- 增加 annular raised/recess details
- 增加 coverplate bolt ring / balance hole ring
- 增加 metadata visual_fidelity / rim_features / hub_sleeve / annular_details
- 更新 validator / metadata validation / mechanical validation / demo / tests

必须修改文件：
1. src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
2. src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
3. src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
4. src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
5. src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
6. src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
7. demo_full_chain.py

必须新增或更新测试：
1. tests/test_axisymmetric_turbine_disk_parameters.py
2. tests/test_axisymmetric_turbine_disk_compiler.py
3. tests/test_axisymmetric_turbine_disk_metadata.py
4. tests/test_axisymmetric_turbine_disk_mechanical_validation.py
5. tests/test_demo_full_chain_turbine_disk.py
6. tests/test_turbine_disk_visual_features.py

参数新增：
rim_slot_count
rim_slot_style
rim_slot_depth_mm
rim_slot_width_mm
rim_slot_neck_width_mm
rim_slot_lobe_width_mm
rim_slot_lobe_depth_mm
rim_slot_axial_margin_mm
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

balance_hole_count
balance_hole_pcd_mm
balance_hole_dia_mm

rim_slot_style 允许：
none
rectangular
dovetail
fir_tree_like

默认 demo 必须使用：
rim_slot_count = 60
rim_slot_style = "fir_tree_like"
front_hub_sleeve_height_mm > 0
enable_annular_details = True
coverplate_bolt_count > 0

几何实现：
1. 先 build revolved base body；
2. add front hub sleeve；
3. add rear hub sleeve if enabled；
4. add annular raised rings；
5. cut annular recesses；
6. cut existing legacy hole rings；
7. cut coverplate bolt ring；
8. cut balance hole ring；
9. cut rim slots；
10. build metadata。

rim slots 实现：
- 用 box cutter 组合形成 rectangular 或 fir_tree_like cutter；
- cutter 初始放在 +X 方向；
- 对 count 做 rotate polar array；
- 每次 result = result.cut(rotated_cutter)；
- style == "none" 时不切；
- fir_tree_like 由 mouth / neck / lobe / root pocket 多个 box union 组成；
- 不要声称真实 fir-tree。

metadata 必须新增：
geometry_family = "axisymmetric_base_with_cyclic_rim_features"

visual_fidelity = {
    "target": "reference_turbine_rotor_disk",
    "contains_cyclic_rim_slots": True,
    "contains_hub_sleeve": True,
    "contains_annular_details": True,
    "contains_coverplate_interface": True,
    "contains_real_blade_attachment": False
}

rim_features = {
    "slot_count": ...,
    "slot_style": ...,
    "slot_depth_mm": ...,
    "slot_width_mm": ...,
    "reference_only": True
}

hub_sleeve = {
    "front_enabled": ...,
    "rear_enabled": ...,
    "front_outer_dia_mm": ...,
    "front_inner_dia_mm": ...,
    "front_height_mm": ...
}

annular_details = {
    "enabled": ...,
    "mid_web_recess": ...,
    "outer_rim_recess": ...,
    "seal_lands": ...
}

warnings 必须包含：
- non-flight reference geometry only
- not airworthy
- not certified
- not manufacturing-ready
- rim slots are visual/reference fir-tree-like features only
- not certified blade attachment geometry
- no contact stress / centrifugal load / fatigue life / burst margin validation

validator 必须新增检查：
- rim_slot_style 合法；
- style == none 时 count == 0；
- rim_slot_count >= 12 when enabled；
- slot depth > 0；
- slot depth < 0.8 * rim radial thickness；
- slot pitch > 1.2 * slot width；
- slot axial thickness > 0；
- front sleeve outer dia > inner dia；
- sleeve inner dia >= bore dia；
- sleeve height >= 0；
- annular recess diameters合法；
- coverplate/balance hole count 与 pcd/dia 规则合法。

mechanical validation 必须新增检查：
- kernel == cadquery_turbine_disk_reference_v2 for v0.2 demo；
- geometry_family 正确；
- rim_features slot_count 与 params 一致；
- visual_fidelity.contains_real_blade_attachment is False；
- hub_sleeve front height 与 params 一致；
- safety flags all True；
- bbox Z = axial_width + front_hub_sleeve_height + rear_hub_sleeve_height within tolerance；
- reference_dimensions 包含 rim_slot_count、rim_slot_style、front_hub_sleeve_height_mm、expected_periodic_slot_count。

demo_full_chain：
更新 run_case_axisymmetric_turbine_disk 的参数，使生成结果明显不像平盘：
- outer_dia 约 520；
- rim_slot_count 60；
- rim_slot_style fir_tree_like；
- front_hub_sleeve_height 58；
- coverplate_bolt_count 18；
- lightening holes 10；
- cooling holes 36；
- annular details enabled；
- expected kernel = cadquery_turbine_disk_reference_v2；
- expected bbox Z 更新为 axial_width + front_hub_sleeve_height + rear_hub_sleeve_height。

验收命令：
cd integrations/engineering_tools
python -m pytest tests -q
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery

完成后输出：
1. 修改文件清单；
2. 新增参数清单；
3. 新增 metadata 字段；
4. 测试结果；
5. demo 结果；
6. 如果失败，不要声称完成，说明失败原因。
```

---

# 21. Definition of Done

只有满足以下全部条件才算完成：

```text
1. axisymmetric_turbine_disk 仍可通过 CAD-IR build；
2. kernel_used = cadquery_turbine_disk_reference_v2；
3. 生成模型外缘有周期性 rim slots；
4. 生成模型中心有 front hub sleeve；
5. 生成模型盘面有 annular details；
6. metadata 有 rim_features；
7. metadata 有 hub_sleeve；
8. metadata 有 visual_fidelity；
9. visual_fidelity.contains_real_blade_attachment = False；
10. warnings 明确 reference only；
11. mechanical validation 通过；
12. demo cadquery 通过；
13. invalid slot 参数会 fail；
14. slot depth 过大会 fail；
15. slot overlap 会 fail；
16. non_flight_reference_only=False 会 fail；
17. 现有 involute_spur_gear 不被破坏；
18. 现有 recipe cases 不被破坏。
```

这版的关键变化是：**承认真实感主要来自非轴对称外缘槽和中心筒状 hub，而不是继续调 hub/web/rim 三个直径。**所以我建议不要再把主要精力放在“盘面多打几圈孔”，而是优先实现 `rim_slot_count + fir_tree_like cutter + hub sleeve + annular details`。这四项一加，视觉上会立刻从“平面法兰盘”变成“涡轮转子盘参考件”。

[1]: file://my_files/file_000000005804722fadd54b16bc80d490 "Pasted text.txt"
[2]: file://my_files/file_000000003fd471f5af80919e99f4577a "Pasted markdown.md"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py "raw.githubusercontent.com"
[4]: https://patents.google.com/patent/EP1394358A2/en?utm_source=chatgpt.com "EP1394358A2 - Gas turbine engine disk rim with axially ..."
