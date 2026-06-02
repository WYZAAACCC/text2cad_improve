"""Fix 3 immature dialects: loft_sweep, shell_housing, sketch_profile.

Strategy: run LLM → capture errors → auto_fix → re-validate.
Stop when all 3 pass OR after round 5.
"""
import json, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent / "src").resolve()
OUT = Path(r"E:\auto_detection_process\demo_output_v5\fix_3")
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()

# ═══════════════════════════════════════════════════════════════════════════════
# Enhanced contract builder with EXPLICIT JSON examples
# ═══════════════════════════════════════════════════════════════════════════════

def build_enhanced_contract(dialect_ids):
    lines = []
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} v{d.version} | phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            pstrs = []
            for pn, pi in props.items():
                pstrs.append(f"{pn}:{pi.get('type','?')}")
            lines.append(f"  {op_name} phase={spec.phase} params: {' | '.join(pstrs)}")

            # ── Explicit JSON examples ──
            if op_name == "create_sweep_path":
                lines.append('    EXAMPLE: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":0,"y_mm":0,"z_mm":50},{"x_mm":30,"y_mm":0,"z_mm":50}]}')
            if op_name == "sweep_profile":
                lines.append('    EXAMPLE: {"shape":"circle","radius_mm":5}')
            if op_name == "loft_sections":
                lines.append('    EXAMPLE: {"sections":[{"position":{"x_mm":0,"y_mm":0,"z_mm":0},"shape":"circle","radius_mm":20},{"position":{"x_mm":0,"y_mm":0,"z_mm":40},"shape":"circle","radius_mm":10}]}')
            if op_name == "helix_sweep":
                lines.append('    EXAMPLE: {"radius_mm":15,"height_mm":40,"pitch_mm":8,"profile_radius_mm":2,"turns":5,"variable_pitch":false}')
            if op_name == "shell_body":
                lines.append('    EXAMPLE: {"thickness_mm":2}')
            if op_name == "hollow_body":
                lines.append('    EXAMPLE: {"wall_thickness_mm":2}')
            if op_name == "create_2d_sketch":
                lines.append('    EXAMPLE: {"plane":"XY"}')
            if op_name == "add_polyline":
                lines.append('    EXAMPLE: {"points":[{"x_mm":0,"y_mm":0},{"x_mm":80,"y_mm":0},{"x_mm":80,"y_mm":8},{"x_mm":0,"y_mm":8}]}')
            if op_name == "close_profile":
                lines.append('    EXAMPLE: {} (empty params)')
            if op_name == "extrude_profile":
                lines.append('    EXAMPLE: {"depth_mm":50,"direction":"+"}')
            if op_name == "cut_profile":
                lines.append('    EXAMPLE: {"depth_mm":10,"direction":"-"}')
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Test cases
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    {
        "id": "fix_sweep", "name": "Sweep Pipe",
        "dialects": ["loft_sweep"],
        "prompt": (
            "Create a U-shaped pipe: create_sweep_path with path_points "
            "[x=0,y=0,z=0], [x=0,y=0,z=50], [x=30,y=0,z=50], [x=30,y=0,z=0]. "
            "Then sweep_profile shape=circle radius_mm=5. "
            "Units mm. Reference only. Not for manufacturing."
        ),
    },
    {
        "id": "fix_helix", "name": "Helix Spring",
        "dialects": ["loft_sweep"],
        "prompt": (
            "Create a coil spring: helix_sweep radius_mm=15 height_mm=40 pitch_mm=8 "
            "profile_radius_mm=2 turns=5 variable_pitch=false. "
            "Units mm. Reference only. Not for manufacturing."
        ),
    },
    {
        "id": "fix_shell", "name": "Shell Housing",
        "dialects": ["axisymmetric", "shell_housing"],
        "prompt": (
            "Create a cup: Component 'cup' (axisymmetric): revolve_profile with profile_stations "
            "r_mm=30 z_front_mm=0 z_rear_mm=40. Then cut_center_bore diameter_mm=25 depth_mm=35. "
            "Component 'shell' (shell_housing): shell_body thickness_mm=2. "
            "shell_body inputs: [{component: cup, output: body}]. "
            "Units mm. Reference only. Not for manufacturing."
        ),
    },
    {
        "id": "fix_l_bracket", "name": "SketchProfile L-Bracket",
        "dialects": ["sketch_profile"],
        "prompt": (
            "Create an L-bracket: create_2d_sketch plane=XY. "
            "add_polyline with points forming L-shape: "
            "[x=0,y=0], [x=80,y=0], [x=80,y=8], [x=50,y=8], [x=50,y=40], [x=42,y=40], [x=42,y=8], [x=0,y=8]. "
            "close_profile. extrude_profile depth_mm=50 direction=+. "
            "Units mm. Reference only. Not for manufacturing."
        ),
    },
]


def call_llm(user_msg, max_retries=2):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
                tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
                timeout=120, extra_body={"thinking": {"type": "disabled"}},
            )
            args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
            if args.get("llm_validation_hints") is None: args["llm_validation_hints"] = {}
            if "units" not in args: args["units"] = "mm"
            if "trust_level" not in args: args["trust_level"] = "reference_geometry"
            return args
        except Exception as e:
            if attempt < max_retries - 1:
                user_msg += f"\n\nPREVIOUS ERROR: {str(e)[:200]}\nPlease fix and retry."
                continue
            raise


def validate_and_build(case, args, round_num):
    cdir = OUT / case["id"] / f"round{round_num}"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

    args = auto_fix(args, REG)

    try:
        doc = RawGcadDocument.model_validate(args)
    except Exception as e:
        return {"ok": False, "error": f"Pydantic: {e}"}

    canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
    (cdir / "validation.json").write_text(json.dumps(report.model_dump() if report else {}, indent=2, default=str), encoding="utf-8")

    if not canonical or not (report and report.ok):
        issues = report.issues if report else []
        return {"ok": False, "error": "Validate: " + "; ".join(f"[{i.code}] {i.message[:100]}" for i in issues[:5]), "issues": issues}

    # Save canonical
    (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str), encoding="utf-8")
    (cdir / "bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str), encoding="utf-8")

    # Build STEP
    bscript = f'''import sys; sys.path.insert(0, r"{SRC.as_posix()}")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"{(cdir / 'canonical.json').as_posix()}",
    validation_seed_json=r"{(cdir / 'bundle.json').as_posix()}",
    out_step=r"{(cdir / 'output.step').as_posix()}",
    metadata_path=r"{(cdir / 'output.metadata.json').as_posix()}")
print("BUILD_OK" if r.ok else f"BUILD_FAILED: {{r.error}}")
'''
    bp = cdir / "_b.py"; bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    if r.returncode == 0 and (cdir / "output.step").exists():
        return {"ok": True, "step_bytes": (cdir / "output.step").stat().st_size}
    return {"ok": False, "error": f"STEP: {r.stderr[:300]}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════════════════════

MAX_ROUNDS = 4
results = {c["id"]: {"status": "pending", "rounds": 0, "final_ok": False} for c in CASES}

for round_num in range(1, MAX_ROUNDS + 1):
    pending = [c for c in CASES if not results[c["id"]]["final_ok"]]
    if not pending:
        break

    print(f"\n{'='*60}")
    print(f"  ROUND {round_num} — {len(pending)} remaining")
    print(f"{'='*60}")

    for case in pending:
        cid = case["id"]
        print(f"\n  [{cid}] ", end="", flush=True)

        contract = build_enhanced_contract(case["dialects"])
        user_msg = f"TASK: {case['prompt']}\n\n{contract}\n\nCRITICAL: Use EXACT param names and structures from examples above. All safety true. trust_level reference_geometry. llm_validation_hints={{}}"

        # If previous round failed, inject errors into prompt
        prev_error = results[cid].get("last_error", "")
        if prev_error and round_num > 1:
            user_msg += f"\n\nPREVIOUS ERRORS (fix these): {prev_error[:500]}"

        try:
            args = call_llm(user_msg)
        except Exception as e:
            results[cid]["last_error"] = str(e)
            print(f"LLM FAIL: {e}", end="")
            continue

        result = validate_and_build(case, args, round_num)
        results[cid]["rounds"] = round_num
        results[cid]["last_error"] = result.get("error", "")

        if result["ok"]:
            results[cid]["final_ok"] = True
            results[cid]["step_bytes"] = result.get("step_bytes", 0)
            print(f"OK STEP={result.get('step_bytes',0)}B", end="")
        else:
            # Extract key error codes for next round
            issues = result.get("issues", [])
            error_codes = [i.code if hasattr(i, 'code') else i.get('code','?') for i in issues[:3]]
            print(f"FAIL [{','.join(error_codes)}]", end="")

print(f"\n\n{'='*60}")
print(f"  FINAL RESULTS")
print(f"{'='*60}")
for cid, r in results.items():
    status = "OK" if r["final_ok"] else f"FAIL (rounds={r['rounds']})"
    step = f" STEP={r.get('step_bytes',0)}B" if r["final_ok"] else ""
    print(f"  {cid}: {status}{step}")

passed = sum(1 for r in results.values() if r["final_ok"])
print(f"\n  {passed}/{len(CASES)} passed")
(OUT / "fix_report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
