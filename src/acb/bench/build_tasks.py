"""Materialize `tasks/<id>/` sources into runnable Harbor tasks under `build/tasks/`.

The graders are vendored into each task's `tests/` directory, which Harbor
only copies into the environment for the verify phase: the agent never sees
the checks it is graded on.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import BUILD_DIR, REPO_ROOT, TASK_BASE_LOCK, TASKS_DIR

METER_HOST = "acb-meter"

ENV_DOCKERFILE = """\
FROM {image}
COPY app/ /app/
WORKDIR /app
"""

# Merged by Harbor into its base compose file for the `main` service.
# privileged: nested Podman needs it. The extra host lets agents reach the
# metering proxy on the runner; the real API key never enters the container.
ENV_COMPOSE = f"""\
services:
  main:
    privileged: true
    extra_hosts:
      - "{METER_HOST}:host-gateway"
"""

TEST_SH = """\
#!/bin/bash
set -uo pipefail
cd /tests
python3 -m acb_graders --spec /tests/spec.toml --app /app --out /logs/verifier
"""

SOLVE_SH = """\
#!/bin/bash
set -euo pipefail
cp -a /solution/files/. /app/
"""


def task_base_image(explicit: str | None) -> str:
    if explicit:
        return explicit
    return TASK_BASE_LOCK.read_text().strip()


def build_task(src: Path, dest: Path, image: str) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    env = dest / "environment"
    tests = dest / "tests"
    solution = dest / "solution"
    env.mkdir(parents=True)
    tests.mkdir()
    solution.mkdir()

    shutil.copy(src / "task.toml", dest / "task.toml")
    shutil.copy(src / "instruction.md", dest / "instruction.md")
    shutil.copytree(src / "app", env / "app")
    (env / "Dockerfile").write_text(ENV_DOCKERFILE.format(image=image))
    (env / "docker-compose.yaml").write_text(ENV_COMPOSE)

    shutil.copy(src / "tests" / "spec.toml", tests / "spec.toml")
    shutil.copytree(REPO_ROOT / "src" / "acb_graders", tests / "acb_graders", ignore=shutil.ignore_patterns("__pycache__"))
    (tests / "test.sh").write_text(TEST_SH)
    (tests / "test.sh").chmod(0o755)

    best = src / "oracles" / "best"
    shutil.copytree(best, solution / "files", ignore=shutil.ignore_patterns("expect.toml"))
    (solution / "solve.sh").write_text(SOLVE_SH)
    (solution / "solve.sh").chmod(0o755)


def build(image: str | None = None, out: str | None = None) -> Path:
    ref = task_base_image(image)
    out_dir = Path(out) if out else BUILD_DIR / "tasks"
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(p for p in TASKS_DIR.iterdir() if (p / "task.toml").exists()):
        build_task(src, out_dir / src.name, ref)
        print(f"built {src.name}")
    return out_dir
