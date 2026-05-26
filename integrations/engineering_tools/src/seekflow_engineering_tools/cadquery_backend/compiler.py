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
    """Generate CadQuery code for an extrude feature."""
    lines = []
    op = feature.operation
    dir_sign = "-" if feature.direction == "-" else ""

    if op == "add":
        lines.append(
            f"result = ("
        )
        lines.append(
            f"    cq.Workplane('{feature.sketch.plane}')"
        )
        lines.append(
            f"    .rect({feature.sketch.profile.width_mm}, "
            f"{feature.sketch.profile.height_mm})"
        )
        lines.append(
            f"    .extrude({dir_sign}{feature.depth_mm})"
        )
        lines.append(")")
    elif op == "cut":
        lines.append(
            f"result = ("
        )
        lines.append(
            f"    result.faces('>Z').workplane()"
        )
        lines.append(
            f"    .rect({feature.sketch.profile.width_mm}, "
            f"{feature.sketch.profile.height_mm})"
        )
        lines.append(
            f"    .cutBlind({dir_sign}{feature.depth_mm})"
        )
        lines.append(")")
    return lines


def _compile_hole(feature) -> list[str]:
    """Generate CadQuery code for a hole feature."""
    lines = []
    hx, hy = feature.position_mm[:2]
    hz = feature.position_mm[2] if len(feature.position_mm) > 2 else 0

    lines.append(
        f"result = ("
    )
    lines.append(
        f"    result.faces('>Z').workplane()"
    )
    lines.append(
        f"    .center({hx}, {hy})"
    )
    depth_str = f"    .hole({feature.diameter_mm})"
    lines.append(depth_str)
    lines.append(")")
    return lines


def _compile_circular_pattern_holes(feature) -> list[str]:
    """Generate CadQuery code for circular pattern holes."""
    lines = []
    cx, cy = feature.center_mm[:2]
    lines.append(
        f"result = ("
    )
    lines.append(
        f"    result.faces('>Z').workplane()"
    )
    lines.append(
        f"    .center({cx}, {cy})"
    )
    lines.append(
        f"    .polarArray({feature.pitch_circle_diameter_mm / 2.0}, 0, 360, "
        f"{feature.count})"
    )
    lines.append(
        f"    .hole({feature.hole_diameter_mm})"
    )
    lines.append(")")
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
        else:
            raise CadQueryCompileError(
                f"Unsupported feature type for cadquery: {feature.type}"
            )

    if out_step:
        lines.append(f'\ncq.exporters.export(result, r"{out_step}")')

    return "\n".join(lines)
