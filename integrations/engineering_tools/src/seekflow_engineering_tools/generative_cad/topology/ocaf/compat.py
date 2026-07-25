"""OCP 7.8.1.1 verified compatibility layer.

All APIs in this module have been verified via smoke test against the actual
environment (Python 3.11.9, CadQuery 2.7.0, OCP 7.8.1.1).

Key findings:
- Static methods use _s suffix: GetApplication_s, DefineFormat_s
- TDocStd_Document needs TCollection_ExtendedString, not plain str
- TopTools_ListOfShape supports Python __iter__ in OCP 7.8.1.1
"""

from __future__ import annotations

from OCP.TCollection import TCollection_ExtendedString
from OCP.TopTools import TopTools_ListOfShape


def get_xcaf_application():
    """Get XCAF application instance. OCP 7.8 uses GetApplication_s."""
    from OCP.XCAFApp import XCAFApp_Application
    return XCAFApp_Application.GetApplication_s()


def define_binxcaf_format(app) -> None:
    """Register BinXCAF format. OCP 7.8 uses DefineFormat_s."""
    from OCP.BinXCAFDrivers import BinXCAFDrivers
    BinXCAFDrivers.DefineFormat_s(app)


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
