"""30 stress30 cases — full LLM→STEP→SW pipeline. All fresh DeepSeek v4-pro calls."""
import json, os, sys, subprocess, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent/"integrations"/"engineering_tools"/"src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent.parent/"integrations"/"engineering_tools"/"src").resolve()
OUT = Path(__file__).parent / "cases"
OUT.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = Path(__file__).parent / "stress30_results.json"

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
REG = default_registry()

def build_contract(dialect_ids):
    lines = ["=== DIALECT CONTRACTS ===","","CRITICAL: output solid->name='body', frame->name='outer_frame', curve->name='curve'.",
    "extrude direction: '+' or '-'. path_points: x_mm/y_mm/z_mm. ALL 7 safety flags=true. op_version='1.0.0'.",""]
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} v{d.version} phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            pstrs = [f"{pn}:{pi.get('type','?')}" for pn, pi in props.items()]
            lines.append(f"  {op_name} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs[:10])}")
        lines.append("")
    return "\n".join(lines)

def call_llm(system, user):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type":"function","function":{"name":"gcad","strict":True,"parameters":schema}}]
    resp = client.chat.completions.create(model="deepseek-v4-pro",
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
        tools=tools, tool_choice={"type":"function","function":{"name":"gcad"}},
        timeout=180, extra_body={"thinking":{"type":"disabled"}})
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)

def build_step(cdir):
    can=(cdir/"canonical.json").as_posix(); val=(cdir/"validation_bundle.json").as_posix()
    stp=(cdir/"output.step").as_posix(); met=(cdir/"output.metadata.json").as_posix()
    script=f"import sys; sys.path.insert(0,r'{SRC.as_posix()}')\nfrom pathlib import Path\nfrom seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files\nr=run_canonical_gcad_from_files(canonical_json=Path(r'{can}'),validation_seed_json=Path(r'{val}'),out_step=Path(r'{stp}'),metadata_path=Path(r'{met}'))\nif r.ok: print('OK')\nelse: print(f'FAIL:{r.error}')\n"
    (cdir/"_build.py").write_text(script,encoding="utf-8")
    r=subprocess.run([CONDA,str(cdir/"_build.py")],capture_output=True,text=True,timeout=600,cwd=str(cdir))
    return r.returncode==0 and (cdir/"output.step").exists()

def import_sw(step, sldprt):
    try:
        from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
        t=Path(r'C:/ProgramData/SOLIDWORKS/SOLIDWORKS 2025/templates/gb_part.prtdot')
        s=SolidWorksClient(visible=False,part_template=t).connect()
        ok=s.import_step_as_part(str(step),str(sldprt))
        s.close_all(); s.close()
        return ok and sldprt.exists() and sldprt.stat().st_size>0
    except: return False

# ============== 30 STRESS30 CASES ==============
CASES = [
{"id":"g1_engine_mount","dialects":["sketch_extrude","axisymmetric","composition"],
"prompt":"汽车发动机悬置支架总成,单位mm.\n组件base_plate(sketch_extrude): extrude_rectangle width_mm=300 height_mm=200 depth_mm=25 centered=true. cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\n组件bushing_left(axisymmetric): revolve_profile station1 r=30 z=0-50. cut_center_bore diameter_mm=16.\n组件bushing_right(axisymmetric): revolve_profile station1 r=30 z=0-50. cut_center_bore diameter_mm=16.\n组件mount_bracket(sketch_extrude): extrude_rectangle width_mm=80 height_mm=60 depth_mm=15 centered=true. cut_hole diameter_mm=10 position_mm=[-25,0]. cut_hole diameter_mm=10 position_mm=[25,0]. add_rib thickness_mm=8 height_mm=20 length_mm=40 position_mm=[0,0,7.5] direction=Y.\n装配__assembly__(composition): 依次boolean_union合并4个组件(每次2 inputs)."},

{"id":"g2_gearbox_housing","dialects":["sketch_extrude","axisymmetric","composition"],
"prompt":"工业减速器箱体总成,单位mm.\n组件housing_base(sketch_extrude): extrude_rectangle width_mm=500 height_mm=350 depth_mm=40 centered=true. cut_rectangular_pocket width_mm=440 height_mm=290 depth_mm=30. cut_hole_pattern_linear hole_dia_mm=18 count_x=2 count_y=2 spacing_x_mm=440 spacing_y_mm=290. add_rib thickness_mm=12 height_mm=25 length_mm=300 position_mm=[-120,0,20] direction=Y. add_rib thickness_mm=12 height_mm=25 length_mm=300 position_mm=[120,0,20] direction=Y.\n组件bearing_a(axisymmetric): revolve_profile station1 r=80 z=0-70,station2 r=60 z=70-75. cut_center_bore diameter_mm=50. cut_circular_hole_pattern count=6 pcd_mm=120 hole_dia_mm=12.\n组件bearing_b(axisymmetric): revolve_profile station1 r=80 z=0-70,station2 r=60 z=70-75. cut_center_bore diameter_mm=50. cut_circular_hole_pattern count=6 pcd_mm=120 hole_dia_mm=12.\n装配__assembly__(composition): 依次boolean_union合并3组件(每次2 inputs)."},

{"id":"g3_hyd_manifold","dialects":["sketch_extrude"],
"prompt":"工程机械液压集成块,单位mm. extrude_rectangle width_mm=150 height_mm=120 depth_mm=180 centered=true. 主油路口P顶面: cut_hole diameter_mm=25 position_mm=[0,0] axis=Z. 工作口A前面: cut_hole diameter_mm=20 position_mm=[50,30] axis=Y. 工作口B前面: cut_hole diameter_mm=20 position_mm=[-50,30] axis=Y. 泄油口T右面: cut_hole diameter_mm=15 position_mm=[0,0] axis=X. 安装孔x4: cut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=120 spacing_y_mm=90. apply_safe_chamfer distance_mm=0.5 target=all_external_edges."},

{"id":"g4_pump_casing","dialects":["axisymmetric","sketch_extrude","composition"],
"prompt":"离心泵蜗壳总成,单位mm.\n组件volute(axisymmetric): revolve_profile station1 r=120 z=0-30,station2 r=90 z=30-80,station3 r=60 z=80-85. cut_center_bore diameter_mm=50. cut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=14.\n组件discharge_flange(sketch_extrude): extrude_rectangle width_mm=150 height_mm=100 depth_mm=20 centered=true. cut_hole diameter_mm=60 position_mm=[0,0]. cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=100 spacing_y_mm=60.\n组件base(sketch_extrude): extrude_rectangle width_mm=250 height_mm=200 depth_mm=30 centered=true. cut_hole_pattern_linear hole_dia_mm=16 count_x=2 count_y=2 spacing_x_mm=200 spacing_y_mm=150.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

{"id":"g5_robot_arm","dialects":["axisymmetric","sketch_extrude","composition"],
"prompt":"工业机器人手臂段,单位mm.\n组件arm_tube(axisymmetric): revolve_profile station1 r=65 z=0-500. cut_center_bore diameter_mm=110 (壁厚10mm).\n组件flange_a(axisymmetric): revolve_profile station1 r=90 z=0-25. cut_center_bore diameter_mm=110. cut_circular_hole_pattern count=8 pcd_mm=150 hole_dia_mm=14.\n组件flange_b(axisymmetric): revolve_profile station1 r=90 z=0-25. cut_center_bore diameter_mm=110. cut_circular_hole_pattern count=8 pcd_mm=150 hole_dia_mm=14.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

{"id":"g6_helix_coil","dialects":["loft_sweep"],
"prompt":"20圈螺旋弹簧管,单位mm. helix_sweep radius_mm=100 height_mm=400 pitch_mm=20 profile_radius_mm=6 turns=20."},

{"id":"g7_3d_tube","dialects":["loft_sweep"],
"prompt":"三维弯曲管路,单位mm. create_sweep_path path_points=[{x_mm:0,y_mm:0,z_mm:0},{x_mm:100,y_mm:50,z_mm:80},{x_mm:200,y_mm:-30,z_mm:150},{x_mm:350,y_mm:20,z_mm:200},{x_mm:450,y_mm:0,z_mm:280},{x_mm:550,y_mm:30,z_mm:350}]. sweep_profile shape=circle radius_mm=15."},

{"id":"g8_var_duct","dialects":["loft_sweep"],
"prompt":"变截面风管,单位mm. loft_sections sections=[{position:{x_mm:0,y_mm:0,z_mm:0},shape:circle,radius_mm:50},{position:{x_mm:0,y_mm:0,z_mm:150},shape:rectangle,width_mm:120,height_mm:80},{position:{x_mm:0,y_mm:0,z_mm:300},shape:circle,radius_mm:40}]."},

{"id":"g9_torsion_spring","dialects":["loft_sweep"],
"prompt":"15圈扭簧,单位mm. helix_sweep radius_mm=60 height_mm=225 pitch_mm=15 profile_radius_mm=4 turns=15."},

{"id":"g10_spiral_volute","dialects":["loft_sweep"],
"prompt":"渐开线蜗壳,单位mm. create_sweep_path path_points从中心螺旋展开8个点. sweep_profile shape=circle radius_mm=12."},

{"id":"g11_pressure_vessel","dialects":["axisymmetric","shell_housing"],
"prompt":"薄壁压力容器,单位mm. revolve_profile station1 r=150 z=0-400. cut_center_bore diameter_mm=290 (内径290外径300壁厚5mm). 两端半球封头."},

{"id":"g12_hollow_bracket","dialects":["sketch_extrude","shell_housing"],
"prompt":"空心支架,单位mm. extrude_rectangle width_mm=200 height_mm=160 depth_mm=70 centered=true. shell_body thickness_mm=3.0. cut_hole_pattern_linear hole_dia_mm=8 count_x=2 count_y=2 spacing_x_mm=150 spacing_y_mm=110. cut_hole diameter_mm=15 position_mm=[0,60] axis=Y."},

{"id":"g13_enclosure","dialects":["sketch_extrude","shell_housing"],
"prompt":"电子设备外壳,单位mm. extrude_rectangle width_mm=300 height_mm=200 depth_mm=150 centered=true. shell_body thickness_mm=4.0. 前面板开口: cut_rectangular_pocket width_mm=100 height_mm=60 depth_mm=4 centered=true plane=YZ. 安装孔: cut_hole_pattern_linear hole_dia_mm=6 count_x=2 count_y=2 spacing_x_mm=260 spacing_y_mm=160."},

{"id":"g14_vacuum_chamber","dialects":["axisymmetric","sketch_extrude","composition"],
"prompt":"真空腔体装配,单位mm.\n组件chamber(axisymmetric): revolve_profile station1 r=100 z=0-400. cut_center_bore diameter_mm=180 (内径180外径200壁厚10mm).\n组件front_cover(sketch_extrude): extrude_rectangle width_mm=220 height_mm=220 depth_mm=20 centered=true. cut_hole diameter_mm=100 position_mm=[0,0]. cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=180 spacing_y_mm=180.\n组件rear_cover(sketch_extrude): extrude_rectangle width_mm=220 height_mm=220 depth_mm=20 centered=true. cut_hole diameter_mm=50 position_mm=[0,0]. cut_hole diameter_mm=50 position_mm=[0,60]. cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=180 spacing_y_mm=180.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

{"id":"g15_heavy_flange","dialects":["axisymmetric"],
"prompt":"重型法兰,单位mm. revolve_profile station1 r=200 z=0-55. cut_center_bore diameter_mm=120. 外圈24孔: cut_circular_hole_pattern count=24 pcd_mm=340 hole_dia_mm=18. 内圈12孔: cut_circular_hole_pattern count=12 pcd_mm=200 hole_dia_mm=12."},

{"id":"g16_stepped_pulley","dialects":["axisymmetric"],
"prompt":"9段多级带轮,单位mm. revolve_profile station1 r=120 z=0-9,station2 r=105 z=9-18,station3 r=90 z=18-27,station4 r=78 z=27-36,station5 r=65 z=36-45,station6 r=55 z=45-54,station7 r=45 z=54-63,station8 r=35 z=63-72,station9 r=25 z=72-87. cut_center_bore diameter_mm=30."},

{"id":"g17_cross_block","dialects":["sketch_extrude"],
"prompt":"六面钻孔测试块100x100x100mm,单位mm. extrude_rectangle width_mm=100 height_mm=100 depth_mm=100 centered=true. top面中心: cut_hole diameter_mm=20 position_mm=[0,0] axis=Z. bottom面偏移: cut_hole diameter_mm=15 position_mm=[20,0] axis=Z. front面2孔: cut_hole diameter_mm=10 position_mm=[20,20] axis=Y. cut_hole diameter_mm=10 position_mm=[-20,20] axis=Y. left面: cut_hole diameter_mm=8 position_mm=[0,0] axis=X. right面: cut_hole diameter_mm=8 position_mm=[0,0] axis=X."},

{"id":"g18_ribbed_panel","dialects":["sketch_extrude"],
"prompt":"加强筋面板,单位mm. extrude_rectangle width_mm=550 height_mm=400 depth_mm=8 centered=true. 7条纵筋: add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[-180,0,4] direction=Y. add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[-120,0,4] direction=Y. add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[-60,0,4] direction=Y. add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[0,0,4] direction=Y. add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[60,0,4] direction=Y. add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[120,0,4] direction=Y. add_rib thickness_mm=4 height_mm=30 length_mm=350 position_mm=[180,0,4] direction=Y. 5条横筋: add_rib thickness_mm=4 height_mm=30 length_mm=500 position_mm=[0,-120,4] direction=X. add_rib thickness_mm=4 height_mm=30 length_mm=500 position_mm=[0,-60,4] direction=X. add_rib thickness_mm=4 height_mm=30 length_mm=500 position_mm=[0,0,4] direction=X. add_rib thickness_mm=4 height_mm=30 length_mm=500 position_mm=[0,60,4] direction=X. add_rib thickness_mm=4 height_mm=30 length_mm=500 position_mm=[0,120,4] direction=X."},

{"id":"g19_precision_base","dialects":["sketch_extrude","axisymmetric"],
"prompt":"精密基座,单位mm. 底板(sketch_extrude): extrude_rectangle width_mm=305 height_mm=280 depth_mm=15 centered=true. 四角定位孔: cut_hole_pattern_linear hole_dia_mm=30 count_x=2 count_y=2 spacing_x_mm=255 spacing_y_mm=230. 中心轴承座(axisymmetric): revolve_profile station1 r=30 z=0-20. cut_center_bore diameter_mm=20. apply_safe_chamfer distance_mm=0.5 target=all_external_edges."},

{"id":"g20_motor_endbell","dialects":["axisymmetric","sketch_extrude","composition"],
"prompt":"电机端盖装配,单位mm.\n组件endbell(axisymmetric): revolve_profile station1 r=125 z=0-20,station2 r=60 z=20-45. cut_center_bore diameter_mm=40. cut_circular_hole_pattern count=6 pcd_mm=200 hole_dia_mm=10.\n组件terminal_box(sketch_extrude): extrude_rectangle width_mm=60 height_mm=40 depth_mm=30 centered=true.\n装配__assembly__(composition): boolean_union合并2组件."},

{"id":"g21_valve_body","dialects":["axisymmetric","composition"],
"prompt":"阀体装配,单位mm.\n组件body(axisymmetric): revolve_profile station1 r=70 z=0-70,station2 r=50 z=70-140. cut_center_bore diameter_mm=30. 进口法兰: cut_circular_hole_pattern count=4 pcd_mm=110 hole_dia_mm=14.\n组件flange(axisymmetric): revolve_profile station1 r=60 z=0-20. cut_center_bore diameter_mm=30. cut_circular_hole_pattern count=4 pcd_mm=90 hole_dia_mm=12.\n装配__assembly__(composition): boolean_union."},

{"id":"g22_heat_sink","dialects":["sketch_extrude"],
"prompt":"散热器,单位mm. extrude_rectangle width_mm=328 height_mm=228 depth_mm=8 centered=true. 18片鳍片: add_rib厚度2mm高100mm间距12mm. 四角安装孔: cut_hole_pattern_linear hole_dia_mm=6 count_x=2 count_y=2 spacing_x_mm=300 spacing_y_mm=200."},

{"id":"g23_pipe_reducer","dialects":["loft_sweep","axisymmetric","composition"],
"prompt":"变径管装配,单位mm.\n组件reducer(loft_sweep): loft_sections从直径100圆截面过渡到直径60圆截面长度150mm.\n组件flange(axisymmetric): revolve_profile station1 r=60 z=0-20. cut_center_bore diameter_mm=60. cut_circular_hole_pattern count=6 pcd_mm=90 hole_dia_mm=12.\n装配__assembly__(composition): boolean_union."},

{"id":"g24_micro_bushing","dialects":["axisymmetric"],
"prompt":"微型轴套,单位mm. revolve_profile station1 r=3 z=0-10. cut_center_bore diameter_mm=5.5 (壁厚仅0.5mm)."},

{"id":"g25_large_ring","dialects":["axisymmetric"],
"prompt":"大直径环件,单位mm. revolve_profile station1 r=500 z=0-30. cut_center_bore diameter_mm=900 (内径900外径1000). 36个螺栓孔: cut_circular_hole_pattern count=36 pcd_mm=950 hole_dia_mm=15."},

{"id":"g26_extreme_shaft","dialects":["axisymmetric"],
"prompt":"细长中空轴,单位mm. revolve_profile station1 r=8 z=0-500. cut_center_bore diameter_mm=6 (外径16内径6壁厚5mm)."},

{"id":"g27_dense_holes","dialects":["sketch_extrude"],
"prompt":"多孔板200x150x10mm,单位mm. extrude_rectangle width_mm=200 height_mm=150 depth_mm=10 centered=true. 20行x15列300个直径3mm通孔间距8mm: cut_hole_pattern_linear hole_dia_mm=3 count_x=20 count_y=15 spacing_x_mm=8 spacing_y_mm=8."},

{"id":"g28_ball_valve","dialects":["axisymmetric","sketch_extrude","composition"],
"prompt":"球阀装配,单位mm.\n组件valve_body(axisymmetric): revolve_profile station1 r=80 z=0-80,station2 r=50 z=80-160. cut_center_bore diameter_mm=30.\n组件ball(axisymmetric): revolve_profile station1 r=50 z=0-50. cut_center_bore diameter_mm=40 (球体通孔).\n组件flange_a(axisymmetric): revolve_profile station1 r=60 z=0-20. cut_center_bore diameter_mm=30. cut_circular_hole_pattern count=4 pcd_mm=90 hole_dia_mm=14.\n组件flange_b(axisymmetric): revolve_profile station1 r=60 z=0-20. cut_center_bore diameter_mm=30. cut_circular_hole_pattern count=4 pcd_mm=90 hole_dia_mm=14.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

{"id":"g29_impeller","dialects":["axisymmetric","composition"],
"prompt":"离心叶轮,单位mm.\n组件hub(axisymmetric): revolve_profile station1 r=150 z=0-35. cut_center_bore diameter_mm=40. 6个叶片均布.\n组件blade(axisymmetric): revolve_profile station1 r=5 z=0-20 长条形.\n装配__assembly__(composition): boolean_union."},

{"id":"g30_hyd_cylinder","dialects":["axisymmetric"],
"prompt":"液压缸端盖,单位mm. revolve_profile station1 r=35 z=0-30. cut_center_bore diameter_mm=30. cut_circular_hole_pattern count=6 pcd_mm=55 hole_dia_mm=8. 密封槽: cut_annular_groove inner_dia_mm=30 outer_dia_mm=40 depth_mm=3 side=front."},
]

if __name__ == "__main__":
    results = []
    t0 = time.time()
    for i, case in enumerate(CASES):
        cid = case["id"]; cdir = OUT / f"stress30_{cid}"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir/"input_text.txt").write_text(case["prompt"], encoding="utf-8")
        print(f"[{i+1:2d}/30] {cid}:", end=" ", flush=True)
        t1 = time.time()
        try:
            contract = build_contract(case["dialects"])
            user_msg = contract + "\n\n=== USER REQUEST ===\n" + case["prompt"] + "\n\nGenerate RawGcadDocument JSON."
            raw = call_llm(LEVEL2_AUTHORING_SYSTEM_PROMPT, user_msg)
            (cdir/"llm_raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
            for attempt in range(3):
                canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
                errs = [i for i in report.issues if i.severity == "error"]
                if not errs: break
                try:
                    fixed, af = auto_fix_with_report(raw, REG)
                    if af.applied:
                        (cdir/f"raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
                        raw = fixed
                except: pass
            (cdir/"validation_report.json").write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
            if errs:
                print(f"VAL_FAIL({len(errs)}) {errs[0].code if errs else '?'}", flush=True)
                results.append({"id":cid,"status":"VAL_FAIL","n_errors":len(errs)})
                continue
            (cdir/"canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            (cdir/"validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            ok = build_step(cdir)
            sz = (cdir/"output.step").stat().st_size if (cdir/"output.step").exists() else 0
            sw = False
            if ok and sz > 100:
                try: sw = import_sw(cdir/"output.step", cdir/"output.SLDPRT")
                except: pass
            dt = time.time() - t1
            print(f"STEP={sz//1024}KB SW={sw} ({dt:.0f}s)", flush=True)
            results.append({"id":cid,"status":"OK" if ok else "BUILD_FAIL","step_kb":sz//1024,"sw":sw,"time_s":int(dt)})
        except Exception as e:
            print(f"FAIL: {e}", flush=True)
            results.append({"id":cid,"status":"EXCEPTION","error":str(e)[:200]})
        # Save incremental
        with open(RESULTS_FILE,"w",encoding="utf-8") as f:
            json.dump({"elapsed_min":int((time.time()-t0)/60),"cases":results}, f, indent=2, ensure_ascii=False)

    total_t = int((time.time()-t0)/60)
    ok = sum(1 for r in results if r["status"]=="OK")
    sw_count = sum(1 for r in results if r.get("sw"))
    print(f"\n=== DONE: {ok}/30 STEP, {sw_count} SW, {total_t}min ===")
