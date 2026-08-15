// Stage B: box edge role Modify across revisions (no boolean).
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Pnt.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS.hxx>
#include <TopExp_Explorer.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TNaming_Builder.hxx>
#include <TNaming_Selector.hxx>
#include <TNaming_Tool.hxx>
#include <TNaming_NamedShape.hxx>
#include <TDF_Label.hxx>
#include <TDF_LabelMap.hxx>
#include <TDocStd_Document.hxx>
#include <XCAFApp_Application.hxx>
#include <BinXCAFDrivers.hxx>
#include <TCollection_ExtendedString.hxx>
#include <Standard_Handle.hxx>
#include <Standard_Real.hxx>
#include <cmath>
#include <iostream>

static const char* ShapeTypeName(TopAbs_ShapeEnum t) {
    switch (t) {
        case TopAbs_COMPOUND: return "COMPOUND";
        case TopAbs_SOLID: return "SOLID";
        case TopAbs_SHELL: return "SHELL";
        case TopAbs_FACE: return "FACE";
        case TopAbs_WIRE: return "WIRE";
        case TopAbs_EDGE: return "EDGE";
        case TopAbs_VERTEX: return "VERTEX";
        default: return "?";
    }
}

static Standard_Real EdgeLength(const TopoDS_Edge& edge) {
    GProp_GProps props;
    BRepGProp::LinearProperties(edge, props);
    return props.Mass();
}

// The top +Y edge: among all edges, the one with max Z, then max Y.
static TopoDS_Edge TopYEdge(const TopoDS_Shape& box) {
    TopoDS_Edge best;
    Standard_Real bestZ = -1e30, bestY = -1e30;
    for (TopExp_Explorer ex(box, TopAbs_EDGE); ex.More(); ex.Next()) {
        TopoDS_Edge e = TopoDS::Edge(ex.Current());
        GProp_GProps p;
        BRepGProp::LinearProperties(e, p);
        gp_Pnt c = p.CentreOfMass();
        if (c.Z() > bestZ + 1e-6 ||
            (std::fabs(c.Z() - bestZ) < 1e-6 && c.Y() > bestY)) {
            bestZ = c.Z();
            bestY = c.Y();
            best = e;
        }
    }
    return best;
}

int main() {
    TopoDS_Shape box1 = BRepPrimAPI_MakeBox(20.0, 20.0, 10.0).Shape();
    TopoDS_Edge edge1 = TopYEdge(box1);
    TopoDS_Shape box2 = BRepPrimAPI_MakeBox(30.0, 30.0, 10.0).Shape();
    TopoDS_Edge edge2 = TopYEdge(box2);

    Handle(XCAFApp_Application) app = XCAFApp_Application::GetApplication();
    BinXCAFDrivers::DefineFormat(app);
    Handle(TDocStd_Document) doc =
        new TDocStd_Document(TCollection_ExtendedString("BinXCAF"));
    app->InitDocument(doc);

    TDF_Label root = doc->Main();
    TDF_Label solidLabel = root.FindChild(1, Standard_True);
    TDF_Label edgeRoleLabel = root.FindChild(2, Standard_True);
    TDF_Label anchorLabel = root.FindChild(3, Standard_True);
    TDF_Label selLabel = root.FindChild(4, Standard_True);

    // Rev1
    TNaming_Builder(solidLabel).Generated(box1);
    TNaming_Builder(edgeRoleLabel).Generated(edge1);
    TNaming_Builder(anchorLabel).Generated(edge1);
    TNaming_Selector selector(selLabel);
    Standard_Boolean selOk = selector.Select(edge1, box1);

    // Rev2
    TNaming_Builder(solidLabel).Modify(box1, box2);
    TNaming_Builder(edgeRoleLabel).Modify(edge1, edge2);

    TDF_LabelMap valid;
    valid.Add(solidLabel);
    valid.Add(edgeRoleLabel);
    valid.Add(anchorLabel);

    Standard_Boolean solved = selector.Solve(valid);
    Handle(TNaming_NamedShape) ns = selector.NamedShape();
    TopoDS_Shape current = TNaming_Tool::CurrentShape(ns);

    int nEdges = 0;
    Standard_Real len = 0.0;
    for (TopExp_Explorer ex(current, TopAbs_EDGE); ex.More(); ex.Next()) {
        ++nEdges;
        len = EdgeLength(TopoDS::Edge(ex.Current()));
    }

    std::cout << "select=" << (selOk ? "ok" : "fail")
              << " solve=" << (solved ? "ok" : "fail")
              << " current_type=" << ShapeTypeName(current.ShapeType())
              << " current_edges=" << nEdges
              << " edge_len=" << len << std::endl;
    return 0;
}
