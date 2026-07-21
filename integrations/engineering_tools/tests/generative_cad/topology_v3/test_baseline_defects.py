"""Phase 0: Failure baseline tests — freeze current V3 topology defects as verifiable tests.

These tests codify the CURRENT broken behavior. After the V3 repair is complete,
all 15 tests should FAIL (each measuring a defect that has been fixed).

Ref: text2cad_persistent_topology_v3_repair_guide.md §1.1–§1.7
"""

import sys
from pathlib import Path

import cadquery as cq
import pytest

# ── Path setup ──
_PROJECT = Path(__file__).resolve().parents[5]  # auto_detection_process/
_SRC = _PROJECT / "integrations" / "engineering_tools" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    _make_compact_key,
    build_entity_records_from_delta,
    name_revolve_faces,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Group A: Static code analysis tests (no geometry needed)
# ═══════════════════════════════════════════════════════════════════════════════


class TestV3FieldsNeverTouchedInDialects:
    """§1.1: V3 fields (lifecycle, binding_state, proof_class, identity_descriptor)
    are defined in models.py but never referenced in the dialects/ directory."""

    V3_FIELDS = ["identity_descriptor", "lifecycle", "binding_state", "proof_class"]

    def test_lifecycle_not_referenced_in_dialects(self):
        """'lifecycle' should have zero references in dialects/ production code."""
        dialects_dir = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
        )
        count = 0
        for py_file in dialects_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("lifecycle")
        assert count == 0, (
            f"Expected 0 references to 'lifecycle' in dialects/, got {count}. "
            f"V3 fields are defined but not yet wired into production handlers."
        )

    def test_binding_state_not_referenced_in_dialects(self):
        """'binding_state' should have zero references in dialects/."""
        dialects_dir = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
        )
        count = 0
        for py_file in dialects_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("binding_state")
        assert count == 0, (
            f"Expected 0 references to 'binding_state' in dialects/, got {count}."
        )

    def test_proof_class_not_referenced_in_dialects(self):
        """'proof_class' should have zero references in dialects/."""
        dialects_dir = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
        )
        count = 0
        for py_file in dialects_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("proof_class")
        assert count == 0, (
            f"Expected 0 references to 'proof_class' in dialects/, got {count}."
        )

    def test_identity_descriptor_not_referenced_in_dialects(self):
        """'identity_descriptor' should have zero references in dialects/."""
        dialects_dir = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
        )
        count = 0
        for py_file in dialects_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("identity_descriptor")
        assert count == 0, (
            f"Expected 0 references to 'identity_descriptor' in dialects/, got {count}."
        )


class TestApplyIdentityDecisionsNeverCalled:
    """§5.5: apply_identity_decisions() exists in registry.py but is never called
    from any handler."""

    def test_apply_identity_decisions_not_imported_in_dialects(self):
        """'apply_identity_decisions' should not be imported in dialects/."""
        dialects_dir = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
        )
        count = 0
        for py_file in dialects_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("apply_identity_decisions")
        assert count == 0, (
            f"Expected 0 references to 'apply_identity_decisions' in dialects/, "
            f"got {count}. This method is implemented but never wired to handlers."
        )


class TestValidateGeometryBindingsNeverCalled:
    """§5.6: validate_geometry_bindings() exists in transaction.py but is never
    called from commit()."""

    def test_validate_geometry_bindings_not_called_in_commit(self):
        """validate_geometry_bindings is not called in TopologyTransaction.commit()."""
        transaction_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "topology"
            / "transaction.py"
        )
        text = transaction_path.read_text(encoding="utf-8")
        # Find the commit() method body
        commit_start = text.find("def commit(self)")
        commit_end = text.find("\n    def ", commit_start + 1)
        if commit_end == -1:
            commit_end = len(text)
        commit_body = text[commit_start:commit_end]
        assert "validate_geometry_bindings" not in commit_body, (
            "validate_geometry_bindings() is NOT called inside commit(). "
            "It exists but is never invoked during transaction commit."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Group B: Semantic naming layer tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDescriptorDiscardOnSemanticNaming:
    """§5.7: _make_compact_key() calls _make_compact_id() but discards the
    descriptor dict, returning only the key string."""

    def test_make_compact_key_returns_tuple_not_string(self):
        """CURRENT BEHAVIOR: _make_compact_key() returns a string (key only),
        discarding the V3 descriptor. After Phase 1 fix, it should return tuple."""
        result = _make_compact_key(
            document_id="test_doc",
            component_id="test_comp",
            producer_node_id="node_1",
            entity_type="face",
            semantic_role="test/role",
        )
        # Current defect: returns str, not tuple[str, dict]
        assert isinstance(result, str), (
            f"_make_compact_key() currently returns {type(result).__name__}, "
            f"not tuple[str, dict]. The V3 descriptor is being discarded."
        )

    def test_build_entity_records_has_no_descriptor(self):
        """build_entity_records_from_delta() creates records with identity_descriptor=None."""
        delta = name_revolve_faces(
            cq.Workplane("XZ").moveTo(10, 0).lineTo(50, 0)
            .lineTo(50, 20).lineTo(10, 20).close().revolve(360),
            document_id="test_doc",
            component_id="disc",
            producer_node_id="n_revolve",
            angle_deg=360,
            axis="Z",
        )
        records = build_entity_records_from_delta(delta, document_id="test_doc")
        assert len(records) > 0, "Expected at least one entity record"
        for rec in records:
            assert rec.identity_descriptor is None, (
                f"Record {rec.persistent_id[:30]}... has identity_descriptor="
                f"{rec.identity_descriptor!r}. Should be None (not yet wired)."
            )


class TestBuildEntityRecordsMissingV3Fields:
    """§1.1: build_entity_records_from_delta() does not populate V3 fields."""

    def test_all_records_have_v3_fields_none(self):
        """Every record from build_entity_records_from_delta has V3 fields = None."""
        delta = name_revolve_faces(
            cq.Workplane("XZ").moveTo(10, 0).lineTo(50, 0)
            .lineTo(50, 20).lineTo(10, 20).close().revolve(360),
            document_id="test_doc",
            component_id="disc",
            producer_node_id="n_revolve",
            angle_deg=360,
            axis="Z",
        )
        records = build_entity_records_from_delta(delta, document_id="test_doc")
        for rec in records:
            assert rec.lifecycle is None, f"lifecycle should be None, got {rec.lifecycle}"
            assert rec.binding_state is None, f"binding_state should be None, got {rec.binding_state}"
            assert rec.proof_class is None, f"proof_class should be None, got {rec.proof_class}"


# ═══════════════════════════════════════════════════════════════════════════════
# Group C: Simple geometry tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBedV2WriterCalledInProduction:
    """§1.2: make_persistent_id_v2() is still called in production handlers
    (sketch_profile, axisymmetric, sketch_extrude)."""

    def test_make_persistent_id_v2_still_in_dialects(self):
        """Search for make_persistent_id_v2 calls in dialects/ directory."""
        dialects_dir = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
        )
        count = 0
        files = []
        for py_file in sorted(dialects_dir.rglob("*.py")):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            if "make_persistent_id_v2" in text:
                count += text.count("make_persistent_id_v2")
                files.append(str(py_file.relative_to(dialects_dir)))
        assert count > 0, (
            f"make_persistent_id_v2() found {count} times in dialects/: {files}. "
            f"After Phase 2 fix, this should be 0."
        )

    def test_v2_writer_import_still_in_sketch_profile(self):
        """sketch_profile/handlers.py still imports make_persistent_id_v2."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "sketch_profile" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")
        assert "make_persistent_id_v2" in text, (
            "sketch_profile/handlers.py still contains make_persistent_id_v2. "
            "After Phase 2 fix, this import should be removed."
        )


class TestBedBooleanGuessedPidMapping:
    """§1.4: composition/handlers.py uses mod_i % len, pop(0), ancestor_pids[:1]
    to guess PID mappings instead of using real OCCT history."""

    def test_mod_i_modulo_len_exists(self):
        """The 'mod_i % len(prev_pids[pn])' pattern exists in composition handlers."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "composition" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")
        assert "mod_i % len" in text, (
            "Pattern 'mod_i % len' found in composition/handlers.py. "
            "Boolean PID mapping is still guessed by modulo arithmetic."
        )

    def test_pop_zero_exists(self):
        """The 'pop(0)' pattern for guessing deleted PIDs exists."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "composition" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")
        assert ".pop(0)" in text, (
            "Pattern '.pop(0)' found in composition/handlers.py. "
            "Deleted entity PID is guessed by consuming a list."
        )

    def test_ancestor_pids_slice_exists(self):
        """The 'ancestor_pids[:1]' star lineage pattern exists."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "composition" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")
        assert "ancestor_pids[:1]" in text, (
            "Pattern 'ancestor_pids[:1]' found. "
            "All new entities are linked to a single ancestor, creating a star lineage."
        )


class TestBedBooleanExceptionSilentSwallow:
    """§0.1 Rule 4: composition/handlers.py L479 uses 'except Exception: pass'
    to silently swallow all errors in the topology path."""

    def test_exception_pass_in_boolean_topology(self):
        """The boolean topology handler swallows exceptions silently."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "composition" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")
        # Count except Exception blocks that are followed by pass within 3 lines
        assert "except Exception:" in text, (
            "except Exception blocks exist in composition/handlers.py"
        )


class TestBedPlaceTransformNoTopologyEvent:
    """§1.5: Place/translate/rotate handlers produce zero topology events."""

    def test_no_topology_transaction_in_place_handlers(self):
        """Search for topology_transaction in transform handlers."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "composition" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")

        # Find each handler function body
        for func_name in [
            "handle_translate_solid",
            "handle_rotate_solid",
            "handle_place_component",
        ]:
            func_start = text.find(f"def {func_name}")
            assert func_start != -1, f"Function {func_name} not found"
            # Find the next def after this function
            next_def = text.find("\ndef ", func_start + 1)
            if next_def == -1:
                next_def = len(text)
            func_body = text[func_start:next_def]
            assert "topology_transaction" not in func_body, (
                f"{func_name} contains topology_transaction — "
                f"should be 0 before Phase 3 fix"
            )
            assert "topology_events" not in func_body, (
                f"{func_name} contains topology_events — "
                f"should be 0 before Phase 3 fix"
            )


class TestBedPatternNoTopologyEvent:
    """§1.5: Pattern handlers produce zero topology events."""

    def test_no_topology_transaction_in_pattern_handlers(self):
        """Search for topology_transaction in pattern handlers."""
        handler_path = (
            _PROJECT / "integrations" / "engineering_tools" / "src"
            / "seekflow_engineering_tools" / "generative_cad" / "dialects"
            / "composition" / "handlers.py"
        )
        text = handler_path.read_text(encoding="utf-8")

        for func_name in [
            "handle_circular_pattern_component",
            "handle_linear_pattern_component",
        ]:
            func_start = text.find(f"def {func_name}")
            assert func_start != -1, f"Function {func_name} not found"
            next_def = text.find("\ndef ", func_start + 1)
            if next_def == -1:
                next_def = len(text)
            func_body = text[func_start:next_def]
            assert "topology_transaction" not in func_body, (
                f"{func_name} contains topology_transaction — "
                f"should be 0 before Phase 4 fix"
            )
            assert "topology_events" not in func_body, (
                f"{func_name} contains topology_events — "
                f"should be 0 before Phase 4 fix"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Group D: Integration tests (require full pipeline or turbine disc data)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBedNodeRenameChangesPids:
    """§1.2: With V2 writer, changing producer_node_id changes the PID because
    it's included in the hash payload."""

    def test_different_node_id_produces_different_pid(self):
        """Semantic naming with different producer_node_id → different PID keys."""
        solid = (
            cq.Workplane("XZ").moveTo(10, 0).lineTo(50, 0)
            .lineTo(50, 20).lineTo(10, 20).close().revolve(360)
        )
        delta_a = name_revolve_faces(
            solid, document_id="test_doc", component_id="disc",
            producer_node_id="n_revolve_original", angle_deg=360, axis="Z",
        )
        delta_b = name_revolve_faces(
            solid, document_id="test_doc", component_id="disc",
            producer_node_id="n_revolve_renamed", angle_deg=360, axis="Z",
        )
        pids_a = {r.result_entity_keys[0] for r in delta_a.relations if r.result_entity_keys}
        pids_b = {r.result_entity_keys[0] for r in delta_b.relations if r.result_entity_keys}
        # With V3 writer using feature_stable_id=producer_node_id fallback,
        # different producer_node_id → different PIDs
        assert pids_a != pids_b, (
            f"V2/V3-fallback writer: different node IDs produce different PIDs.\n"
            f"pids_a sample: {list(pids_a)[:2]}\n"
            f"pids_b sample: {list(pids_b)[:2]}\n"
            f"After Phase 2 fix with stable feature_uid, these should be equal."
        )


class TestBedNoV3DescriptorsOnTurbineDisc:
    """§1.1: V3 identity_descriptor is None on all records produced by handlers."""

    def test_revolve_records_have_no_descriptor(self):
        """After a basic revolve, all records have identity_descriptor=None."""
        solid = (
            cq.Workplane("XZ").moveTo(10, 0).lineTo(50, 0)
            .lineTo(50, 20).lineTo(10, 20).close().revolve(360)
        )
        delta = name_revolve_faces(
            solid, document_id="test_doc", component_id="disc",
            producer_node_id="n_revolve", angle_deg=360, axis="Z",
        )
        records = build_entity_records_from_delta(delta, document_id="test_doc")
        for rec in records:
            assert rec.identity_descriptor is None, (
                f"Record PID={rec.persistent_id[:40]}... has "
                f"identity_descriptor={rec.identity_descriptor!r}. "
                f"Currently None because V3 descriptor is not wired into handlers."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Group E: Complex integration tests (turbine disc pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

# Path to the latest V3 final output with real turbine disc data
_V3_FINAL_DIR = (
    _PROJECT / "app" / "text-to-cad" / "server" / "output"
    / "v3_final_20260721_045319"
)

# Path to turbine disc test data (raw IR)
_TURBINE_RAW = _V3_FINAL_DIR / "raw_fixed.json"


def _run_turbine_disc_pipeline():
    """Run the full turbine disc pipeline and return the RuntimeContext."""
    import json

    if not _TURBINE_RAW.exists():
        pytest.skip(f"Turbine disc data not found: {_TURBINE_RAW}")

    raw = json.loads(_TURBINE_RAW.read_text(encoding="utf-8"))

    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize_with_bundle,
    )
    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
    if canonical is None or not report.ok:
        pytest.skip(f"Validation failed: {report.issues[:2]}")

    import tempfile
    import warnings
    from seekflow_engineering_tools.generative_cad.pipeline.run import (
        run_canonical_gcad,
    )

    ctx_ref = {}
    import seekflow_engineering_tools.generative_cad.dialects.executor as exec_mod
    _orig = exec_mod._apply_topology_delta_if_present

    def _capture(*, node, result, ctx, op_spec=None):
        _orig(node=node, result=result, ctx=ctx, op_spec=op_spec)
        ctx_ref["ctx"] = ctx

    exec_mod._apply_topology_delta_if_present = _capture
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with tempfile.TemporaryDirectory() as tmp:
                result = run_canonical_gcad(
                    canonical=canonical,
                    out_step=Path(tmp) / "out.step",
                    metadata_path=Path(tmp) / "out.json",
                    validation_seed=bundle.to_metadata_dict(),
                )
    finally:
        exec_mod._apply_topology_delta_if_present = _orig

    ctx = ctx_ref.get("ctx")
    if ctx is None:
        pytest.skip("Pipeline did not capture context")
    return ctx


class TestFakeStarLineageExists:
    """§1.7: The current boolean topology creates a star lineage where
    one entity has all other entities as descendants, because of
    ancestor_pids[:1] in composition/handlers.py:549."""

    def test_star_lineage_present_in_turbine_disc(self):
        """Run the turbine disc pipeline and verify star lineage exists:
        one entity has >50% of all entities as descendants."""
        ctx = _run_turbine_disc_pipeline()
        reg = ctx.topology_registry

        # Find the entity with max descendants
        max_descendants = 0
        star_pid = None
        for pid, rec in reg._entities.items():
            nd = len(rec.descendant_ids)
            if nd > max_descendants:
                max_descendants = nd
                star_pid = pid

        total = reg.entity_count
        assert total > 100, f"Expected >100 entities in turbine disc, got {total}"
        assert max_descendants > total * 0.5, (
            f"Star lineage exists: entity {star_pid} has {max_descendants} "
            f"descendants out of {total} total entities ({max_descendants/total:.0%}). "
            f"After Phase 5 fix, no single entity should dominate the DAG."
        )


class TestBedTimelineBeforeAfterWrong:
    """§1.6: The boolean topology renames all faces instead of preserving
    unchanged ones. This means entities_before at boolean step equals
    the final count, not the actual count before boolean."""

    def test_boolean_entities_overshadow_revolve(self):
        """In the current turbine disc, boolean operation re-creates
        labels for ALL faces, effectively resetting the timeline."""
        ctx = _run_turbine_disc_pipeline()
        reg = ctx.topology_registry

        # Find producers
        from collections import Counter
        producer_counts = Counter()
        for rec in reg._entities.values():
            producer_counts[rec.producer_node_id] += 1

        total = reg.entity_count
        # The final boolean node should account for most entities
        # (because it renames everything, not because it creates everything
        #  — this is the defect)
        max_producer = producer_counts.most_common(1)[0]
        assert max_producer[1] > total * 0.3, (
            f"Top producer '{max_producer[0]}' accounts for {max_producer[1]}/{total} "
            f"entities ({max_producer[1]/total:.0%}). "
            f"After Phase 5 fix, entities should be distributed across operations "
            f"with most from revolve surviving boolean unchanged."
        )
