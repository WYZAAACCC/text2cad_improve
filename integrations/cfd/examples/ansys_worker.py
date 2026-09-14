"""LOCAL IMPLEMENTATION POINT: trusted file-RPC worker, no generated scripts.

Configure a fixed absolute command [python_exe, absolute_path_to_this_file].
Populate IMPLEMENTATIONS with your tested generic PyFluent/CFX operations.
Each handler(payload, job_dir) returns the typed evidence specified in README.
Never assert convergence here: return raw samples to the independent monitor.
"""

import json
import sys
from pathlib import Path

from seekflow_cfd.backends import OPERATIONS
from seekflow_cfd.models import CFDError
from seekflow_cfd.storage import atomic_json, confined

# Functions added here are trusted local code, not Agent-produced code.
IMPLEMENTATIONS = {}


def main():
    root = Path.cwd()
    request = json.loads(confined(root, sys.argv[1]).read_text(encoding="utf-8"))
    response = {k: request[k] for k in ("protocol", "call_id", "input_hash")}
    operation = request["operation"]
    try:
        if operation not in OPERATIONS or operation not in IMPLEMENTATIONS:
            raise CFDError(
                "local_adapter_not_implemented",
                f"Implement and validate {operation} in your local Ansys environment",
                operation,
                "capability_gap",
            )
        response["result"] = IMPLEMENTATIONS[operation](request["payload"], root)
    except CFDError as exc:
        response["error"] = exc.diagnostic.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- trusted worker RPC boundary
        response["error"] = {
            "code": "local_solver_error",
            "message": str(exc),
            "status": "failed",
        }
    atomic_json(confined(root, sys.argv[2]), response)


if __name__ == "__main__":
    main()
