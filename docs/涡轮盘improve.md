TextToCAD 涡轮盘建模能力增强 — 改进方案
一、问题根源诊断
通过深度代码分析，当前系统无法让 LLM 用通用建模语言构建正确涡轮盘的根本原因有 5 个：

根因 #1：revolve_profile 的 Z 排序破坏了径向顺序
handlers.py:80：


pts_2d.sort(key=lambda p: p[1])  # sort by z only
这条语句将所有 (r, z) 点按 Z 升序排列。对于涡轮盘剖面——其轴向厚度随半径变化（hub 厚、web 薄、rim 加厚），同一 Z 会对应多个不同的外轮廓半径。Z 排序破坏了正确的 R-Z 多边形拓扑顺序。

更深层的问题是 ProfileStation 的 schema 本身——{r_mm, z_front_mm, z_rear_mm} 被设计为"轴向圆柱段"，天然建模 r(z)（半径随 Z 变化），而不是涡轮盘需要的 z(r)（厚度随半径变化）。RevolveProfileParams 的 docstring 明确声明："profile 必须是 Z 的单值函数（同一 Z 只能有一个半径）"——这种设计正确地排除了涡轮盘剖面的表达。

根因 #2：cut_rim_slot_pattern 只能做折线槽
models.py:109-149 — SlotProfileStation 只有两个字段：depth_mm 和 half_width_mm。Handler 用 lineTo 直线段连接各个站点，产生：

缺失的几何特征	需要的表达
齿根圆角	fillet_mm
倾斜承力面	flank_angle_deg
槽底圆弧	root_radius_mm
齿肩/颈部语义区分	stage_name + role annotation
直线段连接	圆弧/样条过渡
然而两篇文档的共识是：不应该为此新增 fir_tree_slot_v2 专用操作，而是应该让通用 sketch 操作能够表达任意截面轮廓。

根因 #3：路由层偏好 Primitive
prompts.py:9：


9. If the request is better covered by an existing deterministic primitive
   and the user needs high determinism, choose deterministic_primitive.
同时 axisymmetric_turbine_disk.py 是一个 735 行、75 参数的模板——这恰恰是应该避免的方向。test_v11 的路由已经识别出 unsupported_capabilities（多级 fir-tree 无法表达、双密封槽无法表达），但仍然选择了 deterministic_primitive。路由验证器未检查 unsupported_capabilities 与 deterministic_primitive 之间的矛盾。

根因 #4：sketch_profile 缺少关键操作
当前 sketch_profile 支持的草图原语：line、arc、circle、polyline、close → extrude / cut。

缺失：fillet_sketch（无法在草图中导圆角）、spline_curve（无法画样条）、revolve_sketch（只能 extrude，不能 revolve）

根因 #5：circular_pattern_component 只平移不旋转
composition handlers 中的 handle_circular_pattern_component 只做 translate 复制，不旋转副本。这意味着所有副本朝向相同，对需要径向对齐的枞树槽无法直接使用。虽然可以通过 rotate_solid + translate_solid 逐槽处理，但会产生 O(N) 节点爆炸（60 个槽 = 120+ 个额外节点）。

二、改进方案：新增通用 CAD 原子操作
2.1 最高优先级 — revolve_closed_rz_polygon（axisymmetric 方言）
这是 #1 技术阻断点。 没有有序 R-Z 闭合多边形旋转，LLM 无法构建正确的涡轮盘盘体。

操作定义：


op: "revolve_closed_rz_polygon"
dialect: "axisymmetric"
phase: "base_solid"（与现有的 revolve_profile 共存于同一 phase）
input_types: []
output_types: ["solid", "frame"]
effects: ["creates_solid", "creates_frame"]
参数模型：


class RevolveClosedRzPolygonParams(BaseModel):
    axis: Literal["Z"] = "Z"
    points_rz_mm: list[tuple[float, float]] = Field(
        min_length=3,
        description=(
            "有序 (radius_mm, z_mm) 点列表，定义 R-Z 平面内的闭合多边形截面。"
            "点顺序必须为顺时针或逆时针，首尾不自动闭合——"
            "最后一个点会连线回到第一个点。"
            "同一 Z 可以出现多个不同 R 值（不像 revolve_profile 那样受 Z 单值约束）。"
            "适用于涡轮盘、壳体、复杂旋转体等需要变厚度剖面的零件。"
        )
    )
    inner_bore_radius_mm: float | None = Field(
        default=None,
        description="可选中心孔半径。指定后 handler 会在 revolve 前自动扣除中心孔。"
    )
Handler 实现要点（与现有 axisymmetric_turbine_disk.py 的 _build_base_body 相同思路）：


def handle_revolve_closed_rz_polygon(node, ctx):
    points = node.typed_params["points_rz_mm"]
    # 使用 polyline 而非 Z-sorted lineTo — 保留原始顺序
    solid = (
        cq.Workplane("XZ")
        .polyline([(r, z) for r, z in points])
        .close()
        .revolve(360)
    )
    # 可选扣除中心孔
    if bore_r := node.typed_params.get("inner_bore_radius_mm"):
        bore = cq.Workplane("XY").circle(bore_r).extrude(bbox.zlen + 10, both=True)
        solid = solid.cut(bore)
    ...
为什么这是"通用"操作而非"涡轮盘专用"？ 因为它是任何复杂旋转体（法兰、壳体、泵轮、阀体、端盖、叶轮、喷嘴、接头……）的基础建模能力，和 revolve_profile 是同一层级的通用操作。

2.2 高优先级 — fillet_sketch（sketch_profile 方言）
补充 sketch_profile 中缺失的倒圆角能力。这是让 LLM 能画出"有圆角的枞树槽"的关键。


op: "fillet_sketch"
params: { "radius_mm": float, "at_vertex_index": int | None }
2.3 高优先级 — polar_pattern_body（composition 方言增强）
修复 circular_pattern_component 只平移不旋转的问题。新增一个参数控制是否旋转副本。

最小改动： 给现有的 handle_circular_pattern_component 新增 rotate_copies: bool = True 参数，当为 True 时每个副本在平移后额外绕 Z 轴旋转 i * 360/count 度。

2.4 中优先级 — create_tangent_frame（新操作，可选 dialect）
让 LLM 能够在圆柱面外缘指定位置创建局部坐标系。


op: "create_tangent_frame"
params: {
    "target_radius_mm": float,
    "angle_deg": float,
    "z_mm": float,
    "x_direction": "radial_inward" | "radial_outward" | "tangential"
}
outputs: ["frame"]
有了这个，LLM 就不需要在脑子里做"XY 平面原点偏移到 r=250"的空间推理——它可以显式地"在圆柱面 r=250, θ=0, z=0 处放置一个局部坐标系"。

三、改进方案：路由层修复
3.1 禁止 unsupported_capabilities + deterministic_primitive 的组合
在 schemas.py 的 validate_route_invariants 中新增规则：


if self.route_decision == "deterministic_primitive" and self.unsupported_capabilities:
    raise ValueError(
        "Cannot select deterministic_primitive while listing unsupported_capabilities. "
        "If the primitive cannot express all required features, use generative_cad_ir or unsupported."
    )
3.2 修改 L1 路由 Prompt 的优先级
当前 rule 9 鼓励选择 primitive。应改为更中立的表述，并增加一条新规则：


9. [MODIFIED] If the request can be expressed using generative_cad_ir dialects
   (axisymmetric, sketch_extrude, sketch_profile, loft_sweep, shell_housing, composition),
   prefer generative_cad_ir — this enables the LLM to demonstrate general CAD modeling
   capability rather than calling a parameterized template.
   
12. [NEW] If any required geometric feature (fir-tree slots, varying-thickness profiles,
    multi-zone seal grooves, etc.) is listed in unsupported_capabilities, you MUST NOT
    select deterministic_primitive. Use generative_cad_ir or unsupported instead.
3.3 将 axisymmetric_turbine_disk 从路由目录中移出或标记为可选
选项 1（最彻底）：将 TURBOMACHINERY_PRIMITIVES 设为空列表，将 axisymmetric_turbine_disk 移到单独的"非默认"模块中。

选项 2（更温和）：在 build_level1_routing_prompt 中增加一个 include_turbomachinery_primitives: bool = False 参数，默认关闭。

四、改进方案：领域知识作为 Verifier（非 Generator）
这是涡轮盘驱动升级.md 的核心思想——涡轮盘的结构知识应用于验证LLM 构建的模型是否正确，而非直接生成模型。

4.1 Turbomachinery Profile Verifier
新增一个 validation stage（或在 geometry_preflight 中增强），检查：


def verify_turbine_disk_profile(component, nodes):
    """检查 revolve 产生的剖面是否满足涡轮盘结构约束。"""
    checks = [
        # 1. 存在 revolve 操作
        ("has_revolve", check_has_revolve_op(component, nodes)),
        # 2. hub 区域比 web 区域厚
        ("hub_thicker_than_web", check_hub_web_thickness_ratio(component, nodes)),
        # 3. rim 区域比相邻 web 区域厚
        ("rim_thicker_than_web", check_rim_web_thickness_ratio(component, nodes)),
        # 4. 外缘存在轴向贯通切槽
        ("has_rim_axial_slots", check_rim_axial_slots(component, nodes)),
        # 5. 槽型存在 neck/lobe 宽度交替（至少 2 次交替）
        ("slot_has_neck_lobe_alternation", check_slot_width_alternation(component, nodes)),
    ]
注意： 这是 VERIFIER，不是 GENERATOR。它只检查LLM构建的模型是否正确，不参与几何生成。如果任一检查不通过，产生 warning 而非 error——它建议修复但不阻断管线（除非 require_turbomachinery_validation=true）。

4.2 最终几何后验强化
在 geometry_postcheck.py 中，A1 修复已确保 closed=false → error。进一步：

如果 constraints.require_closed_solid=true，最终 closed=false 或 is_valid_solid=false 必须导致 build_generative_cad_model() 返回 ok=false
如果 constraints.expected_body_count 与实际 n_solids 不一致，必须报 error
五、涡轮盘的正确通用建模链
有了上述增强后，LLM 应该用如下通用操作链构建涡轮盘：


Step 1: revolve_closed_rz_polygon(
    points_rz_mm=[
        (60, -38), (120, -38), (170, -22), (215, -16), (250, -32),   # 前侧轮廓
        (250, 32), (215, 16), (170, 22), (120, 38), (60, 38)         # 后侧轮廓
    ]
) → disk_body

Step 2: cut_center_bore(diameter_mm=120) → disk_with_bore

Step 3: create_2d_sketch(plane="XY", origin_x_mm=250, origin_y_mm=0)
         add_line_segment → add_arc_segment → add_line_segment → ...
         fillet_sketch(radius_mm=0.8) × N
         close_profile()
         extrude_profile(depth_mm=70, both=True)
         → slot_cutter

Step 4: circular_pattern_component(slot_cutter, count=60, rotate_copies=True)
         → patterned_cutters

Step 5: boolean_cut(target=disk_with_bore, tool=patterned_cutters)
         → final_disk

Step 6: cut_circular_hole_pattern(count=12, pcd_mm=280, hole_dia_mm=14)  # 螺栓孔
         apply_safe_chamfer(distance_mm=1, required=False)                # 可选倒角
没有任何 turbine_disk() 或 fir_tree_slot() 调用。 全部是通用操作。

六、实施优先级
优先级	改动	理由
P0	revolve_closed_rz_polygon 新操作	#1 技术阻断——没有它 LLM 无法构建正确盘体
P0	路由层修复（3.1 + 3.2）	防止 LLM 再次误选 primitive
P1	polar_pattern_body rotate_copies 修复	当前只平移不旋转，无法正确排布径向槽
P1	fillet_sketch 新操作	让 LLM 能画有圆角的枞树槽截面
P2	领域 Verifier（4.1）	不参与生成，但能暴露 LLM 模型的结构错误
P2	create_tangent_frame 新操作	降低 LLM 空间推理难度
P3	axisymmetric_turbine_disk 移除/门控	关闭落入 primitive 模板的后路
七、与现有代码的关系
与 revolve_profile 共存：revolve_closed_rz_polygon 和 revolve_profile 放在同一个 base_solid phase 中，由 LLM 根据零件复杂度选择
与 sketch_profile 互补：增强 sketch_profile 的曲线和变换能力，使其成为通用的 2D 草图+特征建模语言
与 composition 协作：修复 circular_pattern_component 使其可用作 polar pattern 的通用实现
与现有的 P0-P3 修复兼容：A1-A4、B1-B2、C1-C4 的修复全部保留并继续发挥作用