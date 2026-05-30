"""v0.7: extended legacy isolation — more production modules checked, error-message safe."""

import importlib
import inspect

PRODUCTION_MODULES_V07 = [
    "seekflow_engineering_tools.generative_cad.builder",
    "seekflow_engineering_tools.generative_cad.pipeline.run",
    "seekflow_engineering_tools.generative_cad.validation.pipeline",
    "seekflow_engineering_tools.generative_cad.tools",
    "seekflow_engineering_tools.generative_cad.pipeline.metadata",
    "seekflow_engineering_tools.generative_cad.pipeline.import_artifact",
    "seekflow_engineering_tools.generative_cad.pipeline.artifact",
    "seekflow_engineering_tools.generative_cad.runtime.postconditions",
    "seekflow_engineering_tools.generative_cad.repair.patch",
]

FORBIDDEN_IMPORT_TOKENS = [
    "from seekflow_engineering_tools.generative_cad.ir_v01 import",
    "from seekflow_engineering_tools.generative_cad.legacy",
    "GenerativeCADSpec(",
    "SelectedBase(",
    "FeatureGraph(",
    "BASE_REGISTRY",
]

# Symbols that may appear in error strings but are NOT forbidden imports
FORBIDDEN_IMPORT_ONLY = [
    "GenerativeCADSpec",
    "SelectedBase",
    "feature_graph",
    "selected_bases",
]


class TestLegacyIsolationV07:
    def test_production_modules_do_not_import_legacy_symbols(self):
        for modname in PRODUCTION_MODULES_V07:
            src = inspect.getsource(importlib.import_module(modname))
            for token in FORBIDDEN_IMPORT_TOKENS:
                if token in src:
                    # Allow "Legacy GenerativeCADSpec" in error strings (builder.py's legacy rejection)
                    if token.startswith("from ") or token.startswith("GenerativeCADSpec(") or token.startswith("SelectedBase(") or token.startswith("FeatureGraph("):
                        lines = src.split("\n")
                        for line in lines:
                            if token in line:
                                # Skip error message strings
                                if '"Legacy GenerativeCADSpec' in line or "'Legacy GenerativeCADSpec" in line:
                                    continue
                                if token in line and not line.strip().startswith("#"):
                                    assert False, f"{modname} imports or constructs forbidden legacy token: {token} in line: {line.strip()}"
                    elif token == "BASE_REGISTRY":
                        assert False, f"{modname} references forbidden legacy token: {token}"
