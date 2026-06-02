"""全自动 Text-to-SolidWorks pipeline — 零手动修正。

每条链路: Text → DeepSeek LLM → AutoFixer → Validation → [RepairAgent] → STEP → SW
Agent 自动检测并修复所有常见 LLM 错误，无需人工干预。
"""
import json, os, sys, time, subprocess, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA_PYTHON = r"E:\auto_detection_process\.conda\python.exe"
OUTPUT_DIR = Path(r"E:\auto_detection_process\demo_output_v5")

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix
from seekflow_engineering_tools.generative_cad.authoring.repair_agent import repair_with_llm
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()


# ═══════════════════════════════════════════════════════════════════════════════
# LLM 调用
# ═══════════════════════════════════════════════════════════════════════════════

def call_llm(system: str, user: str) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    raw_schema = RawGcadDocument.model_json_schema()
    tool_schema = to_deepseek_strict_schema(raw_schema)
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": tool_schema}}]

    response = client.chat.completions.create(
        model="deepseek-v4-pro", messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120, extra_body={"thinking": {"type": "disabled"}},
    )
    msg = response.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError("No tool call")
    return json.loads(msg.tool_calls[0].function.arguments)


# ═══════════════════════════════════════════════════════════════════════════════
# Dialect contract (给 LLM 的精确 op/param 表)
# ═══════════════════════════════════════════════════════════════════════════════

def build_contract_text(dialect_ids: list[str]) -> str:
    lines = []
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} v{d.version} | phases: {' → '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            req_list = ps.get("required", [])
            pstrs = []
            for pn, pi in props.items():
                req = "REQUIRED" if pn in req_list else "opt"
                ref = pi.get("$ref", "")
                if ref:
                    rn = ref.split("/")[-1]
                    np = ps.get("$defs", {}).get(rn, {}).get("properties", {})
                    fs = ", ".join(f"{k}:{v.get('type','?')}" for k, v in np.items())
                    pstrs.append(f"{pn}=[{req}] list{{{fs}}}")
                elif "enum" in pi:
                    pstrs.append(f"{pn}={pi['enum']} [{req}]")
                else:
                    pstrs.append(f"{pn}:{pi.get('type','?')} [{req}]")
            lines.append(f"  {op_name} v{spec.op_version} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs)}")
            # 为 revolve_profile 添加显式 example (LLM 在此处最容易出错)
            if op_name == "revolve_profile":
                lines.append("    EXAMPLE: {{\"axis\":\"Z\",\"profile_stations\":[{{\"r_mm\":40.0,\"z_front_mm\":0.0,\"z_rear_mm\":12.0}},{{\"r_mm\":15.0,\"z_front_mm\":12.0,\"z_rear_mm\":13.0}}]}}")
                lines.append("    NOTE: profile_stations is a list of objects. Each object has r_mm (RADIUS=half of diameter), z_front_mm, z_rear_mm. r_mm is NOT diameter! z_rear_mm MUST be > z_front_mm.")
            if op_name == "cut_center_bore":
                lines.append("    EXAMPLE: {{\"diameter_mm\":30.0,\"axis\":\"Z\",\"through_all\":true}}")
            if op_name == "extrude_rectangle":
                lines.append("    EXAMPLE: {{\"width_mm\":100,\"height_mm\":80,\"depth_mm\":10,\"plane\":\"XY\",\"centered\":true}}")
            if op_name == "boolean_union":
                lines.append("    NOTE: boolean_union takes no params (empty dict). Inputs must reference component outputs, not node outputs.")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 验证+自动修复循环 (最多 5 轮)
# ═══════════════════════════════════════════════════════════════════════════════

def validate_and_fix(raw_args: dict, dialect_ids: list[str], max_llm_repairs: int = 3) -> tuple:
    """自动修复 + LLM repair 循环。返回 (canonical, report, bundle) 或 (None, report, None)。"""
    # Step 1: AutoFixer
    raw_args = auto_fix(raw_args, REG)

    # Step 2: 确保必要字段存在
    if raw_args.get("llm_validation_hints") is None:
        raw_args["llm_validation_hints"] = {}
    if "units" not in raw_args:
        raw_args["units"] = "mm"
    if "trust_level" not in raw_args:
        raw_args["trust_level"] = "reference_geometry"

    # Step 3: 尝试验证
    for attempt in range(1 + max_llm_repairs):
        try:
            doc = RawGcadDocument.model_validate(raw_args)
        except Exception as e:
            if attempt < max_llm_repairs:
                # LLM repair
                fake_report = type("R", (), {"issues": [type("I", (), {"code": "pydantic_error", "message": str(e), "path": ""})]})()
                repaired = repair_with_llm(raw_args, fake_report, REG, max_rounds=1)
                if repaired:
                    raw_args = repaired
                    continue
            return None, None, None

        canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
        if canonical and report.ok:
            return canonical, report, bundle

        if attempt < max_llm_repairs:
            repaired = repair_with_llm(raw_args, report, REG, max_rounds=1)
            if repaired:
                raw_args = repaired
                continue

        return None, report, bundle

    return None, None, None


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 构建 + SolidWorks import
# ═══════════════════════════════════════════════════════════════════════════════

def build_step_and_sw(case_dir: Path) -> bool:
    script = f'''
import sys; sys.path.insert(0, r"{Path(__file__).parent / 'src'}")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
result = run_canonical_gcad_from_files(
    canonical_json=r"{(case_dir / 'canonical_gcad.json').as_posix()}",
    validation_seed_json=r"{(case_dir / 'validation_bundle.json').as_posix()}",
    out_step=r"{(case_dir / 'output.step').as_posix()}",
    metadata_path=r"{(case_dir / 'output.metadata.json').as_posix()}",
)
if not result.ok:
    print(f"BUILD_FAILED: {{result.error}}")
    for w in (result.warnings or []): print(f"WARN: {{w}}")
    sys.exit(1)
print("BUILD_OK")
'''
    sp = case_dir / "_build.py"
    sp.write_text(script, encoding="utf-8")
    try:
        r = subprocess.run([CONDA_PYTHON, str(sp)], capture_output=True, text=True, timeout=300, cwd=str(case_dir))
        ok = r.returncode == 0 and (case_dir / "output.step").exists()
        (case_dir / "_build_log.txt").write_text(f"RC={r.returncode}\n{r.stdout}\n{r.stderr}")
        if ok:
            # SW import
            sw_script = f'''
import sys; sys.path.insert(0, r"{Path(__file__).parent / 'src'}")
from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
step = Path(r"{(case_dir / 'output.step').as_posix()}")
sldprt = Path(r"{(case_dir / 'output.SLDPRT').as_posix()}")
client = SolidWorksClient(visible=False).connect()
ok = client.import_step_as_part(step, sldprt)
client.close()
print(f"SW_OK" if ok and sldprt.exists() else "SW_FAIL")
'''
            swp = case_dir / "_import_sw.py"
            swp.write_text(sw_script, encoding="utf-8")
            subprocess.run([sys.executable, str(swp)], capture_output=True, text=True, timeout=120)
        return ok
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    {
        "id": "washer", "name": "Washer 垫圈",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a simple reference washer: outer diameter 80mm, center bore 30mm, thickness 12mm.\n"
            "Use revolve_profile with profile_stations and cut_center_bore with diameter_mm.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    {
        "id": "stepped_shaft", "name": "Stepped Shaft 阶梯轴",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a stepped shaft with three cylindrical sections along Z axis:\n"
            "Bottom: diameter 60mm (r_mm=30), height 20mm (z=0 to 20).\n"
            "Middle: diameter 40mm (r_mm=20), height 30mm (z=20 to 50).\n"
            "Top: diameter 25mm (r_mm=12.5), height 25mm (z=50 to 75).\n"
            "Use revolve_profile with profile_stations defining each section.\n"
            "Apply 1mm chamfer on all external edges using apply_safe_chamfer.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    {
        "id": "hole_plate", "name": "Plate with Holes 带孔板",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "Create a rectangular base plate 120x80x12mm using extrude_rectangle.\n"
            "Add 4 mounting holes diameter 6mm at corners using cut_hole_pattern_linear:\n"
            "count_x=2 count_y=2 spacing_x_mm=90 spacing_y_mm=50.\n"
            "Add a central rectangular pocket 50x30x4mm using cut_rectangular_pocket.\n"
            "Apply 1mm fillet on all external edges using apply_safe_fillet.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    {
        "id": "angle_bracket", "name": "Angle Bracket 直角支架",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "Create an L-shaped bracket using sketch_extrude dialect:\n"
            "1. extrude_rectangle width_mm=80 height_mm=50 depth_mm=8 plane=XY centered=true (base plate)\n"
            "2. add_rectangular_boss width_mm=8 height_mm=40 depth_mm=80 plane=YZ centered=false position_mm=[0,25,0] (vertical leg)\n"
            "3. apply_safe_fillet radius_mm=2 target=all_external_edges\n"
            "Only ONE base_solid (use extrude_rectangle once).\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    {
        "id": "spur_gear", "name": "Spur Gear 齿轮",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a gear blank (NOT the involute teeth — just the cylindrical blank):\n"
            "Outer diameter 44mm, center bore 10mm, thickness 15mm.\n"
            "Use revolve_profile for the blank and cut_center_bore for the bore.\n"
            "This is a reference-geometry blank, not a manufacturing-ready gear.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    {
        "id": "finned_heatsink", "name": "Finned Heatsink 散热器",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "Create a finned heatsink using sketch_extrude:\n"
            "1. extrude_rectangle width_mm=100 height_mm=60 depth_mm=5 (base)\n"
            "2. add_rectangular_boss width_mm=2 height_mm=25 depth_mm=60 position_mm=[-40,0,0] plane=XY centered=true (fin 1)\n"
            "3. add_rectangular_boss width_mm=2 height_mm=25 depth_mm=60 position_mm=[-25,0,0] plane=XY centered=true (fin 2)\n"
            "4. add_rectangular_boss width_mm=2 height_mm=25 depth_mm=60 position_mm=[-10,0,0] plane=XY centered=true (fin 3)\n"
            "5. add_rectangular_boss width_mm=2 height_mm=25 depth_mm=60 position_mm=[5,0,0] plane=XY centered=true (fin 4)\n"
            "6. add_rectangular_boss width_mm=2 height_mm=25 depth_mm=60 position_mm=[20,0,0] plane=XY centered=true (fin 5)\n"
            "7. add_rectangular_boss width_mm=2 height_mm=25 depth_mm=60 position_mm=[35,0,0] plane=XY centered=true (fin 6)\n"
            "8. apply_safe_fillet radius_mm=0.5 target=all_external_edges\n"
            "Only ONE base_solid node (the first extrude_rectangle).\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    {
        "id": "hub_plate", "name": "Hub+Plate Assembly 轴套底板",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "prompt": (
            "Create an assembly of a hub and base plate:\n"
            "Component 'hub' (axisymmetric): revolve_profile with profile_stations: "
            "r_mm=25 z=0-5, r_mm=30 z=5-40. Then cut_center_bore diameter_mm=20.\n"
            "Component 'plate' (sketch_extrude): extrude_rectangle width_mm=100 height_mm=80 depth_mm=10.\n"
            "Component '__assembly__' (composition): boolean_union the hub and plate outputs.\n"
            "The boolean_union node must use component references in inputs: "
            "{component: hub, output: body} and {component: plate, output: body}.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

def run_case(case: dict) -> dict:
    case_dir = OUTPUT_DIR / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    result = {"id": case["id"], "name": case["name"], "ok": False, "stages": [], "error": None, "elapsed_s": -1}
    t0 = time.time()

    try:
        # Save prompt
        (case_dir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        result["stages"].append("prompt")

        # Build contract
        contract_text = build_contract_text(case["dialects"])
        user_msg = f"TASK: {case['prompt']}\n\n{contract_text}\n\nRULES: Use EXACT op/param names above. Output name=body for solids, name=outer_frame for frames. All 7 safety flags true. trust_level=reference_geometry. llm_validation_hints={{}}"

        # LLM call
        print(f"  [{case['id']}] Calling LLM...")
        args = call_llm(LEVEL2_AUTHORING_SYSTEM_PROMPT, user_msg)
        (case_dir / "llm_raw_output.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")
        result["stages"].append("llm")

        # AutoFix + Validate + Repair loop
        print(f"  [{case['id']}] AutoFix+Validate+Repair...")
        canonical, report, bundle = validate_and_fix(args, case["dialects"])
        if canonical is None:
            result["error"] = f"Validation failed after all repairs"
            if report:
                issues = report.issues if report else []
                result["error"] += ": " + "; ".join(f"[{i.code}] {i.message[:80]}" for i in issues[:5])
            (case_dir / "error.txt").write_text(result["error"])
        else:
            result["stages"].append("validated")
            (case_dir / "canonical_gcad.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str), encoding="utf-8")
            (case_dir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str), encoding="utf-8")

            # Build STEP + SW
            print(f"  [{case['id']}] Building STEP+SW...")
            ok = build_step_and_sw(case_dir)
            result["ok"] = ok
            if ok:
                result["stages"].append("step+sw")
                step = case_dir / "output.step"
                sw = case_dir / "output.SLDPRT"
                result["step_bytes"] = step.stat().st_size if step.exists() else 0
                result["sw_bytes"] = sw.stat().st_size if sw.exists() else 0

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        (case_dir / "error.txt").write_text(traceback.format_exc())

    result["elapsed_s"] = round(time.time() - t0, 1)

    stages_str = " → ".join(result["stages"])
    status = "OK" if result["ok"] else "FAIL"
    print(f"       {status} | {stages_str} | {result['elapsed_s']}s")
    if result.get("error"):
        print(f"       {result['error'][:200]}")
    return result


if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"  SeekFlow 全自动 Text-to-SolidWorks Pipeline")
    print(f"  特性: AutoFixer + RepairAgent + 零手动修正")
    print(f"{'='*70}\n")

    results = []
    for i, case in enumerate(CASES):
        print(f"[{i+1}/{len(CASES)}] {case['name']}")
        r = run_case(case)
        results.append(r)
        print()

    # Summary
    passed = sum(1 for r in results if r["ok"])
    sw_count = sum(1 for r in results if r.get("sw_bytes", 0) > 0)
    print(f"{'='*70}")
    print(f"  Total: {len(results)} | STEP+SW: {sw_count} | Validated: {passed}")
    for r in results:
        step_sz = r.get("step_bytes", 0)
        sw_sz = r.get("sw_bytes", 0)
        st = f"STEP={step_sz//1024}KB" if step_sz else "       "
        sw = f"SW={sw_sz//1024}KB" if sw_sz else "     "
        print(f"  [{st}] [{sw}] {r['name']}  {'OK' if r['ok'] else r.get('error','FAIL')[:60]}")
    print(f"{'='*70}")

    (OUTPUT_DIR / "auto_report.json").write_text(
        json.dumps({"total": len(results), "passed": passed, "sw_count": sw_count, "results": results},
                   indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
