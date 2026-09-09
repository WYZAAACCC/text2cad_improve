from pathlib import Path

p = Path(r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server\agentic_l2.py")
s = p.read_text(encoding="utf-8")
old = "def _loads_json(raw):\n    try:\n        return json.loads(raw)\n    except Exception:\n        start = raw.find(\"{\")\n        end = raw.rfind(\"}\")\n        if start >= 0 and end > start:\n            return json.loads(raw[start:end+1])\n        raise"
new = "def _loads_json(raw):\n    try:\n        return json.loads(raw)\n    except Exception:\n        fixed = raw.replace(\": {}}\", \": {}\").replace(\": }\", \": {}\")\n        if fixed != raw:\n            try:\n                return json.loads(fixed)\n            except Exception:\n                pass\n        start = raw.find(\"{\")\n        end = raw.rfind(\"}\")\n        if start >= 0 and end > start:\n            return json.loads(raw[start:end+1])\n        raise"
n = s.count(old)
assert n == 1, n
p.write_text(s.replace(old, new), encoding="utf-8")
print("patched")

