"""Structural agents run on the Flash model unless an explicit override is given."""

from __future__ import annotations

from seekflow_structural.runtime import caller


def test_structural_agent_default_model_is_flash():
    assert caller.DEFAULT_MODEL == "deepseek-v4-flash"
    config = caller.model_config()
    assert config.model == "deepseek-v4-flash"
    assert config.thinking == {"type": "disabled"}
    assert config.temperature == 0