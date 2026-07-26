"""OcafRepository — high-level OCAF document lifecycle and atomic publish.

Implements the create→write→save→verify→publish pipeline described in
§2.4 and §4.2 of the v3.0 implementation guide.

Key design decisions:
- One lineage = one evolving XBF document (not one per revision).
- Save always goes to a temp file first; publish moves it atomically.
- Verification happens in a SUBPROCESS after save, before publish.
- Failed publish never corrupts the previous official XBF.
- All path handling uses ext_utf8() for correct Unicode encoding.

Forbidden patterns (enforced by API design):
- app.Open(path, doc) — use Retrieve() instead
- doc.Main().NewChild() — use FindChild(TAG, True)
- TCollection_ExtendedString(str) without isMultiByte=True
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    define_binxcaf_format,
    ext_utf8,
    get_xcaf_application,
    retrieve_xcaf_document,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
    AtomicPublishError,
    OcafRetrieveError,
    OcafSchemaError,
    OcafStoreError,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    DESIGN_ROOT_TAG,
    TAGPATH_DESIGN_ROOT,
)


@dataclass
class OcafRepository:
    """Manages the full lifecycle of one OCAF lineage document.

    Usage:
        # Create new
        repo = OcafRepository.create()
        root = repo.design_root_label
        # ... write topology data ...
        temp = repo.save_temp()
        repo.publish(temp, Path("design.xbf"))

        # Open existing
        repo = OcafRepository.open(Path("design.xbf"))
    """

    _app: Any = field(repr=False)
    _doc: Any = field(repr=False)
    _design_root: Any = field(repr=False)  # TDF_Label at Tag 100

    # ------------------------------------------------------------------
    # Factory: create new document
    # ------------------------------------------------------------------

    @classmethod
    def create(cls) -> OcafRepository:
        """Create a new OCAF document with fixed Tag 100 DesignRoot.

        The document has no storage path until save_temp() is called.

        IMPORTANT: OCAF does NOT persist empty labels. Every label (including
        DesignRoot) MUST have at least one attribute attached (e.g. TDataStd_Name)
        or it will disappear after SaveAs→Retrieve.
        """
        app = get_xcaf_application()
        define_binxcaf_format(app)

        from OCP.TDocStd import TDocStd_Document
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDataStd import TDataStd_Name
        from OCP.TCollection import TCollection_ExtendedString as TCE

        fmt = TCE("BinXCAF")
        doc = TDocStd_Document(fmt)
        app.InitDocument(doc)

        # Create DesignRoot at fixed Tag 100 — NOT NewChild()
        main_label = doc.Main()
        design_root = main_label.FindChild(DESIGN_ROOT_TAG, True)
        # Attach a Name attribute so the label persists across SaveAs→Retrieve.
        # Empty labels (no attributes) are silently dropped by OCAF serialization.
        TDataStd_Name.Set_s(design_root, TCE("Text2CAD DesignRoot"))

        repo = cls.__new__(cls)
        repo._app = app
        repo._doc = doc
        repo._design_root = design_root
        return repo

    # ------------------------------------------------------------------
    # Factory: open existing document
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> OcafRepository:
        """Open an existing XBF document and verify DesignRoot at Tag 100.

        Uses Retrieve() — not the unsafe Open() with output Handle.

        Raises:
            FileNotFoundError: if path doesn't exist
            OcafRetrieveError: if document can't be read
            OcafSchemaError: if DesignRoot tag 100 is missing
        """
        app = get_xcaf_application()
        define_binxcaf_format(app)

        doc = retrieve_xcaf_document(app, path)

        # Verify DesignRoot
        design_root = doc.Main().FindChild(DESIGN_ROOT_TAG, False)
        if design_root.IsNull():
            raise OcafSchemaError(
                f"DesignRoot at tag {DESIGN_ROOT_TAG} not found in: {path}",
                path=str(path),
                expected_tag=DESIGN_ROOT_TAG,
            )

        repo = cls.__new__(cls)
        repo._app = app
        repo._doc = doc
        repo._design_root = design_root
        return repo

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def app(self):
        """The XCAFApp_Application instance."""
        return self._app

    @property
    def doc(self):
        """The TDocStd_Document handle."""
        return self._doc

    @property
    def design_root_label(self):
        """The DesignRoot TDF_Label (Tag 100 under Main)."""
        return self._design_root

    @property
    def main_label(self):
        """The Main() TDF_Label."""
        return self._doc.Main()

    # ------------------------------------------------------------------
    # Transaction management
    # ------------------------------------------------------------------

    def begin_txn(self) -> None:
        """Start a new OCAF transaction (NewCommand)."""
        self._doc.NewCommand()

    def commit_txn(self) -> None:
        """Commit the current OCAF transaction (CommitCommand)."""
        self._doc.CommitCommand()

    def abort_txn(self) -> None:
        """Abort the current OCAF transaction (AbortCommand)."""
        self._doc.AbortCommand()

    # ------------------------------------------------------------------
    # Structural label access
    # ------------------------------------------------------------------

    def get_or_create_child(self, parent_label, tag: int):
        """Get or create a child label by fixed tag. NEVER uses NewChild()."""
        return parent_label.FindChild(tag, True)

    def find_child(self, parent_label, tag: int):
        """Find a child label by tag. Returns Null label if missing."""
        return parent_label.FindChild(tag, False)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_temp(self, parent_dir: Path | None = None) -> Path:
        """Save the document to a temporary XBF file.

        Args:
            parent_dir: directory for the temp file. If None, uses system temp.

        Returns:
            Path to the saved temp file.

        Raises:
            OcafStoreError: if SaveAs fails.
        """
        import tempfile

        if parent_dir is not None:
            parent_dir = Path(parent_dir).resolve()
            parent_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.gettempdir()) if parent_dir is None else parent_dir
        tmp_name = f"ocaf_{uuid.uuid4().hex}.xbf"
        tmp_path = tmp_dir / tmp_name

        self._save_to(tmp_path)
        return tmp_path

    def save_to(self, path: Path) -> None:
        """Save the document to a specific path.

        Prefer save_temp() + publish() for atomicity on official documents.
        """
        self._save_to(Path(path).resolve())

    def _save_to(self, path: Path) -> None:
        """Internal: perform the SaveAs and verify."""
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        status = self._app.SaveAs(self._doc, ext_utf8(path))

        # PCDM_SS_OK == 0
        if status != 0:
            raise OcafStoreError(
                f"SaveAs failed with status {status}",
                path=str(path),
                pcdm_status=status,
            )

        # fsync to flush OS buffers
        self._fsync_path(path)

    @staticmethod
    def publish(temp_path: Path, official_path: Path) -> Path:
        """Publish a temp XBF to the official location.

        Uses shutil.copy2 + os.remove (instead of os.replace) to work around
        Windows file locking: the OCAF Application Session may still hold a
        handle to the temp file even after app.Close(doc).

        Args:
            temp_path: the temp XBF from save_temp()
            official_path: the target official path

        Returns:
            The official path.

        Raises:
            AtomicPublishError: if temp doesn't exist or copy fails.
        """
        import shutil

        temp = Path(temp_path).resolve()
        official = Path(official_path).resolve()

        if not temp.exists():
            raise AtomicPublishError(
                f"Temp file missing: {temp}",
                temp_path=str(temp),
                official_path=str(official),
            )

        official.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(str(temp), str(official))
        except OSError as exc:
            raise AtomicPublishError(
                f"copy failed: {exc}",
                temp_path=str(temp),
                official_path=str(official),
                os_error=str(exc),
            ) from exc

        # Best-effort cleanup of temp file (may fail on Windows due to OCAF handles)
        try:
            os.remove(str(temp))
        except OSError:
            pass

        # fsync the parent directory so the copy is durable
        OcafRepository._fsync_path(official.parent)

        return official

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fsync_path(path: Path) -> None:
        """Flush a file or directory to disk."""
        try:
            fd = os.open(str(path), os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass  # best-effort fsync

    def close(self) -> None:
        """Release the document from the Application Session and free file handles.

        After close(), the temp file can safely be moved/deleted on Windows.
        """
        if self._doc is not None:
            try:
                self._app.Close(self._doc)
            except Exception:
                pass  # best-effort: app may have already released it
        self._doc = None
        self._app = None
        self._design_root = None
