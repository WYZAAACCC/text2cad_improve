"""Run the CFD expert review on a confirmed spec and persist its trace.

This is a development/review utility. It never executes CFD tools and never
writes or mutates the simulation spec.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations/cfd/src"))
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))

from seekflow_cfd.agents import ExpertTeam  # noqa: E402
from seekflow_cfd.models import SimulationSpec  # noqa: E402
from seekflow_cfd.storage import atomic_json  # noqa: E402
from seekflow_engineering_tools.generative_cad.llm.deepseek_client import (  # noqa: E402
    DeepSeekToolCaller,
)
from seekflow_engineering_tools.generative_cad.llm.models import (  # noqa: E402
    LlmModelConfig,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("spec", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--api-key-file", type=Path)
    p.add_argument("--model", default="deepseek-v4-pro")
    p.add_argument("--base-url", default="https://api.deepseek.com/beta")
    p.add_argument("--timeout-s", type=int, default=120)
    p.add_argument(
        "--record",
        type=Path,
        help="Optional successful CFD record.json for result-evidence review.",
    )
    args = p.parse_args()

    if args.api_key_file:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key_file.read_text(
            encoding="utf-8"
        ).strip()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY is not set")

    spec = SimulationSpec.model_validate(
        json.loads(args.spec.resolve().read_text(encoding="utf-8"))
    )
    team = ExpertTeam(
        DeepSeekToolCaller(),
        LlmModelConfig(
            model=args.model,
            base_url=args.base_url,
            timeout_s=args.timeout_s,
            temperature=0,
        ),
        max_calls=10,
        timeout_s=args.timeout_s,
    )
    team.review(spec)
    result_review = None
    if args.record:
        record = json.loads(args.record.resolve().read_text(encoding="utf-8"))
        state_path = args.record.resolve().parent / "state.json"
        last_sample = None
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("samples"):
                last_sample = state["samples"][-1]
        flux_summary = None
        if last_sample:
            flux = last_sample["mass_flux_kg_s"]
            scale = max(sum(abs(v) for v in flux.values()), 1e-30)
            flux_summary = {
                "boundary_mass_flux_kg_s": flux,
                "net_mass_flux_kg_s": sum(flux.values()),
                "relative_mass_imbalance": abs(sum(flux.values())) / scale,
            }
        result_review = team.review_results(
            spec,
            {
                "metrics": record["metrics"],
                "mesh_report": record["mesh_report"],
                "boundary_flux_summary": flux_summary,
                "scope_note": (
                    "This is a software integration verification case, not a "
                    "certified physical prediction. The energy equation is not "
                    "active for isothermal flow, and mesh independence is not "
                    "claimed from a single mesh."
                ),
            },
            record["solver_log_summary"]["convergence"],
        ).model_dump(mode="json")
    payload = {
        "spec_hash": spec.spec_hash,
        "model": args.model,
        "trace": team.trace,
        "result_review": result_review,
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output.resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
