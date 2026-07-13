"""Knowledge Pack Registry — discover, validate, and retrieve packs from filesystem.

Packs are YAML files in ``knowledge/packs/<domain>/<skill_id>/``.
The registry scans these directories and builds an in-memory index.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.knowledge.schemas import (
    KnowledgePack,
    KnowledgePackManifest,
)


class KnowledgeRegistry:
    """Discover and index versioned knowledge packs from the filesystem."""

    def __init__(self):
        self._packs: dict[str, KnowledgePack] = {}  # key = f"{skill_id}@{version}"
        self._manifests: list[KnowledgePackManifest] = []

    # ── discovery ────────────────────────────────────────────────────

    def discover(self, root: Path) -> int:
        """Scan *root* for knowledge pack directories and load all manifests.

        Each pack directory must contain a ``manifest.yaml`` file.
        Returns the number of packs loaded.
        """
        if not root.exists():
            return 0

        count = 0
        for manifest_path in sorted(root.rglob("manifest.yaml")):
            try:
                pack_dir = manifest_path.parent
                pack = self._load_pack_from_dir(pack_dir)
                key = f"{pack.manifest.skill_id}@{pack.manifest.version}"
                if key in self._packs:
                    raise ValueError(f"duplicate knowledge pack: {key}")
                self._packs[key] = pack
                self._manifests.append(pack.manifest)
                count += 1
            except Exception as exc:
                # Log and skip broken packs — don't crash the server
                import sys
                print(
                    f"[knowledge.registry] WARNING: failed to load {manifest_path}: {exc}",
                    file=sys.stderr,
                )
        return count

    # ── queries ──────────────────────────────────────────────────────

    def list_manifests(self) -> list[KnowledgePackManifest]:
        """Return all discovered pack manifests (for L1 routing summary)."""
        return list(self._manifests)

    def get(self, skill_id: str, version: str | None = None) -> KnowledgePack | None:
        """Retrieve a specific pack by ID and optional version.

        If *version* is None, returns the latest version.
        """
        if version:
            return self._packs.get(f"{skill_id}@{version}")

        # Latest version — find the highest version for this skill_id
        candidates = [
            (k.split("@")[1], p) for k, p in self._packs.items()
            if k.startswith(f"{skill_id}@")
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: _version_tuple(x[0]), reverse=True)
        return candidates[0][1]

    def validate_selections(
        self, selections: list[dict],
        *,
        allow_draft: bool = True,
        selected_dialects: set[str] | None = None,
    ) -> list[str]:
        """Validate a set of knowledge pack selections.

        Args:
            selections: List of {skill_id, skill_version} dicts.
            allow_draft: If False, draft packs are rejected.
            selected_dialects: If provided, each pack's required_dialects
                must be satisfied by this set.

        Returns a list of error messages (empty = all good).
        """
        errors: list[str] = []
        seen_ids: set[str] = set()
        selected_dialects = selected_dialects or set()

        for sel in selections:
            sid = sel.get("skill_id", "")
            ver = sel.get("skill_version", "")

            pack = self.get(sid, ver)
            if pack is None:
                errors.append(
                    f"knowledge pack '{sid}' version '{ver}' not found"
                )
                continue

            if pack.manifest.status == "deprecated":
                errors.append(
                    f"knowledge pack '{sid}' is deprecated — "
                    f"update your selection or remove it"
                )
            elif pack.manifest.status == "draft" and not allow_draft:
                errors.append(
                    f"knowledge pack '{sid}' is in draft status — "
                    f"draft packs are not allowed in this environment"
                )

            if sid in seen_ids:
                errors.append(f"duplicate selection of '{sid}'")
            seen_ids.add(sid)

            # Check dependencies
            for dep in pack.manifest.dependencies:
                dep_pack = self.get(dep.skill_id, dep.min_version)
                if dep_pack is None:
                    errors.append(
                        f"knowledge pack '{sid}' depends on "
                        f"'{dep.skill_id}>={dep.min_version}' which is not available"
                    )

            # Check required dialects
            if selected_dialects and pack.manifest.required_dialects:
                missing = [
                    d for d in pack.manifest.required_dialects
                    if d not in selected_dialects
                ]
                if missing:
                    errors.append(
                        f"knowledge pack '{sid}' requires dialects {missing} "
                        f"which are not selected. Selected: {sorted(selected_dialects)}"
                    )

        # Check for conflicts between selected packs
        selected_ids = {s.get("skill_id", "") for s in selections}
        for sel in selections:
            sid = sel.get("skill_id", "")
            pack = self.get(sid)
            if pack:
                for conflict_id in pack.manifest.conflicts_with:
                    if conflict_id in selected_ids:
                        errors.append(
                            f"'{sid}' conflicts with '{conflict_id}' — "
                            f"cannot select both"
                        )

        return errors

    # ── internals ────────────────────────────────────────────────────

    def _load_pack_from_dir(self, pack_dir: Path) -> KnowledgePack:
        manifest_raw = _read_yaml(pack_dir / "manifest.yaml")
        if not manifest_raw:
            raise ValueError(f"missing or empty manifest.yaml in {pack_dir}")

        manifest = KnowledgePackManifest.model_validate(manifest_raw)
        topology_rules = _read_rules(pack_dir / "topology.yaml")
        parameter_rules = _read_rules(pack_dir / "parameters.yaml")
        self_check_rules = _read_rules(pack_dir / "self_checks.yaml")

        construction_strategy = _read_text(pack_dir / "construction.yaml")
        operation_guidance = _read_text(pack_dir / "operation_guidance.yaml")

        known_conflicts_raw = _read_yaml_any(pack_dir / "known_conflicts.yaml")
        if isinstance(known_conflicts_raw, list):
            known_conflicts = known_conflicts_raw
        elif isinstance(known_conflicts_raw, dict):
            known_conflicts = known_conflicts_raw.get("conflicts", [])
        else:
            known_conflicts = []

        return KnowledgePack(
            manifest=manifest,
            topology_rules=topology_rules,
            parameter_rules=parameter_rules,
            self_check_rules=self_check_rules,
            construction_strategy=construction_strategy,
            operation_guidance=operation_guidance,
            known_conflicts=known_conflicts,
        )


# ── helpers ───────────────────────────────────────────────────────────────

def _read_yaml(path: Path) -> dict | None:
    """Read a YAML file that MUST be a dict (manifest, rules, etc.)."""
    data = _read_yaml_any(path)
    return data if isinstance(data, dict) else None


def _read_yaml_any(path: Path):
    """Read any YAML file — dict, list, or scalar."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_rules(path: Path) -> list:
    data = _read_yaml(path) or {}
    rules_list = data.get("rules", [])
    if not isinstance(rules_list, list):
        return []
    from seekflow_engineering_tools.generative_cad.knowledge.schemas import KnowledgeRule
    result = []
    for r in rules_list:
        try:
            result.append(KnowledgeRule.model_validate(r))
        except Exception:
            pass
    return result


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)
