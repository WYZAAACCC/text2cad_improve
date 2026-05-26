"""Compile CAD-IR into CadQuery Python scripts."""

from __future__ import annotations

from seekflow_engineering_tools.ir.cad import CADPartSpec


class CadQueryCompileError(RuntimeError):
    pass


def _compile_recipe(feature) -> list[str]:
    """Generate CadQuery code for a recipe feature."""
    from seekflow_engineering_tools.cadquery_backend.recipes import (
        CADQUERY_RECIPE_GENERATORS,
    )

    name = feature.recipe_name
    if name not in CADQUERY_RECIPE_GENERATORS:
        raise CadQueryCompileError(f"No CadQuery recipe generator for: {name}")

    gen = CADQUERY_RECIPE_GENERATORS[name]
    code = gen(feature.parameters)
    return code.strip().split("\n") if code else []


def _compile_extrude(feature) -> list[str]:
    """Generate CadQuery code for an extrude feature.

    Supports rectangle, circle, and polygon profiles.
    Supports add and cut operations.
    """
    lines = []
    op = feature.operation
    dir_sign = "-" if feature.direction == "-" else ""
    profile = feature.sketch.profile

    if op == "add":
        lines.append("result = (")
        lines.append(f"    cq.Workplane('{feature.sketch.plane}')")

        if profile.type == "rectangle":
            lines.append(
                f"    .rect({profile.width_mm}, {profile.height_mm})"
            )
        elif profile.type == "circle":
            lines.append(
                f"    .circle({profile.diameter_mm} / 2.0)"
            )
        elif profile.type == "polygon":
            pts = ", ".join(
                f"({p[0]}, {p[1]})" for p in profile.points_mm
            )
            lines.append(f"    .polyline([{pts}]).close()")
        else:
            raise CadQueryCompileError(f"Unsupported profile type: {profile.type}")

        lines.append(f"    .extrude({dir_sign}{feature.depth_mm})")
        lines.append(")")

    elif op == "cut":
        lines.append("result = (")
        lines.append("    result.faces('>Z').workplane()")

        if profile.type == "rectangle":
            lines.append(
                f"    .rect({profile.width_mm}, {profile.height_mm})"
            )
        elif profile.type == "circle":
            lines.append(
                f"    .circle({profile.diameter_mm} / 2.0)"
            )
        elif profile.type == "polygon":
            pts = ", ".join(
                f"({p[0]}, {p[1]})" for p in profile.points_mm
            )
            lines.append(f"    .polyline([{pts}]).close()")
        else:
            raise CadQueryCompileError(f"Unsupported profile type: {profile.type}")

        lines.append(f"    .cutBlind({dir_sign}{feature.depth_mm})")
        lines.append(")")

    return lines


def _compile_hole(feature) -> list[str]:
    """Generate CadQuery code for a hole feature.

    Supports through_all and depth_mm modes.
    Non-Z-axis holes raise CadQueryCompileError.
    """
    if feature.axis != "Z":
        raise CadQueryCompileError(
            f"CadQuery hole axis '{feature.axis}' is not supported. Only Z-axis holes are implemented."
        )

    lines = []
    hx, hy = feature.position_mm[:2]

    lines.append("result = (")
    lines.append("    result.faces('>Z').workplane()")
    lines.append(f"    .center({hx}, {hy})")

    if feature.through_all:
        lines.append(f"    .hole({feature.diameter_mm})")
    elif feature.depth_mm is not None:
        lines.append(f"    .hole({feature.diameter_mm}, depth={feature.depth_mm})")
    else:
        raise CadQueryCompileError(
            "Hole feature must set through_all=True or provide depth_mm."
        )

    lines.append(")")
    return lines


def _compile_circular_pattern_holes(feature) -> list[str]:
    """Generate CadQuery code for circular pattern holes."""
    lines = []
    cx, cy = feature.center_mm[:2]
    lines.append("result = (")
    lines.append("    result.faces('>Z').workplane()")
    lines.append(f"    .center({cx}, {cy})")
    lines.append(
        f"    .polarArray({feature.pitch_circle_diameter_mm / 2.0}, 0, 360, "
        f"{feature.count})"
    )
    lines.append(f"    .hole({feature.hole_diameter_mm})")
    lines.append(")")
    return lines


def _compile_fillet(feature) -> list[str]:
    """Generate CadQuery code for a fillet feature."""
    lines = [
        f"result = result.fillet({feature.radius_mm})"
    ]
    return lines


def _compile_chamfer(feature) -> list[str]:
    """Generate CadQuery code for a chamfer feature."""
    lines = [
        f"result = result.chamfer({feature.distance_mm})"
    ]
    return lines


def compile_cad_ir_to_cadquery_script(
    spec: CADPartSpec, out_step: str | None = None
) -> str:
    """Translate a validated CADPartSpec into a standalone CadQuery Python script.

    Returns the script as a string. The caller can write to a `.py` file and run it.
    """
    lines = [
        "import cadquery as cq",
        "from cadquery import exporters",
        "",
        "result = None",
    ]

    for feature in spec.features:
        if feature.type == "recipe":
            lines.extend(_compile_recipe(feature))
        elif feature.type == "extrude":
            lines.extend(_compile_extrude(feature))
        elif feature.type == "hole":
            lines.extend(_compile_hole(feature))
        elif feature.type == "circular_pattern_holes":
            lines.extend(_compile_circular_pattern_holes(feature))
        elif feature.type == "fillet":
            lines.extend(_compile_fillet(feature))
        elif feature.type == "chamfer":
            lines.extend(_compile_chamfer(feature))
        else:
            raise CadQueryCompileError(
                f"Unsupported feature type for cadquery: {feature.type}"
            )

    if out_step:
        lines.append(f'\ncq.exporters.export(result, r"{out_step}")')

    return "\n".join(lines)
