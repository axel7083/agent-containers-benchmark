"""Expand `matrix.toml` into CI shards with per-shard budget caps.

A shard is one CI job with its own capped OpenRouter key. Trials inside a
shard run sequentially (the metering proxy attributes cost by time window),
so parallelism comes from the number of shards:

- shard_by = "arm":  one shard per cell x arm, running every task.
- shard_by = "task": one shard per cell x arm x task (default): ~5x more,
  shorter jobs, so wall time is bounded by the slowest single task.
"""

from __future__ import annotations

import math
import re
import tomllib

from .paths import MATRIX_FILE, TASKS_DIR

SAFE = re.compile(r"^[A-Za-z0-9._+-]+$")


def load_matrix() -> dict:
    return tomllib.loads(MATRIX_FILE.read_text())


def task_ids() -> list[str]:
    return sorted(p.name for p in TASKS_DIR.iterdir() if (p / "task.toml").exists())


def task_families(task_id: str) -> tuple[str, ...]:
    spec = tomllib.loads((TASKS_DIR / task_id / "tests" / "spec.toml").read_text())
    return tuple(spec.get("families") or [spec["family"]])


def _keep(values: list[str], selector: str) -> list[str]:
    wanted = [s.strip() for s in selector.split(",") if s.strip()]
    if not wanted:
        return values
    unknown = set(wanted) - set(values)
    if unknown:
        raise SystemExit(f"unknown selection: {sorted(unknown)} (known: {values})")
    return [v for v in values if v in wanted]


SHARD_BY = ("arm", "task")


def plan(cells: str = "", arms: str = "", tasks: str = "", trials: int | None = None, shard_by: str | None = None) -> dict:
    matrix = load_matrix()
    trials = trials or matrix["trials"]
    shard_by = shard_by or matrix.get("shard_by", "task")
    if shard_by not in SHARD_BY:
        raise SystemExit(f"shard_by must be one of {SHARD_BY}, got {shard_by!r}")
    all_cells = {c["id"]: c for c in matrix["cells"]}
    selected_tasks = _keep(task_ids(), tasks)
    shards = []
    for cell_id in _keep(list(all_cells), cells):
        cell = all_cells[cell_id]
        for arm in _keep(matrix["arms"], arms):
            per_trial = cell["est_cost_per_trial"]
            if isinstance(per_trial, dict):
                per_trial = per_trial[arm]
            if shard_by == "task":
                groups = [[t] for t in selected_tasks]
            else:
                # The explicit arm appends the rules of the task's check families, one text per Harbor job:
                # tasks sharing a job must share their families.
                by_families: dict[tuple[str, ...], list[str]] = {}
                for t in selected_tasks:
                    by_families.setdefault(task_families(t), []).append(t)
                groups = list(by_families.values())
            for group in groups:
                suffix = group[0] if shard_by == "task" else "+".join(task_families(group[0]))
                shard_id = f"{cell_id}__{arm}__{suffix}"
                for value in (shard_id, cell["harness"], cell["version"], cell["model"].replace("/", ".")):
                    if not SAFE.match(value):
                        raise SystemExit(f"unsafe identifier in matrix: {value!r}")
                est = trials * len(group) * per_trial
                # Round up to the cent: rounding down could leave the cap just below one full-size request.
                cap = max(matrix["cap_floor_usd"], math.ceil((est * matrix["cap_headroom"] + cell.get("max_request_usd", 0.0)) * 100) / 100)
                shards.append({
                    "id": shard_id,
                    "cell": cell_id,
                    "harness": cell["harness"],
                    "version": cell["version"],
                    "model": cell["model"],
                    "arm": arm,
                    "families": list(task_families(group[0])),
                    "tasks": group,
                    "trials": trials,
                    "est_usd": round(est, 4),
                    "cap_usd": cap,
                })
    if len(shards) > 256:
        raise SystemExit(f"{len(shards)} shards exceed GitHub's 256-job matrix limit; narrow the selection or use shard_by=arm")
    return {
        "dataset_version": matrix["dataset_version"],
        "harbor_version": matrix["harbor_version"],
        "shard_by": shard_by,
        # Expected spend decides whether a run fits the budget; caps are per-key safety limits and
        # include one reserved full-size request, so their sum overstates any realistic spend.
        "total_est_usd": round(sum(s["est_usd"] for s in shards), 2),
        "total_cap_usd": round(sum(s["cap_usd"] for s in shards), 2),
        "shards": shards,
    }
