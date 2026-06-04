"""v5.1 全量回归 — 35 cases (15 test_model + 20 stress20)

使用完整 contract builder (含显式示例) + v5.1 fail-closed infrastructure。
"""
import json, os, sys, subprocess, time, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "v6_hybrid_test_output"
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import AssemblyError

REG = default_registry()


def build_full_contract(dialect_ids):
    """完整 contract — 包含每个 op 的显式示例 (复制自 run_test_model.py 的模式)。"""
    lines = [
        "=== DIALECT CONTRACTS (EXACT names required) ===",
        "",
        "=== CRITICAL OUTPUT NAME RULES ===",
        "  output type=solid → name='body'   (NEVER 'solid')",
        "  output type=frame → name='outer_frame'",
        "  output type=curve → name='curve'",
        "  output type=profile → name='profile'",
        "",
        "=== CRITICAL PARAM RULES ===",
        "  extrude direction: '+' or '-' (NEVER 'Z', 'X', 'Y')",
        "  path_points use: x_mm, y_mm, z_mm (NEVER x, y, z)",
        "  chamfer/fillet target: 'all_external_edges' (NEVER 'all_outer_edges')",
        "  revolve_profile params: 'profile_stations' (NEVER 'profile_points', 'stations')",
        "  revolve_profile has NO 'direction' field (only axis='Z')",
        "  thread_class for cut_internal_thread: '6H', '6G', '7H' (NOT '6g')",
        "  thread_class for cut_external_thread: '6g', '6h', '8g' (NOT '6H')",
        "  ALL 7 safety flags must be true",
        "  trust_level='reference_geometry'",
        "",
        "=== CRITICAL COMPOSITION RULES ===",
        "  boolean_union: params={}, inputs=[{component: X, output: body}, {component: Y, output: body}]",
        "  boolean_union ALWAYS takes exactly 2 inputs. For 3+ solids, chain multiple boolean_unions.",
        "  Composition ops ONLY in __assembly__ component.",
        "  Do NOT use boolean_union to create ribs, bosses, holes, or pockets.",
        "",
    ]
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} v{d.version} phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            required = ps.get("required", [])
            pstrs = [f"{pn}{'*' if pn in required else ''}:{pi.get('type','?')}" for pn, pi in props.items()]
            lines.append(f"  {op_name} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs)}")
            # ── 显式示例 (关键!) ──
            if op_name == "revolve_profile":
                lines.append('    EXAMPLE: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":20},{"r_mm":30,"z_front_mm":20,"z_rear_mm":21}]}')
            elif op_name == "extrude_rectangle":
                lines.append('    EXAMPLE: {"width_mm":100,"height_mm":80,"depth_mm":15,"plane":"XY","centered":true,"direction":"+"}')
            elif op_name == "create_sweep_path":
                lines.append('    EXAMPLE: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":50,"y_mm":0,"z_mm":100}]}')
            elif op_name == "sweep_profile":
                lines.append('    EXAMPLE: {"shape":"circle","radius_mm":12}  — consumes curve from create_sweep_path')
            elif op_name == "helix_sweep":
                lines.append('    EXAMPLE: {"radius_mm":15,"height_mm":80,"pitch_mm":10,"profile_radius_mm":1.5,"turns":8}')
            elif op_name == "boolean_union":
                lines.append('    EXAMPLE params={}, inputs=[{component:c1,output:body},{component:c2,output:body}]')
            elif op_name == "shell_body":
                lines.append('    EXAMPLE: {"thickness_mm":2.0}')
            elif op_name == "cut_circular_hole_pattern":
                lines.append('    EXAMPLE: {"count":8,"pcd_mm":120,"hole_dia_mm":11,"axis":"Z","through_all":true}')
            elif op_name == "cut_external_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"length_mm":15,"standard":"ISO_metric","thread_class":"6g"}')
            elif op_name == "cut_internal_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"depth_mm":20,"standard":"ISO_metric","thread_class":"6H"}')
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 35 cases: 15 from test_model.md + 20 from stress20
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    # ─── test_model.md (15) ───
    {"id": "tm01_flange_cover", "name": "T1 法兰盖", "dialects": ["axisymmetric"],
     "prompt": "法兰盖, 单位 mm, 参考几何.\n使用 revolve_profile: station1 r=75 z=0-15, station2 r=40 z=15-25.\ncut_center_bore diameter_mm=20 through_all=true.\n8个螺栓孔 PCD 120mm: cut_circular_hole_pattern count=8 pcd_mm=120 hole_dia_mm=11.\n密封槽: cut_annular_groove side=front inner_dia_mm=85 outer_dia_mm=105 depth_mm=3.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
    {"id": "tm02_l_bracket", "name": "T1 L型支架", "dialects": ["sketch_extrude"],
     "prompt": "L型安装支架, 单位 mm, 参考几何.\nextrude_rectangle width_mm=100 height_mm=80 depth_mm=10 centered=true.\n4个安装孔: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\n加强筋: add_rib thickness_mm=8 height_mm=40 length_mm=60 position_mm=[0,0,5] direction=Y.\n2个定位孔: cut_hole diameter_mm=6 position_mm=[-35,0] through_all=true.\n  cut_hole diameter_mm=6 position_mm=[35,0] through_all=true.\napply_safe_fillet radius_mm=1.5 target=all_external_edges."},
    {"id": "tm03_bearing_seat", "name": "T1 轴承座", "dialects": ["axisymmetric", "sketch_extrude", "composition"],
     "prompt": "轴承座装配, 单位 mm, 参考几何.\n组件 'hub' (axisymmetric): revolve_profile station1 r=35 z=0-15, station2 r=28 z=15-50, station3 r=20 z=50-55. cut_center_bore diameter_mm=25 through_all=true.\n组件 'base' (sketch_extrude): extrude_rectangle width_mm=120 height_mm=60 depth_mm=15 centered=true. cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=90 spacing_y_mm=40.\n装配 '__assembly__' (composition): boolean_union 合并 hub 和 base.\nboolean_union inputs: [{component: hub, output: body}, {component: base, output: body}]."},
    {"id": "tm04_stepped_shaft", "name": "T1 阶梯轴", "dialects": ["axisymmetric"],
     "prompt": "传动阶梯轴, 单位 mm, 参考几何.\nrevolve_profile: station1 r=15 z=0-10, station2 r=22 z=10-50, station3 r=18 z=50-80, station4 r=15 z=80-110, station5 r=12 z=110-120.\ncut_center_bore diameter_mm=8 through_all=true.\ncut_external_thread nominal_dia_mm=12 pitch_mm=1.75 length_mm=10 standard=ISO_metric thread_class=6g.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
    {"id": "tm05_v_pulley", "name": "T1 V型带轮", "dialects": ["axisymmetric"],
     "prompt": "V型带轮, 单位 mm, 参考几何.\nrevolve_profile 7段: station1 r=100 z=0-10, station2 r=95 z=10-18, station3 r=100 z=18-26, station4 r=95 z=26-34, station5 r=100 z=34-42, station6 r=95 z=42-50, station7 r=100 z=50-60.\ncut_center_bore diameter_mm=30 through_all=true.\ncut_circular_hole_pattern count=4 pcd_mm=60 hole_dia_mm=10.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
    {"id": "tm06_spring", "name": "T2 压缩弹簧", "dialects": ["loft_sweep"],
     "prompt": "压缩螺旋弹簧, 单位 mm, 参考几何.\nhelix_sweep: radius_mm=15 height_mm=80 pitch_mm=10 profile_radius_mm=2 turns=8.\n注意: 这是helix_sweep操作, 不是sweep_profile。中径30mm, 簧丝直径4mm, 8圈, 自由长度80mm."},
    {"id": "tm07_roller", "name": "T2 托辊", "dialects": ["axisymmetric", "composition"],
     "prompt": "输送机托辊, 单位 mm.\n组件 'tube' (axisymmetric): revolve_profile station1 r=44.5 z=0-600. cut_center_bore diameter_mm=80 through_all=true.\n组件 'shaft' (axisymmetric): revolve_profile station1 r=15 z=0-650.\n装配 '__assembly__' (composition): boolean_union 合并 tube 和 shaft.\nboolean_union inputs: [{component: tube, output: body}, {component: shaft, output: body}]."},
    {"id": "tm08_weld_fork", "name": "T2 焊接叉", "dialects": ["sketch_extrude"],
     "prompt": "焊接叉, 单位 mm.\nextrude_rectangle width_mm=80 height_mm=50 depth_mm=15 centered=true.\ncut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=30.\nadd_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[-30,0,7.5] centered=true.\nadd_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[30,0,7.5] centered=true.\ncut_hole diameter_mm=25 position_mm=[-30,25] through_all=true.\ncut_hole diameter_mm=25 position_mm=[30,25] through_all=true.\nadd_rib thickness_mm=8 height_mm=15 length_mm=60 position_mm=[0,0,7.5] direction=X.\napply_safe_fillet radius_mm=2 target=all_external_edges."},
    {"id": "tm09_gearbox_cover", "name": "T2 减速器箱盖", "dialects": ["sketch_extrude"],
     "prompt": "减速器上箱盖, 单位 mm.\nextrude_rectangle width_mm=300 height_mm=200 depth_mm=20 centered=true.\ncut_rectangular_pocket width_mm=260 height_mm=160 depth_mm=14 centered=true.\ncut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[-60,0,0] direction=Y.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[60,0,0] direction=Y.\nadd_rectangular_boss width_mm=100 height_mm=80 depth_mm=10 position_mm=[0,0,10] centered=true.\napply_safe_fillet radius_mm=3 target=all_external_edges."},
    {"id": "tm10_hex_nut", "name": "T2 六角螺母", "dialects": ["axisymmetric"],
     "prompt": "M10六角螺母轴对等近似, 单位 mm.\nrevolve_profile: station1 r=9.5 z=0-8.\ncut_center_bore diameter_mm=8.5 through_all=true.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
    {"id": "tm11_turbine_disk", "name": "T3 涡轮盘", "dialects": ["axisymmetric"],
     "prompt": "涡轮盘, 单位 mm.\nrevolve_profile: station1 r=150 z=0-20, station2 r=120 z=20-40, station3 r=80 z=40-65, station4 r=60 z=65-75, station5 r=50 z=75-85.\ncut_center_bore diameter_mm=30 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=80 hole_dia_mm=12.\ncut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=25.\ncut_annular_groove side=front inner_dia_mm=200 outer_dia_mm=240 depth_mm=6.\napply_safe_chamfer distance_mm=1.5 target=all_external_edges."},
    {"id": "tm12_robot_wrist", "name": "T3 机器人腕部", "dialects": ["axisymmetric"],
     "prompt": "机器人腕部壳体, 单位 mm.\nrevolve_profile: station1 r=80 z=0-200.\ncut_center_bore diameter_mm=152 through_all=true (壁厚4mm).\ncut_circular_hole_pattern count=6 pcd_mm=140 hole_dia_mm=8.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
    {"id": "tm13_exhaust_manifold", "name": "T3 排气歧管", "dialects": ["loft_sweep"],
     "prompt": "排气歧管S形弯管, 单位 mm.\ncreate_sweep_path path_points (使用 x_mm/y_mm/z_mm): [{x_mm:0,y_mm:0,z_mm:0},{x_mm:0,y_mm:30,z_mm:80},{x_mm:0,y_mm:60,z_mm:160},{x_mm:0,y_mm:30,z_mm:240},{x_mm:0,y_mm:0,z_mm:320}].\nsweep_profile shape=circle radius_mm=18.\n所有节点同一组件, owner_dialect=loft_sweep."},
    {"id": "tm14_hyd_valve", "name": "T3 液压阀体", "dialects": ["sketch_extrude"],
     "prompt": "液压阀体, 单位 mm.\nextrude_rectangle width_mm=80 height_mm=60 depth_mm=200 centered=true.\nP口: cut_hole diameter_mm=20 position_mm=[0,0] through_all=true axis=Z.\nA口: cut_hole diameter_mm=10 position_mm=[0,15] through_all=true axis=Y.\nB口: cut_hole diameter_mm=10 position_mm=[0,-15] through_all=true axis=Y.\n安装孔x4: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=40.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
    {"id": "tm15_diff_case", "name": "T3 差速器壳体", "dialects": ["axisymmetric"],
     "prompt": "差速器壳体, 单位 mm.\nrevolve_profile: station1 r=75 z=0-20, station2 r=60 z=20-80, station3 r=75 z=80-100.\ncut_center_bore diameter_mm=100 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\ncut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=140 depth_mm=3.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
]

# Add stress20 cases
STRESS20_CASES = [
    {"id": "s01_thin_flange", "name": "S1 超大薄壁法兰", "dialects": ["axisymmetric"],
     "prompt": "超大薄壁法兰, 单位 mm.\nrevolve_profile: station1 r=250 z=0-8.\ncut_center_bore diameter_mm=480 through_all=true.\ncut_circular_hole_pattern count=24 pcd_mm=470 hole_dia_mm=12.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
    {"id": "s02_micro_bushing", "name": "S2 微型轴套", "dialects": ["axisymmetric"],
     "prompt": "微型轴套, 单位 mm.\nrevolve_profile: station1 r=3 z=0-12.\ncut_center_bore diameter_mm=5 through_all=true.\napply_safe_chamfer distance_mm=0.2 target=all_external_edges."},
    {"id": "s03_dense_rib", "name": "S3 密集筋板", "dialects": ["sketch_extrude"],
     "prompt": "密集筋板, 单位 mm.\nextrude_rectangle width_mm=300 height_mm=200 depth_mm=15 centered=true.\ncut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=260 spacing_y_mm=160.\n纵筋x5: add_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[-80,0,7.5] direction=Y. add_rib ... 密集排列.\napply_safe_fillet radius_mm=1.5 target=all_external_edges."},
    {"id": "s04_deep_holes", "name": "S4 深孔阀块", "dialects": ["sketch_extrude"],
     "prompt": "深孔交叉阀块, 单位 mm.\nextrude_rectangle width_mm=100 height_mm=80 depth_mm=150 centered=true.\ncut_hole diameter_mm=25 position_mm=[0,0] through_all=true axis=Z.\ncut_hole diameter_mm=15 position_mm=[0,20] through_all=true axis=Y.\ncut_hole diameter_mm=15 position_mm=[0,-20] through_all=true axis=Y.\ncut_hole diameter_mm=10 position_mm=[25,0] through_all=true axis=X.\ncut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
    {"id": "s05_long_spring", "name": "S5 长弹簧", "dialects": ["loft_sweep"],
     "prompt": "长螺旋弹簧, 单位 mm.\nhelix_sweep: radius_mm=20 height_mm=150 pitch_mm=10 profile_radius_mm=1.5 turns=15.\n注意: helix_sweep, 不是sweep_profile。中径40mm, 簧丝直径3mm, 15圈, 自由长度150mm."},
    {"id": "s06_double_flange", "name": "S6 双层法兰", "dialects": ["axisymmetric", "composition"],
     "prompt": "双层法兰装配, 单位 mm.\n组件 'flange_a' (axisymmetric): revolve_profile station1 r=80 z=0-15. cut_center_bore diameter_mm=60 through_all=true. cut_circular_hole_pattern count=8 pcd_mm=140 hole_dia_mm=11.\n组件 'flange_b' (axisymmetric): revolve_profile station1 r=80 z=0-15. cut_center_bore diameter_mm=60 through_all=true. cut_circular_hole_pattern count=8 pcd_mm=140 hole_dia_mm=11.\n装配 '__assembly__' (composition): boolean_union 合并两个 flange.\nboolean_union inputs: [{component: flange_a, output: body}, {component: flange_b, output: body}]."},
    {"id": "s07_cross_rib", "name": "S7 十字筋箱体", "dialects": ["sketch_extrude"],
     "prompt": "十字筋箱体, 单位 mm.\nextrude_rectangle width_mm=250 height_mm=180 depth_mm=20 centered=true.\ncut_rectangular_pocket width_mm=200 height_mm=130 depth_mm=12 centered=true.\n横纵筋各5条: add_rib thickness_mm=5 height_mm=16 length_mm=120 position_mm=[-60,0,0] direction=Y 等.\ncut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=210 spacing_y_mm=140.\napply_safe_fillet radius_mm=2 target=all_external_edges."},
    {"id": "s08_full_shaft", "name": "S8 全特征轴", "dialects": ["axisymmetric"],
     "prompt": "全特征传动轴, 单位 mm.\nrevolve_profile 7段: station1 r=18 z=0-12, station2 r=12 z=12-45, station3 r=16 z=45-55, station4 r=10 z=55-95, station5 r=14 z=95-105, station6 r=8 z=105-135, station7 r=6 z=135-145.\ncut_center_bore diameter_mm=6 through_all=true.\ncut_external_thread nominal_dia_mm=6 pitch_mm=1.0 length_mm=10 standard=ISO_metric thread_class=6g.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
    {"id": "s09_var_sweep", "name": "S9 变径扫掠管", "dialects": ["loft_sweep"],
     "prompt": "变径扫掠管, 单位 mm.\ncreate_sweep_path path_points(x_mm/y_mm/z_mm): [{x_mm:0,y_mm:0,z_mm:0},{x_mm:60,y_mm:20,z_mm:50},{x_mm:80,y_mm:0,z_mm:100},{x_mm:40,y_mm:-20,z_mm:150},{x_mm:0,y_mm:0,z_mm:200}].\nsweep_profile shape=circle radius_mm=10."},
    {"id": "s10_shelled_box", "name": "S10 薄壁壳体", "dialects": ["sketch_extrude", "shell_housing"],
     "prompt": "薄壁壳体, 单位 mm.\nextrude_rectangle width_mm=200 height_mm=150 depth_mm=100 centered=true.\ncut_rectangular_pocket width_mm=180 height_mm=130 depth_mm=90 centered=true.\nshell_body thickness_mm=3."},
    {"id": "s11_coupling", "name": "S11 联轴器总成", "dialects": ["axisymmetric", "sketch_extrude", "composition"],
     "prompt": "联轴器总成, 单位 mm.\n组件 'hub_a' (axisymmetric): revolve_profile station1 r=50 z=0-40. cut_center_bore diameter_mm=25 through_all=true. cut_circular_hole_pattern count=6 pcd_mm=70 hole_dia_mm=10.\n组件 'hub_b' (axisymmetric): revolve_profile station1 r=50 z=0-40. cut_center_bore diameter_mm=25 through_all=true. cut_circular_hole_pattern count=6 pcd_mm=70 hole_dia_mm=10.\n组件 'spider' (sketch_extrude): extrude_rectangle width_mm=80 height_mm=80 depth_mm=20 centered=true.\n装配 '__assembly__' (composition): 依次boolean_union合并. 每次boolean_union只能2个inputs."},
    {"id": "s12_reducer_base", "name": "S12 减速器底座", "dialects": ["sketch_extrude", "axisymmetric", "composition"],
     "prompt": "减速器底座, 单位 mm.\n组件 'base' (sketch_extrude): extrude_rectangle width_mm=400 height_mm=250 depth_mm=30 centered=true. cut_rectangular_pocket width_mm=350 height_mm=200 depth_mm=15 centered=true. cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=340 spacing_y_mm=190. add_rib thickness_mm=10 height_mm=25 length_mm=200 position_mm=[0,80,15] direction=Y.\n组件 'bearing_a' (axisymmetric): revolve_profile station1 r=45 z=0-50. cut_center_bore diameter_mm=30 through_all=true.\n组件 'bearing_b' (axisymmetric): revolve_profile station1 r=45 z=0-50. cut_center_bore diameter_mm=30 through_all=true.\n装配 '__assembly__' (composition): 依次boolean_union. 每组只2 inputs."},
    {"id": "s13_pipe_system", "name": "S13 多管路系统", "dialects": ["loft_sweep", "composition"],
     "prompt": "多管路系统, 单位 mm.\n组件 'pipe_a' (loft_sweep): create_sweep_path [{x_mm:-30,y_mm:0,z_mm:0},{x_mm:-30,y_mm:0,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}]. sweep_profile shape=circle radius_mm=15.\n组件 'pipe_b' (loft_sweep): create_sweep_path [{x_mm:30,y_mm:0,z_mm:0},{x_mm:30,y_mm:0,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}]. sweep_profile shape=circle radius_mm=15.\n组件 'main' (loft_sweep): create_sweep_path [{x_mm:0,y_mm:0,z_mm:300},{x_mm:0,y_mm:0,z_mm:500}]. sweep_profile shape=circle radius_mm=30.\n装配 '__assembly__' (composition): 依次boolean_union合并pipe_a pipe_b main."},
    {"id": "s14_bearing_full", "name": "S14 完整轴承座", "dialects": ["axisymmetric", "sketch_extrude", "composition"],
     "prompt": "完整轴承座, 单位 mm.\n组件 'housing' (axisymmetric): revolve_profile station1 r=55 z=0-20, station2 r=40 z=20-70, station3 r=35 z=70-75. cut_center_bore diameter_mm=50 through_all=true. cut_circular_hole_pattern count=4 pcd_mm=90 hole_dia_mm=10.\n组件 'base' (sketch_extrude): extrude_rectangle width_mm=200 height_mm=120 depth_mm=20 centered=true. cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=160 spacing_y_mm=80.\n装配 '__assembly__' (composition): boolean_union 合并 housing 和 base. inputs: [{component: housing, output: body}, {component: base, output: body}]."},
    {"id": "s15_multi_valve", "name": "S15 多端口阀块", "dialects": ["sketch_extrude"],
     "prompt": "多端口阀块, 单位 mm.\nextrude_rectangle width_mm=120 height_mm=100 depth_mm=180 centered=true.\nP口T口A口B口多个不同方向孔.\ncut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=100 spacing_y_mm=80.\napply_safe_chamfer distance_mm=0.3 target=all_external_edges."},
    {"id": "s16_turbo_rotor", "name": "S16 涡轮转子", "dialects": ["axisymmetric"],
     "prompt": "涡轮增压器转子轴, 单位 mm.\nrevolve_profile 10段: station1 r=35 z=0-8, station2 r=25 z=8-20, station3 r=18 z=20-45, station4 r=22 z=45-50, station5 r=15 z=50-85, station6 r=20 z=85-95, station7 r=12 z=95-130, station8 r=16 z=130-140, station9 r=28 z=140-150, station10 r=20 z=150-160.\ncut_center_bore diameter_mm=5 through_all=true.\ncut_external_thread nominal_dia_mm=20 pitch_mm=2.5 length_mm=10 standard=ISO_metric thread_class=6g.\napply_safe_chamfer distance_mm=0.3 target=all_external_edges."},
    {"id": "s17_3d_pipe", "name": "S17 3D空间弯管", "dialects": ["loft_sweep"],
     "prompt": "三维空间弯管, 单位 mm.\ncreate_sweep_path path_points(x_mm/y_mm/z_mm): [{x_mm:0,y_mm:0,z_mm:0},{x_mm:30,y_mm:20,z_mm:40},{x_mm:60,y_mm:0,z_mm:80},{x_mm:40,y_mm:-30,z_mm:120},{x_mm:0,y_mm:-20,z_mm:160},{x_mm:-30,y_mm:0,z_mm:200},{x_mm:-10,y_mm:20,z_mm:240},{x_mm:0,y_mm:40,z_mm:280}].\nsweep_profile shape=circle radius_mm=8."},
    {"id": "s18_thin_shell", "name": "S18 大型薄壳", "dialects": ["sketch_extrude", "shell_housing"],
     "prompt": "大型薄壁壳体, 单位 mm.\nextrude_rectangle width_mm=400 height_mm=300 depth_mm=150 centered=true.\ncut_rectangular_pocket width_mm=380 height_mm=280 depth_mm=140 centered=true.\nshell_body thickness_mm=2."},
    {"id": "s19_workbench", "name": "S19 多体工作台", "dialects": ["sketch_extrude", "axisymmetric", "composition"],
     "prompt": "多体组合工作台, 单位 mm.\n组件 'top_plate' (sketch_extrude): extrude_rectangle width_mm=500 height_mm=350 depth_mm=25 centered=true. cut_rectangular_pocket width_mm=400 height_mm=250 depth_mm=10 centered=true. cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=400 spacing_y_mm=250.\n组件 'bottom_plate' (sketch_extrude): extrude_rectangle width_mm=500 height_mm=350 depth_mm=20 centered=true.\n组件 'pillar_left' (axisymmetric): revolve_profile station1 r=30 z=0-200. cut_center_bore diameter_mm=20 through_all=true.\n组件 'pillar_right' (axisymmetric): revolve_profile station1 r=30 z=0-200. cut_center_bore diameter_mm=20 through_all=true.\n装配 '__assembly__' (composition): 依次boolean_union合并4个组件. 每次只2 inputs."},
    {"id": "s20_ultimate", "name": "S20 终极综合件", "dialects": ["axisymmetric", "sketch_extrude", "loft_sweep", "composition"],
     "prompt": "终极综合测试装配, 单位 mm.\n组件 'rotor' (axisymmetric): revolve_profile station1 r=80 z=0-15, station2 r=60 z=15-50, station3 r=40 z=50-65. cut_center_bore diameter_mm=30 through_all=true. cut_circular_hole_pattern count=6 pcd_mm=110 hole_dia_mm=10. apply_safe_chamfer distance_mm=1 target=all_external_edges.\n组件 'mount' (sketch_extrude): extrude_rectangle width_mm=250 height_mm=180 depth_mm=25 centered=true. cut_rectangular_pocket width_mm=180 height_mm=120 depth_mm=15 centered=true. cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=200 spacing_y_mm=130.\n组件 'pipe' (loft_sweep): create_sweep_path [{x_mm:0,y_mm:0,z_mm:0},{x_mm:50,y_mm:30,z_mm:60},{x_mm:100,y_mm:0,z_mm:120}]. sweep_profile shape=circle radius_mm=12.\n装配 '__assembly__' (composition): 依次boolean_union合并3个组件. 每次只2 inputs."},
]

CASES.extend(STRESS20_CASES)


# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_llm_json(text: str) -> str:
    """Remove control characters that break JSON parsing (except newline, tab, CR)."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)


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
    raw_json = resp.choices[0].message.tool_calls[0].function.arguments
    return json.loads(_sanitize_llm_json(raw_json))


def build_step(cdir):
    can = (cdir / "canonical.json").as_posix()
    val = (cdir / "validation_bundle.json").as_posix()
    stp = (cdir / "output.step").as_posix()
    met = (cdir / "output.metadata.json").as_posix()
    bscript = (
        "import sys; sys.path.insert(0, r'" + SRC.as_posix() + "')\n"
        "from pathlib import Path\n"
        "from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files\n"
        "r = run_canonical_gcad_from_files(canonical_json=Path(r'" + can + "'),validation_seed_json=Path(r'" + val + "'),"
        "out_step=Path(r'" + stp + "'),metadata_path=Path(r'" + met + "'))\n"
        "if r.ok: print('BUILD_OK')\nelse: print(f'BUILD_FAILED: {r.error}')\n"
    )
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text(f"RC={r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
    return r.returncode == 0 and (cdir / "output.step").exists()


if __name__ == "__main__":
    import datetime
    print(f"=== v5.1 Full35: {len(CASES)} cases ===\nOutput: {OUT}\n")

    results = []
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        contract = build_full_contract(case["dialects"])
        base_msg = f"TASK: {case['prompt']}\n\n{contract}\n\nCRITICAL: Use EXACT op/param names from contract. Output solid→body. direction=+/-. path_points x_mm/y_mm/z_mm. target=all_external_edges. All safety=true. trust_level=reference_geometry. For composition boolean_union: params={{}}, inputs use component refs, ALWAYS exactly 2 inputs."
        start = time.time()

        ok = False; err = ""
        for attempt in range(5):
            um = base_msg + (f"\n\nFAILED ({attempt+1}/5): {err[:600]}\nFIX ALL ERRORS." if attempt > 0 else "")
            try: args = call_llm(um)
            except Exception as e: err = f"LLM:{e}"; continue
            (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

            try:
                fixed, af = auto_fix_with_report(args, REG)
                (cdir / "autofix_report.json").write_text(json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
                if af.applied: (cdir / "raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
            except: fixed = args
            fixed.setdefault("llm_validation_hints", {})
            if fixed.get("llm_validation_hints") is None: fixed["llm_validation_hints"] = {}
            fixed.setdefault("units", "mm"); fixed.setdefault("trust_level", "reference_geometry")

            try:
                doc = RawGcadDocument.model_validate(fixed)
                canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
                if not (canonical and report and report.ok):
                    issues = report.issues if report else []
                    err = "; ".join("[{}] {}".format(getattr(i,"code","?"), getattr(i,"message",str(i))[:120]) for i in (issues[:3] if issues else []))
                    continue
                (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                if bundle: (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                ok = True; break
            except AssemblyError as e: err = f"AssemblyError:{e}"; continue
            except Exception as e: err = f"Pydantic:{e}"; continue

        if not ok:
            print(f"[{i+1:02d}/35] {case['name']:25s} FAIL: {err[:150]} [{time.time()-start:.0f}s]")
            results.append({"id": case["id"], "name": case["name"], "ok": False, "msg": err[:200]})
            continue

        # Build STEP
        if build_step(cdir):
            sz = (cdir / "output.step").stat().st_size
            # Semantic postcheck
            sem = "?"
            try:
                from seekflow_engineering_tools.generative_cad.authoring.design_intent_extractor import extract_design_intent_metrics
                from seekflow_engineering_tools.generative_cad.runtime.semantic_postcheck import run_semantic_postcheck
                intent = extract_design_intent_metrics(case["prompt"])
                sp = run_semantic_postcheck(step_path=cdir / "output.step", design_intent=intent)
                sem = "OK" if sp.semantic_valid else "FAIL"
                (cdir / "semantic_postcheck.json").write_text(json.dumps(sp.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            except: pass
            print(f"[{i+1:02d}/35] {case['name']:25s} STEP={sz}B sem={sem} [{time.time()-start:.0f}s]")
            results.append({"id": case["id"], "name": case["name"], "ok": True, "msg": f"STEP={sz}B sem={sem}"})
        else:
            print(f"[{i+1:02d}/35] {case['name']:25s} BUILD_FAIL [{time.time()-start:.0f}s]")
            results.append({"id": case["id"], "name": case["name"], "ok": False, "msg": "STEP build failed"})
        time.sleep(0.3)

    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== RESULTS: {passed}/{len(results)} passed ===")
    report = {"timestamp": datetime.datetime.now().isoformat(), "total": len(results),
              "passed": passed, "pipeline": "v5.1-full35", "results": results}
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {OUT}/report.json")
