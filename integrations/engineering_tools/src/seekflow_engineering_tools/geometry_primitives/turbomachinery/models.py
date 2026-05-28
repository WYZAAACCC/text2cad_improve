"""Turbomachinery primitive definitions.

Axisymmetric turbine disk — non-flight reference geometry only.
"""

from seekflow_engineering_tools.geometry_primitives.base import (
    PrimitiveDefinition,
    PrimitiveParameter,
)

AXISYMMETRIC_TURBINE_DISK = PrimitiveDefinition(
    name="axisymmetric_turbine_disk",
    category="turbomachinery",
    description=(
        "Axisymmetric turbine disk non-flight reference geometry: "
        "hub-web-rim body, center bore, and optional bolt/lightening/cooling "
        "hole rings. This primitive is not airworthy, not certified, and not "
        "for manufacturing."
    ),
    parameters=[
        PrimitiveParameter(name="outer_dia_mm", type="float", unit="mm", required=True, min_value=1.0),
        PrimitiveParameter(name="bore_dia_mm", type="float", unit="mm", required=True, min_value=0.0),
        PrimitiveParameter(name="axial_width_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_outer_dia_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="web_outer_dia_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="rim_inner_dia_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_width_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="web_width_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="rim_width_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="web_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="rim_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="edge_chamfer_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),

        PrimitiveParameter(name="bolt_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="bolt_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="bolt_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="bolt_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="lightening_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="lightening_hole_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="lightening_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="lightening_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="cooling_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="cooling_hole_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="cooling_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="cooling_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="quality_grade", type="str", required=False, default="concept_geometry"),
        PrimitiveParameter(name="non_flight_reference_only", type="bool", required=False, default=True),
    ],
    supported_kernels=["cadquery_axisymmetric_revolve_v0"],
    supported_backends=["cadquery", "solidworks2025", "nx12"],
    standards=[],
    validation_defaults={
        "expected_body_count": 1,
        "tolerance_mm": 0.5,
        "non_flight_reference_only": True,
    },
)

TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = [
    AXISYMMETRIC_TURBINE_DISK,
]
