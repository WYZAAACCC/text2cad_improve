"""LLM 自由选择圆角 → 移植到主流程（后处理圆角规划器）。

把实验最终方案（_param_experiment/output/llm_free_select_full 采用的 LLM 自由选择）
作用于主流程产物：读 raw_fixed.json → 候选角表 → LLM 自由选择 {顶点+两条边+半径}
→ 规划期安全半径 clamp → 生成/替换 fillet_sketch 节点 → run_gcad_core_from_files 重建。

零主程序改动：不改 integrations/engineering_tools/src/、不改 server/main.py。
圆角执行仍由主流程 sketch_profile 的 handle_fillet_sketch 承担（list 形式 + proximity 重匹配），
本工具只接管"圆角决策"（选角 + 安全半径），并保证 at_vertex_index 分区互不重叠。

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
    build_candidate_table,
    build_selection_prompt,
    free_select_schema,
    resolve_selection,
)
from fillet_corners import compute_safe_radius  # noqa: E402

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


# ── 语义定位（不依赖固定节点 id）─────────────────────────────────────────────


def _find_extrude_component(ir: dict) -> str:
    for n in ir["nodes"]:
        if n["op"] == "extrude_profile":
            return n["component"]
    raise ValueError("未找到工具体组件 (extrude_profile)")


def _find_slot_profile(ir: dict) -> list:
    comp = _find_extrude_component(ir)
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == "add_polyline":
            return n["params"]["points"]
    raise ValueError(f"组件 {comp} 未找到榫槽轮廓 (add_polyline)")


def _find_close_node(ir: dict, comp: str) -> dict:
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == "close_profile":
            return n
    raise ValueError(f"组件 {comp} 未找到 close_profile")


def _find_extrude_node(ir: dict, comp: str) -> dict:
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == "extrude_profile":
            return n
    raise ValueError(f"组件 {comp} 未找到 extrude_profile")


def _derive_teeth_count(pts: list) -> int:
    """从轮廓点数推导齿数：总点数 = 2*(5+4n)。26 点 → 2。"""
    total = len(pts)
    if total % 2 != 0:
        raise ValueError(f"轮廓点数 {total} 非偶数，无法推导齿数")
    n_upper = total // 2
    if (n_upper - 5) < 0 or (n_upper - 5) % 4 != 0:
        raise ValueError(f"上侧点数 {n_upper} 不符合 5+4n 结构")
    return (n_upper - 5) // 4


# ── LLM 自由选择 ─────────────────────────────────────────────────────────────


def _call_llm_fillet(prompt: str, max_attempts: int) -> tuple:
    """调 LLM 自由选择圆角。返回 (llm_fillets, feedback)。"""
    caller = DeepSeekToolCaller()
    feedback = []
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
            return list(r.arguments.get("fillets", [])), feedback
        except Exception as exc:
            last_err = str(exc)
            feedback.append(f"LLM 调用失败(尝试{attempt + 1}): {last_err}")
    raise RuntimeError(f"LLM 自由选择圆角失败: {last_err}")


def _role_group(key: str, role: str) -> str:
    if "tip" in key:
        return "tip"
    if role == "neck":
        return "neck"
    if role == "connector":
        return "connector"
    return "bottom"


# ── 生成 fillet 节点 ─────────────────────────────────────────────────────────


def build_fillet_plan(pts: list, teeth_count: int, llm_fillets: list) -> dict:
    """由 LLM 自由选择结果构建圆角计划（选角 → 安全半径 → 分组）。

    返回 {corners, at_vertex_map, groups, final_radii, feedback, safe}
      - corners: resolve_selection 后的候选角（含 vertex_idx/lower_vertex_idx）
      - at_vertex_map: {key: [vertex_idx, lower_vertex_idx]}
      - groups: [{radius, at_vertex_index: list}]（按 final radius 分组）
      - final_radii: {key: final_radius}
    """
    cands = build_candidate_table(pts, teeth_count)
    corners, llm_out, feedback = resolve_selection(cands, llm_fillets)
    if not corners:
        return {"corners": [], "at_vertex_map": {}, "groups": [], "final_radii": {},
                "feedback": feedback, "candidates": cands}

    # LLM 请求半径（按角）
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

    # radius_by_role（compute_safe_radius 按组）
    radius_by_role = {}
    for c in corners:
        g = _role_group(c["key"], c["role"])
        radius_by_role[g] = max(radius_by_role.get(g, 0), requested.get(c["key"], 0.5))

    # 规划期安全半径 clamp（从 pts 算邻边 + 相邻碰撞）
    safe = compute_safe_radius(corners, pts, radius_by_role)

    # 每角最终半径 = min(请求, 安全)
    final_radii = {}
    for c in corners:
        key = c["key"]
        final_radii[key] = min(requested.get(key, 0.5), safe.get(key, requested.get(key, 0.5)))

    # at_vertex_index（上下镜像）+ 按 final radius 分组（round 0.1）
    at_vertex_map = {c["key"]: [c["vertex_idx"], c["lower_vertex_idx"]] for c in corners}
    groups: dict[float, list] = {}
    for c in corners:
        r = round(final_radii[c["key"]], 1)
        groups.setdefault(r, []).append(c["key"])
    group_list = [{"radius": r, "at_vertex_index": sorted(
        sum((at_vertex_map[k] for k in keys), []))} for r, keys in sorted(groups.items(), reverse=True)]

    return {"corners": corners, "at_vertex_map": at_vertex_map, "groups": group_list,
            "final_radii": final_radii, "feedback": feedback, "candidates": cands}


def _replace_fillet_chain(ir: dict, plan: dict) -> list:
    """用新 fillet 节点替换 cutter 组件的原 fillet 链，返回新节点 id 列表。"""
    comp = _find_extrude_component(ir)
    close_node = _find_close_node(ir, comp)
    extrude_node = _find_extrude_node(ir, comp)

    # 删除原 fillet 节点
    kept = [n for n in ir["nodes"] if not (n["component"] == comp and n["op"] == "fillet_sketch")]

    # 生成新节点（链式：close → fillet1 → ... → filletN）
    new_ids = []
    prev_node = close_node["id"]
    for i, g in enumerate(plan["groups"], 1):
        nid = f"n_fillet_sel_{i}"
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

    # extrude 输入改指最后一个 fillet
    for n in kept:
        if n["id"] == extrude_node["id"]:
            n["inputs"] = [{"node": new_ids[-1], "output": "profile"}]

    ir["nodes"] = kept
    return new_ids


# ── 主流程 ───────────────────────────────────────────────────────────────────


def apply_llm_fillet_selection(
    base_dir: str | Path,
    out_dir: str | Path | None = None,
    max_attempts: int = 2,
    rebuild: bool = True,
    llm_fillets: list | None = None,
) -> dict:
    """对主流程产物执行 LLM 自由选择圆角 → 生成/替换 fillet 节点 →（可选）重建。

    llm_fillets 可预注入（测试/复用），否则调用 LLM 自由选择。
    返回结果 dict（选角/反馈/节点/重建状态）。
    """
    base = Path(base_dir).resolve()
    out_dir = Path(out_dir or (DEFAULT_OUT / base.name))
    out_dir.mkdir(parents=True, exist_ok=True)

    ir = json.loads((base / "raw_fixed.json").read_text(encoding="utf-8"))
    pts = _find_slot_profile(ir)
    teeth_count = _derive_teeth_count(pts)

    # LLM 自由选择
    cands = build_candidate_table(pts, teeth_count)
    if llm_fillets is None:
        key = API_KEY_FILE.read_text(encoding="utf-8").strip()
        os.environ["DEEPSEEK_API_KEY"] = key
        llm_fillets, _ = _call_llm_fillet(build_selection_prompt(cands, teeth_count), max_attempts)

    plan = build_fillet_plan(pts, teeth_count, llm_fillets)

    # 替换依赖链
    ir_mod = copy.deepcopy(ir)
    new_ids = _replace_fillet_chain(ir_mod, plan)

    raw_path = out_dir / "raw_fillet_selected.json"
    raw_path.write_text(json.dumps(ir_mod, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "ok": True,
        "base_dir": str(base),
        "teeth_count": teeth_count,
        "profile_point_count": len(pts),
        "n_candidates": len(cands),
        "n_selected": len(plan["corners"]),
        "selected_roles": {c["role"]: 0 for c in plan["corners"]},
        "groups": plan["groups"],
        "final_radii": plan["final_radii"],
        "feedback": plan["feedback"],
        "new_fillet_node_ids": new_ids,
        "raw_path": str(raw_path),
        "rebuild": {},
    }
    for c in plan["corners"]:
        result["selected_roles"][c["role"]] += 1

    if not rebuild:
        return result

    # 重建
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

    result["rebuild"] = {
        "ok": res.ok,
        "step": str(step_path),
        "warnings": list(res.warnings) if res.warnings else [],
        "error": getattr(res, "error", None),
    }
    # 提取 geometry_postcheck
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            gp = meta.get("validation", {}).get("geometry_postcheck", {})
            result["rebuild"]["geometry_postcheck"] = {
                k: gp.get(k) for k in ("ok", "volume_mm3", "n_solids", "closed", "is_valid_solid")
            }
        except Exception:
            pass
    # fillet pass-through 检查
    fillet_pt = [w for w in result["rebuild"].get("warnings", [])
                 if "fillet" in w.lower() and ("pass" in w.lower() or "skip" in w.lower())]
    result["rebuild"]["fillet_passthrough_warnings"] = fillet_pt
    result["ok"] = res.ok and (not fillet_pt)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM 自由选择圆角 → 主流程 fillet_sketch 节点规划器")
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
    print(f"[teeth] {result['teeth_count']}  轮廓点 {result['profile_point_count']}")
    print(f"[选角] {result['n_selected']}/{result['n_candidates']}  分布 {result['selected_roles']}")
    print(f"[分组] {result['groups']}")
    if result["feedback"]:
        print(f"[feedback] {result['feedback']}")
    print(f"[节点] {result['new_fillet_node_ids']}")
    print(f"[raw] {result['raw_path']}")
    if result.get("rebuild"):
        rb = result["rebuild"]
        print(f"[重建] ok={rb.get('ok')}  step={rb.get('step')}")
        if rb.get("geometry_postcheck"):
            print(f"[几何] {rb['geometry_postcheck']}")
        if rb.get("fillet_passthrough_warnings"):
            print(f"[fillet跳过] {len(rb['fillet_passthrough_warnings'])} 个 fillet pass-through")
        if rb.get("error"):
            print(f"[错误] {rb['error']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
