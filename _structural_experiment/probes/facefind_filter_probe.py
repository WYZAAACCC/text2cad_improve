"""Does the agent use the numeric filters, given the schema and a summary?

Replays the exchange up to the point where the real run went wrong: the agent
has seen the feature summary and one query result, and is asked for its next
action. What it does with the filter fields is the whole question.
"""
import json, pathlib, sys
sys.path.insert(0, "integrations/structural/src")
sys.path.insert(0, "integrations/engineering_tools/src")
from seekflow_structural.agents import facefind
from seekflow_structural.runtime.caller import build_caller

caller, cfg = build_caller(pathlib.Path("_structural_experiment/input/.deepseek_key"))
spec = facefind.spec(requirement=(
    "the faces that carry the blade load into the body. The load acts normal "
    "to the bearing surface, pressing into the material, so the outward "
    "normal of each of these faces points into the space the blade root "
    "occupies."
), max_calls=20)

conversation = [
    {"role": "system", "content": spec.system_prompt},
    {"role": "user", "content": spec.user_prompt},
]
# The feature summary the agent actually gets now.
features = {"ok": True, "calls_used": 1, "calls_remaining": 19, "result": {"features": [
    {"feature": "n_disc_revolve", "kind": "", "solids": 1, "faces_total": 15,
     "volume_mm3_max": 15197908.6, "bbox_mm_max": [-300, -300, -42.2, 300, 300, 38]},
    {"feature": "n_pat_holes", "kind": "", "solids": 20, "faces_total": 360,
     "volume_mm3_max": 88169.7, "bbox_mm_max": [-6, -6, -400, 6, 6, 400]},
    {"feature": "n_pattern_cutters", "kind": "", "solids": 60, "faces_total": 4080,
     "volume_mm3_max": 15460.9, "bbox_mm_max": [-22.1, -7.6, -40, 0, 7.6, 40]},
    {"feature": "n_final_cut", "kind": "", "solids": 1, "faces_total": 4216,
     "volume_mm3_max": 14300472.5, "bbox_mm_max": [-299.9, -299.9, -42.2, 300, 299.9, 38]},
]}}

def turn(action_kwargs, reply):
    """One exchange: the model called `action_kwargs`, and got `reply` back."""
    conversation.append({"role": "assistant", "content": "", "tool_calls": [{
        "id": "c1", "type": "function",
        "function": {"name": "face_action", "arguments": json.dumps(action_kwargs)}}]})
    conversation.append({"role": "tool", "tool_call_id": "c1",
                         "content": json.dumps(reply, ensure_ascii=False)})

turn({"action": "list_features"}, features)
res = caller.call_strict_tool(
    messages=conversation, tool_name=spec.tool_name,
    tool_description=spec.tool_description,
    tool_schema=spec.action_model.model_json_schema(), model_config=cfg)
print("AFTER list_features ->", json.dumps(res.arguments, ensure_ascii=False)[:700])

# Now feed it the summary of an unfiltered query on the body.
turn(res.arguments, {"ok": True, "calls_used": 2, "calls_remaining": 18, "result": {
    "face_count_total": 4216, "matched": 4216, "filters_applied": {},
    "faces_listed": 0,
    "summary": {"count": 4216,
                "surface_types": {"plane": 2257, "cylinder": 1954, "torus": 3, "cone": 2},
                "area_mm2": {"min": 23.562, "median": 36.07, "max": 90399.34},
                "radius_mm": {"min": 0.0, "median": 286.0, "max": 299.95},
                "z_mm": {"min": -38.0, "median": 0.0, "max": 38.0},
                "normal_radial": {"min": -0.982, "median": 0.146, "max": 1.0},
                "normal_axial": {"min": -1.0, "median": 0.0, "max": 1.0}},
    "note": "the summary describes the whole matched set."}})
res = caller.call_strict_tool(
    messages=conversation, tool_name=spec.tool_name,
    tool_description=spec.tool_description,
    tool_schema=spec.action_model.model_json_schema(), model_config=cfg)
args = res.arguments
numeric = {k: v for k, v in args.items()
           if isinstance(v, (int, float)) and v not in (-1e30, 1e30, 0, 60)}
print("AFTER the summary ->", args.get("action"), "| numeric filters set:", numeric)
print("  rationale:", (args.get("rationale") or "")[:300])
