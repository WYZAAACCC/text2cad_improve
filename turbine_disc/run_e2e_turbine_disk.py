"""End-to-end turbine disk test with topology monitoring — using latest test IR."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations" / "engineering_tools" / "src"))

REF_DIR = Path("app/text-to-cad/server/output/b572661c219c4952")
OUT_DIR = Path(__file__).resolve().parent / "test_topology_turbine_disk"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  Turbine Disk E2E — Topology Monitor")
print(f"  Reference: {REF_DIR.name}")
print("=" * 60)

# Load and fix IR
raw = json.loads((REF_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
if raw.get("llm_validation_hints") is None:
    raw["llm_validation_hints"] = {}

print(f"\n1. IR: {raw['part_name']} ({len(raw['nodes'])} nodes)")
for n in raw["nodes"]:
    print(f"   {n['id']}: {n['dialect']}.{n['op']}")

# Validate
print(f"\n2. VALIDATE:")
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import run_validation
t0 = time.time()
run = run_validation(raw)
print(f"   ok={run.report.ok}, stage={run.report.stage}, time={time.time()-t0:.1f}s")
for iss in run.report.issues[:5]:
    print(f"   [{iss.severity}] {iss.code}: {iss.message[:90]}")
if len(run.report.issues) > 5:
    print(f"   ... {len(run.report.issues)} total issues")

topo_records = [r for r in run.execution_records if "topology" in r.rule_id]
print(f"   Topology rules: {len(topo_records)}")
for r in topo_records:
    print(f"     {r.rule_id}: status={r.status}, issues={r.issue_count}")

if run.canonical is None:
    print("   FAILED"); sys.exit(1)

# Runtime
print(f"\n3. RUNTIME (with topology interceptor):")
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod

_orig_apply = exec_mod._apply_topology_delta_if_present
topo_log = []

def _intercept(*, node, result, ctx):
    before = ctx.topology_registry.entity_count
    active_before = ctx.topology_registry.active_count
    deleted_before = ctx.topology_registry.deleted_count
    _orig_apply(node=node, result=result, ctx=ctx)
    after = ctx.topology_registry.entity_count
    active_after = ctx.topology_registry.active_count
    deleted_after = ctx.topology_registry.deleted_count
    delta = result.topology_delta
    topo_log.append({
        "node": node.id, "op": node.op,
        "has_delta": delta is not None,
        "relations": len(delta.relations) if delta else 0,
        "entities": f"{before}->{after}",
        "active": f"{active_before}->{active_after}",
        "deleted": f"{deleted_before}->{deleted_after}",
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
print(f"   ok={result.ok}, time={elapsed:.1f}s")
if result.error:
    print(f"   ERROR: {result.error[:200]}")

# Topology log
print(f"\n4. TOPOLOGY ENTITY EVOLUTION:")
if topo_log:
    for entry in topo_log:
        delta_str = f"{entry['relations']} relations" if entry["has_delta"] else "no delta"
        print(f"   {entry['node']} ({entry['op']}): {delta_str}")
        print(f"     entities: {entry['entities']}, active: {entry['active']}, deleted: {entry['deleted']}")
else:
    print("   No topology log entries")

# Output comparison
print(f"\n5. OUTPUT COMPARISON:")
ref_step = REF_DIR / "output.step"
our_step = OUT_DIR / "output.step"
ref_meta = REF_DIR / "output.metadata.json"
our_meta = OUT_DIR / "output.metadata.json"

for label, path in [("Reference", ref_step), ("Ours", our_step)]:
    if path.exists():
        size_mb = path.stat().st_size / 1e6
        print(f"   {label} STEP: {size_mb:.1f} MB")
    else:
        print(f"   {label} STEP: MISSING")

# Geometry check
if our_step.exists():
    import cadquery as cq
    try:
        s = cq.importers.importStep(str(our_step))
        if hasattr(s, 'val'): s = s.val()
        if hasattr(s, 'solids'):
            solids = list(s.solids().vals()) if hasattr(s.solids(), 'vals') else list(s.solids())
            s = solids[0] if solids else s
        bb = s.BoundingBox()
        fc = len(s.faces().vals()) if hasattr(s, 'faces') else 0
        closed = s.isClosed() if hasattr(s, 'isClosed') else None
        vol = s.Volume() if hasattr(s, 'Volume') else 0
        ftypes = {}
        if hasattr(s, 'faces'):
            for f in s.faces().vals():
                t = f.geomType(); ftypes[t] = ftypes.get(t, 0) + 1
        print(f"\n6. OUR GEOMETRY:")
        print(f"   Faces: {fc}, BBox: [{bb.xlen:.0f},{bb.ylen:.0f},{bb.zlen:.0f}]mm")
        print(f"   Volume: {vol/1e6:.1f} cm^3, Closed: {closed}")
        print(f"   Types: {ftypes}")
    except Exception as e:
        print(f"\n6. GEOMETRY: inspection failed ({e})")

# Topology warnings
topo_warnings = [w for w in result.warnings if isinstance(w, str) and "topology" in w.lower()]
print(f"\n7. TOPOLOGY WARNINGS: {len(topo_warnings)}")
for w in topo_warnings[:5]:
    print(f"   {str(w)[:120]}")

print(f"\n{'=' * 60}")
print(f"  COMPLETE")
print(f"{'=' * 60}")
