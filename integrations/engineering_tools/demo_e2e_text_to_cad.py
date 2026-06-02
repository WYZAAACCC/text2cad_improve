"""End-to-end Text-to-CAD demo: natural language → DeepSeek → RawGcadDocument → CadQuery STEP → SolidWorks.

Tests all 4 stages of the test matrix:
  Stage 1: Basic features (stepped shaft, hole plate, angle bracket)
  Stage 2: Advanced features (spur gear, finned heatsink)
  Stage 3: Complex profiles (L-bracket with sketch_profile)
  Stage 4: Composition assembly

Output: E:\\auto_detection_process\\demo_output_v5\\
"""
from __future__ import annotations

import json, os, sys, time, uuid, traceback
from dataclasses import dataclass, field
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent / "src"))

OUTPUT_DIR = Path(r"E:\auto_detection_process\demo_output_v5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEEPSEEK_API_KEY = "sk-db9a573912714fd191495d6c6db41ff7"
os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY


# ═══════════════════════════════════════════════════════════════════════════════
# Test Case Definitions
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class E2ETestCase:
    case_id: str
    stage: int
    name: str
    prompt: str
    expected_dialects: list[str] = field(default_factory=list)
    expected_ops: list[str] = field(default_factory=list)
    route: str = "generative_cad_ir"  # or deterministic_primitive
    primitive_name: str | None = None


STAGE1_CASES = [
    E2ETestCase(
        case_id="stage1_stepped_shaft",
        stage=1, name="阶梯轴 (Stepped Shaft)",
        prompt=(
            "Create a stepped shaft with three sections along the Z axis: "
            "base section diameter 60mm height 20mm, "
            "middle section diameter 40mm height 30mm, "
            "top section diameter 25mm height 25mm. "
            "Add 2mm chamfer on all external edges. "
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        expected_dialects=["axisymmetric"],
        expected_ops=["revolve_profile", "apply_safe_chamfer"],
    ),
    E2ETestCase(
        case_id="stage1_hole_plate",
        stage=1, name="带孔矩形板 (Plate with Hole Pattern)",
        prompt=(
            "Create a rectangular base plate 120mm x 80mm x 12mm. "
            "Add 4 mounting holes of diameter 8mm at the corners, "
            "positioned 15mm from each edge. "
            "Add a central rectangular pocket 50mm x 30mm x 4mm deep. "
            "Apply 1mm fillet on all external edges. "
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        expected_dialects=["sketch_extrude"],
        expected_ops=["extrude_rectangle", "cut_hole_pattern_linear", "cut_rectangular_pocket", "apply_safe_fillet"],
    ),
    E2ETestCase(
        case_id="stage1_angle_bracket",
        stage=1, name="直角支架 (Angle Bracket)",
        prompt=(
            "Create an L-shaped mounting bracket: "
            "Base plate 80mm x 50mm x 8mm. "
            "Vertical plate 80mm x 40mm x 8mm, positioned at one edge of the base, extending upward. "
            "Add a triangular reinforcing rib of thickness 6mm, height 20mm at the inner corner. "
            "Add two 6mm mounting holes in the base plate, 15mm from each side edge. "
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        expected_dialects=["sketch_extrude", "composition"],
        expected_ops=["extrude_rectangle", "cut_hole", "add_rib", "boolean_union"],
    ),
]

STAGE2_CASES = [
    E2ETestCase(
        case_id="stage2_spur_gear",
        stage=2, name="参数化齿轮 (Parametric Spur Gear)",
        prompt=(
            "Create an involute spur gear with 20 teeth, module 2mm, "
            "pressure angle 20 degrees, face width 15mm, "
            "center bore diameter 10mm. "
            "Units mm. Reference geometry only."
        ),
        expected_dialects=[],
        expected_ops=[],
        route="deterministic_primitive",
        primitive_name="involute_spur_gear",
    ),
    E2ETestCase(
        case_id="stage2_finned_heatsink",
        stage=2, name="鳍片散热器 (Finned Heatsink)",
        prompt=(
            "Create a finned heatsink: base plate 100mm x 60mm x 5mm. "
            "Add 7 parallel rectangular fins on top, each fin 2mm thick, 25mm tall, "
            "spaced 12mm apart. Apply 0.5mm fillet on all fin edges. "
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        expected_dialects=["sketch_extrude"],
        expected_ops=["extrude_rectangle", "add_rectangular_boss", "apply_safe_fillet"],
    ),
]

STAGE3_CASES = [
    E2ETestCase(
        case_id="stage3_l_bracket_profile",
        stage=3, name="L形支架轮廓 (L-Bracket via sketch_profile)",
        prompt=(
            "Create an L-bracket using a custom 2D profile: "
            "Sketch on XY plane. Draw a polyline forming an L-shape: "
            "start at (0,0), go to (80,0), then (80,8), then (50,8), "
            "then (50,40), then (42,40), then (42,8), then (0,8), close back to (0,0). "
            "Extrude the profile 50mm in the +Z direction. "
            "Add 2mm fillet on all external edges. "
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        expected_dialects=["sketch_profile"],
        expected_ops=["create_2d_sketch", "add_polyline", "close_profile", "extrude_profile"],
    ),
]

STAGE4_CASES = [
    E2ETestCase(
        case_id="stage4_hub_plate_assembly",
        stage=4, name="轴套+底板组合 (Hub + Plate Assembly)",
        prompt=(
            "Create an assembly of a cylindrical hub and a base plate: "
            "Component 1 (hub_body): an axisymmetric hub with outer diameter 50mm, "
            "inner bore 25mm, height 40mm. "
            "Component 2 (base_plate): a rectangular plate 100mm x 80mm x 10mm "
            "using sketch_extrude. "
            "Assembly: place the hub centered on the base plate, then boolean union "
            "them into one solid body. "
            "Units mm. Reference geometry only. Not for manufacturing."
        ),
        expected_dialects=["axisymmetric", "sketch_extrude", "composition"],
        expected_ops=["revolve_profile", "cut_center_bore", "extrude_rectangle", "boolean_union"],
    ),
]

ALL_CASES = STAGE1_CASES + STAGE2_CASES + STAGE3_CASES + STAGE4_CASES


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_deepseek_llm(system_prompt: str, user_prompt: str, tool_name: str, tool_schema: dict, model: str = "deepseek-v4-pro") -> dict:
    """Call DeepSeek API with strict tool calling and thinking disabled."""
    from openai import OpenAI

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/beta")

    tools = [{
        "type": "function",
        "function": {
            "name": tool_name,
            "description": "G-CAD IR generation tool",
            "strict": True,
            "parameters": tool_schema,
        },
    }]

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": tool_name}},
        timeout=120,
        extra_body={"thinking": {"type": "disabled"}},
    )

    msg = response.choices[0].message
    if not msg.tool_calls or len(msg.tool_calls) != 1:
        raise RuntimeError(f"Expected 1 tool call, got {len(msg.tool_calls) if msg.tool_calls else 0}")

    call = msg.tool_calls[0]
    args = json.loads(call.function.arguments)
    # Fix null llm_validation_hints (DeepSeek may send null for optional dict fields)
    if args.get("llm_validation_hints") is None:
        args["llm_validation_hints"] = {}
    return args


def build_llm_raw_gcad(case: E2ETestCase, case_dir: Path) -> dict:
    """Run LLM to generate RawGcadDocument, then validate and build STEP."""
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
    from seekflow_engineering_tools.generative_cad.skills.prompts import (
        LEVEL2_AUTHORING_SYSTEM_PROMPT,
    )

    reg = default_registry()

    # Build dialect catalog for selected dialects
    dialect_info = []
    for did in case.expected_dialects:
        d = reg.get(did)
        if d:
            dialect_info.append(json.dumps({
                "dialect_id": did,
                "version": d.version,
                "phase_order": list(d.phase_order),
                "operations": {
                    op_name: {
                        "phase": spec.phase,
                        "op_version": spec.op_version,
                        "input_types": spec.input_types,
                        "output_types": spec.output_types,
                        "params_schema": spec.params_model.model_json_schema() if hasattr(spec.params_model, 'model_json_schema') else {},
                    }
                    for (op_name, _), spec in d.op_specs().items()
                },
            }, indent=2))

    # Build explicit op list to prevent hallucination
    op_list_lines = []
    for did in case.expected_dialects:
        d = reg.get(did)
        if d:
            for (op_name, op_ver), spec in d.op_specs().items():
                op_list_lines.append(
                    f"  {did}.{op_name} (v{op_ver}) phase={spec.phase} "
                    f"inputs={list(spec.input_types)} outputs={list(spec.output_types)}"
                )

    user_msg = f"""USER REQUEST:
{case.prompt}

ALLOWED OPERATIONS (use ONLY these exact names — do NOT invent):
{chr(10).join(op_list_lines)}

CRITICAL RULES:
1. Use ONLY the SHORT op name (e.g. "revolve_profile", NOT "axisymmetric.revolve_profile").
2. op_version must be exactly "1.0.0" for all nodes.
3. selected_dialects version must be "0.2.0" (NOT "1.0.0").
4. phase must match exactly what's listed above for each op.
5. revolve_profile outputs TWO: [{{"name":"body","type":"solid"}}, {{"name":"outer_frame","type":"frame"}}]. All other ops output ONE: [{{"name":"body","type":"solid"}}].
6. All 7 safety flags must be explicitly true.
7. constraints require_step_file, require_metadata_sidecar, require_closed_solid must be explicitly true.
8. trust_level must be "reference_geometry". llm_validation_hints must be {{}}.
"""

    raw_schema = RawGcadDocument.model_json_schema()
    # Apply DeepSeek strict schema compiler
    from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
        to_deepseek_strict_schema,
    )
    tool_schema = to_deepseek_strict_schema(raw_schema)

    raw_args = run_deepseek_llm(
        system_prompt=LEVEL2_AUTHORING_SYSTEM_PROMPT,
        user_prompt=user_msg,
        tool_name="generate_raw_gcad_document",
        tool_schema=tool_schema,
        model="deepseek-v4-pro",
    )

    # Save raw LLM output
    (case_dir / "llm_raw_output.json").write_text(json.dumps(raw_args, indent=2, ensure_ascii=False), encoding="utf-8")

    # Post-process common LLM mistakes:
    # 1. Strip dialect prefix from op names (e.g., "axisymmetric.revolve_profile" → "revolve_profile")
    for node in raw_args.get("nodes", []):
        op = node.get("op", "")
        if "." in op:
            node["op"] = op.split(".")[-1]

    # 2. Fix selected_dialects version (should be dialect.version, not op_version)
    for sd in raw_args.get("selected_dialects", []):
        if sd.get("dialect") in case.expected_dialects:
            d = reg.get(sd["dialect"])
            if d and sd.get("version") != d.version:
                sd["version"] = d.version

    # Validate
    raw_doc = RawGcadDocument.model_validate(raw_args)
    (case_dir / "raw_gcad_document.json").write_text(json.dumps(raw_doc.model_dump(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    return raw_doc.model_dump()


def build_deterministic_primitive(case: E2ETestCase, case_dir: Path) -> dict:
    """Build via deterministic primitive path (for gears)."""
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir

    config = EngineeringToolsConfig(workspace_root=case_dir, allow_overwrite=True)

    if case.primitive_name == "involute_spur_gear":
        spec = CADPartSpec.model_validate({
            "name": case.name,
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [{
                "id": "gear1",
                "type": "primitive",
                "primitive_name": "involute_spur_gear",
                "parameters": {
                    "module_mm": 2.0, "teeth": 20,
                    "pressure_angle_deg": 20.0, "face_width_mm": 15.0,
                    "bore_dia_mm": 10.0, "quality_grade": "industrial_brep",
                },
            }],
            "validation": {"expected_body_count": 1, "tolerance_mm": 0.5},
        })
    else:
        raise ValueError(f"Unknown primitive: {case.primitive_name}")

    (case_dir / "cad_part_spec.json").write_text(json.dumps(spec.model_dump(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    out_step = case_dir / "output.step"
    result = build_cadquery_from_cad_ir(spec, config, out_step)
    (case_dir / "build_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    return result


def validate_and_canonicalize(raw_doc: dict, case_dir: Path) -> tuple:
    """Run validation pipeline and save canonical graph."""
    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize_with_bundle,
    )

    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw_doc)

    (case_dir / "validation_report.json").write_text(
        json.dumps(report.model_dump() if report else {}, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    if canonical:
        (case_dir / "canonical_gcad.json").write_text(
            json.dumps(canonical.model_dump(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        (case_dir / "validation_bundle.json").write_text(
            json.dumps(bundle.to_metadata_dict() if bundle else {}, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    return canonical, report, bundle


def build_cadquery_step(case_dir: Path) -> dict:
    """Build STEP file from canonical graph using the fixed harness."""
    import subprocess, sys

    graph_files = sorted(case_dir.glob("canonical_gcad.json"))
    if not graph_files:
        return {"ok": False, "error": "No canonical graph found"}

    graph_path = graph_files[0]
    validation_seed = case_dir / "validation_bundle.json"
    step_path = case_dir / "output.step"
    meta_path = case_dir / "output.metadata.json"

    script = f'''
import json, sys
from pathlib import Path
sys.path.insert(0, r"{Path(__file__).parent / 'src'}")

from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"{graph_path.as_posix()}",
    validation_seed_json=r"{validation_seed.as_posix()}",
    out_step=r"{step_path.as_posix()}",
    metadata_path=r"{meta_path.as_posix()}",
)
if not result.ok:
    print(f"BUILD FAILED: {{result.error}}", file=sys.stderr)
    sys.exit(1)
print(f"STEP: {{result.step_path}}")
print(f"Metadata: {{result.metadata_path}}")
'''
    script_path = case_dir / "run_harness.py"
    script_path.write_text(script, encoding="utf-8")

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=300,
            cwd=str(case_dir),
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:],
            "step_exists": step_path.exists(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout after 300s"}


def import_to_solidworks(step_path: Path, case_dir: Path) -> dict:
    """Import STEP file into SolidWorks as native SLDPRT."""
    try:
        from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

        template = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
        if not template.exists():
            template = None

        sldprt_path = case_dir / "output.SLDPRT"
        client = SolidWorksClient(visible=False, part_template=template).connect()
        ok = client.import_step_as_part(step_path, sldprt_path)
        client.close()

        return {
            "ok": ok,
            "sldprt_path": str(sldprt_path) if ok else None,
            "sldprt_exists": sldprt_path.exists() if ok else False,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "note": "SolidWorks may not be available"}


# ═══════════════════════════════════════════════════════════════════════════════
# Main Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_case(case: E2ETestCase) -> dict:
    """Run a single E2E test case through the full pipeline."""
    case_dir = OUTPUT_DIR / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "case_id": case.case_id,
        "name": case.name,
        "stage": case.stage,
        "ok": False,
        "error": None,
        "stages_completed": [],
        "files": [],
        "elapsed_s": -1,
    }

    t0 = time.time()

    try:
        # Save prompt
        (case_dir / "prompt.txt").write_text(case.prompt, encoding="utf-8")
        result["files"].append("prompt.txt")

        # ── Route selection (deterministic_primitive vs generative_cad_ir) ──
        if case.route == "deterministic_primitive":
            result["route"] = "deterministic_primitive"
            build_result = build_deterministic_primitive(case, case_dir)
            result["ok"] = build_result.get("ok", False)
            result["stages_completed"].append("primitive_build")
        else:
            result["route"] = "generative_cad_ir"

            # 1. LLM → RawGcadDocument
            raw_doc = build_llm_raw_gcad(case, case_dir)
            result["stages_completed"].append("llm_raw_generation")

            # 2. Validate + Canonicalize
            canonical, report, bundle = validate_and_canonicalize(raw_doc, case_dir)
            if canonical is None or not (report and report.ok):
                result["error"] = f"Validation failed: {[i.message for i in (report.issues if report else [])]}"
                result["validation_report"] = report.model_dump() if report else {}
                return result
            result["stages_completed"].append("validate_and_canonicalize")

            # 3. Build STEP via CadQuery
            build_result = build_cadquery_step(case_dir)
            result["ok"] = build_result.get("ok", False)
            result["cadquery_build"] = build_result
            if result["ok"]:
                result["stages_completed"].append("cadquery_step_build")
                result["files"].extend(["output.step", "output.metadata.json"])

            # 4. Import to SolidWorks (if available)
            step_path = case_dir / "output.step"
            if step_path.exists():
                sw_result = import_to_solidworks(step_path, case_dir)
                result["solidworks_import"] = sw_result
                if sw_result.get("ok"):
                    result["stages_completed"].append("solidworks_import")
                    result["files"].append("output.SLDPRT")

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()

    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def run_all_cases() -> dict:
    """Run all test cases and generate report."""
    results = []
    total = len(ALL_CASES)

    print(f"\n{'='*70}")
    print(f"  SeekFlow Text-to-CAD End-to-End Test Suite")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Total cases: {total}")
    print(f"{'='*70}\n")

    for i, case in enumerate(ALL_CASES):
        print(f"[{i+1}/{total}] Stage {case.stage} — {case.name} ({case.case_id})")
        print(f"       Route: {case.route}, Dialects: {case.expected_dialects}")

        result = run_case(case)
        results.append(result)

        status = "OK" if result["ok"] else "FAIL"
        stages_str = " → ".join(result["stages_completed"])
        print(f"       Result: {status} | Stages: {stages_str} | {result['elapsed_s']}s")
        if result.get("error"):
            print(f"       Error: {result['error'][:200]}")
        print()

    # Generate summary report
    report = {
        "output_dir": str(OUTPUT_DIR),
        "total": total,
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "by_stage": {},
        "results": results,
    }

    for r in results:
        stage_key = f"stage{r['stage']}"
        if stage_key not in report["by_stage"]:
            report["by_stage"][stage_key] = {"total": 0, "passed": 0}
        report["by_stage"][stage_key]["total"] += 1
        if r["ok"]:
            report["by_stage"][stage_key]["passed"] += 1

    report_path = OUTPUT_DIR / "e2e_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # Print summary
    print(f"{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Total: {report['total']} | Passed: {report['passed']} | Failed: {report['failed']}")
    for stage_key, counts in sorted(report["by_stage"].items()):
        print(f"  {stage_key}: {counts['passed']}/{counts['total']} passed")
    print(f"  Report: {report_path}")
    print(f"{'='*70}")

    return report


if __name__ == "__main__":
    run_all_cases()
