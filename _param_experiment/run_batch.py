"""批量构建管线：候选采样 + 批量执行（采集基础设施，不碰主流程/src）。

候选来源：candidate_sampler 三区采样（candidates.json，candidates_v3，含 zone）。
--run 批量执行（LLM）带断点续跑 / 失败隔离 / 可选并发；跑完联动 run_filter。
--no-run（默认）只调采样器生成候选清单。

用法:
  .conda/python.exe _param_experiment/run_batch.py                      # 采样候选
  .conda/python.exe _param_experiment/run_batch.py --run --limit 5      # 批量执行（LLM）
  .conda/python.exe _param_experiment/run_batch.py --run --family D15 --zone feasible --limit 3
  .conda/python.exe _param_experiment/run_batch.py --run --workers 3 --limit 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets"
CAND = DATASETS / "candidates.json"
STATE = DATASETS / "batch_state.json"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))


def _run_one(cand: dict, use_template: bool = False) -> str:
    """单候选执行：跑 pipeline + 写 family_ref.json。返回 status。
    use_template=True 时用 param_templates 确定性生成 llm_raw（非 LLM）。"""
    import main
    tid = cand["task_id"]
    main._tasks[tid] = {"taskId": tid, "status": "pending", "progress": 0, "result": None, "error": None}
    if use_template:
        # 确定性模板生成 llm_raw → 写任务目录（main 的 TEMPLATE_L2 分支读取）
        import param_templates
        tpl_params = {**cand.get("params", {}), "category": cand.get("category"),
                      "_tag": tid}
        doc = param_templates.build(tpl_params)
        out_dir = main.OUT_ROOT / tid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "llm_raw.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.environ["TEMPLATE_L2"] = "1"
    main._run_pipeline(tid, cand["text"], force_route="generative_cad_ir")
    # 写 family_ref.json（run_enrich 显式标注设计族）
    try:
        out_dir = main.OUT_ROOT / tid
        (out_dir / "family_ref.json").write_text(
            json.dumps({"family_id": cand.get("family"), "category": cand.get("category"),
                        "split": cand.get("split"), "zone": cand.get("zone")},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return main._tasks[tid].get("status", "?")


def _already_done(cand: dict) -> bool:
    """断点续跑：任务目录已存在 raw_fixed.json 视为已处理。"""
    return (OUTPUT / cand["task_id"] / "raw_fixed.json").exists()


def _load_candidates() -> list:
    """读采样器生成的 candidates.json（candidates_v3）；旧 v2（无 zone）兼容。"""
    if not CAND.exists():
        return []
    doc = json.loads(CAND.read_text(encoding="utf-8"))
    return doc.get("candidates", [])


def _save_state(state: dict) -> None:
    DATASETS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _exec_one(cand: dict, state: dict, use_template: bool = False) -> None:
    """执行单候选并更新 batch_state（失败隔离：异常记录不中断）。"""
    tid = cand["task_id"]
    try:
        status = _run_one(cand, use_template=use_template)
        if status == "completed":
            state["succeeded"] += 1
        else:
            state["failed"] += 1
            state["failures"].append({"task_id": tid, "error": f"status={status}"})
    except Exception as exc:  # noqa: BLE001
        state["failed"] += 1
        state["failures"].append({"task_id": tid, "error": str(exc)[:200]})
    state["processed"] += 1
    _save_state(state)


def _exec_worker(cand: dict, use_template: bool = False) -> dict:
    """mp.Pool worker（顶层可 picklable）：执行单个候选，返回结果。"""
    try:
        status = _run_one(cand, use_template=use_template)
        return {"task_id": cand["task_id"], "status": status, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"task_id": cand["task_id"], "status": "error", "error": str(exc)[:200]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="批量构建管线：采样 + 批量执行")
    ap.add_argument("--run", action="store_true", help="批量执行（LLM）；默认只采样候选")
    ap.add_argument("--per-family", type=int, default=12, help="采样时每族候选数")
    ap.add_argument("--family", default=None, help="只处理指定设计族（D01-D32）")
    ap.add_argument("--zone", default=None, choices=["feasible", "boundary", "infeasible"],
                    help="只处理指定采样区")
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 个候选")
    ap.add_argument("--workers", type=int, default=1, help="并发进程数（>1 用 mp.Pool）")
    ap.add_argument("--no-run", action="store_true", help="只采样不执行（默认）")
    ap.add_argument("--template", action="store_true",
                    help="用确定性参数化模板生成 llm_raw（非 LLM），走完整 pipeline 采集")
    args = ap.parse_args(argv)

    # 1. 采样候选（candidate_sampler）
    if args.no_run or not args.run:
        import candidate_sampler
        cand_argv = ["--per-family", str(args.per_family)] \
            + (["--family", args.family] if args.family else [])
        candidate_sampler.main(cand_argv)
    if not args.run:
        print("[--no-run] 未触发 LLM 生成（采集基础设施验证）")
        return 0

    cands = _load_candidates()
    if args.family:
        cands = [c for c in cands if c.get("family") == args.family]
    if args.zone:
        cands = [c for c in cands if c.get("zone") == args.zone]
    if not cands:
        print("候选清单为空（先运行采样：run_batch.py 不带 --run）")
        return 1

    # 2. 断点续跑：跳过已处理
    pending = [c for c in cands if not _already_done(c)]
    skipped = len(cands) - len(pending)
    if args.limit:
        pending = pending[: args.limit]
    print(f"候选 {len(cands)}，已处理跳过 {skipped}，待执行 {len(pending)}")

    state = {"schema": "batch_state_v1", "started_at": datetime.now().isoformat(timespec="seconds"),
             "total": len(pending), "processed": 0, "succeeded": 0, "failed": 0,
             "skipped": skipped, "failures": []}
    _save_state(state)

    # 3. 批量执行（失败隔离 + 可选并发）
    if args.workers > 1 and len(pending) > 1:
        import multiprocessing as mp
        from functools import partial
        with mp.Pool(processes=args.workers) as pool:
            results = pool.map(partial(_exec_worker, use_template=args.template), pending)
        for r in results:
            state["processed"] += 1
            if r["status"] == "completed":
                state["succeeded"] += 1
            else:
                state["failed"] += 1
                state["failures"].append({"task_id": r["task_id"], "error": r["error"]})
            _save_state(state)
    else:
        for c in pending:
            _exec_one(c, state, use_template=args.template)

    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _save_state(state)
    print(f"\n批量执行完成: 成功 {state['succeeded']} / 失败 {state['failed']} / 跳过 {skipped}")
    for f in state["failures"][:10]:
        print(f"  FAIL {f['task_id']}: {f['error']}")

    # 4. 联动级联过滤
    print("\n级联过滤（run_filter）:")
    import run_filter
    run_filter.main([])
    print("可跑 run_enrich → run_index → run_split 完成入库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
