"""Test that the generative CAD path does NOT pollute existing main chain.

Verifies:
- CADPartSpec still rejects type="generative"
- PRIMITIVE_REGISTRY does not contain generative bases
- CAPABILITIES["cadquery"]["stable_primitives"] does not contain generative bases
"""

import pytest


class TestCADPartSpecNotPolluted:
    def test_cad_part_spec_rejects_generative_type(self):
        """CADPartSpec should reject feature type='generative'."""
        from seekflow_engineering_tools.ir.cad import CADPartSpec

        with pytest.raises(ValueError):
            CADPartSpec.model_validate({
                "name": "test",
                "units": "mm",
                "target_backend": ["cadquery"],
                "features": [
                    {
                        "id": "f1",
                        "type": "generative",
                        "graph": {},
                    }
                ],
            })


class TestPrimitiveRegistryNotPolluted:
    def test_primitive_registry_has_no_generative_bases(self):
        """PRIMITIVE_REGISTRY should NOT contain generative base_ids."""
        from seekflow_engineering_tools.geometry_primitives.registry import (
            PRIMITIVE_REGISTRY,
        )

        generative_names = ["axisymmetric_base", "sketch_extrude_base"]
        for name in generative_names:
            assert name not in PRIMITIVE_REGISTRY, (
                f"Generative base {name!r} leaked into PRIMITIVE_REGISTRY!"
            )

    def test_primitive_registry_only_has_real_primitives(self):
        """PRIMITIVE_REGISTRY should only have known primitives."""
        from seekflow_engineering_tools.geometry_primitives.registry import (
            PRIMITIVE_REGISTRY,
        )

        valid_primitives = {"involute_spur_gear", "axisymmetric_turbine_disk"}
        for name in PRIMITIVE_REGISTRY:
            assert name in valid_primitives, (
                f"Unknown primitive {name!r} in registry. "
                "Generative bases must not leak into primitive registry."
            )


class TestCapabilitiesNotPolluted:
    def test_cadquery_stable_primitives_no_generative(self):
        """CAPABILITIES["cadquery"]["stable_primitives"] must NOT contain generative bases."""
        from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

        cq_primitives = CAPABILITIES.get("cadquery", {}).get("stable_primitives", [])
        generative_names = ["axisymmetric_base", "sketch_extrude_base"]
        for name in generative_names:
            assert name not in cq_primitives, (
                f"Generative base {name!r} leaked into cadquery stable_primitives!"
            )

    def test_all_backend_stable_primitives_no_generative(self):
        """No backend's stable_primitives should contain generative bases."""
        from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

        generative_names = ["axisymmetric_base", "sketch_extrude_base"]
        for backend, cap in CAPABILITIES.items():
            if "stable_primitives" not in cap:
                continue
            for name in generative_names:
                assert name not in cap["stable_primitives"], (
                    f"Generative base {name!r} leaked into {backend} stable_primitives!"
                )


class TestPrimitiveCompilerNotPolluted:
    def test_primitive_compiler_no_generative(self):
        """PRIMITIVE_COMPILERS should not contain generative base entries."""
        from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
            PRIMITIVE_COMPILERS,
        )

        generative_names = ["axisymmetric_base", "sketch_extrude_base"]
        for name in generative_names:
            assert name not in PRIMITIVE_COMPILERS, (
                f"Generative base {name!r} leaked into PRIMITIVE_COMPILERS!"
            )


class TestExistingBuilderNotAffected:
    def test_existing_build_still_accepts_cad_part_spec(self):
        """Existing build function should still accept CADPartSpec (just schema check)."""
        from seekflow_engineering_tools.ir.cad import CADPartSpec

        spec = CADPartSpec.model_validate({
            "name": "test_box",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [
                {
                    "id": "box1",
                    "type": "recipe",
                    "recipe_name": "box",
                    "parameters": {
                        "length_mm": 100,
                        "width_mm": 50,
                        "height_mm": 30,
                    },
                }
            ],
        })
        assert spec.name == "test_box"
        assert len(spec.features) == 1
