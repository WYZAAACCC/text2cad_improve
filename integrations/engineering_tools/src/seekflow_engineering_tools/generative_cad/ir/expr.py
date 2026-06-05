"""Strict JSON-safe expression model for derived dimensions and references.

DimExpr allows params to express derived values without hardcoding numbers:
  {"op": "ref", "args": [{"root_kind": "node", "root_id": "n1", "output": "body", "path": ["radius_max_mm"]}]}
  {"op": "sub", "args": [{"op": "ref", ...}, 2], "unit": "mm"}

Design invariants:
- No eval(), no Python expression strings, no dynamic dispatch
- Recursion depth capped at MAX_RECURSION_DEPTH (16)
- Division by near-zero → fail-closed
- Results must be finite

Phase 1: schema definition only (no evaluation).
Phase 2: evaluate_dim_expr() in analysis/expr_eval.py.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Allowed operations ──

DimOp = Literal[
    "const",
    "ref",
    "add",
    "sub",
    "mul",
    "div",
    "min",
    "max",
    "abs",
    "clamp",
]

ALLOWED_DIM_OPS: set[str] = set(DimOp.__args__)  # type: ignore[attr-defined]

# Allowed RefPath properties (Phase 1 whitelist).
# New properties must be added here explicitly — no arbitrary attribute access.
ALLOWED_REF_PROPERTIES: set[str] = {
    "radius_max_mm",
    "radius_min_mm",
    "length_z_mm",
    "bbox",
    "xlen_mm",
    "ylen_mm",
    "zlen_mm",
    "xmin_mm",
    "xmax_mm",
    "ymin_mm",
    "ymax_mm",
    "zmin_mm",
    "zmax_mm",
    "volume_mm3",
    "center_bore_radius_mm",
    "faces",
    "traits",
    "extra",
}

# Maximum recursion depth for nested DimExpr evaluation.
MAX_RECURSION_DEPTH = 16


# ═══════════════════════════════════════════════════════════════════════════════
# RefPath — typed reference to a component/node output property
# ═══════════════════════════════════════════════════════════════════════════════


class RefPath(BaseModel):
    """Typed reference to a geometric property of a component or node output.

    Examples:
        RefPath(root_kind="component", root_id="c1", output="body", path=["radius_max_mm"])
        RefPath(root_kind="node", root_id="n1", output="body", path=["bbox", "zlen_mm"])
        RefPath(root_kind="node", root_id="n2", output="body", path=["extra", "center_bore_radius_mm"])
    """

    model_config = ConfigDict(extra="forbid")

    root_kind: Literal["node", "component"] = Field(
        description="Whether root_id refers to a node or a component.",
    )
    root_id: str = Field(
        min_length=1,
        description="The node ID or component ID.",
    )
    output: str = Field(
        default="body",
        description="The output name of the referenced node/component (default: 'body').",
    )
    path: list[str] = Field(
        default_factory=list,
        description="Property path from the output (e.g. ['radius_max_mm'] or ['bbox', 'zlen_mm']).",
    )

    @model_validator(mode="after")
    def validate_path_segments(self) -> "RefPath":
        """Validate that path segments are in the allowed property whitelist.

        The first segment must always be whitelisted. Under 'extra' and
        'faces', sub-keys are free-form (they're defined at runtime by
        fact rules, not known at schema compile time).
        """
        if not self.path:
            return self

        for i, item in enumerate(self.path):
            if i == 0:
                # First segment must be a known top-level property
                if item not in ALLOWED_REF_PROPERTIES:
                    raise ValueError(
                        f"RefPath path segment {item!r} is not in the allowed property whitelist. "
                        f"Allowed: {sorted(ALLOWED_REF_PROPERTIES)}"
                    )
            elif self.path[0] in ("extra", "faces"):
                # Sub-keys under 'extra' and 'faces' are free-form
                continue
            elif item not in ALLOWED_REF_PROPERTIES:
                raise ValueError(
                    f"RefPath path segment {item!r} is not in the allowed property whitelist. "
                    f"Allowed: {sorted(ALLOWED_REF_PROPERTIES)}"
                )
        return self

    def __str__(self) -> str:
        p = ".".join(self.path)
        return f"{self.root_kind}.{self.root_id}.{self.output}" + (f".{p}" if p else "")


# ═══════════════════════════════════════════════════════════════════════════════
# DimExpr — strict JSON-safe dimension expression
# ═══════════════════════════════════════════════════════════════════════════════


class DimExpr(BaseModel):
    """A dimension expression — JSON-safe, no eval, strict whitelist.

    LLM may emit DimExpr objects in node.params where numeric values are expected.
    The compiler resolves them at analysis time (Phase 2+) using ShapeFacts.

    Example (LLM output):
        {"op": "sub", "args": [{"op": "ref", "args": [{"root_kind": "node", "root_id": "n1", "path": ["radius_max_mm"]}]}, 2.0]}

    Example (concrete):
        {"op": "const", "args": [50.0]}

    Example (PCD = outer_radius - margin):
        {"op": "sub", "args": [
            {"op": "div", "args": [{"op": "ref", "args": [{"root_kind": "node", "root_id": "n1", "output": "body", "path": ["radius_max_mm"]}]}, 2]},
            1.0
        ]}
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["dim_expr"] = "dim_expr"

    op: DimOp = Field(
        description="The operation: const, ref, add, sub, mul, div, min, max, abs, clamp.",
    )
    args: list[Any] = Field(
        default_factory=list,
        description="Arguments: numbers, RefPath dicts, or nested DimExpr dicts.",
    )
    unit: Literal["mm", "deg", "unitless"] = Field(
        default="mm",
        description="The unit of the result.",
    )

    @model_validator(mode="after")
    def validate_arg_count(self) -> "DimExpr":
        """Validate the number and type of arguments for each operation."""
        if self.op == "const":
            if len(self.args) != 1 or not isinstance(self.args[0], (int, float)):
                raise ValueError("const DimExpr requires exactly one numeric arg")
        elif self.op == "ref":
            if len(self.args) != 1:
                raise ValueError("ref DimExpr requires exactly one RefPath-like arg")
            # Validate that a ref arg can be parsed as RefPath
            ref_arg = self.args[0]
            if isinstance(ref_arg, dict):
                try:
                    RefPath.model_validate(ref_arg)
                except Exception as e:
                    raise ValueError(f"ref DimExpr arg is not a valid RefPath: {e}") from e
        elif self.op in ("add", "sub", "mul", "div", "min", "max"):
            if len(self.args) < 2:
                raise ValueError(f"{self.op} DimExpr requires at least 2 args")
        elif self.op == "abs":
            if len(self.args) != 1:
                raise ValueError("abs DimExpr requires exactly one arg")
        elif self.op == "clamp":
            if len(self.args) != 3:
                raise ValueError("clamp DimExpr requires exactly 3 args (value, min, max)")
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# DimExprOrFloat — Pydantic-compatible type that accepts both float and DimExpr
# ═══════════════════════════════════════════════════════════════════════════════


def _validate_dim_expr_or_float(v: Any) -> Any:
    """Before-validator: pass float/int through (with positivity check),
    validate and pass DimExpr dict through (skips numeric constraints).

    DimExpr dicts are allowed through without resolution — they will be
    resolved at analysis time by the FactPropagationPass using upstream
    ShapeFacts. The resolved value replaces the dict in typed_params.

    For numeric values, enforces positivity (> 0) as a basic sanity check.
    For DimExpr dicts, positivity cannot be checked statically — it will
    be verified when the expression is resolved at analysis time.
    """
    if isinstance(v, (int, float)):
        if v != v:  # NaN
            raise ValueError(f"NaN is not a valid dimension value")
        if abs(v) == float("inf"):
            raise ValueError(f"Infinity is not a valid dimension value")
        if v <= 0:
            raise ValueError(f"Dimension must be positive, got {v}")
        return float(v)
    if isinstance(v, dict) and v.get("kind") == "dim_expr":
        # Validate that it's a well-formed DimExpr
        try:
            DimExpr.model_validate(v)
        except Exception as exc:
            raise ValueError(f"Invalid DimExpr: {exc}") from exc
        return v  # Pass through — will be resolved by compiler middle-end
    raise ValueError(
        f"Expected a positive number or DimExpr dict, got {type(v).__name__}: {v!r}"
    )


# Use typing.Annotated for Pydantic v2 compatibility
from typing import Annotated, Union as TypingUnion  # noqa: E402


# DimExprOrFloat: a Pydantic-compatible field type that accepts either
# a positive float or a well-formed DimExpr dict. Uses BeforeValidator
# to intercept both cases before Pydantic's type coercion.
# NOTE: do NOT use Field(gt=0) with this type — the BeforeValidator
# handles positivity checks internally for numeric values, and dict
# values cannot be compared with >. Use plain Field() or Field(default=...).
try:
    from pydantic import BeforeValidator

    DimExprOrFloat = Annotated[
        TypingUnion[float, dict[str, Any]],
        BeforeValidator(_validate_dim_expr_or_float),
    ]
except ImportError:
    # Fallback: plain union type (Pydantic v1 or no Pydantic)
    DimExprOrFloat = TypingUnion[float, dict[str, Any]]  # type: ignore[misc]


# ── Helper: check if a value is a DimExpr-like dict ──


def is_dim_expr(value: Any) -> bool:
    """Return True if a value looks like a DimExpr dict."""
    return isinstance(value, dict) and value.get("kind") == "dim_expr"


def is_ref_path(value: Any) -> bool:
    """Return True if a value looks like a RefPath dict."""
    return isinstance(value, dict) and "root_kind" in value and "root_id" in value
