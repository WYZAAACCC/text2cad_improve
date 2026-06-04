"""Spatial Intent Resolution — v6 Interactive Spatial Frontend.

Phase A (authoring-time): MechanicalObjectGraphDraft → SpatialConstraintGraph → Solver/Validator
Phase C (runtime): ConstraintResolver → NumericPlacement → GeometrySpatialAudit

Does NOT modify RawGcadDocument.
Uses sidecar spatial_contract.json for constraint passing.
"""
