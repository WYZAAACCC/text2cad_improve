"""Deep verify: PersistentTopoId → Locator → actual Face → resolve round-trip."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations" / "engineering_tools" / "src"))

REF_DIR = Path("app/text-to-cad/server/output/fd4658e7d3044f07")

print("=" * 70)
print("  TOPOLOGY CHAIN VERIFICATION")
print("=" * 70)

# Load IR
raw = json.loads((REF_DIR / "raw_fixed.json").read_text(encoding="utf-8"))
if raw.get("llm_validation_hints") is None:
    raw["llm_validation_hints"] = {}

# Validate
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import run_validation
run = run_validation(raw)
canonical = run.canonical

# Runtime with full registry access
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

OUT_DIR = Path(__file__).resolve().parent / "test_topology_verify"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Save registry snapshot after build
_registry_snapshot = {}

def _capture_registry(*, node, result, ctx):
    _registry_snapshot[node.id] = {
        "entity_count": ctx.topology_registry.entity_count,
        "active_count": ctx.topology_registry.active_count,
        "deleted_count": ctx.topology_registry.deleted_count,
        "entities": {
            pid: {
                "role": rec.semantic_role,
                "type": rec.entity_type,
                "status": rec.status,
                "gen": rec.generation,
                "owner": rec.owner_body_handle_id,
                "has_locator": rec.current_locator is not None,
                "locator_pos": rec.current_locator.get("indexed_map_position") if rec.current_locator else None,
            }
            for pid, rec in ctx.topology_registry._entities.items()
        },
    }

import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod
_orig = exec_mod._apply_topology_delta_if_present
exec_mod._apply_topology_delta_if_present = _capture_registry

t0 = time.time()
result = run_canonical_gcad(
    canonical=canonical,
    out_step=OUT_DIR / "output.step",
    metadata_path=OUT_DIR / "output.metadata.json",
    validation_seed={"ok": True, "stage": "complete", "stages": {}},
)
elapsed = time.time() - t0
exec_mod._apply_topology_delta_if_present = _orig

print(f"\nPipeline: ok={result.ok}, time={elapsed:.1f}s\n")

# ── Verify each operation's topology ──
# We need access to the final registry state
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.locator import RuntimeTopoLocator
from seekflow_engineering_tools.generative_cad.topology.shape_binding import ShapeBindingService

# Re-run just the operations we care about with deep inspection
print("=" * 70)
print("  FULL TOPOLOGY CHAIN AUDIT")
print("=" * 70)

# Build a fresh pipeline that gives us registry access
run2 = run_validation(raw)
canonical2 = run2.canonical

# Intercept at a deeper level - capture ctx during execution
ctx_ref = {}

# Monkey-patch the pipeline to capture ctx
from seekflow_engineering_tools.generative_cad.pipeline import run as run_mod
_orig_run_components = run_mod._run_components

def _patched_run_components(canonical, ctx, *args, **kwargs):
    ctx_ref['ctx'] = ctx
    return _orig_run_components(canonical, ctx, *args, **kwargs)

run_mod._run_components = _patched_run_components

result2 = run_canonical_gcad(
    canonical=canonical2,
    out_step=OUT_DIR / "output2.step",
    metadata_path=OUT_DIR / "output2.metadata.json",
    validation_seed={"ok": True, "stage": "complete", "stages": {}},
)
run_mod._run_components = _orig_run_components

ctx = ctx_ref.get('ctx')
if ctx is None:
    print("ERROR: Could not capture RuntimeContext")
    sys.exit(1)

reg = ctx.topology_registry
binding_svc = ShapeBindingService(ctx.object_store)

print(f"\nRegistry state: {reg.entity_count} entities ({reg.active_count} active, {reg.deleted_count} deleted)")
integrity = reg.validate_integrity()
print(f"Integrity: ok={integrity['ok']}, issues={len(integrity['issues'])}")
for iss in integrity['issues'][:5]:
    print(f"  [{iss['code']}] {iss['message'][:100]}")

# ── Audit every entity ──
print(f"\n{'='*70}")
print(f"  PER-ENTITY CHAIN AUDIT")
print(f"{'='*70}")

# Group by producer node
by_node = {}
for pid, rec in reg._entities.items():
    nid = rec.producer_node_id
    if nid not in by_node:
        by_node[nid] = []
    by_node[nid].append((pid, rec))

target_ops = ["revolve_profile", "extrude_profile", "boolean_cut"]
for op_name in target_ops:
    for nid, entities in by_node.items():
        # Check if any entity's producer matches
        roles = [rec.semantic_role for _, rec in entities[:3]]
        if any(op_name in r or "revolved" in r or "extrude" in r or "boolean" in r for r in roles):
            print(f"\n--- {nid} ({len(entities)} entities) ---")

            located = 0
            noloc = 0
            roles_seen: dict[str, int] = {}

            for pid, rec in entities:
                loc = rec.current_locator
                role = rec.semantic_role
                roles_seen[role] = roles_seen.get(role, 0) + 1

                if loc is None:
                    noloc += 1
                    continue

                # ── Verify locator ──
                try:
                    locator = RuntimeTopoLocator(**loc)
                except Exception as e:
                    print(f"  BAD LOCATOR {role}: {e}")
                    continue

                # ── Resolve to actual face ──
                owner_shape = None
                try:
                    owner_shape = ctx.object_store.get(locator.owner_body_handle_id)
                except KeyError:
                    print(f"  OWNER NOT FOUND {role}: {locator.owner_body_handle_id}")
                    continue

                # Build fresh maps and verify
                maps = binding_svc.build_body_maps(locator.owner_body_handle_id, owner_shape)
                if locator.entity_type == "face":
                    face_dict = maps.face_map
                    idx_map = maps._face_indexed_map
                elif locator.entity_type == "edge":
                    face_dict = maps.edge_map
                    idx_map = maps._edge_indexed_map
                else:
                    continue

                actual_face = face_dict.get(locator.indexed_map_position)
                if actual_face is None:
                    print(f"  POSITION OUT OF BOUNDS {role}: pos={locator.indexed_map_position}, map_size={len(face_dict)}")
                    continue

                # Verify the face is the same via FindIndex
                if idx_map is not None:
                    try:
                        found_pos = idx_map.FindIndex(actual_face)
                        if found_pos != locator.indexed_map_position:
                            print(f"  POSITION MISMATCH {role}: expected={locator.indexed_map_position}, found={found_pos}")
                            continue
                    except Exception:
                        pass

                # Verify entity type
                try:
                    actual_type = actual_face.ShapeType() if hasattr(actual_face, 'ShapeType') else None
                    if actual_type is not None:
                        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
                        expected = TopAbs_FACE if locator.entity_type == "face" else TopAbs_EDGE
                        if actual_type != expected:
                            print(f"  TYPE MISMATCH {role}: expected={locator.entity_type}, actual_shape_type={actual_type}")
                            continue
                except Exception:
                    pass

                located += 1

            print(f"  Located: {located}/{located + noloc} ([LOC]={located}, [NOLOC]={noloc})")
            print(f"  Roles: {dict(roles_seen)}")
            break  # found the right node group

print(f"\n{'='*70}")
print(f"  VERIFICATION COMPLETE")
print(f"{'='*70}")
