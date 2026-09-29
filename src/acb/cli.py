"""`acb` command line: validate oracles, build Harbor tasks, plan shards, run the meter, aggregate."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acb")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("oracles", help="grade every oracle fixture and compare with expect.toml")
    p.add_argument("--image", required=True, help="task-base image reference")
    p.add_argument("--task", help="substring filter on task id")
    p.add_argument("--engine", default="podman")

    p = sub.add_parser("build-tasks", help="materialize Harbor tasks into build/tasks")
    p.add_argument("--image", help="task-base image reference (default: images/task-base.lock)")
    p.add_argument("--out", default=None)

    p = sub.add_parser("arm", help="write the extra-instruction file for an arm")
    p.add_argument("arm")
    p.add_argument("--family", default="containerfile")
    p.add_argument("--out", required=True)

    p = sub.add_parser("plan", help="expand matrix.toml into shards (JSON on stdout)")
    p.add_argument("--cells", default="", help="comma-separated cell ids to keep")
    p.add_argument("--arms", default="", help="comma-separated arms to keep")
    p.add_argument("--tasks", default="", help="comma-separated task ids to keep")
    p.add_argument("--trials", type=int, default=None)

    p = sub.add_parser("meter", help="run the OpenRouter metering proxy (key read from stdin)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--model", required=True, help="OpenRouter model slug forced on every request")
    p.add_argument("--log", required=True)

    p = sub.add_parser("aggregate", help="collect Harbor job dirs into summary JSON")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--out", required=True)

    p = sub.add_parser("catalog", help="write the benchmark catalog (checks, arms, gates, tasks) as JSON")
    p.add_argument("--out", required=True)

    p = sub.add_parser("index", help="rebuild the runs index for the site")
    p.add_argument("runs_dir")
    p.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "oracles":
        from .bench.oracles import validate

        outcomes = validate(args.image, args.task, args.engine)
        failed = [o for o in outcomes if not o.ok]
        print(f"{len(outcomes) - len(failed)}/{len(outcomes)} oracle fixtures as expected")
        return 1 if failed else 0
    if args.cmd == "build-tasks":
        from .bench.build_tasks import build

        build(args.image, args.out)
        return 0
    if args.cmd == "arm":
        from pathlib import Path

        from acb_graders.rules import render

        Path(args.out).write_text(render(args.arm, args.family))
        return 0
    if args.cmd == "plan":
        import json

        from .bench.plan import plan

        print(json.dumps(plan(args.cells, args.arms, args.tasks, args.trials)))
        return 0
    if args.cmd == "meter":
        from .meter.proxy import serve

        return serve(args.host, args.port, args.model, args.log, sys.stdin.readline().strip())
    if args.cmd == "aggregate":
        from .bench.aggregate import aggregate

        aggregate(args.inputs, args.out)
        return 0
    if args.cmd == "catalog":
        import json
        from pathlib import Path

        from .bench.catalog import build_catalog

        Path(args.out).write_text(json.dumps(build_catalog(), indent=1))
        return 0
    if args.cmd == "index":
        from .bench.aggregate import index

        index(args.runs_dir, args.out)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
