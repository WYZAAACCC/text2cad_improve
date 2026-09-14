"""Build a crash-isolated face-role index and relation metadata catalog."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

STRUCTURAL_ROOT = Path(__file__).resolve().parents[1]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from seekflow_structural.core.pattern_solids import _open  # noqa: E402

from face_evolution.face_index import (  # noqa: E402
    connect,
    initialize_index,
    insert_face_role,
    insert_relation,
    set_meta,
)

RELATION_PATTERN = re.compile(
    r"^rk:(?P<feature>[^:]+):(?P<component>[^:]+):"
    r"(?P<operation>[^:]+):(?P<selection>[^:]*):"
    r"(?P<source>[^:]+):(?P<entity>[^:]+):"
    r"(?P<kind>[^:]+):(?P<role>.+)$"
)


def _role_entries(bundle: Path, namespace: str) -> list:
    session = _open(bundle)
    try:
        return [
            entry
            for entry in session.label_index.entries()
            if entry.retired_revision is None
            and entry.key.object_kind == "face_role"
            and entry.key.namespace == namespace
        ]
    finally:
        session.close()


def _relation_entries(bundle: Path, namespace: str) -> list:
    session = _open(bundle)
    try:
        return [
            entry
            for entry in session.label_index.entries()
            if entry.retired_revision is None
            and entry.key.object_kind == "relation"
            and entry.key.namespace == namespace
        ]
    finally:
        session.close()


def _run_range(
    python_exe: str,
    worker: Path,
    bundle: Path,
    database: Path,
    namespace: str,
    final_feature: str,
    start: int,
    end: int,
    output: Path,
    timeout_s: int,
) -> dict:
    command = [
        python_exe,
        str(worker),
        str(bundle),
        str(database),
        namespace,
        final_feature,
        str(start),
        str(end),
        str(output),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(
            f"range {start}:{end} failed rc={result.returncode}: "
            + (result.stderr[-800:] or result.stdout[-800:])
        )
    counts = {}
    if result.stdout.strip():
        try:
            counts = json.loads(result.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            counts = {}
    return {
        "start": start,
        "end": end,
        "output": output,
        "counts": counts,
    }


def _index_relation_metadata(connection, bundle: Path, namespace: str) -> int:
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    entries = _relation_entries(bundle, namespace)
    count = 0
    for entry in entries:
        key = entry.key.object_id
        match = RELATION_PATTERN.match(key)
        source_key = match.group("source") if match else None
        evolution_kind = match.group("kind") if match else None
        relation_role = match.group("role") if match else None
        insert_relation(
            connection,
            {
                "relation_id": key,
                "revision_id": history["revision_id"],
                "namespace": namespace,
                "feature_id": namespace.split(":", 1)[-1],
                "relation_key": key,
                "relation_tag": entry.tag_path.tags[-1],
                "label_path": list(entry.tag_path.tags),
                "source_key": source_key,
                "evolution_kind": evolution_kind,
                "relation_role": relation_role,
            },
        )
        count += 1
    return count


def build_index(
    bundle: Path,
    database: Path,
    namespace: str,
    final_feature: str,
    workers: int,
    range_size: int,
    timeout_s: int,
) -> dict:
    bundle = bundle.resolve()
    database = database.resolve()
    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    revision_id = history["revision_id"]
    entries = _role_entries(bundle, namespace)
    connection = connect(database)
    try:
        initialize_index(connection)
        connection.execute(
            "DELETE FROM face_roles WHERE revision_id = ? AND namespace = ?",
            (revision_id, namespace),
        )
        connection.execute(
            "DELETE FROM evolution_relations WHERE revision_id = ? AND namespace = ?",
            (revision_id, namespace),
        )
        connection.commit()
    finally:
        connection.close()

    output_root = database.parent / "ranges"
    output_root.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name("face_role_range_worker.py")
    pending = [
        (start, min(start + range_size, len(entries)))
        for start in range(0, len(entries), range_size)
    ]
    completed = []
    failures = []
    python_exe = sys.executable

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                _run_range,
                python_exe,
                worker,
                bundle,
                database,
                namespace,
                final_feature,
                start,
                end,
                output_root / f"{namespace.replace(':', '_')}_{start}_{end}.jsonl",
                timeout_s,
            ): (start, end)
            for start, end in pending
        }
        while futures:
            for future in as_completed(list(futures)):
                start, end = futures.pop(future)
                try:
                    completed.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    if end - start > 1:
                        middle = (start + end) // 2
                        for low, high in ((start, middle), (middle, end)):
                            futures[
                                pool.submit(
                                    _run_range,
                                    python_exe,
                                    worker,
                                    bundle,
                                    database,
                                    namespace,
                                    final_feature,
                                    low,
                                    high,
                                    output_root
                                    / f"{namespace.replace(':', '_')}_{low}_{high}.jsonl",
                                    timeout_s,
                                )
                            ] = (low, high)
                    else:
                        failures.append(
                            {
                                "start": start,
                                "end": end,
                                "error": str(exc),
                            }
                        )
                break

    connection = connect(database)
    try:
        inserted = 0
        for result in completed:
            for line in Path(result["output"]).read_text(
                encoding="utf-8"
            ).splitlines():
                if line.strip():
                    insert_face_role(connection, json.loads(line))
                    inserted += 1
        relation_count = _index_relation_metadata(
            connection, bundle, namespace
        )
        connection.commit()
        summary = {
            "revision_id": revision_id,
            "namespace": namespace,
            "final_feature": final_feature,
            "role_entry_count": len(entries),
            "inserted_role_count": inserted,
            "relation_count": relation_count,
            "completed_ranges": len(completed),
            "quarantined_ranges": failures,
        }
        set_meta(
            connection,
            f"roles:{revision_id}:{namespace}",
            summary,
        )
        return summary
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--namespace", default="feature:n_final_cut")
    parser.add_argument("--final-feature", default="n_final_cut")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--range-size", type=int, default=400)
    parser.add_argument("--timeout-s", type=int, default=300)
    args = parser.parse_args()
    print(
        json.dumps(
            build_index(
                args.bundle,
                args.database,
                args.namespace,
                args.final_feature,
                args.workers,
                args.range_size,
                args.timeout_s,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
