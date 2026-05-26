"""Test ANSYS template parameter validation."""

from __future__ import annotations

import pytest

from seekflow_engineering_tools.ansys.template_registry import (
    ANSYS_TEMPLATE_SCHEMAS,
    list_template_names,
    validate_template_parameters,
)


class TestANSYSTemplateValidation:
    def test_all_templates_listed(self):
        names = list_template_names()
        assert "static_cantilever_beam_rect" in names
        assert "plate_with_hole_tension" in names
        assert "beam_thermal" in names
        assert "cantilever_modal" in names
        assert "buckling_column" in names
        assert "bilinear_plastic" in names

    def test_rejects_unknown_template(self):
        with pytest.raises(ValueError, match="Unknown template"):
            validate_template_parameters("nonexistent_template", {})

    def test_rejects_unknown_parameter(self):
        with pytest.raises(ValueError, match="Unknown parameter"):
            validate_template_parameters("static_cantilever_beam_rect", {
                "length_mm": 100,
                "width_mm": 20,
                "height_mm": 10,
                "force_n": 1000,
                "unknown_param": 42,
            })

    def test_rejects_negative_length(self):
        with pytest.raises(ValueError, match="< min"):
            validate_template_parameters("static_cantilever_beam_rect", {
                "length_mm": -10,
                "width_mm": 20,
                "height_mm": 10,
                "force_n": 1000,
            })

    def test_fills_defaults(self):
        result = validate_template_parameters("static_cantilever_beam_rect", {
            "length_mm": 100,
            "width_mm": 20,
            "height_mm": 10,
            "force_n": 1000,
        })
        assert result["length_mm"] == 100
        assert result["element_size_mm"] == 10.0  # default

    def test_rejects_missing_required_param(self):
        with pytest.raises(ValueError, match="requires parameter"):
            validate_template_parameters("static_cantilever_beam_rect", {
                "length_mm": 100,
                "width_mm": 20,
                # height_mm missing
                "force_n": 1000,
            })

    def test_rejects_wrong_type(self):
        with pytest.raises(ValueError, match="must be float"):
            validate_template_parameters("static_cantilever_beam_rect", {
                "length_mm": "not_a_number",
                "width_mm": 20,
                "height_mm": 10,
                "force_n": 1000,
            })

    def test_rejects_bool_as_int(self):
        with pytest.raises(ValueError, match="must be int"):
            validate_template_parameters("cantilever_modal", {
                "n_modes": True,
            })

    def test_rejects_modal_n_modes_out_of_range(self):
        with pytest.raises(ValueError, match="> max"):
            validate_template_parameters("cantilever_modal", {
                "n_modes": 200,
            })

    def test_plate_geometry_constraint(self):
        """Hole diameter must be less than plate dimensions."""
        with pytest.raises(ValueError, match="Hole diameter"):
            validate_template_parameters("plate_with_hole_tension", {
                "hole_diameter_mm": 300,  # larger than plate_width_mm=200
            })
