"""Run full LLM -> STEP pipeline for test cases."""
import os, sys, json, time
from pathlib import Path
sys.path.insert(0, r'E:\auto_detection_process\integrations\engineering_tools\src')
os.environ['DEEPSEEK_API_KEY'] = 'sk-db9a573912714fd191495d6c6db41ff7'

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
    build_level1_routing_prompt, build_level2_authoring_prompt, build_level2_tool
)
from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan

TEST_DIR = Path(r'E:\auto_detection_process\demo_output_v5\cc_nonprimitive_eval_20260605_120000')
CASES_DIR = TEST_DIR / 'cases'
CASES_DIR.mkdir(parents=True, exist_ok=True)

caller = DeepSeekToolCaller()
cfg = LlmModelConfig(model='deepseek-chat', temperature=0.0, base_url='https://api.deepseek.com/v1', timeout_s=120)

test_cases = [
    ("flange", "Design a flange: outer diameter 200mm, inner bore 80mm, thickness 20mm. 8 bolt holes of diameter 12mm equally spaced on PCD 160mm. The flange is axisymmetric."),
    ("cross_block", "Design a 100x100x100mm cube with holes on all six faces. Top face: one 20mm diameter through hole at center. Bottom face: one 15mm hole offset (20,0) from center. Front face: two 10mm holes spaced 40mm apart. Back face: one 12mm hole at center. Left face: one 8mm hole. Right face: one 8mm hole."),
    ("spring", "Design a helical coil spring with 10 turns, coil radius 80mm, wire diameter 10mm, pitch 16mm, total height 160mm."),
    ("bracket", "Design a hollow bracket: base plate 200x160x8mm with 4 mounting holes diameter 8mm at corners. Side walls 70mm tall, 5mm thick. Top face has 2 holes diameter 15mm."),
    ("pipe_flange", "Design a pipe with flanges on both ends. Pipe outer diameter 60mm, inner diameter 50mm, length 300mm. Flanges on both ends: diameter 120mm, thickness 15mm, 6 bolt holes diameter 10mm on PCD 90mm. Flanges are coaxial with the pipe."),
]

for ci, (case_id, prompt) in enumerate(test_cases):
    out_dir = CASES_DIR / f'llm_{case_id}'
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'input_text.txt').write_text(prompt, encoding='utf-8')

    print(f'\n[{ci+1}/{len(test_cases)}] {case_id}')
    print(f'  Prompt: {prompt[:120]}...')

    # Step 1: Route (use constrained tool schema from build_level1_tool)
    print(f'  [1/4] Route...', end=' ', flush=True)
    t0 = time.time()
    try:
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_tool
        rp = build_level1_routing_prompt(prompt)
        l1_tool = build_level1_tool()
        rr = caller.call_strict_tool(
            messages=[{'role': 'system', 'content': rp['system']}, {'role': 'user', 'content': rp['user']}],
            tool_name=l1_tool['function']['name'], tool_description=l1_tool['function']['description'],
            tool_schema=l1_tool['function']['parameters'], model_config=cfg,
        )
        sp = DialectSelectionPlan.model_validate(rr.arguments)
        (out_dir / 'route_plan.json').write_text(json.dumps(sp.model_dump(), indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'OK ({time.time()-t0:.1f}s) -> {[sd.dialect for sd in sp.selected_dialects]}', flush=True)
    except Exception as e:
        print(f'FAIL: {e}', flush=True)
        continue

    # Step 2: Author
    print(f'  [2/4] Author...', end=' ', flush=True)
    t0 = time.time()
    try:
        ap = build_level2_authoring_prompt(prompt, sp, strict_usage_skill=False)
        at = build_level2_tool()
        ar = caller.call_strict_tool(
            messages=[{'role': 'system', 'content': ap['system']}, {'role': 'user', 'content': ap['user']}],
            tool_name='generate_raw_gcad_document', tool_description='Generate CAD IR',
            tool_schema=at['function']['parameters'], model_config=cfg,
        )
        raw = ar.arguments
        (out_dir / 'llm_raw.json').write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'OK ({time.time()-t0:.1f}s) -> {len(raw.get("nodes",[]))} nodes', flush=True)
    except Exception as e:
        print(f'FAIL: {e}', flush=True)
        continue

    # Step 3: Validate + autofix + canonicalize
    print(f'  [3/4] Validate...', end=' ', flush=True)
    t0 = time.time()
    try:
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
        if not report.ok:
            fixed, af = auto_fix_with_report(raw, default_registry())
            (out_dir / 'autofix_report.json').write_text(json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding='utf-8')
            if af.applied:
                (out_dir / 'raw_fixed.json').write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding='utf-8')
                canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed)

        (out_dir / 'validation_report.json').write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding='utf-8')
        if canonical and report.ok:
            (out_dir / 'canonical.json').write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding='utf-8')
            print(f'OK ({time.time()-t0:.1f}s)', flush=True)
        else:
            errs = [f'{i.code}' for i in report.issues if i.severity=='error']
            print(f'FAIL_VAL ({errs[:3]})', flush=True)
            continue
    except Exception as e:
        print(f'FAIL: {e}', flush=True)
        continue

    # Step 4: Runtime -> STEP
    print(f'  [4/4] Runtime...', end=' ', flush=True)
    t0 = time.time()
    try:
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        step_out = out_dir / 'output.step'
        meta_out = out_dir / 'metadata.json'
        rr = run_canonical_gcad(canonical=canonical, out_step=step_out, metadata_path=meta_out,
            validation_seed=bundle.to_metadata_dict(), require_full_validation_seed=False)
        elapsed = time.time() - t0
        sz = step_out.stat().st_size if step_out.exists() else 0
        vol = None
        if step_out.exists() and sz > 100:
            try:
                import cadquery as cq
                s = cq.importers.importStep(str(step_out))
                v = s.val() if hasattr(s,'val') else s
                vol = round(v.Volume(),1) if hasattr(v,'Volume') else None
            except: pass
        print(f'{"OK" if rr.ok else "FAIL"} ({sz//1024}KB, vol={vol}mm3, {elapsed:.1f}s)', flush=True)

        (out_dir / 'case_result.json').write_text(json.dumps({
            'case_id': case_id, 'status': 'PASS' if rr.ok else 'FAIL',
            'step_size_bytes': sz, 'volume_mm3': vol,
            'elapsed_s': round(elapsed,1), 'error': rr.error,
        }, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f'FAIL: {e}', flush=True)

print(f'\nDone. Output: {CASES_DIR}')
