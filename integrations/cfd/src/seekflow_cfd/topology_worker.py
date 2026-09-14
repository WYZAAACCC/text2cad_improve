"""Fixed native topology worker. Segfaults cannot kill the orchestrator."""

import json
import sys
from pathlib import Path

from .models import CFDError, GeometryRef, SurfaceRef
from .storage import atomic_json, confined
from .topology import OCAFTopology


def main():
    root = Path.cwd()
    request = json.loads(confined(root, sys.argv[1]).read_text(encoding="utf-8"))
    output = {"call_id": request["call_id"]}
    topology = None
    try:
        topology = OCAFTopology(
            Path(request["input_root"]), GeometryRef.model_validate(request["geometry"])
        )
        output["roles"] = topology.list_topology_roles()
        bindings = {}
        import cadquery as cq

        for raw in request["surfaces"]:
            surface = SurfaceRef.model_validate(raw)
            binding = topology.resolve_role_to_faces(surface)
            for handle in binding.entity_ids:
                filename = "native-faces/" + handle.split(":", 1)[1] + ".brep"
                path = confined(root, filename)
                path.parent.mkdir(parents=True, exist_ok=True)
                cq.Shape.cast(topology.live_shapes[handle]).exportBrep(str(path))
                binding.native_face_artifacts[handle] = filename
            bindings[surface.key] = binding.model_dump(mode="json")
        output["bindings"] = bindings
    except CFDError as exc:
        output["error"] = exc.diagnostic.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- process boundary must preserve diagnostic
        output["error"] = {
            "code": "native_topology_error",
            "message": str(exc),
            "status": "failed",
        }
    finally:
        if topology is not None:
            topology.close()
    atomic_json(confined(root, sys.argv[2]), output)


if __name__ == "__main__":
    main()
