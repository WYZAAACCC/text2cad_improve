"""OcafDocumentSession — per-revision OCAF document session.

Wraps OcafRepository for the common pipeline use case: open a lineage document
(or create one), write one revision's topology data, save to temp, verify in
a subprocess, and atomically publish.

This module is the primary entry point for pipeline code. It delegates to:
- OcafRepository (create/open/save/publish)
- StableLabelIndex (object_id → TagPath mapping)
- schema.py (fixed Tag tree)

All bugs from the previous implementation have been fixed (§3.1 of v3.0 guide):
  - ❌ doc.Main().NewChild() → ✅ FindChild(DESIGN_ROOT_TAG, True)
  - ❌ TCollection_ExtendedString(str) → ✅ ext_utf8(path)
  - ❌ app.Open(path, doc) → ✅ app.Retrieve(folder, name, True)
  - ❌ DesignRoot = doc.Main() on reopen → ✅ FindChild(TAG, False)
  - ❌ save() overwrites official target → ✅ save_temp() + publish()
  - ❌ fsync exceptions swallowed → ✅ structured error types
  - ❌ get_or_create always creates → ✅ label_index.allocate()
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import ext_utf8
from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
    OcafRetrieveError,
    OcafSchemaError,
    OcafStoreError,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.label_index import StableLabelIndex
from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    DESIGN_ROOT_TAG,
    TAGPATH_COMPONENTS,
    TAGPATH_METADATA,
    TAGPATH_SELECTIONS,
    TAGPATH_STABLE_ID_INDEX,
    TagPath,
)


@dataclass
class OcafDocumentSession:
    """Per-revision session for reading and writing OCAF topology data.

    Wraps an OcafRepository and a StableLabelIndex. This is the primary
    API that pipeline code should use.

    Usage:
        # Create new lineage
        session = OcafDocumentSession.create()
        comp_label = session.ensure_component("base_plate")
        feat_label = session.ensure_feature(comp_label, "extrude_1")
        # ... write TNaming data to feat_label ...
        temp = session.save_temp()
        session.publish(temp, Path("design.xbf"))

        # Reopen existing lineage
        session = OcafDocumentSession.open(Path("design.xbf"))
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _repository: OcafRepository | None = field(default=None, repr=False)
    _label_index: StableLabelIndex = field(default_factory=StableLabelIndex)
    _revision_number: int = 1

    # ------------------------------------------------------------------
    # Factory: create new
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, revision_number: int = 1) -> OcafDocumentSession:
        """Create a new OCAF document with fixed schema structure.

        Initialises DesignRoot and all structural sub-labels (Metadata, Components,
        Selections, Assembly, CAEBindings, Revisions, StableIdIndex).

        IMPORTANT: Every label MUST have at least one attribute (e.g. TDataStd_Name)
        or OCAF serialization will silently drop it on SaveAs→Retrieve.
        """
        from OCP.TDataStd import TDataStd_Name
        from OCP.TCollection import TCollection_ExtendedString as TCE

        repo = OcafRepository.create()

        # Pre-create all structural labels with Name attributes so they persist
        _name = TDataStd_Name.Set_s
        _name(repo.design_root_label.FindChild(1, True), TCE("Metadata"))
        _name(repo.design_root_label.FindChild(2, True), TCE("Components"))
        _name(repo.design_root_label.FindChild(3, True), TCE("Selections"))
        _name(repo.design_root_label.FindChild(4, True), TCE("Assembly"))
        _name(repo.design_root_label.FindChild(5, True), TCE("CAEBindings"))
        _name(repo.design_root_label.FindChild(6, True), TCE("Revisions"))
        _name(repo.design_root_label.FindChild(7, True), TCE("StableIdIndex"))

        session = cls.__new__(cls)
        session.session_id = uuid.uuid4().hex[:12]
        session._repository = repo
        session._label_index = StableLabelIndex()
        session._revision_number = revision_number
        return session

    # ------------------------------------------------------------------
    # Factory: open existing
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> OcafDocumentSession:
        """Open an existing OCAF document for reading/writing.

        Uses Retrieve() (not Open()) and verifies the DesignRoot at Tag 100.

        Raises:
            FileNotFoundError: if path doesn't exist
            OcafRetrieveError: if document can't be read
            OcafSchemaError: if DesignRoot tag 100 is missing
        """
        repo = OcafRepository.open(path)

        session = cls.__new__(cls)
        session.session_id = uuid.uuid4().hex[:12]
        session._repository = repo
        # P0-02: rebuild index from OCAF, not empty
        index = StableLabelIndex()
        index.load_from_ocaf(repo.main_label)
        session._label_index = index
        session._revision_number = 1  # caller should update from Metadata
        return session

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def repository(self) -> OcafRepository:
        if self._repository is None:
            raise RuntimeError("OcafDocumentSession is closed")
        return self._repository

    @property
    def label_index(self) -> StableLabelIndex:
        return self._label_index

    @property
    def design_root_label(self):
        """The DesignRoot TDF_Label (Tag 100)."""
        return self.repository.design_root_label

    @property
    def main_label(self):
        """The Main() TDF_Label."""
        return self.repository.main_label

    @property
    def revision_number(self) -> int:
        return self._revision_number

    # ------------------------------------------------------------------
    # Structural label access
    # ------------------------------------------------------------------

    def get_metadata_label(self):
        """Get the Metadata label (Tag 100:1)."""
        return self.repository.get_or_create_child(self.design_root_label, 1)

    def get_components_label(self):
        """Get the Components container label (Tag 100:2)."""
        return self.repository.get_or_create_child(self.design_root_label, 2)

    def get_selections_label(self):
        """Get the Selections container label (Tag 100:3)."""
        return self.repository.get_or_create_child(self.design_root_label, 3)

    def get_stable_id_index_label(self):
        """Get the StableIdIndex label (Tag 100:7)."""
        return self.repository.get_or_create_child(self.design_root_label, 7)

    # ------------------------------------------------------------------
    # Component and Feature management
    # ------------------------------------------------------------------

    def ensure_component(self, component_id: str):
        """Get or create a component label with stable tag allocation.

        Uses StableLabelIndex.allocate() with namespace="lineage" for top-level components.
        Subsequent calls with the same component_id return the same label.
        """
        existing = self._label_index.resolve_key("component", "lineage", component_id)
        if existing is not None:
            return existing.resolve_or_create(self.main_label)

        entry = self._label_index.allocate(
            "component", "lineage", component_id, self._revision_number
        )
        return entry.tag_path.resolve_or_create(self.main_label)

    def ensure_feature(self, component_label, feature_id: str):
        """Get or create a feature label within a component.

        Uses StableLabelIndex.allocate_feature() with namespace="component:<id>".
        The component_label must be the result of ensure_component().
        """
        component_tag = component_label.Tag()
        namespace = f"component:{component_tag}"
        existing = self._label_index.resolve_key("feature", namespace, feature_id)
        if existing is not None:
            return existing.resolve_or_create(self.main_label)

        entry = self._label_index.allocate_feature(
            component_tag, namespace, feature_id, self._revision_number
        )
        return entry.tag_path.resolve_or_create(self.main_label)

    # ------------------------------------------------------------------
    # Selection management
    # ------------------------------------------------------------------

    def ensure_selection(self, selection_id: str):
        """Get or create a selection label with stable tag allocation."""
        existing = self._label_index.resolve_key("selection", "lineage", selection_id)
        if existing is not None:
            return existing.resolve_or_create(self.main_label)

        entry = self._label_index.allocate(
            "selection", "lineage", selection_id, self._revision_number
        )
        return entry.tag_path.resolve_or_create(self.main_label)

    # ------------------------------------------------------------------
    # Transaction helpers
    # ------------------------------------------------------------------

    def begin_write(self) -> None:
        """Start a new OCAF transaction."""
        self.repository.begin_txn()

    def commit_write(self) -> None:
        """Commit the current OCAF transaction."""
        self.repository.commit_txn()

    def abort_write(self) -> None:
        """Abort the current OCAF transaction."""
        self.repository.abort_txn()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_temp(self, parent_dir: Path | None = None) -> Path:
        """Save the document to a temporary XBF file.

        Does NOT overwrite any official file. Use publish() to atomically promote.
        """
        return self.repository.save_temp(parent_dir)

    @staticmethod
    def publish(temp_path: Path, official_path: Path) -> Path:
        """Atomically publish a temp XBF to the official location."""
        return OcafRepository.publish(temp_path, official_path)

    def close(self) -> None:
        """Release the underlying document."""
        if self._repository is not None:
            self._repository.close()
            self._repository = None
