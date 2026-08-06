"""32 族完整流程验证：每族 feasible + boundary 候选走 run_batch 全链（模板确定性执行）。

验证目标：
  1. 每个设计族种子至少一个可行候选能走通完整 pipeline（validation → repair → runtime → MCP gate）
  2. 产物字段覆盖（T/Dg/MSTEP/MBRep/Rquality/Gf+CCAD）
  3. 不同参数组合（族内特征变体）不破坏流程

写 verify32_* 任务目录（.gitignore 已排除）。不碰主流程/src。
用法:
  .conda/python.exe _param_experiment/verify_32_families.py [--per-family N] [--family D15]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import run_batch  # noqa: E402
from design_families import DESIGN_FAMILIES  # noqa: E402


def _fields(out_dir: Path) -> dict:
    return {
        "T": (out_dir / "request.json").exists(),
        "Dg": (out_dir / "raw_fixed.json").exists(),
        "MSTEP": (out_dir / "output.step").exists(),
        "MBRep": (out_dir / "output.brep").exists(),
        "Rquality": (out_dir / "validation_report.json").exists(),
        "GfCCAD": (out_dir / "canonical_ir.json").exists(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default=None, help="只验证指定设计族")
    ap.add_argument("--limit-per-family", type=int, default=2, help="每族最多验证候选数")
    args = ap.parse_args(argv)

    cands = json.loads(
        (_HERE / "output" / "datasets" / "candidates.json").read_text(encoding="utf-8")
    )["candidates"]
    by_fam: dict[str, list] = {}
    for c in cands:
        by_fam.setdefault(c["family"], []).append(c)

    results = []
    for fid in sorted(DESIGN_FAMILIES):
        if args.family and fid != args.family:
            continue
        fam_cands = by_fam.get(fid, [])
        # 优先 feasible，其次 boundary；按 zone 优先级取前 N 个
        ranked = sorted(fam_cands,
                        key=lambda c: (c["zone"] != "feasible", c["zone"] != "boundary"))
        picked = [c for c in ranked if c["zone"] in ("feasible", "boundary")][:args.limit_per_family]
        if not picked:
            results.append((fid, "no_feasible", None, None))
            continue
        for seq_i, c in enumerate(picked):
            tid = f"verify32_{fid}_{seq_i}_{c['zone']}"
            c2 = dict(c)
            c2["task_id"] = tid
            try:
                status = run_batch._run_one(c2, use_template=True)
            except Exception as exc:  # noqa: BLE001
                status = f"exception:{str(exc)[:80]}"
            out = run_batch.OUTPUT / tid
            vf = out / "validation_report.json"
            vok = None
            if vf.exists():
                vok = json.loads(vf.read_text(encoding="utf-8")).get("ok")
            fields = _fields(out)
            results.append((fid, status, vok, fields))
            print(f"[{fid} {c['zone']}] status={status} val={vok} fields={fields}")

    ok = [r for r in results if r[1] == "completed" and r[2] is True
          and r[3] and all(r[3].get(k) for k in ("T", "Dg", "MSTEP", "MBRep", "Rquality"))]
    print(f"\n通过 {len(ok)}/{len(results)}")
    for r in results:
        if not (r[1] == "completed" and r[2] is True):
            print("  未通过:", r)
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
