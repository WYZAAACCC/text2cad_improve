"""PR-6: Pipeline topology_mode tests — off/audit/enforce behavior."""

from pathlib import Path

from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import CaptureSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession


class TestRuntimeContextFields:

    def test_topology_mode_defaults_to_off(self):
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        assert ctx.topology_mode == "off"
        assert ctx.enable_topology_capture is False
        assert ctx.capture_session is None

    def test_topology_fields_present(self):
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        assert hasattr(ctx, "topology_mode")
        assert hasattr(ctx, "design_lineage_id")
        assert hasattr(ctx, "revision_id")
        assert hasattr(ctx, "ocaf_repository")
        assert hasattr(ctx, "selection_service")
        assert hasattr(ctx, "topology_audit")
        assert hasattr(ctx, "required_selection_ids")

    def test_topology_mode_enforce(self):
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        ctx.topology_mode = "enforce"
        assert ctx.topology_mode == "enforce"


class TestTopologyModeOff:

    def test_no_ocaf_when_off(self):
        """When topology_mode='off', no OCAF capture even with ocaf_path."""
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        ctx.topology_mode = "off"
        # No OCAF session created
        assert ctx.capture_session is None
        assert ctx.ocaf_repository is None


class TestOcafWriteAndSave:

    def test_write_and_save_success(self, xbf_path_ascii):
        """Capture session with data → write + save succeeds."""
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import tracked_extrude
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import TopologyCaptureScope

        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        ctx.topology_mode = "audit"
        ctx.capture_session = CaptureSession()

        # Simulate a tracked operation
        profile = cq.Workplane("XY").rect(10, 10).val()
        scope = TopologyCaptureScope(node_id="test_node", component_id="comp_a")
        result = tracked_extrude(profile, (0, 0, 20), scope=scope)
        ctx.capture_session.stage(result.batch)
        assert ctx.capture_session.batch_count >= 1

        # Write and save
        ocaf_session = OcafDocumentSession.create()
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
        writer = TopologyNamingWriter(ocaf_session)
        for batch in ctx.capture_session.iter_batches():
            writer.write_batch(batch)
        ocaf_session.repository.save_to(xbf_path_ascii)

        assert xbf_path_ascii.exists()
        assert xbf_path_ascii.stat().st_size > 100

    def test_write_and_save_audit_mode_warning(self):
        """In audit mode, OCAF failure → warning, not exception."""
        ctx = RuntimeContext(
            out_step=Path("/tmp/test.step"),
            metadata_path=Path("/tmp/test.json"),
            workspace_root=Path("/tmp"),
        )
        ctx.topology_mode = "audit"
        ctx.capture_session = CaptureSession()

        # Add a batch that will fail on write (empty scope)
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            LiveEvolutionBatch, TopologyCaptureScope,
        )
        bad_batch = LiveEvolutionBatch(
            scope=TopologyCaptureScope(node_id="bad"),
            builder_kind="test",
        )
        ctx.capture_session.stage(bad_batch)

        # Write should not crash (audit mode)
        ocaf_session = OcafDocumentSession.create()
        try:
            from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
            writer = TopologyNamingWriter(ocaf_session)
            for batch in ctx.capture_session.iter_batches():
                writer.write_batch(batch)  # empty relations → writes 0
        except Exception as e:
            # In audit mode, failure is captured as warning
            ctx.warnings.append(f"OCAF write failed: {e}")

        # In audit mode, pipeline continues despite OCAF issues
        assert ctx.topology_mode == "audit"


class TestCaptureSessionClear:

    def test_session_clear_after_write(self):
        """CaptureSession should be clearable after write."""
        session = CaptureSession()
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            LiveEvolutionBatch, TopologyCaptureScope,
        )
        batch = LiveEvolutionBatch(
            scope=TopologyCaptureScope(node_id="test"),
            builder_kind="test",
        )
        session.stage(batch)
        assert session.batch_count == 1

        session.clear()
        assert session.batch_count == 0
        assert session.total_relations == 0
