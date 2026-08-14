"""多参数组合涡轮盘主流程生成测试 — 真实 pipeline + 尺寸/圆角/模型验证。

对 5 组参数组合各跑一次完整真实主流程（_run_pipeline：L1 路由→L2 创作→repair loop→重建），
生成后用 mcp_tools 测量工具自动验证：
  1. 盘面尺寸（外径/中心孔/轴厚）vs 需求
  2. 榫槽尺寸（齿数/槽数/槽深/喉部半宽/齿根圆角）vs 需求
  3. 圆角（盘面 hub_web/web_rim、榫槽 root 覆盖）
  4. 模型（STEP solid 有效、bbox 外径≈需求）
并绘制每组盘面/榫槽草图供人工检查。

用法:
  .conda/python.exe _param_experiment/param_sweep_test.py            # 顺序跑 5 组（完整 L1）
  .conda/python.exe _param_experiment/param_sweep_test.py --force-route generative_cad_ir
        # 跳过 L1 路由，强制走 IR 主路径（L1 真实路由可能选 deterministic_primitive，
        # 而 primitive 路径有已知 bug 会崩溃——本测试改为验证 IR 主路径参数组合）
  .conda/python.exe _param_experiment/param_sweep_test.py --only G1,G3  # 只跑指定组
  .conda/python.exe _param_experiment/param_sweep_test.py --no-run    # 只验证已存在任务目录
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False


# ── 5 组参数组合（期望值为断言基准）────────────────────────────
def _text(od, bore, thick, hub, rim, slots, teeth, R, depth, throat, fr):
    return (f"生成一个高压涡轮盘参考几何：轮毂-腹板-轮缘盘体，外径{od}mm，中心孔直径{bore}mm，"
            f"轴向最大厚度{thick}mm，轮毂半厚{hub}mm，轮缘半厚{rim}mm，轮缘上{slots}个{teeth}齿枞树形榫槽，"
            f"分布半径{R}mm，槽深{depth}mm，喉部半宽{throat}mm，齿根圆角{fr}mm。参考几何，非适航件。")


def _expect(od, bore, thick, slots, teeth, depth, throat, fr, tol_od=5, tol_bore=5,
            tol_thick=3, tol_depth=2, tol_throat=0.5, tol_fr=0.3):
    return {"outer_diameter_mm": od, "bore_diameter_mm": bore, "axial_thickness_mm": thick,
            "slots": slots, "teeth_count": teeth, "slot_depth_mm": depth, "throat_half_width_mm": throat,
            "root_fillet_mm": fr,
            "tol": {"outer_diameter_mm": tol_od, "bore_diameter_mm": tol_bore,
                    "axial_thickness_mm": tol_thick, "slot_depth_mm": tol_depth,
                    "throat_half_width_mm": tol_throat, "root_fillet_mm": tol_fr}}

CASES = [
    {"name": "G1_baseline", "text": _text(500, 120, 76, 38, 30, 60, 2, 250, 24, 4.0, 1.0),
     "expect": _expect(500, 120, 76, 60, 2, 24, 4.0, 1.0)},
    {"name": "G2_slots_depth", "text": _text(500, 120, 76, 38, 30, 48, 2, 250, 28, 4.0, 1.0),
     "expect": _expect(500, 120, 76, 48, 2, 28, 4.0, 1.0)},
    {"name": "G3_dims_throat", "text": _text(460, 110, 70, 35, 28, 60, 2, 230, 24, 3.5, 1.0),
     "expect": _expect(460, 110, 70, 60, 2, 24, 3.5, 1.0)},
    {"name": "G4_throat_fillet", "text": _text(500, 110, 76, 38, 30, 60, 2, 250, 24, 3.0, 1.5),
     "expect": _expect(500, 110, 76, 60, 2, 24, 3.0, 1.5)},
    {"name": "G5_3tooth_depth", "text": _text(500, 120, 76, 38, 30, 60, 3, 250, 30, 4.0, 1.2),
     "expect": _expect(500, 120, 76, 60, 3, 30, 4.0, 1.2)},
]


# ── 草图绘制（盘面 + 榫槽，人工检查）───────────────────────────
def _find_profile(ir: dict, component_op: str):
    comp = None
    for n in ir.get("nodes", []):
        if n["op"] == component_op:
            comp = n["component"]
            break
    if comp is None:
        return None, None
    for n in ir.get("nodes", []):
        if n["component"] == comp and n["op"] == "add_polyline":
            return comp, n["params"]["points"]
    return comp, None


def plot_profiles(ir: dict, out_png: Path, title: str):
    disc_comp, disc = _find_profile(ir, "revolve_profile")
    slot_comp, slot = _find_profile(ir, "extrude_profile")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    if disc:
        xs = [p["x_mm"] for p in disc]
        ys = [p["y_mm"] for p in disc]
        ax1.plot(xs, ys, "o-", lw=1.6, ms=3.5)
        ax1.set_title(f"盘面轮廓 (XZ) — {len(disc)} 点", fontsize=10)
        ax1.set_xlabel("半径 mm"); ax1.set_ylabel("轴向 mm")
        ax1.set_aspect("equal"); ax1.grid(alpha=0.3)
    else:
        ax1.set_title("盘面轮廓：未找到")
    if slot:
        xs = [p["x_mm"] for p in slot]
        ys = [p["y_mm"] for p in slot]
        ax2.plot(xs, ys, "o-", lw=1.6, ms=3.5)
        ax2.set_title(f"榫槽轮廓 (XY) — {len(slot)} 点", fontsize=10)
        ax2.set_xlabel("径向 mm"); ax2.set_ylabel("切向半宽 mm")
        ax2.set_aspect("equal"); ax2.grid(alpha=0.3)
    else:
        ax2.set_title("榫槽轮廓：未找到")
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    plt.close(fig)


# ── 验证（复用 mcp_tools 测量工具）────────────────────────────
def _num_approx(actual, expected, tol):
    return actual is not None and abs(actual - expected) <= tol


def verify_case(case: dict, out_dir: Path) -> dict:
    """对生成产物做尺寸/圆角/模型验证，返回 {ok, checks:[{k,label,actual,expected,tol,ok}], details}。"""
    import mcp_tools as mt
    exp = case["expect"]
    checks = []
    out = {"ok": False, "checks": checks, "ir": None}

    raw_p = out_dir / "raw_fixed.json"
    step_p = out_dir / "output.step"
    if not raw_p.exists():
        out["reason"] = "raw_fixed.json 缺失（任务未完成）"
        return out
    if not step_p.exists():
        out["reason"] = "output.step 缺失（runtime 失败）"
    bd = {"base_dir": str(out_dir)}

    # 1. 盘面尺寸（IR）
    try:
        dm = mt.measure_disc_dimensions(bd)
        for k in ("outer_diameter_mm", "bore_diameter_mm", "axial_thickness_mm"):
            a, e, t = dm.get(k), exp[k], exp["tol"][k]
            checks.append({"k": k, "label": {"outer_diameter_mm": "外径", "bore_diameter_mm": "中心孔",
                                             "axial_thickness_mm": "轴厚"}[k],
                           "actual": a, "expected": e, "tol": t, "ok": _num_approx(a, e, t)})
    except Exception as exc:
        checks.append({"k": "disc_dim", "label": "盘面尺寸", "actual": None, "expected": exp,
                       "tol": 0, "ok": False, "error": str(exc)})

    # 2. 榫槽尺寸（IR）
    try:
        sp = mt.measure_fir_tree_slot_profile(bd)
        cnt = mt.count_fir_tree_slots(bd)
        checks.append({"k": "slots", "label": "榫槽数量", "actual": cnt.get("count"),
                       "expected": exp["slots"], "tol": 0, "ok": cnt.get("count") == exp["slots"]})
        for k in ("teeth_count", "slot_depth_mm", "throat_half_width_mm", "root_fillet_mm"):
            e = exp[k]
            label = {"teeth_count": "齿数", "slot_depth_mm": "槽深",
                     "throat_half_width_mm": "喉部半宽", "root_fillet_mm": "齿根圆角"}[k]
            if k == "teeth_count":
                ok = sp.get(k) == e
                checks.append({"k": k, "label": label, "actual": sp.get(k), "expected": e,
                               "tol": 0, "ok": ok})
            else:
                a, t = sp.get(k), exp["tol"].get(k, 2)
                checks.append({"k": k, "label": label, "actual": a, "expected": e,
                               "tol": t, "ok": _num_approx(a, e, t)})
    except Exception as exc:
        checks.append({"k": "slot_dim", "label": "榫槽尺寸", "actual": None, "expected": exp,
                       "tol": 0, "ok": False, "error": str(exc)})

    # 3. 圆角覆盖（IR 结构）
    try:
        ir = json.loads(raw_p.read_text(encoding="utf-8"))
        out["ir"] = ir
        disc_comp = mt._component_with_op(ir, "revolve_profile")
        slot_comp = mt._component_with_op(ir, "extrude_profile")
        disc_fillets = [n for n in ir["nodes"] if n["component"] == disc_comp
                        and n["op"] == "fillet_sketch"]
        slot_fillets = [n for n in ir["nodes"] if n["component"] == slot_comp
                        and n["op"] == "fillet_sketch"]
        def covers(fillet_nodes, targets):
            got = set()
            for n in fillet_nodes:
                ai = n["params"].get("at_vertex_index")
                s = set(ai) if isinstance(ai, list) else ({ai} if isinstance(ai, int) else set())
                got |= s & targets
            return targets <= got
        hub_web_ok = covers(disc_fillets, {2, 9})
        web_rim_ok = covers(disc_fillets, {3, 8})
        checks.append({"k": "disc_hub_web_fillet", "label": "盘面hub_web圆角",
                       "actual": hub_web_ok, "expected": True, "tol": 0, "ok": hub_web_ok})
        checks.append({"k": "disc_web_rim_fillet", "label": "盘面web_rim圆角",
                       "actual": web_rim_ok, "expected": True, "tol": 0, "ok": web_rim_ok})
        root = mt._root_fillet(ir)
        checks.append({"k": "slot_root_fillet", "label": "榫槽齿根圆角节点",
                       "actual": root is not None, "expected": True, "tol": 0,
                       "ok": root is not None and len(slot_fillets) >= 1})
    except Exception as exc:
        checks.append({"k": "fillet_struct", "label": "圆角结构", "actual": None,
                       "expected": True, "tol": 0, "ok": False, "error": str(exc)})

    # 4. 模型有效性（STEP）
    if step_p.exists():
        try:
            sv = mt.check_solid_validity(bd)
            checks.append({"k": "model_solid", "label": "STEP实体", "actual": sv.get("body_count"),
                           "expected": ">=1", "tol": 0,
                           "ok": sv.get("body_count", 0) >= 1 and sv.get("volume_mm3", 0) > 0})
            bb = sv.get("bbox_mm")
            if bb and len(bb) == 3:
                checks.append({"k": "model_od", "label": "模型外径(bbox)",
                               "actual": bb[0], "expected": exp["outer_diameter_mm"],
                               "tol": exp["tol"]["outer_diameter_mm"],
                               "ok": _num_approx(bb[0], exp["outer_diameter_mm"],
                                                 exp["tol"]["outer_diameter_mm"])})
                checks.append({"k": "model_thick", "label": "模型轴厚(bbox)",
                               "actual": bb[2], "expected": exp["axial_thickness_mm"],
                               "tol": exp["tol"]["axial_thickness_mm"],
                               "ok": _num_approx(bb[2], exp["axial_thickness_mm"],
                                                 exp["tol"]["axial_thickness_mm"])})
        except Exception as exc:
            checks.append({"k": "model", "label": "模型", "actual": None, "expected": True,
                           "tol": 0, "ok": False, "error": str(exc)})

    out["ok"] = all(c.get("ok") for c in checks)
    return out


# ── 主流程驱动 ────────────────────────────────────────────────
def run_case(case: dict, no_run: bool, force_route: str | None = None) -> tuple:
    name = case["name"]
    task_id = f"mon_sweep_{name.lower()}"
    out_dir = ROOT / "app" / "text-to-cad" / "server" / "output" / task_id

    if not no_run:
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        os.environ["DEEPSEEK_API_KEY"] = key
        import main
        main._tasks[task_id] = {"status": "pending"}
        print(f"\n[驱动] {name}  task={task_id}")
        print(f"[需求] {case['text'][:80]}...")
        if force_route:
            print(f"[路由] force_route={force_route}（跳过 L1；完整 L1 实测会选 deterministic_primitive 触发已知 bug）")
        main._run_pipeline(task_id, case["text"], force_route=force_route)
        t = main._tasks.get(task_id, {})
        print(f"[状态] {t.get('status')}")
        if t.get("error"):
            print(f"[错误] {t['error'][:200]}")
    else:
        t = {"status": "verify_only"}

    v = verify_case(case, out_dir)
    return {"name": name, "task_id": task_id, "status": t.get("status"), "verify": v}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只跑指定组，如 G1,G3")
    ap.add_argument("--force-route", default=None, help="强制路由（如 generative_cad_ir）；None=完整 L1")
    ap.add_argument("--no-run", action="store_true", help="只验证已存在任务目录，不生成")
    args = ap.parse_args(argv)

    cases = CASES
    if args.only:
        want = [x.strip().upper() for x in args.only.split(",")]
        cases = [c for c in CASES if c["name"].split("_")[0].upper() in want]

    print("=" * 78)
    print("多参数组合涡轮盘主流程生成测试（真实 pipeline + 尺寸/圆角/模型验证）")
    print("=" * 78)
    results = []
    for c in cases:
        try:
            r = run_case(c, args.no_run, force_route=args.force_route)
            results.append(r)
            _dump_case(r)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            results.append({"name": c["name"], "status": "driver_exc", "verify": {"ok": False,
                            "reason": f"驱动异常: {exc}"}})
            print(f"[{c['name']}] 驱动异常: {exc}")

    # 汇总表
    print("\n" + "=" * 78)
    print("汇总")
    print("=" * 78)
    print(f"{'组合':16s} {'任务状态':12s} {'验证':6s} {'失败项':<40s}")
    for r in results:
        v = r.get("verify", {})
        fails = [c["label"] for c in v.get("checks", []) if not c.get("ok")]
        status = r.get("status", "?")
        vok = "PASS" if v.get("ok") else "FAIL"
        print(f"{r['name']:16s} {status:12s} {vok:6s} {','.join(fails)[:60]}")
    # 存汇总 JSON
    summ_path = _HERE / "output" / "param_sweep" / "summary.json"
    summ_path.parent.mkdir(parents=True, exist_ok=True)
    summ_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    print(f"\n[汇总] {summ_path}")
    return 0


def _dump_case(r: dict):
    """打印单组验证明细 + 绘制草图。"""
    name = r["name"]
    task_id = r["task_id"]
    v = r.get("verify", {})
    out_dir = ROOT / "app" / "text-to-cad" / "server" / "output" / task_id
    print(f"[{name}] 验证:")
    for c in v.get("checks", []):
        mark = "PASS" if c.get("ok") else "FAIL"
        if c.get("error"):
            print(f"    [{mark}] {c['label']}: {c['error']}")
        elif isinstance(c.get("actual"), bool):
            print(f"    [{mark}] {c['label']}: {c['actual']}")
        else:
            print(f"    [{mark}] {c['label']}: 实际={c.get('actual')} 期望={c.get('expected')} ±{c.get('tol')}")
    if not v.get("ok"):
        print(f"    -> 验证未全通过: {v.get('reason', '')}")
    # 绘制草图
    ir = v.get("ir")
    if ir:
        png = out_dir / "sweep_sketch.png"
        plot_profiles(ir, png, f"{name} — 盘面与榫槽草图")
        print(f"    [草图] {png}")
    elif (out_dir / "llm_raw.json").exists():
        ir2 = json.loads((out_dir / "llm_raw.json").read_text(encoding="utf-8"))
        png = out_dir / "sweep_sketch.png"
        plot_profiles(ir2, png, f"{name} — 盘面与榫槽草图(LLM首轮)")
        print(f"    [草图] {png} (LLM 首轮)")
    print()


if __name__ == "__main__":
    sys.exit(main())
