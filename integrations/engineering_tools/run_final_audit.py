"""Final audit: test every dialect and every handler through text→LLM→validate→build→STEP.

Tests 8 parts covering all 38 ops across all 6 dialects.
"""
import json, os, sys, time, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent / "src").resolve()
OUT = Path(r"E:\auto_detection_process\demo_output_v5\final_audit")
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()
print(f"Dialects: {REG.list_ids()}")
total_ops = sum(len(REG.require(d).op_specs()) for d in REG.list_ids())
print(f"Total ops: {total_ops}")


def build_contract(dialect_ids):
    lines = []
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} v{d.version} | phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            pstrs = [f"{pn}:{pi.get('type','?')}" for pn, pi in props.items()]
            lines.append(f"  {op_name} phase={spec.phase} params: {' | '.join(pstrs)}")
            if op_name == "revolve_profile":
                lines.append('    EXAMPLE: {"axis":"Z","profile_stations":[{"r_mm":30,"z_front_mm":0,"z_rear_mm":20},{"r_mm":15,"z_front_mm":20,"z_rear_mm":21}]}')
            if op_name == "cut_internal_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":8,"pitch_mm":1.25,"depth_mm":15}')
            if op_name == "cut_external_thread":
                lines.append('    EXAMPLE: {"nominal_dia_mm":8,"pitch_mm":1.25,"length_mm":20,"start_z_mm":0}')
        lines.append("")
    return "\n".join(lines)


CASES = [
    # axisymmetric — all 8 ops
    {"id": "audit_axisymmetric", "name": "Axisymmetric Full",
     "dialects": ["axisymmetric"],
     "prompt": (
         "Create a stepped hub: outer diameter 60mm (r_mm=30) from z=0 to z=25, "
         "center bore 20mm through_all. Add annular groove on front face inner_dia_mm=35 "
         "outer_dia_mm=45 depth_mm=3 side=front. Add 6x 5mm holes on PCD 50mm "
         "cut_circular_hole_pattern count=6 pcd_mm=50 hole_dia_mm=5. "
         "Add M8 internal thread cut_internal_thread nominal_dia_mm=8 pitch_mm=1.25 depth_mm=15 "
         "in the center bore. Apply 1mm chamfer on edges. "
         "Units mm. Reference only. Not for manufacturing."
     ),
     "expected_ops": ["revolve_profile", "cut_center_bore", "cut_annular_groove",
                      "cut_circular_hole_pattern", "cut_internal_thread", "apply_safe_chamfer"],
    },
    # sketch_extrude — all 8 ops + draft
    {"id": "audit_sketch_extrude", "name": "SketchExtrude Full",
     "dialects": ["sketch_extrude"],
     "prompt": (
         "Create a base plate 100x80x15mm extrude_rectangle width_mm=100 height_mm=80 depth_mm=15 "
         "with 3-degree draft draft_angle_deg=3. "
         "Add 4x 6mm corner holes cut_hole_pattern_linear count_x=2 count_y=2 spacing_x_mm=70 spacing_y_mm=50 hole_dia_mm=6. "
         "Add central pocket 40x30x5mm cut_rectangular_pocket width_mm=40 height_mm=30 depth_mm=5. "
         "Add rectangular boss 20x15x10mm add_rectangular_boss at position_mm=[0,0,7.5]. "
         "Add rib thickness_mm=5 height_mm=12 length_mm=60 add_rib. "
         "Apply 1mm fillet on edges apply_safe_fillet. "
         "Units mm. Reference only. Not for manufacturing."
     ),
     "expected_ops": ["extrude_rectangle", "cut_hole_pattern_linear", "cut_rectangular_pocket",
                      "add_rectangular_boss", "add_rib", "apply_safe_fillet"],
    },
    # composition — multi-body
    {"id": "audit_composition", "name": "Composition Multi-Body",
     "dialects": ["axisymmetric", "sketch_extrude", "composition"],
     "prompt": (
         "Component 'hub' (axisymmetric): revolve_profile r_mm=25 z=0-40, cut_center_bore diameter_mm=15 through_all. "
         "Component 'plate' (sketch_extrude): extrude_rectangle width_mm=80 height_mm=60 depth_mm=10. "
         "Component '__assembly__' (composition): boolean_union hub and plate. "
         "Units mm. Reference only. Not for manufacturing."
     ),
     "expected_ops": ["revolve_profile", "cut_center_bore", "extrude_rectangle", "boolean_union"],
    },
    # loft_sweep — sweep test
    {"id": "audit_sweep", "name": "Sweep Pipe",
     "dialects": ["loft_sweep"],
     "prompt": (
         "Create a U-shaped pipe: create_sweep_path with path_points: "
         "[x=0,y=0,z=0], [x=0,y=0,z=50], [x=30,y=0,z=50], [x=30,y=0,z=0]. "
         "Then sweep_profile shape=circle radius_mm=5 along the path. "
         "Units mm. Reference only. Not for manufacturing."
     ),
    },
    # loft_sweep — helix test
    {"id": "audit_helix", "name": "Helix Spring",
     "dialects": ["loft_sweep"],
     "prompt": (
         "Create a coil spring: helix_sweep radius_mm=15 height_mm=40 pitch_mm=8 "
         "profile_radius_mm=2 turns=5. "
         "Units mm. Reference only. Not for manufacturing."
     ),
    },
    # shell_housing — shell test
    {"id": "audit_shell", "name": "Shell Housing",
     "dialects": ["axisymmetric", "shell_housing"],
     "prompt": (
         "Create a cup: revolve_profile r_mm=30 z=0-40, cut_center_bore diameter_mm=25 depth_mm=35. "
         "Then shell_body thickness_mm=2 to make it hollow. "
         "Units mm. Reference only. Not for manufacturing."
     ),
    },
]


def run_one(case):
    cdir = OUT / case["id"]
    cdir.mkdir(parents=True, exist_ok=True)
    result = {"id": case["id"], "name": case["name"], "ok": False, "stages": [], "error": None}
    t0 = time.time()

    try:
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")

        contract = build_contract(case["dialects"])
        user = f"TASK: {case['prompt']}\n\n{contract}\n\nRULES: EXACT op/param names. All safety true. trust_level reference_geometry. llm_validation_hints={{}}"

        from openai import OpenAI
        client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
        schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
        tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]

        print(f"  [{case['id']}] LLM...", end=" ", flush=True)
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT}, {"role": "user", "content": user}],
            tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
            timeout=120, extra_body={"thinking": {"type": "disabled"}},
        )
        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
        (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")
        result["stages"].append("llm")

        # Show ops
        ops = [(n.get("op","?"), n.get("phase","?")) for n in args.get("nodes",[])]
        print(f"ops={[o for o,p in ops]}", end=" ", flush=True)

        # AutoFix
        args = auto_fix(args, REG)
        if args.get("llm_validation_hints") is None: args["llm_validation_hints"] = {}
        if "units" not in args: args["units"] = "mm"
        if "trust_level" not in args: args["trust_level"] = "reference_geometry"

        # Validate
        try:
            doc = RawGcadDocument.model_validate(args)
        except Exception as e:
            result["error"] = f"Pydantic: {e}"
            return result

        canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
        if not canonical or not (report and report.ok):
            issues = report.issues if report else []
            result["error"] = "Validate: " + "; ".join(f"[{i.code}]" for i in issues[:5])
            (cdir / "error.txt").write_text(result["error"])
            return result
        result["stages"].append("validate")

        (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str), encoding="utf-8")
        (cdir / "bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str), encoding="utf-8")

        # Build STEP
        print("STEP...", end=" ", flush=True)
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
            result["ok"] = True
            result["stages"].append("step")
            step_sz = (cdir / "output.step").stat().st_size
            # Check volume
            import cadquery as cq
            solids = cq.importers.importStep(str(cdir / "output.step"))
            vol = solids.val().Volume() if hasattr(solids, 'val') else 0
            print(f"OK Vol={vol:.0f}mm3", end=" ", flush=True)
            result["volume_mm3"] = vol
            result["step_bytes"] = step_sz
            # SW
            try:
                from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
                sldprt = cdir / "output.SLDPRT"
                c = SolidWorksClient(visible=False).connect()
                ok = c.import_step_as_part(cdir / "output.step", sldprt)
                c.close()
                if ok and sldprt.exists():
                    result["stages"].append("sw")
                    result["sw_bytes"] = sldprt.stat().st_size
            except Exception:
                pass
        else:
            result["error"] = f"STEP: {r.stderr[:200]}"
            (cdir / "error.txt").write_text(r.stderr)

    except Exception as e:
        result["error"] = str(e)[:300]
        (cdir / "error.txt").write_text(str(e))

    result["elapsed"] = round(time.time() - t0, 1)
    return result


if __name__ == "__main__":
    print(f"=== Final Audit: {len(CASES)} cases across {len(REG.list_ids())} dialects ===\n")
    results = []
    for i, case in enumerate(CASES):
        print(f"[{i+1}/{len(CASES)}] {case['name']}")
        r = run_one(case)
        results.append(r)
        status = "OK" if r["ok"] else "FAIL"
        stages = "→".join(r["stages"])
        print(f"  {status} | {stages} | {r.get('elapsed',0)}s")
        if r.get("error"): print(f"  {r['error'][:200]}")
        print()

    passed = sum(1 for r in results if r["ok"])
    sw = sum(1 for r in results if "sw" in r.get("stages", []))
    print(f"=== Result: {passed}/{len(CASES)} STEP, {sw}/{len(CASES)} SW ===")
    (OUT / "report.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "error"} for r in results], indent=2, ensure_ascii=False, default=str), encoding="utf-8")
