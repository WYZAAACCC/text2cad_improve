"""全链路 Text-to-SolidWorks 批量生成脚本。

每条链路: Text → DeepSeek LLM → RawGcadDocument → Validation → CadQuery STEP → SolidWorks SLDPRT
LLM 负责生成 RawGcadDocument，系统负责校验、编译、导出。
"""
import json, os, sys, time, subprocess, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA_PYTHON = r"E:\auto_detection_process\.conda\python.exe"
OUTPUT_DIR = Path(r"E:\auto_detection_process\demo_output_v5")

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt builder — 为 LLM 提供精确的 op 名和参数字段名
# ═══════════════════════════════════════════════════════════════════════════════

def build_dialect_cheatsheet(dialect_ids: list[str]) -> str:
    """构建精确的 op 名和参数字段名速查表，防止 LLM 幻觉。"""
    lines = []
    for did in dialect_ids:
        d = REG.get(did)
        if d is None:
            continue
        lines.append(f"=== Dialect: {did} (version={d.version}) ===")
        lines.append(f"Phase order: {' → '.join(d.phase_order)}")
        lines.append("")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            required_list = ps.get("required", [])

            param_strs = []
            for pname, pinfo in props.items():
                req = "REQUIRED" if pname in required_list else "optional"
                ptype = pinfo.get("type", "?")
                desc = pinfo.get("description", "")
                ref = pinfo.get("$ref", "")
                if ref:
                    ref_name = ref.split("/")[-1]
                    nested = ps.get("$defs", {}).get(ref_name, {})
                    nested_props = nested.get("properties", {})
                    fields = []
                    for nk, nv in nested_props.items():
                        ntype = nv.get("type", "?")
                        ndesc = nv.get("description", "")
                        fields.append(f"{nk}:{ntype}")
                    param_strs.append(f"{pname}=[{req}] list of {{{', '.join(fields)}}}")
                elif "enum" in pinfo:
                    param_strs.append(f"{pname}={pinfo['enum']} [{req}]")
                else:
                    param_strs.append(f"{pname}:{ptype} [{req}] {desc[:50]}")

            lines.append(
                f"  op='{op_name}' v='{spec.op_version}' phase='{spec.phase}' "
                f"inputs={list(spec.input_types)} outputs={list(spec.output_types)}"
            )
            lines.append(f"    params: {' | '.join(param_strs)}")
        lines.append("")
    return "\n".join(lines)


def call_deepseek(system: str, user: str, max_retries: int = 3) -> dict:
    """调用 DeepSeek, 带重试和后处理。"""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")

    raw_schema = RawGcadDocument.model_json_schema()
    tool_schema = to_deepseek_strict_schema(raw_schema)
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": tool_schema}}]

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "gcad"}},
                timeout=120,
                extra_body={"thinking": {"type": "disabled"}},
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                if attempt < max_retries - 1:
                    user += "\n\nERROR: You must call the gcad tool. Do not output text."
                    continue
                raise RuntimeError("No tool call returned")

            args = json.loads(msg.tool_calls[0].function.arguments)
            # 修复 null fields
            if args.get("llm_validation_hints") is None:
                args["llm_validation_hints"] = {}

            # 后处理: 修复 output name
            for node in args.get("nodes", []):
                for o in node.get("outputs", []):
                    if o.get("name") == "solid" and o.get("type") == "solid":
                        o["name"] = "body"
                    if o.get("name") == "frame" and o.get("type") == "frame":
                        o["name"] = "outer_frame"

            # 后处理: 修复常见参数字段名/值错误
            for node in args.get("nodes", []):
                op = node.get("op", "")
                params = node.get("params", {})

                # apply_safe_fillet/apply_safe_chamfer target 值修正
                if op in ("apply_safe_fillet", "apply_safe_chamfer"):
                    tgt = params.get("target", "")
                    if tgt in ("all_external", "all", "external", "all_edges"):
                        params["target"] = "all_external_edges"

                # revolve_profile 和 cut_center_bore 缺少 axis 默认值
                if op in ("revolve_profile", "cut_center_bore", "cut_circular_hole_pattern"):
                    if "axis" not in params:
                        params["axis"] = "Z"

                # extrude_rectangle 缺少 centered/direction 默认值
                if op == "extrude_rectangle":
                    if "centered" not in params:
                        params["centered"] = True

                # boolean ops 清理错误参数
                if op in ("boolean_union", "boolean_cut"):
                    for bad_key in ("clean_after", "merge_result", "keep_tool"):
                        params.pop(bad_key, None)

            # 后处理: 修复 root_node 引用 (LLM 有时用错误的 node id)
            node_ids = {n["id"] for n in args.get("nodes", [])}
            for comp in args.get("components", []):
                rn = comp.get("root_node", "")
                if rn and rn not in node_ids:
                    # 尝试找最后一个 node 作为 root
                    comp_nodes = [n for n in args.get("nodes", []) if n.get("component") == comp.get("id")]
                    if comp_nodes:
                        comp["root_node"] = comp_nodes[-1]["id"]

            # 后处理: 修复 dialect 名和 qualified op 名
            known_dialects = set(REG.list_ids())
            for node in args.get("nodes", []):
                op = node.get("op", "")
                if "." in op:
                    node["op"] = op.split(".")[-1]
                if node.get("dialect", "") not in known_dialects:
                    # 尝试从 op 推断 dialect
                    for did in known_dialects:
                        d = REG.get(did)
                        if d:
                            try:
                                d.get_op_spec(node["op"], node.get("op_version", "1.0.0"))
                                node["dialect"] = did
                                break
                            except Exception:
                                pass

            for comp in args.get("components", []):
                if comp.get("owner_dialect", "") not in known_dialects:
                    comp["owner_dialect"] = known_dialects.pop() if known_dialects else "axisymmetric"
                    known_dialects.add(comp["owner_dialect"])

            for sd in args.get("selected_dialects", []):
                if sd.get("dialect", "") not in known_dialects:
                    sd["dialect"] = "axisymmetric"
                d = REG.get(sd["dialect"])
                if d and sd.get("version") != d.version:
                    sd["version"] = d.version

            return args

        except Exception as e:
            err = str(e)
            if "invalid_request_error" in err and attempt < max_retries - 1:
                user += "\n\nERROR from validator: " + err[:200] + "\nPlease fix the JSON structure and retry."
                continue
            raise


# ═══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ═══════════════════════════════════════════════════════════════════════════════

TEST_CASES = [
    {
        "id": "stage1_stepped_shaft",
        "name": "阶梯轴 Stepped Shaft",
        "dialects": ["axisymmetric"],
        "ops": ["revolve_profile", "apply_safe_chamfer"],
        "prompt": (
            "Create a stepped shaft with three cylindrical sections along Z axis:\n"
            "- Bottom section: diameter 60mm, height 20mm\n"
            "- Middle section: diameter 40mm, height 30mm\n"
            "- Top section: diameter 25mm, height 25mm\n"
            "- Apply 2mm chamfer on all external edges\n"
            "Units mm. Reference geometry only. Not for manufacturing.\n\n"
            "Use revolve_profile to define the stepped profile. Each profile_stations entry "
            "represents one cylindrical section. The r_mm value is the RADIUS (half of diameter). "
            "z_front_mm is the start Z, z_rear_mm is the end Z of each section.\n"
            "For a stepped shaft going UP: bottom section Z=0 to 20, middle Z=20 to 50, top Z=50 to 75."
        ),
        "expected_outcome": "should_build",
    },
    {
        "id": "stage1_hole_plate",
        "name": "带孔矩形板 Plate with Holes",
        "dialects": ["sketch_extrude"],
        "ops": ["extrude_rectangle", "cut_hole_pattern_linear", "cut_rectangular_pocket", "apply_safe_fillet"],
        "prompt": (
            "Create a rectangular base plate 120mm wide (X), 80mm tall (Y), 12mm thick (Z).\n"
            "- 4 mounting holes of diameter 8mm at corners, 15mm from each edge\n"
            "  (use cut_hole_pattern_linear with count_x=2, count_y=2, spacing_x=90, spacing_y=50)\n"
            "- Central rectangular pocket 50mm wide, 30mm tall, 4mm deep\n"
            "- Apply 1mm fillet on all external edges\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        "expected_outcome": "should_build",
    },
    {
        "id": "stage1_angle_bracket",
        "name": "直角支架 Angle Bracket",
        "dialects": ["sketch_extrude"],
        "ops": ["extrude_rectangle", "cut_hole", "add_rib", "apply_safe_fillet"],
        "prompt": (
            "Create an L-shaped mounting bracket as a single solid body:\n"
            "- Base plate: extrude_rectangle width=80, height=50, depth=8 (on XY plane)\n"
            "- Vertical plate: extrude_rectangle width=8, height=40, depth=80 (on YZ plane)\n"
            "  position the vertical plate at one edge of the base\n"
            "- Add a triangular rib: add_rib thickness=6, height=20, length=40 at the inner corner\n"
            "- Add two 6mm mounting holes in the base plate\n"
            "- Apply 1mm fillet on all external edges\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        "expected_outcome": "should_build",
    },
    {
        "id": "stage2_spur_gear",
        "name": "渐开线齿轮 Spur Gear",
        "dialects": [],
        "ops": [],
        "prompt": "Create involute spur gear: 20 teeth, module 2mm, pressure angle 20deg, face width 15mm, bore 10mm.",
        "expected_outcome": "should_build",
        "route": "deterministic_primitive",
        "primitive": "involute_spur_gear",
    },
    {
        "id": "stage2_finned_heatsink",
        "name": "鳍片散热器 Finned Heatsink",
        "dialects": ["sketch_extrude"],
        "ops": ["extrude_rectangle", "add_rectangular_boss", "apply_safe_fillet"],
        "prompt": (
            "Create a finned heatsink:\n"
            "- Base plate: extrude_rectangle width=100, height=60, depth=5 (on XY plane)\n"
            "- Add 7 rectangular fins on top: add_rectangular_boss width=2, height=25, depth=60\n"
            "  (representing each fin — call add_rectangular_boss 7 times with different position_mm)\n"
            "- Apply 0.5mm fillet on all external edges\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        "expected_outcome": "should_build",
    },
    {
        "id": "stage3_l_bracket_profile",
        "name": "L形支架轮廓 Sketch Profile Bracket",
        "dialects": ["sketch_profile"],
        "ops": ["create_2d_sketch", "add_polyline", "close_profile", "extrude_profile"],
        "prompt": (
            "Create an L-bracket using sketch_profile dialect:\n"
            "- create_2d_sketch on XY plane\n"
            "- add_polyline with points forming an L-shape:\n"
            "  [x=0,y=0], [x=80,y=0], [x=80,y=8], [x=50,y=8], [x=50,y=40], [x=42,y=40], [x=42,y=8], [x=0,y=8]\n"
            "- close_profile\n"
            "- extrude_profile depth=50 direction=+\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        "expected_outcome": "should_build",
    },
    {
        "id": "stage4_hub_plate_assembly",
        "name": "轴套底板组合 Hub+Plate Assembly",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "ops": ["revolve_profile", "cut_center_bore", "extrude_rectangle", "boolean_union"],
        "prompt": (
            "Create assembly of a cylindrical hub and base plate:\n"
            "Component 1 'hub_body' (axisymmetric): revolve_profile to create hub OD=50mm, "
            "then cut_center_bore diameter=25mm. Height 40mm.\n"
            "Component 2 'base_plate' (sketch_extrude): extrude_rectangle width=100, height=80, depth=10.\n"
            "Assembly '__assembly__' (composition): boolean_union the two component outputs.\n"
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        "expected_outcome": "should_build",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

def run_case(case: dict) -> dict:
    case_dir = OUTPUT_DIR / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    result = {"id": case["id"], "name": case["name"], "ok": False, "stages": [], "files": [], "elapsed_s": -1}
    t0 = time.time()

    try:
        # ── Step 1: 保存 prompt ──
        (case_dir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        result["stages"].append("prompt_saved")

        # ── Step 2: 齿轮走 deterministic primitive ──
        if case.get("route") == "deterministic_primitive":
            result["route"] = "deterministic_primitive"
            ok = build_gear_primitive(case, case_dir)
            result["ok"] = ok
            result["stages"].append("primitive_step")
            if ok and (case_dir / "output.step").exists():
                result["files"].extend(["output.step", "output.metadata.json"])
                import_to_sw(case_dir, result)
        else:
            result["route"] = "generative_cad_ir"

            # ── Step 3: LLM 生成 ──
            cheatsheet = build_dialect_cheatsheet(case["dialects"])
            user_msg = f"""TASK: {case['prompt']}

{cheatsheet}

CRITICAL RULES:
- Use ONLY the EXACT op names and EXACT parameter field names listed above.
- Do NOT invent new field names. Use EXACTLY the names shown (e.g. "profile_stations" not "profile", "width_mm" not "width").
- Output name: ALWAYS use "name":"body" for solid outputs, "name":"outer_frame" for frame outputs. NEVER use "name":"solid".
- selected_dialects version must match the dialect version listed above.
- ALL 7 safety flags must be explicitly true.
- constraints.require_step_file, require_metadata_sidecar, require_closed_solid must all be true.
- trust_level must be "reference_geometry".
- llm_validation_hints: {{}}
"""

            print(f"  [{case['id']}] Calling DeepSeek...")
            args = call_deepseek(LEVEL2_AUTHORING_SYSTEM_PROMPT, user_msg)
            (case_dir / "llm_raw_output.json").write_text(
                json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")
            result["stages"].append("llm_call")

            # ── Step 4: 校验 ──
            try:
                raw_doc = RawGcadDocument.model_validate(args)
            except Exception as e:
                result["error"] = f"Pydantic: {e}"
                (case_dir / "error.txt").write_text(str(e))
                return result

            (case_dir / "raw_gcad_document.json").write_text(
                json.dumps(raw_doc.model_dump(), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")

            canonical, report, bundle = validate_and_canonicalize_with_bundle(raw_doc)
            (case_dir / "validation_report.json").write_text(
                json.dumps(report.model_dump() if report else {}, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")

            if canonical is None or not (report and report.ok):
                issues = report.issues if report else []
                result["error"] = "Validation: " + "; ".join(
                    f"[{i.code}] {i.message[:100]}" for i in issues[:5]
                )
                (case_dir / "error.txt").write_text(result["error"])
                return result

            result["stages"].append("validation_passed")
            (case_dir / "canonical_gcad.json").write_text(
                json.dumps(canonical.model_dump(), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
            (case_dir / "validation_bundle.json").write_text(
                json.dumps(bundle.to_metadata_dict(), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")

            # ── Step 5: Build STEP (conda Python) ──
            print(f"  [{case['id']}] Building STEP...")
            ok = build_step_conda(case_dir)
            result["ok"] = ok
            if ok:
                result["stages"].append("step_built")
                result["files"].extend(["output.step", "output.metadata.json"])

                # ── Step 6: SolidWorks import ──
                import_to_sw(case_dir, result)

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        (case_dir / "error.txt").write_text(traceback.format_exc())

    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def build_step_conda(case_dir: Path) -> bool:
    """使用 conda Python 构建 STEP。"""
    script = f'''
import sys
sys.path.insert(0, r"{Path(__file__).parent / 'src'}")

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
    for w in (result.warnings or []):
        print(f"WARNING: {{w}}")
    sys.exit(1)
print("BUILD_OK")
'''
    script_path = case_dir / "_build_step.py"
    script_path.write_text(script, encoding="utf-8")

    try:
        r = subprocess.run(
            [CONDA_PYTHON, str(script_path)],
            capture_output=True, text=True, timeout=300,
            cwd=str(case_dir),
        )
        ok = r.returncode == 0 and (case_dir / "output.step").exists()
        (case_dir / "_build_log.txt").write_text(
            f"RC={r.returncode}\nSTDOUT={r.stdout[-1000:]}\nSTDERR={r.stderr[-1000:]}")
        return ok
    except subprocess.TimeoutExpired:
        (case_dir / "_build_log.txt").write_text("TIMEOUT")
        return False


def build_gear_primitive(case: dict, case_dir: Path) -> bool:
    """构建渐开线齿轮。"""
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir

    config = EngineeringToolsConfig(workspace_root=case_dir, allow_overwrite=True)

    spec = CADPartSpec.model_validate({
        "name": case["name"],
        "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{
            "id": "gear1", "type": "primitive",
            "primitive_name": "involute_spur_gear",
            "parameters": {
                "module_mm": 2.0, "teeth": 20,
                "pressure_angle_deg": 20.0, "face_width_mm": 15.0,
                "bore_dia_mm": 10.0, "quality_grade": "industrial_brep",
            },
        }],
        "validation": {"expected_body_count": 1, "tolerance_mm": 0.5},
    })
    (case_dir / "cad_part_spec.json").write_text(
        json.dumps(spec.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")

    out_step = case_dir / "output.step"
    script = f'''
import sys, json
sys.path.insert(0, r"{Path(__file__).parent / 'src'}")

from pathlib import Path
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir

spec_json = json.loads(Path(r"{(case_dir / 'cad_part_spec.json').as_posix()}").read_text())
spec = CADPartSpec.model_validate(spec_json)
config = EngineeringToolsConfig(workspace_root=Path(r"{case_dir.as_posix()}"), allow_overwrite=True)
result = build_cadquery_from_cad_ir(spec, config, Path(r"{(case_dir / 'output.step').as_posix()}"))
print(f"BUILD_OK: {{result.get('ok')}}")
if not result.get('ok'):
    print(f"ERROR: {{result.get('error')}}")
'''
    script_path = case_dir / "_build_gear.py"
    script_path.write_text(script, encoding="utf-8")

    try:
        r = subprocess.run(
            [CONDA_PYTHON, str(script_path)],
            capture_output=True, text=True, timeout=300,
            cwd=str(case_dir),
        )
        ok = r.returncode == 0 and (case_dir / "output.step").exists()
        (case_dir / "_build_log.txt").write_text(
            f"RC={r.returncode}\nSTDOUT={r.stdout[-1000:]}\nSTDERR={r.stderr[-1000:]}")
        return ok
    except Exception as e:
        (case_dir / "_build_log.txt").write_text(str(e))
        return False


def import_to_sw(case_dir: Path, result: dict) -> None:
    """导入 STEP 到 SolidWorks。"""
    step_path = case_dir / "output.step"
    sldprt_path = case_dir / "output.SLDPRT"
    if not step_path.exists():
        return

    script = f'''
import sys
sys.path.insert(0, r"{Path(__file__).parent / 'src'}")

from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

step = Path(r"{step_path.as_posix()}")
sldprt = Path(r"{sldprt_path.as_posix()}")
template = Path(r"C:\\ProgramData\\SOLIDWORKS\\SOLIDWORKS 2025\\templates\\gb_part.prtdot")
if not template.exists():
    template = None

client = SolidWorksClient(visible=False, part_template=template).connect()
ok = client.import_step_as_part(step, sldprt)
client.close()
if ok and sldprt.exists():
    print(f"SW_OK: {{sldprt.stat().st_size}} bytes")
else:
    print(f"SW_FAIL: ok={{ok}}, exists={{sldprt.exists()}}")
'''
    script_path = case_dir / "_import_sw.py"
    script_path.write_text(script, encoding="utf-8")

    try:
        r = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0 and sldprt_path.exists():
            result["stages"].append("solidworks_imported")
            result["files"].append("output.SLDPRT")
        (case_dir / "_sw_log.txt").write_text(
            f"RC={r.returncode}\n{r.stdout}\n{r.stderr}")
    except Exception as e:
        (case_dir / "_sw_log.txt").write_text(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"  SeekFlow 全链路 Text-to-SolidWorks 批量生成")
    print(f"  输出目录: {OUTPUT_DIR}")
    print(f"  Conda Python: {CONDA_PYTHON}")
    print(f"{'='*70}\n")

    results = []
    for i, case in enumerate(TEST_CASES):
        print(f"[{i+1}/{len(TEST_CASES)}] {case['name']} ({case['id']})")
        r = run_case(case)
        results.append(r)
        status = "OK" if r["ok"] else "FAIL"
        stages = " → ".join(r["stages"])
        print(f"      结果: {status} | 阶段: {stages} | {r['elapsed_s']}s")
        if r.get("error"):
            print(f"      错误: {r['error'][:200]}")
        print()

    # 汇总
    passed = sum(1 for r in results if r["ok"])
    sw_count = sum(1 for r in results if "solidworks_imported" in r.get("stages", []))
    step_count = sum(1 for r in results if "output.step" in r.get("files", []))

    print(f"{'='*70}")
    print(f"  总计: {len(results)} | 校验通过: {passed} | STEP: {step_count} | SolidWorks: {sw_count}")
    for r in results:
        has_sw = "SW" if "solidworks_imported" in r.get("stages", []) else "  "
        has_step = "STEP" if "output.step" in r.get("files", []) else "    "
        print(f"  [{has_step}] [{has_sw}] {r['name']}")
    print(f"{'='*70}")

    # 保存报告
    report = {
        "output_dir": str(OUTPUT_DIR),
        "total": len(results),
        "passed": passed,
        "step_count": step_count,
        "solidworks_count": sw_count,
        "results": results,
    }
    (OUTPUT_DIR / "batch_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    print(f"  报告: {OUTPUT_DIR / 'batch_report.json'}")
