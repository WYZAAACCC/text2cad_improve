"""基准（参数化模板）vs Agent 系统 llm_raw 对比核对。

以参数化模板（param_templates.build_slot_disc）生成的纯榫槽涡轮盘 llm_raw 为基准，
用相同参数的 prompt 驱动 agentic_l2（Agent A 规划 + disc/slot 轮廓 agent）生成 llm_raw，
逐项核对 agent 输出与基准是否一致，检查 agent 生成系统能否正常生成。

用法（需 DEEPSEEK_API_KEY 环境变量）:
  .conda/python.exe _param_experiment/_compare_agentic_vs_template.py                 # 完整流程
  .conda/python.exe _param_experiment/_compare_agentic_vs_template.py --baseline-only  # 仅生成基准
  .conda/python.exe _param_experiment/_compare_agentic_vs_template.py --family D15 --repeat 3
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# The output tree no longer sits beside this file; see _paths.py.
from _paths import output_root  # noqa: E402
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES, build_text  # noqa: E402
from candidate_sampler import _subject, fam_features  # noqa: E402
from param_templates import build_slot_disc, SLOT_CATS  # noqa: E402


# ── 基准生成 ──────────────────────────────────────────────────

def make_baseline(fam_id: str) -> dict:
    """设计族 → 基准 llm_raw（参数化模板确定性生成，纯榫槽）。"""
    fam = DESIGN_FAMILIES[fam_id]
    assert fam["category"] in SLOT_CATS, f"{fam_id} 不是榫槽类（{fam['category']}）"
    params = _subject(fam)
    params.update(fam_features(fam))
    params["category"] = fam["category"]
    raw = build_slot_disc(params)
    return {"fam_id": fam_id, "text": build_text(fam), "params": params, "llm_raw": raw}


# ── llm_raw 特征提取 ──────────────────────────────────────────

def _comp_by_hint(raw: dict, keys: tuple[str, ...]):
    for c in raw.get("components", []):
        kh = (c.get("kind_hint") or "").lower()
        if any(k in kh for k in keys):
            return c
    return None


def _points_of(raw: dict, comp_id: str) -> list:
    for n in raw.get("nodes", []):
        if n.get("op") == "add_polyline" and n.get("component") == comp_id:
            return n.get("params", {}).get("points", [])
    return []


def _to_xy(pts: list) -> list:
    return [(float(p["x_mm"]), float(p["y_mm"])) for p in pts if isinstance(p, dict)]


def extract(raw: dict) -> dict:
    """从 llm_raw 提取可核对特征（盘体/榫槽轮廓 + 关键结构参数）。"""
    disc_comp = _comp_by_hint(raw, ("disc",))
    slot_comp = _comp_by_hint(raw, ("cutter", "slot"))
    disc_pts = _to_xy(_points_of(raw, disc_comp["id"])) if disc_comp else []
    slot_pts = _to_xy(_points_of(raw, slot_comp["id"])) if slot_comp else []

    # 结构参数
    ops = [n.get("op") for n in raw.get("nodes", [])]
    pattern_count = None
    for n in raw.get("nodes", []):
        if n.get("op") == "circular_pattern_component":
            pattern_count = n.get("params", {}).get("count")
            break
    dialects = [d.get("dialect") for d in raw.get("selected_dialects", [])]

    return {
        "has_disc_comp": disc_comp is not None,
        "has_slot_comp": slot_comp is not None,
        "disc_kind_hint": disc_comp.get("kind_hint") if disc_comp else None,
        "slot_kind_hint": slot_comp.get("kind_hint") if slot_comp else None,
        "disc_points": disc_pts, "slot_points": slot_pts,
        "n_nodes": len(raw.get("nodes", [])),
        "ops": ops,
        "pattern_count": pattern_count,
        "has_boolean_cut": "boolean_cut" in ops,
        "dialects": dialects,
    }


# ── 轮廓质量检查（复用 _test_agentic_batch 的退化判定）────────

def _slot_issues(pts: list, teeth: int) -> list:
    """榫槽轮廓退化检查。返回问题列表（空=通过）。"""
    issues = []
    if not pts or len(pts) < 4:
        return ["无有效榫槽轮廓"]
    expected = 2 * (2 + 4 * teeth + 3)
    if len(pts) != expected:
        issues.append(f"点数 {len(pts)} != 期望 {expected}")
    half = len(pts) // 2
    root = abs(pts[half - 1][1])
    if root < 2:
        issues.append(f"root 半宽 {root:.2f} < 2")
    # 对称
    for i in range(half):
        r, l = pts[i], pts[len(pts) - 1 - i]
        if abs(r[0] - l[0]) > 1e-6 or abs(r[1] + l[1]) > 0.5:
            issues.append("不对称")
            break
    # 重复点 / 短边
    for i in range(len(pts) - 1):
        d = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if d < 0.02:
            issues.append(f"短边/重复点 @ {i}")
            break
    # lobe 递减
    ys = [p[1] for p in pts[:half]]
    peaks = []
    for i in range(1, half - 1):
        if ys[i] >= ys[i - 1] and ys[i] > ys[i + 1]:
            peaks.append(round(ys[i], 3))
    if len(peaks) >= 2 and not all(a > b for a, b in zip(peaks, peaks[1:])):
        issues.append(f"lobe 未递减 {peaks}")
    return issues


def _hausdorff(a: list, b: list) -> float:
    """点集 A → B 的单向 Hausdorff 距离（每点到对方最近点，取最大）。"""
    if not a or not b:
        return float("inf")
    best = [min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in b) for p in a]
    return max(best)


def _points_divergence(gold: list, gen: list) -> dict:
    """轮廓点几何偏差：点数差 + 双向 Hausdorff + 每点平均最近距离。"""
    if not gold or not gen:
        return {"n_gold": len(gold), "n_gen": len(gen), "hausdorff_mm": float("inf")}
    h1 = _hausdorff(gen, gold)
    h2 = _hausdorff(gold, gen)
    mean = sum(min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in gold) for p in gen) / len(gen)
    return {"n_gold": len(gold), "n_gen": len(gen),
            "hausdorff_mm": round(max(h1, h2), 3), "mean_nearest_mm": round(mean, 3)}


# ── 比较 ──────────────────────────────────────────────────────

def compare(fam_id: str, baseline: dict, agent_raw: dict) -> dict:
    b = extract(baseline["llm_raw"])
    a = extract(agent_raw)
    teeth = int(baseline["params"].get("teeth", 2))
    slots = int(baseline["params"].get("slots", 40))

    result = {
        "fam_id": fam_id,
        "structure": {
            "disc_comp": a["has_disc_comp"], "disc_kind_hint": a["disc_kind_hint"],
            "slot_comp": a["has_slot_comp"], "slot_kind_hint": a["slot_kind_hint"],
            "pattern_count": a["pattern_count"], "expected_slots": slots,
            "pattern_ok": a["pattern_count"] == slots,
            "has_boolean_cut": a["has_boolean_cut"],
            "has_sketch_profile_dialect": "sketch_profile" in a["dialects"],
            "has_composition_dialect": "composition" in a["dialects"],
        },
        "disc_divergence": _points_divergence(b["disc_points"], a["disc_points"]),
        "slot_divergence": _points_divergence(b["slot_points"], a["slot_points"]),
        "slot_issues": _slot_issues(a["slot_points"], teeth) if a["slot_points"] else ["无榫槽轮廓"],
    }
    struct = result["structure"]
    result["ok"] = bool(
        struct["disc_comp"] and struct["slot_comp"] and struct["has_boolean_cut"]
        and not result["slot_issues"] and result["slot_divergence"]["n_gen"] == result["slot_divergence"]["n_gold"]
    )
    return result


def _report(res: dict) -> str:
    lines = [f"\n=== 核对报告：{res['fam_id']} ===",
             f"结构: 盘体组件={res['structure']['disc_comp']}({res['structure']['disc_kind_hint']})  "
             f"榫槽组件={res['structure']['slot_comp']}({res['structure']['slot_kind_hint']})",
             f"参数: circular_pattern count={res['structure']['pattern_count']} (期望 {res['structure']['expected_slots']})  "
             f"boolean_cut={res['structure']['has_boolean_cut']}",
             f"方言: sketch_profile={res['structure']['has_sketch_profile_dialect']}  "
             f"composition={res['structure']['has_composition_dialect']}",
             f"盘体轮廓: 基准 {res['disc_divergence'].get('n_gold')} 点 vs agent {res['disc_divergence'].get('n_gen')} 点  "
             f"Hausdorff={res['disc_divergence'].get('hausdorff_mm')}mm  平均最近={res['disc_divergence'].get('mean_nearest_mm')}mm",
             f"榫槽轮廓: 基准 {res['slot_divergence'].get('n_gold')} 点 vs agent {res['slot_divergence'].get('n_gen')} 点  "
             f"Hausdorff={res['slot_divergence'].get('hausdorff_mm')}mm  平均最近={res['slot_divergence'].get('mean_nearest_mm')}mm",
             f"榫槽退化检查: {res['slot_issues'] or '通过'}",
             f"结论: {'通过 ✅  agent 生成了与基准一致的涡轮盘' if res['ok'] else '未完全通过 ❌  见上方差异'}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="D15")
    ap.add_argument("--repeat", type=int, default=1, help="agent 生成重复次数（取最佳）")
    ap.add_argument("--baseline-only", action="store_true")
    args = ap.parse_args(argv)

    baseline = make_baseline(args.family)
    base_dir = output_root() / "_compare_agentic"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_path = base_dir / f"{args.family}_baseline_llm_raw.json"
    base_path.write_text(json.dumps(baseline["llm_raw"], ensure_ascii=False, indent=2), encoding="utf-8")
    bfeat = extract(baseline["llm_raw"])
    print(f"[基准] {args.family} 已生成 -> {base_path}")
    print(f"  盘体轮廓 {len(bfeat['disc_points'])} 点  榫槽轮廓 {len(bfeat['slot_points'])} 点  "
          f"nodes={bfeat['n_nodes']}  pattern_count={bfeat['pattern_count']}")

    if args.baseline_only:
        return 0

    # Agent 生成（需 DEEPSEEK_API_KEY）
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig  # noqa: E402
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller  # noqa: E402
    from agentic_l2 import run_agentic_l2  # noqa: E402

    config = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
    caller = DeepSeekToolCaller()

    results = []
    for i in range(args.repeat):
        out_dir = base_dir / args.family / f"run{i}"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            agent_raw = run_agentic_l2(baseline["text"], None, caller=caller,
                                       llm_model_config=config, out_dir=out_dir)
            res = compare(args.family, baseline, agent_raw)
            res["_run"] = i
            results.append(res)
            print(f"[agent run{i}] ok={res['ok']} 盘体 {res['disc_divergence'].get('n_gen')} 点  "
                  f"榫槽 {res['slot_divergence'].get('n_gen')} 点  issues={res['slot_issues'][:2]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[agent run{i}] ERROR {type(exc).__name__}: {str(exc)[:160]}")

    if not results:
        print("\n[失败] agent 系统多次运行均未产出可比较的 llm_raw")
        return 2

    # 选最优：ok 优先，其次结构完整度（disc+slot 组件），再次轮廓退化问题最少
    def _score(r):
        s = r["structure"]
        struct_n = sum([s["disc_comp"], s["slot_comp"], s["has_boolean_cut"]])
        return (1 if r["ok"] else 0, struct_n, -len(r["slot_issues"]),
                -r["slot_divergence"].get("hausdorff_mm", 1e9))
    best = max(results, key=_score)
    (base_dir / args.family / "compare_report.json").write_text(
        json.dumps({"best_run": best.get("_run"), "all_runs": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(_report(best))
    return 0 if best["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())