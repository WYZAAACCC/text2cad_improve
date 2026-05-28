from __future__ import annotations


REQUIRED_TURBINE_METADATA_KEYS = [
    "radial_zones", "profile_points", "hole_patterns", "safety",
    "geometry_family", "visual_fidelity", "rim_features",
    "hub_sleeve", "annular_details", "slot_generation", "axial_zones",
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

    # ── v0.3: geometry_family ──
    gf = metadata.get("geometry_family")
    if gf != "axisymmetric_base_with_clean_symmetric_fir_tree_slots":
        errors.append(
            "metadata.geometry_family must be 'axisymmetric_base_with_clean_symmetric_fir_tree_slots', "
            f"got {gf!r}"
        )

    # ── v0.4: slot_generation ──
    slot_gen = metadata.get("slot_generation")
    if not isinstance(slot_gen, dict):
        errors.append("metadata.slot_generation must be a dict")
    else:
        if slot_gen.get("version") != "rim_slot_v6_clean_symmetric_polygon":
            errors.append(f"slot_generation.version must be 'rim_slot_v6_clean_symmetric_polygon', got {slot_gen.get('version')!r}")
        if slot_gen.get("orientation") != "axial_through":
            errors.append("slot_generation.orientation must be axial_through")
        if slot_gen.get("socket_mode") != "internal_lobes":
            errors.append("slot_generation.socket_mode must be internal_lobes")
        if slot_gen.get("exposes_lobes_on_od") is not False:
            errors.append("slot_generation.exposes_lobes_on_od must be False")
        if slot_gen.get("opens_front_face") is not True:
            errors.append("slot_generation.opens_front_face must be True")
        if slot_gen.get("opens_back_face") is not True:
            errors.append("slot_generation.opens_back_face must be True")
        if slot_gen.get("opens_outer_diameter") is not True:
            errors.append("slot_generation.opens_outer_diameter must be True")
        # z_range
        z_min = float(slot_gen.get("z_min_mm", 0))
        rim_z_min = float(slot_gen.get("rim_z_min_mm", 0))
        z_max = float(slot_gen.get("z_max_mm", 0))
        rim_z_max = float(slot_gen.get("rim_z_max_mm", 0))
        if z_min >= rim_z_min:
            errors.append(f"slot_generation.z_min_mm ({z_min}) must be < rim_z_min_mm ({rim_z_min})")
        if z_max <= rim_z_max:
            errors.append(f"slot_generation.z_max_mm ({z_max}) must be > rim_z_max_mm ({rim_z_max})")
        # profile bounds
        max_x = float(slot_gen.get("profile_max_x_mm", 0))
        outer_r = float(slot_gen.get("outer_radius_mm", 0))
        min_x = float(slot_gen.get("profile_min_x_mm", 0))
        if outer_r > 0:
            if max_x <= outer_r:
                errors.append(f"slot_generation.profile_max_x_mm ({max_x}) must be > outer_radius_mm ({outer_r})")
            if min_x >= outer_r:
                errors.append(f"slot_generation.profile_min_x_mm ({min_x}) must be < outer_radius_mm ({outer_r})")

    # ── v0.3: rim_features extended ──
    rim = metadata.get("rim_features") or {}
    if int(rim.get("slot_count", 0)) > 0:
        if rim.get("reference_only") is not True:
            errors.append("rim_features.reference_only must be True")
        pts = rim.get("slot_profile_points_xy")
        if not pts or len(pts) < 3:
            errors.append("rim_features.slot_profile_points_xy must be non-empty")

    # ── v0.4: visual_fidelity extended ──
    visual = metadata.get("visual_fidelity") or {}
    if visual.get("contains_box_union_fir_tree_slots") is not False:
        errors.append("visual_fidelity.contains_box_union_fir_tree_slots must be False")
    if visual.get("contains_clean_symmetric_fir_tree_slots") is not True:
        errors.append("visual_fidelity.contains_clean_symmetric_fir_tree_slots must be True")
    if visual.get("contains_real_blade_attachment") is not False:
        errors.append("visual_fidelity.contains_real_blade_attachment must be False")

    # ── v0.3: safety extended ──
    safety = metadata.get("safety") or {}
    if safety.get("not_for_installation") is not True:
        errors.append("safety.not_for_installation must be True")
    if safety.get("no_structural_validation") is not True:
        errors.append("safety.no_structural_validation must be True")
    if safety.get("no_life_prediction") is not True:
        errors.append("safety.no_life_prediction must be True")

    # ── v0.2: hub_sleeve ──
    sleeve = metadata.get("hub_sleeve")
    if not isinstance(sleeve, dict):
        errors.append("metadata.hub_sleeve must be a dict")

    # ── v0.2: annular_details ──
    annular = metadata.get("annular_details")
    if not isinstance(annular, dict):
        errors.append("metadata.annular_details must be a dict")

    return errors
