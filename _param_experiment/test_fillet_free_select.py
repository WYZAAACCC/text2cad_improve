"""LLM 自由选择圆角 — 程序模拟测试（不调 API）。

覆盖：
  1. 候选表 == 现有"必须角清单"（FILLET_ROLES 4n+4），全选等价
  2. 自由子集：只选齿根 neck+connector → 只圆角齿根
  3. 校验拦截：非法 vertex / 边不匹配 / 重复 → feedback + 容错修正
  4. 碰撞安全：大半径请求被 clamp，无相邻碰撞
  5. M1-M12 全选路径回归
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cadquery as cq

from fir_tree_parametric import generate_profile
from fillet_corners import list_required_corners, compute_safe_radius
from fillet_free_select import build_candidate_table, resolve_selection
from fillet_strategy import annotate_roles

# 复用 test_fillet_multicombos 的参数组合
from test_fillet_multicombos import COMBOS, build_wire, req_radius


def role_group(key, role):
    if "tip" in key:
        return "tip"
    return role if role in ("neck", "connector") else "bottom"


def select_all(cands, rbr, exclude_mouth=True):
    """模拟 LLM 全选（可选排除 mouth）。"""
    out = []
    for c in cands:
        if exclude_mouth and c["role"] == "mouth":
            continue
        g = role_group(c["key"], c["role"])
        out.append({"vertex": c["key"], "edge_a": c["edge_a_key"], "edge_b": c["edge_b_key"],
                    "radius_mm": rbr[g]})
    return out


def main():
    print("=== LLM 自由选择圆角 — 程序模拟测试 ===\n")
    all_ok = True
    n_passed = 0

    for name, cfg in COMBOS.items():
        p = cfg["fn"]()
        pts = generate_profile(p)
        cands = build_candidate_table(pts, p.teeth_count)
        n_upper = 5 + 4 * p.teeth_count
        rbr = req_radius(name)

        # ── 1. 候选表 == 必须角清单（排除 mouth）──
        req_keys = {c["key"] for c in list_required_corners(pts, p.teeth_count)}
        cand_keys = {c["key"] for c in cands if c["role"] != "mouth"}
        eq = req_keys == cand_keys
        if not eq:
            print(f"[{name}] FAIL: 候选表 ≠ 必须角清单\n  missing={req_keys - cand_keys} extra={cand_keys - req_keys}")

        # ── 2. 全选路径（等价现有机制）──
        llm = select_all(cands, rbr)
        corners, llm_out, feedback = resolve_selection(cands, llm)
        wire = build_wire(pts)
        from fillet_corners import execute_fillets
        fw = execute_fillets(wire, corners, llm_out, p.teeth_count, pts)
        n0, n1 = len(list(wire.Edges())), len(list(fw.Edges()))
        expect_inc = 2 * len(corners)
        ok_full = (n1 - n0 == expect_inc) and not feedback and (len(corners) == 4 * p.teeth_count + 4)

        # ── 3. 自由子集：只选齿根（neck+connector）──
        llm_root = [{"vertex": c["key"], "edge_a": c["edge_a_key"], "edge_b": c["edge_b_key"],
                     "radius_mm": 0.5}
                    for c in cands if c["role"] in ("neck", "connector")]
        corners_r, llm_r, fb_r = resolve_selection(cands, llm_root)
        fwr = execute_fillets(wire, corners_r, llm_r, p.teeth_count, pts)
        n1r = len(list(fwr.Edges()))
        root_count = sum(1 for c in cands if c["role"] in ("neck", "connector"))
        ok_root = (n1r - n0 == 2 * root_count) and not fb_r

        # ── 4. 碰撞安全：大半径 tip 被 clamp ──
        llm_big = select_all(cands, {"tip": 1.5, "neck": 1.2, "connector": 1.2, "bottom": 1.5})
        corners_b, llm_b, fb_b = resolve_selection(cands, llm_big)
        safe = compute_safe_radius(corners_b, pts, rbr)
        collide = False
        idx = sorted(corners_b, key=lambda c: c["vertex_idx"])
        for k in range(len(idx) - 1):
            a, b = idx[k], idx[k + 1]
            if b["vertex_idx"] - a["vertex_idx"] != 1:
                continue
            va, vb = a["vertex"], b["vertex"]
            L = ((va[0] - vb[0]) ** 2 + (va[1] - vb[1]) ** 2) ** 0.5
            if safe[a["key"]] + safe[b["key"]] > L + 0.01:
                collide = True
        ok_collide = not collide

        # ── 5. 校验拦截：非法 vertex / 边不匹配 / 重复 ──
        bad_llm = [
            {"vertex": "nonexistent@9", "edge_a": "x", "edge_b": "y", "radius_mm": 0.5},  # 非法顶点
            {"vertex": cands[2]["key"], "edge_a": "wrong_edge_a", "edge_b": "wrong_edge_b", "radius_mm": 0.5},  # 边全错
            {"vertex": cands[3]["key"], "edge_a": cands[3]["edge_a_key"], "edge_b": "wrong", "radius_mm": 0.5},  # 边半错
            {"vertex": cands[4]["key"], "edge_a": cands[4]["edge_a_key"], "edge_b": cands[4]["edge_b_key"],
             "radius_mm": 0.5},  # 合法
            {"vertex": cands[4]["key"], "edge_a": cands[4]["edge_a_key"], "edge_b": cands[4]["edge_b_key"],
             "radius_mm": 0.9},  # 重复
        ]
        corners_v, llm_v, fb_v = resolve_selection(cands, bad_llm)
        n_warn = sum(1 for x in fb_v if "未知顶点" in x or "邻边" in x or "重复" in x)
        # 非法顶点被忽略、边错被修正、重复去重：3 个有效角，4 条告警
        ok_validate = (len(corners_v) == 3) and (n_warn == 4)

        status = "PASS" if (eq and ok_full and ok_root and ok_collide and ok_validate) else "FAIL"
        if status == "FAIL":
            all_ok = False
        n_passed += 1
        print(f"  [{name:16s}] 候选角={len(cands)} 全选={len(corners)}角边{n0}→{n1}(+{n1 - n0}) "
              f"齿根={root_count}角边→{n1r}(+{n1r - n0}) 校验:{n_warn}告警 碰撞={collide} -> {status}")

    print(f"\n{'全部通过' if all_ok else '有失败'} ({n_passed}/{len(COMBOS)})")


if __name__ == "__main__":
    main()
