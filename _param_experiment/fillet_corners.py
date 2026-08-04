"""榫槽圆角 — LLM 指定"角 + 半径"方案（保证不漏）。

核心机制（保证不漏圆角）：
  1. 程序根据几何规则生成【必须圆角的角清单】——每个角 = 一个顶点 + 它的两条邻边
  2. LLM 为清单中的每个角指定 radius_mm（设计决策）
  3. 程序验证 LLM 是否覆盖全部角（漏了则反馈补齐）
  4. 按顶点（及两条邻边）执行圆角

角清单规则（哪些角必须圆角）：
  - tip_flank_top @ 每齿      齿顶外斜面端（凸角）
  - tip_platform_end @ 每齿   齿顶平台端（凸角）
  - neck @ 0..teeth_count     齿根/颈部（凹角，应力集中关键）
  - bottom_flare               槽底外扩角（凹角）
  - root                       根部（凹角）

LLM 指定格式（tool schema）：
  fillets: [
    {"role": "tip_flank_top", "tooth_index": 0, "radius_mm": 0.8},
    {"role": "neck", "tooth_index": 1, "radius_mm": 0.5},
    {"role": "root", "tooth_index": -1, "radius_mm": 0.6},
    ...
  ]
  - role: tip_flank_top / tip_platform_end / neck / bottom_flare / root
  - tooth_index: tip 用齿号(0..n-1)；neck 用颈部号(0..n)；bottom 用 -1
"""

from __future__ import annotations

from fillet_strategy import annotate_roles

# 需要圆角的角色集合（凹角：neck/connector/bottom；凸角：tip）
FILLET_ROLES = ("tip_flank_top", "tip_platform_end", "neck", "connector",
                "bottom_flare", "bottom_platform", "root")


def _tooth_of_role(role: str, idx: int) -> int:
    """从上侧顶点索引反推 role 对应的 tooth_index。"""
    if role == "tip_flank_top":
        return (idx - 2) // 4
    if role == "tip_platform_end":
        return (idx - 3) // 4
    if role == "neck":
        if idx == 1:
            return 0  # 颈部0（齿0外斜面起点）
        # 内斜面端：4+4i (i=0..n-2) → 颈部 i+1；最后 4n → 颈部 n
        i = (idx - 4) // 4
        return i + 1
    if role == "connector":
        i = (idx - 5) // 4
        return i + 1
    return -1


def list_required_corners(pts: list, teeth_count: int) -> list[dict]:
    """列出所有必须圆角的角（保证不漏，含上下两侧）。

    每个角 = {role, tooth_index, key, vertex_idx, vertex, edge_a, edge_b,
             lower_vertex_idx, lower_vertex}
    - vertex / edge_a / edge_b = 上侧顶点的坐标与两条邻边
    - lower_vertex = 下侧镜像顶点坐标（也必须圆角）
    """
    n = teeth_count
    n_upper = 5 + 4 * n
    total = 2 * n_upper
    if len(pts) != total:
        raise ValueError(f"点数 {len(pts)} != 2*(5+4n)={total}")

    upper_roles = annotate_roles(n)
    # 上侧角（每个 key 一次，含上下两侧物理顶点）
    corners: list[dict] = []
    seen_keys: set = set()
    for i in range(n_upper):
        role = upper_roles[i]
        if role not in FILLET_ROLES:
            continue
        tooth = _tooth_of_role(role, i)
        key = f"{role}@{tooth}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        lower_i = total - 1 - i
        # 上侧跨界点：mouth(0) 的前驱是 mouth 镜像(total-1)；root(n_upper-1) 的后继是 root 镜像(n_upper)。
        # 用 %n_upper 会在 mouth/root 处取到假邻居（root→mouth 假边），必须按真实闭合轮廓处理。
        prev_u = total - 1 if i == 0 else i - 1
        nxt_u = n_upper if i == n_upper - 1 else i + 1
        prev_l = (lower_i + 1) % total
        nxt_l = (lower_i - 1) % total
        corners.append({
            "role": role,
            "tooth_index": tooth,
            "key": key,
            "vertex_idx": i,
            "vertex": [pts[i]["x_mm"], pts[i]["y_mm"]],
            "edge_a": [[pts[prev_u]["x_mm"], pts[prev_u]["y_mm"]], [pts[i]["x_mm"], pts[i]["y_mm"]]],
            "edge_b": [[pts[i]["x_mm"], pts[i]["y_mm"]], [pts[nxt_u]["x_mm"], pts[nxt_u]["y_mm"]]],
            "lower_vertex_idx": lower_i,
            "lower_vertex": [pts[lower_i]["x_mm"], pts[lower_i]["y_mm"]],
            "lower_edge_a": [[pts[prev_l]["x_mm"], pts[prev_l]["y_mm"]], [pts[lower_i]["x_mm"], pts[lower_i]["y_mm"]]],
            "lower_edge_b": [[pts[lower_i]["x_mm"], pts[lower_i]["y_mm"]], [pts[nxt_l]["x_mm"], pts[nxt_l]["y_mm"]]],
        })
    return corners


def llm_schema() -> dict:
    """LLM 指定的 tool schema（role + tooth_index + radius）。"""
    return {
        "type": "object",
        "properties": {
            "fillets": {
                "type": "array",
                "description": "为每个必须圆角的角指定半径。必须覆盖所有角色组合（缺一个都不行）",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": ["tip_flank_top", "tip_platform_end", "neck", "bottom_flare", "root"]},
                        "tooth_index": {"type": "integer", "description": "tip 用齿号(0..n-1)；neck 用颈部号(0..n)；bottom 用 -1"},
                        "radius_mm": {"type": "number", "minimum": 0.05},
                    },
                    "required": ["role", "tooth_index", "radius_mm"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["fillets"],
        "additionalProperties": False,
    }


def verify_coverage(corners: list, llm_fillets: list) -> tuple:
    """检查 LLM 是否覆盖全部必须圆角的角。返回 (ok, missing, duplicates)。"""
    required_keys = {c["key"] for c in corners}
    provided_keys = set()
    seen = set()
    duplicates = []
    for f in llm_fillets:
        key = f"{f['role']}@{f['tooth_index']}"
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        provided_keys.add(key)
    missing = sorted(required_keys - provided_keys)
    extra = sorted(provided_keys - required_keys)
    return (not missing and not extra and not duplicates), missing, extra, duplicates


def _dist(p1, p2) -> float:
    import math
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def compute_safe_radius(corners: list, pts: list, radius_by_role: dict,
                        edge_factor: float = 0.5) -> dict[str, float]:
    """为每个角计算碰撞安全半径（上下两侧取最小邻边）。

    约束 1（邻边）：半径 ≤ min(上下邻边) × edge_factor
      - 榫槽 edge_factor=0.5（半邻边，保守，短边多）
      - 盘面 edge_factor=1.0（全邻边，长邻边 15-16mm，避免 clamp 掉 10-12mm 工程半径）
    约束 2（相邻碰撞）：相邻两角半径之和 ≤ 共享边长（上下两侧都检查）
    """
    n = len(pts)

    def _role_group(key: str, role: str) -> str:
        if "tip" in key:
            return "tip"
        if role == "neck":
            return "neck"
        if role == "connector":
            return "connector"
        return "bottom"

    # 每角上下邻边长度（通用候选表无 lower_* 字段，仅上侧）
    def _min_edge(c) -> float:
        Ls = [_dist(c["edge_a"][0], c["edge_a"][1]),
              _dist(c["edge_b"][0], c["edge_b"][1])]
        if "lower_edge_a" in c:
            Ls.append(_dist(c["lower_edge_a"][0], c["lower_edge_a"][1]))
            Ls.append(_dist(c["lower_edge_b"][0], c["lower_edge_b"][1]))
        return min(Ls)

    # 初始：半径 = min(邻边) × edge_factor，且 ≤ 请求值
    safe = {}
    for c in corners:
        # radius_by_role 键兼容：盘面按角色（hub_web_transition…）、榫槽按分组（tip/neck/…）
        req = radius_by_role.get(c["role"]) or radius_by_role.get(
            _role_group(c["key"], c["role"]), 0.5)
        r = min(_min_edge(c) * edge_factor, req)
        safe[c["key"]] = max(r, 0.05)

    # 约束 2：相邻角（共享边）半径之和 ≤ 共享边长（上侧 + 下侧）
    # 上下两侧各自按对应顶点索引升序排列；下侧必须用 lower_vertex_idx 排序，
    # 否则（按 vertex_idx 排序）lower_vertex_idx 恒降序，ib-ia!=1 全部跳过 → 下侧检查死代码。
    has_lower = all("lower_vertex_idx" in c for c in corners)
    for _ in range(20):
        changed = False
        for side in ("upper", "lower"):
            if side == "lower" and not has_lower:
                continue  # 通用候选表（单顶点）无下侧镜像
            if side == "upper":
                order = sorted(corners, key=lambda c: c["vertex_idx"])
                get_i, get_v = (lambda c: c["vertex_idx"]), (lambda c: c["vertex"])
            else:
                order = sorted(corners, key=lambda c: c["lower_vertex_idx"])
                get_i, get_v = (lambda c: c["lower_vertex_idx"]), (lambda c: c["lower_vertex"])
            for k in range(len(order) - 1):
                a, b = order[k], order[k + 1]
                ia, ib = get_i(a), get_i(b)
                if ib - ia != 1:
                    continue
                va, vb = get_v(a), get_v(b)
                L = _dist(va, vb)
                ra, rb = safe[a["key"]], safe[b["key"]]
                if ra + rb > L:
                    scale = L / (ra + rb)
                    safe[a["key"]] = max(ra * scale, 0.03)
                    safe[b["key"]] = max(rb * scale, 0.03)
                    changed = True
        if not changed:
            break
    return safe


def execute_fillets(wire, corners: list, llm_fillets: list, teeth_count: int, pts: list = None,
                    failures: dict = None) -> object:
    """按顶点（及两条邻边）执行圆角。位置匹配 + 碰撞安全半径。

    同半径的角分一批 fillet2D，从大到小执行；每个角半径已 clamp 到安全值，
    避免齿顶两端/齿根两端相邻圆角碰撞。

    failures（可选 dict）：若提供，未圆角成功的角 key 会被记录（不静默跳过）。
    一批失败时先降半径重试（r → 0.7r → 0.5r），仍失败再逐角隔离定位。
    """
    import cadquery as cq

    if failures is not None:
        failures.clear()

    corner_map = {c["key"]: c for c in corners}
    # 每个角的请求半径
    requested = {}
    for f in llm_fillets:
        key = f"{f['role']}@{f['tooth_index']}"
        if key in corner_map:
            requested[key] = float(f["radius_mm"])
    if not requested:
        return wire

    # 按角色分组 → 计算安全半径
    role_of_key = {}
    for c in corners:
        g = "tip" if "tip" in c["key"] else (c["role"] if c["role"] in ("neck", "connector") else "bottom")
        role_of_key[c["key"]] = g
    radius_by_role = {}
    for key, r in requested.items():
        g = role_of_key.get(key, "bottom")
        radius_by_role[g] = max(radius_by_role.get(g, 0), r)
    safe_all = compute_safe_radius(corners, pts, radius_by_role) if pts is not None else requested
    # 只圆角 LLM 请求的角（防止默认半径圆角所有角）
    safe = {k: v for k, v in safe_all.items() if k in requested}

    # 每个角的上下两侧顶点都圆角
    all_verts = []
    for key, r in safe.items():
        c = corner_map[key]
        all_verts.append((key, r, tuple(c["vertex"])))
        all_verts.append((key, r, tuple(c["lower_vertex"])))
    # 按半径分组（同半径一批），从大到小
    groups: dict[float, list] = {}
    for key, r, v in all_verts:
        groups.setdefault(round(r, 3), []).append((key, v))
    result = wire
    for radius in sorted(groups.keys(), reverse=True):
        items = groups[radius]
        cur_verts = list(result.Vertices())
        targets = []
        for key, (vx, vy) in items:
            best = min(range(len(cur_verts)),
                       key=lambda j: (cur_verts[j].X - vx) ** 2 + (cur_verts[j].Y - vy) ** 2)
            targets.append(cur_verts[best])
        if not targets:
            continue
        # 降半径重试序列：完整半径 → 0.7 → 0.5
        ok = False
        for try_r in (radius, radius * 0.7, radius * 0.5):
            try:
                result = result.fillet2D(try_r, targets)
                ok = True
                break
            except Exception:
                continue
        if ok:
            continue
        # 整批失败 → 逐角隔离，仍失败则记录（不静默跳过）
        for key, (vx, vy) in items:
            cur = list(result.Vertices())
            best = min(range(len(cur)),
                       key=lambda j: (cur[j].X - vx) ** 2 + (cur[j].Y - vy) ** 2)
            placed = False
            for try_r in (radius, radius * 0.7, radius * 0.5):
                try:
                    result = result.fillet2D(try_r, [cur[best]])
                    placed = True
                    break
                except Exception:
                    continue
            if not placed:
                if failures is not None:
                    failures[key] = f"fillet radius={radius} failed (retries 0.7r/0.5r)"
    return result


if __name__ == "__main__":
    from fir_tree_parametric import FirTreeParams, generate_profile
    import cadquery as cq

    print("=== 必须圆角的角清单（保证不漏）===")
    for n in (2, 3):
        p = FirTreeParams(
            teeth_count=n, slot_depth_mm=26,
            tooth_height_mm=[7 - i * 0.8 for i in range(n)], tooth_thickness_mm=[2] * n,
            top_flank_angle_deg=[66.7] * n, under_flank_angle_deg=[60] * n,
            neck_half_width_mm=[2.6 - i * 0.2 for i in range(n + 1)], neck_platform_mm=2.0,
            bottom_half_width_mm=4.0, bottom_platform_mm=2.0, bottom_flare_angle_deg=60,
        )
        pts = generate_profile(p)
        corners = list_required_corners(pts, n)
        print(f"\n{n}齿：必须圆角 {len(corners)} 个角")
        for c in corners:
            print(f"  {c['key']:28s} 顶点{c['vertex']}  边1:{c['edge_a'][0]}→{c['edge_a'][1]}  边2:{c['edge_b'][0]}→{c['edge_b'][1]}")

        # 模拟 LLM 全覆盖指定（每角一个合理半径）
        llm_fillets = []
        for c in corners:
            r = 0.8 if "tip" in c["key"] else (0.5 if c["role"] == "neck" else 0.6)
            llm_fillets.append({"role": c["role"], "tooth_index": c["tooth_index"], "radius_mm": r})
        ok, missing, extra, dup = verify_coverage(corners, llm_fillets)
        print(f"  覆盖验证: {'PASS' if ok else 'FAIL'} missing={missing} extra={extra} dup={dup}")

        # 执行圆角
        wp = cq.Workplane("XY")
        for i, pt in enumerate(pts):
            if i == 0:
                wp = wp.moveTo(pt["x_mm"], pt["y_mm"])
            else:
                wp = wp.lineTo(pt["x_mm"], pt["y_mm"])
        wp = wp.close()
        wire = wp.wire().val()
        fw = execute_fillets(wire, corners, llm_fillets, n)
        print(f"  圆角执行: {len(list(wire.Edges()))} -> {len(list(fw.Edges()))} 边")
