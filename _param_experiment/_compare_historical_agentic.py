"""参数化基准 vs 历史 agent llm_raw 深度诊断对比（无 API，纯本地）。

对 D15 基线（build_slot_disc 确定性生成）与 3 次历史 agent 输出 run0/1/2，
逐 run 抽取：组件结构、轮廓点数/格式、关键节点参数，并与基准逐一核对。
点格式异常（非 {"x_mm","y_mm"}）也如实报告——本身即"不一致"。
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(_HERE.parent / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from _compare_agentic_vs_template import make_baseline  # noqa: E402

FAM = "D15"
BASE_DIR = _HERE / "output" / "_compare_agentic" / FAM
baseline = make_baseline(FAM)
params = baseline["params"]


def extract_robust(raw):
    comps = []
    for c in raw.get("components", []):
        comps.append({"id": c.get("id"), "kind_hint": c.get("kind_hint"),
                      "owner_dialect": c.get("owner_dialect"), "root_node": c.get("root_node")})
    polylines = []
    for n in raw.get("nodes", []):
        if n.get("op") != "add_polyline":
            continue
        pts = n.get("params", {}).get("points")
        info = {"node": n.get("id"), "component": n.get("component"), "dialect": n.get("dialect"),
                "phase": n.get("phase")}
        if not isinstance(pts, list):
            info["points"] = f"类型={type(pts).__name__}（非列表）"
            polylines.append(info)
            continue
        info["n_points"] = len(pts)
        xs = ys = 0
        bad = []
        for p in pts[:6]:
            if isinstance(p, dict) and "x_mm" in p and "y_mm" in p:
                xs += 1; ys += 1
            elif isinstance(p, dict):
                bad.append(str(list(p.keys())))
            else:
                bad.append(type(p).__name__)
        info["sample"] = pts[:5] if (pts and isinstance(pts[0], (int, float, list))) else pts[:2]
        info["x_mm 点"], info["y_mm 点"] = xs, ys
        if bad:
            info["非 x_mm/y_mm 键"] = bad
        polylines.append(info)
    ops = [n.get("op") for n in raw.get("nodes", [])]
    pat = None
    for n in raw.get("nodes", []):
        if n.get("op") == "circular_pattern_component":
            pat = n.get("params", {})
            break
    dial = [d.get("dialect") for d in raw.get("selected_dialects", [])]
    fillets = [n.get("params", {}).get("radius_mm") for n in raw.get("nodes", [])
               if n.get("op") == "fillet_sketch"]
    return {"components": comps, "polylines": polylines, "ops": ops,
            "pattern": pat, "dialects": dial, "fillet_radii": fillets}


print(f"===== 设计族 {FAM} =====")
print(f"模板参数: {params}")
print(f"基准关键点: 盘体12点 榫槽26点 pattern=40 descend\n")

for run in ("run0", "run1", "run2"):
    p = BASE_DIR / run / "llm_raw.json"
    if not p.exists():
        print(f"### [{run}] 无文件\n"); continue
    raw = json.loads(p.read_text(encoding="utf-8"))
    a = extract_robust(raw)
    print(f"### [{run}]")
    print(f"  dialects: {a['dialects']}")
    print(f"  components:")
    for c in a["components"]:
        print(f"    id={c['id']!r} kind_hint={c['kind_hint']!r} owner={c['owner_dialect']!r} root={c['root_node']!r}")
    print(f"  ops: {a['ops']}")
    print(f"  pattern: {a['pattern']}")
    print(f"  fillet_radii(disc首次/slot): {a['fillet_radii']}")

    # 定位盘体/榫槽 polyline
    show = {"category_disc": False, "category_slot": False}
    disc_cid = next((c["id"] for c in a["components"] if (c["kind_hint"] or "").lower() in
                     ("turbine_disc", "axisymmetric_disc", "disc")), None)
    slot_cid = next((c["id"] for c in a["components"] if (c["kind_hint"] or "").lower() in
                     ("fir_tree_cutter", "fir_tree_slot_cutter")), None)
    for pl in a["polylines"]:
        tag = ""
        if pl["component"] == disc_cid or "disc" in (pl["component"] or ""):
            tag = "  <-- 盘体"
            show["category_disc"] = True
        elif (slot_cid and pl["component"] == slot_cid) or "cutter" in (pl["component"] or ""):
            tag = "  <-- 榫槽"
            show["category_slot"] = True
        print(f"  polyline node={pl['node']} comp={pl['component']} phase={pl['phase']} "
              f"n={pl.get('n_points')} sample={pl.get('sample')} {tag}")
    if show["category_disc"] and not show["category_slot"]:
        print("  ⚠️ 未找到榫槽组件轮廓（榫槽缺失）")
    print()

print("=== 与基准不一致观察（结构性对比，坐标量比对见上）===")