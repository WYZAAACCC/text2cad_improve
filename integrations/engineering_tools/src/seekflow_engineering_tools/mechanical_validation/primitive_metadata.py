"""Generic primitive metadata validation — framework for all primitive types.

IMPORTANT: This is NOT a gear-specific validator. It enforces the minimum
metadata contract that EVERY primitive must meet. Per-primitive validators
(like gear is_standard_involute check) are layered on top.
"""

from __future__ import annotations


def validate_primitive_metadata_v1(
    *,
    primitive_name: str,
    metadata: dict | None,
) -> dict:
    """Validate primitive metadata against the v1 schema (generic, all primitives).

    Keyword-only signature per contract.

    Checks:
      1. metadata exists and is a dict
      2. metadata["primitive"] == primitive_name
      3. metadata_version if present must be "primitive_metadata_v1"
      4. kernel exists and is a non-empty str
      5. parameters exists and is a dict
      6. reference_dimensions exists and is a dict
      7. warnings if present must be list[str]; missing → normalized to []

    Returns:
      {"ok": bool, "issues": list[dict], "normalized_metadata": dict | None}

    Issue format: {"code": str, "message": str, "severity": "error"|"warning"}
    """
    issues: list[dict] = []

    # 1. metadata exists and is dict
    if metadata is None:
        issues.append({
            "code": "primitive_metadata_missing",
            "message": f"Primitive metadata for '{primitive_name}' is missing.",
            "severity": "error",
        })
        return {"ok": False, "issues": issues, "normalized_metadata": None}

    if not isinstance(metadata, dict):
        issues.append({
            "code": "primitive_metadata_not_dict",
            "message": (
                f"Primitive metadata for '{primitive_name}' must be a dict, "
                f"got {type(metadata).__name__}."
            ),
            "severity": "error",
        })
        return {"ok": False, "issues": issues, "normalized_metadata": None}

    # 2. primitive field matches
    actual_primitive = metadata.get("primitive")
    if actual_primitive != primitive_name:
        issues.append({
            "code": "primitive_mismatch",
            "message": (
                f"Metadata primitive field is '{actual_primitive}', "
                f"expected '{primitive_name}'."
            ),
            "severity": "error",
        })

    # 3. metadata_version: if present, must be "primitive_metadata_v1"
    version = metadata.get("metadata_version")
    if version is not None and version != "primitive_metadata_v1":
        issues.append({
            "code": "primitive_metadata_version_unknown",
            "message": (
                f"Metadata version '{version}' is not 'primitive_metadata_v1'."
            ),
            "severity": "error",
        })

    # 4. kernel exists and is non-empty str
    kernel = metadata.get("kernel")
    if kernel is None or not isinstance(kernel, str) or not kernel.strip():
        issues.append({
            "code": "primitive_kernel_missing",
            "message": (
                f"Metadata for '{primitive_name}' missing or invalid 'kernel' field. "
                f"Got: {kernel!r}"
            ),
            "severity": "error",
        })

    # 5. parameters exists and is dict
    params = metadata.get("parameters")
    if params is None or not isinstance(params, dict):
        issues.append({
            "code": "primitive_parameters_missing",
            "message": (
                f"Metadata for '{primitive_name}' missing or invalid 'parameters' field."
            ),
            "severity": "error",
        })

    # 6. reference_dimensions exists and is dict
    ref_dims = metadata.get("reference_dimensions")
    if ref_dims is None or not isinstance(ref_dims, dict):
        issues.append({
            "code": "primitive_reference_dimensions_missing",
            "message": (
                f"Metadata for '{primitive_name}' missing or invalid "
                f"'reference_dimensions' field."
            ),
            "severity": "error",
        })

    # 7. warnings: if present must be list[str]; missing → normalize to []
    normalized = dict(metadata)
    bw = normalized.get("warnings")
    if bw is not None:
        if not isinstance(bw, list):
            issues.append({
                "code": "primitive_warnings_not_list",
                "message": "Metadata 'warnings' must be a list.",
                "severity": "error",
            })
            normalized["warnings"] = []
    else:
        normalized["warnings"] = []

    ok = not any(i["severity"] == "error" for i in issues)
    return {"ok": ok, "issues": issues, "normalized_metadata": normalized if ok else None}
