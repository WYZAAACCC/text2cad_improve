"""unify/mirror are wired into the composition dialect."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.composition.dialect import (
    CompositionDialect,
)
from seekflow_engineering_tools.generative_cad.dialects.composition.handlers import (
    handle_mirror,
    handle_unify,
)


def test_unify_operation_spec_exists():
    spec = CompositionDialect().get_op_spec("unify")
    assert spec.op == "unify"
    assert spec.handler is handle_unify


def test_mirror_operation_spec_exists():
    spec = CompositionDialect().get_op_spec("mirror")
    assert spec.op == "mirror"
    assert spec.handler is handle_mirror
