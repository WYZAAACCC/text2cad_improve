"""v6.0 PR-5: Immutable Revision Bundle tests (v6.0 §7)."""

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.ocaf.revision_store import RevisionStore


class TestRevisionStore:

    def test_init_creates_directories(self, ascii_tmpdir):
        """init_lineage creates the lineage and revisions directories."""
        store = RevisionStore(output_root=ascii_tmpdir, lineage_id="test-lineage")
        store.init_lineage()
        assert store.lineage_dir.exists()
        assert store.revisions_dir.exists()

    def test_head_roundtrip(self, ascii_tmpdir):
        """HEAD.json write → read returns same data."""
        store = RevisionStore(output_root=ascii_tmpdir, lineage_id="test-lineage")
        store.init_lineage()
        store.write_head("rev-000003", 3)
        head = store.read_head()
        assert head is not None
        assert head["head_revision_id"] == "rev-000003"
        assert head["head_revision_number"] == 3
        assert head["lineage_id"] == "test-lineage"

    def test_head_defaults_when_missing(self, ascii_tmpdir):
        """When no HEAD.json, head_revision_number returns 0."""
        store = RevisionStore(output_root=ascii_tmpdir, lineage_id="no-head")
        store.init_lineage()
        assert store.head_revision_number == 0
        assert store.head_revision_id is None

    def test_revision_not_overwritten(self, ascii_tmpdir):
        """Publishing to an existing revision raises FileExistsError."""
        store = RevisionStore(output_root=ascii_tmpdir, lineage_id="test-immutable")
        store.init_lineage()

        staging = store.staging_dir(1)
        staging.mkdir(parents=True)
        (staging / "design.xbf").write_bytes(b"dummy xbf")

        # First publish succeeds
        store.publish_revision(staging, 1)
        assert store.revision_dir(1).exists()

        # Second publish to same revision → error
        staging2 = store.staging_dir(1)
        staging2.mkdir(parents=True)
        (staging2 / "design.xbf").write_bytes(b"another xbf")
        try:
            store.publish_revision(staging2, 1)
            assert False, "Should have raised FileExistsError"
        except FileExistsError:
            pass  # expected

    def test_revision_format(self):
        """Revision IDs follow rev-NNNNNN format."""
        assert RevisionStore.format_revision_id(1) == "rev-000001"
        assert RevisionStore.format_revision_id(42) == "rev-000042"
        assert RevisionStore.format_revision_id(999999) == "rev-999999"
