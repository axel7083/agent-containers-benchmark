#!/usr/bin/env python3
"""Fail CI unless Harbor's oracle agent scores reward 1 and the nop agent scores 0 on every task."""

import json
import sys
from pathlib import Path


def rewards(job_dir: str) -> dict[str, float | None]:
    out = {}
    for path in sorted(Path(job_dir).glob("*/result.json")):
        result = json.loads(path.read_text())
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        out[result["task_name"]] = rewards.get("reward")
    return out


def main(oracle_dir: str, nop_dir: str) -> int:
    problems = []
    oracle, nop = rewards(oracle_dir), rewards(nop_dir)
    if not oracle or not nop:
        problems.append("no trial results found")
    problems += [f"oracle scored {v} on {k}" for k, v in oracle.items() if v != 1.0]
    problems += [f"nop scored {v} on {k}" for k, v in nop.items() if v != 0.0]
    for p in problems:
        print(f"::error::{p}")
    print(f"oracle: {oracle}\nnop: {nop}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
