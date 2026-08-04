"""大量参数组合并行测试 — multiprocessing 并行 worker 加速。

12 组参数组合（覆盖外径/中心孔/轴厚/槽数/槽深/喉部/齿数/齿根圆角 9 维度），
每组走完整真实 pipeline（_run_pipeline force-route IR 主路径），并行跑。

用法:
  .conda/python.exe _param_experiment/param_sweep_parallel.py --batch 1   # 跑第 1 批（组 1-3，3 worker 并行）
  .conda/python.exe _param_experiment/param_sweep_parallel.py --batch 1 --workers 3
  分批并行启动可整体加速（如同时启动 --batch 1 与 --batch 2）。
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from param_sweep_test import _text, _expect, run_case  # noqa: E402


# ── 12 组参数组合（单参数扫描 + 组合）───────────────────────
def _t(od=500, bore=120, thick=76, hub=38, rim=30, slots=60, teeth=2, R=250,
       depth=24, throat=4.0, fr=1.0):
    return _text(od, bore, thick, hub, rim, slots, teeth, R, depth, throat, fr)


def _e(od=500, bore=120, thick=76, slots=60, teeth=2, depth=24, throat=4.0, fr=1.0):
    return _expect(od, bore, thick, slots, teeth, depth, throat, fr)


CASES = [
    {"name": "P1_slots_48",  "text": _t(slots=48),  "expect": _e(slots=48)},
    {"name": "P2_slots_72",  "text": _t(slots=72),  "expect": _e(slots=72)},
    {"name": "P3_depth_28",  "text": _t(depth=28),  "expect": _e(depth=28)},
    {"name": "P4_depth_20",  "text": _t(depth=20),  "expect": _e(depth=20)},
    {"name": "P5_od_460",    "text": _t(od=460, R=230), "expect": _e(od=460)},
    {"name": "P6_od_540",    "text": _t(od=540, R=270), "expect": _e(od=540)},
    {"name": "P7_bore_110",  "text": _t(bore=110),  "expect": _e(bore=110)},
    {"name": "P8_bore_130",  "text": _t(bore=130),  "expect": _e(bore=130)},
    {"name": "P9_thick_66",  "text": _t(thick=66, hub=33, rim=26),
     "expect": _e(thick=66)},
    {"name": "P10_throat_35", "text": _t(throat=3.5), "expect": _e(throat=3.5)},
    {"name": "P11_throat_50", "text": _t(throat=5.0), "expect": _e(throat=5.0)},
    {"name": "P12_teeth3",   "text": _t(teeth=3, depth=28, fr=1.2),
     "expect": _e(teeth=3, depth=28, fr=1.2)},
]

BATCH_SIZE = 3


def _worker(case: dict) -> dict:
    """单个 worker 进程跑一组。返回 (name, status, verify 摘要)。"""
    try:
        r = run_case(case, no_run=False, force_route="generative_cad_ir")
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        r = {"name": case["name"], "status": "exc",
             "verify": {"ok": False, "reason": f"驱动异常: {exc}"}}
    v = r.get("verify", {})
    fails = [c["label"] for c in v.get("checks", []) if not c.get("ok")]
    return {"name": r.get("name", case["name"]), "status": r.get("status", "?"),
            "verify_ok": v.get("ok", False), "reason": v.get("reason", ""),
            "fails": fails, "task_id": r.get("task_id")}


def run_batch(batch_idx: int, workers: int = 3) -> list:
    start = (batch_idx - 1) * BATCH_SIZE
    batch = CASES[start:start + BATCH_SIZE]
    if not batch:
        print(f"[批 {batch_idx}] 无任务（共 {len(CASES)} 组，每批 {BATCH_SIZE} 组）")
        return []
    print(f"[批 {batch_idx}] 并行 {workers} worker: {[c['name'] for c in batch]}")
    with mp.Pool(processes=workers) as pool:
        results = pool.map(_worker, batch)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True, help="批次号（1 起，每批 3 组）")
    ap.add_argument("--workers", type=int, default=3, help="并行 worker 数")
    args = ap.parse_args(argv)

    print("=" * 72)
    print("大量参数组合并行测试（真实 pipeline IR 主路径）")
    print("=" * 72)
    results = run_batch(args.batch, args.workers)

    print(f"\n{'组':16s} {'任务状态':12s} {'验证':6s} {'失败项/原因'}")
    for r in results:
        status = r.get("status", "?")
        vok = "PASS" if r.get("verify_ok") else "FAIL"
        detail = "; ".join(r.get("fails", [])) or r.get("reason", "")
        print(f"{r['name']:16s} {status:12s} {vok:6s} {detail[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
