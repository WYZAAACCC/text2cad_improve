"""Resume v5.1 regression for remaining cases (no SW import)."""
import json, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "v51_regression_output"

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import AssemblyError

REG = default_registry()

CASES = [
    ("tm_weld_fork", "Weld Fork", ["sketch_extrude"],
     "焊接叉, 单位 mm.\nextrude_rectangle width_mm=80 height_mm=50 depth_mm=15 centered=true.\ncut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=30.\nadd_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[-30,0,7.5] centered=true.\nadd_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[30,0,7.5] centered=true.\ncut_hole diameter_mm=25 position_mm=[-30,25] through_all=true.\ncut_hole diameter_mm=25 position_mm=[30,25] through_all=true.\nadd_rib thickness_mm=8 height_mm=15 length_mm=60 position_mm=[0,0,7.5] direction=X.\napply_safe_fillet radius_mm=2 target=all_external_edges."),
    ("tm_gearbox_cover", "Gearbox Cover", ["sketch_extrude"],
     "减速器箱盖, 单位 mm.\nextrude_rectangle width_mm=300 height_mm=200 depth_mm=20 centered=true.\ncut_rectangular_pocket width_mm=260 height_mm=160 depth_mm=14 centered=true.\ncut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[-60,0,0] direction=Y.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[60,0,0] direction=Y.\nadd_rectangular_boss width_mm=100 height_mm=80 depth_mm=10 position_mm=[0,0,10] centered=true.\ncut_rectangular_pocket width_mm=80 height_mm=60 depth_mm=10 centered=true.\napply_safe_fillet radius_mm=3 target=all_external_edges."),
    ("tm_hex_nut", "Hex Nut", ["axisymmetric"],
     "M10六角螺母, 单位 mm.\nrevolve_profile: station1 r=9.5 z=0-8.\ncut_center_bore diameter_mm=8.5 through_all=true.\napply_safe_chamfer distance_mm=1 target=all_external_edges."),
    ("tm_turbine_disk", "Turbine Disk", ["axisymmetric"],
     "涡轮盘, 单位 mm.\nrevolve_profile: station1 r=150 z=0-20, station2 r=120 z=20-40, station3 r=80 z=40-65, station4 r=60 z=65-75, station5 r=50 z=75-85.\ncut_center_bore diameter_mm=30 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=80 hole_dia_mm=12.\ncut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=25.\ncut_annular_groove side=front inner_dia_mm=200 outer_dia_mm=240 depth_mm=6.\napply_safe_chamfer distance_mm=1.5 target=all_external_edges."),
    ("tm_robot_wrist", "Robot Wrist", ["axisymmetric"],
     "机器人腕部, 单位 mm.\nrevolve_profile: station1 r=80 z=0-200.\ncut_center_bore diameter_mm=152 through_all=true.\ncut_circular_hole_pattern count=6 pcd_mm=140 hole_dia_mm=8.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."),
    ("tm_exhaust_manifold", "Exhaust Manifold", ["loft_sweep"],
     "排气歧管S形弯管, 单位 mm.\ncreate_sweep_path path_points: [{x_mm:0,y_mm:0,z_mm:0},{x_mm:0,y_mm:30,z_mm:80},{x_mm:0,y_mm:60,z_mm:160},{x_mm:0,y_mm:30,z_mm:240},{x_mm:0,y_mm:0,z_mm:320}].\nsweep_profile shape=circle radius_mm=18."),
    ("tm_hyd_valve", "Hyd Valve", ["sketch_extrude"],
     "液压阀体, 单位 mm.\nextrude_rectangle width_mm=80 height_mm=60 depth_mm=200 centered=true.\ncut_hole diameter_mm=20 position_mm=[0,0] through_all=true axis=Z.\ncut_hole diameter_mm=10 position_mm=[0,15] through_all=true axis=Y.\ncut_hole diameter_mm=10 position_mm=[0,-15] through_all=true axis=Y.\ncut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=40.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."),
    ("tm_diff_case", "Diff Case", ["axisymmetric"],
     "差速器壳体, 单位 mm.\nrevolve_profile: station1 r=75 z=0-20, station2 r=60 z=20-80, station3 r=75 z=80-100.\ncut_center_bore diameter_mm=100 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\ncut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=140 depth_mm=3.\napply_safe_chamfer distance_mm=1 target=all_external_edges."),
    ("s20_spring", "Long Spring", ["loft_sweep"],
     "长螺旋弹簧, 单位 mm. helix_sweep: radius_mm=20 height_mm=150 pitch_mm=12 profile_radius_mm=1.2 turns=12."),
    ("s20_rib_plate", "Dense Rib", ["sketch_extrude"],
     "密集筋板, 单位 mm.\nextrude_rectangle width_mm=300 height_mm=200 depth_mm=15 centered=true.\ncut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=260 spacing_y_mm=160.\nadd_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[-80,0,7.5] direction=Y.\nadd_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[-40,0,7.5] direction=Y.\nadd_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[0,0,7.5] direction=Y.\nadd_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[40,0,7.5] direction=Y.\nadd_rib thickness_mm=6 height_mm=20 length_mm=150 position_mm=[80,0,7.5] direction=Y.\napply_safe_fillet radius_mm=1.5 target=all_external_edges."),
    ("s20_deep_holes", "Deep Hole Block", ["sketch_extrude"],
     "深孔阀块, 单位 mm.\nextrude_rectangle width_mm=100 height_mm=80 depth_mm=150 centered=true.\ncut_hole diameter_mm=25 position_mm=[0,0] through_all=true axis=Z.\ncut_hole diameter_mm=15 position_mm=[0,20] through_all=true axis=Y.\ncut_hole diameter_mm=15 position_mm=[0,-20] through_all=true axis=Y.\ncut_hole diameter_mm=10 position_mm=[25,0] through_all=true axis=X.\ncut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."),
    ("s20_3d_pipe", "3D Space Pipe", ["loft_sweep"],
     "三维空间弯管, 单位 mm.\ncreate_sweep_path path_points(x_mm/y_mm/z_mm): [{x_mm:0,y_mm:0,z_mm:0},{x_mm:30,y_mm:20,z_mm:40},{x_mm:60,y_mm:0,z_mm:80},{x_mm:40,y_mm:-30,z_mm:120},{x_mm:0,y_mm:-20,z_mm:160},{x_mm:-30,y_mm:0,z_mm:200}].\nsweep_profile shape=circle radius_mm=8."),
    ("s20_valve_block", "Multi-Port Valve", ["sketch_extrude"],
     "多端口阀块, 单位 mm.\nextrude_rectangle width_mm=120 height_mm=100 depth_mm=180 centered=true.\ncut_hole diameter_mm=20 position_mm=[0,30] through_all=true axis=Y.\ncut_hole diameter_mm=25 position_mm=[0,-30] through_all=true axis=Y.\ncut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=100 spacing_y_mm=80.\napply_safe_chamfer distance_mm=0.3 target=all_external_edges."),
]

def call_llm(user_msg):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    resp = client.chat.completions.create(model="deepseek-v4-pro",
        messages=[{"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
        tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120, extra_body={"thinking": {"type": "disabled"}})
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)

def build_step(cdir):
    can = cdir / "canonical.json"
    val = cdir / "validation_bundle.json"
    stp = cdir / "output.step"
    met = cdir / "output.metadata.json"
    bscript = (
        "import sys; sys.path.insert(0, r'" + SRC.as_posix() + "')\n"
        "from pathlib import Path\n"
        "from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files\n"
        "r = run_canonical_gcad_from_files(canonical_json=Path(r'" + can.as_posix() + "'),"
        "validation_seed_json=Path(r'" + val.as_posix() + "'),"
        "out_step=Path(r'" + stp.as_posix() + "'),"
        "metadata_path=Path(r'" + met.as_posix() + "'))\n"
        "if r.ok: print('BUILD_OK')\n"
        "else: print(f'BUILD_FAILED: {r.error}')\n"
    )
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    return r.returncode == 0 and stp.exists()

if __name__ == "__main__":
    for i, (cid, name, dialects, prompt) in enumerate(CASES):
        cdir = OUT / cid
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(prompt, encoding="utf-8")

        contract_lines = ["=== CONTRACT ===", "CRITICAL: output solid->body, direction +/- (NOT Z), path_points x_mm/y_mm/z_mm", "composition ONLY in __assembly__", "boolean_union ALWAYS 2 inputs", ""]
        for did in dialects:
            d = REG.get(did)
            if d is None: continue
            contract_lines.append(f"=== {did} ===")
            for (op_name, _), spec in d.op_specs().items():
                contract_lines.append(f"  {op_name} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")

        base_msg = f"TASK: {prompt}\n\n" + "\n".join(contract_lines) + "\n\nUse EXACT op/param names. All safety=true."
        start = time.time()

        ok = False; err = ""
        for attempt in range(5):
            um = base_msg + (f"\n\nFAILED: {err[:400]}\nFIX. Attempt {attempt+1}/5." if attempt > 0 else "")
            try: args = call_llm(um)
            except Exception as e: err = f"LLM:{e}"; continue
            (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

            try:
                fixed, af = auto_fix_with_report(args, REG)
                (cdir / "autofix_report.json").write_text(json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
            except: fixed = args

            fixed.setdefault("llm_validation_hints", {})
            if fixed.get("llm_validation_hints") is None: fixed["llm_validation_hints"] = {}
            fixed.setdefault("units", "mm"); fixed.setdefault("trust_level", "reference_geometry")

            try:
                doc = RawGcadDocument.model_validate(fixed)
                canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
                if not (canonical and report and report.ok):
                    issues = report.issues or []
                    err = "; ".join("[{}] {}".format(getattr(i,"code","?"), getattr(i,"message",str(i))[:120]) for i in (issues[:3] if issues else []))
                    continue
                (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                if bundle: (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                ok = True; break
            except AssemblyError as e: err = f"AssemblyError:{e}"; continue
            except Exception as e: err = str(e)[:200]; continue

        if ok and build_step(cdir):
            sz = (cdir / "output.step").stat().st_size
            # semantic postcheck
            sem_ok = None
            try:
                from seekflow_engineering_tools.generative_cad.authoring.design_intent_extractor import extract_design_intent_metrics
                from seekflow_engineering_tools.generative_cad.runtime.semantic_postcheck import run_semantic_postcheck
                intent = extract_design_intent_metrics(prompt)
                sp = run_semantic_postcheck(step_path=cdir / "output.step", design_intent=intent)
                sem_ok = sp.semantic_valid
                (cdir / "semantic_postcheck.json").write_text(json.dumps(sp.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            except: pass
            print(f"[{i+1:02d}/13] {name:20s} STEP={sz}B sem={sem_ok} [{time.time()-start:.0f}s]")
        else:
            print(f"[{i+1:02d}/13] {name:20s} FAIL: {err[:150]} [{time.time()-start:.0f}s]")
        time.sleep(0.3)
    print("Done.")
