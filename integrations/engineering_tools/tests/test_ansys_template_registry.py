"""Test ANSYS template registry and schema validation."""

import pytest
from seekflow_engineering_tools.ansys.apdl_templates import list_templates, render_template
from seekflow_engineering_tools.ansys.template_registry import (
    ANSYS_TEMPLATE_SCHEMAS,
    validate_template_parameters,
)


class TestAnsysTemplateRegistry:
    def test_list_templates_contains_all_six(self):
        assert set(list_templates()) == {
            "static_cantilever_beam_rect",
            "plate_with_hole_tension",
            "beam_thermal",
            "cantilever_modal",
            "buckling_column",
            "bilinear_plastic",
        }

    def test_all_templates_render(self):
        """Each template should render with its default/minimal params."""
        for name in list_templates():
            from seekflow_engineering_tools.ansys.template_registry import (
                ANSYS_TEMPLATE_SCHEMAS,
            )
            schema = ANSYS_TEMPLATE_SCHEMAS[name]
            params = {}
            for pname, pinfo in schema["parameters"].items():
                if "default" in pinfo:
                    params[pname] = pinfo["default"]
                elif pinfo.get("required"):
                    # Provide a stub value for required params
                    ptype = pinfo.get("type", "float")
                    if ptype == "int":
                        params[pname] = 10
                    else:
                        params[pname] = 100.0
            apdl = render_template(name, **params)
            assert isinstance(apdl, str)
            assert len(apdl) > 100, f"Template '{name}' too short"
            assert "/CLEAR" in apdl, f"Template '{name}' missing /CLEAR"

    def test_bad_template_name_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            render_template("nonexistent_template")

    def test_template_schemas_exist_for_all(self):
        template_names = set(list_templates())
        schema_names = set(ANSYS_TEMPLATE_SCHEMAS.keys())
        assert template_names == schema_names

    def test_validate_template_parameters_fills_defaults(self):
        params = validate_template_parameters("plate_with_hole_tension", {})
        assert "plate_width_mm" in params
        assert params["plate_width_mm"] == 200.0

    def test_validate_template_parameters_bad_template(self):
        with pytest.raises(ValueError, match="Unknown"):
            validate_template_parameters("bad_template", {})

    def test_validate_template_parameters_required_missing(self):
        with pytest.raises(ValueError, match="requires"):
            validate_template_parameters("static_cantilever_beam_rect", {})

    def test_validate_template_parameters_passes_through(self):
        params = validate_template_parameters(
            "static_cantilever_beam_rect",
            {"length_mm": 300.0, "width_mm": 25.0, "height_mm": 25.0, "force_n": 500.0},
        )
        assert params["length_mm"] == 300.0
        assert params["element_size_mm"] == 10.0  # default

    def test_cantilever_beam_apdl_contains_keywords(self):
        apdl = render_template(
            "static_cantilever_beam_rect",
            length_mm=200, width_mm=20, height_mm=20, force_n=100,
        )
        assert "SOLID185" in apdl
        assert "ANTYPE,STATIC" in apdl

    def test_plate_with_hole_tension_apdl_contains_keywords(self):
        apdl = render_template("plate_with_hole_tension")
        assert "PLANE182" in apdl
        assert "STRESS_CONCENTRATION_Kt" in apdl

    def test_beam_thermal_apdl_contains_keywords(self):
        apdl = render_template("beam_thermal")
        assert "SOLID70" in apdl
        assert "TEMP" in apdl

    def test_cantilever_modal_apdl_contains_keywords(self):
        apdl = render_template("cantilever_modal")
        assert "ANTYPE,MODAL" in apdl
        assert "FREQ_HZ" in apdl

    def test_buckling_column_apdl_contains_keywords(self):
        apdl = render_template("buckling_column")
        assert "BEAM188" in apdl
        assert "BLF" in apdl

    def test_bilinear_plastic_apdl_contains_keywords(self):
        apdl = render_template("bilinear_plastic")
        assert "BKIN" in apdl
        assert "NLGEOM" in apdl
