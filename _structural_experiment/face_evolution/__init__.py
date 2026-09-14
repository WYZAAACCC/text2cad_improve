"""Persistent face-evolution indexing and search for simulation agents."""

from .face_index import SCHEMA_VERSION, connect, initialize_index

__all__ = ["SCHEMA_VERSION", "connect", "initialize_index"]

