"""v6.3 Full Stress Test: Text → LLM → Validate → AutoFix → Runtime → STEP → SW SLDPRT.
Fresh LLM calls for every case. No reused outputs. Deep monitoring of all stages.
Uses strict=False tool calling (DeepSeek known limitation: complex $ref schema rejected in strict mode).
"""
import json, os, sys, time, traceback
from pathlib import Path

sys.path.insert(0, r'E:\auto_detection_process\integrations\engineering_tools\src')
os.environ['DEEPSEEK_API_KEY'] = open(r'E:\auto_detection_process\_archive\apikey.txt').read().strip()

CONDA = r'E:\auto_detection_process\.conda\python.exe'
OUT = Path(__file__).parent
CASES_DIR = OUT / 'cases_v63'
CASES_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# Test Cases
# ═══════════════════════════════════════════════════════════════

CASES = [
    # --- Group A: Single-Body Basic ---
    {"id":"v63_flange","name":"法兰盘","dialects":["axisymmetric"],
     "prompt":"设计一个法兰盘。外径200mm，内径80mm，厚度20mm。在节圆160mm上均布8个直径12mm的螺栓孔。使用axisymmetric方言。单位mm。"},

    {"id":"v63_washer","name":"垫圈","dialects":["axisymmetric"],
     "prompt":"设计一个垫圈。外径100mm，内径40mm，厚度20mm。在节圆70mm上均布6个直径8mm的通孔。使用axisymmetric方言。单位mm。"},

    {"id":"v63_stepped_shaft","name":"阶梯轴","dialects":["axisymmetric"],
     "prompt":"设计一个3段阶梯轴。第1段半径25mm高30mm，第2段半径30mm高50mm，第3段半径20mm高70mm。中心有直径10mm的通孔贯穿全轴。使用axisymmetric方言。单位mm。"},

    {"id":"v63_cross_block","name":"六面钻孔","dialects":["sketch_extrude"],
     "prompt":"设计一个100x100x100mm正方体测试块。顶面中心钻直径20mm通孔。前面钻2个直径10mm侧孔间距40mm。左面钻1个直径8mm侧孔。右面钻1个直径8mm侧孔。使用sketch_extrude方言。单位mm。"},

    # --- Group B: Pattern & Feature ---
    {"id":"v63_dual_pcd","name":"双PCD法兰","dialects":["axisymmetric"],
     "prompt":"设计一个双圈螺栓孔法兰。外径300mm内径60mm厚度40mm。外圈12个直径18mm螺栓孔PCD=240mm。内圈8个直径12mm螺栓孔PCD=160mm。使用axisymmetric方言。单位mm。"},

    {"id":"v63_large_ring","name":"大直径环","dialects":["axisymmetric"],
     "prompt":"设计一个大直径法兰环。外径1000mm内径900mm厚度30mm。均布36个直径16mm通孔PCD=950mm。使用axisymmetric方言。单位mm。"},

    {"id":"v63_perforated","name":"多孔板","dialects":["sketch_extrude"],
     "prompt":"设计一块多孔安装板200x150x10mm。板上需要规则的孔阵列。使用sketch_extrude方言的cut_hole_pattern_linear操作，hole_dia_mm=3, count_x=20, count_y=15, spacing_x_mm=8, spacing_y_mm=8。单位mm。"},

    {"id":"v63_ribbed_base","name":"加筋基座","dialects":["sketch_extrude"],
     "prompt":"设计一个加筋基座300x240x25mm。四角有安装孔。添加纵向和横向加强筋。使用sketch_extrude方言。单位mm。"},

    # --- Group C: Advanced Geometry ---
    {"id":"v63_spring","name":"螺旋弹簧","dialects":["loft_sweep"],
     "prompt":"设计一个15圈螺旋弹簧。螺旋半径60mm，钢丝直径8mm，螺距15mm，总高225mm。使用loft_sweep方言的helix_sweep操作。单位mm。"},

    {"id":"v63_3d_pipe","name":"空间管路","dialects":["loft_sweep"],
     "prompt":"设计一段三维弯曲管路。路径点从(0,0,0)到(500,30,350)经过6个控制点。管截面为圆形，半径15mm。使用loft_sweep方言。单位mm。"},

    {"id":"v63_var_duct","name":"变径风管","dialects":["loft_sweep"],
     "prompt":"设计一个变截面风管。从圆形截面直径100mm过渡到矩形120x80mm再回到圆形直径80mm。三个截面在z=0,150,300mm处。使用loft_sweep方言的loft_sections操作。单位mm。"},

    {"id":"v63_shell_box","name":"壳体箱","dialects":["sketch_extrude"],
     "prompt":"设计一个电子外壳200x150x100mm。抽壳后壁厚3mm。前面有矩形开口80x50mm。使用sketch_extrude方言。单位mm。"},

    # --- Group D: Multi-Component ---
    {"id":"v63_support_frame","name":"支撑框架","dialects":["sketch_extrude","axisymmetric","composition"],
     "prompt":"设计一个四柱支撑框架。底板400x300x20mm有四角安装孔。4根圆柱直径50mm高200mm。顶板400x300x15mm。底板和顶板使用sketch_extrude。柱子使用axisymmetric。装配使用composition的boolean_union。单位mm。"},

    {"id":"v63_double_flange","name":"双法兰管","dialects":["axisymmetric","composition"],
     "prompt":"设计一个双法兰短管。管段外径80mm内径60mm长200mm。两端各有法兰外径140mm厚20mm，带6个直径12mm螺栓孔PCD=110mm。使用axisymmetric和composition方言。单位mm。"},
]

# ═══════════════════════════════════════════════════════════════
# Pipeline functions
# ═══════════════════════════════════════════════════════════════

def call_llm_l1(user_request: str):
    """L1: Route — select dialect. Uses strict=False (thinking disabled)."""
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_tool, build_level1_routing_prompt
    from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    config = LlmModelConfig(model='deepseek-v4-pro', base_url='https://api.deepseek.com/beta')
    caller = DeepSeekToolCaller()
    reg = default_registry()

    l1 = build_level1_routing_prompt(user_request, dialect_catalog=reg.export_catalog())
    l1_tool = build_level1_tool()

    for attempt in range(3):
        try:
            tc = caller.call_strict_tool(
                messages=[{"role":"system","content":l1["system"]},{"role":"user","content":l1["user"]}],
                tool_name=l1_tool["function"]["name"],
                tool_description=l1_tool["function"]["description"],
                tool_schema=l1_tool["function"]["parameters"],
                model_config=config,
            )
            args = dict(tc.arguments)
            for skill in args.get("selected_domain_skills", []):
                if not skill.get("skill_version"):
                    skill["skill_version"] = "1.0"
            plan = DialectSelectionPlan.model_validate(args)
            # Remap legacy names
            LEGACY = {"axisymmetric_base":"axisymmetric","sketch_extrude_base":"sketch_extrude",
                      "sketch_profile_base":"sketch_profile","loft_sweep_base":"loft_sweep",
                      "shell_housing_base":"shell_housing","composition_base":"composition"}
            for sd in plan.selected_dialects:
                if sd.dialect in LEGACY:
                    sd.dialect = LEGACY[sd.dialect]
            return plan
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(3)
    return None


def call_llm_l2(user_request: str, selection_plan):
    """L2: Author — strict=False tool calling with full L2 schema."""
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
        build_level2_authoring_prompt, build_level2_tool,
    )
    config = LlmModelConfig(model='deepseek-v4-pro', base_url='https://api.deepseek.com/beta')
    caller = DeepSeekToolCaller()
    l2 = build_level2_authoring_prompt(user_request, selection_plan)
    l2_tool = build_level2_tool()
    tc = caller.call_strict_tool(
        messages=[{"role":"system","content":l2["system"]},{"role":"user","content":l2["user"]}],
        tool_name=l2_tool["function"]["name"],
        tool_description=l2_tool["function"]["description"],
        tool_schema=l2_tool["function"]["parameters"],
        model_config=config,
    )
    return tc.arguments


def import_sw(step_path, sldprt_path):
    """Import STEP to SolidWorks."""
    try:
        from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
        template = Path(r'C:/ProgramData/SOLIDWORKS/SOLIDWORKS 2025/templates/gb_part.prtdot')
        client = SolidWorksClient(visible=False, part_template=template).connect()
        ok = client.import_step_as_part(str(step_path), str(sldprt_path))
        client.close_all(); client.close()
        return ok and sldprt_path.exists() and sldprt_path.stat().st_size > 0
    except Exception as e:
        return False


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("v6.3 Full Stress Test: Text → STEP → SolidWorks SLDPRT")
    print("=" * 70)
    print(f"Cases: {len(CASES)}")
    print(f"Model: deepseek-v4-pro (strict=False, thinking=disabled)")
    print(f"Output: {CASES_DIR}")
    print()

    results = []
    t_total = time.time()

    for i, case in enumerate(CASES):
        cid = case["id"]
        cdir = CASES_DIR / cid
        cdir.mkdir(parents=True, exist_ok=True)
        print(f"[{i+1}/{len(CASES)}] {cid} ({case['name']}):", end=" ", flush=True)

        (cdir / "input_text.txt").write_text(case["prompt"], encoding="utf-8")
        result = {"id": cid, "status": "STARTED", "step_kb": 0, "sw": False}
        t_case = time.time()

        # ── L1 Route ──
        try:
            plan = call_llm_l1(case["prompt"])
            (cdir / "route_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            print(f"L1({plan.route_decision}, {time.time()-t_case:.0f}s)", end=" ", flush=True)
        except Exception as e:
            print(f"L1_FAIL({e})")
            result["status"] = "L1_FAIL"; result["error"] = str(e)[:200]
            results.append(result); continue

        # ── L2 Author ──
        try:
            raw_json = call_llm_l2(case["prompt"], plan)
            if "llm_validation_hints" not in raw_json:
                raw_json["llm_validation_hints"] = {}
            (cdir / "llm_raw.json").write_text(json.dumps(raw_json, indent=2, ensure_ascii=False), encoding="utf-8")
            n_nodes = len(raw_json.get("nodes", []))
            print(f"L2({n_nodes}n, {time.time()-t_case:.0f}s)", end=" ", flush=True)
        except Exception as e:
            print(f"L2_FAIL({e})")
            result["status"] = "L2_FAIL"; result["error"] = str(e)[:200]
            results.append(result); continue

        # ── Validate + AutoFix ──
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

        REG = default_registry()
        canonical, report, bundle = validate_and_canonicalize_with_bundle(raw_json)
        autofix_applied = False
        if not report.ok:
            try:
                fixed_doc, af_report = auto_fix_with_report(raw_json, REG)
                (cdir / "autofix_report.json").write_text(af_report.model_dump_json(indent=2), encoding="utf-8")
                if af_report.applied:
                    (cdir / "raw_fixed.json").write_text(json.dumps(fixed_doc, indent=2, ensure_ascii=False), encoding="utf-8")
                    canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed_doc)
                    autofix_applied = True
            except: pass

        (cdir / "validation_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        errs = [i for i in report.issues if i.severity == "error"]
        if canonical is None or errs:
            print(f"VAL_FAIL({len(errs)}e{', autofix' if autofix_applied else ''})")
            result["status"] = "VAL_FAIL"; result["errors"] = len(errs)
            results.append(result); continue

        print("VAL_OK", end=" ", flush=True)
        (cdir / "canonical.json").write_text(canonical.model_dump_json(indent=2), encoding="utf-8")
        (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2), encoding="utf-8")

        # ── Runtime → STEP ──
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        try:
            run_result = run_canonical_gcad(
                canonical=canonical, out_step=cdir/"output.step",
                metadata_path=cdir/"output.metadata.json",
                validation_seed=bundle.to_metadata_dict() if bundle else {},
                require_full_validation_seed=False,
            )
            if run_result.ok and (cdir/"output.step").exists():
                step_kb = (cdir/"output.step").stat().st_size // 1024
                result["step_kb"] = step_kb
                print(f"STEP({step_kb}KB)", end=" ", flush=True)

                # ── Metadata check ──
                if (cdir/"output.metadata.json").exists():
                    meta = json.loads((cdir/"output.metadata.json").read_text(encoding="utf-8"))
                    val = meta.get("validation", {})
                    cm = val.get("compiler_middle_end", {})
                    health = val.get("geometry_health_summary", {})
                    print(f"META(cm={cm.get('ok')},h={health.get('total_ops_checked')})", end=" ", flush=True)

                # ── SW import ──
                print("SW...", end=" ", flush=True)
                sw_ok = import_sw(cdir/"output.step", cdir/"output.SLDPRT")
                result["sw"] = sw_ok
                print("OK" if sw_ok else "FAIL", end="", flush=True)
                result["status"] = "PASS" if sw_ok else "STEP_OK"
            else:
                print(f"RT_FAIL", end="", flush=True)
                result["status"] = "RT_FAIL"
                result["error"] = run_result.error[:200] if run_result.error else "Unknown"
        except Exception as e:
            print(f"RT_EXC({e})", end="", flush=True)
            result["status"] = "RT_EXC"; result["error"] = str(e)[:200]

        print()
        results.append(result)

    # ── Summary ──
    t_elapsed = time.time() - t_total
    passed = sum(1 for r in results if r["status"] in ("PASS", "STEP_OK"))
    sw_count = sum(1 for r in results if r.get("sw"))
    print(f"\n{'='*70}")
    print(f"RESULTS: {passed}/{len(CASES)} STEP, {sw_count} SW, {t_elapsed/60:.1f}min")
    for r in results:
        print(f"  [{r['status']}] {r['id']}: step={r.get('step_kb',0)}KB sw={r.get('sw',False)}")
        if r.get("error"):
            print(f"    {r['error'][:120]}")

    with open(OUT / "v63_stress_results.json", "w", encoding="utf-8") as f:
        json.dump({"total":len(CASES),"passed":passed,"sw":sw_count,"elapsed_min":round(t_elapsed/60,1),"cases":results}, f, indent=2, ensure_ascii=False)
    print(f"Results: {OUT / 'v63_stress_results.json'}")
