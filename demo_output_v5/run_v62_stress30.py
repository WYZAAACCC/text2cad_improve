"""v6.2 Stress Test — 30 new high-complexity industrial parts never tested before.

Categories:
  Group 1: Complex Assemblies (spatial stress) — 5 parts
  Group 2: Sweep/Loft/Helix stress — 5 parts
  Group 3: Thin-Wall/Shell — 4 parts
  Group 4: Multi-Feature Single Parts — 5 parts
  Group 5: Mixed Dialect — 4 parts
  Group 6: Edge Cases — 4 parts
  Group 7: Real-World Industrial — 3 parts
"""
import json, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "v62_stress30_output"
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
    lines = [
        "=== DIALECT CONTRACTS (EXACT names required) ===", "",
        "=== CRITICAL RULES ===",
        "  output type=solid -> name='body' (NEVER 'solid')",
        "  output type=frame -> name='outer_frame'",
        "  output type=curve -> name='curve'",
        "  extrude direction: '+' or '-' (NEVER 'Z','X','Y')",
        "  path_points: x_mm/y_mm/z_mm (NEVER x,y,z)",
        "  chamfer/fillet target: 'all_external_edges'",
        "  revolve_profile: 'profile_stations' (NOT 'stations')",
        "  thread_class internal: '6H','6G','7H'. external: '6g','6h','8g'",
        "  ALL 7 safety flags: true. trust_level='reference_geometry'.",
        "  boolean_union: params={}, inputs COMPONENT refs, ALWAYS exactly 2 inputs.",
        "  Composition ONLY in __assembly__. op_version ALWAYS '1.0.0'.",
        "  Node field 'params' NOT 'parameters'.",
        "  cut_hole NOW supports axis='X'/'Y'/'Z' for side drilling!", "",
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
            lines.append(f"    params: {' | '.join(pstrs[:12])}")
            if op_name == "revolve_profile":
                lines.append('    EXAMPLE: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":20}]}')
            elif op_name == "extrude_rectangle":
                lines.append('    EXAMPLE: {"width_mm":100,"height_mm":80,"depth_mm":15,"plane":"XY","centered":true,"direction":"+"}')
            elif op_name == "create_sweep_path":
                lines.append('    EXAMPLE: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":50,"y_mm":0,"z_mm":100}]}')
            elif op_name == "sweep_profile":
                lines.append('    EXAMPLE: {"shape":"circle","radius_mm":12}')
            elif op_name == "helix_sweep":
                lines.append('    EXAMPLE: {"radius_mm":15,"height_mm":80,"pitch_mm":10,"profile_radius_mm":1.5,"turns":8}')
            elif op_name == "boolean_union":
                lines.append('    EXAMPLE: params={}, inputs=[{component:c1,output:body},{component:c2,output:body}]')
            elif op_name == "shell_body":
                lines.append('    EXAMPLE: {"thickness_mm":2.0}')
            elif op_name == "cut_circular_hole_pattern":
                lines.append('    EXAMPLE: {"count":8,"pcd_mm":120,"hole_dia_mm":11,"axis":"Z","through_all":true}')
            elif op_name == "loft_sections":
                lines.append('    EXAMPLE: {"sections":[{"position":{"x_mm":0,"y_mm":0,"z_mm":0},"shape":"circle","radius_mm":20},{"position":{"x_mm":0,"y_mm":0,"z_mm":50},"shape":"circle","radius_mm":30}]}')
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
    raw_json = resp.choices[0].message.tool_calls[0].function.arguments
    return json.loads(raw_json)


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
    bp = cdir / "_build.py"; bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=600, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text(f"RC={r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
    return r.returncode == 0 and (cdir / "output.step").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 30 NEW high-complexity industrial parts
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    # ══════════ Group 1: Complex Assemblies (spatial stress) ══════════
    {"id":"g1_engine_mount","name":"发动机悬置支架总成","dialects":["sketch_extrude","axisymmetric","composition"],
     "prompt":"汽车发动机悬置支架总成, 单位mm.\n"
              "组件base_plate(sketch_extrude): extrude_rectangle width_mm=300 height_mm=200 depth_mm=25 centered=true. "
              "cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\n"
              "组件bushing_left(axisymmetric): revolve_profile station1 r=30 z=0-50. cut_center_bore diameter_mm=16.\n"
              "组件bushing_right(axisymmetric): revolve_profile station1 r=30 z=0-50. cut_center_bore diameter_mm=16.\n"
              "组件mount_bracket(sketch_extrude): extrude_rectangle width_mm=80 height_mm=60 depth_mm=15 centered=true. "
              "cut_hole diameter_mm=10 position_mm=[-25,0]. cut_hole diameter_mm=10 position_mm=[25,0]. "
              "add_rib thickness_mm=8 height_mm=20 length_mm=40 position_mm=[0,0,7.5] direction=Y.\n"
              "装配__assembly__(composition): 依次boolean_union合并4个组件(每次2 inputs)."},

    {"id":"g2_gearbox_housing","name":"减速器箱体总成","dialects":["sketch_extrude","axisymmetric","composition"],
     "prompt":"工业减速器箱体总成, 单位mm.\n"
              "组件housing_base(sketch_extrude): extrude_rectangle width_mm=500 height_mm=350 depth_mm=40 centered=true. "
              "cut_rectangular_pocket width_mm=440 height_mm=290 depth_mm=30. "
              "cut_hole_pattern_linear hole_dia_mm=18 count_x=2 count_y=2 spacing_x_mm=440 spacing_y_mm=290. "
              "add_rib thickness_mm=12 height_mm=25 length_mm=300 position_mm=[-120,0,20] direction=Y. "
              "add_rib thickness_mm=12 height_mm=25 length_mm=300 position_mm=[120,0,20] direction=Y.\n"
              "组件bearing_housing_a(axisymmetric): revolve_profile station1 r=80 z=0-70,station2 r=60 z=70-75. "
              "cut_center_bore diameter_mm=50. cut_circular_hole_pattern count=6 pcd_mm=120 hole_dia_mm=12.\n"
              "组件bearing_housing_b(axisymmetric): revolve_profile station1 r=80 z=0-70,station2 r=60 z=70-75. "
              "cut_center_bore diameter_mm=50. cut_circular_hole_pattern count=6 pcd_mm=120 hole_dia_mm=12.\n"
              "装配__assembly__(composition): 依次boolean_union合并housing_base+bearing_a+bearing_b(每次2 inputs)."},

    {"id":"g3_hyd_manifold","name":"液压集成块","dialects":["sketch_extrude"],
     "prompt":"工程机械液压集成块, 单位mm.\n"
              "extrude_rectangle width_mm=150 height_mm=120 depth_mm=180 centered=true.\n"
              "主油路口P: cut_hole diameter_mm=25 position_mm=[0,0] axis=Z.\n"
              "工作口A: cut_hole diameter_mm=20 position_mm=[50,30] axis=Y.\n"
              "工作口B: cut_hole diameter_mm=20 position_mm=[-50,30] axis=Y.\n"
              "工作口C: cut_hole diameter_mm=20 position_mm=[50,-30] axis=Y.\n"
              "工作口D: cut_hole diameter_mm=20 position_mm=[-50,-30] axis=Y.\n"
              "泄油口T: cut_hole diameter_mm=15 position_mm=[0,0] axis=X.\n"
              "安装孔x4: cut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=120 spacing_y_mm=90.\n"
              "apply_safe_chamfer distance_mm=0.5 target=all_external_edges."},

    {"id":"g4_pump_casing","name":"离心泵蜗壳","dialects":["axisymmetric","sketch_extrude","composition"],
     "prompt":"离心泵蜗壳总成, 单位mm.\n"
              "组件volute(axisymmetric): revolve_profile station1 r=120 z=0-30,station2 r=90 z=30-80,station3 r=60 z=80-85. "
              "cut_center_bore diameter_mm=50. cut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=14.\n"
              "组件discharge_flange(sketch_extrude): extrude_rectangle width_mm=150 height_mm=100 depth_mm=20 centered=true. "
              "cut_hole diameter_mm=60 position_mm=[0,0]. "
              "cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=100 spacing_y_mm=60.\n"
              "组件base(sketch_extrude): extrude_rectangle width_mm=250 height_mm=200 depth_mm=30 centered=true. "
              "cut_hole_pattern_linear hole_dia_mm=16 count_x=2 count_y=2 spacing_x_mm=200 spacing_y_mm=150.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"g5_robot_arm","name":"机器人手臂段","dialects":["axisymmetric","sketch_extrude","composition"],
     "prompt":"工业机器人手臂段总成, 单位mm.\n"
              "组件arm_tube(axisymmetric): revolve_profile station1 r=65 z=0-500. cut_center_bore diameter_mm=110 (壁厚10mm).\n"
              "组件flange_a(axisymmetric): revolve_profile station1 r=90 z=0-25. cut_center_bore diameter_mm=110. "
              "cut_circular_hole_pattern count=8 pcd_mm=150 hole_dia_mm=10.\n"
              "组件flange_b(axisymmetric): revolve_profile station1 r=90 z=0-25. cut_center_bore diameter_mm=110. "
              "cut_circular_hole_pattern count=8 pcd_mm=150 hole_dia_mm=10.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    # ══════════ Group 2: Sweep/Loft/Helix stress ══════════
    {"id":"g6_helix_coil","name":"螺旋换热盘管","dialects":["loft_sweep"],
     "prompt":"工业螺旋换热盘管, 单位mm.\n"
              "helix_sweep radius_mm=80 height_mm=400 pitch_mm=20 profile_radius_mm=6 turns=20.\n"
              "大直径80mm螺旋管, 20圈, 管径12mm, 总高400mm. 使用helix_sweep."},

    {"id":"g7_3d_tube","name":"复杂空间管路","dialects":["loft_sweep"],
     "prompt":"发动机舱复杂空间管路, 单位mm.\n"
              "create_sweep_path path_points(x_mm/y_mm/z_mm):[{x_mm:0,y_mm:0,z_mm:0},{x_mm:80,y_mm:40,z_mm:60},"
              "{x_mm:120,y_mm:-20,z_mm:140},{x_mm:60,y_mm:-80,z_mm:200},{x_mm:0,y_mm:-40,z_mm:280},"
              "{x_mm:-60,y_mm:20,z_mm:340},{x_mm:-40,y_mm:60,z_mm:400},{x_mm:0,y_mm:80,z_mm:460}].\n"
              "sweep_profile shape=circle radius_mm=10. 8个控制点的空间扭曲管路."},

    {"id":"g8_var_duct","name":"变截面过渡管","dialects":["loft_sweep"],
     "prompt":"变截面过渡管道, 单位mm.\n"
              "loft_sections sections:[{position:{x_mm:0,y_mm:0,z_mm:0},shape:circle,radius_mm:40},"
              "{position:{x_mm:0,y_mm:0,z_mm:60},shape:circle,radius_mm:55},"
              "{position:{x_mm:0,y_mm:0,z_mm:120},shape:rectangle,width_mm:100,height_mm:80},"
              "{position:{x_mm:0,y_mm:0,z_mm:200},shape:circle,radius_mm:65}].\n"
              "4个截面从圆过渡到矩形再回到圆. 使用loft_sections."},

    {"id":"g9_torsion_spring","name":"扭力弹簧","dialects":["loft_sweep"],
     "prompt":"扭力弹簧, 单位mm.\n"
              "helix_sweep radius_mm=25 height_mm=120 pitch_mm=8 profile_radius_mm=3 turns=15.\n"
              "中径50mm扭力弹簧, 簧丝直径6mm, 15圈, 自由长度120mm, 螺距8mm."},

    {"id":"g10_spiral_volute","name":"螺旋蜗壳","dialects":["loft_sweep"],
     "prompt":"风机螺旋蜗壳扫掠, 单位mm.\n"
              "create_sweep_path path_points(x_mm/y_mm/z_mm):[{x_mm:50,y_mm:0,z_mm:0},{x_mm:60,y_mm:10,z_mm:0},"
              "{x_mm:75,y_mm:25,z_mm:0},{x_mm:95,y_mm:45,z_mm:0},{x_mm:120,y_mm:70,z_mm:0},"
              "{x_mm:150,y_mm:100,z_mm:0},{x_mm:185,y_mm:135,z_mm:0},{x_mm:225,y_mm:175,z_mm:0}].\n"
              "sweep_profile shape=circle radius_mm=15. 螺旋渐开线蜗壳, 8点控制."},

    # ══════════ Group 3: Thin-Wall/Shell ══════════
    {"id":"g11_pressure_vessel","name":"薄壁压力容器","dialects":["axisymmetric","shell_housing"],
     "prompt":"薄壁压力容器, 单位mm.\n"
              "revolve_profile station1 r=150 z=0-10,station2 r=150 z=10-400,station3 r=150 z=400-410.\n"
              "shell_body thickness_mm=5 (5mm壁厚). 容器直径300mm, 高度400mm. "
              "注意: revolve_profile和shell_body在同一个组件, shell_body的input指向revolve节点."},

    {"id":"g12_hollow_bracket","name":"空心结构支架","dialects":["sketch_extrude","shell_housing"],
     "prompt":"航空航天空心结构支架, 单位mm.\n"
              "先extrude_rectangle width_mm=200 height_mm=120 depth_mm=60 centered=true.\n"
              "再cut_rectangular_pocket width_mm=180 height_mm=100 depth_mm=50.\n"
              "再add_rib thickness_mm=6 height_mm=20 length_mm=100 position_mm=[-60,0,0] direction=Y.\n"
              "再add_rib thickness_mm=6 height_mm=20 length_mm=100 position_mm=[60,0,0] direction=Y.\n"
              "最后shell_body thickness_mm=3. 所有节点同一组件, shell_body的input指向最后一个solid节点."},

    {"id":"g13_enclosure","name":"电子设备外壳","dialects":["sketch_extrude","shell_housing"],
     "prompt":"工业电子设备防护外壳, 单位mm.\n"
              "先extrude_rectangle width_mm=300 height_mm=200 depth_mm=150 centered=true.\n"
              "再shell_body thickness_mm=4.\n"
              "再cut_rectangular_pocket width_mm=260 height_mm=160 depth_mm=140 (内部空腔).\n"
              "再cut_hole_pattern_linear hole_dia_mm=8 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150 (安装孔).\n"
              "apply_safe_fillet radius_mm=2. 所有节点同一组件, owner_dialect=sketch_extrude."},

    {"id":"g14_vacuum_chamber","name":"真空腔体","dialects":["axisymmetric","sketch_extrude","composition"],
     "prompt":"真空腔体总成, 单位mm.\n"
              "组件chamber(axisymmetric): revolve_profile station1 r=100 z=0-300. shell_body thickness_mm=3.\n"
              "组件flange_top(sketch_extrude): extrude_rectangle width_mm=240 height_mm=240 depth_mm=20 centered=true. "
              "cut_hole diameter_mm=200 position_mm=[0,0]. cut_circular_hole_pattern count=12 pcd_mm=210 hole_dia_mm=10.\n"
              "组件flange_bottom(sketch_extrude): extrude_rectangle width_mm=240 height_mm=240 depth_mm=20 centered=true. "
              "cut_hole diameter_mm=200 position_mm=[0,0]. cut_circular_hole_pattern count=12 pcd_mm=210 hole_dia_mm=10.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    # ══════════ Group 4: Multi-Feature Single Parts ══════════
    {"id":"g15_heavy_flange","name":"重型法兰","dialects":["axisymmetric"],
     "prompt":"高压管道重型法兰, 单位mm.\n"
              "revolve_profile: station1 r=200 z=0-50,station2 r=150 z=50-55.\n"
              "cut_center_bore diameter_mm=200.\n"
              "cut_circular_hole_pattern count=24 pcd_mm=340 hole_dia_mm=22.\n"
              "cut_circular_hole_pattern count=12 pcd_mm=280 hole_dia_mm=18.\n"
              "cut_annular_groove side=front inner_dia_mm=240 outer_dia_mm=280 depth_mm=4.\n"
              "cut_annular_groove side=front inner_dia_mm=300 outer_dia_mm=340 depth_mm=4.\n"
              "apply_safe_chamfer distance_mm=2 target=all_external_edges."},

    {"id":"g16_stepped_pulley","name":"多级带轮","dialects":["axisymmetric"],
     "prompt":"多级V型带轮, 单位mm.\n"
              "revolve_profile 9段: station1 r=30 z=0-15,station2 r=60 z=15-25,station3 r=55 z=25-33,"
              "station4 r=80 z=33-43,station5 r=75 z=43-51,station6 r=100 z=51-61,station7 r=95 z=61-69,"
              "station8 r=120 z=69-79,station9 r=115 z=79-87.\n"
              "cut_center_bore diameter_mm=25.\n"
              "cut_circular_hole_pattern count=4 pcd_mm=50 hole_dia_mm=8.\n"
              "apply_safe_chamfer distance_mm=1.5."},

    {"id":"g17_cross_block","name":"六面钻孔块","dialects":["sketch_extrude"],
     "prompt":"六面全方向钻孔测试块, 单位mm.\n"
              "extrude_rectangle width_mm=100 height_mm=100 depth_mm=100 centered=true.\n"
              "顶面孔: cut_hole diameter_mm=30 position_mm=[0,0] axis=Z.\n"
              "底面孔: cut_hole diameter_mm=25 position_mm=[0,0] axis=Z.\n"
              "前侧孔: cut_hole diameter_mm=20 position_mm=[0,0] axis=Y.\n"
              "后侧孔: cut_hole diameter_mm=20 position_mm=[0,0] axis=Y.\n"
              "左侧孔: cut_hole diameter_mm=15 position_mm=[0,0] axis=X.\n"
              "右侧孔: cut_hole diameter_mm=15 position_mm=[0,0] axis=X.\n"
              "安装孔x4: cut_hole_pattern_linear hole_dia_mm=8 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=80.\n"
              "apply_safe_chamfer distance_mm=0.5."},

    {"id":"g18_ribbed_panel","name":"密集筋板结构","dialects":["sketch_extrude"],
     "prompt":"航空结构密集筋板, 单位mm.\n"
              "extrude_rectangle width_mm=400 height_mm=300 depth_mm=20 centered=true.\n"
              "纵向筋x7: add_rib thickness_mm=4 height_mm=30 length_mm=250 position_mm=[-150,0,0] direction=Y. "
              "add_rib ... position_mm=[-100,0,0] ... [-50,0,0] ... [0,0,0] ... [50,0,0] ... [100,0,0] ... [150,0,0].\n"
              "横向筋x5: add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[0,-100,0] direction=X. "
              "add_rib ... position_mm=[0,-50,0] ... [0,0,0] ... [0,50,0] ... [0,100,0].\n"
              "cut_hole_pattern_linear hole_dia_mm=10 count_x=3 count_y=3 spacing_x_mm=150 spacing_y_mm=100.\n"
              "apply_safe_fillet radius_mm=1."},

    {"id":"g19_precision_base","name":"精密仪器基座","dialects":["sketch_extrude"],
     "prompt":"光学精密仪器基座, 单位mm.\n"
              "extrude_rectangle width_mm=250 height_mm=200 depth_mm=35 centered=true.\n"
              "cut_rectangular_pocket width_mm=200 height_mm=150 depth_mm=15.\n"
              "精密安装孔x4: cut_hole diameter_mm=12 position_mm=[-80,60]. "
              "cut_hole diameter_mm=12 position_mm=[80,60]. "
              "cut_hole diameter_mm=12 position_mm=[-80,-60]. "
              "cut_hole diameter_mm=12 position_mm=[80,-60].\n"
              "定位销孔x2: cut_hole diameter_mm=6 position_mm=[-90,0]. cut_hole diameter_mm=6 position_mm=[90,0].\n"
              "固定孔x4: cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=200 spacing_y_mm=150.\n"
              "加强筋x4: add_rib thickness_mm=5 height_mm=12 length_mm=180 position_mm=[-70,0,17.5] direction=Y. "
              "add_rib ... [70,0,17.5] ... [0,-50,17.5] direction=X ... [0,50,17.5] direction=X.\n"
              "减重孔x2: cut_hole diameter_mm=40 position_mm=[-50,0]. cut_hole diameter_mm=40 position_mm=[50,0].\n"
              "apply_safe_fillet radius_mm=1.5. apply_safe_chamfer distance_mm=0.3."},

    # ══════════ Group 5: Mixed Dialect ══════════
    {"id":"g20_motor_endbell","name":"电机端盖","dialects":["axisymmetric","sketch_extrude","composition"],
     "prompt":"电机端盖总成, 单位mm.\n"
              "组件endbell(axisymmetric): revolve_profile station1 r=100 z=0-15,station2 r=80 z=15-40,station3 r=60 z=40-45. "
              "cut_center_bore diameter_mm=30. cut_circular_hole_pattern count=6 pcd_mm=150 hole_dia_mm=10. "
              "cut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=160 depth_mm=3.\n"
              "组件mount_feet(sketch_extrude): extrude_rectangle width_mm=250 height_mm=40 depth_mm=20 centered=true. "
              "cut_hole diameter_mm=12 position_mm=[-100,0]. cut_hole diameter_mm=12 position_mm=[100,0].\n"
              "组件cooling_fins(sketch_extrude): extrude_rectangle width_mm=180 height_mm=5 depth_mm=30 centered=true.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"g21_valve_body","name":"阀体带法兰","dialects":["loft_sweep","axisymmetric","composition"],
     "prompt":"工业阀体总成, 单位mm.\n"
              "组件valve_chamber(axisymmetric): revolve_profile station1 r=50 z=0-120. "
              "cut_center_bore diameter_mm=40.\n"
              "组件inlet_flange(axisymmetric): revolve_profile station1 r=70 z=0-20. "
              "cut_center_bore diameter_mm=40. cut_circular_hole_pattern count=6 pcd_mm=110 hole_dia_mm=14.\n"
              "组件outlet_flange(axisymmetric): revolve_profile station1 r=70 z=0-20. "
              "cut_center_bore diameter_mm=40. cut_circular_hole_pattern count=6 pcd_mm=110 hole_dia_mm=14.\n"
              "组件flow_path(loft_sweep): create_sweep_path[{x_mm:0,y_mm:0,z_mm:0},{x_mm:30,y_mm:0,z_mm:60},{x_mm:0,y_mm:0,z_mm:120}]. "
              "sweep_profile shape=circle radius_mm=20.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"g22_heat_sink","name":"散热器总成","dialects":["sketch_extrude","shell_housing","composition"],
     "prompt":"大功率散热器总成, 单位mm.\n"
              "组件base_plate(sketch_extrude): extrude_rectangle width_mm=300 height_mm=200 depth_mm=15 centered=true.\n"
              "组件fin_array(sketch_extrude): extrude_rectangle width_mm=280 height_mm=3 depth_mm=80 centered=true.\n"
              "组件housing(sketch_extrude): extrude_rectangle width_mm=320 height_mm=220 depth_mm=100 centered=true. "
              "shell_body thickness_mm=4.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"g23_pipe_reducer","name":"变径管接头","dialects":["loft_sweep","axisymmetric","composition"],
     "prompt":"管道变径接头总成, 单位mm.\n"
              "组件reducer_body(loft_sweep): loft_sections sections:["
              "{position:{x_mm:0,y_mm:0,z_mm:0},shape:circle,radius_mm:80},"
              "{position:{x_mm:0,y_mm:0,z_mm:150},shape:circle,radius_mm:50}].\n"
              "组件flange_large(axisymmetric): revolve_profile station1 r=110 z=0-20. cut_center_bore diameter_mm=160. "
              "cut_circular_hole_pattern count=8 pcd_mm=190 hole_dia_mm=18.\n"
              "组件flange_small(axisymmetric): revolve_profile station1 r=80 z=0-20. cut_center_bore diameter_mm=100. "
              "cut_circular_hole_pattern count=8 pcd_mm=140 hole_dia_mm=14.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    # ══════════ Group 6: Edge Cases ══════════
    {"id":"g24_micro_bushing","name":"微型精密轴套","dialects":["axisymmetric"],
     "prompt":"微型精密仪表轴套, 单位mm.\n"
              "revolve_profile station1 r=1.5 z=0-8.\n"
              "cut_center_bore diameter_mm=2.5 (壁厚0.25mm).\n"
              "apply_safe_chamfer distance_mm=0.1. 超小尺寸零件, 外径3mm, 内径2.5mm, 壁厚仅0.25mm."},

    {"id":"g25_large_ring","name":"超大薄壁环","dialects":["axisymmetric"],
     "prompt":"超大直径薄壁环, 单位mm.\n"
              "revolve_profile station1 r=500 z=0-15.\n"
              "cut_center_bore diameter_mm=990 (壁厚5mm).\n"
              "cut_circular_hole_pattern count=36 pcd_mm=970 hole_dia_mm=10.\n"
              "apply_safe_chamfer distance_mm=0.5. 直径1米的薄壁环, 壁厚仅5mm, 36个螺栓孔."},

    {"id":"g26_extreme_shaft","name":"超长细轴","dialects":["axisymmetric"],
     "prompt":"超长细传动轴, 单位mm.\n"
              "revolve_profile: station1 r=8 z=0-500.\n"
              "cut_center_bore diameter_mm=6 (空心轴, 壁厚5mm).\n"
              "apply_safe_chamfer distance_mm=0.5. 长度500mm, 直径16mm, 长径比31:1."},

    {"id":"g27_dense_holes","name":"密集孔板","dialects":["sketch_extrude"],
     "prompt":"密集孔阵列测试板, 单位mm.\n"
              "extrude_rectangle width_mm=200 height_mm=150 depth_mm=10 centered=true.\n"
              "cut_hole_pattern_linear hole_dia_mm=3 count_x=20 count_y=15 spacing_x_mm=9 spacing_y_mm=9.\n"
              "密集排列20x15共300个3mm小孔, 孔间距9mm, 孔边距4.5mm. 测试大量孔的OCCT boolean性能."},

    # ══════════ Group 7: Real-World Industrial ══════════
    {"id":"g28_ball_valve","name":"球阀阀体","dialects":["axisymmetric","sketch_extrude","composition"],
     "prompt":"工业球阀阀体总成, 单位mm.\n"
              "组件valve_body(axisymmetric): revolve_profile station1 r=60 z=0-40,station2 r=45 z=40-120,station3 r=60 z=120-160. "
              "cut_center_bore diameter_mm=40. 侧向出口孔: cut_hole diameter_mm=40 position_mm=[0,80] axis=Y.\n"
              "组件flange_inlet(axisymmetric): revolve_profile station1 r=80 z=0-20. cut_center_bore diameter_mm=40. "
              "cut_circular_hole_pattern count=6 pcd_mm=130 hole_dia_mm=14.\n"
              "组件flange_outlet(axisymmetric): revolve_profile station1 r=80 z=0-20. cut_center_bore diameter_mm=40. "
              "cut_circular_hole_pattern count=6 pcd_mm=130 hole_dia_mm=14.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"g29_impeller","name":"离心叶轮","dialects":["axisymmetric","sketch_extrude","composition"],
     "prompt":"离心泵叶轮总成, 单位mm.\n"
              "组件impeller_disc(axisymmetric): revolve_profile station1 r=20 z=0-10,station2 r=150 z=10-25,station3 r=20 z=25-35. "
              "cut_center_bore diameter_mm=25.\n"
              "组件blade_1(sketch_extrude): extrude_rectangle width_mm=3 height_mm=120 depth_mm=20 centered=true.\n"
              "组件blade_2(sketch_extrude): extrude_rectangle width_mm=3 height_mm=120 depth_mm=20 centered=true.\n"
              "组件blade_3(sketch_extrude): extrude_rectangle width_mm=3 height_mm=120 depth_mm=20 centered=true.\n"
              "组件blade_4(sketch_extrude): extrude_rectangle width_mm=3 height_mm=120 depth_mm=20 centered=true.\n"
              "装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"g30_hyd_cylinder","name":"液压缸端盖","dialects":["axisymmetric"],
     "prompt":"工程机械液压缸端盖, 单位mm.\n"
              "revolve_profile: station1 r=70 z=0-15,station2 r=50 z=15-50,station3 r=55 z=50-65,station4 r=45 z=65-75.\n"
              "cut_center_bore diameter_mm=30.\n"
              "cut_external_thread nominal_dia_mm=60 pitch_mm=3 length_mm=20 standard=ISO_metric thread_class=6g.\n"
              "cut_circular_hole_pattern count=8 pcd_mm=110 hole_dia_mm=12.\n"
              "cut_annular_groove side=front inner_dia_mm=80 outer_dia_mm=100 depth_mm=3.\n"
              "apply_safe_chamfer distance_mm=1.5."},
]


if __name__ == "__main__":
    import datetime
    print(f"=== v6.2 Stress30: {len(CASES)} NEW high-complexity industrial parts ===")
    print(f"Output: {OUT}")
    print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    results = []
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]; cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        contract = build_full_contract(case["dialects"])
        base_msg = (
            f"TASK: {case['prompt']}\n\n{contract}\n\n"
            "CRITICAL: Use EXACT op/param names from contract. Output solid->body. "
            "direction=+/-. path_points x_mm/y_mm/z_mm. All safety=true. "
            "trust_level=reference_geometry. boolean_union ALWAYS 2 inputs. "
            "op_version '1.0.0'. cut_hole NOW supports axis='X'/'Y'/'Z'."
        )
        start = time.time(); ok = False; err = ""; attempts = 0
        for attempt in range(5):
            attempts = attempt + 1
            um = base_msg + (f"\n\nPREVIOUS FAILED ({attempt+1}/5): {err[:600]}\nFIX ALL ERRORS." if attempt > 0 else "")
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
                    try:
                        from seekflow_engineering_tools.generative_cad.validation.repair_hints import build_repair_hints_from_validation
                        hints = build_repair_hints_from_validation(report)
                        if hints: err = err + hints
                    except: pass
                    continue
                (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                if bundle: (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                ok = True; break
            except AssemblyError as e: err = f"Assembly:{e}"; continue
            except Exception as e: err = f"{type(e).__name__}:{e}"; continue

        elapsed = time.time()-start
        if not ok:
            print(f"[{i+1:02d}/30] {case['name']:20s} VALID_FAIL ({attempts} LLM) [{elapsed:.0f}s] {err[:100]}")
            results.append({"id":case["id"],"name":case["name"],"ok":False,"step_ok":False,"msg":err[:200],"attempts":attempts})
            continue

        step_ok = build_step(cdir)
        if step_ok:
            sz = (cdir / "output.step").stat().st_size
            print(f"[{i+1:02d}/30] {case['name']:20s} STEP={sz}B ({attempts} LLM) [{elapsed:.0f}s]")
            results.append({"id":case["id"],"name":case["name"],"ok":True,"step_ok":True,"step_size":sz,"attempts":attempts})
        else:
            print(f"[{i+1:02d}/30] {case['name']:20s} BUILD_FAIL ({attempts} LLM) [{elapsed:.0f}s]")
            results.append({"id":case["id"],"name":case["name"],"ok":True,"step_ok":False,"msg":"build failed","attempts":attempts})

    step_ok = sum(1 for r in results if r.get("step_ok"))
    print(f"\n{'='*60}")
    print(f"STRESS30: {step_ok}/{len(results)} STEP generated ({len(results)-step_ok} failed)")
    for r in results:
        s = "STEP_OK" if r.get("step_ok") else ("VAL_FAIL" if not r.get("ok") else "B_FAIL")
        print(f"  {r['id']:25s} {s:10s} attempts={r.get('attempts','?')} {r.get('step_size','')}")
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults: {OUT / 'results.json'}")
