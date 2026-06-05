"""Full Text → STEP Pipeline Test — v6.3 with Compiler Middle-End.

Fresh LLM prompt → RawGcadDocument → AutoFix → Validate → Runtime → STEP
Deep monitoring of every stage, including compiler middle-end sections.
"""

import sys, json, time, os, traceback
from pathlib import Path

sys.path.insert(0, r'E:\auto_detection_process\integrations\engineering_tools\src')
os.environ['DEEPSEEK_API_KEY'] = open(r'E:\auto_detection_process\_archive\apikey.txt').read().strip()

OUT_DIR = Path(r'E:\auto_detection_process\demo_output_v5\cc_full_pipeline_test_20260605')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# Test cases — increasing complexity
# ═══════════════════════════════════════════════════════════════

TEST_CASES = {
    "v63_washer": (
        "设计一个垫圈。外径100mm，内径40mm，厚度20mm。"
        "在节圆70mm上均布6个直径8mm的通孔。使用axisymmetric方言。"
    ),
    "v63_flange": (
        "设计一个法兰盘。外径200mm，内径60mm，厚度25mm。"
        "在节圆150mm上均布8个直径12mm的螺栓孔。"
        "法兰前后表面各有一圈环形槽，槽宽8mm，深3mm，槽内径120mm，外径140mm。"
        "使用axisymmetric方言。"
    ),
    "v63_stepped_shaft": (
        "设计一个5段阶梯轴。轴线沿Z轴。各段从下到上："
        "第1段：直径30mm，高度20mm；第2段：直径50mm，高度30mm；"
        "第3段：直径40mm，高度40mm；第4段：直径60mm，高度25mm；"
        "第5段：直径20mm，高度15mm。中心有直径10mm的通孔贯穿全轴。"
        "使用axisymmetric方言。"
    ),
    # "v63_3d_pipe": (
    #     "设计一段三维空间弯曲管路，4个路径点：(0,0,0)→(100,0,50)→(200,50,100)→(300,50,0)。"
    #     "管外径30mm，壁厚4mm（内径22mm）。使用loft_sweep方言。"
    # ),
    "v63_cross_block": (
        "设计一个六面钻孔测试块。100mm×100mm×100mm的正方体。"
        "顶面中心有直径20mm的通孔。前面有2个直径10mm的侧孔，间距40mm。"
        "左面有1个直径8mm的侧孔。右面有1个直径8mm的侧孔。"
        "使用sketch_extrude方言。"
    ),
}


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def call_llm_l1(user_request: str):
    """L1: Route — select dialect."""
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_tool
    from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    config = LlmModelConfig(model='deepseek-v4-pro', base_url='https://api.deepseek.com/beta')
    caller = DeepSeekToolCaller()
    reg = default_registry()

    # Build prompt content with catalog
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import build_level1_routing_prompt
    l1 = build_level1_routing_prompt(user_request, dialect_catalog=reg.export_catalog())

    # Use enum-constrained tool schema
    l1_tool = build_level1_tool()

    tc = caller.call_strict_tool(
        messages=[
            {"role": "system", "content": l1["system"]},
            {"role": "user", "content": l1["user"]},
        ],
        tool_name=l1_tool["function"]["name"],
        tool_description=l1_tool["function"]["description"],
        tool_schema=l1_tool["function"]["parameters"],
        model_config=config,
    )
    l1_args = tc.arguments
    try:
        plan = DialectSelectionPlan.model_validate(l1_args)
    except Exception:
        # DeepSeek v4-pro sometimes omits required sub-fields like skill_version.
        # Patch missing fields and retry validation.
        args = dict(l1_args)
        for skill in args.get("selected_domain_skills", []):
            if not skill.get("skill_version"):
                skill["skill_version"] = "1.0"
        plan = DialectSelectionPlan.model_validate(args)

    # v6.3: Post-process — DeepSeek v4-pro sometimes outputs old legacy base names
    # (e.g. 'axisymmetric_base') despite enum constraints. Remap to current names.
    LEGACY_NAME_MAP = {
        "axisymmetric_base": "axisymmetric",
        "sketch_extrude_base": "sketch_extrude",
        "sketch_profile_base": "sketch_profile",
        "loft_sweep_base": "loft_sweep",
        "shell_housing_base": "shell_housing",
        "composition_base": "composition",
    }
    for sd in plan.selected_dialects:
        if sd.dialect in LEGACY_NAME_MAP:
            sd.dialect = LEGACY_NAME_MAP[sd.dialect]
    return plan


def call_llm_l2(user_request: str, selection_plan):
    """L2: Author — generate RawGcadDocument via strict=False tool calling.

    DeepSeek v4-pro with thinking disabled + strict=False handles the full
    41-variant L2 schema (121KB, no $defs after inline transformation).
    strict=True is NOT used because DeepSeek's internal validation rejects
    complex schemas with 'field anyOf: one of type, anyOf, $ref required'
    despite the schema being structurally correct.
    """
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
        messages=[
            {"role": "system", "content": l2["system"]},
            {"role": "user", "content": l2["user"]},
        ],
        tool_name=l2_tool["function"]["name"],
        tool_description=l2_tool["function"]["description"],
        tool_schema=l2_tool["function"]["parameters"],
        model_config=config,
    )
    return tc.arguments


def _fix_common_llm_hallucinations(doc: dict, selection_plan) -> dict:
    """Post-process LLM output to fix common op/dialect name errors."""
    # Map of known LLM hallucinations → correct names
    # (DeepSeek v4-pro without strict tools invents these)
    OP_ALIASES = {
        # LLM invents these — map to correct dialect.op
        "create_cylinder": ("axisymmetric", "revolve_profile"),
        "cut_center_hole": ("axisymmetric", "cut_center_bore"),
        "cut_hole_circular_pattern": ("axisymmetric", "cut_circular_hole_pattern"),
        "cut_annular_groove": ("axisymmetric", "cut_annular_groove"),
        "cut_rim_slots": ("axisymmetric", "cut_rim_slot_pattern"),
        "create_thread": ("axisymmetric", "cut_internal_thread"),
        "create_external_thread": ("axisymmetric", "cut_external_thread"),
        "add_chamfer": ("axisymmetric", "apply_safe_chamfer"),
        "add_chamfer_se": ("sketch_extrude", "apply_safe_chamfer"),
        "add_fillet": ("sketch_extrude", "apply_safe_fillet"),
        "create_block": ("sketch_extrude", "extrude_rectangle"),
        "cut_hole_se": ("sketch_extrude", "cut_hole"),
        "cut_pocket": ("sketch_extrude", "cut_rectangular_pocket"),
        "cut_hole_grid": ("sketch_extrude", "cut_hole_pattern_linear"),
        "add_boss": ("sketch_extrude", "add_rectangular_boss"),
        "add_rib_se": ("sketch_extrude", "add_rib"),
        # v6.3 V2 ops — LLM sometimes uses these in wrong dialect
        "cut_hole_v2": ("sketch_extrude", "cut_hole"),  # Downgrade V2→V1 for compat
        "drill_hole_3d": ("sketch_extrude", "cut_hole"),  # Downgrade for compat
        "cut_hole_pattern_linear_v2": ("sketch_extrude", "cut_hole_pattern_linear"),
        # No-op nodes
        "remove_holes": None,
        "cleanup": None,
        "compose": None,
        "finalize": None,
    }
    DIALECT_ALIASES = {
        "basic_solid_modeling": "axisymmetric",
        "hole_operations": "axisymmetric",
        "feature_creation": "axisymmetric",
        "block_operations": "sketch_extrude",
        "pattern_operations": "axisymmetric",
        "solid_modeling": "axisymmetric",
        "sketch_modeling": "sketch_extrude",
    }

    # Fix dialect names in nodes
    for node in doc.get("nodes", []):
        old_dialect = node.get("dialect", "")
        if old_dialect in DIALECT_ALIASES:
            node["dialect"] = DIALECT_ALIASES[old_dialect]

        # Fix op names
        old_op = node.get("op", "")
        if old_op in OP_ALIASES:
            mapped = OP_ALIASES[old_op]
            if mapped is None:
                node["_remove"] = True  # Mark for removal
            else:
                node["dialect"] = mapped[0]
                node["op"] = mapped[1]

    # Remove marked nodes
    nodes = doc.get("nodes", [])
    doc["nodes"] = [n for n in nodes if not n.get("_remove")]
    for n in doc["nodes"]:
        n.pop("_remove", None)

    # Fix component dialects
    for comp in doc.get("components", []):
        if comp.get("owner_dialect") in DIALECT_ALIASES:
            comp["owner_dialect"] = DIALECT_ALIASES[comp["owner_dialect"]]

    # Fix selected_dialects
    sel_dialects = doc.get("selected_dialects", doc.get("selected_dialect", []))
    if isinstance(sel_dialects, list):
        for sd in sel_dialects:
            if sd.get("dialect") in DIALECT_ALIASES:
                sd["dialect"] = DIALECT_ALIASES[sd["dialect"]]

    return doc


def run_case(case_id: str, prompt: str, out_dir: Path):
    """Run full Text → STEP pipeline for one case."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    result = {
        "case_id": case_id, "stage": "STARTED",
        "l1_ok": False, "l2_ok": False, "validation_ok": False,
        "runtime_ok": False, "step_ok": False,
        "elapsed_l1_s": 0, "elapsed_l2_s": 0,
        "elapsed_runtime_s": 0, "step_size_kb": 0,
        "errors": [], "metadata_sections": [],
    }

    print(f"  [{case_id}] ", end="", flush=True)

    # ── Stage 1: L1 Routing ──
    t0 = time.time()
    try:
        plan = call_llm_l1(prompt)
        result["l1_ok"] = True
        result["elapsed_l1_s"] = round(time.time() - t0, 1)
        (out_dir / "route_plan.json").write_text(
            json.dumps(plan.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"L1({plan.route_decision}/{plan.selected_dialects[0].dialect if plan.selected_dialects else '?'}, {result['elapsed_l1_s']}s) ", end="", flush=True)
    except Exception as e:
        result["errors"].append(f"L1: {e}")
        print(f"L1_FAIL({e})")
        return result

    # ── Stage 2: L2 Authoring ──
    t0 = time.time()
    try:
        raw_json = call_llm_l2(prompt, plan)
        result["l2_ok"] = True
        result["elapsed_l2_s"] = round(time.time() - t0, 1)
        # Strip llm_validation_hints if present — they're optional
        if "llm_validation_hints" not in raw_json:
            raw_json["llm_validation_hints"] = {}
        (out_dir / "raw_original.json").write_text(
            json.dumps(raw_json, indent=2, ensure_ascii=False), encoding="utf-8")
        n_nodes = len(raw_json.get("nodes", []))
        print(f"L2({n_nodes} nodes, {result['elapsed_l2_s']}s) ", end="", flush=True)
    except Exception as e:
        result["errors"].append(f"L2: {e}")
        print(f"L2_FAIL({e})")
        return result

    # ── Stage 3: Validate + AutoFix + Canonicalize ──
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
    from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw_json)
    autofix_applied = False
    if not report.ok:
        try:
            fixed_doc, af_report = auto_fix_with_report(raw_json, default_registry())
            (out_dir / "autofix_report.json").write_text(
                json.dumps(af_report.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            if af_report.applied:
                (out_dir / "raw_fixed.json").write_text(
                    json.dumps(fixed_doc, indent=2, ensure_ascii=False), encoding="utf-8")
                canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed_doc)
                autofix_applied = True
        except Exception:
            pass

    (out_dir / "validation_report.json").write_text(
        json.dumps(report.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    if canonical is None or not report.ok:
        errors = [i for i in report.issues if i.severity == "error"]
        result["errors"].append(f"Validation: {len(errors)} errors")
        print(f"VAL_FAIL({len(errors)} errs) ", end="", flush=True)
        return result

    result["validation_ok"] = True
    (out_dir / "canonical.json").write_text(
        json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"VAL_OK(autofix={autofix_applied}) ", end="", flush=True)

    # ── Stage 4: Runtime → STEP ──
    from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
    t0 = time.time()
    try:
        run_result = run_canonical_gcad(
            canonical=canonical,
            out_step=out_dir / "output.step",
            metadata_path=out_dir / "output.metadata.json",
            validation_seed=bundle.to_metadata_dict() if bundle else {},
            require_full_validation_seed=False,
        )
        result["elapsed_runtime_s"] = round(time.time() - t0, 1)

        if run_result.ok:
            result["runtime_ok"] = True
            step_size = (out_dir / "output.step").stat().st_size
            result["step_size_kb"] = round(step_size / 1024, 1)
            result["step_ok"] = True
            print(f"RT_OK({result['step_size_kb']}KB, {result['elapsed_runtime_s']}s) ", end="", flush=True)

            # Extract metadata sections
            if (out_dir / "output.metadata.json").exists():
                meta = json.loads((out_dir / "output.metadata.json").read_text(encoding="utf-8"))
                val = meta.get("validation", {})
                result["metadata_sections"] = sorted(val.keys())
                # Check v6.3 sections
                cm = val.get("compiler_middle_end", {})
                plan_rpt = val.get("planning_report", {})
                health = val.get("geometry_health_summary", {})
                print(f"META(cm={cm.get('ok')}, plan={len(plan_rpt.get('issues',[]))} issues, health={health.get('total_ops_checked')} ops)", end="", flush=True)

                if run_result.warnings:
                    (out_dir / "runtime_warnings.json").write_text(
                        json.dumps(run_result.warnings, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            result["errors"].append(f"Runtime: {run_result.error}")
            print(f"RT_FAIL ", end="", flush=True)
    except Exception as e:
        result["elapsed_runtime_s"] = round(time.time() - t0, 1)
        result["errors"].append(f"Runtime exception: {traceback.format_exc()[:200]}")
        print(f"RT_EXC({e}) ", end="", flush=True)

    print()
    return result


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("v6.3 Full Text → STEP Pipeline Test (Compiler Middle-End)")
    print("=" * 70)
    print(f"Cases: {len(TEST_CASES)}")
    print(f"Model: deepseek-v4-pro")
    print(f"Output: {OUT_DIR}")
    print()

    all_results = []
    t_start = time.time()

    for case_id, prompt in TEST_CASES.items():
        case_dir = OUT_DIR / case_id
        result = run_case(case_id, prompt, case_dir)
        all_results.append(result)
        (case_dir / "case_result.json").write_text(
            json.dumps(result, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    total_s = time.time() - t_start
    passed = sum(1 for r in all_results if r.get("step_ok"))
    validated = sum(1 for r in all_results if r.get("validation_ok"))

    print()
    print("=" * 70)
    print(f"RESULTS: {passed}/{len(all_results)} STEP generated, {validated} validated")
    print(f"Total time: {total_s/60:.1f} min")
    for r in all_results:
        status = "PASS" if r.get("step_ok") else ("VAL" if r.get("validation_ok") else "FAIL")
        print(f"  [{status}] {r['case_id']}: L1={r['l1_ok']} L2={r['l2_ok']} VAL={r['validation_ok']} RT={r['runtime_ok']} STEP={r.get('step_size_kb',0)}KB")
        if r["errors"]:
            for e in r["errors"][:2]:
                print(f"    err: {e[:120]}")

    with open(OUT_DIR / "full_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "total": len(all_results), "passed": passed, "validated": validated,
            "elapsed_min": round(total_s / 60, 1), "cases": all_results,
        }, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nResults saved to {OUT_DIR / 'full_results.json'}")
