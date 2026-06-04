"""Safe boolean operations with controlled degradation.

v6.3: Added fuzzy_fuse + heal_shape + boolean_union_safe to replace
the old translate-margin hack in composition/handlers.py.

Fillet strategy: try full radius → try 0.5*radius → try 0.25*radius → skip with record.
All failures produce degraded feature records for audit trail.
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════════════════════════
# v6.3: Safe boolean union (replaces translate-margin hack)
# ═══════════════════════════════════════════════════════════════════════════════


def heal_shape(shape):
    """Repair B-Rep topology errors without changing geometry.

    Uses OCCT ShapeFix_Shape to fix common issues like:
    - Tiny gaps between faces
    - Inconsistent edge tolerances
    - Degenerate edges/faces

    Returns repaired shape, or original if repair fails.
    """
    try:
        from OCP.ShapeFix import ShapeFix_Shape
        fixer = ShapeFix_Shape()
        fixer.Init(shape)
        fixer.Perform()
        return fixer.Shape()
    except Exception:
        return shape


def fuzzy_fuse_shapes(a_shape, b_shape, fuzzy_mm: float):
    """Fuse two shapes with fuzzy tolerance — no geometry movement.

    Uses OCCT BRepAlgoAPI_Fuse.SetFuzzyValue() to handle near-tangent
    and grazing contact. Unlike the old translate-margin hack, this does
    NOT change the position of either solid.
    """
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

        # Attempt 1: OCCT 7.6+ direct constructor
        try:
            fuse = BRepAlgoAPI_Fuse(a_shape, b_shape)
        except TypeError:
            # Attempt 2: Older OCCT — empty constructor + SetArguments/SetTools
            from OCP.TopTools import TopTools_ListOfShape
            args = TopTools_ListOfShape()
            args.Append(a_shape)
            tools = TopTools_ListOfShape()
            tools.Append(b_shape)
            fuse = BRepAlgoAPI_Fuse()
            fuse.SetArguments(args)
            fuse.SetTools(tools)

        if fuzzy_mm > 0:
            try:
                fuse.SetFuzzyValue(fuzzy_mm)
            except AttributeError:
                pass  # Older OCCT may not support SetFuzzyValue

        fuse.Build()

        if not fuse.IsDone():
            raise RuntimeError("BRepAlgoAPI_Fuse with fuzzy tolerance failed")
        return fuse.Shape()
    except ImportError:
        raise


def boolean_union_safe(a, b, tolerance, *, allow_compound: bool = False):
    """Safe boolean union with progressive fallback.

    Attempt 1: CadQuery union
    Attempt 2: OCCT fuzzy fuse (no geometry movement)
    Attempt 3: Shape healing + fuzzy fuse
    Attempt 4: Compound (multi-body, if allowed)
    Failure: hard fail — NO silent degradation, NO geometry movement
    """
    import cadquery as cq

    # Attempt 1: CadQuery union
    try:
        result = a.union(b)
        if _is_single_valid_solid(result):
            return result, []
    except Exception:
        pass

    # Attempt 2: OCCT fuzzy fuse
    fuzzy_levels = [
        tolerance.linear_mm,
        tolerance.linear_mm * 5,
        tolerance.linear_mm * 10,
    ]
    for fuzzy in fuzzy_levels:
        try:
            a_w = a.val().wrapped if hasattr(a, 'val') else a.wrapped
            b_w = b.val().wrapped if hasattr(b, 'val') else b.wrapped
            shape = fuzzy_fuse_shapes(a_w, b_w, fuzzy)
            wp = cq.Workplane(obj=shape)
            if _is_single_valid_solid(wp):
                return wp, [{"strategy": "fuzzy_fuse", "fuzzy_mm": fuzzy}]
        except Exception:
            pass

    # Attempt 3: Shape healing + fuzzy fuse
    try:
        a_w = a.val().wrapped if hasattr(a, 'val') else a.wrapped
        b_w = b.val().wrapped if hasattr(b, 'val') else b.wrapped
        ah = heal_shape(a_w)
        bh = heal_shape(b_w)
        shape = fuzzy_fuse_shapes(ah, bh, tolerance.linear_mm * 10)
        wp = cq.Workplane(obj=shape)
        if _is_single_valid_solid(wp):
            return wp, [{"strategy": "heal_and_fuse"}]
    except Exception:
        pass

    # Attempt 4: Compound
    if allow_compound:
        from OCP.TopoDS import TopoDS_Compound
        from OCP.BRep import BRep_Builder
        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        a_w = a.val().wrapped if hasattr(a, 'val') else a.wrapped
        b_w = b.val().wrapped if hasattr(b, 'val') else b.wrapped
        builder.Add(compound, a_w)
        builder.Add(compound, b_w)
        return cq.Workplane(obj=compound), [{"strategy": "compound"}]

    raise RuntimeError(
        "boolean_union_safe: all strategies failed. "
        "Check for non-intersecting geometry or grazing contact."
    )


def _is_single_valid_solid(wp) -> bool:
    """Check that a Workplane contains exactly one valid solid."""
    try:
        if hasattr(wp, 'Solids'):
            return len(list(wp.Solids())) == 1
        inner = wp.val() if hasattr(wp, 'val') else wp
        if hasattr(inner, 'Solids'):
            return len(list(inner.Solids())) == 1
        return inner.Volume() > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Fillet fallback (existing, unchanged)
# ═══════════════════════════════════════════════════════════════════════════════


def try_fillet_with_fallback(
    body,
    radius_mm: float,
    selector: str = "all_external_edges",
    fallback_ratios: tuple[float, ...] = (0.5, 0.25),
):
    """Attempt fillet with progressive radius reduction.

    selector values:
    - "all_external_edges": body.fillet(radius)
    - "top_edges": edges on +Z facing faces
    - "bottom_edges": edges on -Z facing faces
    - "vertical_edges": edges parallel to Z

    Returns (result_body, degraded_records).
    """
    if radius_mm <= 0:
        return body, []

    radii_to_try = [radius_mm] + [radius_mm * r for r in fallback_ratios]
    degraded: list[dict] = []

    for r in radii_to_try:
        if r < 0.1:
            continue
        try:
            if selector == "all_external_edges":
                return body.fillet(r), degraded
            elif selector == "top_edges":
                result = _fillet_faces(body, ">Z", r)
            elif selector == "bottom_edges":
                result = _fillet_faces(body, "<Z", r)
            elif selector == "vertical_edges":
                result = _fillet_vertical(body, r)
            else:
                return body.fillet(r), degraded

            if result is not None:
                return result, degraded
        except (ValueError, RuntimeError) as e:
            degraded.append({
                "radius_attempted": r,
                "selector": selector,
                "error": str(e)[:200],
            })

    degraded.append({
        "radius_attempted": radius_mm,
        "selector": selector,
        "result": "skipped_all_fallbacks",
    })
    return body, degraded


def _fillet_faces(body, face_selector: str, radius: float):
    """Fillet edges on faces matching a CadQuery selector."""
    try:
        faces = body.faces(face_selector)
        edges = faces.edges()
        return edges.fillet(radius)
    except Exception:
        return None


def _fillet_vertical(body, radius: float):
    """Fillet edges approximately parallel to Z axis."""
    try:
        return body.edges("|Z").fillet(radius)
    except Exception:
        return None
