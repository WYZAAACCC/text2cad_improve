from _main_experiment.report import write_report


def test_write_report_creates_files(tmp_path):
    aggregate = {
        "methods": [{"method_id": "m1", "runs": 10, "engineering_pass1": 0.8}],
        "levels": [],
        "slots": [],
    }
    paths = write_report(aggregate, {"bootstrap": {}}, tmp_path)
    assert paths["json"].exists()
    assert paths["csv"].exists()
    assert paths["markdown"].exists()
