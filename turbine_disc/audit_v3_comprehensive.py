"""V3 持久拓扑命名全面审计 — 时序正确性与继承关系验证."""
import json, sys, tempfile, warnings
from pathlib import Path
from collections import defaultdict, Counter

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "integrations" / "engineering_tools" / "src"))
DATA_DIR = _PROJECT / "app" / "text-to-cad" / "server" / "output" / "v3_final_20260721_045319"
raw = json.loads((DATA_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)

# ======== Run pipeline twice: once to capture lifecycle, once for final registry ========

# Run 1: capture per-transaction snapshots
import seekflow_engineering_tools.generative_cad.topology.transaction as tx_mod
_orig_commit = tx_mod.TopologyTransaction.commit

entity_lifecycle = defaultdict(list)
seq_snapshots = []

def _intercept_commit(self):
    staged = self._staged
    before = {}
    for pid, rec in staged._entities.items():
        before[pid] = {
            "status": rec.status, "generation": rec.generation,
            "producer": rec.producer_node_id, "entity_type": rec.entity_type,
            "semantic_role": rec.semantic_role, "has_locator": rec.current_locator is not None,
            "has_descriptor": rec.identity_descriptor is not None,
            "anc_count": len(rec.ancestor_ids), "desc_count": len(rec.descendant_ids),
            "owner_body": rec.owner_body_handle_id,
        }
    seq_snapshots.append(before)
    _orig_commit(self)
    for pid, rec in self._original._entities.items():
        entity_lifecycle[pid].append({
            "seq": len(seq_snapshots) - 1, "status": rec.status,
            "generation": rec.generation, "producer": rec.producer_node_id,
        })

tx_mod.TopologyTransaction.commit = _intercept_commit

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    with tempfile.TemporaryDirectory() as tmp:
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        result = run_canonical_gcad(
            canonical=canonical, out_step=Path(tmp)/"out.step",
            metadata_path=Path(tmp)/"out.json", validation_seed=bundle.to_metadata_dict(),
        )

tx_mod.TopologyTransaction.commit = _orig_commit

# Run 2: get clean final registry
final_reg = []
def _cap2(self):
    _orig_commit(self)
    final_reg.append(self._original)
tx_mod.TopologyTransaction.commit = _cap2

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    with tempfile.TemporaryDirectory() as tmp:
        result2 = run_canonical_gcad(
            canonical=canonical, out_step=Path(tmp)/"out.step",
            metadata_path=Path(tmp)/"out.json", validation_seed=bundle.to_metadata_dict(),
        )
tx_mod.TopologyTransaction.commit = _orig_commit

reg = final_reg[-1]

# ======== 1. Transaction 序列分析 ========
print("=" * 60)
print("1. Transaction 序列分析")
print("=" * 60)
for i, snap in enumerate(seq_snapshots):
    active = sum(1 for v in snap.values() if v["status"] == "active")
    deleted = sum(1 for v in snap.values() if v["status"] == "deleted")
    with_loc = sum(1 for v in snap.values() if v["has_locator"])
    producers = Counter(v["producer"] for v in snap.values())
    print(f"  Seq {i}: {len(snap)} entities ({active} active, {deleted} deleted, {with_loc} locator)")
    for pn, cnt in producers.most_common():
        print(f"    producer={pn}: {cnt}")

# ======== 2. 实体跨操作存活分析 ========
print()
print("=" * 60)
print("2. PID 跨阶段一致性 — 是否每阶段重建？")
print("=" * 60)
multi_seq = {pid: events for pid, events in entity_lifecycle.items() if len(events) > 1}
single_seq = {pid: events for pid, events in entity_lifecycle.items() if len(events) == 1}
print(f"  跨阶段存活实体 (>1 transaction): {len(multi_seq)}")
print(f"  仅存在于单阶段: {len(single_seq)}")
print(f"  总实体: {len(entity_lifecycle)}")

if multi_seq:
    # Show a surviving entity
    sample = list(multi_seq.items())[0]
    print(f"\n  示例存活实体 PID={sample[0][:60]}...")
    for evt in sample[1]:
        print(f"    seq={evt['seq']} status={evt['status']} gen={evt['generation']} producer={evt['producer']}")

# Check: do entities created in seq 0 survive to seq 2?
seq0_pids = set()
for pid, events in entity_lifecycle.items():
    if events[0]["seq"] == 0:
        seq0_pids.add(pid)
seq2_pids = set()
for pid, events in entity_lifecycle.items():
    for evt in events:
        if evt["seq"] == max(s["seq"] for s in entity_lifecycle[pid]):
            seq2_pids.add(pid)
survivors = seq0_pids & set(multi_seq.keys())
print(f"  Seq 0 中创建并在后续存活的实体: {len(survivors)}")

# ======== 3. Generation 验证 ========
print()
print("=" * 60)
print("3. Generation 验证 — 是否反映真实操作数？")
print("=" * 60)
gen_counts = Counter()
for pid, events in entity_lifecycle.items():
    max_gen = max(e["generation"] for e in events)
    gen_counts[max_gen] += 1
print(f"  Generation 分布: {dict(sorted(gen_counts.items()))}")

gen_bad = sum(1 for pid, events in multi_seq.items()
              if max(e["generation"] for e in events) == 0)
first_gen_bad = sum(1 for events in entity_lifecycle.values()
                    if events[0]["generation"] != 0)
print(f"  跨阶段存活但 gen=0: {gen_bad} (应为 0)")
print(f"  首现但 gen!=0: {first_gen_bad} (应为 0)")

# ======== 4. feature_stable_id 验证 ========
print()
print("=" * 60)
print("4. feature_stable_id — 是否使用设计身份？")
print("=" * 60)
fid_ok = 0; fid_bad = 0; fid_none = 0
for pid, rec in reg._entities.items():
    if not pid.startswith("gct3_"): continue
    if not rec.identity_descriptor:
        fid_none += 1; continue
    fsid = rec.identity_descriptor.get("feature_stable_id", "")
    if fsid and fsid != rec.producer_node_id:
        fid_ok += 1
    else:
        fid_bad += 1
total = fid_ok + fid_bad + fid_none
print(f"  feature_stable_id != producer_node_id (正确): {fid_ok}/{total} ({100*fid_ok/max(total,1):.1f}%)")
print(f"  feature_stable_id == producer_node_id (未更新): {fid_bad}/{total} ({100*fid_bad/max(total,1):.1f}%)")
if fid_bad > 0:
    samples = [(pid, rec) for pid, rec in reg._entities.items()
               if pid.startswith("gct3_") and rec.identity_descriptor
               and rec.identity_descriptor.get("feature_stable_id","") == rec.producer_node_id][:3]
    print(f"  仍使用 producer_node_id 的示例:")
    for pid, rec in samples:
        print(f"    producer={rec.producer_node_id} role={rec.semantic_role}")

# ======== 5. Lineage 验证 ========
print()
print("=" * 60)
print("5. Lineage 验证 — 祖先/后代关系是否正确？")
print("=" * 60)
bidir_ok = 0; bidir_bad = 0
for pid, rec in reg._entities.items():
    for aid in rec.ancestor_ids:
        anc = reg._entities.get(aid)
        if anc is None or pid not in anc.descendant_ids:
            bidir_bad += 1
        else:
            bidir_ok += 1
    for did in rec.descendant_ids:
        desc = reg._entities.get(did)
        if desc is None or pid not in desc.ancestor_ids:
            bidir_bad += 1
        else:
            bidir_ok += 1
print(f"  双向一致: {bidir_ok}, 不一致/断裂: {bidir_bad}")

# Check ancestors are always from earlier producers
producer_order = {}
for i, pn in enumerate(sorted(set(r.producer_node_id for r in reg._entities.values()))):
    producer_order[pn] = i
anc_time_bad = 0
for pid, rec in reg._entities.items():
    for aid in rec.ancestor_ids:
        anc = reg._entities.get(aid)
        if anc and producer_order.get(anc.producer_node_id, 999) > producer_order.get(rec.producer_node_id, 0):
            anc_time_bad += 1
print(f"  祖先来自更晚操作的时序错误: {anc_time_bad} (应为 0)")

# Show lineage sample
with_anc = [(pid, rec) for pid, rec in reg._entities.items() if rec.ancestor_ids]
with_desc = [(pid, rec) for pid, rec in reg._entities.items() if rec.descendant_ids]
if with_anc and with_desc:
    print(f"\n  Lineage 示例:")
    child = with_anc[0]
    print(f"    子实体: producer={child[1].producer_node_id} role={child[1].semantic_role[:40]} anc_count={len(child[1].ancestor_ids)}")
    for aid in child[1].ancestor_ids[:2]:
        anc = reg._entities.get(aid)
        if anc:
            print(f"      祖先: producer={anc.producer_node_id} role={anc.semantic_role[:40]} gen={anc.generation} desc_count={len(anc.descendant_ids)}")

# ======== 6. 核心判定 ========
print()
print("=" * 60)
print("6. 核心判定")
print("=" * 60)
checks = [
    ("跨阶段 PID 保持一致(非每阶段重建)", len(multi_seq) > 0, f"{len(multi_seq)} 存活"),
    ("存活实体 generation > 0", gen_bad == 0, f"{gen_bad} gen=0"),
    ("首现实体 generation = 0", first_gen_bad == 0, f"{first_gen_bad} gen!=0"),
    ("feature_stable_id 正确", fid_ok > fid_bad, f"{100*fid_ok/max(total,1):.0f}%"),
    ("Lineage 双向一致", bidir_bad == 0, f"{bidir_bad} 断裂"),
    ("Lineage 时序正确", anc_time_bad == 0, f"{anc_time_bad} 错序"),
]
for name, ok, detail in checks:
    print(f"  {'✅' if ok else '❌'} {name}: {detail}")
print()
all_ok = all(ok for _, ok, _ in checks)
print(f"  {'✅ V3 持久拓扑命名基本正确' if all_ok else '❌ V3 持久拓扑命名仍有问题'}")
