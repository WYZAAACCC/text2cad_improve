"""v0.6: extended legacy isolation — more production modules checked."""

import importlib
import inspect

PRODUCTION_MODULES_V06 = [
    "seekflow_engineering_tools.generative_cad.builder",
    "seekflow_engineering_tools.generative_cad.pipeline.run",
    "seekflow_engineering_tools.generative_cad.validation.pipeline",
    "seekflow_engineering_tools.generative_cad.tools",
    "seekflow_engineering_tools.generative_cad.pipeline.metadata",
    "seekflow_engineering_tools.generative_cad.pipeline.import_artifact",
]

FORBIDDEN = [
    "GenerativeCADSpec",
    "SelectedBase",
    "FeatureGraph",
    "BASE_REGISTRY",
    "selected_bases",
    "feature_graph",
]


class TestLegacyIsolationV06:
    def test_production_modules_do_not_import_legacy_symbols(self):
        for modname in PRODUCTION_MODULES_V06:
            src = inspect.getsource(importlib.import_module(modname))
            for token in FORBIDDEN:
                # Only check for actual import statements, not error messages
                import_line = f"import {token}"
                from_line = f"from seekflow_engineering_tools.generative_cad.ir import {token}"
                from_legacy = f"from seekflow_engineering_tools.generative_cad.legacy"
                if import_line in src or from_line in src or (from_legacy in src and token in src and f"legacy.{token}" not in src and f"ir_v01.{token}" not in src):
                    assert False, f"{modname} imports forbidden legacy token: {token}"
