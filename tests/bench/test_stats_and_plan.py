from acb.bench.aggregate import DOCKER_CMD, PODMAN_BUILD
from acb.bench.harness import harbor_agent_args
from acb.bench.plan import plan
from acb.bench.stats import cluster_bootstrap_mean, wilson


def test_wilson():
    assert wilson(0, 0) == (None, None)
    lo, hi = wilson(5, 10)
    assert 0.2 < lo < 0.5 < hi < 0.8


def test_cluster_bootstrap():
    mean, (lo, hi) = cluster_bootstrap_mean({"a": [1.0, 1.0], "b": [0.0], "c": [0.5]})
    assert mean == 0.5 and lo <= mean <= hi


def test_plan_caps_are_positive_and_ids_unique():
    p = plan()
    ids = [s["id"] for s in p["shards"]]
    assert len(ids) == len(set(ids)) and all(s["cap_usd"] > 0 for s in p["shards"])


def test_command_detection():
    assert DOCKER_CMD.search("cd /app && docker build -t x .")
    assert not DOCKER_CMD.search("cat Dockerfile .dockerignore")
    assert PODMAN_BUILD.search("podman build -t app .")


def test_agent_args_never_carry_a_real_key():
    args = harbor_agent_args("claude-code", "1.0.0", "anthropic/claude-haiku-4.5", "http://acb-meter:8787", "tok")
    assert "ANTHROPIC_API_KEY=tok" in args and not any("sk-or-" in a for a in args)


def test_key_usage_is_the_cost_of_record():
    from acb.bench.aggregate import reconcile

    trials = [
        {"shard": "s", "metered": {"billed_cost_usd": 0.01}},
        {"shard": "s", "metered": {"billed_cost_usd": 0.03}},
    ]
    shards = reconcile(trials, {"shards": {"s": {"usage": 0.05}}})
    assert shards["s"]["unattributed_usd"] == 0.01
    # The per-key total is split across trials in proportion to what the proxy saw.
    assert [t["cost_usd"] for t in trials] == [0.0125, 0.0375]


def test_per_arm_cost_estimates():
    from acb.bench.plan import load_matrix

    cell = next(c for c in load_matrix()["cells"] if isinstance(c["est_cost_per_trial"], dict))
    est = cell["est_cost_per_trial"]
    shards = {s["arm"]: s for s in plan(cells=cell["id"], trials=1, shard_by="arm")["shards"]}
    assert (shards["explicit"]["cap_usd"] > shards["implicit"]["cap_usd"]) == (est["explicit"] > est["implicit"])


def test_task_sharding_splits_every_cell_and_arm_by_task():
    from acb.bench.plan import task_ids

    from acb.bench.plan import load_matrix

    cell = load_matrix()["cells"][0]["id"]
    by_arm = plan(cells=cell, shard_by="arm")["shards"]
    by_task = plan(cells=cell, shard_by="task")["shards"]
    assert len(by_task) == len(by_arm) * len(task_ids())
    assert all(len(s["tasks"]) == 1 and s["id"].endswith(s["tasks"][0]) for s in by_task)
    # Same trials planned either way.
    assert sum(len(s["tasks"]) for s in by_task) == sum(len(s["tasks"]) for s in by_arm)


def test_catalog_is_generated_from_sources():
    from acb.bench.catalog import build_catalog
    from acb_graders.checks import CONTAINERFILE_CHECKS

    cat = build_catalog()
    assert [c["id"] for c in cat["families"]["containerfile"]["checks"]] == [c.id for c in CONTAINERFILE_CHECKS]
    assert all(c["title"] and c["why"] and c["how"] for c in cat["families"]["containerfile"]["checks"])
    explicit = next(a for a in cat["arms"] if a["id"] == "explicit")
    assert "Pin base images by `@sha256:` digest." in explicit["appended"]["containerfile"]
    node = next(t for t in cat["tasks"] if t["id"] == "containerfile-node-api")
    lock = next(f for f in node["files"] if f["path"] == "package-lock.json")
    assert lock["content"] is None and lock["size"] > 0
    assert {o["name"] for o in node["oracles"]} >= {"best", "naive"}


def test_trials_without_artifact_do_not_count_against_single_checks():
    from acb.bench.aggregate import summarize

    def trial(failure_class, status):
        return {
            "shard": "c__implicit", "cell": "c", "arm": "implicit", "harness": "h", "model": "m", "task": "t",
            "failure_class": failure_class, "reward": 1.0 if failure_class == "none" else 0.0,
            "practice_uncond": 1.0 if status == "pass" else 0.0, "checks": {"x": {"status": status, "evidence": ""}},
            "metered": {}, "harness_reported": {}, "process": {}, "agent_seconds": 1.0,
        }

    cell = summarize([trial("none", "pass"), trial("no-artifact", "fail")])["cells"][0]
    assert cell["checks"]["x"] == {"pass": 1, "fail": 0, "na": 0, "error": 0, "rate": 1.0}
    assert cell["practice_uncond_mean"] == 0.5  # the practice score still counts the empty trial as 0


def test_key_limit_403_counts_as_budget_not_model_failure():
    from acb.bench.aggregate import attribute

    requests = [
        {"ts": 10.0, "status": 200, "generation_ids": []},
        {"ts": 11.0, "status": 403, "error": '{"error":{"message":"Key limit exceeded (total limit)."}}'},
        {"ts": 12.0, "status": 403, "error": "forbidden"},
    ]
    assert attribute(requests, {}, 9.0, 13.0)["budget_hits"] == 1
