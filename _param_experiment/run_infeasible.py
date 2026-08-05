"""数据集不可行样本证据 gatherer（独立后处理，不碰主流程）。

论文"不可行设计拒绝"需 conflict_constraints / geometry_evidence。本脚本聚合：
  ① _param_experiment/output/sweep_*.log 的 failed 任务 + 错误行
  ② 任务目录 pipeline_log.json（ok:false）的 error + MCP gate failed_checks
产出 _param_experiment/output/infeasible_samples.json
  {"schema": "infeasible_samples_v1", "samples": [{task_id, error_code, evidence, failed_checks}]}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
LOG_DIR = _HERE / "output"
OUT = LOG_DIR / "infeasible_samples.json"

_ERROR_PAT = re.compile(
    r"(L2 authoring failed[^\n]*|MCP quality gate failed[^\n]*|Validation: \d+ errors[^\n]*"
    r"|L1 routing failed[^\n]*|Primitive build failed[^\n]*|Request timed out)")
_TASK_PAT = re.compile(r"task=([A-Za-z0-9_]+)")


def _scan_logs() -> dict:
    samples: dict = {}
    for log in sorted(LOG_DIR.glob("sweep_*.log")):
        cur = None
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _TASK_PAT.search(line)
            if m:
                cur = m.group(1)
            if not cur:
                continue
            rec = samples.setdefault(cur, {"task_id": cur, "error_code": "run_failed",
                                           "evidence": "", "failed_checks": None})
            em = _ERROR_PAT.search(line)
            if em:
                rec["evidence"] = em.group(0).strip()
            elif "failed" in line and "task=" not in line and not rec["evidence"]:
                rec["evidence"] = line.strip()[:120]
    return samples


def _scan_task_dirs() -> dict:
    samples: dict = {}
    for d in OUTPUT.iterdir():
        if not d.is_dir():
            continue
        pl = d / "pipeline_log.json"
        if not pl.exists():
            continue
        try:
            p = json.loads(pl.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not p.get("ok"):
            gate = (p.get("stages") or {}).get("mcp_gate") or {}
            samples[d.name] = {"task_id": d.name, "error_code": "pipeline_failed",
                               "evidence": p.get("error") or "",
                               "failed_checks": gate.get("failed_checks")}
    return samples


def main(argv=None) -> int:
    out = {}
    out.update(_scan_logs())
    out.update(_scan_task_dirs())
    data = {"schema": "infeasible_samples_v1", "count": len(out),
            "samples": list(out.values())}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"infeasible samples: {len(out)} -> {OUT}")
    for s in list(out.values())[:8]:
        print(f"  {s['task_id']:24s} {s['error_code']:16s} {(s['evidence'] or '')[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
