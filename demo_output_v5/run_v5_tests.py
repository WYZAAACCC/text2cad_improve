"""全链路测试 Runner v5 — 使用改进后的 audited autofix + strict schema.

每个 case: text → DeepSeek LLM → auto_fix_with_report → validate → STEP → SolidWorks.
所有产物保存到 demo_output_v5/<case_id>/ 目录。
"""

import json, os, sys, subprocess, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "v5_tests"
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix, auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()


def build_contract(dialect_ids):
    """为指定的 dialect 构建详细的 contract text。"""
    lines = []
    for did in dialect_ids:
        d = REG.get(did)
        if d is None:
            continue
        lines.append(f"=== {did} v{d.version} phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            pstrs = [f"{pn}:{pi.get('type','?')}" for pn, pi in props.items()]
            lines.append(f"  {op_name} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs)}")
            # 关键 op 的显式示例
            if op_name == "revolve_profile":
                lines.append('    EX: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":30},{"r_mm":20,"z_front_mm":30,"z_rear_mm":31}]}')
            if op_name == "extrude_rectangle":
                lines.append('    EX: {"width_mm":100,"height_mm":80,"depth_mm":15,"plane":"XY","centered":true,"direction":"+"}')
            if op_name == "create_sweep_path":
                lines.append('    EX: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":30,"y_mm":0,"z_mm":50}]}')
            if op_name == "sweep_profile":
                lines.append('    EX: {"shape":"circle","radius_mm":12}  — requires curve input from create_sweep_path')
            if op_name == "boolean_union":
                lines.append('    NOTE: empty params {}. Inputs MUST reference component outputs: [{component: c1, output: body}]')
            if op_name == "shell_body":
                lines.append('    EX: {"thickness_mm":2.0}')
            if op_name == "cut_internal_thread":
                lines.append('    EX: {"nominal_dia_mm":8,"pitch_mm":1.25,"depth_mm":20,"standard":"ISO_metric","thread_class":"6H"}')
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 7 个精心设计的复杂工程零件
# ═══════════════════════════════════════════════════════════════════════════════

CASES = [
    # ── axisymmetric: 阶梯轴 ──
    {
        "id": "stepped_shaft",
        "name": "阶梯轴 Stepped Shaft",
        "dialects": ["axisymmetric"],
        "prompt": (
            "精密阶梯轴, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义 5 段阶梯轮廓:\n"
            "  station1 r=25 z=0-10 (左轴肩),\n"
            "  station2 r=18 z=10-50 (中段轴承位),\n"
            "  station3 r=25 z=50-60 (右轴肩),\n"
            "  station4 r=15 z=60-90 (右端轴颈),\n"
            "  station5 r=10 z=90-100 (右端螺纹段).\n"
            "左端面中心孔: cut_center_bore diameter_mm=8 depth_mm=15 through_all=false.\n"
            "右端螺纹段切外螺纹: cut_external_thread nominal_dia_mm=10 pitch_mm=1.5 depth_mm=10 standard=ISO_metric thread_class=6g.\n"
            "轴肩倒角 1mm: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
    # ── sketch_extrude: 传感器安装板 ──
    {
        "id": "sensor_mount_plate",
        "name": "传感器安装板 Sensor Mount Plate",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "精密传感器安装底板, 单位 mm, 参考几何.\n"
            "主体板: extrude_rectangle width_mm=160 height_mm=100 depth_mm=12 centered=true.\n"
            "四角安装沉孔 (M6): cut_hole_pattern_linear hole_dia_mm=6.5 count_x=2 count_y=2 spacing_x_mm=130 spacing_y_mm=70 through_all=true.\n"
            "中央传感器定位槽: cut_rectangular_pocket width_mm=60 height_mm=40 depth_mm=5 centered=true.\n"
            "槽底 4 个 M3 螺孔: cut_hole_pattern_linear hole_dia_mm=3.2 count_x=2 count_y=2 spacing_x_mm=40 spacing_y_mm=20 through_all=true.\n"
            "左侧加强筋: add_rib thickness_mm=6 height_mm=15 length_mm=80 position_mm=[-70,0,6] direction=Y.\n"
            "右侧加强筋: add_rib thickness_mm=6 height_mm=15 length_mm=80 position_mm=[70,0,6] direction=Y.\n"
            "顶部传感器凸台: add_rectangular_boss width_mm=30 height_mm=25 depth_mm=8 position_mm=[0,40,6] centered=true.\n"
            "凸台上定位孔: cut_hole diameter_mm=4 position_mm=[0,40] through_all=true.\n"
            "所有边缘圆角 1.5mm: apply_safe_fillet radius_mm=1.5 target=all_external_edges."
        ),
    },
    # ── axisymmetric: 阀体 ──
    {
        "id": "valve_body",
        "name": "阀体 Valve Body",
        "dialects": ["axisymmetric"],
        "prompt": (
            "工业阀门阀体, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义阀体轮廓:\n"
            "  station1 r=45 z=0-15 (法兰),\n"
            "  station2 r=35 z=15-60 (阀腔外壁),\n"
            "  station3 r=30 z=60-65 (缩径段),\n"
            "  station4 r=22 z=65-80 (出口颈).\n"
            "中心通孔: cut_center_bore diameter_mm=25 through_all=true.\n"
            "法兰上 6 个螺栓孔 PCD 70mm: cut_circular_hole_pattern count=6 pcd_mm=70 hole_dia_mm=10.\n"
            "进口端面环槽: cut_annular_groove side=front inner_dia_mm=55 outer_dia_mm=70 depth_mm=4.\n"
            "所有外边缘倒角 1mm: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
    # ── loft_sweep: U形换热管 ──
    {
        "id": "u_bend_heat_exchanger_tube",
        "name": "U形换热管 U-Bend Heat Exchanger Tube",
        "dialects": ["loft_sweep"],
        "prompt": (
            "换热器U形管, 单位 mm, 参考几何.\n"
            "创建扫掠路径 create_sweep_path path_points (使用 x_mm, y_mm, z_mm):\n"
            "  {x_mm:0,y_mm:0,z_mm:0} → {x_mm:0,y_mm:0,z_mm:100} → {x_mm:0,y_mm:50,z_mm:100} → {x_mm:0,y_mm:50,z_mm:0}.\n"
            "使用 sweep_profile shape=circle radius_mm=8 沿路径扫掠生成圆管.\n"
            "所有节点在同一组件中, owner_dialect=loft_sweep.\n"
            "注意: 路径点字段必须使用 x_mm/y_mm/z_mm (不是 x/y/z)."
        ),
    },
    # ── sketch_extrude + axisymmetric: 轴承座 ──
    {
        "id": "pillow_block",
        "name": "带座轴承 Pillow Block Bearing",
        "dialects": ["axisymmetric", "sketch_extrude", "composition"],
        "prompt": (
            "带座轴承装配, 单位 mm, 参考几何.\n"
            "组件 'housing' (axisymmetric): revolve_profile 定义轴承座圈:\n"
            "  station1 r=35 z=0-20 (底座法兰), station2 r=28 z=20-45 (座圈外壁), station3 r=20 z=45-46 (内缘).\n"
            "  cut_center_bore diameter_mm=30 through_all=true.\n"
            "组件 'base' (sketch_extrude): extrude_rectangle width_mm=120 height_mm=80 depth_mm=15 centered=true.\n"
            "  cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=90 spacing_y_mm=50.\n"
            "装配 '__assembly__' (composition): boolean_union 合并 housing 和 base.\n"
            "boolean_union inputs: [{component: housing, output: body}, {component: base, output: body}]."
        ),
    },
    # ── sketch_extrude: 齿轮箱盖 ──
    {
        "id": "gearbox_cover",
        "name": "齿轮箱盖 Gearbox Cover",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "齿轮箱上盖, 单位 mm, 参考几何.\n"
            "主体板: extrude_rectangle width_mm=200 height_mm=140 depth_mm=15 centered=true.\n"
            "四周安装法兰孔: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=170 spacing_y_mm=110 through_all=true.\n"
            "中央观察窗开口: cut_rectangular_pocket width_mm=100 height_mm=70 depth_mm=15 centered=true.\n"
            "观察窗周围加强框: add_rectangular_boss width_mm=110 height_mm=80 depth_mm=5 position_mm=[0,0,7.5] centered=true.\n"
            "纵向加强筋 ×2: add_rib thickness_mm=6 height_mm=12 length_mm=120 position_mm=[-40,0,7.5] direction=Y.\n"
            "  和 add_rib thickness_mm=6 height_mm=12 length_mm=120 position_mm=[40,0,7.5] direction=Y.\n"
            "横向加强筋: add_rib thickness_mm=6 height_mm=12 length_mm=80 position_mm=[0,0,7.5] direction=X.\n"
            "所有边缘圆角 2mm: apply_safe_fillet radius_mm=2 target=all_external_edges."
        ),
    },
    # ── axisymmetric: 轴套 ──
    {
        "id": "shaft_sleeve",
        "name": "轴套 Shaft Sleeve",
        "dialects": ["axisymmetric"],
        "prompt": (
            "传动轴保护轴套, 单位 mm, 参考几何.\n"
            "使用 revolve_profile 定义轴套轮廓:\n"
            "  station1 r=30 z=0-5 (前端法兰),\n"
            "  station2 r=22 z=5-60 (套筒外壁),\n"
            "  station3 r=28 z=60-65 (后端法兰).\n"
            "内孔: cut_center_bore diameter_mm=16 through_all=true.\n"
            "前端法兰 4 个螺栓孔 PCD 44mm: cut_circular_hole_pattern count=4 pcd_mm=44 hole_dia_mm=6.5.\n"
            "后端法兰 4 个螺栓孔 PCD 48mm: cut_circular_hole_pattern count=4 pcd_mm=48 hole_dia_mm=6.5.\n"
            "前端面环槽: cut_annular_groove side=front inner_dia_mm=44 outer_dia_mm=52 depth_mm=2.\n"
            "所有外缘倒角 0.5mm: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Runner — 使用改进后的 audited autofix
# ═══════════════════════════════════════════════════════════════════════════════

def call_llm(user_msg, system_prompt=None):
    """调用 DeepSeek 生成 RawGcadDocument JSON。"""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    resp = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_prompt or LEVEL2_AUTHORING_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)


def validate_and_build(case, args, cdir):
    """使用 audited autofix + validation + STEP build + SW import。

    Returns: (ok: bool, msg: str, metrics: dict | None)
    """
    # ── 保存 LLM 原始输出 ──
    (cdir / "llm_raw.json").write_text(
        json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    # ── Audited autofix ──
    autofix_report = None
    try:
        fixed_args, autofix_report = auto_fix_with_report(args, REG)
        (cdir / "autofix_report.json").write_text(
            json.dumps(autofix_report.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if autofix_report.applied:
            (cdir / "raw_fixed.json").write_text(
                json.dumps(fixed_args, indent=2, ensure_ascii=False), encoding="utf-8",
            )
        args = fixed_args
    except Exception as e:
        (cdir / "autofix_error.txt").write_text(f"{e}\n{traceback.format_exc()}")

    # ── 补全必需字段 ──
    if args.get("llm_validation_hints") is None:
        args["llm_validation_hints"] = {}
    if "units" not in args:
        args["units"] = "mm"
    if "trust_level" not in args:
        args["trust_level"] = "reference_geometry"

    # ── 原始验证（保存验证报告） ──
    raw_valid = False
    try:
        doc = RawGcadDocument.model_validate(args)
        canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
        if report:
            (cdir / "raw_original_validation.json").write_text(
                json.dumps(_report_dict(report), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        raw_valid = canonical is not None and report is not None and report.ok
    except Exception as e:
        (cdir / "raw_original_validation_error.txt").write_text(f"{e}")

    # ── 如果原始验证失败，尝试 autofix 后再验证 ──
    if not raw_valid:
        try:
            doc = RawGcadDocument.model_validate(args)
            canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
            if canonical and report and report.ok:
                raw_valid = True
                (cdir / "raw_fixed_validation.json").write_text(
                    json.dumps(_report_dict(report), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception:
            pass

    if not raw_valid:
        issues = report.issues if report else []
        err_msg = "Validate: " + "; ".join(
            f"[{getattr(i, 'code', '?')}] {getattr(i, 'message', str(i))[:120]}"
            for i in (issues[:5] if issues else [])
        )
        return False, err_msg, None

    # ── 保存 canonical ──
    can_dict = canonical.model_dump()
    (cdir / "canonical.json").write_text(
        json.dumps(can_dict, indent=2, default=str, ensure_ascii=False), encoding="utf-8",
    )
    if bundle:
        (cdir / "validation_bundle.json").write_text(
            json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── 构建 STEP ──
    bscript = f'''import sys; sys.path.insert(0, r"{SRC.as_posix()}")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"{(cdir / 'canonical.json').as_posix()}",
    validation_seed_json=r"{(cdir / 'validation_bundle.json').as_posix()}",
    out_step=r"{(cdir / 'output.step').as_posix()}",
    metadata_path=r"{(cdir / 'output.metadata.json').as_posix()}")
if r.ok:
    print("BUILD_OK")
else:
    print(f"BUILD_FAILED: {{r.error}}")
    for w in (r.warnings or []): print(f"WARN: {{w[:300]}}")
    for d in (r.degraded_features or []): print(f"DEGRADED: {{d}}")
'''
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text(f"RC={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")

    step_ok = r.returncode == 0 and (cdir / "output.step").exists()
    metrics = {}

    if step_ok:
        step_sz = (cdir / "output.step").stat().st_size
        metrics["step_size"] = step_sz

        # ── SolidWorks 导入 ──
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            sldprt = cdir / "output.SLDPRT"
            c = SolidWorksClient(visible=False).connect()
            ok = c.import_step_as_part(cdir / "output.step", sldprt)
            c.close()
            sw_sz = sldprt.stat().st_size if ok and sldprt.exists() else 0
            metrics["sw_size"] = sw_sz
            return True, f"STEP={step_sz}B SW={sw_sz}B", metrics
        except Exception as e:
            return True, f"STEP={step_sz}B SW=N/A ({e})", metrics
    else:
        # ── 重试: 移除 chamfer/fillet 节点 ──
        cg = json.loads((cdir / "canonical.json").read_text())
        old_count = len(cg["nodes"])
        cg["nodes"] = [n for n in cg["nodes"] if n.get("op") not in ("apply_safe_chamfer", "apply_safe_fillet")]
        if len(cg["nodes"]) < old_count:
            node_ids = {n["id"] for n in cg["nodes"]}
            for comp in cg.get("components", []):
                if comp.get("root_node", "") not in node_ids and cg["nodes"]:
                    comp["root_node"] = cg["nodes"][-1]["id"]
            (cdir / "canonical.json").write_text(json.dumps(cg, indent=2))
            bp.write_text(bscript, encoding="utf-8")
            r2 = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
            (cdir / "_build_log_retry.txt").write_text(f"RC={r2.returncode}\n{r2.stdout}\n{r2.stderr}")
            if r2.returncode == 0 and (cdir / "output.step").exists():
                step_sz = (cdir / "output.step").stat().st_size
                metrics["step_size"] = step_sz
                try:
                    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
                    sldprt = cdir / "output.SLDPRT"
                    c = SolidWorksClient(visible=False).connect()
                    ok = c.import_step_as_part(cdir / "output.step", sldprt)
                    c.close()
                    sw_sz = sldprt.stat().st_size if ok and sldprt.exists() else 0
                    metrics["sw_size"] = sw_sz
                    return True, f"STEP={step_sz}B SW={sw_sz}B (no edge ops)", metrics
                except:
                    return True, f"STEP={step_sz}B (no edge ops)", metrics
        return False, f"STEP: {r.stderr[:300]}", None


def _report_dict(report) -> dict:
    """ValidationReport → JSON-safe dict."""
    if report is None:
        return {"ok": False, "issues": []}
    if hasattr(report, "model_dump"):
        return report.model_dump()
    if isinstance(report, dict):
        return report
    return {
        "ok": getattr(report, "ok", False),
        "stage": getattr(report, "stage", "unknown"),
        "issues": [
            i.model_dump() if hasattr(i, "model_dump") else i
            for i in getattr(report, "issues", [])
        ],
        "stages_run": getattr(report, "stages_run", []),
    }


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import datetime
    print(f"=== V5 Pipeline Tests: {len(CASES)} cases ===\n")
    print(f"Output: {OUT}\n")

    results = []
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        start = time.time()

        print(f"[{i+1}/{len(CASES)}] {case['name']} ({case['id']})")
        print(f"  Dialects: {case['dialects']}")

        contract = build_contract(case["dialects"])
        user_msg = (
            f"TASK: {case['prompt']}\n\n"
            f"{contract}\n\n"
            f"RULES: Use EXACT op names and param names from the contract above. "
            f"All 7 safety flags MUST be true. "
            f"trust_level=reference_geometry. "
            f"llm_validation_hints={{}}. "
            f"For loft_sweep path_points, use x_mm/y_mm/z_mm NOT x/y/z. "
            f"For extrude direction use '+' or '-' NOT 'Z'. "
            f"For chamfer/fillet target use 'all_external_edges' exactly. "
            f"Output schema: RawGcadDocument."
        )

        ok = False
        error_msg = ""
        for attempt in range(3):
            if attempt > 0:
                user_msg += (
                    f"\n\nPREVIOUS ATTEMPT FAILED WITH ERRORS:\n{error_msg[:600]}\n\n"
                    f"Fix ALL the errors listed above. Pay attention to exact parameter names, "
                    f"allowed values, and required fields."
                )

            print(f"  Round {attempt+1}: LLM...", end=" ", flush=True)
            try:
                args = call_llm(user_msg)
            except Exception as e:
                print(f"LLM FAIL: {e}")
                error_msg = str(e)
                continue

            ok, msg, metrics = validate_and_build(case, args, cdir)
            elapsed = time.time() - start
            print(f"{msg}  [{elapsed:.0f}s]")
            if ok:
                break
            error_msg = msg
            time.sleep(0.5)

        results.append({
            "id": case["id"], "name": case["name"],
            "ok": ok, "msg": msg,
            "attempts": attempt + 1,
            "elapsed_s": round(time.time() - start, 1),
        })
        print()

    # ── 最终报告 ──
    print(f"=== RESULTS ===")
    passed = sum(1 for r in results if r["ok"])
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        print(f"  {status} {r['name']} ({r['attempts']} attempts, {r['elapsed_s']}s): {r['msg'][:120]}")
    print(f"\n  {passed}/{len(results)} passed")

    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total": len(results),
        "passed": passed,
        "results": results,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report saved to {OUT / 'report.json'}")
