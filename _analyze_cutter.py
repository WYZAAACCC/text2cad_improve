import json
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
RUN = ROOT / "_main_experiment" / "output" / "runs" / "full_agentic" / "T25" / "seed_0" / "latest" / "llm_raw.json"
GOLD = ROOT / "_main_experiment" / "output" / "golden" / "T25" / "llm_raw.json"

doc = json.loads(RUN.read_text(encoding="utf-8"))
gold = json.loads(GOLD.read_text(encoding="utf-8"))

def show(d, tag):
    print("=====", tag, "=====")
    for n in d.get("nodes", []):
        if n.get("op") in ("create_2d_sketch", "add_polyline", "close_profile", "fillet_sketch", "extrude_profile", "boolean_cut", "circular_pattern_component"):
            print(n.get("id"), n.get("op"), "phase=", n.get("phase"), "op_version=", n.get("op_version"))
            print("   params:", json.dumps(n.get("params", {}), ensure_ascii=False)[:500])

show(doc, "AGENT T25 seed0")
show(gold, "GOLD T25")
