import cadquery as cq
from cadquery import exporters
import json

BUILD_WARNINGS = []
PRIMITIVE_METADATA = {}
result = None
# [Primitive: involute_spur_gear]
from seekflow_engineering_tools.geometry_primitives.gears.cq_gears_adapter import (
    cq_gears_available,
    build_involute_spur_gear_cq_gears,
)
from seekflow_engineering_tools.geometry_primitives.gears.cadquery_fallback import (
    build_visual_spur_gear_fallback,
)
from seekflow_engineering_tools.geometry_primitives.gears.metadata import (
    write_primitive_metadata,
)
from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)

_params = {
    "module_mm": 2.0,
    "teeth": 20,
    "pressure_angle_deg": 20.0,
    "face_width_mm": 15.0,
    "bore_dia_mm": 10.0,
    "quality_grade": "industrial_brep",
}

if cq_gears_available():
    result, PRIMITIVE_METADATA["involute_spur_gear"] = build_involute_spur_gear_cq_gears(_params)
else:
    BUILD_WARNINGS.append("cq_gears is not available; using visual fallback (NOT certified involute).")
    result, PRIMITIVE_METADATA["involute_spur_gear"] = build_visual_spur_gear_fallback(_params)
    BUILD_WARNINGS.extend(
        PRIMITIVE_METADATA["involute_spur_gear"].get("warnings", [])
    )

cq.exporters.export(result, r"E:\auto_detection_process\demo_output_v5\stage2_spur_gear\output.step")

# Write primitive metadata sidecar
_meta_payload = {
    "primitive_metadata": PRIMITIVE_METADATA,
    "build_warnings": BUILD_WARNINGS,
}
with open(r"E:\auto_detection_process\demo_output_v5\stage2_spur_gear\output.metadata.json", "w", encoding="utf-8") as _f:
    json.dump(_meta_payload, _f, indent=2, ensure_ascii=False, default=str)

if BUILD_WARNINGS:
    for w in BUILD_WARNINGS:
        print(f"CQ_WARNING: {w}")