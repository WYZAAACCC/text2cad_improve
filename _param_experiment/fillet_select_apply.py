"""LLM 自由选择圆角 → 主流程（盘面 + 榫槽统一，后处理圆角规划器）。

**最终目标**：所有圆角（盘面 XZ + 榫槽 XY）都由 **LLM 自由选择"一个点 + 两条邻边 + 半径"**
决定，程序不硬编码圆角。程序只提供候选角表（语义 key）、校验（resolve_selection）、
安全半径保护（compute_safe_radius）与执行（生成 fillet_sketch 节点 → run_gcad_core_from_files 重建）。

对每个圆角组件（盘面 = 含 revolve_profile、榫槽 = 含 extrude_profile）各一次 LLM 选择：
  1. 提取轮廓点 + 角色表（盘面 DISC_ROLES / 榫槽 annotate_roles）
  2. 通用候选角表 → prompt（坐标语义区分）→ LLM 选 {vertex, edge_a, edge_b, radius_mm}
  3. resolve_selection 校验 → 安全半径（盘面 edge_factor=1.0 / 榫槽 0.5）
  4. 转 at_vertex_index（list 形式，按半径分组每节点一组）→ 替换该组件 fillet 链
  5. run_gcad_core_from_files 重建

用法:
  .conda/python.exe _param_experiment/fillet_select_apply.py \
        [--base-dir <目录>] [--out <输出目录>] [--no-rebuild] [--max-attempts N]

产物: out/raw_fillet_selected.json + output.step + output.metadata.json（重建时）
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
ROOT = _HERE.parent
SRC = ROOT / "integrations" / "engineering_tools" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fillet_free_select import (  # noqa: E402
    DISC_ROLES,
    ROLE_MEANING,
    build_candidate_table_generic,
    free_select_schema,
    resolve_selection,
)
from fillet_corners import compute_safe_radius  # noqa: E402
from fillet_strategy import annotate_roles  # noqa: E402

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import (  # noqa: E402
    DeepSeekToolCaller,
)
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig  # noqa: E402
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (  # noqa: E402
    to_deepseek_strict_schema,
)

MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
API_KEY_FILE = ROOT / "_archive" / "apikey.txt"
DEFAULT_BASE = ROOT / "app" / "text-to-cad" / "server" / "output" / "b572661c219c4952"
DEFAULT_OUT = _HERE / "output" / "fillet_select"

# 组件规格：(定位 op, 类型, edge_factor, 坐标语义, 半径参考 min/max)
COMPONENT_SPECS = [
    ("revolve_profile", "disc", 1.0,
     "盘面（XZ 子午截面：x=半径mm 60-250, y=轴向mm -38~+38）", 6.0, 20.0),
    ("extrude_profile", "slot", 0.5,
     "榫槽（XY 切面：x=径向深度mm 0=轮缘面 负向=向中心, y=切向半宽mm）", 0.4, 1.5),
]


# ── 语义定位 ─────────────────────────────────────────────────────────────


def _find_component_with_op(ir: dict, op: str):
    for n in ir.get("nodes", []):
        if n["op"] == op:
            return n["component"]
    return None


def _find_profile_points(ir: dict, comp: str):
    for n in ir.get("nodes", []):
        if n["component"] == comp and n["op"] == "add_polyline":
            return n["params"]["points"]
    return None


def _find_close_node(ir: dict, comp: str):
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == "close_profile":
            return n
    raise ValueError(f"组件 {comp} 未找到 close_profile")


def _find_terminal_node(ir: dict, comp: str, op: str):
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == op:
            return n
    raise ValueError(f"组件 {comp} 未找到 {op}")


def _derive_teeth_count(pts: list) -> int:
    total = len(pts)
    if total % 2 != 0:
        raise ValueError(f"点数 {total} 非偶数")
    n_upper = total // 2
    if (n_upper - 5) < 0 or (n_upper - 5) % 4 != 0:
        raise ValueError(f"上侧点数 {n_upper} 不符合 5+4n 结构")
    return (n_upper - 5) // 4


def _build_component_roles(pts: list, comp_type: str) -> list:
    """角色表：盘面固定 12 角色；榫槽 = annotate_roles + 下侧镜像。"""
    if comp_type == "disc":
        if len(pts) != len(DISC_ROLES):
            raise ValueError(f"盘面点数 {len(pts)} != {len(DISC_ROLES)}（候选角表需盘面 12 点结构）")
        return list(DISC_ROLES)
    n = _derive_teeth_count(pts)
    upper = annotate_roles(n)
    return upper + upper[::-1]


# ── LLM 自由选择 ─────────────────────────────────────────────────────────


def _call_llm_fillet(prompt: str, max_attempts: int) -> list:
    caller = DeepSeekToolCaller()
    last_err = None
    for attempt in range(max_attempts):
        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请输出你选择要圆角的 fillets（顶点+两条邻边+半径）。"},
            ]
            r = caller.call_strict_tool(
                messages=messages,
                tool_name="emit_fillets",
                tool_description="Emit freely selected fillet corners (vertex + two edges + radius)",
                tool_schema=to_deepseek_strict_schema(free_select_schema()),
                model_config=MODEL_CONFIG,
            )
            return list(r.arguments.get("fillets", []))
        except Exception as exc:
            last_err = str(exc)
    raise RuntimeError(f"LLM 自由选择圆角失败: {last_err}")


def build_selection_prompt(candidates: list, comp_type: str, r_min: float, r_max: float) -> str:
    """选角 prompt：按组件类型区分坐标语义、角色释义与半径量级。"""
    plane_desc = COMPONENT_SPECS[0][3] if comp_type == "disc" else COMPONENT_SPECS[1][3]
    title = "盘面（R-Z 子午截面）" if comp_type == "disc" else "榫槽（枞树形轮廓）"
    lines = [
        f"{title}轮廓已生成，共 {len(candidates)} 个候选角。",
        f"坐标语义：{plane_desc}。",
        "你需要【自由选择】要圆角的角。轮廓上每个角由一个顶点和它的两条邻边构成。",
        "",
        "候选角表（每角 = 顶点key + 两条邻边key + 顶点坐标）：",
    ]
    for c in candidates:
        meaning = ROLE_MEANING.get(c["role"], c["role"])
        lines.append(
            f"  {c['key']:30s} {meaning:18s} "
            f"顶点({c['vertex'][0]:7.1f},{c['vertex'][1]:6.1f})  "
            f"边a:{c['edge_a_key']}  边b:{c['edge_b_key']}"
        )
    lines.append("")
    lines.append("选角原则：")
    if comp_type == "disc":
        lines += [
            "  - hub_web_transition（轮毂→腹板凹角）/ web_rim_transition（腹板→轮缘凹角）："
            "应力集中关键，【强烈建议】圆角",
            "  - hub_outer_corner / rim_inner_step：可选圆角（工程变体）",
            "  - bore_mouth / rim_outer_corner：通常不圆角（bore 是定位面、rim 外圆是加工基准）",
        ]
    else:
        lines += [
            "  - 齿根凹角 neck@i / connector@i：应力集中关键，【强烈建议】圆角",
            "  - 齿顶凸角 tip_flank_top@i / tip_platform_end@i：建议圆角",
            "  - 槽底 bottom_flare@-1 / bottom_platform@-1 / root@-1：建议圆角",
            "  - 口部 mouth@-1：通常不圆角（保持口部形状）",
        ]
    lines += [
        f"  - 半径参考：{r_min}~{r_max}mm（盘面取大值，榫槽取小值）",
        "  - 碰撞注意：相邻两角（共享一条边）半径之和 ≤ 共享边长，过大程序会自动 clamp",
        "",
        "硬规则：",
        "  1. vertex / edge_a / edge_b 必须【逐字抄写】自上面的候选角表，不得自创或修改任何字符",
        "  2. edge_a / edge_b 必须是该顶点在表中的两条邻边",
        "  3. 只输出你选择要圆角的角；不想圆角的角【不要】出现",
        "  4. 可只选必须圆角的角，也可全选",
    ]
    return "\n".join(lines)


# ── 规划与节点生成 ─────────────────────────────────────────────────────────


def build_component_plan(pts: list, roles: list, edge_factor: float,
                         llm_fillets: list) -> dict:
    """候选角表 → LLM 选角 → 安全半径 → 按半径分组。"""
    cands = build_candidate_table_generic(pts, roles)
    corners, _llm_out, feedback = resolve_selection(cands, llm_fillets)
    if not corners:
        return {"corners": [], "groups": [], "final_radii": {}, "feedback": feedback,
                "candidates": cands, "at_vertex_map": {}}

    requested = {}
    for f in llm_fillets:
        vk = f.get("vertex")
        if vk is None:
            continue
        try:
            r = max(float(f.get("radius_mm", 0.5)), 0.05)
        except (TypeError, ValueError):
            r = 0.5
        requested[vk] = r

    # radius_by_role（按角色分组取 max 请求）
    radius_by_role = {}
    for c in corners:
        radius_by_role[c["role"]] = max(radius_by_role.get(c["role"], 0),
                                        requested.get(c["key"], 0.5))
    safe = compute_safe_radius(corners, pts, radius_by_role, edge_factor)

    final_radii = {}
    for c in corners:
        key = c["key"]
        final_radii[key] = min(requested.get(key, 0.5), safe.get(key, requested.get(key, 0.5)))

    at_vertex_map = {c["key"]: [c["vertex_idx"]] for c in corners}
    groups: dict[float, list] = {}
    for c in corners:
        r = round(final_radii[c["key"]], 1)
        groups.setdefault(r, []).extend(at_vertex_map[c["key"]])
    group_list = [{"radius": r, "at_vertex_index": sorted(set(groups[r]))}
                  for r in sorted(groups, reverse=True)]

    return {"corners": corners, "groups": group_list, "final_radii": final_radii,
            "feedback": feedback, "candidates": cands, "at_vertex_map": at_vertex_map}


def _replace_fillet_chain(ir: dict, plan: dict, comp: str, terminal_op: str) -> list:
    """替换组件 fillet 链：close → fillet₁→…→fillet_N → terminal。返回新节点 id。"""
    close_node = _find_close_node(ir, comp)
    terminal_node = _find_terminal_node(ir, comp, terminal_op)

    kept = [n for n in ir["nodes"] if not (n["component"] == comp and n["op"] == "fillet_sketch")]
    new_ids = []
    prev_node = close_node["id"]
    for i, g in enumerate(plan["groups"], 1):
        nid = f"n_fillet_{comp}_{i}"
        new_ids.append(nid)
        kept.append({
            "id": nid,
            "component": comp,
            "dialect": "sketch_profile",
            "op": "fillet_sketch",
            "op_version": "1.0.0",
            "phase": "edge_treatment",
            "inputs": [{"node": prev_node, "output": "profile"}],
            "outputs": [{"name": "profile", "type": "profile"}],
            "params": {"radius_mm": g["radius"], "at_vertex_index": g["at_vertex_index"]},
            "required": False,
            "degradation_policy": "may_skip_with_warning",
        })
        prev_node = nid

    for n in kept:
        if n["id"] == terminal_node["id"]:
            n["inputs"] = [{"node": new_ids[-1], "output": "profile"}]

    ir["nodes"] = kept
    return new_ids


# ── 主流程 ─────────────────────────────────────────────────────────────────


def apply_llm_fillet_selection(
    base_dir: str | Path,
    out_dir: str | Path | None = None,
    max_attempts: int = 2,
    rebuild: bool = True,
    llm_fillets: dict | None = None,
) -> dict:
    """对主流程产物执行 LLM 自由选择圆角（盘面 + 榫槽）→ 替换节点 →（可选）重建。

    llm_fillets: 可选预注入 {comp_type: [{vertex, edge_a, edge_b, radius_mm}]}（测试用）。
    返回结果 dict。
    """
    base = Path(base_dir).resolve()
    out_dir = Path(out_dir or (DEFAULT_OUT / base.name))
    out_dir.mkdir(parents=True, exist_ok=True)

    ir = json.loads((base / "raw_fixed.json").read_text(encoding="utf-8"))
    ir_mod = copy.deepcopy(ir)

    # API key
    if llm_fillets is None:
        key = API_KEY_FILE.read_text(encoding="utf-8").strip()
        os.environ["DEEPSEEK_API_KEY"] = key

    result = {"ok": True, "base_dir": str(base), "components": {}}

    for op, comp_type, edge_factor, _plane_desc, r_min, r_max in COMPONENT_SPECS:
        comp = _find_component_with_op(ir_mod, op)
        if comp is None:
            continue
        pts = _find_profile_points(ir_mod, comp)
        roles = _build_component_roles(pts, comp_type)
        cands = build_candidate_table_generic(pts, roles)

        if llm_fillets is not None:
            fillets_for = llm_fillets.get(comp_type, [])
        else:
            fillets_for = _call_llm_fillet(
                build_selection_prompt(cands, comp_type, r_min, r_max), max_attempts)

        plan = build_component_plan(pts, roles, edge_factor, fillets_for)
        new_ids = _replace_fillet_chain(ir_mod, plan, comp, op)

        comp_result = {
            "comp_type": comp_type, "component": comp,
            "n_candidates": len(cands), "n_selected": len(plan["corners"]),
            "selected_roles": {c["role"]: 0 for c in plan["corners"]},
            "groups": plan["groups"], "final_radii": plan["final_radii"],
            "feedback": plan["feedback"], "new_fillet_node_ids": new_ids,
        }
        for c in plan["corners"]:
            comp_result["selected_roles"][c["role"]] += 1
        result["components"][comp_type] = comp_result

    raw_path = out_dir / "raw_fillet_selected.json"
    raw_path.write_text(json.dumps(ir_mod, ensure_ascii=False, indent=2), encoding="utf-8")
    result["raw_path"] = str(raw_path)

    if not rebuild:
        return result

    step_path = out_dir / "output.step"
    meta_path = out_dir / "output.metadata.json"
    try:
        from seekflow_engineering_tools.generative_cad.pipeline.run import (
            run_gcad_core_from_files,
        )
        res = run_gcad_core_from_files(raw_path, step_path, meta_path)
    except Exception as exc:
        result["rebuild"] = {"ok": False, "error": f"重建异常: {exc}"}
        result["ok"] = False
        return result

    rb = {"ok": res.ok, "step": str(step_path),
          "warnings": list(res.warnings) if res.warnings else [],
          "error": getattr(res, "error", None)}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            gp = meta.get("validation", {}).get("geometry_postcheck", {})
            rb["geometry_postcheck"] = {k: gp.get(k)
                                        for k in ("ok", "volume_mm3", "n_solids", "closed", "is_valid_solid")}
        except Exception:
            pass
    fillet_pt = [w for w in rb["warnings"]
                 if "fillet" in str(w).lower() and ("pass" in str(w).lower() or "skip" in str(w).lower())]
    rb["fillet_passthrough_warnings"] = fillet_pt
    result["rebuild"] = rb
    result["ok"] = res.ok and (not fillet_pt)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM 自由选择圆角 → 主流程（盘面+榫槽统一）规划器")
    ap.add_argument("--base-dir", default=None, help="主流程建模产物目录（含 raw_fixed.json + output.step）")
    ap.add_argument("--out", default=None, help="输出目录（默认 _param_experiment/output/fillet_select/<hash>）")
    ap.add_argument("--no-rebuild", action="store_true", help="只规划生成节点，不重建 STEP")
    ap.add_argument("--max-attempts", type=int, default=2, help="LLM 调用最大尝试次数")
    args = ap.parse_args(argv)

    base = Path(args.base_dir).resolve() if args.base_dir else DEFAULT_BASE
    if not (base / "raw_fixed.json").exists():
        print(f"ERROR: 目标目录缺 raw_fixed.json: {base}", file=sys.stderr)
        return 2

    result = apply_llm_fillet_selection(
        base, out_dir=args.out, max_attempts=args.max_attempts, rebuild=not args.no_rebuild,
    )

    print(f"[base] {base.name}")
    for ct, r in result.get("components", {}).items():
        print(f"=== {ct} 组件（{r['component']}）===")
        print(f"  选角 {r['n_selected']}/{r['n_candidates']}  分布 {r['selected_roles']}")
        print(f"  分组 {r['groups']}")
        print(f"  节点 {r['new_fillet_node_ids']}")
        if r["feedback"]:
            print(f"  feedback {r['feedback']}")
    print(f"[raw] {result['raw_path']}")
    if result.get("rebuild"):
        rb = result["rebuild"]
        print(f"[重建] ok={rb.get('ok')}")
        if rb.get("geometry_postcheck"):
            print(f"[几何] {rb['geometry_postcheck']}")
        if rb.get("fillet_passthrough_warnings"):
            print(f"[fillet跳过] {len(rb['fillet_passthrough_warnings'])} 个")
        if rb.get("error"):
            print(f"[错误] {rb['error']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
