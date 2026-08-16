// Full-structure C++ reproduction: box face roles + box edge roles + boolean
// face/edge relations + face and edge selections solved together.
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
#include <TopoDS_Face.hxx>
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
#include <functional>
#include <iostream>
#include <vector>

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

static gp_Pnt FaceCenter(const TopoDS_Face& face) {
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    return props.CentreOfMass();
}

static TopoDS_Face FindFaceByCenter(
    const TopoDS_Shape& shape,
    const std::function<Standard_Boolean(const gp_Pnt&)>& predicate)
{
    for (TopExp_Explorer ex(shape, TopAbs_FACE); ex.More(); ex.Next()) {
        TopoDS_Face f = TopoDS::Face(ex.Current());
        if (predicate(FaceCenter(f))) return f;
    }
    return TopoDS_Face();
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
        if (re.IsPartner(edge) || re.IsSame(edge)) return re;
    }
    return TopoDS_Edge();
}

static TopoDS_Face PartnerFace(const TopoDS_Shape& result, const TopoDS_Face& face) {
    for (TopExp_Explorer ex(result, TopAbs_FACE); ex.More(); ex.Next()) {
        TopoDS_Face rf = TopoDS::Face(ex.Current());
        if (rf.IsPartner(face) || rf.IsSame(face)) return rf;
    }
    return TopoDS_Face();
}

static std::vector<TopoDS_Edge> AllEdges(const TopoDS_Shape& shape) {
    std::vector<TopoDS_Edge> edges;
    for (TopExp_Explorer ex(shape, TopAbs_EDGE); ex.More(); ex.Next()) {
        edges.push_back(TopoDS::Edge(ex.Current()));
    }
    return edges;
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
    TopoDS_Shape box2 = BRepPrimAPI_MakeBox(30.0, 30.0, 10.0).Shape();

    auto topPred = [](const gp_Pnt& c) { return std::fabs(c.Z() - 10.0) < 1e-6; };
    auto bottomPred = [](const gp_Pnt& c) { return std::fabs(c.Z()) < 1e-6; };
    auto plusXPred = [](const gp_Pnt& c) { return std::fabs(c.X() - 20.0) < 1e-6; };
    auto minusXPred = [](const gp_Pnt& c) { return std::fabs(c.X()) < 1e-6; };
    auto plusYPred = [](const gp_Pnt& c) { return std::fabs(c.Y() - 20.0) < 1e-6; };
    auto minusYPred = [](const gp_Pnt& c) { return std::fabs(c.Y()) < 1e-6; };

    TopoDS_Face top1 = FindFaceByCenter(box1, topPred);
    TopoDS_Face bottom1 = FindFaceByCenter(box1, bottomPred);
    TopoDS_Face plusX1 = FindFaceByCenter(box1, plusXPred);
    TopoDS_Face minusX1 = FindFaceByCenter(box1, minusXPred);
    TopoDS_Face plusY1 = FindFaceByCenter(box1, plusYPred);
    TopoDS_Face minusY1 = FindFaceByCenter(box1, minusYPred);

    TopoDS_Face top2 = FindFaceByCenter(box2, topPred);
    TopoDS_Face bottom2 = FindFaceByCenter(box2, bottomPred);
    TopoDS_Face plusX2 = FindFaceByCenter(box2, plusXPred);
    TopoDS_Face minusX2 = FindFaceByCenter(box2, minusXPred);
    TopoDS_Face plusY2 = FindFaceByCenter(box2, plusYPred);
    TopoDS_Face minusY2 = FindFaceByCenter(box2, minusYPred);

    std::vector<TopoDS_Edge> edges1 = AllEdges(box1);
    std::vector<TopoDS_Edge> edges2 = AllEdges(box2);
    TopoDS_Edge edge1 = TopYEdge(box1);
    TopoDS_Edge edge2 = TopYEdge(box2);

    Handle(XCAFApp_Application) app = XCAFApp_Application::GetApplication();
    BinXCAFDrivers::DefineFormat(app);
    Handle(TDocStd_Document) doc =
        new TDocStd_Document(TCollection_ExtendedString("BinXCAF"));
    app->InitDocument(doc);

    TDF_Label root = doc->Main();
    TDF_Label boxLabel = root.FindChild(1, Standard_True);
    TDF_Label cutLabel = root.FindChild(2, Standard_True);
    TDF_Label cutFaceRoleLabel = root.FindChild(3, Standard_True);
    TDF_Label cutEdgeRoleLabel = root.FindChild(4, Standard_True);
    TDF_Label faceAnchorLabel = root.FindChild(5, Standard_True);
    TDF_Label edgeAnchorLabel = root.FindChild(6, Standard_True);
    TDF_Label faceSelLabel = root.FindChild(7, Standard_True);
    TDF_Label edgeSelLabel = root.FindChild(8, Standard_True);

    std::vector<TDF_Label> faceRoleLabels;
    std::vector<TDF_Label> edgeRoleLabels;
    for (int i = 0; i < 6; ++i) {
        faceRoleLabels.push_back(root.FindChild(20 + i, Standard_True));
    }
    for (int i = 0; i < 12; ++i) {
        edgeRoleLabels.push_back(root.FindChild(40 + i, Standard_True));
    }

    TNaming_Builder(boxLabel).Generated(box1);
    TNaming_Builder(faceRoleLabels[0]).Generated(top1);
    TNaming_Builder(faceRoleLabels[1]).Generated(bottom1);
    TNaming_Builder(faceRoleLabels[2]).Generated(plusX1);
    TNaming_Builder(faceRoleLabels[3]).Generated(minusX1);
    TNaming_Builder(faceRoleLabels[4]).Generated(plusY1);
    TNaming_Builder(faceRoleLabels[5]).Generated(minusY1);
    for (int i = 0; i < 12 && i < static_cast<int>(edges1.size()); ++i) {
        TNaming_Builder(edgeRoleLabels[i]).Generated(edges1[i]);
    }
    TNaming_Builder(faceAnchorLabel).Generated(top1);
    TNaming_Builder(edgeAnchorLabel).Generated(edge1);

    TNaming_Selector faceSelector(faceSelLabel);
    Standard_Boolean faceSelOk = faceSelector.Select(top1, box1);
    TNaming_Selector edgeSelector(edgeSelLabel);
    Standard_Boolean edgeSelOk = edgeSelector.Select(edge1, box1);

    TopoDS_Shape tool1 = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(10.0, 10.0, 0.0), gp_Dir(0, 0, 1)), 2.0, 10.0).Shape();
    TopoDS_Shape cut1 = Cut(box1, tool1);
    TopoDS_Face top1_cut = PartnerFace(cut1, top1);
    TopoDS_Edge edge1_cut = PartnerEdge(cut1, edge1);
    TNaming_Builder(cutLabel).Generated(cut1);
    if (!top1_cut.IsNull()) TNaming_Builder(cutFaceRoleLabel).Modify(top1, top1_cut);
    if (!edge1_cut.IsNull()) TNaming_Builder(cutEdgeRoleLabel).Modify(edge1, edge1_cut);

    TNaming_Builder(boxLabel).Modify(box1, box2);
    TNaming_Builder(faceRoleLabels[0]).Modify(top1, top2);
    TNaming_Builder(faceRoleLabels[1]).Modify(bottom1, bottom2);
    TNaming_Builder(faceRoleLabels[2]).Modify(plusX1, plusX2);
    TNaming_Builder(faceRoleLabels[3]).Modify(minusX1, minusX2);
    TNaming_Builder(faceRoleLabels[4]).Modify(plusY1, plusY2);
    TNaming_Builder(faceRoleLabels[5]).Modify(minusY1, minusY2);
    for (int i = 0; i < 12 && i < static_cast<int>(edges1.size()) &&
                    i < static_cast<int>(edges2.size()); ++i) {
        TNaming_Builder(edgeRoleLabels[i]).Modify(edges1[i], edges2[i]);
    }

    TopoDS_Shape tool2 = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(15.0, 15.0, 0.0), gp_Dir(0, 0, 1)), 2.0, 10.0).Shape();
    TopoDS_Shape cut2 = Cut(box2, tool2);
    TopoDS_Face top2_cut = PartnerFace(cut2, top2);
    TopoDS_Edge edge2_cut = PartnerEdge(cut2, edge2);
    TNaming_Builder(cutLabel).Modify(cut1, cut2);
    if (!top1_cut.IsNull() && !top2_cut.IsNull()) {
        TNaming_Builder(cutFaceRoleLabel).Modify(top1_cut, top2_cut);
    }
    if (!edge1_cut.IsNull() && !edge2_cut.IsNull()) {
        TNaming_Builder(cutEdgeRoleLabel).Modify(edge1_cut, edge2_cut);
    }

    TDF_LabelMap valid;
    valid.Add(boxLabel);
    valid.Add(cutLabel);
    valid.Add(cutFaceRoleLabel);
    valid.Add(cutEdgeRoleLabel);
    valid.Add(faceAnchorLabel);
    valid.Add(edgeAnchorLabel);
    for (const auto& l : faceRoleLabels) valid.Add(l);
    for (const auto& l : edgeRoleLabels) valid.Add(l);

    Standard_Boolean faceSolved = faceSelector.Solve(valid);
    Handle(TNaming_NamedShape) faceNs = faceSelector.NamedShape();
    TopoDS_Shape currentFace = TNaming_Tool::CurrentShape(faceNs);

    Standard_Boolean edgeSolved = edgeSelector.Solve(valid);
    Handle(TNaming_NamedShape) edgeNs = edgeSelector.NamedShape();
    TopoDS_Shape currentEdge = TNaming_Tool::CurrentShape(edgeNs);

    int nFaces = 0;
    for (TopExp_Explorer ex(currentFace, TopAbs_FACE); ex.More(); ex.Next()) ++nFaces;
    int nEdges = 0;
    Standard_Real len = 0.0;
    for (TopExp_Explorer ex(currentEdge, TopAbs_EDGE); ex.More(); ex.Next()) {
        ++nEdges;
        len = EdgeLength(TopoDS::Edge(ex.Current()));
    }

    std::cout << "face_select=" << (faceSelOk ? "ok" : "fail")
              << " face_solve=" << (faceSolved ? "ok" : "fail")
              << " face_type=" << ShapeTypeName(currentFace.ShapeType())
              << " face_count=" << nFaces
              << " edge_select=" << (edgeSelOk ? "ok" : "fail")
              << " edge_solve=" << (edgeSolved ? "ok" : "fail")
              << " edge_type=" << ShapeTypeName(currentEdge.ShapeType())
              << " edge_count=" << nEdges
              << " edge_len=" << len << std::endl;
    return 0;
}
