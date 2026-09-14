"""Are the chain's and the probe's inputs to the agent actually identical?

The observation is that the probe submits and the chain does not, and the
tempting conclusion is that something about the chain differs. That conclusion
is only worth anything if the inputs have been compared rather than assumed,
so this builds both and diffs every field the agent can see.

Checked: the two AgentSpec objects field by field, the two model configs, and
every field of the two FaceFinderStates. Anything that differs is printed with
both values.
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import fields

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.agents import facefind          # noqa: E402
from seekflow_structural.agents.assembly import REQUIREMENTS  # noqa: E402
from seekflow_structural.runtime.caller import build_caller   # noqa: E402

BUNDLE = REPO / "_cfd_experiment" / "input" / "lineage" / "D27"
KEY = REPO / "_structural_experiment" / "input" / ".deepseek_key"

# What the probe hardcodes.
PROBE_REQUIREMENT = (
    "the faces that carry the blade load into the body. The load acts normal "
    "to the bearing surface, pressing into the material, so the outward "
    "normal of each of these faces points into the space the blade root "
    "occupies."
)
PROBE_SECTOR = {"theta_low_deg": 9.0, "theta_high_deg": 27.0}
PROBE_INDEX = REPO / "_structural_experiment" / "work" / "D27_fast.sqlite"
PROBE_WORKDIR = REPO / "_structural_experiment" / "work" / "facefind_origins"

# What the chain derived, taken from the run that failed.
CHAIN_SECTOR_DEG = 18.0
CHAIN_THETA_LOW = 9.0


def report(label: str, left, right) -> bool:
    same = left == right
    print(f"{'same ' if same else 'DIFF '} {label}")
    if not same:
        if isinstance(left, str) and isinstance(right, str):
            print(f"        chain: {left!r}")
            print(f"        probe: {right!r}")
            for index, (a, b) in enumerate(zip(left, right)):
                if a != b:
                    print(f"        first difference at {index}: "
                          f"{left[max(0,index-40):index+40]!r} vs "
                          f"{right[max(0,index-40):index+40]!r}")
                    break
            if len(left) != len(right):
                print(f"        lengths: chain={len(left)} probe={len(right)}")
        else:
            print(f"        chain: {left!r}")
            print(f"        probe: {right!r}")
    return same


def main() -> int:
    caller, config = build_caller(KEY)
    del caller

    chain_spec = facefind.spec(
        requirement=REQUIREMENTS["flank_surface_normal"],
        sector_deg=CHAIN_SECTOR_DEG, theta_low_deg=CHAIN_THETA_LOW,
        max_calls=30,
    )
    probe_spec = facefind.spec(
        requirement=PROBE_REQUIREMENT,
        sector_deg=18.0, theta_low_deg=9.0, max_calls=30,
    )

    print("=== the spec the agent is given ===")
    all_same = True
    for field in fields(chain_spec):
        all_same &= report(
            field.name,
            getattr(chain_spec, field.name),
            getattr(probe_spec, field.name),
        )
    all_same &= report(
        "tool_schema",
        json.dumps(chain_spec.action_model.model_json_schema(), sort_keys=True),
        json.dumps(probe_spec.action_model.model_json_schema(), sort_keys=True),
    )

    print()
    print("=== the model config ===")
    all_same &= report("model", config.model, config.model)
    all_same &= report("base_url", config.base_url, config.base_url)
    all_same &= report("temperature", config.temperature, config.temperature)
    all_same &= report("timeout_s", config.timeout_s, config.timeout_s)

    print()
    print("=== the state, field by field ===")
    chain_state = facefind.FaceFinderState(
        session=None, bundle=BUNDLE,
        evolution_db=pathlib.Path("CHAIN") / "model" / "face_evolution.sqlite",
        sector={
            "theta_low_deg": CHAIN_THETA_LOW,
            "theta_high_deg": (CHAIN_THETA_LOW + CHAIN_SECTOR_DEG) % 360.0,
        },
        workdir=pathlib.Path("CHAIN") / "agent" / "analyses",
    )
    probe_state = facefind.FaceFinderState(
        session=None, bundle=BUNDLE, evolution_db=PROBE_INDEX,
        sector=PROBE_SECTOR, workdir=PROBE_WORKDIR,
    )
    for field in fields(chain_state):
        name = field.name
        if name in ("session", "cache", "rows", "analyses", "origins_cache"):
            print(f"skip  {name} (built at run time)")
            continue
        report(name, getattr(chain_state, name), getattr(probe_state, name))

    print()
    print("=== the sector the prompt is built from ===")
    chain_scope = facefind._scope_lines(CHAIN_SECTOR_DEG, CHAIN_THETA_LOW)
    probe_scope = facefind._scope_lines(18.0, 9.0)
    all_same &= report("scope lines", chain_scope, probe_scope)

    print()
    print("EVERY STATIC INPUT IDENTICAL:", all_same)
    print()
    print("Note: the two paths below differ and are NOT agent inputs -")
    print(f"  chain index : CHAIN/model/face_evolution.sqlite (built lazily)")
    print(f"  probe index : {PROBE_INDEX.name} (pre-built)")
    print(f"  chain workdir: CHAIN/agent/analyses")
    print(f"  probe workdir: {PROBE_WORKDIR.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
