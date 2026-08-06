"""P0-1 早期任务字段回溯：补齐 canonical_ir / output.brep / request.json（独立后处理，不碰主流程/src）。

早期任务（mon_sweep_*、16 位 hex）在基础设施演化前生成，缺后加字段：
  - canonical_ir.json（Gf+CCAD）：raw_fixed.json → RawGcadDocument.model_validate → canonicalize()
  - output.brep（MBRep）：output.step → importStep → export（标记 brep_source=step_roundtrip，
    非原生，F13 已知限制；写 brep_source.json 供 run_enrich 识别）
  - request.json（T 全文）：mon_sweep_* 由 param_sweep_test.CASES 确定性重建；
    16 位 hex（uuid 截断）无法反推 → 写 missing 占位（不伪造全文）
  - pipeline_log.json / tool_calls.json（L 日志/轨迹）：运行时数据未记录 → 不可回溯，
    保持缺失不伪造
完成后重跑 run_enrich.run_one 刷新 dataset_enrich（含 b_rep_source/request_source 标记）。

用法:
  .conda/python.exe _param_experiment/backfill_fields.py
  .conda/python.exe _param_experiment/backfill_fields.py --only mon_sweep_g1_baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
SERVER = ROOT / "app" / "text-to-cad" / "server"
OUTPUT = SERVER / "output"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument  # noqa: E402
from seekflow_engineering_tools.generative_cad.validation.canonicalize import canonicalize  # noqa: E402

import run_enrich  # noqa: E402
import param_sweep_test  # noqa: E402


def _all_sweep_cases() -> list:
    """合并 param_sweep_test.CASES（G 系列）+ param_sweep_parallel.P_CASES/Q_CASES（P/Q 系列）。"""
    cases = list(getattr(param_sweep_test, "CASES", []) or [])
    try:
        import param_sweep_parallel
        cases += list(getattr(param_sweep_parallel, "P_CASES", []) or [])
        cases += list(getattr(param_sweep_parallel, "Q_CASES", []) or [])
    except Exception:  # noqa: BLE001
        pass
    return cases


def _reconstruct_sweep_text(tid: str) -> str | None:
    """mon_sweep_<name> → CASES/P_CASES/Q_CASES 里的确定性需求文本。"""
    if not tid.startswith("mon_sweep_"):
        return None
    name = tid[len("mon_sweep_"):]
    for case in _all_sweep_cases():
        if str(case.get("name", "")).lower() == name:
            text = case.get("text")
            return text if isinstance(text, str) and text.strip() else None
    return None


def _backfill_canonical(base: Path) -> str | None:
    """raw_fixed.json → canonical_ir.json。返回错误串或 None（成功/跳过）。"""
    canon_path = base / "canonical_ir.json"
    if canon_path.exists():
        return None
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        return "skip(no raw_fixed.json)"
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if raw.get("llm_validation_hints") is None:
            raw["llm_validation_hints"] = {}  # 早期 raw 缺省 None → 规范化（RawGcadDocument 要求 dict）
        doc = RawGcadDocument.model_validate(raw)
        canonical, report = canonicalize(doc)
        if canonical is None:
            errs = [i.code for i in report.issues if i.severity == "error"][:5]
            return f"canonicalize None (issues={errs})"
        canon_path.write_text(canonical.model_dump_json(indent=2), encoding="utf-8")
        return None
    except Exception as exc:  # noqa: BLE001
        return f"failed: {type(exc).__name__}: {exc}"


def _backfill_brep(base: Path) -> str | None:
    """output.step → output.brep（回读版），写 brep_source.json 标记。返回错误串或 None。"""
    brep_path = base / "output.brep"
    step = base / "output.step"
    if brep_path.exists():
        return None
    if not step.exists():
        return "skip(no output.step)"
    try:
        import cadquery as cq
        shape = cq.importers.importStep(str(step))
        cq.exporters.export(shape, str(brep_path))
        (base / "brep_source.json").write_text(
            json.dumps({"source": "step_roundtrip", "note": "backfill_fields from output.step"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        return None
    except Exception as exc:  # noqa: BLE001
        return f"failed: {type(exc).__name__}: {exc}"


def _backfill_request(base: Path, tid: str) -> str:
    """request.json（T 全文）。mon_sweep_* 从 CASES/P_CASES/Q_CASES 重建；其余写 missing 占位。"""
    req = base / "request.json"
    if req.exists():
        try:
            cur = json.loads(req.read_text(encoding="utf-8"))
            if cur.get("backfilled_from"):
                return "backfilled_cases"
            if cur.get("missing"):
                pass  # missing 占位 → 尝试重建覆盖（P/Q 系列初版未重建）
            else:
                return "existing"
        except Exception:  # noqa: BLE001
            return "existing"
        text = _reconstruct_sweep_text(tid)
        if text:
            req.write_text(json.dumps(
                {"text": text, "desc_style": None, "backfilled_from": "sweep_cases"},
                ensure_ascii=False, indent=2), encoding="utf-8")
            return "backfilled_cases"
        return "missing"
    text = _reconstruct_sweep_text(tid)
    if text:
        req.write_text(json.dumps(
            {"text": text, "desc_style": None, "backfilled_from": "sweep_cases"},
            ensure_ascii=False, indent=2), encoding="utf-8")
        return "backfilled_cases"
    req.write_text(json.dumps(
        {"text": None, "desc_style": None, "backfilled_from": None,
         "missing": "text not recoverable (uuid task)"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return "missing"


def run_one(tid: str) -> dict:
    base = OUTPUT / tid
    rep = {"task_id": tid, "canonical_ir": None, "brep": None, "request": None}
    if not (base / "raw_fixed.json").exists():
        rep["canonical_ir"] = "skip(no raw_fixed.json)"
        return rep
    rep["canonical_ir"] = _backfill_canonical(base)
    rep["brep"] = _backfill_brep(base)
    rep["request"] = _backfill_request(base, tid)
    # 重跑 run_enrich 刷新 dataset_enrich（含 b_rep_source/request_source）
    try:
        run_enrich.run_one(tid)
    except Exception as exc:  # noqa: BLE001
        rep["enrich"] = f"failed: {type(exc).__name__}: {exc}"
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="P0-1 早期任务字段回溯（canonical_ir/brep/T 全文）")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    args = ap.parse_args(argv)

    if args.only:
        tids = [args.only]
    else:
        tids = sorted(p.name for p in OUTPUT.iterdir()
                      if p.is_dir() and (p / "raw_fixed.json").exists())
    if not tids:
        print("没有任务目录")
        return 1

    canon_ok = brep_ok = req_ok = 0
    for tid in tids:
        r = run_one(tid)
        c = "OK" if r["canonical_ir"] is None else ("-" if r["canonical_ir"].startswith("skip") else "ERR")
        b = "OK" if r["brep"] is None else ("-" if r["brep"].startswith("skip") else "ERR")
        q = "OK" if r["request"] not in ("missing",) else ("MISS" if r["request"] == "missing" else r["request"])
        if c == "OK":
            canon_ok += 1
        if b == "OK":
            brep_ok += 1
        if r["request"] == "existing" or r["request"] == "backfilled_cases":
            req_ok += 1
        print(f"- {tid:28s} canonical={c}  brep={b}  request={r['request']}")
        for k, v in r.items():
            if k != "task_id" and isinstance(v, str) and v.startswith(("failed", "canonicalize None")):
                print(f"      {k}: {v}")
    print(f"DONE  canonical {canon_ok}/{len(tids)}  brep {brep_ok}/{len(tids)}  "
          f"request {req_ok}/{len(tids)}（含 backfill）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
