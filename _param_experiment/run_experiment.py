"""涡轮盘/榫槽轮廓参数化 — 隔离 LLM 实验主脚本。

隔离运行，不触碰主程序。只读复用:
  - DeepSeekToolCaller / LlmModelConfig（generative_cad.llm）
  - to_deepseek_strict_schema（generative_cad.authoring.strict_schema）

用法:
  .conda/python.exe _param_experiment/run_experiment.py [--combos A,B,C,D] [--smoke]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 无 GUI 后端
import matplotlib.pyplot as plt

# 中文字体支持（Windows: SimHei / Microsoft YaHei）
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

# ── 隔离路径 ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent          # auto_detection_process
SRC = ROOT / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
    to_deepseek_strict_schema,
)

from param_prompts import (
    COMBINATIONS,
    PROFILE_SCHEMA,
    build_system_prompt,
)

OUT_ROOT = Path(__file__).resolve().parent / "output"
DEFAULT_OUTDIR = "solutionA_round2"
OUT = OUT_ROOT / DEFAULT_OUTDIR

API_KEY_FILE = ROOT / "_archive" / "apikey.txt"

MODEL_CONFIG = LlmModelConfig(
    model="deepseek-v4-pro",
    base_url="https://api.deepseek.com/beta",
)

TOOL_NAME = "generate_profiles"
TOOL_DESC = (
    "Generate turbine disc R-Z profile points and fir-tree slot XY profile points "
    "from the given parameterized rules and parameters."
)


# ── LLM 调用 ────────────────────────────────────────────────────────────────

def call_llm(system_prompt: str) -> dict:
    caller = DeepSeekToolCaller()
    strict_schema = to_deepseek_strict_schema(PROFILE_SCHEMA)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按上述参数化规则输出盘面与榫槽轮廓点。"},
    ]
    result = caller.call_strict_tool(
        messages=messages,
        tool_name=TOOL_NAME,
        tool_description=TOOL_DESC,
        tool_schema=strict_schema,
        model_config=MODEL_CONFIG,
    )
    return dict(result.arguments)


# ── 校验 ────────────────────────────────────────────────────────────────────

def validate_disc(points, params: dict) -> list[str]:
    issues = []
    if len(points) != 12:
        issues.append(f"盘面点数={len(points)}，应为 12")
    else:
        # 对称性: 点 i 与点 (12-i) 应 y 相反、x 相同
        for i in range(6):
            p, q = points[i], points[11 - i]
            if abs(p["x_mm"] - q["x_mm"]) > 1e-6 or abs(p["y_mm"] + q["y_mm"]) > 1e-6:
                issues.append(f"盘面不对称: 点{i+1}({p}) vs 点{12-i}({q})")
                break
    xs = [p["x_mm"] for p in points]
    br, rr = params["bore_radius_mm"], params["rim_radius_mm"]
    if xs and (min(xs) < br - 1 or max(xs) > rr + 1):
        issues.append(f"盘面半径越界: min_x={min(xs)} max_x={max(xs)} (应 [{br},{rr}])")
    return issues


def validate_slot(points, params: dict) -> list[str]:
    issues = []
    tc = params["teeth_count"]
    expected = 2 * (2 + 4 * tc + 3)
    if len(points) != expected:
        issues.append(f"榫槽点数={len(points)}，应为 2×({2 + 4 * tc + 3})={expected}（teeth_count={tc}）")
    if points:
        xs = [p["x_mm"] for p in points]
        if max(xs) > 0.01:
            issues.append(f"榫槽 x 不应为正: max_x={max(xs)}")
        if min(xs) < -params["slot_depth_mm"] - 1:
            issues.append(f"榫槽超深: min_x={min(xs)} vs slot_depth={params['slot_depth_mm']}")
    return issues


# ── 绘制 ────────────────────────────────────────────────────────────────────

def _closed(points) -> tuple[list, list]:
    xs = [p["x_mm"] for p in points] + [points[0]["x_mm"]]
    ys = [p["y_mm"] for p in points] + [points[0]["y_mm"]]
    return xs, ys


def plot_disc(points, params: dict, label: str, out_path: Path) -> None:
    xs, ys = _closed(points)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, "-o", color="#1f77b4", ms=3, lw=1.5)
    ax.axhline(0, color="gray", lw=0.6, ls="--")
    ax.set_aspect("equal")
    ax.set_title(f"Disc R-Z Profile — {label}\n12 points, bore={params['bore_radius_mm']} hub={params['hub_radius_mm']} rim={params['rim_radius_mm']}")
    ax.set_xlabel("Radius (mm)  [x]")
    ax.set_ylabel("Axial (mm)  [y]")
    ax.grid(alpha=0.3)
    # 标注关键半径
    for r, nm in [("bore_radius_mm", "bore"), ("hub_radius_mm", "hub"),
                  ("rim_web_junction_mm", "web/rim"), ("rim_radius_mm", "rim")]:
        ax.axvline(params[r], color="gray", lw=0.5, ls=":")
        ax.text(params[r], ys[0], nm, fontsize=7, rotation=90, va="bottom")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_slot(points, params: dict, label: str, out_path: Path) -> None:
    xs, ys = _closed(points)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, "-o", color="#d62728", ms=3, lw=1.5)
    ax.axhline(0, color="gray", lw=0.6, ls="--")
    ax.set_aspect("equal")
    ax.set_title(f"Fir-tree Slot XY Profile — {label}\nteeth={params['teeth_count']}, depth={params['slot_depth_mm']}mm, flank={params['flank_angle_deg']}deg")
    ax.set_xlabel("Radial depth (mm)  [x, 0=rim surface]")
    ax.set_ylabel("Tangential half-width (mm)  [y]")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ── 参数忠实度对照 ─────────────────────────────────────────────────────────

def compare_params(input_params: dict, used_params: dict) -> list[str]:
    diffs = []
    for k, v in input_params.items():
        uv = used_params.get(k)
        if uv is None:
            diffs.append(f"  - {k}: 输入={v} 但 LLM 未回传")
        elif abs(float(uv) - float(v)) > 1e-6:
            diffs.append(f"  - {k}: 输入={v}  LLM 采用={uv}")
    return diffs


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main(combos: list[str], smoke: bool = False, outdir: str | None = None) -> None:
    global OUT
    if outdir:
        OUT = OUT_ROOT / outdir
    OUT.mkdir(parents=True, exist_ok=True)

    key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        print("!! _archive/apikey.txt 为空")
        sys.exit(1)
    os.environ["DEEPSEEK_API_KEY"] = key
    print(f"API key loaded: {key[:6]}...")
    print(f"产物目录: {OUT}")

    report = {"generated": "2026-08-03", "combos": {}}
    for cid in combos:
        combo = COMBINATIONS[cid]
        print(f"\n{'='*60}\n[{cid}] {combo['label']}")
        try:
            sys_prompt = build_system_prompt(combo)
            args = call_llm(sys_prompt)
        except Exception as e:
            print(f"  !! LLM 调用失败: {type(e).__name__}: {e}")
            report["combos"][cid] = {"status": "error", "error": str(e)}
            continue

        # 保存原始 LLM 输出
        llm_path = OUT / f"llm_{cid}.json"
        llm_path.write_text(json.dumps(args, ensure_ascii=False, indent=2), encoding="utf-8")

        disc_pts = args.get("disc_points", [])
        slot_pts = args.get("slot_points", [])
        disc_used = args.get("disc_params_used", {})
        slot_used = args.get("slot_params_used", {})

        # 校验
        disc_issues = validate_disc(disc_pts, combo["disc"])
        slot_issues = validate_slot(slot_pts, combo["slot"])
        print(f"  disc_points={len(disc_pts)}  slot_points={len(slot_pts)}")
        for i in disc_issues:
            print(f"  [盘面校验] {i}")
        for i in slot_issues:
            print(f"  [榫槽校验] {i}")

        # 参数忠实度
        print("  -- 盘面参数对照 --")
        for d in compare_params(combo["disc"], disc_used):
            print(d)
        print("  -- 榫槽参数对照 --")
        for d in compare_params(combo["slot"], slot_used):
            print(d)

        # 小数保留检查
        all_coords = []
        for p in list(disc_pts) + list(slot_pts):
            all_coords.extend([float(p["x_mm"]), float(p["y_mm"])])
        n_frac = sum(1 for v in all_coords if not float(v).is_integer())
        print(f"  小数保留: 共 {len(all_coords)} 个坐标，含小数 {n_frac} 个")

        # 输入含小数的参数是否精确回传
        for name, inp, used in (("盘面", combo["disc"], disc_used), ("榫槽", combo["slot"], slot_used)):
            for k, v in inp.items():
                if isinstance(v, float) and not float(v).is_integer():
                    uv = used.get(k)
                    exact = uv is not None and abs(float(uv) - float(v)) < 1e-9
                    print(f"  精度 {name}.{k}: 输入={v} 回传={uv} [{'OK' if exact else 'MISMATCH'}]")

        # 绘制
        if disc_pts:
            plot_disc(disc_pts, combo["disc"], combo["label"], OUT / f"disc_profile_{cid}.png")
        if slot_pts:
            plot_slot(slot_pts, combo["slot"], combo["label"], OUT / f"slot_profile_{cid}.png")
        print(f"  → PNG 已生成: disc_profile_{cid}.png, slot_profile_{cid}.png")

        report["combos"][cid] = {
            "status": "ok",
            "disc_points": len(disc_pts),
            "slot_points": len(slot_pts),
            "disc_issues": disc_issues,
            "slot_issues": slot_issues,
        }

    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成。产物目录: {OUT}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--combos", default="A_baseline,B_small,C_large_3tooth,D_steep_flank")
    ap.add_argument("--smoke", action="store_true", help="只跑第一个组合做冒烟")
    ap.add_argument("--outdir", default=None, help="output 下的子目录名，默认 solutionA_round2")
    args = ap.parse_args()
    combos = [c.strip() for c in args.combos.split(",") if c.strip()]
    if args.smoke:
        combos = combos[:1]
    main(combos, smoke=args.smoke, outdir=args.outdir)
