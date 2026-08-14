"""临时：多批完整 pipeline 测试（agent 系统），统计成功率 + 失败原因分类。

每次跑完整 main._run_pipeline（agent 生成 → validation → runtime → MCP 门），
统计 completed 率，并诊断失败任务的原因（L2 生成/validation/runtime/MCP 门）。

用法: .conda/python.exe _param_experiment/_test_pipeline_batch.py [--n 5]
"""
import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
# DEEPSEEK_API_KEY must be set in the environment.
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES, build_text


def classify_failure(tid: str) -> dict:
    """诊断失败任务的失败阶段与原因。"""
    p = ROOT / "app" / "text-to-cad" / "server" / "output" / tid
    info = {"error": None, "stage": "unknown", "detail": None}
    pl = p / "pipeline_log.json"
    if pl.exists():
        try:
            d = json.loads(pl.read_text(encoding="utf-8"))
            info["error"] = d.get("error") or ""
        except Exception:
            pass
    err = info["error"] or ""
    if "L2 authoring" in err:
        info["stage"] = "l2_authoring"
    elif "Validation" in err:
        info["stage"] = "validation"
        vr = p / "validation_report.json"
        if vr.exists():
            try:
                v = json.loads(vr.read_text(encoding="utf-8"))
                codes = sorted({i.get("code") for i in v.get("issues", [])
                                if i.get("severity") in ("error", "fatal")})
                info["detail"] = codes[:6]
            except Exception:
                pass
    elif "MCP quality gate" in err:
        info["stage"] = "mcp_gate"
        import re
        m = re.search(r"\[(.*?)\]", err)
        info["detail"] = m.group(1).split(",") if m else []
    else:
        info["stage"] = "other"
    return info


# 多参数组合：覆盖 2/3/4 齿、不同槽数/槽深、基础盘
DEFAULT_FAMILIES = ["D15", "D16", "D19", "D22", "D01"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", default=",".join(DEFAULT_FAMILIES),
                    help="逗号分隔设计族 id（多参数组合）")
    args = ap.parse_args(argv)
    families = [f.strip() for f in args.families.split(",") if f.strip()]

    import main
    OUT = ROOT / "app" / "text-to-cad" / "server" / "output"
    stats = {"total": len(families), "success": 0, "failed": 0}
    fail_by_stage: dict = {}
    details = []
    for fam in families:
        tid = f"batch_pipe_{fam}"
        text = build_text(DESIGN_FAMILIES[fam])
        main._tasks[tid] = {"taskId": tid, "status": "pending", "progress": 0,
                            "result": None, "error": None}
        try:
            main._run_pipeline(tid, text, force_route="generative_cad_ir")
        except Exception as exc:
            print(f"[{tid}] EXC {type(exc).__name__}: {str(exc)[:120]}")
            details.append({"tid": tid, "family": fam, "status": "exc",
                            "stage": "exception", "detail": str(exc)[:120]})
            stats["failed"] += 1
            fail_by_stage["exception"] = fail_by_stage.get("exception", 0) + 1
            import shutil
            shutil.rmtree(OUT / tid, ignore_errors=True)
            continue
        status = main._tasks[tid].get("status", "?")
        if status == "completed":
            stats["success"] += 1
            print(f"[{tid}] SUCCESS")
            details.append({"tid": tid, "family": fam, "status": status})
        else:
            stats["failed"] += 1
            f = classify_failure(tid)
            fail_by_stage[f["stage"]] = fail_by_stage.get(f["stage"], 0) + 1
            print(f"[{tid}] FAIL stage={f['stage']} detail={f['detail']} err={(f['error'] or '')[:110]}")
            details.append({"tid": tid, "family": fam, "status": status, **f})
        import shutil
        shutil.rmtree(OUT / tid, ignore_errors=True)

    n = max(1, stats["total"])
    print(f"\n=== 多参数组合 pipeline 统计（{n} 族）===")
    print(f"  成功: {stats['success']}/{n} = {stats['success']/n*100:.0f}%")
    print(f"  失败: {stats['failed']}/{n}")
    if fail_by_stage:
        print("  失败阶段分布:", json.dumps(fail_by_stage, ensure_ascii=False))
    print("  逐族:", json.dumps([{"fam": d.get("family"), "status": d.get("status"),
                                 "stage": d.get("stage", ""), "detail": d.get("detail")}
                                for d in details], ensure_ascii=False))
    (ROOT / "_param_experiment" / "output" / "pipeline_batch_report.json").write_text(
        json.dumps({"stats": stats, "fail_by_stage": fail_by_stage, "details": details},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
