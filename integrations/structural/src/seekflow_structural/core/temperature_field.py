"""What the temperature is at a point - one answer, in one place.

The temperature field used to be computed twice: once when the APDL deck was
written, to emit `BF,node,TEMP`, and again after the solve, to look up the
yield stress that turns a von Mises value into a safety factor. The two copies
agreed only because the rotation axis is forced to be global Z, which made
`hypot(x, y)` and a projection onto the axis give the same radius. Nothing
detected the day they stopped agreeing, and the symptom would have been a
safety factor computed against a temperature the solver never saw.

So the field lives here and both callers ask this module. The APDL writer also
writes the values it used to `node_temperature.csv`, and the postprocessor
compares its own evaluation against that file - which turns "the two agree"
from a claim into a measurement.

A field is a source, not just a formula. Besides the two analytic profiles
there were always meant to be, there are two sampled sources: a point cloud of
`x,y,z,value` readings, which is the shape a CFD export arrives in, and an
expression the agent supplies. Sampled sources can be asked for a value
anywhere, so they must be able to say where they have no business answering -
see `FieldCoverage` and the `outside_support_policy` contract below.
"""
from __future__ import annotations

import ast
import csv
import json
import math
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

# Functions an agent-supplied expression may call. Everything else in `math`
# is left out deliberately: this is a temperature formula, and a formula that
# needs `erf` or `gamma` is a sign the intent is wrong, not that the whitelist
# is too short.
_ALLOWED_FUNCTIONS = {
    "abs": abs, "min": min, "max": max, "sqrt": math.sqrt, "exp": math.exp,
    "log": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "atan": math.atan, "atan2": math.atan2, "pi": math.pi,
    "pow": pow, "floor": math.floor, "ceil": math.ceil,
}


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _norm(a):
    return math.sqrt(sum(v * v for v in a))


@dataclass
class FieldCoverage:
    """What a field was asked, and how far its answer can be trusted.

    A field that silently extrapolates is worse than one that refuses, because
    the extrapolated region is exactly where the answer is least constrained
    and it looks no different from the rest. Every field therefore reports
    whether it had support at each point it was asked about, and the count is
    carried into the metrics and the report rather than staying inside this
    module.
    """

    kind: str
    node_count: int = 0
    evaluated_node_count: int = 0
    outside_support_count: int = 0
    outside_fraction: float = 0.0
    outside_node_ids_sample: list[int] = dataclass_field(default_factory=list)
    min_value: float | None = None
    max_value: float | None = None
    source_spacing_mm: float | None = None
    nearest_sample_distance_max_mm: float | None = None
    policy: str | None = None
    limits: list[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "node_count": self.node_count,
            "evaluated_node_count": self.evaluated_node_count,
            "outside_support_count": self.outside_support_count,
            "outside_fraction": round(self.outside_fraction, 6),
            "outside_node_ids_sample": self.outside_node_ids_sample,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "source_spacing_mm": self.source_spacing_mm,
            "nearest_sample_distance_max_mm": self.nearest_sample_distance_max_mm,
            "policy": self.policy,
            "limits": self.limits,
        }


class TemperatureField:
    """Base class. Subclasses supply `_raw_at` and describe themselves."""

    kind = "unknown"

    def _raw_at(self, x: float, y: float, z: float) -> float | None:
        """Value at a point, or None where the field has no support."""
        raise NotImplementedError

    def temperature_at(self, x: float, y: float, z: float) -> float:
        value = self._raw_at(x, y, z)
        if value is None:
            raise ValueError(
                f"{self.kind} field has no support at "
                f"({x:.4f}, {y:.4f}, {z:.4f}) and its policy does not allow "
                "an answer there"
            )
        return value

    def fingerprint(self) -> dict:
        raise NotImplementedError

    def limits(self) -> list[str]:
        return []

    def source_spacing_mm(self) -> float | None:
        return None

    def evaluate(self, points) -> tuple[dict[int, float], FieldCoverage]:
        """Value at every point, together with how well it was supported.

        `points` is an iterable of `(node_id, (x, y, z))`. Nodes the field has
        no support for are still returned - they carry the policy's answer -
        but they are counted, sampled and reported, because a number that came
        from outside the data is a different kind of number from one that came
        from inside it.
        """
        values: dict[int, float] = {}
        outside_ids: list[int] = []
        outside_seen: set[int] = set()
        nearest_max = 0.0
        for node_id, xyz in points:
            value = self._raw_at(*xyz)
            if value is None:
                outside_ids.append(node_id)
                outside_seen.add(node_id)
                distance = self._nearest_distance(*xyz)
                if distance is not None and distance > nearest_max:
                    nearest_max = distance
            else:
                values[node_id] = value

        outside = outside_ids
        for node_id, xyz in points:
            if node_id in outside_seen:
                values[node_id] = self._outside_value(*xyz)

        numbers = list(values.values())
        coverage = FieldCoverage(
            kind=self.kind,
            node_count=len(values),
            evaluated_node_count=len(values) - len(outside),
            outside_support_count=len(outside),
            outside_fraction=(len(outside) / len(values)) if values else 0.0,
            outside_node_ids_sample=outside[:20],
            min_value=round(min(numbers), 6) if numbers else None,
            max_value=round(max(numbers), 6) if numbers else None,
            source_spacing_mm=self.source_spacing_mm(),
            nearest_sample_distance_max_mm=(
                round(nearest_max, 6) if nearest_max else None
            ),
            policy=self.policy_name(),
            limits=self.limits(),
        )
        return values, coverage

    # Sampled fields override these three.
    def _outside_value(self, x, y, z) -> float:
        raise NotImplementedError

    def _nearest_distance(self, x, y, z) -> float | None:
        return None

    def policy_name(self) -> str | None:
        return None


class IsothermalField(TemperatureField):
    kind = "isothermal"

    def __init__(self, uniform_c: float):
        self.uniform_c = float(uniform_c)

    def _raw_at(self, x, y, z):
        return self.uniform_c

    def fingerprint(self) -> dict:
        return {"model": self.kind, "uniform_c": self.uniform_c}

    def limits(self) -> list[str]:
        return ["temperature is uniform; no thermal gradient is represented"]


class RadialPowerLawField(TemperatureField):
    """Bore-to-rim power law, evaluated by projecting onto the rotation axis.

    The projection matters: the previous implementation used `hypot(x, y)` in
    one place and an axis projection in the other. Those agree only while the
    axis is global Z, so the two would have diverged silently on any part
    rotated in the assembly.
    """

    kind = "radial_power_law"

    def __init__(self, bore_c, rim_c, bore_radius_mm, outer_radius_mm, exponent,
                 axis_origin, axis_direction):
        self.bore_c = float(bore_c)
        self.rim_c = float(rim_c)
        self.bore_radius_mm = float(bore_radius_mm)
        self.outer_radius_mm = float(outer_radius_mm)
        self.exponent = float(exponent)
        self.axis_origin = [float(v) for v in axis_origin]
        self.axis_direction = [float(v) for v in axis_direction]

    def radius_at(self, x, y, z) -> float:
        rel = _sub((x, y, z), self.axis_origin)
        axial = _dot(rel, self.axis_direction)
        radial = [rel[i] - axial * self.axis_direction[i] for i in range(3)]
        return _norm(radial)

    def _raw_at(self, x, y, z):
        span = self.outer_radius_mm - self.bore_radius_mm
        fraction = (self.radius_at(x, y, z) - self.bore_radius_mm) / span
        fraction = min(1.0, max(0.0, fraction))
        return self.bore_c + (self.rim_c - self.bore_c) * (
            fraction ** self.exponent
        )

    def fingerprint(self) -> dict:
        return {
            "model": self.kind, "bore_c": self.bore_c, "rim_c": self.rim_c,
            "bore_radius_mm": self.bore_radius_mm,
            "outer_radius_mm": self.outer_radius_mm, "exponent": self.exponent,
            "axis_origin_mm": self.axis_origin,
            "axis_direction": self.axis_direction,
        }

    def limits(self) -> list[str]:
        return [
            "radial power law is axisymmetric: it cannot represent a "
            "temperature that varies with azimuth or with axial position",
            "the profile is clamped outside "
            f"{self.bore_radius_mm:g}..{self.outer_radius_mm:g} mm, so any "
            "material beyond those radii is held at the end value",
        ]


class NodeProfileField(TemperatureField):
    """Exact per-node values, keyed by mesh node id - no interpolation."""

    kind = "node_profile_file"

    def __init__(self, values: dict[int, float], source: str):
        self.values = {int(k): float(v) for k, v in values.items()}
        self.source = source

    def _raw_at(self, x, y, z):
        raise ValueError(
            "a node_profile_file field is keyed by node id and has no value "
            "at a coordinate; resolve it through evaluate() with the mesh "
            "points instead"
        )

    def evaluate(self, points) -> tuple[dict[int, float], FieldCoverage]:
        values: dict[int, float] = {}
        missing: list[int] = []
        for node_id, _xyz in points:
            if node_id in self.values:
                values[node_id] = self.values[node_id]
            else:
                missing.append(node_id)
        if missing:
            raise ValueError(
                f"{self.source} has no temperature for {len(missing)} mesh "
                f"node(s), first: {missing[:5]}. A partial node profile would "
                "leave those nodes at the ANSYS default instead of the "
                "intended temperature."
            )
        numbers = list(values.values())
        return values, FieldCoverage(
            kind=self.kind,
            node_count=len(values),
            evaluated_node_count=len(values),
            min_value=round(min(numbers), 6) if numbers else None,
            max_value=round(max(numbers), 6) if numbers else None,
            limits=[f"values read verbatim from {self.source}"],
        )

    def fingerprint(self) -> dict:
        digest = sorted(self.values.items())
        return {
            "model": self.kind, "source": str(self.source),
            "node_count": len(self.values),
            # A cheap content stamp, so two different profiles do not share a
            # fingerprint just because they have the same shape of description.
            "checksum": f"{sum(self.values.values()):.6f}",
            "first_keys": [k for k, _ in digest[:5]],
        }

    def limits(self) -> list[str]:
        return [f"values read verbatim from {self.source}"]


class PointCloudField(TemperatureField):
    """Scattered `x,y,z,value` readings, interpolated linearly.

    This is the shape a CFD export arrives in, so it is also the place the
    honest question gets asked: a cloud covers a volume, and a structural mesh
    is rarely inside it. Support is defined as the convex hull of the samples -
    inside it the interpolation is a real interpolation; outside it there is no
    data and linear extrapolation of a temperature field is not a defensible
    answer. Points outside are counted, their distance to the nearest sample is
    measured, and the count is reported.
    """

    kind = "coordinate_samples"

    POLICIES = ("nearest_sample", "reference_temperature", "fail")

    def __init__(self, samples, policy: str, reference_c: float,
                 source: str = "(in memory)"):
        if policy not in self.POLICIES:
            raise ValueError(
                f"unknown outside_support_policy {policy!r}; choose one of "
                f"{', '.join(self.POLICIES)}"
            )
        self.policy = policy
        self.reference_c = float(reference_c)
        self.source = source
        self.samples = [tuple(float(v) for v in row) for row in samples]
        if not self.samples:
            raise ValueError(f"{source} contains no sample points")
        self._tri = None
        self._interp = None
        self._tree = None
        self._qhull_error: str | None = None
        self._spacing = self._measure_spacing()

    @classmethod
    def from_file(cls, path: Path, policy: str, reference_c: float):
        rows = []
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped[0] in "#!":
                continue
            parts = [p for p in stripped.replace(";", ",").split(",") if p.strip()]
            if len(parts) < 4:
                continue
            try:
                rows.append([float(p) for p in parts[:4]])
            except ValueError:
                continue
        if not rows:
            raise ValueError(
                f"{path} has no readable 'x,y,z,value' rows; the reader skips "
                "blank lines and lines starting with # or !"
            )
        return cls(rows, policy, reference_c, source=str(path))

    def _build(self):
        if self._tri is not None or self._qhull_error is not None:
            return
        from scipy.interpolate import LinearNDInterpolator
        from scipy.spatial import Delaunay, QhullError

        points = [row[:3] for row in self.samples]
        values = [row[3] for row in self.samples]
        try:
            self._tri = Delaunay(points)
            self._interp = LinearNDInterpolator(self._tri, values)
        except QhullError as exc:
            # A cloud that is a single surface, or collinear, has no volume to
            # interpolate in. That is a fact about the source, not a crash.
            self._qhull_error = (
                "the sample cloud has no 3D extent (it is coplanar or "
                f"collinear), so nothing can be interpolated: {exc}"
            )

    def _tree_(self):
        if self._tree is None:
            from scipy.spatial import cKDTree

            self._tree = cKDTree([row[:3] for row in self.samples])
        return self._tree

    def _measure_spacing(self) -> float | None:
        """Median nearest-neighbour distance among the samples.

        The point-cloud analogue of a probe's resolving power: a cloud whose
        own spacing is coarser than the mesh it is sampled onto cannot carry
        detail finer than that spacing, and no error estimate computed from
        the interpolation alone would reveal it.
        """
        if len(self.samples) < 2:
            return None
        try:
            distances, _ = self._tree_().query(
                [row[:3] for row in self.samples], k=2
            )
            nearest = sorted(d[1] for d in distances if d[1] > 0)
            if not nearest:
                return None
            return round(nearest[len(nearest) // 2], 6)
        except Exception:
            return None

    def _raw_at(self, x, y, z):
        self._build()
        if self._qhull_error is not None or self._interp is None:
            return None
        # Outside the hull the interpolator returns NaN. Asking it directly is
        # also cheaper than a separate `find_simplex` call: the interpolator
        # finds the simplex itself, so an explicit test would walk the
        # triangulation twice for every one of a few hundred thousand nodes.
        value = float(self._interp(x, y, z))
        if math.isnan(value):
            return None
        return value

    def _outside_value(self, x, y, z) -> float:
        if self.policy == "fail":
            raise ValueError(
                f"point ({x:.4f}, {y:.4f}, {z:.4f}) is outside the support of "
                f"{self.source} and outside_support_policy is 'fail'"
            )
        if self.policy == "reference_temperature":
            return self.reference_c
        _, index = self._tree_().query((x, y, z))
        return float(self.samples[int(index)][3])

    def _nearest_distance(self, x, y, z) -> float | None:
        if self._qhull_error is not None:
            return None
        try:
            distance, _ = self._tree_().query((x, y, z))
            return float(distance)
        except Exception:
            return None

    def policy_name(self) -> str | None:
        return self.policy

    def source_spacing_mm(self) -> float | None:
        return self._spacing

    def fingerprint(self) -> dict:
        return {
            "model": self.kind,
            "source": str(self.source),
            "sample_count": len(self.samples),
            "outside_support_policy": self.policy,
            "reference_temperature_c": self.reference_c,
            "sample_value_sum": round(
                sum(row[3] for row in self.samples), 6
            ),
        }

    def limits(self) -> list[str]:
        notes = []
        if self._qhull_error is not None:
            notes.append(self._qhull_error)
        else:
            notes.append(
                "support is the convex hull of the samples; points outside it "
                "are not interpolated"
            )
        if self.policy == "nearest_sample":
            notes.append(
                "points outside the hull take their nearest sample's value, "
                "which is flat rather than extrapolated and can leave a step "
                "at the hull boundary"
            )
        elif self.policy == "reference_temperature":
            notes.append(
                "points outside the hull are held at the reference "
                "temperature, so any real thermal load there is dropped"
            )
        if self._spacing is not None:
            notes.append(
                f"median sample spacing is {self._spacing:g} mm; structure "
                "finer than that is not carried by this source"
            )
        return notes


_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Call, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
    ast.Mod, ast.USub, ast.UAdd, ast.Subscript,
)


def _check_expression(expression: str) -> None:
    """Refuse anything but arithmetic over named variables and functions.

    Clearing `__builtins__` is not enough on its own. `().__class__.__bases__
    [0].__subclasses__()` reaches the interpreter's class registry without
    calling a single builtin - it was measured doing exactly that before this
    check existed. Attribute access is therefore not allowed at all, and the
    only subscript permitted is `params['name']`.

    This is a formulae checker for a temperature field, not a sandbox: it
    bounds what a malformed or careless expression can reach, and it does not
    make a hostile one safe to run.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"temperature expression {expression!r} is not valid "
                         f"Python: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(
                f"temperature expression {expression!r} uses "
                f"{type(node).__name__}, which is not allowed; an expression "
                "may use arithmetic, the parameters, and the listed functions"
            )
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCTIONS \
                and node.id not in {"x", "y", "z", "r", "theta_deg", "params"}:
            raise ValueError(
                f"temperature expression {expression!r} refers to "
                f"{node.id!r}, which is not a known variable or function"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError(
                    f"temperature expression {expression!r} calls something "
                    "that is not a plain function name"
                )
            if node.func.id not in _ALLOWED_FUNCTIONS:
                raise ValueError(
                    f"temperature expression {expression!r} calls "
                    f"{node.func.id!r}, which is not an allowed function"
                )
        if isinstance(node, ast.Subscript) and not (
            isinstance(node.value, ast.Name) and node.value.id == "params"
        ):
            raise ValueError(
                f"temperature expression {expression!r} subscripts something "
                "other than params"
            )


class ExpressionField(TemperatureField):
    """A formula the agent supplies, evaluated at each mesh node.

    The expression is checked against a syntax whitelist and evaluated with no
    builtins reachable, so the worst a careless expression can do is produce a
    wrong number. See `_check_expression` for what that does and does not
    cover.
    """

    kind = "analytic_expression"

    def __init__(self, expression: str, parameters, axis_origin,
                 axis_direction, source: str = "(inline)"):
        self.expression = str(expression)
        _check_expression(self.expression)
        self.parameters = {
            str(k): float(v) for k, v in dict(parameters or {}).items()
        }
        self.axis_origin = [float(v) for v in axis_origin]
        self.axis_direction = [float(v) for v in axis_direction]
        self.source = source
        self._code = compile(self.expression, "<temperature expression>", "eval")
        # Fail at construction, not on the first node, if the formula is bad.
        self._raw_at(0.0, 0.0, 0.0)

    def _raw_at(self, x, y, z):
        rel = _sub((x, y, z), self.axis_origin)
        axial = _dot(rel, self.axis_direction)
        radial = [rel[i] - axial * self.axis_direction[i] for i in range(3)]
        names = dict(_ALLOWED_FUNCTIONS)
        names.update(
            {
                "x": x, "y": y, "z": z,
                "r": _norm(radial),
                "theta_deg": math.degrees(math.atan2(radial[1], radial[0]))
                % 360.0,
                "params": self.parameters,
            }
        )
        try:
            value = eval(self._code, {"__builtins__": {}}, names)
        except Exception as exc:
            raise ValueError(
                f"temperature expression {self.expression!r} failed at "
                f"({x:.4f}, {y:.4f}, {z:.4f}): {exc}"
            ) from exc
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"temperature expression {self.expression!r} evaluated to "
                f"{type(value).__name__} at ({x:.4f}, {y:.4f}, {z:.4f}), not "
                "a number"
            ) from exc
        if not math.isfinite(value):
            raise ValueError(
                f"temperature expression {self.expression!r} returned "
                f"{value!r} at ({x:.4f}, {y:.4f}, {z:.4f})"
            )
        return value

    def fingerprint(self) -> dict:
        return {
            "model": self.kind,
            "expression": self.expression,
            "parameters": self.parameters,
            "source": str(self.source),
        }

    def limits(self) -> list[str]:
        return [
            "the expression is evaluated at mesh nodes only; it carries no "
            "error estimate and no independent check",
            # Worth saying because radial_power_law does clamp and this does
            # not: an expression written to match that profile will differ
            # from it wherever the mesh falls outside the stated radii, and
            # only there - measured on D27 at 139 nodes inside the bore, by
            # up to 0.028 C.
            "the expression is used exactly as written: unlike "
            "radial_power_law it does not clamp outside the bore and rim, so "
            "a formula meant to reproduce that profile will extrapolate "
            "beyond it unless it clamps too",
        ]


def _axis(intent_rotation):
    """Origin and unit direction of the rotation axis, or the Z axis."""
    if intent_rotation is None:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
    origin = [float(v) for v in intent_rotation.axis_origin_mm]
    direction = [float(v) for v in intent_rotation.axis_direction]
    norm = _norm(direction)
    if norm <= 0:
        raise ValueError("rotation axis direction is degenerate")
    return origin, [v / norm for v in direction]


def build_temperature_field(profile, rotation=None,
                            source_root: Path | None = None
                            ) -> TemperatureField:
    """Turn a TemperatureIntent into a field. The only constructor callers use.

    `source_root` is the directory a file-backed source is resolved against;
    it defaults to the current directory so an absolute path always works.
    """
    if profile is None:
        raise ValueError("temperature intent is required")

    origin, direction = _axis(rotation)
    model = profile.model

    if model == "isothermal":
        return IsothermalField(profile.uniform_c)

    if model == "radial_power_law":
        return RadialPowerLawField(
            profile.bore_c, profile.rim_c, profile.bore_radius_mm,
            profile.outer_radius_mm, profile.exponent, origin, direction,
        )

    if model == "node_profile_file":
        path = _resolve(profile.node_profile_file, source_root)
        values = {}
        with path.open(newline="", encoding="utf-8", errors="replace") as stream:
            for row in csv.DictReader(stream):
                try:
                    values[int(float(row["nid"]))] = float(
                        row.get("temperature_c") or row["value"]
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        if not values:
            raise ValueError(
                f"{path} has no readable 'nid,temperature_c' rows"
            )
        return NodeProfileField(values, source=str(path))

    if model == "coordinate_samples":
        path = _resolve(profile.sample_points_file, source_root)
        policy = profile.outside_support_policy or "nearest_sample"
        return PointCloudField.from_file(
            path, policy, profile.reference_temperature_c
        )

    if model == "analytic_expression":
        return ExpressionField(
            profile.expression, profile.parameters, origin, direction
        )

    raise ValueError(f"unsupported temperature model {model!r}")


def _resolve(name, source_root: Path | None) -> Path:
    if not name:
        raise ValueError("temperature source file path is empty")
    path = Path(name)
    if path.is_absolute():
        return path
    return (Path(source_root) if source_root else Path.cwd()) / path


def summary_block(field: TemperatureField, coverage: FieldCoverage) -> dict:
    """The audit shape both the materializer and the postprocessor emit."""
    return {
        "kind": field.kind,
        "fingerprint": field.fingerprint(),
        "coverage": coverage.to_dict(),
        "limits": coverage.limits,
    }


def to_json(block: dict) -> str:
    return json.dumps(block, ensure_ascii=False, sort_keys=True)
