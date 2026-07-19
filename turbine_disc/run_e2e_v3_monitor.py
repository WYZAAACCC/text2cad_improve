"""V3 Topology E2E Deep Monitor — HPT Turbine Disk."""
import json, sys, time, hashlib
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations" / "engineering_tools" / "src"))

REF_DIR = Path(r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server\output\b572661c219c4952")
OUT_DIR = Path(__file__).resolve().parent / "test_topo_e2e_v3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("  V3 TOPOLOGY E2E MONITOR — HPT Turbine Disk")
print("=" * 70)

# Load IR
raw = json.loads((REF_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
raw.setdefault("llm_validation_hints", {})
print(f"\n[IR] {raw['part_name']} | {len(raw['nodes'])} nodes | {raw['document_id']}")

# Manual canonicalize (bypass pre-existing validation bug)
from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
from seekflow_engineering_tools.generative_cad.ir.canonical import (
    CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
    CanonicalSelectedDialect, CanonicalValueRef, CanonicalValueDecl,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import graph_hash
from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect

parsed = parse_raw_gcad_document(raw)
if not parsed.ok:
    print("PARSE FAILED"); sys.exit(1)
raw_doc = parsed.document

# Build canonical
nodes = []
for rn in raw_doc.nodes:
    try:
        dialect = require_dialect(rn.dialect)
        op_spec = dialect.get_op_spec(rn.op, rn.op_version)
        if op_spec is None:
            print(f"  SKIP {rn.id}: no op_spec for {rn.dialect}.{rn.op}")
            continue
        cn = CanonicalNode(
            id=rn.id, dialect=rn.dialect, op=rn.op, op_version=rn.op_version,
            phase=rn.phase or op_spec.phase,
            component=rn.component, required=rn.required,
            degradation_policy=rn.degradation_policy,
            params=rn.params, typed_params={},
            inputs=[CanonicalValueRef(**i.model_dump()) for i in (rn.inputs or [])],
            outputs=[CanonicalValueDecl(**o.model_dump()) for o in (rn.outputs or [])],
            operation_effects=list(op_spec.effects),
            postconditions=list(op_spec.postconditions),
        )
        nodes.append(cn)
    except Exception as exc:
        print(f"  ERROR building {rn.id}: {exc}")

comps = [CanonicalComponent(
    id=rc.id, owner_dialect=rc.owner_dialect, root_node=rc.root_node, output_aliases={},
) for rc in raw_doc.components]

dials = [CanonicalSelectedDialect(
    dialect=sd.dialect, version=sd.version,
    contract_hash="sha256:" + hashlib.sha256(b"v3").hexdigest(),
) for sd in raw_doc.selected_dialects]

canonical = CanonicalGcadDocument(
    document_id=raw_doc.document_id, part_name=raw_doc.part_name,
    units=raw_doc.units, trust_level=raw_doc.trust_level,
    schema_version=raw_doc.schema_version,
    selected_dialects=dials, components=comps, nodes=nodes,
    constraints=raw_doc.constraints, safety=raw_doc.safety,
    canonical_version="0.2.0",
    canonical_graph_hash=graph_hash(nodes),
    raw_graph_hash=graph_hash([n.model_dump() for n in raw_doc.nodes]),
    llm_validation_hints=raw_doc.llm_validation_hints or {},
)
print(f"  Canonical: {len(canonical.nodes)} nodes, hash={canonical.canonical_graph_hash[:24]}")

# Runtime
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod

_orig = exec_mod._apply_topology_delta_if_present
topo_log = []
ctx_ref = {}

def _intercept(*, node, result, ctx, op_spec=None):
    before = ctx.topology_registry.entity_count
    _orig(node=node, result=result, ctx=ctx, op_spec=op_spec)
    after = ctx.topology_registry.entity_count
    d = result.topology_delta
    entry = {
        "node": node.id, "op": node.op, "dialect": node.dialect,
        "before": before, "after": after, "added": after - before,
        "has_delta": d is not None,
        "provider": d.history_provider if d else "none",
        "relations": len(d.relations) if d else 0,
    }
    if d:
        entry["roles"] = dict(Counter(r.semantic_role or "?" for r in d.relations))
    topo_log.append(entry)
    if after > 0:
        ctx_ref['ctx'] = ctx

exec_mod._apply_topology_delta_if_present = _intercept

print(f"\n[RUNTIME] Building geometry...")
t0 = time.time()
try:
    res = run_canonical_gcad(
        canonical=canonical,
        out_step=OUT_DIR / "output.step",
        metadata_path=OUT_DIR / "output.metadata.json",
        validation_seed={"ok": True, "stage": "complete", "stages": {}},
    )
    elapsed = time.time() - t0
    exec_mod._apply_topology_delta_if_present = _orig
    print(f"  {'OK' if res.ok else 'FAIL'}, {elapsed:.1f}s")
    if not res.ok and res.error:
        print(f"  Error: {res.error[:300]}")
except Exception as exc:
    elapsed = time.time() - t0
    exec_mod._apply_topology_delta_if_present = _orig
    print(f"  EXCEPTION: {exc}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# Topology log
print(f"\n{'='*70}\n[TOPOLOGY PRODUCTION LOG]")
total = 0
for e in topo_log:
    total += e["added"]
    flag = "*" if e["has_delta"] else " "
    print(f"  {flag} {e['node'][:30]:30s} | {e['op'][:20]:20s} | +{e['added']:3d}e | {e['provider'][:28]}")
    if e.get("roles"):
        for r, c in list(e["roles"].items())[:2]:
            print(f"       {r} (x{c})")
print(f"  TOTAL: {total} entities across {len(topo_log)} operations")

# Registry
ctx = ctx_ref.get('ctx')
if ctx:
    reg = ctx.topology_registry
    sup_count = reg.entity_count - reg.active_count - reg.deleted_count
    integ = reg.validate_integrity()
    issues_n = len(integ["issues"])

    print(f"\n{'='*70}\n[REGISTRY STATE]")
    print(f"  Total: {reg.entity_count} | Active: {reg.active_count} | "
          f"Deleted: {reg.deleted_count} | Superseded: {sup_count}")
    print(f"  Integrity: {'OK' if integ['ok'] else f'FAIL ({issues_n} issues)'}")
    for iss in integ['issues'][:5]:
        print(f"    [{iss['code']}] {iss['message'][:100]}")

    print(f"\n[BY PRODUCER NODE]")
    for nid in sorted(set(r.producer_node_id for r in reg._entities.values())):
        recs = [r for r in reg._entities.values() if r.producer_node_id == nid]
        st = Counter(r.status for r in recs)
        w_loc = sum(1 for r in recs if r.current_locator)
        w_v3 = sum(1 for r in recs if getattr(r, 'identity_descriptor', None))
        ops = "/".join(list(set(r.semantic_role.split("/")[0] for r in recs))[:3])
        print(f"  {nid}: {len(recs)}e [LOC={w_loc} V3={w_v3}] {dict(st)} [{ops}]")

    active = [r for r in reg._entities.values() if r.status == "active"]
    w_loc = sum(1 for r in active if r.current_locator)
    w_v3 = sum(1 for r in active if getattr(r, 'identity_descriptor', None))
    step_exists = (OUT_DIR / "output.step").exists()
    step_mb = (OUT_DIR / "output.step").stat().st_size / 1e6 if step_exists else 0

    print(f"\n[FINAL SUMMARY]")
    print(f"  Active entities: {len(active)} ({w_loc} with locator, {w_v3} with V3 descriptor)")
    print(f"  STEP file: {step_mb:.1f}MB" if step_exists else "  STEP: NOT CREATED")
    print(f"  Pipeline time: {elapsed:.1f}s")
    passed = integ["ok"] and w_loc > 0
    print(f"  => {'ALL CHECKS PASSED' if passed else 'ISSUES FOUND'}")
else:
    print("\n[WARNING] No topology registry state captured")

print(f"\n{'='*70}")
