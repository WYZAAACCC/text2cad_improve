"""Create a compact audit summary for selected-face CFD domain transfer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("domain_response", type=Path)
    parser.add_argument("selected_faces", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    response = json.loads(args.domain_response.read_text(encoding="utf-8"))
    if response.get("error"):
        raise SystemExit(json.dumps(response["error"], ensure_ascii=False))
    selection = json.loads(args.selected_faces.read_text(encoding="utf-8"))
    result = response["result"]
    boundary_map = result["boundary_map"]
    selected_keys = list(selection["bindings"])

    selected_rows = []
    for key in selected_keys:
        binding = boundary_map.get(key)
        if binding is None:
            binding = next(
                (
                    value
                    for value in boundary_map.values()
                    if value.get("source_key") == key
                ),
                None,
            )
        if binding is None:
            raise SystemExit(f"missing selected boundary in domain response: {key}")
        metadata = selection.get("selection_metadata", {}).get(key, {})
        selected_rows.append(
            {
                "source_key": key,
                "face_index": metadata.get("face_index"),
                "face_facts": metadata.get("face_facts"),
                "brep_sha256": metadata.get("brep_sha256"),
                "target_entity_ids": binding["entity_ids"],
                "parent_entity_ids": binding.get("parent_entity_ids", []),
                "proof": binding.get("proof"),
                "provenance": binding.get("provenance"),
            }
        )

    summary = {
        "schema_version": "selected_face_domain_transfer_summary_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "domain_id": result["domain_id"],
        "spec_hash": result["spec_hash"],
        "volume_m3": result["volume_m3"],
        "boundary_count": len(boundary_map),
        "exterior_entity_count": len(result["exterior_entity_ids"]),
        "uncovered_entity_count": len(result.get("uncovered_entity_ids", [])),
        "selected_face_count": len(selected_rows),
        "selected_faces": selected_rows,
        "persistent_identity_status": selection.get(
            "persistent_identity_status", "unknown"
        ),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
