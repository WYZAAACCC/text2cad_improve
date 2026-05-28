from __future__ import annotations


REQUIRED_TURBINE_METADATA_KEYS = [
    "radial_zones",
    "profile_points",
    "hole_patterns",
    "safety",
    "geometry_family",
    "visual_fidelity",
    "rim_features",
    "hub_sleeve",
    "annular_details",
]


def validate_axisymmetric_turbine_disk_metadata(metadata: dict) -> list[str]:
    errors: list[str] = []

    # ── required top-level keys ──
    for key in REQUIRED_TURBINE_METADATA_KEYS:
        if key not in metadata:
            errors.append(f"axisymmetric_turbine_disk metadata missing '{key}'")

    # ── radial_zones ──
    radial_zones = metadata.get("radial_zones")
    if not isinstance(radial_zones, dict):
        errors.append("axisymmetric_turbine_disk metadata 'radial_zones' must be a dict")
    else:
        required_zones = [
            "bore_radius_mm",
            "hub_outer_radius_mm",
            "web_outer_radius_mm",
            "rim_inner_radius_mm",
            "outer_radius_mm",
        ]
        for key in required_zones:
            if key not in radial_zones:
                errors.append(f"radial_zones missing '{key}'")

    # ── profile_points ──
    profile_points = metadata.get("profile_points")
    if not isinstance(profile_points, list) or len(profile_points) < 4:
        errors.append("axisymmetric_turbine_disk metadata 'profile_points' must be a non-empty list")

    # ── hole_patterns ──
    hole_patterns = metadata.get("hole_patterns")
    if not isinstance(hole_patterns, list):
        errors.append("axisymmetric_turbine_disk metadata 'hole_patterns' must be a list")
    else:
        names = {p.get("name") for p in hole_patterns if isinstance(p, dict)}
        for expected in {"bolt", "lightening", "cooling"}:
            if expected not in names:
                errors.append(f"hole_patterns missing '{expected}' pattern")

    # ── safety ──
    safety = metadata.get("safety")
    if not isinstance(safety, dict):
        errors.append("axisymmetric_turbine_disk metadata 'safety' must be a dict")
    else:
        if safety.get("non_flight_reference_only") is not True:
            errors.append("safety.non_flight_reference_only must be True")
        if safety.get("not_airworthy") is not True:
            errors.append("safety.not_airworthy must be True")
        if safety.get("not_certified") is not True:
            errors.append("safety.not_certified must be True")
        if safety.get("not_for_manufacturing") is not True:
            errors.append("safety.not_for_manufacturing must be True")

    # ── v0.2: geometry_family ──
    gf = metadata.get("geometry_family")
    if gf != "axisymmetric_base_with_cyclic_rim_features":
        errors.append(
            "metadata.geometry_family must be 'axisymmetric_base_with_cyclic_rim_features', "
            f"got {gf!r}"
        )

    # ── v0.2: visual_fidelity ──
    visual = metadata.get("visual_fidelity")
    if not isinstance(visual, dict):
        errors.append("metadata.visual_fidelity must be a dict")
    else:
        if visual.get("contains_real_blade_attachment") is not False:
            errors.append("visual_fidelity.contains_real_blade_attachment must be False")

    # ── v0.2: rim_features ──
    rim = metadata.get("rim_features")
    if not isinstance(rim, dict):
        errors.append("metadata.rim_features must be a dict")
    else:
        if "slot_count" not in rim:
            errors.append("rim_features.slot_count missing")
        if "slot_style" not in rim:
            errors.append("rim_features.slot_style missing")
        if rim.get("reference_only") is not True:
            errors.append("rim_features.reference_only must be True")

    # ── v0.2: hub_sleeve ──
    sleeve = metadata.get("hub_sleeve")
    if not isinstance(sleeve, dict):
        errors.append("metadata.hub_sleeve must be a dict")

    # ── v0.2: annular_details ──
    annular = metadata.get("annular_details")
    if not isinstance(annular, dict):
        errors.append("metadata.annular_details must be a dict")

    return errors
