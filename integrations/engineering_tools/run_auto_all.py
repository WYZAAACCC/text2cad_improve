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
            if op_name == "cut_rim_slot_pattern":
                lines.append(
                    '    EXAMPLE: {"count":4,"slot_depth_mm":3.0,'
                    '"slot_profile":{"kind":"symmetric_station_profile",'
                    '"stations":[{"depth_mm":0.0,"half_width_mm":2.0},'
                    '{"depth_mm":3.0,"half_width_mm":2.0}]}}'
                )
                lines.append(
                    "    NOTE: slot_profile is an OBJECT with kind and stations. "
                    "NOT a list! stations is a list of {depth_mm, half_width_mm} objects."
                )
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
    # ═══ 案例1: 复杂多级法兰 — 测试 axisymmetric 极限 ═══
    {
        "id": "complex_flange",
        "name": "多级法兰 Multi-Stage Flange",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a complex multi-stage industrial flange with the following features, all modeled as one axisymmetric solid:\n"
            "1. Base flange disc: outer diameter 200mm, thickness 20mm, with profile starting at z=0.\n"
            "2. Central hub boss rising from the disc: outer diameter 80mm, height 35mm above the disc (z=20 to z=55).\n"
            "3. Center bore through the entire part: diameter 40mm, through_all=true.\n"
            "4. An annular groove on the front face of the flange disc: inner_dia_mm=120, outer_dia_mm=140, depth_mm=4, side='front'.\n"
            "5. A circular bolt hole pattern on the flange: 8 holes, diameter 10mm each, on PCD (pitch circle diameter) 160mm.\n"
            "6. A second circular hole pattern on the hub top face: 4 holes, diameter 6mm each, on PCD 60mm.\n"
            "7. Apply a 2mm chamfer on all external edges.\n"
            "Use revolve_profile with properly sequenced profile_stations (each station is a vertical segment from bottom to top). "
            "The profile must trace: base disc outer wall (r=100, z=0 to 20), hub outer wall (r=40, z=20 to 55), "
            "then step down to bore (r=20, z=55 to 56). r_mm is RADIUS (half of diameter). "
            "z_rear_mm of each station MUST equal z_front_mm of the next station.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    # ═══ 案例2: 多级阶梯轴带环槽 — 测试 axisymmetric 多特征组合 ═══
    {
        "id": "complex_shaft",
        "name": "多级阶梯轴 Multi-Step Shaft",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a complex multi-section stepped shaft with the following features from bottom (z=0) to top:\n"
            "Section 1: diameter 80mm (r_mm=40), height 30mm (z=0 to 30).\n"
            "Section 2: diameter 60mm (r_mm=30), height 25mm (z=30 to 55).\n"
            "Section 3: diameter 45mm (r_mm=22.5), height 20mm (z=55 to 75).\n"
            "Section 4: diameter 30mm (r_mm=15), height 35mm (z=75 to 110).\n"
            "Section 5: diameter 20mm (r_mm=10), height 20mm (z=110 to 130).\n"
            "Add a center bore of diameter 12mm through the entire shaft (through_all=true).\n"
            "Add an annular groove on section 3: side='front', inner_dia_mm=28, outer_dia_mm=38, depth_mm=3.\n"
            "Add a rim slot pattern on section 1 outer rim: count=6, slot_depth_mm=4, with symmetric_station_profile: "
            "stations=[{depth_mm:0, half_width_mm:3}, {depth_mm:4, half_width_mm:3}].\n"
            "Apply 1.5mm chamfer on all external edges.\n"
            "Use revolve_profile with 5 profile_stations. Each station describes one vertical segment. "
            "z_rear_mm of station N MUST equal z_front_mm of station N+1.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    # ═══ 案例3: 复杂安装底板 — 测试 sketch_extrude 极限 ═══
    {
        "id": "complex_baseplate",
        "name": "复杂安装底板 Complex Mounting Plate",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "Create a complex mounting base plate with multiple machined features:\n"
            "1. Main plate: extrude_rectangle width_mm=200 height_mm=150 depth_mm=20 centered=true.\n"
            "2. Four corner mounting holes (M8 clearance): cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 "
            "spacing_x_mm=170 spacing_y_mm=120, through_all=true.\n"
            "3. A large central rectangular pocket: cut_rectangular_pocket width_mm=120 height_mm=80 depth_mm=8 centered=true.\n"
            "4. Two additional M6 threaded holes on the left side: use two cut_hole operations with diameter_mm=6.8, "
            "position_mm=[-70, 30] and position_mm=[-70, -30], through_all=true.\n"
            "5. A rectangular boss on the right side: add_rectangular_boss width_mm=40 height_mm=30 depth_mm=10 "
            "position_mm=[70, 0, 10] centered=true.\n"
            "6. A reinforcing rib across the center: add_rib thickness_mm=6 height_mm=15 length_mm=120 position_mm=[0, 0, 10].\n"
            "7. Apply a 2mm fillet on all external edges: apply_safe_fillet radius_mm=2 target=all_external_edges.\n"
            "Only ONE base_solid node. Cut holes BEFORE pocket, and add boss and rib in boss_rib phase.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    # ═══ 案例4: 加强筋角撑 — 测试多特征组合 ═══
    {
        "id": "complex_bracket",
        "name": "加强筋角撑 Reinforced Angle Bracket",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "Create a heavily reinforced L-shaped angle bracket:\n"
            "1. Vertical wall: extrude_rectangle width_mm=100 height_mm=80 depth_mm=12 centered=true (the main base_solid).\n"
            "2. Horizontal base flange: add_rectangular_boss width_mm=100 height_mm=60 depth_mm=12 "
            "position_mm=[0, -40, 0] plane=YZ centered=false.\n"
            "3. Left triangular gusset rib: add_rib thickness_mm=8 height_mm=35 length_mm=50 position_mm=[-40, 0, 6].\n"
            "4. Right triangular gusset rib: add_rib thickness_mm=8 height_mm=35 length_mm=50 position_mm=[40, 0, 6].\n"
            "5. Four mounting holes in the base flange: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 "
            "spacing_x_mm=70 spacing_y_mm=40.\n"
            "6. Two alignment holes in the vertical wall: cut_hole diameter_mm=6 "
            "position_mm=[-30, 40] and position_mm=[30, 40], through_all=true.\n"
            "7. Apply 3mm fillet on all edges: apply_safe_fillet radius_mm=3 target=all_external_edges.\n"
            "Only ONE base_solid (extrude_rectangle). All other features modify it.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    # ═══ 案例5: 齿轮毛坯带减重孔 — 测试 axisymmetric 多 pattern ═══
    {
        "id": "complex_gear_blank",
        "name": "齿轮毛坯带减重孔 Gear Blank with Lightening",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a gear blank with lightening features:\n"
            "1. Main gear body: outer diameter 120mm (r_mm=60), face width 25mm (z=0 to 25).\n"
            "2. Hub on one side: diameter 50mm (r_mm=25), extending 15mm above (z=25 to 40).\n"
            "3. Center bore: diameter 20mm (r_mm=10), through_all=true.\n"
            "4. Six lightening holes on PCD 90mm: cut_circular_hole_pattern count=6 hole_dia_mm=15 pcd_mm=90 through_all=true.\n"
            "5. Four bolt holes on the hub PCD 38mm: cut_circular_hole_pattern count=4 hole_dia_mm=6 pcd_mm=38 through_all=true.\n"
            "6. Annular groove on the rear face: cut_annular_groove side='rear' inner_dia_mm=80 outer_dia_mm=100 depth_mm=5.\n"
            "7. Apply 1mm chamfer on external edges.\n"
            "Use revolve_profile with sequential profile_stations: first station for main body outer wall, "
            "second for hub outer wall. r_mm=RADIUS not diameter.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    # ═══ 案例6: 变高度鳍片散热器 — 测试大量重复特征 ═══
    {
        "id": "complex_heatsink",
        "name": "变高度鳍片散热器 Variable-Fin Heatsink",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "Create a heatsink with variable-height fins and a slotted base:\n"
            "1. Base plate: extrude_rectangle width_mm=120 height_mm=80 depth_mm=8 centered=true.\n"
            "2. Center fin (tallest): add_rectangular_boss width_mm=3 height_mm=40 depth_mm=80 "
            "position_mm=[0, 0, 4] plane=XY centered=true.\n"
            "3. Two mid-height fins: add_rectangular_boss width_mm=3 height_mm=30 depth_mm=80 "
            "position_mm=[-25, 0, 4] and position_mm=[25, 0, 4] plane=XY centered=true.\n"
            "4. Two short outer fins: add_rectangular_boss width_mm=3 height_mm=20 depth_mm=80 "
            "position_mm=[-50, 0, 4] and position_mm=[50, 0, 4] plane=XY centered=true.\n"
            "5. Two mounting slots in the base: cut_rectangular_pocket width_mm=10 height_mm=5 depth_mm=8 "
            "centered=true, one at position_mm=[-50, -30, 0] and another at [50, -30, 0].\n"
            "6. Apply 0.5mm fillet on all fin edges: apply_safe_fillet radius_mm=0.5 target=all_external_edges.\n"
            "Only ONE base_solid (extrude_rectangle).\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
    },
    # ═══ 案例7: 三组件装配 — 测试 composition 极限 ═══
    {
        "id": "complex_assembly",
        "name": "三组件装配 Three-Component Assembly",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "prompt": (
            "Create an assembly of three components united into one solid:\n\n"
            "Component A 'flange' (axisymmetric): a flange with outer diameter 150mm (r_mm=75), "
            "thickness 18mm (z=0 to 18), center bore diameter 50mm, and 6 bolt holes on PCD 120mm "
            "with hole_dia_mm=10. Use revolve_profile with proper sequential profile_stations.\n\n"
            "Component B 'boss' (axisymmetric): a cylindrical boss with outer diameter 60mm (r_mm=30), "
            "height 40mm (z=18 to 58), and a center bore diameter 30mm matching the flange bore. "
            "Use revolve_profile.\n\n"
            "Component C 'rib_plate' (sketch_extrude): a rectangular reinforcing plate "
            "width_mm=150 height_mm=10 depth_mm=40 using extrude_rectangle, positioned to brace "
            "between the flange and boss.\n\n"
            "Component '__assembly__' (composition): use boolean_union to merge all three component "
            "outputs. Each boolean_union input must reference {component: <id>, output: body}.\n"
            "Use multiple boolean_union nodes if needed: first union(A, B), then union(result, C).\n"
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
