"""v6.1 — 针对之前 8 个失败 case 的修复后回归测试。"""
import json, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "v61_8failed_output"
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import AssemblyError

REG = default_registry()

# ═══════════════════════════════════════════════════════════════════════════════
# Proven contract builder (from run_v51_full35.py)
# ═══════════════════════════════════════════════════════════════════════════════

def build_full_contract(dialect_ids):
    lines = [
        "=== DIALECT CONTRACTS (EXACT names required) ===", "",
        "=== CRITICAL OUTPUT NAME RULES ===",
        "  output type=solid -> name='body'   (NEVER 'solid')",
        "  output type=frame -> name='outer_frame'",
        "  output type=curve -> name='curve'",
        "  output type=profile -> name='profile'", "",
        "=== CRITICAL PARAM RULES ===",
        "  extrude direction: '+' or '-' (NEVER 'Z', 'X', 'Y')",
        "  path_points use: x_mm, y_mm, z_mm (NEVER x, y, z)",
        "  chamfer/fillet target: 'all_external_edges'",
        "  revolve_profile params: 'profile_stations' (NEVER 'profile_points', 'stations')",
        "  revolve_profile has NO 'direction' field (only axis='Z')",
        "  thread_class cut_internal: '6H','6G','7H' (NOT '6g')",
        "  thread_class cut_external: '6g','6h','8g' (NOT '6H')",
        "  ALL 7 safety flags must be true",
        "  trust_level='reference_geometry'", "",
        "=== EXACT JSON FIELD NAMES ===",
        "  Node field for parameters is 'params' (NOT 'parameters')",
        "  Node field for operation version is 'op_version' (ALWAYS '1.0.0')",
        "  schema_version MUST be 'g_cad_core_v0.2'",
        "  Safety: ALL 7 fields must be true",
        "  boolean_union: params={}, inputs use component refs, ALWAYS exactly 2 inputs",
        "  Composition ops ONLY in __assembly__ component", "",
        "=== MIXED DIALECT TEMPLATE ===",
        "  shell_housing + sketch_extrude in SAME component:",
        "  component owner_dialect=sketch_extrude, nodes use their own dialect",
        "  shell_body node: inputs=[{node:EXTRUDE_NODE_ID,output:body}]",
        "  Do NOT create separate component for shell_housing", "",
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
                lines.append('    EXAMPLE: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":20},{"r_mm":30,"z_front_mm":20,"z_rear_mm":21}]}')
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
            elif op_name == "cut_external_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"length_mm":15,"standard":"ISO_metric","thread_class":"6g"}')
            elif op_name == "cut_internal_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":10,"pitch_mm":1.5,"depth_mm":20,"standard":"ISO_metric","thread_class":"6H"}')
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
# 8 previously-failed cases
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    {"id":"s01_thin_flange","name":"超大薄壁法兰(几何矛盾)","dialects":["axisymmetric"],
     "prompt":"超大薄壁法兰, 单位 mm.\nrevolve_profile station1 r=250 z=0-8.\ncut_center_bore diameter_mm=480 (壁厚10mm).\ncut_circular_hole_pattern count=24 pcd_mm=470 hole_dia_mm=12.\napply_safe_chamfer distance_mm=0.5.",
     "expected":"preflight应报错: bore(480) > outer_dia(500) 但壁厚=(500-480)/2=10mm, 实际上几何是可行的! 原prompt可能有歧义"},

    {"id":"s05_long_spring","name":"长弹簧(15圈分段)","dialects":["loft_sweep"],
     "prompt":"长螺旋弹簧, 单位 mm.\nhelix_sweep radius_mm=20 height_mm=150 pitch_mm=10 profile_radius_mm=1.5 turns=15.\n中径40mm, 簧丝直径3mm, 15圈, 自由长度150mm.",
     "expected":"分段OCP MakePipe + Fuse, volume ratio > 0.65"},

    {"id":"s10_shelled_box","name":"薄壁壳体(混编dialect)","dialects":["sketch_extrude","shell_housing"],
     "prompt":"薄壁壳体, 单位 mm.\n单个组件comp_1, owner_dialect=sketch_extrude.\n先extrude_rectangle width_mm=200 height_mm=150 depth_mm=100 centered=true.\n再cut_rectangular_pocket width_mm=180 height_mm=130 depth_mm=90.\n最后shell_body thickness_mm=3.\n注意: extrude和shell在同一个组件, shell_body的input指向extrude节点.",
     "expected":"混编dialect正确: sketch_extrude创建solid, shell_housing的shell_body消费"},

    {"id":"s13_pipe_system","name":"多管路系统(竖直sweep)","dialects":["loft_sweep","composition"],
     "prompt":"多管路系统, 单位 mm.\n组件pipe_a(loft_sweep): create_sweep_path[{x_mm:-30,y_mm:0,z_mm:0},{x_mm:-30,y_mm:0,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}]. sweep_profile shape=circle radius_mm=15.\n组件pipe_b(loft_sweep): create_sweep_path[{x_mm:30,y_mm:0,z_mm:0},{x_mm:30,y_mm:0,z_mm:200},{x_mm:0,y_mm:0,z_mm:300}]. sweep_profile shape=circle radius_mm=15.\n组件main(loft_sweep): create_sweep_path[{x_mm:0,y_mm:0,z_mm:300},{x_mm:0,y_mm:0,z_mm:500}]. sweep_profile shape=circle radius_mm=30.\n装配__assembly__(composition): 依次boolean_union(每次2 inputs).",
     "expected":"OCP 3D pipe处理竖直段(z=300→500), 不崩溃"},

    {"id":"s15_multi_valve","name":"多通阀体(复杂特征)","dialects":["axisymmetric"],
     "prompt":"多通阀体, 单位 mm, 参考几何.\nrevolve_profile station1 r=60 z=0-100.\ncut_center_bore diameter_mm=30.\ncut_circular_hole_pattern count=4 pcd_mm=80 hole_dia_mm=6.\ncut_annular_groove side=front inner_dia_mm=50 outer_dia_mm=70 depth_mm=2.\napply_safe_chamfer distance_mm=1.",
     "expected":"增强的op_version修复+prompt模板, LLM应输出正确JSON"},

    {"id":"tm06_spring","name":"压缩弹簧(8圈OCP)","dialects":["loft_sweep"],
     "prompt":"压缩螺旋弹簧, 单位 mm, 参考几何.\nhelix_sweep: radius_mm=15 height_mm=80 pitch_mm=10 profile_radius_mm=2 turns=8.\n中径30mm, 簧丝直径4mm, 8圈.",
     "expected":"8圈一次性OCP MakePipe, volume ratio > 0.55"},

    {"id":"tm12_robot_wrist","name":"机器人腕部(JSON sanitize)","dialects":["axisymmetric"],
     "prompt":"机器人腕部壳体, 单位 mm.\nrevolve_profile station1 r=80 z=0-200.\ncut_center_bore diameter_mm=152 (壁厚4mm).\ncut_circular_hole_pattern count=6 pcd_mm=140 hole_dia_mm=8.\napply_safe_chamfer distance_mm=0.5.",
     "expected":"JSON sanitizer清除control chars, 5次重试成功"},

    {"id":"tm15_diff_case","name":"差速器壳体(preflight)","dialects":["axisymmetric"],
     "prompt":"差速器壳体, 单位 mm.\nrevolve_profile: station1 r=75 z=0-20, station2 r=60 z=20-80, station3 r=75 z=80-100.\ncut_center_bore diameter_mm=100.\ncut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\ncut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=140 depth_mm=3.\napply_safe_chamfer distance_mm=1.",
     "expected":"preflight检查: bore(100) < outer(150), 壁厚25mm可行. 应通过validation."},
]


if __name__ == "__main__":
    import datetime
    print(f"=== v6.1 8-Failed-Case Regression ===")
    print(f"Output: {OUT}")
    print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    results = []
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]; cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        (cdir / "expected.txt").write_text(case["expected"], encoding="utf-8")
        contract = build_full_contract(case["dialects"])
        base_msg = (
            f"TASK: {case['prompt']}\n\n{contract}\n\n"
            "CRITICAL: Use EXACT op/param names from contract. "
            "Output solid->body. direction=+/-. path_points x_mm/y_mm/z_mm. "
            "All safety=true. trust_level=reference_geometry. "
            "boolean_union ALWAYS 2 inputs with params={}. "
            "Node field is 'params' NOT 'parameters'. op_version ALWAYS '1.0.0'."
        )
        start = time.time(); ok = False; err = ""; llm_attempts = 0
        for attempt in range(5):
            llm_attempts = attempt + 1
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
                    continue
                (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                if bundle: (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                ok = True; break
            except AssemblyError as e: err = f"Assembly:{e}"; continue
            except Exception as e: err = f"{type(e).__name__}:{e}"; continue

        elapsed = time.time()-start
        if not ok:
            print(f"[{i+1}/8] {case['name']:25s} VALID_FAIL ({llm_attempts} LLM calls) [{elapsed:.0f}s]")
            print(f"       Error: {err[:150]}")
            results.append({"id":case["id"],"name":case["name"],"ok":False,"step_ok":False,"msg":err[:200],"llm_attempts":llm_attempts})
            continue

        step_ok = build_step(cdir)
        elapsed2 = time.time()-start
        if step_ok:
            sz = (cdir / "output.step").stat().st_size
            print(f"[{i+1}/8] {case['name']:25s} STEP={sz}B ({llm_attempts} LLM, build={elapsed2-elapsed:.0f}s) [{elapsed2:.0f}s]")
            results.append({"id":case["id"],"name":case["name"],"ok":True,"step_ok":True,"step_size":sz,"llm_attempts":llm_attempts})
        else:
            print(f"[{i+1}/8] {case['name']:25s} BUILD_FAILED ({llm_attempts} LLM calls) [{elapsed2:.0f}s]")
            results.append({"id":case["id"],"name":case["name"],"ok":True,"step_ok":False,"msg":"build failed","llm_attempts":llm_attempts})

    # Summary
    step_ok = sum(1 for r in results if r.get("step_ok"))
    valid_ok = sum(1 for r in results if r.get("ok"))
    print(f"\n{'='*60}")
    print(f"SUMMARY: {step_ok}/8 STEP generated, {valid_ok}/8 validated")
    for r in results:
        status = "STEP_OK" if r.get("step_ok") else ("VALID_FAIL" if not r.get("ok") else "BUILD_FAIL")
        print(f"  {r['id']:25s} {status:12s} attempts={r.get('llm_attempts','?')} {r.get('step_size','')}")

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults: {OUT / 'results.json'}")
