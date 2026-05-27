"""Test that cq-gears is only in optional dependencies, not main deps."""

from pathlib import Path
import tomllib


def _load_pyproject():
    path = Path(__file__).parent.parent / "pyproject.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)


def test_cq_gears_not_in_main_dependencies():
    """cq-gears must NOT be in the main [project].dependencies."""
    data = _load_pyproject()
    main_deps = data.get("project", {}).get("dependencies", [])
    for dep in main_deps:
        assert "cq-gears" not in dep, (
            f"cq-gears found in main dependencies: {dep}"
        )


def test_cq_gears_in_gears_optional():
    """cq-gears must be in [project.optional-dependencies].gears."""
    data = _load_pyproject()
    opt_deps = data.get("project", {}).get("optional-dependencies", {})
    gears_deps = opt_deps.get("gears", [])
    assert any("cq-gears" in d for d in gears_deps), (
        f"cq-gears not found in optional-dependencies.gears"
    )


def test_cq_gears_in_industrial_optional():
    """cq-gears must also be in [project.optional-dependencies].industrial."""
    data = _load_pyproject()
    opt_deps = data.get("project", {}).get("optional-dependencies", {})
    industrial_deps = opt_deps.get("industrial", [])
    assert any("cq-gears" in d for d in industrial_deps), (
        f"cq-gears not found in optional-dependencies.industrial"
    )


def test_build123d_optional_exists():
    """build123d must be available as optional dependency."""
    data = _load_pyproject()
    opt_deps = data.get("project", {}).get("optional-dependencies", {})
    assert "build123d" in opt_deps, "build123d optional dependency group missing"



def test_cadquery_optional_exists():
    """cadquery must be available as optional dependency."""
    data = _load_pyproject()
    opt_deps = data.get("project", {}).get("optional-dependencies", {})
    assert "cadquery" in opt_deps, "cadquery optional dependency group missing"


def test_pytest_markers_exist():
    """pytest markers for cq_gears must be configured."""
    data = _load_pyproject()
    markers = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
    marker_names = [m.split(":")[0].strip() if ":" in m else m.strip() for m in markers]
    assert "requires_cq_gears" in marker_names, "requires_cq_gears marker missing"
    assert "not_requires_cq_gears" in marker_names, "not_requires_cq_gears marker missing"
