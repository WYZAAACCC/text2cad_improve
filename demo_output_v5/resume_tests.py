"""Resume remaining 8 test cases from test_model.md."""
import json, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))
os.environ["DEEPSEEK_API_KEY"] = "sk-db9a573912714fd191495d6c6db41ff7"

CONDA = r"E:\auto_detection_process\.conda\python.exe"
SRC = (Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src").resolve()
OUT = Path(__file__).parent / "test_model_output"

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import to_deepseek_strict_schema
from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.skills.prompts import LEVEL2_AUTHORING_SYSTEM_PROMPT
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle

REG = default_registry()

CASES = [
    {
        "id": "t2_weld_fork", "name": "焊接叉 Weld Fork",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "传动轴焊接叉, 单位 mm, 参考几何.\n"
            "底板: extrude_rectangle width_mm=80 height_mm=50 depth_mm=15 centered=true.\n"
            "安装孔: cut_hole_pattern_linear hole_dia_mm=10 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=30.\n"
            "左叉臂: add_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[-30,0,7.5] centered=true.\n"
            "右叉臂: add_rectangular_boss width_mm=12 height_mm=60 depth_mm=15 position_mm=[30,0,7.5] centered=true.\n"
            "左销孔: cut_hole diameter_mm=25 position_mm=[-30,25] through_all=true.\n"
            "右销孔: cut_hole diameter_mm=25 position_mm=[30,25] through_all=true.\n"
            "加强筋: add_rib thickness_mm=8 height_mm=15 length_mm=60 position_mm=[0,0,7.5] direction=X.\n"
            "圆角: apply_safe_fillet radius_mm=2 target=all_external_edges."
        ),
    },
    {
        "id": "t2_gearbox_cover", "name": "减速器上箱盖 Gearbox Cover",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "减速器上箱盖, 单位 mm, 参考几何.\n"
            "主体: extrude_rectangle width_mm=300 height_mm=200 depth_mm=20 centered=true.\n"
            "减重腔: cut_rectangular_pocket width_mm=260 height_mm=160 depth_mm=14 centered=true.\n"
            "安装孔: cut_hole_pattern_linear hole_dia_mm=12 count_x=2 count_y=2 spacing_x_mm=250 spacing_y_mm=150.\n"
            "纵筋x3: add_rib thickness_mm=8 height_mm=18 length_mm=150 position_mm=[-60,0,0] direction=Y.\n"
            "横筋x2: add_rib thickness_mm=8 height_mm=18 length_mm=220 position_mm=[0,-40,0] direction=X.\n"
            "窥视孔凸台: add_rectangular_boss width_mm=100 height_mm=80 depth_mm=10 position_mm=[0,0,10] centered=true.\n"
            "窥视孔: cut_rectangular_pocket width_mm=80 height_mm=60 depth_mm=10 position_mm=[0,0,10] centered=true.\n"
            "圆角: apply_safe_fillet radius_mm=3 target=all_external_edges."
        ),
    },
    {
        "id": "t2_hex_nut", "name": "六角螺母 Hex Nut",
        "dialects": ["axisymmetric"],
        "prompt": (
            "M10六角螺母轴对等近似, 单位 mm, 参考几何.\n"
            "正六边形外接圆直径约18.5mm (对边16mm时).\n"
            "使用 revolve_profile: station1 r=9.5 z=0-8.\n"
            "螺纹底孔: cut_center_bore diameter_mm=8.5 through_all=true.\n"
            "倒角: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
    {
        "id": "t3_turbine_disk", "name": "涡轮盘 Turbine Disk",
        "dialects": ["axisymmetric"],
        "prompt": (
            "燃气轮机涡轮盘, 单位 mm, 参考几何.\n"
            "revolve_profile 5段轮廓:\n"
            "  station1 r=150 z=0-20 (轮缘),\n"
            "  station2 r=120 z=20-40 (锥段),\n"
            "  station3 r=80 z=40-65 (辐板),\n"
            "  station4 r=60 z=65-75 (过渡段),\n"
            "  station5 r=50 z=75-85 (轮毂).\n"
            "中心孔: cut_center_bore diameter_mm=30 through_all=true.\n"
            "螺栓孔PCD80: cut_circular_hole_pattern count=8 pcd_mm=80 hole_dia_mm=12.\n"
            "减重孔PCD180: cut_circular_hole_pattern count=6 pcd_mm=180 hole_dia_mm=25.\n"
            "环槽: cut_annular_groove side=front inner_dia_mm=200 outer_dia_mm=240 depth_mm=6.\n"
            "倒角: apply_safe_chamfer distance_mm=1.5 target=all_external_edges."
        ),
    },
    {
        "id": "t3_robot_wrist", "name": "机器人腕部壳体 Robot Wrist",
        "dialects": ["axisymmetric"],
        "prompt": (
            "机器人腕部壳体, 单位 mm, 参考几何.\n"
            "revolve_profile 薄壁圆筒:\n"
            "  station1 r=60 z=0-200 (外壁).\n"
            "内腔: cut_center_bore diameter_mm=112 through_all=true (壁厚4mm).\n"
            "法兰孔: cut_circular_hole_pattern count=6 pcd_mm=140 hole_dia_mm=9.\n"
            "倒角: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
    {
        "id": "t3_exhaust_manifold", "name": "排气歧管 Exhaust Manifold",
        "dialects": ["loft_sweep"],
        "prompt": (
            "排气歧管S形弯管, 单位 mm, 参考几何.\n"
            "create_sweep_path path_points (使用 x_mm/y_mm/z_mm):\n"
            "  [{x_mm:0,y_mm:0,z_mm:0},{x_mm:0,y_mm:30,z_mm:80},{x_mm:0,y_mm:60,z_mm:160},{x_mm:0,y_mm:30,z_mm:240},{x_mm:0,y_mm:0,z_mm:320}].\n"
            "sweep_profile shape=circle radius_mm=18.\n"
            "所有节点在同一组件, owner_dialect=loft_sweep."
        ),
    },
    {
        "id": "t3_hyd_valve", "name": "液压阀体 Hyd Valve Body",
        "dialects": ["sketch_extrude"],
        "prompt": (
            "液压阀体, 单位 mm, 参考几何.\n"
            "主体: extrude_rectangle width_mm=80 height_mm=60 depth_mm=200 centered=true.\n"
            "P口主阀芯孔: cut_hole diameter_mm=20 position_mm=[0,0] through_all=true axis=Z.\n"
            "A油口: cut_hole diameter_mm=10 position_mm=[0,15] through_all=true axis=Y.\n"
            "B油口: cut_hole diameter_mm=10 position_mm=[0,-15] through_all=true axis=Y.\n"
            "T回油: cut_hole diameter_mm=14 position_mm=[0,0] through_all=true axis=Y.\n"
            "安装孔x4: cut_hole_pattern_linear hole_dia_mm=9 count_x=2 count_y=2 spacing_x_mm=60 spacing_y_mm=40.\n"
            "倒角: apply_safe_chamfer distance_mm=0.5 target=all_external_edges."
        ),
    },
    {
        "id": "t3_diff_case", "name": "差速器壳体 Diff Case",
        "dialects": ["axisymmetric"],
        "prompt": (
            "差速器壳体, 单位 mm, 参考几何.\n"
            "revolve_profile 球壳:\n"
            "  station1 r=75 z=0-20 (法兰),\n"
            "  station2 r=60 z=20-80 (球壳),\n"
            "  station3 r=75 z=80-100 (对侧法兰).\n"
            "腔体: cut_center_bore diameter_mm=100 through_all=true.\n"
            "法兰孔PCD130: cut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\n"
            "对侧法兰孔PCD130: cut_circular_hole_pattern count=8 pcd_mm=130 hole_dia_mm=10.\n"
            "环槽: cut_annular_groove side=front inner_dia_mm=120 outer_dia_mm=140 depth_mm=3.\n"
            "倒角: apply_safe_chamfer distance_mm=1 target=all_external_edges."
        ),
    },
]


def build_contract(dialect_ids):
    lines = [
        "=== DIALECT CONTRACTS (EXACT names required) ===",
        "CRITICAL: output type=solid name='body' (NOT 'solid')",
        "CRITICAL: output type=frame name='outer_frame'",
        "CRITICAL: output type=curve name='curve'",
        "CRITICAL: extrude direction '+' or '-' (NOT Z/X/Y)",
        "CRITICAL: path_points use x_mm/y_mm/z_mm (NOT x/y/z)",
        "CRITICAL: target='all_external_edges'",
        "CRITICAL: ALL safety=true, trust_level='reference_geometry'",
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
            elif op_name == "create_sweep_path":
                lines.append('    EX: {"path_points":[{"x_mm":0,"y_mm":0,"z_mm":0},{"x_mm":50,"y_mm":0,"z_mm":100}]}')
            elif op_name == "cut_circular_hole_pattern":
                lines.append('    EX: {"count":8,"pcd_mm":120,"hole_dia_mm":11,"axis":"Z","through_all":true}')
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
    bscript = (
        "import sys; sys.path.insert(0, r'" + SRC.as_posix() + "')\n"
        "from pathlib import Path\n"
        "from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files\n"
        "can = Path(r'" + (cdir / "canonical.json").as_posix() + "')\n"
        "val = Path(r'" + (cdir / "validation_bundle.json").as_posix() + "')\n"
        "stp = Path(r'" + (cdir / "output.step").as_posix() + "')\n"
        "met = Path(r'" + (cdir / "output.metadata.json").as_posix() + "')\n"
        "r = run_canonical_gcad_from_files(canonical_json=can, validation_seed_json=val, out_step=stp, metadata_path=met)\n"
        "if r.ok: print('BUILD_OK')\n"
        "else: print(f'BUILD_FAILED: {r.error}')\n"
    )
    bp = cdir / "_build.py"
    bp.write_text(bscript, encoding="utf-8")
    r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=300, cwd=str(cdir))
    (cdir / "_build_log.txt").write_text("RC=" + str(r.returncode) + "\n" + r.stdout + "\n" + r.stderr, encoding="utf-8")
    return r.returncode == 0 and (cdir / "output.step").exists()


if __name__ == "__main__":
    for i, case in enumerate(CASES):
        cdir = OUT / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
        contract = build_contract(case["dialects"])
        user_msg = f"TASK: {case['prompt']}\n\n{contract}\n\nCRITICAL: Use EXACT op/param names. output name solid→body. direction=+/-. path_points: x_mm/y_mm/z_mm. target=all_external_edges. ALL safety=true. trust_level=reference_geometry."
        start = time.time()

        ok = False
        err = ""
        for attempt in range(4):
            if attempt > 0:
                user_msg += f"\n\nPREVIOUS FAILED: {err[:500]}\nFIX ALL ERRORS. Attempt {attempt+1}/4."
            print(f"[{i+1}/8] {case['name']} r{attempt+1}...", end=" ", flush=True)
            try:
                args = call_llm(user_msg)
            except Exception as e:
                err = str(e)
                print(f"LLM_FAIL: {e}")
                continue
            (cdir / "llm_raw.json").write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

            # autofix
            try:
                fixed, af = auto_fix_with_report(args, REG)
                (cdir / "autofix_report.json").write_text(json.dumps(af.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
                if af.applied:
                    (cdir / "raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
            except:
                fixed = args

            fixed.setdefault("llm_validation_hints", {})
            fixed.setdefault("units", "mm")
            fixed.setdefault("trust_level", "reference_geometry")

            # validate
            try:
                doc = RawGcadDocument.model_validate(fixed)
                canonical, report, bundle = validate_and_canonicalize_with_bundle(doc)
                if not (canonical and report and report.ok):
                    issues = report.issues if report else []
                    err = "; ".join("[{}] {}".format(getattr(i, "code", "?"), getattr(i, "message", str(i))[:120]) for i in (issues[:4] if issues else []))
                    print(f"VAL_FAIL: {err[:120]}")
                    continue
                (cdir / "canonical.json").write_text(json.dumps(canonical.model_dump(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                if bundle:
                    (cdir / "validation_bundle.json").write_text(json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False), encoding="utf-8")
                ok = True
                break
            except Exception as e:
                err = str(e)[:200]
                print(f"Pydantic: {e}")
                continue

        if not ok:
            print(f"FAILED after {attempt+1} attempts: {err[:120]}")
            continue

        # Build STEP
        if build_step(cdir):
            step_sz = (cdir / "output.step").stat().st_size
            print(f"STEP={step_sz}B [{time.time()-start:.0f}s]")
        else:
            # Retry without chamfer
            cg = json.loads((cdir / "canonical.json").read_text(encoding="utf-8"))
            old_n = len(cg["nodes"])
            cg["nodes"] = [n for n in cg["nodes"] if n.get("op") not in ("apply_safe_chamfer", "apply_safe_fillet")]
            if len(cg["nodes"]) < old_n:
                for comp in cg.get("components", []):
                    if comp.get("root_node", "") not in {n["id"] for n in cg["nodes"]} and cg["nodes"]:
                        comp["root_node"] = cg["nodes"][-1]["id"]
                (cdir / "canonical.json").write_text(json.dumps(cg, indent=2), encoding="utf-8")
                if build_step(cdir):
                    print(f"STEP={(cdir/'output.step').stat().st_size}B (no edge) [{time.time()-start:.0f}s]")
                else:
                    print(f"STEP_FAIL [{time.time()-start:.0f}s]")
            else:
                print(f"STEP_FAIL [{time.time()-start:.0f}s]")
        time.sleep(0.5)
    print("\nDone.")
