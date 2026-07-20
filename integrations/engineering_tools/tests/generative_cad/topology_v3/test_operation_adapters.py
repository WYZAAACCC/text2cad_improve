"""PR-4: Operation-specific history adapters — §2.3, §2.4 tests.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.3, §2.4
"""

import inspect

from seekflow_engineering_tools.generative_cad.topology.operation_adapters import (
    BooleanHistoryAdapter,
    ChamferHistoryAdapter,
    FilletHistoryAdapter,
    LoftHistoryAdapter,
    OperationHistoryAdapter,
    PrismHistoryAdapter,
    RevolveHistoryAdapter,
    SweepHistoryAdapter,
    ThickSolidHistoryAdapter,
)

ALL_ADAPTERS = [
    PrismHistoryAdapter,
    RevolveHistoryAdapter,
    FilletHistoryAdapter,
    ChamferHistoryAdapter,
    ThickSolidHistoryAdapter,
    LoftHistoryAdapter,
    SweepHistoryAdapter,
    BooleanHistoryAdapter,
]


# ═══════════════════════════════════════════════════════════════════════════════
# §2.4 — Adapter protocol compliance
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdapterProtocolCompliance:
    """Every named adapter must expose the required interface."""

    def test_every_adapter_has_adapter_name(self):
        for adapter_cls in ALL_ADAPTERS:
            assert hasattr(adapter_cls, "adapter_name"), (
                f"{adapter_cls.__name__} missing adapter_name"
            )
            assert isinstance(adapter_cls.adapter_name, str)
            assert len(adapter_cls.adapter_name) > 0

    def test_every_adapter_has_execute_method(self):
        for adapter_cls in ALL_ADAPTERS:
            assert hasattr(adapter_cls, "execute"), (
                f"{adapter_cls.__name__} missing execute()"
            )
            assert callable(adapter_cls.execute)

    def test_every_adapter_has_extract_source_history_method(self):
        for adapter_cls in ALL_ADAPTERS:
            assert hasattr(adapter_cls, "extract_source_history"), (
                f"{adapter_cls.__name__} missing extract_source_history()"
            )

    def test_every_adapter_has_derive_operation_semantics_method(self):
        for adapter_cls in ALL_ADAPTERS:
            assert hasattr(adapter_cls, "derive_operation_semantics"), (
                f"{adapter_cls.__name__} missing derive_operation_semantics()"
            )

    def test_adapter_count_is_eight(self):
        """§2.4 requires at least 8 operation-specific adapters."""
        assert len(ALL_ADAPTERS) == 8, (
            f"Expected 8 adapters, got {len(ALL_ADAPTERS)}"
        )


class TestPrismRevolveSpecifics:
    """Prism and Revolve adapters must provide FirstShape/LastShape (§2.4)."""

    def test_prism_has_first_shape_last_shape(self):
        assert hasattr(PrismHistoryAdapter, "first_shape")
        assert hasattr(PrismHistoryAdapter, "last_shape")

    def test_revolve_has_first_shape_last_shape(self):
        assert hasattr(RevolveHistoryAdapter, "first_shape")
        assert hasattr(RevolveHistoryAdapter, "last_shape")

    def test_revolve_has_degenerated(self):
        """Revolve MUST track degenerated edges (§2.4)."""
        assert hasattr(RevolveHistoryAdapter, "degenerated"), (
            "RevolveHistoryAdapter must provide degenerated() for "
            "axis-touching profile edge tracking (§2.4)"
        )

    def test_loft_has_first_shape_last_shape(self):
        """Loft MUST provide FirstShape/LastShape for caps (§2.4)."""
        assert hasattr(LoftHistoryAdapter, "first_shape")
        assert hasattr(LoftHistoryAdapter, "last_shape")


class TestOperationHistoryAdapterProtocol:
    """OperationHistoryAdapter Protocol can be used for type checking."""

    def test_protocol_exists_and_is_importable(self):
        assert OperationHistoryAdapter is not None

    def test_protocol_has_expected_methods(self):
        methods = [
            m for m in dir(OperationHistoryAdapter)
            if not m.startswith("_") and callable(getattr(OperationHistoryAdapter, m, None))
        ]
        for required in ("execute", "extract_source_history", "derive_operation_semantics"):
            assert required in methods, (
                f"OperationHistoryAdapter Protocol missing {required}"
            )

    def test_prism_conforms_to_protocol_structurally(self):
        """PrismHistoryAdapter should conform to the Protocol structurally."""
        # Check all three protocol methods exist on the class
        for method_name in ("execute", "extract_source_history", "derive_operation_semantics"):
            assert hasattr(PrismHistoryAdapter, method_name), (
                f"PrismHistoryAdapter must implement {method_name} to "
                f"conform to OperationHistoryAdapter Protocol"
            )
