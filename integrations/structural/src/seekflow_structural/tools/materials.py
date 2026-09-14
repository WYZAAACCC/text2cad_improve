"""Material properties, and where each number came from.

A simulation needs a stress-strain curve and a thermal expansion curve, and
neither can be measured from the model - they are facts about the alloy, not
about the part. So they have to come from somewhere, and there are only two
honest places: the person asking, or a table that says where its numbers came
from.

This is the second. Every entry carries a `source` naming where its values
were taken from and by whom, and `lookup` hands that string back with the
numbers so it travels into the run's audit rather than being dropped at the
door. A value with no traceable origin is worse than a missing one: it looks
like data.

The table is short on purpose. It holds what this repository has already
checked - the alloy the existing turbine-disc case was run on - and it grows
by someone adding an entry *with its source*, not by filling in plausible
numbers for alloys nobody has data for. An agent that cannot find its alloy
here is expected to say so and ask, which is the outcome the whole design
prefers.
"""
from __future__ import annotations

# Every entry: a canonical name, the other names it is known by, where the
# numbers came from, the two temperature-independent properties, and a table
# of the three that vary with temperature.
#
# The unit of density is tonnes per cubic millimetre, because that is what the
# deck's material card takes and what the case stores; 8.24 t/m3 expressed
# this way is 8.24e-9.
ALLOYS: dict[str, dict] = {
    "GH4169": {
        "aliases": ["Inconel 718", "IN718", "GH4169", "NC19FeNb", "718"],
        "source": (
            "GH4169 / Inconel 718, quoted from "
            "app/text-to-cad/server/fea3d/manual_config.json, where the entry "
            "is named 'GH4169 / Inconel 718 (手册典型值, 人工可改)' - handbook "
            "typical values, editable by hand. That is the whole of its "
            "provenance: it is a handbook curve, not a tested batch, and the "
            "entry says so. The D19 and D27 case files reuse these same "
            "numbers under the label 'Synthetic validation material', which "
            "understates them - they are a named alloy's handbook values, and "
            "the temperature points match this entry one for one."
        ),
        "poisson_ratio": 0.3,
        "density_t_mm3": 8.24e-9,
        "points": [
            {"temperature_c": 20.0, "young_mpa": 205000.0,
             "alpha_per_c": 1.18e-5, "yield_mpa": 1100.0},
            {"temperature_c": 300.0, "young_mpa": 190000.0,
             "alpha_per_c": 1.35e-5, "yield_mpa": 1050.0},
            {"temperature_c": 500.0, "young_mpa": 178000.0,
             "alpha_per_c": 1.44e-5, "yield_mpa": 1000.0},
            {"temperature_c": 650.0, "young_mpa": 165000.0,
             "alpha_per_c": 1.54e-5, "yield_mpa": 950.0},
        ],
    },
}


def _key(name: str) -> str:
    """A name reduced to the form names are compared in.

    Alloy names arrive with case, spaces, hyphens and slashes that carry no
    meaning - "Inconel 718", "inconel-718" and "INCONEL718" are one alloy.
    """
    return "".join(
        character for character in str(name).lower() if character.isalnum()
    )


def _index() -> dict[str, str]:
    """Every name and alias, mapped to the canonical name it means."""
    out: dict[str, str] = {}
    for canonical, entry in ALLOYS.items():
        out[_key(canonical)] = canonical
        for alias in entry.get("aliases", []):
            out[_key(alias)] = canonical
    return out


def resolve(name: str) -> str | None:
    """The canonical name for whatever the caller called this alloy."""
    return _index().get(_key(name))


def describe() -> list[dict]:
    """What the table holds, one row per alloy.

    Enough for a caller to decide whether the alloy it was told about is here
    without pulling the numbers for all of them.
    """
    out = []
    for canonical, entry in ALLOYS.items():
        points = entry["points"]
        out.append({
            "name": canonical,
            "also_known_as": list(entry.get("aliases", [])),
            "source": entry["source"],
            "temperature_range_c": [
                points[0]["temperature_c"], points[-1]["temperature_c"],
            ],
            "point_count": len(points),
        })
    return out


def _interpolate(points: list[dict], temperature_c: float, field: str) -> float:
    """Linear between the two points that bracket the temperature."""
    for index in range(len(points) - 1):
        low, high = points[index], points[index + 1]
        if low["temperature_c"] <= temperature_c <= high["temperature_c"]:
            span = high["temperature_c"] - low["temperature_c"]
            if span <= 0:
                return float(low[field])
            weight = (temperature_c - low["temperature_c"]) / span
            return float(low[field]) + weight * (
                float(high[field]) - float(low[field])
            )
    # Outside the table. Clamping is what the deck does with a material card,
    # so the value returned is the nearest one - and `extrapolated` says that
    # it is, rather than leaving the caller to notice.
    nearest = points[0] if temperature_c < points[0]["temperature_c"] \
        else points[-1]
    return float(nearest[field])


def lookup(name: str, temperature_c: float | None = None) -> dict:
    """One alloy: its table, and optionally its properties at a temperature.

    Raises `KeyError` with the names that *are* in the table, because a caller
    that guessed an alloy name needs to see what the alternatives were.
    """
    canonical = resolve(name)
    if canonical is None:
        raise KeyError(
            f"{name!r} is not in the material table; it holds "
            + ", ".join(sorted(ALLOYS))
        )
    entry = ALLOYS[canonical]
    points = [dict(point) for point in entry["points"]]
    out = {
        "name": canonical,
        "source": entry["source"],
        "poisson_ratio": entry["poisson_ratio"],
        "density_t_mm3": entry["density_t_mm3"],
        # Exactly the shape a material card takes, so a caller can pass this
        # straight on rather than reassembling it and getting a field wrong.
        "points": points,
    }
    if temperature_c is None:
        return out

    low = points[0]["temperature_c"]
    high = points[-1]["temperature_c"]
    temperature = float(temperature_c)
    out["at_temperature"] = {
        "temperature_c": temperature,
        "young_mpa": _interpolate(points, temperature, "young_mpa"),
        "alpha_per_c": _interpolate(points, temperature, "alpha_per_c"),
        "yield_mpa": _interpolate(points, temperature, "yield_mpa"),
        "within_table": low <= temperature <= high,
        "note": (
            f"interpolated between the tabulated points {low:g} and {high:g} C"
            if low <= temperature <= high
            else (
                f"{temperature:g} C is outside the tabulated range "
                f"{low:g}..{high:g} C, so this is the nearest tabulated value "
                "and not an interpolation"
            )
        ),
    }
    return out


__all__ = ["ALLOYS", "describe", "lookup", "resolve"]
