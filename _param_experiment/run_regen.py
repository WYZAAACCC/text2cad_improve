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
    PARAM_REGISTRY, _current_value, _resolve_param_nodes, check_solid_validity,
    count_fir_tree_slots, measure_disc_dimensions, measure_fir_tree_slot_profile,
    regenerate_model, validate_slot_step_roundtrip,
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


_DIM_KEYS = ("outer_diameter_mm", "bore_diameter_mm", "axial_thickness_mm")


def _dims_within_tol(before: dict, after: dict, tol: float = 0.05) -> bool:
    """主体关键尺寸稳定性（论文 5.5：回读关键尺寸误差 <0.05mm）。

    PARAM_REGISTRY 的可再生参数（槽数/分布半径/轴向深度/圆角）不修改主体尺寸，
    故 before/after 主体尺寸应保持 <tol。
    """
    detail = {}
    for k in _DIM_KEYS:
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            diff = abs(a - b)
            detail[k] = round(diff, 4)
            if diff > tol:
                return False
    return bool(detail)


def _fv(b, a):
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return round(a - b, 4)
    return None


def run_one(task_id: str, params, copy: bool = False) -> dict:
    """params: list[(param_key, new_value or None)]；None → cur×0.6 安全减少。"""
    base = OUTPUT / task_id
    report = {"task_id": task_id, "schema": "regen_report_v1", "param_updates": [],
              "param_changes": [], "before": {}, "after": {}, "delta": {},
              "regenerated_ok": False, "new_base_dir": None, "checks": None,
              "error": None, "timestamp": datetime.now().isoformat(timespec="seconds")}
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        report["error"] = "任务目录无 raw_fixed.json"
        return report

    try:
        ir = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"raw_fixed.json 读取失败: {exc}"
        return report

    # 逐参数校验可用性（_resolve_param_nodes 语义定位），不可用跳过，可用的继续
    updates = []
    skipped = []
    for pk, nv in params:
        reg = next((r for r in PARAM_REGISTRY if r["param"] == pk), None)
        if reg is None:
            skipped.append(f"{pk}(未知key)")
            continue
        if not _resolve_param_nodes(ir, pk):
            skipped.append(f"{pk}(文档不可用)")
            continue
        new = _safe_new_value(reg, _current_value(ir, reg), nv)
        if new is None:
            skipped.append(f"{pk}(无当前值)")
            continue
        updates.append({"param_key": pk, "new_value": new})
    if not updates:
        report["error"] = f"无可用参数更新（跳过: {', '.join(skipped) or '全部不可用'}）"
        (base / "regen_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    report["param_updates"] = updates
    report["skipped_params"] = skipped or None
    report["before"] = _measure(str(base))

    res = regenerate_model({"base_dir": str(base), "param_updates": updates})
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
    # P1-2 补 STEP 回读一致性 / 主体尺寸稳定性 / 有效实体校验（论文 5.5）
    try:
        report["roundtrip"] = validate_slot_step_roundtrip({"base_dir": res["new_base_dir"]})
    except Exception as exc:  # noqa: BLE001
        report["roundtrip"] = {"error": str(exc)}
    report["dims_stable_05mm"] = _dims_within_tol(report["before"], report["after"])
    try:
        sv = check_solid_validity({"base_dir": res["new_base_dir"]})
        report["solid_valid"] = bool(sv.get("ok"))
    except Exception:  # noqa: BLE001
        report["solid_valid"] = None
    report["slot_feature_delta"] = {k: _fv(report["before"].get(k), report["after"].get(k))
                                    for k in ("count", "teeth_count")}

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
                    help=f"参数 key（可选：{[r['param'] for r in PARAM_REGISTRY]}；与 --params 互斥）")
    ap.add_argument("--new-value", type=float, default=None, help="指定新值（默认 cur×0.6 安全减少）")
    ap.add_argument("--params", default=None,
                    help='多参数 "slot_count:48,root_fillet:1.5"（逗号 k:v，缺 v 则 cur×0.6）')
    ap.add_argument("--copy", action="store_true", help="把新模型复制进任务目录 regen/<tag>/")
    args = ap.parse_args(argv)

    if args.params:
        params = []
        for item in args.params.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                k, v = item.split(":", 1)
                params.append((k.strip(), float(v)))
            else:
                params.append((item, None))
    else:
        params = [(args.param, args.new_value)]

    if args.only:
        tasks = [args.only]
    else:
        tasks = sorted(p.name for p in OUTPUT.iterdir()
                       if p.is_dir() and (p / "raw_fixed.json").exists())
    if not tasks:
        print("没有任务目录")
        return 1

    print(f"Rregen 参数再生（{params}，{len(tasks)} 个任务）")
    for tid in tasks:
        print(f"- {tid} ...", end=" ", flush=True)
        r = run_one(tid, params, copy=args.copy)
        if r["regenerated_ok"]:
            chs = [f"{c.get('param')}:{c.get('old')}→{c.get('new')}" for c in r["param_changes"]]
            print(f"OK  {', '.join(chs)}  after_count={r['after'].get('count')}")
        else:
            print(f"FAIL  {r['error']}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
