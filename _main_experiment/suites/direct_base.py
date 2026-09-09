"""Direct-Base baseline: LLM writes CadQuery code, executed without IR harness."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import ExperimentConfig
from ..llm import OpenAICompatToolClient
from ..schemas import MetricResult, RunResult, RunStatus, TaskSpec
from ..utils import atomic_write_json, utc_now_iso
from .base import suite_root

_CODE_SYSTEM = (
    "You are a CadQuery code generator. Output ONLY executable Python code that "
    "builds the requested turbine disc, exports STEP to OUT_STEP, and prints "
    "{'ok': true}. Use import cadquery as cq. The variable OUT_STEP is provided."
)


def _run_code_utf8(code: str, *, timeout: float = 120.0):
    """Execute code as a UTF-8 temp module (avoids GBK temp-file syntax errors)."""
    import os as _os
    import subprocess
    import tempfile

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False,
                                      encoding="utf-8")
    try:
        tmp.write(code)
        tmp.close()
        return subprocess.run(
            [_os.sys.executable, tmp.name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, shell=False,
            env=dict(_os.environ),
            cwd=tempfile.gettempdir(),
        )
    finally:
        try:
            _os.unlink(tmp.name)
        except Exception:
            pass


def run_direct_base(
    task: TaskSpec,
    config: ExperimentConfig,
    seed: int,
) -> RunResult:
    client = OpenAICompatToolClient()
    out_dir = suite_root(config, "direct_base") / "runs" / task.task_id / f"seed_{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = RunResult(
        run_id=f"{task.task_id}_{seed}", method_id="direct_base",
        task_id=task.task_id, seed=seed,
        started_at=utc_now_iso(),
    )
    try:
        llm = config.llm.model_copy(update={"seed": seed})
        call = client.call_strict_tool(
            messages=[
                {"role": "system", "content": _CODE_SYSTEM},
                {"role": "user", "content": task.prompt},
            ],
            tool_name="emit_cadquery", tool_description="输出 CadQuery 代码",
            tool_schema={"type": "object", "properties": {"code": {"type": "string"}},
                         "required": ["code"]},
            config=llm,
        )
        code = call.arguments.get("code", "")
        atomic_write_json(out_dir / "generated_code.json", {"code": code})
        step = out_dir / "output.step"
        wrapped = (
            "import os, json, cadquery as cq\n"
            f"OUT_STEP = {str(step)!r}\n"
            + code
        )
        proc = _run_code_utf8(wrapped, timeout=120.0)
        ok = proc.returncode == 0 and step.exists()
        result.status = RunStatus.COMPLETED if ok else RunStatus.FAILED
        result.ok = ok
        result.outputs = {"step": str(step), "code": str(out_dir / "generated_code.json")}
        result.error_message = proc.stderr[:300] if not ok else None
        result.error_stage = "runtime" if not ok else None
        if ok:
            try:
                import cadquery as cq
                obj = cq.importers.importStep(str(step))
                bb = obj.val().BoundingBox()
                measured = {
                    "outer_diameter_mm": round(max(bb.xlen, bb.ylen), 3),
                    "axial_thickness_mm": round(bb.zlen, 3),
                }
                atomic_write_json(out_dir / "measurements.json", measured)
                result.outputs["measurements"] = str(out_dir / "measurements.json")
                tol = max((d.tolerance_mm for d in task.gold.key_dimensions), default=0.05)
                ok_dims = all(
                    abs(measured.get(name, 1e9) - d.expected_mm) <= max(tol, d.tolerance_mm)
                    for name, d in ((n, next(x for x in task.gold.key_dimensions if x.name == n))
                                    for n in ("outer_diameter_mm", "axial_thickness_mm")
                                    if any(x.name == n for x in task.gold.key_dimensions))
                )
                result.metrics.append(MetricResult(
                    metric_id="direct_engineering_ok",
                    name="Direct-Base Engineering Pass（bbox 可测尺寸）",
                    value=ok_dims, unit="ratio", level="task", passed=ok_dims,
                    notes=f"measured={measured}",
                ))
            except Exception as exc:  # noqa: BLE001
                result.metrics.append(MetricResult(
                    metric_id="direct_measure_error", name="Direct-Base 尺寸测量",
                    value=False, passed=False, notes=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        result.status = RunStatus.FAILED
        result.ok = False
        result.error_stage = "llm"
        result.error_message = str(exc)[:300]
    result.finished_at = utc_now_iso()
    atomic_write_json(out_dir / "run.json", result.model_dump(mode="json"))
    return result


def run_suite(tasks: list[TaskSpec], config: ExperimentConfig,
              *, seeds: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)) -> list[RunResult]:
    results = []
    for task in tasks:
        for seed in seeds:
            try:
                results.append(run_direct_base(task, config, seed))
            except Exception as exc:  # noqa: BLE001
                results.append(RunResult(
                    run_id=f"{task.task_id}_{seed}", method_id="direct_base",
                    task_id=task.task_id, seed=seed, status=RunStatus.FAILED,
                    ok=False, error_stage="harness", error_message=str(exc)[:300]))
    return results


def aggregate(results: list[RunResult]) -> dict[str, Any]:
    total = max(1, len(results))
    eng_ok = sum(
        1 for r in results
        if any(m.metric_id == "direct_engineering_ok" and m.value for m in r.metrics)
    )
    return {
        "runs": len(results),
        "cad_pass1": round(sum(1 for r in results if r.ok) / total, 4),
        "engineering_pass1_bbox": round(eng_ok / total, 4),
        "note": "Direct-Base 无 IR/规范；工程指标基于 STEP 包围盒可测尺寸（外径/轴厚），"
                "bore/槽深等需截面测量，不在 bbox 口径内。",
    }
