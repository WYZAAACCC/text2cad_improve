from _main_experiment.cli import main


def test_cli_tasks_writes_json(tmp_path):
    exit_code = main([
        "--output", str(tmp_path / "output"),
        "tasks",
    ])
    assert exit_code == 0
    assert (tmp_path / "output" / "tasks.json").exists()
