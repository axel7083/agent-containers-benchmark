"""Collect CI artifacts into one run file and summary statistics.

Artifacts come from jobs where agents executed arbitrary code, so everything
here is treated as untrusted data: JSON is parsed, numbers are coerced, and
strings are length-capped. Nothing from an artifact is ever executed.

Per trial we join:
- Harbor's `result.json` (task, timings, harness-reported tokens, rewards),
- the grader's `verifier/checks.json` (failure class, per-check evidence),
- the ATIF trajectory (process metrics: tool calls, docker vs podman usage),
- the metering proxy log (OpenRouter-billed cost, attributed by time window;
  trials inside a shard run sequentially with `-n 1`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .stats import cluster_bootstrap_mean, wilson

SCHEMA_VERSION = 1
_BOUNDARY = r"""(?:^|[\s;&|(`$"'])"""  # shell separators, or a quote (Codex embeds commands in JS strings)
DOCKER_CMD = re.compile(_BOUNDARY + r"docker(?:-compose)?\s+(?:build|run|compose|ps|images|pull|push|exec|logs|rm|rmi|inspect|stop|start|tag|login|buildx|version|info)\b")
PODMAN_CMD = re.compile(_BOUNDARY + r"podman\s+[a-z]")
PODMAN_BUILD = re.compile(_BOUNDARY + r"podman\s+(?:build|image\s+build)\b")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _str(value: Any, limit: int = 300) -> str | None:
    return str(value)[:limit] if value is not None else None


def _ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _commands(trajectory: dict) -> list[str]:
    out: list[str] = []
    for step in trajectory.get("steps") or []:
        for call in (step or {}).get("tool_calls") or []:
            args = (call or {}).get("arguments") or {}
            for value in args.values() if isinstance(args, dict) else []:
                if isinstance(value, str):
                    out.append(value)
                elif isinstance(value, list):
                    out.extend(v for v in value if isinstance(v, str))
    return out


def process_metrics(trajectory: dict | None) -> dict[str, Any]:
    if not isinstance(trajectory, dict):
        return {}
    steps = trajectory.get("steps") or []
    commands = _commands(trajectory)
    text = "\n".join(commands)
    return {
        "steps": len(steps),
        "tool_calls": sum(len((s or {}).get("tool_calls") or []) for s in steps),
        "docker_commands": len(DOCKER_CMD.findall(text)),
        "podman_commands": len(PODMAN_CMD.findall(text)),
        "self_built": bool(PODMAN_BUILD.search(text)),
    }


def meter_costs(meter_log: Path) -> tuple[list[dict], dict[str, dict]]:
    requests, generations = [], {}
    if not meter_log.exists():
        return requests, generations
    for line in meter_log.read_text(errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "request":
            requests.append(entry)
        elif entry.get("type") == "generation" and isinstance(entry.get("id"), str):
            generations[entry["id"]] = entry
    return requests, generations


def attribute(requests: list[dict], generations: dict[str, dict], start: float | None, end: float | None) -> dict[str, Any]:
    if start is None or end is None:
        return {}
    cost = 0.0
    prompt = completion = cached = 0
    providers: set[str] = set()
    n = budget_hits = errors = 0
    missing = 0
    for req in requests:
        ts = _num(req.get("ts"))
        if ts is None or not (start - 1 <= ts <= end + 1):
            continue
        n += 1
        status = req.get("status")
        # OpenRouter answers 402 when credits run out and 403 "Key limit exceeded" when a key hits its cap.
        if status == 402 or (status == 403 and "limit" in str(req.get("error", "")).lower()):
            budget_hits += 1
        elif isinstance(status, int) and status >= 400 and status != 499:  # 499: client cancelled
            errors += 1
        for gid in req.get("generation_ids") or []:
            gen = generations.get(gid)
            if not gen or gen.get("missing"):
                missing += 1
                continue
            cost += _num(gen.get("total_cost")) or 0.0
            prompt += int(_num(gen.get("native_tokens_prompt") or gen.get("tokens_prompt")) or 0)
            completion += int(_num(gen.get("native_tokens_completion") or gen.get("tokens_completion")) or 0)
            cached += int(_num(gen.get("native_tokens_cached")) or 0)
            if gen.get("provider_name"):
                providers.add(_str(gen["provider_name"], 60))
    return {
        "billed_cost_usd": round(cost, 6),
        "requests": n,
        "request_errors": errors,
        "budget_hits": budget_hits,
        "generations_unresolved": missing,
        "tokens_prompt": prompt,
        "tokens_cached": cached,
        "tokens_completion": completion,
        "providers": sorted(providers),
    }


def collect_shard(shard_dir: Path) -> list[dict]:
    shard = _load(shard_dir / "shard.json") or {}
    requests, generations = meter_costs(shard_dir / "meter.jsonl")
    trials = []
    for result_path in sorted(shard_dir.glob("jobs/*/*/result.json")):
        trial_dir = result_path.parent
        result = _load(result_path)
        if not isinstance(result, dict):
            continue
        agent_result = result.get("agent_result") or {}
        rewards = ((result.get("verifier_result") or {}).get("rewards")) or {}
        checks = _load(trial_dir / "verifier" / "checks.json") or {}
        timing = result.get("agent_execution") or {}
        start, end = _ts(timing.get("started_at")), _ts(timing.get("finished_at"))
        exception = (result.get("exception_info") or {}).get("exception_type")
        failure_class = _str(checks.get("failure_class"), 40) if checks else None
        metered = attribute(requests, generations, start, end)
        if metered.get("budget_hits"):
            failure_class = "budget"
        elif exception == "AgentTimeoutError" and failure_class != "none":
            # Ran out of time: still a failure of the agent, but labelled as such rather than by
            # whatever half-finished state the grader found.
            failure_class = "timeout"
        elif failure_class is None:
            failure_class = "infra" if exception else "no-verdict"
        task = _str(result.get("task_name"), 120) or ""
        trials.append({
            "shard": _str(shard.get("id"), 120),
            "cell": _str(shard.get("cell"), 120),
            "harness": _str(shard.get("harness"), 60),
            "harness_version": _str(((result.get("agent_info") or {}).get("version")), 60),
            "model": _str(shard.get("model"), 120),
            "arm": _str(shard.get("arm"), 20),
            "task": task.split("/")[-1],
            "gate": _str(checks.get("gate"), 20),
            "families": [_str(f, 40) for f in (checks.get("families") or [])][:8],
            "trial": _str(result.get("trial_name"), 120),
            "reward": _num(rewards.get("reward")),
            "practice_uncond": _num(rewards.get("practice_uncond")),
            "practice_cond": _num(rewards.get("practice_cond")),
            "gates": {k.removeprefix("gate."): _num(v) for k, v in rewards.items() if isinstance(k, str) and k.startswith("gate.")},
            "checks": {
                _str(c.get("id"), 60): {"status": _str(c.get("status"), 10), "evidence": _str(c.get("evidence"), 200)}
                for c in checks.get("checks") or [] if isinstance(c, dict)
            },
            "hadolint_codes": sorted({_str(f.get("code"), 12) for f in ((checks.get("runtime") or {}).get("hadolint") or []) if isinstance(f, dict)}),
            "image_size_mb": round((_num((checks.get("runtime") or {}).get("image_size_bytes")) or 0) / 1e6, 1) or None,
            "failure_class": failure_class,
            "exception": _str(exception, 80),
            "agent_seconds": round(end - start, 1) if start and end else None,
            "harness_reported": {
                "input_tokens": _num(agent_result.get("n_input_tokens")),
                "cache_tokens": _num(agent_result.get("n_cache_tokens")),
                "output_tokens": _num(agent_result.get("n_output_tokens")),
                "cost_usd": _num(agent_result.get("cost_usd")),
            },
            "metered": metered,
            "process": process_metrics(_load(trial_dir / "agent" / "trajectory.json")),
        })
    return trials


EXCLUDED = {"infra", "budget", "no-verdict"}
# A trial without a Containerfile scores 0 on practice, but says nothing about any single practice:
# it is left out of per-check pass rates.
NO_EVIDENCE = {"no-artifact"}


def reconcile(trials: list[dict], billing: dict | None) -> dict[str, dict]:
    """Make OpenRouter per-key usage the cost of record.

    Each shard has its own key, so the key's `usage` is the exact billed total
    for the shard. The proxy's per-generation costs only split that total
    across trials; whatever the proxy could not see (e.g. a request the agent
    cancelled mid-stream) is reported as unattributed, never dropped.
    """
    shards: dict[str, dict] = {}
    usage = {k: _num((v or {}).get("usage")) for k, v in ((billing or {}).get("shards") or {}).items()}
    by_shard: dict[str, list[dict]] = defaultdict(list)
    for t in trials:
        by_shard[t["shard"]].append(t)
    for shard, items in by_shard.items():
        metered = sum(t["metered"].get("billed_cost_usd") or 0.0 for t in items)
        key_usage = usage.get(shard)
        total = key_usage if key_usage is not None else metered
        scale = total / metered if metered else 0.0
        for t in items:
            t["cost_usd"] = round((t["metered"].get("billed_cost_usd") or 0.0) * scale, 6)
        shards[shard] = {
            "key_usage_usd": key_usage,
            "metered_usd": round(metered, 6),
            "unattributed_usd": round(total - metered, 6) if key_usage is not None else None,
        }
    return shards


def summarize(
    trials: list[dict], shard_costs: dict[str, dict] | None = None, planned: dict[tuple[str, str], int] | None = None
) -> dict[str, Any]:
    shard_costs = shard_costs or {}
    planned = planned or {}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in trials:
        groups[(t["cell"], t["arm"])].append(t)
    cells = []
    for (cell, arm), items in sorted(groups.items()):
        valid = [t for t in items if t["failure_class"] not in EXCLUDED]
        passed = sum(1 for t in valid if t["reward"] == 1.0)
        lo, hi = wilson(passed, len(valid))
        by_task: dict[str, list[float]] = defaultdict(list)
        for t in valid:
            if t["practice_uncond"] is not None:
                by_task[t["task"]].append(t["practice_uncond"])
        mean, (plo, phi) = cluster_bootstrap_mean(by_task)
        check_rates: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0, "na": 0, "error": 0})
        for t in valid:
            if t["failure_class"] in NO_EVIDENCE:
                continue
            for cid, c in t["checks"].items():
                if c["status"] in check_rates[cid]:
                    check_rates[cid][c["status"]] += 1
        shard_ids = sorted({t["shard"] for t in items})
        billed = sum((shard_costs.get(sid, {}).get("key_usage_usd") or 0.0) for sid in shard_ids) if shard_costs else None
        if not billed:
            billed = sum(t.get("cost_usd", t["metered"].get("billed_cost_usd")) or 0.0 for t in items)
        unattributed = sum((shard_costs.get(sid, {}).get("unattributed_usd") or 0.0) for sid in shard_ids)
        reported = [t["harness_reported"].get("cost_usd") for t in items]
        cells.append({
            "cell": cell,
            "arm": arm,
            "harness": items[0]["harness"],
            "model": items[0]["model"],
            "n_trials": len(items),
            "n_planned": planned.get((cell, arm)) or None,
            "n_valid": len(valid),
            "excluded": {k: sum(1 for t in items if t["failure_class"] == k) for k in EXCLUDED if any(t["failure_class"] == k for t in items)},
            "gate_pass_rate": passed / len(valid) if valid else None,
            "gate_pass_ci": [lo, hi],
            "practice_uncond_mean": mean,
            "practice_uncond_ci": [plo, phi],
            "checks": {cid: v | {"rate": v["pass"] / (v["pass"] + v["fail"]) if v["pass"] + v["fail"] else None} for cid, v in sorted(check_rates.items())},
            "billed_cost_usd": round(billed, 4),
            "unattributed_cost_usd": round(unattributed, 4),
            "harness_reported_cost_usd": round(sum(c for c in reported if c), 4) if any(reported) else None,
            "cost_per_success_usd": round(billed / passed, 4) if passed else None,
            "mean_agent_seconds": _mean([t["agent_seconds"] for t in items]),
            "docker_usage_rate": _mean([1.0 if t["process"].get("docker_commands") else 0.0 for t in items if t["process"]]),
            "self_built_rate": _mean([1.0 if t["process"].get("self_built") else 0.0 for t in items if t["process"]]),
            "failure_classes": dict(sorted(_count(t["failure_class"] for t in items).items())),
        })
    return {"cells": cells}


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _count(values) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values:
        out[str(v)] += 1
    return out


def aggregate(inputs: list[str], out: str) -> dict:
    trials: list[dict] = []
    plan, billing = None, None
    for root in map(Path, inputs):
        plan = plan or _load(root / "plan.json")
        billing = billing or _load(root / "billing" / "billing.json")
        for shard_dir in sorted(p.parent for p in root.glob("**/shard.json")):
            trials.extend(collect_shard(shard_dir))
    shard_costs = reconcile(trials, billing)
    planned: dict[tuple[str, str], int] = defaultdict(int)
    for s in (plan or {}).get("shards", []):
        planned[(s["cell"], s["arm"])] += len(s["tasks"]) * int(s["trials"])
    run = {
        "schema_version": SCHEMA_VERSION,
        "status": os.environ.get("RUN_RESULT", "unknown"),
        # Free-text provenance, e.g. "kube trials re-graded after a gate fix".
        "note": os.environ.get("RUN_NOTE") or None,
        "n_planned": sum(planned.values()) or None,
        "run_id": os.environ.get("RUN_ID", "local"),
        "run_url": os.environ.get("RUN_URL"),
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "dataset_version": (plan or {}).get("dataset_version"),
        "harbor_version": (plan or {}).get("harbor_version"),
        "billing": billing,
        "shards": shard_costs,
        "catalog": _catalog(),
        "summary": summarize(trials, shard_costs, planned),
        "trials": trials,
    }
    Path(out).write_text(json.dumps(run, indent=1))
    return run


def _catalog() -> dict | None:
    """Snapshot of the definitions this run was graded with (the site prefers it over the current one)."""
    try:
        from .catalog import build_catalog

        return build_catalog()
    except Exception as exc:  # never lose a run because documentation could not be built
        print(f"warning: catalog not embedded: {exc}")
        return None


def resummarize(run_path: str) -> dict:
    """Recompute a published run's summary from its stored trials (after an aggregation fix)."""
    run = json.loads(Path(run_path).read_text())
    planned = {(c["cell"], c["arm"]): c.get("n_planned") or 0 for c in run["summary"]["cells"]}
    run["summary"] = summarize(run["trials"], run.get("shards") or {}, planned)
    Path(run_path).write_text(json.dumps(run, indent=1))
    return run


def index(runs_dir: str, out: str) -> dict:
    runs = []
    for path in sorted(Path(runs_dir).glob("*.json")):
        run = _load(path)
        if not isinstance(run, dict):
            continue
        billed = sum((c.get("billed_cost_usd") or 0) for c in (run.get("summary") or {}).get("cells", []))
        runs.append({
            "file": f"runs/{path.name}",
            "run_id": run.get("run_id"),
            "run_url": run.get("run_url"),
            "created_at": run.get("created_at"),
            "dataset_version": run.get("dataset_version"),
            "status": run.get("status"),
            "note": run.get("note"),
            "n_trials": len(run.get("trials") or []),
            "n_planned": run.get("n_planned"),
            "billed_cost_usd": round(billed, 4),
        })
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    data = {"generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "runs": runs}
    Path(out).write_text(json.dumps(data, indent=1))
    return data
