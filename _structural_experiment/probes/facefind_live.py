"""Run the real facefind loop against the real part, printing each turn raw.

Everything is the production path - same dispatch, same state, same schema -
so what the model emits here is what it emits in the chain. Only the number of
turns is capped, so a wrong pattern shows up in a minute rather than twenty.
"""
import json, pathlib, sys
sys.path.insert(0, "integrations/structural/src")
sys.path.insert(0, "integrations/engineering_tools/src")
from seekflow_structural.agents import facefind
from seekflow_structural.runtime import loop as loop_mod
from seekflow_structural.runtime.caller import build_caller
from seekflow_structural.tools import geometry

CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 8
bundle = pathlib.Path("_cfd_experiment/input/lineage/D27")
session = geometry.open_bundle(bundle)
state = facefind.FaceFinderState(session=session)
caller, cfg = build_caller(pathlib.Path("_structural_experiment/input/.deepseek_key"))

spec = facefind.spec(requirement=(
    "the faces that carry the blade load into the body. The load acts normal "
    "to the bearing surface, pressing into the material, so the outward "
    "normal of each of these faces points into the space the blade root "
    "occupies."), max_calls=CAP)

# Wrap the caller so every raw turn is visible, then delegate to the real loop.
class Spy:
    def __init__(self, inner): self.inner, self.n = inner, 0
    def call_strict_tool(self, **kw):
        r = self.inner.call_strict_tool(**kw)
        self.n += 1
        a = r.arguments
        numeric = {k: v for k, v in a.items()
                   if isinstance(v, (int, float))
                   and v not in (-1e30, 1e30, 0, 60)}
        print(f"[{self.n}] {a.get('action')}"
              f"{' st=' + str(a.get('surface_type')) if a.get('surface_type') else ''}"
              f"{' feature=' + str(a.get('feature')) if a.get('feature') else ''}"
              f" numeric={numeric}")
        if a.get("rationale"):
            print("     why:", str(a["rationale"])[:220])
        return r

try:
    out = loop_mod.run_agent(spec, caller=Spy(caller), model_config=cfg,
                             dispatch=facefind.DISPATCH, context=state)
    print("final:", json.dumps(out.final, ensure_ascii=False)[:400])
    print("exhausted:", out.exhausted)
finally:
    session.close()
