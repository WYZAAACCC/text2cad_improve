"""临时验证：canonical_ir.json 序列化可行性（用已有 raw_fixed.json 走真实 canonicalize）。"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.canonicalize import canonicalize

out = ROOT / "app" / "text-to-cad" / "server" / "output" / "mon_sweep_q2_slots_96"
raw = json.loads((out / "raw_fixed.json").read_text(encoding="utf-8"))
canonical, report = canonicalize(RawGcadDocument.model_validate(raw))
assert canonical is not None, f"canonicalize failed: {report}"
txt = canonical.model_dump_json(indent=2)
data = json.loads(txt)
assert data.get("nodes"), "nodes empty"
print(f"canonical serialize OK: nodes={len(data['nodes'])} components={len(data['components'])} hash={data.get('canonical_graph_hash','')[:12]}")
