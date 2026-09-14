"""List persistent topology roles from one immutable CAD lineage bundle."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/cfd/src"))
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))

from seekflow_cfd.models import GeometryRef  # noqa: E402
from seekflow_cfd.topology import OCAFTopology  # noqa: E402
from seekflow_cfd.storage import file_hash  # noqa: E402
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (  # noqa: E402
    OcafDocumentSession,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--kind")
    parser.add_argument("--namespace")
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    geometry = GeometryRef(
        lineage_id=history["lineage_id"],
        revision_id=history["revision_id"],
        cad_record_id="structural-inspect-" + history["lineage_id"],
        geometry={"path": "model.step", "sha256": file_hash(bundle / "model.step")},
        topology={"path": "design.xbf", "sha256": file_hash(bundle / "design.xbf")},
        history_evidence={
            "path": "history.json",
            "sha256": file_hash(bundle / "history.json"),
        },
        length_unit="mm",
    )
    raw_session = OcafDocumentSession.open(bundle / "design.xbf")
    try:
        print(
            json.dumps(
                {
                    "metadata": raw_session.get_lineage_metadata(),
                    "revision_number": raw_session.revision_number,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        roles = [
            {
                "kind": entry.key.object_kind,
                "namespace": entry.key.namespace,
                "key": entry.key.object_id,
                "label_path": list(entry.tag_path.tags),
            }
            for entry in raw_session.label_index.entries()
            if entry.retired_revision is None
            and entry.key.object_kind in {"selection", "face_role", "edge_role"}
        ]
        counts = Counter(role["kind"] for role in roles)
        print(json.dumps(counts, indent=2))
        face_groups = Counter(
            (role["namespace"], role["key"].split("/", 1)[0])
            for role in roles
            if role["kind"] == "face_role"
        )
        if args.namespace is None:
            print("FACE_ROLE_GROUPS")
            for (namespace, prefix), count in sorted(face_groups.items()):
                print(
                    json.dumps(
                        {"namespace": namespace, "prefix": prefix, "count": count}
                    )
                )
        selected = [
            role
            for role in roles
            if (args.kind is None or role["kind"] == args.kind)
            and (args.namespace is None or role["namespace"] == args.namespace)
        ]
        for role in selected[: args.limit]:
            print(json.dumps(role, ensure_ascii=False))
    finally:
        raw_session.close()


if __name__ == "__main__":
    main()
