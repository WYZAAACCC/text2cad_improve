from pathlib import Path

p = Path(r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server\agentic_l2.py")
s = p.read_text(encoding="utf-8")
old = "        fixed = raw.replace(\": {}}\", \": {}\").replace(\": }\", \": {}\")\n        if fixed != raw:\n            try:\n                return json.loads(fixed)\n            except Exception:\n                pass"
new = "        fixed = raw.replace(\": {}}\", \": {}\").replace(\": }\", \": {}\")\n        if fixed != raw:\n            opens = fixed.count(\"{\")\n            closes = fixed.count(\"}\")\n            if opens > closes:\n                fixed += \"}\" * (opens - closes)\n            try:\n                return json.loads(fixed)\n            except Exception:\n                pass"
n = s.count(old)
assert n == 1, n
p.write_text(s.replace(old, new), encoding="utf-8")
print("patched")

