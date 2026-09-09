import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
RUNS = ROOT / "_main_experiment" / "output" / "runs" / "full_agentic"
REPLAY = ROOT / "_main_experiment" / "output" / ("replay_t14_with_llm" if (sys.argv[1:] and sys.argv[1] == "t14") else ("replay_t15_t24_with_llm" if (sys.argv[1:] and sys.argv[1] == "t15_t24") else "replay_with_llm"))
TASKS = ["T14"] if (sys.argv[1:] and sys.argv[1] == "t14") else (["T%02d" % i for i in range(15, 25)] if (sys.argv[1:] and sys.argv[1] == "t15_t24") else ["T25", "T26", "T27", "T28", "T29", "T30", "T31", "T32"])

_TASK_MAP = {}


def _init(task_dicts):
    global _TASK_MAP
    _TASK_MAP = {d["task_id"]: d for d in task_dicts}


def process(job):
    t, s = job
    src = RUNS / t / ("seed_%d" % s) / "latest" / "llm_raw.json"
    if not src.exists():
        return {"task": t, "seed": s, "status": "no_llm_raw"}
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
        spec = _TASK_MAP[t]
        from _main_experiment.config import default_experiment_config
        from _main_experiment.schemas import MethodSpec, TaskSpec
        from _main_experiment.llm import OpenAICompatToolClient
        from _main_experiment.pipeline import BenchLlmCaller, _run_with_repair, run_mcp_quality_gate

        config = default_experiment_config()
        task_spec = TaskSpec.model_validate(spec)
        method = MethodSpec(
            method_id="full_agentic_replay",
            display_name="full_agentic_replay",
            llm=config.llm,
            flags={"agentic": True, "force_generative": True},
        )
        llm_cfg = config.llm.model_copy(update={"seed": s})
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        caller = BenchLlmCaller(OpenAICompatToolClient(), llm_cfg, usage)
        out = REPLAY / t / ("seed_%d" % s)
        out.mkdir(parents=True, exist_ok=True)
        loop = _run_with_repair(
            raw, task_spec=task_spec, method_spec=method,
            run_path=out, caller=caller, llm_config=llm_cfg,
        )
        (out / "raw_fixed.json").write_text(
            json.dumps(loop.document, ensure_ascii=False), encoding="utf-8")
        if getattr(loop.vrun, "canonical", None) is not None:
            (out / "canonical_ir.json").write_text(
                loop.vrun.canonical.model_dump_json(indent=2), encoding="utf-8")
        gate = run_mcp_quality_gate(out)
        ok = bool(loop.outcome.ok
                  and loop.run_result is not None and loop.run_result.ok
                  and gate["summary"]["ok"])
        return {
            "task": t, "seed": s, "ok": ok,
            "stop": loop.outcome.stop_code,
            "reason": loop.outcome.stop_reason,
            "gate_failed": gate["summary"]["failed_checks"],
            "usage": usage,
        }
    except Exception as exc:
        return {"task": t, "seed": s, "status": "exception", "error": str(exc)[:200]}


def main():
    sys.path.insert(0, str(ROOT))
    from _main_experiment.config import default_experiment_config
    from _main_experiment.aggregate import load_tasks
    tasks = load_tasks(default_experiment_config())
    task_dicts = [t.model_dump(mode="json") for t in tasks if t.task_id in TASKS]
    jobs = [(t, s) for t in TASKS for s in range(10)]
    with Pool(processes=10, initializer=_init, initargs=(task_dicts,)) as pool:
        results = pool.map(process, jobs)
    processed = [r for r in results if r.get("status") != "no_llm_raw"]
    ok = [r for r in processed if r.get("ok")]
    print("processed:", len(processed))
    print("ok:", len(ok))
    print("pass_rate:", (len(ok) / len(processed)) if processed else 0)
    stops = {}
    for r in processed:
        key = r.get("stop") or r.get("status")
        stops[key] = stops.get(key, 0) + 1
    print("stop distribution:", stops)
    print("failures:")
    for r in sorted(processed, key=lambda x: (x["task"], x["seed"])):
        if not r.get("ok"):
            print(" ", r)


if __name__ == "__main__":
    main()

