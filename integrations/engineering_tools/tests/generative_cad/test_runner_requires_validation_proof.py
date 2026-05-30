"""P1: Runner validation proof requirement tests."""


class TestRunnerRequiresValidationProof:
    """Verify canonical runner cannot produce artifact without validation proof."""

    @staticmethod
    def _canonical():
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalComponent, CanonicalNode,
            CanonicalSelectedDialect, CanonicalValueDecl, CanonicalValueRef,
        )
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
        ch = dialect_contract_hash("axisymmetric")
        return CanonicalGcadDocument(
            schema_version="g_cad_core_v0.2",
            canonical_version="canonical_gcad_v0.2",
            document_id="test", part_name="test",
            units="mm", trust_level="reference_geometry",
            raw_graph_hash="sha256:abc",
            canonical_graph_hash="sha256:def",
            selected_dialects=[
                CanonicalSelectedDialect(dialect="axisymmetric", version="0.2.0", contract_hash=ch)
            ],
            components=[
                CanonicalComponent(id="disk", owner_dialect="axisymmetric", root_node="n_body")
            ],
            nodes=[
                CanonicalNode(
                    id="n_body", component="disk", dialect="axisymmetric",
                    op="revolve_profile", op_version="1.0.0", phase="base_solid",
                    inputs=[],
                    outputs=[
                        CanonicalValueDecl(name="body", type="solid", value_id="v1"),
                        CanonicalValueDecl(name="outer_frame", type="frame", value_id="v2"),
                    ],
                    params={"axis": "Z", "profile_stations": [
                        {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 5},
                        {"r_mm": 100, "z_front_mm": 5, "z_rear_mm": 10},
                        {"r_mm": 50, "z_front_mm": 10, "z_rear_mm": 15},
                    ]},
                    typed_params={"axis": "Z"},
                    required=True, degradation_policy="fail",
                ),
            ],
            constraints={
                "require_step_file": True, "require_metadata_sidecar": True,
                "require_closed_solid": True, "expected_body_count": 1,
                "max_runtime_seconds": 120,
            },
            safety={
                "non_flight_reference_only": True, "not_airworthy": True,
                "not_certified": True, "not_for_manufacturing": True,
                "not_for_installation": True, "no_structural_validation": True,
                "no_life_prediction": True,
            },
        )

    @staticmethod
    def _minimal_validation_seed() -> dict:
        return {
            "core_validation": {"ok": True},
            "dialect_semantics": {"ok": True},
            "geometry_preflight": {"ok": True},
            "runtime_postconditions": {"ok": True},
            "inspection_validation": {"ok": True},
        }

    def test_run_canonical_requires_validation_seed(self, tmp_path):
        """run_canonical_gcad requires validation_seed — no default."""
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        import inspect
        sig = inspect.signature(run_canonical_gcad)
        params = sig.parameters
        assert "validation_seed" in params
        # validation_seed must not have a default value
        assert params["validation_seed"].default is inspect.Parameter.empty

    def test_run_canonical_without_validation_seed_fails(self, tmp_path):
        """Passing empty dict with require_full_validation_seed=True fails."""
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        canonical = self._canonical()
        result = run_canonical_gcad(
            canonical,
            out_step=tmp_path / "out.step",
            metadata_path=tmp_path / "out.metadata.json",
            validation_seed={},
            require_full_validation_seed=True,
        )
        assert not result.ok
        assert "validation_seed" in result.error.lower()

    def test_run_canonical_accepts_valid_seed(self, tmp_path):
        """With valid validation_seed, runner proceeds (may fail at geometry but not at guard)."""
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        canonical = self._canonical()
        result = run_canonical_gcad(
            canonical,
            out_step=tmp_path / "out.step",
            metadata_path=tmp_path / "out.metadata.json",
            validation_seed=self._minimal_validation_seed(),
            require_full_validation_seed=True,
        )
        # The guard should pass — geometry may fail (normal), but not due to missing seed
        assert "validation_seed" not in (result.error or "").lower()

    def test_run_canonical_from_files_requires_validation_seed_json(self, tmp_path):
        """run_canonical_gcad_from_files has validation_seed_json parameter."""
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
        import inspect, json
        sig = inspect.signature(run_canonical_gcad_from_files)
        assert "validation_seed_json" in sig.parameters

        # Missing validation seed file should fail
        cj = tmp_path / "canonical.json"
        cj.write_text(json.dumps(self._canonical().model_dump()))
        vsj = tmp_path / "nonexistent.validation.json"
        result = run_canonical_gcad_from_files(
            canonical_json=cj,
            validation_seed_json=vsj,
            out_step=tmp_path / "out.step",
            metadata_path=tmp_path / "out.metadata.json",
        )
        assert not result.ok

    def test_test_helper_has_unverified_runner(self):
        """Private _run_canonical_gcad_unverified_for_tests exists."""
        from seekflow_engineering_tools.generative_cad.pipeline._test_helpers import (
            _run_canonical_gcad_unverified_for_tests,
        )
        assert callable(_run_canonical_gcad_unverified_for_tests)
        # Confirm it's private
        assert "_run_canonical_gcad_unverified_for_tests" in str(_run_canonical_gcad_unverified_for_tests)

    def test_validation_seed_not_mutated_by_runner(self, tmp_path):
        """Runner deep-copies validation_seed, original unchanged."""
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        import copy
        canonical = self._canonical()
        seed = self._minimal_validation_seed()
        original = copy.deepcopy(seed)
        result = run_canonical_gcad(
            canonical,
            out_step=tmp_path / "out.step",
            metadata_path=tmp_path / "out.metadata.json",
            validation_seed=seed,
            require_full_validation_seed=True,
        )
        assert seed == original  # Seed must not be mutated

    def test_builder_harness_generates_validation_seed_json(self, tmp_path):
        """Builder writes validation seed JSON file."""
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "validation_seed_json" in src
        assert "validation_seed_path" in src
        assert ".validation.json" in src

    def test_builder_harness_passes_validation_seed_json_param(self):
        """The generated harness includes validation_seed_json parameter."""
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder._generate_harness_script)
        assert "validation_seed_json" in src
