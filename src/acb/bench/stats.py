"""Small, dependency-free statistics used by the aggregator."""

from __future__ import annotations

import math
import random


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def cluster_bootstrap_mean(
    by_cluster: dict[str, list[float]], iterations: int = 2000, seed: int = 7
) -> tuple[float | None, tuple[float | None, float | None]]:
    """Mean over clusters (tasks) with a 95% percentile bootstrap CI.

    Trials of the same task are correlated, so tasks, not trials, are
    resampled. Each task contributes the mean of its trials.
    """
    means = [sum(v) / len(v) for v in by_cluster.values() if v]
    if not means:
        return None, (None, None)
    point = sum(means) / len(means)
    if len(means) == 1:
        return round(point, 4), (None, None)
    rng = random.Random(seed)
    samples = sorted(sum(rng.choice(means) for _ in means) / len(means) for _ in range(iterations))
    lo = samples[int(0.025 * iterations)]
    hi = samples[int(0.975 * iterations) - 1]
    return round(point, 4), (round(lo, 4), round(hi, 4))
