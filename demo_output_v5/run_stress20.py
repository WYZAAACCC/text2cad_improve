"""极限压力测试 — 20 个高复杂度零件，专门暴露系统漏洞。

Tier 1 (参数边界): 薄壁/微型/多筋/深孔/长螺旋
Tier 2 (特征交互): 双层/十字筋/多特征轴/变径管/组合箱体
Tier 3 (多方言): 联轴器/减速器座/管路系统/轴承座总成/多端口阀
Tier 4 (极限): 增压器转子/空间弯管/薄壳箱/多体底座/综合测试件

重点审计: 体积 bbox 合理性、chamfer/fillet 降级、STEP 密度异常、
LLM 参数错误、multi-dialect 装配正确性、large-part 性能。
"""

import json, os, sys, subprocess, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "stress20_output"
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()

# ═══════════════════════════════════════════════════════════════════════════════
# 20 个高复杂度测试零件
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    # ═══ Tier 1: 参数边界压力测试 ═══
    {
        "id": "s01_thin_large_flange",
        "name": "超大薄壁法兰 Thin Large Flange",
        "dialects": ["axisymmetric"],
        "test_dim": "极值参数: 外径500mm, 壁厚仅3mm, 测试大直径薄壁回转体",
        "prompt": (
            "超大薄壁法兰, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义:\n"
            "  station1 r=250 z=0-8 (法兰盘, 外径500mm厚8mm).\n"
            "中心孔: cut_center_bore diameter_mm=480 through_all=true (壁厚仅10mm).\n"
            "24个螺栓孔 PCD 470mm: cut_circular_hole_pattern count=24 pcd_mm=470 hole_dia_mm=12.\n"
            "所有外边缘倒角 0.5mm: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
    {
        "id": "s02_micro_bushing",
        "name": "微型精密轴套 Micro Bushing",
        "dialects": ["axisymmetric"],
        "test_dim": "极小尺寸: 外径6mm, 壁厚0.5mm, 测试精度极限",
        "prompt": (
            "微型轴套, 单位 mm, 参考几何.\n"
            "使用 revolve_profile: station1 r=3 z=0-12 (外径6mm).\n"
            "内孔: cut_center_bore diameter_mm=5 through_all=true (壁厚0.5mm).\n"
            "两端倒角 0.2mm: apply_safe_chamfer distance_mm=0.2 target=all_external_edges."
        ),
    },
    {
        "id": "s03_dense_rib_plate",
        "name": "密集加强筋板 Dense Rib Plate",
        "dialects": ["sketch_extrude"],
        "test_dim": "大量筋特征: 10条筋交叉排列, 测试特征交互与重叠",
        "prompt": (
            "密集加强筋底板, 单位 mm, 参考几何.\n"
            "底板: extrude_rectangle width_mm=300 height_mm=200 depth_mm=15 centered=true.\n"
            "安装孔: cut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=260 spacing_y_mm=160.\n"
            "纵筋x5 (Y方向): add_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[-80,0,7.5] direction=Y.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[-40,0,7.5] direction=Y.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[0,0,7.5] direction=Y.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[40,0,7.5] direction=Y.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[80,0,7.5] direction=Y.\n"
            "横筋x5 (X方向): add_rib thickness_mm=6 height_mm=20 length_mm=220 position_mm=[0,-50,7.5] direction=X.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=220 position_mm=[0,-25,7.5] direction=X.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=220 position_mm=[0,0,7.5] direction=X.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=220 position_mm=[0,25,7.5] direction=X.\n"
            "  add_rib thickness_mm=6 height_mm=20 length_mm=220 position_mm=[0,50,7.5] direction=X.\n"
            "圆角: apply_safe_fillet radius_mm=1.5 target=all_external_edges."
        ),
    },
    {
        "id": "s04_deep_hole_manifold",
        "name": "深孔交叉阀块 Deep Hole Manifold",
        "dialects": ["sketch_extrude"],
        "test_dim": "多个深孔在内部交叉, 测试孔系布尔运算正确性",
        "prompt": (
            "深孔交叉阀块, 单位 mm, 参考几何.\n"
            "主体: extrude_rectangle width_mm=100 height_mm=80 depth_mm=150 centered=true.\n"
            "纵向主孔: cut_hole diameter_mm=25 position_mm=[0,0] through_all=true axis=Z.\n"
            "横向孔1: cut_hole diameter_mm=15 position_mm=[0,20] through_all=true axis=Y.\n"
            "横向孔2: cut_hole diameter_mm=15 position_mm=[0,-20] through_all=true axis=Y.\n"
            "斜向孔: cut_hole diameter_mm=10 position_mm=[25,0] through_all=true axis=X.\n"
            "安装孔x4: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\n"
            "所有边缘倒角 0.5mm: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
    {
        "id": "s05_long_spring",
        "name": "长螺旋弹簧 Long Helix Spring",
        "dialects": ["loft_sweep"],
        "test_dim": "修复后的 helix_sweep: 15圈, 测试大圈数正确性",
        "prompt": (
            "长螺旋弹簧, 单位 mm, 参考几何.\n"
            "使用 helix_sweep:\n"
            "  radius_mm=20 (中径40mm),\n"
            "  height_mm=150 (自由长度),\n"
            "  pitch_mm=10 (节距),\n"
            "  profile_radius_mm=1.5 (簧丝直径3mm),\n"
            "  turns=15.\n"
            "注意: 这是helix_sweep操作, 不是sweep_profile。确保 profile_radius_mm < 0.45 * pitch/(2*pi)."
        ),
    },

    # ═══ Tier 2: 特征交互压力测试 ═══
    {
        "id": "s06_double_flange_assy",
        "name": "双层法兰装配 Double Flange Assembly",
        "dialects": ["axisymmetric", "composition"],
        "test_dim": "两个独立回转体 + boolean_union, 测试装配对齐",
        "prompt": (
            "双层法兰装配, 单位 mm, 参考几何.\n"
            "组件 'flange_a' (axisymmetric): revolve_profile station1 r=80 z=0-15.\n"
            "  cut_center_bore diameter_mm=60 through_all=true.\n"
            "  cut_circular_hole_pattern count=8 pcd_mm=140 hole_dia_mm=11.\n"
            "组件 'flange_b' (axisymmetric): revolve_profile station1 r=80 z=0-15.\n"
            "  cut_center_bore diameter_mm=60 through_all=true.\n"
            "  cut_circular_hole_pattern count=8 pcd_mm=140 hole_dia_mm=11.\n"
            "装配 '__assembly__' (composition): boolean_union 合并 flange_a 和 flange_b.\n"
            "boolean_union inputs: [{component: flange_a, output: body}, {component: flange_b, output: body}]."
        ),
    },
    {
        "id": "s07_cross_rib_box",
        "name": "十字交叉筋箱体 Cross-Rib Box",
        "dialects": ["sketch_extrude"],
        "test_dim": "大量X/Y筋在中心密集交叉, 测试重叠特征容错",
        "prompt": (
            "十字交叉筋加强箱体, 单位 mm, 参考几何.\n"
            "底板: extrude_rectangle width_mm=250 height_mm=180 depth_mm=20 centered=true.\n"
            "中心减重腔: cut_rectangular_pocket width_mm=200 height_mm=130 depth_mm=12 centered=true.\n"
            "纵筋x6 (Y方向, 间距25mm): add_rib thickness_mm=5 height_mm=16 length_mm=120 position_mm=[-60,0,0] direction=Y.\n"
            "横筋x6 (X方向, 间距25mm): add_rib thickness_mm=5 height_mm=16 length_mm=160 position_mm=[0,-60,0] direction=X.\n"
            "安装孔: cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=210 spacing_y_mm=140.\n"
            "圆角: apply_safe_fillet radius_mm=2 target=all_external_edges."
        ),
    },
    {
        "id": "s08_multi_step_shaft_all_features",
        "name": "全特征阶梯轴 Full-Feature Stepped Shaft",
        "dialects": ["axisymmetric"],
        "test_dim": "单零件最大特征密度: 8段轮廓+3种孔+螺纹+环槽+倒角",
        "prompt": (
            "全特征传动轴, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义 7 段阶梯轮廓:\n"
            "  station1 r=18 z=0-12 (左轴肩),\n"
            "  station2 r=12 z=12-45 (轴承位),\n"
            "  station3 r=16 z=45-55 (定位环),\n"
            "  station4 r=10 z=55-95 (中间段),\n"
            "  station5 r=14 z=95-105 (齿轮位),\n"
            "  station6 r=8 z=105-135 (输出段),\n"
            "  station7 r=6 z=135-145 (螺纹段).\n"
            "左端中心孔: cut_center_bore diameter_mm=6 through_all=false depth_mm=20.\n"
            "齿轮位键槽近似: cut_annular_groove side=front inner_dia_mm=20 outer_dia_mm=24 depth_mm=3.\n"
            "螺纹: cut_external_thread nominal_dia_mm=6 pitch_mm=1.0 length_mm=10 standard=ISO_metric thread_class=6g.\n"
            "所有轴肩倒角 0.5mm: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
    {
        "id": "s09_variable_sweep_pipe",
        "name": "变径扫掠管 Variable Sweep Pipe",
        "dialects": ["loft_sweep"],
        "test_dim": "复杂3D路径+大曲率弯折, 测试sweep自交与曲率极限",
        "prompt": (
            "变径扫掠管, 单位 mm, 参考几何.\n"
            "第一段管道: create_sweep_path path_points (x_mm/y_mm/z_mm):\n"
            "  [{x_mm:0,y_mm:0,z_mm:0},{x_mm:60,y_mm:20,z_mm:50},{x_mm:80,y_mm:0,z_mm:100},{x_mm:40,y_mm:-20,z_mm:150},{x_mm:0,y_mm:0,z_mm:200}].\n"
            "  sweep_profile shape=circle radius_mm=10.\n"
            "第二段管道 (同组件内): create_sweep_path path_points:\n"
            "  [{x_mm:0,y_mm:0,z_mm:200},{x_mm:-40,y_mm:20,z_mm:250},{x_mm:-80,y_mm:0,z_mm:300}].\n"
            "  sweep_profile shape=circle radius_mm=12.\n"
            "确保 path_point 字段使用 x_mm/y_mm/z_mm."
        ),
    },
    {
        "id": "s10_shelled_ribbed_housing",
        "name": "薄壁筋壳体 Shelled Ribbed Housing",
        "dialects": ["sketch_extrude", "shell_housing"],
        "test_dim": "sketch_extrude基础 + shell_housing抽壳, 测试薄壁+筋共存",
        "prompt": (
            "薄壁加强筋壳体, 单位 mm, 参考几何.\n"
            "主体: extrude_rectangle width_mm=200 height_mm=150 depth_mm=100 centered=true.\n"
            "中心腔体: cut_rectangular_pocket width_mm=180 height_mm=130 depth_mm=90 centered=true.\n"
            "顶部开口: cut_rectangular_pocket width_mm=120 height_mm=80 depth_mm=5 centered=true.\n"
            "外壳抽壳: shell_body thickness_mm=3.\n"
            "内筋x2: add_rib thickness_mm=4 height_mm=20 length_mm=100 position_mm=[-40,0,20] direction=Y.\n"
            "  add_rib thickness_mm=4 height_mm=20 length_mm=100 position_mm=[40,0,20] direction=Y.\n"
            "安装孔: cut_hole_pattern_linear hole_dia_mm=8 count_x=2 count_y=2 spacing_x_mm=160 spacing_y_mm=110.\n"
            "圆角: apply_safe_fillet radius_mm=2 target=all_external_edges."
        ),
    },

    # ═══ Tier 3: 多方言复杂度 ═══
    {
        "id": "s11_coupling_assembly",
        "name": "联轴器总成 Coupling Assembly",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "test_dim": "3组件装配: 2个axisymmetric半联轴器+1个中间弹性体",
        "prompt": (
            "弹性联轴器总成, 单位 mm, 参考几何.\n"
            "组件 'hub_a' (axisymmetric): revolve_profile station1 r=50 z=0-40.\n"
            "  cut_center_bore diameter_mm=25 through_all=true.\n"
            "  cut_circular_hole_pattern count=6 pcd_mm=70 hole_dia_mm=10.\n"
            "组件 'hub_b' (axisymmetric): revolve_profile station1 r=50 z=0-40.\n"
            "  cut_center_bore diameter_mm=25 through_all=true.\n"
            "  cut_circular_hole_pattern count=6 pcd_mm=70 hole_dia_mm=10.\n"
            "组件 'spider' (sketch_extrude): extrude_rectangle width_mm=80 height_mm=80 depth_mm=20 centered=true.\n"
            "  cut_center_bore diameter_mm=25 through_all=true.\n"
            "装配 '__assembly__' (composition):\n"
            "  boolean_union 合并 hub_a 和 spider.\n"
            "  boolean_union 合并结果和 hub_b.\n"
            "每个 boolean_union 的 inputs: [{component: X, output: body}, {component: Y, output: body}]."
        ),
    },
    {
        "id": "s12_reducer_base",
        "name": "减速器底座 Reducer Base",
        "dialects": ["sketch_extrude", "axisymmetric", "composition"],
        "test_dim": "3组件: sketch_extrude底座+2个axisymmetric轴承座+多次boolean_union",
        "prompt": (
            "减速器底座总成, 单位 mm, 参考几何.\n"
            "组件 'base' (sketch_extrude): extrude_rectangle width_mm=400 height_mm=250 depth_mm=30 centered=true.\n"
            "  cut_rectangular_pocket width_mm=350 height_mm=200 depth_mm=15 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=340 spacing_y_mm=190.\n"
            "  add_rib thickness_mm=10 height_mm=25 length_mm=200 position_mm=[0,80,15] direction=Y.\n"
            "  add_rib thickness_mm=10 height_mm=25 length_mm=200 position_mm=[0,-80,15] direction=Y.\n"
            "组件 'bearing_a' (axisymmetric): revolve_profile station1 r=45 z=0-50.\n"
            "  cut_center_bore diameter_mm=30 through_all=true.\n"
            "组件 'bearing_b' (axisymmetric): revolve_profile station1 r=45 z=0-50.\n"
            "  cut_center_bore diameter_mm=30 through_all=true.\n"
            "装配 '__assembly__' (composition): 依次 boolean_union 合并 base、bearing_a、bearing_b."
        ),
    },
    {
        "id": "s13_pipe_system",
        "name": "多管路系统 Multi-Pipe System",
        "dialects": ["loft_sweep", "composition"],
        "test_dim": "4条独立扫掠管道+composition合并, 测试多sweep共存",
        "prompt": (
            "多管路汇流系统, 单位 mm, 参考几何.\n"
            "组件 'pipe_a' (loft_sweep): create_sweep_path:\n"
            "  [{x_mm:-30,y_mm:0,z_mm:0},{x_mm:-30,y_mm:0,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}].\n"
            "  sweep_profile shape=circle radius_mm=15.\n"
            "组件 'pipe_b' (loft_sweep): create_sweep_path:\n"
            "  [{x_mm:30,y_mm:0,z_mm:0},{x_mm:30,y_mm:0,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}].\n"
            "  sweep_profile shape=circle radius_mm=15.\n"
            "组件 'pipe_c' (loft_sweep): create_sweep_path:\n"
            "  [{x_mm:0,y_mm:-30,z_mm:50},{x_mm:0,y_mm:-30,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}].\n"
            "  sweep_profile shape=circle radius_mm=12.\n"
            "组件 'main' (loft_sweep): create_sweep_path:\n"
            "  [{x_mm:0,y_mm:0,z_mm:300},{x_mm:0,y_mm:0,z_mm:500}].\n"
            "  sweep_profile shape=circle radius_mm=30.\n"
            "装配 '__assembly__' (composition): boolean_union 依次合并 pipe_a, pipe_b, pipe_c, main."
        ),
    },
    {
        "id": "s14_bearing_housing_full",
        "name": "完整轴承座总成 Full Bearing Housing",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "test_dim": "复杂多体装配: 轴承座+底座+端盖+螺栓孔对齐",
        "prompt": (
            "完整轴承座总成, 单位 mm, 参考几何.\n"
            "组件 'housing' (axisymmetric): revolve_profile:\n"
            "  station1 r=55 z=0-20 (安装法兰),\n"
            "  station2 r=40 z=20-70 (座圈外壁),\n"
            "  station3 r=35 z=70-75 (内缘).\n"
            "  cut_center_bore diameter_mm=50 through_all=true.\n"
            "  cut_circular_hole_pattern count=4 pcd_mm=90 hole_dia_mm=10.\n"
            "组件 'base' (sketch_extrude): extrude_rectangle width_mm=200 height_mm=120 depth_mm=20 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=160 spacing_y_mm=80.\n"
            "  add_rib thickness_mm=10 height_mm=30 length_mm=80 position_mm=[-50,0,10] direction=Y.\n"
            "  add_rib thickness_mm=10 height_mm=30 length_mm=80 position_mm=[50,0,10] direction=Y.\n"
            "装配 '__assembly__' (composition): boolean_union 合并 housing 和 base."
        ),
    },
    {
        "id": "s15_multi_port_valve_block",
        "name": "多端口液压阀块 Multi-Port Valve Block",
        "dialects": ["sketch_extrude"],
        "test_dim": "长方体上12个不同方向的孔, 测试孔系密集交叉",
        "prompt": (
            "多端口液压集成块, 单位 mm, 参考几何.\n"
            "主体: extrude_rectangle width_mm=120 height_mm=100 depth_mm=180 centered=true.\n"
            "P口 (顶面): cut_hole diameter_mm=20 position_mm=[0,30] through_all=true axis=Y.\n"
            "T口 (顶面): cut_hole diameter_mm=25 position_mm=[0,-30] through_all=true axis=Y.\n"
            "A1-A4工作口 (前面): cut_hole diameter_mm=12 position_mm=[-40,0] through_all=false depth_mm=50 axis=Z.\n"
            "B1-B4工作口 (后面): cut_hole diameter_mm=12 position_mm=[40,0] through_all=false depth_mm=50 axis=Z.\n"
            "先导口 (左侧): cut_hole diameter_mm=6 position_mm=[0,0] through_all=true axis=X.\n"
            "测压口 (右侧): cut_hole diameter_mm=4 position_mm=[0,30] through_all=false depth_mm=30 axis=X.\n"
            "安装孔x4: cut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=100 spacing_y_mm=80.\n"
            "倒角: apply_safe_chamfer distance_mm=0.3 target=all_external_edges."
        ),
    },

    # ═══ Tier 4: 极限压力 ═══
    {
        "id": "s16_turbocharger_rotor",
        "name": "涡轮增压器转子 Turbo Rotor",
        "dialects": ["axisymmetric"],
        "test_dim": "超多站回转体(10+站), 测试轮廓处理极限",
        "prompt": (
            "涡轮增压器转子轴, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义 10 段复杂轮廓:\n"
            "  station1 r=35 z=0-8 (压气机叶轮安装面),\n"
            "  station2 r=25 z=8-20 (轴肩),\n"
            "  station3 r=18 z=20-45 (前轴承位),\n"
            "  station4 r=22 z=45-50 (止推环),\n"
            "  station5 r=15 z=50-85 (中间轴段),\n"
            "  station6 r=20 z=85-95 (密封环台),\n"
            "  station7 r=12 z=95-130 (后轴承位),\n"
            "  station8 r=16 z=130-140 (涡轮安装面),\n"
            "  station9 r=28 z=140-150 (涡轮背板),\n"
            "  station10 r=20 z=150-160 (锁紧螺纹段).\n"
            "两端中心孔: cut_center_bore diameter_mm=5 through_all=true.\n"
            "锁紧螺纹: cut_external_thread nominal_dia_mm=20 pitch_mm=2.5 length_mm=10 standard=ISO_metric thread_class=6g.\n"
            "所有轴肩倒角 0.3mm: apply_safe_chamfer distance_mm=0.3 target=all_external_edges."
        ),
    },
    {
        "id": "s17_complex_3d_sweep",
        "name": "三维空间弯管 3D Space Pipe",
        "dialects": ["loft_sweep"],
        "test_dim": "全3D路径(非平面弯管), 测试sweep在3D空间的正确性",
        "prompt": (
            "三维空间弯管(非平面路径), 单位 mm, 参考几何.\n"
            "使用 create_sweep_path 定义3D空间路径:\n"
            "  path_points (x_mm/y_mm/z_mm):\n"
            "  [{x_mm:0,y_mm:0,z_mm:0},{x_mm:30,y_mm:20,z_mm:40},{x_mm:60,y_mm:0,z_mm:80},{x_mm:40,y_mm:-30,z_mm:120},{x_mm:0,y_mm:-20,z_mm:160},{x_mm:-30,y_mm:0,z_mm:200},{x_mm:-10,y_mm:20,z_mm:240},{x_mm:0,y_mm:40,z_mm:280}].\n"
            "sweep_profile shape=circle radius_mm=8.\n"
            "注意: 路径在X/Y/Z三个方向都有变化, 不是平面曲线。"
        ),
    },
    {
        "id": "s18_large_thin_shell_box",
        "name": "大型薄壁壳体 Large Thin Shell Box",
        "dialects": ["sketch_extrude", "shell_housing"],
        "test_dim": "400mm大尺寸薄壁抽壳(壁厚2mm), 测试大尺寸+极薄壁稳定性",
        "prompt": (
            "大型薄壁电子设备壳体, 单位 mm, 参考几何.\n"
            "主体: extrude_rectangle width_mm=400 height_mm=300 depth_mm=150 centered=true.\n"
            "内部腔体: cut_rectangular_pocket width_mm=380 height_mm=280 depth_mm=140 centered=true.\n"
            "薄壁抽壳: shell_body thickness_mm=2.\n"
            "底面法兰: add_rectangular_boss width_mm=420 height_mm=320 depth_mm=8 position_mm=[0,0,-71] centered=true.\n"
            "法兰安装孔: cut_hole_pattern_linear hole_dia_mm=6 count_x=3 count_y=3 spacing_x_mm=180 spacing_y_mm=130.\n"
            "顶部开口: cut_rectangular_pocket width_mm=200 height_mm=150 depth_mm=5 centered=true.\n"
            "圆角: apply_safe_fillet radius_mm=3 target=all_external_edges."
        ),
    },
    {
        "id": "s19_multi_body_base",
        "name": "多体组合工作台 Multi-Body Workbench",
        "dialects": ["sketch_extrude", "axisymmetric", "composition"],
        "test_dim": "4组件装配: 2个sketch_extrude板+2个axisymmetric支柱",
        "prompt": (
            "多体组合工作台, 单位 mm, 参考几何.\n"
            "组件 'top_plate' (sketch_extrude): extrude_rectangle width_mm=500 height_mm=350 depth_mm=25 centered=true.\n"
            "  cut_rectangular_pocket width_mm=400 height_mm=250 depth_mm=10 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=400 spacing_y_mm=250.\n"
            "组件 'bottom_plate' (sketch_extrude): extrude_rectangle width_mm=500 height_mm=350 depth_mm=20 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=440 spacing_y_mm=290.\n"
            "组件 'pillar_left' (axisymmetric): revolve_profile station1 r=30 z=0-200.\n"
            "  cut_center_bore diameter_mm=20 through_all=true.\n"
            "组件 'pillar_right' (axisymmetric): revolve_profile station1 r=30 z=0-200.\n"
            "  cut_center_bore diameter_mm=20 through_all=true.\n"
            "装配 '__assembly__' (composition): 依次 boolean_union 合并 top_plate, bottom_plate, pillar_left, pillar_right."
        ),
    },
    {
        "id": "s20_ultimate_composite",
        "name": "终极综合测试件 Ultimate Composite",
        "dialects": ["axisymmetric", "sketch_extrude", "loft_sweep", "composition"],
        "test_dim": "全部4个建模方言的综合装配, 系统极限压力测试",
        "prompt": (
            "终极综合测试装配体, 单位 mm, 参考几何.\n"
            "组件 'rotor' (axisymmetric): revolve_profile:\n"
            "  station1 r=80 z=0-15, station2 r=60 z=15-50, station3 r=40 z=50-65.\n"
            "  cut_center_bore diameter_mm=30 through_all=true.\n"
            "  cut_circular_hole_pattern count=6 pcd_mm=110 hole_dia_mm=10.\n"
            "  apply_safe_chamfer distance_mm=1 target=all_external_edges.\n"
            "组件 'mount' (sketch_extrude): extrude_rectangle width_mm=250 height_mm=180 depth_mm=25 centered=true.\n"
            "  cut_rectangular_pocket width_mm=180 height_mm=120 depth_mm=15 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=200 spacing_y_mm=130.\n"
            "  add_rib thickness_mm=8 height_mm=20 length_mm=100 position_mm=[0,60,12.5] direction=Y.\n"
            "  add_rib thickness_mm=8 height_mm=20 length_mm=100 position_mm=[0,-60,12.5] direction=Y.\n"
            "组件 'pipe' (loft_sweep): create_sweep_path:\n"
            "  [{x_mm:0,y_mm:0,z_mm:0},{x_mm:50,y_mm:30,z_mm:60},{x_mm:100,y_mm:0,z_mm:120}].\n"
            "  sweep_profile shape=circle radius_mm=12.\n"
            "装配 '__assembly__' (composition): 依次 boolean_union 合并 rotor, mount, pipe."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

def build_contract(dialect_ids):
    lines = [
        "=== DIALECT CONTRACTS — USE EXACT NAMES ===",
        "=== OUTPUT NAME RULES (CRITICAL) ===",
        "  output type=solid → name='body' (NEVER 'solid')",
        "  output type=frame → name='outer_frame' (NEVER 'frame')",
        "  output type=curve → name='curve'",
        "  output type=profile → name='profile'",
        "",
        "=== PARAM RULES (CRITICAL) ===",
        "  extrude direction: '+' or '-' (NEVER 'Z','X','Y')",
        "  path_points coordinates: x_mm, y_mm, z_mm (NEVER x,y,z)",
        "  chamfer/fillet target: 'all_external_edges' (NEVER 'all_outer_edges')",
        "  thread_class for cut_internal_thread: '6H','6G','7H'",
        "  thread_class for cut_external_thread: '6g','6h','8g'",
        "  ALL 7 safety flags MUST be true",
        "  trust_level='reference_geometry'",
        "",
        "=== COMPOSITION RULES ===",
        "  boolean_union: empty params {},",
        "  inputs MUST be component refs: [{component: X, output: body}, ...]",
        "  Do NOT use node refs for cross-component inputs",
        "",
    ]
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} v{d.version} — phases: {' → '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            pstrs = [f"{pn}:{pi.get('type','?')}" for pn, pi in props.items()]
            lines.append(f"  {op_name}  phase={spec.phase}  inputs={list(spec.input_types)}  outputs={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs)}")
            if op_name == "revolve_profile":
                lines.append('    EXAMPLE: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":20},{"r_mm":30,"z_front_mm":20,"z_rear_mm":21}]}')
            elif op_name == "extrude_rectangle":
                lines.append('    EXAMPLE: {"width_mm":100,"height_mm":80,"depth_mm":15,"plane":"XY","centered":true,"direction":"+"}')
            elif op_name == "create_sweep_path":
                lines.append('    EXAMPLE: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":50,"y_mm":0,"z_mm":100}]}')
            elif op_name == "sweep_profile":
                lines.append('    EXAMPLE: {"shape":"circle","radius_mm":12}  — requires curve input from create_sweep_path')
            elif op_name == "helix_sweep":
                lines.append('    EXAMPLE: {"radius_mm":15,"height_mm":80,"pitch_mm":10,"profile_radius_mm":1.5,"turns":8}')
            elif op_name == "boolean_union":
                lines.append('    EXAMPLE: params={}, inputs=[{component:c1,output:body},{component:c2,output:body}]')
            elif op_name == "shell_body":
                lines.append('    EXAMPLE: {"thickness_mm":2.0}  — input must be solid from previous op')
            elif op_name == "cut_circular_hole_pattern":
                lines.append('    EXAMPLE: {"count":8,"pcd_mm":120,"hole_dia_mm":11,"axis":"Z","through_all":true}')
            elif op_name == "cut_external_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"length_mm":15,"standard":"ISO_metric","thread_class":"6g"}')
        lines.append("")
    return "\n".join(lines)


def call_llm(user_msg):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    resp = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[{"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
        tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120, extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)


def build_step_file(cdir):
    """Generate and run the STEP build subprocess."""
    bscript = (
        "import sys; sys.path.insert(0, r'" + SRC.as_posix() + "')\n"
        "from pathlib import Path\n"
        "from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files\n"
        "can = Path(r'" + (cdir / "canonical.json").as_posix() + "')\n"
        "val = Path(r'" + (cdir / "validation_bundle.json").as_posix() + "')\n"
        "stp = Path(r'" + (cdir / "output.step").as_posix() + "')\n"
        "met = Path(r'" + (cdir / "output.metadata.json").as_posix() + "')\n"
        "r = run_canonical_gcad_from_files(canonical_json=can, validation_seed_json=val, out_step=stp, metadata_path=met)\n"
        "if r.ok:\n"
        "    print('BUILD_OK')\n"
        "    for m in (r.operation_metrics or []):\n"
        "        print('OP:' + str(m.get('node_id','?')) + '/' + str(m.get('op','?')) + ':' + str(m.get('status','?')))\n"
        "    for d in (r.degraded_features or []):\n"
        "        print('DEGRADED:' + str(d.get('node_id','?')) + '/' + str(d.get('op','?')) + ':' + str(d.get('reason','?'))[:200])\n"
        "else:\n"
        "    print('BUILD_FAILED: ' + str(r.error)[:500])\n"
        "    for w in (r.warnings or []): print('WARN:' + str(w)[:200])\n"
    )
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text(
        "RC=" + str(r.returncode) + "\nSTDOUT:\n" + r.stdout + "\nSTDERR:\n" + r.stderr, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


def audit_geometry(step_path):
    """验证 STEP 几何: 体积、bbox、solid状态。"""
    try:
        import cadquery as cq
        result = cq.importers.importStep(str(step_path))
        solid = result.val()
        vol = solid.Volume()
        bb = solid.BoundingBox()
        return {
            "valid": solid.isValid(),
            "vol_mm3": round(vol, 2),
            "bbox_x": round(bb.xlen, 3),
            "bbox_y": round(bb.ylen, 3),
            "bbox_z": round(bb.zlen, 3),
        }
    except Exception as e:
        return {"error": str(e)[:150]}


def process_case(case, cdir):
    """Run one case through full pipeline. Returns (ok, msg, audit_dict)."""
    audit = {"case": case["id"], "dialects": case["dialects"],
             "test_dim": case.get("test_dim", "")}

    (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
    contract = build_contract(case["dialects"])

    base_msg = (
        f"TASK: {case['prompt']}\n\n{contract}\n\n"
        "CRITICAL: Use EXACT op/param names from contract. output solid→body. direction=+/-. "
        "path_points use x_mm/y_mm/z_mm. target=all_external_edges. ALL safety=true. "
        "trust_level=reference_geometry. For composition, boolean_union params={} inputs use component refs."
    )

    ok = False
    err = ""
    for attempt in range(5):
        user_msg = base_msg
        if attempt > 0:
            user_msg += f"\n\nPREVIOUS ATTEMPT FAILED:\n{err[:600]}\nFIX ALL ERRORS. Attempt {attempt+1}/5."

        try:
            args = call_llm(user_msg)
        except Exception as e:
            err = f"LLM: {e}"
            continue

        audit["llm_nodes_raw"] = len(args.get("nodes", []))
        (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

        # LLM error detection
        llm_errs = []
        for n in args.get("nodes", []):
            for o in n.get("outputs", []):
                if o.get("name") == "solid" and o.get("type") == "solid":
                    llm_errs.append(f"{n['id']}:output_name=solid")
            d = n.get("params", {}).get("direction", "")
            if d in ("Z", "X", "Y", "z", "x", "y") and n.get("op", "") not in ("add_rib",):
                llm_errs.append(f"{n['id']}:direction={d}")
            for pt in n.get("params", {}).get("path_points", []):
                if "x" in pt and "x_mm" not in pt:
                    llm_errs.append(f"{n['id']}:bare_xyz")
        audit["llm_errors"] = llm_errs

        # Autofix
        try:
            fixed, af = auto_fix_with_report(args, REG)
            (cdir / "autofix_report.json").write_text(json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
            audit["af_applied"] = af.applied
            audit["af_count"] = len(af.entries)
            audit["af_rules"] = [e.rule_id for e in af.entries]
            if af.applied:
                (cdir / "raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
        except:
            fixed = args
            audit["af_error"] = True

        fixed.setdefault("llm_validation_hints", {})
        if fixed.get("llm_validation_hints") is None:
            fixed["llm_validation_hints"] = {}
        fixed.setdefault("units", "mm")
        fixed.setdefault("trust_level", "reference_geometry")

        # Validate
        try:
            doc = RawGcadDocument.model_validate(fixed)
            canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
            if not (canonical and report and report.ok):
                issues = report.issues if report else []
                err = "; ".join(
                    "[{}] {}".format(getattr(i, "code", "?"), getattr(i, "message", str(i))[:120])
                    for i in (issues[:5] if issues else []))
                audit["val_issues"] = [{"code": getattr(i, "code", "?"), "msg": getattr(i, "message", str(i))[:150]} for i in (issues or [])[:3]]
                continue
            audit["val_ok"] = True
            (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            if bundle:
                (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            ok = True
            break
        except Exception as e:
            err = f"Pydantic: {e}"

    if not ok:
        return False, f"VAL: {err[:200]}", audit

    # Build STEP
    rc, stdout, stderr = build_step_file(cdir)
    audit["build_rc"] = rc
    audit["build_ok"] = "BUILD_OK" in stdout

    if not audit["build_ok"]:
        # Retry without chamfer/fillet
        cg = json.loads((cdir / "canonical.json").read_text(encoding="utf-8"))
        old_n = len(cg["nodes"])
        cg["nodes"] = [n for n in cg["nodes"] if n.get("op") not in ("apply_safe_chamfer", "apply_safe_fillet")]
        if len(cg["nodes"]) < old_n:
            for comp in cg.get("components", []):
                if comp.get("root_node", "") not in {n["id"] for n in cg["nodes"]} and cg["nodes"]:
                    comp["root_node"] = cg["nodes"][-1]["id"]
            (cdir / "canonical.json").write_text(json.dumps(cg, indent=2), encoding="utf-8")
            rc2, stdout2, _ = build_step_file(cdir)
            audit["build_ok"] = "BUILD_OK" in stdout2
            audit["edge_ops_removed"] = True

    if audit["build_ok"] and (cdir / "output.step").exists():
        step_sz = (cdir / "output.step").stat().st_size
        audit["step_size"] = step_sz
        geom = audit_geometry(cdir / "output.step")
        audit["geometry"] = geom
        vol = geom.get("vol_mm3", 0)
        bbox = geom.get("bbox_x", 0)

        # Anomaly detection
        flags = []
        if vol <= 0.01:
            flags.append("ZERO_VOL")
        if step_sz < 5000 and vol > 100:
            flags.append("TINY_STEP")
        if vol > 50000 and step_sz > 0 and step_sz / vol < 0.03:
            flags.append("LOW_DENSITY")
        if bbox > 0 and geom.get("bbox_z", 0) > 0:
            aspect = max(bbox, geom["bbox_y"], geom["bbox_z"]) / min(bbox, geom["bbox_y"], geom["bbox_z"])
            if aspect > 50:
                flags.append(f"EXTREME_ASPECT={aspect:.0f}")
        audit["flags"] = flags

        # SW import
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            sldprt = cdir / "output.SLDPRT"
            c = SolidWorksClient(visible=False).connect()
            try:
                ok_sw = c.import_step_as_part(cdir / "output.step", sldprt)
                audit["sw_size"] = sldprt.stat().st_size if ok_sw and sldprt.exists() else 0
            finally:
                c.close()
        except:
            audit["sw_size"] = -1

        msg = f"STEP={step_sz}B vol={vol:.0f}mm3 bbox=[{geom.get('bbox_x',0):.0f}x{geom.get('bbox_y',0):.0f}x{geom.get('bbox_z',0):.0f}]"
        if flags:
            msg += " " + " ".join(flags)
        if audit.get("edge_ops_removed"):
            msg += " NO_EDGE"
        return True, msg, audit
    else:
        return False, f"STEP: {stderr[:200]}", audit


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import datetime
    print(f"=== Stress20 Pipeline: {len(CASES)} cases ===\n")
    print(f"Output: {OUT}\n")

    results = []
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        start = time.time()
        print(f"[{i+1:02d}/20] {case['name']}  [{case.get('test_dim','')[:80]}]")
        print(f"  Dialects: {case['dialects']}  ", end="", flush=True)

        ok, msg, audit = process_case(case, cdir)
        elapsed = time.time() - start
        print(f"→ {msg}  [{elapsed:.0f}s]")

        if audit.get("llm_errors"):
            for e in audit["llm_errors"]:
                print(f"    WARN LLM: {e}")
        if audit.get("val_issues"):
            for vi in audit["val_issues"]:
                print(f"    WARN VAL: [{vi['code']}] {vi['msg'][:120]}")

        results.append({"id": case["id"], "name": case["name"], "ok": ok, "msg": msg,
                        "attempts_elapsed": f"{elapsed:.0f}s", "audit": audit})
        time.sleep(0.3)

    # Report
    print(f"\n{'='*80}")
    passed = sum(1 for r in results if r["ok"])
    print(f"RESULTS: {passed}/{len(results)} passed")
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        a = r.get("audit", {})
        g = a.get("geometry", {})
        vol_str = f" vol={g.get('vol_mm3',0):.0f}" if g else ""
        flags = " " + ",".join(a.get("flags", [])) if a.get("flags") else ""
        print(f"  {status} {r['name']:35s} {r['msg'][:100]}{vol_str}{flags}")

    report = {"timestamp": datetime.datetime.now().isoformat(),
              "total": len(results), "passed": passed, "results": results}
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (OUT / "full_audit.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReports: {OUT}/report.json, {OUT}/full_audit.json")
