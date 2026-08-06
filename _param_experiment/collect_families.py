"""全族多参数组合采集：每族多参数组合 → 完整流程（模板确定性）→ 保存。

目录结构（用户核实 step 用）：
  _param_experiment/output/collection/<family>/<combo_id>/
    output.step / output.brep / raw_fixed.json / canonical_ir.json /
    validation_report.json / request.json / pipeline_log.json / family_ref.json / params.json

- 特征族（hole/groove/slot/coupled/complex_rim）：取采样器全部 feasible 候选
- basic 族（D01-D04）：采样器只有 1 候选，用 _BASIC_VARIANTS（8 个主体组合，论文范围）
- 断点续跑：collection/<family>/<combo>/output.step 已存在则跳过

用法:
  .conda/python.exe _param_experiment/collect_families.py [--family D15]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import run_batch  # noqa: E402
from design_families import DESIGN_FAMILIES  # noqa: E402

COLLECTION = _HERE / "output" / "collection"

# basic 族多主体变体（论文范围：od 360-760, bore 50-200, thick 30-130）
_BASIC_VARIANTS = [
    {"od_mm": 460, "bore_mm": 110, "thick_mm": 70, "hub_mm": 36, "rim_mm": 28},
    {"od_mm": 500, "bore_mm": 120, "thick_mm": 76, "hub_mm": 38, "rim_mm": 30},
    {"od_mm": 520, "bore_mm": 100, "thick_mm": 80, "hub_mm": 38, "rim_mm": 30},
    {"od_mm": 560, "bore_mm": 130, "thick_mm": 85, "hub_mm": 40, "rim_mm": 32},
    {"od_mm": 580, "bore_mm": 140, "thick_mm": 95, "hub_mm": 42, "rim_mm": 34},
    {"od_mm": 620, "bore_mm": 150, "thick_mm": 90, "hub_mm": 45, "rim_mm": 38},
    {"od_mm": 680, "bore_mm": 170, "thick_mm": 105, "hub_mm": 50, "rim_mm": 42},
    {"od_mm": 740, "bore_mm": 190, "thick_mm": 115, "hub_mm": 55, "rim_mm": 46},
]

# 复制到 collection 的关键产物
_ARTIFACTS = ("output.step", "output.brep", "raw_fixed.json", "canonical_ir.json",
              "validation_report.json", "request.json", "pipeline_log.json", "family_ref.json")


def _combo_id(fid: str, seq: int, tag: str) -> str:
    return f"c{fid}_n{seq:02d}_{tag}"


def _collect(out_dir: Path, dst_dir: Path, params: dict) -> dict:
    """复制产物到 collection/<family>/<combo>/，写 params.json。"""
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in _ARTIFACTS:
        src = out_dir / name
        if src.exists():
            shutil.copy2(src, dst_dir / name)
            copied.append(name)
    (dst_dir / "params.json").write_text(
        json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"copied": copied, "has_step": (dst_dir / "output.step").exists()}


def _basic_cands(fid: str) -> list:
    return [{"task_id": _combo_id(fid, i, "basic"), "family": fid, "category": "basic",
             "zone": "feasible", "params": {**v, "rim_radial_mm": round(0.12 * v["od_mm"], 1)},
             "text": ""} for i, v in enumerate(_BASIC_VARIANTS)]


def _run(cand: dict, fid: str) -> dict:
    tid = cand["task_id"]
    dst = COLLECTION / fid / tid
    if (dst / "output.step").exists():
        return {"tid": tid, "skipped": True}
    out_dir = run_batch.OUTPUT / tid
    try:
        status = run_batch._run_one(cand, use_template=True)
    except Exception as exc:  # noqa: BLE001
        status = f"exception:{str(exc)[:80]}"
    info = {"tid": tid, "status": status}
    if status == "completed":
        info.update(_collect(out_dir, dst, cand["params"]))
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default=None, help="只采集指定设计族")
    args = ap.parse_args(argv)

    cands = json.loads(
        (_HERE / "output" / "datasets" / "candidates.json").read_text(encoding="utf-8")
    )["candidates"]
    by_fam: dict[str, list] = {}
    for c in cands:
        by_fam.setdefault(c["family"], []).append(c)

    stats = []
    for fid in sorted(DESIGN_FAMILIES):
        if args.family and fid != args.family:
            continue
        cat = DESIGN_FAMILIES[fid]["category"]
        if cat == "basic":
            picks = _basic_cands(fid)
        else:
            # feasible + boundary 全收（boundary 是贴近约束边界的真实数据，论文需要；
            # 此前只收 feasible 导致 D14 环形腔组合（boundary）被丢弃）
            fe = [c for c in by_fam.get(fid, []) if c["zone"] in ("feasible", "boundary")]
            # task_id 保持候选语义，collection 内序号用
            picks = []
            for i, c in enumerate(fe):
                c2 = dict(c)
                c2["task_id"] = _combo_id(fid, i, c["zone"])
                picks.append(c2)
        ok, skip, fail = 0, 0, 0
        for c in picks:
            r = _run(c, fid)
            if r.get("skipped"):
                skip += 1
            elif r.get("status") == "completed":
                ok += 1
            else:
                fail += 1
                print(f"  [{fid}] {r['tid']} FAIL {r['status']}")
        stats.append((fid, cat, len(picks), ok, skip, fail))
        print(f"[{fid}] {cat} 组合{len(picks)} 成功{ok} 跳过{skip} 失败{fail}")

    print("\n采集汇总 ->", COLLECTION)
    total_ok = sum(s[3] for s in stats)
    print(f"成功产出 {total_ok} 个组合的完整数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
