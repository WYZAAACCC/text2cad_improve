"""Full text-to-CAD pipeline test: LLM(deepseek-v4-pro) -> validate -> autofix -> runtime -> STEP -> SW SLDPRT.
Pattern follows run_v62_stress30.py with fresh prompts for every case.
"""
import json, os, sys, subprocess, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent
CASES_DIR = OUT / "cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()

def build_contract(dialect_ids):
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
        "  cut_hole NOW supports axis='X'/'Y'/'Z' for side drilling!",
        "  cut_hole_v2: use target_face+center_uv_mm+normal_axis (preferred for new parts)", "",
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
            elif op_name == "cut_hole":
                lines.append('    EXAMPLE: {"diameter_mm":10,"position_mm":[20,20],"axis":"Z","through_all":true}')
            elif op_name == "cut_hole_v2":
                lines.append('    EXAMPLE: {"diameter_mm":10,"placement":{"target_face":"top","center_uv_mm":[20,20],"normal_axis":"+Z","through_mode":"through_all"}}')
            elif op_name == "helix_sweep":
                lines.append('    EXAMPLE: {"radius_mm":80,"height_mm":160,"pitch_mm":16,"profile_radius_mm":5,"turns":10}')
            elif op_name == "sweep_profile":
                lines.append('    EXAMPLE: {"shape":"circle","radius_mm":12}')
            elif op_name == "boolean_union":
                lines.append('    EXAMPLE: params={}, inputs=[{component:c1,output:body},{component:c2,output:body}]')
            elif op_name == "shell_body":
                lines.append('    EXAMPLE: {"thickness_mm":3.0}')
            elif op_name == "cut_circular_hole_pattern":
                lines.append('    EXAMPLE: {"count":8,"pcd_mm":160,"hole_dia_mm":12,"axis":"Z","through_all":true}')
            elif op_name == "cut_hole_pattern_linear":
                lines.append('    EXAMPLE: {"hole_dia_mm":11,"count_x":2,"count_y":2,"spacing_x_mm":120,"spacing_y_mm":90,"axis":"Z"}')
        lines.append("")
    return "\n".join(lines)


def call_llm(system_prompt, user_msg):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    resp = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}],
        tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120, extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)


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


def import_sw(step_path, sldprt_path):
    """Import STEP to SolidWorks, return True on success."""
    try:
        from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
        template = Path(r'C:/ProgramData/SOLIDWORKS/SOLIDWORKS 2025/templates/gb_part.prtdot')
        client = SolidWorksClient(visible=False, part_template=template).connect()
        ok = client.import_step_as_part(str(step_path), str(sldprt_path))
        client.close_all(); client.close()
        return ok and sldprt_path.exists() and sldprt_path.stat().st_size > 0
    except Exception as e:
        print(f"    SW error: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# 15 Test Cases — 5 from stress30 + 10 new
# ═══════════════════════════════════════════════════════════

CASES = [
    # --- Group A: Single-Body Basic ---
    {"id":"v4_flange","name":"法兰盘","dialects":["axisymmetric"],
     "prompt":"法兰盘, 单位mm. revolve_profile 外径200内径80厚20: station1 r=100 z=0-20. cut_center_bore diameter_mm=80. cut_circular_hole_pattern count=8 pcd_mm=160 hole_dia_mm=12."},

    {"id":"v4_shaft","name":"阶梯轴","dialects":["axisymmetric"],
     "prompt":"阶梯轴, 单位mm. revolve_profile 多级台阶: station1 r=25 z=0-30, station2 r=30 z=30-80, station3 r=20 z=80-150. cut_center_bore diameter_mm=10 (中心通孔). apply_safe_chamfer distance_mm=1.0 target=all_external_edges."},

    {"id":"v4_valve_block","name":"阀块","dialects":["sketch_extrude"],
     "prompt":"液压阀块, 单位mm. extrude_rectangle width_mm=120 height_mm=100 depth_mm=150 centered=true. cut_hole diameter_mm=20 position_mm=[0,0] axis=Z (P口顶面). cut_hole diameter_mm=15 position_mm=[30,20] axis=Y (A口前面). cut_hole diameter_mm=15 position_mm=[-30,20] axis=Y (B口前面). cut_hole diameter_mm=25 position_mm=[0,0] axis=X (进油口右面)."},

    # --- Group B: Hole & Pattern Semantics ---
    {"id":"v4_cross_block","name":"六面钻孔","dialects":["sketch_extrude"],
     "prompt":"六面钻孔测试块100x100x100mm, 单位mm. extrude_rectangle width_mm=100 height_mm=100 depth_mm=100 centered=true. top面: cut_hole diameter_mm=20 position_mm=[0,0] axis=Z. bottom面: cut_hole diameter_mm=15 position_mm=[15,0] axis=Z. front面: cut_hole diameter_mm=12 position_mm=[20,20] axis=Y. back面: cut_hole diameter_mm=12 position_mm=[-20,20] axis=Y. right面: cut_hole diameter_mm=10 position_mm=[0,0] axis=X. left面: cut_hole diameter_mm=10 position_mm=[0,0] axis=X."},

    {"id":"v4_dual_pcd","name":"双PCD法兰","dialects":["axisymmetric"],
     "prompt":"双圈螺栓孔法兰, 单位mm. revolve_profile 外径300内径60厚40: station1 r=150 z=0-40. cut_center_bore diameter_mm=60. 外圈: cut_circular_hole_pattern count=12 pcd_mm=240 hole_dia_mm=18. 内圈: cut_circular_hole_pattern count=8 pcd_mm=160 hole_dia_mm=12."},

    {"id":"v4_perforated","name":"多孔板","dialects":["sketch_extrude"],
     "prompt":"多孔安装板200x150x10mm, 单位mm. extrude_rectangle width_mm=200 height_mm=150 depth_mm=10 centered=true. 20行x15列共300个直径3mm通孔, 间距8mm: cut_hole_pattern_linear hole_dia_mm=3 count_x=20 count_y=15 spacing_x_mm=8 spacing_y_mm=8."},

    # --- Group C: Feature Order & Scope ---
    {"id":"v4_ribbed_base","name":"加筋基座","dialects":["sketch_extrude"],
     "prompt":"加筋基座, 单位mm. extrude_rectangle width_mm=300 height_mm=240 depth_mm=25 centered=true. 四角安装孔: cut_hole_pattern_linear hole_dia_mm=14 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=190. 加筋: add_rib thickness_mm=10 height_mm=30 length_mm=200 position_mm=[0,-100,12.5] direction=X. add_rib thickness_mm=10 height_mm=30 length_mm=200 position_mm=[0,100,12.5] direction=X. add_rib thickness_mm=10 height_mm=30 length_mm=140 position_mm=[-100,0,12.5] direction=Y. add_rib thickness_mm=10 height_mm=30 length_mm=140 position_mm=[100,0,12.5] direction=Y."},

    {"id":"v4_shell_box","name":"壳体箱","dialects":["sketch_extrude","shell_housing"],
     "prompt":"电子外壳, 单位mm. extrude_rectangle width_mm=200 height_mm=150 depth_mm=100 centered=true. shell_body thickness_mm=3.0 (抽壳后壁厚3mm). 底面开口保持不变. 正面开口: cut_rectangular_pocket width_mm=80 height_mm=50 depth_mm=3 centered=true plane=YZ (前面板开口). 安装孔: cut_hole_pattern_linear hole_dia_mm=5 count_x=2 count_y=2 spacing_x_mm=160 spacing_y_mm=110."},

    # --- Group D: Advanced Geometry ---
    {"id":"v4_spring","name":"螺旋弹簧","dialects":["loft_sweep"],
     "prompt":"螺旋弹簧15圈, 单位mm. helix_sweep radius_mm=60 height_mm=225 pitch_mm=15 profile_radius_mm=4 turns=15. strict_semantic:false."},

    {"id":"v4_3d_pipe","name":"空间管路","dialects":["loft_sweep"],
     "prompt":"三维弯曲管路, 单位mm. create_sweep_path path_points=[{x_mm:0,y_mm:0,z_mm:0},{x_mm:100,y_mm:50,z_mm:80},{x_mm:200,y_mm:-30,z_mm:150},{x_mm:300,y_mm:20,z_mm:200},{x_mm:400,y_mm:0,z_mm:280},{x_mm:500,y_mm:30,z_mm:350}]. sweep_profile shape=circle radius_mm=15."},

    {"id":"v4_var_duct","name":"变径风管","dialects":["loft_sweep"],
     "prompt":"变截面风管, 单位mm. loft_sections sections=[{position:{x_mm:0,y_mm:0,z_mm:0},shape:circle,radius_mm:50},{position:{x_mm:0,y_mm:0,z_mm:150},shape:rectangle,width_mm:100,height_mm:70},{position:{x_mm:0,y_mm:0,z_mm:300},shape:circle,radius_mm:40}]."},

    # --- Group E: Multi-Component/Assembly ---
    {"id":"v4_support_frame","name":"支撑框架","dialects":["sketch_extrude","axisymmetric","composition"],
     "prompt":"四柱支撑框架, 单位mm.\n组件base_plate(sketch_extrude): extrude_rectangle width_mm=400 height_mm=300 depth_mm=20 centered=true. 4安装孔: cut_hole_pattern_linear hole_dia_mm=16 count_x=2 count_y=2 spacing_x_mm=350 spacing_y_mm=250.\n组件pillar(axisymmetric): revolve_profile station1 r=25 z=0-200. 生产4个副本.\n组件top_plate(sketch_extrude): extrude_rectangle width_mm=400 height_mm=300 depth_mm=15 centered=true.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    {"id":"v4_double_flange","name":"双法兰管","dialects":["axisymmetric","composition"],
     "prompt":"双法兰短管, 单位mm.\n组件pipe(axisymmetric): revolve_profile station1 r=40 z=0-200 (内径60外径80). cut_center_bore diameter_mm=60.\n组件flange_a(axisymmetric): revolve_profile station1 r=70 z=0-20. cut_center_bore diameter_mm=80. cut_circular_hole_pattern count=6 pcd_mm=110 hole_dia_mm=12.\n组件flange_b(axisymmetric): revolve_profile station1 r=70 z=0-20. cut_center_bore diameter_mm=80. cut_circular_hole_pattern count=6 pcd_mm=110 hole_dia_mm=12.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs)."},

    # --- Group F: Boundary Tests ---
    {"id":"v4_large_ring","name":"大直径环","dialects":["axisymmetric"],
     "prompt":"大直径法兰环, 单位mm. revolve_profile 外径1000内径900厚30: station1 r=500 z=0-30. cut_center_bore diameter_mm=900. 均布36个直径16mm通孔: cut_circular_hole_pattern count=36 pcd_mm=950 hole_dia_mm=16."},

    {"id":"v4_thin_sleeve","name":"薄壁轴套","dialects":["axisymmetric"],
     "prompt":"薄壁轴套, 单位mm. revolve_profile 外径12内径10厚20: station1 r=6 z=0-20. cut_center_bore diameter_mm=10. 此零件壁厚仅1mm."},
]


if __name__ == "__main__":
    results = []
    t_start = time.time()

    for i, case in enumerate(CASES):
        cid = case["id"]
        cdir = CASES_DIR / cid
        cdir.mkdir(parents=True, exist_ok=True)
        print(f"\n{'='*50}\n[{i+1}/{len(CASES)}] {cid}: {case['name']}")

        # Save prompt
        (cdir / "input_text.txt").write_text(case["prompt"], encoding="utf-8")

        # Build contract
        contract = build_contract(case["dialects"])
        user_msg = contract + "\n\n=== USER REQUEST ===\n" + case["prompt"] + "\n\nGenerate RawGcadDocument JSON."

        # LLM call
        print("  LLM...", end=" ", flush=True)
        t0 = time.time()
        try:
            raw = call_llm(LEVEL2_AUTHORING_SYSTEM_PROMPT, user_msg)
            (cdir / "llm_raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
            n_nodes = len(raw.get("nodes", []))
            print(f"OK ({time.time()-t0:.0f}s, {n_nodes} nodes)", end=" ", flush=True)
            attempts = 1
            while attempts <= 3:
                canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
                errs = [i for i in report.issues if i.severity == "error"]
                if report.ok:
                    break
                if attempts == 3:
                    break
                # Try autofix
                try:
                    fixed, af = auto_fix_with_report(raw, REG)
                    (cdir / f"autofix_report_{attempts}.json").write_text(
                        json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
                    if af.applied:
                        (cdir / "raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
                        raw = fixed
                        print(f"autofix({len(af.entries)})", end=" ", flush=True)
                except: pass
                attempts += 1
        except Exception as e:
            print(f"LLM_FAIL: {e}")
            results.append({"id": cid, "status": "LLM_FAIL", "error": str(e)[:200]})
            continue

        (cdir / "validation_report.json").write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        if len(errs) > 0:
            print(f"VAL_FAIL({len(errs)} errs)")
            results.append({"id": cid, "status": "VAL_FAIL", "errors": len(errs)})
            continue

        # Save canonical + bundle
        (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")

        # Runtime
        print(f"build...", end=" ", flush=True)
        ok = build_step(cdir)
        step_size = (cdir / "output.step").stat().st_size if (cdir / "output.step").exists() else 0
        status = "STEP_OK" if ok else "BUILD_FAIL"
        print(f"{status} ({step_size//1024}KB)", end="", flush=True)

        # SW import
        sw_ok = False
        if ok:
            print(" SW...", end=" ", flush=True)
            sw_ok = import_sw(cdir / "output.step", cdir / "output.SLDPRT")
            print("OK" if sw_ok else "FAIL", end="", flush=True)

        print()
        results.append({"id": cid, "status": status, "step_kb": step_size//1024, "sw": sw_ok})

    # Summary
    print(f"\n{'='*60}")
    print(f"TOTAL: {len(CASES)} cases, {int((time.time()-t_start)/60)}min")
    passed = sum(1 for r in results if r["status"] == "STEP_OK")
    sw_imported = sum(1 for r in results if r.get("sw"))
    print(f"STEP: {passed}/{len(CASES)} | SW: {sw_imported}")
    for r in results:
        print(f"  {r['id']}: {r['status']} | step={r.get('step_kb','?')}KB | sw={r.get('sw','?')}")

    with open(OUT / "results.json", "w", encoding="utf-8") as f:
        json.dump({"total": len(CASES), "step_ok": passed, "sw_ok": sw_imported, "cases": results}, f, indent=2, ensure_ascii=False)
    print(f"\nResults: {OUT / 'results.json'}")
