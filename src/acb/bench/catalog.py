"""Machine-readable description of the benchmark, generated from its sources.

The results site renders this instead of hardcoding anything: checks come
from the grader code, gates and failure classes from `gates.py`, prompt arms
from `rules.py` (including the exact text appended to the prompt), and tasks
from `tasks/<id>/` (instruction, spec, starting files, reference solutions).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from acb_graders.checks import CHECKS_BY_FAMILY
from acb_graders.gates import FAILURE_CLASS_HELP, GATES_BY_KIND
from acb_graders.rules import ARM_INFO, ARMS, render

from .plan import load_matrix
from .paths import TASKS_DIR

SCHEMA_VERSION = 1
MAX_INLINE_BYTES = 8_000
# Generated or vendored files: listed with their size, content omitted.
OMIT_CONTENT = {"package-lock.json", "go.sum", "poetry.lock", "uv.lock", "yarn.lock", "pnpm-lock.yaml"}


def _files(root: Path) -> list[dict]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if path.name == "expect.toml":
            continue
        size = path.stat().st_size
        content = None
        if path.name not in OMIT_CONTENT and size <= MAX_INLINE_BYTES:
            try:
                content = path.read_text()
            except UnicodeDecodeError:
                content = None
        files.append({"path": rel, "size": size, "content": content})
    return files


def _task(task_dir: Path) -> dict:
    meta = tomllib.loads((task_dir / "task.toml").read_text())
    spec = tomllib.loads((task_dir / "tests" / "spec.toml").read_text())
    families = spec.get("families") or [spec["family"]]
    oracles = []
    for oracle_dir in sorted((task_dir / "oracles").iterdir()):
        expect = tomllib.loads((oracle_dir / "expect.toml").read_text())
        oracles.append({"name": oracle_dir.name, "expect": expect, "files": _files(oracle_dir)})
    return {
        "id": task_dir.name,
        "family": spec["family"],
        "families": families,
        "gate": spec.get("gate", "image"),
        "metadata": meta.get("metadata", {}),
        # Exact text appended to the instruction in each prompt arm, for this task's check families.
        "appended": {arm: render(arm, families) for arm in ARMS},
        "timeouts": {"agent_sec": meta.get("agent", {}).get("timeout_sec"), "verifier_sec": meta.get("verifier", {}).get("timeout_sec")},
        "instruction": (task_dir / "instruction.md").read_text(),
        "spec": {
            "language": spec.get("app", {}).get("language"),
            "port": spec.get("app", {}).get("port"),
            "needs_build": spec.get("app", {}).get("needs_build", False),
            "run_args": spec.get("run", {}).get("args", []),
            "run_env": spec.get("run", {}).get("env", {}),
            "probe": spec.get("probe", {}),
            "image_size_mb": spec.get("budget", {}).get("image_size_mb"),
            "canary_file": spec.get("canary", {}).get("file"),
        },
        "files": _files(task_dir / "app"),
        "oracles": oracles,
    }


def build_catalog() -> dict:
    matrix = load_matrix()
    families = sorted(CHECKS_BY_FAMILY)
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_version": matrix["dataset_version"],
        "harbor_version": matrix["harbor_version"],
        "arms": [
            {"id": arm, **ARM_INFO[arm], "appended": {family: render(arm, family) for family in families}}
            for arm in ARMS
        ],
        "gates": list(GATES_BY_KIND["image"]),
        "gates_by_kind": {kind: list(gates) for kind, gates in GATES_BY_KIND.items()},
        "failure_classes": FAILURE_CLASS_HELP,
        "families": {
            family: {"checks": [check.describe() for check in CHECKS_BY_FAMILY[family]]} for family in families
        },
        "cells": [
            {k: cell[k] for k in ("id", "harness", "version", "model")} for cell in matrix["cells"]
        ],
        "tasks": [_task(p) for p in sorted(TASKS_DIR.iterdir()) if (p / "task.toml").exists()],
    }
