"""临时：多次运行 agent 系统（Agent A + 轮廓 agent），只检查 llm_raw 轮廓质量（不跑 validation）。

统计：root≥2 / 点数==2×(2+4×teeth+3) / 对称 / 无短边 / lobe 递减 的成功率。
用法: .conda/python.exe _param_experiment/_test_agentic_batch.py [--n 5]
"""
import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
# DEEPSEEK_API_KEY must be set in the environment.
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES, build_text
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from agentic_l2 import run_agentic_l2


def check_slot(pts, teeth):
    """榫槽轮廓质量检查。返回问题列表（空=通过）。"""
    issues = []
    if not isinstance(pts, list) or len(pts) < 4:
        return ["无有效轮廓"]
    n = len(pts)
    expected = 2 * (2 + 4 * teeth + 3)
    if n != expected:
        issues.append(f"点数 {n} != 期望 {expected}")
    half = n // 2
    root_y = abs(pts[half - 1].get("y_mm", 0))
    if root_y < 2:
        issues.append(f"root 半宽 {root_y:.1f} < 2")
    for i in range(half):
        r, l = pts[i], pts[n - 1 - i]
        if abs(r["x_mm"] - l["x_mm"]) > 1e-6 or abs(r["y_mm"] + l["y_mm"]) > 0.5:
            issues.append("不对称")
            break
    for i in range(n - 1):
        d = ((pts[i + 1]["x_mm"] - pts[i]["x_mm"]) ** 2 +
             (pts[i + 1]["y_mm"] - pts[i]["y_mm"]) ** 2) ** 0.5
        if d < 1e-6:
            issues.append("重复点")
            break
    ys = [p["y_mm"] for p in pts[:half]]
    peaks = []
    for i in range(1, half - 1):
        if ys[i] >= ys[i - 1] and ys[i] > ys[i + 1]:
            peaks.append(round(ys[i], 3))
    if len(peaks) >= 2 and not all(a > b for a, b in zip(peaks, peaks[1:])):
        issues.append(f"lobe 未递减 {peaks}")
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args(argv)

    text = build_text(DESIGN_FAMILIES["D15"])  # teeth=2
    teeth = 2
    config = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
    caller = DeepSeekToolCaller()
    out_root = ROOT / "app" / "text-to-cad" / "server" / "output" / "_agentic_batch"

    stats = {"runs": 0, "root_ok": 0, "points_ok": 0, "sym_ok": 0, "no_shortedge_ok": 0,
             "lobe_ok": 0, "all_ok": 0, "errors": 0}
    details = []
    for i in range(args.n):
        d = out_root / f"run{i}"
        d.mkdir(parents=True, exist_ok=True)
        try:
            raw = run_agentic_l2(text, None, caller=caller, llm_model_config=config, out_dir=d)
            # 提取榫槽轮廓（component kind_hint = fir_tree_cutter 的 add_polyline）
            slot_pts = None
            comps = {c.get("id"): c for c in raw.get("components", [])}
            for n_ in raw.get("nodes", []):
                if n_.get("op") == "add_polyline":
                    comp = comps.get(n_.get("component"), {})
                    if comp.get("kind_hint") == "fir_tree_cutter":
                        slot_pts = n_.get("params", {}).get("points")
            issues = check_slot(slot_pts, teeth) if slot_pts else ["无榫槽轮廓"]
            stats["runs"] += 1
            if "root 半宽" not in " ".join(issues):
                stats["root_ok"] += 1
            if not any("点数" in x for x in issues):
                stats["points_ok"] += 1
            if "不对称" not in issues:
                stats["sym_ok"] += 1
            if "重复点" not in issues:
                stats["no_shortedge_ok"] += 1
            if "lobe 未递减" not in " ".join(issues):
                stats["lobe_ok"] += 1
            if not issues:
                stats["all_ok"] += 1
            details.append({"run": i, "ok": not issues, "issues": issues,
                            "root": round(abs(slot_pts[len(slot_pts) // 2 - 1]["y_mm"]), 2) if slot_pts else None,
                            "points": len(slot_pts) if slot_pts else 0})
            print(f"[run{i}] ok={not issues} root={details[-1]['root']} pts={details[-1]['points']} "
                  f"issues={issues[:3]}")
        except Exception as exc:
            stats["errors"] += 1
            print(f"[run{i}] ERROR {type(exc).__name__}: {str(exc)[:150]}")
            details.append({"run": i, "ok": False, "issues": [f"ERROR {str(exc)[:80]}"],
                            "root": None, "points": 0})

    n_ok = max(1, stats["runs"])
    print(f"\n=== 统计（{stats['runs']} 成功 / {args.n} 次，{stats['errors']} 错误）===")
    print(f"  root≥2:     {stats['root_ok']}/{n_ok} = {stats['root_ok']/n_ok*100:.0f}%")
    print(f"  点数正确:   {stats['points_ok']}/{n_ok} = {stats['points_ok']/n_ok*100:.0f}%")
    print(f"  对称:       {stats['sym_ok']}/{n_ok} = {stats['sym_ok']/n_ok*100:.0f}%")
    print(f"  无短边:     {stats['no_shortedge_ok']}/{n_ok} = {stats['no_shortedge_ok']/n_ok*100:.0f}%")
    print(f"  lobe 递减:  {stats['lobe_ok']}/{n_ok} = {stats['lobe_ok']/n_ok*100:.0f}%")
    print(f"  全部通过:   {stats['all_ok']}/{n_ok} = {stats['all_ok']/n_ok*100:.0f}%")
    (out_root / "batch_report.json").write_text(
        json.dumps({"stats": stats, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
