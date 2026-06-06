"""v6.3 Full 45-Case Test: Text -> LLM -> Validate -> AutoFix -> Runtime -> STEP.
Fresh DeepSeek v4-pro calls for every case. Skipped: g27_dense_holes (OCP segfault 300 holes).
SW import only for files <500KB to avoid memory crashes.
"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, r'E:\auto_detection_process\integrations\engineering_tools\src')
os.environ['DEEPSEEK_API_KEY'] = open(r'E:\auto_detection_process\_archive\apikey.txt').read().strip()

OUT = Path(__file__).parent / 'cases_v63_full45'
OUT.mkdir(parents=True, exist_ok=True)

# ════════════════ ALL 45 CASES ════════════════
CASES = [
    # --- Group A: v4 single-body (15 cases) ---
    {"id":"v4_flange","prompt":"设计法兰盘,单位mm. revolve_profile外径200内径80厚20:station1 r=100 z=0-20. cut_center_bore diameter_mm=80. cut_circular_hole_pattern count=8 pcd_mm=160 hole_dia_mm=12."},
    {"id":"v4_shaft","prompt":"设计阶梯轴,单位mm. revolve_profile多级台阶:station1 r=25 z=0-30,station2 r=30 z=30-80,station3 r=20 z=80-150. cut_center_bore diameter_mm=10. apply_safe_chamfer distance_mm=1.0."},
    {"id":"v4_valve_block","prompt":"设计液压阀块120x100x150mm,单位mm. extrude_rectangle width_mm=120 height_mm=100 depth_mm=150 centered=true. cut_hole P口直径20mm顶面axis=Z. cut_hole A/B口直径15mm前面axis=Y位置[30,20]和[-30,20]. cut_hole进油口直径25mm右面axis=X."},
    {"id":"v4_cross_block","prompt":"设计六面钻孔块100x100x100mm,单位mm. extrude_rectangle width_mm=100 height_mm=100 depth_mm=100 centered=true. 顶面cut_hole直径20 axis=Z. 底面cut_hole直径15 axis=Z偏移[15,0]. 前面2个cut_hole直径12 axis=Y位置[20,20]和[-20,20]. 右面左面cut_hole直径10 axis=X."},
    {"id":"v4_dual_pcd","prompt":"设计双圈螺栓法兰,单位mm. revolve_profile外径300内径60厚40:station1 r=150 z=0-40. cut_center_bore diameter_mm=60. 外圈cut_circular_hole_pattern count=12 pcd_mm=240 hole_dia_mm=18. 内圈cut_circular_hole_pattern count=8 pcd_mm=160 hole_dia_mm=12."},
    {"id":"v4_perforated","prompt":"设计多孔板200x150x10mm,单位mm. extrude_rectangle width_mm=200 height_mm=150 depth_mm=10 centered=true. cut_hole_pattern_linear hole_dia_mm=3 count_x=20 count_y=15 spacing_x_mm=8 spacing_y_mm=8."},
    {"id":"v4_ribbed_base","prompt":"设计加筋基座300x240x25mm,单位mm. extrude_rectangle width_mm=300 height_mm=240 depth_mm=25 centered=true. 四角孔cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=190. 4条筋add_rib厚10高30."},
    {"id":"v4_shell_box","prompt":"设计电子外壳200x150x100mm,单位mm. extrude_rectangle width_mm=200 height_mm=150 depth_mm=100 centered=true. shell_body thickness_mm=3. 面板开口cut_rectangular_pocket宽80高50深3."},
    {"id":"v4_spring","prompt":"设计螺旋弹簧15圈,单位mm. helix_sweep radius_mm=60 height_mm=225 pitch_mm=15 profile_radius_mm=4 turns=15."},
    {"id":"v4_3d_pipe","prompt":"设计三维管路6点,单位mm. create_sweep_path path_points=(0,0,0)->(100,50,80)->(200,-30,150)->(300,20,200)->(400,0,280)->(500,30,350). sweep_profile shape=circle radius_mm=15."},
    {"id":"v4_var_duct","prompt":"设计变截面风管,单位mm. loft_sections sections=[{z:0,circle,r:50},{z:150,rectangle,w:120,h:80},{z:300,circle,r:40}]."},
    {"id":"v4_support_frame","prompt":"设计四柱框架,单位mm. 底板400x300x20有四角安装孔16mm. 4圆柱直径50高200. 顶板400x300x15. 用sketch_extrude+axisymmetric+composition."},
    {"id":"v4_double_flange","prompt":"设计双法兰短管,单位mm. 管段外径80内径60长200. 两端法兰外径140厚20各6个M12孔PCD110. 用axisymmetric+composition."},
    {"id":"v4_large_ring","prompt":"设计大直径环外径1000内径900厚30,单位mm. revolve_profile station1 r=500 z=0-30. cut_center_bore diameter_mm=900. cut_circular_hole_pattern count=36 pcd_mm=950 hole_dia_mm=16."},
    {"id":"v4_thin_sleeve","prompt":"设计薄壁轴套外径12内径10厚20,单位mm. revolve_profile station1 r=6 z=0-20. cut_center_bore diameter_mm=10."},

    # --- Group B: stress30 (30 cases) ---
    {"id":"g1_engine_mount","prompt":"汽车发动机悬置支架总成,单位mm. 底板300x200x25有4个M14安装孔. 2个衬套外径60内径16高50. 安装支架80x60x15带2个M10孔. 用sketch_extrude+axisymmetric+composition做boolean_union."},
    {"id":"g2_gearbox_housing","prompt":"减速器箱体总成500x350x40,单位mm. 箱体底板有矩形凹槽440x290深30. 2个轴承座外径80内径50高70各6个M12孔PCD120. 用sketch_extrude+axisymmetric+composition."},
    {"id":"g3_hyd_manifold","prompt":"液压集成块150x120x180mm,单位mm. extrude_rectangle. 顶面直径25 P口. 前面2个直径20工作口. 右面直径15泄油口. 四角4个M11安装孔. 倒角0.5mm."},
    {"id":"g4_pump_casing","prompt":"离心泵蜗壳总成,单位mm. 蜗壳主体外径120到60渐变. 排出法兰150x100x20. 底座250x200x30. 用axisymmetric+sketch_extrude+composition."},
    {"id":"g5_robot_arm","prompt":"机器人手臂段,单位mm. 管段外径130内径110长500. 两端法兰外径180厚25各8个M14孔PCD150. 用axisymmetric+composition."},
    {"id":"g6_helix_coil","prompt":"20圈螺旋管,单位mm. helix_sweep radius_mm=100 height_mm=400 pitch_mm=20 profile_radius_mm=6 turns=20."},
    {"id":"g7_3d_tube","prompt":"三维弯曲管路6点路径,单位mm. sweep半径15. 从(0,0,0)到(550,30,350)."},
    {"id":"g8_var_duct","prompt":"变截面风管三截面,单位mm. loft从圆D100到矩形120x80再到圆D80,间距150mm."},
    {"id":"g9_torsion_spring","prompt":"15圈扭簧,单位mm. helix_sweep radius_mm=60 height_mm=225 pitch_mm=15 profile_radius_mm=4 turns=15."},
    {"id":"g10_spiral_volute","prompt":"渐开线蜗壳8点螺旋,单位mm. sweep_profile圆形半径12."},
    {"id":"g11_pressure_vessel","prompt":"薄壁压力容器外径300内径290高400,单位mm. revolve_profile壁厚5mm两端半球封头. 用axisymmetric+shell_housing."},
    {"id":"g12_hollow_bracket","prompt":"空心支架200x160x70mm,单位mm. extrude_rectangle后shell_body厚3mm. 四角8mm安装孔. 侧面2个15mm过孔."},
    {"id":"g13_enclosure","prompt":"设备外壳300x200x150mm,单位mm. extrude_rectangle后shell_body厚4mm. 前面板100x60开口. 安装孔6mm四角."},
    {"id":"g14_vacuum_chamber","prompt":"真空腔体外径200内径180长400,单位mm. 前后盖板220x220x20. 前盖观察窗直径100. 后盖2个直径50泵接口. 用axisymmetric+sketch_extrude+composition."},
    {"id":"g15_heavy_flange","prompt":"重型法兰外径400内径120厚55,单位mm. 外圈24个M18孔PCD340. 内圈12个M12孔PCD200起始角15度."},
    {"id":"g16_stepped_pulley","prompt":"9段多级带轮,单位mm. revolve_profile各级半径120,105,90,78,65,55,45,35,25. 每级宽9mm总高87. 中心孔直径30."},
    {"id":"g17_cross_block","prompt":"六面钻孔块100mm立方,单位mm. extrude_rectangle. 顶面直径20孔. 前面2个直径10间距40. 左右面各直径8."},
    {"id":"g18_ribbed_panel","prompt":"加强筋面板550x400x8mm,单位mm. extrude_rectangle后7条纵筋4条横筋厚4高30. 间距约60mm交叉网格."},
    {"id":"g19_precision_base","prompt":"精密基座305x280x15mm,单位mm. extrude_rectangle后四角直径30定位孔. 中心轴承座直径40内径20高20."},
    {"id":"g20_motor_endbell","prompt":"电机端盖外径250内径40,单位mm. revolve_profile+extrude_rectangle接线盒60x40x30. 6个M10安装孔PCD200. 用composition."},
    {"id":"g21_valve_body","prompt":"阀体装配球径140壁厚8,单位mm. revolve_profile+两端法兰. 进口法兰直径100出口法兰直径80各4个M12孔. 阀杆孔直径20."},
    {"id":"g22_heat_sink","prompt":"散热器328x228x8mm,单位mm. extrude_rectangle后18片鳍片厚2高100间距12. 四角6mm安装孔."},
    {"id":"g23_pipe_reducer","prompt":"变径管从D100到D60长150mm,单位mm. loft_sections+法兰厚20外径120. 6个M12孔PCD90."},
    {"id":"g24_micro_bushing","prompt":"微型轴套外径6内径5.5长10mm,单位mm. revolve_profile壁厚0.25mm. 端面倒角0.2mm."},
    {"id":"g25_large_ring","prompt":"大直径环外径1000内径900厚30,单位mm. revolve_profile r=500 z=0-30. cut_center_bore diameter_mm=900. cut_circular_hole_pattern count=36 pcd_mm=950 hole_dia_mm=15."},
    {"id":"g26_extreme_shaft","prompt":"细长中空轴外径16内径6长500mm,单位mm. revolve_profile壁厚5mm."},
    # SKIP g27: 300 holes OCP segfault
    {"id":"g28_ball_valve","prompt":"球阀装配,单位mm. 阀体外径160球径100通孔80. 两端法兰直径120各4个M14孔. 阀杆直径25. 用axisymmetric+composition."},
    {"id":"g29_impeller","prompt":"离心叶轮,单位mm. 轮毂外径300内径40高35. 6个均布叶片厚5高20. 用axisymmetric+composition."},
    {"id":"g30_hyd_cylinder","prompt":"液压缸端盖外径70内径30厚30,单位mm. revolve_profile. 6个M8安装孔PCD55. 密封槽宽5深3."},
]

# ═══════════════════ PIPELINE ═══════════════════
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
    build_level2_authoring_prompt, build_level2_tool,
    build_level1_routing_prompt, build_level1_tool,
)
from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

REG = default_registry()
config = LlmModelConfig(model='deepseek-v4-pro', base_url='https://api.deepseek.com/beta')
caller = DeepSeekToolCaller()
LEGACY = {'axisymmetric_base':'axisymmetric','sketch_extrude_base':'sketch_extrude',
          'loft_sweep_base':'loft_sweep','shell_housing_base':'shell_housing','composition_base':'composition'}

# SW import disabled — SW crashed due to memory pressure. Generate STEP only.
def try_sw(step_path, sldprt_path, max_kb=500):
    return False, "SW_DISABLED"

results = []; t0 = time.time()
for i, case in enumerate(CASES):
    cid = case['id']; cdir = OUT / cid; cdir.mkdir(parents=True, exist_ok=True)
    (cdir/'input_text.txt').write_text(case['prompt'], encoding='utf-8')
    print(f"[{i+1:2d}/44] {cid}:", end=" ", flush=True)
    r = {'id':cid,'status':'STARTED','step_kb':0,'sw':False}

    # L1 (retry 4x)
    l1 = build_level1_routing_prompt(case['prompt'], dialect_catalog=REG.export_catalog())
    lt = build_level1_tool()
    plan = None
    for _ in range(4):
        try:
            tc = caller.call_strict_tool(
                messages=[{'role':'system','content':l1['system']},{'role':'user','content':l1['user']}],
                tool_name=lt['function']['name'],tool_description=lt['function']['description'],
                tool_schema=lt['function']['parameters'],model_config=config)
            a = dict(tc.arguments)
            for s in a.get('selected_domain_skills',[]):
                if not s.get('skill_version'): s['skill_version']='1.0'
            plan = DialectSelectionPlan.model_validate(a)
            for sd in plan.selected_dialects:
                if sd.dialect in LEGACY: sd.dialect = LEGACY[sd.dialect]
            break
        except: time.sleep(4)
    if plan is None: print('L1_FAIL'); r['status']='L1_FAIL'; results.append(r); continue
    (cdir/'route_plan.json').write_text(plan.model_dump_json(indent=2), encoding='utf-8')

    # L2
    try:
        l2 = build_level2_authoring_prompt(case['prompt'], plan)
        lt2 = build_level2_tool()
        tc2 = caller.call_strict_tool(
            messages=[{'role':'system','content':l2['system']},{'role':'user','content':l2['user']}],
            tool_name=lt2['function']['name'],tool_description=lt2['function']['description'],
            tool_schema=lt2['function']['parameters'],model_config=config)
        raw = tc2.arguments
        if 'llm_validation_hints' not in raw: raw['llm_validation_hints'] = {}
        (cdir/'llm_raw.json').write_text(json.dumps(raw,indent=2,ensure_ascii=False),encoding='utf-8')
    except Exception as e: print(f'L2_FAIL'); r['status']='L2_FAIL'; results.append(r); continue

    # Validate + autofix
    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
    if not report.ok:
        try:
            fixed, af = auto_fix_with_report(raw, REG)
            (cdir/'autofix_report.json').write_text(af.model_dump_json(indent=2),encoding='utf-8')
            if af.applied:
                (cdir/'raw_fixed.json').write_text(json.dumps(fixed,indent=2,ensure_ascii=False),encoding='utf-8')
                canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed)
        except: pass
    (cdir/'validation_report.json').write_text(report.model_dump_json(indent=2),encoding='utf-8')
    errs = [i for i in report.issues if i.severity=='error']
    if canonical is None or errs: print(f'VAL_FAIL({len(errs)}e)'); r['status']='VAL_FAIL';r['n_err']=len(errs); results.append(r); continue

    print('VAL_OK',end=' ',flush=True)
    (cdir/'canonical.json').write_text(canonical.model_dump_json(indent=2),encoding='utf-8')
    (cdir/'validation_bundle.json').write_text(json.dumps(bundle.to_metadata_dict(),indent=2),encoding='utf-8')

    # Runtime
    try:
        rr = run_canonical_gcad(canonical=canonical, out_step=cdir/'output.step', metadata_path=cdir/'output.metadata.json',
                                validation_seed=bundle.to_metadata_dict() if bundle else {}, require_full_validation_seed=False)
        if rr.ok and (cdir/'output.step').exists():
            kb = (cdir/'output.step').stat().st_size//1024; r['step_kb']=kb
            print(f'STEP({kb}KB)',end=' ',flush=True)
            # SW (skip large files)
            sw_ok, sw_msg = try_sw(cdir/'output.step', cdir/'output.SLDPRT', max_kb=500)
            r['sw']=sw_ok; r['sw_msg']=sw_msg
            print(f'SW_{"OK" if sw_ok else sw_msg}',end='',flush=True)
            r['status']='PASS' if sw_ok else 'STEP_OK'
        else: print('RT_FAIL'); r['status']='RT_FAIL'; r['error']=(rr.error or '?')[:100]
    except Exception as e: print(f'RT_EXC'); r['status']='RT_EXC'; r['error']=str(e)[:100]
    print(); results.append(r)

# Summary
elapsed = time.time()-t0
passed = sum(1 for r in results if r['status'] in ('PASS','STEP_OK'))
sw = sum(1 for r in results if r.get('sw'))
print(f"\n{'='*60}\nTOTAL: {len(CASES)} cases, {elapsed/60:.0f}min, STEP={passed}, SW={sw}")
for r in results:
    print(f"  [{r['status']}] {r['id']}: step={r.get('step_kb',0)}KB sw={r.get('sw',False)}")
with open(OUT.parent/'v63_full45_results.json','w',encoding='utf-8') as f:
    json.dump({'total':len(CASES),'passed':passed,'sw':sw,'elapsed_min':round(elapsed/60,1),'cases':results},f,indent=2,ensure_ascii=False)
print("Done:",OUT.parent/'v63_full45_results.json')
