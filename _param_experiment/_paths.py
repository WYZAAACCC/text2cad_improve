"""Where this package's generated output lives.

The output tree is 16 GB of generated models, sweeps and datasets, and it
lives on the larger drive to keep the working disk free. It was moved there
with `robocopy /MOVE`; the code below resolves whichever layout is on disk, so
the move was a copy and nothing else - no code change, because every script
asks here instead of spelling the path out.

`_param_experiment` itself stays where it is, moved or not, because the
repository root is located by looking for directories like it - see
`find_repo_root` in `tools/parametric.py`, `_find_repo_root` in
`core/mesh_feedback.py` and the face-mapping block in `cli.py`, which between
them use `_param_experiment` and `_structural_experiment` as markers. So the
directories are landmarks and only the data inside them is free to move.

Every script in this package used to spell the location as `_HERE / "output"`,
which stopped being true the moment the data moved. Measured before the
change: 39 references across 29 scripts, not one of them exercisable by the
test suite - which is the reason for one indirection rather than 39 edited
call sites.
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: The tree after the move.
_MOVED = Path(
    r"F:\text_to_cad_improve\auto_detection_process\_param_experiment\output"
)

#: The tree as it was laid out before it.
_BESIDE = _HERE / "output"


def output_root() -> Path:
    """The output tree, wherever it currently is.

    Emptiness is checked as well as existence. The directory on the other
    drive exists from the moment it is created and stays empty until the copy
    finishes, so a check for existence alone pointed every script at an empty
    tree while the data was still on the disk beside them - which reads as
    "the dataset is gone" rather than as "the copy is not done".
    """
    if _MOVED.is_dir() and any(_MOVED.iterdir()):
        return _MOVED
    if _BESIDE.is_dir():
        return _BESIDE
    return _MOVED


def under(*parts: str) -> Path:
    """A path inside the output tree."""
    return output_root().joinpath(*parts)
