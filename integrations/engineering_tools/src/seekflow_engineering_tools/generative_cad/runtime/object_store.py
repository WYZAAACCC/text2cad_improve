"""RuntimeObjectStore — typed object storage for cross-dialect handle exchange."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.handles import (
    RuntimeHandle,
    SolidHandle,
    SolidArrayHandle,
    FrameHandle,
)


@dataclass(frozen=True)
class StoredRuntimeObject:
    handle_id: str
    value_type: str
    obj: object


class RuntimeObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self._handles: dict[str, RuntimeHandle] = {}

    def put(self, handle: RuntimeHandle, obj: Any) -> RuntimeHandle:
        if handle.id in self._objects:
            raise ValueError(f"duplicate runtime handle id: {handle.id}")
        self._handles[handle.id] = handle
        self._objects[handle.id] = obj
        return handle

    def get(self, handle_or_id: RuntimeHandle | str) -> Any:
        hid = handle_or_id.id if isinstance(handle_or_id, RuntimeHandle) else handle_or_id
        if hid not in self._objects:
            raise KeyError(f"runtime object not found: {hid}")
        return self._objects[hid]

    def get_handle(self, handle_id: str) -> RuntimeHandle:
        if handle_id not in self._handles:
            raise KeyError(f"runtime handle not found: {handle_id}")
        return self._handles[handle_id]

    def get_typed(self, handle_id: str) -> StoredRuntimeObject:
        """Return typed handle + object for output validation."""
        handle = self.get_handle(handle_id)
        obj = self.get(handle_id)
        return StoredRuntimeObject(
            handle_id=handle_id,
            value_type=handle.type,
            obj=obj,
        )

    def put_solid(self, handle: SolidHandle, obj: Any) -> SolidHandle:
        self.put(handle, obj)
        return handle

    def put_frame(self, handle: FrameHandle, obj: Any | None = None) -> FrameHandle:
        self.put(handle, obj)
        return handle

    def put_solid_array(self, handle: SolidArrayHandle, obj: list[Any]) -> SolidArrayHandle:
        self.put(handle, obj)
        return handle
