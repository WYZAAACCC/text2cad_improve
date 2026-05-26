"""SolidWorks model inspector — via COM or file inspection."""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.inspection.common import ModelInspection


def inspect_sldprt_file(sldprt_path: Path) -> ModelInspection:
    """Inspect a SolidWorks part file for basic geometric properties.

    Uses the file size as a rough proxy for complexity when COM is
    not available. For full inspection, open in SolidWorks via COM.
    """
    inspection = ModelInspection()

    if not sldprt_path.exists():
        inspection.warnings.append(f"File not found: {sldprt_path}")
        return inspection

    file_size = sldprt_path.stat().st_size
    inspection.warnings.append(
        f"SLDPRT inspection limited to file metadata ({file_size} bytes). "
        "Full bbox/body_count requires COM connection."
    )

    return inspection


def inspect_sldprt_via_com(model, client) -> ModelInspection:
    """Inspect an open SolidWorks model via COM to extract geometry data.

    Requires an active SolidWorksClient session with an open model.
    """
    inspection = ModelInspection()

    try:
        mass_props = model.Extension.GetMassProperties(1, 0)
        if mass_props:
            inspection.volume_mm3 = float(mass_props[3]) * 1e9  # m³ → mm³
            inspection.mass_g = float(mass_props[1]) * 1000.0  # kg → g
    except Exception:
        inspection.warnings.append("Could not read mass properties.")

    try:
        bodies = model.GetBodies2(0, True)
        if bodies:
            inspection.body_count = len(bodies)
    except Exception:
        inspection.warnings.append("Could not count bodies.")

    try:
        features = model.FeatureManager.GetFeatures(True)
        if features:
            inspection.feature_names = [f.Name for f in features]
    except Exception:
        inspection.warnings.append("Could not enumerate features.")

    return inspection
