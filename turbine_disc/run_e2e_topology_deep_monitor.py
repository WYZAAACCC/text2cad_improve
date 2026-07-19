"""E2E topology deep monitor test — turbine disk full pipeline with topology auditing."""
import json, sys, time, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations" / "engineering_tools" / "src"))

# Use latest test IR
REF_DIR = Path("app/text-to-cad/server/output/fd4658e7d3044f07")
OUT_DIR = Path(__file__).resolve().parent / "test_topology_deep_monitor"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("  TOPOLOGY DEEP MONITOR — Turbine Disk E2E")
print(f"  Reference: {REF_DIR}")
print("=" * 70)

# ── Load IR ──
raw = json.loads((REF_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
if raw.get("llm_validation_hints") is None:
    raw["llm_validation_hints"] = {}
raw["llm_validation_hints"] = raw.get("llm_validation_hints", {}) or {}

print(f"\n{'='*70}")
print(f"  1. IR ANALYSIS")
print(f"{'='*70}")
print(f"  Part: {raw['part_name']}")
print(f"  Nodes: {len(raw['nodes'])}")
print(f"  Document ID: {raw.get('document_id', 'N/A')}")
print(f"  Dialects: {[d['dialect'] for d in raw.get('selected_dialects', [])]}")

# Count operations by type
from collections import Counter
op_counts = Counter(n['op'] for n in raw['nodes'])
print(f"  Operations: {dict(op_counts)}")

for n in raw['nodes']:
    effects = []
    op = n['op']
    if 'extrude' in op or 'revolve' in op: effects.append('CREATES_SOLID')
    if 'cut' in op or 'hole' in op: effects.append('CUTS_MATERIAL')
    if 'boolean' in op: effects.append('BOOLEAN')
    if 'fillet' in op or 'chamfer' in op: effects.append('EDGE_TREATMENT')
    if 'pattern' in op: effects.append('PATTERN')
    print(f"    {n['id']}: {n['dialect']}.{op} {'[required]' if n.get('required', True) else '[optional]'} {' '.join(effects)}")

# ── Validation ──
print(f"\n{'='*70}")
print(f"  2. VALIDATION")
print(f"{'='*70}")
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import run_validation
t0 = time.time()
run = run_validation(raw)
print(f"  ok={run.report.ok}, stage={run.report.stage}, time={time.time()-t0:.1f}s")
print(f"  Issues: {len(run.report.issues)} total")

# Topology-specific issues
topo_issues = [i for i in run.report.issues if 'TOPOLOGY' in i.code or 'topology' in i.code.lower()]
print(f"  Topology issues: {len(topo_issues)}")
for iss in topo_issues[:10]:
    print(f"    [{iss.severity}] {iss.code}: {iss.message[:100]}")

topo_rules = [r for r in run.execution_records if 'topology' in r.rule_id]
print(f"  Topology rules executed: {len(topo_rules)}")
for r in topo_rules:
    print(f"    {r.rule_id}: status={r.status}, issues={r.issue_count}")

if run.canonical is None:
    print("  FAILED — cannot proceed to runtime")
    sys.exit(1)
print(f"  canonical_graph_hash: {run.canonical.canonical_graph_hash[:24]}...")
print(f"  document_id: {run.canonical.document_id}")

# ── Runtime with deep topology interceptor ──
print(f"\n{'='*70}")
print(f"  3. RUNTIME EXECUTION (deep topology interceptor)")
print(f"{'='*70}")

from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod

_orig_apply = exec_mod._apply_topology_delta_if_present
topo_log = []

def _intercept(*, node, result, ctx):
    before = ctx.topology_registry.entity_count
    active_before = ctx.topology_registry.active_count
    deleted_before = ctx.topology_registry.deleted_count

    # Run original
    _orig_apply(node=node, result=result, ctx=ctx)

    after = ctx.topology_registry.entity_count
    active_after = ctx.topology_registry.active_count
    deleted_after = ctx.topology_registry.deleted_count

    # Collect per-entity samples
    entity_samples = []
    for pid, rec in list(ctx.topology_registry._entities.items()):
        if rec.producer_node_id == node.id:
            entity_samples.append({
                "pid": pid[:40] + "...",
                "role": rec.semantic_role,
                "type": rec.entity_type,
                "status": rec.status,
                "gen": rec.generation,
                "has_locator": rec.current_locator is not None,
            })

    delta = result.topology_delta
    topo_log.append({
        "node": node.id,
        "op": node.op,
        "dialect": node.dialect,
        "has_delta": delta is not None,
        "relations": len(delta.relations) if delta else 0,
        "provider": delta.history_provider if delta else "none",
        "entities_before": before, "entities_after": after,
        "active_before": active_before, "active_after": active_after,
        "deleted_before": deleted_before, "deleted_after": deleted_after,
        "samples": entity_samples[:5],
    })

exec_mod._apply_topology_delta_if_present = _intercept

t0 = time.time()
result = run_canonical_gcad(
    canonical=run.canonical,
    out_step=OUT_DIR / "output.step",
    metadata_path=OUT_DIR / "output.metadata.json",
    validation_seed={"ok": True, "stage": "complete", "stages": {}},
)
elapsed = time.time() - t0
exec_mod._apply_topology_delta_if_present = _orig_apply

print(f"  ok={result.ok}, time={elapsed:.1f}s")
if result.error:
    print(f"  Error: {result.error[:200]}")

# ── Topology Delta Log ──
print(f"\n{'='*70}")
print(f"  4. TOPOLOGY DELTA LOG")
print(f"{'='*70}")
if not topo_log:
    print("  NO topology deltas captured!")
else:
    total_relations = 0
    ops_with_delta = 0
    for entry in topo_log:
        delta_str = f"{entry['relations']} rels ({entry['provider']})" if entry["has_delta"] else "NO DELTA"
        marker = "!!" if not entry["has_delta"] else "OK"
        if entry["dialect"] in ("composition", "sketch_profile", "axisymmetric") and not entry["has_delta"]:
            marker = "--"  # Expected: delta may be None for some ops
        print(f"  {marker} {entry['node']} ({entry['dialect']}.{entry['op']}): {delta_str}")
        print(f"     Entities: {entry['entities_before']}→{entry['entities_after']} "
              f"| active: {entry['active_before']}→{entry['active_after']} "
              f"| deleted: {entry['deleted_before']}→{entry['deleted_after']}")
        if entry.get("samples"):
            for s in entry["samples"]:
                loc_mark = "[LOC]" if s["has_locator"] else "[NOLOC]"
                print(f"       {loc_mark} {s['role']} ({s['type']}) status={s['status']} gen={s['gen']}")
        total_relations += entry["relations"]
        if entry["has_delta"]:
            ops_with_delta += 1

    print(f"\n  Summary: {ops_with_delta}/{len(topo_log)} ops produced deltas")
    print(f"  Total relations: {total_relations}")

# ── Topology Registry State ──
print(f"\n{'='*70}")
print(f"  5. TOPOLOGY REGISTRY STATE")
print(f"{'='*70}")

# Use the context from the runtime
ctx = None
for entry in topo_log:
    pass  # We need to access the registry

# Check topology events and warnings from result
if result.warnings:
    topo_warnings = [w for w in result.warnings if isinstance(w, str) and 'topology' in w.lower()]
    print(f"  Topology warnings: {len(topo_warnings)}")
    for w in topo_warnings[:5]:
        print(f"    {str(w)[:150]}")

# ── Integrity check ──
print(f"\n{'='*70}")
print(f"  6. TOPOLOGY INTEGRITY")
print(f"{'='*70}")

# Reconstruct a registry from the sidecar (if generated)
sidecar_path = OUT_DIR / "output.topology.json"
# The sidecar is NOT automatically generated — check metadata instead
meta_path = OUT_DIR / "output.metadata.json"
if meta_path.exists():
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    gm = meta.get("generative_metadata", {})
    print(f"  Metadata version: {gm.get('metadata_version', '?')}")
    print(f"  Warnings: {len(gm.get('warnings', []))}")
    print(f"  Degraded: {len(gm.get('degraded_features', []))}")
    print(f"  Unsupported: {gm.get('unsupported_capabilities', [])}")

    # Runtime report analysis
    rr = meta.get("runtime_report", {})
    if rr:
        print(f"  Runtime ok: {rr.get('ok')}")
        gh = rr.get("geometry_health", {})
        print(f"  Geometry health entries: {len(gh)}")
        for k, v in list(gh.items())[:3]:
            print(f"    {k}: status={v.get('status')}, closed={v.get('closed')}, volume={v.get('volume_mm3', '?')}")

# ── STEP Geometry ──
print(f"\n{'='*70}")
print(f"  7. STEP GEOMETRY VERIFICATION")
print(f"{'='*70}")
step_path = OUT_DIR / "output.step"
if step_path.exists():
    step_kb = step_path.stat().st_size / 1024
    print(f"  STEP size: {step_kb:.1f} KB")

    try:
        import cadquery as cq
        s = cq.importers.importStep(str(step_path))
        if hasattr(s, 'val'):
            s = s.val()
        if hasattr(s, 'solids'):
            solids = list(s.solids().vals() if hasattr(s.solids(), 'vals') else s.solids())
            s = solids[0] if solids else s

        bb = s.BoundingBox()
        fc = len(s.faces().vals()) if hasattr(s, 'faces') else 0
        closed = s.isClosed() if hasattr(s, "isClosed") else None
        vol = s.Volume() if hasattr(s, "Volume") else 0

        ftypes = {}
        if hasattr(s, 'faces'):
            for f in s.faces().vals():
                t = f.geomType()
                ftypes[t] = ftypes.get(t, 0) + 1

        print(f"  Faces: {fc}")
        print(f"  BBox: [{bb.xlen:.0f}, {bb.ylen:.0f}, {bb.zlen:.0f}] mm")
        print(f"  Volume: {vol/1e3:.1f} cm³, Closed: {closed}")
        print(f"  Face types: {ftypes}")
        print(f"  Body count: {len(solids) if 'solids' in dir() else 'N/A'}")
    except Exception as e:
        print(f"  STEP inspection failed: {e}")

# ── Files ──
print(f"\n{'='*70}")
print(f"  8. OUTPUT FILES")
print(f"{'='*70}")
for f in sorted(OUT_DIR.glob("*")):
    if f.is_file():
        print(f"  {f.name}: {f.stat().st_size / 1024:.1f} KB")

# ── Final Verdict ──
print(f"\n{'='*70}")
print(f"  FINAL VERDICT")
print(f"{'='*70}")
print(f"  Pipeline: {'OK' if result.ok else 'FAILED'}")
print(f"  Time: {elapsed:.1f}s")
if topo_log:
    ops_with = sum(1 for e in topo_log if e['has_delta'])
    print(f"  Topology ops with delta: {ops_with}/{len(topo_log)}")
    print(f"  Total relations: {sum(e['relations'] for e in topo_log)}")
print(f"{'='*70}")
