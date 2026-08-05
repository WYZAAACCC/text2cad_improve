"""临时检查：第一梯队实现情况（design_id/fingerprint/family/labels/constraints/不可行样本）。"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
sys.path.insert(0, str(_HERE))

ok_all = True


def chk(name, cond, detail=""):
    global ok_all
    print(f"{name:42s}", "OK " if cond else "FAIL", detail)
    ok_all = ok_all and bool(cond)


def load(tid):
    p = OUTPUT / tid / "dataset_enrich.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ── 1. design_id 一致性：3 个同参数 verify 任务 ──
vids = ["verify_br_c735fc40", "verify_ds_7d530150", "verify_la_699ad04d"]
ds = [load(t) for t in vids]
chk("verify_* 3 任务都有 v2", all(d and d.get("schema") == "dataset_enrich_v2" for d in ds))
dids = {d["design_id"] for d in ds}
chk("verify_* design_id 相同（同参数捆绑）", len(dids) == 1, f"ids={len(dids)}")

# ── 2. fingerprint 语义：design_id 聚合 vs 指纹区分 ──
# 仅 verify_br 是 MBRep 实现后的新 run（有 output.brep）；verify_ds/la 为旧任务无 brep
br = load("verify_br_c735fc40")
chk("有 brep 的任务指纹非空", bool(br and br["b_rep_fingerprint"]))
chk("无 brep 旧任务 fingerprint=null",
    all(d["b_rep_fingerprint"] is None for d in ds if d and d.get("task_id") != "verify_br_c735fc40"))

# ── 3. family/design_id：G1-G5 系列 ──
g1 = load("mon_sweep_g1_baseline")
g5 = load("mon_sweep_g5_3tooth_depth")
chk("mon_sweep_g1 family=G1", g1 and g1["design_family_id"] == "G1", g1 and g1["design_family_id"])
chk("G5 design_id 有值（IR 测量兜底）",
    bool(g5 and g5["design_id"]), f"source={g5 and g5.get('design_vec_source')} family={g5 and g5['design_family_id']}")
# G5 需求 3 齿但实际生成 2 齿（失败模型），IR 测量兜底 → 匹配 G1，语义正确
chk("G5 兜底来源已标注", g5 and g5.get("design_vec_source") == "ir-measured")

# ── 4. labels/constraints 完整性 ──
d = load("verify_br_c735fc40")
chk("labels 完整", d["labels"] and d["labels"]["feasible"] and d["labels"]["slot_key_dims"] and d["labels"]["feature_counts"])
chk("constraints 3 适用 + 2 N/A", len(d["constraints"]) == 5
    and sum(1 for c in d["constraints"] if c.get("applicable")) == 3
    and sum(1 for c in d["constraints"] if not c.get("applicable")) == 2)

# ── 5. 旧任务兜底：mon_sweep_q2 无 request.json/brep ──
q2 = load("mon_sweep_q2_slots_96")
chk("mon_sweep_q2 design_id 有值（extracted 兜底）", bool(q2 and q2["design_id"]))
chk("mon_sweep_q2 fingerprint=null（无 brep）", q2 and q2["b_rep_fingerprint"] is None)

# ── 6. 不可行样本 ──
inf = json.loads((_HERE / "output" / "infeasible_samples.json").read_text(encoding="utf-8"))
chk("infeasible_samples 非空", inf["count"] > 0, f"count={inf['count']}")
chk("infeasible 有 error_code/evidence",
    all(s.get("error_code") and s.get("evidence") for s in inf["samples"]))

print("\nALL", "OK" if ok_all else "FAIL")
