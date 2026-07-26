"""OCP 7.8.1.1 verified compatibility layer.

All APIs in this module have been verified via smoke test against the actual
environment (Python 3.11.9, CadQuery 2.7.0, OCP 7.8.1.1).

Key findings (from diagnostic tests 1-10):
- Static methods use _s suffix: GetApplication_s, DefineFormat_s
- TDocStd_Document needs TCollection_ExtendedString, not plain str
- TopTools_ListOfShape supports Python __iter__ in OCP 7.8.1.1
- TCollection_ExtendedString(str, True) is REQUIRED for UTF-8 paths
- app.Retrieve(folder, name, True) is the safe read API
- FindAttribute returns a Restore() shell — use TDF_AttributeIterator instead
- TNaming_Selector.NamedShape() returns the real Handle
- doc.Main().NewChild() collides with XCAF reserved Tags 1-10

Forbidden APIs (will crash or silently corrupt):
- TCollection_ExtendedString(str) without isMultiByte=True
- app.Open(path, doc) — uses unsafe output Handle
- TDF_Tool.Label_s() — ACCESS VIOLATION in OCP 7.8.1.1
- doc.Main().NewChild() — collides with XCAF reserved tags
- FindAttribute result passed to APIs expecting a real Label
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from OCP.TCollection import TCollection_ExtendedString
from OCP.TopTools import TopTools_ListOfShape


# ---------------------------------------------------------------------------
# UTF-8 path construction — §2.1 of v3.0 implementation guide
# ---------------------------------------------------------------------------

def ext_utf8(value: str | Path) -> TCollection_ExtendedString:
    """Construct a TCollection_ExtendedString from a Python path/string.

    **The second argument (isMultiByte=True) is NOT optional.**
    Without it, OCP 7.8.1.1 interprets the char* bytes as Latin-1,
    corrupting any non-ASCII characters in the path.

    Verified: diagnostic test 7 (UTF-8 constructor), test 9 (ASCII + Chinese paths).
    """
    return TCollection_ExtendedString(str(value), True)


# ---------------------------------------------------------------------------
# Application and format registration
# ---------------------------------------------------------------------------

def get_xcaf_application():
    """Get XCAF application instance. OCP 7.8 uses GetApplication_s."""
    from OCP.XCAFApp import XCAFApp_Application
    return XCAFApp_Application.GetApplication_s()


def define_binxcaf_format(app) -> None:
    """Register BinXCAF format. OCP 7.8 uses DefineFormat_s."""
    from OCP.BinXCAFDrivers import BinXCAFDrivers
    BinXCAFDrivers.DefineFormat_s(app)


def define_xmlxcaf_format(app) -> None:
    """Register XmlXCAF format. OCP 7.8 uses DefineFormat_s."""
    from OCP.XmlXCAFDrivers import XmlXCAFDrivers
    XmlXCAFDrivers.DefineFormat_s(app)


# ---------------------------------------------------------------------------
# Document lifecycle — §2.2 of v3.0 implementation guide
# ---------------------------------------------------------------------------

def new_xcaf_document(app):
    """Create a new TDocStd_Document with BinXCAF storage format.

    IMPORTANT: Must use TCollection_ExtendedString — plain str is rejected
    by OCP 7.8.1.1 TDocStd_Document constructor.
    """
    from OCP.TDocStd import TDocStd_Document
    fmt = TCollection_ExtendedString("BinXCAF")
    doc = TDocStd_Document(fmt)
    app.InitDocument(doc)
    return doc


def retrieve_xcaf_document(app, path: Path) -> Any:
    """Retrieve an existing XBF document from disk.

    Uses the safe app.Retrieve(folder, name, True) API — NOT app.Open(path, doc).
    The Retrieve() call returns the document directly without the unsafe output-Handle
    pattern that Open() uses.

    Returns the TDocStd_Document handle.

    Raises OcafRetrieveError if the file does not exist, is too small, or cannot be read.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"XBF document not found: {p}")

    # Safety check: reject empty/corrupted files before handing to OCCT.
    # OCP's app.Retrieve() ACCESS VIOLATES on garbage data.
    min_size = 8  # XBF header is at least 8 bytes
    if p.stat().st_size < min_size:
        raise RuntimeError(
            f"XBF document too small ({p.stat().st_size} bytes), likely corrupted: {p}"
        )

    # Retrieve(folder, filename, isMultiByte=True)
    doc = app.Retrieve(ext_utf8(p.parent), ext_utf8(p.name), True)

    if doc is None:
        raise RuntimeError(f"app.Retrieve returned None for: {p}")

    # Check that the document has content (not an empty shell)
    # A valid XBF will have at least Main() label
    main_label = doc.Main()
    if main_label.IsNull():
        raise RuntimeError(f"Retrieved document has Null Main() label: {p}")

    return doc


# ---------------------------------------------------------------------------
# Safe attribute navigation — §2.3 of v3.0 implementation guide
# ---------------------------------------------------------------------------

def get_named_shape_from_selector(selector_label) -> Any | None:
    """Get the real TNaming_NamedShape Handle from a Selector's label.

    Uses TNaming_Selector.NamedShape() which returns the genuine Handle,
    NOT the Restore() shell that FindAttribute produces.

    Returns None if no NamedShape is present.
    """
    from OCP.TNaming import TNaming_Selector

    sel = TNaming_Selector(selector_label)
    if sel.IsNull():
        return None
    ns = sel.NamedShape()
    if ns is None or ns.IsNull():
        return None
    return ns


def iter_label_attributes(label) -> list[Any]:
    """Enumerate all real attributes on a TDF_Label via TDF_AttributeIterator.

    This is the safe way to discover attributes — FindAttribute returns a
    Restore() shell whose Label() is Null.
    """
    from OCP.TDF import TDF_AttributeIterator

    results = []
    it = TDF_AttributeIterator(label)
    while it.More():
        results.append(it.Value())
        it.Next()
    return results


def get_attribute_by_type(label, attr_type) -> Any | None:
    """Find a specific attribute on a label by dynamic type.

    Searches via TDF_AttributeIterator (safe) rather than FindAttribute (Restore shell).
    Returns the real attribute handle, or None.
    """
    from OCP.TDF import TDF_AttributeIterator

    it = TDF_AttributeIterator(label)
    while it.More():
        attr = it.Value()
        if attr.IsKind(attr_type):
            return attr
        it.Next()
    return None


# ---------------------------------------------------------------------------
# TNaming label collection — for building Solve() valid_labels
# ---------------------------------------------------------------------------

def collect_tnaming_labels(root_label) -> Any:
    """Recursively collect all labels with TNaming_NamedShape into TDF_LabelMap.

    Used to build the valid_labels parameter for TNaming_Selector.Solve().
    Walks the entire label subtree from root_label.

    Args:
        root_label: A TDF_Label to start searching from.

    Returns:
        TDF_LabelMap containing all labels that have TNaming_NamedShape attributes.
    """
    from OCP.TDF import TDF_LabelMap, TDF_ChildIterator, TDF_AttributeIterator

    label_map = TDF_LabelMap()

    def _walk(label):
        # Check if this label has TNaming_NamedShape
        it = TDF_AttributeIterator(label)
        while it.More():
            attr = it.Value()
            if attr.DynamicType().Name() == "TNaming_NamedShape":
                label_map.Add(label)
                break
            it.Next()
        # Recurse into children
        child_it = TDF_ChildIterator(label)
        while child_it.More():
            _walk(child_it.Value())
            child_it.Next()

    _walk(root_label)
    return label_map


# ---------------------------------------------------------------------------
# TopTools_ListOfShape helpers
# ---------------------------------------------------------------------------

def list_of_shape_from_iterable(shapes) -> TopTools_ListOfShape:
    """Convert a Python iterable of TopoDS_Shape to TopTools_ListOfShape."""
    lst = TopTools_ListOfShape()
    for s in shapes:
        lst.Append(s)
    return lst


def iter_list_of_shape(lst: TopTools_ListOfShape):
    """Iterate a TopTools_ListOfShape.

    OCP 7.8.1.1 TopTools_ListOfShape supports Python __iter__ natively.
    """
    return iter(lst)
