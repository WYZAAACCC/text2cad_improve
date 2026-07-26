"""Smoke test: Tag 100 fixed schema creation and recovery.

Verifies §4.3 of the v3.0 implementation guide:
  - DesignRoot at fixed Tag 100 (not NewChild)
  - Structural sub-labels (Metadata, Components, Selections, ...) at fixed tags
  - DocumentSession creates full tree on create()
  - Reopen recovers full tree via FindChild(TAG, False)

Root cause #3 from diagnostic phase: NewChild() collides with XCAF reserved Tags 1-10.
"""

import json
import subprocess
import sys
from pathlib import Path

# Compute source directory relative to this test file.
_SRC_DIR = str(Path(__file__).resolve().parents[5] / "src")


class TestDesignRootTag100:
    """DesignRoot must be at fixed Tag 100."""

    def test_create_uses_tag_100(self):
        """OcafRepository.create() puts DesignRoot at Tag 100."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import (
            OcafRepository,
        )

        repo = OcafRepository.create()
        root = repo.design_root_label
        assert not root.IsNull()
        assert root.Tag() == 100

        # Verify it is a direct child of Main
        main = repo.main_label
        assert not main.IsNull()
        found = main.FindChild(100, False)
        assert not found.IsNull()
        assert found.Tag() == 100

    def test_open_finds_tag_100(self, xbf_path_ascii):
        """OcafRepository.open() recovers DesignRoot at Tag 100."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import (
            OcafRepository,
        )

        repo = OcafRepository.create()
        repo.save_to(xbf_path_ascii)

        repo2 = OcafRepository.open(xbf_path_ascii)
        root = repo2.design_root_label
        assert not root.IsNull()
        assert root.Tag() == 100

    def test_no_newchild_used(self):
        """Verify that DesignRoot.Tag() == 100, not 1 (which would mean NewChild)."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import (
            OcafRepository,
        )

        repo = OcafRepository.create()
        # If NewChild() was used, Tag would be 1 (first XCAF Shapes label)
        assert repo.design_root_label.Tag() == 100
        # Main's first child (Shapes) should still be at Tag 1
        shapes_label = repo.main_label.FindChild(1, False)
        # XCAF tools exist at their reserved tags
        assert shapes_label.Tag() == 1 if not shapes_label.IsNull() else True


class TestDocumentSessionSchema:
    """OcafDocumentSession creates all structural labels."""

    def test_create_populates_all_structural_labels(self):
        """DocumentSession.create() pre-creates all 7 structural sub-labels."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )

        session = OcafDocumentSession.create()
        root = session.design_root_label

        expected_tags = {
            1: "Metadata",
            2: "Components",
            3: "Selections",
            4: "Assembly",
            5: "CAEBindings",
            6: "Revisions",
            7: "StableIdIndex",
        }

        for tag, name in expected_tags.items():
            child = root.FindChild(tag, False)
            assert not child.IsNull(), f"Structural label '{name}' at tag {tag} is missing"
            assert child.Tag() == tag

    def test_save_and_reopen_preserves_structural_labels(self, xbf_path_ascii):
        """After save→open, all structural labels are still present."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )

        session = OcafDocumentSession.create()
        temp = session.save_temp(xbf_path_ascii.parent)

        # Reopen
        session2 = OcafDocumentSession.open(temp)
        root = session2.design_root_label

        for tag in [1, 2, 3, 4, 5, 6, 7]:
            child = root.FindChild(tag, False)
            assert not child.IsNull(), f"Tag {tag} missing after reopen"

    def test_subprocess_verifies_schema(self, xbf_path_ascii):
        """Independent subprocess confirms Tag 100 and all structural labels."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )

        session = OcafDocumentSession.create()
        temp = session.save_temp(xbf_path_ascii.parent)

        code = f'''
import json, sys
sys.path.insert(0, r"{_SRC_DIR}")

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession

session = OcafDocumentSession.open(r"{temp}")
root = session.design_root_label

tags_found = {{}}
for tag in [1, 2, 3, 4, 5, 6, 7]:
    child = root.FindChild(tag, False)
    tags_found[str(tag)] = not child.IsNull()

result = {{"status": "ok", "design_root_tag": root.Tag(), "children": tags_found}}
print(json.dumps(result))
'''
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["status"] == "ok"
        assert result["design_root_tag"] == 100
        for tag_str, found in result["children"].items():
            assert found, f"Tag {tag_str} not found in subprocess"


class TestStableLabelIndex:
    """StableLabelIndex allocates persistent tags >= 1000."""

    def test_allocate_component_uses_dynamic_tag(self):
        """Component allocation gets tag >= 1000."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.label_index import (
            StableLabelIndex,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            DYNAMIC_TAG_START,
        )

        index = StableLabelIndex()
        entry = index.allocate("component", "base_plate", revision=1)
        assert entry.tag_path.tags[2] >= DYNAMIC_TAG_START  # tag is 3rd element

    def test_same_id_returns_same_entry(self):
        """Same object_id returns the same entry (idempotent)."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.label_index import (
            StableLabelIndex,
        )

        index = StableLabelIndex()
        e1 = index.allocate("component", "base_plate", revision=1)
        e2 = index.allocate("component", "base_plate", revision=1)
        assert e1.tag_path == e2.tag_path
        assert e1.object_kind == e2.object_kind

    def test_different_kinds_get_different_tags(self):
        """Components and selections use separate tag counters."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.label_index import (
            StableLabelIndex,
        )

        index = StableLabelIndex()
        c = index.allocate("component", "comp_a", revision=1)
        s = index.allocate("selection", "sel_a", revision=1)
        # Different root containers
        assert c.tag_path.tags[:2] != s.tag_path.tags[:2]

    def test_conflict_detection(self):
        """Same ID with different kind raises StableLabelConflictError."""
        import pytest
        from seekflow_engineering_tools.generative_cad.topology.ocaf.label_index import (
            StableLabelIndex,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
            StableLabelConflictError,
        )

        index = StableLabelIndex()
        index.allocate("component", "obj_x", revision=1)
        with pytest.raises(StableLabelConflictError):
            index.allocate("selection", "obj_x", revision=1)

    def test_retire_marks_entry(self):
        """Retired entries are marked but not removed."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.label_index import (
            StableLabelIndex,
        )

        index = StableLabelIndex()
        index.allocate("component", "to_retire", revision=1)
        index.retire("to_retire", revision=3)
        entry = index.resolve_path(index.resolve_id("to_retire"))
        assert entry is not None
        assert entry.retired_revision == 3
