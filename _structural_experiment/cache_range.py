"""Populate the generic role-fact cache with isolated per-role workers.

This tool is topology-only. It does not know which faces are structural
contacts; it only makes persistent-role inspection resilient to individual
malformed/deleted shapes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

from seekflow_structural.core.role_facts import CACHE_ROOT, _cache_path, _role_entries

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (  # noqa: E402
    OcafDocumentSession,
)


def _existing(path: Path) -> set[str]:
    done = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["key"])
            except Exception:
                pass
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("namespace")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    session = OcafDocumentSession.open(bundle / "design.xbf")
    try:
        keys = [
            entry.key.object_id
            for entry in _role_entries(session)
            if entry.key.namespace == args.namespace
        ][args.offset : args.offset + max(1, args.limit)]
    finally:
        session.close()

    path = _cache_path(bundle, args.namespace)
    done = _existing(path)
    pending = [key for key in keys if key not in done]

    def inspect(key: str):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "role_facts.py"),
                str(bundle),
                "facts",
                "--namespace",
                args.namespace,
                "--key",
                key,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return {
                "namespace": args.namespace,
                "key": key,
                "facts": json.loads(result.stdout)["facts"],
            }
        return {
            "namespace": args.namespace,
            "key": key,
            "error": (result.stderr or result.stdout or "worker failed")[-500:],
            "returncode": result.returncode,
        }

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as out:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.workers)
        ) as pool:
            for row in pool.map(inspect, pending):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(row["key"], "ok" if "facts" in row else "error", flush=True)
    print(path)


if __name__ == "__main__":
    main()
