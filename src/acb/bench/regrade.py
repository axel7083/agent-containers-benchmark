"""Re-grade finished trials from the `/app` each run keeps, after a grader fix.

Agents are not re-run (and nothing is billed): the grader is executed on the
files the agent left, in the task-base image, and the trial's verifier output
and rewards are replaced in the downloaded artifact tree. Re-aggregate
afterwards to publish the corrected run.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .oracles import grade_app
from .paths import TASKS_DIR


def regrade(root: str, image: str, task_filter: str | None = None, engine: str = "podman") -> list[dict]:
    changes = []
    for result_path in sorted(Path(root).glob("**/jobs/*/*/result.json")):
        trial_dir = result_path.parent
        result = json.loads(result_path.read_text())
        task = str(result.get("task_name", "")).split("/")[-1]
        if task_filter and task_filter not in task:
            continue
        saved = trial_dir / "artifacts" / "app"
        if not saved.is_dir() or not (TASKS_DIR / task).is_dir():
            print(f"skip {trial_dir.name}: no saved /app")
            continue
        with tempfile.TemporaryDirectory(prefix="acb-regrade-") as tmp:
            app = Path(tmp) / "app"
            shutil.copytree(saved, app, symlinks=True)
            graded = grade_app(TASKS_DIR / task, app, image, engine)
        reward = graded.pop("reward")
        old = ((result.get("verifier_result") or {}).get("rewards") or {})
        verifier = trial_dir / "verifier"
        verifier.mkdir(exist_ok=True)
        (verifier / "checks.json").write_text(json.dumps(graded, indent=2))
        (verifier / "reward.json").write_text(json.dumps(reward, indent=2))
        result.setdefault("verifier_result", {})["rewards"] = reward
        result_path.write_text(json.dumps(result, indent=2))
        change = {"trial": trial_dir.name, "shard": trial_dir.parent.name, "reward": (old.get("reward"), reward.get("reward")),
                  "practice": (old.get("practice_uncond"), reward.get("practice_uncond")), "class": graded["failure_class"]}
        changes.append(change)
        print(f"{change['shard']:60s} reward {change['reward'][0]} -> {change['reward'][1]}  practice {change['practice'][0]} -> "
              f"{change['practice'][1]}  ({change['class']})")
    return changes
