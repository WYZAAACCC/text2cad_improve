"""Where the loop's runs are kept.

The run trees are 32 GB of meshes, solves, generated STEP files and the
evidence the reports are written from. They were moved off the working disk
to the larger one; nothing else moved with them, because the code, the master
templates and the documents the runs start from are all small and are read
from a fixed place.

`_loop_test` is still the name, on whichever disk holds it. Both layouts
resolve, so a checkout that has never been moved behaves the same as one that
has, and nothing has to know which it is running in.

Emptiness is checked as well as existence: the directory on the other drive
exists from the moment it is created and stays empty until the copy finishes,
so a check for existence alone would point a run at an empty tree and read as
"the runs are gone".
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: The runs after the move.
_MOVED = Path(r"F:\text_to_cad_improve\auto_detection_process\_loop_test")

#: The runs as they were laid out before it.
_BESIDE = _HERE.parent / "_loop_test"


def loop_test() -> Path:
    """The directory holding the loop's runs, wherever it currently is."""
    if _MOVED.is_dir() and any(_MOVED.iterdir()):
        return _MOVED
    if _BESIDE.is_dir():
        return _BESIDE
    return _MOVED
