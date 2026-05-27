from __future__ import annotations

from dataclasses import dataclass, field

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
        ],
        "stable_primitives": [
            "involute_spur_gear",
        ],
        "primitive_strategy": {
            "involute_spur_gear": "cadquery_step_import",
        },
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
            "Gear primitives are imported via canonical STEP (cadquery_step_import strategy).",
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
        "stable_primitives": [
            "involute_spur_gear",
        ],
        "primitive_strategy": {
            "involute_spur_gear": "cadquery_step_import",
        },
        "exports": [
            "prt",
            "step",
        ],
        "caveats": [
            "NXOpen must run inside NX bridge journal.",
            "External Python submits JSON jobs only.",
            "Gear primitives are imported via canonical STEP (cadquery_step_import strategy).",
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
            "shaft_basic",
            "shaft_with_keyway",
        ],
        "stable_primitives": [
            "involute_spur_gear",
        ],
        "primitive_strategy": {
            "involute_spur_gear": "native_cadquery_primitive",
        },
        "exports": [
            "step",
            "stl",
        ],
        "caveats": [
            "No native SolidWorks or NX feature tree.",
        ],
    },
}


@dataclass
class BackendChoice:
    """Result of backend selection with fallback information."""
    backend: str
    fallback_from: str | None = None
    warnings: list[str] = field(default_factory=list)


def load_capability_registry() -> dict:
    """Return the full capability catalog."""
    return dict(CAPABILITIES)


def backend_supports_recipe(backend: str, recipe: str) -> bool:
    cap = CAPABILITIES.get(backend, {})
    return recipe in cap.get("stable_recipes", [])


def backend_supports_feature(backend: str, feature) -> bool:
    """Check if a backend supports a given feature (recipe or primitive)."""
    cap = CAPABILITIES.get(backend, {})

    feat_type = getattr(feature, "type", None)

    if feat_type == "recipe":
        return feature.recipe_name in cap.get("stable_recipes", [])
    elif feat_type == "primitive":
        return backend_supports_primitive(backend, feature.primitive_name)

    # Non-recipe/non-primitive features (extrude, hole, etc.) are cadquery-only
    return backend == "cadquery"


def get_backend_caveats(backend: str) -> list[str]:
    cap = CAPABILITIES.get(backend, {})
    return cap.get("caveats", [])


def list_backend_recipes(backend: str) -> list[str]:
    cap = CAPABILITIES.get(backend, {})
    return cap.get("stable_recipes", [])


def backend_supports_primitive(backend: str, primitive_name: str) -> bool:
    cap = CAPABILITIES.get(backend, {})
    return primitive_name in cap.get("stable_primitives", [])


def get_primitive_strategy(backend: str, primitive_name: str) -> str | None:
    cap = CAPABILITIES.get(backend, {})
    strategies = cap.get("primitive_strategy", {})
    return strategies.get(primitive_name)


def choose_backend(spec: CADPartSpec, preferred: list[str] | None = None) -> BackendChoice:
    """Select best available backend for a CADPartSpec.

    Rules:
    1. If user-specified backend supports all features → return it.
    2. If user-specified backend doesn't support → fallback to cadquery with warning.
    3. If no preference → prefer cadquery, then try SolidWorks/NX.
    4. If no backend supports → return "none" (ok=false upstream).
    """
    candidates = preferred or [b for b in spec.target_backend]
    fallback_from: str | None = None
    warnings: list[str] = []

    # Try preferred backends first
    for backend in candidates:
        all_ok = True
        for feat in spec.features:
            if not backend_supports_feature(backend, feat):
                all_ok = False
                break
        if all_ok:
            return BackendChoice(backend=backend, warnings=warnings)

    # Preferred backends don't support all features — fall back to cadquery
    if candidates and candidates[0] != "cadquery":
        fallback_from = candidates[0]
        warnings.append(
            f"Backend '{fallback_from}' does not support all features. "
            f"Falling back to cadquery."
        )

    # Check if cadquery can handle it
    all_cq_ok = True
    for feat in spec.features:
        if not backend_supports_feature("cadquery", feat):
            all_cq_ok = False
            break
    if all_cq_ok:
        return BackendChoice(backend="cadquery", fallback_from=fallback_from, warnings=warnings)

    return BackendChoice(backend="none", fallback_from=fallback_from, warnings=warnings)
