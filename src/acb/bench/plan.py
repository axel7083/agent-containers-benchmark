"""Expand `matrix.toml` into CI shards (cell x arm) with per-shard budget caps."""

from __future__ import annotations

import re
import tomllib

from .paths import MATRIX_FILE, TASKS_DIR

SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def load_matrix() -> dict:
    return tomllib.loads(MATRIX_FILE.read_text())


def task_ids() -> list[str]:
    return sorted(p.name for p in TASKS_DIR.iterdir() if (p / "task.toml").exists())


def _keep(values: list[str], selector: str) -> list[str]:
    wanted = [s.strip() for s in selector.split(",") if s.strip()]
    if not wanted:
        return values
    unknown = set(wanted) - set(values)
    if unknown:
        raise SystemExit(f"unknown selection: {sorted(unknown)} (known: {values})")
    return [v for v in values if v in wanted]


def plan(cells: str = "", arms: str = "", tasks: str = "", trials: int | None = None) -> dict:
    matrix = load_matrix()
    trials = trials or matrix["trials"]
    all_cells = {c["id"]: c for c in matrix["cells"]}
    selected_tasks = _keep(task_ids(), tasks)
    shards = []
    for cell_id in _keep(list(all_cells), cells):
        cell = all_cells[cell_id]
        for arm in _keep(matrix["arms"], arms):
            shard_id = f"{cell_id}__{arm}"
            for value in (shard_id, cell["harness"], cell["version"], cell["model"].replace("/", ".")):
                if not SAFE.match(value):
                    raise SystemExit(f"unsafe identifier in matrix: {value!r}")
            est = trials * len(selected_tasks) * cell["est_cost_per_trial"]
            cap = max(matrix["cap_floor_usd"], round(est * matrix["cap_headroom"], 2))
            shards.append({
                "id": shard_id,
                "cell": cell_id,
                "harness": cell["harness"],
                "version": cell["version"],
                "model": cell["model"],
                "arm": arm,
                "tasks": selected_tasks,
                "trials": trials,
                "cap_usd": cap,
            })
    return {
        "dataset_version": matrix["dataset_version"],
        "harbor_version": matrix["harbor_version"],
        "total_cap_usd": round(sum(s["cap_usd"] for s in shards), 2),
        "shards": shards,
    }
