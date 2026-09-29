"""Grade a task: `python3 -m acb_graders --spec spec.toml --app /app --out /logs/verifier`.

Writes Harbor's flat numeric `reward.json` plus a detailed `checks.json`.
Practice checks run whenever an artifact exists, so we report both an
unconditional practice score and one conditional on the gates passing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import gates
from .checks import CHECKS_BY_FAMILY
from .containerfile import parse_file
from .model import Artifacts, CheckResult, Spec

SCHEMA_VERSION = 1


def practice_score(results: list[CheckResult]) -> float | None:
    scored = [r for r in results if r.weight > 0 and r.status in ("pass", "fail")]
    total = sum(r.weight for r in scored)
    if total == 0:
        return None
    return sum(r.weight for r in scored if r.status == "pass") / total


def grade(spec: Spec, app_dir: Path) -> dict:
    artifacts = Artifacts(app_dir=app_dir, spec=spec)
    artifacts.containerfile_path = gates.find_containerfile(app_dir)
    if artifacts.containerfile_path is not None:
        artifacts.containerfile = parse_file(artifacts.containerfile_path)

    try:
        gate = gates.run_gates(artifacts)
    except Exception as exc:  # grader crash is infra, never a model failure
        gate = gates.GateResult(failure_class="infra", log=[f"grader error: {type(exc).__name__}: {exc}"])

    results = [check.run(artifacts) for check in CHECKS_BY_FAMILY[spec.family]]
    uncond = practice_score(results) or 0.0
    passed = gate.passed

    reward: dict[str, float] = {
        "reward": 1.0 if passed else 0.0,
        "practice_uncond": round(uncond, 4),
    }
    if passed:
        reward["practice_cond"] = round(uncond, 4)
    for name in ("artifact", "build", "start", "probe"):
        if name in gate.gates:
            reward[f"gate.{name}"] = 1.0 if gate.gates[name] else 0.0
    for r in results:
        if r.status in ("pass", "fail"):
            reward[f"check.{r.id}"] = 1.0 if r.status == "pass" else 0.0

    details = {
        "schema_version": SCHEMA_VERSION,
        "family": spec.family,
        "failure_class": gate.failure_class,
        "gates": gate.gates,
        "containerfile": str(artifacts.containerfile_path.relative_to(app_dir)) if artifacts.containerfile_path else None,
        "checks": [r.as_dict() for r in results],
        "runtime": {
            "image_size_bytes": artifacts.runtime.image_size_bytes,
            "image_user": artifacts.runtime.image_user,
            "process_uids": artifacts.runtime.process_uids,
            "hadolint": artifacts.runtime.hadolint,
        },
        "log": gate.log,
    }
    return {"reward": reward, "details": details}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acb_graders")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--app", type=Path, default=Path("/app"))
    parser.add_argument("--out", type=Path, default=Path("/logs/verifier"))
    parser.add_argument("--keep", action="store_true", help="keep the verify image and container")
    args = parser.parse_args(argv)

    spec = Spec.load(args.spec)
    try:
        out = grade(spec, args.app)
    finally:
        if not args.keep:
            gates.cleanup()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "reward.json").write_text(json.dumps(out["reward"], indent=2))
    (args.out / "checks.json").write_text(json.dumps(out["details"], indent=2))
    summary = {k: v for k, v in out["reward"].items() if not k.startswith("check.")}
    print(json.dumps({"failure_class": out["details"]["failure_class"], **summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
