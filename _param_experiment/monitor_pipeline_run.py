"""驱动主流程生成 + 全程监控 + 绘制盘面/榫槽草图（人工检查）。

真实调用 server/main.py 的 _run_pipeline（L1 路由 → L2 创作 → repair loop → run），
与生产 Web 链路完全一致。生成完成后：
  1. 打印任务状态（_tasks）+ 产物文件检查
  2. 从 raw_fixed.json / llm_raw.json 提取盘面（XZ）+ 榫槽（XY）轮廓，绘制 PNG

用法:
  .conda/python.exe _param_experiment/monitor_pipeline_run.py [--task <id>] [--text <需求>] [--no-run]
  --no-run 只绘制不生成（用于已存在的任务目录）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

DEFAULT_TEXT = (
    "生成一个高压涡轮盘参考几何：轮毂-腹板-轮缘盘体，外径500mm，中心孔直径120mm，"
    "轴向最大厚度76mm，轮毂半厚38mm，轮缘半厚30mm，轮缘上60个双齿枞树形榫槽，"
    "分布半径250mm，槽深24mm，喉部半宽4mm，齿根圆角1mm。参考几何，非适航件。"
)


def _find_profile(ir: dict, component_op: str):
    comp = None
    for n in ir.get("nodes", []):
        if n["op"] == component_op:
            comp = n["component"]
            break
    if comp is None:
        return None, None
    for n in ir.get("nodes", []):
        if n["component"] == comp and n["op"] == "add_polyline":
            return comp, n["params"]["points"]
    return comp, None


def plot_profiles(ir: dict, out_png: Path, title: str):
    disc_comp, disc = _find_profile(ir, "revolve_profile")
    slot_comp, slot = _find_profile(ir, "extrude_profile")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    if disc:
        xs = [p["x_mm"] for p in disc]
        ys = [p["y_mm"] for p in disc]
        ax1.plot(xs, ys, "o-", lw=1.6, ms=3.5)
        ax1.set_title(f"盘面轮廓 (XZ) — {disc_comp} — {len(disc)} 点")
        ax1.set_xlabel("半径 mm"); ax1.set_ylabel("轴向 mm")
        ax1.set_aspect("equal"); ax1.grid(alpha=0.3)
    else:
        ax1.set_title("盘面轮廓：未找到")
    if slot:
        xs = [p["x_mm"] for p in slot]
        ys = [p["y_mm"] for p in slot]
        ax2.plot(xs, ys, "o-", lw=1.6, ms=3.5)
        ax2.set_title(f"榫槽轮廓 (XY) — {slot_comp} — {len(slot)} 点")
        ax2.set_xlabel("径向 mm (0=轮缘面)"); ax2.set_ylabel("切向半宽 mm")
        ax2.set_aspect("equal"); ax2.grid(alpha=0.3)
    else:
        ax2.set_title("榫槽轮廓：未找到")
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    plt.close(fig)
    return (disc_comp, len(disc)) if disc else (None, 0), (slot_comp, len(slot)) if slot else (None, 0)


def run_pipeline(task_id: str, text: str, force_route: str | None = None) -> dict:
    """调用主流程 _run_pipeline，监控状态与产物。"""
    key = (ROOT / "_archive" / "apikey.txt").read_text(encoding="utf-8").strip()
    os.environ["DEEPSEEK_API_KEY"] = key
    import main

    # 模拟 api_generate 先初始化 _tasks（否则 _update_task 是 no-op）
    main._tasks[task_id] = {"status": "pending"}

    out_dir = main.OUT_ROOT / task_id
    print(f"[驱动] task={task_id}")
    print(f"[需求] {text[:60]}...")
    if force_route:
        print(f"[路由] force_route={force_route}（跳过 L1）")

    main._run_pipeline(task_id, text, force_route=force_route)

    t = main._tasks.get(task_id, {})
    print(f"[状态] {t.get('status')}")
    if t.get("error"):
        print(f"[错误] {t['error'][:400]}")
    print(f"[结果] {json.dumps(t.get('result', {}), ensure_ascii=False)[:400]}")

    print("\n=== 产物检查 ===")
    for f in ["prompt_trace_l1.json", "route_plan.json", "llm_raw.json", "raw_fixed.json",
              "validation_report.json", "repair_summary.json", "validation_execution.json",
              "output.metadata.json", "output.step", "output.stl"]:
        p = out_dir / f
        kb = p.stat().st_size // 1024 if p.exists() else 0
        print(f"  {f:28s} {'OK' if p.exists() else '缺失':4s} {kb}KB")

    # 校验报告摘要
    vr = out_dir / "validation_report.json"
    if vr.exists():
        rep = json.loads(vr.read_text(encoding="utf-8"))
        print(f"[validation] ok={rep.get('ok')} stages={len(rep.get('stages_run', []))}")

    # 绘制草图
    ir_path = out_dir / "raw_fixed.json"
    src = "raw_fixed.json"
    if not ir_path.exists():
        ir_path = out_dir / "llm_raw.json"
        src = "llm_raw.json"
    if ir_path.exists():
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        png = out_dir / "sketch_check.png"
        d, s = plot_profiles(ir, png, f"{task_id} — 盘面与榫槽草图（{src}）")
        print(f"[绘制] {png}")
        print(f"[盘面] {d}  [榫槽] {s}")
        # 也绘制 LLM 首轮（如与 final 不同）
        llm_path = out_dir / "llm_raw.json"
        if llm_path.exists() and src == "raw_fixed.json":
            ir2 = json.loads(llm_path.read_text(encoding="utf-8"))
            png2 = out_dir / "sketch_check_llm.png"
            d2, s2 = plot_profiles(ir2, png2, f"{task_id} — LLM 首轮草图（llm_raw.json）")
            print(f"[绘制-LLM首轮] {png2}  盘面{d2} 榫槽{s2}")
    else:
        print("[绘制] 无 raw 可绘")
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="驱动主流程生成 + 监控 + 绘制草图")
    ap.add_argument("--task", default=None, help="任务 id（默认自动生成）")
    ap.add_argument("--text", default=DEFAULT_TEXT, help="建模需求")
    ap.add_argument("--force-route", default=None,
                    help="跳过 L1 强制路由（如 generative_cad_ir）；None=走完整 L1")
    ap.add_argument("--no-run", action="store_true", help="只绘制已存在任务，不生成")
    args = ap.parse_args(argv)

    task_id = args.task or f"mon_{uuid.uuid4().hex[:12]}"
    if args.no_run:
        # 只绘制
        out_dir = ROOT / "app" / "text-to-cad" / "server" / "output" / task_id
        for name in ("raw_fixed.json", "llm_raw.json"):
            p = out_dir / name
            if p.exists():
                ir = json.loads(p.read_text(encoding="utf-8"))
                png = out_dir / f"sketch_check_{name.split('.')[0]}.png"
                plot_profiles(ir, png, f"{task_id} — {name}")
                print(f"[绘制] {png}")
                break
        return 0
    run_pipeline(task_id, args.text, force_route=args.force_route)
    return 0


if __name__ == "__main__":
    sys.exit(main())
