"""Evaluation statistics with preserved legacy algorithms and opt-in cluster bootstrap."""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

BOOTSTRAP_ROUNDS = 2000
_BOOTSTRAP_CELLS = 1_000_000
_RANDOM_RESAMPLES = 2000
_WILSON_Z = 1.959963984540054


def bootstrap_numpy_percentile_batched(values: Sequence[float], seed: int) -> tuple[float, float] | None:
    """Replay: 2000 batched default_rng(seed) means, linear 2.5/97.5 percentiles; empty returns None."""
    if not values:
        return None
    data = np.asarray(values, dtype=np.float64)
    n = data.size
    rng = np.random.default_rng(seed)
    rows = max(1, _BOOTSTRAP_CELLS // n)
    means: list[NDArray[np.float64]] = []
    done = 0
    while done < BOOTSTRAP_ROUNDS:
        batch = min(rows, BOOTSTRAP_ROUNDS - done)
        means.append(data[rng.integers(0, n, size=(batch, n))].mean(axis=1))
        done += batch
    low, high = np.percentile(np.concatenate(means), [2.5, 97.5])
    return float(low), float(high)


def bootstrap_numpy_percentile_min_two(values: Sequence[float], seed: str) -> tuple[float, float] | None:
    """Persona: 2000 SHA256-seeded default_rng means, linear 2.5/97.5 percentiles; fewer than two returns None."""
    if len(values) < 2:
        return None
    rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    arr = np.asarray(values, dtype=float)
    means = arr[rng.integers(0, len(arr), size=(BOOTSTRAP_ROUNDS, len(arr)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _rng(seed: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))


def bootstrap_numpy_percentile_single_group(values: Sequence[float], seed: str) -> tuple[float, float] | None:
    """Scenarios: one group, 2000 SHA256-seeded default_rng means, linear 2.5/97.5 percentiles; empty None."""
    return bootstrap_numpy_percentile_stratified([values], seed)


def bootstrap_numpy_percentile_stratified(groups: Sequence[Sequence[float]], seed: str) -> tuple[float, float] | None:
    """Scenarios: 2000 SHA256/default_rng equal-group means, linear 2.5/97.5 percentiles; all-empty None."""
    data = [np.asarray(g, dtype=np.float64) for g in groups if len(g)]
    if not data:
        return None
    rng = _rng(seed)
    means = np.zeros(BOOTSTRAP_ROUNDS)
    for g in data:
        means += g[rng.integers(0, g.size, size=(BOOTSTRAP_ROUNDS, g.size))].mean(axis=1)
    low, high = np.percentile(means / len(data), [2.5, 97.5])
    return float(low), float(high)


def bootstrap_grouped(groups: Mapping[str, Sequence[float]], seed: str) -> tuple[float, float] | None:
    """Cluster bootstrap: resample whole groups, weighting the mean by drawn group sizes.

    Callers must average repeats into one value per case BEFORE grouping. Empty groups are ignored;
    fewer than two nonempty groups returns None. Sorted keys make mapping insertion order irrelevant.
    Use 2000 SHA256-seeded default_rng rounds and linear 2.5/97.5 percentiles.
    """
    data = [np.asarray(groups[key], dtype=np.float64) for key in sorted(groups) if len(groups[key])]
    if len(data) < 2:
        return None
    sums = np.asarray([g.sum() for g in data], dtype=np.float64)
    sizes = np.asarray([g.size for g in data], dtype=np.float64)
    rng = _rng(seed)
    rows = max(1, _BOOTSTRAP_CELLS // len(data))
    means: list[NDArray[np.float64]] = []
    done = 0
    while done < BOOTSTRAP_ROUNDS:
        batch = min(rows, BOOTSTRAP_ROUNDS - done)
        draws = rng.integers(0, len(data), size=(batch, len(data)))
        means.append(sums[draws].sum(axis=1) / sizes[draws].sum(axis=1))
        done += batch
    low, high = np.percentile(np.concatenate(means), [2.5, 97.5])
    return float(low), float(high)


def bootstrap_random_order_statistic(diffs: list[float], seed: str) -> tuple[float, float]:
    """Summarize: 2000 Random(str) mean resamples, sorted indices 50/1949; empty raises ZeroDivisionError."""
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(_RANDOM_RESAMPLES))
    return means[int(0.025 * _RANDOM_RESAMPLES)], means[int(0.975 * _RANDOM_RESAMPLES) - 1]


def mcnemar_exact_p(only_first: int, only_second: int) -> float:
    """Replay: exact two-sided binomial(p=0.5) discordant-pair tail, capped at 1; no discordance returns 1."""
    n = only_first + only_second
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(only_first, only_second) + 1))
    return min(1.0, 2 * tail / (1 << n))


def wilson_upper_95(error_rate: float | None, n: int) -> float | None:
    """Calibration: two-sided Wilson 95% upper bound (z=1.959963984540054), capped at 1; None stays None."""
    upper = None
    if error_rate is not None:
        z_squared = _WILSON_Z**2
        upper = min(
            1.0,
            (
                error_rate
                + z_squared / (2 * n)
                + _WILSON_Z * math.sqrt(error_rate * (1 - error_rate) / n + z_squared / (4 * n * n))
            )
            / (1 + z_squared / n),
        )
    return upper
