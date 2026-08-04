"""analyze_param_impact 测试 — 参数再生影响分析（论文公式 Vregen = VΔP ∪ Descendants(VΔP)）。

覆盖：
  - 语义源解析（不依赖 PARAM_REGISTRY 死绑节点 ID）在 b572 与 mon_*（圆角 LLM 自由选择后）都可用
  - 下游闭包正确性（节点集合与计划一致）
  - 未知参数 / 缺失参数 / node_id 路径 / new_value 范围校验
用法：
  .conda/python.exe test_analyze_param_impact.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_tools import analyze_param_impact

B572 = str(Path(__file__).resolve().parent.parent / "app" / "text-to-cad" / "server" / "output" / "b572661c219c4952")
MON = str(Path(__file__).resolve().parent.parent / "app" / "text-to-cad" / "server" / "output" / "mon_e2b035beb218")


def ids(affected_nodes):
    return sorted(n["id"] for n in affected_nodes)


def main():
    print("=== analyze_param_impact 测试 ===\n")
    all_ok = True
    n = 0

    def check(label, cond, detail=""):
        nonlocal all_ok, n
        all_ok &= cond
        n += 1
        print(f"[{label}] {'PASS' if cond else 'FAIL'} {detail}")

    # 1. slot_count → b572 {n_pattern_cutters, n_bool_cut_all}
    r = analyze_param_impact({"param_key": "slot_count", "base_dir": B572})
    check("slot_count/b572", r["ok"] and ids(r["affected_nodes"]) == ["n_bool_cut_all", "n_pattern_cutters"],
          f"affected={ids(r['affected_nodes'])}")

    # 2. slot_axial_depth → b572 {n_extrude_cutter, n_pattern_cutters, n_bool_cut_all}
    r = analyze_param_impact({"param_key": "slot_axial_depth", "base_dir": B572})
    check("slot_axial_depth/b572", r["ok"] and r["affected_node_count"] == 3,
          f"affected={ids(r['affected_nodes'])}")

    # 3. disc_hub_web_fillet → b572 7 节点（源 2 对称 + 下游）
    r = analyze_param_impact({"param_key": "disc_hub_web_fillet", "base_dir": B572})
    check("disc_hub_web_fillet/b572", r["ok"] and r["affected_node_count"] == 7,
          f"cnt={r['affected_node_count']} affected={ids(r['affected_nodes'])}")

    # 4. root_fillet → mon（主成分语义定位，精确源节点，不含并集）
    r = analyze_param_impact({"param_key": "root_fillet", "base_dir": MON})
    src = sorted(n["id"] for n in r["source_nodes"])
    check("root_fillet/mon", r["ok"] and src == ["n_cutter_fillet_r1p0"] and r["affected_node_count"] == 6,
          f"src={src} cnt={r['affected_node_count']} affected={ids(r['affected_nodes'])}")

    # 5. 未知参数 → ok:false
    r = analyze_param_impact({"param_key": "nope", "base_dir": B572})
    check("unknown param", not r["ok"] and "未知" in r["error"], r.get("error"))

    # 6. 缺失参数 → ok:false
    r = analyze_param_impact({})
    check("missing param", not r["ok"], r.get("error"))

    # 7. node_id 路径：b572 单节点闭包
    r = analyze_param_impact({"node_id": "n_fillet_cutter_neck_root", "base_dir": B572})
    check("node_id path", r["ok"] and r["param_key"] is None and "n_extrude_cutter" in ids(r["affected_nodes"]),
          f"affected={ids(r['affected_nodes'])}")

    # 8. new_value 范围校验（slot_count 合理范围 [24,96]）
    r1 = analyze_param_impact({"param_key": "slot_count", "new_value": 48, "base_dir": B572})
    r2 = analyze_param_impact({"param_key": "slot_count", "new_value": 200, "base_dir": B572})
    check("new_value in_range", r1["ok"] and r1["in_range"] is True and r2["in_range"] is False,
          f"in={r1['in_range']} out={r2['in_range']}")

    # 9. 不存在的 node_id → ok:false
    r = analyze_param_impact({"node_id": "n_missing", "base_dir": B572})
    check("missing node_id", not r["ok"], r.get("error"))

    # 10. root_fillet → b572 语义定位 = 原死绑 ID（主成分 neck），证明语义化向后兼容
    r = analyze_param_impact({"param_key": "root_fillet", "base_dir": B572})
    src = sorted(n["id"] for n in r["source_nodes"])
    check("root_fillet/b572 semantic==deadbind", r["ok"] and src == ["n_fillet_cutter_neck_root"],
          f"src={src} affected={ids(r['affected_nodes'])}")

    print(f"\n{'='*60}")
    print(f"测试结果: {'全部通过' if all_ok else '有失败'} ({n}/{n})")


if __name__ == "__main__":
    main()
