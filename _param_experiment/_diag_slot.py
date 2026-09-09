"""对比 agent 生成的榫槽与参数化基准榫槽的逐点坐标 + fillet 参数。"""
import json, sys, math
from pathlib import Path

BASE = Path(r"e:\text_to_cad_improve\auto_detection_process\_param_experiment\output\_compare_agentic\D15_baseline_llm_raw.json")
AGENT = Path(r"e:\text_to_cad_improve\auto_detection_process\_param_experiment\output\_compare_agentic\D15\run2\llm_raw.json")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def slots_of(doc):
    out = []
    for n in doc.get("nodes", []):
        if n.get("op") == "add_polyline":
            out.append((n.get("component"), n.get("id"),
                        n.get("params", {}).get("points") or []))
    return out


def fillets_of(doc):
    out = []
    for n in doc.get("nodes", []):
        if n.get("op") == "fillet_sketch":
            out.append((n.get("component"), n.get("id"), n.get("params")))
    return out


def main():
    ag = load(AGENT); base = load(BASE)
    print("===== add_polyline 节点 =====")
    for _sid, _nid, pts in slots_of(base):
        print(f"  [BASE] {_sid}/{_nid} n={len(pts)}")
    for _sid, _nid, pts in slots_of(ag):
        print(f"  [AGENT] {_sid}/{_nid} n={len(pts)}")
    print("\n===== fillet_sketch 参数 =====")
    for _sid, _nid, p in fillets_of(base):
        print(f"  [BASE] {_sid}/{_nid}: at_vertex_index={p.get('at_vertex_index')} radius_mm={p.get('radius_mm')} taper={p.get('_taper_half_mm')}")
    for _sid, _nid, p in fillets_of(ag):
        print(f"  [AGENT] {_sid}/{_nid}: at_vertex_index={p.get('at_vertex_index')} radius_mm={p.get('radius_mm')} taper={p.get('_taper_half_mm')}")

    # 逐点对比（按 x 排序后 y 差）
    def pts_of(slots, key):
        for _s, nid, pts in slots:
            if nid == key:
                return pts
        return []

    def norm(pts, which):
        # 转 {x,y}
        res = []
        for p in pts:
            if isinstance(p, dict):
                res.append((float(p.get("x_mm", p.get("x", 0))), float(p.get("y_mm", p.get("y", 0)))))
            elif isinstance(p, (list, tuple)):
                res.append((float(p[0]), float(p[1])))
        return res

    ag_slots = slots_of(ag); base_slots = slots_of(base)
    # 定位槽 polyline（x 多为负 / 点数>=20）
    def pick_slot(slots):
        best = None
        for _s, nid, pts in slots:
            np_ = norm(pts, ""); 
            if len(np_) >= 20:
                best = (nid, np_)
        return best

    _an, ap = pick_slot(ag_slots)
    _bn, bp = pick_slot(base_slots)
    print("\n===== 榫槽逐点对比 (AGENT vs BASE) =====")
    print(f"点数: AGENT={len(ap)} BASE={len(bp)}")
    for i in range(max(len(ap), len(bp))):
        a = ap[i] if i < len(ap) else None
        b = bp[i] if i < len(bp) else None
        if a and b:
            d = math.hypot(a[0]-b[0], a[1]-b[1])
            flag = "  <== diff" if d > 0.8 else ""
            print(f"  [{i:2d}] AGENT=({a[0]:7.3f},{a[1]:7.3f})  BASE=({b[0]:7.3f},{b[1]:7.3f})  Δ={d:6.3f}{flag}")
        elif a:
            print(f"  [{i:2d}] AGENT=({a[0]:7.3f},{a[1]:7.3f})  BASE=<缺失>")
        else:
            print(f"  [{i:2d}] AGENT=<缺失>  BASE=({b[0]:7.3f},{b[1]:7.3f})")


main()