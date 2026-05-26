"""Path safety utilities – dual-layer defence on top of SeekFlow PolicyEngine."""

from __future__ import annotations

from pathlib import Path


def ensure_inside_workspace(workspace_root: Path, user_path: str | Path) -> Path:
    """Resolve *user_path* and refuse it if outside *workspace_root*.

    Relative paths are resolved against *workspace_root*.
    """
    workspace_root = Path(workspace_root).resolve()
    candidate = Path(user_path)

    if not candidate.is_absolute():
        candidate = workspace_root / candidate

    candidate = candidate.resolve()

    try:
        candidate.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"Path is outside workspace. path={candidate}, workspace={workspace_root}"
        )

    return candidate


def ensure_extension(path: Path, allowed: set[str]) -> Path:
    """Raise if *path* suffix is not in *allowed*."""
    if path.suffix.lower() not in allowed:
        raise ValueError(
            f"File extension {path.suffix!r} is not allowed. Allowed: {sorted(allowed)}"
        )
    return path
