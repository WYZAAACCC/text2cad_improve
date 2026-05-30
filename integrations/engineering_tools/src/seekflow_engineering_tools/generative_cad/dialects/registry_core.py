"""Frozen DialectRegistry — explicit, freezable, injectable, test-isolatable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.base import BaseDialect
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

FORBIDDEN_PART_TOKENS = {
    "turbine_disk",
    "flange",
    "bracket",
    "gearbox",
    "bearing",
}


@dataclass
class DialectRegistry:
    _dialects: dict[str, BaseDialect] = field(default_factory=dict)
    _frozen: bool = False

    def register(self, dialect: BaseDialect) -> None:
        if self._frozen:
            raise RuntimeError("DialectRegistry is frozen")
        did = dialect.dialect_id
        if not did:
            raise ValueError("dialect_id must be non-empty")
        if did in self._dialects:
            raise ValueError(f"duplicate dialect_id: {did}")
        for token in FORBIDDEN_PART_TOKENS:
            if token in did:
                raise ValueError(
                    f"dialect_id {did!r} appears to name a part, not a CAD grammar dialect"
                )
        self._dialects[did] = dialect

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, dialect_id: str) -> BaseDialect:
        try:
            return self._dialects[dialect_id]
        except KeyError as exc:
            raise KeyError(f"unknown dialect: {dialect_id!r}") from exc

    def get(self, dialect_id: str) -> BaseDialect | None:
        return self._dialects.get(dialect_id)

    def list_ids(self) -> list[str]:
        return sorted(self._dialects)

    def export_catalog(self) -> dict[str, Any]:
        return {
            "catalog_version": "0.3.0",
            "dialects": [
                self._dialects[k].manifest()
                for k in sorted(self._dialects)
            ],
        }

    def contract_hash(self, dialect_id: str) -> str:
        return contract_hash(self.require(dialect_id).contract())
