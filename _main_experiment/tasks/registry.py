"""Task registry with strict TaskSpec validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..schemas import TaskSpec
from ..utils import atomic_write_json


def load_tasks_file(path: str | Path) -> list[TaskSpec]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TaskSpec.model_validate(item) for item in data]


def write_tasks_file(path: str | Path, tasks: Iterable[TaskSpec]) -> Path:
    return atomic_write_json(
        path,
        [task.model_dump(mode="json") for task in tasks],
    )


def list_tasks(tasks: Iterable[TaskSpec]) -> list[TaskSpec]:
    return list(tasks)


def get_task(tasks: Iterable[TaskSpec], task_id: str) -> TaskSpec | None:
    return next((t for t in tasks if t.task_id == task_id), None)
