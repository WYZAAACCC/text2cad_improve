"""Continue an existing Fluent checkpoint with an optional inlet velocity."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local"))

from fluent_worker import _run_fluent  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("job_dir", type=Path)
    p.add_argument("checkpoint", help="checkpoint basename without .cas.gz/.dat.gz")
    p.add_argument("--inlet", type=float)
    p.add_argument("--iterations", type=int, default=100)
    p.add_argument("--cpu", type=int, default=8)
    args = p.parse_args()
    job = args.job_dir.resolve()
    cout = job / (args.checkpoint + ".cas.gz")
    dout = job / (args.checkpoint + ".dat.gz")
    lines = [
        '/file/read-case "' + str(cout) + '"',
        '/file/read-data "' + str(dout) + '"',
    ]
    if args.inlet is not None:
        lines.append(
            "/define/boundary-conditions/set/velocity-inlet "
            f"z_inlet () vmag n {args.inlet} q"
        )
        lines.append("/solve/initialize/initialize-flow")
    lines.append(f"/solve/iterate {args.iterations}")
    lines.append('/file/write-case "probe-final.cas.gz"')
    lines.append('/file/write-data "probe-final.dat.gz"')
    lines.append("/exit")
    log = _run_fluent(job, "solver/probe", lines, args.cpu)
    text = log.read_text(encoding="utf-8", errors="replace")
    print(text[-12000:])


if __name__ == "__main__":
    main()
