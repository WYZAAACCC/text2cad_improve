涡轮盘建模失败根因深度诊断
一、结论速览
问题	根本原因	代码锚点	两次测试
① 榫槽只切一半	ExtrudeProfileParams.direction 只允许 "+"/"-","both" 是死代码;cutter 单向 +Z 挤出,只覆盖 disc 的 Z>0 半边	params.py:55 / handlers.py:185-194	两次都有(v11 备注已记"Z 只切一半")
② 盘面没从内到外由厚变薄	prompts rule 30c 的示例剖面把 web 画成平直水平线,最新测试 LLM 照搬;v11 是 LLM 偶然发挥斜点	prompts.py:129-133	v11✅ 斜点 / 最新❌ 平直台阶
③ 榫槽无圆角、不完整枞树	fillet_sketch 用 wire.Vertices() 提取顶点失败,降级保留无圆角 profile	handlers.py:362-388	两次都失败(v11:CadQuery 不支持 fillet2D;最新:顶点提取异常)
④ 转折处无圆角过渡	②(无斜点)+ ③(fillet失败)叠加;v11 靠斜点当过渡,最新两者皆无	—	最新❌ 纯直角
核心洞察:这 4 个问题里,只有 ② 是 LLM 输出波动,①③④ 都是代码层缺陷——而且 ①③ 在两次测试中都存在,v11 之所以"看起来成功",只是因为 LLM 那次恰好用斜点补救了 ②④,而榫槽只切一半的问题 v11 一直没解决(报告自己写了"Z 只切一半")。

二、两次测试 IR 层面的关键差异
两次走的是同一条链路(sketch_profile + composition,无 axisymmetric),节点拓扑完全同构:create_2d_sketch → add_polyline → close_profile → fillet_sketch → revolve_profile(disc) + 同构 cutter → circular_pattern_component → boolean_cut。差异只在 LLM 生成的剖面点坐标:

disc 剖面(web 段 r=120→215)— 这是问题②的现场:


最新测试(平直台阶,无变厚度):
  (120, 37)→(120, 15)→(215, 15)→(215, 30)
   ↑hub边     ↑直角降到±15   ↑web水平平直   ↑直角升到±30轮缘
   web 段 Y=±15 恒定,厚30mm,从内到外厚度不变

v11(斜点锥形,有变厚度):
  (120,-22)→(155,-20)→(185,-17)→(215,-15)
   ↑hub边    ↑斜点1    ↑斜点2    ↑斜点3   逐渐由±22收窄到±15
   web 段用3段斜线,厚44mm→30mm,从内到外由厚变薄 ✓
cutter 方向:两次 direction="+", depth=80 完全相同(问题①的现场)。

三、逐问题深度诊断(结合代码)
问题① 榫槽只切一半 —— direction="both" 是死代码
坐标系还原:

disc 剖面在 XZ 平面,CadQuery Workplane("XZ") 把 2D (x_mm, y_mm) 映射到 3D (R, 0, Z)。剖面点 (60, -37)...(60, 37) → revolve 绕 Z 轴 → disc 轴向 Z∈[-37, +37],关于 Z=0 对称,厚 74mm。
cutter 剖面在 XY 平面,extrude direction="+" 沿 +Z 挤出 depth=80 → cutter Z∈[0, +80]。
交集:cutter 的 Z 范围 [0, 80] 与 disc 的 [-37, +37] 仅在 [0, +37] 相交。disc 的 Z∈[-37, 0] 半边完全没有 cutter 覆盖,轮缘下半边一个槽都没切到。阵列 60 份后,每个榫槽都是"半截"——上半有槽、下半完整。

代码根因:params.py:55


class ExtrudeProfileParams(BaseModel):
    direction: Literal["+", "-"] = "+"   # ← 没有 "both"!
而 handlers.py:185-188 却有:


if direction == "both":
    # Symmetric extrude: depth_mm=80 with "both" means total Z height = 80mm (±40mm)
    solid = wp.extrude(depth / 2.0, both=True)
这是死代码——params 的 Literal["+", "-"] 会在 RAW 校验的 params 阶段拒绝任何 "both"。进度报告 Fix 19 写了"handle_extrude_profile direction='both' 对称挤出",但只改了 handler 没改 params,所以 LLM 永远无法传 both。两次测试 cutter 都只能是 "+",单向挤出必然只切对称盘的一半。

为什么 v11 也"成功"了:它的榫槽同样只切了一半,只是当时还没人盯着这个点;进度报告第五节 v11 备注明确写"Z 只切一半"。这不是 v11 解决了,而是被"首次全管线通过"的喜悦掩盖了。

问题② 盘面没从内到外由厚变薄 —— prompts 示例本身就是平直的
这不是代码 bug,是 prompt 引导缺陷。prompts.py:129-133 的 rule 30c 给 LLM 看的示例剖面:


points=[{60,-37.5},{120,-37.5},{120,-15.5},{215,-15.5},{215,-30},{250,-30},...]
                              ↑ web 起点 ±15.5    ↑ web 终点 ±15.5
示例里 web 段 (120,-15.5)→(215,-15.5) 就是一条水平线,Y 恒定 ±15.5,从内到外厚度完全不变。最新测试的 LLM 严格照搬了这个示例(web 段 ±15 平直),所以没有变厚度。v11 那次 LLM 反而"擅自"用了斜点 (120,-22)→(155,-20)→(185,-17)→(215,-15) 实现了锥形变薄——这是 LLM 的偶然发挥,不是 prompt 引导的功劳。

根因:sketch_profile 方言没有"变厚度/锥面"原语,只能靠多点折线近似;而 prompt 示例没示范"用斜点表达变厚度",反而示范了平直台阶。rule 30c 文字说"hub thick→web thin→rim thick",但示例图(点坐标)演示的是台阶式突变,LLM 照图不照文字。

问题③ 榫槽无圆角、不完整 —— fillet_sketch 顶点提取 bug
handlers.py:362-369 的 fillet 实现从 CadQuery wire 提取顶点:


wire = wires[0]
verts = wire.Vertices()
acc_points = [(v.X, v.Y) for v in verts]   # ← 这里炸了
两次测试的 metadata warnings 实锤:

最新:fillet_sketch on 'n_fillet_disc': vertex extraction failed (BRep_API: command not done) + cutter BRepAdaptor_Curve::No geometry
v11:CadQuery does not support fillet2D, skipping(更早版本直接跳过)
wire.Vertices() 对 close_profile 后的闭合 wire(尤其是经 mirror/带圆弧的)返回不可用顶点对象,v.X 触发 BRep_API: command not done。失败后 handlers.py:384-388 只 except + warning,wp 保持原值:


except Exception as e:
    ctx.warnings.append(f"fillet_sketch on '{node.id}': vertex extraction failed ({e}), keeping original profile")
后果:disc 转折点无圆角、cutter 枞树齿尖无圆角。枞树槽本应有齿根圆角(应力集中点),现在全是尖角;加上问题①只切一半,槽形既不完整也无圆角。

关于"枞树方向":核对最新测试 cutter 坐标,mouth(X=0)宽±4 → 交替收窄 → root(X=-22)窄±1,是"外宽里窄",方向其实正确。进度报告问题#2说的方向反是更早测试的问题,最新这次没反。所以"没完全枞树状"主因是 fillet 失败(齿尖尖锐)+ 只切一半(形状残缺),不是方向反。

问题④ 转折处无圆角过渡 —— ②③叠加
disc 的 hub→web、web→rim 转折要"圆角过渡"需要两件事至少其一:斜点过渡 或 fillet 圆角。

v11:web 用斜点(②有)+ fillet 失败(③)→ 斜面本身充当过渡,看起来"有过渡"
最新:web 平直(②无)+ fillet 失败(③)→ 纯直角硬转折,零过渡
所以最新测试比 v11 视觉上更差,是 ②③ 同时退化的叠加效应。

四、为什么"错误"几何能通过全管线?
这是最该警惕的系统性问题——fail-closed 安全门只管"几何有效",完全不管"设计意图是否实现":

fillet_sketch 失败降级为 warning 而非 error(handlers.py:385),不阻塞管线。
boolean_cut 正常执行 target.cut(tool)(composition/handlers.py:391),cutter 只切半边但结果仍是合法 closed solid。
geometry_postcheck 只查 closed=true / n_solids=1 / volume>0 / bbox 有效(geometry_postcheck.py)——全部通过(最新:closed=true, volume=8,403,515, n_solids=1)。
没有任何语义检查会验证:榫槽是否贯穿整个轮缘厚度?圆角是否真的生成?web 是否真的变厚度?榫槽数量/深度是否符合设计意图?
geometry_health_summary 里 disc 和 cutter 都是 status=warning, score=0.85(bbox 缺失扣分),但 warning 不阻断。系统把"几何有效性"等同于"建模正确性",这是一个根本性的语义缺口——LLM 产出的 IR 即使完整通过了 14 阶段校验 + 编译器中间端 + 运行时 postcheck,仍可以是一个"几何合法但设计意图完全落空"的零件。

五、修复建议(代码层面,按优先级)
P0 — 修复问题①(榫槽只切一半),改一行即可
params.py:55 把 Literal["+", "-"] 改为 Literal["+", "-", "both"],激活 handlers.py:185 已有的 both 分支。然后在 prompts.py:155-157 的 cutter 规则里强制 direction="both"(cutter 必须贯穿整个盘厚)。这是性价比最高的修复,一行改动解决一个两次测试都存在的硬伤。

P0 — 修复问题③(fillet_sketch 顶点提取)
handlers.py:362-369 放弃 wire.Vertices(),改用 polyline_points 状态(已在 handlers.py:102-108 由 add_polyline 累积),或用 OCCT TopExp_Explorer+BRep_Tool::Pnt 直接取顶点(进度报告问题#1 方案 A/B)。当前实现"从 wire 反推顶点"的路径本身就脆弱。

P1 — 修复问题②(盘面变厚度)
prompts.py:129-133 的示例剖面把 web 段改成斜点:{120,-22},{155,-20},{185,-17},{215,-15}(照搬 v11 那次 LLM 的成功坐标),并在文字里明确"web 段必须用 3-5 个斜点实现由厚变薄,禁止水平平直"。让 LLM 照着正确的图学。

P1 — 补语义检查(治本)
在 geometry_preflight 或一个新的 design_intent_postcheck 里加:榫槽 cutter 的 Z 范围必须覆盖 disc 轴向范围的 100%(检测只切一半);fillet_sketch 降级时若节点 required=true 应升级为 error 而非 warning(检测圆角丢失)。当前 fillet_sketch 失败无声降级,是"几何合法但设计落空"的主要入口。