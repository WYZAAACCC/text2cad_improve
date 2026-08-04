"""确认 request.json/canonical_ir.json 内容与输入一致（避免编码损坏）。"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "_param_experiment"))

from param_sweep_test import _text  # noqa: E402

d = ROOT / "app" / "text-to-cad" / "server" / "output" / "verify_ds_7d530150"
req = json.loads((d / "request.json").read_text(encoding="utf-8"))
expected = _text(500, 120, 76, 38, 30, 48, 2, 250, 24, 4.0, 1.0)
assert req["text"] == expected, "request.text 与输入不一致!"
assert req["desc_style"] is None
print("request roundtrip OK  text_len =", len(req["text"]), " desc_style =", req["desc_style"])

raw = json.loads((d / "raw_fixed.json").read_text(encoding="utf-8"))
ir = json.loads((d / "canonical_ir.json").read_text(encoding="utf-8"))
assert ir["document_id"] == raw.get("document_id"), "document_id 不一致"
print("canonical_ir roundtrip OK  document_id =", ir["document_id"])
print("request.text 前 40 字符:", req["text"][:40])
