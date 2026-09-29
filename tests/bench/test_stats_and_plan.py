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
    shards = {s["id"]: s for s in plan(cells="claude-code.haiku-4.5", trials=1)["shards"]}
    assert shards["claude-code.haiku-4.5__explicit"]["cap_usd"] > shards["claude-code.haiku-4.5__implicit"]["cap_usd"]


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
