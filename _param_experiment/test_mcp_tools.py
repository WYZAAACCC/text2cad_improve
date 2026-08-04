"""MCP 工具集测试 — 单元（对照 metadata 已知值）+ 交叉验证 + LLM 集成。

基准：app/text-to-cad/server/output/b572661c219c4952 (KT787_JB_210)
已知值（来自 output.metadata.json）：
  V=8799358.512mm³, body=1, bbox=[499.937,499.937,76]
  Disk-G-CAD: 外径 500(250×2), 中心孔 120(60×2), 榫槽 60/2齿, 节距 26.18, 槽深 24
用法：
  .conda/python.exe test_mcp_tools.py           # 单元 + 交叉验证
  .conda/python.exe test_mcp_tools.py --llm     # 加 LLM 端到端
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_tools import TOOLS


def call(name, args=None):
    return TOOLS[name]["handler"](args or {})


def approx(v, ref, tol, label):
    ok = abs(v - ref) <= tol
    print(f"    {'PASS' if ok else 'FAIL'} {label}: {v} (ref {ref} ±{tol})")
    return ok


def main():
    print("=== MCP 工具集单元测试（基准 b572661c219c4952）===\n")
    all_ok = True
    n = 0

    # ── 1. 实体类 ──
    r = call("check_solid_validity")
    ok = r.get("ok") and approx(r["volume_mm3"], 8799358.512, 1, "体积") and r["body_count"] == 1
    all_ok &= ok; n += 1
    print(f"[check_solid_validity] {'PASS' if ok else 'FAIL'} body={r.get('body_count')} faces={r.get('face_count')} edges={r.get('edge_count')}")

    r = call("check_degenerate_geometry")
    ok = r.get("ok") and r["small_edges_count"] == 0 and r["small_faces_count"] == 0
    all_ok &= ok; n += 1
    print(f"[check_degenerate_geometry] {'PASS' if ok else 'FAIL'} 边{r.get('total_edges')}(小{r.get('small_edges_count')}) 面{r.get('total_faces')}(小{r.get('small_faces_count')})")

    # ── 2. 测量类（IR vs B-rep 交叉验证）──
    ir = call("measure_disc_dimensions")
    br = call("measure_disc_from_brep")
    ok = (approx(ir["outer_diameter_mm"], 500, 0.1, "外径(IR)")
          and approx(ir["bore_diameter_mm"], 120, 0.1, "中心孔(IR)")
          and approx(ir["axial_thickness_mm"], 76, 0.1, "轴厚(IR)"))
    all_ok &= ok; n += 1
    print(f"[measure_disc_dimensions(IR)] {'PASS' if ok else 'FAIL'} 外径{ir['outer_diameter_mm']} 中心孔{ir['bore_diameter_mm']} 轴厚{ir['axial_thickness_mm']}")
    ok = (approx(br["outer_diameter_mm"], 500, 1, "外径(B-rep)")
          and approx(br["axial_thickness_mm"], 76, 0.1, "轴厚(B-rep)")
          and approx(br["bore_radius_mm_approx"], 60, 2, "中心孔半径(B-rep截面)"))
    all_ok &= ok; n += 1
    print(f"[measure_disc_from_brep] {'PASS' if ok else 'FAIL'} 外径{br['outer_diameter_mm']} 中心孔r={br['bore_radius_mm_approx']} 轴厚{br['axial_thickness_mm']}")
    cross = abs(ir["outer_diameter_mm"] - br["outer_diameter_mm"]) <= 1.0
    all_ok &= cross; n += 1
    print(f"[交叉验证 IR vs B-rep 外径] {'PASS' if cross else 'FAIL'}")

    r = call("count_fir_tree_slots")
    ok = approx(r["count"], 60, 0, "榫槽数量") and approx(r["circumferential_pitch_mm"], 26.18, 0.1, "节距")
    all_ok &= ok; n += 1
    print(f"[count_fir_tree_slots] {'PASS' if ok else 'FAIL'} count={r.get('count')} 节距={r.get('circumferential_pitch_mm')}")

    r = call("measure_fir_tree_slot_profile")
    ok = (r["teeth_count"] == 2 and approx(r["slot_depth_mm"], 24, 0.5, "槽深")
          and r.get("root_fillet_mm") == 1.0)
    all_ok &= ok; n += 1
    print(f"[measure_fir_tree_slot_profile] {'PASS' if ok else 'FAIL'} 齿数={r.get('teeth_count')} 槽深={r.get('slot_depth_mm')} 齿面角={r.get('flank_angle_deg')}° 齿根圆角={r.get('root_fillet_mm')}")

    # ── 3. 约束类 ──
    for name in ("check_slot_pitch_and_ligament", "check_slot_depth_and_rim",
                 "check_adjacent_feature_clearance"):
        r = call(name)
        ok = r.get("ok")
        all_ok &= ok; n += 1
        print(f"[{name}] {'PASS' if ok else 'FAIL'} { {k: v for k, v in r.items() if k != 'ok'} }")

    # ── 4. 对比类 ──
    r = call("compare_slot_profile_to_requirement")
    ok = r.get("ok")
    all_ok &= ok; n += 1
    print(f"[compare_slot_profile_to_requirement] {'PASS' if ok else 'FAIL'}")
    for d in r.get("comparison", []):
        print(f"    {d['param']}: exp={d['expected']} act={d['actual']} err={d.get('error')} {'OK' if d.get('ok') else 'X'}")

    r = call("inspect_slot_root_fillet")
    ok = r.get("applied") and r.get("root_fillet_mm") == 1.0
    all_ok &= ok; n += 1
    print(f"[inspect_slot_root_fillet] {'PASS' if ok else 'FAIL'} radius={r.get('root_fillet_mm')} applied={r.get('applied')}")

    # ── 5. 交换类 ──
    for name in ("validate_slot_pattern_periodicity", "validate_slot_step_roundtrip"):
        r = call(name)
        ok = r.get("ok")
        all_ok &= ok; n += 1
        print(f"[{name}] {'PASS' if ok else 'FAIL'} { {k: v for k, v in r.items() if k != 'ok'} }")

    # ── 6. 展示类（含局部放大图）──
    r = call("render_standard_views", {"focus": "root_fillet"})
    ok = r.get("ok") and Path(r["section_view_png"]).exists() and Path(r["detail_view_png"]).exists()
    all_ok &= ok; n += 1
    print(f"[render_standard_views] {'PASS' if ok else 'FAIL'} {r.get('section_view_png')} detail={r.get('detail_view_png')}")

    # ── 7. 汇总 ──
    r = call("generate_quality_report")
    ok = r.get("ok") and len(r["passed_checks"]) >= 5 and not r["failed_checks"]
    all_ok &= ok; n += 1
    print(f"[generate_quality_report] {'PASS' if ok else 'FAIL'} 通过{len(r.get('passed_checks', []))} 失败{r.get('failed_checks')}")

    # ── 8. base_dir 透传 + 新任务目录（mon_*，圆角 LLM 自由选择后产物）──
    MON_DIR = str(Path(__file__).resolve().parent.parent / "app" / "text-to-cad" / "server" / "output" / "mon_e2b035beb218")
    r = call("generate_quality_report", {"base_dir": MON_DIR})
    ok = r.get("ok") and not r["failed_checks"]
    all_ok &= ok; n += 1
    print(f"[generate_quality_report @ mon_* 新目录] {'PASS' if ok else 'FAIL'} 通过{len(r.get('passed_checks', []))} 失败{r.get('failed_checks')}")

    print(f"\n{'='*60}")
    print(f"单元测试: {'全部通过' if all_ok else '有失败'} ({n}/{n})")

    # ── LLM 集成（可选 --llm）──
    if "--llm" in sys.argv:
        print("\n=== LLM 端到端（真实 DeepSeek）===")
        from mcp_server import run_quality_assurance
        task = ("请对该涡轮盘执行完整质量检查：实体有效性、外径/中心孔直径/轴向厚度、"
                "榫槽数量、齿数、槽深、齿面角、周向节距与最小剩余材料、槽深与轮缘厚度约束、"
                "STEP 导出-回读体积一致性。汇总结果并给出工程验收结论。")
        result = run_quality_assurance(task)
        seq = result.get("tool_sequence", [])
        print(f"工具调用序列（{len(seq)} 次）:")
        for i, s in enumerate(seq, 1):
            print(f"  [{i}] {s['tool']} -> ok={s['result'].get('ok')}")
        names = [s["tool"] for s in seq]
        halluc = sum(1 for s in seq if s["result"].get("ok") is False and "未知工具" in str(s["result"]))
        print(f"终止: {result.get('termination')} | 幻觉工具: {halluc} | 验收: {result.get('accepted')}")
        if result.get("final_report"):
            print(f"\n最终报告:\n{result['final_report'][:800]}")
        if result.get("error"):
            print(f"\n错误: {result['error']}")


if __name__ == "__main__":
    main()
