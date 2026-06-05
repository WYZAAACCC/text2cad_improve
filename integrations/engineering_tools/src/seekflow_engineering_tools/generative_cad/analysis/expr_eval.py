"""DimExpr evaluator — resolve symbolic dimension expressions using ShapeFacts.

Phase 2: evaluate_dim_expr() resolves DimExpr dicts to concrete float values
by looking up RefPath targets in FactStore and recursively computing arithmetic.

Design invariants:
- No eval(), no Python expression strings, no dynamic dispatch.
- All operations are whitelisted in ir/expr.py DimOp.
- Unknown references → returns None (not error — caller decides).
- Division by near-zero → ValueError.
- Recursion depth capped at MAX_RECURSION_DEPTH (16).
"""

from __future__ import annotations

from typing import Any


def evaluate_dim_expr(
    expr: float | int | dict[str, Any],
    store: Any,  # FactStore
    *,
    depth: int = 0,
) -> float | None:
    """Evaluate a DimExpr to a concrete float value.

    Args:
        expr: A numeric value (returned as-is) or a DimExpr dict.
        store: FactStore containing ShapeFacts for RefPath resolution.
        depth: Current recursion depth (internal, capped at MAX_RECURSION_DEPTH).

    Returns:
        The resolved float value, or None if any reference is unresolved.

    Raises:
        ValueError: On division by zero, invalid operations, or recursion overflow.
    """
    from seekflow_engineering_tools.generative_cad.ir.expr import (
        MAX_RECURSION_DEPTH,
        DimExpr,
        RefPath,
        is_dim_expr,
    )

    # ── Numeric literal ──
    if isinstance(expr, (int, float)):
        if expr != expr:  # NaN check
            raise ValueError("DimExpr evaluation encountered NaN")
        if abs(expr) == float("inf"):
            raise ValueError("DimExpr evaluation encountered infinity")
        return float(expr)

    # ── Not a DimExpr dict ──
    if not is_dim_expr(expr):
        return None

    # ── Recursion guard ──
    if depth >= MAX_RECURSION_DEPTH:
        raise ValueError(
            f"DimExpr recursion depth exceeded ({MAX_RECURSION_DEPTH})"
        )

    # Validate and parse
    try:
        dim = DimExpr.model_validate(expr)
    except Exception as exc:
        raise ValueError(f"Invalid DimExpr: {exc}") from exc

    # ── const ──
    if dim.op == "const":
        return float(dim.args[0])

    # ── ref ──
    if dim.op == "ref":
        return _resolve_ref(dim.args[0], store)

    # ── abs ──
    if dim.op == "abs":
        val = evaluate_dim_expr(dim.args[0], store, depth=depth + 1)
        if val is None:
            return None
        return abs(val)

    # ── clamp ──
    if dim.op == "clamp":
        val = evaluate_dim_expr(dim.args[0], store, depth=depth + 1)
        lo = evaluate_dim_expr(dim.args[1], store, depth=depth + 1)
        hi = evaluate_dim_expr(dim.args[2], store, depth=depth + 1)
        if val is None or lo is None or hi is None:
            return None
        return max(lo, min(hi, val))

    # ── Arithmetic: add, sub, mul, div, min, max ──
    # All require at least 2 args
    values: list[float] = []
    for arg in dim.args:
        v = evaluate_dim_expr(arg, store, depth=depth + 1)
        if v is None:
            return None
        values.append(v)

    if dim.op == "add":
        return sum(values)
    elif dim.op == "sub":
        result = values[0]
        for v in values[1:]:
            result -= v
        return result
    elif dim.op == "mul":
        result = 1.0
        for v in values:
            result *= v
        return result
    elif dim.op == "div":
        result = values[0]
        for v in values[1:]:
            if abs(v) < 1e-15:
                raise ValueError("DimExpr division by near-zero value")
            result /= v
        return result
    elif dim.op == "min":
        return min(values)
    elif dim.op == "max":
        return max(values)

    raise ValueError(f"Unknown DimExpr operation: {dim.op!r}")


def _resolve_ref(ref_arg: Any, store: Any) -> float | None:
    """Resolve a RefPath argument to a numeric value from FactStore.

    Supports path segments:
    - ["radius_max_mm"] → facts.radius_max_mm.value
    - ["bbox", "xlen_mm"] → facts.bbox.xlen_mm.value
    - ["extra", "center_bore_radius_mm"] → facts.extra["center_bore_radius_mm"]
    """
    from seekflow_engineering_tools.generative_cad.ir.expr import RefPath

    if isinstance(ref_arg, dict):
        try:
            ref = RefPath.model_validate(ref_arg)
        except Exception:
            return None
    elif isinstance(ref_arg, RefPath):
        ref = ref_arg
    else:
        return None

    # Look up ShapeFacts from store
    facts = None
    if ref.root_kind == "node":
        facts = store.get_node_output(ref.root_id, ref.output)
    elif ref.root_kind == "component":
        facts = store.get_component_output(ref.root_id, ref.output)

    if facts is None:
        return None

    # Walk the path to get the value
    return _walk_fact_path(facts, ref.path)


def _walk_fact_path(facts, path: list[str]) -> float | None:
    """Walk a path into a ShapeFacts to extract a numeric value.

    Supported paths:
    - [] → None (no property specified)
    - ["radius_max_mm"] → facts.radius_max_mm.value
    - ["radius_min_mm"] → facts.radius_min_mm.value
    - ["length_z_mm"] → facts.length_z_mm.value
    - ["volume_mm3"] → facts.volume_mm3.value
    - ["bbox", "xlen_mm"] → facts.bbox.xlen_mm.value
    - ["bbox", "ylen_mm"] → facts.bbox.ylen_mm.value
    - ["bbox", "zlen_mm"] → facts.bbox.zlen_mm.value
    - ["bbox", "xmin_mm"] → facts.bbox.xmin_mm.value
    - ... (any BBoxFacts field)
    - ["extra", "<key>"] → facts.extra["<key>"] (must be numeric)
    """
    if not path:
        return None

    current: Any = facts
    for i, segment in enumerate(path):
        if hasattr(current, segment):
            current = getattr(current, segment)
        elif isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None

        # If this is the last segment, try to extract numeric value
        if i == len(path) - 1:
            # NumericFact → .value
            if hasattr(current, "value"):
                return current.value
            # Plain numeric
            if isinstance(current, (int, float)):
                return float(current)
            return None

    return None


# ── Convenience: resolve all DimExpr in typed_params ──


def resolve_typed_params_dim_exprs(
    typed_params: dict[str, Any],
    store: Any,
) -> dict[str, Any]:
    """Resolve all DimExpr values in typed_params to concrete floats.

    For each value in typed_params:
    - If it's a DimExpr dict → evaluate and replace with float
    - If it's a nested dict/list → recurse
    - Otherwise → pass through unchanged

    Returns a new dict with DimExprs resolved. Unknown refs remain as-is
    (the caller can detect them by checking for dict values).
    """
    resolved: dict[str, Any] = {}
    for key, value in typed_params.items():
        resolved[key] = _resolve_value(value, store)
    return resolved


def _resolve_value(value: Any, store: Any) -> Any:
    """Recursively resolve DimExpr values."""
    from seekflow_engineering_tools.generative_cad.ir.expr import is_dim_expr

    if is_dim_expr(value):
        result = evaluate_dim_expr(value, store)
        return result if result is not None else value  # keep original if unresolved

    if isinstance(value, dict):
        return {k: _resolve_value(v, store) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_value(v, store) for v in value]

    return value
