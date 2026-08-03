"""LLM 自由选择圆角角（点 + 两条边）机制。

与 fillet_corners.py（程序定角清单，强制全覆盖）不同，本模块让 LLM 自由选择：
  - 候选角表：轮廓全部顶点（含 mouth）的角，每角含顶点 key + 两条邻边 key + 坐标
  - LLM 用语义 key 引用顶点和边，输出 {vertex, edge_a, edge_b, radius_mm}
  - 程序解析校验（顶点存在、两条边围绕该顶点）、去重、容错修正，然后执行圆角
不强制覆盖 —— LLM 可只选 1 个角，也可全选。

用法:
  candidates = build_candidate_table(pts, teeth_count)
  prompt = build_selection_prompt(candidates, teeth_count)
  # LLM 按 prompt 输出 llm_fillets = [{vertex, edge_a, edge_b, radius_mm}, ...]
  corners, llm_out, feedback = resolve_selection(candidates, llm_fillets)
  fw = execute_fillets(wire, corners, llm_out, teeth_count, pts, failures=fails)
"""

from __future__ import annotations

from fillet_strategy import annotate_roles
from fillet_corners import _tooth_of_role, execute_fillets

ROLE_MEANING = {
    "mouth": "口部上缘",
    "neck": "齿根/颈部（凹角，应力集中）",
    "tip_flank_top": "齿顶外斜面端（凸角）",
    "tip_platform_end": "齿顶平台端（凸角）",
    "connector": "齿间连接线端（齿根山谷侧）",
    "bottom_flare": "槽底外扩角",
    "bottom_platform": "槽底平台端",
    "root": "根部（凹角）",
}


def build_candidate_table(pts: list, teeth_count: int) -> list[dict]:
    """全部顶点（含 mouth）候选角表。

    每角 = 上侧顶点 key + 上/下坐标 + 两条邻边(key+坐标) + 索引。
    结构兼容 execute_fillets / compute_safe_radius 的 corners 格式。
    """
    n = teeth_count
    n_upper = 5 + 4 * n
    total = 2 * n_upper
    if len(pts) != total:
        raise ValueError(f"点数 {len(pts)} != 2*(5+4n)={total}")
    roles = annotate_roles(n)

    # 每个顶点的 key（total 长）：上侧 = {role}@{tooth}；下侧镜像 = 对称上侧 key + "_m"
    vkeys = []
    for i in range(n_upper):
        vkeys.append(f"{roles[i]}@{_tooth_of_role(roles[i], i)}")
    for j in range(n_upper):
        vkeys.append(vkeys[n_upper - 1 - j] + "_m")

    cands = []
    for i in range(n_upper):
        prev = total - 1 if i == 0 else i - 1          # mouth 前驱 = 镜像 mouth
        nxt = n_upper if i == n_upper - 1 else i + 1   # root 后继 = root 镜像
        lower_i = total - 1 - i
        l_prev = (lower_i + 1) % total
        l_nxt = (lower_i - 1) % total
        cands.append({
            "key": vkeys[i],
            "role": roles[i],
            "tooth_index": _tooth_of_role(roles[i], i),
            "vertex_idx": i,
            "vertex": [pts[i]["x_mm"], pts[i]["y_mm"]],
            "edge_a_key": f"{vkeys[prev]}→{vkeys[i]}",
            "edge_b_key": f"{vkeys[i]}→{vkeys[nxt]}",
            "edge_a": [[pts[prev]["x_mm"], pts[prev]["y_mm"]], [pts[i]["x_mm"], pts[i]["y_mm"]]],
            "edge_b": [[pts[i]["x_mm"], pts[i]["y_mm"]], [pts[nxt]["x_mm"], pts[nxt]["y_mm"]]],
            "lower_vertex_idx": lower_i,
            "lower_vertex": [pts[lower_i]["x_mm"], pts[lower_i]["y_mm"]],
            "lower_edge_a": [[pts[l_prev]["x_mm"], pts[l_prev]["y_mm"]], [pts[lower_i]["x_mm"], pts[lower_i]["y_mm"]]],
            "lower_edge_b": [[pts[lower_i]["x_mm"], pts[lower_i]["y_mm"]], [pts[l_nxt]["x_mm"], pts[l_nxt]["y_mm"]]],
        })
    return cands


def free_select_schema() -> dict:
    """LLM 自由选择 schema：vertex/edge 为字符串 key（不输出坐标）。"""
    return {
        "type": "object",
        "properties": {
            "fillets": {
                "type": "array",
                "description": "自由选择要圆角的角。每个角 = 顶点 + 两条邻边 + 半径。vertex/edge 必须逐字抄自候选角表",
                "items": {
                    "type": "object",
                    "properties": {
                        "vertex": {"type": "string", "description": "顶点 key，如 neck@1"},
                        "edge_a": {"type": "string", "description": "第一条邻边 key，如 tip_platform_end@0→neck@1"},
                        "edge_b": {"type": "string", "description": "第二条邻边 key，如 neck@1→connector@1"},
                        "radius_mm": {"type": "number", "minimum": 0.05, "description": "圆角半径(mm)"},
                    },
                    "required": ["vertex", "edge_a", "edge_b", "radius_mm"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["fillets"],
        "additionalProperties": False,
    }


def build_selection_prompt(candidates: list, teeth_count: int) -> str:
    """告诉 LLM 有哪些候选角 + 选角原则。"""
    lines = [
        f"枞树形榫槽（{teeth_count}齿）轮廓已生成，共 {len(candidates)} 个候选角。",
        "你需要【自由选择】要圆角的角。轮廓上每个角由一个顶点和它的两条邻边构成。",
        "",
        "候选角表（每角 = 顶点key + 两条邻边key + 顶点坐标）：",
    ]
    for c in candidates:
        lines.append(
            f"  {c['key']:22s} {ROLE_MEANING[c['role']]:26s} "
            f"顶点({c['vertex'][0]:7.3f},{c['vertex'][1]:6.3f})  "
            f"边a:{c['edge_a_key']}  边b:{c['edge_b_key']}"
        )
    lines += [
        "",
        "选角原则：",
        "  - 齿根凹角 neck@i / connector@i：应力集中关键，【强烈建议】圆角",
        "  - 齿顶凸角 tip_flank_top@i / tip_platform_end@i：建议圆角",
        "  - 槽底 bottom_flare@-1 / bottom_platform@-1 / root@-1：建议圆角",
        "  - 口部 mouth@-1：通常不圆角（保持口部形状）",
        "  - 半径参考：齿顶≈0.8，齿根≈0.5，底部≈0.6",
        "  - 碰撞注意：相邻两角（共享一条边）半径之和 ≤ 共享边长，过大程序会自动 clamp",
        "",
        "硬规则：",
        "  1. vertex / edge_a / edge_b 必须【逐字抄写】自上面的候选角表，不得自创或修改任何字符",
        "  2. edge_a / edge_b 必须是该顶点在表中的两条邻边",
        "  3. 只输出你选择要圆角的角；不想圆角的角【不要】出现",
        "  4. 可只选齿根（neck/connector），也可全选",
    ]
    return "\n".join(lines)


def resolve_selection(candidates: list, llm_fillets: list) -> tuple:
    """解析并校验 LLM 的自由选择。

    返回 (selected_corners, llm_fillets_out, feedback)
      - selected_corners: 候选表子集（喂 execute_fillets 的 corners）
      - llm_fillets_out: [{role, tooth_index, radius_mm}]（喂 execute_fillets）
      - feedback: 校验告警（非法 key / 边不匹配容错修正 / 重复）
    """
    cand_map = {c["key"]: c for c in candidates}
    selected: dict = {}   # key -> radius
    feedback: list[str] = []
    for f in llm_fillets:
        if not isinstance(f, dict):
            continue
        vkey = f.get("vertex")
        if vkey not in cand_map:
            feedback.append(f"未知顶点 key: {vkey!r}（已忽略）")
            continue
        c = cand_map[vkey]
        eA, eB = f.get("edge_a"), f.get("edge_b")
        want = {c["edge_a_key"], c["edge_b_key"]}
        got = {eA, eB}
        if not (want & got):
            feedback.append(f"{vkey}: 边 {eA!r}/{eB!r} 均不是该顶点邻边（已自动改用正确邻边）")
        elif got != want:
            feedback.append(f"{vkey}: 边 {eA!r}/{eB!r} 与候选不完全匹配（已自动改用正确邻边）")
        if vkey in selected:
            feedback.append(f"{vkey}: 重复选择（保留首次半径 {selected[vkey]}）")
            continue
        try:
            r = max(float(f.get("radius_mm", 0.5)), 0.05)
        except (TypeError, ValueError):
            r = 0.5
        selected[vkey] = r
    selected_corners = [cand_map[k] for k in selected]
    llm_out = [{"role": cand_map[k]["role"], "tooth_index": cand_map[k]["tooth_index"],
                "radius_mm": r} for k, r in selected.items()]
    return selected_corners, llm_out, feedback


if __name__ == "__main__":
    from fir_tree_parametric import FirTreeParams, generate_profile
    import cadquery as cq

    p = FirTreeParams(
        teeth_count=3, slot_depth_mm=26,
        tooth_height_mm=[6, 5, 4], tooth_thickness_mm=[2, 2, 2],
        top_flank_angle_deg=[66.7] * 3, under_flank_angle_deg=[60] * 3,
        neck_half_width_mm=[2.6, 2.33, 2.07, 1.8], neck_platform_mm=2.0,
        bottom_half_width_mm=4.0, bottom_platform_mm=2.0, bottom_flare_angle_deg=60,
    )
    pts = generate_profile(p)
    cands = build_candidate_table(pts, p.teeth_count)
    print(f"3齿候选角表（{len(cands)} 个）：")
    for c in cands:
        print(f"  {c['key']:22s} {ROLE_MEANING[c['role']]}")

    # 模拟 LLM 自由选择：只选齿根（neck + connector）
    llm = []
    for c in cands:
        if c["role"] in ("neck", "connector"):
            llm.append({"vertex": c["key"], "edge_a": c["edge_a_key"], "edge_b": c["edge_b_key"],
                        "radius_mm": 0.5})
    corners, llm_out, feedback = resolve_selection(cands, llm)
    print(f"\n只选齿根: 选中 {len(corners)} 个角, feedback={feedback}")
    wp = cq.Workplane("XY")
    for i, pt in enumerate(pts):
        wp = wp.moveTo(pt["x_mm"], pt["y_mm"]) if i == 0 else wp.lineTo(pt["x_mm"], pt["y_mm"])
    wp = wp.close()
    wire = wp.wire().val()
    fw = execute_fillets(wire, corners, llm_out, p.teeth_count, pts)
    print(f"圆角执行: {len(list(wire.Edges()))} -> {len(list(fw.Edges()))} 边 (只圆齿根)")
