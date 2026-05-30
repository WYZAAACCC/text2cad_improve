"""P0: Raw explicit safety/constraints hardening tests."""


class TestRawExplicitSafetyConstraints:
    """Verify missing safety, missing constraints, missing flags, false flags all fail."""

    # ── Helpers ──

    @staticmethod
    def _valid_minimal() -> dict:
        return {
            "schema_version": "g_cad_core_v0.2",
            "document_id": "test-001",
            "part_name": "test_part",
            "units": "mm",
            "trust_level": "reference_geometry",
            "selected_dialects": [
                {"dialect": "axisymmetric", "version": "0.2.0"}
            ],
            "components": [
                {"id": "c1", "owner_dialect": "axisymmetric", "root_node": "n1"}
            ],
            "nodes": [
                {
                    "id": "n1", "component": "c1", "dialect": "axisymmetric",
                    "op": "revolve_profile", "op_version": "1.0.0",
                    "phase": "base_solid", "inputs": [], "outputs": [
                        {"name": "body", "type": "solid"},
                        {"name": "outer_frame", "type": "frame"},
                    ],
                    "params": {
                        "axis": "Z",
                        "profile_stations": [
                            {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 5},
                            {"r_mm": 100, "z_front_mm": 5, "z_rear_mm": 10},
                            {"r_mm": 50, "z_front_mm": 10, "z_rear_mm": 15},
                        ],
                    },
                    "required": True, "degradation_policy": "fail",
                }
            ],
            "constraints": {
                "require_step_file": True,
                "require_metadata_sidecar": True,
                "require_closed_solid": True,
                "expected_body_count": 1,
            },
            "safety": {
                "non_flight_reference_only": True,
                "not_airworthy": True,
                "not_certified": True,
                "not_for_manufacturing": True,
                "not_for_installation": True,
                "no_structural_validation": True,
                "no_life_prediction": True,
            },
        }

    @staticmethod
    def _parse_and_validate(data: dict):
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize
        return validate_and_canonicalize(data)

    # ── Missing top-level fields ──

    def test_missing_safety_fails_structure(self):
        data = self._valid_minimal()
        del data["safety"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok
        assert any("safety" in i.code.lower() or "safety" in i.message.lower()
                   for i in report.issues)

    def test_missing_constraints_fails_structure(self):
        data = self._valid_minimal()
        del data["constraints"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok
        assert any("constraint" in i.code.lower() or "constraint" in i.message.lower()
                   for i in report.issues)

    def test_missing_schema_version_fails_structure(self):
        data = self._valid_minimal()
        del data["schema_version"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    def test_missing_units_fails_structure(self):
        data = self._valid_minimal()
        del data["units"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    def test_missing_trust_level_fails_structure(self):
        data = self._valid_minimal()
        del data["trust_level"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    # ── Missing safety flags ──

    def test_missing_safety_flag_fails_structure(self):
        data = self._valid_minimal()
        del data["safety"]["not_airworthy"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok
        assert any("/safety/not_airworthy" in (getattr(i, "path", "") or "")
                   for i in report.issues)

    def test_missing_multiple_safety_flags_fails(self):
        data = self._valid_minimal()
        del data["safety"]["not_certified"]
        del data["safety"]["no_life_prediction"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    # ── Missing constraint flags ──

    def test_missing_constraint_flag_fails_structure(self):
        data = self._valid_minimal()
        del data["constraints"]["require_step_file"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok
        assert any("/constraints/require_step_file" in (getattr(i, "path", "") or "")
                   for i in report.issues)

    def test_missing_expected_body_count_fails_structure(self):
        data = self._valid_minimal()
        del data["constraints"]["expected_body_count"]
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    # ── False flags ──

    def test_safety_false_fails_structure(self):
        data = self._valid_minimal()
        data["safety"]["not_airworthy"] = False
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    def test_constraint_require_step_false_fails_structure(self):
        data = self._valid_minimal()
        data["constraints"]["require_step_file"] = False
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    def test_constraint_require_closed_solid_false_fails_structure(self):
        data = self._valid_minimal()
        data["constraints"]["require_closed_solid"] = False
        canonical, report = self._parse_and_validate(data)
        assert canonical is None
        assert not report.ok

    # ── Valid path ──

    def test_valid_explicit_safety_constraints_passes(self):
        data = self._valid_minimal()
        canonical, report = self._parse_and_validate(data)
        assert canonical is not None
        assert report.ok

    # ── Error path notation ──

    def test_parse_error_path_uses_slash_notation(self):
        data = self._valid_minimal()
        del data["safety"]
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        result = parse_raw_gcad_document(data)
        assert not result.ok
        paths = [i.path for i in result.issues]
        assert "/safety" in paths

    def test_parse_error_path_for_safety_flag(self):
        data = self._valid_minimal()
        del data["safety"]["not_airworthy"]
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        result = parse_raw_gcad_document(data)
        assert not result.ok
        paths = [i.path for i in result.issues]
        assert "/safety/not_airworthy" in paths

    def test_parse_error_path_for_constraint_flag(self):
        data = self._valid_minimal()
        del data["constraints"]["require_closed_solid"]
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        result = parse_raw_gcad_document(data)
        assert not result.ok
        paths = [i.path for i in result.issues]
        assert "/constraints/require_closed_solid" in paths


class TestParseRawGcadDocument:
    """Direct parse_raw_gcad_document unit tests."""

    def test_parse_valid_returns_ok(self):
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        data = TestRawExplicitSafetyConstraints._valid_minimal()
        result = parse_raw_gcad_document(data)
        assert result.ok
        assert result.document is not None
        assert result.document.part_name == "test_part"

    def test_parse_not_a_dict_fails(self):
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        result = parse_raw_gcad_document([])
        assert not result.ok
        assert any(i.code == "not_a_dict" for i in result.issues)

    def test_parse_missing_safety_and_constraints_reports_both(self):
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        data = TestRawExplicitSafetyConstraints._valid_minimal()
        del data["safety"]
        del data["constraints"]
        result = parse_raw_gcad_document(data)
        assert not result.ok
        codes = {i.code for i in result.issues}
        assert "missing_required_field" in codes
        paths = {i.path for i in result.issues}
        assert "/safety" in paths
        assert "/constraints" in paths

    def test_parse_nulls_as_safety_fails_validation(self):
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        data = TestRawExplicitSafetyConstraints._valid_minimal()
        data["safety"] = None
        result = parse_raw_gcad_document(data)
        assert not result.ok
        assert any("safety" in i.message.lower() for i in result.issues)
