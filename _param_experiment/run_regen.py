"""数据集字段 Rregen：参数修改与模型再生测试（独立后处理脚本，不碰主流程）。

论文 S 元组 Rregen = "参数修改和模型再生测试结果"。复用 _param_experiment/mcp_tools
的已验证链路（PARAM_REGISTRY 语义定位 + regenerate_model 整文档重建 + 测量函数），
本脚本只做编排与报告构建，输出 output/<task_id>/regen_report.json。

用法:
  .conda/python.exe _param_experiment/run_regen.py --only mon_sweep_q2_slots_96
  .conda/python.exe _param_experiment/run_regen.py                  # 批量扫描全部任务目录
  .conda/python.exe _param_experiment/run_regen.py --param slot_count --new-value 48
  .conda/python.exe _param_experiment/run_regen.py --only mon_sweep_q2_slots_96 --copy
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
SERVER = ROOT / "app" / "text-to-cad" / "server"
OUTPUT = SERVER / "output"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from mcp_tools import (  # noqa: E402
    PARAM_REGISTRY, _current_value, count_fir_tree_slots,
    measure_disc_dimensions, measure_fir_tree_slot_profile, regenerate_model,
)


def _safe_new_value(reg: dict, cur, new_value=None):
    """新值：--new-value 指定；否则当前值 ×0.6（安全减少），clamp 到范围。"""
    lo, hi = reg["range"]
    if new_value is not None:
        return float(new_value) if reg["type"] == "float" else int(new_value)
    if cur is None:
        return None
    v = float(cur) * 0.6
    v = max(float(lo), min(float(hi), v))
    return int(round(v)) if reg["type"] == "int" else round(v, 3)


def _measure(base: str) -> dict:
    """对 base_dir 目录测量（IR 确定性 + 槽数 + 轮廓尺寸）。"""
    out = {}
    try:
        out.update(measure_disc_dimensions({"base_dir": base}))
    except Exception as exc:  # noqa: BLE001
        out["disc_error"] = str(exc)
    for fn in (count_fir_tree_slots, measure_fir_tree_slot_profile):
        try:
            out.update(fn({"base_dir": base}))
        except Exception:  # noqa: BLE001
            pass
    return out


def _delta(before: dict, after: dict) -> dict:
    d = {}
    for k in ("outer_diameter_mm", "outer_radius_mm", "bore_diameter_mm",
              "axial_thickness_mm", "count", "distribution_radius_mm",
              "circumferential_pitch_mm", "slot_depth_mm", "throat_half_width_mm"):
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            d[k] = round(a - b, 4)
    return d


def run_one(task_id: str, param_key: str, new_value=None, copy: bool = False) -> dict:
    base = OUTPUT / task_id
    report = {"task_id": task_id, "schema": "regen_report_v1",
              "param": param_key, "param_changes": [],
              "before": {}, "after": {}, "delta": {},
              "regenerated_ok": False, "new_base_dir": None, "checks": None,
              "error": None, "timestamp": datetime.now().isoformat(timespec="seconds")}
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        report["error"] = "任务目录无 raw_fixed.json"
        return report

    reg = next((r for r in PARAM_REGISTRY if r["param"] == param_key), None)
    if reg is None:
        report["error"] = f"未知参数 key {param_key!r}"
        return report
    try:
        ir = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"raw_fixed.json 读取失败: {exc}"
        return report

    cur = _current_value(ir, reg)
    new = _safe_new_value(reg, cur, new_value)
    if new is None:
        report["error"] = f"参数 {param_key} 当前文档不可用"
        return report
    report["before"] = _measure(str(base))

    res = regenerate_model({"base_dir": str(base),
                            "param_updates": [{"param_key": param_key, "new_value": new}]})
    if not res.get("ok"):
        report["error"] = res.get("reason") or "再生失败"
        report["param_changes"] = res.get("param_changes", [])
        (base / "regen_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    report["regenerated_ok"] = True
    report["param_changes"] = res.get("param_changes", [])
    report["new_base_dir"] = res.get("new_base_dir")
    report["checks"] = res.get("checks")
    report["after"] = _measure(res["new_base_dir"])
    report["delta"] = _delta(report["before"], report["after"])

    if copy and res.get("new_base_dir"):
        tag = Path(res["new_base_dir"]).name
        dst = base / "regen" / tag
        if not dst.exists():
            shutil.copytree(res["new_base_dir"], dst)
        report["new_base_dir_copied"] = str(dst)

    (base / "regen_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rregen 参数再生测试（数据集字段）")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    ap.add_argument("--param", default="slot_count",
                    help=f"参数 key（可选：{[r['param'] for r in PARAM_REGISTRY]}）")
    ap.add_argument("--new-value", type=float, default=None, help="指定新值（默认 cur×0.6 安全减少）")
    ap.add_argument("--copy", action="store_true", help="把新模型复制进任务目录 regen/<tag>/")
    args = ap.parse_args(argv)

    if args.only:
        tasks = [args.only]
    else:
        tasks = sorted(p.name for p in OUTPUT.iterdir()
                       if p.is_dir() and (p / "raw_fixed.json").exists())
    if not tasks:
        print("没有任务目录")
        return 1

    print(f"Rregen 参数再生（param={args.param}，{len(tasks)} 个任务）")
    for tid in tasks:
        print(f"- {tid} ...", end=" ", flush=True)
        r = run_one(tid, args.param, args.new_value, copy=args.copy)
        if r["regenerated_ok"]:
            ch = r["param_changes"][0] if r["param_changes"] else {}
            print(f"OK  {ch.get('param')}: {ch.get('old')}→{ch.get('new')}  "
                  f"槽数 {r['after'].get('count')}  "
                  f"delta={ {k: v for k, v in r['delta'].items() if k == 'count'} }")
        else:
            print(f"FAIL  {r['error']}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
