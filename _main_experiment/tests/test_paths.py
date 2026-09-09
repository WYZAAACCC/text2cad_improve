import pytest

from _main_experiment.config import ExperimentConfig
from _main_experiment.paths import ensure_inside_experiment_output, run_dir


def test_run_dir_is_inside_output(tmp_path):
    config = ExperimentConfig(output_root=tmp_path)
    path = run_dir("method-a", "T01", 3, config=config)
    assert str(path).startswith(str(tmp_path.resolve()))


def test_ensure_inside_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        ensure_inside_experiment_output("../outside", output_root=tmp_path)
