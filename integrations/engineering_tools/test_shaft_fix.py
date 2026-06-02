"""Test complex shaft with rim_slot example + phase ordering fix."""
import json, os, sys, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent / "src").resolve()
OUT = Path(r"E:\auto_detection_process\demo_output_v5")
cdir = OUT / "complex_shaft"
cdir.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()

# Build contract with explicit examples
did = "axisymmetric"
d = REG.require(did)
contract_lines = [f"=== {did} v{d.version} | phases: {' -> '.join(d.phase_order)} ==="]
for (op_name, _), spec in d.op_specs().items():
    ps = spec.params_model.model_json_schema()
    props = ps.get("properties", {})
    pstrs = []
    for pn, pi in props.items():
        pstrs.append(f"{pn}:{pi.get('type','?')}")
    contract_lines.append(f"  {op_name} phase={spec.phase} params: {' | '.join(pstrs)}")
    if op_name == "revolve_profile":
        contract_lines.append(
            '    EXAMPLE: {"axis":"Z","profile_stations":['
            '{"r_mm":40,"z_front_mm":0,"z_rear_mm":30},'
            '{"r_mm":30,"z_front_mm":30,"z_rear_mm":55}]}'
        )
    if op_name == "cut_rim_slot_pattern":
        contract_lines.append(
            '    EXAMPLE: {"count":6,"slot_depth_mm":4,'
            '"slot_profile":{"kind":"symmetric_station_profile",'
            '"stations":[{"depth_mm":0,"half_width_mm":3},'
            '{"depth_mm":4,"half_width_mm":3}]}}'
        )
        contract_lines.append("    NOTE: slot_profile is OBJECT not list! kind=string, stations=list of {depth_mm, half_width_mm}.")

contract = "\n".join(contract_lines)

user_msg = (
    "TASK: Create complex stepped shaft with 5 sections (z=0-30 r=40, z=30-55 r=30, "
    "z=55-75 r=22.5, z=75-110 r=15, z=110-130 r=10), center bore dia=12mm through_all, "
    "annular groove on section3 (inner_dia=28 outer_dia=38 depth=3 side=front), "
    "rim slots on section1 (count=6 depth=4 with slot_profile using symmetric_station_profile), "
    "chamfer 1.5mm on external edges.\n\n"
    f"{contract}\n\n"
    "CRITICAL: Phase order MUST be respected (base_solid->primary_cut->annular_detail->pattern_cut->rim_detail->edge_treatment). "
    "Use EXACT param field names from examples above. slot_profile must be OBJECT with kind and stations. "
    "All safety flags true. trust_level=reference_geometry. llm_validation_hints={}"
)

(cdir / "prompt_v2.txt").write_text(user_msg, encoding="utf-8")

# Call DeepSeek
from openai import OpenAI
client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]

print("Calling DeepSeek...")
resp = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
    tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
    timeout=120, extra_body={"thinking": {"type": "disabled"}},
)
args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
(cdir / "llm_raw_output_v2.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

# Show LLM output
phases = [(n.get("op", "?"), n.get("phase", "?")) for n in args.get("nodes", [])]
print(f"LLM ops ({len(phases)}): {' -> '.join(f'{o}[{p}]' for o, p in phases)}")

# Check rim_slot params
for n in args.get("nodes", []):
    if n.get("op") == "cut_rim_slot_pattern":
        sp = n.get("params", {}).get("slot_profile", {})
        print(f"rim_slot profile type: {type(sp).__name__}, keys: {list(sp.keys()) if isinstance(sp, dict) else 'N/A'}")

# AutoFix
args = auto_fix(args, REG)
if args.get("llm_validation_hints") is None:
    args["llm_validation_hints"] = {}
if "units" not in args:
    args["units"] = "mm"
if "trust_level" not in args:
    args["trust_level"] = "reference_geometry"

phases2 = [(n.get("op", "?"), n.get("phase", "?")) for n in args.get("nodes", [])]
print(f"After auto_fix: {' -> '.join(f'{o}[{p}]' for o, p in phases2)}")

# Validate
try:
    doc = RawGcadDocument.model_validate(args)
    canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
    if canonical and report.ok:
        print("VALIDATION PASSED")
        (cdir / "canonical_gcad.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str), encoding="utf-8")
        (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str), encoding="utf-8")

        # Build STEP
        bscript = f'''import sys; sys.path.insert(0, r"{SRC.as_posix()}")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"{(cdir / 'canonical_gcad.json').as_posix()}",
    validation_seed_json=r"{(cdir / 'validation_bundle.json').as_posix()}",
    out_step=r"{(cdir / 'output.step').as_posix()}",
    metadata_path=r"{(cdir / 'output.metadata.json').as_posix()}")
print("BUILD_OK" if r.ok else f"BUILD_FAILED: {{r.error}}")
'''
        bp = cdir / "_b2.py"
        bp.write_text(bscript, encoding="utf-8")
        r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
        if r.returncode == 0 and (cdir / "output.step").exists():
            step_sz = (cdir / "output.step").stat().st_size
            # Volume check
            import cadquery as cq
            solids = cq.importers.importStep(str(cdir / "output.step"))
            vol = solids.val().Volume() if hasattr(solids, "val") else 0
            print(f"STEP OK: {step_sz}B Vol={vol:.0f}mm3")
            # SW
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            sldprt = cdir / "output.SLDPRT"
            c = SolidWorksClient(visible=False).connect()
            ok = c.import_step_as_part(cdir / "output.step", sldprt)
            c.close()
            print(f"SW: {sldprt.stat().st_size if ok and sldprt.exists() else 0}B")
        else:
            print(f"STEP FAIL: {r.stderr[:500]}")
    else:
        issues = report.issues if report else []
        print(f"VALIDATION FAILED ({len(issues)} issues):")
        for i in issues[:5]:
            print(f"  [{i.code}] {i.message[:120]}")
except Exception as e:
    import traceback
    print(f"FAIL: {e}")
    traceback.print_exc()
