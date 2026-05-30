"""v0.7: ValidationReport.fail / ok_report schema tests."""


class TestValidationReportSchema:
    def test_validation_report_accepts_stages_run(self):
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        report = ValidationReport(
            ok=True,
            stage="complete",
            stages_run=["structure", "complete"],
        )
        assert report.stages_run == ["structure", "complete"]

    def test_validation_report_fail_accepts_stages_run_without_passing_to_issue(self):
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        report = ValidationReport.fail(
            stage="geometry_preflight",
            code="bad_geometry",
            message="bad",
            stages_run=["structure", "canonicalize", "geometry_preflight"],
        )
        assert report.stages_run[-1] == "geometry_preflight"
        # stages_run must NOT appear on ValidationIssue
        assert not hasattr(report.issues[0], "stages_run")

    def test_validation_report_ok_report_sets_default_stage(self):
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        report = ValidationReport.ok_report("structure")
        assert report.stages_run == ["structure"]

    def test_validation_report_ok_report_accepts_explicit_stages_run(self):
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        report = ValidationReport.ok_report("registry", stages_run=["structure", "registry"])
        assert report.stages_run == ["structure", "registry"]

    def test_validation_report_fail_passes_issue_fields_correctly(self):
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        report = ValidationReport.fail(
            stage="typecheck",
            code="type_mismatch",
            message="Expected solid, got frame",
            node_id="n1",
            component_id="c1",
            path="/nodes/n1/outputs/0",
            expected="solid",
            actual="frame",
        )
        assert not report.ok
        assert report.stage == "typecheck"
        assert report.stages_run == ["typecheck"]
        issue = report.issues[0]
        assert issue.node_id == "n1"
        assert issue.component_id == "c1"
        assert issue.path == "/nodes/n1/outputs/0"
        assert issue.expected == "solid"
        assert issue.actual == "frame"

    def test_validation_report_fail_defaults_stages_run_to_stage(self):
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
        report = ValidationReport.fail("safety", "safety_missing", "missing safety")
        assert report.stages_run == ["safety"]
