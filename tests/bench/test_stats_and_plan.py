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
