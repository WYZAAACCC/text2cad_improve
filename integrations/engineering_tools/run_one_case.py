"""Run a single test case with ultra-explicit prompt to verify full chain."""
import os, json, sys
sys.path.insert(0, "src")
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

from pathlib import Path
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT

OUTPUT_DIR = Path(r"E:\auto_detection_process\demo_output_v5\washer_proof")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

reg = default_registry()
d = reg.require("axisymmetric")

# Build extremely explicit param info
params_info = []
for (op_name, _), spec in d.op_specs().items():
    ps = spec.params_model.model_json_schema()
    props = ps.get("properties", {})
    required_list = ps.get("required", [])
    param_list = []
    for pname, pinfo in props.items():
        req = "REQUIRED" if pname in required_list else "optional"
        desc = pinfo.get("description", "")
        ptype = pinfo.get("type", "any")
        ref = pinfo.get("$ref", "")
        if ref:
            ref_name = ref.split("/")[-1]
            nested = ps.get("$defs", {}).get(ref_name, {})
            nested_props = nested.get("properties", {})
            field_strs = []
            for k, v in nested_props.items():
                field_strs.append(f"{k}:{v.get('type','?')}")
            param_list.append(f"{pname}: [{req}] list of {{{', '.join(field_strs)}}}")
        else:
            param_list.append(f"{pname}: {ptype} [{req}] {desc[:60]}")
    params_info.append(f"  {op_name} params: {' | '.join(param_list)}")

user_msg = f"""Create a simple washer: outer diameter 80mm, center bore 30mm, thickness 12mm. Units mm.

EXACT OPERATION NAMES AND THEIR EXACT PARAMETER FIELDS (use THESE names exactly):
{chr(10).join(params_info)}

EXAMPLE revolve_profile params (copy this structure exactly, adjust values for washer):
{{"axis": "Z", "profile_stations": [{{"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 2.0}}, {{"r_mm": 40.0, "z_front_mm": 2.0, "z_rear_mm": 12.0}}, {{"r_mm": 15.0, "z_front_mm": 12.0, "z_rear_mm": 13.0}}]}}

EXAMPLE cut_center_bore params (copy exactly with correct diameter):
{{"diameter_mm": 30.0, "axis": "Z", "through_all": true}}

CRITICAL RULES:
- revolve_profile: op_version="1.0.0" phase="base_solid" outputs: [body:solid, outer_frame:frame] inputs: []
- cut_center_bore: op_version="1.0.0" phase="primary_cut" outputs: [body:solid] inputs: [body from revolve_profile]
- selected_dialects version="0.2.0" (NOT "1.0.0")
- ALL 7 safety flags true. ALL 3 constraint flags true. trust_level "reference_geometry".
- llm_validation_hints: {{}}
"""

(OUTPUT_DIR / "prompt.txt").write_text(user_msg, encoding="utf-8")

s = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())

from openai import OpenAI
client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": s}}]

print("Calling DeepSeek...")
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ],
    tools=tools,
    tool_choice={"type": "function", "function": {"name": "gcad"}},
    timeout=120,
    extra_body={"thinking": {"type": "disabled"}},
)

msg = response.choices[0].message
args = json.loads(msg.tool_calls[0].function.arguments)
if args.get("llm_validation_hints") is None:
    args["llm_validation_hints"] = {}

# Post-process common LLM mistakes
KNOWN_DIALECTS = set(reg.list_ids())
for node in args.get("nodes", []):
    op = node.get("op", "")
    if "." in op:
        node["op"] = op.split(".")[-1]
    # Fix hallucinated dialect names
    if node.get("dialect", "") not in KNOWN_DIALECTS:
        node["dialect"] = "axisymmetric"  # fallback for single-dialect case
for comp in args.get("components", []):
    if comp.get("owner_dialect", "") not in KNOWN_DIALECTS:
        comp["owner_dialect"] = "axisymmetric"
for sd in args.get("selected_dialects", []):
    if sd.get("version") == "1.0.0":
        sd["version"] = "0.2.0"
    if sd.get("dialect", "") not in KNOWN_DIALECTS:
        sd["dialect"] = "axisymmetric"

(OUTPUT_DIR / "llm_raw_output.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

print("\n=== LLM OUTPUT ===")
nodes = args.get("nodes", [])
print(f"Nodes: {len(nodes)}")
for n in nodes:
    print(f"  {n['id']}: {n['dialect']}.{n['op']} phase={n['phase']} v={n['op_version']}")
    for k, v in n.get("params", {}).items():
        print(f"    {k}: {str(v)[:100]}")
    for o in n.get("outputs", []):
        print(f"    -> {o['name']}:{o['type']}")

safety = args.get("safety", {})
print(f"Safety all true: {all(v is True for v in safety.values())}")
constraints = args.get("constraints", {})
print(f"Constraints ok: {constraints.get('require_step_file')}/{constraints.get('require_closed_solid')}")

# Validate
print("\n=== VALIDATION ===")
try:
    raw_doc = RawGcadDocument.model_validate(args)
    (OUTPUT_DIR / "raw_gcad_document.json").write_text(
        json.dumps(raw_doc.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
except Exception as e:
    print(f"Pydantic validation FAILED: {e}")
    sys.exit(1)

from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
canonical, report, bundle = validate_and_canonicalize_with_bundle(raw_doc)

if canonical and report.ok:
    print(f"VALIDATION PASSED! canonical={len(canonical.nodes)} nodes")
    (OUTPUT_DIR / "canonical_gcad.json").write_text(
        json.dumps(canonical.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "validation_bundle.json").write_text(
        json.dumps(bundle.to_metadata_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Build STEP
    print("\n=== BUILDING STEP ===")
    import subprocess
    script = f'''
import json, sys
from pathlib import Path
sys.path.insert(0, r"{Path(__file__).parent / 'src'}")

from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"{(OUTPUT_DIR / 'canonical_gcad.json').as_posix()}",
    validation_seed_json=r"{(OUTPUT_DIR / 'validation_bundle.json').as_posix()}",
    out_step=r"{(OUTPUT_DIR / 'output.step').as_posix()}",
    metadata_path=r"{(OUTPUT_DIR / 'output.metadata.json').as_posix()}",
)
if not result.ok:
    print(f"BUILD FAILED: {{result.error}}", file=sys.stderr)
    sys.exit(1)
print(f"STEP: {{result.step_path}}")
print(f"Metadata: {{result.metadata_path}}")
'''
    script_path = OUTPUT_DIR / "run_harness.py"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True, text=True, timeout=300,
        cwd=str(OUTPUT_DIR),
    )
    print(f"Build RC: {result.returncode}")
    print(f"Stdout: {result.stdout[:500]}")
    if result.stderr:
        print(f"Stderr: {result.stderr[:500]}")

    step_path = OUTPUT_DIR / "output.step"
    if step_path.exists():
        print(f"\nSTEP FILE CREATED: {step_path} ({step_path.stat().st_size} bytes)")
        # Try SolidWorks import
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            sldprt_path = OUTPUT_DIR / "output.SLDPRT"
            template = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
            if not template.exists():
                template = None
            client = SolidWorksClient(visible=False, part_template=template).connect()
            ok = client.import_step_as_part(step_path, sldprt_path)
            client.close()
            if ok:
                print(f"SOLIDWORKS SLDPRT CREATED: {sldprt_path} ({sldprt_path.stat().st_size} bytes)")
            else:
                print(f"SolidWorks import returned False (SLDPRT may not exist or SW not available)")
        except Exception as e:
            print(f"SolidWorks import skipped: {e}")
    else:
        print("STEP file NOT created")
else:
    print(f"VALIDATION FAILED ({len(report.issues if report else [])} issues):")
    for i in (report.issues if report else [])[:10]:
        print(f"  [{i.code}] {i.message[:150]}")

print(f"\n=== DONE ===")
print(f"Output: {OUTPUT_DIR}")
