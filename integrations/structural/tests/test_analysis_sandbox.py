"""The code sandbox: what it hands over, and what it refuses.

The point of this tool is that an agent can answer a question its fixed tools
cannot - so the tests are about the handover rather than about the isolation.
An agent that writes three lines to look at the shape of its data should get
the same measurements back that its own tools report, and should be told
plainly when it cannot run anything at all.

These run a real subprocess. That costs about a second each and is the only
way to test the thing: a sandbox that is mocked is a sandbox whose environment
has not been checked, and the environment is where this went wrong twice - the
geometry stack will not import without `SystemRoot`, and win32com places its
generated cache through `TEMP`.
"""
from __future__ import annotations

import os

import pytest

from seekflow_structural.agents import facefind
from seekflow_structural.errors import StructuralError
from seekflow_structural.runtime import analysis

FEATURE = "n_final_cut"


def _row(*, area=50.0, r=212.0, theta=0.0, kind="plane",
         normal=(-0.5, 0.8, 0.0)):
    radial, tangential, axial = normal
    return {
        "surface_type": kind,
        "area_mm2": area,
        "centroid_mm": [r, 0.0, 0.0],
        "centroid_cyl_mm_deg": [r, theta, 0.0],
        "normal_xyz": list(normal),
        "normal_cylindrical": {
            "radial": radial, "tangential": tangential, "axial": axial
        },
        "edge_count": 4,
    }


@pytest.fixture
def state(tmp_path):
    rows = [
        _row(r=212.0, theta=1.0),
        _row(r=212.0, theta=2.0),
        _row(r=290.0, theta=3.0),
    ]
    return facefind.FaceFinderState(
        session=None,
        cache={(FEATURE, 0): rows},
        bundle=None,
        workdir=tmp_path / "analyses",
    )


def _analyse(state, code, **kwargs):
    return facefind._run_analysis(
        facefind.Action(
            action="run_analysis", feature=FEATURE, code=code, **kwargs
        ),
        state,
    )["result"]


# --------------------------------------------------------------------------
# The environment the child needs
# --------------------------------------------------------------------------

def test_the_child_environment_carries_what_windows_needs():
    """Measured, not assumed.

    With a stripped environment the geometry stack fails to import with
    `WinError 10106` (Winsock cannot initialise without SystemRoot) and then
    with a missing `C:\\Windows\\gen_py` (win32com places its generated cache
    through TEMP). Both read like missing software and are neither.
    """
    environment = analysis.sandbox_environment(analysis.package_src())
    assert "PYTHONPATH" in environment
    for name in ("SystemRoot", "windir", "TEMP", "TMP"):
        if name in os.environ:
            assert environment[name] == os.environ[name]


def test_the_environment_is_built_rather_than_inherited():
    """A credential in this process must not reach a script the agent wrote."""
    environment = analysis.sandbox_environment(analysis.package_src())
    assert set(environment) <= set(analysis.WINDOWS_ENV) | {"PYTHONPATH"}


def test_the_timeout_covers_starting_the_interpreter():
    """The default has to be usable: import alone is most of a call."""
    assert analysis.DEFAULT_TIMEOUT_S >= 60.0
    assert analysis.MAX_TIMEOUT_S >= analysis.DEFAULT_TIMEOUT_S


# --------------------------------------------------------------------------
# What the child is handed
# --------------------------------------------------------------------------

def test_the_script_receives_the_rows_the_agent_can_already_see(state):
    result = _analyse(state, (
        "from seekflow_structural import sandbox_kit as kit\n"
        "rows = kit.rows()\n"
        "print(len(rows))\n"
        "print(sorted({r['centroid_cyl_mm_deg'][0] for r in rows}))\n"
    ))
    assert result["succeeded"] is True, result["stderr"]
    assert "3" in result["stdout"]
    assert "212.0" in result["stdout"] and "290.0" in result["stdout"]


def test_the_script_is_told_the_scope_it_is_looking_at(tmp_path):
    scoped = facefind.FaceFinderState(
        session=None,
        cache={(FEATURE, 0): [_row()]},
        sector={"theta_low_deg": 9.0, "theta_high_deg": 27.0},
        workdir=tmp_path / "analyses",
    )
    result = _analyse(scoped, (
        "from seekflow_structural import sandbox_kit as kit\n"
        "print(kit.scope()['feature'])\n"
        "print(kit.scope()['sector'])\n"
    ))
    assert result["succeeded"] is True, result["stderr"]
    assert FEATURE in result["stdout"]
    assert "9.0" in result["stdout"]


def test_a_script_that_fails_is_reported_as_a_failure_not_an_error(state):
    """A broken script is the script's problem, and the agent has to see it."""
    result = _analyse(state, "raise ValueError('the shape was not what I thought')")
    assert result["ran"] is True
    assert result["succeeded"] is False
    assert "the shape was not what I thought" in result["stderr"]


def test_stdout_is_bounded(state):
    result = _analyse(state, "print('x' * 50000)")
    assert len(result["stdout"]) <= facefind.MAX_ANALYSIS_OUTPUT
    assert result["stdout_truncated"] is True


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------

def test_an_empty_script_is_refused(state):
    with pytest.raises(StructuralError) as exc:
        _analyse(state, "   \n  ")
    assert exc.value.diagnostic.code == "no_code"


def test_a_run_with_no_sandbox_directory_says_so_rather_than_reaching_for_one():
    """An offline state has no workdir, and the tool must not invent one."""
    bare = facefind.FaceFinderState(session=None, cache={(FEATURE, 0): []})
    with pytest.raises(StructuralError) as exc:
        _analyse(bare, "print(1)")
    assert exc.value.diagnostic.code == "no_sandbox"


# --------------------------------------------------------------------------
# The audit trail
# --------------------------------------------------------------------------

def test_every_script_is_recorded_with_the_question_it_answered(state):
    _analyse(state, "print('first')", purpose="is the radius one band or two")
    _analyse(state, "print('second')", purpose="how big is the outer band")

    assert len(state.analyses) == 2
    first = state.analyses[0]
    assert first["purpose"] == "is the radius one band or two"
    assert "first" in first["stdout"]
    assert first["ok"] is True

    record = facefind.Outcome(
        final=None, trace=[], calls=2, exhausted=False,
        requirement="r", state=state,
    ).record()
    assert len(record["analyses"]) == 2
    assert record["analyses"][1]["purpose"] == "how big is the outer band"


def test_each_run_gets_its_own_directory(state):
    _analyse(state, "print(1)")
    _analyse(state, "print(2)")
    directories = sorted(p.name for p in state.workdir.iterdir())
    assert directories == ["000", "001"]
    assert (state.workdir / "000" / "input.json").exists()


def test_a_script_gets_the_flat_names_a_tool_reply_uses(state):
    """The sandbox and the tools must spell the same facts the same way.

    `sandbox_kit.rows()` was documented as "read them with the keys you would
    see in a tool reply", and that was untrue: tool replies report
    `radius_mm`, flat, while the rows carried `centroid_cyl_mm_deg[0]`. Three
    separate runs wrote a script whose only purpose was to print the key names
    and discover the mismatch, each costing an LLM round trip to rediscover
    the same thing.
    """
    result = _analyse(state, (
        "from seekflow_structural import sandbox_kit as kit\n"
        "row = kit.rows()[0]\n"
        "print(row['radius_mm'], row['theta_deg'], row['z_mm'])\n"
        "print(row['normal_radial'], row['normal_tangential'], "
        "row['normal_axial'])\n"
        "print(row['centroid_cyl_mm_deg'][0], "
        "row['centroid_cyl_mm_deg'][1])\n"
        "print(row['normal_cylindrical']['radial'])\n"
    ))
    assert result["succeeded"] is True, result["stderr"]
    lines = result["stdout"].strip().splitlines()
    flat_radius, flat_theta, _ = (float(v) for v in lines[0].split())
    nested_radius, nested_theta = (float(v) for v in lines[2].split())
    assert flat_radius == pytest.approx(nested_radius)
    assert flat_theta == pytest.approx(nested_theta)
    assert float(lines[1].split()[0]) == pytest.approx(float(lines[3]))


def test_the_row_fields_are_documented_where_the_script_reads_them():
    from seekflow_structural import sandbox_kit

    assert "radius_mm" in sandbox_kit.ROW_FIELDS
    assert "centroid_cyl_mm_deg" in sandbox_kit.ROW_FIELDS
    for name, meaning in sandbox_kit.ROW_FIELDS.items():
        assert meaning.strip(), name


def test_the_list_position_is_documented_as_the_face_index(state):
    """There is no `face_index` field, and nothing said so.

    A run spent one of its thirty calls on a script whose only line printed
    the key names, titled "Find the index field name in rows" - looking for a
    field that does not exist, because the list is already in that order.
    """
    from seekflow_structural import sandbox_kit

    assert "face_index" not in sandbox_kit.ROW_FIELDS
    assert "POSITION IS THE FACE INDEX" in sandbox_kit.rows.__doc__

    result = _analyse(state, (
        "from seekflow_structural import sandbox_kit as kit\n"
        "rows = kit.rows()\n"
        "hit = [i for i, r in enumerate(rows)\n"
        "       if r.get('surface_type') == 'plane'\n"
        "       and (r.get('normal_radial') or 0) <= -0.2]\n"
        "print(hit)\n"
    ))
    assert result["succeeded"] is True, result["stderr"]
    # the positions a script filters to are the indices a submission names
    assert result["stdout"].strip() == "[0, 1, 2]"
