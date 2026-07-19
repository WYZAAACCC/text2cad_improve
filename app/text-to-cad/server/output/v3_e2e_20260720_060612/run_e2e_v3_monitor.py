"""V3 Topology E2E Deep Monitor — 最新测试数据持久化拓扑命名全链路监控"""
import json, sys, time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations" / "engineering_tools" / "src"))

REF_DIR = Path(r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server\output\b572661c219c4952")
OUT_DIR = Path(__file__).resolve().parent / "test_topo_e2e_v3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 72)
print("  V3 持久拓扑命名全链路深度监控")
print("  HPT Turbine Disk — b572661c219c4952")
print("=" * 72)

# ═══════════════════════════════════════════════════════════════
# 1. IR 分析
# ═══════════════════════════════════════════════════════════════
raw = json.loads((REF_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
raw.setdefault("llm_validation_hints", {})
print(f"\n[1. IR分析] {raw['part_name']} | {len(raw['nodes'])} nodes | {raw['document_id']}")
for n in raw['nodes']:
    req = "REQ" if n.get('required', True) else "OPT"
    effects = []
    op = n['op']
    if 'revolve' in op or 'extrude' in op: effects.append("CREATES_SOLID")
    if 'cut' in op or 'boolean_cut' in op: effects.append("CUTS")
    if 'fillet' in op: effects.append("TREATMENT")
    print(f"  {n['id'][:30]:30s} {n['dialect']}.{op:25s} [{req}] {' '.join(effects)}")

# ═══════════════════════════════════════════════════════════════
# 2. 校验
# ═══════════════════════════════════════════════════════════════
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import run_validation
t0 = time.time()
run = run_validation(raw)
print(f"\n[2. 校验] ok={run.report.ok}, stage={run.report.stage}, {time.time()-t0:.1f}s")
assert run.canonical is not None, "Canonical must succeed"
canonical = run.canonical
print(f"  canonical_graph_hash: {canonical.canonical_graph_hash}")

# ═══════════════════════════════════════════════════════════════
# 3. 运行时 + 拓扑拦截
# ═══════════════════════════════════════════════════════════════
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod

_orig_apply = exec_mod._apply_topology_delta_if_present
topo_log = []
ctx_ref = {}

def _intercept(*, node, result, ctx, op_spec=None):
    before_count = ctx.topology_registry.entity_count
    _orig_apply(node=node, result=result, ctx=ctx, op_spec=op_spec)
    after_count = ctx.topology_registry.entity_count
    delta = result.topology_delta

    entry = {
        "node_id": node.id, "op": node.op, "dialect": node.dialect,
        "entities_before": before_count, "entities_after": after_count,
        "added": after_count - before_count,
        "has_delta": delta is not None,
        "provider": delta.history_provider if delta else "NONE",
        "relation_count": len(delta.relations) if delta else 0,
    }
    if delta and delta.relations:
        roles_sample = [r.semantic_role for r in delta.relations[:5] if r.semantic_role]
        entry["sample_roles"] = roles_sample[:3]
    topo_log.append(entry)
    if after_count > 0:
        ctx_ref['ctx'] = ctx

exec_mod._apply_topology_delta_if_present = _intercept

print(f"\n[3. 运行时] 构建几何体 + 拓扑命名...")
t0 = time.time()
result = run_canonical_gcad(
    canonical=canonical,
    out_step=OUT_DIR / "output.step",
    metadata_path=OUT_DIR / "output.metadata.json",
    validation_seed={"ok": True, "stage": "complete", "stages": {}},
)
elapsed = time.time() - t0
exec_mod._apply_topology_delta_if_present = _orig_apply

print(f"  Pipeline: {'OK' if result.ok else 'FAIL'}, {elapsed:.1f}s")
if result.warnings:
    topo_warnings = [w for w in result.warnings if 'topology' in w.lower()]
    print(f"  Topology warnings: {len(topo_warnings)}")
    for w in topo_warnings[:3]:
        print(f"    {w[:150]}")

# ═══════════════════════════════════════════════════════════════
# 4. 拓扑生产日志
# ═══════════════════════════════════════════════════════════════
print(f"\n[4. 拓扑生产日志]")
print(f"  {'Node':<30s} {'Op':<22s} {'+Ent':>5s} {'Delta':>5s} {'Provider':<30s} {'Relations':>5s} {'Sample Roles'}")
print(f"  {'-'*30} {'-'*22} {'-'*5} {'-'*5} {'-'*30} {'-'*5} {'-'*20}")
total_entities = 0
delta_ops = 0
no_delta_ops = 0
for e in topo_log:
    total_entities += e["added"]
    if e["has_delta"]: delta_ops += 1
    else: no_delta_ops += 1
    roles_str = ", ".join(e.get("sample_roles", [])[:2]) if e.get("sample_roles") else ""
    print(f"  {e['node_id'][:30]:30s} {e['op'][:22]:22s} {e['added']:5d} {str(e['has_delta']):5s} {e['provider'][:30]:30s} {e['relation_count']:5d} {roles_str}")
print(f"  TOTAL: {total_entities} entities | {delta_ops} ops with delta | {no_delta_ops} without")

# ═══════════════════════════════════════════════════════════════
# 5. Registry 状态
# ═══════════════════════════════════════════════════════════════
ctx = ctx_ref.get('ctx')
if not ctx:
    print("\n[5. Registry] NO TOPOLOGY DATA!")
    sys.exit(1)

reg = ctx.topology_registry

print(f"\n[5. Registry 状态]")
print(f"  总实体: {reg.entity_count}")
print(f"  Active: {reg.active_count} | Deleted: {reg.deleted_count} | Superseded: {reg.entity_count - reg.active_count - reg.deleted_count}")

integrity = reg.validate_integrity()
if integrity["ok"]:
    print(f"  完整性: [PASS] PASS")
else:
    print(f"  完整性: [FAIL] FAIL ({len(integrity['issues'])} issues)")
    for iss in integrity['issues'][:5]:
        print(f"    [{iss['code']}] {iss['message'][:120]}")

# ═══════════════════════════════════════════════════════════════
# 6. 按生产者分析
# ═══════════════════════════════════════════════════════════════
print(f"\n[6. 按操作分析]")
for nid in sorted(set(r.producer_node_id for r in reg._entities.values())):
    recs = [r for r in reg._entities.values() if r.producer_node_id == nid]
    statuses = Counter(r.status for r in recs)
    types = Counter(r.entity_type for r in recs)
    with_loc = sum(1 for r in recs if r.current_locator)
    with_v3 = sum(1 for r in recs if getattr(r, 'identity_descriptor', None))
    roles = list(set(r.semantic_role for r in recs))[:3]
    roles_str = ", ".join(roles)
    print(f"  {nid}: {len(recs)} entities [LOC={with_loc}, V3={with_v3}]")
    print(f"    Status: {dict(statuses)} | Types: {dict(types)}")
    print(f"    Roles: {roles_str}")

# ═══════════════════════════════════════════════════════════════
# 7. 全链路检查
# ═══════════════════════════════════════════════════════════════
print(f"\n[7. 全链路检查]")
active = [r for r in reg._entities.values() if r.status == "active"]
w_loc = sum(1 for r in active if r.current_locator)
w_v3 = sum(1 for r in active if getattr(r, 'identity_descriptor', None))
step_size = (OUT_DIR / "output.step").stat().st_size / 1e6 if (OUT_DIR / "output.step").exists() else 0

checks = [
    ("Registry 有实体", reg.entity_count > 0),
    ("有 Active 实体", len(active) > 0),
    ("有 Locator 绑定", w_loc > 0),
    ("有 V3 Descriptor", w_v3 > 0),
    ("完整性检查通过", integrity["ok"]),
    ("STEP 文件生成", step_size > 0),
    ("Pipeline 成功", result.ok),
]

all_ok = True
for name, ok in checks:
    mark = "[PASS]" if ok else "[FAIL]"
    if not ok: all_ok = False
    print(f"  {mark} {name}")

print(f"\n  Active: {len(active)} ({w_loc} LOC, {w_v3} V3)")
print(f"  STEP: {step_size:.1f}MB | Pipeline: {elapsed:.1f}s")
print(f"  => {'[PASS] ALL CHECKS PASSED' if all_ok else '[FAIL] ISSUES FOUND'}")

print(f"\n{'='*72}")
print(f"  监控完成")
print(f"{'='*72}")
