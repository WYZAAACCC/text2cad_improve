from pathlib import Path

p = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\authoring\auto_fixer.py")
s = p.read_text(encoding="utf-8")
old = "def _fill_default_params(doc: dict) -> dict:\n    \"\"\"填充缺失的有默认值的参数。\"\"\"\n    defaults = {"
new = "def _fill_default_params(doc: dict) -> dict:\n    \"\"\"填充缺失的有默认值的参数。\"\"\"\n    revolve_components = {n.get(\"component\") for n in doc.get(\"nodes\", [])\n                           if n.get(\"op\") == \"revolve_profile\"}\n    for node in doc.get(\"nodes\", []):\n        if (node.get(\"op\") == \"create_2d_sketch\"\n                and node.get(\"component\") in revolve_components):\n            params = node.setdefault(\"params\", {})\n            params.setdefault(\"plane\", \"XZ\")\n            params.setdefault(\"origin_x_mm\", 0)\n            params.setdefault(\"origin_y_mm\", 0)\n    defaults = {"
n = s.count(old)
assert n == 1, n
p.write_text(s.replace(old, new), encoding="utf-8")
print("patched")

