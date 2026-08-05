"""临时检查：第二梯队任务构造器产出质量。"""
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
D = _HERE / "output" / "datasets"

ok_all = True


def chk(name, cond, detail=""):
    global ok_all
    print(f"{name:46s}", "OK " if cond else "FAIL", detail)
    ok_all = ok_all and bool(cond)


def count(typ):
    return len(list((D / f"{typ}_tasks").glob("*.json")))


# ── Edit ──
n = count("edit")
chk(f"edit 样本数>0", n > 0, f"={n}")
for f in list((D / "edit_tasks").glob("*.json"))[:3]:
    s = json.load(open(f, encoding="utf-8"))
    chk(f"edit {s['sample_id'][:30]} 结构完整",
        s["instruction"] and s["design_id"] and s["before"] and s["after"] and s["validated_ok"],
        s["instruction"][:30])

# ── Repair ──
n = count("repair")
chk(f"repair 样本数>0", n > 0, f"={n}")
for f in list((D / "repair_tasks").glob("*.json"))[:4]:
    s = json.load(open(f, encoding="utf-8"))
    chk(f"repair {s['sample_id'][:34]} wrong/right+repair_ok",
        s.get("wrong_ir") and s.get("right_ir") and s.get("repair_ok") is True,
        f"src={s.get('error_source')} rule={s.get('rule_id')}")
    if s.get("error_source") == "controlled_injection":
        chk(f"repair {s['sample_id'][:34]} 错误码已触发",
            bool(s.get("validation_error_codes")), str(s.get("validation_error_codes")))

# ── MCP ──
n = count("mcp")
chk(f"mcp 样本数>0", n > 0, f"={n}")
single = [json.loads(f.read_text(encoding="utf-8")) for f in (D / "mcp_tasks").glob("*.json")
          if "single_tool" in f.name]
multi = [json.loads(f.read_text(encoding="utf-8")) for f in (D / "mcp_tasks").glob("*.json")
         if "multi_tool" in f.name]
chk(f"mcp single/multi 都有", len(single) > 0 and len(multi) > 0,
    f"single={len(single)} multi={len(multi)}")
if single:
    s = single[0]
    chk("mcp 样本含 expected_args + tool_sequence",
        s.get("expected_args") and s.get("tool_sequence") and s.get("validated_ok"),
        f"tools={[t['tool'] for t in s['tool_sequence']]}")

# ── design_id 继承 ──
src = json.loads((_HERE.parent / "app" / "text-to-cad" / "server" / "output"
                  / "mon_sweep_q2_slots_96" / "dataset_enrich.json").read_text(encoding="utf-8"))
edit = [json.loads(f.read_text(encoding="utf-8")) for f in (D / "edit_tasks").glob("*.json")
        if "mon_sweep_q2_slots_96" in f.name]
if edit:
    chk("edit design_id 继承源", edit[0]["design_id"] == src.get("design_id"))

print("\nALL", "OK" if ok_all else "FAIL")
