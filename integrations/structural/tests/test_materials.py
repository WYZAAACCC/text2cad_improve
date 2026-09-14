"""The material table: what it holds, and what it refuses to hold.

The rule this file exists to keep is that a number in the table can be traced
to where it came from. A material property is not something this package can
measure from the model - it is a fact about an alloy - so the only thing that
makes it usable is knowing whose values they are. An entry without a source is
indistinguishable from a guess that happens to be written down.
"""
from __future__ import annotations

import pytest

from seekflow_structural.tools import materials


def test_every_entry_says_where_its_numbers_came_from():
    for name, entry in materials.ALLOYS.items():
        assert entry["source"].strip(), name
        # A source naming a file is checkable; "handbook" on its own is not.
        assert len(entry["source"]) > 40, name


def test_the_table_is_deliberately_short_rather_than_padded():
    """One alloy, because one alloy is what the repository has data for.

    Filling this out with plausible numbers for alloys nobody has measured
    would make the table look more useful and be worth less: an agent would
    take a value from it and no one downstream could tell it from a real one.
    """
    assert list(materials.ALLOYS) == ["GH4169"]


def test_an_alloy_is_found_by_any_of_its_names():
    for spelling in ("GH4169", "gh4169", "Inconel 718", "INCONEL-718",
                     "inconel718", "718"):
        assert materials.resolve(spelling) == "GH4169", spelling


def test_an_unknown_alloy_raises_with_the_names_that_are_known():
    with pytest.raises(KeyError) as exc:
        materials.lookup("Ti-6Al-4V")
    assert "GH4169" in str(exc.value)


def test_the_lookup_returns_the_card_itself_not_a_summary_of_it():
    """The points come back in the shape the deck's material card takes.

    A caller that has to reassemble them is a caller that can put the wrong
    young's modulus against the wrong temperature, and nothing would say so.
    """
    found = materials.lookup("GH4169", 400.0)
    assert found["poisson_ratio"] == 0.3
    assert found["density_t_mm3"] == pytest.approx(8.24e-9)
    assert len(found["points"]) >= 2
    for point in found["points"]:
        assert set(point) == {
            "temperature_c", "young_mpa", "alpha_per_c", "yield_mpa"
        }
    temperatures = [p["temperature_c"] for p in found["points"]]
    assert temperatures == sorted(temperatures)


def test_properties_are_interpolated_between_the_tabulated_points():
    found = materials.lookup("GH4169", 400.0)
    at = found["at_temperature"]
    assert at["within_table"] is True
    # 400 C sits between the 300 C and 500 C points.
    assert 178000.0 < at["young_mpa"] < 190000.0
    assert 1.35e-5 < at["alpha_per_c"] < 1.44e-5
    assert "interpolated" in at["note"]


def test_asking_at_a_tabulated_temperature_returns_that_point():
    at = materials.lookup("GH4169", 500.0)["at_temperature"]
    assert at["young_mpa"] == pytest.approx(178000.0)
    assert at["yield_mpa"] == pytest.approx(1000.0)


def test_outside_the_table_is_reported_as_clamped_not_interpolated():
    """A run at 900 C is a run the data does not cover.

    The number returned is the nearest tabulated one, which is what the deck
    would do with the card anyway - so it is returned, and it says that is
    what happened rather than leaving the caller to notice.
    """
    at = materials.lookup("GH4169", 900.0)["at_temperature"]
    assert at["within_table"] is False
    assert at["young_mpa"] == pytest.approx(165000.0)
    assert "outside the tabulated range" in at["note"]


def test_describe_summarises_without_handing_over_the_numbers():
    rows = materials.describe()
    assert len(rows) == 1
    assert rows[0]["name"] == "GH4169"
    assert rows[0]["temperature_range_c"] == [20.0, 650.0]
    assert "Inconel 718" in rows[0]["also_known_as"]
    assert "source" in rows[0]


def test_asking_for_no_temperature_returns_the_card_alone():
    found = materials.lookup("GH4169")
    assert "at_temperature" not in found
    assert "points" in found
