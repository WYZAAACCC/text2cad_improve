cmake_minimum_required(VERSION 3.20)
project(ocaf_fixture CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Avoid an MSVC CRT side-by-side assembly dependency in the fixture executable:
# OCCT conda DLLs were built against a newer vc14_runtime than the system MSVC.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

find_package(OpenCASCADE REQUIRED)

add_executable(ocaf_smoke src/ocaf_smoke.cpp)

target_link_libraries(ocaf_smoke PRIVATE
    TKernel
    TKMath
    TKG2d
    TKG3d
    TKGeomBase
    TKBRep
    TKGeomAlgo
    TKTopAlgo
    TKPrim
    TKBool
    TKBO
    TKFillet
    TKOffset
    TKShHealing
    TKFeat
    TKXSBase
    TKService
    TKCAF
    TKBinXCAF
    TKStd
    TKStdL
    TKLCAF
)
