"""Validate graders against every oracle fixture of every task.

Each `tasks/<id>/oracles/<name>/` holds files overlaid on the task's `app/`
plus an `expect.toml` stating the expected reward and check statuses. The
fixture is graded inside the task-base image exactly like Harbor's verify
phase does, so a grader regression or an unfair check shows up here, before
any money is spent on agents.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .paths import REPO_ROOT, TASKS_DIR


@dataclass
class OracleOutcome:
    task: str
    oracle: str
    ok: bool
    problems: list[str] = field(default_factory=list)


def grade_fixture(task_dir: Path, oracle_dir: Path, image: str, engine: str = "podman") -> dict:
    with tempfile.TemporaryDirectory(prefix="acb-oracle-") as tmp:
        work = Path(tmp)
        app, out = work / "app", work / "out"
        shutil.copytree(task_dir / "app", app)
        shutil.copytree(oracle_dir, app, dirs_exist_ok=True)
        (app / "expect.toml").unlink(missing_ok=True)
        out.mkdir()
        subprocess.run(
            [
                engine, "run", "--rm", "--privileged",
                "-v", f"{REPO_ROOT / 'src'}:/tests:ro,z",
                "-v", f"{task_dir / 'tests' / 'spec.toml'}:/spec.toml:ro,z",
                "-v", f"{app}:/app:z",
                "-v", f"{out}:/out:z",
                "-w", "/tests",
                image,
                "python3", "-m", "acb_graders", "--spec", "/spec.toml", "--app", "/app", "--out", "/out",
            ],
            check=True,
            timeout=1800,
        )
        return json.loads((out / "checks.json").read_text()) | {"reward": json.loads((out / "reward.json").read_text())}


def compare(result: dict, expect: dict) -> list[str]:
    problems = []
    if "reward" in expect and result["reward"]["reward"] != expect["reward"]:
        problems.append(f"reward {result['reward']['reward']} != {expect['reward']} (failure_class={result['failure_class']})")
    statuses = {c["id"]: c["status"] for c in result["checks"]}
    for status, ids in expect.get("checks", {}).items():
        for check_id in ids:
            got = statuses.get(check_id)
            if got != status:
                evidence = next((c["evidence"] for c in result["checks"] if c["id"] == check_id), "")
                problems.append(f"{check_id}: expected {status}, got {got} ({evidence})")
    return problems


def validate(image: str, task_filter: str | None = None, engine: str = "podman") -> list[OracleOutcome]:
    outcomes = []
    for task_dir in sorted(p for p in TASKS_DIR.iterdir() if (p / "task.toml").exists()):
        if task_filter and task_filter not in task_dir.name:
            continue
        for oracle_dir in sorted((task_dir / "oracles").iterdir()):
            expect = tomllib.loads((oracle_dir / "expect.toml").read_text())
            try:
                result = grade_fixture(task_dir, oracle_dir, image, engine)
                problems = compare(result, expect)
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                problems = [f"grading crashed: {exc}"]
            outcome = OracleOutcome(task_dir.name, oracle_dir.name, not problems, problems)
            print(f"{'ok  ' if outcome.ok else 'FAIL'} {task_dir.name}/{oracle_dir.name}")
            for p in problems:
                print(f"     - {p}")
            outcomes.append(outcome)
    return outcomes
