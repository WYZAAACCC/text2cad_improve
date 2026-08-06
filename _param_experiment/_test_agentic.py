"""临时：快速验证 agentic_l2（Agent A + 轮廓 agent），检查骨架与轮廓质量。"""
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
for cand in (_HERE.parent / "_archive" / "apikey.txt",
             Path(r"E:\auto_detection_process\_archive\apikey.txt")):
    if cand.exists():
        os.environ["DEEPSEEK_API_KEY"] = cand.read_text().strip()
        break
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES, build_text
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from agentic_l2 import run_agentic_l2

text = build_text(DESIGN_FAMILIES["D15"])
config = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
caller = DeepSeekToolCaller()
out_dir = ROOT / "app" / "text-to-cad" / "server" / "output" / "_agentic_test"
out_dir.mkdir(parents=True, exist_ok=True)

raw = run_agentic_l2(text, None, caller=caller, llm_model_config=config, out_dir=out_dir)

print("=== 生成 IR 概要 ===")
print("nodes:", len(raw.get("nodes", [])))
for n in raw.get("nodes", []):
    op = n.get("op")
    if op == "add_polyline":
        pts = n.get("params", {}).get("points", [])
        xs = [round(p.get("x_mm"), 2) for p in pts]
        ys = [round(p.get("y_mm"), 2) for p in pts]
        print(f"[{n.get('id')}] {op} points={len(pts)}")
        print(f"   x={xs}")
        print(f"   y={ys}")
        # 退化检查：root 半宽>0、相邻边>=1.5
        if len(pts) >= 4:
            n_half = len(pts) // 2
            root_y = abs(ys[n_half - 1])
            print(f"   root半宽={root_y} (>0? {root_y > 0})")
            mins = min(abs(pts[i + 1]["x_mm"] - pts[i]["x_mm"]) + abs(pts[i + 1]["y_mm"] - pts[i]["y_mm"])
                       for i in range(len(pts) - 1))
            print(f"   最接近邻边曼哈顿距离={round(mins, 2)}")
    else:
        p = n.get("params", {})
        print(f"[{n.get('id')}] {op} params={json.dumps(p, ensure_ascii=False)[:100]}")
print("\nprofiles:", json.dumps(json.loads((out_dir / "agent_a_plan.json").read_text(encoding="utf-8")).get("profiles"), ensure_ascii=False)[:400])
