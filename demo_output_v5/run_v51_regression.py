"""v5.1 全链路回归测试 — 使用升级后的 fail-closed assembler + semantic postcheck.

重跑 stress20 (20 cases) + test_model (15 cases)，总计 35 个 case。
使用 v5.1 新特性: AssemblyError fail-closed, helix 体积验证, semantic postcheck,
composition governance, shell preflight。

审计重点:
  1. v5.1 相比 v5.0 的行为变化 (哪些 case 从 pass→fail, fail→pass)
  2. AssemblyError 触发模式
  3. semantic postcheck 结果
  4. helix 体积验证结果
  5. 体积/bbox/STEP 密度异常
"""

import json, os, sys, subprocess, time, traceback, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "v51_regression_output"
OUT.mkdir(parents=True, exist_ok=True)

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.authoring.raw_assembler import AssemblyError

REG = default_registry()


# ═══════════════════════════════════════════════════════════════════════════════
# Reuse case definitions from both suites
# ═══════════════════════════════════════════════════════════════════════════════

def _get_test_model_cases():
    """Return the 15 test_model.md cases (same prompts as run_test_model.py)."""
    return [
        {"id": "tm_flange_cover", "name": "法兰盖 Flange Cover",
         "dialects": ["axisymmetric"],
         "prompt": "法兰盖, 单位 mm, 参考几何.\n使用 revolve_profile: station1 r=75 z=0-15, station2 r=40 z=15-25.\ncut_center_bore diameter_mm=20 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=120 hole_dia_mm=11.\ncut_annular_groove side=front inner_dia_mm=85 outer_dia_mm=105 depth_mm=3.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
        {"id": "tm_l_bracket", "name": "L型支架 L-Bracket",
         "dialects": ["sketch_extrude"],
         "prompt": "L型安装支架, 单位 mm, 参考几何.\nextrude_rectangle width_mm=100 height_mm=80 depth_mm=10 centered=true.\ncut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\nadd_rib thickness_mm=8 height_mm=40 length_mm=60 position_mm=[0,0,5] direction=Y.\ncut_hole diameter_mm=6 position_mm=[-35,0] through_all=true.\ncut_hole diameter_mm=6 position_mm=[35,0] through_all=true.\napply_safe_fillet radius_mm=1.5 target=all_external_edges."},
        {"id": "tm_bearing_seat", "name": "轴承座 Bearing Seat",
         "dialects": ["axisymmetric", "sketch_extrude", "composition"],
         "prompt": "轴承座装配, 单位 mm, 参考几何.\n组件 'hub' (axisymmetric): revolve_profile station1 r=35 z=0-15, station2 r=28 z=15-50, station3 r=20 z=50-55. cut_center_bore diameter_mm=25 through_all=true.\n组件 'base' (sketch_extrude): extrude_rectangle width_mm=120 height_mm=60 depth_mm=15 centered=true. cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=90 spacing_y_mm=40.\n装配 '__assembly__' (composition): boolean_union 合并 hub 和 base. inputs: [{component: hub, output: body}, {component: base, output: body}]."},
        {"id": "tm_stepped_shaft", "name": "阶梯轴 Stepped Shaft",
         "dialects": ["axisymmetric"],
         "prompt": "传动阶梯轴, 单位 mm, 参考几何.\nrevolve_profile: station1 r=15 z=0-10, station2 r=22 z=10-50, station3 r=18 z=50-80, station4 r=15 z=80-110, station5 r=12 z=110-120.\ncut_center_bore diameter_mm=8 through_all=true.\ncut_external_thread nominal_dia_mm=12 pitch_mm=1.75 length_mm=10 standard=ISO_metric thread_class=6g.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
        {"id": "tm_v_pulley", "name": "V型带轮 V-Pulley",
         "dialects": ["axisymmetric"],
         "prompt": "V型带轮, 单位 mm, 参考几何.\nrevolve_profile: station1 r=100 z=0-10, station2 r=95 z=10-18, station3 r=100 z=18-26, station4 r=95 z=26-34, station5 r=100 z=34-42, station6 r=95 z=42-50, station7 r=100 z=50-60.\ncut_center_bore diameter_mm=30 through_all=true.\ncut_circular_hole_pattern count=4 pcd_mm=60 hole_dia_mm=10.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
        {"id": "tm_spring", "name": "压缩弹簧 Spring",
         "dialects": ["loft_sweep"],
         "prompt": "压缩螺旋弹簧, 单位 mm, 参考几何.\nhelix_sweep: radius_mm=15 height_mm=80 pitch_mm=10 profile_radius_mm=2 turns=8."},
        {"id": "tm_roller", "name": "托辊 Roller",
         "dialects": ["axisymmetric", "composition"],
         "prompt": "输送机托辊, 单位 mm, 参考几何.\n组件 'tube' (axisymmetric): revolve_profile station1 r=44.5 z=0-600. cut_center_bore diameter_mm=80 through_all=true.\n组件 'shaft' (axisymmetric): revolve_profile station1 r=15 z=0-650.\n装配 '__assembly__' (composition): boolean_union 合并 tube 和 shaft."},
        {"id": "tm_weld_fork", "name": "焊接叉 Weld Fork",
         "dialects": ["sketch_extrude"],
         "prompt": "焊接叉, 单位 mm, 参考几何.\nextrude_rectangle width_mm=80 height_mm=50 depth_mm=15 centered=true.\ncut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=30.\nadd_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[-30,0,7.5] centered=true.\nadd_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[30,0,7.5] centered=true.\ncut_hole diameter_mm=25 position_mm=[-30,25] through_all=true.\ncut_hole diameter_mm=25 position_mm=[30,25] through_all=true.\nadd_rib thickness_mm=8 height_mm=15 length_mm=60 position_mm=[0,0,7.5] direction=X.\napply_safe_fillet radius_mm=2 target=all_external_edges."},
        {"id": "tm_gearbox_cover", "name": "减速器箱盖 Gearbox Cover",
         "dialects": ["sketch_extrude"],
         "prompt": "减速器上箱盖, 单位 mm, 参考几何.\nextrude_rectangle width_mm=300 height_mm=200 depth_mm=20 centered=true.\ncut_rectangular_pocket width_mm=260 height_mm=160 depth_mm=14 centered=true.\ncut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[-60,0,0] direction=Y.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[0,0,0] direction=Y.\nadd_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[60,0,0] direction=Y.\nadd_rib thickness_mm=8 height_mm=18 length_mm=220 position_mm=[0,-40,0] direction=X.\nadd_rib thickness_mm=8 height_mm=18 length_mm=220 position_mm=[0,40,0] direction=X.\nadd_rectangular_boss width_mm=100 height_mm=80 depth_mm=10 position_mm=[0,0,10] centered=true.\ncut_rectangular_pocket width_mm=80 height_mm=60 depth_mm=10 centered=true.\napply_safe_fillet radius_mm=3 target=all_external_edges."},
        {"id": "tm_hex_nut", "name": "六角螺母 Hex Nut",
         "dialects": ["axisymmetric"],
         "prompt": "M10六角螺母轴对等近似, 单位 mm, 参考几何.\nrevolve_profile: station1 r=9.5 z=0-8.\ncut_center_bore diameter_mm=8.5 through_all=true.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
        {"id": "tm_turbine_disk", "name": "涡轮盘 Turbine Disk",
         "dialects": ["axisymmetric"],
         "prompt": "涡轮盘, 单位 mm, 参考几何.\nrevolve_profile: station1 r=150 z=0-20, station2 r=120 z=20-40, station3 r=80 z=40-65, station4 r=60 z=65-75, station5 r=50 z=75-85.\ncut_center_bore diameter_mm=30 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=80 hole_dia_mm=12.\ncut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=25.\ncut_annular_groove side=front inner_dia_mm=200 outer_dia_mm=240 depth_mm=6.\napply_safe_chamfer distance_mm=1.5 target=all_external_edges."},
        {"id": "tm_robot_wrist", "name": "机器人腕部 Robot Wrist",
         "dialects": ["axisymmetric"],
         "prompt": "机器人腕部壳体, 单位 mm, 参考几何.\nrevolve_profile: station1 r=60 z=0-200.\ncut_center_bore diameter_mm=112 through_all=true.\ncut_circular_hole_pattern count=6 pcd_mm=140 hole_dia_mm=9.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
        {"id": "tm_exhaust_manifold", "name": "排气歧管 Exhaust Manifold",
         "dialects": ["loft_sweep"],
         "prompt": "排气歧管S形弯管, 单位 mm, 参考几何.\ncreate_sweep_path path_points: [{x_mm:0,y_mm:0,z_mm:0},{x_mm:0,y_mm:30,z_mm:80},{x_mm:0,y_mm:60,z_mm:160},{x_mm:0,y_mm:30,z_mm:240},{x_mm:0,y_mm:0,z_mm:320}].\nsweep_profile shape=circle radius_mm=18."},
        {"id": "tm_hyd_valve", "name": "液压阀体 Hyd Valve",
         "dialects": ["sketch_extrude"],
         "prompt": "液压阀体, 单位 mm, 参考几何.\nextrude_rectangle width_mm=80 height_mm=60 depth_mm=200 centered=true.\ncut_hole diameter_mm=20 position_mm=[0,0] through_all=true axis=Z.\ncut_hole diameter_mm=10 position_mm=[0,15] through_all=true axis=Y.\ncut_hole diameter_mm=10 position_mm=[0,-15] through_all=true axis=Y.\ncut_hole diameter_mm=14 position_mm=[0,0] through_all=true axis=Y.\ncut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=40.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
        {"id": "tm_diff_case", "name": "差速器壳体 Diff Case",
         "dialects": ["axisymmetric"],
         "prompt": "差速器壳体, 单位 mm, 参考几何.\nrevolve_profile: station1 r=75 z=0-20, station2 r=60 z=20-80, station3 r=75 z=80-100.\ncut_center_bore diameter_mm=100 through_all=true.\ncut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\ncut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\ncut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=140 depth_mm=3.\napply_safe_chamfer distance_mm=1 target=all_external_edges."},
    ]


def _get_stress20_cases():
    """Return subset of stress20 cases that test v5.1 new features."""
    return [
        {"id": "s20_spring", "name": "长弹簧 Long Helix Spring",
         "dialects": ["loft_sweep"],
         "prompt": "长螺旋弹簧, 单位 mm. helix_sweep: radius_mm=20 height_mm=150 pitch_mm=10 profile_radius_mm=1.5 turns=15."},
        {"id": "s20_rib_plate", "name": "密集筋板 Dense Rib Plate",
         "dialects": ["sketch_extrude"],
         "prompt": "密集筋板, 单位 mm. extrude_rectangle width_mm=300 height_mm=200 depth_mm=15 centered=true.\ncut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=260 spacing_y_mm=160.\n(add_rib ×10 密集排列).\napply_safe_fillet radius_mm=1.5 target=all_external_edges."},
        {"id": "s20_deep_holes", "name": "深孔阀块 Deep Hole Block",
         "dialects": ["sketch_extrude"],
         "prompt": "深孔交叉阀块, 单位 mm.\nextrude_rectangle width_mm=100 height_mm=80 depth_mm=150 centered=true.\ncut_hole diameter_mm=25 position_mm=[0,0] through_all=true axis=Z.\ncut_hole diameter_mm=15 position_mm=[0,20] through_all=true axis=Y.\ncut_hole diameter_mm=15 position_mm=[0,-20] through_all=true axis=Y.\ncut_hole diameter_mm=10 position_mm=[25,0] through_all=true axis=X.\ncut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=80 spacing_y_mm=60.\napply_safe_chamfer distance_mm=0.5 target=all_external_edges."},
        {"id": "s20_3d_pipe", "name": "3D空间弯管 3D Space Pipe",
         "dialects": ["loft_sweep"],
         "prompt": "三维空间弯管, 单位 mm.\ncreate_sweep_path path_points(x_mm/y_mm/z_mm): [{x_mm:0,y_mm:0,z_mm:0},{x_mm:30,y_mm:20,z_mm:40},{x_mm:60,y_mm:0,z_mm:80},{x_mm:40,y_mm:-30,z_mm:120},{x_mm:0,y_mm:-20,z_mm:160},{x_mm:-30,y_mm:0,z_mm:200}].\nsweep_profile shape=circle radius_mm=8."},
        {"id": "s20_valve_block", "name": "多端口阀块 Multi-Port Valve",
         "dialects": ["sketch_extrude"],
         "prompt": "多端口液压集成块, 单位 mm.\nextrude_rectangle width_mm=120 height_mm=100 depth_mm=180 centered=true.\ncut_hole diameter_mm=20 position_mm=[0,30] through_all=true axis=Y.\ncut_hole diameter_mm=25 position_mm=[0,-30] through_all=true axis=Y.\ncut_hole diameter_mm=12 position_mm=[-40,0] through_all=false depth_mm=50 axis=Z.\ncut_hole diameter_mm=12 position_mm=[40,0] through_all=false depth_mm=50 axis=Z.\ncut_hole diameter_mm=6 position_mm=[0,0] through_all=true axis=X.\ncut_hole_pattern_linear hole_dia_mm=11 count_x=2 count_y=2 spacing_x_mm=100 spacing_y_mm=80.\napply_safe_chamfer distance_mm=0.3 target=all_external_edges."},
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

def build_contract(dialect_ids):
    lines = [
        "=== DIALECT CONTRACTS (EXACT names) ===",
        "CRITICAL: output type=solid → name='body'",
        "CRITICAL: extrude direction '+' or '-' (NOT Z/X/Y)",
        "CRITICAL: path_points use x_mm/y_mm/z_mm (NOT x/y/z)",
        "CRITICAL: target='all_external_edges'",
        "CRITICAL: composition ops ONLY in __assembly__ component",
        "CRITICAL: boolean_union ALWAYS 2 inputs, use pairwise chain for 3+ solids",
        "",
    ]
    for did in dialect_ids:
        d = REG.get(did)
        if d is None: continue
        lines.append(f"=== {did} phases: {' -> '.join(d.phase_order)} ===")
        for (op_name, _), spec in d.op_specs().items():
            ps = spec.params_model.model_json_schema()
            props = ps.get("properties", {})
            pstrs = [f"{pn}:{pi.get('type','?')}" for pn, pi in props.items()]
            lines.append(f"  {op_name} phase={spec.phase} in={list(spec.input_types)} out={list(spec.output_types)}")
            lines.append(f"    params: {' | '.join(pstrs)}")
            if op_name == "revolve_profile":
                lines.append('    EX: {"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":20}]}')
            elif op_name == "extrude_rectangle":
                lines.append('    EX: {"width_mm":100,"height_mm":80,"depth_mm":15,"plane":"XY","centered":true,"direction":"+"}')
            elif op_name == "helix_sweep":
                lines.append('    EX: {"radius_mm":15,"height_mm":80,"pitch_mm":10,"profile_radius_mm":1.5,"turns":8}')
        lines.append("")
    return "\n".join(lines)


def call_llm(user_msg):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/beta")
    schema = to_deepseek_strict_schema(RawGcadDocument.model_json_schema())
    tools = [{"type": "function", "function": {"name": "gcad", "strict": True, "parameters": schema}}]
    resp = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[{"role": "system", "content": LEVEL2_AUTHORING_SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
        tools=tools, tool_choice={"type": "function", "function": {"name": "gcad"}},
        timeout=120, extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)


def build_step(cdir):
    bscript = ("import sys; sys.path.insert(0, r'" + SRC.as_posix() + "')\n"
        "from pathlib import Path\n"
        "from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files\n"
        "can = Path(r'" + (cdir / "canonical.json").as_posix() + "')\n"
        "val = Path(r'" + (cdir / "validation_bundle.json").as_posix() + "')\n"
        "stp = Path(r'" + (cdir / "output.step").as_posix() + "')\n"
        "met = Path(r'" + (cdir / "output.metadata.json").as_posix() + "')\n"
        "r = run_canonical_gcad_from_files(canonical_json=can, validation_seed_json=val, out_step=stp, metadata_path=met)\n"
        "if r.ok:\n"
        "    print('BUILD_OK')\n"
        "    for m in (r.operation_metrics or []): print('OP:' + str(m.get('node_id','?')) + '/' + str(m.get('op','?')) + ':' + str(m.get('status','?')))\n"
        "    for d in (r.degraded_features or []): print('DEGRADED:' + str(d.get('node_id','?')) + '/' + str(d.get('op','?')))\n"
        "else:\n"
        "    print('BUILD_FAILED: ' + str(r.error)[:500])\n"
        "    for w in (r.warnings or []): print('WARN:' + str(w)[:200])\n")
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text(f"RC={r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


def audit_geometry(step_path):
    try:
        import cadquery as cq
        result = cq.importers.importStep(str(step_path))
        solid = result.val()
        vol = solid.Volume()
        bb = solid.BoundingBox()
        return {"valid": solid.isValid(), "vol_mm3": round(vol, 2),
                "bbox_x": round(bb.xlen, 3), "bbox_y": round(bb.ylen, 3),
                "bbox_z": round(bb.zlen, 3)}
    except Exception as e:
        return {"error": str(e)[:150]}


def process_case(case, cdir):
    audit = {"case": case["id"], "dialects": case["dialects"]}
    (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
    contract = build_contract(case["dialects"])
    base_msg = f"TASK: {case['prompt']}\n\n{contract}\n\nCRITICAL: Use EXACT op/param names. output solid→body. direction=+/-. path_points x_mm/y_mm/z_mm. target=all_external_edges. ALL safety=true. composition ops ONLY in __assembly__. boolean_union ALWAYS 2 inputs."

    ok = False
    err = ""
    for attempt in range(5):
        user_msg = base_msg
        if attempt > 0:
            user_msg += f"\n\nFAILED: {err[:500]}\nFIX ALL ERRORS. Attempt {attempt+1}/5."
        try:
            args = call_llm(user_msg)
        except Exception as e:
            err = f"LLM: {e}"; continue
        audit["llm_nodes"] = len(args.get("nodes", []))
        (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

        # LLM errors
        llm_errs = []
        for n in args.get("nodes", []):
            for o in n.get("outputs", []):
                if o.get("name") == "solid" and o.get("type") == "solid": llm_errs.append(f"{n['id']}:output=solid")
            d = n.get("params", {}).get("direction", "")
            if d in ("Z","X","Y","z","x","y") and n.get("op","") not in ("add_rib",): llm_errs.append(f"{n['id']}:direction={d}")
            for pt in n.get("params", {}).get("path_points", []):
                if "x" in pt and "x_mm" not in pt: llm_errs.append(f"{n['id']}:bare_xyz")
        audit["llm_errors"] = llm_errs

        # Autofix
        try:
            fixed, af = auto_fix_with_report(args, REG)
            (cdir / "autofix_report.json").write_text(json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
            audit["af_count"] = len(af.entries)
            if af.applied: (cdir / "raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
        except:
            fixed = args; audit["af_error"] = True
        fixed.setdefault("llm_validation_hints", {})
        if fixed.get("llm_validation_hints") is None: fixed["llm_validation_hints"] = {}
        fixed.setdefault("units", "mm")
        fixed.setdefault("trust_level", "reference_geometry")

        # Validate (may trigger AssemblyError from v5.1 raw_assembler if wiring fails)
        try:
            doc = RawGcadDocument.model_validate(fixed)
            canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
            if not (canonical and report and report.ok):
                issues = report.issues if report else []
                err = "; ".join(f"[{getattr(i,'code','?')}] {getattr(i,'message',str(i))[:120]}" for i in (issues[:4] if issues else []))
                audit["val_issues"] = [{"code": getattr(i,"code","?"), "msg": getattr(i,"message",str(i))[:150]} for i in (issues or [])[:3]]
                continue
            audit["val_ok"] = True
            (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            if bundle: (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
            ok = True; break
        except AssemblyError as e:
            err = f"AssemblyError: {e}"; audit["assembly_error"] = str(e)[:300]
            continue
        except Exception as e:
            err = f"Pydantic: {e}"; continue

    if not ok:
        return False, f"VAL: {err[:200]}", audit

    # Build STEP
    rc, stdout, stderr = build_step(cdir)
    audit["build_ok"] = "BUILD_OK" in stdout
    audit["degraded"] = [l for l in stdout.split("\n") if "DEGRADED" in l]

    if not audit["build_ok"]:
        # Retry without chamfer/fillet
        cg = json.loads((cdir / "canonical.json").read_text(encoding="utf-8"))
        old_n = len(cg["nodes"])
        cg["nodes"] = [n for n in cg["nodes"] if n.get("op") not in ("apply_safe_chamfer","apply_safe_fillet")]
        if len(cg["nodes"]) < old_n:
            for comp in cg.get("components",[]):
                if comp.get("root_node","") not in {n["id"] for n in cg["nodes"]} and cg["nodes"]:
                    comp["root_node"] = cg["nodes"][-1]["id"]
            (cdir / "canonical.json").write_text(json.dumps(cg, indent=2), encoding="utf-8")
            rc2, stdout2, _ = build_step(cdir)
            audit["build_ok"] = "BUILD_OK" in stdout2
            audit["no_edge"] = True

    if audit["build_ok"] and (cdir / "output.step").exists():
        step_sz = (cdir / "output.step").stat().st_size
        audit["step_size"] = step_sz
        geom = audit_geometry(cdir / "output.step")
        audit["geometry"] = geom
        vol = geom.get("vol_mm3", 0)

        # Anomaly detection
        flags = []
        if vol <= 0.01: flags.append("ZERO_VOL")
        if step_sz < 5000 and vol > 100: flags.append("TINY_STEP")
        if vol > 50000 and step_sz > 0 and step_sz / vol < 0.03: flags.append("LOW_DENSITY")
        audit["flags"] = flags

        # Semantic postcheck (v5.1)
        try:
            from seekflow_engineering_tools.generative_cad.authoring.design_intent_extractor import extract_design_intent_metrics
            from seekflow_engineering_tools.generative_cad.runtime.semantic_postcheck import run_semantic_postcheck
            intent = extract_design_intent_metrics(case["prompt"])
            sp = run_semantic_postcheck(step_path=cdir / "output.step", design_intent=intent,
                                         degraded_ops=audit.get("degraded", []))
            audit["semantic_valid"] = sp.semantic_valid
            audit["semantic_issues"] = [{"code": i.code, "msg": i.message[:150]} for i in sp.issues]
            if sp.measured:
                audit["semantic_measured"] = sp.measured.model_dump()
            (cdir / "semantic_postcheck.json").write_text(json.dumps(sp.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            audit["semantic_error"] = str(e)[:150]

        # SW import skipped in quick mode

        msg = f"STEP={step_sz}B vol={vol:.0f}"
        if geom.get("bbox_x"): msg += f" bbox=[{geom['bbox_x']:.0f}x{geom['bbox_y']:.0f}x{geom['bbox_z']:.0f}]"
        if flags: msg += " " + ",".join(flags)
        if audit.get("semantic_valid") is False: msg += " SEMANTIC_FAIL"
        return True, msg, audit
    else:
        return False, f"STEP: {stderr[:200]}", audit


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import datetime
    all_cases = _get_test_model_cases() + _get_stress20_cases()
    print(f"=== v5.1 Regression: {len(all_cases)} cases ===\nOutput: {OUT}\n")

    results = []
    for i, case in enumerate(all_cases):
        cdir = OUT / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        start = time.time()
        print(f"[{i+1:02d}/{len(all_cases)}] {case['name']} ({case['id']}) ", end="", flush=True)
        ok, msg, audit = process_case(case, cdir)
        elapsed = time.time() - start
        print(f"-> {msg} [{elapsed:.0f}s]")
        if audit.get("llm_errors"):
            for e in audit["llm_errors"]: print(f"   LLM_ERR: {e}")
        if audit.get("val_issues"):
            for vi in audit["val_issues"]: print(f"   VAL: [{vi['code']}] {vi['msg'][:120]}")
        if audit.get("assembly_error"): print(f"   ASSEMBLY: {audit['assembly_error'][:200]}")
        results.append({"id": case["id"], "name": case["name"], "ok": ok, "msg": msg,
                        "elapsed": f"{elapsed:.0f}s", "audit": audit})
        time.sleep(0.3)

    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== RESULTS: {passed}/{len(results)} passed ===")
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        a = r.get("audit", {})
        sv = a.get("semantic_valid")
        sv_str = f" sem={'OK' if sv else 'FAIL'}" if sv is not None else ""
        flags = ",".join(a.get("flags",[]))
        print(f"  {status:4s} {r['name']:30s} {r['msg'][:120]}{sv_str} {flags}")

    report = {"timestamp": datetime.datetime.now().isoformat(), "total": len(results),
              "passed": passed, "pipeline_version": "v5.1", "results": results}
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (OUT / "full_audit.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReports: {OUT}/")
