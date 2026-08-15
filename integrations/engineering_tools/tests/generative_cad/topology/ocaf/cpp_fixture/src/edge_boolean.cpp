// Stage C: box edge role + boolean cut edge carry-through across revisions.
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Pnt.hxx>
#include <gp_Dir.hxx>
#include <gp_Ax2.hxx>
#include <BOPAlgo_BOP.hxx>
#include <BOPAlgo_Operation.hxx>
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

static TopoDS_Edge PartnerEdge(const TopoDS_Shape& result, const TopoDS_Edge& edge) {
    for (TopExp_Explorer ex(result, TopAbs_EDGE); ex.More(); ex.Next()) {
        TopoDS_Edge re = TopoDS::Edge(ex.Current());
        if (re.IsPartner(edge) || re.IsSame(edge)) {
            return re;
        }
    }
    return TopoDS_Edge();
}

static TopoDS_Shape Cut(const TopoDS_Shape& box, const TopoDS_Shape& tool) {
    BOPAlgo_BOP bop;
    bop.SetOperation(BOPAlgo_CUT);
    bop.SetToFillHistory(Standard_True);
    bop.AddArgument(box);
    bop.AddTool(tool);
    bop.Perform();
    return bop.Shape();
}

int main() {
    TopoDS_Shape box1 = BRepPrimAPI_MakeBox(20.0, 20.0, 10.0).Shape();
    TopoDS_Edge edge1 = TopYEdge(box1);
    TopoDS_Shape box2 = BRepPrimAPI_MakeBox(30.0, 30.0, 10.0).Shape();
    TopoDS_Edge edge2 = TopYEdge(box2);

    TopoDS_Shape tool1 =
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10.0, 10.0, 0.0), gp_Dir(0, 0, 1)), 2.0, 10.0).Shape();
    TopoDS_Shape tool2 =
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(15.0, 15.0, 0.0), gp_Dir(0, 0, 1)), 2.0, 10.0).Shape();

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
    TDF_Label cutLabel = root.FindChild(5, Standard_True);
    TDF_Label cutEdgeLabel = root.FindChild(6, Standard_True);

    // Rev1
    TNaming_Builder(solidLabel).Generated(box1);
    TNaming_Builder(edgeRoleLabel).Generated(edge1);
    TNaming_Builder(anchorLabel).Generated(edge1);
    TNaming_Selector selector(selLabel);
    selector.Select(edge1, box1);

    TopoDS_Shape cut1 = Cut(box1, tool1);
    TopoDS_Edge edge1_cut = PartnerEdge(cut1, edge1);
    TNaming_Builder(cutLabel).Generated(cut1);
    TNaming_Builder(cutEdgeLabel).Modify(edge1, edge1_cut);

    // Rev2
    TNaming_Builder(solidLabel).Modify(box1, box2);
    TNaming_Builder(edgeRoleLabel).Modify(edge1, edge2);

    TopoDS_Shape cut2 = Cut(box2, tool2);
    TopoDS_Edge edge2_cut = PartnerEdge(cut2, edge2);
    TNaming_Builder(cutLabel).Modify(cut1, cut2);
    TNaming_Builder(cutEdgeLabel).Modify(edge2, edge2_cut);

    TDF_LabelMap valid;
    valid.Add(solidLabel);
    valid.Add(edgeRoleLabel);
    valid.Add(anchorLabel);
    valid.Add(cutLabel);
    valid.Add(cutEdgeLabel);

    Standard_Boolean solved = selector.Solve(valid);
    Handle(TNaming_NamedShape) ns = selector.NamedShape();
    TopoDS_Shape current = TNaming_Tool::CurrentShape(ns);

    int nEdges = 0;
    Standard_Real len = 0.0;
    for (TopExp_Explorer ex(current, TopAbs_EDGE); ex.More(); ex.Next()) {
        ++nEdges;
        len = EdgeLength(TopoDS::Edge(ex.Current()));
    }

    std::cout << "solve=" << (solved ? "ok" : "fail")
              << " current_type=" << ShapeTypeName(current.ShapeType())
              << " current_edges=" << nEdges
              << " edge_len=" << len << std::endl;
    return 0;
}
