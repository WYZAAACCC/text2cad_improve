"""End-to-end topology naming deep monitor test — non-primitive full pipeline."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations" / "engineering_tools" / "src"))

print("=" * 60)
print("  E2E Topology Naming — Full Pipeline Deep Monitor")
print("=" * 60)

# Valid raw IR: block + hole (extrude_rectangle + cut_hole)
raw = {
    "schema_version": "g_cad_core_v0.2",
    "document_id": "e2e-topology-test",
    "part_name": "BlockWithHole",
    "units": "mm",
    "trust_level": "concept_geometry",
    "selected_dialects": [{"dialect": "sketch_extrude", "version": "0.2.0"}],
    "components": [{"id": "block", "owner_dialect": "sketch_extrude", "kind_hint": "block", "root_node": "n2"}],
    "nodes": [
        {"id": "n1", "component": "block", "dialect": "sketch_extrude", "op": "extrude_rectangle",
         "op_version": "1.0.0", "phase": "base_solid",
         "inputs": [], "outputs": [{"name": "body", "type": "solid"}],
         "params": {"width_mm": 100, "height_mm": 60, "depth_mm": 30, "plane": "XY", "centered": True},
         "required": True, "degradation_policy": "fail"},
        {"id": "n2", "component": "block", "dialect": "sketch_extrude", "op": "cut_hole",
         "op_version": "1.0.0", "phase": "primary_cut",
         "inputs": [{"node": "n1", "output": "body"}],
         "outputs": [{"name": "body", "type": "solid"}],
         "params": {"diameter_mm": 20, "position_mm": [0, 0, 0], "axis": "Z"},
         "required": True, "degradation_policy": "fail"},
    ],
    "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                    "require_closed_solid": True, "expected_body_count": 1},
    "safety": {"non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
               "not_for_manufacturing": True, "not_for_installation": True,
               "no_structural_validation": True, "no_life_prediction": True},
    "llm_validation_hints": {},
}

# Step 1: Validate + Canonicalize
print(f"\n1. VALIDATE: {len(raw['nodes'])} nodes [{raw['nodes'][0]['op']}, {raw['nodes'][1]['op']}]")
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import run_validation
run = run_validation(raw)
print(f"   ok={run.report.ok}, stage={run.report.stage}, {len(run.report.issues)} issues")
for iss in run.report.issues[:8]:
    print(f"   [{iss.severity}] {iss.code}: {iss.message[:90]}")

topo_records = [r for r in run.execution_records if "topology" in r.rule_id]
topo_issues = [i for i in run.report.issues if "TOPOLOGY" in i.code]
print(f"   TOPOLOGY rules executed: {len(topo_records)}, issues: {len(topo_issues)}")
for r in topo_records:
    print(f"     {r.rule_id}: status={r.status}, issues={r.issue_count}")
for iss in topo_issues:
    print(f"     [{iss.severity}] {iss.code}")

if run.canonical is None:
    print("   FAILED — check issues above")
    sys.exit(1)
print(f"   canonical_graph_hash={run.canonical.canonical_graph_hash[:16]}...")

# Step 2: Runtime with topology interceptor
print(f"\n2. RUNTIME EXECUTION (with topology interceptor):")
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

out_dir = Path(__file__).resolve().parent / "test_topology_e2e"
out_dir.mkdir(parents=True, exist_ok=True)

# Intercept topology delta application in executor
import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod
_orig_apply = exec_mod._apply_topology_delta_if_present
topo_log = []

def _intercept(*, node, result, ctx):
    before_entities = ctx.topology_registry.entity_count
    before_active = ctx.topology_registry.active_count
    before_deleted = ctx.topology_registry.deleted_count
    _orig_apply(node=node, result=result, ctx=ctx)
    after_entities = ctx.topology_registry.entity_count
    after_active = ctx.topology_registry.active_count
    after_deleted = ctx.topology_registry.deleted_count
    delta = result.topology_delta
    topo_log.append({
        "node": node.id, "op": node.op,
        "has_delta": delta is not None,
        "relations": len(delta.relations) if delta else 0,
        "provider": delta.history_provider if delta else "none",
        "entities_before": before_entities,
        "entities_after": after_entities,
        "active_before": before_active,
        "active_after": after_active,
        "deleted_before": before_deleted,
        "deleted_after": after_deleted,
    })

exec_mod._apply_topology_delta_if_present = _intercept

t0 = time.time()
result = run_canonical_gcad(
    canonical=run.canonical, out_step=out_dir / "output.step",
    metadata_path=out_dir / "output.metadata.json",
    validation_seed={"ok": True, "stage": "complete", "stages": {}},
)
elapsed = time.time() - t0
exec_mod._apply_topology_delta_if_present = _orig_apply
print(f"   ok={result.ok}, time={elapsed:.1f}s")
if result.error:
    print(f"   Error: {result.error[:150]}")

# Step 3: Topology log analysis
print(f"\n3. TOPOLOGY DELTA LOG:")
if not topo_log:
    print("   NO topology deltas captured!")
    print("   (handlers produce topology via side-channel, not through executor)")
else:
    for entry in topo_log:
        delta_str = f"{entry['relations']} rels ({entry['provider']})" if entry["has_delta"] else "NONE"
        print(f"   {entry['node']} ({entry['op']}): {delta_str}")
        print(f"     Entities: {entry['entities_before']}->{entry['entities_after']} "
              f"(active: {entry['active_before']}->{entry['active_after']}, "
              f"deleted: {entry['deleted_before']}->{entry['deleted_after']})")

# Step 4: Runtime report analysis
print(f"\n4. RUNTIME REPORT:")
if hasattr(result, "runtime_report") and result.runtime_report:
    rr = result.runtime_report
    print(f"   ok={rr.ok}")
    if hasattr(rr, "geometry_health"):
        gh = rr.geometry_health
        print(f"   geometry_health entries: {len(gh)}")
        for k, v in list(gh.items())[:3]:
            print(f"     {k}: status={v.get('status')}, closed={v.get('closed')}")

# Step 5: Output files
print(f"\n5. OUTPUT FILES:")
for f in sorted(out_dir.glob("*")):
    if f.is_file():
        print(f"   {f.name}: {f.stat().st_size / 1024:.1f} KB")

# Step 6: Metadata analysis
meta_path = out_dir / "output.metadata.json"
if meta_path.exists():
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    gm = meta.get("generative_metadata", {})
    print(f"\n6. METADATA:")
    print(f"   version: {gm.get('metadata_version', '?')}")
    print(f"   warnings: {len(gm.get('warnings', []))}")
    print(f"   degraded: {len(gm.get('degraded_features', []))}")
    print(f"   unsupported: {gm.get('unsupported_capabilities', [])}")

# Step 7: Geometry health
step_path = out_dir / "output.step"
if step_path.exists():
    import cadquery as cq
    s = cq.importers.importStep(str(step_path))
    # Handle both Workplane and Compound returns
    if hasattr(s, 'val'):
        s = s.val()
    if hasattr(s, 'solids'):
        solids = s.solids().vals() if hasattr(s.solids(), 'vals') else list(s.solids())
        s = solids[0] if solids else s
    try:
        bb = s.BoundingBox()
        fc = len(s.faces().vals()) if hasattr(s, 'faces') else 0
        closed = s.isClosed() if hasattr(s, "isClosed") else None
        vol = s.Volume()
        ftypes = {}
        if hasattr(s, 'faces'):
            for f in s.faces().vals():
                t = f.geomType()
                ftypes[t] = ftypes.get(t, 0) + 1
        print(f"\n7. GEOMETRY:")
        print(f"   Faces: {fc}, BBox: [{bb.xlen:.0f}, {bb.ylen:.0f}, {bb.zlen:.0f}] mm")
        print(f"   Volume: {vol / 1e3:.1f} cm^3, Closed: {closed}")
        print(f"   Face types: {ftypes}")
        cyl_count = ftypes.get("CYLINDER", 0)
        print(f"   Hole wall faces (CYLINDER): {cyl_count}")
    except Exception as e:
        print(f"\n7. GEOMETRY: import OK but inspection failed ({e})")

# Step 8: Topology warnings
if result.warnings:
    topo_warnings = [w for w in result.warnings if isinstance(w, str) and "topology" in w.lower()]
    print(f"\n8. TOPOLOGY-RELATED WARNINGS: {len(topo_warnings)}")
    for w in topo_warnings[:5]:
        print(f"   {str(w)[:120]}")

print(f"\n{'=' * 60}")
if topo_log:
    total_relations = sum(e["relations"] for e in topo_log)
    ops_with_delta = sum(1 for e in topo_log if e["has_delta"])
    print(f"  RESULT: {ops_with_delta}/{len(topo_log)} ops produced topology deltas")
    print(f"  Total topology relations: {total_relations}")
else:
    print(f"  RESULT: No topology deltas through executor path")
    print(f"  (cut_hole handler produces topology via side-channel)")
print(f"{'=' * 60}")
