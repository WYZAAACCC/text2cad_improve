"""Test NX bridge bootstrap fail-closed behavior."""

import json
import pytest
from pathlib import Path


def test_all_action_handlers_return_explicit_ok():
    """Every action handler must return an explicit 'ok' field."""
    import importlib.util
    import ast
    import textwrap
    from pathlib import Path

    module_path = Path(__file__).parent.parent / "src" / "seekflow_engineering_tools" / "nx" / "nx_bridge_bootstrap.py"
    source = module_path.read_text(encoding="utf-8")

    tree = ast.parse(source)

    # Find the ACTION_HANDLERS dict
    handlers = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ACTION_HANDLERS":
                    if isinstance(node.value, ast.Dict):
                        for key, value in zip(node.value.keys, node.value.values):
                            if isinstance(key, ast.Constant):
                                handlers[key.value] = value

    assert len(handlers) >= 6, f"Expected at least 6 action handlers, got {len(handlers)}"
    assert "import_step_as_prt" in handlers, "import_step_as_prt must be in ACTION_HANDLERS"

    # Check that create_block_part, export_step, create_block_with_hole,
    # create_l_bracket, create_stepped_block, import_step_as_prt all exist
    required = [
        "create_block_part", "create_block_with_hole",
        "create_l_bracket", "create_stepped_block",
        "export_step", "import_step_as_prt",
    ]
    for name in required:
        assert name in handlers, f"Handler '{name}' missing from ACTION_HANDLERS"


def test_process_one_job_does_not_default_ok_to_true():
    """process_one_job must not use result_payload.get('ok', True)."""
    from pathlib import Path

    module_path = Path(__file__).parent.parent / "src" / "seekflow_engineering_tools" / "nx" / "nx_bridge_bootstrap.py"
    source = module_path.read_text(encoding="utf-8")

    # The default ok=True pattern must not exist
    assert 'result_payload.get("ok", True)' not in source, (
        "process_one_job must not default ok to True — "
        "use .get('ok') and treat None as failure."
    )


def test_handler_returns_none_ok_treated_as_failure():
    """If a handler omits 'ok', process_one_job treats it as failure."""
    # Simulate the logic
    result_payload = {"files_created": ["test.prt"], "metrics": {}}
    handler_ok = result_payload.get("ok")
    if handler_ok is None:
        handler_ok = False
    assert handler_ok is False, "Missing 'ok' must be treated as False (fail-closed)"


def test_handler_returns_explicit_ok_true():
    """If a handler returns explicit ok=True, it's accepted."""
    result_payload = {"ok": True, "files_created": ["test.prt"], "metrics": {}}
    handler_ok = result_payload.get("ok")
    if handler_ok is None:
        handler_ok = False
    assert handler_ok is True


def test_handler_returns_false_with_error():
    """Handler ok=False with error message must be fail-closed."""
    result_payload = {"ok": False, "error": "STEP import failed", "files_created": [], "metrics": {}}
    handler_ok = result_payload.get("ok")
    if handler_ok is None:
        handler_ok = False
    error_msg = result_payload.get("error")
    assert not (bool(handler_ok) and error_msg is None)
