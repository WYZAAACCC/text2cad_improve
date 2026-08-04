"""临时验证：run_enrich 的 ⑦a ir_doc_hash（结构哈希）+ ⑦b param_template_id（参数向量）。"""
import copy
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import run_enrich  # noqa: E402
from param_sweep_test import _text  # noqa: E402

base = ROOT / "app" / "text-to-cad" / "server" / "output" / "mon_sweep_q2_slots_96"
raw = json.loads((base / "raw_fixed.json").read_text(encoding="utf-8"))

# ── ⑦a：结构哈希 ──
h0 = run_enrich._ir_doc_hash(raw)
print("ir_doc_hash base:", h0[:20])

# 改参数值（count 96→60）：hash 应不变
raw2 = copy.deepcopy(raw)
for n in raw2["nodes"]:
    if n["op"] == "circular_pattern_component":
        n["params"]["count"] = 60
h1 = run_enrich._ir_doc_hash(raw2)
assert h0 == h1, "改参数值 hash 不应变化"
print("改 count 96→60 → hash 不变  PASS")

# 改圆角值：hash 不变
raw3 = copy.deepcopy(raw)
for n in raw3["nodes"]:
    if n["op"] == "fillet_sketch":
        n["params"]["radius_mm"] = 9.99
h2 = run_enrich._ir_doc_hash(raw3)
assert h0 == h2, "改圆角值 hash 不应变化"
print("改圆角值 → hash 不变  PASS")

# 增节点：hash 应变
raw4 = copy.deepcopy(raw)
raw4["nodes"].append({"id": "n_extra", "component": "disc_body", "dialect": "sketch_profile",
                      "op": "dummy_op", "params": {}})
h3 = run_enrich._ir_doc_hash(raw4)
assert h0 != h3, "新增节点 hash 应变化"
print("新增节点 → hash 变化  PASS")

# 改节点 id（保序）：hash 应不变（抗 LLM 命名漂移）
raw5 = copy.deepcopy(raw)
renamed = {}
for n in raw5["nodes"]:
    renamed[n["id"]] = "new_" + n["id"]
    n["id"] = "new_" + n["id"]
for n in raw5["nodes"]:
    for inp in n.get("inputs") or []:
        if inp.get("node") in renamed:
            inp["node"] = renamed[inp["node"]]
for comp in raw5.get("components") or []:
    if comp.get("root_node") in renamed:
        comp["root_node"] = renamed[comp["root_node"]]
h4 = run_enrich._ir_doc_hash(raw5)
assert h0 == h4, "改节点 id hash 不应变化"
print("改节点 id（保序）→ hash 不变  PASS")

# 结构分组间乱序（组内保序）：hash 应不变（抗整体顺序漂移）
raw6 = copy.deepcopy(raw)
def _skey(n):
    return (str(n.get("component", "")), str(n.get("dialect", "")), str(n.get("op", "")),
            str(n.get("op_version", "")),
            run_enrich._json_hash(run_enrich._symbolize(n.get("params", {}))))
groups = {}
for n in raw6["nodes"]:
    groups.setdefault(_skey(n), []).append(n)
import random
random.seed(2)
glist = list(groups.values())
random.shuffle(glist)
raw6["nodes"] = [n for g in glist for n in g]
h5 = run_enrich._ir_doc_hash(raw6)
assert h0 == h5, "结构分组间乱序 hash 不应变化"
print("结构分组间乱序 → hash 不变  PASS")

# ── ⑦b：参数向量 ──
t_g1 = _text(500, 120, 76, 38, 30, 60, 2, 250, 24, 4.0, 1.0)
t_g1_rw = ("请生成高压涡轮盘的参考模型：轮毂-腹板-轮缘结构，外径500mm、中心孔直径120mm、"
           "轴向最大厚度76mm、轮毂半厚38mm、轮缘半厚30mm、轮缘上60个2齿枞树形榫槽、"
           "分布半径250mm、槽深24mm、喉部半宽4.0mm、齿根圆角1.0mm。参考几何，非适航件。")
t_g2 = _text(500, 120, 76, 38, 30, 48, 2, 250, 28, 4.0, 1.0)

p1 = run_enrich._param_template_id(t_g1)
p1r = run_enrich._param_template_id(t_g1_rw)
p2 = run_enrich._param_template_id(t_g2)
assert p1 == p1r, "同组合改写应同 id"
assert p1 != p2, "不同组合应不同 id"
print("⑦b: G1 vs 改写 同 id, G1 vs G2 不同 id  PASS")
print("  p1 =", p1[:20])
print("  p2 =", p2[:20])

print("ALL OK")
