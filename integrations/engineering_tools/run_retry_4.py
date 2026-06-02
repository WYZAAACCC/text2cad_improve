"""Retry the 4 failing cases with explicit examples for revolve_profile."""
import json, os, sys, time, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
OUT = Path(r"E:\auto_detection_process\demo_output_v5")
SRC = Path(__file__).parent / "src"

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()


def build_contract(dialect_ids):
    lines = []
    for did in dialect_ids:
        d = REG.get(did)
        if d is None:
            continue
        lines.append(f"=== {did} v{d.version} | phases: {' -> '.join(d.phase_order)} ===")
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
                    np_data = ps.get("$defs", {}).get(rn, {}).get("properties", {})
                    fs = ", ".join(f"{k}:{v.get('type','?')}" for k, v in np_data.items())
                    pstrs.append(f"{pn}=[{req}] list{{{fs}}}")
                elif "enum" in pi:
                    pstrs.append(f"{pn}={pi['enum']} [{req}]")
                else:
                    pstrs.append(f"{pn}:{pi.get('type','?')} [{req}]")
            lines.append(
                f"  {op_name} v{spec.op_version} phase={spec.phase} "
                f"in={list(spec.input_types)} out={list(spec.output_types)}"
            )
            lines.append(f"    params: {' | '.join(pstrs)}")
            # Explicit examples for hallucination-prone ops
            if op_name == "revolve_profile":
                lines.append(
                    '    EXAMPLE: {"axis":"Z","profile_stations":['
                    '{"r_mm":40.0,"z_front_mm":0.0,"z_rear_mm":12.0},'
                    '{"r_mm":15.0,"z_front_mm":12.0,"z_rear_mm":13.0}]}'
                )
                lines.append(
                    "    CRITICAL: r_mm=RADIUS(half of diameter). "
                    "z_rear_mm MUST be > z_front_mm. "
                    "profile_stations is a list of OBJECTS with r_mm,z_front_mm,z_rear_mm fields."
                )
            if op_name == "cut_center_bore":
                lines.append('    EXAMPLE: {"diameter_mm":30.0,"axis":"Z","through_all":true}')
            if op_name == "extrude_rectangle":
                lines.append('    EXAMPLE: {"width_mm":100,"height_mm":80,"depth_mm":10,"plane":"XY","centered":true}')
            if op_name == "boolean_union":
                lines.append("    NOTE: boolean_union takes empty params {}. Inputs reference component outputs, not node outputs.")
        lines.append("")
    return "\n".join(lines)


CASES = [
    {
        "id": "washer", "name": "Washer",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a simple reference washer: outer diameter 80mm (r_mm=40), "
            "center bore 30mm (diameter_mm=30), thickness 12mm. "
            "Use revolve_profile with profile_stations and cut_center_bore. "
            "Units mm. Not for manufacturing."
        ),
    },
    {
        "id": "stepped_shaft", "name": "Stepped Shaft",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a stepped shaft with 3 sections along Z axis:\n"
            "- Bottom: dia 60mm (r_mm=30), z=0 to 20\n"
            "- Middle: dia 40mm (r_mm=20), z=20 to 50\n"
            "- Top: dia 25mm (r_mm=12.5), z=50 to 75\n"
            "Use revolve_profile with 3 profile_stations. "
            "Units mm. Not for manufacturing."
        ),
    },
    {
        "id": "spur_gear", "name": "Gear Blank",
        "dialects": ["axisymmetric"],
        "prompt": (
            "Create a cylindrical gear blank: outer diameter 44mm (r_mm=22), "
            "center bore 10mm (diameter_mm=10), thickness 15mm. "
            "Use revolve_profile and cut_center_bore. "
            "Units mm. Not for manufacturing."
        ),
    },
    {
        "id": "hub_plate", "name": "Hub+Plate Assembly",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "prompt": (
            "Create an assembly of a hub and base plate:\n"
            "Component 'hub' (axisymmetric): revolve_profile with profile_stations "
            "r_mm=25 z=0-5, r_mm=30 z=5-40. Then cut_center_bore diameter_mm=20.\n"
            "Component 'plate' (sketch_extrude): extrude_rectangle width_mm=100 height_mm=80 depth_mm=10.\n"
            "Component '__assembly__' (composition): boolean_union the hub and plate."
            "boolean_union inputs: [{component: hub, output: body}, {component: plate, output: body}].\n"
            "Units mm. Not for manufacturing."
        ),
    },
]

for case in CASES:
    cdir = OUT / case["id"]
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
    print(f"[{case['id']}] LLM...", end=" ", flush=True)
    t0 = time.time()

    contract = build_contract(case["dialects"])
    user = (
        f"TASK: {case['prompt']}\n\n{contract}\n\n"
        "RULES: Use EXACT op/param names. Output name=body for solids, name=outer_frame for frames. "
        "All 7 safety flags true. trust_level=reference_geometry. llm_validation_hints={}"
    )

    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]

    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
            timeout=120, extra_body={"thinking": {"type": "disabled"}},
        )
        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
    except Exception as e:
        print(f"LLM FAIL: {e}")
        continue

    (cdir / "llm_raw_output.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

    # AutoFix
    args = auto_fix(args, REG)
    if args.get("llm_validation_hints") is None:
        args["llm_validation_hints"] = {}
    if "units" not in args:
        args["units"] = "mm"
    if "trust_level" not in args:
        args["trust_level"] = "reference_geometry"

    # Validate
    try:
        doc = RawGcadDocument.model_validate(args)
    except Exception as e:
        print(f"Pydantic FAIL: {str(e)[:100]}")
        continue

    canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
    if not canonical or not (report and report.ok):
        issues = report.issues if report else []
        print(f"Validate FAIL: {'; '.join(f'[{i.code}] {i.message[:60]}' for i in issues[:3])}")
        continue

    (cdir / "canonical_gcad.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str), encoding="utf-8")
    (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str), encoding="utf-8")

    # Build STEP
    print("validated, STEP...", end=" ", flush=True)
    bscript = f'''import sys; sys.path.insert(0, r"{SRC.as_posix()}")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"{(cdir / 'canonical_gcad.json').as_posix()}",
    validation_seed_json=r"{(cdir / 'validation_bundle.json').as_posix()}",
    out_step=r"{(cdir / 'output.step').as_posix()}",
    metadata_path=r"{(cdir / 'output.metadata.json').as_posix()}")
if not r.ok: print(f"BUILD_FAILED: {{r.error}}"); import sys; sys.exit(1)
print("BUILD_OK")'''
    bp = cdir / "_b.py"
    bp.write_text(bscript, encoding="utf-8")
    try:
        r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
        ok = r.returncode == 0 and (cdir / "output.step").exists()
        if ok:
            step_sz = (cdir / "output.step").stat().st_size
            # SW import
            swscript = f'''import sys; sys.path.insert(0, r"{SRC.as_posix()}")
from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
c = SolidWorksClient(visible=False).connect()
ok = c.import_step_as_part(Path(r"{(cdir / 'output.step').as_posix()}"), Path(r"{(cdir / 'output.SLDPRT').as_posix()}"))
c.close()
print("SW_OK" if ok else "SW_FAIL")'''
            sp = cdir / "_s.py"
            sp.write_text(swscript, encoding="utf-8")
            subprocess.run([sys.executable, str(sp)], capture_output=True, text=True, timeout=120)
            sw_sz = (cdir / "output.SLDPRT").stat().st_size if (cdir / "output.SLDPRT").exists() else 0
            print(f"OK STEP={step_sz // 1024}KB SW={sw_sz // 1024}KB ({time.time() - t0:.0f}s)")
        else:
            print(f"STEP FAIL: {r.stderr[:300]}")
    except Exception as e:
        print(f"Build FAIL: {e}")

print("DONE")
