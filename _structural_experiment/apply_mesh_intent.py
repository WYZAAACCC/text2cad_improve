"""Apply an agent-authored mesh refinement intent to a mesh config."""
from __future__ import annotations
import argparse, json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("intent", type=Path)
p.add_argument("base_config", type=Path)
p.add_argument("output", type=Path)
p.add_argument("--max-elements", type=int, default=150000)
a = p.parse_args()

doc = json.loads(a.intent.read_text(encoding="utf-8"))
final = doc["final"]
if not final.get("accepted"):
    raise SystemExit("mesh intent was not accepted: %s" % final.get("questions"))

cfg = json.loads(a.base_config.read_text(encoding="utf-8"))
refinement = final["refinement"]
cfg["mesh"]["refinement"] = {
    "web_size_mm": refinement["web_size_mm"],
    "zones": [
        {"name": z["name"], "r_center_mm": z["r_center_mm"],
         "size_mm": z["size_mm"], "ramp_mm": z["ramp_mm"]}
        for z in refinement["zones"]
    ],
}
# The agent's floor drives the global minimum; a size it asked for must not be
# clamped away by the hand-set default.
cfg["mesh"]["size_min_mm"] = min(
    [cfg["mesh"].get("size_min_mm", 1e9)] + [z["size_mm"] for z in refinement["zones"]]
)
cfg["mesh"]["size_max_mm"] = max(
    [cfg["mesh"].get("size_max_mm", 0.0), refinement["web_size_mm"]]
)
cfg["mesh"]["source"] = "agent_mesh_intent"
a.output.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(cfg["mesh"], indent=2, ensure_ascii=False))
