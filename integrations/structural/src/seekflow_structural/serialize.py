"""One canonical form for anything that gets hashed.

Every integrity check in this package - the audit hash chain, the per-file
manifest, the stage hashes that decide what a resume invalidates - compares
digests. Two spellings of the same value would produce two different digests
and make a healthy job look tampered with, so the encoding lives here and
nothing hashes anything without going through it.
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()
