"""v0.5 legacy isolation tests — production modules must not import legacy symbols."""

import importlib
import inspect

PRODUCTION_MODULES = [
    "seekflow_engineering_tools.generative_cad.builder",
    "seekflow_engineering_tools.generative_cad.pipeline.run",
    "seekflow_engineering_tools.generative_cad.validation.pipeline",
    "seekflow_engineering_tools.generative_cad.tools",
]


class TestLegacyIsolation:
    def test_production_modules_do_not_import_legacy_symbols(self):
        for modname in PRODUCTION_MODULES:
            mod = importlib.import_module(modname)
            src = inspect.getsource(mod)
            # Check for actual import/usage, not just error message mentions
            assert "from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec" not in src, f"{modname} imports GenerativeCADSpec"
            assert "BASE_REGISTRY" not in src, f"{modname} references BASE_REGISTRY"

    def test_builder_rejects_legacy_spec(self):
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
        from seekflow_engineering_tools.generative_cad.legacy.ir_v01 import GenerativeCADSpec

        spec = GenerativeCADSpec.model_validate({
            "part_name": "legacy_test",
            "selected_bases": [{"base_id": "axisymmetric_base", "base_version": "0.1.0"}],
            "feature_graph": {
                "nodes": [{
                    "id": "n1", "base_id": "axisymmetric_base", "op": "revolve_profile",
                    "phase": "base_solid",
                    "params": {
                        "axis": "Z",
                        "profile_stations": [
                            {"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 5},
                            {"r_mm": 30, "z_front_mm": 5, "z_rear_mm": 10},
                        ],
                    },
                }],
            },
        })

        class FakeConfig:
            workspace_root = __import__("pathlib").Path("/tmp/test_legacy")
            allow_overwrite = True

        result = build_generative_cad_model(
            spec=spec, config=FakeConfig(),
            out_step="/tmp/test_legacy/out.step", inspect=False,
        )
        assert not result["ok"]
        assert "Legacy GenerativeCADSpec" in result["error"]
