// Minimal OCCT C++ smoke test: build a box, report volume and face count.
// Verifies the OCCT C++ SDK + MSVC + CMake toolchain is usable.
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS_Shape.hxx>
#include <TopExp_Explorer.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <iostream>

int main() {
    TopoDS_Shape box = BRepPrimAPI_MakeBox(20.0, 20.0, 10.0).Shape();

    GProp_GProps props;
    BRepGProp::VolumeProperties(box, props);

    int nfaces = 0;
    for (TopExp_Explorer ex(box, TopAbs_FACE); ex.More(); ex.Next()) {
        ++nfaces;
    }

    std::cout << "OCCT_SMOKE_OK volume=" << props.Mass()
              << " faces=" << nfaces << std::endl;
    return 0;
}
