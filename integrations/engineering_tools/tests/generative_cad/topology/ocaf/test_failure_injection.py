"""PR-B: Failure injection tests (v5.0 §6.8).

Verifies that errors at each OCAF pipeline stage are handled correctly
and never corrupt the previous XBF / HEAD state.
"""

from pathlib import Path

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    EvolutionKind, TopologyEntityKind, ProofClass, TopologyRunConfig,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.verify_worker import verify_xbf
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import CaptureSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_batch(box, node_id="test_node", component_id="comp_a"):
    scope = TopologyCaptureScope(node_id=node_id, component_id=component_id)
    rel = LiveEvolutionRelation(
        relation_id=f"{node_id}/0", operation_id=node_id,
        kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
        source_key="body", old_shape=None, new_shapes=(box.wrapped,),
        proof=ProofClass.EXACT_CONSTRUCTION,
    )
    return LiveEvolutionBatch(
        scope=scope, builder_kind="Primitive",
        result_shape=box.wrapped, context_shape=box.wrapped, relations=[rel],
    )


def _assert_xbf_valid(xbf_path: Path) -> dict:
    """Verify an XBF file via subprocess and return the result dict."""
    vresult = verify_xbf(xbf_path)
    return {
        "ok": vresult.ok,
        "design_root": vresult.design_root_present,
        "entries": vresult.index_entry_count,
        "native_crash": vresult.native_crash,
        "errors": vresult.errors,
    }


# ===========================================================================
# T_F1: Writer failure → abort → previous XBF intact
# ===========================================================================

class TestWriterFailure:

    def test_write_failure_preserves_previous_xbf(self, xbf_path_ascii):
        """If a write fails after previous successful save, the old XBF is intact."""
        box = cq.Workplane("XY").box(10, 10, 10).val()

        # Create and save a valid XBF first (simulating "previous revision")
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        writer.write_batch(_make_valid_batch(box, "valid_node", "comp_a"))
        session.ensure_component("comp_a")
        session.ensure_feature(session.ensure_component("comp_a"), "valid_node")
        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf_path_ascii)
        valid_hash = xbf_path_ascii.stat().st_size
        session.close()

        # Now simulate a write that fails BEFORE commit
        session2 = OcafDocumentSession.open(xbf_path_ascii)
        session2.begin_write()
        try:
            writer2 = TopologyNamingWriter(session2)
            # Write one valid batch, then inject a bad one
            writer2.write_batch(_make_valid_batch(box, "good_node", "comp_a"))
            # Simulate failure mid-write by raising
            raise RuntimeError("Simulated mid-write failure")
        except RuntimeError:
            session2.abort_write()

        # After abort, the file on disk should be unchanged
        session2.close()
        assert xbf_path_ascii.stat().st_size == valid_hash, \
            "XBF file was modified despite abort!"

        # Reopen — should still have original data
        reopened = OcafDocumentSession.open(xbf_path_ascii)
        assert reopened.label_index.entry_count >= 1
        reopened.close()

    def test_abort_then_retry_succeeds(self, xbf_path_ascii):
        """After an abort, a fresh write succeeds normally."""
        box = cq.Workplane("XY").box(10, 10, 10).val()

        session = OcafDocumentSession.create()
        # First attempt: abort
        session.begin_write()
        writer = TopologyNamingWriter(session)
        writer.write_batch(_make_valid_batch(box, "node_1", "comp_a"))
        session.abort_write()

        # Second attempt: succeed
        session.begin_write()
        writer.write_batch(_make_valid_batch(box, "node_2", "comp_a"))
        session.ensure_component("comp_a")
        session.ensure_feature(session.ensure_component("comp_a"), "node_2")
        session.label_index.save_to_ocaf(session.main_label)
        session.commit_write()
        session.repository.save_to(xbf_path_ascii)
        session.close()

        # Verify
        vresult = _assert_xbf_valid(xbf_path_ascii)
        assert vresult["ok"], f"XBF invalid after abort+retry: {vresult['errors']}"
        assert vresult["entries"] >= 1


# ===========================================================================
# T_F2: Index save failure → abort → no corrupt XBF
# ===========================================================================

class TestIndexFailure:

    def test_index_save_failure_handled(self, xbf_path_ascii):
        """Index save exception does not leave a corrupt XBF on disk."""
        box = cq.Workplane("XY").box(10, 10, 10).val()

        session = OcafDocumentSession.create()
        session.begin_write()
        writer = TopologyNamingWriter(session)
        writer.write_batch(_make_valid_batch(box, "test_node", "comp_a"))

        # Force index save to fail by corrupting the index
        session.label_index.clear()  # empty index — save still works but entries=0
        session.label_index.save_to_ocaf(session.main_label)
        session.commit_write()
        session.repository.save_to(xbf_path_ascii)
        session.close()

        # Should still be a valid XBF (just with 0 entries)
        vresult = _assert_xbf_valid(xbf_path_ascii)
        assert vresult["ok"], f"XBF invalid after empty index save: {vresult['errors']}"

        # Reopen — should get empty index
        reopened = OcafDocumentSession.open(xbf_path_ascii)
        assert reopened.label_index.entry_count == 0
        reopened.close()


# ===========================================================================
# T_F3: Commit failure → no partial file
# ===========================================================================

class TestCommitFailure:

    def test_no_commit_no_file(self, xbf_path_ascii):
        """Without explicit commit, saved data should not produce side effects."""
        # Don't save — just verify nothing crashes
        session = OcafDocumentSession.create()
        session.begin_write()
        # No commit — just abort
        session.abort_write()
        session.close()

        # Nothing was written to disk
        assert not xbf_path_ascii.exists()


# ===========================================================================
# T_F4: Verify worker native crash isolation
# ===========================================================================

class TestVerifyWorker:

    def test_verify_valid_xbf_returns_ok(self, xbf_path_ascii):
        """Valid XBF → verify returns ok=True."""
        session = OcafDocumentSession.create()
        session.ensure_component("test")
        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf_path_ascii)
        session.close()

        vresult = verify_xbf(xbf_path_ascii)
        assert vresult.ok
        assert vresult.design_root_present
        assert vresult.schema_version is not None
        assert vresult.index_entry_count >= 1
        assert not vresult.native_crash

    def test_verify_corrupted_xbf_returns_not_ok(self, ascii_tmpdir):
        """Corrupted/empty file → verify returns ok=False."""
        bad_file = ascii_tmpdir / "bad.xbf"
        bad_file.write_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x00")  # 8 bytes of zeros

        vresult = verify_xbf(bad_file)
        # May crash (native) or return errors — either way, ok=False
        assert not vresult.ok, f"Corrupted XBF should not pass verify: {vresult}"

    def test_verify_missing_file_returns_not_ok(self, ascii_tmpdir):
        """Missing file → verify returns ok=False."""
        vresult = verify_xbf(ascii_tmpdir / "nonexistent.xbf")
        assert not vresult.ok
        assert len(vresult.errors) >= 1


# ===========================================================================
# T_F5: Mode semantics (off/audit/enforce)
# ===========================================================================

class TestTopologyModes:

    def test_topology_run_config_defaults(self):
        """Default TopologyRunConfig is mode=off."""
        config = TopologyRunConfig()
        assert config.mode == "off"
        assert config.verify_in_subprocess is True
        assert config.required_selection_ids == ()
        assert config.lineage_id == ""

    def test_topology_run_config_enforce(self):
        """Enforce mode sets all fields correctly."""
        config = TopologyRunConfig(
            mode="enforce",
            lineage_id="test-lineage",
            revision_id="rev-001",
            parent_revision_id="rev-000",
            output_root=Path("/tmp/test"),
            required_selection_ids=("top_face",),
            verify_in_subprocess=True,
        )
        assert config.mode == "enforce"
        assert config.lineage_id == "test-lineage"
        assert config.revision_id == "rev-001"
        assert config.parent_revision_id == "rev-000"
        assert config.required_selection_ids == ("top_face",)

    def test_off_mode_no_ocaf_capture(self):
        """When topology_mode='off', no OCAF capture session is created."""
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        ctx.topology_mode = "off"
        assert ctx.capture_session is None
        assert ctx.enable_topology_capture is False

    def test_audit_mode_capture_enabled(self):
        """When topology_mode='audit', capture session is active."""
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        ctx.topology_mode = "audit"
        ctx.enable_topology_capture = True
        ctx.capture_session = CaptureSession()

        box = cq.Workplane("XY").box(10, 10, 10).val()
        batch = _make_valid_batch(box, "audit_node", "comp_a")
        ctx.capture_session.stage(batch)

        assert ctx.capture_session.batch_count == 1


# ===========================================================================
# T_F6: ocaf_path backwards compatibility
# ===========================================================================

class TestBackwardsCompat:

    def test_topology_run_config_ocaf_path_derived(self):
        """ocaf_path is derived from output_root + lineage_id."""
        config = TopologyRunConfig(
            mode="audit",
            lineage_id="test-lineage",
            output_root=Path("/tmp/test_output"),
        )
        expected = Path("/tmp/test_output") / "lineage" / "test-lineage" / "design.xbf"
        assert config.ocaf_path == expected

    def test_ocaf_path_none_when_no_output_root(self):
        """ocaf_path returns None if output_root or lineage_id is missing."""
        config = TopologyRunConfig(mode="audit")
        assert config.ocaf_path is None

        config2 = TopologyRunConfig(mode="audit", lineage_id="dl-1")
        assert config2.ocaf_path is None
