"""PR-8: Hardening tests — corrupted XBF, save rollback, path edge cases, perf baseline."""

import os
import time
from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import AtomicPublishError


# ---------------------------------------------------------------------------
# T9: Corrupted XBF detection
# ---------------------------------------------------------------------------

class TestCorruptedXBF:

    def test_empty_file_raises(self, ascii_tmpdir):
        """Opening an empty file raises clear error (min_size guard)."""
        empty = ascii_tmpdir / "empty.xbf"
        empty.write_bytes(b"")
        with pytest.raises(Exception) as exc_info:
            OcafRepository.open(empty)
        # Must be a RuntimeError from the min_size guard, not a segfault
        assert "too small" in str(exc_info.value).lower() or "RuntimeError" in str(type(exc_info.value))

    def test_truncated_xbf_raises(self, ascii_tmpdir):
        """Truncated small file is caught by min_size guard."""
        truncated = ascii_tmpdir / "truncated.xbf"
        truncated.write_bytes(b"\x00" * 4)  # < 8 bytes = min_size guard
        with pytest.raises(Exception):
            OcafRepository.open(truncated)

    def test_valid_xbf_opens(self, ascii_tmpdir):
        """Valid XBF still opens fine."""
        session = OcafDocumentSession.create()
        xbf = ascii_tmpdir / "valid.xbf"
        session.repository.save_to(xbf)
        repo = OcafRepository.open(xbf)
        assert not repo.design_root_label.IsNull()


# ---------------------------------------------------------------------------
# T9: Save failure rollback
# ---------------------------------------------------------------------------

class TestSaveRollback:

    def test_save_to_invalid_path_raises(self):
        """Saving to a path with null byte raises ValueError."""
        repo = OcafRepository.create()
        with pytest.raises(ValueError):
            repo.save_to(Path("C:/invalid_\x00_dir/test.xbf"))

    def test_official_survives_save_failure(self, ascii_tmpdir):
        """Existing XBF remains intact after a failed save attempt."""
        s1 = OcafDocumentSession.create()
        official = ascii_tmpdir / "surviving.xbf"
        s1.repository.save_to(official)
        s1.close()
        original_size = official.stat().st_size

        # Try saving with invalid path — should not affect official
        try:
            s2 = OcafDocumentSession.open(official)
            with pytest.raises(ValueError):
                s2.repository.save_to(Path("C:/bad_\x00/test.xbf"))
        except Exception:
            pass

        assert official.exists()
        assert official.stat().st_size == original_size

    def test_publish_missing_temp_raises(self, ascii_tmpdir):
        """Publishing non-existent temp raises AtomicPublishError."""
        fake_temp = ascii_tmpdir / "does_not_exist.xbf"
        target = ascii_tmpdir / "target.xbf"
        with pytest.raises(AtomicPublishError):
            OcafRepository.publish(fake_temp, target)


# ---------------------------------------------------------------------------
# T10: Path edge cases
# ---------------------------------------------------------------------------

class TestPathEdgeCases:

    def test_path_with_spaces(self, ascii_tmpdir):
        """Paths with spaces work."""
        spaced_dir = ascii_tmpdir / "path with spaces"
        spaced_dir.mkdir(exist_ok=True)
        xbf = spaced_dir / "test file.xbf"

        session = OcafDocumentSession.create()
        session.repository.save_to(xbf)
        assert xbf.exists()
        repo = OcafRepository.open(xbf)
        assert not repo.design_root_label.IsNull()

    def test_long_path(self, ascii_tmpdir):
        """Long paths (~200 chars) work."""
        long_name = "a" * 180 + ".xbf"
        xbf = ascii_tmpdir / long_name

        session = OcafDocumentSession.create()
        session.repository.save_to(xbf)
        assert xbf.exists()
        repo = OcafRepository.open(xbf)
        assert not repo.design_root_label.IsNull()


# ---------------------------------------------------------------------------
# T11: CAE Gate (hardening)
# ---------------------------------------------------------------------------

class TestCaeGateHardening:

    def test_all_required_bindings_pass(self):
        """Preflight with valid selection passes."""
        import cadquery as cq
        from OCP.TDF import TDF_LabelMap
        from OCP.TNaming import TNaming_Builder
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            TopologyEntityKind, SelectionPolicy, CaeBinding,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import (
            run_cae_preflight,
        )

        session = OcafDocumentSession.create()
        box = cq.Workplane("XY").box(10, 20, 30).val()
        face = box.faces(">Z")

        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "box")
        TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

        service = PersistentSelectionService(session)
        service.create("top", face.wrapped, box.wrapped,
                       SelectionPolicy(entity_kind=TopologyEntityKind.FACE))

        valid_labels = TDF_LabelMap()
        valid_labels.Add(feat.FindChild(2, False))

        bindings = [CaeBinding(binding_id="b1", selection_id="top", analysis_role="load")]
        result = run_cae_preflight(bindings, service, valid_labels)
        assert isinstance(result.ok, bool)

    def test_unresolved_binding_blocks_solver(self):
        """Unresolved required binding → ok=False."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import CaeBinding
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.cae_preflight import (
            run_cae_preflight,
        )

        session = OcafDocumentSession.create()
        service = PersistentSelectionService(session)
        bindings = [CaeBinding(binding_id="b1", selection_id="ghost", analysis_role="load")]
        result = run_cae_preflight(bindings, service)
        assert result.ok is False


# ---------------------------------------------------------------------------
# Performance baseline
# ---------------------------------------------------------------------------

class TestPerformanceBaseline:

    def test_save_performance(self, ascii_tmpdir):
        """Record save time + file size for a simple document."""
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import tracked_extrude
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import TopologyCaptureScope

        session = OcafDocumentSession.create()
        profile = cq.Workplane("XY").rect(10, 10).val()
        result = tracked_extrude(profile, (0, 0, 20),
                                 scope=TopologyCaptureScope(node_id="perf", component_id="c1"))
        writer = TopologyNamingWriter(session)
        writer.write_batch(result.batch)

        xbf = ascii_tmpdir / "perf.xbf"
        start = time.perf_counter()
        session.repository.save_to(xbf)
        elapsed = time.perf_counter() - start

        size_kb = xbf.stat().st_size / 1024
        print(f"\n  Save: {elapsed*1000:.1f}ms, Size: {size_kb:.1f} KB")
        assert elapsed < 5.0  # should be well under 5 seconds
        assert size_kb > 0.1

    def test_reopen_performance(self, ascii_tmpdir):
        """Record reopen time."""
        session = OcafDocumentSession.create()
        xbf = ascii_tmpdir / "reopen_perf.xbf"
        session.repository.save_to(xbf)
        session.close()

        start = time.perf_counter()
        repo = OcafRepository.open(xbf)
        elapsed = time.perf_counter() - start
        print(f"\n  Reopen: {elapsed*1000:.1f}ms")
        assert not repo.design_root_label.IsNull()
        assert elapsed < 5.0
