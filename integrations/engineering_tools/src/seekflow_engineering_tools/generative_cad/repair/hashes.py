"""Repair hashing — stable hashes for graph, error signatures, and patches."""

import hashlib
import json

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.repair.patch import RepairPatchV2
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def raw_graph_hash(raw: RawGcadDocument | dict) -> str:
    """Deterministic hash of the raw document's nodes."""
    if isinstance(raw, RawGcadDocument):
        raw = raw.model_dump()
    nodes_json = json.dumps(raw.get("nodes", []), sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(nodes_json.encode()).hexdigest()


def error_signature_hash(report: ValidationReport | dict) -> str:
    """Hash of error codes for stable repair detection."""
    if isinstance(report, ValidationReport):
        codes = sorted(set(i.code for i in report.issues))
    elif isinstance(report, dict):
        codes = sorted(set(i.get("code", "") for i in report.get("issues", [])))
    else:
        codes = []
    sig = "|".join(codes)
    return "sha256:" + hashlib.sha256(sig.encode()).hexdigest()


def repair_patch_hash(patch: RepairPatchV2 | dict) -> str:
    """Deterministic hash of a repair patch."""
    if isinstance(patch, RepairPatchV2):
        patch = patch.model_dump()
    patch_json = json.dumps(patch, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(patch_json.encode()).hexdigest()
