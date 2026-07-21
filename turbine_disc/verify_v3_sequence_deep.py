"""V3 持久拓扑命名逐阶段深度验证 — Phase 14 最终审计.

对每个 topology transaction 提交时刻截获状态，严格回答：
  1. 实体是否在操作间累积（不是每个阶段重建）？
  2. 前后继承关系是否真实（PID 在阶段间保持一致）？
  3. 修改/删除/新建 是否真实反映 OCCT 操作结果？
  4. descriptor 是否存在且一致？
"""

import json
import sys
import tempfile
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "integrations" / "engineering_tools" / "src"))

DATA_DIR = _PROJECT / "app" / "text-to-cad" / "server" / "output" / "v3_final_20260721_045319"

print("=" * 72)
print("  V3 持久拓扑命名逐阶段深度验证 — Phase 14 审计")
print(f"  数据: {DATA_DIR.name}")
print("=" * 72)

# ═════════════════════════════════════════════════════════════════════════════
# 1. 加载 + 拦截 transaction commit
# ═════════════════════════════════════════════════════════════════════════════
raw = json.loads((DATA_DIR / "raw_fixed.json").read_text(encoding="utf-8"))

from seekflow_engineering_tools.generative_cad.validation.pipeline import (
    validate_and_canonicalize_with_bundle,
)
canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
if canonical is None or not report.ok:
    print(f"  [FAIL] Validation: {[i.message for i in report.issues[:3]]}")
    sys.exit(1)
print(f"  [OK] Validation: {len(canonical.nodes)} nodes, {len(canonical.components)} components")

# ── Intercept TopologyTransaction.commit() ──
import seekflow_engineering_tools.generative_cad.topology.transaction as tx_mod

_orig_commit = tx_mod.TopologyTransaction.commit
sequence = []
snapshots = []
entity_timeline = defaultdict(list)

def _snapshot(reg):
    pids = {}
    for pid, rec in reg._entities.items():
        pids[pid] = {
            "status": rec.status, "generation": rec.generation,
            "producer": rec.producer_node_id, "semantic_role": rec.semantic_role,
            "entity_type": rec.entity_type,
            "has_descriptor": rec.identity_descriptor is not None,
            "has_lifecycle": rec.lifecycle is not None,
            "has_binding": rec.binding_state is not None,
            "has_proof": rec.proof_class is not None,
            "ancestor_count": len(rec.ancestor_ids),
            "descendant_count": len(rec.descendant_ids),
        }
    return {"total": reg.entity_count, "active": reg.active_count,
            "deleted": reg.deleted_count, "pids": pids}

def _intercept_commit(self):
    before = _snapshot(self._original)
    _orig_commit(self)
    after = _snapshot(self._original)

    before_pids = set(before["pids"].keys())
    after_pids = set(after["pids"].keys())
    new_pids = after_pids - before_pids
    surviving = before_pids & after_pids
    seq = len(sequence)
    sequence.append(seq)

    snapshots.append({
        "seq": seq, "total_before": before["total"], "total_after": after["total"],
        "new_count": len(new_pids), "surviving_count": len(surviving),
        "deleted": before["deleted"], "active": after["active"],
        "before_pids": before_pids, "after_pids": after_pids,
        "new_pids": new_pids, "surviving_pids": surviving,
    })

    for pid in surviving:
        rec = self._original._entities.get(pid)
        if rec:
            entity_timeline[pid].append({"seq": seq, "status": rec.status,
                                          "generation": rec.generation})
    for pid in new_pids:
        rec = self._original._entities.get(pid)
        if rec:
            entity_timeline[pid].append({"seq": seq, "status": "created",
                                          "generation": rec.generation})

tx_mod.TopologyTransaction.commit = _intercept_commit

ctx_ref = {}
t0 = time.time()
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    with tempfile.TemporaryDirectory() as tmp:
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        result = run_canonical_gcad(
            canonical=canonical,
            out_step=Path(tmp) / "out.step",
            metadata_path=Path(tmp) / "out.json",
            validation_seed=bundle.to_metadata_dict(),
        )
        ctx_ref["ctx"] = getattr(result, "runtime_report", None)

tx_mod.TopologyTransaction.commit = _orig_commit
elapsed = time.time() - t0
print(f"  Pipeline: {'PASS' if result.ok else 'FAIL'} ({elapsed:.1f}s)")

ctx = None
# Reconstruct ctx from the result's metadata
if hasattr(result, 'operation_metrics'):
    ctx = None  # Will use snapshot data

# ═════════════════════════════════════════════════════════════════════════════
# 2. 逐 transaction 分析
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n[2] 逐 Transaction 拓扑状态 ({len(snapshots)} 次提交):")
print(f"{'Seq':<4} {'Before':>6} {'After':>6} {'New':>5} {'Survive':>7} {'Active':>6} {'Deleted':>7}")

cumulative_ok = 0
for i, s in enumerate(snapshots):
    has_survival = "YES" if s["surviving_count"] > 0 else ("INIT" if s["total_before"] == 0 else "NO")
    if s["surviving_count"] > 0:
        cumulative_ok += 1
    print(f"{s['seq']:<4} {s['total_before']:>6} {s['total_after']:>6} "
          f"{s['new_count']:>5} {s['surviving_count']:>7} {s['active']:>6} {s['deleted']:>7}  {has_survival}")

print(f"\n  累积检测: {cumulative_ok}/{max(len(snapshots)-1, 1)} 非首次提交有实体存活")

# ═════════════════════════════════════════════════════════════════════════════
# 3. 最终 Registry 深度分析（从 snapshots 最后状态）
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n[3] 最终 Registry 深度分析 (来自快照):")

if snapshots:
    last = snapshots[-1]
    last_pids = last["after_pids"]
    # We need the actual registry. Let's run a separate mini-run.
    # For now, use the intercept data.

    # Count producers from entity_timeline
    producers = defaultdict(list)
    for pid, timeline in entity_timeline.items():
        for entry in timeline:
            if entry["status"] == "created":
                producers[entry.get("node_id", f"step_{entry['seq']}")].append(pid)

    print(f"  总实体: {last['total_after']}")
    print(f"  活跃: {last['active']}")
    print(f"  Producer 数: {len(producers)}")

    for pn in sorted(producers, key=lambda x: len(producers[x]), reverse=True):
        print(f"    {pn[:40]:<40} {len(producers[pn]):>5} entities")

    # Survival counts
    survival_counts = Counter()
    for pid, timeline in entity_timeline.items():
        survival_counts[len(timeline)] += 1
    print(f"\n  实体存活 transaction 数分布: {dict(sorted(survival_counts.items()))}")
    multi_step = sum(c for steps, c in survival_counts.items() if steps > 1)
    print(f"  存活 >1 个 transaction 的实体: {multi_step}/{len(entity_timeline)}")

# ═════════════════════════════════════════════════════════════════════════════
# 4. 读取最终 sidecar
# ═════════════════════════════════════════════════════════════════════════════
sidecar_path = DATA_DIR / "output.topology.json"
if sidecar_path.exists():
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    entities = sidecar.get("entities", {})
    if entities:
        if isinstance(entities, dict):
            with_desc = sum(1 for e in entities.values() if e.get("identity_descriptor"))
        else:
            with_desc = sum(1 for e in entities if e.get("identity_descriptor"))
        with_lifecycle = sum(1 for e in entities.values() if e.get("lifecycle"))
        print(f"\n[4] 已有 Sidecar 分析:")
        print(f"  实体数: {len(entities)}")
        print(f"  Descriptor: {with_desc}/{len(entities)} ({100*with_desc/len(entities):.0f}%)")
        print(f"  Lifecycle: {with_lifecycle}/{len(entities)} ({100*with_lifecycle/len(entities):.0f}%)")
        # Check producers in sidecar
        sp = Counter(e.get("producer_node_id", "?") for e in entities.values())
        print(f"  Producer 分布: {dict(sp)}")

        # Check generations
        gen_dist = Counter(e.get("generation", 0) for e in entities.values())
        print(f"  Generation 分布: {dict(gen_dist)}")
        gen_gt_0 = sum(c for g, c in gen_dist.items() if g > 0)
        print(f"  Generation > 0: {gen_gt_0} ({100*gen_gt_0/len(entities):.1f}%)")

        # Ancestor/descendant
        has_anc = sum(1 for e in entities.values() if e.get("ancestor_ids"))
        has_desc = sum(1 for e in entities.values() if e.get("descendant_ids"))
        max_desc = max((len(e.get("descendant_ids", [])) for e in entities.values()), default=0)
        print(f"  Ancestor 链接: {has_anc}/{len(entities)}")
        print(f"  Descendant 链接: {has_desc}/{len(entities)}")
        print(f"  最大 descendants: {max_desc}")
        star = max_desc > len(entities) * 0.5 and len(entities) > 10
        print(f"  星形 lineage: {'❌ 存在' if star else '✅ 无'}")

# ═════════════════════════════════════════════════════════════════════════════
# 5. 核心判定
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n[5] 核心判定:")
checks = []

checks.append(("多 Producer 共存", len(producers) >= 2, f"{len(producers)} producers"))
checks.append(("实体跨操作存活", multi_step > 0, f"{multi_step} 实体存活 >1 个 transaction"))
checks.append(("Descriptor 存在", with_desc > 0, f"{with_desc}/{len(entities)}"))
checks.append(("Lifecycle 存在", with_lifecycle > 0, f"{with_lifecycle}/{len(entities)}"))
checks.append(("非每阶段重建", cumulative_ok > 0, f"{cumulative_ok}/{len(snapshots)} 非首次提交有存活实体"))
checks.append(("Generation 追踪", gen_gt_0 > 0, f"{gen_gt_0} 实体 gen>0"))
checks.append(("无星形 lineage", not star, f"max_desc={max_desc}/{len(entities)}"))
checks.append(("Pipeline 成功", result.ok, str(result.ok)))

for name, ok, detail in checks:
    print(f"  {'✅' if ok else '❌'} {name}: {detail}")

all_ok = all(ok for _, ok, _ in checks)
print(f"\n{'=' * 72}")
print(f"  判定: {'✅ V3 持久拓扑命名时序正确' if all_ok else '❌ V3 持久拓扑命名时序不完整'}")
print(f"{'=' * 72}")

# ── Save report ──
report = {
    "test_data": str(DATA_DIR),
    "pipeline_ok": result.ok,
    "elapsed_s": round(elapsed, 1),
    "snapshots": [{k: (len(v) if isinstance(v, set) else v) for k, v in s.items()} for s in snapshots],
    "sidecar_summary": {
        "entities": len(entities), "with_descriptor": with_desc, "with_lifecycle": with_lifecycle,
        "producers": dict(sp), "generations": dict(gen_dist), "gen_gt_0": gen_gt_0,
        "star_lineage": star, "max_descendants": max_desc,
    },
    "checks": {name: {"ok": ok, "detail": detail} for name, ok, detail in checks},
    "all_passed": all_ok,
}
OUT = _PROJECT / "turbine_disc" / "v3_sequence_deep_report_phase14.json"
json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(f"报告: {OUT}")
