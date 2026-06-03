"""test_model.md 全链路验证 — 15 个精选零件覆盖 4 个难度梯队。

每个 case: text → DeepSeek LLM (strict schema) → audited autofix → validate
→ canonical → CadQuery STEP → geometry audit → SolidWorks SLDPRT.

重点审计项: LLM 输出质量、STEP 几何正确性、模型体积/bbox 合理性、
chamfer/fillet 降级情况、autofix 修复记录。
"""

import json, os, sys, subprocess, time, traceback, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "test_model_output"
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix, auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()


def build_contract(dialect_ids):
    """为指定的 dialect 构建详细 contract text，含显式示例和禁止事项。"""
    lines = [
        "=== DIALECT CONTRACTS (exact names required) ===",
        "IMPORTANT RULES:",
        "  - output type=solid MUST use name='body' (NOT 'solid')",
        "  - output type=frame MUST use name='outer_frame' (NOT 'frame')",
        "  - output type=curve MUST use name='curve'",
        "  - output type=profile MUST use name='profile'",
        "  - input reference to previous node: {node: '<id>', output: '<name>'}",
        "  - cross-component reference: {component: '<comp_id>', output: '<name>'}",
        "  - extrude direction: '+' or '-' (NOT 'Z', 'X', 'Y')",
        "  - chamfer/fillet target: 'all_external_edges' (NOT 'all_outer_edges')",
        "  - loft_sweep path_points: x_mm/y_mm/z_mm (NOT x/y/z)",
        "  - ALL 7 safety flags must be true",
        "  - trust_level = 'reference_geometry'",
        "",
    ]
    for did in dialect_ids:
        d = REG.get(did)
        if d is None:
            continue
        lines.append(f"=== {did} v{d.version} phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            required = ps.get("required", [])
            pstrs = []
            for pn, pi in props.items():
                ptype = pi.get("type", "?")
                if "enum" in pi or "const" in pi or "anyOf" in pi:
                    const_vals = pi.get("enum") or ([pi["const"]] if "const" in pi else None)
                    if const_vals:
                        ptype = "|".join(str(v) for v in const_vals)
                req = "*" if pn in required else ""
                pstrs.append(f"{pn}{req}:{ptype}")
            lines.append(f"  {op_name} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs)}")
            # 关键 op 的显式示例
            if op_name == "revolve_profile":
                lines.append('    EXAMPLE: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":20},{"r_mm":25,"z_front_mm":20,"z_rear_mm":21}]}')
            elif op_name == "extrude_rectangle":
                lines.append('    EXAMPLE: {"width_mm":100,"height_mm":80,"depth_mm":15,"plane":"XY","centered":true,"direction":"+"}')
            elif op_name == "create_sweep_path":
                lines.append('    EXAMPLE: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":50,"y_mm":0,"z_mm":100}]}')
            elif op_name == "sweep_profile":
                lines.append('    EXAMPLE: {"shape":"circle","radius_mm":12}')
            elif op_name == "helix_sweep":
                lines.append('    EXAMPLE: {"radius_mm":15,"height_mm":80,"pitch_mm":10,"profile_radius_mm":2,"turns":8}')
            elif op_name == "boolean_union":
                lines.append('    NOTE: params={}. Inputs=[{component:c1,output:body},{component:c2,output:body}]')
            elif op_name == "shell_body":
                lines.append('    EXAMPLE: {"thickness_mm":2.0}')
            elif op_name == "cut_internal_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"depth_mm":20,"standard":"ISO_metric","thread_class":"6H"}')
            elif op_name == "cut_external_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"length_mm":15,"standard":"ISO_metric","thread_class":"6g"}')
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 15 个精选测试零件
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    # ─── 第一梯队：基础特征 ───
    {
        "id": "t1_flange_cover",
        "name": "T1 法兰盖 Flange Cover",
        "dialects": ["axisymmetric"],
        "prompt": (
            "法兰盖, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义轮廓:\n"
            "  station1 r=75 z=0-15 (法兰盘),\n"
            "  station2 r=40 z=15-25 (凸台).\n"
            "切中心孔: cut_center_bore diameter_mm=20 through_all=true.\n"
            "8个螺栓孔 PCD 120mm: cut_circular_hole_pattern count=8 pcd_mm=120 hole_dia_mm=11.\n"
            "底面密封槽: cut_annular_groove side=front inner_dia_mm=85 outer_dia_mm=105 depth_mm=3.\n"
            "所有外边缘倒角 1mm: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
    {
        "id": "t1_l_bracket",
        "name": "T1 L型支架 L-Bracket",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "L型安装支架, 单位 mm, 参考几何.\n"
            "底板: extrude_rectangle width_mm=100 height_mm=80 depth_mm=10 centered=true.\n"
            "底板4个沉头安装孔: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\n"
            "立板加强筋: add_rib thickness_mm=8 height_mm=40 length_mm=60 position_mm=[0,0,5] direction=Y.\n"
            "左右两个定位孔: cut_hole diameter_mm=6 position_mm=[-35,0] through_all=true.\n"
            "  cut_hole diameter_mm=6 position_mm=[35,0] through_all=true.\n"
            "所有边缘圆角 1.5mm: apply_safe_fillet radius_mm=1.5 target=all_external_edges."
        ),
    },
    {
        "id": "t1_bearing_seat",
        "name": "T1 轴承座 Bearing Seat",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "prompt": (
            "带加强筋轴承座装配, 单位 mm, 参考几何.\n"
            "组件 'hub' (axisymmetric): revolve_profile 定义轴承座圈:\n"
            "  station1 r=35 z=0-15 (底座法兰), station2 r=28 z=15-50 (座圈外壁), station3 r=20 z=50-55 (内缘).\n"
            "  cut_center_bore diameter_mm=25 through_all=true.\n"
            "组件 'base' (sketch_extrude): extrude_rectangle width_mm=120 height_mm=60 depth_mm=15 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=90 spacing_y_mm=40.\n"
            "  add_rib thickness_mm=8 height_mm=25 length_mm=50 position_mm=[-30,0,7.5] direction=Y.\n"
            "  add_rib thickness_mm=8 height_mm=25 length_mm=50 position_mm=[30,0,7.5] direction=Y.\n"
            "装配 '__assembly__' (composition): boolean_union 合并 hub 和 base.\n"
            "boolean_union inputs: [{component: hub, output: body}, {component: base, output: body}]."
        ),
    },
    {
        "id": "t1_stepped_shaft",
        "name": "T1 阶梯轴 Stepped Shaft",
        "dialects": ["axisymmetric"],
        "prompt": (
            "传动阶梯轴, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义 5 段阶梯轮廓:\n"
            "  station1 r=15 z=0-10,\n"
            "  station2 r=22 z=10-50 (轴承位),\n"
            "  station3 r=18 z=50-80 (中间段),\n"
            "  station4 r=15 z=80-110 (输出段),\n"
            "  station5 r=12 z=110-120 (螺纹段).\n"
            "左端中心孔: cut_center_bore diameter_mm=8 through_all=true.\n"
            "右端螺纹: cut_external_thread nominal_dia_mm=12 pitch_mm=1.75 length_mm=10 standard=ISO_metric thread_class=6g.\n"
            "所有轴肩倒角 1mm: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
    {
        "id": "t1_v_pulley",
        "name": "T1 V型带轮 V-Belt Pulley",
        "dialects": ["axisymmetric"],
        "prompt": (
            "V型带轮, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义多槽带轮轮廓:\n"
            "  station1 r=100 z=0-10 (前缘),\n"
            "  station2 r=95 z=10-18 (第一槽底),\n"
            "  station3 r=100 z=18-26 (第一/二槽间脊),\n"
            "  station4 r=95 z=26-34 (第二槽底),\n"
            "  station5 r=100 z=34-42 (第二/三槽间脊),\n"
            "  station6 r=95 z=42-50 (第三槽底),\n"
            "  station7 r=100 z=50-60 (后缘).\n"
            "中心孔: cut_center_bore diameter_mm=30 through_all=true.\n"
            "轮毂螺栓孔 PCD 60mm: cut_circular_hole_pattern count=4 pcd_mm=60 hole_dia_mm=10.\n"
            "外缘倒角 1mm: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },

    # ─── 第二梯队：中等复杂度 ───
    {
        "id": "t2_spring",
        "name": "T2 压缩弹簧 Compression Spring",
        "dialects": ["loft_sweep"],
        "prompt": (
            "压缩螺旋弹簧, 单位 mm, 参考几何.\n"
            "使用 helix_sweep 创建弹簧:\n"
            "  radius_mm=15 (中径30mm),\n"
            "  height_mm=80 (自由长度),\n"
            "  pitch_mm=10 (节距),\n"
            "  profile_radius_mm=2 (簧丝直径4mm),\n"
            "  turns=8 (8圈).\n"
            "所有节点在同一组件中, owner_dialect=loft_sweep.\n"
            "注意: 这是helix_sweep操作, 不是sweep_profile。"
        ),
    },
    {
        "id": "t2_roller",
        "name": "T2 托辊 Roller",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "prompt": (
            "输送机托辊, 单位 mm, 参考几何.\n"
            "组件 'tube' (axisymmetric): revolve_profile 定义滚筒:\n"
            "  station1 r=44.5 z=0-600 (筒体外壁 r=内径+壁厚=40+4.5),\n"
            "  station2 r=40 z=600-601 (内缘).\n"
            "  cut_center_bore diameter_mm=80 through_all=true.\n"
            "组件 'shaft' (axisymmetric): revolve_profile 定义轴:\n"
            "  station1 r=15 z=0-650 (轴).\n"
            "装配 '__assembly__' (composition): boolean_union 合并 tube 和 shaft.\n"
            "boolean_union inputs: [{component: tube, output: body}, {component: shaft, output: body}]."
        ),
    },
    {
        "id": "t2_weld_fork",
        "name": "T2 焊接叉 Weld Fork",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "传动轴焊接叉, 单位 mm, 参考几何.\n"
            "底板: extrude_rectangle width_mm=80 height_mm=50 depth_mm=15 centered=true.\n"
            "底板安装孔: cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=30.\n"
            "左侧叉臂凸台: add_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[-30,0,7.5] centered=true.\n"
            "右侧叉臂凸台: add_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[30,0,7.5] centered=true.\n"
            "左侧叉臂销孔: cut_hole diameter_mm=25 position_mm=[-30,25] through_all=true.\n"
            "右侧叉臂销孔: cut_hole diameter_mm=25 position_mm=[30,25] through_all=true.\n"
            "底板加强筋: add_rib thickness_mm=8 height_mm=15 length_mm=60 position_mm=[0,0,7.5] direction=X.\n"
            "所有边缘圆角 2mm: apply_safe_fillet radius_mm=2 target=all_external_edges."
        ),
    },
    {
        "id": "t2_gearbox_cover_complex",
        "name": "T2 减速器上箱盖 Gearbox Top Cover",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "工业减速器上箱盖, 单位 mm, 参考几何.\n"
            "主体板: extrude_rectangle width_mm=300 height_mm=200 depth_mm=20 centered=true.\n"
            "顶部减重腔体: cut_rectangular_pocket width_mm=260 height_mm=160 depth_mm=14 centered=true.\n"
            "底面法兰安装孔: cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\n"
            "纵向加强筋x3: add_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[-60,0,0] direction=Y.\n"
            "  add_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[0,0,0] direction=Y.\n"
            "  add_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[60,0,0] direction=Y.\n"
            "横向加强筋x2: add_rib thickness_mm=8 height_mm=18 length_mm=220 position_mm=[0,-40,0] direction=X.\n"
            "  add_rib thickness_mm=8 height_mm=18 length_mm=220 position_mm=[0,40,0] direction=X.\n"
            "顶部窥视孔凸台: add_rectangular_boss width_mm=100 height_mm=80 depth_mm=10 position_mm=[0,0,10] centered=true.\n"
            "窥视孔开口: cut_rectangular_pocket width_mm=80 height_mm=60 depth_mm=10 position_mm=[0,0,10] centered=true.\n"
            "所有边缘圆角 3mm: apply_safe_fillet radius_mm=3 target=all_external_edges."
        ),
    },
    {
        "id": "t2_hex_nut",
        "name": "T2 六角螺母 Hex Nut",
        "dialects": ["axisymmetric"],
        "prompt": (
            "M10六角螺母的轴对等几何体, 单位 mm, 参考几何.\n"
            "注意: 螺母是非回转体, 此处用轴对等外形模拟 (外接圆直径16mm→r=9.2, 对边16mm时外接圆≈18.5mm→取r=9.5).\n"
            "使用 revolve_profile 定义螺母外形:\n"
            "  station1 r=9.5 z=0-8 (六角体外接圆).\n"
            "中心螺纹孔: cut_center_bore diameter_mm=8.5 through_all=true.\n"
            "  (M10粗牙螺纹底孔直径8.5mm).\n"
            "顶底边缘倒角: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },

    # ─── 第三梯队：高复杂度 ───
    {
        "id": "t3_turbine_disk_complex",
        "name": "T3 涡轮盘 Turbine Disk",
        "dialects": ["axisymmetric"],
        "prompt": (
            "燃气轮机涡轮盘, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义复杂轮廓:\n"
            "  station1 r=150 z=0-20 (前缘轮缘),\n"
            "  station2 r=120 z=20-40 (盘面锥段),\n"
            "  station3 r=80 z=40-65 (辐板薄壁段),\n"
            "  station4 r=60 z=65-75 (过渡段),\n"
            "  station5 r=50 z=75-85 (轮毂厚壁段).\n"
            "中心孔: cut_center_bore diameter_mm=30 through_all=true.\n"
            "轮毂螺栓孔 PCD 80mm: cut_circular_hole_pattern count=8 pcd_mm=80 hole_dia_mm=12.\n"
            "盘面减重孔 PCD 180mm: cut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=25.\n"
            "前表面环槽: cut_annular_groove side=front inner_dia_mm=200 outer_dia_mm=240 depth_mm=6.\n"
            "外缘倒角 1.5mm: apply_safe_chamfer distance_mm=1.5 target=all_external_edges."
        ),
    },
    {
        "id": "t3_robot_wrist_housing",
        "name": "T3 机器人腕部壳体 Robot Wrist Housing",
        "dialects": ["axisymmetric", "sketch_extrude", "composition", "shell_housing"],
        "prompt": (
            "工业机器人腕部壳体, 单位 mm, 参考几何.\n"
            "组件 'body' (axisymmetric): revolve_profile 定义薄壁圆筒:\n"
            "  station1 r=60 z=0-200 (外壁),\n"
            "  station2 r=56 z=200-205 (内壁台阶).\n"
            "  cut_center_bore diameter_mm=112 through_all=true (内径112→壁厚4mm).\n"
            "  然后在 'body' 上: shell_body thickness_mm=4.\n"
            "组件 'flange' (axisymmetric): revolve_profile 定义法兰:\n"
            "  station1 r=80 z=0-15 (法兰盘).\n"
            "  cut_center_bore diameter_mm=112 through_all=true.\n"
            "  cut_circular_hole_pattern count=6 pcd_mm=140 hole_dia_mm=9.\n"
            "组件 'boss' (sketch_extrude): extrude_rectangle width_mm=30 height_mm=30 depth_mm=15 centered=true.\n"
            "  (传感器安装凸台).\n"
            "装配 '__assembly__' (composition):\n"
            "  boolean_union 合并 flange 和 body.\n"
            "  boolean_union 合并结果和 boss.\n"
            "参考: boolean_union inputs: [{component:X, output:body}, {component:Y, output:body}]."
        ),
    },
    {
        "id": "t3_exhaust_manifold_4to1",
        "name": "T3 4合1排气歧管 4-into-1 Exhaust Manifold",
        "dialects": ["loft_sweep", "sketch_extrude", "composition"],
        "prompt": (
            "简化4合1排气歧管, 单位 mm, 参考几何.\n"
            "组件 'pipe1' (loft_sweep): create_sweep_path path_points:\n"
            "  {x_mm:-40,y_mm:0,z_mm:0} → {x_mm:-40,y_mm:0,z_mm:150} → {x_mm:0,y_mm:0,z_mm:300}.\n"
            "  sweep_profile shape=circle radius_mm=18.\n"
            "组件 'pipe2' (loft_sweep): create_sweep_path path_points:\n"
            "  {x_mm:40,y_mm:0,z_mm:0} → {x_mm:40,y_mm:0,z_mm:150} → {x_mm:0,y_mm:0,z_mm:300}.\n"
            "  sweep_profile shape=circle radius_mm=18.\n"
            "组件 'collector' (loft_sweep): create_sweep_path path_points:\n"
            "  {x_mm:0,y_mm:0,z_mm:300} → {x_mm:0,y_mm:0,z_mm:450}.\n"
            "  sweep_profile shape=circle radius_mm=30.\n"
            "装配 '__assembly__' (composition):\n"
            "  boolean_union 合并 pipe1 和 pipe2.\n"
            "  boolean_union 合并结果和 collector.\n"
            "参考: boolean_union inputs 必须引用 component output: [{component: pipe1, output: body}, {component: pipe2, output: body}]."
        ),
    },
    {
        "id": "t3_hydraulic_valve_body",
        "name": "T3 液压多路阀阀体 Hydraulic Multi-way Valve Body",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "液压阀体简化模型, 单位 mm, 参考几何.\n"
            "主体块: extrude_rectangle width_mm=80 height_mm=60 depth_mm=200 centered=true.\n"
            "主阀芯孔 (P口): cut_hole diameter_mm=20 position_mm=[0,0] through_all=true axis=Z.\n"
            "A工作油口 (侧面): cut_hole diameter_mm=10 position_mm=[0,15] through_all=true axis=Y.\n"
            "B工作油口 (侧面): cut_hole diameter_mm=10 position_mm=[0,-15] through_all=true axis=Y.\n"
            "T回油口 (顶面): cut_hole diameter_mm=14 position_mm=[0,0] through_all=true axis=Y.\n"
            "安装螺栓孔x4: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=40.\n"
            "所有边缘倒角 0.5mm: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
    {
        "id": "t3_differential_case",
        "name": "T3 差速器壳体 Differential Case",
        "dialects": ["axisymmetric"],
        "prompt": (
            "差速器壳体简化模型, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义壳体外形:\n"
            "  station1 r=75 z=0-20 (法兰面),\n"
            "  station2 r=60 z=20-80 (球壳段),\n"
            "  station3 r=75 z=80-100 (对侧法兰).\n"
            "中心腔体: cut_center_bore diameter_mm=100 through_all=true.\n"
            "法兰螺栓孔 PCD 130mm: cut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\n"
            "对侧法兰螺栓孔 PCD 130mm: cut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\n"
            "法兰面环槽: cut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=140 depth_mm=3.\n"
            "外缘倒角 1mm: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

def call_llm(user_msg, system_prompt=None):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    resp = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_prompt or LEVEL2_AUTHORING_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)


def audit_step_geometry(step_path):
    """用 cadquery 审计 STEP 几何：体积、bbox、solid 检查。"""
    try:
        import cadquery as cq
        from OCP.TopAbs import TopAbs_SOLID
        shape = cq.importers.importStep(str(step_path))
        solids = [s for s in shape.Shape().Solids()]
        if not solids:
            return {"error": "No solids found", "volume": 0, "bbox": None}
        solid = solids[0]
        from OCP.BRepCheck import BRepCheck_Analyzer
        analyzer = BRepCheck_Analyzer(solid)
        check_ok = analyzer.IsValid()
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        props = GProp_GProps()
        BRepGProp.Volume(solid, props)
        vol = props.Mass()
        bbox = solid.BoundingBox()
        return {
            "valid_solid": check_ok,
            "volume_mm3": round(vol, 4),
            "bbox_x": round(bbox.XMax() - bbox.XMin(), 3),
            "bbox_y": round(bbox.YMax() - bbox.YMin(), 3),
            "bbox_z": round(bbox.ZMax() - bbox.ZMin(), 3),
            "solid_count": len(solids),
        }
    except Exception as e:
        return {"error": str(e)[:200], "volume": 0, "bbox": None}


def validate_and_build(case, args, cdir):
    audit = {}

    # ── 保存 LLM 原始输出 ──
    (cdir / "llm_raw.json").write_text(
        json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 记录 LLM 输出质量指标 ──
    nodes = args.get("nodes", [])
    comps = args.get("components", [])
    audit["llm_node_count"] = len(nodes)
    audit["llm_component_count"] = len(comps)
    audit["llm_raw_size"] = len(json.dumps(args))
    # 检测常见 LLM 错误
    output_name_errors = 0
    input_name_errors = 0
    direction_errors = 0
    path_point_errors = 0
    for n in nodes:
        for o in n.get("outputs", []):
            if o.get("name") == "solid" and o.get("type") == "solid":
                output_name_errors += 1
            if o.get("name") == "frame" and o.get("type") == "frame":
                output_name_errors += 1
        for inp in n.get("inputs", []):
            if inp.get("output") == "solid":
                input_name_errors += 1
        if n.get("params", {}).get("direction") in ("Z", "X", "Y", "z", "x", "y"):
            direction_errors += 1
        for pt in n.get("params", {}).get("path_points", []):
            if "x" in pt and "x_mm" not in pt:
                path_point_errors += 1
    audit["llm_output_name_errors"] = output_name_errors
    audit["llm_input_name_errors"] = input_name_errors
    audit["llm_direction_errors"] = direction_errors
    audit["llm_path_point_errors"] = path_point_errors

    # ── Audited autofix ──
    fixed_args = args
    try:
        fixed_args, autofix_report = auto_fix_with_report(args, REG)
        (cdir / "autofix_report.json").write_text(
            json.dumps(autofix_report.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        audit["autofix_applied"] = autofix_report.applied
        audit["autofix_entry_count"] = len(autofix_report.entries)
        audit["autofix_entries"] = [
            {"rule": e.rule_id, "severity": e.severity}
            for e in autofix_report.entries
        ]
        if autofix_report.applied:
            (cdir / "raw_fixed.json").write_text(
                json.dumps(fixed_args, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        audit["autofix_error"] = str(e)[:200]

    # ── 补全必需字段 ──
    if fixed_args.get("llm_validation_hints") is None:
        fixed_args["llm_validation_hints"] = {}
    if "units" not in fixed_args:
        fixed_args["units"] = "mm"
    if "trust_level" not in fixed_args:
        fixed_args["trust_level"] = "reference_geometry"

    # ── 验证 ──
    validation_ok = False
    report = None
    try:
        doc = RawGcadDocument.model_validate(fixed_args)
        canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
        if report:
            (cdir / "raw_original_validation.json").write_text(
                json.dumps(_report_dict(report), indent=2, ensure_ascii=False),
                encoding="utf-8")
        validation_ok = canonical is not None and report is not None and report.ok
        audit["validation_ok"] = validation_ok
        audit["validation_stage"] = report.stage if report else "none"
        if not validation_ok and report:
            audit["validation_issues"] = [
                {"code": getattr(i, "code", "?"), "msg": getattr(i, "message", str(i))[:200]}
                for i in (report.issues or [])[:5]
            ]
    except Exception as e:
        audit["validation_error"] = str(e)[:200]
        return False, f"Pydantic/Validate: {e}", audit

    if not validation_ok:
        issues = report.issues if report else []
        err_msg = "; ".join(
            f"[{getattr(i, 'code', '?')}] {getattr(i, 'message', str(i))[:120]}"
            for i in (issues[:5] if issues else []))
        return False, err_msg, audit

    # ── 保存 canonical ──
    can_dict = canonical.model_dump()
    (cdir / "canonical.json").write_text(
        json.dumps(can_dict, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    if bundle:
        (cdir / "validation_bundle.json").write_text(
            json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False),
            encoding="utf-8")

    # ── 构建 STEP ──
    bscript = f'''import sys; sys.path.insert(0, r"{SRC.as_posix()}")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
can_path = Path(r"{(cdir / 'canonical.json').as_posix()}")
val_path = Path(r"{(cdir / 'validation_bundle.json').as_posix()}")
step_path = Path(r"{(cdir / 'output.step').as_posix()}")
meta_path = Path(r"{(cdir / 'output.metadata.json').as_posix()}")
r = run_canonical_gcad_from_files(
    canonical_json=can_path, validation_seed_json=val_path,
    out_step=step_path, metadata_path=meta_path)
if r.ok:
    print("BUILD_OK")
    for m in (r.operation_metrics or []):
        print(f"OP:{{m.get('node_id','?')}}/{{m.get('op','?')}}:{{m.get('status','?')}}")
    for d in (r.degraded_features or []):
        print(f"DEGRADED:{{d.get('node_id','?')}}/{{d.get('op','?')}}:{{d.get('reason','?')}}")
else:
    print(f"BUILD_FAILED: {{r.error}}")
    for w in (r.warnings or []):
        print(f"WARN: {{w[:200]}}")
'''
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text(
        f"RC={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}", encoding="utf-8")

    audit["build_rc"] = r.returncode
    audit["build_stdout"] = r.stdout[:1000] if r.stdout else ""
    audit["degraded_ops"] = [
        line for line in (r.stdout or "").split("\n")
        if "DEGRADED" in line
    ]

    step_ok = r.returncode == 0 and (cdir / "output.step").exists()

    if step_ok:
        step_sz = (cdir / "output.step").stat().st_size
        audit["step_size"] = step_sz

        # ── 几何审计 ──
        geom = audit_step_geometry(cdir / "output.step")
        audit["geometry"] = geom

        # ── SolidWorks ──
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            sldprt = cdir / "output.SLDPRT"
            c = SolidWorksClient(visible=False).connect()
            ok = c.import_step_as_part(cdir / "output.step", sldprt)
            c.close()
            sw_sz = sldprt.stat().st_size if ok and sldprt.exists() else 0
            audit["sw_size"] = sw_sz
            msg = f"STEP={step_sz}B GEO={geom} SW={sw_sz}B"
        except Exception as e:
            audit["sw_error"] = str(e)[:100]
            msg = f"STEP={step_sz}B GEO={geom} SW=N/A"
        return True, msg, audit
    else:
        # ── 重试: 移除 chamfer/fillet ──
        cg = json.loads((cdir / "canonical.json").read_text(encoding="utf-8"))
        old_count = len(cg["nodes"])
        cg["nodes"] = [n for n in cg["nodes"]
                       if n.get("op") not in ("apply_safe_chamfer", "apply_safe_fillet")]
        if len(cg["nodes"]) < old_count:
            node_ids = {n["id"] for n in cg["nodes"]}
            for comp in cg.get("components", []):
                if comp.get("root_node", "") not in node_ids and cg["nodes"]:
                    comp["root_node"] = cg["nodes"][-1]["id"]
            (cdir / "canonical.json").write_text(json.dumps(cg, indent=2), encoding="utf-8")
            bp.write_text(bscript, encoding="utf-8")
            r2 = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
            (cdir / "_build_log_retry.txt").write_text(
                f"RC={r2.returncode}\n{r2.stdout}\n{r2.stderr}", encoding="utf-8")
            if r2.returncode == 0 and (cdir / "output.step").exists():
                step_sz = (cdir / "output.step").stat().st_size
                audit["step_size"] = step_sz
                audit["build_retry_success"] = True
                geom = audit_step_geometry(cdir / "output.step")
                audit["geometry"] = geom
                try:
                    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
                    sldprt = cdir / "output.SLDPRT"
                    c = SolidWorksClient(visible=False).connect()
                    ok = c.import_step_as_part(cdir / "output.step", sldprt)
                    c.close()
                    audit["sw_size"] = sldprt.stat().st_size if ok and sldprt.exists() else 0
                    return True, f"STEP={step_sz}B GEO={geom} SW={audit.get('sw_size',0)}B (no edge ops)", audit
                except:
                    return True, f"STEP={step_sz}B GEO={geom} (no edge ops)", audit
        audit["build_stderr"] = r.stderr[:500]
        return False, f"STEP failed: {r.stderr[:200]}", audit


def _report_dict(report) -> dict:
    if report is None:
        return {"ok": False, "issues": []}
    if hasattr(report, "model_dump"):
        return report.model_dump()
    if isinstance(report, dict):
        return report
    return {
        "ok": getattr(report, "ok", False),
        "stage": getattr(report, "stage", "unknown"),
        "issues": [
            i.model_dump() if hasattr(i, "model_dump") else i
            for i in getattr(report, "issues", [])
        ],
        "stages_run": getattr(report, "stages_run", []),
    }


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import datetime
    print(f"=== test_model.md Pipeline: {len(CASES)} cases ===\n")
    print(f"Output: {OUT}\n")

    results = []
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        start = time.time()

        print(f"[{i+1}/{len(CASES)}] {case['name']} ({case['id']})")
        print(f"  Dialects: {case['dialects']}")

        contract = build_contract(case["dialects"])
        user_msg = (
            f"TASK: {case['prompt']}\n\n"
            f"{contract}\n\n"
            f"CRITICAL OUTPUT RULES:\n"
            f"  - Output name for solid type: 'body' (NOT 'solid')\n"
            f"  - Output name for frame type: 'outer_frame' (NOT 'frame')\n"
            f"  - Output name for curve type: 'curve'\n"
            f"  - extrude direction: '+' or '-' (NOT 'Z'/'X'/'Y')\n"
            f"  - loft_sweep path points: x_mm/y_mm/z_mm (NOT x/y/z)\n"
            f"  - chamfer/fillet target: 'all_external_edges'\n"
            f"  - ALL safety flags must be true\n"
            f"  - trust_level='reference_geometry'\n"
            f"  - For composition: boolean_union has empty params {{}}, inputs must be component refs\n"
            f"Generate complete RawGcadDocument as JSON."
        )

        ok = False
        error_msg = ""
        last_audit = {}
        for attempt in range(4):
            if attempt > 0:
                user_msg += (
                    f"\n\nPREVIOUS ATTEMPT FAILED:\n{error_msg[:800]}\n\n"
                    f"FIX ALL THESE ERRORS. Use EXACT op/param names from contract. "
                    f"This is attempt {attempt+1}/4."
                )

            print(f"  Round {attempt+1}: LLM...", end=" ", flush=True)
            try:
                args = call_llm(user_msg)
            except Exception as e:
                print(f"LLM FAIL: {e}")
                error_msg = str(e)
                continue

            ok, msg, audit_data = validate_and_build(case, args, cdir)
            last_audit = audit_data
            elapsed = time.time() - start
            print(f"{msg}  [{elapsed:.0f}s]")
            if ok:
                break
            error_msg = msg
            time.sleep(0.5)

        results.append({
            "id": case["id"], "name": case["name"],
            "ok": ok, "msg": msg,
            "attempts": attempt + 1,
            "elapsed_s": round(time.time() - start, 1),
            "audit": last_audit,
        })
        print()

    # ── 报告 ──
    print(f"=== RESULTS ===")
    passed = sum(1 for r in results if r["ok"])
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        geom = r.get("audit", {}).get("geometry", {})
        vol = geom.get("volume_mm3", "?")
        bbox = ""
        if geom.get("bbox_x"):
            bbox = f" bbox=[{geom.get('bbox_x')}x{geom.get('bbox_y')}x{geom.get('bbox_z')}]"
        print(f"  {status} {r['name']} (x{r['attempts']}, {r['elapsed_s']}s) vol={vol}{bbox}")
    print(f"\n  {passed}/{len(results)} passed")

    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total": len(results), "passed": passed,
        "results": results,
    }
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (OUT / "full_audit.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReports saved to {OUT}/report.json and {OUT}/full_audit.json")
