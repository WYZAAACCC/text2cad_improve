"""ImportGateResult — typed Pydantic model for native import gate output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ImportGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    state: Literal["native_import_eligible"] | None = None
    issues: list[dict]
    metadata: dict | None
    gate: dict
