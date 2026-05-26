from __future__ import annotations

from seekflow_engineering_tools.ir.cad import CADPartSpec

CAPABILITIES: dict = {
    "solidworks2025": {
        "software": "solidworks",
        "version": "2025",
        "units_api": "m",
        "units_ir": "mm",
        "stable_recipes": [
            "box",
            "flanged_hub",
            "spur_gear",
        ],
        "experimental_features": [
            "cut_extrude",
            "fillet",
        ],
        "exports": [
            "sldprt",
            "step",
        ],
        "caveats": [
            "Complex features must go through strict VBS recipe wrappers.",
            "Do not call FeatureExtrusion2 directly from LLM-generated Python.",
        ],
    },
    "nx12": {
        "software": "nx",
        "version": "12.0",
        "units_api": "mm",
        "units_ir": "mm",
        "stable_recipes": [
            "box",
            "block_with_hole",
            "l_bracket",
            "stepped_block",
        ],
        "exports": [
            "prt",
            "step",
        ],
        "caveats": [
            "NXOpen must run inside NX bridge journal.",
            "External Python submits JSON jobs only.",
        ],
    },
    "ansys181": {
        "software": "ansys",
        "version": "18.1",
        "units_ir": "mm,N,MPa",
        "stable_templates": [
            "static_cantilever_beam_rect",
            "plate_with_hole_tension",
            "beam_thermal",
            "cantilever_modal",
            "buckling_column",
            "bilinear_plastic",
        ],
        "caveats": [
            "Use APDL batch only.",
            "Do not use PyMAPDL gRPC for ANSYS 18.1.",
        ],
    },
    "cadquery": {
        "software": "cadquery",
        "units_ir": "mm",
        "stable_recipes": [
            "box",
            "cylinder",
            "block_with_hole",
            "l_bracket",
            "stepped_block",
            "flanged_hub",
            "spur_gear",
            "shaft_basic",
            "shaft_with_keyway",
        ],
        "exports": [
            "step",
            "stl",
        ],
        "caveats": [
            "No native SolidWorks or NX feature tree.",
        ],
    },
}


def backend_supports_recipe(backend: str, recipe: str) -> bool:
    cap = CAPABILITIES.get(backend, {})
    return recipe in cap.get("stable_recipes", [])


def get_backend_caveats(backend: str) -> list[str]:
    cap = CAPABILITIES.get(backend, {})
    return cap.get("caveats", [])


def list_backend_recipes(backend: str) -> list[str]:
    cap = CAPABILITIES.get(backend, {})
    return cap.get("stable_recipes", [])


def choose_backend(spec: CADPartSpec, preferred: list[str] | None = None) -> str:
    """Select best available backend for a CADPartSpec.

    Prefers backends in *preferred* order, falling back to cadquery.
    Falls back to cadquery if no preferred backend supports all recipes.
    """
    candidates = preferred or [b for b in spec.target_backend]

    for backend in candidates:
        all_ok = True
        for feat in spec.features:
            if feat.type == "recipe":
                if not backend_supports_recipe(backend, feat.recipe_name):
                    all_ok = False
                    break
        if all_ok:
            return backend

    return "cadquery"
