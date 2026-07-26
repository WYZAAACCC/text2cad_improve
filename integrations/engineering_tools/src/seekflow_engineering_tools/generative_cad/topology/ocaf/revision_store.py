"""Immutable Revision Bundle — v6.0 §7.

Manages lineage/revisions/rev-NNNNNN/ directory structure with HEAD.json
atomic updates. Each revision is a complete, immutable directory containing
design.xbf, model.step, and metadata.json.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RevisionStore:
    """Manages immutable revision directories for one design lineage.

    Directory structure:
        output_root/lineage/<lineage_id>/
        ├── HEAD.json
        └── revisions/
            └── rev-000001/
                ├── design.xbf
                ├── model.step
                └── metadata.json
    """

    output_root: Path
    lineage_id: str

    @property
    def lineage_dir(self) -> Path:
        return self.output_root / "lineage" / self.lineage_id

    @property
    def revisions_dir(self) -> Path:
        return self.lineage_dir / "revisions"

    @property
    def head_path(self) -> Path:
        return self.lineage_dir / "HEAD.json"

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def init_lineage(self) -> Path:
        """Create the lineage directory structure. Idempotent."""
        self.lineage_dir.mkdir(parents=True, exist_ok=True)
        self.revisions_dir.mkdir(parents=True, exist_ok=True)
        return self.lineage_dir

    # ------------------------------------------------------------------
    # Revision paths
    # ------------------------------------------------------------------

    @staticmethod
    def format_revision_id(rev_number: int) -> str:
        """rev-000001 format."""
        return f"rev-{rev_number:06d}"

    def revision_dir(self, rev_number: int) -> Path:
        """Get the immutable directory for a specific revision."""
        return self.revisions_dir / self.format_revision_id(rev_number)

    def staging_dir(self, rev_number: int) -> Path:
        """Get a staging directory for building a revision."""
        return self.revisions_dir / f".staging-{self.format_revision_id(rev_number)}"

    # ------------------------------------------------------------------
    # HEAD management
    # ------------------------------------------------------------------

    def write_head(self, revision_id: str, revision_number: int) -> None:
        """Atomically write HEAD.json."""
        head = {
            "head_revision_id": revision_id,
            "head_revision_number": revision_number,
            "lineage_id": self.lineage_id,
        }
        # Atomic: write temp, then rename
        tmp = self.head_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(head, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self.head_path))

    def read_head(self) -> dict | None:
        """Read HEAD.json. Returns None if missing."""
        if not self.head_path.exists():
            return None
        try:
            return json.loads(self.head_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @property
    def head_revision_number(self) -> int:
        """Current HEAD revision number, or 0 if no HEAD."""
        head = self.read_head()
        return head.get("head_revision_number", 0) if head else 0

    @property
    def head_revision_id(self) -> str | None:
        """Current HEAD revision ID, or None."""
        head = self.read_head()
        return head.get("head_revision_id") if head else None

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish_revision(
        self,
        staging_dir: Path,
        rev_number: int,
        *,
        step_path: Path | None = None,
        metadata_path: Path | None = None,
    ) -> Path:
        """Publish a staging directory to an immutable revision directory.

        Args:
            staging_dir: The staging directory with design.xbf etc.
            rev_number: Revision number.
            step_path: Optional STEP file to copy into the bundle.
            metadata_path: Optional metadata JSON to copy.

        Returns:
            The published revision directory path.
        """
        final_dir = self.revision_dir(rev_number)

        # Never overwrite an existing revision (immutable)
        if final_dir.exists():
            raise FileExistsError(
                f"Revision {self.format_revision_id(rev_number)} already exists at {final_dir}"
            )

        # Ensure parent exists
        final_dir.mkdir(parents=True, exist_ok=True)

        # Copy XBF
        xbf_src = staging_dir / "design.xbf"
        if xbf_src.exists():
            shutil.copy2(str(xbf_src), str(final_dir / "design.xbf"))

        # Copy STEP
        if step_path is not None and step_path.exists():
            shutil.copy2(str(step_path), str(final_dir / "model.step"))

        # Copy metadata
        if metadata_path is not None and metadata_path.exists():
            shutil.copy2(str(metadata_path), str(final_dir / "metadata.json"))

        # Update HEAD
        self.write_head(self.format_revision_id(rev_number), rev_number)

        # Cleanup staging
        try:
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        except OSError:
            pass

        return final_dir
