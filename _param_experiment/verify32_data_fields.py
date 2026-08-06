"""32 族数据字段验证：对 verify32_* 成功任务跑 run_enrich + run_regen，检查数据集字段。

验证目标：每个设计族可行候选在完整流程（run_batch → enrich → regen）后
获得论文 S 元组字段：T/Dg/MSTEP/MBRep/Rquality/Gf+CCAD/enrich/regen_report。

用法（需先跑完 verify_32_families.py）:
  .conda/python.exe _param_experiment/verify32_data_fields.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import run_enrich  # noqa: E402
import run_regen  # noqa: E402

# 榫槽类 regen 参数：slot_count（再生测试）；盘型类：disc_hub_web_fillet
_SLOT_CATS = ("slot", "coupled", "complex_rim")


def _category(tid: str) -> str:
    try:
        fr = json.loads((OUTPUT / tid / "family_ref.json").read_text(encoding="utf-8"))
        return fr.get("category", "")
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    dirs = sorted(p.name for p in OUTPUT.iterdir()
                  if p.is_dir() and p.name.startswith("verify32_")
                  and (p / "validation_report.json").exists())
    if not dirs:
        print("无 verify32_* 任务（先跑 verify_32_families.py）")
        return 1
    results = []
    for tid in dirs:
        # 1) run_enrich
        try:
            r = run_enrich.run_one(tid)
            enrich_ok = not r.get("error") and (OUTPUT / tid / "dataset_enrich.json").exists()
        except Exception as exc:  # noqa: BLE001
            enrich_ok = f"err:{str(exc)[:60]}"
        # 2) run_regen（按类别选参数）。论文 Rregen = 再生测试记录：
        #    regen_report.json 存在且含 before/after 即为字段产出（无论再生结果 ok/退化）。
        cat = _category(tid)
        param_key = "slot_count" if cat in _SLOT_CATS else "disc_hub_web_fillet"
        try:
            rr = run_regen.run_one(tid, [(param_key, None)], copy=False)
            rp = OUTPUT / tid / "regen_report.json"
            regen_ok = bool(rr.get("before", {}).get("ok")) and rp.exists()
        except Exception as exc:  # noqa: BLE001
            regen_ok = f"err:{str(exc)[:60]}"
        vf = OUTPUT / tid / "validation_report.json"
        vok = json.loads(vf.read_text(encoding="utf-8")).get("ok")
        fields = {
            "T": (OUTPUT / tid / "request.json").exists(),
            "Dg": (OUTPUT / tid / "raw_fixed.json").exists(),
            "MSTEP": (OUTPUT / tid / "output.step").exists(),
            "MBRep": (OUTPUT / tid / "output.brep").exists(),
            "Rquality": (OUTPUT / tid / "validation_report.json").exists(),
            "GfCCAD": (OUTPUT / tid / "canonical_ir.json").exists(),
            "enrich": enrich_ok,
            "regen": regen_ok,
        }
        results.append((tid, cat, vok, fields))
        print(f"[{tid}] {cat} val={vok} enrich={enrich_ok} regen={regen_ok}")

    ok = [r for r in results if r[2] is True
          and all(r[3].get(k) in (True,) for k in ("T", "Dg", "MSTEP", "MBRep", "Rquality", "enrich"))]
    print(f"\n通过（含 enrich） {len(ok)}/{len(results)}")
    for r in results:
        bad = [k for k, v in r[3].items() if v is not True]
        if bad:
            print(f"  缺字段 {r[0]} {r[1]}: {bad}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
