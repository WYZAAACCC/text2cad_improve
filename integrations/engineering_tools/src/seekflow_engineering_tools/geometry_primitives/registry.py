from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition

PRIMITIVE_REGISTRY: dict[str, PrimitiveDefinition] = {}
_REGISTRY_LOAD_ERRORS: list[str] = []

PRIMITIVE_FAMILY_MODULES: list[str] = [
    "seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES",
    "seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES",
]


def _load_definitions_from_module(path: str) -> list[PrimitiveDefinition]:
    """Import a ``module_path:attr_name`` string and return a list of PrimitiveDefinition.

    Raises ImportError/AttributeError/TypeError on failure — caller collects into
    _REGISTRY_LOAD_ERRORS.
    """
    module_path, attr_name = path.rsplit(":", 1)
    import importlib
    mod = importlib.import_module(module_path)
    definitions = getattr(mod, attr_name)
    if not isinstance(definitions, list):
        raise TypeError(
            f"{module_path}:{attr_name} is not a list, got {type(definitions).__name__}"
        )
    validated: list[PrimitiveDefinition] = []
    for i, item in enumerate(definitions):
        if not isinstance(item, PrimitiveDefinition):
            raise TypeError(
                f"{module_path}:{attr_name}[{i}] is not a PrimitiveDefinition, "
                f"got {type(item).__name__}"
            )
        validated.append(item)
    return validated


def _populate_registry():
    PRIMITIVE_REGISTRY.clear()
    _REGISTRY_LOAD_ERRORS.clear()

    for path in PRIMITIVE_FAMILY_MODULES:
        try:
            definitions = _load_definitions_from_module(path)
        except ImportError as exc:
            _REGISTRY_LOAD_ERRORS.append(
                f"Failed to import primitive family '{path}': {type(exc).__name__}: {exc}"
            )
            continue
        except (AttributeError, TypeError, ValueError) as exc:
            _REGISTRY_LOAD_ERRORS.append(
                f"Invalid primitive family '{path}': {type(exc).__name__}: {exc}"
            )
            continue

        for p in definitions:
            if p.name in PRIMITIVE_REGISTRY:
                _REGISTRY_LOAD_ERRORS.append(
                    f"Duplicate primitive registered: '{p.name}' "
                    f"(from '{path}', already in registry)"
                )
                continue
            PRIMITIVE_REGISTRY[p.name] = p


def _raise_if_registry_unhealthy():
    if _REGISTRY_LOAD_ERRORS:
        raise RuntimeError("Primitive registry load errors: " + "; ".join(_REGISTRY_LOAD_ERRORS))


def list_primitive_names() -> list[str]:
    _raise_if_registry_unhealthy()
    return sorted(PRIMITIVE_REGISTRY.keys())


def get_primitive(name: str) -> PrimitiveDefinition | None:
    _raise_if_registry_unhealthy()
    return PRIMITIVE_REGISTRY.get(name)


def normalize_primitive_parameters(primitive_name: str, parameters: dict) -> dict:
    pd = get_primitive(primitive_name)
    if pd is None:
        raise ValueError(
            f"Unknown primitive: '{primitive_name}'. Available: {list_primitive_names()}"
        )

    errors: list[str] = []
    schema_params = {p.name: p for p in pd.parameters}
    normalized: dict = {}

    for key in parameters:
        if key not in schema_params:
            errors.append(
                f"Unknown parameter '{key}' for primitive '{primitive_name}'. "
                f"Allowed: {sorted(schema_params.keys())}"
            )

    for pname, pinfo in schema_params.items():
        if pname in parameters:
            value = parameters[pname]
            expected_type = pinfo.type

            try:
                if expected_type == "float":
                    if isinstance(value, bool):
                        errors.append(f"Parameter '{pname}' must be float, got bool")
                        continue
                    normalized[pname] = float(value)
                elif expected_type == "int":
                    if isinstance(value, bool):
                        errors.append(f"Parameter '{pname}' must be int, got bool")
                        continue
                    normalized[pname] = int(value)
                elif expected_type == "str":
                    normalized[pname] = str(value)
                elif expected_type == "bool":
                    normalized[pname] = bool(value)
            except (TypeError, ValueError):
                errors.append(
                    f"Parameter '{pname}' must be {expected_type}, "
                    f"got {type(value).__name__}: {value}"
                )
                continue

            if expected_type in ("float", "int") and not isinstance(value, bool):
                v = float(normalized[pname])
                if pinfo.min_value is not None and v < pinfo.min_value:
                    errors.append(f"Parameter '{pname}' value {v} < min {pinfo.min_value}")
                if pinfo.max_value is not None and v > pinfo.max_value:
                    errors.append(f"Parameter '{pname}' value {v} > max {pinfo.max_value}")

        elif pinfo.required:
            errors.append(f"Missing required parameter '{pname}' for primitive '{primitive_name}'")
        elif pinfo.default is not None:
            normalized[pname] = pinfo.default

    if errors:
        raise ValueError("; ".join(errors))

    if primitive_name == "involute_spur_gear":
        from seekflow_engineering_tools.geometry_primitives.gears.validator import (
            validate_involute_spur_gear_parameters,
        )
        gear_errors = validate_involute_spur_gear_parameters(normalized)
        if gear_errors:
            raise ValueError("Gear validation failed: " + "; ".join(gear_errors))

    return normalized


def backend_supports_primitive(backend: str, primitive_name: str) -> bool:
    pd = get_primitive(primitive_name)
    if pd is None:
        return False
    return backend in pd.supported_backends


_populate_registry()
