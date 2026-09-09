"""将已生成的 llm_raw（agent 或参数化）送入主流程下游：
   llm_raw → validation → repair 双环 → runtime → output.step
   复用 repair_kernel.run_generation_loop（与 main._run_pipeline 的 L2 之后完全一致），
   不再重跑 L1 路由 / L2 agent 生成。
"""
import argparse
import json
import os
import sys
from pathlib import Path

_SERVER = Path(r"e:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server")
_ENG = Path(r"e:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src")
_PARAM = Path(r"e:\text_to_cad_improve\auto_detection_process\_param_experiment")
for p in (_SERVER, _ENG, _PARAM):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm_raw", required=True, help="输入的 llm_raw.json 路径")
    ap.add_argument("--out", required=True, help="输出目录（output.step / output.metadata.json / raw_fixed.json）")
    a = ap.parse_args()

    raw = json.loads(Path(a.llm_raw).read_text(encoding="utf-8"))
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    step_path = out_dir / "output.step"
    meta_path = out_dir / "output.metadata.json"

    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    from seekflow_engineering_tools.generative_cad.repair_kernel import (
        RepairLoopConfig,
        run_generation_loop,
    )

    config = LlmModelConfig(model="deepseek-v4-pro",
                            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/beta"))
    caller = DeepSeekToolCaller()
    reg = default_registry()

    loop = run_generation_loop(
        raw, out_step=step_path, metadata_path=meta_path,
        dialect_registry=reg, config=RepairLoopConfig(),
        validation_repair_caller=caller, runtime_repair_caller=caller,
        llm_model_config=config, audit_dir=out_dir, user_request="",
    )

    try:
        (out_dir / "raw_fixed.json").write_text(
            json.dumps(loop.document, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    rr = loop.run_result
    print("RUNTIME_OK:", bool(rr.ok) if rr else None)
    print("STOP_CODE:", loop.outcome.stop_code)
    print("VLLM_ATTEMPTS:", loop.outcome.validation_llm_attempts,
          "RLLM_ATTEMPTS:", loop.outcome.runtime_llm_attempts)
    print("STEP_EXISTS:", step_path.exists(),
          "STEP_KB:", step_path.stat().st_size // 1024 if step_path.exists() else 0)
    print("META_EXISTS:", meta_path.exists())


if __name__ == "__main__":
    main()