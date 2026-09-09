import json
from multiprocessing import Pool
from pathlib import Path

from seekflow_engineering_tools.generative_cad.validation_kernel import run_validation
from seekflow_engineering_tools.generative_cad.repair_kernel.engine import repair_documents
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
RUNS = ROOT / "_main_experiment" / "output" / "runs" / "full_agentic"
WORK = ROOT / "_main_experiment" / "output" / "replay_structural_fix"
TASKS = ["T25", "T26", "T27", "T28", "T29", "T30", "T31", "T32"]


def process(job):
    t, s = job
    src = RUNS / t / ("seed_%d" % s) / "latest" / "llm_raw.json"
    if not src.exists():
        return {"task": t, "seed": s, "status": "no_llm_raw"}
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
        vr0 = run_validation(doc)
        res = repair_documents(doc, vr0, dialect_registry=default_registry())
        if not res.run.report.ok:
            return {"task": t, "seed": s, "status": "validation_failed",
                    "codes": sorted({i.code for i in res.run.report.issues})}
        out = WORK / ("%s_seed_%d" % (t, s))
        out.mkdir(parents=True, exist_ok=True)
        step = out / "output.step"
        meta = out / "output.metadata.json"
        can = out / "canonical_ir.json"
        can.write_text(res.run.canonical.model_dump_json(indent=2), encoding="utf-8")
        seed_p = out / "validation_seed.json"
        seed_p.write_text(json.dumps(res.run.bundle.to_metadata_dict(), ensure_ascii=False), encoding="utf-8")
        rr = run_canonical_gcad(
            res.run.canonical, out_step=step, metadata_path=meta,
            validation_seed=res.run.bundle.to_metadata_dict(),
            canonical_ir_path=can, validation_seed_path=seed_p,
            require_full_validation_seed=False,
        )
        if not rr.ok:
            return {"task": t, "seed": s, "status": "runtime_failed", "error": rr.error[:200]}
        from _main_experiment.pipeline import run_mcp_quality_gate
        gate = run_mcp_quality_gate(out)
        if gate["summary"]["ok"]:
            return {"task": t, "seed": s, "status": "gate_ok"}
        return {"task": t, "seed": s, "status": "gate_failed",
                "failed": gate["summary"]["failed_checks"]}
    except Exception as exc:
        return {"task": t, "seed": s, "status": "exception", "error": str(exc)[:200]}


def main():
    jobs = [(t, s) for t in TASKS for s in range(10)]
    with Pool(processes=8) as pool:
        results = pool.map(process, jobs)
    stats = {}
    for r in results:
        stats[r["status"]] = stats.get(r["status"], 0) + 1
    print("status counts:", stats)
    processed = sum(1 for r in results if r["status"] != "no_llm_raw")
    valid = sum(1 for r in results if r["status"] not in ("no_llm_raw", "validation_failed", "exception"))
    final_ok = stats.get("gate_ok", 0)
    print("processed:", processed)
    print("validation_pass:", valid)
    print("validation_pass_rate:", (valid / processed) if processed else 0)
    print("final_gate_ok:", final_ok)
    print("final_gate_rate:", (final_ok / processed) if processed else 0)
    print("failures:")
    for r in sorted(results, key=lambda x: (x["task"], x["seed"])):
        if r["status"] not in ("gate_ok", "no_llm_raw"):
            print(" ", r)


if __name__ == "__main__":
    main()

