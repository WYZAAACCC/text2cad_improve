// Minimal C++ TNaming select/solve smoke.
// Mirrors the Python OCP path: write a box via TNaming_Builder.Generated,
// select a face via TNaming_Selector.Select, Solve, then inspect the result.
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS_Shape.hxx>
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
#include <iostream>

static const char* ShapeTypeName(TopAbs_ShapeEnum t) {
    switch (t) {
        case TopAbs_COMPOUND: return "COMPOUND";
        case TopAbs_COMPSOLID: return "COMPSOLID";
        case TopAbs_SOLID: return "SOLID";
        case TopAbs_SHELL: return "SHELL";
        case TopAbs_FACE: return "FACE";
        case TopAbs_WIRE: return "WIRE";
        case TopAbs_EDGE: return "EDGE";
        case TopAbs_VERTEX: return "VERTEX";
        default: return "?";
    }
}

static int FaceCount(const TopoDS_Shape& shape) {
    int n = 0;
    for (TopExp_Explorer ex(shape, TopAbs_FACE); ex.More(); ex.Next()) {
        ++n;
    }
    return n;
}

static TopoDS_Face TopFace(const TopoDS_Shape& box) {
    TopoDS_Face top;
    Standard_Real maxZ = -1e30;
    for (TopExp_Explorer ex(box, TopAbs_FACE); ex.More(); ex.Next()) {
        TopoDS_Face f = TopoDS::Face(ex.Current());
        GProp_GProps props;
        BRepGProp::SurfaceProperties(f, props);
        Standard_Real z = props.CentreOfMass().Z();
        if (z > maxZ) {
            maxZ = z;
            top = f;
        }
    }
    return top;
}

int main() {
    TopoDS_Shape box = BRepPrimAPI_MakeBox(20.0, 20.0, 10.0).Shape();
    TopoDS_Face top = TopFace(box);

    Handle(XCAFApp_Application) app = XCAFApp_Application::GetApplication();
    BinXCAFDrivers::DefineFormat(app);
    Handle(TDocStd_Document) doc =
        new TDocStd_Document(TCollection_ExtendedString("BinXCAF"));
    app->InitDocument(doc);

    TDF_Label root = doc->Main();
    TDF_Label boxLabel = root.FindChild(1, Standard_True);
    TDF_Label selLabel = root.FindChild(2, Standard_True);

    TNaming_Builder boxBuilder(boxLabel);
    boxBuilder.Generated(box);

    TNaming_Selector selector(selLabel);
    Standard_Boolean selOk = selector.Select(top, box);
    std::cout << "select=" << (selOk ? "ok" : "fail") << std::endl;

    TDF_LabelMap valid;
    valid.Add(boxLabel);
    Standard_Boolean solved = selector.Solve(valid);
    std::cout << "solve=" << (solved ? "ok" : "fail") << std::endl;

    Handle(TNaming_NamedShape) ns = selector.NamedShape();
    TopoDS_Shape current = TNaming_Tool::CurrentShape(ns);
    TopoDS_Shape get = TNaming_Tool::GetShape(ns);

    std::cout << "current_type=" << ShapeTypeName(current.ShapeType())
              << " current_faces=" << FaceCount(current) << std::endl;
    std::cout << "get_type=" << ShapeTypeName(get.ShapeType())
              << " get_faces=" << FaceCount(get) << std::endl;

    // Case 2: name the selected face first (the G1 anchor mechanism), then
    // select + solve. Valid labels now include both the body and the anchor.
    TDF_Label anchorLabel = root.FindChild(3, Standard_True);
    TNaming_Builder anchorBuilder(anchorLabel);
    anchorBuilder.Generated(top);

    TDF_Label sel2Label = root.FindChild(4, Standard_True);
    TNaming_Selector selector2(sel2Label);
    selector2.Select(top, box);

    TDF_LabelMap valid2;
    valid2.Add(boxLabel);
    valid2.Add(anchorLabel);
    Standard_Boolean solved2 = selector2.Solve(valid2);

    Handle(TNaming_NamedShape) ns2 = selector2.NamedShape();
    TopoDS_Shape current2 = TNaming_Tool::CurrentShape(ns2);
    std::cout << "named_solve=" << (solved2 ? "ok" : "fail")
              << " named_current_type=" << ShapeTypeName(current2.ShapeType())
              << " named_current_faces=" << FaceCount(current2) << std::endl;

    return 0;
}
