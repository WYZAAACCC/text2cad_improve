"""Fixed OCAF Tag schema for Text2CAD topology naming.

Implements §4.3 of the v3.0 implementation guide:

    0:1 Main / XCAF Document Tool
    ├── 1..10                 XCAF reserved tools (NEVER touch)
    └── 100                   Text2CAD DesignRoot
        ├── 1 Metadata
        ├── 2 Components
        ├── 3 Selections
        ├── 4 Assembly
        ├── 5 CAEBindings
        ├── 6 Revisions
        └── 7 StableIdIndex

Component:
    Components/<component-tag>
    ├── 1 Metadata
    ├── 2 Features
    ├── 3 CurrentBody
    └── 4 Audit

Feature:
    Features/<feature-tag>
    ├── 1 Metadata
    ├── 2 CurrentResult
    ├── 3 EvolutionRelations
    ├── 4 ConstructionRoles
    └── 5 RevisionAudit

Selection:
    Selections/<selection-tag>
    ├── 1 NativeNaming           # TNaming_Selector exclusive
    ├── 2 Metadata
    ├── 3 SemanticContract
    └── 4 Audit

All tag lookups use FindChild(tag, create) — NEVER NewChild().
Dynamic object tags start at 1000 to avoid clashes with structural sub-tags.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

DESIGN_ROOT_TAG = 100
"""Main entry point for all Text2CAD data. Far from XCAF reserved 1-10."""

# ---------------------------------------------------------------------------
# DesignRoot structural sub-tags (1-9)
# ---------------------------------------------------------------------------

TAG_METADATA = 1
"""Schema version, lineage ID, creation timestamp."""

TAG_COMPONENTS = 2
"""Container for component labels. Each component gets a dynamic tag >= 1000."""

TAG_SELECTIONS = 3
"""Container for persistent topology selections (TNaming_Selector-based)."""

TAG_ASSEMBLY = 4
"""Assembly structure / product relationships."""

TAG_CAE_BINDINGS = 5
"""CAE load, constraint, and mesh-control bindings to selections."""

TAG_REVISIONS = 6
"""Revision history log (audit trail, not geometry)."""

TAG_STABLE_ID_INDEX = 7
"""Persistent object_id → TagPath index (OCAF is authoritative source)."""

# ---------------------------------------------------------------------------
# Component sub-tags
# ---------------------------------------------------------------------------

COMPONENT_TAG_METADATA = 1
COMPONENT_TAG_FEATURES = 2
COMPONENT_TAG_CURRENT_BODY = 3
COMPONENT_TAG_AUDIT = 4

# ---------------------------------------------------------------------------
# Feature sub-tags
# ---------------------------------------------------------------------------

FEATURE_TAG_METADATA = 1
FEATURE_TAG_RESULT_ROOT = 2        # v6.0 §3: body + sub-shape TNaming children
FEATURE_TAG_RELATION_METADATA = 3  # v6.0 §3: JSON metadata only (no TNaming)
FEATURE_TAG_CONSTRUCTION_ROLES = 4
FEATURE_TAG_REVISION_AUDIT = 5

# Backward compat aliases
FEATURE_TAG_CURRENT_RESULT = FEATURE_TAG_RESULT_ROOT
FEATURE_TAG_EVOLUTION_RELATIONS = FEATURE_TAG_RELATION_METADATA

# ResultRoot sub-tags for semantic roles (v6.0 §3.2)
ROLE_TAG_BASE = 1001

# ---------------------------------------------------------------------------
# Selection sub-tags
# ---------------------------------------------------------------------------

SELECTION_TAG_NATIVE_NAMING = 1    # TNaming_Selector exclusive — must NOT hold business attrs
SELECTION_TAG_METADATA = 2
SELECTION_TAG_SEMANTIC_CONTRACT = 3
SELECTION_TAG_AUDIT = 4
SELECTION_TAG_FINGERPRINT = 5      # geometric fingerprint for cross-process DELETED detection
SELECTION_TAG_SHAPE_ANCHOR = 6     # TNaming anchor for the selected sub-shape (FACE/EDGE)

# ---------------------------------------------------------------------------
# StableIdIndex sub-tags (v5.0 §5.4)
# ---------------------------------------------------------------------------

INDEX_TAG_METADATA = 1
INDEX_TAG_COUNTERS = 2
INDEX_TAG_ENTRIES = 3

# Metadata
INDEX_META_SCHEMA_VERSION = 1
INDEX_META_INDEX_REVISION = 2

# Counter kinds (v5.0 §5.4: separate counter per object kind)
INDEX_COUNTER_KINDS = [
    "component",       # tag 1
    "feature",         # tag 2
    "selection",       # tag 3
    "relation",        # tag 4
    "revision",        # tag 5
    "cae_binding",     # tag 6
    "face_role",       # tag 7
]

# ---------------------------------------------------------------------------
# DesignRoot Metadata sub-tags (Tag 100:1) — v5.0 §7.2
# ---------------------------------------------------------------------------

META_TAG_SCHEMA_VERSION = 1
META_TAG_LINEAGE_ID = 2
META_TAG_HEAD_REVISION_ID = 3
META_TAG_HEAD_REVISION_NUMBER = 4

# ---------------------------------------------------------------------------
# Revisions sub-tags (Tag 100:6)
# ---------------------------------------------------------------------------

REVISION_TAG_ENTRY_BASE = 1001  # first revision entry tag under 100:6

# ---------------------------------------------------------------------------
# Object tag range
# ---------------------------------------------------------------------------

DYNAMIC_TAG_START = 1000
"""First tag available for dynamic object allocation (component, feature, selection).
Tags 1-999 are reserved for fixed structural labels and XCAF system tools.
"""

# ---------------------------------------------------------------------------
# TagPath — stable address within the label tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TagPath:
    """A stable address in the OCAF label tree, expressed as a tuple of tags.

    TagPath is the persistence-safe equivalent of a TDF_Label entry string.
    Starting from Main (tag 0), each subsequent tag is an argument to FindChild().

    Example:
        TagPath((DESIGN_ROOT_TAG, TAG_COMPONENTS, 1042, COMPONENT_TAG_FEATURES))
        → doc.Main().FindChild(100).FindChild(2).FindChild(1042).FindChild(2)
    """

    tags: tuple[int, ...]

    def __post_init__(self):
        if not self.tags:
            raise ValueError("TagPath must contain at least one tag")
        if self.tags[0] != DESIGN_ROOT_TAG:
            raise ValueError(
                f"TagPath must start with DESIGN_ROOT_TAG ({DESIGN_ROOT_TAG}), "
                f"got {self.tags[0]}"
            )

    def __str__(self) -> str:
        return ":".join(str(t) for t in self.tags)

    @classmethod
    def from_label(cls, label, main_label) -> TagPath:
        """Reconstruct a TagPath from a TDF_Label by walking up to Main.

        Uses FindChild reverse-lookup (Tag-based, NOT Entry-based).
        This is a diagnostic helper; prefer storing TagPath explicitly.
        """
        tags = []
        current = label
        while not current.IsNull() and current != main_label:
            tag = current.Tag()
            tags.append(tag)
            current = current.Father()
        tags.reverse()
        if not tags:
            raise ValueError("Could not reconstruct TagPath: no tags found")
        return cls(tuple(tags))

    def resolve(self, main_label):
        """Walk this TagPath from Main(), returning the target TDF_Label.

        Uses FindChild(tag, False) — does NOT create missing labels.
        Returns a Null label if any segment is missing.
        """
        from OCP.TDF import TDF_Label

        current = main_label
        for tag in self.tags:
            current = current.FindChild(tag, False)
            if current.IsNull():
                return TDF_Label()  # return Null
        return current

    def resolve_or_create(self, main_label):
        """Walk this TagPath from Main(), creating missing segments.

        Uses FindChild(tag, True) at each level.
        """
        current = main_label
        for tag in self.tags:
            current = current.FindChild(tag, True)
        return current

    @property
    def parent(self) -> TagPath:
        """Return the parent TagPath (one level up)."""
        if len(self.tags) <= 1:
            raise ValueError("Cannot get parent of root-level TagPath")
        return TagPath(self.tags[:-1])

    def child(self, tag: int) -> TagPath:
        """Return a child TagPath by appending a tag."""
        return TagPath(self.tags + (tag,))


# ---------------------------------------------------------------------------
# Pre-built TagPaths for the fixed schema
# ---------------------------------------------------------------------------

# DesignRoot → structural children
TAGPATH_DESIGN_ROOT = TagPath((DESIGN_ROOT_TAG,))
TAGPATH_METADATA = TagPath((DESIGN_ROOT_TAG, TAG_METADATA))
TAGPATH_COMPONENTS = TagPath((DESIGN_ROOT_TAG, TAG_COMPONENTS))
TAGPATH_SELECTIONS = TagPath((DESIGN_ROOT_TAG, TAG_SELECTIONS))
TAGPATH_ASSEMBLY = TagPath((DESIGN_ROOT_TAG, TAG_ASSEMBLY))
TAGPATH_CAE_BINDINGS = TagPath((DESIGN_ROOT_TAG, TAG_CAE_BINDINGS))
TAGPATH_REVISIONS = TagPath((DESIGN_ROOT_TAG, TAG_REVISIONS))
TAGPATH_STABLE_ID_INDEX = TagPath((DESIGN_ROOT_TAG, TAG_STABLE_ID_INDEX))

# All structural TagPaths under DesignRoot
ALL_STRUCTURAL_TAGPATHS = frozenset({
    TAGPATH_DESIGN_ROOT,
    TAGPATH_METADATA,
    TAGPATH_COMPONENTS,
    TAGPATH_SELECTIONS,
    TAGPATH_ASSEMBLY,
    TAGPATH_CAE_BINDINGS,
    TAGPATH_REVISIONS,
    TAGPATH_STABLE_ID_INDEX,
})


def make_component_tagpath(component_tag: int) -> TagPath:
    """Build TagPath for Components/<tag>."""
    if component_tag < DYNAMIC_TAG_START:
        raise ValueError(
            f"Component tag {component_tag} is in reserved range. "
            f"Must be >= {DYNAMIC_TAG_START}"
        )
    return TagPath((DESIGN_ROOT_TAG, TAG_COMPONENTS, component_tag))


def make_feature_tagpath(component_tag: int, feature_tag: int) -> TagPath:
    """Build TagPath for Components/<ctag>/Features/<ftag>."""
    if feature_tag < DYNAMIC_TAG_START:
        raise ValueError(
            f"Feature tag {feature_tag} is in reserved range. "
            f"Must be >= {DYNAMIC_TAG_START}"
        )
    return TagPath((DESIGN_ROOT_TAG, TAG_COMPONENTS, component_tag, COMPONENT_TAG_FEATURES, feature_tag))


def make_selection_tagpath(selection_tag: int) -> TagPath:
    """Build TagPath for Selections/<tag>."""
    if selection_tag < DYNAMIC_TAG_START:
        raise ValueError(
            f"Selection tag {selection_tag} is in reserved range. "
            f"Must be >= {DYNAMIC_TAG_START}"
        )
    return TagPath((DESIGN_ROOT_TAG, TAG_SELECTIONS, selection_tag))
