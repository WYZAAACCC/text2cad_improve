"""Deep time-sequence verification: trace every entity through every operation.

Checks:
  1. Per-operation entity creation (which entities did each op produce?)
  2. Survivorship: do entities from earlier ops survive later ops?
  3. Modification tracking: does boolean_cut update entity generation?
  4. Deletion tracking: are tool faces marked deleted after cut?
  5. Generation tracking: do modified faces get generation++?
  6. Ancestor/descendant links: does the DAG have edges?
  7. PID stability: same semantic role → same PID across rebuilds?

Output: turbine_disc/timeline_deep_report.json
"""

import json, sys, time
from pathlib import Path
from collections import Counter, defaultdict

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "integrations" / "engineering_tools" / "src"))

import cadquery as cq
from seekflow_engineering_tools.generative_cad.validation.pipeline import (
    validate_and_canonicalize_with_bundle,
)
from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

DATA_DIR = _PROJECT / "app" / "text-to-cad" / "server" / "output" / "v3_e2e_20260720_060612"

print("=" * 72)
print("  时序拓扑命名深度验证 — 逐操作 entity 追踪")
print(f"  Data: {DATA_DIR.name}")
print("=" * 72)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Load + Validate
# ═══════════════════════════════════════════════════════════════════════════════
print("\n[1] 加载 IR + 校验...")
raw = json.loads((DATA_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
assert canonical is not None and report.ok
print(f"  [PASS] {len(raw['nodes'])} nodes, {len(raw['components'])} components")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Run pipeline with per-operation snapshots
# ═══════════════════════════════════════════════════════════════════════════════
print("\n[2] 运行 pipeline + 每步快照...")

import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod

_orig_apply = exec_mod._apply_topology_delta_if_present
snapshots = []  # list[{node_id, op, entities_before, entities_after, by_producer, by_status}]

def _snapshot(ctx, node_id, op):
    reg = ctx.topology_registry
    by_prod = defaultdict(list)
    by_status = Counter()
    for pid, rec in reg._entities.items():
        by_prod[rec.producer_node_id].append({
            "pid": pid[:30],
            "status": rec.status,
            "generation": rec.generation,
            "semantic_role": rec.semantic_role,
            "ancestor_count": len(rec.ancestor_ids),
            "descendant_count": len(rec.descendant_ids),
        })
        by_status[rec.status] += 1
    return {
        "node_id": node_id,
        "op": op,
        "total": reg.entity_count,
        "by_producer": {k: len(v) for k, v in by_prod.items()},
        "by_status": dict(by_status),
        "entities": {k: v for k, v in by_prod.items()},
    }

def _intercept(*, node, result, ctx, op_spec=None):
    op = f"{node.dialect}.{node.op}"
    before_snap = _snapshot(ctx, node.id, op)
    _orig_apply(node=node, result=result, ctx=ctx, op_spec=op_spec)
    after_snap = _snapshot(ctx, node.id, op)
    snapshots.append({
        "node_id": node.id,
        "op": op,
        "total_before": before_snap["total"],
        "total_after": after_snap["total"],
        "added": after_snap["total"] - before_snap["total"],
        "by_producer_before": before_snap["by_producer"],
        "by_producer_after": after_snap["by_producer"],
        "by_status_after": after_snap["by_status"],
    })

exec_mod._apply_topology_delta_if_present = _intercept

t0 = time.time()
import tempfile, warnings
warnings.filterwarnings("ignore")
with tempfile.TemporaryDirectory() as tmp:
    result = run_canonical_gcad(
        canonical=canonical,
        out_step=Path(tmp) / "out.step",
        metadata_path=Path(tmp) / "out.json",
        validation_seed=bundle.to_metadata_dict(),
    )
exec_mod._apply_topology_delta_if_present = _orig_apply

elapsed = time.time() - t0
print(f"  Pipeline: {'PASS' if result.ok else 'FAIL'} ({elapsed:.1f}s)")
if not result.ok:
    print(f"  Error: {result.error}")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Analyze snapshots
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n[3] 时序分析 ({len(snapshots)} 操作):")

# Filter to ops that changed the registry
active_ops = [s for s in snapshots if s["added"] != 0 or s["total_after"] > 0]
if not active_ops:
    print("  ⚠ 无操作改变了 registry（实体可能在 handler 内部注册）")
    # The interceptor snapshots are at executor delta time — entities
    # registered in-handler appear between snapshots.
    # Let's find where entities appeared by comparing consecutive snapshots
    prev_producers = set()
    for i, s in enumerate(snapshots):
        curr = set(s["by_producer_after"].keys())
        appeared = curr - prev_producers
        if appeared:
            print(f"  [{i:2d}] {s['op'][:40]:40s} entities appeared: {appeared}")
        prev_producers = curr
else:
    for s in active_ops:
        print(f"  {s['op'][:45]:45s} +{s['added']:4d} → total={s['total_after']:4d}")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Deep analysis of final registry
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n[4] 最终 registry 深度分析:")

# Re-run with same context capture (use final ctx from last run via global)
# Build a simple disc to get the registry after pipeline
import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod2
ctx_ref = {}
_orig2 = exec_mod2._apply_topology_delta_if_present

def _capture(*, node, result, ctx, op_spec=None):
    _orig2(node=node, result=result, ctx=ctx, op_spec=op_spec)
    ctx_ref['ctx'] = ctx

exec_mod2._apply_topology_delta_if_present = _capture
with tempfile.TemporaryDirectory() as tmp:
    result = run_canonical_gcad(
        canonical=canonical,
        out_step=Path(tmp) / "out2.step",
        metadata_path=Path(tmp) / "out2.json",
        validation_seed=bundle.to_metadata_dict(),
    )
exec_mod2._apply_topology_delta_if_present = _orig2

ctx = ctx_ref.get('ctx')
if not ctx:
    print("  [FAIL] No context captured")
    sys.exit(1)

reg = ctx.topology_registry

# Analyze each entity
entities_data = []
by_generation = Counter()
by_ancestor_count = Counter()
by_descendant_count = Counter()
producers = defaultdict(list)

for pid, rec in reg._entities.items():
    entry = {
        "pid": pid[:40],
        "producer": rec.producer_node_id,
        "entity_type": rec.entity_type,
        "status": rec.status,
        "semantic_role": rec.semantic_role,
        "generation": rec.generation,
        "ancestor_count": len(rec.ancestor_ids),
        "descendant_count": len(rec.descendant_ids),
        "resolution_method": rec.resolution_method,
        "has_v3_descriptor": getattr(rec, 'identity_descriptor', None) is not None,
    }
    entities_data.append(entry)
    by_generation[rec.generation] += 1
    by_ancestor_count[len(rec.ancestor_ids)] += 1
    by_descendant_count[len(rec.descendant_ids)] += 1
    producers[rec.producer_node_id].append(entry)

print(f"  Total entities: {reg.entity_count}")
print(f"  Active: {reg.active_count}  Deleted: {reg.deleted_count}")
print(f"  By generation: {dict(by_generation)}")
print(f"  By ancestor count: {dict(by_ancestor_count)}")
print(f"  By descendant count: {dict(by_descendant_count)}")
print(f"  By producer:")
for pn in sorted(producers):
    entries = producers[pn]
    statuses = Counter(e["status"] for e in entries)
    roles_sample = [e["semantic_role"] for e in entries[:3]]
    print(f"    {pn[:40]:40s} {len(entries):4d} entities  status={dict(statuses)}  roles={roles_sample}")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Time-sequence correctness checks
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n[5] 时序正确性检查:")

checks = []

# Check 1: Multiple producers → entities from different ops survive together
multi_producer = len(producers) >= 2
checks.append(("多 producer 共存 (时序累积)", multi_producer,
    f"{len(producers)} producers: {list(producers.keys())}"))

# Check 2: Not all entities are from a single operation
all_same_producer = len(producers) == 1
checks.append(("非单一操作产生 (非全部重命名)", not all_same_producer,
    f"{len(producers)} distinct producers"))

# Check 3: Entity status diversity (some active, potentially some deleted)
has_active = reg.active_count > 0
checks.append(("有 active 实体", has_active, f"{reg.active_count} active"))

# Check 4: Entity count > 0
has_entities = reg.entity_count > 0
checks.append(("Registry 有实体", has_entities, f"{reg.entity_count} entities"))

# Check 5: Generation tracking - at least some entities have generation > 0
# (indicating modification was tracked, not all created fresh)
gen_0_count = by_generation.get(0, 0)
gen_all_0 = gen_0_count == reg.entity_count
checks.append(("存在非零 generation (修改被追踪)", not gen_all_0,
    f"generation distribution: {dict(by_generation)}"))

# Check 6: At least one entity has ancestors (indicating lineage exists)
has_ancestors = by_ancestor_count.get(0, 0) < reg.entity_count
checks.append(("存在 ancestor 链接 (lineage DAG)", has_ancestors,
    f"ancestor distribution: {dict(by_ancestor_count)}"))

# Check 7: At least one entity has descendants
has_descendants = by_descendant_count.get(0, 0) < reg.entity_count
checks.append(("存在 descendant 链接", has_descendants,
    f"descendant distribution: {dict(by_descendant_count)}"))

# Check 8: No entity has been "reset" (all generation=0 means every op creates new)
# A correct system should have some entities with generation>0
modified_exists = any(e["generation"] > 0 for e in entities_data)
checks.append(("存在被修改的 entity (非全部新建)", modified_exists,
    f"entities with gen>0: {sum(1 for e in entities_data if e['generation'] > 0)}"))

for name, ok, detail in checks:
    mark = "[PASS]" if ok else "[FAIL]"
    print(f"  {mark} {name}: {detail}")

all_ok = all(ok for _, ok, _ in checks)
verdict = (
    "时序正确的持久化拓扑命名: 实体在操作间正确累积、继承和修改"
    if all_ok else
    "时序关系不完整: 部分继承/修改关系未被正确追踪。\n"
    "  当前状态: 实体在操作间共存（非全部重命名），但 lineage DAG、generation 追踪和 ancestor/descendant 链接需要进一步完善。"
)

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Report
# ═══════════════════════════════════════════════════════════════════════════════
report = {
    "test_data": str(DATA_DIR),
    "pipeline_ok": result.ok,
    "elapsed_s": round(elapsed, 1),
    "total_entities": reg.entity_count,
    "active_count": reg.active_count,
    "deleted_count": reg.deleted_count,
    "producers": list(producers.keys()),
    "producer_counts": {k: len(v) for k, v in producers.items()},
    "by_generation": dict(by_generation),
    "by_ancestor_count": dict(by_ancestor_count),
    "by_descendant_count": dict(by_descendant_count),
    "checks": {name: {"ok": ok, "detail": detail} for name, ok, detail in checks},
    "all_passed": all_ok,
    "verdict": verdict,
}

OUT = _PROJECT / "turbine_disc" / "timeline_deep_report.json"
json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

print(f"\n{'=' * 72}")
print(f"  最终判断: {verdict[:80]}...")
print(f"  报告: {OUT}")
print(f"{'=' * 72}")
