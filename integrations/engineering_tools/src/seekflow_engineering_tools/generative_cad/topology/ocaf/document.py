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
        # v6.0 §6.1: recover revision_number from lineage metadata
        meta = session.get_lineage_metadata()
        head_rev = meta.get("head_revision_number")
        session._revision_number = head_rev if head_rev is not None else 1
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

    @staticmethod
    def _attach_name(label, name: str) -> None:
        """Attach a TDataStd_Name to a label so OCAF persists it.

        Empty labels (no attributes) are silently dropped by SaveAs→Retrieve.
        Every dynamically-allocated label MUST have at least one attribute.
        """
        from OCP.TDataStd import TDataStd_Name
        from OCP.TCollection import TCollection_ExtendedString as TCE
        TDataStd_Name.Set_s(label, TCE(name))

    def ensure_component(self, component_id: str):
        """Get or create a component label with stable tag allocation.

        Uses StableLabelIndex.allocate() with namespace="lineage" for top-level components.
        Subsequent calls with the same component_id return the same label.
        """
        existing = self._label_index.resolve_key("component", "lineage", component_id)
        if existing is not None:
            label = existing.resolve_or_create(self.main_label)
            # Ensure the label persists (may have been dropped if empty)
            self._attach_name(label, f"Component:{component_id}")
            return label

        entry = self._label_index.allocate(
            "component", "lineage", component_id, self._revision_number
        )
        label = entry.tag_path.resolve_or_create(self.main_label)
        self._attach_name(label, f"Component:{component_id}")
        return label

    def ensure_feature(
        self, component_label, feature_id: str, component_id: str | None = None,
    ):
        """Get or create a feature label within a component.

        Uses StableLabelIndex.allocate_feature(). The feature namespace is
        ``component:<component_id>`` — derived from the explicit component_id
        argument, or reverse-looked-up from the component label's index entry.
        This makes feature identity semantic (and consistent with
        ensure_component), falling back to the component Tag only when the
        component has no index entry.
        """
        component_tag = component_label.Tag()
        if component_id is None:
            from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
                make_component_tagpath,
            )
            comp_entry = self._label_index.resolve_path(
                make_component_tagpath(component_tag),
            )
            if comp_entry is not None:
                component_id = comp_entry.key.object_id

        namespace = (
            f"component:{component_id}" if component_id is not None
            else f"component:{component_tag}"
        )
        existing = self._label_index.resolve_key("feature", namespace, feature_id)
        if existing is not None:
            label = existing.resolve_or_create(self.main_label)
            self._attach_name(label, f"Feature:{feature_id}")
            return label

        entry = self._label_index.allocate_feature(
            component_tag, namespace, feature_id, self._revision_number
        )
        label = entry.tag_path.resolve_or_create(self.main_label)
        self._attach_name(label, f"Feature:{feature_id}")
        return label

    # ------------------------------------------------------------------
    # Selection management
    # ------------------------------------------------------------------

    def ensure_selection(self, selection_id: str):
        """Get or create a selection label with stable tag allocation."""
        existing = self._label_index.resolve_key("selection", "lineage", selection_id)
        if existing is not None:
            label = existing.resolve_or_create(self.main_label)
            self._attach_name(label, f"Selection:{selection_id}")
            return label

        entry = self._label_index.allocate(
            "selection", "lineage", selection_id, self._revision_number
        )
        label = entry.tag_path.resolve_or_create(self.main_label)
        self._attach_name(label, f"Selection:{selection_id}")
        return label

    def collect_component_tnaming_labels(self, component_id: str):
        """Collect TNaming labels for a component's dependency closure.

        Scopes valid_labels to one component's feature subtree, avoiding the
        global (whole-document) collection for multi-component models.
        """
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            collect_tnaming_labels,
        )

        comp_label = self.ensure_component(component_id)
        return collect_tnaming_labels(comp_label)

    # ------------------------------------------------------------------
    # DesignRoot Metadata — v5.0 §7.2
    # ------------------------------------------------------------------

    def set_lineage_metadata(self, lineage_id: str, schema_version: str = "gcad_topo_v4@ocaf_v2") -> None:
        """Write lineage identity to DesignRoot Metadata (Tag 100:1)."""
        from OCP.TDataStd import TDataStd_AsciiString, TDataStd_Integer
        from OCP.TCollection import TCollection_AsciiString as TCAscii
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            META_TAG_SCHEMA_VERSION, META_TAG_LINEAGE_ID,
            META_TAG_HEAD_REVISION_ID, META_TAG_HEAD_REVISION_NUMBER,
        )

        meta = self.get_metadata_label()
        TDataStd_AsciiString.Set_s(
            meta.FindChild(META_TAG_SCHEMA_VERSION, True), TCAscii(schema_version))
        TDataStd_AsciiString.Set_s(
            meta.FindChild(META_TAG_LINEAGE_ID, True), TCAscii(lineage_id))
        TDataStd_Integer.Set_s(
            meta.FindChild(META_TAG_HEAD_REVISION_NUMBER, True), self._revision_number)

    def get_lineage_metadata(self) -> dict:
        """Read lineage identity from DesignRoot Metadata. Returns {} if unreadable."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            read_ascii_string, read_integer,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            META_TAG_SCHEMA_VERSION, META_TAG_LINEAGE_ID,
            META_TAG_HEAD_REVISION_ID, META_TAG_HEAD_REVISION_NUMBER,
        )

        meta = self.get_metadata_label()
        return {
            "schema_version": read_ascii_string(meta.FindChild(META_TAG_SCHEMA_VERSION, False)),
            "lineage_id": read_ascii_string(meta.FindChild(META_TAG_LINEAGE_ID, False)),
            "head_revision_id": read_ascii_string(meta.FindChild(META_TAG_HEAD_REVISION_ID, False)),
            "head_revision_number": read_integer(meta.FindChild(META_TAG_HEAD_REVISION_NUMBER, False)),
        }

    def write_revision_record(self, record) -> None:
        """Persist a RevisionRecord to Tag 100:6 (Revisions)."""
        import json
        from OCP.TDataStd import TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            REVISION_TAG_ENTRY_BASE, TAG_REVISIONS,
        )

        revisions_label = self.design_root_label.FindChild(TAG_REVISIONS, True)
        entry_tag = REVISION_TAG_ENTRY_BASE + record.revision_number
        rev_label = revisions_label.FindChild(entry_tag, True)
        TDataStd_AsciiString.Set_s(rev_label, TCAscii(json.dumps(record.to_dict())))

    # ------------------------------------------------------------------
    # Cross-revision shape retrieval — v5.0 §7.4
    # ------------------------------------------------------------------

    def get_current_result_shape(self, feature_label):
        """Read the CurrentResult TNaming_NamedShape from a feature label.

        Returns the TopoDS_Shape stored at Tag 2 (CurrentResult), or None.
        Used to retrieve the previous revision's result for Modify(old,new).
        """
        from OCP.TNaming import TNaming_Tool
        from OCP.TDF import TDF_AttributeIterator

        result_label = feature_label.FindChild(2, False)  # TAG_CURRENT_RESULT
        if result_label.IsNull():
            return None

        # Find TNaming_NamedShape via iterator (safe path)
        it = TDF_AttributeIterator(result_label)
        while it.More():
            attr = it.Value()
            if attr.DynamicType().Name() == "TNaming_NamedShape":
                current = TNaming_Tool.CurrentShape_s(attr)
                if current is not None:
                    return current
            it.Next()
        return None

    def get_current_role_result(self, feature_label, role_tag: int):
        """Read a role face's TNaming_NamedShape under ResultRoot (Tag 2).

        Returns the TopoDS_Shape stored at ResultRoot/<role_tag>, or None.
        Used to retrieve the previous revision's role face for Modify(old,new).
        """
        from OCP.TNaming import TNaming_Tool
        from OCP.TDF import TDF_AttributeIterator

        result_root = feature_label.FindChild(2, False)  # TAG_CURRENT_RESULT
        if result_root.IsNull():
            return None
        role_label = result_root.FindChild(role_tag, False)
        if role_label.IsNull():
            return None

        it = TDF_AttributeIterator(role_label)
        while it.More():
            attr = it.Value()
            if attr.DynamicType().Name() == "TNaming_NamedShape":
                current = TNaming_Tool.CurrentShape_s(attr)
                if current is not None:
                    return current
            it.Next()
        return None

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
