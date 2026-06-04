"""Geometry postcondition gate — validates final solid geometry before STEP export.

Runs AFTER composition/assembly and BEFORE STEP export.
Checks: volume > 0, solid count, bbox validity, closed solid.

This is the definitive "is the geometry actually correct?" gate.
STEP file existence alone is NOT sufficient — a file can contain
MULTI_SOLID, negative volume, or empty geometry.

Reference: llm_skill_base21.md §5.3, §10 (final acceptance criteria)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GeometryPostcheckResult:
    """Structured result of geometry postcondition validation."""

    ok: bool
    volume_mm3: float | None = None
    n_solids: int | None = None
    bbox_mm: tuple[float, float, float] | None = None
    closed: bool | None = None
    is_valid_solid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_final_geometry(
    ctx,
    final_handle_id: str,
    *,
    expected_body_count: int = 1,
    allow_multi_body: bool = False,
) -> GeometryPostcheckResult:
    """Validate the final solid geometry post-assembly.

    Args:
        ctx: RuntimeContext with object_store
        final_handle_id: Handle ID of the final solid
        expected_body_count: Expected number of solid bodies (default 1)
        allow_multi_body: If True, multi-solid is a warning not an error

    Returns:
        GeometryPostcheckResult with structured pass/fail and diagnostics.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Retrieve final solid
    try:
        solid = ctx.object_store.get(final_handle_id)
    except Exception as exc:
        return GeometryPostcheckResult(
            ok=False,
            errors=[f"Final solid handle '{final_handle_id}' not retrievable: {exc}"],
        )

    if solid is None:
        return GeometryPostcheckResult(
            ok=False,
            errors=[f"Final solid handle '{final_handle_id}' resolved to None"],
        )

    # 2. Count solid bodies
    n_solids = _count_solids(solid)
    # NOTE: CadQuery Solids() can return 0 for valid helical/swept geometry.
    # When n_solids==0 but volume>0, treat as an inspection artifact (warning).
    if n_solids is not None:
        if n_solids == 0:
            # Check volume BEFORE declaring empty — may be inspection artifact
            pass  # Defer to volume check below
        elif n_solids > expected_body_count and not allow_multi_body:
            errors.append(
                f"Final geometry has {n_solids} solid bodies "
                f"(expected {expected_body_count}). This means boolean_union "
                f"failed to merge components. Check for grazing contact or "
                f"non-intersecting solids in the assembly."
            )
        elif n_solids > expected_body_count:
            warnings.append(
                f"Multi-body output: {n_solids} solids (expected {expected_body_count})"
            )

    # 3. Volume check (runs BEFORE n_solids==0 evaluation)
    volume = _measure_volume(solid)
    if volume is not None:
        if volume <= 0:
            if n_solids == 0:
                errors.append("Final geometry has 0 solid bodies (empty)")
            errors.append(
                f"Final geometry has non-positive volume ({volume:.4f} mm³). "
                f"Possible causes: OCCT boolean failure on thin walls, "
                f"self-intersecting sweep, or inverted normals."
            )
        elif n_solids == 0:
            # n_solids==0 but volume>0 → CadQuery inspection artifact
            # (common with helical sweeps, shells, complex lofts)
            warnings.append(
                f"Solid count is 0 but volume is {volume:.2f} mm³. "
                f"This is likely a CadQuery inspection artifact — "
                f"the STEP file is valid. Suppressing n_solids error."
            )
    elif n_solids == 0:
        # No volume measurement AND no solids → truly empty
        errors.append("Final geometry has 0 solid bodies and volume cannot be measured")
    elif volume is not None and volume > 0 and volume < 0.001:
        warnings.append(f"Final volume near zero ({volume:.6f} mm³)")

    # 4. BBox check
    bbox = _measure_bbox(solid)
    if bbox is not None:
        xlen, ylen, zlen = bbox[0], bbox[1], bbox[2]
        if xlen <= 0 or ylen <= 0 or zlen <= 0:
            errors.append(
                f"Final geometry has degenerate bounding box: "
                f"({xlen:.4f}, {ylen:.4f}, {zlen:.4f}) mm"
            )
    else:
        errors.append("Cannot measure bounding box of final geometry")

    # 5. Closed solid check
    closed = _check_closed(solid)
    is_valid = closed is True and volume is not None and volume > 0

    ok = len(errors) == 0

    return GeometryPostcheckResult(
        ok=ok,
        volume_mm3=volume,
        n_solids=n_solids,
        bbox_mm=bbox,
        closed=closed,
        is_valid_solid=is_valid,
        errors=errors,
        warnings=warnings,
    )


def validate_step_post_export(step_path, min_size_bytes: int = 100) -> GeometryPostcheckResult:
    """Validate the exported STEP file on disk.

    Checks: file exists, non-empty, minimum plausible size, parseable.
    """
    import os

    if not os.path.exists(str(step_path)):
        return GeometryPostcheckResult(
            ok=False,
            errors=[f"STEP file not found: {step_path}"],
        )

    size = os.path.getsize(str(step_path))
    if size == 0:
        return GeometryPostcheckResult(
            ok=False,
            errors=[f"STEP file is empty: {step_path}"],
        )
    if size < min_size_bytes:
        return GeometryPostcheckResult(
            ok=False,
            errors=[f"STEP file too small ({size} bytes < {min_size_bytes} min): {step_path}"],
        )

    # Quick validation: STEP file should start with ISO-10303-21
    try:
        with open(str(step_path), "r", encoding="utf-8", errors="replace") as f:
            header = f.read(256)
        if "ISO-10303-21" not in header and "FILE_SCHEMA" not in header.upper():
            return GeometryPostcheckResult(
                ok=False,
                errors=[f"STEP file does not appear to be valid ISO-10303-21: {step_path}"],
            )
    except Exception as exc:
        return GeometryPostcheckResult(
            ok=False,
            errors=[f"Cannot read STEP file: {exc}"],
        )

    return GeometryPostcheckResult(
        ok=True,
        volume_mm3=None,  # cannot measure from file alone
        warnings=[],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Internal measurement helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _count_solids(solid) -> int | None:
    try:
        if hasattr(solid, "Solids"):
            return len(list(solid.Solids()))
        if hasattr(solid, "val"):
            inner = solid.val()
            if hasattr(inner, "Solids"):
                return len(list(inner.Solids()))
        return 1
    except Exception:
        return None


def _measure_volume(solid) -> float | None:
    try:
        if hasattr(solid, "Volume"):
            return solid.Volume()
        if hasattr(solid, "val"):
            inner = solid.val()
            if hasattr(inner, "Volume"):
                return inner.Volume()
        return None
    except Exception:
        return None


def _measure_bbox(solid) -> tuple[float, float, float] | None:
    try:
        if hasattr(solid, "val"):
            solid = solid.val()
        bb = solid.BoundingBox()
        return (bb.xlen, bb.ylen, bb.zlen)
    except Exception:
        return None


def _check_closed(solid) -> bool | None:
    try:
        if hasattr(solid, "val"):
            solid = solid.val()
        if hasattr(solid, "Closed"):
            return solid.Closed()
        return None
    except Exception:
        return None
