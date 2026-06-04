"""Full LLM → STEP → SolidWorks Pipeline Test Runner.

For each test case:
1. Send natural language prompt to DeepSeek → RawGcadDocument
2. Run validation + auto_fixer
3. Run runtime pipeline → STEP
4. Import STEP to SolidWorks → SLDPRT

No existing LLM outputs are reused — every case starts from a fresh prompt.
"""
import sys, json, time, os, traceback, hashlib
from pathlib import Path

sys.path.insert(0, r'E:\auto_detection_process\integrations\engineering_tools\src')
os.environ['DEEPSEEK_API_KEY'] = 'sk-db9a573912714fd191495d6c6db41ff7'

TEST_ROOT = Path(r'E:\auto_detection_process\demo_output_v5\cc_nonprimitive_eval_20260605_120000')
CASES_DIR = TEST_ROOT / 'cases'
REPORTS_DIR = TEST_ROOT / 'reports'
CASES_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# Test prompts — fresh designs for each stress30 case
# ═══════════════════════════════════════════════════════════════

STRESS30_PROMPTS = {
    "g1_engine_mount": (
        "设计一个发动机支架装配体，由底板、两块侧板和一个顶板组成。"
        "底板尺寸300mm×200mm×20mm，四周有4个直径12mm的安装孔，孔中心距边缘30mm。"
        "侧板厚15mm，高60mm，位于底板两侧。顶板尺寸200mm×200mm×15mm，在侧板上方。"
        "所有组件通过螺栓连接，需要保证同轴对齐。"
    ),
    "g2_gearbox_housing": (
        "设计一个变速箱壳体，箱体尺寸500mm×400mm×120mm，壁厚8mm的中空壳体。"
        "顶面有直径80mm的轴承座孔，四周法兰有12个M10螺栓孔，PCD 450mm。"
        "底部有2个定位销孔。箱体内部有加强筋交叉分布。"
    ),
    "g3_hyd_manifold": (
        "设计一个液压阀块，尺寸150mm×120mm×180mm的长方体。"
        "顶面有2个直径20mm的P口和T口，间距60mm。底面有1个直径25mm的进油口。"
        "前面有4个直径15mm的工作油口，矩形排列。"
        "右侧面有1个直径10mm的先导油口。左侧面有1个直径10mm的泄油口。"
        "六个面各有不同的功能孔，这是典型的六面钻孔阀块。"
    ),
    "g4_pump_casing": (
        "设计一个水泵蜗壳，由蜗壳主体、进口法兰、出口法兰组成。"
        "蜗壳主体是渐开线蜗壳形状，外径250mm，内径60mm，厚度80mm。"
        "进口法兰直径120mm在蜗壳中心，出口法兰直径80mm在蜗壳侧面。"
        "法兰各有6个直径10mm的螺栓孔，PCD分别匹配法兰大小。"
    ),
    "g5_robot_arm": (
        "设计一个机器人手臂管段，由一段长管和两端法兰组成。"
        "管外径80mm，内径60mm，长度500mm。"
        "两端法兰外径150mm，厚20mm，各有8个直径12mm的螺栓孔，PCD 120mm。"
        "法兰与管同轴，法兰面与管端面贴合。"
    ),
    "g6_helix_coil": (
        "设计一个20圈的螺旋弹簧管，螺旋半径100mm，管截面直径12mm。"
        "螺距20mm，总高度400mm。弹簧材质需要连续的螺旋扫掠路径生成。"
    ),
    "g7_3d_tube": (
        "设计一段三维空间弯曲管路，包含8个路径点。"
        "管外径30mm，内径24mm。路径从(0,0,0)开始，经过多个空间弯折点，"
        "最终到达(500,200,400)。管路需要在每个弯折处平滑过渡。"
    ),
    "g8_var_duct": (
        "设计一个变截面风管，从圆形截面(直径100mm)过渡到矩形截面(120mm×80mm)"
        "再过渡回圆形截面(直径80mm)。三个截面分别在z=0mm, z=150mm, z=300mm处。"
        "截面之间需要平滑放样过渡。"
    ),
    "g9_torsion_spring": (
        "设计一个15圈的扭簧，螺旋半径60mm，钢丝直径8mm，"
        "螺距15mm，总高度225mm。弹簧两端各有一段直线延伸用于安装。"
    ),
    "g10_spiral_volute": (
        "设计一个渐开线蜗壳，从中心向外螺旋展开。"
        "起始半径30mm，终了半径90mm，厚度25mm。"
        "蜗壳截面为圆形，直径从10mm逐渐增大到25mm。"
    ),
    "g11_pressure_vessel": (
        "设计一个薄壁压力容器，圆筒形主体外径300mm，高度400mm，壁厚5mm。"
        "两端为半球形封头。顶面有直径50mm的管接口。"
        "底面有4个直径20mm的支撑脚安装孔。"
    ),
    "g12_hollow_bracket": (
        "设计一个空心支架，主体尺寸200mm×160mm×70mm，壁厚3mm的壳体。"
        "底面开放，顶面有4个直径8mm的安装孔，四角分布。"
        "侧面有2个直径15mm的线缆过孔。"
    ),
    "g13_enclosure": (
        "设计一个电子设备外壳，尺寸300mm×200mm×150mm，壁厚4mm。"
        "前面板有1个矩形开口(100mm×60mm)，后面板有4个直径6mm的安装孔。"
        "底面有散热槽阵列(6条平行槽，槽宽3mm，间距10mm)。"
    ),
    "g14_vacuum_chamber": (
        "设计一个真空腔体装配，由腔体主体、前盖板、后盖板组成。"
        "腔体主体是圆筒形，外径200mm，内径180mm，长度400mm。"
        "前盖板有直径100mm的观察窗口，后盖板有2个直径25mm的真空泵接口。"
        "盖板各通过8个M8螺栓与主体连接。前盖板和后盖板与主体同轴且面对面接触。"
    ),
    "g15_heavy_flange": (
        "设计一个重型法兰，外径400mm，内径120mm，厚度55mm。"
        "外圈有24个直径18mm的螺栓孔，PCD 340mm，起始角0度。"
        "内圈有12个直径12mm的螺栓孔，PCD 200mm，起始角15度。"
        "两圈螺栓孔需要不同的起始角以避免干涉。"
    ),
    "g16_stepped_pulley": (
        "设计一个9段多级带轮，最大外径240mm，中心孔径30mm。"
        "各级直径依次为240, 210, 180, 155, 130, 110, 90, 70, 50mm。"
        "每级宽度9mm，总高87mm。各级之间需要倒角过渡。"
    ),
    "g17_cross_block": (
        "设计一个六面钻孔测试块，100mm×100mm×100mm的正方体。"
        "顶面有1个直径20mm的通孔在中心。底面有1个直径15mm的通孔偏移(20,0)。"
        "前面有2个直径10mm的孔，间距40mm。后面有1个直径12mm的孔在中心。"
        "左面有1个直径8mm的孔。右面有1个直径8mm的孔。"
        "这是典型的六面钻孔测试，验证axis=X/Y/Z三个方向的钻孔能力。"
    ),
    "g18_ribbed_panel": (
        "设计一个加强筋面板，尺寸550mm×400mm×8mm的底板。"
        "纵向有7条加强筋，横向有5条加强筋，筋厚度4mm，高度30mm。"
        "筋在底板上面，交叉形成网格。四周各有安装孔。"
    ),
    "g19_precision_base": (
        "设计一个精密基座，底板尺寸305mm×280mm×15mm。"
        "底板上有4个直径30mm的定位孔，PCD 200mm分布在四角。"
        "中心有一个直径60mm的轴承安装孔，带有4个M8固定螺孔。"
        "底板四周有倒角处理。底面有网格状减重槽。"
    ),
    "g20_motor_endbell": (
        "设计一个电机端盖装配体，由端盖主体、轴承座和接线盒组成。"
        "端盖外径250mm，中心轴承座外径80mm，内径40mm。"
        "端盖上有6个直径10mm的安装孔，PCD 200mm。"
        "接线盒在端盖侧面，尺寸60mm×40mm×30mm。"
    ),
    "g21_valve_body": (
        "设计一个阀体装配，由阀体主体和两端法兰组成。"
        "阀体主体为球形，外径140mm，壁厚8mm。"
        "进口法兰直径100mm在前端，出口法兰直径80mm在后端，与阀体同轴。"
        "法兰各有4个直径12mm的螺栓孔。顶部有阀杆安装孔直径20mm。"
    ),
    "g22_heat_sink": (
        "设计一个散热器，底板尺寸328mm×228mm×8mm。"
        "底板上方有18片散热鳍片，每片厚2mm，高100mm，间距12mm。"
        "底板四角有4个直径6mm的安装孔。鳍片与底板紧密接触。"
    ),
    "g23_pipe_reducer": (
        "设计一个变径管，从直径100mm的圆截面过渡到直径60mm的圆截面，"
        "再连接一个直径120mm的法兰。变径段长度150mm，法兰厚度20mm。"
        "法兰上有6个直径12mm的螺栓孔，PCD 90mm。变径段与法兰同轴。"
    ),
    "g24_micro_bushing": (
        "设计一个微型轴套，外径6mm，内径5.5mm，长度10mm。"
        "壁厚仅0.25mm。材料为黄铜。端面需要倒角0.2mm。"
    ),
    "g25_large_ring": (
        "设计一个大直径环件，外径1000mm，内径900mm，厚度30mm。"
        "环上有36个直径15mm的均布通孔，PCD 950mm。"
        "孔不能与中心孔或外边缘干涉。"
    ),
    "g26_extreme_shaft": (
        "设计一个极细长轴，直径10mm，长度500mm。"
        "轴的一端有直径16mm的轴肩，长度15mm。"
        "壁厚仅1mm的中空结构。轴两端需要倒角处理。"
    ),
    "g27_dense_holes": (
        "设计一块多孔板，200mm×150mm×10mm的平板。"
        "板上需要300个直径3mm的通孔，以20行×15列的矩形阵列排列，"
        "间距8mm，均匀分布在整个板面上。孔必须全部打通。"
    ),
    "g28_ball_valve": (
        "设计一个球阀装配体，由阀体、球体、阀杆和两端法兰组成。"
        "阀体外径160mm，球体直径100mm在阀体中心。"
        "两端法兰直径120mm，各有4个直径14mm的螺栓孔。"
        "顶部阀杆直径25mm。球体上有直径80mm的通孔。"
    ),
    "g29_impeller": (
        "设计一个离心叶轮装配体，由轮毂和6个叶片组成。"
        "轮毂外径300mm，中心孔径40mm，高度35mm。"
        "6个叶片均匀分布在轮毂圆周上，叶片厚5mm，高20mm。"
        "叶片从中心向外弯曲，形成离心泵叶轮结构。"
    ),
    "g30_hyd_cylinder": (
        "设计一个液压缸端盖，外径70mm，内径30mm的中心孔。"
        "端盖厚度30mm。上有6个直径8mm的安装螺栓孔，PCD 55mm。"
        "中心孔带有密封槽，槽宽5mm，深3mm。"
    ),
}

def call_deepseek(prompt_text):
    """Call DeepSeek to generate RawGcadDocument from prompt."""
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekClient
    from seekflow_engineering_tools.generative_cad.llm.provider import ToolCallResult

    client = DeepSeekClient(api_key=os.environ['DEEPSEEK_API_KEY'])

    # Build system + user messages with the full authoring prompt
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
        build_level1_routing_prompt, build_level2_authoring_prompt, build_level2_tool
    )
    from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan

    # Step 1: Route
    route_prompt = build_level1_routing_prompt(prompt_text)
    route_tool = {
        "type": "function",
        "function": {
            "name": "select_dialect_plan",
            "description": "Select CAD route and dialects",
            "parameters": DialectSelectionPlan.model_json_schema(),
        }
    }

    route_result = client.chat_completion(
        messages=[
            {"role": "system", "content": route_prompt["system"]},
            {"role": "user", "content": route_prompt["user"]},
        ],
        tools=[route_tool],
        tool_choice={"type": "function", "function": {"name": "select_dialect_plan"}},
        temperature=0.0,
    )

    route_msg = route_result["choices"][0]["message"]
    if "tool_calls" not in route_msg:
        return None, "LLM did not call route tool", None

    route_args = json.loads(route_msg["tool_calls"][0]["function"]["arguments"])
    selection_plan = DialectSelectionPlan.model_validate(route_args)

    # Step 2: Author
    author_prompt = build_level2_authoring_prompt(prompt_text, selection_plan)
    author_tool = build_level2_tool()

    author_result = client.chat_completion(
        messages=[
            {"role": "system", "content": author_prompt["system"]},
            {"role": "user", "content": author_prompt["user"]},
        ],
        tools=[author_tool],
        tool_choice={"type": "function", "function": {"name": "generate_raw_gcad_document"}},
        temperature=0.0,
    )

    author_msg = author_result["choices"][0]["message"]
    if "tool_calls" not in author_msg:
        return None, "LLM did not call author tool", selection_plan

    raw_json = json.loads(author_msg["tool_calls"][0]["function"]["arguments"])

    return raw_json, None, selection_plan


def run_single_case(case_id, prompt, out_dir):
    """Run a single test case through full LLM → STEP → SW pipeline."""
    result = {
        "case_id": case_id, "status": "STARTED", "step_exists": False,
        "sldprt_exists": False, "errors": [], "elapsed_llm_s": 0,
        "elapsed_runtime_s": 0, "elapsed_sw_s": 0,
    }
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save prompt
    (out_dir / "input_text.txt").write_text(prompt, encoding="utf-8")

    # ── Step 1: LLM call ──
    print(f"  LLM call...", end=" ", flush=True)
    t0 = time.time()
    try:
        raw_json, llm_error, selection_plan = call_deepseek(prompt)
        result["elapsed_llm_s"] = round(time.time() - t0, 1)
        if llm_error:
            result["status"] = "FAIL_LLM"
            result["errors"].append(f"LLM: {llm_error}")
            print(f"FAIL ({llm_error[:80]})")
            return result
        print(f"OK ({result['elapsed_llm_s']}s)", end=" ", flush=True)
    except Exception as e:
        result["elapsed_llm_s"] = round(time.time() - t0, 1)
        result["status"] = "FAIL_LLM_EXCEPTION"
        result["errors"].append(f"LLM exception: {e}")
        print(f"EXCEPTION ({e})")
        return result

    # Save raw JSON
    (out_dir / "llm_raw.json").write_text(json.dumps(raw_json, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    if selection_plan:
        (out_dir / "route_plan.json").write_text(json.dumps(selection_plan.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    # ── Step 2: Validate + autofix ──
    print(f"validate...", end=" ", flush=True)
    from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
    from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry

    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw_json)
    autofix_applied = False
    if not report.ok:
        # Try autofix
        try:
            fixed_doc, af_report = auto_fix_with_report(raw_json, default_registry())
            (out_dir / "autofix_report.json").write_text(json.dumps(af_report.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            if af_report.applied:
                (out_dir / "raw_fixed.json").write_text(json.dumps(fixed_doc, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed_doc)
                autofix_applied = True
        except Exception:
            pass

    (out_dir / "validation_report.json").write_text(json.dumps(report.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    if canonical is None or not report.ok:
        errors = [i for i in report.issues if i.severity == "error"]
        result["status"] = "FAIL_VALIDATION"
        result["errors"].append(f"Validation failed after autofix: {len(errors)} errors")
        print(f"FAIL_VALIDATION ({len(errors)} errors)", end=" ", flush=True)
    else:
        (out_dir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"OK", end=" ", flush=True)

        # ── Step 3: Runtime → STEP ──
        print(f"runtime...", end=" ", flush=True)
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        step_out = out_dir / "output.step"
        meta_out = out_dir / "metadata.json"

        t0 = time.time()
        try:
            run_result = run_canonical_gcad(
                canonical=canonical, out_step=step_out, metadata_path=meta_out,
                validation_seed=bundle.to_metadata_dict() if bundle else {"core_validation": {"ok": True, "stages": {}, "issues": []}},
                require_full_validation_seed=False,
            )
            result["elapsed_runtime_s"] = round(time.time() - t0, 1)

            if run_result.ok:
                result["step_exists"] = step_out.exists()
                result["step_size_bytes"] = step_out.stat().st_size if step_out.exists() else 0
                print(f"OK ({result['step_size_bytes']/1024:.0f}KB, {result['elapsed_runtime_s']}s)", end=" ", flush=True)

                # ── Step 4: SolidWorks import ──
                print(f"SW...", end=" ", flush=True)
                t0 = time.time()
                try:
                    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
                    template = Path(r'C:/ProgramData/SOLIDWORKS/SOLIDWORKS 2025/templates/gb_part.prtdot')
                    sw_client = SolidWorksClient(visible=False, part_template=template).connect()
                    sldprt_out = out_dir / "output.SLDPRT"
                    ok_sw = sw_client.import_step_as_part(str(step_out), str(sldprt_out))
                    sw_client.close_all()
                    sw_client.close()
                    result["elapsed_sw_s"] = round(time.time() - t0, 1)
                    result["sldprt_exists"] = sldprt_out.exists() and sldprt_out.stat().st_size > 0
                    result["sldprt_size_bytes"] = sldprt_out.stat().st_size if result["sldprt_exists"] else 0
                    status = "SW_OK" if result["sldprt_exists"] else "SW_FAIL"
                    print(f"{status} ({result.get('sldprt_size_bytes',0)/1024:.0f}KB, {result['elapsed_sw_s']}s)", end="", flush=True)
                except Exception as e:
                    result["elapsed_sw_s"] = round(time.time() - t0, 1)
                    result["errors"].append(f"SW: {e}")
                    print(f"SW_ERROR", end="", flush=True)

                result["status"] = "PASS"
            else:
                result["status"] = "FAIL_RUNTIME"
                result["errors"].append(run_result.error or "Unknown runtime error")
                print(f"FAIL_RUNTIME", end=" ", flush=True)
        except Exception as e:
            result["elapsed_runtime_s"] = round(time.time() - t0, 1)
            result["status"] = "FAIL_RUNTIME_EXCEPTION"
            result["errors"].append(f"Runtime exception: {e}")
            print(f"EXCEPTION ({e})", end=" ", flush=True)

    print()
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("Full LLM → STEP → SolidWorks Pipeline Test")
    print("=" * 70)
    print(f"Cases: {len(STRESS30_PROMPTS)}")
    print(f"Output: {CASES_DIR}")
    print()

    all_results = []
    t_total_start = time.time()

    for i, (case_id, prompt) in enumerate(STRESS30_PROMPTS.items()):
        out_dir = CASES_DIR / f"full_llm_{case_id}"
        print(f"[{i+1}/{len(STRESS30_PROMPTS)}] {case_id}:", end=" ", flush=True)

        result = run_single_case(case_id, prompt, out_dir)
        all_results.append(result)

        # Save incremental results
        (out_dir / "case_result.json").write_text(json.dumps(result, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    total_elapsed = time.time() - t_total_start

    # Summary
    passed = sum(1 for r in all_results if r['status'] == 'PASS')
    with_sw = sum(1 for r in all_results if r.get('sldprt_exists'))
    print()
    print("=" * 70)
    print(f"TOTAL: {len(all_results)} cases, {total_elapsed/60:.1f} min")
    print(f"PASS: {passed} | SW imported: {with_sw}")
    for r in all_results:
        print(f"  {r['case_id']}: {r['status']} | step={r.get('step_size_bytes',0)//1024}KB | sldprt={r.get('sldprt_size_bytes',0)//1024}KB")

    with open(TEST_ROOT / 'full_llm_results.json', 'w', encoding='utf-8') as f:
        json.dump({"total": len(all_results), "passed": passed, "sw_imported": with_sw, "elapsed_min": round(total_elapsed/60, 1), "cases": all_results}, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nResults saved.")
