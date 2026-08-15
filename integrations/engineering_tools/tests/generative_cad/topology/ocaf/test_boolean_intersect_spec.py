"""boolean_intersect is wired into the composition dialect."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import (
    CompositionDialect,
)
from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import (
    handle_boolean_intersect,
)


def test_boolean_intersect_operation_spec_exists():
    spec = CompositionDialect().get_op_spec("boolean_intersect")
    assert spec.op == "boolean_intersect"
    assert spec.handler is handle_boolean_intersect
