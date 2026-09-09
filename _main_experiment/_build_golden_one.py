"""Build one golden task (helper for timeouts / debugging)."""
from __future__ import annotations

import sys

from .aggregate import load_tasks
from .config import default_experiment_config
from .tasks.golden_builder import build_golden_for_task


def main() -> int:
    task_id = sys.argv[1]
    config = default_experiment_config()
    task = next(t for t in load_tasks(config) if t.task_id == task_id)
    result = build_golden_for_task(task, config)
    print(f"{task_id} ok={result.get('ok')} mcp={result.get('mcp_gate', {}).get('ok')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
