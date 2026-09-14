"""Independent CLI: schema, validate, mock, local, resume, batch, and summaries."""

import argparse
import json
import sys
from pathlib import Path

from .backends import Capabilities, MockBackend
from .local import LocalWorkerBackend
from .models import CFDError, SimulationSpec
from .orchestrator import CFDOrchestrator
from .reporting import aggregate
from .storage import atomic_json
from .topology import IsolatedOCAFTopology, MockTopology


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["schema", "validate", "run", "batch", "summary"])
    p.add_argument("spec", nargs="?")
    p.add_argument("--output", default="_cfd_experiment/output")
    p.add_argument("--input-root", default=".")
    p.add_argument("--backend", choices=["mock", "local"], default="mock")
    p.add_argument(
        "--worker-config", help="Operator-controlled JSON with command/capabilities"
    )
    p.add_argument("--job-id")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()
    try:
        if args.command == "schema":
            if args.spec:
                atomic_json(Path(args.spec), SimulationSpec.model_json_schema())
            else:
                print(
                    json.dumps(
                        SimulationSpec.model_json_schema(), ensure_ascii=False, indent=2
                    )
                )
            return 0
        if args.command == "summary":
            print(
                json.dumps(aggregate(Path(args.output)), ensure_ascii=False, indent=2)
            )
            return 0
        if not args.spec:
            p.error("spec JSON path is required")
        data = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        specs = data if args.command == "batch" else [data]
        if args.resume and (not args.job_id or args.command == "batch"):
            p.error("resume requires a single run and explicit --job-id")
        records = []
        for item in specs:
            spec = SimulationSpec.model_validate(item)
            if args.command == "validate":
                print(json.dumps({"valid": True, "spec_hash": spec.spec_hash}))
                return 0
            root = Path(args.input_root).resolve()
            if args.backend == "mock":
                backend = MockBackend()
                keys = [
                    b.surface.key
                    for b in spec.boundary_specs
                    if b.surface.source == "selection"
                ] + [
                    r.surface.key
                    for r in spec.mesh_strategy.refinements
                    if r.surface.source == "selection"
                ]
                factory = lambda g, keys=keys: MockTopology(g, keys)
            else:
                if not args.worker_config:
                    p.error("local backend requires --worker-config")
                config = json.loads(
                    Path(args.worker_config).read_text(encoding="utf-8")
                )
                backend = LocalWorkerBackend(
                    config["command"],
                    Capabilities.model_validate(config["capabilities"]),
                    input_root=root,
                )
                factory = lambda g, root=root: IsolatedOCAFTopology(root, g)
            runner = CFDOrchestrator(Path(args.output), root, backend, factory)
            records.append(runner.run(spec, job_id=args.job_id, resume=args.resume))
        print(
            json.dumps(
                records if args.command == "batch" else records[0],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if all(r["status"] == "success" for r in records) else 1
    except CFDError as exc:
        print(exc.diagnostic.model_dump_json(indent=2), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
