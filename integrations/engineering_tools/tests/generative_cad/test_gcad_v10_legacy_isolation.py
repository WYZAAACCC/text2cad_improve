"""v1.0: legacy isolation — production modules must not import legacy schema."""

import importlib
import inspect

PRODUCTION_MODULES_V10 = [
    "seekflow_engineering_tools.generative_cad.builder",
    "seekflow_engineering_tools.generative_cad.pipeline.run",
    "seekflow_engineering_tools.generative_cad.pipeline.metadata",
    "seekflow_engineering_tools.generative_cad.pipeline.import_artifact",
    "seekflow_engineering_tools.generative_cad.validation.pipeline",
    "seekflow_engineering_tools.generative_cad.tools",
    "seekflow_engineering_tools.generative_cad.skills.prompts",
]

FORBIDDEN_IMPORT_PATTERNS = [
    "from seekflow_engineering_tools.generative_cad.ir import",
    "from seekflow_engineering_tools.generative_cad.registry import",
    "from seekflow_engineering_tools.generative_cad.base import",
    "GenerativeCADSpec(",
    "SelectedBase(",
    "FeatureGraph(",
    "BASE_REGISTRY",
    "selected_bases=",
    "feature_graph=",
]


class TestLegacyIsolationV10:
    def test_production_modules_do_not_import_legacy_schema(self):
        for module_name in PRODUCTION_MODULES_V10:
            src = inspect.getsource(importlib.import_module(module_name))
            for pattern in FORBIDDEN_IMPORT_PATTERNS:
                # Allow "Legacy GenerativeCADSpec" in error message strings only
                if pattern == "GenerativeCADSpec(":
                    lines = src.split("\n")
                    for line in lines:
                        if pattern in line:
                            if '"Legacy GenerativeCADSpec' in line or "'Legacy GenerativeCADSpec" in line:
                                continue
                            if not line.strip().startswith("#"):
                                assert False, f"{module_name}: {pattern!r} in line: {line.strip()}"
                else:
                    assert pattern not in src, f"{module_name} contains legacy pattern {pattern!r}"
